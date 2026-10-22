"""Item.title none while a Prose Item's text gives none.

DB decision 50: a Prose Item's `title` is read from its published text alone,
with no stored fallback, and a registered document's text may give none (DB
assertion 223).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-22

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.alter_column("items", "title", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    """Downgrade database schema."""
    op.alter_column("items", "title", existing_type=sa.Text(), nullable=False)
