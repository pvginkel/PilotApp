"""Chats, their reads, the effects, the writer's questions and a Turn's words.

Slice 022, P2: DB §2.3's Chat, Effect and Writer Question and §2.1's Chat
Read; Close Cause's `finished` and `reopened` (DB decision 57); Turn's
`words` beside its `message` (DB decision 59), a person's Turn written before
it given its message as its words, since nothing was sent before them
(assertion 251).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CLOSE_CAUSE = ("timeout", "created")


def upgrade() -> None:
    """Upgrade database schema."""
    op.execute("ALTER TYPE close_cause ADD VALUE 'finished'")
    op.execute("ALTER TYPE close_cause ADD VALUE 'reopened'")

    op.add_column("turns", sa.Column("words", sa.Text(), nullable=True))
    op.execute("UPDATE turns SET words = message WHERE author_user_id IS NOT NULL")
    op.create_check_constraint(
        "ck_turns_words",
        "turns",
        "(author_user_id IS NULL) = (words IS NULL)"
        " AND (words IS NOT NULL"
        " OR (quote_item_id IS NULL AND quote_block_id IS NULL))",
    )

    op.create_table(
        "chats",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("session_kind_code", sa.Text(), nullable=False),
        sa.Column(
            "kind_code",
            postgresql.ENUM(name="chat_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "close_cause_code",
            postgresql.ENUM(name="close_cause", create_type=False),
            nullable=True,
        ),
        sa.CheckConstraint("session_kind_code = 'chat'", name="ck_chats_session_kind"),
        sa.CheckConstraint(
            "(closed_at IS NULL) = (close_cause_code IS NULL)", name="ck_chats_close"
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "id", "session_kind_code"],
            ["sessions.project_id", "sessions.id", "sessions.kind_code"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_chats_open",
        "chats",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("closed_at IS NULL"),
    )

    op.create_table(
        "chat_reads",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "project_id"),
    )

    op.create_table(
        "effects",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("turn_id", sa.BigInteger(), nullable=False),
        sa.Column("record_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "kind_code",
            postgresql.ENUM(name="effect_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("item_id", sa.Uuid(), nullable=True),
        sa.Column("block_id", sa.BigInteger(), nullable=True),
        sa.Column("attachment_id", sa.Uuid(), nullable=True),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(kind_code IN ('added', 'marked', 'stopped', 'registered'))"
            " = (item_id IS NOT NULL)"
            " AND (kind_code = 'attached') = (attachment_id IS NOT NULL)"
            " AND (kind_code = 'answered' OR block_id IS NULL)",
            name="ck_effects_names",
        ),
        sa.ForeignKeyConstraint(["turn_id"], ["turns.id"]),
        sa.ForeignKeyConstraint(["record_id"], ["session_records.id"]),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.ForeignKeyConstraint(["block_id"], ["blocks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["attachment_id"], ["attachments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_effects_turn_id", "effects", ["turn_id"])
    op.create_index("ix_effects_block_id", "effects", ["block_id"])

    op.create_table(
        "writer_questions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("turn_id", sa.BigInteger(), nullable=False),
        sa.Column("block_id", sa.BigInteger(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column(
            "asked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["turn_id"], ["turns.id"]),
        sa.ForeignKeyConstraint(["block_id"], ["blocks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_writer_questions_turn_id", "writer_questions", ["turn_id"])
    op.create_index(
        "uq_writer_questions_block_id", "writer_questions", ["block_id"], unique=True
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_table("writer_questions")
    op.drop_table("effects")
    op.drop_table("chat_reads")
    op.drop_table("chats")
    op.drop_constraint("ck_turns_words", "turns")
    op.drop_column("turns", "words")
    # PostgreSQL drops no enum value in place; no column holds the type now.
    bind = op.get_bind()
    postgresql.ENUM(name="close_cause").drop(bind)
    postgresql.ENUM(*CLOSE_CAUSE, name="close_cause").create(bind)
