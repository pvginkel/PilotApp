"""A person's message to a project's brain (design 3 §5.1, §5.3; F38.3,
F130; DB Chat, Turn, assertions 159, 229, 243, 251).

A message is a Turn of the project's open chat, the person's words verbatim
with their quote tags, its `send` record in its place, and the Item or the
Block its first quote tag names its quote. With a chat open whose session is
up, it goes through the relay's send (`RelayService.send`), which resumes a
controller session that is gone. With none open it starts one: a Chat
`project`, its Session a `chat` one in the store, its first Turn the brief
(`BriefService.project_chat`) followed by the words, through the gate
(`SessionStartService.start_brain`). A chat whose start failed, or was
stopped before its brief went out, starts afresh, briefed, in the same chat: a
project has one chat open at a time, and no Close Cause is a failure or a stop.
While its start is under way or held, a message is refused, as one is while a
turn runs, which the controller refuses.

A draft's, a finished project's and an archived project's chat take no
message.
"""

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import Block, Chat, Item, Project, Turn, User
from app.models import Session as AgentSession
from app.models.reference import ChatKind, ProjectState, RecordKind, SessionState
from app.services.brief_service import BriefService
from app.services.pilot_server import unheld_token_hash
from app.services.project_service import project_name
from app.services.relay_service import RelayService, Words
from app.services.session_record_service import SessionRecordService
from app.services.session_scope import STORE_REPO
from app.services.session_start_service import SessionStartService
from app.services.start_gate import CHAT_KIND

QUOTE_TAG = re.compile(
    r'<quoted_(item|block) id="([^"]+)">[\s\S]*?</quoted_\1 id="\2">'
)
"""A quote tag (F38.3; DB decision 29), the closing tag repeating the id."""

_IN_FLIGHT = "a turn of its chat is in flight"


