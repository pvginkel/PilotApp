"""The session start: a Session brought up end to end, from its row to its
brief's send (design 2 §13.2, §7.1; F88.1, F125; decision 38).

`start_session` writes, in the caller's transaction, the Session `starting` and
its first Turn, the brief, before the environment is up. Once that commits, the
Session's start loop, `start:<id>`, brings the environment up, creates the
headless session and sends the brief, whose `202` starts the relay. Each phase
the start enters is a `server` record in no Turn (DB assertion 220), and each
such record rebuilds the current line in its transaction.

Every failure of the controller during the start leaves the Session `failed`
with its `error` and a `server` record saying so, its brief no longer in
flight, and nothing is retried (F125).
"""

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core_exceptions import ExternalServiceException
from app.database import scoped_session
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import Environment, Project, Turn
from app.models import Session as AgentSession
from app.models.reference import RecordKind, SessionState
from app.services.controller_client import ControllerClient, HeadlessCreateRequest
from app.services.current_line import while_starting
from app.services.environment_service import EnvironmentService
from app.services.relay_service import RelayService
from app.services.session_record_service import SessionRecordService
from app.services.session_stream_service import SessionStreamService
from app.services.supervisor import LoopHandle, Supervisor
from app.utils.after_commit import after_commit

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)

START_JOB = "start"

STARTING = "starting"
"""The `type` of the `server` record that names a phase of the start."""

START_FAILED = "start-failed"
"""The `type` of the `server` record a start that failed writes."""

CREATING = "Creating the session…"


@dataclass(frozen=True)
class SessionOptions:
    """The headless create's options, which the Session keeps (DB Session)."""

    agent: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    resume: str | None = None
    """A conversation to resume: the Session's `conversation_id`."""


@dataclass(frozen=True)
class _LoopStart:
    # `after_commit()` runs a callback equal to one it holds once.
    starts: "SessionStartService"
    session_id: uuid.UUID

    def __call__(self) -> None:
        self.starts._start_loop(self.session_id)


@dataclass(frozen=True)
class _Pending:
    """A `starting` Session, as its start loop's run reads it."""

    env_id: str
    controller_session: str | None
    create: HeadlessCreateRequest
    brief_id: int


