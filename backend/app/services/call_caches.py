"""A Call's derived caches beside its cost, and a Transcript's (DB §2.7,
Call; §7.4; decision 79.14; assertions 543 and 546).

One statement says what a Call's are (`_DERIVED`), with *predecessor* the
Call its `predecessor_id` names:

- `waited_seconds`: from its predecessor's `completed_at` to its own
  `sent_at`, or to its `completed_at` where it has no `sent_at`; none on a
  Call with no predecessor.
- `rewind`: its predecessor is another Call than the one before it by
  `position`.
- `cache_miss` (DB 546): with *left* the cache-read and cache-write tokens
  of its predecessor and *ref* the lesser of *left* and its own
  `context_tokens`, more than half of *ref* was not read from the cache, and
  its `context_tokens` is at least nine tenths of *left*.
- `past_ttl`: `waited_seconds` exceeds the lifetime of the cache its
  predecessor wrote, an hour where it wrote a one-hour cache, else five
  minutes where it wrote a five-minute one. A predecessor that wrote none
  left no lifetime to exceed.
- `launch_id` (DB 543): its Prompt's Launch, or, for a sub-agent's thread,
  the Launch of its main thread whose `started_at` and `ended_at` hold its
  `completed_at`, a Launch with no `ended_at` holding every moment from its
  start on.

A Call with no predecessor is no rewind, no miss and past no lifetime.

A publication derives them for the Calls it carries before it writes them
(`caches`), a main thread's also the Launch of each Call its sub-agents'
threads hold (`hold_sub_agents_calls`): a main thread published after its
sub-agents' threads, or whose Launches moved, leaves those Calls in the
Launch that now holds them.

A Transcript's `first_call_at` and `last_call_at` are the `completed_at` of
its first and of its last Call by `position`; the publication sets them with
the Transcript's row.

A server from before these caches writes a Call with none, and leaves its
Transcript's two times as they stood: the release before this one takes
publications while the next one starts. `CallCacheService.derive` gives
every stored Call whose flags are none its caches, and those Calls'
Transcripts their two times; a deploy runs it after the revisions
(`post_migration_hook`).
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.call import CONTEXT_TOKENS, PRICED_KINDS

_TOKEN_COLUMNS = tuple(f"{kind}_tokens" for kind in PRICED_KINDS)

_CACHES = ("waited_seconds", "rewind", "cache_miss", "past_ttl", "launch_id")

_HELD_IN = """(
    SELECT l.id FROM launches AS l
    WHERE l.transcript_id = t.main_id AND l.started_at <= c.completed_at
        AND (l.ended_at IS NULL OR c.completed_at <= l.ended_at)
    ORDER BY l.started_at DESC LIMIT 1
)"""
"""The Launch of the main thread of `t`, a sub-agent's thread, that holds
the `completed_at` of `c`, a Call of `t`."""

_DERIVED = f"""
SELECT c.id, w.waited_seconds,
    coalesce(p.position <> c.position - 1, false) AS rewind,
    coalesce(2 * (least(w.left_cached, c.context_tokens) - c.cache_read_tokens)
            > least(w.left_cached, c.context_tokens)
        AND 10 * c.context_tokens >= 9 * w.left_cached, false) AS cache_miss,
    coalesce(w.waited_seconds > CASE WHEN p.cache_write_1h_tokens > 0 THEN 3600
        WHEN p.cache_write_5m_tokens > 0 THEN 300 END, false) AS past_ttl,
    coalesce(prompts.launch_id, {_HELD_IN}) AS launch_id
FROM {{calls}} AS c
JOIN transcripts AS t ON t.id = c.transcript_id
LEFT JOIN {{earlier}} AS p ON p.id = c.predecessor_id
LEFT JOIN prompts ON prompts.id = c.prompt_id
CROSS JOIN LATERAL (
    SELECT CAST(extract(epoch FROM coalesce(c.sent_at, c.completed_at)
            - p.completed_at) AS double precision) AS waited_seconds,
        p.cache_read_tokens + p.cache_write_5m_tokens + p.cache_write_1h_tokens
            AS left_cached
) AS w
"""
"""Each Call of `calls` with its caches, its predecessor read from
`earlier`."""

_GIVEN = f"""
WITH given AS MATERIALIZED (
    SELECT *, {CONTEXT_TOKENS} AS context_tokens
    FROM jsonb_to_recordset(CAST(:calls AS jsonb)) AS given (
        id bigint, transcript_id uuid, position integer, prompt_id bigint,
        predecessor_id bigint, sent_at timestamptz, completed_at timestamptz,
        {", ".join(f"{column} integer" for column in _TOKEN_COLUMNS)}
    )
)
"""
"""The Calls a caller gives, as a Call's row has them."""

