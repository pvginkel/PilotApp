"""Clarification Run: the role of a work item that puts a pass's questions to
the writer.

Slice 026, P4: when the pre-ruling pass's job ends having asked, its questions
go to the writer as one work item resuming the worker's conversation; the
role names the pass it clarifies, one run a pass, and holds the writer's
reply, the run's turn's final text, with when it came (DB decision 63).

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-29

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        "clarification_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pass_id", sa.Uuid(), nullable=False),
        sa.Column("reply", sa.Text(), nullable=True),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["id"], ["work.id"]),
        sa.ForeignKeyConstraint(["pass_id"], ["work.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("pass_id <> id", name="ck_clarification_runs_pass"),
        sa.CheckConstraint(
            "(reply IS NULL) = (replied_at IS NULL)",
            name="ck_clarification_runs_reply",
        ),
    )
    op.create_index(
        "uq_clarification_runs_pass_id", "clarification_runs", ["pass_id"], unique=True
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index("uq_clarification_runs_pass_id", "clarification_runs")
    op.drop_table("clarification_runs")
