"""Usage Reading, Window Share and Quota Week: what a row must hold."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.models import QuotaWeek, UsageReading, WindowShare
from app.models.reference import UsageWindow
from tests.support.database import violated_constraint

TAKEN_AT = datetime(2026, 10, 8, 23, 50, tzinfo=UTC)
WEEK_RESETS_AT = datetime(2026, 10, 9, 7, tzinfo=UTC)


def _reading(session: DbSession, *, stale: bool = False) -> UsageReading:
    reading = UsageReading(taken_at=TAKEN_AT, received_at=TAKEN_AT, stale=stale)
    session.add(reading)
    session.flush()
    return reading


class TestUsageReading:
    def test_a_reading_carries_a_share_per_window(self, session: DbSession) -> None:
        reading = _reading(session)
        session.add_all(
            [
                WindowShare(
                    reading_id=reading.id,
                    window_code=UsageWindow.SEVEN_DAY,
                    share=0.96,
                    resets_at=WEEK_RESETS_AT,
                ),
                WindowShare(
                    reading_id=reading.id,
                    window_code=UsageWindow.FIVE_HOUR,
                    share=0.64,
                    resets_at=datetime(2026, 10, 9, 2, tzinfo=UTC),
                ),
            ]
        )

        session.flush()

        windows = session.scalars(
            select(WindowShare.window_code).where(WindowShare.reading_id == reading.id)
        ).all()
        assert sorted(windows) == [UsageWindow.FIVE_HOUR, UsageWindow.SEVEN_DAY]

    def test_a_share_may_pass_one_and_keeps_its_figure_exactly(
        self, session: DbSession
    ) -> None:
        reading = _reading(session, stale=True)
        share = WindowShare(
            reading_id=reading.id,
            window_code=UsageWindow.SEVEN_DAY,
            share=0.1 + 1.0000000000000002,
            resets_at=WEEK_RESETS_AT,
        )
        session.add(share)
        session.flush()
        session.expire(share)

        assert share.share == 0.1 + 1.0000000000000002

    def test_a_reading_carries_at_most_one_share_per_window(
        self, session: DbSession
    ) -> None:
        reading = _reading(session)
        session.add_all(
            WindowShare(
                reading_id=reading.id,
                window_code=UsageWindow.SEVEN_DAY,
                share=share,
                resets_at=WEEK_RESETS_AT,
            )
            for share in (0.96, 0.97)
        )

        assert (
            violated_constraint(session) == "window_shares_reading_id_window_code_key"
        )

    def test_a_share_is_carried_by_a_reading(self, session: DbSession) -> None:
        session.add(
            WindowShare(
                reading_id=404,
                window_code=UsageWindow.SEVEN_DAY,
                share=0.5,
                resets_at=WEEK_RESETS_AT,
            )
        )

        assert violated_constraint(session) == "window_shares_reading_id_fkey"


# A Thursday 10:00 UTC before the first week the revisions seed.
WEEK_STARTS_AT = datetime(2024, 11, 7, 10, tzinfo=UTC)
WEEK = timedelta(days=7)


def _week(session: DbSession, starts_at: datetime, ends_at: datetime) -> None:
    session.add(QuotaWeek(starts_at=starts_at, ends_at=ends_at))


class TestQuotaWeek:
    def test_a_week_starts_where_the_one_before_it_ends(
        self, session: DbSession
    ) -> None:
        _week(session, WEEK_STARTS_AT, WEEK_STARTS_AT + WEEK)
        _week(session, WEEK_STARTS_AT + WEEK, WEEK_STARTS_AT + 2 * WEEK)

        session.flush()

        held = session.scalars(
            select(QuotaWeek.starts_at).where(
                QuotaWeek.starts_at <= WEEK_STARTS_AT + WEEK,
                QuotaWeek.ends_at > WEEK_STARTS_AT + WEEK,
            )
        ).all()
        assert held == [WEEK_STARTS_AT + WEEK]

    @pytest.mark.parametrize(
        "length", [timedelta(0), timedelta(seconds=-1)], ids=["empty", "backwards"]
    )
    def test_a_week_ends_after_it_starts(
        self, session: DbSession, length: timedelta
    ) -> None:
        _week(session, WEEK_STARTS_AT, WEEK_STARTS_AT + length)

        assert violated_constraint(session) == "ck_quota_weeks_period"

    @pytest.mark.parametrize(
        ("starts", "ends"),
        [
            (timedelta(days=6, hours=23, minutes=59, seconds=59), 2 * WEEK),
            (timedelta(days=-3), timedelta(seconds=1)),
            (timedelta(days=1), timedelta(days=2)),
            (timedelta(0), WEEK),
        ],
        ids=["a-second-before-its-end", "a-second-into-it", "inside-it", "the-same"],
    )
    def test_no_two_weeks_overlap(
        self, session: DbSession, starts: timedelta, ends: timedelta
    ) -> None:
        _week(session, WEEK_STARTS_AT, WEEK_STARTS_AT + WEEK)
        session.flush()
        _week(session, WEEK_STARTS_AT + starts, WEEK_STARTS_AT + ends)

        assert violated_constraint(session) == "ex_quota_weeks_overlap"
