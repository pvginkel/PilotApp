"""Commits and file edits.

Slice 052 (DB §2.9; assertions 557 and 577 to 581): `commits`, a Commit held
from the Tool Call that made it or given by its Repository's history;
`files`, with the class the labeller gives each; `file_changes`, a Commit's
lines per File; and `file_edits`, a Tool Call's.

Revision ID: 0059
Revises: 0058
Create Date: 2026-11-26

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0059"
down_revision: str | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        "commits",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("repository_id", sa.BigInteger(), nullable=False),
        sa.Column("sha", sa.Text(), nullable=True),
        sa.Column("made_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("tool_call_id", sa.BigInteger(), nullable=True),
        sa.Column("lines_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "tool_call_id IS NOT NULL OR lines_read_at IS NOT NULL",
            name="ck_commits_source",
        ),
        sa.CheckConstraint(
            "(made_at IS NULL) = (lines_read_at IS NULL)"
            " AND (lines_read_at IS NULL OR sha IS NOT NULL)",
            name="ck_commits_read",
        ),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"]),
        sa.ForeignKeyConstraint(
            ["tool_call_id"], ["tool_calls.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "repository_id"),
        sa.UniqueConstraint("repository_id", "sha"),
    )
    op.create_index("ix_commits_tool_call_id", "commits", ["tool_call_id"])
    op.create_table(
        "files",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("repository_id", sa.BigInteger(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("class_code", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["class_code"], ["file_classes.code"]),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "repository_id"),
        sa.UniqueConstraint("repository_id", "path"),
    )
    op.create_table(
        "file_changes",
        sa.Column("commit_id", sa.BigInteger(), nullable=False),
        sa.Column("file_id", sa.BigInteger(), nullable=False),
        sa.Column("repository_id", sa.BigInteger(), nullable=False),
        sa.Column("lines_added", sa.Integer(), nullable=False),
        sa.Column("lines_removed", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "lines_added >= 0 AND lines_removed >= 0", name="ck_file_changes_lines"
        ),
        sa.ForeignKeyConstraint(
            ["commit_id", "repository_id"],
            ["commits.id", "commits.repository_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["file_id", "repository_id"], ["files.id", "files.repository_id"]
        ),
        sa.PrimaryKeyConstraint("commit_id", "file_id"),
    )
    op.create_table(
        "file_edits",
        sa.Column("tool_call_id", sa.BigInteger(), nullable=False),
        sa.Column("file_id", sa.BigInteger(), nullable=False),
        sa.Column("lines_added", sa.Integer(), nullable=False),
        sa.Column("lines_removed", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "lines_added >= 0 AND lines_removed >= 0", name="ck_file_edits_lines"
        ),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"]),
        sa.ForeignKeyConstraint(
            ["tool_call_id"], ["tool_calls.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("tool_call_id", "file_id"),
    )


def downgrade() -> None:
    """Downgrade database schema: every Commit, File and edit is lost."""
    op.drop_table("file_edits")
    op.drop_table("file_changes")
    op.drop_table("files")
    op.drop_index("ix_commits_tool_call_id", table_name="commits")
    op.drop_table("commits")
