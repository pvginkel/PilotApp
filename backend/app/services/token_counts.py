"""A Turn's tokens and its cost, read from `claude`'s `result` line (F135.9;
DB decision 67, assertions 272, 273 and 275).

KubeCoder runs a fresh `claude` per turn, so what a run reports is the turn's
own. A `result` line's `modelUsage` gives each model the run called with its
counts, sub-agents included; its `usage` counts the main thread's calls alone.
The counts are therefore `modelUsage`'s, summed over its models, and the cost
the line's `total_cost_usd`.

One run can print several `result` lines, one at each end of its main loop, as
when a backgrounded task wakes it again; each carries the run's figures so far.
So each `result` line recorded writes the Turn's counts and cost from that line
alone, in place of an earlier line's, and the last line's figures stand. A line
whose `modelUsage` is not `claude`'s shape writes nothing, as does every other
line.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import TokenCount, Turn
from app.models.reference import TokenKind

_FIELDS = {
    TokenKind.INPUT: "inputTokens",
    TokenKind.CACHE_WRITE: "cacheCreationInputTokens",
    TokenKind.CACHE_READ: "cacheReadInputTokens",
    TokenKind.OUTPUT: "outputTokens",
}
"""Each kind's field in a model's entry of `modelUsage`."""


@dataclass(frozen=True)
class Spent:
    """What a `result` line reports its run spent: the tokens of every kind,
    summed over the models it called, and the cost in US dollars, None where
    the line gives none."""

    tokens: Mapping[TokenKind, int]
    cost: Decimal | None


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
    """Write the Turn's counts and cost from the raw line `claude` printed in
    it, when the line reports what its run spent (`spent`)."""
    reported = spent(line)
    if reported is None:
        return
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


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_amount(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )
