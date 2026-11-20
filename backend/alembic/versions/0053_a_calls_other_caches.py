"""A Call's other caches, a Transcript's first and last Call's time, and the
Step Transcripts by the conversation they name.

Slice 053 (DB §2.7, Call; §7.4; decisions 79.7 and 79.14; assertions 538,
543 and 546): on `calls` the derived caches `waited_seconds`, `rewind`,
`cache_miss`, `past_ttl` and `launch_id`, the Launch it was made in; on
`transcripts` `first_call_at` and `last_call_at`; and the index a placement
reads the Step Transcripts of one conversation through.

No cache is derived here: the step that follows the revisions derives them
for every Call stored with none, and gives those Calls' Transcripts their
two times (`app/services/call_caches.py`). `ix_calls_underived` holds the
Calls that step derives at every deploy.

Revision ID: 0053
Revises: 0052
Create Date: 2026-11-20

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column("calls", sa.Column("waited_seconds", sa.Double(), nullable=True))
    op.add_column("calls", sa.Column("rewind", sa.Boolean(), nullable=True))
    op.add_column("calls", sa.Column("cache_miss", sa.Boolean(), nullable=True))
    op.add_column("calls", sa.Column("past_ttl", sa.Boolean(), nullable=True))
    op.add_column("calls", sa.Column("launch_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "calls_launch_id_fkey",
        "calls",
        "launches",
        ["launch_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_calls_derived",
        "calls",
        "(rewind IS NULL) = (cache_miss IS NULL)"
        " AND (rewind IS NULL) = (past_ttl IS NULL)",
    )
    op.create_index(
        "ix_calls_underived",
        "calls",
        ["id"],
        postgresql_where=sa.text("rewind IS NULL"),
    )
    op.create_index("ix_calls_launch_id", "calls", ["launch_id"])
    op.add_column(
        "transcripts",
        sa.Column("first_call_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "transcripts",
        sa.Column("last_call_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_transcripts_call_times",
        "transcripts",
        "(first_call_at IS NULL) = (last_call_at IS NULL)",
    )
    op.create_index(
        "ix_step_transcripts_session_id", "step_transcripts", ["session_id"]
    )


def downgrade() -> None:
    """Downgrade database schema: each Call's caches and each Transcript's
    two times go with their columns."""
    op.drop_index("ix_step_transcripts_session_id", table_name="step_transcripts")
    op.drop_constraint("ck_transcripts_call_times", "transcripts", type_="check")
    op.drop_column("transcripts", "last_call_at")
    op.drop_column("transcripts", "first_call_at")
    op.drop_index("ix_calls_launch_id", table_name="calls")
    op.drop_index("ix_calls_underived", table_name="calls")
    op.drop_constraint("ck_calls_derived", "calls", type_="check")
    op.drop_constraint("calls_launch_id_fkey", "calls", type_="foreignkey")
    op.drop_column("calls", "launch_id")
    op.drop_column("calls", "past_ttl")
    op.drop_column("calls", "cache_miss")
    op.drop_column("calls", "rewind")
    op.drop_column("calls", "waited_seconds")
