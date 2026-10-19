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
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, Any

from prometheus_client import Counter, Gauge
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core_exceptions import ExternalServiceException
from app.database import scoped_session
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import Session as AgentSession
from app.models import Turn
from app.models.reference import RecordKind, SessionState
from app.services.controller_client import ControllerClient, RawFrame, ResultFrame
from app.services.current_line import CurrentLine, after_line, after_partial, at_send
from app.services.environment_service import EnvironmentService
from app.services.session_record_service import (
    SessionRecordService,
    stream_position,
)
from app.services.session_stream_service import SessionStreamService
from app.services.supervisor import LoopHandle, Supervisor
from app.utils.after_commit import after_commit

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

RELAY_JOB = "relay"

SEND_FAILED = "send-failed"
"""The `type` of the `server` record a send that failed before its `202` writes."""

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
    offset: int
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
        """Register the `relay` job, whose loops are one per Session.

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
        supervisor.register_job(RELAY_JOB, needs_controller=True)

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

        Returns:
            The Turn; one whose send failed has its `error`

        Raises:
            RecordNotFoundException: No Session has the id
            InvalidOperationException: The Session has no controller session
        """
        session = self._records(db).require_session(session_id)
        try:
            self._deliver(session, message)
        except ExternalServiceException as error:
            turn = self._new_turn(db, session_id, message, author_user_id)
            self._failed(db, turn, error)
            return turn
        turn = self._new_turn(db, session_id, message, author_user_id)
        self._accepted(db, turn)
        return turn

    def send_turn(self, db: Session, turn_id: int) -> Turn:
        """Send a Turn written before its send, as the session start writes its
        brief (§9.6), and relay it once the caller's transaction commits. As
        `send`, with the Turn's `started_at` moved to the send.

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
        try:
            self._deliver(session, turn.message)
        except ExternalServiceException as error:
            self._failed(db, turn, error)
            return turn
        self._accepted(db, turn)
        return turn

    def relay(self, session_id: uuid.UUID, handle: LoopHandle) -> None:
        """The relay loop's run: the Session's turn in flight relayed from the
        controller session's last recorded offset to its `result` frame.
        Returns at once when no turn is in flight, and when the loop is told to
        stop.

        Raises:
            ExternalServiceException: The stream could not be opened, or dropped
                before the turn's `result`
        """
        with scoped_session(self._container) as db:
            opening = _opening(db, session_id)
        if opening is None:
            return
        RELAYS_RUNNING.inc()
        try:
            self._relay_turn(opening, handle)
        finally:
            RELAYS_RUNNING.dec()

    def _start_relay(self, session_id: uuid.UUID) -> None:
        # A relay past its turn's last action still counts as live: `again`
        # has it run once more, which relays this turn.
        self._supervisor.start_loop(
            RELAY_JOB, partial(self.relay, session_id), key=str(session_id), again=True
        )

    def _deliver(self, session: AgentSession, message: str) -> None:
        if session.controller_session is None:
            raise InvalidOperationException(
                f"send a turn to session {session.id}", "it has no controller session"
            )
        self._client().send_message(
            session.environment_id, session.controller_session, message
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

    def _relay_turn(self, opening: _Opening, handle: LoopHandle) -> None:
        progress = _Progress(opening.offset, opening.current_line)
        stream = self._client().open_response_stream(
            opening.env_id, opening.controller_session, opening.offset
        )
        with stream, handle.holding(stream):
            for frame in stream:
                if isinstance(frame, RawFrame):
                    self._line(opening, frame, progress)
                elif isinstance(frame, ResultFrame):
                    self._end_turn(opening, frame, progress.offset)
                    return

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
        engine's turn end. After the commit, the environment's shutdown timer
        is armed if nothing runs there.

        A later Turn in flight is a send the controller accepted once this
        turn's result was out, committed first: the Session stays `running`
        for it, its current line that send's."""
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
                turn.ended_at = datetime.now(UTC)
                if frame.is_error:
                    turn.error = frame.result or _TURN_FAILED
                following = _turn_in_flight(db, opening.session_id)
                if following is None:
                    _refresh_turns(db, session, turn)
                    session.state_code = (
                        SessionState.STOPPED if frame.interrupted else SessionState.IDLE
                    )
                    session.current_line = None
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
        offset=position.raw_offset if position is not None and resumed else 0,
        current_line=session.current_line,
    )


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
