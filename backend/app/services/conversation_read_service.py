"""A calling session's conversations as their caller reads them (F150.10,
F150.11; DB Conversation, assertion 337): the one a call names, and the list
of those its environment opened.

A Conversation answers to its opener alone: the User its first Turn's author
is, calling from the Environment it was opened from. A call about it from any
other User or Environment, one that names no environment among them, is
answered as for an id that never was, and lists none of it.

Pilot's reply to the caller's latest message (`reply`) is read from the
Session's records from that message's `send` on: its own Turn's and those of
every Turn the server sent after it, the follow-up of a save still held
(F79) among them, during which the caller's next message is refused. It is
`running` while a Turn is in flight, as a message's refusal reads that
(`in_flight`), and is read as it stands, with no wait.

A project's people read every Conversation of the project (`of_project`,
`one_of_project`; F150.12), whoever opened it: each with the Environment it
was opened from, by its name, and whether Pilot is answering in it, its
Session in a state a person's Stop ends (F44).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.engine.views import pilot_text
from app.exceptions import RecordNotFoundException
from app.models import Conversation, Environment, Project, Turn, User
from app.models import Session as AgentSession
from app.models.reference import RecordKind, SessionState
from app.services.conversation_service import in_flight
from app.services.session_record_service import each_record, read_records
from app.services.session_start_service import START_FAILED, STOPPABLE

MESSAGE_SEPARATOR = "\n\n---\n\n"
"""What stands between the sections of a reply's text, as between a turn's
messages in the answer of KubeCoder's `get_session_response` (F150.10)."""

ReplyState = Literal["running", "done", "error", "interrupted"]


@dataclass(frozen=True)
class ListedConversation:
    """A Conversation, when it opened, its Session's creation, the count of
    its Turns, and whether one is in flight, when it takes no message."""

    conversation: Conversation
    opened_at: datetime
    turns: int
    in_flight: bool


@dataclass(frozen=True)
class ProjectConversation:
    """A Conversation as its project's people read it: the Environment it
    was opened from, when it opened, its Session's creation, and its
    Session's state."""

    conversation: Conversation
    environment: Environment
    opened_at: datetime
    state: SessionState

    @property
    def answering(self) -> bool:
        """Whether Pilot is answering in it: its Session in a state a
        person's Stop ends (F44), its start held at the gate or under way,
        or a turn of it running."""
        return self.state in STOPPABLE


@dataclass(frozen=True)
class Reply:
    """Pilot's reply to a caller's latest message, as it stands.

    `state` is `running` while a Turn of the Conversation is in flight;
    else `error` where a Turn of the reply has an error or its start failed,
    `interrupted` where its last Turn ended on an interrupted result or on
    none, stopped before the worker gave one, and `done` otherwise.
    `turn` is the number of the caller's Turn, none while `running`.
    `text` is each text Pilot wrote since the message, in order, joined by
    `MESSAGE_SEPARATOR`, an `error`'s reason its last section unless Pilot's
    last text says it; none where there is none.
    """

    turn: int | None
    state: ReplyState
    text: str | None


