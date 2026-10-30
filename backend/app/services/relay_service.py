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
  record has, and is skipped (§9.4). A `result` line `claude` prints writes the
  Turn's tokens and cost in the same transaction (`token_counts`).
- The `result` frame, and nothing else, ends the Turn and the run.

A stream that drops, or stays silent past the client's read timeout, raises, and
the supervisor runs the loop again with backoff: it reopens at the last
committed offset.

A Session stopped under its turn (F67.1) keeps its relay to the turn's
`result`, which the controller's interrupt brings: its lines are recorded and
its state stays `stopped`, its line none. A turn the controller never got, or
whose controller session is gone, ends there with no `result`. The interrupt
runs on a loop of its own, `interrupt:<id>`, once the stop commits.

A work item's turn that ends neither interrupted nor in error makes it done
(decision 44), unless a usage halt whose setting is the cooperative stop
holds then, or its project's pause: the halt file's holders
(`HaltFileService`). Such a run stays open, `idle`, its nudge owed, a
clarification run's reply recorded; the nudge carries it on once nothing
holds it (`SessionStartService.send_nudges`), and it is done at its first
normal turn end with neither holding (F135.3, F135.6, F141.3; DB 232).
A work item's or a job's turn that ends in error with its stream showing the
quota wall (`quota_wall`) is `failed` with its nudge owed from its end, and a
job's pass puts no question to the writer then: a reading decides the wall,
and the nudges' loop the rest (the ruling on the wall).

A brain session's turn that ends with a save of its own still held (the
engine's turn end, `DocumentService.turn_ended`) gets the Session the server's
follow-up turn, naming each such path and its faults (F79; design 3 §5.1),
written in flight in the turn end's transaction and sent by the relay's next
run; a follow-up turn that itself ends so gets none. A job's work item is done
at its last turn's end, the follow-up's when it gets one. A Turn's end in a chat
closed while it ran writes the close's record after it
(`ChatCloseService.turn_ended`).

Each run first asks the controller whether it has the turn in flight (§8.2): a
Turn written before its send that the controller never got is sent then. A
controller session that is gone is resumed (§9.6, F71): re-created with the
Session's conversation in the same environment, Pilot's MCP server handed to it
with a token minted for it (`PilotServer`), and carried on by a server-own
"continue" Turn, or the ended Turn's message again when the Session has no
conversation. An environment that is not running is waited for, the running
Session's line saying it restarts while it reads `provisioning` or `starting`.
One that settles `stopped` or `deleting`, or is gone, was stopped elsewhere,
which no restart reads as: the Turn ends with a `server` record naming the
cause, and a running Session is `stopped` as Stop stops it, by no one. At
STARTUP the job's reconcile runs the relay of every Session with a Turn in
flight.
"""

import json
import logging
import re
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
from app.engine.views import ViewService
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import Environment, Project, Turn, Work
from app.models import Session as AgentSession
from app.models.reference import RecordKind, SessionState, WorkTrigger
from app.schemas.timeline import StopCause
from app.services.brief_service import is_follow_up
from app.services.chat_close_service import ChatCloseService
from app.services.controller_client import (
    ControllerClient,
    ControllerProblem,
    ControllerProblemType,
    ControllerUnreachable,
    EnvironmentWait,
    RawFrame,
    ResultFrame,
    SessionSnapshot,
)
from app.services.current_line import (
    CurrentLine,
    after_line,
    after_partial,
    at_send,
    while_starting,
)
from app.services.environment_service import EnvironmentService
from app.services.pilot_server import PilotServer
from app.services.quota_wall import turn_shows_wall
from app.services.session_record_service import (
    SessionRecordService,
    read_records,
    stream_position,
)
from app.services.session_scope import scoped_create
from app.services.session_stream_service import SessionStreamService
from app.services.start_gate import JOB_KIND, WORK_KIND, WorkSlots
from app.services.supervisor import LoopHandle, Supervisor
from app.services.token_counts import count_tokens
from app.services.turn_end_read_service import TurnEndReadService
from app.services.work_status import work_moved
from app.utils.after_commit import after_commit

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)

RELAY_JOB = "relay"

INTERRUPT_JOB = "interrupt"

SEND_FAILED = "send-failed"
"""The `type` of the `server` record a send that failed before its `202` writes."""

SESSION_GONE = "session-gone"
"""The `type` of the `server` record a resume writes: the controller session was
gone."""

RESTARTING = "restarting"
"""The `type` of the `server` record whose `text` a running Session's line
takes while its environment restarts under the turn (F71)."""

ENVIRONMENT_STOPPED = "environment-stopped"
"""The `type` of the `server` record that ends a Turn whose environment was
stopped under it, its `cause` a Stop Cause (F71)."""

CONTINUE = "continue"
"""The message of the server's own Turn that carries a resumed session on (F71)."""

