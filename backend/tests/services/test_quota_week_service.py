"""The Quota Weeks as the usage readings write them (DB §2.5, Quota Week;
decision 79.26; assertion 550): the rule a reset is followed by, a week's
label, the weeks the record holds, and the weeks stored after each reading
recorded."""

from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from app.models import QuotaWeek
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerUsageReading
from app.services.quota_week_service import (
    Period,
    QuotaWeekService,
    follow,
    label,
    quota_weeks,
)
from app.services.usage_service import UsageService
from tests.support.supervisor import LogWaiter, listening

WEEK = timedelta(days=7)
SECOND = timedelta(seconds=1)

# Week 45 of 2026 by the fixed rule, a Thursday 10:00 UTC to the next.
STARTS_AT = datetime(2026, 11, 5, 10, tzinfo=UTC)
ENDS_AT = datetime(2026, 11, 12, 10, tzinfo=UTC)
RUNNING = Period(STARTS_AT, ENDS_AT)
TAKEN_AT = datetime(2026, 11, 6, 8, 20, tzinfo=UTC)


def _at(day: int, hour: int = 10, minute: int = 0, second: int = 0) -> datetime:
    """A moment of November 2026, in UTC."""
    return datetime(2026, 11, day, hour, minute, second, tzinfo=UTC)


class TestFollow:
    @pytest.mark.parametrize(
        "reset",
        [ENDS_AT, ENDS_AT - SECOND, ENDS_AT - 2 * SECOND, ENDS_AT + 59 * SECOND],
        ids=["the-same", "a-second-before", "two-seconds-before", "under-a-minute"],
    )
    def test_the_reset_the_running_week_ends_at_changes_nothing(
        self, reset: datetime
    ) -> None:
        assert follow(RUNNING, reset) == [RUNNING]

    @pytest.mark.parametrize(
        "reset",
        [STARTS_AT, STARTS_AT + 59 * SECOND, STARTS_AT - WEEK, _at(1, 7)],
        ids=["its-start", "under-a-minute-past-it", "the-week-before", "earlier"],
    )
    def test_a_reset_not_after_the_running_weeks_start_changes_nothing(
        self, reset: datetime
    ) -> None:
        assert follow(RUNNING, reset) == [RUNNING]

    @pytest.mark.parametrize(
        "reset",
        [_at(11), _at(12, 9, 59), _at(7, 16, 30), STARTS_AT + timedelta(minutes=1)],
        ids=["a-day-earlier", "a-minute-earlier", "days-earlier", "a-minute-long"],
    )
    def test_a_window_opened_no_later_than_the_running_week_moves_its_end(
        self, reset: datetime
    ) -> None:
        assert follow(RUNNING, reset) == [Period(STARTS_AT, reset)]

    def test_a_week_ended_short_takes_a_later_reset_within_its_seven_days(
        self,
    ) -> None:
        short = Period(STARTS_AT, _at(10, 8, 30))

        assert follow(short, ENDS_AT) == [RUNNING]

    @pytest.mark.parametrize("off", [-2 * SECOND, -SECOND, timedelta(0), 59 * SECOND])
    def test_the_next_reset_writes_the_week_that_starts_where_the_running_one_ends(
        self, off: timedelta
    ) -> None:
        reset = ENDS_AT + WEEK + off

        assert follow(RUNNING, reset) == [RUNNING, Period(ENDS_AT, reset)]

    def test_a_reset_off_schedule_cuts_the_running_week_short_where_its_window_opened(
        self,
    ) -> None:
        """DB §3's sample: week 45 cut short on Tuesday the 10th at 08:30,
        week 46 running from there."""
        assert follow(RUNNING, _at(17, 8, 30)) == [
            Period(STARTS_AT, _at(10, 8, 30)),
            Period(_at(10, 8, 30), _at(17, 8, 30)),
        ]

    @pytest.mark.parametrize(
        ("reset", "cut"),
        [
            (ENDS_AT + timedelta(minutes=1), STARTS_AT + timedelta(minutes=1)),
            (ENDS_AT + WEEK - timedelta(minutes=1), ENDS_AT - timedelta(minutes=1)),
        ],
        ids=["a-minute-in", "a-minute-before-its-end"],
    )
    def test_a_minute_tells_a_window_opened_inside_the_running_week(
        self, reset: datetime, cut: datetime
    ) -> None:
        assert follow(RUNNING, reset) == [Period(STARTS_AT, cut), Period(cut, reset)]

    @pytest.mark.parametrize("off", [-SECOND, timedelta(0), SECOND])
    def test_the_weeks_no_reading_named_are_counted_back_from_the_reset(
        self, off: timedelta
    ) -> None:
        reset = ENDS_AT + 3 * WEEK + off

        assert follow(RUNNING, reset) == [
            RUNNING,
            Period(ENDS_AT, reset - 2 * WEEK),
            Period(reset - 2 * WEEK, reset - WEEK),
            Period(reset - WEEK, reset),
        ]

    def test_the_earliest_of_them_starts_at_the_running_weeks_end_cut_short(
        self,
    ) -> None:
        reset = datetime(2026, 12, 1, 8, 30, tzinfo=UTC)

        assert follow(RUNNING, reset) == [
            RUNNING,
            Period(ENDS_AT, _at(17, 8, 30)),
            Period(_at(17, 8, 30), _at(24, 8, 30)),
            Period(_at(24, 8, 30), reset),
        ]

    def test_a_window_opened_a_minute_past_the_running_weeks_end_leaves_a_week_of_it(
        self,
    ) -> None:
        opened = ENDS_AT + timedelta(minutes=1)

        assert follow(RUNNING, opened + WEEK) == [
            RUNNING,
            Period(ENDS_AT, opened),
            Period(opened, opened + WEEK),
        ]

    @pytest.mark.parametrize(
        "reset",
        [
            ENDS_AT - SECOND,
            STARTS_AT - WEEK,
            _at(11),
            ENDS_AT + WEEK - SECOND,
            _at(17, 8, 30),
            ENDS_AT + 3 * WEEK + SECOND,
            datetime(2026, 12, 1, 8, 30, tzinfo=UTC),
        ],
    )
    def test_the_weeks_leave_no_gap_and_none_passes_seven_days_by_a_minute(
        self, reset: datetime
    ) -> None:
        weeks = follow(RUNNING, reset)

        assert weeks[0].starts_at == STARTS_AT
        assert all(week.starts_at < week.ends_at for week in weeks)
        assert all(
            week.ends_at - week.starts_at < WEEK + timedelta(minutes=1)
            for week in weeks
        )
        assert [week.ends_at for week in weeks[:-1]] == [
            week.starts_at for week in weeks[1:]
        ]


