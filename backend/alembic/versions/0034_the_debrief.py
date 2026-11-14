"""A Work's `debrief`, Debrief Entry, and a Progress Step's `why`.

Slice 043, P1 (DB decision 76, assertions 322 to 329): the stage session's
own debrief on its Work, none for a job, and every account of it a Debrief
Entry, keyed by its Work and its place in the order given, written once with
it; and a step's short line under its label.

Revision ID: 0034
Revises: 0033
Create Date: 2026-11-14

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column("work", sa.Column("debrief", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_work_debrief", "work", "session_kind_code = 'work' OR debrief IS NULL"
    )
    op.create_table(
        "debrief_entries",
        sa.Column("work_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("section", sa.Text(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("duration", sa.Integer(), nullable=False),
        sa.Column("words", sa.Text(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("why", sa.Text(), nullable=True),
        sa.CheckConstraint("position >= 1", name="ck_debrief_entries_position"),
        sa.CheckConstraint('"round" >= 1', name="ck_debrief_entries_round"),
        sa.CheckConstraint("duration >= 0", name="ck_debrief_entries_duration"),
        sa.CheckConstraint(
            "words IS NULL OR passed IS NULL", name="ck_debrief_entries_result"
        ),
        sa.ForeignKeyConstraint(["work_id"], ["work.id"]),
        sa.PrimaryKeyConstraint("work_id", "position"),
    )
    op.add_column("progress_steps", sa.Column("why", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade database schema: every debrief and every step's why is lost."""
    op.drop_column("progress_steps", "why")
    op.drop_table("debrief_entries")
    op.drop_constraint("ck_work_debrief", "work", type_="check")
    op.drop_column("work", "debrief")