class ChatService:
    """Takes a person's message to a project's brain."""

    def __init__(
        self,
        db: Session,
        relay_service: RelayService,
        session_start_service: SessionStartService,
        brief_service: BriefService,
        session_record_service: SessionRecordService,
        brain_model: str,
        brain_reasoning_effort: str,
    ) -> None:
        """Take messages, a chat's start made on `brain_model` at
        `brain_reasoning_effort` (F139; design 3 §12)."""
        self.db = db
        self.relay_service = relay_service
        self.session_start_service = session_start_service
        self.brief_service = brief_service
        self.records = session_record_service
        self.brain_model = brain_model
        self.brain_reasoning_effort = brain_reasoning_effort

    def send(self, project_id: uuid.UUID, person: User, words: str) -> Turn:
        """`person`'s message to the project's brain, `words` verbatim, in the
        caller's transaction: sent to the project's open chat, or a chat
        started with it.

        With the chat's session up, the controller's send goes first, as
        `RelayService.send` makes it. A start makes no controller call: it is
        written under the project's row, locked as a change of its standing
        locks it, so two starts of the project's chat, or a start and a
        Finish, never interleave, and runs once this commits.

        Returns:
            The Turn; one whose send failed has its `error`

        Raises:
            RecordNotFoundException: No project has the id
            InvalidOperationException: The project is a draft, finished or
                archived; its chat's start is under way, or a turn of it is in
                flight; no controller or no store environment is configured
        """
        project = self.db.get(Project, project_id, populate_existing=True)
        if project is None:
            raise RecordNotFoundException("Project", str(project_id))
        operation = f"send a message to Pilot in {project_name(project)}"
        _refuse_closed(project, operation)
        quoted = self._quote(project, person, words)
        session = self._open_chat(project.id)
        if session is not None and not _unbriefed(session):
            return self.relay_service.send(self.db, session.id, words, words=quoted)
        return self._start(project_id, person, quoted, operation)

    def _start(
        self, project_id: uuid.UUID, person: User, words: Words, operation: str
    ) -> Turn:
        """The project's chat started with `words`: a new one, or the open
        one whose start failed or was stopped before its brief went out,
        afresh in a headless session of its own. The open chat's Session is
        locked after the project's row (the start's lock order)."""
        project = self._locked(project_id)
        _refuse_closed(project, operation)
        session = self._open_chat(project.id)
        if session is None:
            session = self._new_chat(project)
        else:
            session = self.records.lock_session(session.id)
            match session.state_code:
                case SessionState.HELD | SessionState.STARTING:
                    raise InvalidOperationException(operation, "its chat is starting")
                case SessionState.STOPPED if session.turn_ended_at is None:
                    raise InvalidOperationException(operation, _IN_FLIGHT)
                case _ if _unbriefed(session):
                    session.controller_session = None
                    session.error = None
                case _:
                    raise InvalidOperationException(operation, _IN_FLIGHT)
        now = datetime.now(UTC)
        last = self.db.scalar(
            select(func.max(Turn.seq)).where(Turn.session_id == session.id)
        )
        turn = Turn(
            session_id=session.id,
            seq=(last or 0) + 1,
            author_user_id=person.id,
            message=self.brief_service.project_chat(project, person, words.text, now),
            words=words.text,
            quote_item_id=words.quote_item_id,
            quote_block_id=words.quote_block_id,
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

    def _new_chat(self, project: Project) -> AgentSession:
        """A Chat `project` and its Session, in no environment until its start
        takes the store, in the store repo's root, on the brain's model and
        effort, its token none holds until its create mints one."""
        session = AgentSession(
            project_id=project.id,
            kind_code=CHAT_KIND,
            cwd=STORE_REPO,
            model=self.brain_model,
            reasoning_effort=self.brain_reasoning_effort,
            token_hash=unheld_token_hash(),
            state_code=SessionState.STARTING,
        )
        self.db.add(session)
        self.db.flush()
        self.db.add(
            Chat(
                id=session.id,
                project_id=project.id,
                session_kind_code=CHAT_KIND,
                kind_code=ChatKind.PROJECT,
            )
        )
        self.db.flush()
        return session

    def _open_chat(self, project_id: uuid.UUID) -> AgentSession | None:
        """The Session of the project's open chat, read afresh; None while
        none is open."""
        return self.db.scalars(
            select(AgentSession)
            .join(Chat, Chat.id == AgentSession.id)
            .where(Chat.project_id == project_id, Chat.closed_at.is_(None))
            .execution_options(populate_existing=True)
        ).one_or_none()

    def _locked(self, project_id: uuid.UUID) -> Project:
        """The project, its row held as a change of its standing holds it
        (`ProjectService`), read as the lock found it."""
        return self.db.scalars(
            select(Project)
            .where(Project.id == project_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        ).one()

    def _quote(self, project: Project, person: User, words: str) -> Words:
        """`person`'s `words`, quoting the Item or the Block of the project
        their first quote tag names (DB 159); none when it names neither."""
        tag = QUOTE_TAG.search(words)
        item_id = block_id = None
        if tag is not None:
            kind, ref = tag.groups()
            if kind == "item":
                quoted = _uuid(ref)
                if quoted is not None:
                    item_id = self.db.scalar(
                        select(Item.id).where(
                            Item.id == quoted, Item.project_id == project.id
                        )
                    )
            else:
                item, _, local_id = ref.partition("/")
                quoted = _uuid(item)
                if quoted is not None:
                    block_id = self.db.scalar(
                        select(Block.id)
                        .join(Item, Item.id == Block.document_id)
                        .where(
                            Block.document_id == quoted,
                            Block.local_id == local_id,
                            Item.project_id == project.id,
                        )
                    )
        return Words(person.id, words, quote_item_id=item_id, quote_block_id=block_id)


def _unbriefed(session: AgentSession) -> bool:
    """A chat's Session a message is not sent to (`_start`): its start held or
    under way, failed, or stopped with no conversation for a turn to
    continue."""
    match session.state_code:
        case SessionState.HELD | SessionState.STARTING | SessionState.FAILED:
            return True
        case SessionState.STOPPED:
            return session.conversation_id is None
        case _:
            return False


def _uuid(text: str) -> uuid.UUID | None:
    """`text` as an id; None for text no id is, which quotes nothing."""
    try:
        return uuid.UUID(text)
    except ValueError:
        return None


def _refuse_closed(project: Project, operation: str) -> None:
    """Refuse a message to a draft's chat, which is the definition chat's, and
    to a finished or an archived project's.

    Raises:
        InvalidOperationException: The project is a draft, finished or
            archived
    """
    if project.archived:
        raise InvalidOperationException(operation, "its project is archived")
    if project.state_code is ProjectState.DRAFT:
        raise InvalidOperationException(operation, "its project is a draft")
    if project.state_code is ProjectState.FINISHED:
        raise InvalidOperationException(operation, "its project is finished")
