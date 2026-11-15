"""Session, Turn and Session Record (DB §2.3), and a Session's Hold (DB §2.5),
with the columns the record gives them."""

import uuid
from datetime import datetime
from decimal import Decimal
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
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.reference import (
    EFFECT_KIND,
    HOLD_KIND,
    RECORD_KIND,
    SESSION_STATE,
    TURN_CAUSE,
    EffectKind,
    HoldKind,
    RecordKind,
    SessionState,
    TurnCause,
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
    environment_id: Mapped[str | None] = mapped_column(ForeignKey("environments.id"))
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

    `message` is what was sent; `words` a person's own, verbatim with their
    quote tags, which `message` ends with (DB assertion 251).
    `quote_item_id` and `quote_block_id` are read from the quote tag in
    `words` at the send (DB §7.4); the tag stays when the agent removes a
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
        # A person's Turn has their words, the server's none, and a quote is
        # read from the words (DB assertions 159, 251).
        CheckConstraint(
            "(author_user_id IS NULL) = (words IS NULL)"
            " AND (words IS NOT NULL"
            " OR (quote_item_id IS NULL AND quote_block_id IS NULL))",
            name="ck_turns_words",
        ),
        # A Turn with an author is a person's, and the server's own has none
        # (DB §2.3, Turn; §2.11, Turn Cause).
        CheckConstraint(
            "(cause_code = 'person') = (author_user_id IS NOT NULL)",
            name="ck_turns_cause",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"))
    seq: Mapped[int] = mapped_column(Integer)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    message: Mapped[str] = mapped_column(Text)
    words: Mapped[str | None] = mapped_column(Text)
    quote_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("items.id"))
    quote_block_id: Mapped[int | None] = mapped_column(
        ForeignKey("blocks.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    cost: Mapped[Decimal | None] = mapped_column(Numeric)
    """US dollars, the turn's own as its `result` line reports them, less what
    its conversation reported before it (`token_counts`), notional on a
    subscription; none without one (DB 275)."""
    cause_code: Mapped[TurnCause] = mapped_column(TURN_CAUSE)
    """Why Pilot sent it, given at the write (DB 352)."""


class Hold(db.Model):  # type: ignore[name-defined]
    """One period in which Pilot kept a Session from running for one reason
    outside it (DB §2.5, Hold; 360, 362), ended once: a Session has one open
    at a time, and a reason that changes ends it and starts the next. A start
    the gate keeps `held` has one from the gate's first keeping it until the
    gate lets it go, a Stop stops it or its job is withdrawn. A Session at rest
    that is owed its nudge has one while a reason withholds the nudge
    (`holds.at_rest`), until that reason lifts, the nudge or a Resume carries
    the Session on, a Stop, a Close, a Stop and take over or the quota wall's
    settle leaves it owed no nudge, a Finish or an Archive means the nudge goes
    out no more, or the release finds it owed none. Nothing reads one to decide
    anything."""

    __tablename__ = "holds"
    __table_args__ = (
        # One Hold of a Session at a time, whatever writes at once: a reason
        # that changes ends one Hold and starts the next (DB 362, 559).
        Index(
            "uq_holds_open_session_id",
            "session_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        CheckConstraint("ended_at >= started_at", name="ck_holds_period"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"))
    kind_code: Mapped[HoldKind] = mapped_column(HOLD_KIND)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """None while the Session is held."""


class TokenCount(db.Model):  # type: ignore[name-defined]
    """The tokens of one kind one Turn used, the turn's own as its `result`
    line reports them, less what its conversation reported before it
    (`token_counts`), summed over every model it called (DB 272, 273, 275)."""

    __tablename__ = "token_counts"
    __table_args__ = (
        UniqueConstraint("turn_id", "token_kind_code"),
        CheckConstraint("tokens >= 0", name="ck_token_counts_tokens"),
        # The four kinds a `result` line names, each within no other.
        CheckConstraint(
            "token_kind_code IN ('input', 'cache_write', 'cache_read', 'output')",
            name="ck_token_counts_kind",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    turn_id: Mapped[int] = mapped_column(ForeignKey("turns.id"))
    token_kind_code: Mapped[str] = mapped_column(ForeignKey("token_kinds.code"))
    tokens: Mapped[int] = mapped_column(BigInteger)


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


class Effect(db.Model):  # type: ignore[name-defined]
    """One change to the record a session's tool call made during a Turn,
    placed in its Session's list by the `server` record written with it.

    `record_id` is a `server` record of the Turn `turn_id` (DB assertion
    216), which no key holds: the writer places the Effect.
    """

    __tablename__ = "effects"
    __table_args__ = (
        Index("ix_effects_turn_id", "turn_id"),
        # "In the chat" on a Block goes to its latest Effect's record (F42.3).
        Index("ix_effects_block_id", "block_id"),
        # What an Effect names follows its kind (DB assertion 160). An
        # `answered` Effect's Block is cleared when the agent removes it from
        # the draft, as a Turn's quote is.
        CheckConstraint(
            "(kind_code IN ('added', 'marked', 'stopped', 'registered'))"
            " = (item_id IS NOT NULL)"
            " AND (kind_code = 'attached') = (attachment_id IS NOT NULL)"
            " AND (kind_code = 'answered' OR block_id IS NULL)",
            name="ck_effects_names",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    turn_id: Mapped[int] = mapped_column(ForeignKey("turns.id"))
    record_id: Mapped[int] = mapped_column(ForeignKey("session_records.id"))
    kind_code: Mapped[EffectKind] = mapped_column(EFFECT_KIND)
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("items.id"))
    block_id: Mapped[int | None] = mapped_column(
        ForeignKey("blocks.id", ondelete="SET NULL")
    )
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("attachments.id")
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class WriterQuestion(db.Model):  # type: ignore[name-defined]
    """One question the pre-ruling pass put to a registered document's writer
    about one Block of it, in the pass's Turn (DB decision 59)."""

    __tablename__ = "writer_questions"
    __table_args__ = (
        # The clarification run batches a pass's questions by its Turn.
        Index("ix_writer_questions_turn_id", "turn_id"),
        # One question per Block in version 1 (DB assertion 250).
        Index("uq_writer_questions_block_id", "block_id", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    turn_id: Mapped[int] = mapped_column(ForeignKey("turns.id"))
    block_id: Mapped[int] = mapped_column(ForeignKey("blocks.id"))
    question: Mapped[str] = mapped_column(Text)
    asked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
