"""Conversation (DB §2.3), the subtype of Session beside Chat (DB decision 77).

`conversations` is the extension table keyed by its Session's id (DB §7.3).
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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.reference import CLOSE_CAUSE, CloseCause


class Conversation(db.Model):  # type: ignore[name-defined]
    """A Session that holds one exchange of messages between a session
    outside Pilot and Pilot about one Project, through Pilot's projects
    surface: opened from an Environment, the caller's, by a session there.

    `project_id` and `session_kind_code` are its Session's, carried so that
    the key reaches a `conversation` Session (DB assertion 149). Who opened
    it is its first Turn's author, which no column holds (DB 337). A Project
    has several open at once (DB 335).
    """

    __tablename__ = "conversations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "id", "session_kind_code"],
            ["sessions.project_id", "sessions.id", "sessions.kind_code"],
        ),
        CheckConstraint(
            "session_kind_code = 'conversation'",
            name="ck_conversations_session_kind",
        ),
        # A Conversation closes once, with its cause.
        CheckConstraint(
            "(closed_at IS NULL) = (close_cause_code IS NULL)",
            name="ck_conversations_close",
        ),
        # None opens on a draft, which Create project closes the chat of (DB 334).
        CheckConstraint(
            "close_cause_code <> 'created'", name="ck_conversations_close_cause"
        ),
        # A caller's list is its Environment's (DB 337).
        Index("ix_conversations_caller_environment_id", "caller_environment_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    project_id: Mapped[uuid.UUID]
    session_kind_code: Mapped[str] = mapped_column(Text)
    caller_environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id"))
    caller_session: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_cause_code: Mapped[CloseCause | None] = mapped_column(CLOSE_CAUSE)
