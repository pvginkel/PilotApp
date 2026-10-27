"""A project chat's close (F130, F5.5, F128.1, F48.2; DB decisions 57, 60,
assertions 244, 245; design 2 §13): at Create project, the definition chat,
`created`, at Finish, `finished`, at Reopen, `reopened`, and at Archive,
`archived`, in the transition's transaction; and `chat_close_timeout`
after its last turn ended with no turn in flight, `timeout`, on the
scheduler's tick. A closed chat is never sent to again: the next message
starts a chat of its own (`ChatService`).

The close's `server` record, `{"type": "closed", "cause": <cause>}`, is the
chat's last (F130.1). The close writes it when no Turn of the chat's Session is
in flight; else the end of that Turn writes it (`turn_ended`) — a turn the
transition stopped, whose relay records the interrupt's end after the
transition commits.

The tick ends the chat's controller session, under its Session's lock, before
it closes the chat, its Session then `ended`; a controller that does not
answer leaves the chat open for the next tick. Create project, Finish, Reopen
and Archive call no controller: a chat they close keeps its controller
session, idle or interrupted, and nothing sends to it again. The definition chat never closes
by timeout (F130.2).
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.engine.views import ViewService
from app.models import Chat, Project, Turn
from app.models import Session as AgentSession
from app.models.reference import ChatKind, CloseCause, RecordKind, SessionState
from app.services.controller_client import (
    ControllerClient,
    ControllerProblem,
    ControllerProblemType,
)
from app.services.session_record_service import SessionRecordService, read_records
from app.services.session_stream_service import SessionStreamService
from app.services.supervisor import Supervisor
from app.services.work_status import work_moved

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)

CLOSE_TIMER = "chat-close"

CLOSED = "closed"
"""The `type` of the `server` record of a chat's close, its last record."""

_RECORD_PAGE = 32
"""The `server` records one read of a Session's takes, newest first."""

_NOTHING_TO_END = (ControllerProblemType.NOT_FOUND, ControllerProblemType.CONFLICT)
"""The controller's refusals of a session's end that leave no session to end:
its environment gone, or not running, which no headless session outlives."""


