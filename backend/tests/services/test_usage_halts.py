"""The usage halts (design 4 §6, *The halts*; F135.1, F135.4, F135.8; DB 266):
the week's and the five-hour's, decided from the latest Usage Reading at their
limits, a window left out holding none, a five-hour limit of 0 none, a stale
window lifted one minute past its reset; when each began; whether a hard-stop
halt holds; and their watcher, which tells of a turn at a recorded reading and
on its timer, asks for the nudges owed at a turn (DB 232), and asks for the
hard stop while one holds and a work item runs."""

import json
from collections.abc import Generator, Iterator
from datetime import UTC, datetime, timedelta
from queue import Empty
from typing import Any

import pytest
from dependency_injector import providers
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.app_config import HaltSetting
from app.models import (
    Environment,
    Project,
    QuotaOverrule,
    UsageReading,
    User,
    WindowShare,
)
from app.models import Session as AgentSession
from app.models.reference import OverruleKind, ProjectState, SessionState, UsageWindow
from app.services import usage_halts as usage_halts_module
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerUsageReading
from app.services.sse_connection_manager import SSEConnection, SSEConnectionManager
from app.services.supervisor import Supervisor
from app.services.usage_halts import TIMER, Halt, Offer, UsageHalts, UsageWatcher
from app.services.usage_service import Usage, UsageService
from tests.support.supervisor import LogWaiter, Supervise, listening, wait_until

WEEK = UsageWindow.SEVEN_DAY
FIVE_HOUR = UsageWindow.FIVE_HOUR
ALLOWANCE = OverruleKind.ALLOWANCE
RUN_OUT = OverruleKind.RUN_OUT

COOPERATIVE = HaltSetting.COOPERATIVE_STOP
HARD = HaltSetting.HARD_STOP


def _halts(
    *,
    five_hour_limit: float = 0.75,
    week_halt: HaltSetting = COOPERATIVE,
    five_hour_halt: HaltSetting = COOPERATIVE,
) -> UsageHalts:
    """The halts at the default limits and settings, but those given."""
    return UsageHalts(
        week_limit=0.9,
        week_allowance=0.05,
        week_second_limit=0.98,
        five_hour_limit=five_hour_limit,
        week_halt=week_halt,
        five_hour_halt=five_hour_halt,
    )


HALTS = _halts()

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


def _overrule(
    db: Session,
    person: User,
    *,
    kind: OverruleKind = OverruleKind.ALLOWANCE,
    target: float | None = 0.98,
    made_at: datetime = RECEIVED_AT + timedelta(minutes=5),
    ended_at: datetime | None = None,
) -> QuotaOverrule:
    """A Quota Overrule `person` made at `made_at`, by default an allowance
    holding, five minutes after the first reading's receipt."""
    made = QuotaOverrule(
        kind_code=kind,
        made_by_user_id=person.id,
        made_at=made_at,
        target=target,
        ended_at=ended_at,
    )
    db.add(made)
    db.flush()
    return made


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

        assert _halts(five_hour_limit=0).holding(session) == ()

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


class TestStopping:
    """Whether a halt whose setting is the hard stop holds (F135.6; DB 269)."""

    @pytest.mark.parametrize(
        ("week", "five_hour", "stopping"),
        [
            (0.95, 0.1, True),
            (0.5, 0.8, False),
            (0.95, 0.8, True),
            (0.5, 0.1, False),
        ],
    )
    def test_only_a_hard_stop_halt_that_holds_stops(
        self, session: Session, week: float, five_hour: float, stopping: bool
    ) -> None:
        _record(session, week=week, five_hour=five_hour)

        assert _halts(week_halt=HARD).stopping(session) is stopping

    @pytest.mark.parametrize("setting", [COOPERATIVE, HaltSetting.NO_NEW_WORK])
    def test_a_halt_of_another_setting_stops_nothing(
        self, session: Session, setting: HaltSetting
    ) -> None:
        _record(session, week=0.95, five_hour=0.8)

        halts = _halts(week_halt=setting, five_hour_halt=setting)
        assert halts.stopping(session) is False

    def test_the_five_hours_hard_stop_stops_at_its_limit(
        self, session: Session
    ) -> None:
        _record(session, week=0.95, five_hour=0.8)

        assert _halts(five_hour_halt=HARD).stopping(session) is True

    def test_none_stops_before_the_first_reading(self, session: Session) -> None:
        assert _halts(week_halt=HARD, five_hour_halt=HARD).stopping(session) is False

    def test_an_overrule_that_holds_lifts_the_weeks_hard_stop(
        self, session: Session, person: User
    ) -> None:
        _record(session, week=0.95, five_hour=0.1)
        _overrule(session, person)

        assert _halts(week_halt=HARD).stopping(session) is False

    def test_stops_reads_each_windows_setting(self) -> None:
        halts = _halts(five_hour_halt=HARD)

        assert (halts.stops([WEEK]), halts.stops([FIVE_HOUR]), halts.stops([])) == (
            False,
            True,
            False,
        )


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
            Halt(WEEK, 0.93, began, latest.taken_at, Offer(ALLOWANCE, 0.98)),
            Halt(FIVE_HOUR, 0.8, latest.received_at, latest.taken_at, None),
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
            Halt(WEEK, 0.95, held.received_at, held.taken_at, Offer(ALLOWANCE, 0.98))
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


