"""A registered document's refused write-back.

Slice 009, P7: once a registered document is closed, its text, the answers in
it, is written back to the file it was registered from (F65.1).
`written_back_at` says when it was; `write_back_refused_at`, when the
controller refused it for what is wrong with the file, its path or its
environment, so that the write is not made again until the document's next
close.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-25

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column(
        "documents",
        sa.Column("write_back_refused_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_documents_write_back_refused",
        "documents",
        "write_back_refused_at IS NULL"
        " OR (source_path IS NOT NULL AND published_text IS NOT NULL"
        " AND written_back_at IS NULL)",
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_constraint("ck_documents_write_back_refused", "documents")
    op.drop_column("documents", "write_back_refused_at")
