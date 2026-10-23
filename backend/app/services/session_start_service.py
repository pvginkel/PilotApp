"""The session start: a Session brought up end to end, from its row to its
brief's send (design 2 §13.2, §13.4, §7.1; F88.1, F125, F141.5; decision 38).

`start_session` writes, in the caller's transaction, the Session and its first
Turn, the brief, before the environment is up; `start_work` writes a work
item's so, its Item and its Work with it. The gate (§13.4) decides the
Session's state: `held` while it is closed, with nothing run for it, else
`starting`. A `starting` Session's start loop, `start:<id>`, runs once that
commits: it brings the environment up, creates the headless session and sends
the brief, whose `202` starts the relay. Each phase the start enters is a
`server` record in no Turn (DB assertion 220), and each such record rebuilds
the current line in its transaction.

A start that meets a call the controller does not answer goes back to `held`
with its rows as they stand, the outage on (DB 230). Every other failure of the
controller during the start leaves the Session `failed` with its `error` and a
`server` record saying so, its brief no longer in flight, and nothing is
retried (F125).

When the gate opens — the outage off, at the probe's success or the fleet
stream's reconnect — the held Sessions it opens for move to `starting` in
`created_at` order, each under its lock while it is still `held`, and each
loop resumes its start where the rows left it. The probe, the controller's
readiness call, runs on the scheduler's tick while the outage holds.

At STARTUP the job's reconcile runs the start loop of every Session still
`starting`, which resumes where its rows left it, and opens the gate for the
held ones (§8.2). Each write the run makes is conditional on the rows it read,
under the Session's lock, so a second process running the same start during a
roll's overlap (§8.1) changes nothing the first has written.
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
from app.models import Environment, Project, Turn, Work
from app.models import Session as AgentSession
from app.models.reference import RecordKind, SessionState
from app.services.controller_client import (
    ControllerClient,
    ControllerUnreachable,
    HeadlessCreateRequest,
)
from app.services.controller_outage import ControllerOutage
from app.services.current_line import while_starting
from app.services.environment_service import EnvironmentService
from app.services.relay_service import RelayService
from app.services.session_record_service import SessionRecordService
from app.services.session_stream_service import SessionStreamService
from app.services.start_gate import held_reason
from app.services.supervisor import LoopHandle, Supervisor
from app.services.work_status import work_moved
from app.utils.after_commit import after_commit

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)

START_JOB = "start"

RELEASE_KEY = "held"
"""The key of the start job's loop that moves the held Sessions on."""

PROBE_TIMER = "controller-probe"

STARTING = "starting"
"""The `type` of the `server` record that names a phase of the start."""

START_FAILED = "start-failed"
"""The `type` of the `server` record a start that failed writes."""

CREATING = "Creating the session…"

WORK_KIND = "work"


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
class _HeldWritten:
    # `after_commit()` runs a callback equal to one it holds once.
    starts: "SessionStartService"

    def __call__(self) -> None:
        # The gate may have opened between the write's read of it and this
        # commit, its release missing the Session; the release reads the
        # project's pause itself.
        if not self.starts._outage.holds:
            self.starts.release_held()


@dataclass(frozen=True)
class _Pending:
    """A `starting` Session, as its start loop's run reads it."""

    env_id: str
    controller_session: str | None
    create: HeadlessCreateRequest
    brief_id: int


