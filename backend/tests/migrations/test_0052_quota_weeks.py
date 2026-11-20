"""Revision 0052: the Quota Weeks written for the record as it stands, by the
fixed rule up to the first reading and by the readings' resets from there, and
its downgrade, which takes them."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session as DbSession

from app.models import QuotaWeek, UsageReading, WindowShare
from app.models.reference import UsageWindow
from tests.support.revisions import run_revision

WEEK = timedelta(days=7)
FIRST = datetime(2025, 1, 2, 10, tzinfo=UTC)


def _weeks(db: DbSession) -> list[tuple[datetime, datetime]]:
    return [
        (week.starts_at, week.ends_at)
        for week in db.scalars(select(QuotaWeek).order_by(QuotaWeek.starts_at))
    ]


def _reading(
    db: DbSession,
    taken_at: datetime,
    seven_day_resets_at: datetime | None,
) -> None:
    """A Usage Reading stored, with its five-hour Window Share and, given
    its reset, its seven-day one."""
    reading = UsageReading(taken_at=taken_at, received_at=taken_at, stale=False)
    db.add(reading)
    db.flush()
    resets = {UsageWindow.FIVE_HOUR: taken_at + timedelta(hours=3)}
    if seven_day_resets_at is not None:
        resets[UsageWindow.SEVEN_DAY] = seven_day_resets_at
    db.add_all(
        WindowShare(
            reading_id=reading.id, window_code=window, share=0.3, resets_at=resets_at
        )
        for window, resets_at in resets.items()
    )
    db.flush()


def _fixed(weeks: list[tuple[datetime, datetime]]) -> bool:
    """Whether the weeks are the fixed rule's from its first Thursday: seven
    days each, each starting where the one before it ends."""
    return weeks == [
        (FIRST + index * WEEK, FIRST + (index + 1) * WEEK)
        for index in range(len(weeks))
    ]


class TestTheDowngrade:
    def test_the_weeks_go_with_their_table(self, session: DbSession) -> None:
        run_revision(session, "0052", "downgrade")

        assert session.scalar(text("SELECT to_regclass('quota_weeks')")) is None


class TestTheUpgrade:
    def test_with_no_reading_stored_the_fixed_rule_seeds_the_weeks_to_the_running_one(
        self, session: DbSession
    ) -> None:
        run_revision(session, "0052", "downgrade")
        before = datetime.now(UTC)

        run_revision(session, "0052", "upgrade")

        weeks = _weeks(session)
        assert _fixed(weeks)
        assert weeks[-1][0] <= before < weeks[-1][1]

    def test_the_fixed_rule_seeds_to_the_first_reading_and_its_resets_write_the_rest(
        self, session: DbSession
    ) -> None:
        run_revision(session, "0052", "downgrade")
        october = datetime(2026, 10, 1, tzinfo=UTC)
        november = datetime(2026, 11, 1, tzinfo=UTC)
        # A reading with no seven-day window, then the week of 15 October
        # named a second apart, its reset passed, a reset on schedule, and
        # one off schedule, on Tuesday 3 November at 08:30.
        _reading(session, october + timedelta(days=11, hours=9), None)
        _reading(
            session,
            october + timedelta(days=19, hours=12),
            october + timedelta(days=21, hours=9, minutes=59, seconds=59),
        )
        _reading(
            session,
            october + timedelta(days=19, hours=12, minutes=10),
            october + timedelta(days=21, hours=10),
        )
        _reading(
            session,
            october + timedelta(days=21, hours=10, minutes=4),
            october + timedelta(days=28, hours=9, minutes=59, seconds=59),
        )
        _reading(
            session,
            october + timedelta(days=28, hours=10, minutes=4),
            november + timedelta(days=4, hours=10),
        )
        _reading(
            session,
            november + timedelta(days=2, hours=8, minutes=34),
            november + timedelta(days=9, hours=8, minutes=30),
        )

        run_revision(session, "0052", "upgrade")

        weeks = _weeks(session)
        closed_early = datetime(2026, 10, 29, 9, 59, 59, tzinfo=UTC)
        cut = datetime(2026, 11, 3, 8, 30, tzinfo=UTC)
        assert _fixed(weeks[:-3])
        assert weeks[-4:] == [
            (
                datetime(2026, 10, 15, 10, tzinfo=UTC),
                datetime(2026, 10, 22, 10, tzinfo=UTC),
            ),
            (datetime(2026, 10, 22, 10, tzinfo=UTC), closed_early),
            (closed_early, cut),
            (cut, datetime(2026, 11, 10, 8, 30, tzinfo=UTC)),
        ]

    def test_readings_missed_for_weeks_leave_no_gap(self, session: DbSession) -> None:
        run_revision(session, "0052", "downgrade")
        first = datetime(2026, 10, 20, 12, tzinfo=UTC)
        _reading(session, first, datetime(2026, 10, 22, 10, tzinfo=UTC))
        _reading(
            session, first + 3 * WEEK, datetime(2026, 11, 12, 9, 59, 59, tzinfo=UTC)
        )

        run_revision(session, "0052", "upgrade")

        weeks = _weeks(session)
        assert _fixed(weeks[:-3])
        assert weeks[-3:] == [
            (
                datetime(2026, 10, 22, 10, tzinfo=UTC),
                datetime(2026, 10, 29, 9, 59, 59, tzinfo=UTC),
            ),
            (
                datetime(2026, 10, 29, 9, 59, 59, tzinfo=UTC),
                datetime(2026, 11, 5, 9, 59, 59, tzinfo=UTC),
            ),
            (
                datetime(2026, 11, 5, 9, 59, 59, tzinfo=UTC),
                datetime(2026, 11, 12, 9, 59, 59, tzinfo=UTC),
            ),
        ]
