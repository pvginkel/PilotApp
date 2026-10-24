"""Pilot's own environments.

DB decision 56: Environment's `server_created_at`, `repo` and `delete_due_at`
with the delete timer's and the take's indexes (DB §7.6); Work's `repo`; a
Session's Environment none while its start is held (DB 107); Sync Outcome
struck with Repository Sync.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column(
        "environments",
        sa.Column("server_created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("environments", sa.Column("repo", sa.Text(), nullable=True))
    op.add_column(
        "environments",
        sa.Column("delete_due_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_environments_repo",
        "environments",
        "(server_created_at IS NULL) = (repo IS NULL)",
    )
    op.create_check_constraint(
        "ck_environments_delete_due_at",
        "environments",
        "delete_due_at IS NULL OR server_created_at IS NOT NULL",
    )
    op.create_index(
        "ix_environments_delete_due_at",
        "environments",
        ["delete_due_at"],
        postgresql_where=sa.text("delete_due_at IS NOT NULL"),
    )
    op.create_index(
        "ix_environments_repo",
        "environments",
        ["repo"],
        postgresql_where=sa.text("server_created_at IS NOT NULL"),
    )
    op.add_column("work", sa.Column("repo", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_work_repo", "work", "session_kind_code = 'work' OR repo IS NULL"
    )
    op.alter_column("sessions", "environment_id", nullable=True)
    postgresql.ENUM(name="sync_outcome").drop(op.get_bind())


def downgrade() -> None:
    """Downgrade database schema."""
    postgresql.ENUM("pulled", "rebased", "skipped", name="sync_outcome").create(
        op.get_bind()
    )
    op.alter_column("sessions", "environment_id", nullable=False)
    op.drop_constraint("ck_work_repo", "work")
    op.drop_column("work", "repo")
    op.drop_index("ix_environments_repo", table_name="environments")
    op.drop_index("ix_environments_delete_due_at", table_name="environments")
    op.drop_constraint("ck_environments_delete_due_at", "environments")
    op.drop_constraint("ck_environments_repo", "environments")
    op.drop_column("environments", "delete_due_at")
    op.drop_column("environments", "repo")
    op.drop_column("environments", "server_created_at")