class TestOverrule:
    def test_one_that_holds_lifts_the_weeks_halt_and_not_the_five_hours(
        self, session: Session, person: User
    ) -> None:
        reading = _record(session, week=0.95, five_hour=0.8)
        _overrule(session, person)

        assert HALTS.holding(session) == (FIVE_HOUR,)
        assert HALTS.halted(session) == FIVE_HOUR
        assert HALTS.halts(session) == [
            Halt(FIVE_HOUR, 0.8, reading.received_at, reading.taken_at, None)
        ]
        assert HALTS.offer(session) is None

    def test_a_spent_one_lifts_nothing(self, session: Session, person: User) -> None:
        _record(session, week=0.95)
        _overrule(session, person, ended_at=RECEIVED_AT + timedelta(minutes=8))

        assert HALTS.holding(session) == (WEEK,)

    @pytest.mark.parametrize(
        ("week", "offer"),
        [
            (0.9, Offer(ALLOWANCE, 0.95)),
            # The target held to the second limit.
            (0.95, Offer(ALLOWANCE, 0.98)),
            (0.9799, Offer(ALLOWANCE, 0.98)),
            (0.98, Offer(RUN_OUT, None)),
            (1.03, Offer(RUN_OUT, None)),
        ],
    )
    def test_the_weeks_halt_offers_the_allowance_under_the_second_limit_and_run_out_at_it(
        self, session: Session, week: float, offer: Offer
    ) -> None:
        _record(session, week=week)

        assert HALTS.offer(session) == offer
        [halt] = HALTS.halts(session)
        assert halt.offer == offer

    @pytest.mark.parametrize("week", [None, 0.89])
    def test_no_overrule_is_offered_while_the_weeks_halt_does_not_hold(
        self, session: Session, week: float | None
    ) -> None:
        _record(session, week=week, five_hour=0.9)

        assert HALTS.offer(session) is None

    def test_none_is_offered_before_the_first_reading(self, session: Session) -> None:
        assert HALTS.offer(session) is None

    def test_the_halt_held_again_at_an_overrules_end_began_then(
        self, session: Session, person: User
    ) -> None:
        _record(session, week=0.95)
        ended = RECEIVED_AT + timedelta(hours=2)
        _overrule(session, person, ended_at=ended)
        _record(session, week=0.98, received_at=ended)

        [halt] = HALTS.halts(session)

        assert halt.since == ended

    def test_an_overrules_end_before_the_halts_run_leaves_its_start(
        self, session: Session, person: User
    ) -> None:
        _overrule(session, person, ended_at=RECEIVED_AT - timedelta(days=1))
        first = _record(session, week=0.95)

        [halt] = HALTS.halts(session)

        assert halt.since == first.received_at


