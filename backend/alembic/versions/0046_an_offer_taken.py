"""An offer taken: the job it places.

Slice 062 (DB decision 84, assertions 629 and 630): Work Trigger's
`offer_taken`, the trigger of the job a member's press of a Pilot Note's
offer places, and `work.trigger_note_id`, the Pilot Note that job names,
set exactly for that trigger and with no trigger Item beside it. Nothing is
backfilled: no offer was taken before.

Revision ID: 0046
Revises: 0045
Create Date: 2026-11-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WORK_TRIGGER = ("setup", "worker_turn_ended", "item_done", "wait_fired")


def upgrade() -> None:
    """Upgrade database schema."""
    # PostgreSQL refuses a new enum value in the transaction that added it,
    # and the check on an offer's job reads `offer_taken`.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE work_trigger ADD VALUE 'offer_taken'")

    op.add_column("work", sa.Column("trigger_note_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(None, "work", "pilot_notes", ["trigger_note_id"], ["id"])
    op.create_check_constraint(
        "ck_work_trigger_note",
        "work",
        "(trigger_note_id IS NOT NULL)"
        " = (trigger_code IS NOT DISTINCT FROM 'offer_taken')"
        " AND (trigger_note_id IS NULL OR trigger_item_id IS NULL)",
    )


def downgrade() -> None:
    """Downgrade database schema: Work Trigger rebuilt without `offer_taken`,
    which PostgreSQL drops no value of in place; an offer's job fails the
    cast."""
    op.drop_constraint("ck_work_trigger_note", "work", type_="check")
    op.drop_column("work", "trigger_note_id")
    op.execute("ALTER TYPE work_trigger RENAME TO work_trigger_0045")
    postgresql.ENUM(*WORK_TRIGGER, name="work_trigger").create(op.get_bind())
    op.execute(
        "ALTER TABLE work ALTER COLUMN trigger_code"
        " TYPE work_trigger USING trigger_code::text::work_trigger"
    )
    op.execute("DROP TYPE work_trigger_0045")
