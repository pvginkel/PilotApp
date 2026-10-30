"""The usage service: the readings the fleet stream hands it, recorded as DB
decision 67 has them (assertion 274), and the age of the figures it holds
(design 4 §6)."""

import math
import threading
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flask import Flask
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database import scoped_session
from app.models import UsageReading, WindowShare
from app.models.reference import UsageWindow
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerUsageReading
from app.services.usage_service import READING_AGE, Usage, UsageService, WindowFigure
from tests.support.supervisor import LogWaiter, listening, metric_value, wait_until

USAGE_LOGGER = "app.services.usage_service"

TAKEN_AT = datetime(2026, 10, 8, 23, 40, tzinfo=UTC)
FIVE_HOUR_RESETS_AT = datetime(2026, 10, 9, 2, tzinfo=UTC)
WEEK_RESETS_AT = datetime(2026, 10, 9, 7, tzinfo=UTC)

NO_READING_YET = {
    "takenAt": None,
    "stale": True,
    "staleReason": "no-reading-yet",
    "windows": [],
}


def _reading(
    seven_day: float | None = 0.77,
    five_hour: float | None = 0.08,
    *,
    taken_at: datetime = TAKEN_AT,
    stale_reason: str | None = None,
    week_resets_at: datetime = WEEK_RESETS_AT,
) -> ControllerUsageReading:
    """A reading as the controller serves it; stale with a reason."""
    windows: list[dict[str, Any]] = []
    if five_hour is not None:
        windows.append(
            {
                "window": "five_hour",
                "share": five_hour,
                "resetsAt": FIVE_HOUR_RESETS_AT.isoformat(),
            }
        )
    if seven_day is not None:
        windows.append(
            {
                "window": "seven_day",
                "share": seven_day,
                "resetsAt": week_resets_at.isoformat(),
            }
        )
    return ControllerUsageReading.model_validate(
        {
            "takenAt": taken_at.isoformat(),
            "stale": stale_reason is not None,
            "staleReason": stale_reason,
            "windows": windows,
        }
    )


def _usage(
    seven_day: float | None = 0.77,
    five_hour: float | None = 0.08,
    *,
    taken_at: datetime = TAKEN_AT,
    stale: bool = False,
) -> Usage:
    windows = {}
    if five_hour is not None:
        windows[UsageWindow.FIVE_HOUR] = WindowFigure(five_hour, FIVE_HOUR_RESETS_AT)
    if seven_day is not None:
        windows[UsageWindow.SEVEN_DAY] = WindowFigure(seven_day, WEEK_RESETS_AT)
    return Usage(taken_at, stale, windows)


def _count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(UsageReading)) or 0


@pytest.fixture
def usage(container: ServiceContainer) -> UsageService:
    """A service of its own on the test's session: no reading held."""
    return UsageService(container=container)


@pytest.fixture
def usage_log() -> Generator[LogWaiter]:
    with listening(USAGE_LOGGER) as waiter:
        yield waiter