class ConversationReadService:
    """Reads a caller's conversations, in the caller's transaction."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def owned(
        self, conversation_id: uuid.UUID, caller: User, environment_id: str | None
    ) -> ListedConversation:
        """The Conversation, for `caller` calling from the environment
        `environment_id`, none where the call named none.

        Raises:
            RecordNotFoundException: No Conversation has the id, or another
                User or Environment opened it
        """
        return _listed(*self._row(conversation_id, caller, environment_id))

    def reply(
        self, conversation_id: uuid.UUID, caller: User, environment_id: str | None
    ) -> Reply:
        """Pilot's reply to the latest message of the Conversation, for
        `caller` calling from the environment `environment_id`, none where
        the call named none, as it stands now.

        Raises:
            RecordNotFoundException: No Conversation has the id, or another
                User or Environment opened it
        """
        _, session = self._row(conversation_id, caller, environment_id)
        running = in_flight(session)
        turns = self._since_message(conversation_id)
        asked, last = turns[0], turns[-1]
        # A caller's Turn is written with its `send`, the first record of it
        # (`ConversationService._start`, `RelayService.send`).
        [sent] = read_records(self.db, conversation_id, turn_id=asked.id, limit=1)
        after = sent.record.seq - 1
        sections = [
            text
            for stored in each_record(
                self.db, conversation_id, RecordKind.CLAUDE, "assistant", after=after
            )
            for text in pilot_text(stored.record.payload)
        ]
        if running or last.ended_at is None:
            return Reply(None, "running", _joined(sections))
        state, reason = self._outcome(conversation_id, turns, after)
        if reason is not None and sections[-1:] != [reason]:
            sections.append(reason)
        return Reply(asked.seq, state, _joined(sections))

    def opened(
        self,
        caller: User,
        environment_id: str | None,
        project_id: uuid.UUID | None = None,
    ) -> list[ListedConversation]:
        """The Conversations `caller` opened from the environment
        `environment_id`, open and closed, in the order they opened, whatever
        session there opened each; of the project `project_id` alone where
        one is given. None for a call that named no environment."""
        if environment_id is None:
            return []
        opened = _opened_by(caller, environment_id)
        if project_id is not None:
            opened = opened.where(Conversation.project_id == project_id)
        return [
            _listed(conversation, session)
            for conversation, session in self.db.execute(
                opened.order_by(AgentSession.created_at, Conversation.id)
            )
        ]

    def of_project(self, project_id: uuid.UUID) -> list[ProjectConversation]:
        """The project's Conversations, open and closed, whoever opened
        them, in the order they opened.

        Raises:
            RecordNotFoundException: No project has the id
        """
        if self.db.get(Project, project_id) is None:
            raise RecordNotFoundException("Project", str(project_id))
        return [
            ProjectConversation(*row)
            for row in self.db.execute(
                _of_project(project_id).order_by(
                    AgentSession.created_at, Conversation.id
                )
            )
        ]

    def one_of_project(
        self, project_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> ProjectConversation:
        """The Conversation, one of the project's.

        Raises:
            RecordNotFoundException: No Conversation of the project has the
                id
        """
        row = self.db.execute(
            _of_project(project_id).where(Conversation.id == conversation_id)
        ).one_or_none()
        if row is None:
            raise RecordNotFoundException("Conversation", str(conversation_id))
        return ProjectConversation(*row)

    def _row(
        self, conversation_id: uuid.UUID, caller: User, environment_id: str | None
    ) -> tuple[Conversation, AgentSession]:
        """The Conversation and its Session, for `caller` calling from the
        environment `environment_id`.

        Raises:
            RecordNotFoundException: No Conversation has the id, or another
                User or Environment opened it
        """
        if environment_id is not None:
            row = self.db.execute(
                _opened_by(caller, environment_id).where(
                    Conversation.id == conversation_id
                )
            ).one_or_none()
            if row is not None:
                return row[0], row[1]
        raise RecordNotFoundException("Conversation", str(conversation_id))

    def _since_message(self, conversation_id: uuid.UUID) -> Sequence[Turn]:
        """The Conversation's latest Turn with an author, its caller's
        latest message, and every Turn after it, the server's own, in
        order, read afresh. A Conversation opens with its caller's Turn."""
        asked = (
            select(Turn.seq)
            .where(Turn.session_id == conversation_id, Turn.author_user_id.is_not(None))
            .order_by(Turn.seq.desc())
            .limit(1)
            .scalar_subquery()
        )
        return self.db.scalars(
            select(Turn)
            .where(Turn.session_id == conversation_id, Turn.seq >= asked)
            .order_by(Turn.seq)
            .execution_options(populate_existing=True)
        ).all()

    def _outcome(
        self, conversation_id: uuid.UUID, turns: Sequence[Turn], after: int
    ) -> tuple[ReplyState, str | None]:
        """How the reply whose Turns are `turns`, each ended, came out, with
        an error's reason, read from the records after the `seq` `after`:
        the latest error of a Turn of it, else its start's failure, which no
        Turn carries, else its last Turn's result."""
        errors = [turn.error for turn in turns if turn.error is not None]
        if errors:
            return "error", errors[-1]
        failed = read_records(
            self.db,
            conversation_id,
            after=after,
            kind=RecordKind.SERVER,
            payload_type=START_FAILED,
            limit=1,
            newest_first=True,
        )
        if failed:
            return "error", failed[0].record.payload["reason"]
        results = read_records(
            self.db,
            conversation_id,
            after=after,
            kind=RecordKind.RESULT,
            limit=1,
            newest_first=True,
        )
        if (
            results
            and results[0].turn == turns[-1].seq
            and not results[0].record.payload.get("interrupted")
        ):
            return "done", None
        return "interrupted", None


def _joined(sections: list[str]) -> str | None:
    return MESSAGE_SEPARATOR.join(sections) or None


def _opened_by(caller: User, environment_id: str) -> Select[Conversation, AgentSession]:
    """The Conversations `caller` opened from the environment, each with its
    Session, read afresh."""
    return (
        select(Conversation, AgentSession)
        .join(AgentSession, AgentSession.id == Conversation.id)
        .join(Turn, (Turn.session_id == Conversation.id) & (Turn.seq == 1))
        .where(
            Turn.author_user_id == caller.id,
            Conversation.caller_environment_id == environment_id,
        )
        .execution_options(populate_existing=True)
    )


def _of_project(
    project_id: uuid.UUID,
) -> Select[Conversation, Environment, datetime, SessionState]:
    """The project's Conversations, each with its caller's Environment, its
    Session's creation and its Session's state, read afresh."""
    return (
        select(
            Conversation, Environment, AgentSession.created_at, AgentSession.state_code
        )
        .join(AgentSession, AgentSession.id == Conversation.id)
        .join(Environment, Environment.id == Conversation.caller_environment_id)
        .where(Conversation.project_id == project_id)
        .execution_options(populate_existing=True)
    )


def _listed(conversation: Conversation, session: AgentSession) -> ListedConversation:
    return ListedConversation(
        conversation, session.created_at, session.turns, in_flight(session)
    )
