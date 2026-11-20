"""The collector's walks: the moment each ended.

Slice 050 (DB decisions 79.19 and 79.28): `walks`, a row per pass of the
collector over the fleet's home, holding when the server was told that it
ended and nothing else. Nothing is backfilled: no collector has walked.

Revision ID: 0050
Revises: 0049
Create Date: 2026-11-19

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0050"
down_revision: str | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        "walks",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade database schema: the walks kept go with their table."""
    op.drop_table("walks")
