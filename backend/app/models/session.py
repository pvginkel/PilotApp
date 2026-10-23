"""Session, Turn and Session Record (DB §2.3), with the columns the record gives them."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.reference import (
    RECORD_KIND,
    SESSION_STATE,
    RecordKind,
    SessionState,
)


class Session(db.Model):  # type: ignore[name-defined]
    """A run of a conversation Pilot drives with Claude Code in one Environment.

    `turns`, `turn_started_at` and `turn_ended_at` are caches of its Turns,
    refreshed by the server on every Turn; `current_line` one of its Session
    Records, rebuilt by the relay on each it writes and null while no Turn is
    in flight (DB §7.4, assertion 221).
    """

    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_state_code", "state_code"),
        # What a Work's key references, so its Session is of its Project and
        # its Session Kind is one the Work's checks read.
        UniqueConstraint("project_id", "id", "kind_code"),
        # The gate starts held Sessions in `created_at` order.
        Index(
            "ix_sessions_held",
            "created_at",
            postgresql_where=text("state_code = 'held'"),
        ),
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
    current_line: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True)
    )


class Turn(db.Model):  # type: ignore[name-defined]
    """One message sent to a Session and the reply it produced, from the send
    to the turn's end; the server's own turns have no author.

    `quote_item_id` and `quote_block_id` are read from the quote tag in
    `message` at the send (DB §7.4); the tag stays when the agent removes a
    quoted draft Block, and `quote_block_id` is then cleared.
    """

    __tablename__ = "turns"
    __table_args__ = (
        UniqueConstraint("session_id", "seq"),
        # What a Session Record's key to its Turn references, so the Turn is
        # of the record's own Session.
        UniqueConstraint("session_id", "id"),
        CheckConstraint("seq >= 1", name="ck_turns_seq"),
        # An Item or a Block, never both (DB assertion 159).
        CheckConstraint(
            "quote_item_id IS NULL OR quote_block_id IS NULL", name="ck_turns_quote"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"))
    seq: Mapped[int] = mapped_column(Integer)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    message: Mapped[str] = mapped_column(Text)
    quote_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("items.id"))
    quote_block_id: Mapped[int | None] = mapped_column(
        ForeignKey("blocks.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class SessionRecord(db.Model):  # type: ignore[name-defined]
    """One entry in a Session's list: a line of the raw response stream, the
    worker's `result` frame, a person's message in its place, or the server's
    own line.

    `seq` runs from 1 without a gap per Session in the order written (DB
    assertion 217), which no constraint holds: the writer takes it under the
    Session row's lock.
    """

    __tablename__ = "session_records"
    # `at` comes back with the insert, so no refresh reads the table outside
    # the one read function (design 2 §11.4).
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        UniqueConstraint("session_id", "seq"),
        ForeignKeyConstraint(
            ["session_id", "turn_id"], ["turns.session_id", "turns.id"]
        ),
        CheckConstraint("seq >= 1", name="ck_session_records_seq"),
        # A line of the stream falls in a Turn and carries where it is in its
        # controller session's raw file; no other kind does (DB assertion 218).
        CheckConstraint(
            "(kind_code IN ('claude', 'result')) = (raw_offset IS NOT NULL)"
            " AND (kind_code IN ('claude', 'result')) = (controller_session IS NOT NULL)"
            " AND (kind_code NOT IN ('claude', 'result') OR turn_id IS NOT NULL)",
            name="ck_session_records_stream",
        ),
        # A partial `stream_event` line is never stored (DB assertion 218).
        CheckConstraint(
            "kind_code <> 'claude'"
            " OR payload ->> 'type' IS DISTINCT FROM 'stream_event'",
            name="ck_session_records_partial",
        ),
        # A `send` falls in its Turn and has no payload, its words and author
        # being the Turn's; every other kind has one (DB assertion 219).
        CheckConstraint(
            "(kind_code = 'send') = (payload IS NULL)"
            " AND (kind_code <> 'send' OR turn_id IS NOT NULL)",
            name="ck_session_records_send",
        ),
        # A Turn has at most one `send` (DB assertion 219).
        Index(
            "uq_session_records_send_turn_id",
            "turn_id",
            unique=True,
            postgresql_where=text("kind_code = 'send'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"))
    seq: Mapped[int] = mapped_column(Integer)
    turn_id: Mapped[int | None] = mapped_column(BigInteger)
    kind_code: Mapped[RecordKind] = mapped_column(RECORD_KIND)
    payload: Mapped[Any] = mapped_column(JSONB(none_as_null=True), nullable=True)
    raw_offset: Mapped[int | None] = mapped_column(BigInteger)
    controller_session: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