_EARLIER = """(
    SELECT id, position, completed_at, cache_read_tokens, cache_write_5m_tokens,
        cache_write_1h_tokens
    FROM given
    UNION ALL
    SELECT id, position, completed_at, cache_read_tokens, cache_write_5m_tokens,
        cache_write_1h_tokens
    FROM calls WHERE id = ANY(CAST(:stored AS bigint[]))
)"""
"""The Calls a given Call's predecessor is among: the Calls given, and the
stored ones of the ids `stored`."""

_DERIVE = f"""
WITH derived AS (
    UPDATE calls SET {", ".join(f"{cache} = d.{cache}" for cache in _CACHES)}
    FROM ({_DERIVED.format(calls="calls", earlier="calls")}
        WHERE c.rewind IS NULL) AS d
    WHERE calls.id = d.id
    RETURNING calls.transcript_id
)
SELECT transcript_id, count(*) AS calls FROM derived GROUP BY transcript_id
"""
"""Give every stored Call whose flags are none its caches; the Transcripts
of those Calls, each with their number."""

_TIME = """
UPDATE transcripts SET
    first_call_at = (
        SELECT completed_at FROM calls WHERE transcript_id = transcripts.id
        ORDER BY position LIMIT 1
    ),
    last_call_at = (
        SELECT completed_at FROM calls WHERE transcript_id = transcripts.id
        ORDER BY position DESC LIMIT 1
    )
WHERE id = ANY(CAST(:transcripts AS uuid[]))
"""
"""Give the Transcripts of those ids their first and their last Call's
time."""

_HOLD = f"""
UPDATE calls SET launch_id = held.launch_id
FROM (
    SELECT c.id, {_HELD_IN} AS launch_id
    FROM calls AS c
    JOIN transcripts AS t ON t.id = c.transcript_id
    WHERE t.session_id = :conversation AND t.agent_id IS NOT NULL
) AS held
WHERE calls.id = held.id AND calls.launch_id IS DISTINCT FROM held.launch_id
"""
"""Leave each Call of the conversation's sub-agents' threads in the Launch
of their main thread that holds it, written where it is in another."""


@dataclass(frozen=True)
class Derived:
    """What a run of the step wrote: the Calls it gave their caches, and the
    Transcripts of those Calls, which it gave their two times."""

    calls: int
    transcripts: int


def caches(db: Session, calls: Sequence[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """The caches of each Call given, by its `id`, as `db` reads the record.
    A Call is given as its row has it: its `id`, its `transcript_id`, its
    `position`, its `prompt_id`, its `predecessor_id`, its `sent_at`, its
    `completed_at` and its tokens by kind, a `_tokens` column each. Its
    Transcript and its Prompt have their rows, and its predecessor is a Call
    given or a stored one."""
    if not calls:
        return {}
    ids = {call["id"] for call in calls}
    stored = {call["predecessor_id"] for call in calls} - ids - {None}
    given = json.dumps(
        [
            {
                "id": call["id"],
                "transcript_id": str(call["transcript_id"]),
                "position": call["position"],
                "prompt_id": call["prompt_id"],
                "predecessor_id": call["predecessor_id"],
                "sent_at": call["sent_at"] and call["sent_at"].isoformat(),
                "completed_at": call["completed_at"].isoformat(),
            }
            | {column: call[column] for column in _TOKEN_COLUMNS}
            for call in calls
        ]
    )
    return {
        row.id: {cache: getattr(row, cache) for cache in _CACHES}
        for row in db.execute(
            text(_GIVEN + _DERIVED.format(calls="given", earlier=_EARLIER)),
            {"calls": given, "stored": sorted(stored)},
        )
    }


def hold_sub_agents_calls(db: Session, conversation: str) -> None:
    """Leave each Call of the sub-agents' threads of the conversation of
    that id of Claude Code's in the Launch of its main thread that holds it
    (DB 543), none where none does. A Call in that Launch already is not
    written."""
    db.execute(text(_HOLD), {"conversation": conversation})


class CallCacheService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def derive(self) -> Derived:
        """Give every stored Call whose flags are none its caches, and each
        Transcript of such a Call its first and its last Call's time, in the
        caller's transaction. A Call the session holds is not read again.

        A Call written while this runs keeps its flags none, and its
        Transcript is brought right with it by the next run."""
        derived = {
            row.transcript_id: row.calls for row in self.db.execute(text(_DERIVE))
        }
        if derived:
            self.db.execute(
                text(_TIME), {"transcripts": [str(thread) for thread in derived]}
            )
        return Derived(calls=sum(derived.values()), transcripts=len(derived))
