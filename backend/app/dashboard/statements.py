"""The statements of a view's rows (`architecture.md` Part 1, "What SQL does
and what the process does"), built from a plan.

- **One grouped scan per fact** a measure is answered from gives the sums,
  counts, maxima and means of its measures over its own rows, under three
  groupings: by the By, all of it (the All row), and by the By and the color,
  the split each measure that stacks takes; with the By's name, its place on
  its order and whether a row holds the focus.
- **One statement per fact and grain** gives the measures whose items are a
  part coarser than the fact's rows, in two levels: each item's figure taken
  together as the figure says, their sum or their largest, by the By and
  for the All row, an item whole across the By's rows; then the aggregate
  across the items. A median or a P90 of the fact's own rows is a statement
  of the rows alone. Each is a hashed grouping, never a distinct count by
  sort.

A measure stacks where its figure does, its aggregate adds up — a sum, or a
count of its fact's rows — and the color is a dimension its fact has, or
the token kinds and the figure has them. Each row a measure reads carries
its figure where the measure's own filters keep the row, else none, so that
every aggregate over it ignores the row.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Double,
    Select,
    and_,
    case,
    cast,
    false,
    func,
    not_,
    or_,
    select,
    true,
    tuple_,
)

from app.dashboard.catalogue import COUNT, Catalogue, Dimension, Figure, Row
from app.dashboard.planner import Condition, Plan, Planned, Window
from app.dashboard.state import TOKEN_KIND, Filter, Value

SCANNED = ("sum", COUNT, "max", "mean")
"""The aggregates the grouped scan takes over its fact's own rows."""

PERCENTILES = {"median": 0.5, "p90": 0.9}

_LENGTH = 24_000
"""The bound of a statement, which carries its fact's source as SQL text,
some 2,400 characters for the Call fact, and every measure's and filter's
expressions over it."""


@dataclass(frozen=True)
class Scan:
    """A fact's grouped scan. `measures` are the indexes, among the plan's
    simples, of those it answers; `splits` of those it splits by the color,
    and `kinds` of those it splits by the token kinds."""

    fact: str
    select: Select[Any]
    joins: tuple[str, ...]
    through: tuple[tuple[str, str], ...]
    measures: tuple[int, ...]
    splits: tuple[int, ...]
    kinds: tuple[int, ...]
    colored: bool


@dataclass(frozen=True)
class Items:
    """A fact's measures over the items of `grain`, a part, none being the
    fact's own rows; `measures` the indexes of those it answers."""

    fact: str
    grain: str | None
    select: Select[Any]
    joins: tuple[str, ...]
    through: tuple[tuple[str, str], ...]
    measures: tuple[int, ...]


Statement = Scan | Items


def stacks(planned: Planned, color: str | None, catalogue: Catalogue) -> bool:
    """Whether the measure splits by the color."""
    measure = planned.measure
    figure = catalogue.figure(measure.figure)
    if color is None or planned.refused is not None or not figure.stacks:
        return False
    adds = measure.aggregate == "sum" or (
        measure.aggregate == COUNT and planned.grain is None
    )
    if color == TOKEN_KIND:
        return figure.kinds is not None and measure.aggregate == "sum"
    return adds and planned.fact in catalogue.offered(color)


def statements(found: Plan, catalogue: Catalogue) -> tuple[Statement, ...]:
    """The statements of the plan's rows, the scans first, each fact in the
    catalogue's order."""
    simples = found.simples
    scans: list[Statement] = []
    items: list[Statement] = []
    for fact in catalogue.facts:
        mine = [
            index
            for index, planned in enumerate(simples)
            if planned.fact == fact.key and planned.refused is None
        ]
        if not mine:
            continue
        scanned = [
            index
            for index in mine
            if simples[index].grain is None
            and simples[index].measure.aggregate in SCANNED
        ]
        split = [
            index for index in mine if stacks(simples[index], found.color, catalogue)
        ]
        scans.append(_Builder(found, catalogue, fact.key).scan(scanned, split))
        grains = dict.fromkeys(
            simples[index].grain for index in mine if index not in scanned
        )
        for grain in grains:
            answered = [
                index
                for index in mine
                if index not in scanned and simples[index].grain == grain
            ]
            items.append(_Builder(found, catalogue, fact.key).items(grain, answered))
    return (*scans, *items)


