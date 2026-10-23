"""The send and the relay: a turn sent to a controller session, relayed into its
Session's records and live to its views until the worker's `result` frame ends
it (design 2 §9, D5; D004; F40.1's records, F40.4's relay).

The send calls the controller first and writes the Turn on its `202`. After the
commit the Session's relay loop, `relay:<id>`, opens the response stream at the
controller session's last recorded offset and takes each frame in order:

- A `stream_event` line is never a record (DB assertion 218). A main-thread
  block start or text delta is forwarded to the Session's hub as a partial, and
  every other is dropped, a sub-agent's among them.
- Every other line, a blank or non-JSON one included, is a `claude` record, in
  a transaction of its own that rebuilds the Session's current line. A line at
  or below the last recorded offset of the same controller session is one the
  record has, and is skipped (§9.4).
- The `result` frame, and nothing else, ends the Turn and the run.

A stream that drops, or stays silent past the client's read timeout, raises, and
the supervisor runs the loop again with backoff: it reopens at the last
committed offset.

Each run first asks the controller whether it has the turn in flight (§8.2): a
Turn written before its send that the controller never got is sent then. A
controller session that is gone is resumed (§9.6, F71): re-created with the
Session's conversation in the same environment, and carried on by a server-own
"continue" Turn. An environment that is not running is waited for. At STARTUP
the job's reconcile runs the relay of every Session with a Turn in flight.
"""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, Any

from prometheus_client import Counter, Gauge
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core_exceptions import ExternalServiceException
from app.database import scoped_session
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import Session as AgentSession
from app.models import Turn, Work
from app.models.reference import RecordKind, SessionState
from app.services.controller_client import (
    ControllerClient,
    ControllerProblem,
    ControllerProblemType,
    HeadlessCreateRequest,
    RawFrame,
    ResultFrame,
    SessionSnapshot,
)
from app.services.current_line import CurrentLine, after_line, after_partial, at_send
from app.services.environment_service import EnvironmentService
from app.services.session_record_service import (
    SessionRecordService,
    read_records,
    stream_position,
)
from app.services.session_stream_service import SessionStreamService
from app.services.supervisor import LoopHandle, Supervisor
from app.utils.after_commit import after_commit

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)

RELAY_JOB = "relay"

SEND_FAILED = "send-failed"
"""The `type` of the `server` record a send that failed before its `202` writes."""

SESSION_GONE = "session-gone"
"""The `type` of the `server` record a resume writes: the controller session was
gone."""

CONTINUE = "continue"
"""The message of the server's own Turn that carries a resumed session on (F71)."""

SETTLE_WAIT_MS = 10_000
"""How long one wait for an environment to settle is held; a loop that is not
told to stop waits again until it settles."""

_SETTLING = ("provisioning", "starting", "stopping")
_TURN_IN_FLIGHT = ("busy", "interrupting")

_TURN_FAILED = "The turn ended in an error"

RELAYS_RUNNING = Gauge(
    "pilot_relays_running", "Turns in flight this process is relaying"
)
PARTIALS_FORWARDED_TOTAL = Counter(
    "pilot_partials_forwarded_total",
    "Main-thread block starts and text deltas forwarded to the Sessions' hubs",
)


@dataclass(frozen=True)
class _Opening:
    """The turn in flight a relay's run opens the stream for."""

    session_id: uuid.UUID
    env_id: str
    controller_session: str
    turn_id: int
    message: str
    offset: int
    recorded_turn: int
    """The controller's number of the last turn the record ended in this
    controller session; 0 before the first."""
    current_line: CurrentLine | None


@dataclass
class _Progress:
    offset: int
    """The offset after the stream's last raw frame; at first the one it opened at."""
    current_line: CurrentLine | None
    """The Session's current line as the run last wrote or read it."""


@dataclass(frozen=True)
class _RelayStart:
    # `after_commit()` runs a callback equal to one it holds once.
    relays: "RelayService"
    session_id: uuid.UUID

    def __call__(self) -> None:
        self.relays._start_relay(self.session_id)


