"""A Launch carries the Session and the Turn of Pilot's that started it.

`launches.session_id` and `turn_seq`: the Session that ran the Launch, held
once, and with it the Turn that started it, a Turn of that Session (DB
decision 79 point 7; assertions 385, 386 and 537). `ix_sessions_conversation_id`
is read by every publication, which looks for the Sessions of its
conversation (DB 538).

Revision ID: 0041
Revises: 0040
Create Date: 2026-11-16

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column("launches", sa.Column("session_id", sa.Uuid(), nullable=True))
    op.add_column("launches", sa.Column("turn_seq", sa.Integer(), nullable=True))
    op.create_foreign_key(None, "launches", "sessions", ["session_id"], ["id"])
    op.create_foreign_key(
        None,
        "launches",
        "turns",
        ["session_id", "turn_seq"],
        ["session_id", "seq"],
    )
    op.create_check_constraint(
        "ck_launches_turn",
        "launches",
        "turn_seq IS NULL OR session_id IS NOT NULL",
    )
    op.create_index(
        "ix_sessions_conversation_id",
        "sessions",
        ["conversation_id"],
        postgresql_where=sa.text("conversation_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index("ix_sessions_conversation_id", table_name="sessions")
    op.drop_constraint("ck_launches_turn", "launches", type_="check")
    op.drop_column("launches", "turn_seq")
    op.drop_column("launches", "session_id")
