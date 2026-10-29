"""Claim Assignment: the work item a claimed action is given to.

Slice 026, P3: the pre-ruling pass names, on the `add_item` of the work item
that does it, each action of a registered document it claims; a Block named
again by a later work item keeps its earlier namings, the latest standing (DB
decision 64).

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-29

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        "claim_assignments",
        sa.Column("work_id", sa.Uuid(), nullable=False),
        sa.Column("block_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["work_id"], ["work.id"]),
        sa.ForeignKeyConstraint(["block_id"], ["blocks.id"]),
        sa.PrimaryKeyConstraint("work_id", "block_id"),
    )
    op.create_index("ix_claim_assignments_block_id", "claim_assignments", ["block_id"])


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index("ix_claim_assignments_block_id", "claim_assignments")
    op.drop_table("claim_assignments")
