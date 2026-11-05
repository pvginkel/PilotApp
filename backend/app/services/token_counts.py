"""A Turn's tokens and its cost, read from `claude`'s `result` line (F135.9;
DB decision 67, assertions 272, 273 and 275).

A `result` line's `modelUsage` gives each model the run called with its counts,
sub-agents included; its `usage` counts the main thread's calls alone. The
counts are therefore `modelUsage`'s, summed over its models, and the cost the
line's `total_cost_usd`.

A run that resumes a conversation starts from the figures the conversation's
last run left, so its `result` line reports the conversation's figures so far,
`sessions.conversation_id` spanning its Sessions. A Turn's own are its line's
less the line of the conversation's previous Turn that reported, that Turn's
last one `spent` reads. A line with any figure below that line's is a fresh
total, and the Turn's own as it is.

One run can print several `result` lines, one at each end of its main loop, as
when a backgrounded task wakes it again; each carries the run's figures so far.
So each `result` line recorded writes the Turn's own counts and cost from that
line, in place of an earlier line's, and the last line's figures stand. A line
whose `modelUsage` is not `claude`'s shape writes nothing, as does every other
line.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Session as AgentSession
from app.models import TokenCount, Turn
from app.models.reference import RecordKind, TokenKind
from app.services.session_record_service import read_records

_FIELDS = {
    TokenKind.INPUT: "inputTokens",
    TokenKind.CACHE_WRITE: "cacheCreationInputTokens",
    TokenKind.CACHE_READ: "cacheReadInputTokens",
    TokenKind.OUTPUT: "outputTokens",
}
"""Each kind's field in a model's entry of `modelUsage`."""

# The `result` lines of a Turn read at a time, newest first.
_PAGE = 8


@dataclass(frozen=True)
class Spent:
    """What a `result` line reports its run spent, or what a Turn spent: the
    tokens of every kind, summed over the models it called, and the cost in
    US dollars, None where the line gives none."""

    tokens: Mapping[TokenKind, int]
    cost: Decimal | None

    def less(self, before: "Spent | None") -> "Spent":
        """These figures less `before`, the figures the conversation reported
        last before them; these as they are without `before`, and where any
        of them is below its own there, a fresh total. Where either lacks a
        cost, the cost is this one's."""
        if before is None or not self._carry_on(before):
            return self
        return Spent(
            {
                kind: tokens - before.tokens[kind]
                for kind, tokens in self.tokens.items()
            },
            self.cost
            if self.cost is None or before.cost is None
            else self.cost - before.cost,
        )

    def _carry_on(self, before: "Spent") -> bool:
        return all(
            tokens >= before.tokens[kind] for kind, tokens in self.tokens.items()
        ) and (self.cost is None or before.cost is None or self.cost >= before.cost)


def spent(line: Any) -> Spent | None:
    """What the raw line `claude` printed reports its run spent; None unless
    it is a `result` line whose `modelUsage` maps each model to its counts,
    a count it leaves out being 0."""
    if not isinstance(line, dict) or line.get("type") != "result":
        return None
    models = line.get("modelUsage")
    if not isinstance(models, dict) or not all(
        isinstance(model, dict) for model in models.values()
    ):
        return None
    tokens: dict[TokenKind, int] = {}
    for kind, field in _FIELDS.items():
        counts = [model.get(field, 0) for model in models.values()]
        if not all(_is_count(count) for count in counts):
            return None
        tokens[kind] = sum(counts)
    cost = line.get("total_cost_usd")
    return Spent(tokens, Decimal(str(cost)) if _is_amount(cost) else None)


def count_tokens(db: Session, turn_id: int, line: Any) -> None:
    """Write the Turn's own counts and cost from the raw line `claude` printed
    in it, when the line reports what its run spent (`spent`): its figures
    less those the conversation reported last before the Turn."""
    reported = spent(line)
    if reported is None:
        return
    reported = reported.less(reported_before(db, turn_id))
    statement = insert(TokenCount).values(
        [
            {"turn_id": turn_id, "token_kind_code": kind, "tokens": tokens}
            for kind, tokens in reported.tokens.items()
        ]
    )
    db.execute(
        statement.on_conflict_do_update(
            index_elements=[TokenCount.turn_id, TokenCount.token_kind_code],
            set_={"tokens": statement.excluded.tokens},
        )
    )
    db.get_one(Turn, turn_id).cost = reported.cost


def reported_before(db: Session, turn_id: int) -> Spent | None:
    """The figures the Turn's conversation reported last before it: the last
    `result` line `spent` reads of the conversation's latest earlier Turn that
    has Token Counts, the conversation spanning its Sessions; None where none
    has."""
    conversation = db.scalar(
        select(AgentSession.conversation_id)
        .join(Turn, Turn.session_id == AgentSession.id)
        .where(Turn.id == turn_id)
    )
    if conversation is None:
        return None
    previous = db.execute(
        select(Turn.id, Turn.session_id)
        .join(AgentSession, AgentSession.id == Turn.session_id)
        .where(
            AgentSession.conversation_id == conversation,
            Turn.id < turn_id,
            select(TokenCount.id).where(TokenCount.turn_id == Turn.id).exists(),
        )
        .order_by(Turn.id.desc())
        .limit(1)
    ).first()
    if previous is None:
        return None
    before = None
    while True:
        # A Turn with Token Counts has a line `spent` reads (DB 275).
        page = read_records(
            db,
            previous.session_id,
            before=before,
            turn_id=previous.id,
            kind=RecordKind.CLAUDE,
            payload_type="result",
            limit=_PAGE,
            newest_first=True,
        )
        for stored in page:
            reported = spent(stored.record.payload)
            if reported is not None:
                return reported
        before = page[-1].record.seq


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_amount(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )
