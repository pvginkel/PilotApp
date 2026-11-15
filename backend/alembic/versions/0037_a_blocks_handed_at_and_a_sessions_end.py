"""A Block's `handed_at`, and the ended Sessions' `ended_at`.

Slice 048, P4 (DB decision 79; Block's `handed_at`, Session's `ended_at`):
`blocks.handed_at`, when the Block last came from Pilot's side to a person's
to answer, the server's and none on every Block there is: none is
back-filled. And `sessions.ended_at`, which nothing wrote, set on every
Session that is `ended`: the one move there is a project chat's close on its
timeout, whose transaction wrote the chat's `closed_at`.

Revision ID: 0037
Revises: 0036
Create Date: 2026-11-16

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column(
        "blocks", sa.Column("handed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        "UPDATE sessions SET ended_at = chats.closed_at FROM chats"
        " WHERE chats.id = sessions.id AND sessions.state_code = 'ended'"
        " AND sessions.ended_at IS NULL"
    )


def downgrade() -> None:
    """Downgrade database schema: every `handed_at` is lost, and no Session
    has an `ended_at`, as before this revision."""
    op.execute("UPDATE sessions SET ended_at = NULL")
    op.drop_column("blocks", "handed_at")
