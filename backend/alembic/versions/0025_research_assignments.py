"""Research Assignment: the work item that checks a fact a Block rests on.

Slice 036, P1: the pre-ruling pass names, on the `add_item` of the work item
that checks a fact a block's answer rests on, each such block of a registered
document; a Block named again by a later work item keeps its earlier namings,
the latest standing (DB decision 71).

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-02

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        "research_assignments",
        sa.Column("work_id", sa.Uuid(), nullable=False),
        sa.Column("block_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["work_id"], ["work.id"]),
        sa.ForeignKeyConstraint(["block_id"], ["blocks.id"]),
        sa.PrimaryKeyConstraint("work_id", "block_id"),
    )
    op.create_index(
        "ix_research_assignments_block_id", "research_assignments", ["block_id"]
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index("ix_research_assignments_block_id", "research_assignments")
    op.drop_table("research_assignments")
