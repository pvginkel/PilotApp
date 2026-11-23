"""The facts Pilot's code declares, Pilot's own and the collector's, and the
joins their rows reach the record through (F154.3; DB decision 79.42).

- **Call**: a Call, and each Turn whose conversation's Transcript was never
  collected standing in with its own cost, marked an estimate. A stand-in
  has its Turn's tokens by the kinds a Turn counts, and no Call's facts.
- **Turn**: a Turn of Pilot's.
- **Event**: an Event, or an occurrence of a kind another entity records
  (DB 560), each at its own moment on the Call it is held on, with its one
  short detail from the fact behind it: an API error's status, a saved
  output's tool and size, a denial's kind and tool, a hook's command, a
  compaction's trigger, a fallback's model. An event is an item by its key,
  its kind and the id of the row that records it (`event_key`).

Every source carries the columns the joins start from, whatever the fact:
`transcript_id` the thread, `session_id` and `turn_seq` Pilot's Session and
Turn, `at` the row's moment. A Call's and an Event's also carry the Call's
own facts and its `launch_id`. No join here loses or doubles a row.
"""

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    ColumnElement,
    DateTime,
    Double,
    Integer,
    Numeric,
    Text,
    Uuid,
    and_,
    column,
    func,
    text,
)
from sqlalchemy.sql.expression import FromClause
from sqlalchemy.types import TypeEngine

from app.dashboard.catalogue import Fact, Join, Row
from app.models import (
    Chat,
    ClarificationRun,
    Compaction,
    Component,
    ComponentVersion,
    Environment,
    LaunchComponent,
    Project,
    QuotaWeek,
    Repository,
    Session,
    Transcript,
    Turn,
    User,
    Work,
)
from app.models.call import RECORDED_ELSEWHERE


@dataclass(frozen=True)
class Occurrence:
    """An Event Kind whose occurrences another entity records, which no
    publication names and no row of Event Kind holds: its name, and whether
    it counts as an error."""

    code: str
    name: str
    is_error: bool


OCCURRENCES = (
    Occurrence("compaction", "Compaction", False),
    Occurrence("rewind", "Rewind", False),
    Occurrence("cache_miss", "Cache miss", False),
    Occurrence("past_ttl", "Wait past the cache's lifetime", False),
    Occurrence("model_fallback", "Model fallback", True),
    Occurrence("max_tokens", "Stopped at max tokens", True),
    Occurrence("refusal", "Stopped by a refusal", True),
    Occurrence("output_saved", "Tool output saved to disk", False),
    Occurrence("denied", "Tool use denied", False),
    Occurrence("hook_error", "Hook error", True),
)
"""The kinds of `RECORDED_ELSEWHERE`, in its order."""

_ERROR = {kind.code: str(kind.is_error).lower() for kind in OCCURRENCES}

DETAIL: tuple[tuple[str, TypeEngine[Any]], ...] = (
    ("detail", Text()),
    ("tool_code", Text()),
    ("saved_characters", Integer()),
    ("denial_kind_code", Text()),
    ("hook_command", Text()),
    ("trigger_code", Text()),
    ("fallback_model_code", Text()),
)
"""The Event fact's columns of an event's detail, each its source's: a
stored Event's own qualifier, an API error's status; the tool whose output
was saved or whose use was denied; a saved output's full size in
characters; a denial's kind; a failed hook's command; a compaction's
trigger; the model a fallback's Call was answered by."""

_EVENT_KEY = re.compile(r"([a-z0-9_]+):([1-9][0-9]*)")


def event_key(kind: str, source_id: int) -> str:
    """An event's key as an item: its kind and the id of the row that
    records it, an Event's, a Call's, a Tool Call's or a Hook Run's, which
    its kind says, `cache_miss:42`."""
    return f"{kind}:{source_id}"


def read_event_key(written: str) -> tuple[str, int] | None:
    """An event's kind and the id of the row that records it, from its key;
    none where the key is not of that form."""
    found = _EVENT_KEY.fullmatch(written)
    if found is None:
        return None
    return found[1], int(found[2])


