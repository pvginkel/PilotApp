"""The usage halts (design 4 §6, *The halts*; F135.1, F135.4, F135.8; DB 266):
the week's and the five-hour's, decided from the latest Usage Reading at their
limits, a window left out holding none, a five-hour limit of 0 none, a stale
window lifted one minute past its reset; when each began; and their watcher,
which tells of a turn at a recorded reading and on its timer."""

import json
from collections.abc import Generator, Iterator
from datetime import UTC, datetime, timedelta
from queue import Empty
from typing import Any

import pytest
from dependency_injector import providers
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UsageReading, User, WindowShare
from app.models.reference import UsageWindow
from app.services import usage_halts as usage_halts_module
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerUsageReading
from app.services.sse_connection_manager import SSEConnection, SSEConnectionManager
from app.services.supervisor import Supervisor
from app.services.usage_halts import TIMER, Halt, UsageHalts, UsageWatcher
from app.services.usage_service import Usage, UsageService
from tests.support.supervisor import LogWaiter, Supervise, listening, wait_until

WEEK = UsageWindow.SEVEN_DAY
FIVE_HOUR = UsageWindow.FIVE_HOUR

HALTS = UsageHalts(week_limit=0.9, five_hour_limit=0.75)

RECEIVED_AT = datetime(2026, 10, 8, 9, tzinfo=UTC)
WEEK_RESETS_AT = datetime(2026, 10, 9, 7, tzinfo=UTC)
FIVE_HOUR_RESETS_AT = datetime(2026, 10, 8, 12, tzinfo=UTC)


def _record(
    db: Session,
    *,
    week: float | None = None,
    five_hour: float | None = None,
    stale: bool = False,
    received_at: datetime = RECEIVED_AT,
    week_resets_at: datetime = WEEK_RESETS_AT,
    five_hour_resets_at: datetime = FIVE_HOUR_RESETS_AT,
) -> UsageReading:
    """A Usage Reading recorded at `received_at`, taken a minute before, with a
    Window Share for each window given a share."""
    reading = UsageReading(
        taken_at=received_at - timedelta(minutes=1),
        received_at=received_at,
        stale=stale,
    )
    db.add(reading)
    db.flush()
    for window, share, resets_at in (
        (WEEK, week, week_resets_at),
        (FIVE_HOUR, five_hour, five_hour_resets_at),
    ):
        if share is not None:
            db.add(
                WindowShare(
                    reading_id=reading.id,
                    window_code=window,
                    share=share,
                    resets_at=resets_at,
                )
            )
    db.flush()
    return reading


class _Clock:
    """`datetime` with the halts' `now()` at `at`."""

    at = RECEIVED_AT

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        return cls.at


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[_Clock]]:
    """The halts' clock, at RECEIVED_AT until a test moves it."""

    class Clock(_Clock):
        at = RECEIVED_AT

    monkeypatch.setattr(usage_halts_module, "datetime", Clock)
    yield Clock