SETTLE_WAIT_MS = 10_000
"""How long one wait for an environment to settle is held; a loop that is not
told to stop waits again until it settles."""

_TURN_IN_FLIGHT = ("busy", "interrupting")

_STOPS: dict[str, tuple[StopCause, str]] = {
    "stopped": (StopCause.ENVIRONMENT_STOPPED, "is stopped"),
    "deleting": (StopCause.ENVIRONMENT_DELETING, "is deleting"),
    "error": (StopCause.ENVIRONMENT_ERROR, "is in error"),
}
"""A settled status that stops a turn's Session, its Stop Cause and the words
of its reason."""

_TURN_FAILED = "The turn ended in an error"

# What jsonb refuses in a string: a NUL, and a surrogate no pair completes.
_REFUSED = re.compile(r"[\x00\ud800-\udfff]")

RELAYS_RUNNING = Gauge(
    "pilot_relays_running", "Turns in flight this process is relaying"
)
PARTIALS_FORWARDED_TOTAL = Counter(
    "pilot_partials_forwarded_total",
    "Main-thread block starts and text deltas forwarded to the Sessions' hubs",
)


@dataclass(frozen=True)
class Words:
    """A person's message: whose it is, their words verbatim with their quote
    tags (DB Turn `words`), and the Item or the Block its quote tag names."""

    author_user_id: uuid.UUID
    text: str
    quote_item_id: uuid.UUID | None = None
    quote_block_id: int | None = None


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
    stopped: bool
    """The Session was stopped under the turn: it is relayed to its end, and
    never sent."""


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


@dataclass(frozen=True)
class _InterruptStart:
    # `after_commit()` runs a callback equal to one it holds once.
    relays: "RelayService"
    session_id: uuid.UUID

    def __call__(self) -> None:
        self.relays._start_interrupt(self.session_id)


