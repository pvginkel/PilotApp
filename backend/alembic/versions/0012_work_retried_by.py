"""A job's Retry: the job it placed.

Slice 025, P5: a failed or stopped job of Pilot's own offers Retry, which
places a fresh job for the same trigger at the project's next place; the
failed one's line stays, marked as retried by the new job, offering Retry
no more and counted by no badge (F94.5; DB Work).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column("work", sa.Column("retried_by_id", sa.Uuid(), nullable=True))
    op.create_unique_constraint(None, "work", ["project_id", "id", "session_kind_code"])
    op.create_foreign_key(
        None,
        "work",
        "work",
        ["project_id", "retried_by_id", "session_kind_code"],
        ["project_id", "id", "session_kind_code"],
    )
    op.create_check_constraint(
        "ck_work_retried_by",
        "work",
        "retried_by_id IS NULL OR (session_kind_code = 'job' AND retried_by_id <> id)",
    )
    op.create_index("uq_work_retried_by_id", "work", ["retried_by_id"], unique=True)


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index("uq_work_retried_by_id", "work")
    op.drop_constraint("ck_work_retried_by", "work")
    op.drop_constraint("work_project_id_retried_by_id_session_kind_code_fkey", "work")
    op.drop_constraint("work_project_id_id_session_kind_code_key", "work")
    op.drop_column("work", "retried_by_id")