class TestLabel:
    @pytest.mark.parametrize(
        ("starts_at", "ends_at", "labelled"),
        [
            (STARTS_AT, ENDS_AT, (2026, 45)),
            (STARTS_AT - SECOND, ENDS_AT - 2 * SECOND, (2026, 45)),
            (_at(10, 8, 30), _at(17, 8, 30), (2026, 46)),
            (STARTS_AT, _at(10, 8, 30), (2026, 45)),
            (_at(12, 23, 59, 59), _at(13), (2026, 46)),
            (
                datetime(2026, 12, 31, 10, tzinfo=UTC),
                datetime(2027, 1, 7, 10, tzinfo=UTC),
                (2026, 53),
            ),
            (
                datetime(2027, 1, 7, 10, tzinfo=UTC),
                datetime(2027, 1, 14, 10, tzinfo=UTC),
                (2027, 1),
            ),
        ],
        ids=[
            "thursday-to-thursday",
            "a-second-early",
            "tuesday-to-tuesday",
            "cut-short-after-its-thursday",
            "its-thursdays-last-second",
            "the-years-last",
            "the-years-first",
        ],
    )
    def test_a_week_is_labelled_by_the_iso_week_of_its_first_thursday(
        self, starts_at: datetime, ends_at: datetime, labelled: tuple[int, int]
    ) -> None:
        assert label(starts_at, ends_at) == labelled

    @pytest.mark.parametrize(
        ("starts_at", "ends_at", "labelled"),
        [
            (_at(6, 12), _at(10, 8, 30), date(2026, 11, 6)),
            (_at(6, 0), _at(12, 0), date(2026, 11, 6)),
            (
                datetime(2026, 11, 5, 0, 30, tzinfo=timezone(timedelta(hours=2))),
                datetime(2026, 11, 5, 1, 30, tzinfo=timezone(timedelta(hours=2))),
                date(2026, 11, 4),
            ),
        ],
        ids=["friday-to-tuesday", "ending-as-thursday-starts", "a-thursday-elsewhere"],
    )
    def test_a_week_cut_short_with_no_thursday_is_labelled_by_its_starts_utc_date(
        self, starts_at: datetime, ends_at: datetime, labelled: date
    ) -> None:
        assert label(starts_at, ends_at) == labelled


