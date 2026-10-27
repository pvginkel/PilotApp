"""A person's message to a project's brain (design 3 §5.1, §5.3; F38.3,
F130, F5.5, F128.5; DB Chat, Turn, assertions 159, 229, 243, 244, 245, 251).

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

Pilot's answer in the open chat is stopped as a work item's is, by any person,
whoever sent its message (F44).

A message to the open chat holds its Session's lock from before its send to
the commit, so no close or stop interleaves with it (`ChatCloseService`,
`SessionStartService.stop_project`): one that finds the chat closed meanwhile
starts the project's next chat, and one that finds its project archived is
refused. Its words are
sent as they are, unless the chat's previous Turn with an author has another
author: then the line naming the person goes before them, as the brief names
the first (DB decision 61); and unless the project's handbook changed since
the chat's previous Turn: then the server's `<store_notification>` saying so
goes before both, counted (D052).

A finished project's chat reads only: a message starts it as in an open
project, its create boxed with nothing to write and no surface
(`scoped_create`), its brief the finished project's. A draft's chat, the
definition chat, takes no message, nor does an archived project, whose open
chat Archive closed (`ChatCloseService`): the refusal guards a send racing
the archive.
"""

import re
import uuid
from datetime import UTC, datetime

from prometheus_client import Counter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine.views import ListedChat, ViewService
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import Block, Chat, Document, Item, Project, Turn, User
from app.models import Session as AgentSession
from app.models.reference import (
    ChatKind,
    DocumentRole,
    ProjectState,
    RecordKind,
    SessionState,
)
from app.services.brief_service import BriefService
from app.services.pilot_server import unheld_token_hash
from app.services.project_service import project_name
from app.services.relay_service import SEND_FAILED, RelayService, Words
from app.services.session_record_service import SessionRecordService, read_records
from app.services.session_scope import STORE_REPO
from app.services.session_start_service import SessionStartService
from app.services.start_gate import CHAT_KIND

QUOTE_TAG = re.compile(
    r'<quoted_(item|block) id="([^"]+)">[\s\S]*?</quoted_\1 id="\2">'
    r'|<quoted_path path="(handbook\.md|project\.md|attachments/[1-9][0-9]*/[^"/]+)'
    r'">[\s\S]*?</quoted_path path="\3">'
)
"""A quote tag (F38.3; DB decisions 29, 62), the closing tag repeating the
attribute: an item's or a block's by id, or a file's by its path in the
project's folder, the handbook's, the project document's or an attachment's;
a path tag naming any other path is no quote."""

STORE_NOTIFICATION = (
    "<store_notification>\n"
    "The handbook (handbook.md) changed since your last turn.\n"
    "</store_notification>"
)
"""The server's notice before a person's words when the handbook changed since
the chat's previous Turn (design 3 §5.3)."""

_IN_FLIGHT = "a turn of its chat is in flight"

HANDBOOK_CHANGED_TOTAL = Counter(
    "pilot_chat_handbook_changed_total",
    "Chat turns sent with the server's notice that the project's handbook changed"
    " since the chat's previous turn, by project",
    ["project"],
)


