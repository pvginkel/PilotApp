"""Call, Tool Call, Event and Context Part (DB §2.7), with the reference
entities that classify them (§2.11): what a Transcript asked of the model and
what each request did, as a collector's publication gives it (DB decisions 79
and 81).

The reference entities here are the collector's: a row is written when a
publication first names its code, and no revision writes one (DB §7.2). Event
Kind and Context Part Kind hold the labeller's values beside them, and an
Event and a Context Part the labeller gave stand beside the collector's.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.vocabulary import declared_value_args

CONTEXT_TOKENS = (
    "input_tokens + cache_write_5m_tokens + cache_write_1h_tokens + cache_read_tokens"
)
"""A Call's `context_tokens`, in its columns."""


class Model(db.Model):  # type: ignore[name-defined]
    """A kind of model a Call is answered by, by Claude's id.

    `priced_as_code` is the Model whose Prices it takes where it has none of
    its own (DB 548): set when the Model is first met, and dropped once the
    price file names it (`price_service`).
    """

    __tablename__ = "models"
    __table_args__ = (
        CheckConstraint("priced_as_code <> code", name="ck_models_priced_as"),
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    priced_as_code: Mapped[str | None] = mapped_column(ForeignKey("models.code"))


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

    `context_tokens` is the sum of its tokens of the input and cache kinds,
    which PostgreSQL derives. `cost` is its tokens of each kind at the Price
    in force for its Model, in US dollars (DB 548), none where a kind it
    counts has no Price; the publication derives it, and a load of the price
    file again (`price_service`).

    `waited_seconds`, `rewind`, `cache_miss`, `past_ttl` and `launch_id` are
    derived too (`call_caches`): the seconds from its predecessor's
    `completed_at` to its own `sent_at`, or to its `completed_at` where it
    has no `sent_at`, none on a chain's first; whether its predecessor is
    another Call than the one before it by `position`; whether it is a cache
    miss (DB 546); whether it waited longer than the cache its predecessor
    wrote lives; and the Launch it was made in (DB 543), none where Pilot
    holds none. The three flags are none together, on a Call a server from
    before them wrote, until the step after a deploy's revisions derives
    them. That its Launch is of its Transcript, or of its Transcript's main
    thread, is the publication's to keep.

    Its labels are `wait_cause_code`, `segment_position`, `call_class_code`
    and `avoidable_kind_code`. `segment_position` names the Segment it falls
    in by its place, a Segment of its own Transcript (DB 555).
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
        # Checked at each statement: a write holds a Segment before a Call
        # names its position, and removes one only once no Call does.
        ForeignKeyConstraint(
            ["transcript_id", "segment_position"],
            ["segments.transcript_id", "segments.position"],
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
        # The Calls a load of the price file prices at every deploy.
        Index("ix_calls_unpriced", "id", postgresql_where=text("cost IS NULL")),
        CheckConstraint(
            "(rewind IS NULL) = (cache_miss IS NULL)"
            " AND (rewind IS NULL) = (past_ttl IS NULL)",
            name="ck_calls_derived",
        ),
        # The Calls the step after a deploy's revisions derives the caches of.
        Index("ix_calls_underived", "id", postgresql_where=text("rewind IS NULL")),
        # Read when a Launch goes, to clear the Calls made in it.
        Index("ix_calls_launch_id", "launch_id"),
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
    context_tokens: Mapped[int] = mapped_column(
        Integer, Computed(CONTEXT_TOKENS, persisted=True)
    )
    cost: Mapped[Decimal | None] = mapped_column(Numeric)
    waited_seconds: Mapped[float | None] = mapped_column(Double)
    rewind: Mapped[bool | None] = mapped_column(Boolean)
    cache_miss: Mapped[bool | None] = mapped_column(Boolean)
    past_ttl: Mapped[bool | None] = mapped_column(Boolean)
    launch_id: Mapped[int | None] = mapped_column(
        ForeignKey("launches.id", ondelete="SET NULL")
    )
    wait_cause_code: Mapped[str | None] = mapped_column(ForeignKey("wait_causes.code"))
    segment_position: Mapped[int | None] = mapped_column(Integer)
    call_class_code: Mapped[str | None] = mapped_column(ForeignKey("call_classes.code"))
    avoidable_kind_code: Mapped[str | None] = mapped_column(
        ForeignKey("avoidable_kinds.code")
    )


PRICED_KINDS = (
    "input",
    "cache_write_5m",
    "cache_write_1h",
    "cache_read",
    "output",
)
"""The Token Kinds a Price is of, those nothing is within (DB 547), each a
`_tokens` column of a Call."""


class Price(db.Model):  # type: ignore[name-defined]
    """A rate for one Token Kind of one Model from `effective_at` on, in US
    dollars per million tokens, until the next Price of its Model, Token
    Kind and `above_context` applies.

    `above_context` is the context size in tokens from which the rate
    applies, none for the base rate. Its rows are the price file's
    (`price_service`): a row is added and none is changed or removed.
    """

    __tablename__ = "prices"
    __table_args__ = (
        UniqueConstraint(
            "model_code",
            "token_kind_code",
            "above_context",
            "effective_at",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "token_kind_code IN ("
            + ", ".join(f"'{kind}'" for kind in PRICED_KINDS)
            + ")",
            name="ck_prices_kind",
        ),
        CheckConstraint("above_context > 0", name="ck_prices_above_context"),
        CheckConstraint("rate >= 0", name="ck_prices_rate"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    model_code: Mapped[str] = mapped_column(ForeignKey("models.code"))
    token_kind_code: Mapped[str] = mapped_column(ForeignKey("token_kinds.code"))
    above_context: Mapped[int | None] = mapped_column(Integer)
    rate: Mapped[Decimal] = mapped_column(Numeric)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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
    Call's Transcript, within which its `tool_use_id` is unique.

    Its labels are `command_class_code`, `effect_kind_code` and
    `effect_subject`, the id of what that change touched, a card's or a
    fieldnote's.
    """

    __tablename__ = "tool_calls"
    __table_args__ = (
        ForeignKeyConstraint(
            ["transcript_id", "call_id"],
            ["calls.transcript_id", "calls.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("transcript_id", "tool_use_id"),
        # What a Test Run's key references, so a Tool Call's run carries its
        # Transcript.
        UniqueConstraint("transcript_id", "id"),
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
        # A subject is of the change it touched.
        CheckConstraint(
            "effect_subject IS NULL OR effect_kind_code IS NOT NULL",
            name="ck_tool_calls_effect_subject",
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
    command_class_code: Mapped[str | None] = mapped_column(
        ForeignKey("command_classes.code")
    )
    effect_kind_code: Mapped[str | None] = mapped_column(
        ForeignKey("tool_effect_kinds.code")
    )
    effect_subject: Mapped[str | None] = mapped_column(Text)


RECORDED_ELSEWHERE = (
    "compaction",
    "rewind",
    "cache_miss",
    "past_ttl",
    "model_fallback",
    "max_tokens",
    "refusal",
    "output_saved",
    "denied",
    "hook_error",
)
"""The Event Kinds whose occurrences a Compaction, a Call, a Tool Call and a
Hook Run record, and no Event (DB 560)."""


class EventKind(db.Model):  # type: ignore[name-defined]
    """A kind of occurrence the screen marks; `is_error` whether it counts as
    an error.

    The collector's values are met by a publication and hold a code, a name
    and `is_error` alone. The labeller's are declared (`app.models.vocabulary`)
    and hold their `description` and `position` too, a `position` none once
    the labeller no longer declares the value (DB 585).
    """

    __tablename__ = "event_kinds"
    __table_args__ = declared_value_args(
        "event_kinds",
        # A value with a place in the labeller's list is one it declared,
        # which names its line.
        CheckConstraint(
            "position IS NULL OR description IS NOT NULL",
            name="ck_event_kinds_described",
        ),
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    is_error: Mapped[bool] = mapped_column(Boolean)
    description: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int | None] = mapped_column(Integer)


class Event(db.Model):  # type: ignore[name-defined]
    """An occurrence in a Transcript, at one moment, that no other entity
    records, held on the last Call before it, else the first. `labelled` is
    whether it is a label, one the labeller marked, and not an occurrence
    the collector read off the file."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_call_id", "call_id"),
        CheckConstraint(
            "kind_code NOT IN ("
            + ", ".join(f"'{kind}'" for kind in RECORDED_ELSEWHERE)
            + ")",
            name="ck_events_kind",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"))
    kind_code: Mapped[str] = mapped_column(ForeignKey("event_kinds.code"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    detail: Mapped[str | None] = mapped_column(Text)
    labelled: Mapped[bool] = mapped_column(Boolean, server_default=false())


class ContextPartKind(db.Model):  # type: ignore[name-defined]
    """A kind of component of a Call's context: the collector's, a code and
    a name, and the labeller's, with their `description` and `position` too,
    as Event Kind's are."""

    __tablename__ = "context_part_kinds"
    __table_args__ = declared_value_args(
        "context_part_kinds",
        # A value with a place in the labeller's list is one it declared,
        # which names its line.
        CheckConstraint(
            "position IS NULL OR description IS NOT NULL",
            name="ck_context_part_kinds_described",
        ),
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int | None] = mapped_column(Integer)


class ContextPart(db.Model):  # type: ignore[name-defined]
    """A component of what a Call carried that no earlier Call of its Launch
    did; `name` which one of its kind. `labelled` is whether it is a label,
    one the labeller gave, as an Event's is."""

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
    labelled: Mapped[bool] = mapped_column(Boolean, server_default=false())
