"""The Quota Weeks, written from the usage readings (DB §2.5, Quota Week;
decision 79.26; assertion 550).

A Quota Week runs from one reset of the subscription's seven-day window to
the next, the end exclusive. The weeks leave no gap and none overlap: each
starts where the one before it ends. The latest is the running week, and its
end is the reset its reading names.

Each Usage Reading recorded is followed (`follow`): its seven-day Window
Share names a reset, and where the running week does not end at it, the weeks
are brought to it. A reading names one reset a second or two apart from poll
to poll, so two resets under a minute apart are one (`SAME`).

The weeks before the first reading are revision 0052's, by the fixed rule,
Thursday 10:00 UTC, so the table always holds a running week. A Call falls in
the week whose bounds hold its `completed_at`, met at the query.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from typing import TYPE_CHECKING

from sqlalchemy import select, text

from app.database import scoped_session
from app.models import QuotaWeek
from app.models.reference import UsageWindow
from app.services.usage_service import UsageService, latest

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)

WEEK = timedelta(days=7)
SAME = timedelta(minutes=1)
"""Two resets nearer than this are one reset: production's readings of
13 to 20 November 2026 name one reset at 09:59:58, 09:59:59 and 10:00:00."""

THURSDAY = 3
"""`date.weekday()` of a Thursday."""


@dataclass(frozen=True)
class Period:
    """A Quota Week's bounds, the end exclusive."""

    starts_at: datetime
    ends_at: datetime


def follow(running: Period, reset: datetime) -> list[Period]:
    """The weeks that take the running week's place once a reading names
    `reset`: the running week first, its end where the reset leaves it, then
    each week written after it.

    The reset closes a window of seven days, which opened at `reset - WEEK`:

    - A reset the running week ends at, or one not after its start, changes
      nothing.
    - A window that opened no later than the running week is the running
      week under another end: its end moves to the reset.
    - A window that opened inside the running week cut it short: the running
      week ends where the window opened, and the window is the next week. One
      that opened at the running week's end is the next week.
    - A window that opened after the running week's end leaves weeks no
      reading named: they are counted back from the reset, seven days each,
      and the earliest starts at the running week's end, cut short.
    """
    opened = reset - WEEK
    if reset < running.starts_at + SAME or _same(reset, running.ends_at):
        return [running]
    if opened < running.starts_at + SAME:
        return [Period(running.starts_at, reset)]
    if opened < running.ends_at + SAME:
        cut = running.ends_at if _same(opened, running.ends_at) else opened
        return [Period(running.starts_at, cut), Period(cut, reset)]
    bounds = [reset]
    while bounds[0] - WEEK >= running.ends_at + SAME:
        bounds.insert(0, bounds[0] - WEEK)
    bounds.insert(0, running.ends_at)
    return [running, *(Period(*bound) for bound in pairwise(bounds))]


def _same(one: datetime, other: datetime) -> bool:
    return abs(one - other) < SAME


def label(starts_at: datetime, ends_at: datetime) -> tuple[int, int] | date:
    """What a Quota Week is labelled by: the ISO year and week of its
    Thursday, the first Thursday in UTC it holds a moment of; a week cut
    short with no Thursday in it, its start's date in UTC.

    Two weeks may share a label, where a reset cut a week short on its
    Thursday.
    """
    started = starts_at.astimezone(UTC).date()
    thursday = started + timedelta(days=(THURSDAY - started.weekday()) % 7)
    if datetime.combine(thursday, time.min, UTC) >= ends_at:
        return started
    year, week, _ = thursday.isocalendar()
    return year, week


class QuotaWeekService:
    """The weeks kept in step with the usage readings recorded."""

    def __init__(
        self, container: "ServiceContainer", usage_service: UsageService
    ) -> None:
        """Hear every reading the usage service records.

        Args:
            container: Gives each following its database session
            usage_service: Tells of each reading it records
        """
        self._container = container
        usage_service.subscribe(self.follow_latest)

    def follow_latest(self) -> None:
        """Bring the weeks to the reset the latest Usage Reading's seven-day
        Window Share names; a reading with none leaves them as they are."""
        with scoped_session(self._container) as db:
            # Two processes overlapping in a roll may each follow a reading:
            # the lock has the later one read the weeks the earlier one wrote.
            db.execute(text("LOCK TABLE quota_weeks IN EXCLUSIVE MODE"))
            usage = latest(db)
            figure = None if usage is None else usage.windows.get(UsageWindow.SEVEN_DAY)
            if figure is None:
                return
            running = db.scalars(
                select(QuotaWeek).order_by(QuotaWeek.starts_at.desc()).limit(1)
            ).one()
            first, *later = follow(
                Period(running.starts_at, running.ends_at), figure.resets_at
            )
            if first.ends_at != running.ends_at:
                logger.info(
                    "Quota week from %s: its end moved from %s to %s",
                    running.starts_at.isoformat(),
                    running.ends_at.isoformat(),
                    first.ends_at.isoformat(),
                )
                running.ends_at = first.ends_at
                # Written before the weeks after it, which start where it
                # now ends: none may overlap.
                db.flush()
            for week in later:
                logger.info(
                    "Quota week written: %s to %s",
                    week.starts_at.isoformat(),
                    week.ends_at.isoformat(),
                )
            db.add_all(
                QuotaWeek(starts_at=week.starts_at, ends_at=week.ends_at)
                for week in later
            )