class ChatService:
    """Takes a person's message to a project's brain."""

    def __init__(
        self,
        db: Session,
        relay_service: RelayService,
        session_start_service: SessionStartService,
        brief_service: BriefService,
        session_record_service: SessionRecordService,
        view_service: ViewService,
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
        self.view_service = view_service
        self.brain_model = brain_model
        self.brain_reasoning_effort = brain_reasoning_effort

    def send(self, project_id: uuid.UUID, person: User, words: str) -> Turn:
        """`person`'s message to the project's brain, `words` verbatim, in the
        caller's transaction: sent to the project's open chat, or a chat
        started with it.

        With the chat's session up, the controller's send goes first, as
        `RelayService.send` makes it, under the chat's Session's lock. A start
        makes no controller call: it is written under the project's row,
        locked as a change of its standing locks it, so two starts of the
        project's chat, or a start and a Finish, never interleave, and runs
        once this commits.

        Returns:
            The Turn; one whose send failed has its `error`

        Raises:
            RecordNotFoundException: No project has the id
            InvalidOperationException: The project is a draft or archived; its
                chat's start is under way, or a turn of it is in flight; no
                controller or no store environment is configured
        """
        project = self.db.get(Project, project_id, populate_existing=True)
        if project is None:
            raise RecordNotFoundException("Project", str(project_id))
        operation = f"send a message to Pilot in {project_name(project)}"
        _refuse_message(project, operation)
        quoted = self._quote(project, person, words)
        session = self._open_chat(project.id)
        if session is not None and not _unbriefed(session):
            locked = self._still_open(project, session.id)
            if locked is not None:
                return self._send(project, locked, person, quoted)
        return self._start(project_id, person, quoted, operation)

    def stop(self, project_id: uuid.UUID, person: User) -> ListedChat:
        """`person`'s Stop of Pilot's answer in the project's open chat,
        whoever sent its message, in the caller's transaction (F44), as a work
        item's Stop (`SessionStartService.stop_chat`): a turn in flight is
        interrupted once this commits, the conversation kept for the next
        message; a start held or under way ends its Turn unsent, and the next
        message starts the chat afresh, briefed. The chat closes on its
        timeout as after any turn.

        Returns:
            The chat, its Session `stopped`

        Raises:
            RecordNotFoundException: No project has the id
            InvalidOperationException: No chat of the project is open, or
                Pilot is not answering in it
        """
        project = self.db.get(Project, project_id)
        if project is None:
            raise RecordNotFoundException("Project", str(project_id))
        operation = f"stop Pilot in {project_name(project)}"
        chat = self._open_chat(project.id)
        if chat is None:
            raise InvalidOperationException(operation, "no chat is open")
        session = self.session_start_service.stop_chat(
            self.db, chat.id, person, operation
        )
        return ListedChat(
            self.db.get_one(Chat, session.id), session.created_at, session.state_code
        )

    def _send(
        self, project: Project, session: AgentSession, person: User, words: Words
    ) -> Turn:
        """`person`'s `words` sent to the chat's Session as a turn of it,
        after the line naming them when the chat's previous Turn with an
        author that reached the brain has another author (DB decision 61),
        and first the server's notice when the handbook changed since its
        previous Turn (D052; DB assertion 251), the notice counted once it
        went out."""
        changed = self._handbook_changed(project, session)
        message = words.text
        if self._previous_author(session) != person.id:
            message = f"{self.brief_service.message_from(project, person)}\n{message}"
        if changed:
            message = f"{STORE_NOTIFICATION}\n\n{message}"
        turn = self.relay_service.send(self.db, session.id, message, words=words)
        if changed and turn.error is None:
            HANDBOOK_CHANGED_TOTAL.labels(project=str(project.id)).inc()
        return turn

    def _still_open(
        self, project: Project, session_id: uuid.UUID
    ) -> AgentSession | None:
        """The open chat's Session, locked until the transaction ends while
        its chat is still open, its start went out and its project is not
        archived, so that no close or stop interleaves with its send. None
        when it closed, its start fell through or its project was archived
        meanwhile: the lock let go with the savepoint that took it, since a
        start locks the project's row first (the start's lock order). A
        transition that stops the project's sessions holds that lock to its
        commit (`SessionStartService.stop_project`), so `project` is read
        under it."""
        savepoint = self.db.begin_nested()
        session = self.records.lock_session(session_id)
        chat = self.db.get_one(Chat, session_id, populate_existing=True)
        self.db.get_one(Project, project.id, populate_existing=True)
        if chat.closed_at is None and not project.archived and not _unbriefed(session):
            savepoint.commit()
            return session
        savepoint.rollback()
        return None

    def _previous_author(self, session: AgentSession) -> uuid.UUID | None:
        """The author of the chat's latest Turn with one that reached the
        brain: a server Turn has none, and one whose send failed (F125) never
        went out."""
        authored = self.db.execute(
            select(Turn.id, Turn.author_user_id, Turn.error)
            .where(Turn.session_id == session.id, Turn.author_user_id.is_not(None))
            .order_by(Turn.seq.desc())
        ).all()
        for turn_id, author, error in authored:
            if error is None or not read_records(
                self.db,
                session.id,
                turn_id=turn_id,
                kind=RecordKind.SERVER,
                payload_type=SEND_FAILED,
                limit=1,
            ):
                return author
        return None

    def _handbook_changed(self, project: Project, session: AgentSession) -> bool:
        """Whether the project's handbook was published after the chat's
        previous Turn that reached the brain was sent: one whose send failed
        (F125) never went out, nor the notice it carried, so its retry
        carries it again."""
        published = self.db.scalar(
            select(Document.published_at).where(
                Document.project_id == project.id,
                Document.role_code == DocumentRole.HANDBOOK,
            )
        )
        if published is None:
            return False
        turns = self.db.execute(
            select(Turn.id, Turn.started_at, Turn.error)
            .where(Turn.session_id == session.id)
            .order_by(Turn.seq.desc())
        ).all()
        for turn_id, started_at, error in turns:
            if error is None or not read_records(
                self.db,
                session.id,
                turn_id=turn_id,
                kind=RecordKind.SERVER,
                payload_type=SEND_FAILED,
                limit=1,
            ):
                return published > started_at
        return False

    def _start(
        self, project_id: uuid.UUID, person: User, words: Words, operation: str
    ) -> Turn:
        """The project's chat started with `words`: a new one, or the open
        one whose start failed or was stopped before its brief went out,
        afresh in a headless session of its own. The open chat's Session is
        locked after the project's row (the start's lock order)."""
        project = self._locked(project_id)
        _refuse_message(project, operation)
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
        effort, its token none holds until its create mints one; its opening
        told to the browsers and to `chat.md`."""
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
        self.view_service.chats_moved(project)
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
        their first quote tag names (DB 159); none when it names neither, a
        file's by its path among them (DB decision 62)."""
        tag = QUOTE_TAG.search(words)
        item_id = block_id = None
        if tag is not None and tag[1] is not None:
            kind, ref = tag[1], tag[2]
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


def _refuse_message(project: Project, operation: str) -> None:
    """Refuse a message to a draft's chat, which is the definition chat's, and
    to an archived project's, a send racing the archive among them (F128.5;
    DB 245).

    Raises:
        InvalidOperationException: The project is a draft or archived
    """
    if project.archived:
        raise InvalidOperationException(operation, "its project is archived")
    if project.state_code is ProjectState.DRAFT:
        raise InvalidOperationException(operation, "its project is a draft")
