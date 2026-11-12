"""A person's `join_calls`.

Slice 045, P2 (DB decision 77; 339; F134.2): the profile page's switch *Join
projects started on my behalf*, a person's opt-out as `alarms` is, on for
every row there is.

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-12

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column(
        "users",
        sa.Column("join_calls", sa.Boolean(), server_default=sa.true(), nullable=False),
    )


def downgrade() -> None:
    """Downgrade database schema: where each person's switch stood is
    dropped."""
    op.drop_column("users", "join_calls")
