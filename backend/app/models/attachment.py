"""Attachment (DB §2.1) and Item Attachment (DB §2.2)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.reference import ATTACHMENT_SOURCE, AttachmentSource


class Attachment(db.Model):  # type: ignore[name-defined]
    """A copy of a file kept for the reader, never edited.

    In the tree at `attachments/<batch>/<filename>` of its Project's folder
    (DB decision 39). `title`, `size` and `sha256` are stored once, at the
    copy (DB §7.4).
    """

    __tablename__ = "attachments"
    __table_args__ = (
        UniqueConstraint("project_id", "batch", "filename"),
        CheckConstraint("batch >= 1", name="ck_attachments_batch"),
        # The draft copy has no source and no session; a file all three (DB
        # assertion 165).
        CheckConstraint(
            "(source_code = 'draft') = (source_environment_id IS NULL)"
            " AND (source_code = 'draft') = (source_path IS NULL)"
            " AND (source_code = 'draft') = (created_by_session_id IS NULL)",
            name="ck_attachments_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    batch: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(Text)
    # Read and written through `AttachmentStore` alone: loading a row never
    # reads the bytes, and touching the attribute on a loaded row raises.
    content: Mapped[bytes] = mapped_column(
        LargeBinary, deferred=True, deferred_raiseload=True
    )
    source_code: Mapped[AttachmentSource] = mapped_column(ATTACHMENT_SOURCE)
    source_environment_id: Mapped[str | None] = mapped_column(
        ForeignKey("environments.id")
    )
    source_path: Mapped[str | None] = mapped_column(Text)
    copied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id")
    )


class ItemAttachment(db.Model):  # type: ignore[name-defined]
    """One Attachment hung on one Item, in a position among the Item's."""

    __tablename__ = "item_attachments"

    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id"), primary_key=True)
    attachment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("attachments.id"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer)
    attached_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