class TestQuotaWeeks:
    def test_they_are_the_records_in_the_order_they_start(
        self, session: DbSession
    ) -> None:
        session.execute(delete(QuotaWeek))
        session.add_all(
            [
                QuotaWeek(starts_at=STARTS_AT, ends_at=ENDS_AT),
                QuotaWeek(starts_at=STARTS_AT - WEEK, ends_at=STARTS_AT),
            ]
        )
        session.flush()

        assert quota_weeks(session) == (Period(STARTS_AT - WEEK, STARTS_AT), RUNNING)


def _reading(
    resets_at: datetime | None, *, taken_at: datetime = TAKEN_AT, share: float = 0.4
) -> ControllerUsageReading:
    """A reading as the controller serves it, its seven-day window resetting
    at `resets_at`; with none, the five-hour window alone."""
    windows = [
        {
            "window": "five_hour",
            "share": share,
            "resetsAt": (taken_at + timedelta(hours=2)).isoformat(),
        }
    ]
    if resets_at is not None:
        windows.append(
            {"window": "seven_day", "share": share, "resetsAt": resets_at.isoformat()}
        )
    return ControllerUsageReading.model_validate(
        {
            "takenAt": taken_at.isoformat(),
            "stale": False,
            "staleReason": None,
            "windows": windows,
        }
    )


def _weeks(db: DbSession) -> list[tuple[datetime, datetime]]:
    return [
        (week.starts_at, week.ends_at)
        for week in db.scalars(select(QuotaWeek).order_by(QuotaWeek.starts_at))
    ]


@pytest.fixture
def usage(container: ServiceContainer, session: DbSession) -> UsageService:
    """A usage service of its own, heard by a Quota Week service of its own,
    over two weeks stored: week 44 and the running week 45."""
    session.execute(delete(QuotaWeek))
    session.add_all(
        [
            QuotaWeek(starts_at=STARTS_AT - WEEK, ends_at=STARTS_AT),
            QuotaWeek(starts_at=STARTS_AT, ends_at=ENDS_AT),
        ]
    )
    session.flush()
    service = UsageService(container=container)
    QuotaWeekService(container=container, usage_service=service)
    return service


@pytest.fixture
def weeks_log() -> Generator[LogWaiter]:
    with listening("app.services.quota_week_service") as waiter:
        yield waiter


WEEK_44 = (STARTS_AT - WEEK, STARTS_AT)