class SessionStartService:
    """Brings Sessions up: writes each `starting`, then runs its start loop."""

    def __init__(
        self,
        container: "ServiceContainer",
        supervisor: Supervisor,
        session_streams: SessionStreamService,
        environment_service: EnvironmentService,
        relay_service: RelayService,
        controller_configured: bool,
    ) -> None:
        """Register the `start` job, whose loops are one per Session.

        Args:
            container: Gives each start transaction its database session, and
                the client
            supervisor: Runs the start loops
            session_streams: Woken by the records the start writes
            environment_service: Makes the Environment row, starts the
                environment, and clears and arms its shutdown timer
            relay_service: Sends the brief, and relays its turn
            controller_configured: False refuses every start
        """
        self._container = container
        self._supervisor = supervisor
        self._streams = session_streams
        self._environments = environment_service
        self._relays = relay_service
        self._controller_configured = controller_configured
        supervisor.register_job(START_JOB, needs_controller=True)

    def start_session(
        self,
        db: Session,
        project_id: uuid.UUID,
        env_id: str,
        *,
        kind_code: str,
        cwd: str,
        brief: str,
        options: SessionOptions | None = None,
    ) -> AgentSession:
        """Write a Session `starting` in the environment, its first Turn the
        brief, in the caller's transaction, and run its start once that commits.

        The Environment row is made on Pilot's first touch, the Session gets
        the hash of a token minted for it, its first `server` record names the
        environment's start, and the environment's shutdown timer is cleared.

        Returns:
            The Session, `starting`

        Raises:
            InvalidOperationException: No controller is configured
            RecordNotFoundException: No Project has the id
            ControllerProblem: `not-found` when the controller has no such
                environment
            ExternalServiceException: The controller failed otherwise
        """
        if not self._controller_configured:
            raise InvalidOperationException(
                f"start a session in environment {env_id}",
                "no controller is configured",
            )
        if db.get(Project, project_id) is None:
            raise RecordNotFoundException("Project", str(project_id))
        options = options or SessionOptions()
        self._environments.ensure_environment(db, env_id)
        environment = db.get_one(Environment, env_id)
        now = datetime.now(UTC)
        session = AgentSession(
            project_id=project_id,
            environment_id=env_id,
            kind_code=kind_code,
            cwd=cwd,
            agent=options.agent,
            model=options.model,
            reasoning_effort=options.reasoning_effort,
            conversation_id=options.resume,
            token_hash=hashlib.sha256(secrets.token_urlsafe(32).encode()).hexdigest(),
            state_code=SessionState.STARTING,
            turns=1,
            turn_started_at=now,
        )
        db.add(session)
        db.flush()
        db.add(Turn(session_id=session.id, seq=1, message=brief, started_at=now))
        db.flush()
        self._phase(db, session.id, f"Starting {environment.name}…")
        self._environments.clear_shutdown_timer(db, env_id)
        after_commit(_LoopStart(self, session.id))
        return session

    def run(self, session_id: uuid.UUID, handle: LoopHandle) -> None:
        """The start loop's run, from where the Session's rows left its start:
        the environment brought up and the headless session created while the
        Session has no controller session, then the brief sent. Returns at once
        for a Session no longer `starting`, and between the phases when the
        loop is told to stop.
        """
        with scoped_session(self._container) as db:
            pending = _pending(db, session_id)
        if pending is None:
            return
        if pending.controller_session is None:
            try:
                self._environments.start(pending.env_id)
                if handle.stopping:
                    return
                with scoped_session(self._container) as db:
                    self._phase(db, session_id, CREATING)
                created = self._client().create_headless_session(
                    pending.env_id, pending.create
                )
            except ExternalServiceException as error:
                with scoped_session(self._container) as db:
                    self._fail(db, session_id, str(error), recorded=False)
                return
            with scoped_session(self._container) as db:
                session = self._records(db).lock_session(session_id)
                session.controller_session = created.name
                session.started_at = datetime.now(UTC)
            if handle.stopping:
                return
        with scoped_session(self._container) as db:
            brief = self._relays.send_turn(db, pending.brief_id)
            if brief.error is not None:
                self._fail(db, session_id, brief.error, recorded=True)

    def _start_loop(self, session_id: uuid.UUID) -> None:
        self._supervisor.start_loop(
            START_JOB, partial(self.run, session_id), key=str(session_id)
        )

    def _phase(self, db: Session, session_id: uuid.UUID, text: str) -> None:
        """The `server` record naming the phase the start enters, and the
        current line in its words."""
        records = self._records(db)
        record = records.append(
            session_id, RecordKind.SERVER, payload={"type": STARTING, "text": text}
        )
        session = records.lock_session(session_id)
        session.current_line = while_starting(text, record.at)

    def _fail(
        self, db: Session, session_id: uuid.UUID, reason: str, *, recorded: bool
    ) -> None:
        """The Session `failed` with `reason`, its brief ended, and a `server`
        record saying so unless the brief's failed send `recorded` one. Then
        the environment's shutdown timer is armed, if it is Pilot's to stop and
        nothing else runs or starts there."""
        records = self._records(db)
        if not recorded:
            records.append(
                session_id,
                RecordKind.SERVER,
                payload={"type": START_FAILED, "reason": reason},
            )
        session = records.lock_session(session_id)
        brief = _brief(db, session_id)
        if brief.ended_at is None:
            brief.ended_at = datetime.now(UTC)
        session.turn_ended_at = brief.ended_at
        session.state_code = SessionState.FAILED
        session.error = reason
        session.current_line = None
        self._environments.arm_shutdown_timer(db, session.environment_id)
        logger.warning("Session %s failed to start: %s", session_id, reason)

    def _records(self, db: Session) -> SessionRecordService:
        return SessionRecordService(db, self._streams)

    def _client(self) -> ControllerClient:
        client: ControllerClient = self._container.controller_client()
        return client


def _pending(db: Session, session_id: uuid.UUID) -> _Pending | None:
    """The Session's start as its rows have it; None when it is not
    `starting`."""
    session = db.get_one(AgentSession, session_id)
    if session.state_code != SessionState.STARTING:
        return None
    return _Pending(
        env_id=session.environment_id,
        controller_session=session.controller_session,
        create=HeadlessCreateRequest(
            cwd=session.cwd,
            resume=session.conversation_id,
            agent=session.agent,
            model=session.model,
            reasoning_effort=session.reasoning_effort,
        ),
        brief_id=_brief(db, session_id).id,
    )


def _brief(db: Session, session_id: uuid.UUID) -> Turn:
    """The Session's first Turn, which its start writes."""
    return db.scalars(
        select(Turn).where(Turn.session_id == session_id, Turn.seq == 1)
    ).one()