class RelayService:
    """Sends a Session its turns, relays each into its records, and interrupts
    the turn of a Session stopped under it."""

    def __init__(
        self,
        container: "ServiceContainer",
        supervisor: Supervisor,
        session_streams: SessionStreamService,
        environment_service: EnvironmentService,
        work_slots: WorkSlots,
        pilot_server: PilotServer,
        turn_end_reads: TurnEndReadService,
        chat_closes: ChatCloseService,
    ) -> None:
        """Register the `relay` job, whose loops are one per Session, and whose
        reconcile runs the relay of every Session with a Turn in flight; and the
        `interrupt` job, whose reconcile interrupts the turn of every Session
        stopped under it.

        Args:
            container: Gives each relay transaction its database session, and
                the client
            supervisor: Runs the relays, and restarts one whose stream drops
            session_streams: The hubs the partials go to, and the wakes
            environment_service: Clears and arms the environments' shutdown
                timer around a turn
            work_slots: Opened by a work item's run that ends under its turn
            pilot_server: Hands each re-create Pilot's MCP server, with a token
                minted for it
            turn_end_reads: Reads the documents a work item's run registered,
                once the turn that ends the run commits
            chat_closes: Writes a closed chat's close after its last turn's
                end
        """
        self._container = container
        self._supervisor = supervisor
        self._streams = session_streams
        self._environments = environment_service
        self._slots = work_slots
        self._pilot_server = pilot_server
        self._reads = turn_end_reads
        self._closes = chat_closes
        supervisor.register_job(
            RELAY_JOB, needs_controller=True, reconcile=self._reconcile
        )
        supervisor.register_job(
            INTERRUPT_JOB, needs_controller=True, reconcile=self._reconcile_interrupts
        )

    def send(
        self,
        db: Session,
        session_id: uuid.UUID,
        message: str,
        *,
        words: Words | None = None,
    ) -> Turn:
        """Send the Session a new Turn, `message`, and relay it once the
        caller's transaction commits (§9.6). A person's message carries their
        `words`, which `message` ends with (DB assertion 251).

        The controller's send goes first. On its `202`, under the Session's
        lock: the Turn, its `send` record when a person wrote it, the Session
        `running` with its current line set, and the environment's shutdown
        timer cleared. A send that
        fails before the `202` writes the Turn ended with its `error`, and a
        `server` record saying so (F125).

        A controller session that is gone (`404`) is re-created first (§9.6),
        and the Turn written in flight as on a `202`: the Session's relay sends
        it to the new session once the caller's transaction commits, which
        commits that session's token's hash with it, so its first tool call is
        admitted. A send refused because
        the controller has a turn in flight writes nothing; while the record
        has a Turn in flight, it starts the Session's relay when this process
        runs none (refinement D2).

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
            turn = self._new_turn(db, session_id, message, words)
            self._failed(db, turn, error)
            return turn
        turn = self._new_turn(db, session_id, message, words)
        self._accepted(db, turn)
        return turn

    def send_turn(self, db: Session, turn_id: int) -> Turn:
        """Send a `starting` Session's Turn written before its send, as the
        session start writes its brief and a Resume its own (§9.6), and relay it
        once the caller's transaction commits. As `send`, with the Turn's
        `started_at` moved to the send.

        A Turn the controller has already, sent before a cut or by another
        process (§8.2, §8.1), is not sent again; one whose send another
        process's commit made `running` first is left as it is. One a Stop
        ended while its send went out is in flight again, as the controller has
        it: its relay records it to the end the interrupt gives it.

        Returns:
            The Turn; one whose send failed has its `error`

        Raises:
            RecordNotFoundException: No Turn or Session has the id
            InvalidOperationException: The Session has no controller session
            ControllerUnreachable: The controller did not answer; nothing is
                written, and the Turn is still unsent as far as the record
                knows
        """
        turn = db.get(Turn, turn_id)
        if turn is None:
            raise RecordNotFoundException("Turn", str(turn_id))
        session = self._records(db).require_session(turn.session_id)
        name = _controller_session(session)
        recorded = _recorded_turn(db, session.id, name)
        failure: ExternalServiceException | None = None
        try:
            self._deliver_once(_environment_id(session), name, recorded, turn.message)
        except ControllerUnreachable:
            raise
        except ExternalServiceException as error:
            failure = error
        session = self._records(db).lock_session(session.id)
        if not _in_flight(db, turn.id):
            if (
                failure is None
                and session.state_code == SessionState.STOPPED
                and not _has_result(db, session.id, turn.id)
            ):
                self._stopped_under_send(db, session, turn)
            return turn
        if session.state_code == SessionState.RUNNING:
            return turn
        if failure is None:
            self._accepted(db, turn)
        else:
            self._failed(db, turn, failure)
        return turn

    def request_interrupt(self, session_id: uuid.UUID) -> None:
        """Interrupt the turn of the Session, stopped under it, once the
        caller's transaction commits, on a loop of its own (F67.1)."""
        after_commit(_InterruptStart(self, session_id))

    def interrupt(self, session_id: uuid.UUID, handle: LoopHandle) -> None:
        """The interrupt loop's run: the controller's interrupt of the turn in
        flight of the Session, while it is `stopped` with one. A controller
        that does not answer leaves the turn to run out, the pause's
        cooperative semantics (F141.3); a controller session or an environment
        that is gone has no turn to interrupt.

        Raises:
            ExternalServiceException: The controller failed otherwise
        """
        with scoped_session(self._container) as db:
            session = db.get_one(AgentSession, session_id)
            if (
                session.state_code != SessionState.STOPPED
                or session.controller_session is None
                or _turn_in_flight(db, session_id) is None
            ):
                return
            env_id, name = _environment_id(session), session.controller_session
        try:
            self._client().interrupt(env_id, name)
        except ControllerUnreachable as error:
            logger.warning(
                "Session %s stopped; its turn runs out, the controller unreachable: %s",
                session_id,
                error,
            )
            return
        except ControllerProblem as problem:
            if problem.problem_type not in (
                ControllerProblemType.NOT_FOUND,
                ControllerProblemType.CONFLICT,
            ):
                raise
            logger.info(
                "Session %s stopped with no turn to interrupt: %s", session_id, problem
            )
            return
        logger.info("Session %s stopped: its turn interrupted", session_id)

    def relay(self, session_id: uuid.UUID, handle: LoopHandle) -> None:
        """The relay loop's run: the Session's turn in flight relayed from the
        controller session's last recorded offset to its `result` frame.
        Returns at once when no turn is in flight, and when the loop is told to
        stop.

        The turn in flight is sent first when the controller does not have it.
        A controller session that is gone is resumed, and an environment that
        is not running is waited for until it settles; then the run carries on
        with the Session as its rows have it. An environment stopped
        elsewhere, in error, or gone, ends the turn and stops the Session. A
        stream the watchdog closes (`Supervisor.interrupt_loop`) is reopened. A
        Session stopped under its turn is never sent it: the turn is relayed
        when the controller has it, and ends with no `result` when the
        controller never got it or its controller session is gone.

        Raises:
            ExternalServiceException: The controller failed, or the stream
                dropped before the turn's `result`
        """
        while not handle.stopping:
            with scoped_session(self._container) as db:
                opening = _opening(db, session_id)
            if opening is None:
                return
            try:
                if opening.stopped:
                    snapshot = self._client().get_session(
                        opening.env_id, opening.controller_session
                    )
                    if not _has_turn(snapshot, opening.recorded_turn):
                        self._end_stopped(opening, None)
                        return
                else:
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
                    case ControllerProblemType.NOT_FOUND if opening.stopped:
                        self._end_stopped(opening, problem)
                        return
                    case ControllerProblemType.NOT_FOUND:
                        self._resume(opening, problem)
                    case ControllerProblemType.CONFLICT:
                        self._await_environment(opening, handle)
                    case _:
                        raise

    def _reconcile(self, db: Session) -> None:
        """At STARTUP: run the relay of every Session `running` or `stopped`
        with a Turn in flight (§8.2). Its run decides from the controller's
        state whether to relay the turn, send it first, or end it."""
        for session_id in _with_turn_in_flight(db, _RELAYED):
            logger.info("Resuming the relay of session %s", session_id)
            self._supervisor.start_loop(
                RELAY_JOB, partial(self.relay, session_id), key=str(session_id)
            )

    def _reconcile_interrupts(self, db: Session) -> None:
        """At STARTUP: interrupt the turn of every Session stopped under it,
        whose interrupt a restart may have cut."""
        for session_id in _with_turn_in_flight(db, (SessionState.STOPPED,)):
            self._start_interrupt(session_id)

    def _start_interrupt(self, session_id: uuid.UUID) -> None:
        self._supervisor.start_loop(
            INTERRUPT_JOB,
            partial(self.interrupt, session_id),
            key=str(session_id),
            again=True,
        )

    def _start_relay(self, session_id: uuid.UUID) -> None:
        # A relay past its turn's last action still counts as live: `again`
        # has it run once more, which relays this turn.
        self._supervisor.start_loop(
            RELAY_JOB, partial(self.relay, session_id), key=str(session_id), again=True
        )

    def _deliver(self, session: AgentSession, message: str) -> None:
        self._client().send_message(
            _environment_id(session), _controller_session(session), message
        )

    def _deliver_resuming(
        self, db: Session, session: AgentSession, message: str
    ) -> None:
        """Send `message`; a controller session that is gone is re-created
        under the Session's lock, and the message left to the relay, unless
        another process re-created it first, whose session it goes to (§9.6).
        A session busy with a turn has the send refused, and the Session's
        relay started if this process runs none."""
        try:
            self._deliver(session, message)
        except ControllerProblem as problem:
            match problem.problem_type:
                case ControllerProblemType.SESSION_BUSY:
                    if _turn_in_flight(db, session.id) is not None:
                        self._supervisor.start_loop(
                            RELAY_JOB,
                            partial(self.relay, session.id),
                            key=str(session.id),
                        )
                    raise InvalidOperationException(
                        f"send a turn to session {session.id}", "a turn is in flight"
                    ) from problem
                case ControllerProblemType.NOT_FOUND:
                    gone = session.controller_session
                    session = self._records(db).lock_session(session.id)
                    if session.controller_session == gone:
                        self._recreate(db, session, problem)
                    else:
                        self._deliver(session, message)
                case _:
                    raise

    def _deliver_once(
        self, env_id: str, name: str, recorded_turn: int, message: str
    ) -> None:
        """Send a Turn written before its send, unless the controller has it
        already (§8.2): its session busy, or past the turn the record last
        ended in it. A send refused as busy while the controller has the turn
        is one another process made first. On return the controller has the
        turn."""
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
        is re-created, and a server-own Turn, which the run sends next, carries
        the Session on: "continue", or the ended Turn's message while no Turn
        of the Session went out — it has no conversation yet, or a
        continuation's from its placement — which the new session would not
        know. An environment the create does not find is gone, and stops the
        Session. Nothing is done when another process resumed it first, or the
        Session has moved on."""
        with scoped_session(self._container) as db:
            session = self._records(db).lock_session(opening.session_id)
            if (
                session.state_code != SessionState.RUNNING
                or session.controller_session != opening.controller_session
            ):
                return
            try:
                self._recreate(db, session, problem)
            except ControllerProblem as missing:
                # The create's one `404` is its environment's.
                if missing.problem_type is not ControllerProblemType.NOT_FOUND:
                    raise
                self._stop_elsewhere(
                    db,
                    session,
                    opening.turn_id,
                    StopCause.ENVIRONMENT_GONE,
                    str(missing),
                )
                return
            message = (
                opening.message
                if session.conversation_id is None
                or stream_position(db, session.id) is None
                else CONTINUE
            )
            turn = self._new_turn(db, session.id, message, None)
            session.state_code = SessionState.RUNNING
            session.current_line = at_send(None, turn.started_at)
            _refresh_turns(db, session, turn)
            self._moved(session)

    def _recreate(
        self, db: Session, session: AgentSession, problem: ControllerProblem
    ) -> None:
        """Under the Session's lock: a `server` record outside any Turn saying
        the controller session is gone, every Turn in flight ended with no
        `result`, the session re-created as every create of it is
        (`scoped_create`), resuming the Session's conversation in its
        environment, Pilot's MCP server handed to it with a token minted for
        it, and `controller_session` and `token_hash`
        overwritten (§9.6; decision 9). A `running` Session is left `idle`, for
        its caller's next Turn.

        Raises:
            ExternalServiceException: The create failed, and nothing is written
        """
        gone = session.controller_session
        injected = self._pilot_server.inject(scoped_create(db, session))
        created = self._client().create_headless_session(
            _environment_id(session), injected.request
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
        session.token_hash = injected.token_hash
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
            self._moved(session, state=True)
        db.flush()
        logger.info(
            "Session %s lost controller session %s; resumed as %s in environment %s",
            session.id,
            gone,
            created.name,
            session.environment_id,
        )

    def _await_environment(self, opening: _Opening, handle: LoopHandle) -> None:
        """Wait until the turn's environment settles `running` (§9.6), or the
        loop is told to stop. While it reads `provisioning` or `starting`, as a
        restart reads, the running Session's line says it restarts. One that
        settles `stopped`, `deleting` or `error`, or is gone, was stopped
        elsewhere: the turn ends there, and the Session stops. A Resume starts
        one in `error` again, KubeCoder's way out of it."""
        env_id = opening.env_id
        logger.info("Environment %s is not running: waiting for it to settle", env_id)
        # The first read answers at once, so the line says so from the start.
        wait: EnvironmentWait | None = None
        while not handle.stopping:
            try:
                environment = self._client().get_environment(
                    env_id, wait=wait, wait_ms=SETTLE_WAIT_MS
                )
            except ControllerProblem as problem:
                if problem.problem_type is not ControllerProblemType.NOT_FOUND:
                    raise
                self._stopped_elsewhere(
                    opening, StopCause.ENVIRONMENT_GONE, str(problem)
                )
                return
            wait = "settled"
            match environment.status:
                case "running":
                    return
                case "stopped" | "deleting" | "error":
                    cause, state = _STOPS[environment.status]
                    self._stopped_elsewhere(
                        opening, cause, f"environment {env_id} {state}"
                    )
                    return
                case "provisioning" | "starting":
                    self._restarting(opening)
                case "stopping":
                    pass

    def _restarting(self, opening: _Opening) -> None:
        """The running Session's line, and a `server` record of the Turn in
        flight, saying its environment restarts (F71, F26.2), once: the
        session's next line moves it on, as does the resume. Nothing is done
        when the Session has moved on."""
        with scoped_session(self._container) as db:
            records = self._records(db)
            session = records.lock_session(opening.session_id)
            if (
                session.state_code != SessionState.RUNNING
                or session.controller_session != opening.controller_session
                or not _in_flight(db, opening.turn_id)
            ):
                return
            environment = db.get_one(Environment, session.environment_id)
            text = f"{environment.name} is restarting…"
            line = session.current_line
            if line is not None and line.get("text") == text:
                return
            record = records.append(
                session.id,
                RecordKind.SERVER,
                payload={"type": RESTARTING, "text": text},
                turn_id=opening.turn_id,
            )
            session.current_line = while_starting(text, record.at)
            self._moved(session)

    def _stopped_elsewhere(
        self, opening: _Opening, cause: StopCause, reason: str
    ) -> None:
        """`_stop_elsewhere` in a transaction of its own, unless the Session
        has moved on: it is neither running nor stopped, has another
        controller session, or its turn ended."""
        with scoped_session(self._container) as db:
            session = self._records(db).lock_session(opening.session_id)
            if (
                session.state_code not in _RELAYED
                or session.controller_session != opening.controller_session
                or not _in_flight(db, opening.turn_id)
            ):
                return
            self._stop_elsewhere(db, session, opening.turn_id, cause, reason)

    def _stop_elsewhere(
        self,
        db: Session,
        session: AgentSession,
        turn_id: int,
        cause: StopCause,
        reason: str,
    ) -> None:
        """Under the Session's lock: its environment stopped under the Turn in
        flight `turn_id`, a stop made elsewhere (§9.6, F71). A `server` record
        naming the `cause` is the Turn's last, every Turn in flight ends with
        no `result`, and a `running` Session is `stopped` as Stop stops it, by
        no one, with no current line; one stopped already keeps its stop. The
        documents it was writing are let go, as at a turn's end, and the
        environment's shutdown timer is armed. A work item's slot opens once
        this commits."""
        self._records(db).append(
            session.id,
            RecordKind.SERVER,
            payload={"type": ENVIRONMENT_STOPPED, "cause": cause, "reason": reason},
            turn_id=turn_id,
        )
        now = datetime.now(UTC)
        for turn in db.scalars(
            select(Turn).where(Turn.session_id == session.id, Turn.ended_at.is_(None))
        ):
            turn.ended_at = now
        _refresh_turns(db, session, db.get_one(Turn, turn_id))
        if session.state_code == SessionState.RUNNING:
            session.state_code = SessionState.STOPPED
            session.stopped_at = now
            session.stopped_by_user_id = None
            session.current_line = None
            self._moved(session, state=True)
            self._slots.left(session, SessionState.RUNNING)
        self._container.document_service().turn_ended(session)
        self._closes.turn_ended(db, session)
        self._environments.arm_shutdown_timer(db, _environment_id(session))
        logger.info("Session %s stopped under its turn: %s", session.id, reason)

    def _new_turn(
        self,
        db: Session,
        session_id: uuid.UUID,
        message: str,
        words: Words | None,
    ) -> Turn:
        records = self._records(db)
        records.lock_session(session_id)
        last = db.scalar(
            select(func.max(Turn.seq)).where(Turn.session_id == session_id)
        )
        turn = Turn(
            session_id=session_id,
            seq=(last or 0) + 1,
            message=message,
            started_at=datetime.now(UTC),
        )
        if words is not None:
            turn.author_user_id = words.author_user_id
            turn.words = words.text
            turn.quote_item_id = words.quote_item_id
            turn.quote_block_id = words.quote_block_id
        db.add(turn)
        db.flush()
        if words is not None:
            records.append(session_id, RecordKind.SEND, turn_id=turn.id)
        return turn

    def _accepted(self, db: Session, turn: Turn) -> None:
        session = self._records(db).lock_session(turn.session_id)
        turn.started_at = datetime.now(UTC)
        moved_state = session.state_code != SessionState.RUNNING
        session.state_code = SessionState.RUNNING
        session.current_line = at_send(session.current_line, turn.started_at)
        _refresh_turns(db, session, turn)
        self._moved(session, state=moved_state)
        self._environments.clear_shutdown_timer(db, _environment_id(session))
        after_commit(_RelayStart(self, session.id))

    def _failed(self, db: Session, turn: Turn, error: ExternalServiceException) -> None:
        records = self._records(db)
        session = records.lock_session(turn.session_id)
        turn.ended_at = datetime.now(UTC)
        turn.error = str(error)
        records.append(
            session.id,
            RecordKind.SERVER,
            payload={"type": SEND_FAILED, "reason": str(error)},
            turn_id=turn.id,
        )
        _refresh_turns(db, session, turn)

    def _stopped_under_send(
        self, db: Session, session: AgentSession, turn: Turn
    ) -> None:
        """Under the Session's lock: the Turn a Stop ended while its send went
        out in flight again, since the controller has it, its relay started
        and the turn interrupted once the transaction commits."""
        turn.ended_at = None
        _refresh_turns(db, session, turn)
        after_commit(_RelayStart(self, session.id))
        self.request_interrupt(session.id)
        logger.info(
            "Session %s was stopped while its turn's send went out: interrupting it",
            session.id,
        )

    def _end_stopped(
        self, opening: _Opening, problem: ControllerProblem | None
    ) -> None:
        """A stopped Session's turn in flight ended with no `result`: one the
        controller never got, or, with `problem`, whose controller session is
        gone, a `server` record saying so (§9.6). The documents it was writing
        are let go, as at a turn's end. Nothing is done when the Session has
        moved on."""
        with scoped_session(self._container) as db:
            records = self._records(db)
            session = records.lock_session(opening.session_id)
            if (
                session.state_code != SessionState.STOPPED
                or session.controller_session != opening.controller_session
                or not _in_flight(db, opening.turn_id)
            ):
                return
            if problem is not None:
                records.append(
                    session.id,
                    RecordKind.SERVER,
                    payload={"type": SESSION_GONE, "reason": str(problem)},
                )
            turn = db.get_one(Turn, opening.turn_id)
            turn.ended_at = datetime.now(UTC)
            _refresh_turns(db, session, turn)
            self._moved(session)
            self._container.document_service().turn_ended(session)
            self._closes.turn_ended(db, session)
            self._environments.arm_shutdown_timer(db, _environment_id(session))

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
        count_tokens(db, opening.turn_id, payload)
        if session.state_code == SessionState.RUNNING:
            line = after_line(session.current_line, payload, record.at)
            if line != session.current_line:
                session.current_line = line
                self._moved(session)
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
        transaction of its own only when it changes; a stopped Session has
        none."""
        at = datetime.now(UTC)
        if opening.stopped or after_partial(progress.current_line, line, at) is None:
            return
        with scoped_session(self._container) as db:
            session = self._records(db).lock_session(opening.session_id)
            if session.state_code == SessionState.RUNNING and _in_flight(
                db, opening.turn_id
            ):
                moved = after_partial(session.current_line, line, at)
                if moved is not None:
                    session.current_line = moved
                    self._moved(session)
            progress.current_line = session.current_line

    def _end_turn(self, opening: _Opening, frame: ResultFrame, offset: int) -> None:
        """The Turn's end, in one transaction (§9.2): the `result` record at the
        offset of the stream's last raw frame, the Turn ended, the Session
        `idle` (`stopped` when interrupted, by no one) with no current line,
        and the engine's turn end. A work item's Session whose turn ended in
        error is `failed` instead, the error the Turn's (F125), and one that
        ended neither interrupted nor in error makes the work item done
        (decision 44), or, under a cooperative usage halt or its project's
        pause, leaves it open with its nudge owed (`_ended`). A Session
        stopped under the turn stays as its stop left it. A brain session left `idle` with a save of its own still held
        stays `running` with the follow-up turn (`_follow_up`), a job's work
        item done at that turn's end, not this one's. A worker's done run
        that registered nothing has the job after its turn placed here
        (`TurnEndReadService.run_ended`), and a pass that asked its writer its
        clarification run (`ClarificationService.pass_ended`): a worker's and
        a pass's turn end lock their project's row before their Session's,
        the start's lock order. After the
        commit, a work item's slot opens, the documents its done run
        registered are read, and the environment's shutdown timer is armed if
        nothing runs there.

        A later Turn in flight is a send the controller accepted once this
        turn's result was out, committed first: the Session stays `running`
        for it, its current line that send's. An earlier Turn still open lost
        its `result` to this turn's send, as the controller holds a turn's
        result only until the next send: it ends here, with no `result`
        record."""
        with scoped_session(self._container) as db:
            records = self._records(db)
            _lock_placing_project(db, opening.session_id)
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
                before = session.state_code
                held = self._container.document_service().turn_ended(session)
                follows_up = bool(held) and _follows_up(session, turn)
                if following is None:
                    _refresh_turns(db, session, turn)
                    if before != SessionState.STOPPED:
                        self._ended(db, session, turn, frame, ended_at, follows_up)
                    session.current_line = None
                else:
                    session.current_line = at_send(None, following.started_at)
                if follows_up and session.state_code == SessionState.IDLE:
                    self._follow_up(db, session, held)
                self._moved(session, state=session.state_code != before)
                self._slots.left(session, before)
                self._closes.turn_ended(db, session)
        if not ended:
            # Another process's relay ended the turn.
            self._streams.wake(opening.session_id)
            return
        with scoped_session(self._container) as db:
            self._environments.arm_shutdown_timer(db, opening.env_id)

    def _ended(
        self,
        db: Session,
        session: AgentSession,
        turn: Turn,
        frame: ResultFrame,
        at: datetime,
        follows_up: bool,
    ) -> None:
        """The Session's state at its `turn`'s end with no later Turn in
        flight: `stopped` when interrupted, by no one, `failed` for a work
        item's turn ended in error, else `idle`, its work item done (§9.2; DB
        Session State; decision 44) unless the follow-up turn `follows_up`: a
        job's is done at its last turn's end (design 3 §5.1). A worker's done
        run has its documents read, the job after its turn following them,
        and a clarification run's reply recorded; a pass's last turn ended
        `idle` or `failed` puts the questions it asked to the writer (DB 254,
        255). A worker's run whose turn ends `idle` while the halt file is
        wanted for it, a cooperative usage halt holding or its project
        paused, is not done: its nudge is owed, and a clarification run's
        reply is recorded now, as the turn's final text (DB 232, 255). One
        `failed` whose turn's stream shows the quota wall has its nudge owed,
        a pass asking nothing yet: it is not at its end (the ruling on the
        wall)."""
        work = db.get(Work, session.id) is not None
        if frame.interrupted:
            session.state_code = SessionState.STOPPED
            session.stopped_at = at
            session.stopped_by_user_id = None
        elif work and frame.is_error:
            session.state_code = SessionState.FAILED
            if turn_shows_wall(db, session.id, turn.id):
                session.nudge_owed_at = at
                logger.info(
                    "Session %s ended its turn at the quota wall, its nudge owed "
                    "once a reading confirms it",
                    session.id,
                )
            elif session.kind_code == JOB_KIND:
                self._container.clarification_service().pass_ended(session)
        else:
            session.state_code = SessionState.IDLE
            if work and not follows_up:
                clarifications = self._container.clarification_service()
                if session.kind_code == WORK_KIND and self._halted(db, session):
                    session.nudge_owed_at = at
                    clarifications.replied(session, frame.result, at)
                    logger.info(
                        "Session %s ended its turn halted or paused, its nudge owed",
                        session.id,
                    )
                    return
                self._container.record_service().work_done(session.id, at)
                if session.kind_code == WORK_KIND:
                    clarifications.replied(session, frame.result, at)
                    self._reads.run_ended(db, session)
                else:
                    clarifications.pass_ended(session)

    def _halted(self, db: Session, session: AgentSession) -> bool:
        """Whether the halt file is wanted for the worker's Session now: a
        usage halt whose setting is the cooperative stop holds, or its
        project, whose row the turn's end holds, is paused (F135.6,
        F141.3)."""
        return db.get_one(
            Project, session.project_id
        ).paused or self._container.halt_file_service().halting(db)

    def _follow_up(self, db: Session, session: AgentSession, held: list[str]) -> None:
        """Under the Session's lock, its turn ended `idle` with its saves of
        `held` still held: the server's follow-up turn in flight, no author,
        naming them (`BriefService.follow_up`), the Session `running` with it,
        and its relay run again once this commits to send it (F79)."""
        message = self._container.brief_service().follow_up(held)
        turn = self._new_turn(db, session.id, message, None)
        session.state_code = SessionState.RUNNING
        session.current_line = at_send(None, turn.started_at)
        _refresh_turns(db, session, turn)
        after_commit(_RelayStart(self, session.id))
        logger.info(
            "Session %s gets the follow-up turn: %s held", session.id, ", ".join(held)
        )

    def _moved(self, session: AgentSession, *, state: bool = False) -> None:
        work_moved(self._container.engine_bus(), session, state=state)

    def _records(self, db: Session) -> SessionRecordService:
        return SessionRecordService(
            db, self._streams, ViewService(db, self._container.engine_bus())
        )

    def _client(self) -> ControllerClient:
        client: ControllerClient = self._container.controller_client()
        return client


_RELAYED = (SessionState.RUNNING, SessionState.STOPPED)
"""The states in which a Session's turn in flight is relayed."""


