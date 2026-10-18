"""Session (DB §2.3), with the columns the record gives it."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.reference import SESSION_STATE, SessionState


class Session(db.Model):  # type: ignore[name-defined]
    """A run of a conversation Pilot drives with Claude Code in one Environment.

    `turns`, `turn_started_at` and `turn_ended_at` are caches of its Turns,
    refreshed by the server on every Turn (DB §7.4).
    """

    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_state_code", "state_code"),
        # The MCP server's bearer check resolves a token to one Session.
        Index("uq_sessions_token_hash", "token_hash", unique=True),
        Index(
            "ix_sessions_nudge_owed_at",
            "nudge_owed_at",
            postgresql_where=text("nudge_owed_at IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id"))
    kind_code: Mapped[str] = mapped_column(ForeignKey("session_kinds.code"))
    controller_session: Mapped[str | None] = mapped_column(Text)
    conversation_id: Mapped[str | None] = mapped_column(Text)
    cwd: Mapped[str] = mapped_column(Text)
    agent: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    reasoning_effort: Mapped[str | None] = mapped_column(Text)
    token_hash: Mapped[str] = mapped_column(Text)
    state_code: Mapped[SessionState] = mapped_column(SESSION_STATE)
    error: Mapped[str | None] = mapped_column(Text)
    turns: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    turn_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    turn_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    nudge_owed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
