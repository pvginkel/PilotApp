"""A registered document's failed read.

Slice 009, ruling D1: a registered document whose file the read at the end of
its run could not read or parse keeps no text; `read_failed_at`, when that
read was made, tells it from one still awaiting its read, so that it takes its
closes and is not read again (review 7).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-25

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column(
        "documents",
        sa.Column("read_failed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_documents_read_failed",
        "documents",
        "read_failed_at IS NULL"
        " OR (source_path IS NOT NULL AND published_text IS NULL)",
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_constraint("ck_documents_read_failed", "documents")
    op.drop_column("documents", "read_failed_at")