def _lock_placing_project(db: Session, session_id: uuid.UUID) -> None:
    """The project's row of a Session whose turn's end may place a work item,
    locked until the transaction ends and read as the lock found it: a
    worker's, whose done run places the job after its turn, and a pass's, the
    job after a worker's turn, whose end places its clarification run; any
    other Session's is not locked."""
    session = db.get_one(AgentSession, session_id)
    if session.kind_code == WORK_KIND or (
        db.scalar(select(Work.trigger_code).where(Work.id == session_id))
        is WorkTrigger.WORKER_TURN_ENDED
    ):
        db.scalars(
            select(Project)
            .where(Project.id == session.project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()


def _opening(db: Session, session_id: uuid.UUID) -> _Opening | None:
    """The Session's turn in flight and where its stream resumes; None when the
    Session is neither `running` nor stopped under its turn."""
    session = db.get_one(AgentSession, session_id)
    if session.state_code not in _RELAYED or session.controller_session is None:
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
        env_id=_environment_id(session),
        controller_session=session.controller_session,
        turn_id=turn.id,
        message=turn.message,
        offset=position.raw_offset if position is not None and resumed else 0,
        recorded_turn=_recorded_turn(db, session_id, session.controller_session),
        current_line=session.current_line,
        stopped=session.state_code == SessionState.STOPPED,
    )


def _with_turn_in_flight(
    db: Session, states: tuple[SessionState, ...]
) -> list[uuid.UUID]:
    """The Sessions in one of `states` with a Turn in flight, by id."""
    in_flight = exists().where(
        Turn.session_id == AgentSession.id, Turn.ended_at.is_(None)
    )
    return list(
        db.scalars(
            select(AgentSession.id)
            .where(AgentSession.state_code.in_(states), in_flight)
            .order_by(AgentSession.id)
        )
    )


def _follows_up(session: AgentSession, turn: Turn) -> bool:
    """Whether a brain session's turn `turn`, ended with a save of its own
    still held, gets the follow-up turn once it leaves the Session `idle`:
    it is no follow-up itself (one per turn, D065)."""
    return session.kind_code != WORK_KIND and not is_follow_up(turn)


def _environment_id(session: AgentSession) -> str:
    # The relay serves a Session its start placed in an Environment.
    assert session.environment_id is not None
    return session.environment_id


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


def _has_result(db: Session, session_id: uuid.UUID, turn_id: int) -> bool:
    """Whether a relay recorded the end of the Turn, the Session's latest:
    the Session's last `result` record is the Turn's."""
    last = next(
        iter(
            read_records(
                db, session_id, kind=RecordKind.RESULT, limit=1, newest_first=True
            )
        ),
        None,
    )
    return last is not None and last.record.turn_id == turn_id


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
    one that is not a JSON object or that jsonb refuses (a `\\u0000`, or a lone
    surrogate such as a truncated emoji's `\\ud83d`)."""
    try:
        value = json.loads(line)
    except ValueError:
        return line
    return value if isinstance(value, dict) and _storable(value) else line


def _storable(value: Any) -> bool:
    """Whether jsonb takes every string of a parsed line, its keys included."""
    if isinstance(value, str):
        return _REFUSED.search(value) is None
    if isinstance(value, dict):
        return all(_storable(key) and _storable(item) for key, item in value.items())
    if isinstance(value, list):
        return all(_storable(item) for item in value)
    return True


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
