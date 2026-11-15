"""The Hold.

Slice 048, P2 (DB decision 79, assertions 360 to 362 and 559): Hold Kind,
Pilot's own closed list, an enum (DB §7.2), the gate's eight reasons; and
`holds`, one row for each period in which the gate kept one Session waiting
for one reason, at most one of a Session open at a time. No Hold is
back-filled: a Session held as this revision runs gets its Hold when the
gate is next read for it.

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HOLD_KIND = (
    "week_halt",
    "five_hour_halt",
    "pause",
    "store_update",
    "outage",
    "slot",
    "queue",
    "conversation",
)


def upgrade() -> None:
    """Upgrade database schema."""
    postgresql.ENUM(*HOLD_KIND, name="hold_kind").create(op.get_bind())
    op.create_table(
        "holds",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind_code",
            postgresql.ENUM(name="hold_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("ended_at >= started_at", name="ck_holds_period"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_holds_open_session_id",
        "holds",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade database schema: every Hold is lost."""
    op.drop_index(
        "uq_holds_open_session_id",
        table_name="holds",
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.drop_table("holds")
    postgresql.ENUM(name="hold_kind").drop(op.get_bind())