class TestHolding:
    def test_none_holds_before_the_first_reading(self, session: Session) -> None:
        assert HALTS.holding(session) == ()
        assert HALTS.halted(session) is None
        assert HALTS.halts(session) == []

    @pytest.mark.parametrize(
        ("week", "holding"),
        [(0.8999, ()), (0.9, (WEEK,)), (1.2, (WEEK,))],
    )
    def test_the_weeks_halt_holds_at_or_over_the_first_limit(
        self, session: Session, week: float, holding: tuple[UsageWindow, ...]
    ) -> None:
        _record(session, week=week, five_hour=0.1)

        assert HALTS.holding(session) == holding

    @pytest.mark.parametrize(
        ("five_hour", "holding"),
        [(0.7499, ()), (0.75, (FIVE_HOUR,)), (1.0, (FIVE_HOUR,))],
    )
    def test_the_five_hour_halt_holds_at_or_over_its_limit(
        self, session: Session, five_hour: float, holding: tuple[UsageWindow, ...]
    ) -> None:
        _record(session, week=0.5, five_hour=five_hour)

        assert HALTS.holding(session) == holding

    def test_both_hold_the_weeks_first(self, session: Session) -> None:
        _record(session, week=0.95, five_hour=0.8)

        assert HALTS.holding(session) == (WEEK, FIVE_HOUR)
        assert HALTS.halted(session) == WEEK

    @pytest.mark.parametrize(
        ("week", "five_hour", "holding"),
        [(None, 0.8, (FIVE_HOUR,)), (0.95, None, (WEEK,)), (None, None, ())],
    )
    def test_a_window_the_reading_leaves_out_holds_no_halt(
        self,
        session: Session,
        week: float | None,
        five_hour: float | None,
        holding: tuple[UsageWindow, ...],
    ) -> None:
        _record(session, week=0.95, five_hour=0.8, received_at=RECEIVED_AT)
        _record(
            session,
            week=week,
            five_hour=five_hour,
            received_at=RECEIVED_AT + timedelta(minutes=10),
        )

        assert HALTS.holding(session) == holding

    def test_a_five_hour_limit_of_0_holds_none(self, session: Session) -> None:
        _record(session, week=0.5, five_hour=1.3)

        assert UsageHalts(week_limit=0.9, five_hour_limit=0).holding(session) == ()

    def test_a_lower_share_lifts_the_halt_a_lower_one_still_over_holds_it(
        self, session: Session
    ) -> None:
        _record(session, week=0.95, five_hour=0.8)
        _record(
            session,
            week=0.92,
            five_hour=0.2,
            received_at=RECEIVED_AT + timedelta(minutes=10),
        )
        assert HALTS.holding(session) == (WEEK,)

        _record(
            session,
            week=0.04,
            five_hour=0.2,
            received_at=RECEIVED_AT + timedelta(minutes=20),
        )

        assert HALTS.holding(session) == ()

    @pytest.mark.parametrize("window", [WEEK, FIVE_HOUR])
    @pytest.mark.parametrize(
        ("past_reset", "stale", "holds"),
        [
            (timedelta(seconds=59), True, True),
            (timedelta(minutes=1), True, False),
            (timedelta(hours=3), True, False),
            # A fresh reading decides, whatever the clock.
            (timedelta(hours=3), False, True),
        ],
    )
    def test_a_stale_window_counts_as_reset_a_minute_past_its_reset(
        self,
        session: Session,
        clock: type[_Clock],
        window: UsageWindow,
        past_reset: timedelta,
        stale: bool,
        holds: bool,
    ) -> None:
        resets_at = RECEIVED_AT + timedelta(hours=2)
        _record(
            session,
            week=0.95 if window is WEEK else 0.1,
            five_hour=0.8 if window is FIVE_HOUR else 0.1,
            stale=stale,
            week_resets_at=resets_at,
            five_hour_resets_at=resets_at,
        )

        clock.at = resets_at + past_reset

        assert HALTS.holding(session) == ((window,) if holds else ())

    def test_each_stale_window_lifts_at_its_own_reset(
        self, session: Session, clock: type[_Clock]
    ) -> None:
        _record(session, week=0.95, five_hour=0.8, stale=True)

        clock.at = FIVE_HOUR_RESETS_AT + timedelta(minutes=1)

        assert HALTS.holding(session) == (WEEK,)


