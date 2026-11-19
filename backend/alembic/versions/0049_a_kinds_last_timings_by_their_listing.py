"""A kind's last timings, by their listing and in one repo.

Slice 049 (F156.4, F156.5): the estimate reads a kind's last Step Timings
that were listed ahead and its last that were not, in all repos and in one
repo's own. Each of those reads is a range of an index here, ended at its
limit: the index on `(kind_code, ended_at)` it replaces walked a kind's whole
history for a repo's or one listing's few.

Revision ID: 0049
Revises: 0048
Create Date: 2026-11-19

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.drop_index("ix_step_timings_kind_code_ended_at", table_name="step_timings")
    op.create_index(
        "ix_step_timings_kind_code_listed_ahead_ended_at",
        "step_timings",
        ["kind_code", "listed_ahead", "ended_at", "id"],
    )
    op.create_index(
        "ix_step_timings_repo_kind_code_listed_ahead_ended_at",
        "step_timings",
        ["repo", "kind_code", "listed_ahead", "ended_at", "id"],
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index(
        "ix_step_timings_repo_kind_code_listed_ahead_ended_at",
        table_name="step_timings",
    )
    op.drop_index(
        "ix_step_timings_kind_code_listed_ahead_ended_at", table_name="step_timings"
    )
    op.create_index(
        "ix_step_timings_kind_code_ended_at",
        "step_timings",
        ["kind_code", "ended_at"],
    )