class TestUsageService:
    def test_latest_is_none_before_the_first_reading(
        self, usage: UsageService, session: Session
    ) -> None:
        assert usage.latest(session) is None

    def test_a_first_reading_is_recorded_with_a_share_per_window(
        self, usage: UsageService, session: Session
    ) -> None:
        before = datetime.now(UTC)

        usage.receive(_reading())

        [reading] = session.scalars(select(UsageReading)).all()
        shares = session.scalars(
            select(WindowShare).where(WindowShare.reading_id == reading.id)
        ).all()
        assert (reading.taken_at, reading.stale) == (TAKEN_AT, False)
        assert reading.received_at >= before
        assert {(s.window_code, s.share, s.resets_at) for s in shares} == {
            (UsageWindow.FIVE_HOUR, 0.08, FIVE_HOUR_RESETS_AT),
            (UsageWindow.SEVEN_DAY, 0.77, WEEK_RESETS_AT),
        }
        assert usage.latest(session) == _usage()

    @pytest.mark.parametrize(
        "without_figures",
        [
            NO_READING_YET,
            {**NO_READING_YET, "staleReason": "no-credential"},
            {
                "takenAt": TAKEN_AT.isoformat(),
                "stale": False,
                "staleReason": None,
                "windows": [],
            },
        ],
        ids=["no-reading-yet", "failing-before-an-answer", "answered-with-no-window"],
    )
    def test_a_reading_without_figures_leaves_the_latest_as_it_is(
        self,
        usage: UsageService,
        session: Session,
        usage_log: LogWaiter,
        without_figures: dict[str, Any],
    ) -> None:
        usage.receive(_reading(0.5))

        usage.receive(ControllerUsageReading.model_validate(without_figures))

        assert _count(session) == 1
        assert usage.latest(session) == _usage(0.5)
        assert usage_log.matching(r"Usage reading without figures.*") == [
            f"Usage reading without figures ({without_figures['staleReason']}): "
            "the latest recorded stands"
        ]

    def test_a_reading_without_figures_before_the_first_records_none(
        self, usage: UsageService, session: Session
    ) -> None:
        usage.receive(ControllerUsageReading.model_validate(NO_READING_YET))

        assert usage.latest(session) is None

    def test_a_reading_moving_only_its_taken_at_is_not_recorded(
        self, usage: UsageService, session: Session, usage_log: LogWaiter
    ) -> None:
        usage.receive(_reading())

        usage.receive(_reading(taken_at=TAKEN_AT + timedelta(minutes=10)))

        assert _count(session) == 1
        assert usage.latest(session) == _usage()
        assert usage_log.matching(r".*unchanged.*") == [
            "Usage reading taken at 2026-10-08T23:50:00+00:00: "
            "unchanged since the latest recorded"
        ]

    @pytest.mark.parametrize(
        ("changed", "recorded"),
        [
            (_reading(0.76), _usage(0.76)),
            (_reading(five_hour=0.09), _usage(five_hour=0.09)),
            (
                _reading(week_resets_at=WEEK_RESETS_AT + timedelta(days=7)),
                Usage(
                    TAKEN_AT,
                    False,
                    {
                        UsageWindow.FIVE_HOUR: WindowFigure(0.08, FIVE_HOUR_RESETS_AT),
                        UsageWindow.SEVEN_DAY: WindowFigure(
                            0.77, WEEK_RESETS_AT + timedelta(days=7)
                        ),
                    },
                ),
            ),
            (_reading(five_hour=None), _usage(five_hour=None)),
        ],
        ids=["a-lower-share", "a-higher-share", "a-reset-moved", "a-window-missing"],
    )
    def test_a_change_of_its_figures_is_recorded(
        self,
        usage: UsageService,
        session: Session,
        changed: ControllerUsageReading,
        recorded: Usage,
    ) -> None:
        usage.receive(_reading())

        usage.receive(changed)

        assert _count(session) == 2
        assert usage.latest(session) == recorded

    def test_a_window_appearing_is_recorded(
        self, usage: UsageService, session: Session
    ) -> None:
        usage.receive(_reading(five_hour=None))

        usage.receive(_reading(taken_at=TAKEN_AT + timedelta(minutes=10)))

        assert _count(session) == 2
        assert usage.latest(session) == _usage(
            taken_at=TAKEN_AT + timedelta(minutes=10)
        )

    def test_going_stale_and_fresh_again_are_each_recorded(
        self, usage: UsageService, session: Session, usage_log: LogWaiter
    ) -> None:
        fresh_again_at = TAKEN_AT + timedelta(hours=8)
        usage.receive(_reading())

        usage.receive(_reading(stale_reason="token-expired"))
        stale = usage.latest(session)
        usage.receive(_reading(taken_at=fresh_again_at))

        assert _count(session) == 3
        assert stale == _usage(stale=True)
        assert usage.latest(session) == _usage(taken_at=fresh_again_at)
        # Why a reading is stale is the log's alone.
        stale_lines = usage_log.matching(
            r"Usage reading \d+ recorded, taken at 2026-10-08T23:40:00\+00:00: "
            r"five_hour 0\.08 to 2026-10-09T02:00:00\+00:00, seven_day 0\.77 "
            r"to 2026-10-09T07:00:00\+00:00; stale \(token-expired\)"
        )
        assert len(stale_lines) == 1

    def test_a_reading_older_than_the_latest_recorded_is_ignored(
        self, usage: UsageService, session: Session, usage_log: LogWaiter
    ) -> None:
        usage.receive(_reading())

        usage.receive(_reading(0.5, taken_at=TAKEN_AT - timedelta(minutes=10)))

        assert _count(session) == 1
        assert usage.latest(session) == _usage()
        usage_log.wait_for(r"Usage reading taken at .* is older .*: ignored")

    def test_a_reading_as_old_as_the_latest_with_other_figures_is_recorded(
        self, usage: UsageService, session: Session
    ) -> None:
        usage.receive(_reading())

        usage.receive(_reading(0.78))

        assert _count(session) == 2
        assert usage.latest(session) == _usage(0.78)

    def test_after_a_restart_the_first_reading_is_compared_with_the_last_recorded(
        self, container: ServiceContainer, session: Session
    ) -> None:
        UsageService(container=container).receive(_reading())
        restarted = UsageService(container=container)

        restarted.receive(_reading(taken_at=TAKEN_AT + timedelta(hours=1)))
        unchanged = _count(session)
        restarted.receive(_reading(0.8, taken_at=TAKEN_AT + timedelta(hours=2)))

        assert unchanged == 1
        assert _count(session) == 2
        assert restarted.latest(session) == _usage(
            0.8, taken_at=TAKEN_AT + timedelta(hours=2)
        )

    def test_two_processes_receiving_one_reading_record_it_once(
        self, committed_app: Flask
    ) -> None:
        # Two backends overlap in a roll, each with its own fleet stream.
        container = committed_app.container
        receivers = [UsageService(container=container) for _ in range(2)]
        holder: Session = container.session_maker()()
        holder.execute(text("LOCK TABLE usage_readings IN EXCLUSIVE MODE"))
        threads = [
            threading.Thread(target=receiver.receive, args=(_reading(),))
            for receiver in receivers
        ]
        try:
            for thread in threads:
                thread.start()
            wait_until(lambda: _waiting_on_the_table(container) == 2, "both waiting")
        finally:
            holder.rollback()
            holder.close()
        for thread in threads:
            thread.join()

        with scoped_session(container) as db:
            assert _count(db) == 1


