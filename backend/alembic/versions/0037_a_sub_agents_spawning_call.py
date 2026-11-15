"""A sub-agent's thread holds the name of its spawning call.

`transcripts.spawned_by_tool_use_id`: the `tool_use_id` a sub-agent's record
names its spawning Tool Call by, held from the thread's own publication, so
that the thread is joined to that Tool Call whichever of the two is published
first (DB decision 79.16; assertions 380 and 534).

Revision ID: 0037
Revises: 0036
Create Date: 2026-11-16

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column(
        "transcripts",
        sa.Column("spawned_by_tool_use_id", sa.Text(), nullable=True),
    )
    op.drop_constraint("ck_transcripts_main_thread", "transcripts", type_="check")
    op.create_check_constraint(
        "ck_transcripts_main_thread",
        "transcripts",
        "agent_id IS NOT NULL OR (main_id IS NULL AND spawned_by_id IS NULL"
        " AND spawned_by_tool_use_id IS NULL)",
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_constraint("ck_transcripts_main_thread", "transcripts", type_="check")
    op.drop_column("transcripts", "spawned_by_tool_use_id")
    op.create_check_constraint(
        "ck_transcripts_main_thread",
        "transcripts",
        "agent_id IS NOT NULL OR (main_id IS NULL AND spawned_by_id IS NULL)",
    )
