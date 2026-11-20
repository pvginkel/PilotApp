"""The Quota Weeks: the subscription's seven-day windows, reset to reset.

Slice 053 (DB §2.5, Quota Week; decision 79.26; assertion 550):
`quota_weeks`, a row per window, the end exclusive, none overlapping.

The weeks are written here for the record as it stands. By the fixed rule,
Thursday 10:00 UTC, from 2 January 2025, the Thursday after the Prices' first
date, to the week that holds the first Usage Reading with a seven-day Window
Share, or this revision's run where none is stored. From there on by each
such reading's reset in the readings' order, as
`app/services/quota_week_service.py` follows one at this revision.

Revision ID: 0052
Revises: 0051
Create Date: 2026-11-20

"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from itertools import pairwise

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FIRST = datetime(2025, 1, 2, 10, tzinfo=UTC)
WEEK = timedelta(days=7)
SAME = timedelta(minutes=1)

RESETS = sa.text(
    "SELECT r.taken_at, s.resets_at FROM window_shares s"
    " JOIN usage_readings r ON r.id = s.reading_id"
    " WHERE s.window_code = 'seven_day' ORDER BY r.id"
)

type Week = tuple[datetime, datetime]


def upgrade() -> None:
    """Upgrade database schema."""
    quota_weeks = op.create_table(
        "quota_weeks",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("starts_at < ends_at", name="ck_quota_weeks_period"),
        postgresql.ExcludeConstraint(
            (sa.text("tstzrange(starts_at, ends_at)"), "&&"),
            name="ex_quota_weeks_overlap",
            using="gist",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    bind = op.get_bind()
    readings = bind.execute(RESETS).all()
    until = readings[0].taken_at if readings else datetime.now(UTC)
    weeks = _seeded(until)
    for reading in readings:
        weeks[-1:] = _follow(weeks[-1], reading.resets_at)
    op.bulk_insert(
        quota_weeks,
        [{"starts_at": starts_at, "ends_at": ends_at} for starts_at, ends_at in weeks],
    )


def _seeded(until: datetime) -> list[Week]:
    """The weeks of the fixed rule, through the one that holds `until`."""
    weeks = [(FIRST, FIRST + WEEK)]
    while weeks[-1][1] <= until:
        weeks.append((weeks[-1][1], weeks[-1][1] + WEEK))
    return weeks


def _follow(running: Week, reset: datetime) -> list[Week]:
    """The weeks that take the running week's place once a reading names
    `reset`: the running week, its end where the reset leaves it, and each
    week after it."""
    starts_at, ends_at = running
    opened = reset - WEEK
    if reset < starts_at + SAME or abs(reset - ends_at) < SAME:
        return [running]
    if opened < starts_at + SAME:
        return [(starts_at, reset)]
    if opened < ends_at + SAME:
        cut = ends_at if abs(opened - ends_at) < SAME else opened
        return [(starts_at, cut), (cut, reset)]
    bounds = [reset]
    while bounds[0] - WEEK >= ends_at + SAME:
        bounds.insert(0, bounds[0] - WEEK)
    bounds.insert(0, ends_at)
    return [running, *pairwise(bounds)]


def downgrade() -> None:
    """Downgrade database schema: the weeks go with their table."""
    op.drop_table("quota_weeks")
