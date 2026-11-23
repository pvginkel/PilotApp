"""The two counts (F154.6), each answered as a task, and one attribute's
values in a view's scope, searched, answered at once (`architecture.md`
Part 1, "The routes, by what they answer").

- **The attributes' counts**, asked when By's panel opens: each
  dimension's count of values in the view's scope, none counting as one,
  under every chip, its own included, so that a drilled project reads one
  (F163.2); an order dimension its part's. Each is counted on the first
  fact that offers it, one statement a fact, and each fact's counts are
  handed on as they come.
- **The quick filters' counts and amounts**, asked with the view: each
  quick filter's count, the rows it keeps of the fact its condition is on
  or the items of its grain among them, and its figure summed over the rows
  it keeps, in the view's scope and under the quick filters that are on, so
  that one that is on narrows the others' (F162.6); one statement a fact,
  so that no query of the view groups twice for one, an each-item filter
  coarser than the call among them. One on the By's rows, the outlier rows'
  or a threshold's, counts the By's rows it keeps, judged on the rows of
  the view's first measure or of its threshold's, and its figure summed over
  them; one of those that is on narrows the others to the rows it keeps.
- **One attribute's values**, for a filter's pane: in the view's scope
  without the attribute's own chips, so that its other values show, each
  value with its rows and its cost, those whose label or key holds the
  words searched, the largest cost first, a time's in their order; at most
  `VALUES`, with the count of all.

Each counts in the scope before a threshold on the By's rows and the
outlier rows' chip (D5), `Plan.scope`, and every statement runs under the
engine's bounds. A task is answered when it is done, its reads one after
another, each fact's attributes' count in a read of its own, and the quick
filters' judging of the By's rows in one and their tallies in another, so
that only a read, never the task whole, is held to the engine's timeout.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.dashboard.address import Address, AddressService, View
from app.dashboard.bounds import Bounds
from app.dashboard.catalogue import Catalogue, Dimension, QuickFilter
from app.dashboard.outliers import outliers
from app.dashboard.planner import Condition, Plan, Threshold, plan
from app.dashboard.reading import read_chip
from app.dashboard.refusal import listed, nearest, quoted
from app.dashboard.rows import Shaper, ran, value_label
from app.dashboard.state import (
    Chip,
    Measure,
    OnItems,
    OnRows,
    Outliers,
    Pin,
    Simple,
    Value,
)
from app.dashboard.statements import (
    Tally,
    attributes,
    statements,
    tallied,
    valued,
)
from app.exceptions import ValidationException

VALUES = 200
"""The values an attribute's answer carries at most."""

COST = "cost"
"""The figure a value's amount is the sum of."""


@dataclass(frozen=True)
class Count:
    """A dimension's count of values in a view's scope."""

    dimension: str
    count: int


Counted = Callable[[tuple[Count, ...], int, int], None]
"""Handed each fact's counts as they come, with the facts counted so far
and the facts there are to count."""


@dataclass(frozen=True)
class QuickFilterCount:
    """A quick filter's count in a view's scope, and its figure's sum over
    what it keeps, none where it names no figure."""

    key: str
    count: int
    amount: float | None


@dataclass(frozen=True)
class AttributeValue:
    """One value of an attribute in a view's scope: `key` typed as its
    dimension reads it, `label` none where the key is its own, its rows, and
    their cost, none where the attribute's fact has no cost."""

    key: Value
    label: str | None
    count: int
    cost: float | None


@dataclass(frozen=True)
class Values:
    """An attribute's values in a view's scope, at most `VALUES` of the
    `total` that the search keeps."""

    address: Address
    zone: str
    dimension: Dimension
    values: tuple[AttributeValue, ...]
    total: int


