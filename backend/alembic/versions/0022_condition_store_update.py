"""Condition's `store_update`.

Slice 033, P2: Pilot updating its store, a Store Update unlifted, is a
condition of the gold bar with its alarm (F144.4; DB decision 68).

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-01

"""

from collections.abc import Sequence

from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONDITION = ("outage", "week_halt", "five_hour_halt")


def upgrade() -> None:
    """Upgrade database schema."""
    op.execute("ALTER TYPE condition ADD VALUE 'store_update' AFTER 'outage'")


def downgrade() -> None:
    """Downgrade database schema: the enum rebuilt without `store_update`,
    which PostgreSQL drops no value of in place; an alarm of the store's
    update fails the cast."""
    op.execute("ALTER TYPE condition RENAME TO condition_0022")
    postgresql.ENUM(*CONDITION, name="condition").create(op.get_bind())
    op.execute(
        "ALTER TABLE alarms ALTER COLUMN condition_code"
        " TYPE condition USING condition_code::text::condition"
    )
    op.execute("DROP TYPE condition_0022")
