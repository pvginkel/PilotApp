"""A Work's `done_note`.

Slice 042, P9 (DB decision 78): Pilot's reason for closing a stopped work
item for good, the words `stop_work` gave, set with its Item's `done_at` at
that close and never changed; none for a Work a person closed, for one done
any other way and for an open one (DB 346).

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-13

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column("work", sa.Column("done_note", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade database schema: every reason of a close is lost."""
    op.drop_column("work", "done_note")
