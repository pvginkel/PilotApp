"""Document and Document Version (DB §2.2).

A document's texts are `text` with `lz4` compression, which the revision sets
and these models cannot carry (DB §7.1).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.reference import (
    DOCUMENT_ROLE,
    VERSION_CAUSE,
    DocumentRole,
    VersionCause,
)


class Document(db.Model):  # type: ignore[name-defined]
    """A Markdown file of a Project's tree whose content the record holds.

    Every Document is a Prose Item or a Project Document (DB assertion 148),
    both kept here (DB §7.3): a Prose Item's `id` is its Item's, and its
    `summary` a cache of the published text (DB §7.4); a Project Document has
    `project_id` and `role_code` and none of the Prose Item's columns.
    """

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "(project_id IS NULL) = (role_code IS NULL)"
            " AND (project_id IS NULL OR (summary IS NULL"
            " AND source_environment_id IS NULL AND source_path IS NULL"
            " AND written_back_at IS NULL))",
            name="ck_documents_subtype",
        ),
        CheckConstraint(
            "(source_environment_id IS NULL) = (source_path IS NULL)",
            name="ck_documents_source",
        ),
        CheckConstraint(
            "(ingested_text IS NULL) = (ingested_hash IS NULL)"
            " AND (ingested_text IS NULL) = (ingested_at IS NULL)"
            " AND (ingested_session_id IS NULL OR ingested_text IS NOT NULL)",
            name="ck_documents_ingested",
        ),
        CheckConstraint(
            "(published_text IS NULL) = (published_hash IS NULL)"
            " AND (published_text IS NULL) = (published_at IS NULL)",
            name="ck_documents_published",
        ),
        CheckConstraint(
            "(writing_session_id IS NULL) = (writing_since IS NULL)",
            name="ck_documents_writing",
        ),
        # A Prose Item's path is unique through its Item's `seq`.
        Index(
            "uq_documents_project_path",
            "project_id",
            "path",
            unique=True,
            postgresql_where=text("project_id IS NOT NULL"),
        ),
        # One draft and one handbook per Project (DB assertion 150).
        Index(
            "uq_documents_project_role",
            "project_id",
            "role_code",
            unique=True,
            postgresql_where=text("project_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    path: Mapped[str] = mapped_column(Text)
    ingested_text: Mapped[str | None] = mapped_column(Text, info={"allow_empty": True})
    ingested_hash: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id")
    )
    published_text: Mapped[str | None] = mapped_column(Text, info={"allow_empty": True})
    published_hash: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    writing_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id")
    )
    writing_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    summary: Mapped[str | None] = mapped_column(Text)
    source_environment_id: Mapped[str | None] = mapped_column(
        ForeignKey("environments.id")
    )
    source_path: Mapped[str | None] = mapped_column(Text)
    written_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    role_code: Mapped[DocumentRole | None] = mapped_column(DOCUMENT_ROLE)


class DocumentVersion(db.Model):  # type: ignore[name-defined]
    """A state of a Document fixed at its birth, its registration, a turn or Done."""

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "number"),
        CheckConstraint("number >= 1", name="ck_document_versions_number"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    number: Mapped[int] = mapped_column(Integer)
    cause_code: Mapped[VersionCause] = mapped_column(VERSION_CAUSE)
    text: Mapped[str] = mapped_column(Text, info={"allow_empty": True})
    hash: Mapped[str] = mapped_column(Text)
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sessions.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
