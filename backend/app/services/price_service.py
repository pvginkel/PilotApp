"""The Prices, loaded from the price file, a Model priced as another, and a
Call's cost (DB §2.7, Price and Call; §2.11, Model; decision 79.22; F152.12).

The price file, `app/prices.csv`, is the list of the models' public prices.
A load adds each row of it the Prices do not hold and changes and removes
none; it adds a Model the file names that no Call has met. A deploy loads it
after the revisions (`post_migration_hook`), and so does the load of the
invented record.

A Call's `cost` is, for each Token Kind it counts tokens of, those tokens at
the Price of that kind for its Model, or for the Model it is `priced_as`,
with the greatest `above_context` not above its `context_tokens`, in force
at its `completed_at` (DB 548). A Call that counts tokens of a kind no such
Price covers has no cost. One statement says it (`_priced`), for a
publication's Calls before it writes them (`costs`) and for the Calls stored
(`PriceService.load`).

A Model with no Price of its own is priced as another, set once, when it is
first met (`price_as_family`): a dated snapshot, such as
`claude-haiku-4-5-20251001`, as the Model it is a snapshot of where the
Prices know that one, else as the newest Model of its family the Prices
know. A Model's family is the word after `claude-` in its code, and the
newest of a family is the one with the highest version in its code. Once the
file names a Model, a load drops its `priced_as`.

A load and a publication take turns (`prices_turn`): a load waits for the
publications in flight and holds off the next ones until it has committed,
so that no Call is priced at the Prices of before a load and written after
it. After it has written, a load prices the Calls of each Model whose prices
it changed, and every Call stored with no cost, the ones a server that
priced nothing wrote among them.
"""

import csv
import json
import re
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import CursorResult, Integer, cast, func, literal, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.exceptions import InvalidOperationException
from app.models import Model, Price
from app.models.call import CONTEXT_TOKENS, PRICED_KINDS

PRICE_FILE = Path(__file__).resolve().parents[1] / "prices.csv"

PRICES_LOCK = 261
"""The first key of the Prices' turn (`advisory_turn`); the second is 0."""

_TOKEN_COLUMNS = tuple(f"{kind}_tokens" for kind in PRICED_KINDS)

_PRICED = f"""
SELECT c.id, priced.cost
FROM {{calls}} AS c
JOIN models AS m ON m.code = c.model_code
CROSS JOIN LATERAL (
    SELECT CASE WHEN count(p.rate) = count(*)
        THEN trim_scale(coalesce(sum(k.tokens * p.rate), 0) / 1000000) END AS cost
    FROM (VALUES {", ".join(f"('{kind}', c.{kind}_tokens)" for kind in PRICED_KINDS)})
        AS k (kind, tokens)
    LEFT JOIN LATERAL (
        SELECT rate FROM prices
        WHERE model_code = coalesce(m.priced_as_code, m.code)
            AND token_kind_code = k.kind
            AND effective_at <= c.completed_at
            AND (above_context IS NULL OR above_context <= c.context_tokens)
        ORDER BY above_context DESC NULLS LAST, effective_at DESC
        LIMIT 1
    ) AS p ON true
    WHERE k.tokens > 0
) AS priced
"""
"""Each Call of `calls` with its cost (DB 548)."""

_GIVEN = f"""(
    SELECT *, {CONTEXT_TOKENS} AS context_tokens
    FROM jsonb_to_recordset(CAST(:calls AS jsonb)) AS given (
        id bigint, model_code text, completed_at timestamptz,
        {", ".join(f"{column} integer" for column in _TOKEN_COLUMNS)}
    )
)"""
"""The Calls a caller gives, as a Call's row has them."""

_REPRICE = f"""
UPDATE calls SET cost = priced.cost
FROM ({_PRICED.format(calls="calls")} WHERE {{scope}}) AS priced
WHERE calls.id = priced.id AND calls.cost IS DISTINCT FROM priced.cost
"""
"""Give the stored Calls of `scope` their cost, where it is another."""