def described(found: Plan, catalogue: Catalogue) -> list[dict[str, Any]]:
    """Each statement as the file of states holds it: its fact, the part its
    items are, its groupings by the dimensions' keys, the joins it reads and
    each dimension it reads through another fact's conversations."""
    entries = []
    for statement in statements(found, catalogue):
        entry: dict[str, Any] = {"fact": statement.fact}
        if isinstance(statement, Scan):
            groupings = [[found.by], []]
            if statement.colored:
                groupings.append([found.by, str(found.color)])
        else:
            if statement.grain is not None:
                entry["items"] = statement.grain
            groupings = [[found.by], []]
        entry["grouping"] = groupings
        entry["joins"] = list(statement.joins)
        if statement.through:
            entry["through"] = dict(statement.through)
        entries.append(entry)
    return entries


class _Builder:
    """One statement's expressions over one row of its fact. The row's
    source is taken once every expression over it is built: it joins only
    what was read before it."""

    def __init__(self, found: Plan, catalogue: Catalogue, fact: str) -> None:
        self.plan = found
        self.catalogue = catalogue
        self.row = catalogue.row(catalogue.fact(fact))
        self.through: dict[str, str] = {}

    # ------------------------------------------------------------ the rows read

    def scoped(self) -> list[ColumnElement[bool]]:
        """What keeps a row: the window and the scope."""
        return [
            _in_window(self.row, self.plan.window),
            *(self.kept(condition) for condition in self.plan.scope),
        ]

    def kept(self, condition: Condition | Filter) -> ColumnElement[bool]:
        """Whether the row passes `condition`: on its own dimension where
        the fact has it, else through the conversations of the first fact
        that has it, among that fact's rows in the window."""
        key = condition.dimension
        dimension = self.catalogue.dimension(key)
        offered = self.catalogue.offered(key)
        if self.row.fact.key in offered:
            matched = _matches(dimension.path(self.row), condition.values)
        elif offered:
            self.through[key] = offered[0]
            home = self.catalogue.row(self.catalogue.fact(offered[0]))
            where = [
                home["transcript_id"].is_not(None),
                _matches(dimension.path(home), condition.values),
                _in_window(home, self.plan.window),
            ]
            conversations = (
                select(home["transcript_id"])
                .select_from(home.source())
                .where(*where)
                .correlate(None)
            )
            matched = func.coalesce(
                self.row["transcript_id"].in_(conversations), false()
            )
        else:
            matched = false()
        return not_(matched) if condition.negated else matched

    def value(self, planned: Planned, *also: ColumnElement[bool]) -> ColumnElement[Any]:
        """The measure's figure on the row, none where its filters, or
        `also`, do not keep it."""
        figure = self.catalogue.figure(planned.measure.figure)
        return self.filtered(figure.path(self.row), planned, *also)

    def filtered(
        self, path: ColumnElement[Any], planned: Planned, *also: ColumnElement[bool]
    ) -> ColumnElement[Any]:
        conditions = [*(self.kept(one) for one in planned.measure.filters), *also]
        if not conditions:
            return path
        return case((and_(*conditions), path))

    def by(self) -> Dimension:
        return self.catalogue.dimension(self.plan.by)

    # ------------------------------------------------------------ the scan

    def scan(self, scanned: Sequence[int], split: Sequence[int]) -> Scan:
        simples = self.plan.simples
        by = self.by()
        color = self.plan.color
        colored = color is not None and color != TOKEN_KIND and bool(split)
        columns: list[ColumnElement[Any]] = [by.path(self.row).label("b")]
        if colored:
            assert color is not None
            dimension = self.catalogue.dimension(color)
            columns.append(dimension.path(self.row).label("c"))
            if dimension.name is not None:
                columns.append(dimension.name(self.row).label("c_name"))
        if by.name is not None:
            columns.append(by.name(self.row).label("b_name"))
        order = _order_of(self.catalogue, by.key)
        if order is not None and order.axis is not None:
            columns.append(order.axis(self.row).label("axis"))
        focus = self.plan.focus
        if focus is not None and self.row.fact.key in self.catalogue.offered(
            focus.dimension
        ):
            columns.append(
                (
                    self.catalogue.dimension(focus.dimension).path(self.row)
                    == focus.key
                ).label("focus")
            )
        for index in scanned:
            columns.append(self.value(simples[index]).label(f"v{index}"))
        kinds: list[int] = []
        for index in split:
            planned = simples[index]
            also = (
                [self.grain_of(planned).is_not(None)]
                if planned.grain is not None
                else []
            )
            if color == TOKEN_KIND:
                kinds.append(index)
                figure = self.catalogue.figure(planned.measure.figure)
                assert figure.kinds is not None
                for kind, path in figure.kinds.items():
                    columns.append(
                        self.filtered(path(self.row), planned, *also).label(
                            f"k{index}_{kind}"
                        )
                    )
            else:
                columns.append(self.value(planned, *also).label(f"s{index}"))
        where = self.scoped()
        inner = (
            select(*columns).select_from(self.row.source()).where(*where).subquery("r")
        )
        b = inner.c.b
        c = inner.c.c if colored else None
        outer: list[ColumnElement[Any]] = [
            (func.grouping(b, c) if c is not None else func.grouping(b)).label("g"),
            b,
        ]
        if c is not None:
            outer.append(c)
            if "c_name" in inner.c:
                outer.append(func.max(inner.c.c_name).label("c_name"))
        if "b_name" in inner.c:
            outer.append(func.max(inner.c.b_name).label("b_name"))
        if "axis" in inner.c:
            outer.append(func.min(inner.c.axis).label("axis"))
        if "focus" in inner.c:
            outer.append(func.bool_or(inner.c.focus).label("focus"))
        for index in scanned:
            value = inner.c[f"v{index}"]
            outer += [
                _scanned(simples[index].measure.aggregate, value).label(f"v{index}"),
                func.count(value).label(f"n{index}"),
            ]
        for index in split:
            aggregate = simples[index].measure.aggregate
            if index in kinds:
                figure = self.catalogue.figure(simples[index].measure.figure)
                assert figure.kinds is not None
                outer += [
                    func.sum(inner.c[f"k{index}_{kind}"]).label(f"k{index}_{kind}")
                    for kind in figure.kinds
                ]
            else:
                value = inner.c[f"s{index}"]
                outer.append(
                    (
                        func.count(value) if aggregate == COUNT else func.sum(value)
                    ).label(f"s{index}")
                )
        sets = [tuple_(b), tuple_()]
        if c is not None:
            sets.append(tuple_(b, c))
        statement = (
            select(*outer)
            .select_from(inner)
            .group_by(func.grouping_sets(*sets))
            .execution_options(max_statement_length=_LENGTH)
        )
        return Scan(
            fact=self.row.fact.key,
            select=statement,
            joins=self.row.taken,
            through=tuple(self.through.items()),
            measures=tuple(scanned),
            splits=tuple(split),
            kinds=tuple(kinds),
            colored=colored,
        )

    def grain_of(self, planned: Planned) -> ColumnElement[Any]:
        assert planned.grain is not None
        return self.catalogue.dimension(planned.grain).path(self.row)

    # ------------------------------------------------------------ the items

    def items(self, grain: str | None, answered: Sequence[int]) -> Items:
        simples = self.plan.simples
        b = self.by().path(self.row).label("b")
        values = [self.value(simples[index]).label(f"v{index}") for index in answered]
        where = self.scoped()
        if grain is None:
            rows = (
                select(b, *values)
                .select_from(self.row.source())
                .where(*where)
                .subquery("r")
            )
            per_item = rows
            group: ColumnElement[Any] = func.grouping(rows.c.b)
            grouping = func.grouping_sets(tuple_(rows.c.b), tuple_())
        else:
            item = self.catalogue.dimension(grain).path(self.row).label("item")
            rows = (
                select(b, item, *values)
                .select_from(self.row.source())
                .where(*where, item.is_not(None))
                .subquery("r")
            )
            per_item = (
                select(
                    func.grouping(rows.c.b).label("g"),
                    rows.c.b,
                    rows.c.item,
                    *(
                        _within(
                            self.catalogue.figure(simples[index].measure.figure),
                            rows.c[f"v{index}"],
                        ).label(f"v{index}")
                        for index in answered
                    ),
                )
                .group_by(
                    func.grouping_sets(
                        tuple_(rows.c.b, rows.c.item), tuple_(rows.c.item)
                    )
                )
                .subquery("i")
            )
            group = per_item.c.g
            grouping = None
        columns: list[ColumnElement[Any]] = [group.label("g"), per_item.c.b]
        for index in answered:
            value = per_item.c[f"v{index}"]
            columns += [
                _across(simples[index].measure.aggregate, value).label(f"v{index}"),
                func.count(value).label(f"n{index}"),
            ]
        statement = select(*columns).select_from(per_item)
        statement = (
            statement.group_by(grouping)
            if grouping is not None
            else statement.group_by(per_item.c.g, per_item.c.b)
        )
        return Items(
            fact=self.row.fact.key,
            grain=grain,
            select=statement.execution_options(max_statement_length=_LENGTH),
            joins=self.row.taken,
            through=tuple(self.through.items()),
            measures=tuple(answered),
        )


