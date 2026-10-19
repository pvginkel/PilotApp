"""Turns and Session Records.

DB §2.3's Turn and Session Record, and Session's `current_line`; DB §2.4's
Record Kind in place of the first revision's `line_kind`, which decision 49
replaced before anything used it.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RECORD_KIND = ("claude", "send", "server", "result")
LINE_KIND = ("log", "message", "server")


def upgrade() -> None:
    """Upgrade database schema."""
    bind = op.get_bind()
    postgresql.ENUM(name="line_kind").drop(bind)
    postgresql.ENUM(*RECORD_KIND, name="record_kind").create(bind)

    op.add_column(
        "sessions",
        sa.Column("current_line", postgresql.JSONB(), nullable=True),
    )
    op.create_table(
        "turns",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("quote_item_id", sa.Uuid(), nullable=True),
        sa.Column("quote_block_id", sa.BigInteger(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint("seq >= 1", name="ck_turns_seq"),
        sa.CheckConstraint(
            "quote_item_id IS NULL OR quote_block_id IS NULL", name="ck_turns_quote"
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["quote_item_id"], ["items.id"]),
        sa.ForeignKeyConstraint(["quote_block_id"], ["blocks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "seq"),
        sa.UniqueConstraint("session_id", "id"),
    )
    op.create_table(
        "session_records",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("turn_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "kind_code",
            postgresql.ENUM(*RECORD_KIND, name="record_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("raw_offset", sa.BigInteger(), nullable=True),
        sa.Column("controller_session", sa.Text(), nullable=True),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("seq >= 1", name="ck_session_records_seq"),
        sa.CheckConstraint(
            "(kind_code IN ('claude', 'result')) = (raw_offset IS NOT NULL)"
            " AND (kind_code IN ('claude', 'result')) = (controller_session IS NOT NULL)"
            " AND (kind_code NOT IN ('claude', 'result') OR turn_id IS NOT NULL)",
            name="ck_session_records_stream",
        ),
        sa.CheckConstraint(
            "kind_code <> 'claude'"
            " OR payload ->> 'type' IS DISTINCT FROM 'stream_event'",
            name="ck_session_records_partial",
        ),
        sa.CheckConstraint(
            "(kind_code = 'send') = (payload IS NULL)"
            " AND (kind_code <> 'send' OR turn_id IS NOT NULL)",
            name="ck_session_records_send",
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(
            ["session_id", "turn_id"], ["turns.session_id", "turns.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "seq"),
    )
    op.create_index(
        "uq_session_records_send_turn_id",
        "session_records",
        ["turn_id"],
        unique=True,
        postgresql_where=sa.text("kind_code = 'send'"),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_table("session_records")
    op.drop_table("turns")
    op.drop_column("sessions", "current_line")
    bind = op.get_bind()
    postgresql.ENUM(name="record_kind").drop(bind)
    postgresql.ENUM(*LINE_KIND, name="line_kind").create(bind)