class TestEndSpent:
    def test_none_holds_none_ends(self, session: Session) -> None:
        _record(session, week=0.95)

        assert HALTS.end_spent(session) is None

    @pytest.mark.parametrize(
        ("kind", "target", "week", "spent"),
        [
            (ALLOWANCE, 0.96, 0.9599, False),
            (ALLOWANCE, 0.96, 0.96, True),
            (ALLOWANCE, 0.96, 0.99, True),
            (RUN_OUT, None, 0.9999, False),
            (RUN_OUT, None, 1.0, True),
        ],
    )
    def test_a_reading_at_or_over_its_target_spends_it(
        self,
        session: Session,
        clock: type[_Clock],
        person: User,
        kind: OverruleKind,
        target: float | None,
        week: float,
        spent: bool,
    ) -> None:
        _record(session, week=0.92)
        made = _overrule(session, person, kind=kind, target=target)
        _record(session, week=week, received_at=RECEIVED_AT + timedelta(minutes=10))
        clock.at = RECEIVED_AT + timedelta(minutes=10)

        ended = HALTS.end_spent(session)

        assert ended is (made if spent else None)
        session.refresh(made)
        assert made.ended_at == (clock.at if spent else None)

    @pytest.mark.parametrize(
        ("made_at", "target"), [(0.9, 0.95), (0.91, 0.96), (0.92, 0.97)]
    )
    def test_a_reading_at_the_allowances_offered_target_spends_it(
        self, session: Session, person: User, made_at: float, target: float
    ) -> None:
        _record(session, week=made_at)
        offer = HALTS.offer(session)
        assert offer is not None
        made = _overrule(session, person, target=offer.target)
        _record(session, week=target, received_at=RECEIVED_AT + timedelta(minutes=10))

        assert HALTS.end_spent(session) is made

    def test_a_run_out_made_at_the_wall_is_spent_at_once(
        self, session: Session, person: User
    ) -> None:
        _record(session, week=1.02)
        made = _overrule(session, person, kind=RUN_OUT, target=None)

        assert HALTS.end_spent(session) is made

    def test_a_reading_lower_than_the_one_before_spends_it_under_its_target(
        self, session: Session, person: User
    ) -> None:
        _record(session, week=0.96)
        made = _overrule(session, person)
        _record(session, week=0.955, received_at=RECEIVED_AT + timedelta(minutes=10))

        assert HALTS.end_spent(session) is made
        # The share still over the first limit: the halt holds again.
        assert HALTS.holding(session) == (WEEK,)

    def test_a_lower_reading_the_overrule_was_made_after_spends_nothing(
        self, session: Session, person: User
    ) -> None:
        _record(session, week=0.99)
        _record(session, week=0.96, received_at=RECEIVED_AT + timedelta(minutes=1))
        _overrule(session, person, made_at=RECEIVED_AT + timedelta(minutes=2))

        assert HALTS.end_spent(session) is None

    def test_the_reading_before_is_the_one_before_that_carries_the_week(
        self, session: Session, person: User
    ) -> None:
        _record(session, week=0.96)
        made = _overrule(session, person)
        _record(session, five_hour=0.2, received_at=RECEIVED_AT + timedelta(minutes=10))
        # The latest without the week spends nothing.
        assert HALTS.end_spent(session) is None
        _record(session, week=0.955, received_at=RECEIVED_AT + timedelta(minutes=20))

        assert HALTS.end_spent(session) is made

    @pytest.mark.parametrize(
        ("past_reset", "spent"),
        [(timedelta(seconds=59), False), (timedelta(minutes=1), True)],
    )
    def test_a_stale_week_a_minute_past_its_reset_spends_it(
        self,
        session: Session,
        clock: type[_Clock],
        person: User,
        past_reset: timedelta,
        spent: bool,
    ) -> None:
        _record(session, week=0.95, stale=True)
        made = _overrule(session, person)
        clock.at = WEEK_RESETS_AT + past_reset

        assert HALTS.end_spent(session) is (made if spent else None)

    def test_it_is_ended_once(
        self, session: Session, monkeypatch: pytest.MonkeyPatch, person: User
    ) -> None:
        _record(session, week=0.92)
        made = _overrule(session, person)
        _record(session, week=0.99, received_at=RECEIVED_AT + timedelta(minutes=10))
        # Another decision ends it between this one's read and its write.
        first_end = RECEIVED_AT + timedelta(minutes=11)
        read = usage_halts_module.overrule

        def overtaken(db: Session) -> QuotaOverrule | None:
            holding = read(db)
            db.execute(
                update(QuotaOverrule)
                .where(QuotaOverrule.id == made.id)
                .values(ended_at=first_end)
                .execution_options(synchronize_session=False)
            )
            return holding

        monkeypatch.setattr(usage_halts_module, "overrule", overtaken)

        assert HALTS.end_spent(session) is None
        session.expire_all()
        assert session.get_one(QuotaOverrule, made.id).ended_at == first_end


class _Gate:
    """The session start, as the watcher asks it again, for the hard stop
    and for the nudges owed."""

    def __init__(self) -> None:
        self.released = 0
        self.hard_stops = 0
        self.nudged = 0

    def release_held(self) -> None:
        self.released += 1

    def hard_stop(self) -> None:
        self.hard_stops += 1

    def send_nudges(self) -> None:
        self.nudged += 1


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


class _HaltFiles:
    """The halt files, as the watcher asks for their sweep."""

    def __init__(self) -> None:
        self.requested = 0

    def request(self) -> None:
        self.requested += 1


