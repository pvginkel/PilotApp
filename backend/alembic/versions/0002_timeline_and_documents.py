"""Timeline and documents.

DB §2.2's Item, Document (with Prose Item's and Project Document's columns,
DB §7.3), Document Version, Save Error, Block, Block Option, Item Attachment
and Plan Note Reference, and DB §2.1's Attachment. A document's texts are
compressed with lz4 (DB §7.1).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18

"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The enum types are the first revision's.
ENUM_VALUES: dict[str, tuple[str, ...]] = {
    "document_role": ("draft", "handbook"),
    "version_cause": ("born", "registered", "turn", "done"),
    "error_kind": ("parse", "reverted"),
    "block_kind": ("decision", "question", "action"),
    "answer_channel": ("app", "chat", "recommended", "autopilot"),
    "attachment_source": ("file", "draft"),
}

COMPRESSED_COLUMNS = (
    ("documents", "ingested_text"),
    ("documents", "published_text"),
    ("document_versions", "text"),
)


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*ENUM_VALUES[name], name=name, create_type=False)


def _timestamp(name: str, *, nullable: bool = True) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _created_at() -> sa.Column[datetime]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    """Upgrade database schema."""
    _create_items()
    _create_documents()
    _create_save_errors()
    _create_blocks()
    _create_attachments()
    op.create_table(
        "plan_note_references",
        sa.Column("plan_note_id", sa.BigInteger(), nullable=False),
        sa.Column("block_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["plan_note_id"], ["plan_notes.id"]),
        sa.ForeignKeyConstraint(["block_id"], ["blocks.id"]),
        sa.PrimaryKeyConstraint("plan_note_id", "block_id"),
    )
    op.create_index(
        "ix_plan_note_references_block_id", "plan_note_references", ["block_id"]
    )

    for table, column in COMPRESSED_COLUMNS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET COMPRESSION lz4")


def _create_items() -> None:
    op.create_table(
        "items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind_code", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("plan_task_id", sa.Text(), nullable=True),
        sa.Column("urgent", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("for_user_id", sa.Uuid(), nullable=True),
        _created_at(),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_session_id", sa.Uuid(), nullable=True),
        _timestamp("done_at"),
        sa.Column("done_cause_code", sa.Text(), nullable=True),
        sa.Column("done_by_user_id", sa.Uuid(), nullable=True),
        _timestamp("consumed_at"),
        sa.Column("consumed_session_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("seq >= 1", name="ck_items_seq"),
        sa.CheckConstraint(
            "(created_by_user_id IS NULL) <> (created_by_session_id IS NULL)"
            " AND (created_by_user_id IS NULL OR kind_code = 'opening')",
            name="ck_items_created_by",
        ),
        sa.CheckConstraint(
            "(done_at IS NULL) = (done_cause_code IS NULL)"
            " AND (done_by_user_id IS NULL OR done_at IS NOT NULL)",
            name="ck_items_done",
        ),
        sa.CheckConstraint(
            "(consumed_at IS NULL) = (consumed_session_id IS NULL)",
            name="ck_items_consumed",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["kind_code"], ["item_kinds.code"]),
        sa.ForeignKeyConstraint(
            ["project_id", "plan_task_id"],
            ["plan_tasks.project_id", "plan_tasks.task_id"],
        ),
        sa.ForeignKeyConstraint(["for_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by_session_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["done_cause_code"], ["done_causes.code"]),
        sa.ForeignKeyConstraint(["done_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["consumed_session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "seq"),
    )
    op.create_index(
        "ix_items_open",
        "items",
        ["project_id", "seq"],
        postgresql_where=sa.text("done_at IS NULL"),
    )


def _create_documents() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("ingested_text", sa.Text(), nullable=True),
        sa.Column("ingested_hash", sa.Text(), nullable=True),
        _timestamp("ingested_at"),
        sa.Column("ingested_session_id", sa.Uuid(), nullable=True),
        sa.Column("published_text", sa.Text(), nullable=True),
        sa.Column("published_hash", sa.Text(), nullable=True),
        _timestamp("published_at"),
        sa.Column("writing_session_id", sa.Uuid(), nullable=True),
        _timestamp("writing_since"),
        _created_at(),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("source_environment_id", sa.Text(), nullable=True),
        sa.Column("source_path", sa.Text(), nullable=True),
        _timestamp("written_back_at"),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("role_code", _enum("document_role"), nullable=True),
        sa.CheckConstraint(
            "(project_id IS NULL) = (role_code IS NULL)"
            " AND (project_id IS NULL OR (summary IS NULL"
            " AND source_environment_id IS NULL AND source_path IS NULL"
            " AND written_back_at IS NULL))",
            name="ck_documents_subtype",
        ),
        sa.CheckConstraint(
            "(source_environment_id IS NULL) = (source_path IS NULL)",
            name="ck_documents_source",
        ),
        sa.CheckConstraint(
            "(ingested_text IS NULL) = (ingested_hash IS NULL)"
            " AND (ingested_text IS NULL) = (ingested_at IS NULL)"
            " AND (ingested_session_id IS NULL OR ingested_text IS NOT NULL)",
            name="ck_documents_ingested",
        ),
        sa.CheckConstraint(
            "(published_text IS NULL) = (published_hash IS NULL)"
            " AND (published_text IS NULL) = (published_at IS NULL)",
            name="ck_documents_published",
        ),
        sa.CheckConstraint(
            "(writing_session_id IS NULL) = (writing_since IS NULL)",
            name="ck_documents_writing",
        ),
        sa.ForeignKeyConstraint(["ingested_session_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["writing_session_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["source_environment_id"], ["environments.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_documents_project_path",
        "documents",
        ["project_id", "path"],
        unique=True,
        postgresql_where=sa.text("project_id IS NOT NULL"),
    )
    op.create_index(
        "uq_documents_project_role",
        "documents",
        ["project_id", "role_code"],
        unique=True,
        postgresql_where=sa.text("project_id IS NOT NULL"),
    )
    op.create_table(
        "document_versions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("cause_code", _enum("version_cause"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("hash", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        _created_at(),
        sa.CheckConstraint("number >= 1", name="ck_document_versions_number"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "number"),
    )


def _create_save_errors() -> None:
    op.create_table(
        "save_errors",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("environment_id", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("kind_code", _enum("error_kind"), nullable=False),
        sa.Column("line", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["environment_id"], ["environments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_save_errors_environment_id_path", "save_errors", ["environment_id", "path"]
    )


def _create_blocks() -> None:
    op.create_table(
        "blocks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("local_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind_code", _enum("block_kind"), nullable=False),
        sa.Column(
            "confirmation", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("because_code", sa.Text(), nullable=True),
        sa.Column("proposal", sa.Text(), nullable=True),
        sa.Column("default_value", sa.Text(), nullable=True),
        sa.Column("check_text", sa.Text(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("answered_by_user_id", sa.Uuid(), nullable=True),
        _timestamp("answered_at"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("via_code", _enum("answer_channel"), nullable=True),
        _timestamp("done_at"),
        sa.Column("deferred_to_task_id", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "NOT confirmation OR (kind_code = 'decision'"
            " AND because_code IS NOT NULL AND proposal IS NOT NULL)",
            name="ck_blocks_confirmation",
        ),
        sa.CheckConstraint(
            "deferred_to_task_id IS NULL OR answer = 'deferred'",
            name="ck_blocks_deferred_to",
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["because_code"], ["confirmation_reasons.code"]),
        sa.ForeignKeyConstraint(["answered_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "local_id"),
    )
    op.create_index(
        "ix_blocks_deferred_to_task_id",
        "blocks",
        ["deferred_to_task_id"],
        postgresql_where=sa.text("deferred_to_task_id IS NOT NULL"),
    )
    op.create_table(
        "block_options",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("block_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column(
            "recommended", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.ForeignKeyConstraint(["block_id"], ["blocks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_block_options_block_id_position", "block_options", ["block_id", "position"]
    )


def _create_attachments() -> None:
    op.create_table(
        "attachments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("batch", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("source_code", _enum("attachment_source"), nullable=False),
        sa.Column("source_environment_id", sa.Text(), nullable=True),
        sa.Column("source_path", sa.Text(), nullable=True),
        _timestamp("copied_at", nullable=False),
        sa.Column("created_by_session_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("batch >= 1", name="ck_attachments_batch"),
        sa.CheckConstraint(
            "(source_code = 'draft') = (source_environment_id IS NULL)"
            " AND (source_code = 'draft') = (source_path IS NULL)"
            " AND (source_code = 'draft') = (created_by_session_id IS NULL)",
            name="ck_attachments_source",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["source_environment_id"], ["environments.id"]),
        sa.ForeignKeyConstraint(["created_by_session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "batch", "filename"),
    )
    op.create_table(
        "item_attachments",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("attachment_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        _timestamp("attached_at", nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.ForeignKeyConstraint(["attachment_id"], ["attachments.id"]),
        sa.PrimaryKeyConstraint("item_id", "attachment_id"),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    for table in (
        "plan_note_references",
        "item_attachments",
        "attachments",
        "block_options",
        "blocks",
        "save_errors",
        "document_versions",
        "documents",
        "items",
    ):
        op.drop_table(table)