class ChatCloseService:
    """Closes the project chats: at Create project, Finish, Reopen and
    Archive, and on the timer."""

    def __init__(
        self,
        container: "ServiceContainer",
        supervisor: Supervisor,
        session_streams: SessionStreamService,
        close_after_seconds: float,
    ) -> None:
        """Register the close timer, its reconcile its tick.

        Args:
            container: Gives the tick its client and the bus
            supervisor: Runs the timer on its tick
            session_streams: Woken by the close's record
            close_after_seconds: How long after its last turn ended an open
                project chat with no turn in flight is closed
        """
        self._container = container
        self._streams = session_streams
        self._close_after = timedelta(seconds=close_after_seconds)
        supervisor.register_timer(
            CLOSE_TIMER, self.run_close_timer, needs_controller=True
        )

    def open_chat(self, db: Session, project: Project) -> Chat | None:
        """The project's open chat, none while none is open, its Session
        locked until the caller's transaction ends, after the project's row,
        which the caller holds, and before any Item: a message's send holds
        that lock from before its Turn to its commit (`ChatService`)."""
        chat = db.scalars(
            select(Chat)
            .where(Chat.project_id == project.id, Chat.closed_at.is_(None))
            .execution_options(populate_existing=True)
        ).one_or_none()
        if chat is not None:
            self._records(db).lock_session(chat.id)
        return chat

    def close_open(
        self, db: Session, project: Project, cause: CloseCause, at: datetime
    ) -> None:
        """The project's open chat closed with `cause` at `at`, Create
        project's, Finish's, Reopen's or Archive's (F48.2, F5.5, F128.1), in
        the caller's transaction, which holds the project's row and has
        stopped the project's sessions, the chat's among them, or at Create
        found no Turn of it in flight (`open_chat`'s lock)."""
        chat = self.open_chat(db, project)
        if chat is None:
            return
        self._close(db, self._records(db), chat, cause, at)

    def turn_ended(self, db: Session, session: AgentSession) -> None:
        """A Turn of the Session ended, under its lock: a chat closed while
        the Turn was in flight has the close's record written now that none
        is, so the close stands last; once."""
        chat = db.get(Chat, session.id, populate_existing=True)
        if (
            chat is None
            or chat.close_cause_code is None
            or _in_flight(db, session.id)
            or _close_recorded(db, session.id)
        ):
            return
        self._records(db).append(
            session.id, RecordKind.SERVER, payload=_closed(chat.close_cause_code)
        )

    def run_close_timer(self, db: Session) -> None:
        """The close timer's tick, and its reconcile (F130; design 2 §13):
        every open project chat whose Session's last Turn ended
        `chat_close_timeout` ago or more, with no Turn in flight, closed
        `timeout`, its controller session ended. Each chat's close is a
        transaction of its own, under its Session's lock: one another
        transaction holds, a message's send among them, is skipped."""
        cutoff = datetime.now(UTC) - self._close_after
        due = db.scalars(
            select(Chat.id)
            .join(AgentSession, AgentSession.id == Chat.id)
            .where(
                Chat.closed_at.is_(None),
                Chat.kind_code == ChatKind.PROJECT,
                AgentSession.turn_ended_at <= cutoff,
            )
            .order_by(AgentSession.turn_ended_at, Chat.id)
        ).all()
        for chat_id in due:
            self._close_if_due(db, chat_id, cutoff)
            db.commit()

    def _close_if_due(self, db: Session, chat_id: uuid.UUID, cutoff: datetime) -> None:
        session = db.scalars(
            select(AgentSession)
            .where(AgentSession.id == chat_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).one_or_none()
        if session is None:
            return
        chat = db.get_one(Chat, chat_id, populate_existing=True)
        if (
            chat.closed_at is not None
            or session.turn_ended_at is None
            or session.turn_ended_at > cutoff
            or _in_flight(db, chat_id)
        ):
            return
        if session.controller_session is not None:
            # A controller session is created in its Session's Environment.
            assert session.environment_id is not None
            self._end(session.environment_id, session.controller_session)
            session.state_code = SessionState.ENDED
            session.current_line = None
            work_moved(self._container.engine_bus(), session, state=True)
        self._close(db, self._records(db), chat, CloseCause.TIMEOUT, datetime.now(UTC))

    def _end(self, env_id: str, name: str) -> None:
        """End the controller session; one its environment no longer runs
        is ended already.

        Raises:
            ControllerUnreachable: The controller did not answer
            ExternalServiceException: The controller failed otherwise
        """
        try:
            self._client().end_session(env_id, name)
        except ControllerProblem as problem:
            if problem.problem_type not in _NOTHING_TO_END:
                raise
            logger.info("Session %s has no session to end: %s", name, problem)

    def _close(
        self,
        db: Session,
        records: SessionRecordService,
        chat: Chat,
        cause: CloseCause,
        at: datetime,
    ) -> None:
        """Under the chat's Session's lock: closed with `cause` at `at`, and
        the close's record written unless a Turn is in flight; the close told
        to the browsers and to `chat.md`."""
        chat.closed_at = at
        chat.close_cause_code = cause
        db.flush()
        if not _in_flight(db, chat.id):
            records.append(chat.id, RecordKind.SERVER, payload=_closed(cause))
        self._views(db).chats_moved(db.get_one(Project, chat.project_id))
        logger.info("Chat %s closed: %s", chat.id, cause)

    def _records(self, db: Session) -> SessionRecordService:
        return SessionRecordService(db, self._streams, self._views(db))

    def _views(self, db: Session) -> ViewService:
        return ViewService(db, self._container.engine_bus())

    def _client(self) -> ControllerClient:
        client: ControllerClient = self._container.controller_client()
        return client


def _closed(cause: CloseCause) -> dict[str, str]:
    return {"type": CLOSED, "cause": cause}


def _in_flight(db: Session, session_id: uuid.UUID) -> bool:
    """Whether a Turn of the Session has not ended."""
    return bool(
        db.scalar(
            select(
                exists().where(Turn.session_id == session_id, Turn.ended_at.is_(None))
            )
        )
    )


def _close_recorded(db: Session, session_id: uuid.UUID) -> bool:
    """Whether the Session has its close's record, its `server` records read
    newest first a page at a time."""
    before = None
    while True:
        page = read_records(
            db,
            session_id,
            before=before,
            kind=RecordKind.SERVER,
            limit=_RECORD_PAGE,
            newest_first=True,
        )
        if any(stored.record.payload.get("type") == CLOSED for stored in page):
            return True
        if len(page) < _RECORD_PAGE:
            return False
        before = page[-1].record.seq
