"""Confirmation Reason's `standing-grant`.

Slice 026, P1: a standing grant, a permission meant to outlast the project or
reach past it, of the kept column, which the switch never answers (F54.3; DB
Confirmation Reason, decision 34).

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-29

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.execute(
        "INSERT INTO confirmation_reasons"
        " (code, name, asks_under_autopilot, description)"
        " VALUES ('standing-grant', 'Standing grant', true,"
        " 'A standing grant, a permission meant to outlast the project or reach"
        " past it, of the kept column: asked under auto pilot too.')"
    )


def downgrade() -> None:
    """Downgrade database schema: the row deleted; a block `because:
    standing-grant` fails the delete."""
    op.execute("DELETE FROM confirmation_reasons WHERE code = 'standing-grant'")