@dataclass(frozen=True)
class FilePrice:
    """A row of the price file."""

    model: str
    token_kind: str
    above_context: int | None
    rate: Decimal
    effective_at: datetime

    @property
    def key(self) -> tuple[str, str, int | None, datetime]:
        """What tells a Price from every other."""
        return (self.model, self.token_kind, self.above_context, self.effective_at)


@dataclass(frozen=True)
class PriceLoad:
    """What a load wrote: the Prices it added, the Models it gave a
    `priced_as` or took one from, and the Calls whose cost it set."""

    prices: int
    models: int
    calls: int


def read_price_file(path: Path = PRICE_FILE) -> list[FilePrice]:
    """The rows of the price file at `path`, in its order. A line that opens
    with `#` is a comment."""
    with path.open(newline="", encoding="utf-8") as file:
        rows = csv.DictReader(line for line in file if not line.startswith("#"))
        return [
            FilePrice(
                model=row["model"],
                token_kind=row["token_kind"],
                above_context=int(row["above_context"])
                if row["above_context"]
                else None,
                rate=Decimal(row["rate"]),
                effective_at=datetime.combine(
                    date.fromisoformat(row["effective_from"]), time(), UTC
                ),
            )
            for row in rows
        ]


def prices_turn(db: Session, *, load: bool = False) -> None:
    """Take the Prices' turn, held until `db`'s transaction ends: a load's
    alone, a publication's beside every other publication's."""
    lock = func.pg_advisory_xact_lock if load else func.pg_advisory_xact_lock_shared
    db.execute(
        select(lock(cast(literal(PRICES_LOCK), Integer), cast(literal(0), Integer)))
    )


def family(code: str) -> str | None:
    """The family of the Model of that code: the word after `claude-`."""
    words = code.split("-")
    return words[1] if words[0] == "claude" and len(words) > 1 else None


def _snapshot_of(code: str) -> str | None:
    """The code of the Model a dated snapshot is of."""
    base, _, dated = code.rpartition("-")
    return base if re.fullmatch(r"\d{8}", dated) else None


def _version(code: str) -> tuple[int, ...]:
    """The version in a Model's code: `claude-opus-5-5`'s is 5.5."""
    return tuple(
        int(word) for word in code.split("-")[2:] if word.isdigit() and len(word) < 8
    )


def priced_as(code: str, priced: Collection[str]) -> str | None:
    """The Model the Model of `code`, which has no Price, takes its Prices
    from, among `priced`, the Models the Prices know; none where they know
    none of its family."""
    base = _snapshot_of(code)
    if base in priced:
        return base
    named = family(code)
    kin = [other for other in priced if named is not None and family(other) == named]
    return max(
        kin,
        key=lambda other: (_version(other), _snapshot_of(other) is None, other),
        default=None,
    )


def price_as_family(db: Session, codes: Iterable[str] | None = None) -> list[str]:
    """Give each Model of `codes`, each Model there is by default, that has
    neither a Price nor a `priced_as` the Model it is priced as, where the
    Prices know one. Returned are the codes of the Models given one."""
    unpriced = (
        select(Model)
        .where(
            Model.priced_as_code.is_(None),
            Model.code.not_in(select(Price.model_code)),
        )
        .order_by(Model.code)
    )
    if codes is not None:
        unpriced = unpriced.where(Model.code.in_(sorted(codes)))
    waiting = db.scalars(unpriced).all()
    if not waiting:
        return []
    priced = set(db.scalars(select(Price.model_code).distinct()))
    given: list[str] = []
    for model in waiting:
        lender = priced_as(model.code, priced)
        if lender is not None:
            model.priced_as_code = lender
            given.append(model.code)
    db.flush()
    return given