class SessionStartService:
    """Brings Sessions up through the gate: writes each `held` or `starting`,
    runs the start loop of each `starting` one, and moves the held ones on
    when the gate opens."""

    def __init__(
        self,
        container: "ServiceContainer",
        supervisor: Supervisor,
        session_streams: SessionStreamService,
        environment_service: EnvironmentService,
        relay_service: RelayService,
        controller_outage: ControllerOutage,
        controller_configured: bool,
    ) -> None:
        """Register the `start` job, whose loops are one per Session and one
        that moves the held Sessions on, and whose reconcile runs the start of
        every Session still `starting` and opens the gate; and the probe's
        timer.

        Args:
            container: Gives each start transaction its database session, and
                the client
            supervisor: Runs the start loops and the probe
            session_streams: Woken by the records the start writes
            environment_service: Makes the Environment row, starts the
                environment, and clears and arms its shutdown timer
            relay_service: Sends the brief, and relays its turn
            controller_outage: The gate's outage, which the probe turns off;
                its turning off opens the gate
            controller_configured: False refuses every start
        """
        self._container = container
        self._supervisor = supervisor
        self._streams = session_streams
        self._environments = environment_service
        self._relays = relay_service
        self._outage = controller_outage
        self._controller_configured = controller_configured
        supervisor.register_job(
            START_JOB, needs_controller=True, reconcile=self._reconcile
        )
        supervisor.register_timer(PROBE_TIMER, self.run_probe, needs_controller=True)
        controller_outage.subscribe(self._outage_moved)

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
        """Write a Session in the environment, its first Turn the brief, in
        the caller's transaction, through the gate (§13.4): `held` while the
        gate is closed for it, with nothing run; else `starting`, its start
        run once that commits.

        The Environment row is made on Pilot's first touch, and the Session
        gets the hash of a token minted for it. A `starting` one's first
        `server` record names the environment's start, and the environment's
        shutdown timer is cleared.

        Returns:
            The Session, `starting`, or `held` while the gate is closed

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
        project = db.get(Project, project_id)
        if project is None:
            raise RecordNotFoundException("Project", str(project_id))
        options = options or SessionOptions()
        self._environments.ensure_for_start(db, env_id)
        held = held_reason(
            paused=project.paused,
            kind_code=kind_code,
            unreachable=self._outage.holds,
        )
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
            state_code=SessionState.STARTING if held is None else SessionState.HELD,
            turns=1,
            turn_started_at=now,
        )
        db.add(session)
        db.flush()
        db.add(Turn(session_id=session.id, seq=1, message=brief, started_at=now))
        db.flush()
        if held is None:
            self._begin(db, session)
        else:
            after_commit(_HeldWritten(self))
            logger.info("Session %s is held at its start: %s", session.id, held)
        return session

    def start_work(
        self,
        db: Session,
        project_id: uuid.UUID,
        env_id: str,
        *,
        title: str,
        brief: str,
        cwd: str,
        plan_task_id: str | None = None,
    ) -> Work:
        """Place a work item titled `title` on the project's timeline, on the
        plan's task `plan_task_id` when given, and write its `work` Session's
        start in the environment through the gate as `start_session` writes
        one, in the caller's transaction: its Item, its Work and its Session
        one id (DB Work, decision 3).

        Returns:
            The Work

        Raises:
            InvalidOperationException: No controller is configured
            RecordNotFoundException: No Project has the id, or its plan has
                no task `plan_task_id`
            ControllerProblem: `not-found` when the controller has no such
                environment
            ExternalServiceException: The controller failed otherwise
        """
        session = self.start_session(
            db, project_id, env_id, kind_code=WORK_KIND, cwd=cwd, brief=brief
        )
        return self._container.record_service().place_work(
            db.get_one(Project, project_id), session, title, plan_task_id
        )

    def run(self, session_id: uuid.UUID, handle: LoopHandle) -> None:
        """The start loop's run, from where the Session's rows left its start:
        the environment brought up and the headless session created while the
        Session has no controller session, then the brief sent, unless the
        controller has it already. Returns at once for a Session no longer
        `starting`, and between the phases when the loop is told to stop. A
        controller session another process recorded first stands, and the one
        this run created is left to the controller's reaper. A call the
        controller does not answer returns the Session to `held`; any other
        failure fails it (F125).
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
                    pending = self._creating(db, session_id)
                if pending is None:
                    return
                created = (
                    self._client().create_headless_session(
                        pending.env_id, pending.create
                    )
                    if pending.controller_session is None
                    else None
                )
            except ControllerUnreachable as error:
                with scoped_session(self._container) as db:
                    self._hold(db, session_id, error)
                return
            except ExternalServiceException as error:
                with scoped_session(self._container) as db:
                    self._fail(db, session_id, str(error), recorded=False)
                return
            if created is not None:
                with scoped_session(self._container) as db:
                    session = self._records(db).lock_session(session_id)
                    if (
                        session.state_code == SessionState.STARTING
                        and session.controller_session is None
                    ):
                        session.controller_session = created.name
                        session.started_at = datetime.now(UTC)
                        self._moved(session)
            if handle.stopping:
                return
        with scoped_session(self._container) as db:
            try:
                brief = self._relays.send_turn(db, pending.brief_id)
            except ControllerUnreachable as error:
                self._hold(db, session_id, error)
                return
            if brief.error is not None:
                self._fail(db, session_id, brief.error, recorded=True)

    def release_held(self) -> None:
        """Move on the held Sessions the gate is open for, on a loop of their
        own: called once the gate may have opened. A call while that loop runs
        has it run once more."""
        self._supervisor.start_loop(
            START_JOB, self.release, key=RELEASE_KEY, again=True
        )

    def release(self, handle: LoopHandle) -> None:
        """The release loop's run: each held Session in `created_at` order,
        moved to `starting` under its lock while it is still `held` and the
        gate is open for it, its loop run once that commits. Ends while the
        outage holds, which holds every start."""
        with scoped_session(self._container) as db:
            held = db.scalars(
                select(AgentSession.id)
                .where(AgentSession.state_code == SessionState.HELD)
                .order_by(AgentSession.created_at, AgentSession.id)
            ).all()
        for session_id in held:
            if handle.stopping or self._outage.holds:
                return
            with scoped_session(self._container) as db:
                self._release_one(db, session_id)

    def run_probe(self, db: Session) -> None:
        """The gate's probe, on the scheduler's tick (§8.2, §13.4): while the
        outage holds, the controller's readiness call, whose answer turns it
        off; one with no answer keeps it on."""
        if not self._outage.holds:
            return
        try:
            self._client().probe()
        except ExternalServiceException as error:
            logger.debug("The probe found the controller unreachable: %s", error)
            return
        self._outage.probe_answered()

    def _reconcile(self, db: Session) -> None:
        """At STARTUP: run the start of every Session still `starting`, and
        open the gate for the held ones, the outage off in a fresh process
        (§8.2)."""
        for session_id in db.scalars(
            select(AgentSession.id)
            .where(AgentSession.state_code == SessionState.STARTING)
            .order_by(AgentSession.id)
        ):
            logger.info("Resuming the start of session %s", session_id)
            self._start_loop(session_id)
        self.release_held()

    def _release_one(self, db: Session, session_id: uuid.UUID) -> None:
        session = self._records(db).lock_session(session_id)
        if session.state_code != SessionState.HELD:
            return
        project = db.get_one(Project, session.project_id, populate_existing=True)
        if (
            held_reason(
                paused=project.paused,
                kind_code=session.kind_code,
                unreachable=self._outage.holds,
            )
            is not None
        ):
            return
        session.state_code = SessionState.STARTING
        self._begin(db, session)
        self._moved(session, state=True)
        logger.info("Session %s goes on from held", session_id)

    def _begin(self, db: Session, session: AgentSession) -> None:
        """The start of a `starting` Session begun: the phase that starts its
        environment, unless it has its controller session already, the
        environment's shutdown timer cleared, and its loop run once the
        transaction commits."""
        if session.controller_session is None:
            environment = db.get_one(Environment, session.environment_id)
            self._phase(db, session.id, f"Starting {environment.name}…")
        self._environments.clear_shutdown_timer(db, session.environment_id)
        after_commit(_LoopStart(self, session.id))

    def _hold(
        self, db: Session, session_id: uuid.UUID, error: ControllerUnreachable
    ) -> None:
        """The Session back to `held` where its rows stand, the outage on,
        while it is still `starting` (DB 230)."""
        session = self._records(db).lock_session(session_id)
        if session.state_code != SessionState.STARTING:
            return
        session.state_code = SessionState.HELD
        self._moved(session, state=True)
        after_commit(_HeldWritten(self))
        logger.warning("Session %s is held: %s", session_id, error)

    def _outage_moved(self) -> None:
        if not self._outage.holds:
            self.release_held()

    def _start_loop(self, session_id: uuid.UUID) -> None:
        # A run that held the Session still counts as live until its thread
        # ends: `again` has it run once more, which resumes the start.
        self._supervisor.start_loop(
            START_JOB, partial(self.run, session_id), key=str(session_id), again=True
        )

    def _creating(self, db: Session, session_id: uuid.UUID) -> _Pending | None:
        """The Session's start as its rows have it under its lock, with the
        phase that creates the headless session written while it has no
        controller session; None when it is no longer `starting`."""
        self._records(db).lock_session(session_id)
        pending = _pending(db, session_id)
        if pending is not None and pending.controller_session is None:
            self._phase(db, session_id, CREATING)
        return pending

    def _phase(self, db: Session, session_id: uuid.UUID, text: str) -> None:
        """The `server` record naming the phase the start enters, and the
        current line in its words."""
        records = self._records(db)
        record = records.append(
            session_id, RecordKind.SERVER, payload={"type": STARTING, "text": text}
        )
        session = records.lock_session(session_id)
        session.current_line = while_starting(text, record.at)
        self._moved(session)

    def _fail(
        self, db: Session, session_id: uuid.UUID, reason: str, *, recorded: bool
    ) -> None:
        """The Session `failed` with `reason`, its brief ended, and a `server`
        record saying so unless the brief's failed send `recorded` one. Then
        the environment's shutdown timer is armed, if it is Pilot's to stop and
        nothing else runs or starts there. A Session no longer `starting` is
        left as it is."""
        records = self._records(db)
        if records.lock_session(session_id).state_code != SessionState.STARTING:
            return
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
        self._moved(session, state=True)
        self._environments.arm_shutdown_timer(db, session.environment_id)
        logger.warning("Session %s failed to start: %s", session_id, reason)

    def _moved(self, session: AgentSession, *, state: bool = False) -> None:
        work_moved(self._container.engine_bus(), session, state=state)

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
