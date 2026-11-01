"""Store Update.

Slice 033, P1: the operator's update of the store while Pilot runs, made by
`update-store` and run by the server from the row, at most one unlifted at a
time (DB decision 68, assertions 276 and 279).

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-01

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        "store_updates",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("made_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lift_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lifted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_store_updates_unlifted",
        "store_updates",
        [sa.text("(lifted_at IS NULL)")],
        unique=True,
        postgresql_where=sa.text("lifted_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index("uq_store_updates_unlifted", table_name="store_updates")
    op.drop_table("store_updates")