def _order_of(catalogue: Catalogue, part: str) -> Dimension | None:
    """The first order dimension along which `part` lies."""
    return next(
        (
            dimension
            for dimension in catalogue.dimensions
            if dimension.group == "order" and dimension.base == part
        ),
        None,
    )


def _within(figure: Figure, value: ColumnElement[Any]) -> ColumnElement[Any]:
    """An item's figure, its rows' taken together as the figure says."""
    return func.max(value) if figure.within == "max" else func.sum(value)


def _in_window(row: Row, window: Window) -> ColumnElement[bool]:
    if window is None:
        return true()
    at = row["at"]
    spans = []
    for start, end in window:
        bounds = [
            *([at >= start] if start is not None else []),
            *([at < end] if end is not None else []),
        ]
        spans.append(and_(*bounds) if bounds else true())
    return or_(*spans) if spans else false()


def _matches(path: ColumnElement[Any], values: Sequence[Value]) -> ColumnElement[bool]:
    """Whether the path's value is among `values`, none among them matching
    a row with none."""
    known = [value for value in values if value is not None]
    matched = [
        *([path.in_(known)] if known else []),
        *([path.is_(None)] if len(known) < len(values) else []),
    ]
    return func.coalesce(or_(*matched), false())


def _scanned(aggregate: str, value: ColumnElement[Any]) -> ColumnElement[Any]:
    if aggregate == "sum":
        return func.sum(value)
    if aggregate == COUNT:
        return func.count(value)
    if aggregate == "max":
        return func.max(value)
    return func.avg(value)


def _across(aggregate: str, value: ColumnElement[Any]) -> ColumnElement[Any]:
    if aggregate in PERCENTILES:
        return func.percentile_cont(PERCENTILES[aggregate]).within_group(
            cast(value, Double)
        )
    return _scanned(aggregate, value)