class TestHalts:
    def test_a_halt_carries_its_share_its_age_and_the_receipt_its_run_began(
        self, session: Session
    ) -> None:
        _record(session, week=0.85, five_hour=0.2, received_at=RECEIVED_AT)
        began = RECEIVED_AT + timedelta(minutes=10)
        _record(session, week=0.91, five_hour=0.2, received_at=began)
        latest = _record(
            session,
            week=0.93,
            five_hour=0.8,
            received_at=RECEIVED_AT + timedelta(minutes=20),
        )

        assert HALTS.halts(session) == [
            Halt(WEEK, 0.93, began, latest.taken_at),
            Halt(FIVE_HOUR, 0.8, latest.received_at, latest.taken_at),
        ]

    def test_a_run_reaches_back_to_the_first_reading(self, session: Session) -> None:
        first = _record(session, week=0.9)
        _record(session, week=0.97, received_at=RECEIVED_AT + timedelta(minutes=10))

        assert [halt.since for halt in HALTS.halts(session)] == [first.received_at]

    def test_a_window_left_out_ends_the_run(self, session: Session) -> None:
        _record(session, week=0.95, five_hour=0.8)
        _record(session, five_hour=0.8, received_at=RECEIVED_AT + timedelta(minutes=10))
        again = _record(
            session, week=0.95, received_at=RECEIVED_AT + timedelta(minutes=20)
        )

        assert [halt.since for halt in HALTS.halts(session)] == [again.received_at]

    def test_a_reading_recorded_while_they_are_read_is_the_next_reads(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        held = _record(session, week=0.95)
        read = usage_halts_module.recorded

        def overtaken(db: Session, reading_id: int) -> Usage:
            figures = read(db, reading_id)
            _record(session, week=0.1, received_at=RECEIVED_AT + timedelta(minutes=10))
            return figures

        monkeypatch.setattr(usage_halts_module, "recorded", overtaken)

        assert HALTS.halts(session) == [
            Halt(WEEK, 0.95, held.received_at, held.taken_at)
        ]

    @pytest.mark.parametrize(
        ("next_after_reset", "since_first"),
        [(timedelta(minutes=1), False), (timedelta(seconds=59), True)],
    )
    def test_a_stale_reading_lifted_before_the_next_ends_the_run(
        self, session: Session, next_after_reset: timedelta, since_first: bool
    ) -> None:
        resets_at = RECEIVED_AT + timedelta(hours=1)
        first = _record(session, week=0.95, stale=True, week_resets_at=resets_at)
        # A fresh reading with the same figures: the week did not turn.
        latest = _record(
            session,
            week=0.95,
            received_at=resets_at + next_after_reset,
            week_resets_at=resets_at,
        )

        [halt] = HALTS.halts(session)

        assert halt.since == (first if since_first else latest).received_at


class _Gate:
    """The session start, as the watcher asks it again."""

    def __init__(self) -> None:
        self.released = 0

    def release_held(self) -> None:
        self.released += 1


def _reading(
    week: float | None, five_hour: float | None = 0.1, *, minutes: int = 0
) -> ControllerUsageReading:
    """A fresh reading as the controller serves it, taken `minutes` after
    RECEIVED_AT."""
    windows = [
        {"window": window, "share": share, "resetsAt": resets_at.isoformat()}
        for window, share, resets_at in (
            ("five_hour", five_hour, FIVE_HOUR_RESETS_AT),
            ("seven_day", week, WEEK_RESETS_AT),
        )
        if share is not None
    ]
    return ControllerUsageReading.model_validate(
        {
            "takenAt": (RECEIVED_AT + timedelta(minutes=minutes)).isoformat(),
            "stale": False,
            "staleReason": None,
            "windows": windows,
        }
    )


def _frames(connection: SSEConnection) -> list[dict[str, Any]]:
    queued = []
    while True:
        try:
            frame = connection.next_frame(timeout=0)
        except Empty:
            return queued
        assert frame is not None
        queued.append(json.loads(frame.removeprefix("data: ")))


def _codes(frames: list[dict[str, Any]]) -> list[list[str]]:
    return [
        [condition["code"] for condition in frame["payload"]["conditions"]]
        for frame in frames
    ]


@pytest.fixture
def gate(container: ServiceContainer) -> _Gate:
    gate = _Gate()
    container.session_start_service.override(providers.Object(gate))
    return gate


@pytest.fixture
def usage(container: ServiceContainer) -> UsageService:
    return UsageService(container=container)


@pytest.fixture
def supervisor(container: ServiceContainer, supervise: Supervise) -> Supervisor:
    return supervise(container)[0]


@pytest.fixture
def watcher(
    container: ServiceContainer, supervisor: Supervisor, usage: UsageService
) -> UsageWatcher:
    """A watcher of its own, on its own usage service and supervisor."""
    return UsageWatcher(
        container=container,
        supervisor=supervisor,
        usage_service=usage,
        usage_halts=HALTS,
    )


@pytest.fixture
def connection(container: ServiceContainer, person: User) -> Generator[SSEConnection]:
    manager: SSEConnectionManager = container.sse_connection_manager()
    assert person.subject is not None
    opened = manager.on_connect("ada-1", person.subject)
    yield opened
    manager.on_disconnect(opened)


@pytest.fixture
def halts_log() -> Generator[LogWaiter]:
    with listening("app.services.usage_halts") as waiter:
        yield waiter


class TestUsageWatcher:
    def test_a_reading_that_turns_a_halt_on_tells_the_conditions_and_asks_the_gate(
        self,
        session: Session,
        usage: UsageService,
        watcher: UsageWatcher,
        gate: _Gate,
        connection: SSEConnection,
        halts_log: LogWaiter,
    ) -> None:
        usage.receive(_reading(0.95))

        [frame] = _frames(connection)
        [halt] = frame["payload"]["conditions"]
        reading = session.scalars(select(UsageReading)).one()
        assert halt == {
            "code": "week_halt",
            "since": reading.received_at.isoformat().replace("+00:00", "Z"),
            "share": 0.95,
            "taken_at": "2026-10-08T09:00:00Z",
        }
        assert gate.released == 1
        assert halts_log.matching("The week's halt holds: .*")

    def test_a_reading_under_the_limits_turns_nothing_and_tells_nothing(
        self,
        usage: UsageService,
        watcher: UsageWatcher,
        gate: _Gate,
        connection: SSEConnection,
    ) -> None:
        usage.receive(_reading(0.5))

        assert (_frames(connection), gate.released) == ([], 0)

    def test_a_reading_while_a_halt_holds_tells_its_figures_and_asks_the_gate_nothing(
        self,
        usage: UsageService,
        watcher: UsageWatcher,
        gate: _Gate,
        connection: SSEConnection,
    ) -> None:
        usage.receive(_reading(0.95))
        _frames(connection)

        usage.receive(_reading(0.96, minutes=10))

        [frame] = _frames(connection)
        assert [c["share"] for c in frame["payload"]["conditions"]] == [0.96]
        assert gate.released == 1

    def test_each_halts_turn_on_and_off_is_told(
        self,
        usage: UsageService,
        watcher: UsageWatcher,
        gate: _Gate,
        connection: SSEConnection,
        halts_log: LogWaiter,
    ) -> None:
        usage.receive(_reading(0.95))
        usage.receive(_reading(0.95, 0.8, minutes=10))
        usage.receive(_reading(0.95, 0.3, minutes=20))
        usage.receive(_reading(0.1, 0.3, minutes=30))

        assert _codes(_frames(connection)) == [
            ["week_halt"],
            ["week_halt", "five_hour_halt"],
            ["week_halt"],
            [],
        ]
        assert gate.released == 4
        assert halts_log.matching("The five-hour halt lifted: .*")
        assert halts_log.matching("The week's halt lifted: .*")

    def test_a_reading_not_recorded_turns_nothing(
        self,
        usage: UsageService,
        watcher: UsageWatcher,
        gate: _Gate,
        connection: SSEConnection,
    ) -> None:
        usage.receive(_reading(0.5, minutes=10))
        # Older than the latest recorded: ignored.
        usage.receive(_reading(0.95))

        assert (_frames(connection), gate.released) == ([], 0)

    def test_the_timer_lifts_a_stale_halt_a_minute_past_its_reset(
        self,
        session: Session,
        clock: type[_Clock],
        watcher: UsageWatcher,
        gate: _Gate,
        connection: SSEConnection,
    ) -> None:
        _record(session, week=0.95, stale=True)
        watcher.reevaluate()
        assert _codes(_frames(connection)) == [["week_halt"]]

        clock.at = WEEK_RESETS_AT + timedelta(seconds=59)
        watcher.run_timer(session)
        assert _frames(connection) == []

        clock.at = WEEK_RESETS_AT + timedelta(minutes=1)
        watcher.run_timer(session)

        assert _codes(_frames(connection)) == [[]]
        assert gate.released == 2

    def test_its_timer_runs_on_the_schedulers_tick_from_startup(
        self,
        container: ServiceContainer,
        supervise: Supervise,
        session: Session,
        clock: type[_Clock],
        gate: _Gate,
        connection: SSEConnection,
    ) -> None:
        supervisor, coordinator = supervise(container)
        UsageWatcher(
            container=container,
            supervisor=supervisor,
            usage_service=UsageService(container=container),
            usage_halts=HALTS,
        )
        _record(session, week=0.95)

        coordinator.fire_startup()
        try:
            wait_until(lambda: gate.released == 1, f"the {TIMER} timer's turn")
        finally:
            coordinator.shutdown()
        assert _codes(_frames(connection)) == [["week_halt"]]
