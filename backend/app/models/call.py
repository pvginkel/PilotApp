"""Call, Tool Call, Event and Context Part (DB §2.7), with the reference
entities that classify them (§2.11): what a Transcript asked of the model and
what each request did, as a collector's publication gives it (DB decisions 79
and 81).

The reference entities here are the collector's: a row is written when a
publication first names its code, and no revision writes one (DB §7.2).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class Model(db.Model):  # type: ignore[name-defined]
    """A kind of model a Call is answered by, by Claude's id."""

    __tablename__ = "models"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)


class StopReason(db.Model):  # type: ignore[name-defined]
    """A kind of unusual end of a response."""

    __tablename__ = "stop_reasons"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)


class MissCause(db.Model):  # type: ignore[name-defined]
    """A kind of reason for a cache miss."""

    __tablename__ = "miss_causes"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)


class Call(db.Model):  # type: ignore[name-defined]
    """A request a Transcript made to the model, with its response.

    Its Call Token Counts are the five `_tokens` columns named for a Token
    Kind, one for each kind nothing is within (DB §7.7, 547);
    `thinking_tokens` is a part of `output_tokens` and no kind. `position` is
    its place among its Transcript's Calls in the file's order, from 1. Its
    Prompt, its predecessor and its Compaction are its own Transcript's (DB
    542, 545); that its predecessor has a lower `position` is the
    publication's to keep.
    """

    __tablename__ = "calls"
    __table_args__ = (
        UniqueConstraint("transcript_id", "message_id"),
        # Checked at the commit, so a publication moves a Transcript's Calls
        # up or down in its transaction.
        UniqueConstraint(
            "transcript_id",
            "position",
            name="uq_calls_transcript_id_position",
            deferrable=True,
            initially="DEFERRED",
        ),
        # What a Tool Call's key and a Call's to its predecessor reference.
        UniqueConstraint("transcript_id", "id"),
        ForeignKeyConstraint(
            ["transcript_id", "prompt_id"], ["prompts.transcript_id", "prompts.id"]
        ),
        ForeignKeyConstraint(
            ["transcript_id", "predecessor_id"], ["calls.transcript_id", "calls.id"]
        ),
        ForeignKeyConstraint(
            ["transcript_id", "compaction_id"],
            ["compactions.transcript_id", "compactions.id"],
        ),
        CheckConstraint("position >= 1", name="ck_calls_position"),
        # The model asked for is held where it differs.
        CheckConstraint(
            "requested_model_code <> model_code", name="ck_calls_requested_model"
        ),
        CheckConstraint(
            "input_tokens >= 0 AND cache_write_5m_tokens >= 0"
            " AND cache_write_1h_tokens >= 0 AND cache_read_tokens >= 0"
            " AND output_tokens >= 0 AND thinking_tokens >= 0",
            name="ck_calls_tokens",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    transcript_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transcripts.id"))
    message_id: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)
    prompt_id: Mapped[int | None] = mapped_column(BigInteger)
    predecessor_id: Mapped[int | None] = mapped_column(BigInteger)
    compaction_id: Mapped[int | None] = mapped_column(BigInteger)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    model_code: Mapped[str] = mapped_column(ForeignKey("models.code"))
    requested_model_code: Mapped[str | None] = mapped_column(ForeignKey("models.code"))
    effort: Mapped[str | None] = mapped_column(Text)
    stop_reason_code: Mapped[str | None] = mapped_column(
        ForeignKey("stop_reasons.code")
    )
    thinking_tokens: Mapped[int | None] = mapped_column(Integer)
    attributed_skill: Mapped[str | None] = mapped_column(Text)
    attributed_plugin: Mapped[str | None] = mapped_column(Text)
    miss_cause_code: Mapped[str | None] = mapped_column(ForeignKey("miss_causes.code"))
    input_tokens: Mapped[int] = mapped_column(Integer)
    cache_write_5m_tokens: Mapped[int] = mapped_column(Integer)
    cache_write_1h_tokens: Mapped[int] = mapped_column(Integer)
    cache_read_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)


