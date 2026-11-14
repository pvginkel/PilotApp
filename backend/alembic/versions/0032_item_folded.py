"""An Item's `folded`.

Slice 042, P7 (DB decision 75): an open Item folded on the timeline, its head
and about three lines, the same for every member, set and cleared by a
person's fold and unfold and cleared by the Item's close, so that no done
Item is folded (DB 316 to 318).

Revision ID: 0032
Revises: 0031
Create Date: 2026-11-13

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column(
        "items",
        sa.Column("folded", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_check_constraint(
        "ck_items_folded", "items", "NOT folded OR done_at IS NULL"
    )


def downgrade() -> None:
    """Downgrade database schema: every fold is lost."""
    op.drop_constraint("ck_items_folded", "items", type_="check")
    op.drop_column("items", "folded")
