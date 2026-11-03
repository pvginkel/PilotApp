"""Done Cause's `cancelled`.

Slice 036, P5: a person's Cancel on an open registered document of a run that
holds a Block of another document closes every open document of that run at
once, done `cancelled`, which offers no undo; the run is ended (DB decision
72).

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-03

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.execute(
        "INSERT INTO done_causes (code, name, undo_offered)"
        " VALUES ('cancelled', 'Cancelled', false)"
    )


def downgrade() -> None:
    """Downgrade database schema: the row deleted; an item done `cancelled`
    fails the delete."""
    op.execute("DELETE FROM done_causes WHERE code = 'cancelled'")
