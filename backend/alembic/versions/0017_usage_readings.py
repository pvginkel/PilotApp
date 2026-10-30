"""Usage Reading and Window Share, classified by Usage Window.

Slice 028, P2: Pilot records the subscription's usage as KubeCoder's
controller serves it on the fleet stream, a reading per change received with
figures, a share per window it carries (DB decision 67, assertions 270, 271
and 274).

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USAGE_WINDOW = ("five_hour", "seven_day")


def upgrade() -> None:
    """Upgrade database schema."""
    postgresql.ENUM(*USAGE_WINDOW, name="usage_window").create(op.get_bind())
    op.create_table(
        "usage_readings",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stale", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "window_shares",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("reading_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "window_code",
            postgresql.ENUM(name="usage_window", create_type=False),
            nullable=False,
        ),
        sa.Column("share", sa.Double(), nullable=False),
        sa.Column("resets_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["reading_id"], ["usage_readings.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reading_id", "window_code"),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_table("window_shares")
    op.drop_table("usage_readings")
    postgresql.ENUM(name="usage_window").drop(op.get_bind())