@pytest.fixture
def halt_files(container: ServiceContainer) -> _HaltFiles:
    halt_files = _HaltFiles()
    container.halt_file_service.override(providers.Object(halt_files))
    return halt_files


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
def hard_watcher(
    container: ServiceContainer, supervisor: Supervisor, usage: UsageService
) -> UsageWatcher:
    """A watcher of its own whose week's halt is the hard stop and whose
    five-hour halt the cooperative stop."""
    return UsageWatcher(
        container=container,
        supervisor=supervisor,
        usage_service=usage,
        usage_halts=_halts(week_halt=HARD),
    )


def _session(db: Session, person: User, kind: str, state: SessionState) -> None:
    """A Session of `kind` in `state`, in a project and an environment of its
    own."""
    project = Project(
        created_by_user_id=person.id, state_code=ProjectState.OPEN, slug=kind
    )
    environment = Environment(id=f"env-{kind}-{state}", name=kind, exempt=False)
    db.add_all([project, environment])
    db.flush()
    db.add(
        AgentSession(
            project_id=project.id,
            environment_id=environment.id,
            kind_code=kind,
            cwd="/work/Example",
            token_hash=f"{kind}-{state}".ljust(64, "0"),
            state_code=state,
        )
    )
    db.flush()


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
            "offer": "allowance",
            "target": 0.98,
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

    def test_each_halts_turn_sweeps_the_halt_files(
        self,
        usage: UsageService,
        watcher: UsageWatcher,
        gate: _Gate,
        halt_files: _HaltFiles,
    ) -> None:
        usage.receive(_reading(0.95))
        turned_on = halt_files.requested
        usage.receive(_reading(0.96, minutes=10))
        held = halt_files.requested
        usage.receive(_reading(0.1, minutes=20))

        assert (turned_on, held, halt_files.requested) == (1, 1, 2)

    def test_each_halts_turn_asks_for_the_nudges_owed(
        self,
        usage: UsageService,
        watcher: UsageWatcher,
        gate: _Gate,
    ) -> None:
        """A halt lifted is the reading that lets an owed nudge go (F135.8;
        DB 232); the nudges' loop reads what holds each one."""
        usage.receive(_reading(0.95))
        turned_on = gate.nudged
        usage.receive(_reading(0.96, minutes=10))
        held = gate.nudged
        usage.receive(_reading(0.1, minutes=20))

        assert (turned_on, held, gate.nudged) == (1, 1, 2)

    def test_a_reading_while_a_wall_owes_its_nudge_asks_for_the_nudges(
        self,
        session: Session,
        person: User,
        usage: UsageService,
        watcher: UsageWatcher,
        gate: _Gate,
    ) -> None:
        """A reading may confirm a turn's quota wall, decide it missed or
        bring the quota back, whatever the halts do (the ruling on the wall;
        V11)."""
        usage.receive(_reading(0.5))
        _session(session, person, "work", SessionState.FAILED)
        usage.receive(_reading(0.6, minutes=10))
        assert gate.nudged == 0

        session.execute(update(AgentSession).values(nudge_owed_at=RECEIVED_AT))
        usage.receive(_reading(0.7, minutes=20))
        assert gate.nudged == 1

        # A halt's turn asks once.
        usage.receive(_reading(0.95, minutes=30))
        assert gate.nudged == 2

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
        # The stale fallback's lift lets the nudges owed go.
        assert gate.nudged == 2

    def test_an_overrule_made_lifts_the_halt_whatever_this_process_told(
        self,
        session: Session,
        person: User,
        watcher: UsageWatcher,
        gate: _Gate,
        connection: SSEConnection,
    ) -> None:
        _record(session, week=0.95)
        _overrule(session, person)

        watcher.overruled()

        assert _codes(_frames(connection)) == [[]]
        assert (gate.released, gate.nudged) == (1, 1)

    def test_a_reading_that_spends_the_overrule_ends_it_and_the_halt_holds_again(
        self,
        session: Session,
        person: User,
        usage: UsageService,
        watcher: UsageWatcher,
        gate: _Gate,
        connection: SSEConnection,
        halts_log: LogWaiter,
    ) -> None:
        usage.receive(_reading(0.95))
        made = _overrule(session, person, made_at=datetime.now(UTC))
        watcher.overruled()
        # Under its target, and not lower: nothing to tell.
        usage.receive(_reading(0.96, minutes=10))

        usage.receive(_reading(0.98, minutes=20))

        frames = _frames(connection)
        assert _codes(frames) == [["week_halt"], [], ["week_halt"]]
        session.refresh(made)
        assert made.ended_at is not None
        assert frames[-1]["payload"]["conditions"][0]["since"] == (
            made.ended_at.isoformat().replace("+00:00", "Z")
        )
        assert gate.released == 3
        assert halts_log.matching(r"Quota overrule \d+ \(allowance\) ended: .*")

    def test_an_overrules_end_with_no_turn_is_told(
        self,
        session: Session,
        person: User,
        usage: UsageService,
        watcher: UsageWatcher,
        gate: _Gate,
        connection: SSEConnection,
    ) -> None:
        usage.receive(_reading(0.95))
        _overrule(session, person, made_at=datetime.now(UTC))
        watcher.overruled()
        _frames(connection)

        # Lower, and under the first limit: the halt does not hold again.
        usage.receive(_reading(0.3, minutes=10))

        assert _codes(_frames(connection)) == [[]]
        assert gate.released == 2
        assert HALTS.offer(session) is None

    def test_the_timer_ends_the_overrule_a_minute_past_a_stale_weeks_reset(
        self,
        session: Session,
        clock: type[_Clock],
        person: User,
        watcher: UsageWatcher,
        gate: _Gate,
        connection: SSEConnection,
    ) -> None:
        _record(session, week=0.95, stale=True)
        made = _overrule(session, person)
        watcher.reevaluate()
        assert _frames(connection) == []

        clock.at = WEEK_RESETS_AT + timedelta(minutes=1)
        watcher.run_timer(session)

        assert _codes(_frames(connection)) == [[]]
        session.refresh(made)
        assert made.ended_at == clock.at
        assert gate.released == 0

    def test_a_hard_stop_halt_turned_on_while_a_work_item_runs_asks_for_the_hard_stop(
        self,
        session: Session,
        person: User,
        usage: UsageService,
        hard_watcher: UsageWatcher,
        gate: _Gate,
        halt_files: _HaltFiles,
    ) -> None:
        _session(session, person, "work", SessionState.RUNNING)

        usage.receive(_reading(0.95))

        assert (gate.hard_stops, gate.released, halt_files.requested) == (1, 1, 1)

    def test_while_it_holds_each_decision_asks_again_for_a_work_item_still_running(
        self,
        session: Session,
        person: User,
        usage: UsageService,
        hard_watcher: UsageWatcher,
        gate: _Gate,
        halt_files: _HaltFiles,
    ) -> None:
        """A work item the gate let through before the halt turned on is
        stopped at the next decision: the hard stop holds while the halt does,
        not at its turn alone."""
        usage.receive(_reading(0.95))
        assert gate.hard_stops == 0
        _session(session, person, "work", SessionState.RUNNING)

        hard_watcher.run_timer(session)
        usage.receive(_reading(0.96, minutes=10))

        assert (gate.hard_stops, gate.released) == (2, 1)

    @pytest.mark.parametrize(
        ("kind", "state"),
        [
            ("work", SessionState.STARTING),
            ("work", SessionState.HELD),
            ("work", SessionState.STOPPED),
            ("work", SessionState.IDLE),
            ("chat", SessionState.RUNNING),
            ("job", SessionState.RUNNING),
        ],
    )
    def test_with_no_work_item_running_none_is_asked(
        self,
        session: Session,
        person: User,
        usage: UsageService,
        hard_watcher: UsageWatcher,
        gate: _Gate,
        kind: str,
        state: SessionState,
    ) -> None:
        _session(session, person, kind, state)

        usage.receive(_reading(0.95))

        assert (gate.hard_stops, gate.released) == (0, 1)

    def test_a_halt_of_the_cooperative_stop_asks_for_none(
        self,
        session: Session,
        person: User,
        usage: UsageService,
        hard_watcher: UsageWatcher,
        gate: _Gate,
    ) -> None:
        _session(session, person, "work", SessionState.RUNNING)

        usage.receive(_reading(0.5, 0.8))

        assert (gate.hard_stops, gate.released) == (0, 1)

    def test_an_overrule_made_lifts_the_hard_stop(
        self,
        session: Session,
        person: User,
        usage: UsageService,
        hard_watcher: UsageWatcher,
        gate: _Gate,
    ) -> None:
        usage.receive(_reading(0.95))
        _overrule(session, person, made_at=datetime.now(UTC))
        _session(session, person, "work", SessionState.RUNNING)

        hard_watcher.overruled()

        assert (gate.hard_stops, gate.released) == (0, 2)

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