class CountsService:
    """The two counts of a view, and an attribute's values."""

    def __init__(
        self, db: Session, address_service: AddressService, bounds: Bounds
    ) -> None:
        self.db = db
        self.address_service = address_service
        self.bounds = bounds

    def attributes(
        self, view: View, now: datetime, counted: Counted | None = None
    ) -> tuple[Count, ...]:
        """Each dimension's count of values in the view's scope, its time
        as it stands at `now`, in the catalogue's order; `counted` handed
        each fact's.

        Raises:
            QueryRefusedException: a statement passed the engine's bounds
        """
        catalogue = view.catalogue
        found = _scope(plan(view.address.state, catalogue, view.weeks, now))
        homes: dict[str, list[str]] = {}
        for dimension in catalogue.dimensions:
            offered = catalogue.offered(dimension.key)
            if dimension.base is None and offered:
                homes.setdefault(offered[0], []).append(dimension.key)
        facts = [fact.key for fact in catalogue.facts if fact.key in homes]
        counts: dict[str, int] = {}
        for done, fact in enumerate(facts, start=1):
            keys = homes[fact]
            with self.bounds.read(self.db) as db:
                found_row = db.execute(
                    attributes(found, catalogue, fact, keys).select
                ).one()
            part = {key: _counted(found_row, index) for index, key in enumerate(keys)}
            part.update(
                {
                    dimension.key: part[dimension.base]
                    for dimension in catalogue.dimensions
                    if dimension.base in part
                }
            )
            counts.update(part)
            if counted is not None:
                counted(
                    tuple(Count(key, count) for key, count in part.items()),
                    done,
                    len(facts),
                )
        return tuple(
            Count(dimension.key, counts.get(dimension.key, 0))
            for dimension in catalogue.dimensions
        )

    def quick_filters(self, view: View, now: datetime) -> tuple[QuickFilterCount, ...]:
        """Each quick filter's count and amount in the view's scope, under
        the quick filters that are on, its time as it stands at `now`, in
        the catalogue's order.

        Raises:
            QueryRefusedException: a statement passed the engine's bounds
        """
        catalogue = view.catalogue
        held = catalogue.quick_filters
        chips = [
            read_chip(quick_filter.condition, catalogue, view.weeks)
            for quick_filter in held
        ]
        found = _scope(plan(view.address.state, catalogue, view.weeks, now))
        with self.bounds.read(self.db) as db:
            judged, narrowed = _on_rows(db, view, now, held, chips)
        if narrowed is not None:
            found = replace(found, rows=tuple(narrowed))
        with self.bounds.read(self.db) as db:
            counted = _tallied(db, found, catalogue, held, chips, judged)
        return tuple(
            judged[index] if index in judged else counted[index]
            for index in range(len(held))
        )

    def values(
        self,
        written: str,
        dimension: str,
        search: str | None = None,
        now: datetime | None = None,
    ) -> Values:
        """The values of the attribute `dimension` in the scope of the
        state `written` without its own chips, its time as it stands at
        `now`, those whose label or key holds `search`, the case aside.

        Raises:
            StateRefusedException: the state has a fault
            ValidationException: the catalogue has no dimension `dimension`
            QueryRefusedException: a statement passed the engine's bounds
        """
        view = self.address_service.view(written)
        catalogue = view.catalogue
        keys = [one.key for one in catalogue.dimensions]
        if dimension not in keys:
            near = nearest(dimension, keys)
            raise ValidationException(
                f'Cannot list the values of "{dimension}" because it is no '
                "dimension of the catalogue's."
                + (f" Did you mean {listed(quoted(near), 'or')}?" if near else "")
            )
        chosen = catalogue.dimension(dimension)
        state = view.address.state
        own = replace(
            state,
            chips=tuple(
                chip
                for chip in state.chips
                if not (isinstance(chip, Pin) and chip.dimension == dimension)
            ),
        )
        found = _scope(plan(own, catalogue, view.weeks, now or datetime.now(UTC)))
        words = (search or "").strip().casefold() or None
        closed = chosen.values is not None
        statement = valued(
            found,
            catalogue,
            chosen,
            catalogue.figure(COST),
            None if closed else words,
            None if closed else VALUES,
        )
        with self.bounds.read(self.db) as db:
            found_rows = db.execute(statement.select).all()
        listed_values = [
            AttributeValue(
                key=row.k,
                label=value_label(chosen, row.k, row._mapping.get("name")),
                count=row.n,
                cost=None if row._mapping.get("v") is None else float(row.v),
            )
            for row in found_rows
        ]
        if closed and words is not None:
            listed_values = [
                one
                for one in listed_values
                if words
                in f"{one.label or ''} {'' if one.key is None else one.key}".casefold()
            ]
        total = (
            len(listed_values) if closed else (found_rows[0].total if found_rows else 0)
        )
        return Values(
            address=view.address,
            zone=catalogue.zone,
            dimension=chosen,
            values=tuple(listed_values[:VALUES]),
            total=total,
        )


def _scope(found: Plan) -> Plan:
    """The plan's scope alone: no marks, no threshold on the By's rows and
    no outlier rows' chip, its statements narrowed to no rows (D5)."""
    return replace(found, marks=(), thresholds=(), outliers=None, rows=None)


def _counted(row: Any, index: int) -> int:
    """A dimension's count from the attributes' row: grouped, its groups;
    the fact's own part, its rows with one and one for those with none."""
    mapping = row._mapping
    if f"a{index}" in mapping:
        return int(mapping[f"a{index}"])
    return int(mapping[f"n{index}"] or 0) + (1 if mapping[f"z{index}"] else 0)


def _on_rows(
    db: Session,
    view: View,
    now: datetime,
    held: Sequence[QuickFilter],
    chips: Sequence[Chip],
) -> tuple[dict[int, QuickFilterCount], set[Value] | None]:
    """The count and amount of each quick filter on the By's rows, by its
    index among `held`, and the By's values those that are on and keep hold,
    none where none such is on."""
    judged = [
        index for index, chip in enumerate(chips) if isinstance(chip, OnRows | Outliers)
    ]
    if not judged:
        return {}, None
    kept, sums = _judged(
        db,
        view,
        now,
        [held[index] for index in judged],
        [chips[index] for index in judged],
    )
    narrowed = _narrowed(
        [
            kept[place]
            for place, index in enumerate(judged)
            if held[index].key in view.address.state.quick_filters
            and not chips[index].marked
        ]
    )
    answered: dict[int, QuickFilterCount] = {}
    for place, index in enumerate(judged):
        rows = kept[place] if narrowed is None else kept[place] & narrowed
        answered[index] = QuickFilterCount(
            held[index].key,
            len(rows),
            None
            if held[index].amount is None
            else _amount(sum(sums[place].get(row, 0.0) for row in rows)),
        )
    return answered, narrowed


