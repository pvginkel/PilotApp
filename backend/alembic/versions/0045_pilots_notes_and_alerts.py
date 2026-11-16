"""Pilot Note and Send Alert.

Slice 062 (DB decision 84, assertions 616 to 627, 631 and 632): Pilot's note
on a Prose Item, on one Block of its Document or on the Prose Item as a
whole, and its alert that another open ask, the Block it awaits, comes
before this one's Send, each written at a call of a Turn of Pilot's; of a
place's notes and of a Prose Item's alerts the latest stands, the earlier
kept. The notices already on the timelines stay notices: nothing is
backfilled.

Revision ID: 0045
Revises: 0044
Create Date: 2026-11-16

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        "pilot_notes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("block_id", sa.BigInteger(), nullable=True),
        sa.Column("turn_id", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("suggested_answer", sa.Text(), nullable=True),
        sa.Column("suggested_note", sa.Text(), nullable=True),
        sa.Column("offer", sa.Text(), nullable=True),
        sa.Column("offer_taken_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("offer_taken_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "text IS NOT NULL OR suggested_answer IS NOT NULL"
            " OR suggested_note IS NOT NULL OR offer IS NOT NULL",
            name="ck_pilot_notes_holds",
        ),
        sa.CheckConstraint(
            "block_id IS NOT NULL OR (suggested_answer IS NULL"
            " AND suggested_note IS NULL AND offer IS NULL)",
            name="ck_pilot_notes_on_the_item",
        ),
        sa.CheckConstraint(
            "(offer_taken_at IS NULL) = (offer_taken_by_user_id IS NULL)"
            " AND (offer_taken_at IS NULL OR offer IS NOT NULL)",
            name="ck_pilot_notes_offer_taken",
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.ForeignKeyConstraint(["block_id"], ["blocks.id"]),
        sa.ForeignKeyConstraint(["turn_id"], ["turns.id"]),
        sa.ForeignKeyConstraint(["offer_taken_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pilot_notes_item_id_block_id_id",
        "pilot_notes",
        ["item_id", "block_id", "id"],
    )
    op.create_table(
        "send_alerts",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("awaits_block_id", sa.BigInteger(), nullable=False),
        sa.Column("turn_id", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.ForeignKeyConstraint(["awaits_block_id"], ["blocks.id"]),
        sa.ForeignKeyConstraint(["turn_id"], ["turns.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_send_alerts_item_id_id", "send_alerts", ["item_id", "id"])


def downgrade() -> None:
    """Downgrade database schema: every note and alert Pilot wrote is lost."""
    op.drop_table("send_alerts")
    op.drop_table("pilot_notes")
