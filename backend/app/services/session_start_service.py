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

A work item's Stop ends its Session where it is (F67.1): a turn in flight is
interrupted after the commit, and a start held or under way ends, nothing of it
sent afterwards. Finish and Archive stop every Session of the project so (F5.1,
F128.1). Its Resume writes a server-own Turn, "continue", or the ended Turn's
message while the Session has no conversation (R15's rule), and passes the gate
as a start does (F67.2): `held`, or `starting`, its loop sending the Turn to
its controller session, or to one created anew, its environment started again,
when that one is gone or its environment is not running (§9.6).
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
from app.models import Environment, Project, Turn, User, Work
from app.models import Session as AgentSession
from app.models.reference import ProjectState, RecordKind, SessionState
from app.services.controller_client import (
    ControllerClient,
    ControllerProblem,
    ControllerProblemType,
    ControllerUnreachable,
    HeadlessCreateRequest,
)
from app.services.controller_outage import ControllerOutage
from app.services.current_line import while_starting
from app.services.environment_service import EnvironmentService
from app.services.relay_service import CONTINUE, SESSION_GONE, RelayService
from app.services.session_record_service import SessionRecordService
from app.services.session_stream_service import SessionStreamService
from app.services.start_gate import CHAT_KIND, held_reason
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

STOPPABLE = (SessionState.RUNNING, SessionState.STARTING, SessionState.HELD)
"""The states a Stop ends a Session in: a turn in flight, a start under way or
held at the gate."""

_STOP_REFUSALS = {
    SessionState.IDLE: "its turn has ended",
    SessionState.STOPPED: "it is stopped already",
    SessionState.ENDED: "its session has ended",
    SessionState.FAILED: "it has failed",
}

_RESUMABLE = (SessionState.STOPPED, SessionState.FAILED)

_RESUME_REFUSALS = {
    SessionState.HELD: "its start waits at the gate",
    SessionState.STARTING: "it is starting",
    SessionState.RUNNING: "it is running",
    SessionState.IDLE: "its turn has ended",
    SessionState.ENDED: "its session has ended",
}

_DONE_STATUSES = ("ended", "error")
"""A headless session's terminal statuses: it takes no turn."""


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
    turn_id: int
    """The Turn the start sends: the brief, or a Resume's."""
    resuming: bool
    """The Turn is a Resume's: the Session's controller session may be gone,
    or its environment stopped, since it last ran."""


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

        Nothing but a Chat's starts in a finished or an archived project
        (F5.1, F128.1): the project's row is read under a share lock, so a
        start and a Finish or an Archive never interleave.

        Returns:
            The Session, `starting`, or `held` while the gate is closed

        Raises:
            InvalidOperationException: No controller is configured, or the
                project is finished or archived
            RecordNotFoundException: No Project has the id
            ControllerProblem: `not-found` when the controller has no such
                environment
            ExternalServiceException: The controller failed otherwise
        """
        operation = f"start a session in environment {env_id}"
        if not self._controller_configured:
            raise InvalidOperationException(operation, "no controller is configured")
        project = _shared(db, project_id)
        refusal = _closed(project)
        if refusal is not None and kind_code != CHAT_KIND:
            raise InvalidOperationException(operation, refusal)
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
            InvalidOperationException: No controller is configured, or the
                project is finished or archived
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
        Session has no controller session, then its Turn sent, the brief or a
        Resume's, unless the controller has it already. A Resume's controller
        session that is gone, or whose environment is not running, is given up
        first, a `server` record saying so, and the start goes on from the
        environment. Returns at once for a Session no longer `starting`, and
        between the phases when the loop is told to stop. A controller session
        another process recorded first stands, and the one this run created is
        left to the controller's reaper, as it is for a Session stopped while
        it was created. A call the controller does not answer
        returns the Session to `held`; any other failure fails it (F125).
        """
        with scoped_session(self._container) as db:
            pending = _pending(db, session_id)
        if pending is None:
            return
        if pending.resuming and pending.controller_session is not None:
            try:
                lost = self._lost_reason(pending.env_id, pending.controller_session)
            except ControllerUnreachable as error:
                with scoped_session(self._container) as db:
                    self._hold(db, session_id, error)
                return
            except ExternalServiceException as error:
                with scoped_session(self._container) as db:
                    self._fail(db, session_id, str(error), recorded=False)
                return
            if lost is not None:
                with scoped_session(self._container) as db:
                    pending = self._lost(
                        db, session_id, pending.controller_session, lost
                    )
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
                    if session.state_code != SessionState.STARTING:
                        return
                    if session.controller_session is None:
                        session.controller_session = created.name
                        session.started_at = datetime.now(UTC)
                        self._moved(session)
            if handle.stopping:
                return
        with scoped_session(self._container) as db:
            try:
                turn = self._relays.send_turn(db, pending.turn_id)
            except ControllerUnreachable as error:
                self._hold(db, session_id, error)
                return
            if turn.error is not None:
                self._fail(db, session_id, turn.error, recorded=True)
            elif pending.resuming:
                self._resumed(db, session_id, turn)

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

    def stop(self, db: Session, session_id: uuid.UUID, person: User) -> AgentSession:
        """`person`'s Stop of a work item, in the caller's transaction (F67.1):
        its Session `stopped` where it is, as `_stop` writes it.

        Returns:
            The Session, `stopped`

        Raises:
            RecordNotFoundException: No Session has the id
            InvalidOperationException: The Session is no work item's, or it is
                neither running, starting nor held at the gate
        """
        session = self._records(db).lock_session(session_id)
        operation = f"stop work item {session_id}"
        if db.get(Work, session_id) is None:
            raise InvalidOperationException(operation, "it is no work item")
        if session.state_code not in STOPPABLE:
            raise InvalidOperationException(
                operation, _STOP_REFUSALS[session.state_code]
            )
        self._stop(db, session, person, datetime.now(UTC))
        return session

    def stop_project(
        self, db: Session, project: Project, person: User, at: datetime
    ) -> None:
        """Every Session of the project running, starting or held, a Chat's
        among them, stopped by `person` at `at` as a Stop stops a work item:
        Finish's and Archive's (F5.1, F128.1). It calls no controller in the
        transaction. The caller holds the project's row; the Sessions are
        locked before any Item, which a turn's end locks after its Session."""
        for session in db.scalars(
            select(AgentSession)
            .where(
                AgentSession.project_id == project.id,
                AgentSession.state_code.in_(STOPPABLE),
            )
            .order_by(AgentSession.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ):
            self._stop(db, session, person, at)

    def resume(self, db: Session, session_id: uuid.UUID) -> AgentSession:
        """A work item's Resume, stopped or failed, in the caller's
        transaction (F67.2): a server-own Turn, "continue", or the ended
        Turn's message while the Session has no conversation (R15's rule, so
        a failed start's carries its brief), and the Session through the gate
        (§13.4): `held` while it is closed, else `starting`, its loop sending
        the Turn once this commits. The item stays one item (F26.7); its
        Session's `error` is cleared.

        The project's row is read under a share lock, so a Resume and a
        Finish or an Archive never interleave.

        Returns:
            The Session, `starting`, or `held` while the gate is closed

        Raises:
            RecordNotFoundException: No Session has the id
            InvalidOperationException: No controller is configured; the
                Session is no work item's, is neither stopped nor failed, or
                has its stopped turn still in flight; or the project is
                finished or archived
        """
        operation = f"resume work item {session_id}"
        if not self._controller_configured:
            raise InvalidOperationException(operation, "no controller is configured")
        records = self._records(db)
        project = _shared(db, records.require_session(session_id).project_id)
        session = records.lock_session(session_id)
        if db.get(Work, session_id) is None:
            raise InvalidOperationException(operation, "it is no work item")
        if session.state_code not in _RESUMABLE:
            raise InvalidOperationException(
                operation, _RESUME_REFUSALS[session.state_code]
            )
        refusal = _closed(project)
        if refusal is not None:
            raise InvalidOperationException(operation, refusal)
        ended = _latest_turn(db, session_id)
        if ended.ended_at is None:
            raise InvalidOperationException(
                operation, "its stopped turn is still ending"
            )
        now = datetime.now(UTC)
        turn = Turn(
            session_id=session_id,
            seq=ended.seq + 1,
            message=ended.message if session.conversation_id is None else CONTINUE,
            started_at=now,
        )
        db.add(turn)
        db.flush()
        session.turns = turn.seq
        session.turn_started_at = now
        session.turn_ended_at = None
        session.error = None
        session.current_line = None
        held = held_reason(
            paused=project.paused,
            kind_code=session.kind_code,
            unreachable=self._outage.holds,
        )
        if held is None:
            session.state_code = SessionState.STARTING
            self._begin(db, session)
        else:
            session.state_code = SessionState.HELD
            after_commit(_HeldWritten(self))
        self._moved(session, state=True)
        logger.info(
            "Session %s resumed%s",
            session_id,
            "" if held is None else f", held: {held}",
        )
        return session

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

    def _stop(
        self, db: Session, session: AgentSession, person: User, at: datetime
    ) -> None:
        """Under the Session's lock: `stopped` by `person` at `at`, with no
        current line (F67.1, F69.2). A turn in flight stays so, for its relay to
        record to the end the controller's interrupt gives it once this
        commits; a start held or under way has its Turn ended unsent, and its
        loop sends nothing more. The environment's shutdown timer is armed if
        nothing else runs or starts there."""
        before = session.state_code
        session.state_code = SessionState.STOPPED
        session.stopped_at = at
        session.stopped_by_user_id = person.id
        session.current_line = None
        if before == SessionState.RUNNING:
            self._relays.request_interrupt(session.id)
        else:
            turn = _latest_turn(db, session.id)
            turn.ended_at = at
            session.turn_ended_at = at
        self._environments.arm_shutdown_timer(db, session.environment_id)
        self._moved(session, state=True)
        logger.info("Session %s stopped by %s, %s", session.id, person.handle, before)

    def _lost_reason(self, env_id: str, name: str) -> str | None:
        """Why the controller session takes no turn: gone, ended, or its
        environment not running; None when it takes one.

        Raises:
            ExternalServiceException: The controller failed otherwise
        """
        try:
            snapshot = self._client().get_session(env_id, name)
        except ControllerProblem as problem:
            if problem.problem_type not in (
                ControllerProblemType.NOT_FOUND,
                ControllerProblemType.CONFLICT,
            ):
                raise
            return str(problem)
        if snapshot.status in _DONE_STATUSES:
            return f"controller session {name} is {snapshot.status}"
        return None

    def _lost(
        self, db: Session, session_id: uuid.UUID, gone: str, reason: str
    ) -> _Pending | None:
        """Under the Session's lock, while it is `starting` on the controller
        session `gone`: a `server` record saying it is gone, the Session left
        with none, and the phase that starts its environment; the start as its
        rows then have it. None when it has moved on."""
        records = self._records(db)
        session = records.lock_session(session_id)
        if (
            session.state_code != SessionState.STARTING
            or session.controller_session != gone
        ):
            return None
        records.append(
            session_id,
            RecordKind.SERVER,
            payload={"type": SESSION_GONE, "reason": reason},
        )
        session.controller_session = None
        environment = db.get_one(Environment, session.environment_id)
        self._phase(db, session_id, f"Starting {environment.name}…")
        logger.info(
            "Session %s resumes in a new controller session: %s", session_id, reason
        )
        return _pending(db, session_id)

    def _resumed(self, db: Session, session_id: uuid.UUID, turn: Turn) -> None:
        """A Resume's Turn sent: the Session's run counts from it, as "running
        N min" reads it."""
        session = self._records(db).lock_session(session_id)
        if session.state_code == SessionState.RUNNING:
            session.started_at = turn.started_at
            self._moved(session)

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
        """The Session `failed` with `reason`, the Turn its start sends ended,
        and a `server` record saying so unless that Turn's failed send
        `recorded` one. Then the environment's shutdown timer is armed, if it
        is Pilot's to stop and nothing else runs or starts there. A Session no
        longer `starting` is left as it is."""
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
        turn = _latest_turn(db, session_id)
        if turn.ended_at is None:
            turn.ended_at = datetime.now(UTC)
        session.turn_ended_at = turn.ended_at
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
    turn = _latest_turn(db, session_id)
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
        turn_id=turn.id,
        resuming=turn.seq > 1,
    )


def _latest_turn(db: Session, session_id: uuid.UUID) -> Turn:
    """The Session's latest Turn: the one its start or its Resume sends while
    it is `held` or `starting`, and the one a Resume follows."""
    return db.scalars(
        select(Turn)
        .where(Turn.session_id == session_id)
        .order_by(Turn.seq.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    ).one()


def _shared(db: Session, project_id: uuid.UUID) -> Project:
    """The project, its row under a share lock until the transaction ends, so
    no change of its standing interleaves, read as the lock found it.

    Raises:
        RecordNotFoundException: No Project has the id
    """
    project = db.scalars(
        select(Project)
        .where(Project.id == project_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if project is None:
        raise RecordNotFoundException("Project", str(project_id))
    return project


def _closed(project: Project) -> str | None:
    """Why nothing of the project starts: finished or archived (F5.1,
    F128.1); None while it may."""
    if project.archived:
        return "its project is archived"
    if project.state_code is ProjectState.FINISHED:
        return "its project is finished"
    return None