class TestQuotaWeekService:
    def test_a_reading_that_names_the_running_weeks_end_writes_nothing(
        self, usage: UsageService, session: DbSession, weeks_log: LogWaiter
    ) -> None:
        usage.receive(_reading(ENDS_AT - SECOND))
        usage.receive(_reading(ENDS_AT, share=0.41))
        usage.receive(_reading(ENDS_AT - 2 * SECOND, share=0.42))

        assert _weeks(session) == [WEEK_44, (STARTS_AT, ENDS_AT)]
        assert weeks_log.matching("Quota week.*") == []

    def test_a_reading_past_the_reset_writes_the_next_week(
        self, usage: UsageService, session: DbSession, weeks_log: LogWaiter
    ) -> None:
        reset = ENDS_AT + WEEK - SECOND

        usage.receive(_reading(reset, taken_at=ENDS_AT + timedelta(minutes=4)))

        assert _weeks(session) == [WEEK_44, (STARTS_AT, ENDS_AT), (ENDS_AT, reset)]
        assert weeks_log.matching("Quota week.*") == [
            "Quota week written: 2026-11-12T10:00:00+00:00 to 2026-11-19T09:59:59+00:00"
        ]

    def test_each_week_is_written_once_however_many_readings_name_its_reset(
        self, usage: UsageService, session: DbSession
    ) -> None:
        after = ENDS_AT + timedelta(minutes=4)

        for minutes, off in enumerate([-SECOND, timedelta(0), -2 * SECOND]):
            usage.receive(
                _reading(
                    ENDS_AT + WEEK + off,
                    taken_at=after + timedelta(minutes=10 * minutes),
                    share=0.01 * (minutes + 1),
                )
            )

        assert _weeks(session) == [
            WEEK_44,
            (STARTS_AT, ENDS_AT),
            (ENDS_AT, ENDS_AT + WEEK - SECOND),
        ]

    def test_a_reset_off_schedule_cuts_the_running_week_short_and_starts_the_next(
        self, usage: UsageService, session: DbSession, weeks_log: LogWaiter
    ) -> None:
        usage.receive(_reading(_at(17, 8, 30), taken_at=_at(10, 8, 34)))

        assert _weeks(session) == [
            WEEK_44,
            (STARTS_AT, _at(10, 8, 30)),
            (_at(10, 8, 30), _at(17, 8, 30)),
        ]
        assert weeks_log.matching("Quota week.*") == [
            "Quota week from 2026-11-05T10:00:00+00:00: its end moved from "
            "2026-11-12T10:00:00+00:00 to 2026-11-10T08:30:00+00:00",
            "Quota week written: 2026-11-10T08:30:00+00:00 to 2026-11-17T08:30:00+00:00",
        ]

    def test_a_later_reading_that_names_another_reset_moves_the_running_weeks_end(
        self, usage: UsageService, session: DbSession, weeks_log: LogWaiter
    ) -> None:
        usage.receive(_reading(_at(11, 16)))

        assert _weeks(session) == [WEEK_44, (STARTS_AT, _at(11, 16))]
        assert weeks_log.matching("Quota week.*") == [
            "Quota week from 2026-11-05T10:00:00+00:00: its end moved from "
            "2026-11-12T10:00:00+00:00 to 2026-11-11T16:00:00+00:00"
        ]

    def test_the_weeks_no_reading_named_are_written_with_the_one_it_names(
        self, usage: UsageService, session: DbSession
    ) -> None:
        reset = ENDS_AT + 3 * WEEK

        usage.receive(_reading(reset, taken_at=reset - timedelta(days=2)))

        assert _weeks(session) == [
            WEEK_44,
            (STARTS_AT, ENDS_AT),
            (ENDS_AT, ENDS_AT + WEEK),
            (ENDS_AT + WEEK, ENDS_AT + 2 * WEEK),
            (ENDS_AT + 2 * WEEK, reset),
        ]

    def test_a_reading_with_no_seven_day_window_leaves_the_weeks(
        self, usage: UsageService, session: DbSession
    ) -> None:
        usage.receive(_reading(None))

        assert _weeks(session) == [WEEK_44, (STARTS_AT, ENDS_AT)]

    def test_a_reading_whose_reset_is_before_the_running_week_leaves_the_weeks(
        self, usage: UsageService, session: DbSession
    ) -> None:
        usage.receive(_reading(STARTS_AT - timedelta(days=2)))

        assert _weeks(session) == [WEEK_44, (STARTS_AT, ENDS_AT)]

    def test_a_moment_falls_in_one_week_its_end_the_next_weeks(
        self, usage: UsageService, session: DbSession
    ) -> None:
        usage.receive(_reading(_at(17, 8, 30), taken_at=_at(10, 8, 34)))

        def holding(moment: datetime) -> list[datetime]:
            return list(
                session.scalars(
                    select(QuotaWeek.starts_at).where(
                        QuotaWeek.starts_at <= moment, moment < QuotaWeek.ends_at
                    )
                )
            )

        assert holding(_at(10, 8, 29, 59)) == [STARTS_AT]
        assert holding(_at(10, 8, 30)) == [_at(10, 8, 30)]
        assert holding(STARTS_AT) == [STARTS_AT]
        assert holding(_at(17, 8, 30)) == []
