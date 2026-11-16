"""Conversation, Session Kind `conversation` and Close Cause's `ended`.

Slice 059 (DB decision 77, assertions 330 to 337): a Conversation, a
subtype of Session beside Chat, holds one exchange of messages between a
session outside Pilot and Pilot about one Project. Its row is keyed by its
Session's id and names the Environment its opener called from and that
caller's session; it closes once, with its cause, `ended` its caller's end
and never a Chat's, `created` a Chat's alone.

Revision ID: 0035
Revises: 0034
Create Date: 2026-11-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CLOSE_CAUSE = ("timeout", "created", "finished", "reopened", "archived")


def upgrade() -> None:
    """Upgrade database schema."""
    # PostgreSQL refuses a new enum value in the transaction that added it,
    # and the check on a chat's close reads `ended`.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE close_cause ADD VALUE 'ended'")

    op.execute(
        "INSERT INTO session_kinds (code, name, surface, on_timeline)"
        " VALUES ('conversation', 'Conversation', 'pilot-store', false)"
    )
    op.create_check_constraint(
        "ck_chats_close_cause", "chats", "close_cause_code <> 'ended'"
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("session_kind_code", sa.Text(), nullable=False),
        sa.Column("caller_environment_id", sa.Text(), nullable=False),
        sa.Column("caller_session", sa.Text(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "close_cause_code",
            postgresql.ENUM(name="close_cause", create_type=False),
            nullable=True,
        ),
        sa.CheckConstraint(
            "session_kind_code = 'conversation'",
            name="ck_conversations_session_kind",
        ),
        sa.CheckConstraint(
            "(closed_at IS NULL) = (close_cause_code IS NULL)",
            name="ck_conversations_close",
        ),
        sa.CheckConstraint(
            "close_cause_code <> 'created'", name="ck_conversations_close_cause"
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "id", "session_kind_code"],
            ["sessions.project_id", "sessions.id", "sessions.kind_code"],
        ),
        sa.ForeignKeyConstraint(["caller_environment_id"], ["environments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversations_caller_environment_id",
        "conversations",
        ["caller_environment_id"],
    )


def downgrade() -> None:
    """Downgrade database schema: every conversation is lost with its table,
    its Session's rows staying, which fail the delete of their kind; the enum
    rebuilt without `ended`, which PostgreSQL drops no value of in place."""
    op.drop_index("ix_conversations_caller_environment_id", "conversations")
    op.drop_table("conversations")
    op.drop_constraint("ck_chats_close_cause", "chats", type_="check")
    op.execute("DELETE FROM session_kinds WHERE code = 'conversation'")
    op.execute("ALTER TYPE close_cause RENAME TO close_cause_0035")
    postgresql.ENUM(*CLOSE_CAUSE, name="close_cause").create(op.get_bind())
    op.execute(
        "ALTER TABLE chats ALTER COLUMN close_cause_code"
        " TYPE close_cause USING close_cause_code::text::close_cause"
    )
    op.execute("DROP TYPE close_cause_0035")
