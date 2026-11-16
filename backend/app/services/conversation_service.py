"""A conversation a session outside Pilot holds with a project's brain,
through Pilot's projects surface (F150.10, F150.12; design 3 §5.1, §5.3; DB
Conversation, decision 77, assertions 330 to 337).

A Conversation is opened with its caller's first message on a project that is
open or finished and not archived, never on a draft, from the environment and
the session the call came from, as the service user the call came as. Its
Session is a `conversation` one in the store, as a chat's is: in the store
repo's root on the brain's model and effort, boxed to the project's folder
and handed `pilot-store`, a finished project's reading only with no surface
(`scoped_create`). Its first Turn is the conversation's brief
(`BriefService.conversation`) followed by the caller's words, through the
gate (`SessionStartService.start_brain`): it takes no slot and waits behind
no job, and several are open on one project at once, beside its chat, from
one calling session or from several.

The caller's Environment row is written at the opening
(`CallerEnvironmentService`), from the controller's report where it has one,
else named by its id: no opening is refused for where it came from.

A later message is a Turn of the conversation, the caller's words verbatim,
after the server's `<store_notification>` when the project's handbook changed
since its previous Turn, counted as a chat's (D052). It goes through the
relay's send (`RelayService.send`), which resumes a controller session that
is gone. It is refused while a Turn of the conversation is in flight, its
start held or under way among them, with nothing queued (DB 336), read from
the record under the Session's lock, with no controller call. A conversation
whose start failed, or was stopped before its brief went out, starts afresh
with the next message, briefed, in the same conversation, as a chat does.

Every Turn's author is the service user (DB 336). A closed conversation and
an archived project's take no Turn (DB 334).

Under a Store Update unlifted no message is taken, the opening's included,
and no Turn written, as a chat's (F144.2; DB 282, 335).

Its caller's interrupt stops the Turn in flight as a person's Stop stops a
chat's (`SessionStartService.stop_chat`), by the service user, and keeps the
conversation open: the next message goes to its thread, or starts it afresh,
briefed, when the stop ended its start unsent. Its caller's end closes it,
`ended`, a Turn in flight stopped first (`ChatCloseService.end`). Neither
refuses for what it finds: an interrupt with no Turn in flight and the end of
a closed conversation change nothing, as KubeCoder's interrupt of an idle
session and its end of one gone.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import Conversation, Environment, Project, Turn, User
from app.models import Session as AgentSession
from app.models.reference import ProjectState, RecordKind, SessionState
from app.services.brief_service import BriefService
from app.services.caller_environment_service import CallerEnvironmentService
from app.services.chat_close_service import ChatCloseService
from app.services.chat_service import (
    HANDBOOK_CHANGED_TOTAL,
    STORE_NOTIFICATION,
    handbook_changed,
    lock_standing,
    unbriefed,
)
from app.services.pilot_server import unheld_token_hash
from app.services.project_service import project_name
from app.services.relay_service import RelayService, Words
from app.services.session_record_service import SessionRecordService
from app.services.session_scope import STORE_REPO
from app.services.session_start_service import STOPPABLE, SessionStartService
from app.services.start_gate import CONVERSATION_KIND
from app.services.store_update_service import unlifted

_IN_FLIGHT = "a turn of its conversation is in flight"

_UPDATING = "Pilot is updating"


class ConversationService:
    """Opens a calling session's conversation with a project's brain, takes
    its later messages, and its caller's interrupt and end."""

    def __init__(
        self,
        db: Session,
        relay_service: RelayService,
        session_start_service: SessionStartService,
        brief_service: BriefService,
        session_record_service: SessionRecordService,
        caller_environment_service: CallerEnvironmentService,
        chat_close_service: ChatCloseService,
        brain_model: str,
        brain_reasoning_effort: str,
    ) -> None:
        """Open conversations, each one's start made on `brain_model` at
        `brain_reasoning_effort`, as a chat's (F139; design 3 §12)."""
        self.db = db
        self.relay_service = relay_service
        self.session_start_service = session_start_service
        self.brief_service = brief_service
        self.records = session_record_service
        self.caller_environments = caller_environment_service
        self.chat_close_service = chat_close_service
        self.brain_model = brain_model
        self.brain_reasoning_effort = brain_reasoning_effort

    def open(
        self,
        project_id: uuid.UUID,
        caller: User,
        environment_id: str,
        caller_session: str | None,
        words: str,
    ) -> Turn:
        """A Conversation on the project opened with `words`, the first
        message of the service user `caller`, calling from the environment
        `environment_id` in the session `caller_session`, none where the
        call named none, an empty name stored as none, in the caller's
        transaction. The Conversation is the Turn's Session.

        The environment's row is written with it where Pilot has none, the
        controller asked for its report before any lock is taken. The start
        makes no other controller call: it is written under the project's
        row, locked as a change of its standing locks it, and runs once this
        commits.

        Returns:
            The conversation's first Turn, its brief before the words

        Raises:
            RecordNotFoundException: No project has the id
            InvalidOperationException: The project is a draft or archived;
                Pilot is updating its store; no controller or no store
                environment is configured
        """
        project = self.db.get(Project, project_id, populate_existing=True)
        if project is None:
            raise RecordNotFoundException("Project", str(project_id))
        operation = f"open a conversation with Pilot in {project_name(project)}"
        _refuse_opening(project, operation)
        if unlifted(self.db) is not None:
            raise InvalidOperationException(operation, _UPDATING)
        report = self.caller_environments.reported(environment_id)
        project = lock_standing(self.db, project_id)
        _refuse_opening(project, operation)
        environment = self.caller_environments.row(environment_id, report)
        session = AgentSession(
            project_id=project.id,
            kind_code=CONVERSATION_KIND,
            cwd=STORE_REPO,
            model=self.brain_model,
            reasoning_effort=self.brain_reasoning_effort,
            token_hash=unheld_token_hash(),
            state_code=SessionState.STARTING,
        )
        self.db.add(session)
        self.db.flush()
        conversation = Conversation(
            id=session.id,
            project_id=project.id,
            session_kind_code=CONVERSATION_KIND,
            caller_environment_id=environment.id,
            caller_session=caller_session,
        )
        self.db.add(conversation)
        self.db.flush()
        return self._start(project, session, conversation, caller, words, operation)

    def send(self, conversation_id: uuid.UUID, caller: User, words: str) -> Turn:
        """The next message of the service user `caller` to the
        Conversation, `words` verbatim, in the caller's transaction: a Turn
        of it, sent to its Session, whose controller's send goes first, as
        `RelayService.send` makes it, under the Session's lock. One whose
        start failed, or was stopped before its brief went out, starts
        afresh with it, briefed.

        Returns:
            The Turn; one whose send failed has its `error`

        Raises:
            RecordNotFoundException: No Conversation has the id
            InvalidOperationException: The conversation is closed, or its
                project archived; Pilot is updating its store; a Turn of it
                is in flight, its start held or under way included; no
                controller or no store environment is configured
        """
        conversation = self._conversation(conversation_id)
        project = self.db.get_one(Project, conversation.project_id)
        operation = f"send a message to Pilot in {project_name(project)}"
        if unlifted(self.db) is not None:
            raise InvalidOperationException(operation, _UPDATING)
        session = self.db.get_one(AgentSession, conversation_id, populate_existing=True)
        if unbriefed(session):
            return self._start_again(conversation_id, caller, words, operation)
        self.records.lock_project(conversation_id)
        session = self.records.lock_session(conversation_id)
        self._refuse_message(conversation, operation)
        if _in_flight(session):
            raise InvalidOperationException(operation, _IN_FLIGHT)
        changed = handbook_changed(self.db, project, session)
        message = f"{STORE_NOTIFICATION}\n\n{words}" if changed else words
        turn = self.relay_service.send(
            self.db, session.id, message, words=Words(caller.id, words)
        )
        if changed and turn.error is None:
            HANDBOOK_CHANGED_TOTAL.labels(project=str(project.id)).inc()
        return turn

    def interrupt(self, conversation_id: uuid.UUID, caller: User) -> Conversation:
        """The interrupt of the service user `caller`, in the caller's
        transaction: the Conversation's Turn in flight stopped by them, as a
        person's Stop stops a chat's, once this commits; a start held or
        under way ends its Turn unsent. The conversation stays open for the
        next message. With no Turn to stop it changes nothing, a closed
        conversation's included.

        Returns:
            The Conversation

        Raises:
            RecordNotFoundException: No Conversation has the id
        """
        conversation = self._conversation(conversation_id)
        self._stop(conversation, caller)
        return conversation

    def end(self, conversation_id: uuid.UUID, caller: User) -> Conversation:
        """The end of the Conversation by the service user `caller`, in the
        caller's transaction: closed `ended`, a Turn of it in flight stopped
        first, by them. One closed already stays as it closed.

        Returns:
            The Conversation, closed

        Raises:
            RecordNotFoundException: No Conversation has the id
        """
        conversation = self._conversation(conversation_id)
        self._stop(conversation, caller)
        if conversation.closed_at is None:
            self.chat_close_service.end(self.db, conversation, datetime.now(UTC))
        return conversation

    def _conversation(self, conversation_id: uuid.UUID) -> Conversation:
        """The Conversation.

        Raises:
            RecordNotFoundException: No Conversation has the id
        """
        conversation = self.db.get(Conversation, conversation_id)
        if conversation is None:
            raise RecordNotFoundException("Conversation", str(conversation_id))
        return conversation

    def _stop(self, conversation: Conversation, caller: User) -> None:
        """The Conversation's Session locked to the transaction's end, after
        its project's row, held shared (the start's lock order), the
        Conversation read under it, and its Turn in flight, if any, stopped
        by `caller`."""
        self.records.lock_project(conversation.id)
        session = self.records.lock_session(conversation.id)
        self.db.refresh(conversation)
        if session.state_code in STOPPABLE:
            project = self.db.get_one(Project, conversation.project_id)
            self.session_start_service.stop_chat(
                self.db, session.id, caller, f"stop Pilot in {project_name(project)}"
            )

    def _start_again(
        self, conversation_id: uuid.UUID, caller: User, words: str, operation: str
    ) -> Turn:
        """The Conversation whose start failed or was stopped before its
        brief went out started afresh with `words`, in a headless session of
        its own. Its Session is locked after the project's row (the start's
        lock order)."""
        conversation = self.db.get_one(Conversation, conversation_id)
        project = lock_standing(self.db, conversation.project_id)
        session = self.records.lock_session(conversation_id)
        self._refuse_message(conversation, operation)
        if _in_flight(session) or not unbriefed(session):
            raise InvalidOperationException(operation, _IN_FLIGHT)
        session.controller_session = None
        session.error = None
        return self._start(project, session, conversation, caller, words, operation)

    def _start(
        self,
        project: Project,
        session: AgentSession,
        conversation: Conversation,
        caller: User,
        words: str,
        operation: str,
    ) -> Turn:
        """The Conversation's Session, under the project's row, started with
        its brief and `words` after it as `caller`'s Turn, its `send` record
        in its place, through the gate."""
        now = datetime.now(UTC)
        last = self.db.scalar(
            select(func.max(Turn.seq)).where(Turn.session_id == session.id)
        )
        turn = Turn(
            session_id=session.id,
            seq=(last or 0) + 1,
            author_user_id=caller.id,
            message=self.brief_service.conversation(
                project,
                self.db.get_one(Environment, conversation.caller_environment_id),
                conversation.caller_session,
                words,
                now,
            ),
            words=words,
            started_at=now,
        )
        self.db.add(turn)
        self.db.flush()
        self.records.append(session.id, RecordKind.SEND, turn_id=turn.id)
        session.turns = turn.seq
        session.turn_started_at = now
        session.turn_ended_at = None
        session.current_line = None
        self.session_start_service.start_brain(self.db, project, session, operation)
        return turn

    def _refuse_message(self, conversation: Conversation, operation: str) -> None:
        """Refuse a message to a closed Conversation and to an archived
        project's, each read under the Session's lock, which a close and a
        transition that stops the project's sessions hold (DB 334).

        Raises:
            InvalidOperationException: The conversation is closed, or its
                project is archived
        """
        self.db.refresh(conversation)
        if conversation.closed_at is not None:
            raise InvalidOperationException(operation, "its conversation is closed")
        project = self.db.get_one(
            Project, conversation.project_id, populate_existing=True
        )
        if project.archived:
            raise InvalidOperationException(operation, "its project is archived")


def _in_flight(session: AgentSession) -> bool:
    """Whether a Turn of the Conversation's Session, its row locked, is in
    flight: its start held or under way, a turn running, or one stopped and
    still being relayed to its end."""
    match session.state_code:
        case SessionState.HELD | SessionState.STARTING | SessionState.RUNNING:
            return True
        case SessionState.STOPPED:
            return session.turn_ended_at is None
        case _:
            return False


def _refuse_opening(project: Project, operation: str) -> None:
    """Refuse a Conversation on a draft, whose definition chat is the one
    session that writes its `project.md`, and on an archived project (DB
    334).

    Raises:
        InvalidOperationException: The project is a draft or archived
    """
    if project.archived:
        raise InvalidOperationException(operation, "its project is archived")
    if project.state_code is ProjectState.DRAFT:
        raise InvalidOperationException(operation, "its project is a draft")
