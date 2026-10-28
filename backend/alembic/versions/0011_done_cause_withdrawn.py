"""Done Cause's `withdrawn`.

Slice 025, P4: an Undo of an item of Pilot's own before the brief of the job
its close placed went out withdraws that job, which never starts: its work
item is done `withdrawn`, which offers no undo (F14.1; DB Work Trigger
`item_done`).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-28

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.execute(
        "INSERT INTO done_causes (code, name, undo_offered)"
        " VALUES ('withdrawn', 'Withdrawn', false)"
    )


def downgrade() -> None:
    """Downgrade database schema: the row deleted; an item done `withdrawn`
    fails the delete."""
    op.execute("DELETE FROM done_causes WHERE code = 'withdrawn'")
