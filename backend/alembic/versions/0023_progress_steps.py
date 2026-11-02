"""Progress Step, classified by Progress State.

Slice 034, P1: a work item's run lists the steps it goes through, each with
its code, label, place, state and the server's two stamps (DB decision 69,
assertions 283 to 288).

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROGRESS_STATE = ("pending", "active", "done")


def upgrade() -> None:
    """Upgrade database schema."""
    postgresql.ENUM(*PROGRESS_STATE, name="progress_state").create(op.get_bind())
    op.create_table(
        "progress_steps",
        sa.Column("work_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "state_code",
            postgresql.ENUM(name="progress_state", create_type=False),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("position >= 1", name="ck_progress_steps_position"),
        sa.CheckConstraint(
            "state_code = 'pending' OR started_at IS NOT NULL",
            name="ck_progress_steps_started",
        ),
        sa.CheckConstraint(
            "(state_code = 'done') = (ended_at IS NOT NULL)",
            name="ck_progress_steps_ended",
        ),
        sa.ForeignKeyConstraint(["work_id"], ["work.id"]),
        sa.PrimaryKeyConstraint("work_id", "code"),
        sa.UniqueConstraint(
            "work_id",
            "position",
            name="uq_progress_steps_work_id_position",
            deferrable=True,
            initially="DEFERRED",
        ),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_table("progress_steps")
    postgresql.ENUM(name="progress_state").drop(op.get_bind())
