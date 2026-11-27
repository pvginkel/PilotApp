"""The Files with no class.

Slice 052 (DB §2.9, File's `class?`): `ix_files_unclassed`, the Files the
labeller has not classed, which a collector asks for at every walk, so that a
walk where none waits reads no File (F158.5).

Revision ID: 0060
Revises: 0059
Create Date: 2026-11-27

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0060"
down_revision: str | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_index(
        "ix_files_unclassed",
        "files",
        ["id"],
        postgresql_where=sa.text("class_code IS NULL"),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index("ix_files_unclassed", table_name="files")