class TestReadingAge:
    def test_it_is_nan_before_a_reading_with_figures(self, usage: UsageService) -> None:
        usage.receive(ControllerUsageReading.model_validate(NO_READING_YET))

        assert math.isnan(metric_value(READING_AGE))

    def test_it_is_zero_while_the_reading_is_fresh(self, usage: UsageService) -> None:
        usage.receive(_reading(taken_at=datetime.now(UTC) - timedelta(hours=1)))

        assert metric_value(READING_AGE) == 0

    def test_while_stale_it_is_the_time_since_the_last_answer(
        self, usage: UsageService
    ) -> None:
        usage.receive(
            _reading(
                taken_at=datetime.now(UTC) - timedelta(hours=1),
                stale_reason="token-expired",
            )
        )

        assert 3600 <= metric_value(READING_AGE) < 3660

    def test_a_reading_without_figures_leaves_it_as_it_is(
        self, usage: UsageService
    ) -> None:
        usage.receive(
            _reading(
                taken_at=datetime.now(UTC) - timedelta(hours=1),
                stale_reason="token-expired",
            )
        )

        usage.receive(ControllerUsageReading.model_validate(NO_READING_YET))

        assert metric_value(READING_AGE) >= 3600

    def test_an_older_reading_leaves_it_as_it_is(self, usage: UsageService) -> None:
        taken_at = datetime.now(UTC) - timedelta(hours=1)
        usage.receive(_reading(taken_at=taken_at, stale_reason="token-expired"))

        usage.receive(_reading(taken_at=taken_at - timedelta(minutes=10)))

        assert metric_value(READING_AGE) >= 3600


def _waiting_on_the_table(container: ServiceContainer) -> int:
    with scoped_session(container) as db:
        return (
            db.scalar(
                text(
                    "SELECT count(*) FROM pg_locks l JOIN pg_class c"
                    " ON c.oid = l.relation"
                    " WHERE c.relname = 'usage_readings' AND NOT l.granted"
                )
            )
            or 0
        )