def costs(db: Session, calls: Sequence[dict[str, Any]]) -> dict[int, Decimal | None]:
    """The cost of each Call given, by its `id`, at the Prices `db` reads.
    A Call is given as its row has it: its `id`, its `model_code`, its
    `completed_at` and its tokens by kind, a `_tokens` column each. Its
    Model has a row."""
    if not calls:
        return {}
    given = json.dumps(
        [
            {
                "id": call["id"],
                "model_code": call["model_code"],
                "completed_at": call["completed_at"].isoformat(),
            }
            | {column: call[column] for column in _TOKEN_COLUMNS}
            for call in calls
        ]
    )
    return {
        row.id: row.cost
        for row in db.execute(text(_PRICED.format(calls=_GIVEN)), {"calls": given})
    }


class PriceService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def load(self, rows: Sequence[FilePrice]) -> PriceLoad:
        """Load the price file's rows, in the caller's transaction.

        Each row the Prices do not hold is added, and none is removed. A
        Model a row names that Pilot has not met is written, named by its
        code. A Model the Prices know loses its `priced_as`, and each Model
        with neither a Price nor a `priced_as` is given one
        (`price_as_family`). The stored Calls of every Model whose prices
        that changed, and every stored Call with no cost, are priced. A Call
        the session holds is not read again.

        Raises:
            InvalidOperationException: a row gives another rate than the
                Price Pilot holds of its Model, Token Kind, `above_context`
                and moment; nothing is written.
        """
        prices_turn(self.db, load=True)
        held = {
            (model, kind, above_context, effective_at): rate
            for model, kind, above_context, effective_at, rate in self.db.execute(
                select(
                    Price.model_code,
                    Price.token_kind_code,
                    Price.above_context,
                    Price.effective_at,
                    Price.rate,
                )
            )
        }
        edited = [row for row in rows if held.get(row.key, row.rate) != row.rate]
        if edited:
            raise InvalidOperationException(
                "load the prices",
                "the price file changes "
                + ", ".join(_described(row, held[row.key]) for row in edited)
                + "; a rate that changed is a new row with its own date",
            )
        gained = [row for row in rows if row.key not in held]
        named = sorted({row.model for row in gained})
        if named:
            self.db.execute(
                pg_insert(Model).on_conflict_do_nothing(),
                [{"code": code, "name": code} for code in named],
            )
            self.db.execute(
                pg_insert(Price),
                [
                    {
                        "model_code": row.model,
                        "token_kind_code": row.token_kind,
                        "above_context": row.above_context,
                        "rate": row.rate,
                        "effective_at": row.effective_at,
                    }
                    for row in gained
                ],
            )
        freed = self.db.scalars(
            update(Model)
            .where(
                Model.priced_as_code.is_not(None),
                Model.code.in_(select(Price.model_code)),
            )
            .values(priced_as_code=None)
            .returning(Model.code)
        ).all()
        lent = price_as_family(self.db)
        moved = sorted({*named, *freed, *lent})
        calls = self._reprice("c.cost IS NULL")
        if moved:
            takers = self.db.scalars(
                select(Model.code).where(
                    Model.code.in_(moved) | Model.priced_as_code.in_(moved)
                )
            ).all()
            calls += self._reprice("c.model_code = ANY(:models)", models=list(takers))
        return PriceLoad(prices=len(gained), models=len(freed) + len(lent), calls=calls)

    def _reprice(self, scope: str, **values: Any) -> int:
        """Price the stored Calls of `scope`; the number whose cost it set."""
        result = self.db.execute(text(_REPRICE.format(scope=scope)), values)
        assert isinstance(result, CursorResult)
        return result.rowcount


def _described(row: FilePrice, held: Decimal) -> str:
    context = f" above {row.above_context:,} tokens" if row.above_context else ""
    return (
        f"{row.model}'s {row.token_kind} rate{context} of "
        f"{row.effective_at.date().isoformat()} from {held.normalize():f} to "
        f"{row.rate.normalize():f}"
    )