# A Call's own columns as every fact that reaches one carries them, over
# `c`, a Call, and `l`, its Launch.
_OF_A_CALL: tuple[tuple[str, str, TypeEngine[Any]], ...] = (
    ("call_id", "c.id", BigInteger()),
    ("transcript_id", "c.transcript_id", Uuid()),
    ("launch_id", "c.launch_id", BigInteger()),
    ("session_id", "l.session_id", Uuid()),
    ("turn_seq", "l.turn_seq", Integer()),
    ("completed_at", "c.completed_at", DateTime(timezone=True)),
    ("sent_at", "c.sent_at", DateTime(timezone=True)),
    ("model_code", "c.model_code", Text()),
    ("effort", "c.effort", Text()),
    ("stop_reason_code", "c.stop_reason_code", Text()),
    ("miss_cause_code", "c.miss_cause_code", Text()),
    ("compaction_id", "c.compaction_id", BigInteger()),
    ("rewind", "coalesce(c.rewind, false)", Boolean()),
    ("cache_miss", "coalesce(c.cache_miss, false)", Boolean()),
    ("past_ttl", "coalesce(c.past_ttl, false)", Boolean()),
    ("waited_seconds", "c.waited_seconds", Double()),
    ("input_tokens", "c.input_tokens", BigInteger()),
    (
        "cache_write_tokens",
        "c.cache_write_5m_tokens + c.cache_write_1h_tokens",
        BigInteger(),
    ),
    ("cache_read_tokens", "c.cache_read_tokens", BigInteger()),
    ("output_tokens", "c.output_tokens", BigInteger()),
    ("context_tokens", "c.context_tokens", Integer()),
    ("cost", "c.cost", Numeric()),
    ("position", "c.position", Integer()),
)

_CALLS = (
    "SELECT "
    + ", ".join(f"{expression} AS {name}" for name, expression, _ in _OF_A_CALL)
    + " FROM calls AS c LEFT JOIN launches AS l ON l.id = c.launch_id"
)

_UNCOLLECTED = """NOT EXISTS (
    SELECT FROM transcripts AS x
    WHERE x.session_id = s.conversation_id AND x.agent_id IS NULL
)"""
"""Whether the conversation of `s`, a Session, has no Transcript."""

_CALL = f"""
SELECT calls.*, calls.completed_at AS at, false AS estimate FROM ({_CALLS}) AS calls
UNION ALL
SELECT NULL, NULL, NULL, t.session_id, t.seq, coalesce(t.ended_at, t.started_at),
    NULL, NULL, NULL, NULL, NULL, NULL, false, false, false, NULL,
    coalesce(k.input_tokens, 0), coalesce(k.cache_write_tokens, 0),
    coalesce(k.cache_read_tokens, 0), coalesce(k.output_tokens, 0), NULL, t.cost, NULL,
    coalesce(t.ended_at, t.started_at), true
FROM turns AS t
JOIN sessions AS s ON s.id = t.session_id
LEFT JOIN (
    SELECT turn_id,
        sum(tokens) FILTER (WHERE token_kind_code = 'input') AS input_tokens,
        sum(tokens) FILTER (WHERE token_kind_code = 'cache_write') AS cache_write_tokens,
        sum(tokens) FILTER (WHERE token_kind_code = 'cache_read') AS cache_read_tokens,
        sum(tokens) FILTER (WHERE token_kind_code = 'output') AS output_tokens
    FROM token_counts GROUP BY turn_id
) AS k ON k.turn_id = t.id
WHERE {_UNCOLLECTED}
"""

_TURN = """
SELECT t.id AS turn_id, t.session_id, t.seq AS turn_seq, x.id AS transcript_id,
    t.started_at AS at, t.error IS NOT NULL AS failed, t.cost AS reported_cost,
    CAST(extract(epoch FROM t.ended_at - t.started_at) AS double precision) AS seconds
FROM turns AS t
JOIN sessions AS s ON s.id = t.session_id
LEFT JOIN transcripts AS x ON x.session_id = s.conversation_id AND x.agent_id IS NULL
"""

# What the other entities record, each under its Event Kind: a Call's own,
# with its Compaction's; a Tool Call's; and a failed Hook Run's, held on the
# last Call of the Prompt whose run it ended. `source_id` is the id of the row
# that records it, and the detail's columns are those of its source.
_EVENT = f"""
SELECT o.event_id, o.source_id, o.kind_code, o.is_error, o.at, o.detail, o.tool_code,
    o.saved_characters, o.denial_kind_code, o.hook_command, o.trigger_code,
    o.fallback_model_code, calls.*
FROM (
    SELECT e.id AS event_id, e.id AS source_id, e.call_id, e.kind_code, k.is_error, e.at,
        e.detail, NULL AS tool_code, NULL::integer AS saved_characters,
        NULL AS denial_kind_code, NULL AS hook_command, NULL AS trigger_code,
        NULL AS fallback_model_code
    FROM events AS e JOIN event_kinds AS k ON k.code = e.kind_code
    UNION ALL
    SELECT NULL, c.id, c.id, o.kind_code, o.is_error, o.at, NULL, NULL, NULL, NULL, NULL,
        o.trigger_code, o.model_code
    FROM calls AS c
    LEFT JOIN compactions AS m ON m.id = c.compaction_id
    CROSS JOIN LATERAL (VALUES
        ('compaction', m.id IS NOT NULL, {_ERROR["compaction"]}, m.at, m.trigger_code,
            NULL),
        ('rewind', c.rewind, {_ERROR["rewind"]}, c.completed_at, NULL, NULL),
        ('cache_miss', c.cache_miss, {_ERROR["cache_miss"]}, c.completed_at, NULL, NULL),
        ('past_ttl', c.past_ttl, {_ERROR["past_ttl"]}, c.completed_at, NULL, NULL),
        ('model_fallback', c.requested_model_code IS NOT NULL,
            {_ERROR["model_fallback"]}, c.completed_at, NULL, c.model_code),
        ('max_tokens', c.stop_reason_code = 'max_tokens',
            {_ERROR["max_tokens"]}, c.completed_at, NULL, NULL),
        ('refusal', c.stop_reason_code = 'refusal', {_ERROR["refusal"]}, c.completed_at,
            NULL, NULL)
    ) AS o (kind_code, occurred, is_error, at, trigger_code, model_code)
    WHERE o.occurred
    UNION ALL
    SELECT NULL, r.id, r.call_id, o.kind_code, o.is_error,
        coalesce(r.returned_at, r.requested_at), NULL, r.tool_code, o.saved_characters,
        o.denial_kind_code, NULL, NULL, NULL
    FROM tool_calls AS r
    CROSS JOIN LATERAL (VALUES
        ('output_saved', r.saved_characters IS NOT NULL, {_ERROR["output_saved"]},
            r.saved_characters, NULL),
        ('denied', r.denial_kind_code IS NOT NULL, {_ERROR["denied"]}, NULL,
            r.denial_kind_code)
    ) AS o (kind_code, occurred, is_error, saved_characters, denial_kind_code)
    WHERE o.occurred
    UNION ALL
    SELECT NULL, h.id, c.id, 'hook_error', {_ERROR["hook_error"]}, c.completed_at, NULL,
        NULL, NULL, NULL, h.command, NULL, NULL
    FROM hook_runs AS h
    JOIN prompts AS p ON p.id = h.prompt_id
    CROSS JOIN LATERAL (
        SELECT last.id, last.completed_at FROM calls AS last
        WHERE last.transcript_id = p.transcript_id AND last.prompt_id = p.id
        ORDER BY last.position DESC LIMIT 1
    ) AS c
    WHERE h.failed
) AS o
JOIN ({_CALLS}) AS calls ON calls.call_id = o.call_id
"""


def _source(name: str, sql: str, *columns: tuple[str, TypeEngine[Any]]) -> FromClause:
    return (
        text(sql)
        .columns(*(column(key, type_) for key, type_ in columns))
        .subquery(name)
    )


_OF_A_CALL_TYPED = tuple((name, type_) for name, _, type_ in _OF_A_CALL)

CALL = Fact(
    key="call",
    label="Calls",
    one="call",
    many="calls",
    source=_source(
        "call",
        _CALL,
        *_OF_A_CALL_TYPED,
        ("at", DateTime(timezone=True)),
        ("estimate", Boolean()),
    ),
    counts="calls",
    part="call",
)

TURN = Fact(
    key="turn",
    label="Pilot turns",
    one="Pilot turn",
    many="Pilot turns",
    source=_source(
        "turn",
        _TURN,
        ("turn_id", BigInteger()),
        ("session_id", Uuid()),
        ("turn_seq", Integer()),
        ("transcript_id", Uuid()),
        ("at", DateTime(timezone=True)),
        ("failed", Boolean()),
        ("reported_cost", Numeric()),
        ("seconds", Double()),
    ),
    counts="turns",
    part="pturn",
)

EVENT = Fact(
    key="event",
    label="Events",
    one="event",
    many="events",
    source=_source(
        "event",
        _EVENT,
        ("event_id", BigInteger()),
        ("source_id", BigInteger()),
        ("kind_code", Text()),
        ("is_error", Boolean()),
        ("at", DateTime(timezone=True)),
        *DETAIL,
        *_OF_A_CALL_TYPED,
    ),
    counts="events",
    shows=("event_kind", "event_error"),
)

FACTS = (CALL, TURN, EVENT)

assert tuple(kind.code for kind in OCCURRENCES) == RECORDED_ELSEWHERE

# A main thread on no project (DB 540) with the start of its sitting: the
# first Call of the earliest such thread a chain of gaps under `:gap` seconds
# links it to, each gap from the last Call of the threads before to the next
# one's first (DB §2.6, Transcript, `sitting_started_at`).
_SITTING = """
SELECT loose.id, max(loose.first_call_at) FILTER (WHERE loose.opens) OVER (
        ORDER BY loose.first_call_at, loose.id ROWS UNBOUNDED PRECEDING
    ) AS started_at
FROM (
    SELECT t.id, t.first_call_at, coalesce(
        t.first_call_at - max(t.last_call_at) OVER (
            ORDER BY t.first_call_at, t.id
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) >= make_interval(secs => :gap), true) AS opens
    FROM transcripts AS t
    WHERE t.agent_id IS NULL AND t.adopted_project_id IS NULL
        AND t.first_call_at IS NOT NULL
        AND NOT EXISTS (
            SELECT FROM launches AS l
            WHERE l.transcript_id = t.id AND l.session_id IS NOT NULL
        )
) AS loose
"""

_session = Session.__table__.alias("session")
_turn = Turn.__table__.alias("pturn")
_author = User.__table__.alias("author")
_work = Work.__table__.alias("work")
_chat = Chat.__table__.alias("chat")
_clarification = ClarificationRun.__table__.alias("clarification")
_thread = Transcript.__table__.alias("thread")
_main = Transcript.__table__.alias("main")
_project = Project.__table__.alias("project")
_environment = Environment.__table__.alias("environment")
_repository = Repository.__table__.alias("repository")
_quota_week = QuotaWeek.__table__.alias("quota_week")
_compaction = Compaction.__table__.alias("compaction")


def own_joins(sitting_gap: timedelta) -> tuple[Join, ...]:
    """The joins of Pilot's own record and the collector's facts; a sitting
    ends at a gap of `sitting_gap` or more."""
    sitting = (
        text(_SITTING)
        .bindparams(gap=sitting_gap.total_seconds())
        .columns(column("id", Uuid()), column("started_at", DateTime(timezone=True)))
        .subquery("sitting")
    )
    return (
        Join("session", _session, lambda row: _session.c.id == row["session_id"]),
        Join(
            "turn",
            _turn,
            lambda row: and_(
                _turn.c.session_id == row["session_id"],
                _turn.c.seq == row["turn_seq"],
            ),
        ),
        Join(
            "author",
            _author,
            lambda row: _author.c.id == row.to("turn").c.author_user_id,
        ),
        Join("work", _work, lambda row: _work.c.id == row["session_id"]),
        Join("chat", _chat, lambda row: _chat.c.id == row["session_id"]),
        Join(
            "clarification",
            _clarification,
            lambda row: _clarification.c.id == row["session_id"],
        ),
        Join("thread", _thread, lambda row: _thread.c.id == row["transcript_id"]),
        Join("main", _main, lambda row: _main.c.id == _main_id(row)),
        Join(
            "project",
            _project,
            lambda row: (
                _project.c.id
                == func.coalesce(
                    row.to("session").c.project_id, row.to("main").c.adopted_project_id
                )
            ),
        ),
        Join(
            "environment",
            _environment,
            lambda row: (
                _environment.c.id
                == func.coalesce(
                    row.to("main").c.environment_id, row.to("session").c.environment_id
                )
            ),
        ),
        Join(
            "repository",
            _repository,
            lambda row: _repository.c.id == row.to("thread").c.repository_id,
        ),
        Join(
            "quota_week",
            _quota_week,
            lambda row: and_(
                _quota_week.c.starts_at <= row["at"], row["at"] < _quota_week.c.ends_at
            ),
        ),
        Join("sitting", sitting, lambda row: sitting.c.id == _main_id(row)),
        Join(
            "compaction",
            _compaction,
            lambda row: _compaction.c.id == row["compaction_id"],
        ),
    )


def _main_id(row: Row) -> ColumnElement[Any]:
    thread = row.to("thread")
    return func.coalesce(thread.c.main_id, thread.c.id)


def version_joins(component: Component) -> tuple[Join, Join]:
    """The joins from a row's Launch to the version of `component` it ran
    with, one at most (DB 541): its Launch Component, then the version. The
    joins hold the Component's code, never the row, which the session that
    read it lets go while the process keeps the catalogue."""
    code = component.code
    used = LaunchComponent.__table__.alias(f"used_{code}")
    version = ComponentVersion.__table__.alias(version_join(code))
    return (
        Join(
            used.name,
            used,
            lambda row: and_(
                used.c.launch_id == row["launch_id"],
                used.c.component_code == code,
            ),
        ),
        Join(
            version.name,
            version,
            lambda row: version.c.id == row.to(used.name).c.component_version_id,
        ),
    )


def version_join(component_code: str) -> str:
    """The key of the join that reaches the version of the Component a
    row's Launch ran with."""
    return f"version_{component_code}"