class RelayService:
    """Sends a Session its turns and relays each into its records."""

    def __init__(
        self,
        container: "ServiceContainer",
        supervisor: Supervisor,
        session_streams: SessionStreamService,
        environment_service: EnvironmentService,
    ) -> None:
        """Register the `relay` job, whose loops are one per Session, and whose
        reconcile runs the relay of every Session with a Turn in flight.

        Args:
            container: Gives each relay transaction its database session, and
                the client
            supervisor: Runs the relays, and restarts one whose stream drops
            session_streams: The hubs the partials go to, and the wakes
            environment_service: Clears and arms the environments' shutdown
                timer around a turn
        """
        self._container = container
        self._supervisor = supervisor
        self._streams = session_streams
        self._environments = environment_service
        supervisor.register_job(
            RELAY_JOB, needs_controller=True, reconcile=self._reconcile
        )

    def send(
        self,
        db: Session,
        session_id: uuid.UUID,
        message: str,
        *,
        author_user_id: uuid.UUID | None = None,
    ) -> Turn:
        """Send the Session a new Turn, a person's message when it has an
        author, and relay it once the caller's transaction commits (§9.6).

        The controller's send goes first. On its `202`, under the Session's
        lock: the Turn, its `send` record when a person wrote it, the Session
        `running` with its current line set, and the environment's shutdown
        timer cleared. A send that
        fails before the `202` writes the Turn ended with its `error`, and a
        `server` record saying so (F125).

        A controller session that is gone (`404`) is resumed first, and the
        message sent to the one that replaces it (§9.6). A send refused because
        the controller has a turn in flight writes nothing, and starts the
        Session's relay when this process runs none.

        Returns:
            The Turn; one whose send failed has its `error`

        Raises:
            RecordNotFoundException: No Session has the id
            InvalidOperationException: The Session has no controller session,
                or the controller has a turn in flight (`409 session-busy`)
        """
        session = self._records(db).require_session(session_id)
        try:
            self._deliver_resuming(db, session, message)
        except ExternalServiceException as error:
            turn = self._new_turn(db, session_id, message, author_user_id)
            self._failed(db, turn, error)
            return turn
        turn = self._new_turn(db, session_id, message, author_user_id)
        self._accepted(db, turn)
        return turn

    def send_turn(self, db: Session, turn_id: int) -> Turn:
        """Send the first Turn of a `starting` Session's controller session,
        written before its send, as the session start writes its brief (§9.6),
        and relay it once the caller's transaction commits. As `send`, with the
        Turn's `started_at` moved to the send.

        A Turn the controller has already, sent before a cut or by another
        process (§8.2, §8.1), is not sent again; one whose send another
        process's commit made `running` first is left as it is.

        Returns:
            The Turn; one whose send failed has its `error`

        Raises:
            RecordNotFoundException: No Turn or Session has the id
            InvalidOperationException: The Session has no controller session
        """
        turn = db.get(Turn, turn_id)
        if turn is None:
            raise RecordNotFoundException("Turn", str(turn_id))
        session = self._records(db).require_session(turn.session_id)
        name = _controller_session(session)
        recorded = _recorded_turn(db, session.id, name)
        failure: ExternalServiceException | None = None
        try:
            self._deliver_once(session.environment_id, name, recorded, turn.message)
        except ExternalServiceException as error:
            failure = error
        session = self._records(db).lock_session(session.id)
        if not _in_flight(db, turn.id) or session.state_code == SessionState.RUNNING:
            return turn
        if failure is None:
            self._accepted(db, turn)
        else:
            self._failed(db, turn, failure)
        return turn

    def relay(self, session_id: uuid.UUID, handle: LoopHandle) -> None:
        """The relay loop's run: the Session's turn in flight relayed from the
        controller session's last recorded offset to its `result` frame.
        Returns at once when no turn is in flight, and when the loop is told to
        stop.

        The turn in flight is sent first when the controller does not have it.
        A controller session that is gone is resumed, and an environment that
        is not running is waited for until it settles; then the run carries on
        with the Session as its rows have it. A stream the watchdog closes
        (`Supervisor.interrupt_loop`) is reopened.

        Raises:
            ExternalServiceException: The controller failed, the stream dropped
                before the turn's `result`, or the environment settled other
                than `running`
        """
        while not handle.stopping:
            with scoped_session(self._container) as db:
                opening = _opening(db, session_id)
            if opening is None:
                return
            try:
                self._deliver_once(
                    opening.env_id,
                    opening.controller_session,
                    opening.recorded_turn,
                    opening.message,
                )
                if self._relay_turn(opening, handle):
                    return
            except ControllerProblem as problem:
                match problem.problem_type:
                    case ControllerProblemType.NOT_FOUND:
                        self._resume(opening, problem)
                    case ControllerProblemType.CONFLICT:
                        self._await_environment(opening.env_id, handle)
                    case _:
                        raise

    def _reconcile(self, db: Session) -> None:
        """At STARTUP: run the relay of every Session `running` with a Turn in
        flight (§8.2). Its run decides from the controller's state whether to
        relay the turn or send it first."""
        in_flight = exists().where(
            Turn.session_id == AgentSession.id, Turn.ended_at.is_(None)
        )
        for session_id in db.scalars(
            select(AgentSession.id)
            .where(AgentSession.state_code == SessionState.RUNNING, in_flight)
            .order_by(AgentSession.id)
        ):
            logger.info("Resuming the relay of session %s", session_id)
            self._supervisor.start_loop(
                RELAY_JOB, partial(self.relay, session_id), key=str(session_id)
            )

    def _start_relay(self, session_id: uuid.UUID) -> None:
        # A relay past its turn's last action still counts as live: `again`
        # has it run once more, which relays this turn.
        self._supervisor.start_loop(
            RELAY_JOB, partial(self.relay, session_id), key=str(session_id), again=True
        )

    def _deliver(self, session: AgentSession, message: str) -> None:
        self._client().send_message(
            session.environment_id, _controller_session(session), message
        )

    def _deliver_resuming(
        self, db: Session, session: AgentSession, message: str
    ) -> None:
        """Send `message`; a controller session that is gone is resumed first
        (§9.6). A session busy with a turn has the send refused, and the
        Session's relay started if this process runs none."""
        try:
            self._deliver(session, message)
        except ControllerProblem as problem:
            match problem.problem_type:
                case ControllerProblemType.SESSION_BUSY:
                    self._supervisor.start_loop(
                        RELAY_JOB, partial(self.relay, session.id), key=str(session.id)
                    )
                    raise InvalidOperationException(
                        f"send a turn to session {session.id}", "a turn is in flight"
                    ) from problem
                case ControllerProblemType.NOT_FOUND:
                    gone = session.controller_session
                    session = self._records(db).lock_session(session.id)
                    if session.controller_session == gone:
                        self._recreate(db, session, problem)
                    self._deliver(session, message)
                case _:
                    raise

    def _deliver_once(
        self, env_id: str, name: str, recorded_turn: int, message: str
    ) -> None:
        """Send a Turn written before its send, unless the controller has it
        already (§8.2): its session busy, or past the turn the record last
        ended in it. A send refused as busy while the controller has the turn
        is one another process made first."""
        client = self._client()
        if _has_turn(client.get_session(env_id, name), recorded_turn):
            return
        try:
            client.send_message(env_id, name, message)
        except ControllerProblem as problem:
            if problem.problem_type is not ControllerProblemType.SESSION_BUSY:
                raise
            if not _has_turn(client.get_session(env_id, name), recorded_turn):
                raise

    def _resume(self, opening: _Opening, problem: ControllerProblem) -> None:
        """The relay's resume of a controller session that is gone (§9.6): it
        is re-created, and a server-own "continue" Turn, which the run sends
        next, carries the Session on. Nothing is done when another process
        resumed it first, or the Session has moved on."""
        with scoped_session(self._container) as db:
            session = self._records(db).lock_session(opening.session_id)
            if (
                session.state_code != SessionState.RUNNING
                or session.controller_session != opening.controller_session
            ):
                return
            self._recreate(db, session, problem)
            turn = self._new_turn(db, session.id, CONTINUE, None)
            session.state_code = SessionState.RUNNING
            session.current_line = at_send(None, turn.started_at)
            _refresh_turns(db, session, turn)

    def _recreate(
        self, db: Session, session: AgentSession, problem: ControllerProblem
    ) -> None:
        """Under the Session's lock: a `server` record outside any Turn saying
        the controller session is gone, every Turn in flight ended with no
        `result`, the session re-created with `resume` the Session's
        conversation in its environment, and `controller_session` overwritten
        (§9.6; decision 9). A `running` Session is left `idle`, for its caller's
        next Turn.

        Raises:
            ExternalServiceException: The create failed, and nothing is written
        """
        gone = session.controller_session
        created = self._client().create_headless_session(
            session.environment_id,
            HeadlessCreateRequest(
                cwd=session.cwd,
                resume=session.conversation_id,
                agent=session.agent,
                model=session.model,
                reasoning_effort=session.reasoning_effort,
            ),
        )
        self._records(db).append(
            session.id,
            RecordKind.SERVER,
            payload={"type": SESSION_GONE, "reason": str(problem)},
        )
        now = datetime.now(UTC)
        for turn in db.scalars(
            select(Turn).where(Turn.session_id == session.id, Turn.ended_at.is_(None))
        ):
            turn.ended_at = now
        session.controller_session = created.name
        if session.state_code == SessionState.RUNNING:
            session.state_code = SessionState.IDLE
            session.current_line = None
            latest = db.scalars(
                select(Turn)
                .where(Turn.session_id == session.id)
                .order_by(Turn.seq.desc())
            ).first()
            if latest is not None:
                _refresh_turns(db, session, latest)
        db.flush()
        logger.info(
            "Session %s lost controller session %s; resumed as %s in environment %s",
            session.id,
            gone,
            created.name,
            session.environment_id,
        )

    def _await_environment(self, env_id: str, handle: LoopHandle) -> None:
        """Wait until the environment settles (§9.6), or the loop is told to
        stop.

        Raises:
            ExternalServiceException: It settled other than `running`
        """
        logger.info("Environment %s is not running: waiting for it to settle", env_id)
        while not handle.stopping:
            environment = self._client().get_environment(
                env_id, wait="settled", wait_ms=SETTLE_WAIT_MS
            )
            if environment.status == "running":
                return
            if environment.status not in _SETTLING:
                raise ExternalServiceException(
                    f"relay a turn in environment {env_id}",
                    f"the environment settled {environment.status}",
                )

    def _new_turn(
        self,
        db: Session,
        session_id: uuid.UUID,
        message: str,
        author_user_id: uuid.UUID | None,
    ) -> Turn:
        self._records(db).lock_session(session_id)
        last = db.scalar(
            select(func.max(Turn.seq)).where(Turn.session_id == session_id)
        )
        turn = Turn(
            session_id=session_id,
            seq=(last or 0) + 1,
            author_user_id=author_user_id,
            message=message,
            started_at=datetime.now(UTC),
        )
        db.add(turn)
        db.flush()
        return turn

    def _accepted(self, db: Session, turn: Turn) -> None:
        records = self._records(db)
        session = records.lock_session(turn.session_id)
        turn.started_at = datetime.now(UTC)
        if turn.author_user_id is not None:
            records.append(session.id, RecordKind.SEND, turn_id=turn.id)
        session.state_code = SessionState.RUNNING
        session.current_line = at_send(session.current_line, turn.started_at)
        _refresh_turns(db, session, turn)
        self._environments.clear_shutdown_timer(db, session.environment_id)
        after_commit(_RelayStart(self, session.id))

    def _failed(self, db: Session, turn: Turn, error: ExternalServiceException) -> None:
        records = self._records(db)
        session = records.lock_session(turn.session_id)
        turn.ended_at = datetime.now(UTC)
        turn.error = str(error)
        if turn.author_user_id is not None:
            records.append(session.id, RecordKind.SEND, turn_id=turn.id)
        records.append(
            session.id,
            RecordKind.SERVER,
            payload={"type": SEND_FAILED, "reason": str(error)},
            turn_id=turn.id,
        )
        _refresh_turns(db, session, turn)

    def _relay_turn(self, opening: _Opening, handle: LoopHandle) -> bool:
        """Relay the stream to the turn's `result`; whether it came. A stream
        closed by the loop's stop or by the watchdog ends without it."""
        progress = _Progress(opening.offset, opening.current_line)
        stream = self._client().open_response_stream(
            opening.env_id, opening.controller_session, opening.offset
        )
        RELAYS_RUNNING.inc()
        try:
            with stream, handle.holding(stream):
                for frame in stream:
                    if isinstance(frame, RawFrame):
                        self._line(opening, frame, progress)
                    elif isinstance(frame, ResultFrame):
                        self._end_turn(opening, frame, progress.offset)
                        return True
            return False
        finally:
            RELAYS_RUNNING.dec()

    def _line(self, opening: _Opening, frame: RawFrame, progress: _Progress) -> None:
        progress.offset = frame.offset
        payload = _payload(frame.line)
        if isinstance(payload, dict) and payload.get("type") == "stream_event":
            if _forwarded(payload):
                PARTIALS_FORWARDED_TOTAL.inc()
                self._streams.forward_partial(opening.session_id, payload)
                self._partial(opening, payload, progress)
            return
        with scoped_session(self._container) as db:
            recorded = self._record(db, opening, frame, payload, progress)
        if not recorded:
            # The record's own commit wakes the hub; a skipped line wakes it
            # here, for a record another process's relay committed (§9.4).
            self._streams.wake(opening.session_id)

    def _record(
        self,
        db: Session,
        opening: _Opening,
        frame: RawFrame,
        payload: Any,
        progress: _Progress,
    ) -> bool:
        records = self._records(db)
        session = records.lock_session(opening.session_id)
        position = stream_position(db, opening.session_id)
        if (
            position is not None
            and position.controller_session == opening.controller_session
            and frame.offset <= position.raw_offset
        ):
            return False
        record = records.append(
            opening.session_id,
            RecordKind.CLAUDE,
            payload=payload,
            turn_id=opening.turn_id,
            raw_offset=frame.offset,
            controller_session=opening.controller_session,
        )
        session.current_line = after_line(session.current_line, payload, record.at)
        progress.current_line = session.current_line
        if session.conversation_id is None and isinstance(payload, dict):
            # Every line `claude` prints names its conversation, which a resume
            # carries on (§9.6).
            conversation = payload.get("session_id")
            if isinstance(conversation, str) and conversation:
                session.conversation_id = conversation
        return True

    def _partial(
        self, opening: _Opening, line: dict[str, Any], progress: _Progress
    ) -> None:
        """Move the current line's state to the one the partial implies, in a
        transaction of its own only when it changes."""
        at = datetime.now(UTC)
        if after_partial(progress.current_line, line, at) is None:
            return
        with scoped_session(self._container) as db:
            session = self._records(db).lock_session(opening.session_id)
            if _in_flight(db, opening.turn_id):
                moved = after_partial(session.current_line, line, at)
                if moved is not None:
                    session.current_line = moved
            progress.current_line = session.current_line

    def _end_turn(self, opening: _Opening, frame: ResultFrame, offset: int) -> None:
        """The Turn's end, in one transaction (§9.2): the `result` record at the
        offset of the stream's last raw frame, the Turn ended, the Session
        `idle` (`stopped` when interrupted) with no current line, and the
        engine's turn end. A work item's Session whose turn ended in error is
        `failed` instead, the error the Turn's (F125), and one that ended
        neither interrupted nor in error makes the work item done (decision
        44). After the commit, the environment's shutdown timer is armed if
        nothing runs there.

        A later Turn in flight is a send the controller accepted once this
        turn's result was out, committed first: the Session stays `running`
        for it, its current line that send's. An earlier Turn still open lost
        its `result` to this turn's send, as the controller holds a turn's
        result only until the next send: it ends here, with no `result`
        record."""
        with scoped_session(self._container) as db:
            records = self._records(db)
            session = records.lock_session(opening.session_id)
            ended = _in_flight(db, opening.turn_id)
            if ended:
                records.append(
                    opening.session_id,
                    RecordKind.RESULT,
                    payload=frame.payload,
                    turn_id=opening.turn_id,
                    raw_offset=offset,
                    controller_session=opening.controller_session,
                )
                turn = db.get_one(Turn, opening.turn_id)
                ended_at = datetime.now(UTC)
                turn.ended_at = ended_at
                if frame.is_error:
                    turn.error = frame.result or _TURN_FAILED
                for earlier in db.scalars(
                    select(Turn).where(
                        Turn.session_id == opening.session_id,
                        Turn.ended_at.is_(None),
                        Turn.seq < turn.seq,
                    )
                ):
                    earlier.ended_at = ended_at
                following = _turn_in_flight(db, opening.session_id)
                if following is None:
                    _refresh_turns(db, session, turn)
                    work = db.get(Work, opening.session_id) is not None
                    session.state_code = _ended(frame, work=work)
                    session.current_line = None
                    if work and session.state_code == SessionState.IDLE:
                        self._container.record_service().work_done(
                            opening.session_id, ended_at
                        )
                else:
                    session.current_line = at_send(None, following.started_at)
                self._container.document_service().turn_ended(session)
        if not ended:
            # Another process's relay ended the turn.
            self._streams.wake(opening.session_id)
            return
        with scoped_session(self._container) as db:
            self._environments.arm_shutdown_timer(db, opening.env_id)

    def _records(self, db: Session) -> SessionRecordService:
        return SessionRecordService(db, self._streams)

    def _client(self) -> ControllerClient:
        client: ControllerClient = self._container.controller_client()
        return client


def _opening(db: Session, session_id: uuid.UUID) -> _Opening | None:
    """The Session's turn in flight and where its stream resumes; None when the
    Session is not `running`."""
    session = db.get_one(AgentSession, session_id)
    if session.state_code != SessionState.RUNNING or session.controller_session is None:
        return None
    turn = _turn_in_flight(db, session_id)
    if turn is None:
        return None
    position = stream_position(db, session_id)
    resumed = (
        position is not None
        and position.controller_session == session.controller_session
    )
    return _Opening(
        session_id=session_id,
        env_id=session.environment_id,
        controller_session=session.controller_session,
        turn_id=turn.id,
        message=turn.message,
        offset=position.raw_offset if position is not None and resumed else 0,
        recorded_turn=_recorded_turn(db, session_id, session.controller_session),
        current_line=session.current_line,
    )


def _controller_session(session: AgentSession) -> str:
    if session.controller_session is None:
        raise InvalidOperationException(
            f"send a turn to session {session.id}", "it has no controller session"
        )
    return session.controller_session


def _recorded_turn(db: Session, session_id: uuid.UUID, controller_session: str) -> int:
    """The controller's number of the turn the Session's last `result` record
    ended, when that record is of `controller_session`; else 0 (§8.2)."""
    last = next(
        iter(
            read_records(
                db, session_id, kind=RecordKind.RESULT, limit=1, newest_first=True
            )
        ),
        None,
    )
    if last is None or last.record.controller_session != controller_session:
        return 0
    turn = last.record.payload.get("turn")
    return turn if isinstance(turn, int) else 0