def _tallied(
    db: Session,
    found: Plan,
    catalogue: Catalogue,
    held: Sequence[QuickFilter],
    chips: Sequence[Chip],
    judged: dict[int, QuickFilterCount],
) -> dict[int, QuickFilterCount]:
    """The count and amount of each quick filter `judged` does not hold, by
    its index among `held`: one statement a fact, each of its tallies a
    column."""
    tallies: dict[str, list[tuple[int, str, Tally]]] = {}
    for index, chip in enumerate(chips):
        if index not in judged:
            for on, role, tally in _tallies(catalogue, held[index], chip):
                tallies.setdefault(on, []).append((index, role, tally))
    taken: dict[int, dict[str, Any]] = {}
    for fact in catalogue.facts:
        mine = tallies.get(fact.key)
        if not mine:
            continue
        found_row = db.execute(
            tallied(found, catalogue, fact.key, [tally for _, _, tally in mine]).select
        ).one()
        for place, (index, role, _) in enumerate(mine):
            taken.setdefault(index, {})[role] = found_row[place]
    return {
        index: QuickFilterCount(
            held[index].key,
            int(columns["count"]),
            None if held[index].amount is None else _amount(columns["amount"]),
        )
        for index, columns in taken.items()
    }


def _tallies(
    catalogue: Catalogue, quick_filter: QuickFilter, chip: Chip
) -> list[tuple[str, str, Tally]]:
    """A quick filter's count, and its amount where it names a figure, each
    a tally on the fact it reads: a chip on values counts the rows of the
    first fact that offers its dimension, a condition on each item the
    items of its grain, or the rows, of its figure's fact."""
    if isinstance(chip, Pin):
        kept: Condition | OnItems = Condition(chip.dimension, chip.values, chip.negated)
        counted = Tally(kept)
        fact = catalogue.offered(chip.dimension)[0]
    else:
        assert isinstance(chip, OnItems)
        kept = replace(chip, marked=False)
        counted = Tally(kept, grain=chip.measure.grain)
        fact = catalogue.figure(chip.measure.figure).fact
    tallies = [(fact, "count", counted)]
    if quick_filter.amount is not None:
        tallies.append(
            (
                catalogue.figure(quick_filter.amount).fact,
                "amount",
                Tally(kept, figure=quick_filter.amount),
            )
        )
    return tallies


def _judged(
    db: Session,
    view: View,
    now: datetime,
    held: Sequence[QuickFilter],
    chips: Sequence[Chip],
) -> tuple[list[set[Value]], list[dict[Value, float]]]:
    """For each quick filter on the By's rows, the By's values it keeps in
    the view's scope, and on each of them its figure's sum: one read of the
    rows of the view's first measure, each threshold's and each figure's."""
    state = view.address.state
    asked: list[Measure] = [state.measures[0]]
    judging: list[int] = []
    summing: list[int | None] = []
    for quick_filter, chip in zip(held, chips, strict=True):
        if isinstance(chip, OnRows):
            judging.append(len(asked))
            asked.append(chip.measure)
        else:
            judging.append(0)
        if quick_filter.amount is None:
            summing.append(None)
        else:
            summing.append(len(asked))
            asked.append(Simple(quick_filter.amount, "sum"))
    found = _scope(
        plan(replace(state, measures=tuple(asked)), view.catalogue, view.weeks, now)
    )
    shaper = Shaper(view.catalogue, found, view.address)
    shaper.take(ran(db, statements(found, view.catalogue)))

    def values(at: int) -> dict[Value, float]:
        return {
            key: value
            for key, taken in shaper.rows.items()
            if (value := shaper.value(taken, found.measures[at])[0]) is not None
        }

    kept: list[set[Value]] = []
    for chip, at in zip(chips, judging, strict=True):
        if isinstance(chip, OnRows):
            threshold = Threshold(found.measures[at], chip.operator, chip.number)
            kept.append(
                {
                    key
                    for key, taken in shaper.rows.items()
                    if threshold.passes(shaper.value(taken, threshold.measured)[0])
                }
            )
        else:
            kept.append(outliers(values(at)))
    return kept, [{} if at is None else values(at) for at in summing]


def _narrowed(kept: Sequence[set[Value]]) -> set[Value] | None:
    """The By's values every one of `kept` holds, none where there are no
    sets to hold them."""
    if not kept:
        return None
    return set.intersection(*kept)


def _amount(value: Decimal | float | None) -> float:
    """A sum over what a quick filter keeps, 0 where nothing it keeps has
    the figure."""
    return 0.0 if value is None else float(value)
