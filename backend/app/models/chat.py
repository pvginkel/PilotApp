"""Chat (DB §2.3), the subtype of Session, and Chat Read (DB §2.1).

`chats` is the extension table keyed by its Session's id (DB §7.3).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.reference import CHAT_KIND, CLOSE_CAUSE, ChatKind, CloseCause


class Chat(db.Model):  # type: ignore[name-defined]
    """A Session that holds one conversation between a project's people and
    Pilot: the definition chat of a draft, or one of a project's chats.

    `project_id` and `session_kind_code` are its Session's, carried so that
    the key reaches a `chat` Session (DB assertion 149) and a Project has one
    chat open at a time.
    """

    __tablename__ = "chats"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "id", "session_kind_code"],
            ["sessions.project_id", "sessions.id", "sessions.kind_code"],
        ),
        CheckConstraint("session_kind_code = 'chat'", name="ck_chats_session_kind"),
        # A Chat closes once, with its cause.
        CheckConstraint(
            "(closed_at IS NULL) = (close_cause_code IS NULL)", name="ck_chats_close"
        ),
        # One chat per project at a time, whichever Discuss opens it (U r16).
        Index(
            "uq_chats_open",
            "project_id",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    project_id: Mapped[uuid.UUID]
    session_kind_code: Mapped[str] = mapped_column(Text)
    kind_code: Mapped[ChatKind] = mapped_column(CHAT_KIND)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_cause_code: Mapped[CloseCause | None] = mapped_column(CLOSE_CAUSE)


class ChatRead(db.Model):  # type: ignore[name-defined]
    """One User's position in one Project's chat: when they last had it in
    view at its end, on whichever device. Per Project, so that a rotation
    keeps it."""

    __tablename__ = "chat_reads"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id"), primary_key=True
    )
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