def _has_turn(snapshot: SessionSnapshot, recorded_turn: int) -> bool:
    """Whether the controller has had the turn in flight: its session is busy
    with it, or has ended a turn the record has not."""
    return snapshot.status in _TURN_IN_FLIGHT or (snapshot.turn or 0) > recorded_turn


def _turn_in_flight(db: Session, session_id: uuid.UUID) -> Turn | None:
    """The Session's latest Turn with no `ended_at`; a failed send's Turn,
    ended at once, may come after it."""
    return db.scalars(
        select(Turn)
        .where(Turn.session_id == session_id, Turn.ended_at.is_(None))
        .order_by(Turn.seq.desc())
    ).first()


def _in_flight(db: Session, turn_id: int) -> bool:
    """Whether the Turn has not ended, read afresh: under the Session's lock,
    which every end of a Turn takes."""
    turn = db.get_one(Turn, turn_id, populate_existing=True)
    return turn.ended_at is None


def _ended(frame: ResultFrame, *, work: bool) -> SessionState:
    """The Session's state at its turn's end with no later Turn in flight:
    `stopped` when interrupted, `failed` for a work item's turn ended in
    error, else `idle` (§9.2; DB Session State)."""
    if frame.interrupted:
        return SessionState.STOPPED
    if work and frame.is_error:
        return SessionState.FAILED
    return SessionState.IDLE


def _refresh_turns(db: Session, session: AgentSession, turn: Turn) -> None:
    """The Session's caches of its Turns: their count, and the times of the
    latest, `turn` (DB assertion 168)."""
    session.turns = (
        db.scalar(
            select(func.count()).select_from(Turn).where(Turn.session_id == session.id)
        )
        or 0
    )
    session.turn_started_at = turn.started_at
    session.turn_ended_at = turn.ended_at


def _payload(line: str) -> Any:
    """A raw line as a record holds it: its JSON object, or the line's text for
    one that is not a JSON object."""
    try:
        value = json.loads(line)
    except ValueError:
        return line
    return value if isinstance(value, dict) else line


def _forwarded(line: dict[str, Any]) -> bool:
    """Whether a `stream_event` line goes to the hub: a main-thread block's
    start or text delta (§9.2)."""
    event = line.get("event")
    if line.get("parent_tool_use_id") or not isinstance(event, dict):
        return False
    if event.get("type") == "content_block_start":
        return True
    delta = event.get("delta")
    return (
        event.get("type") == "content_block_delta"
        and isinstance(delta, dict)
        and delta.get("type") == "text_delta"
    )
