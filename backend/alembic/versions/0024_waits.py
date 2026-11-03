"""Wait, with Card Wait and Timed Wait, Wait Firing and Card Transition.

Slice 027, P2: the brain adds a card wait or a timed wait through `add_item`,
which the server fires on a matching Card Transition, at its due time or on a
person's request, each firing a row on the wait, and the brain closes it
through `mark` with a note (DB decisions 46 and 73, assertions 184 to 200 and
300).

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_unique_constraint(None, "items", ["id", "kind_code"])
    op.create_table(
        "waits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind_code", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cards", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("states", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("done_note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "kind_code IN ('card_wait', 'timed_wait')", name="ck_waits_kind"
        ),
        sa.CheckConstraint(
            "(kind_code = 'timed_wait') = (due_at IS NOT NULL)"
            " AND (kind_code = 'card_wait') = (cards IS NOT NULL)"
            " AND (cards IS NULL) = (states IS NULL)"
            " AND (cards IS NULL"
            " OR (cardinality(cards) >= 1 AND cardinality(states) >= 1))",
            name="ck_waits_halves",
        ),
        sa.ForeignKeyConstraint(["id", "kind_code"], ["items.id", "items.kind_code"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "kind_code"),
    )
    op.create_index(
        "ix_waits_due_at",
        "waits",
        ["due_at"],
        postgresql_where=sa.text("due_at IS NOT NULL"),
    )
    op.create_index(
        "ix_waits_cards",
        "waits",
        ["cards"],
        postgresql_using="gin",
        postgresql_where=sa.text("cards IS NOT NULL"),
    )
    op.create_table(
        "card_transitions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("card", sa.Text(), nullable=False),
        sa.Column("from_state", sa.Text(), nullable=True),
        sa.Column("to_state", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("by", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "wait_firings",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("wait_id", sa.Uuid(), nullable=False),
        sa.Column("wait_kind_code", sa.Text(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column(
            "cause_code",
            postgresql.ENUM(name="firing_cause", create_type=False),
            nullable=False,
        ),
        sa.Column("transition_id", sa.BigInteger(), nullable=True),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("fired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("seq >= 1", name="ck_wait_firings_seq"),
        sa.CheckConstraint(
            "(cause_code = 'transition') = (transition_id IS NOT NULL)"
            " AND (cause_code = 'requested') = (requested_by_user_id IS NOT NULL)",
            name="ck_wait_firings_cause",
        ),
        sa.CheckConstraint(
            "(cause_code <> 'transition' OR wait_kind_code = 'card_wait')"
            " AND (cause_code <> 'due' OR wait_kind_code = 'timed_wait')",
            name="ck_wait_firings_kind",
        ),
        sa.ForeignKeyConstraint(
            ["wait_id", "wait_kind_code"], ["waits.id", "waits.kind_code"]
        ),
        sa.ForeignKeyConstraint(["transition_id"], ["card_transitions.id"]),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["work.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("wait_id", "seq"),
    )
    op.create_index(
        "uq_wait_firings_due",
        "wait_firings",
        ["wait_id"],
        unique=True,
        postgresql_where=sa.text("cause_code = 'due'"),
    )
    op.create_index(
        "uq_wait_firings_transition_id_wait_id",
        "wait_firings",
        ["transition_id", "wait_id"],
        unique=True,
        postgresql_where=sa.text("transition_id IS NOT NULL"),
    )
    op.create_index(
        "ix_wait_firings_pending",
        "wait_firings",
        ["wait_id"],
        postgresql_where=sa.text("job_id IS NULL"),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index("ix_wait_firings_pending", "wait_firings")
    op.drop_index("uq_wait_firings_transition_id_wait_id", "wait_firings")
    op.drop_index("uq_wait_firings_due", "wait_firings")
    op.drop_table("wait_firings")
    op.drop_table("card_transitions")
    op.drop_index("ix_waits_cards", "waits")
    op.drop_index("ix_waits_due_at", "waits")
    op.drop_table("waits")
    op.drop_constraint("items_id_kind_code_key", "items")
