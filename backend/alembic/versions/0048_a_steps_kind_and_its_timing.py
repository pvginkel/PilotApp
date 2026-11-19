"""A step's kind, its conversations and its timing.

Slice 049 (DB decision 79; assertions 353 to 358, 562 to 565, 572 to 574):
Step Kind, the workflow's, a row written as a publication first names its
code; a Progress Step's `kind_code`, `listed_ahead` and `marked`; Step
Transcript, a step's naming of a main thread by Claude Code's session id,
deleted with its step; and Step Timing, a finished step kept whatever becomes
of its list, with the repo its Work had when it was written, so that a seeded
timing's `key` is unique within it. Nothing is backfilled: a step Pilot holds
was published with no kind and no mark, and whether it was listed ahead is
unknown.

Revision ID: 0048
Revises: 0047
Create Date: 2026-11-19

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        "step_kinds",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    op.add_column("progress_steps", sa.Column("kind_code", sa.Text(), nullable=True))
    op.add_column(
        "progress_steps", sa.Column("listed_ahead", sa.Boolean(), nullable=True)
    )
    op.add_column("progress_steps", sa.Column("marked", sa.Boolean(), nullable=True))
    op.create_foreign_key(None, "progress_steps", "step_kinds", ["kind_code"], ["code"])
    op.create_table(
        "step_transcripts",
        sa.Column("work_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["work_id", "code"],
            ["progress_steps.work_id", "progress_steps.code"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("work_id", "code", "session_id"),
    )
    op.create_table(
        "step_timings",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("work_id", sa.Uuid(), nullable=False),
        sa.Column("kind_code", sa.Text(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration", sa.Integer(), nullable=False),
        sa.Column("listed_ahead", sa.Boolean(), nullable=True),
        sa.Column("marked", sa.Boolean(), nullable=True),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column("key", sa.Text(), nullable=True),
        sa.Column("repo", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "(code IS NULL) <> (key IS NULL)", name="ck_step_timings_code_or_key"
        ),
        sa.CheckConstraint(
            "key IS NULL OR repo IS NOT NULL", name="ck_step_timings_seeded_repo"
        ),
        sa.CheckConstraint(
            "key IS NULL OR marked IS NULL", name="ck_step_timings_seeded_marked"
        ),
        sa.CheckConstraint("duration >= 0", name="ck_step_timings_duration"),
        sa.ForeignKeyConstraint(["work_id"], ["work.id"]),
        sa.ForeignKeyConstraint(["kind_code"], ["step_kinds.code"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("work_id", "code", name="uq_step_timings_work_id_code"),
    )
    op.create_index(
        "uq_step_timings_repo_key",
        "step_timings",
        ["repo", "key"],
        unique=True,
        postgresql_where=sa.text("key IS NOT NULL"),
    )
    op.create_index(
        "ix_step_timings_kind_code_ended_at",
        "step_timings",
        ["kind_code", "ended_at"],
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_table("step_timings")
    op.drop_table("step_transcripts")
    op.drop_constraint(
        "progress_steps_kind_code_fkey", "progress_steps", type_="foreignkey"
    )
    op.drop_column("progress_steps", "marked")
    op.drop_column("progress_steps", "listed_ahead")
    op.drop_column("progress_steps", "kind_code")
    op.drop_table("step_kinds")