class Tool(db.Model):  # type: ignore[name-defined]
    """A kind of tool a Tool Call calls, by Claude Code's name; `mcp_server`
    the MCP server it is of."""

    __tablename__ = "tools"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    mcp_server: Mapped[str | None] = mapped_column(Text)


class DenialKind(db.Model):  # type: ignore[name-defined]
    """A kind of denier of a Tool Call."""

    __tablename__ = "denial_kinds"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)


class ToolCall(db.Model):  # type: ignore[name-defined]
    """A call of one tool a Call requested, with its result. It carries its
    Call's Transcript, within which its `tool_use_id` is unique."""

    __tablename__ = "tool_calls"
    __table_args__ = (
        ForeignKeyConstraint(
            ["transcript_id", "call_id"],
            ["calls.transcript_id", "calls.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("transcript_id", "tool_use_id"),
        Index("ix_tool_calls_call_id", "call_id"),
        # An exit code is held where it was not zero.
        CheckConstraint("exit_code <> 0", name="ck_tool_calls_exit_code"),
        # DB 587.
        CheckConstraint(
            "denial_kind_code IS DISTINCT FROM 'hook' OR failed",
            name="ck_tool_calls_denied_by_hook",
        ),
        CheckConstraint(
            "result_characters >= 0 AND saved_characters >= 0",
            name="ck_tool_calls_characters",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    transcript_id: Mapped[uuid.UUID] = mapped_column()
    call_id: Mapped[int] = mapped_column(BigInteger)
    tool_use_id: Mapped[str] = mapped_column(Text)
    tool_code: Mapped[str] = mapped_column(ForeignKey("tools.code"))
    first_argument: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed: Mapped[bool] = mapped_column(Boolean)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    interrupted: Mapped[bool] = mapped_column(Boolean)
    denial_kind_code: Mapped[str | None] = mapped_column(
        ForeignKey("denial_kinds.code")
    )
    result_characters: Mapped[int | None] = mapped_column(Integer)
    saved_characters: Mapped[int | None] = mapped_column(Integer)


class EventKind(db.Model):  # type: ignore[name-defined]
    """A kind of occurrence the screen marks; `is_error` whether it counts as
    an error."""

    __tablename__ = "event_kinds"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    is_error: Mapped[bool] = mapped_column(Boolean)


class Event(db.Model):  # type: ignore[name-defined]
    """An occurrence in a Transcript, at one moment, that no other entity
    records, held on the last Call before it, else the first."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_call_id", "call_id"),
        # The occurrences a Compaction, a Call, a Tool Call and a Hook Run
        # record are stored as no Event (DB 560).
        CheckConstraint(
            "kind_code NOT IN ('compaction', 'rewind', 'cache_miss', 'past_ttl',"
            " 'model_fallback', 'max_tokens', 'refusal', 'output_saved', 'denied',"
            " 'hook_error')",
            name="ck_events_kind",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"))
    kind_code: Mapped[str] = mapped_column(ForeignKey("event_kinds.code"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    detail: Mapped[str | None] = mapped_column(Text)


class ContextPartKind(db.Model):  # type: ignore[name-defined]
    """A kind of component of a Call's context."""

    __tablename__ = "context_part_kinds"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)


class ContextPart(db.Model):  # type: ignore[name-defined]
    """A component of what a Call carried that no earlier Call of its Launch
    did; `name` which one of its kind."""

    __tablename__ = "context_parts"
    __table_args__ = (
        Index("ix_context_parts_call_id", "call_id"),
        CheckConstraint("characters >= 0", name="ck_context_parts_characters"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"))
    kind_code: Mapped[str] = mapped_column(ForeignKey("context_part_kinds.code"))
    name: Mapped[str | None] = mapped_column(Text)
    characters: Mapped[int] = mapped_column(Integer)
