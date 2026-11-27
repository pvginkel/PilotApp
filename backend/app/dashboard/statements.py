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
- **One marks statement per fact** the view's measures read, where a chip
  marks: by the By, the rows the marks keep, their count and each marking
  measure's part.

A series reads more, each a statement of one fact (`Read`):

- **a bucket's items**, for a measure drawn as its items' dots: by the By
  and the item, each item's figure there, its first moment, its name and
  the role its rows share, where they share one, in the order of the By's
  values on their axis, then of the items' first moments;
- **the points' roles**: by the By, the role its rows share, where they
  share one;
- **the members before the range**, in order: the last of the By's values
  whose place on the axis is before the window, under the scope over all
  time; and **the items before the range** of a measure drawn as its items'
  dots, the last to start before the window, each item's figure over all
  its rows;
- **the first sightings** of a marker's dimension: each value's first
  moment, under the scope over all time;
- **a role's configuration's changes**, on the Calls under the scope over
  all time: each Work Unit with a role, at its start, else its first
  Call's, its model and effort those of its first Call on a main thread,
  where they differ from those of the unit of the same role before it, by a
  window's lag;
- **the events by bucket**: by the By and the event's kind, their count and
  whether the kind counts as an error.

The lanes read, each a statement of one fact: **the spans**, by the By its
rows' first and last moment; **the waits**, each row that comes a gap or
more after the one before it of its value of the By, with that one's moment,
a window's lag; **the runs**, by the By the stretches of consecutive rows of
one value of a dimension and one thread with no such gap in them, each with
its first and last moment, its rows, their cost and whether a gap opens it,
a window's lag and a running count of where one opens; and **the events**, by
the By in time order, each with its detail. The items read, by index of the
thing they are about: **a part's items**, by each item its first and last
moment and each figure taken together, the earliest first, with the count
of all; **a fact's own rows as items**, each with the dimensions shown on
it; and **a thread's calls and its events** over all time, each call saying
whether the plan's window and scope hold it.

The counts read, each one statement of one fact: **the attributes'
counts**, each dimension's count of values, none counting as one, by a
grouping of the rows on each, a grouping set apiece, the fact's own row
counted by its rows; **the quick filters' tally**, a column for each count
and amount a quick filter takes there, the rows it keeps or the items of its
grain among them, by a grouping set of the items apiece, and its figure
summed over those rows; and **a dimension's values**, each with the count of
its rows and its figure's sum, searched by their name or their key. None is
a distinct count, which PostgreSQL takes by a sort.

A condition on each item reads its figure over each item's rows of all
time, its own filters keeping them: on a fact's own rows the row's figure,
on a part the items whose figure, taken together as it says, passes. The
By's values a plan is narrowed to are one array, bound once whatever their
number.

A measure adds up where its figure stacks and its aggregate is a sum, or a
count of its fact's rows. It stacks where it adds up and the color is a
dimension its fact has, or the token kinds and the figure has them; it marks
where it adds up. Each row a measure reads carries its figure where the
measure's own filters keep the row, else none, so that every aggregate over
it ignores the row.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Double,
    Select,
    Text,
    and_,
    any_,
    case,
    cast,
    false,
    func,
    literal,
    not_,
    or_,
    select,
    true,
    tuple_,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.sql.functions import FunctionElement

from app.dashboard.assembly import EVENT_KIND
from app.dashboard.catalogue import COUNT, Catalogue, Dimension, Figure, Row
from app.dashboard.dimensions import ROLE
from app.dashboard.facts import CALL, DETAIL
from app.dashboard.planner import (
    Kept,
    Plan,
    Planned,
    Window,
    sides,
    written,
)
from app.dashboard.state import TOKEN_KIND, Filter, OnItems, Value

SCANNED = ("sum", COUNT, "max", "mean")
"""The aggregates the grouped scan takes over its fact's own rows."""

PERCENTILES = {"median": 0.5, "p90": 0.9}

LENGTH = 24_000
"""The bound of a statement, which carries its fact's source as SQL text,
some 2,700 characters for the Call fact, and every measure's and filter's
expressions over it."""


ATTRIBUTES_LENGTH = 2 * LENGTH
"""The bound of the attributes' counts, which carry a path for every
dimension a fact is the first to offer: some 15,000 characters for the Call
fact's under no chip, with six Work Unit Kinds declared."""


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


@dataclass(frozen=True)
class Marked:
    """A fact's rows the plan's marks keep, by the By: their count, and the
    part of each measure that marks, `measures` the indexes of those."""

    fact: str
    select: Select[Any]
    joins: tuple[str, ...]
    through: tuple[tuple[str, str], ...]
    measures: tuple[int, ...]


Statement = Scan | Items | Marked


@dataclass(frozen=True)
class Tally:
    """A column of a fact's tally of the quick filters: the rows `kept`
    keeps counted, or their items of `grain`, or `figure` summed over them."""

    kept: Kept
    grain: str | None = None
    figure: str | None = None


@dataclass(frozen=True)
class Read:
    """One of a series' statements: its fact, the joins it reads and each
    dimension it reads through another fact's conversations."""

    fact: str
    select: Select[Any]
    joins: tuple[str, ...]
    through: tuple[tuple[str, str], ...]


def adds(planned: Planned, catalogue: Catalogue) -> bool:
    """Whether the measure adds up over the rows: a sum, or a count of its
    fact's rows, of a figure that stacks, answered."""
    measure = planned.answered
    if not planned.answers or not catalogue.figure(measure.figure).stacks:
        return False
    return measure.aggregate == "sum" or (
        measure.aggregate == COUNT and planned.grain is None
    )


def stacks(planned: Planned, color: str | None, catalogue: Catalogue) -> bool:
    """Whether the measure splits by the color."""
    if color is None or not adds(planned, catalogue):
        return False
    if color == TOKEN_KIND:
        figure = catalogue.figure(planned.answered.figure)
        return figure.kinds is not None and planned.answered.aggregate == "sum"
    return planned.fact in catalogue.offered(color)


def statements(found: Plan, catalogue: Catalogue) -> tuple[Statement, ...]:
    """The statements of the plan's rows, the scans first, then the items',
    then the marks', each fact in the catalogue's order."""
    simples = found.simples
    viewed = {side.measure for measured in found.measures for side in sides(measured)}
    scans: list[Statement] = []
    items: list[Statement] = []
    marked: list[Statement] = []
    for fact in catalogue.facts:
        mine = [
            index
            for index, planned in enumerate(simples)
            if planned.fact == fact.key and planned.answers
        ]
        if not mine:
            continue
        shown = [index for index in mine if simples[index].measure in viewed]
        if found.marks and shown:
            marked.append(
                _Builder(found, catalogue, fact.key).marked(
                    [index for index in shown if adds(simples[index], catalogue)]
                )
            )
        scanned = [
            index
            for index in mine
            if simples[index].grain is None
            and simples[index].answered.aggregate in SCANNED
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
    return (*scans, *items, *marked)


def described(found: Plan, catalogue: Catalogue) -> list[dict[str, Any]]:
    """Each statement as the file of states holds it: its fact, the part its
    items are, its groupings by the dimensions' keys, the joins it reads and
    each dimension it reads through another fact's conversations."""
    entries = []
    for statement in statements(found, catalogue):
        entry: dict[str, Any] = {"fact": statement.fact}
        if isinstance(statement, Marked):
            entry["marks"] = True
            groupings = [[found.by]]
        elif isinstance(statement, Scan):
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


def read_described(read: Read) -> dict[str, Any]:
    """One of a presentation's reads as the file of states holds it: its
    fact, the joins it reads and each dimension it reads through another
    fact's conversations."""
    entry: dict[str, Any] = {"fact": read.fact, "joins": list(read.joins)}
    if read.through:
        entry["through"] = dict(read.through)
    return entry


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
        """What keeps a row: the window, the scope, and the By's values the
        plan is narrowed to."""
        scoped = [
            _in_window(self.row, self.plan.window),
            *(self.kept(condition) for condition in self.plan.scope),
        ]
        rows = self.plan.rows
        if rows is not None:
            scoped.append(self.holds(self.plan.by, lambda path: _among(path, rows)))
        return scoped

    def kept(self, condition: Kept | Filter) -> ColumnElement[bool]:
        """Whether the row passes `condition`."""
        if isinstance(condition, OnItems):
            return self.each(condition)
        values = condition.values
        matched = self.holds(condition.dimension, lambda path: _matches(path, values))
        return not_(matched) if condition.negated else matched

    def holds(
        self, key: str, matching: Callable[[ColumnElement[Any]], ColumnElement[bool]]
    ) -> ColumnElement[bool]:
        """Whether the row's value of the dimension `key` passes `matching`:
        its own where the fact has it, else through the conversations of the
        first fact that has it, among that fact's rows in the window; none
        on a fact whose rows lie in no conversation."""
        dimension = self.catalogue.dimension(key)
        offered = self.catalogue.offered(key)
        if self.row.fact.key in offered:
            return matching(dimension.path(self.row))
        if not offered or not _threaded(self.row):
            return false()
        self.through[key] = offered[0]
        home = self.catalogue.row(self.catalogue.fact(offered[0]))
        where = [
            home["transcript_id"].is_not(None),
            matching(dimension.path(home)),
            _in_window(home, self.plan.window),
        ]
        conversations = (
            select(home["transcript_id"])
            .select_from(home.source())
            .where(*where)
            .correlate(None)
        )
        return func.coalesce(self.row["transcript_id"].in_(conversations), false())

    def each(self, chip: OnItems) -> ColumnElement[bool]:
        """Whether the row passes a condition on each item: its own figure,
        on its fact's own rows; else whether its item is among those that
        pass, on the item's part where the fact has it; else through the
        conversations of the rows that pass, among the figure's fact's rows
        in the window."""
        measure = chip.measure
        figure = self.catalogue.figure(measure.figure)
        home = _Builder(self.plan, self.catalogue, figure.fact)
        if measure.grain is None:
            if self.row.fact.key == figure.fact:
                matched = _past(
                    self.filtered(figure.path(self.row), measure.filters), chip
                )
            else:
                passing = _past(
                    home.filtered(figure.path(home.row), measure.filters), chip
                )
                matched = self.conversations(home, passing, written(chip))
            return not_(matched) if chip.negated else matched
        part = self.catalogue.dimension(measure.grain)
        item = part.path(home.row)
        value = _within(figure, home.filtered(figure.path(home.row), measure.filters))
        items = (
            select(item)
            .select_from(home.row.source())
            .where(item.is_not(None))
            .group_by(item)
            .having(_past(value, chip))
            .correlate(None)
        )
        if self.row.fact.key in self.catalogue.offered(part.key):
            matched = func.coalesce(part.path(self.row).in_(items), false())
        else:
            other = _Builder(self.plan, self.catalogue, figure.fact)
            matched = self.conversations(
                other, part.path(other.row).in_(items), written(chip)
            )
        return not_(matched) if chip.negated else matched

    def conversations(
        self, home: _Builder, passing: ColumnElement[bool], key: str
    ) -> ColumnElement[bool]:
        """Whether the row's conversation holds a row of `home`'s fact in
        the window that `passing` keeps; none where either fact's rows lie
        in no conversation."""
        if not (_threaded(self.row) and _threaded(home.row)):
            return false()
        self.through[key] = home.row.fact.key
        where = [
            home.row["transcript_id"].is_not(None),
            passing,
            _in_window(home.row, self.plan.window),
        ]
        conversations = (
            select(home.row["transcript_id"])
            .select_from(home.row.source())
            .where(*where)
            .correlate(None)
        )
        return func.coalesce(self.row["transcript_id"].in_(conversations), false())

    def value(self, planned: Planned, *also: ColumnElement[bool]) -> ColumnElement[Any]:
        """The measure's figure on the row, none where its filters, or
        `also`, do not keep it."""
        measure = planned.answered
        figure = self.catalogue.figure(measure.figure)
        return self.filtered(figure.path(self.row), measure.filters, *also)

    def filtered(
        self,
        path: ColumnElement[Any],
        filters: Sequence[Filter],
        *also: ColumnElement[bool],
    ) -> ColumnElement[Any]:
        conditions = [*(self.kept(one) for one in filters), *also]
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
        if by.at is not None:
            columns.append(by.at(self.row).label("b_at"))
        order = ordered(self.catalogue, by)
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
                figure = self.catalogue.figure(planned.answered.figure)
                assert figure.kinds is not None
                for kind, path in figure.kinds.items():
                    columns.append(
                        self.filtered(
                            path(self.row), planned.answered.filters, *also
                        ).label(f"k{index}_{kind}")
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
        if "b_at" in inner.c:
            outer.append(func.min(inner.c.b_at).label("b_at"))
        if "axis" in inner.c:
            outer.append(func.min(inner.c.axis).label("axis"))
        if "focus" in inner.c:
            outer.append(func.bool_or(inner.c.focus).label("focus"))
        for index in scanned:
            value = inner.c[f"v{index}"]
            outer += [
                _scanned(simples[index].answered.aggregate, value).label(f"v{index}"),
                func.count(value).label(f"n{index}"),
            ]
        for index in split:
            aggregate = simples[index].answered.aggregate
            if index in kinds:
                figure = self.catalogue.figure(simples[index].answered.figure)
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
            .execution_options(max_statement_length=LENGTH)
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
                            self.catalogue.figure(simples[index].answered.figure),
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
                _across(simples[index].answered.aggregate, value).label(f"v{index}"),
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
            select=statement.execution_options(max_statement_length=LENGTH),
            joins=self.row.taken,
            through=tuple(self.through.items()),
            measures=tuple(answered),
        )

    # ------------------------------------------------------------ the marks

    def marked(self, marking: Sequence[int]) -> Marked:
        """By the By, the rows the scope and the marks keep, and the part of
        each measure of `marking` on them."""
        simples = self.plan.simples
        columns: list[ColumnElement[Any]] = [self.by().path(self.row).label("b")]
        for index in marking:
            planned = simples[index]
            also = (
                [self.grain_of(planned).is_not(None)]
                if planned.grain is not None
                else []
            )
            columns.append(self.value(planned, *also).label(f"v{index}"))
        where = [*self.scoped(), *(self.kept(mark) for mark in self.plan.marks)]
        inner = (
            select(*columns).select_from(self.row.source()).where(*where).subquery("r")
        )
        outer: list[ColumnElement[Any]] = [inner.c.b, func.count().label("n")]
        for index in marking:
            value = inner.c[f"v{index}"]
            outer.append(
                (
                    func.count(value)
                    if simples[index].answered.aggregate == COUNT
                    else func.sum(value)
                ).label(f"v{index}")
            )
        return Marked(
            fact=self.row.fact.key,
            select=select(*outer)
            .select_from(inner)
            .group_by(inner.c.b)
            .execution_options(max_statement_length=LENGTH),
            joins=self.row.taken,
            through=tuple(self.through.items()),
            measures=tuple(marking),
        )

    # ------------------------------------------------------------ a series'

    def read(self, statement: Select[Any], length: int = LENGTH) -> Read:
        return Read(
            fact=self.row.fact.key,
            select=statement.execution_options(max_statement_length=length),
            joins=self.row.taken,
            through=tuple(self.through.items()),
        )

    def place(self) -> ColumnElement[Any]:
        """The row's By's place on its axis: its order's, else its own."""
        by = self.by()
        order = ordered(self.catalogue, by)
        if order is not None and order.axis is not None:
            return order.axis(self.row)
        return by.path(self.row)

    def bucketed(self, planned: Planned, most: int) -> Read:
        assert planned.grain is not None
        part = self.catalogue.dimension(planned.grain)
        b = self.by().path(self.row)
        item = part.path(self.row)
        columns: list[ColumnElement[Any]] = [
            b.label("b"),
            item.label("item"),
            self.value(planned).label("v"),
            self.row["at"].label("at"),
            self.place().label("place"),
        ]
        if part.name is not None:
            columns.append(part.name(self.row).label("name"))
        if self.row.fact.key in self.catalogue.offered(ROLE):
            columns.append(self.catalogue.dimension(ROLE).path(self.row).label("role"))
        rows = (
            select(*columns)
            .select_from(self.row.source())
            .where(*self.scoped(), b.is_not(None), item.is_not(None))
            .subquery("r")
        )
        value = _within(self.catalogue.figure(planned.answered.figure), rows.c.v)
        grouped: list[ColumnElement[Any]] = [
            rows.c.b,
            rows.c.item,
            value.label("v"),
            func.min(rows.c.at).label("at"),
            func.min(func.min(rows.c.place)).over(partition_by=rows.c.b).label("place"),
        ]
        if "name" in rows.c:
            grouped.append(func.max(rows.c.name).label("name"))
        if "role" in rows.c:
            grouped.append(_shared(rows.c.role).label("role"))
        items = (
            select(*grouped)
            .group_by(rows.c.b, rows.c.item)
            .having(value.is_not(None))
            .subquery("i")
        )
        return self.read(
            select(*items.c)
            .order_by(items.c.place, items.c.b, items.c.at, items.c.item)
            .limit(most)
        )

    def members_before(
        self, start: datetime, excluded: Sequence[Value], most: int
    ) -> Read:
        b = self.by().path(self.row)
        where = [*self.scoped(), b.is_not(None)]
        if excluded:
            where.append(not_(_among(b, excluded)))
        rows = (
            select(b.label("b"), self.place().label("place"))
            .select_from(self.row.source())
            .where(*where)
            .subquery("r")
        )
        place = func.min(rows.c.place)
        return self.read(
            select(rows.c.b)
            .group_by(rows.c.b)
            .having(place < start)
            .order_by(place.desc(), rows.c.b)
            .limit(most)
        )

    def items_before(
        self, planned: Planned, start: datetime, excluded: Sequence[Value], most: int
    ) -> Read:
        assert planned.grain is not None
        item = self.catalogue.dimension(planned.grain).path(self.row)
        where = [*self.scoped(), item.is_not(None)]
        if excluded:
            where.append(not_(_among(item, excluded)))
        rows = (
            select(
                item.label("item"),
                self.value(planned).label("v"),
                self.row["at"].label("at"),
            )
            .select_from(self.row.source())
            .where(*where)
            .subquery("r")
        )
        value = _within(self.catalogue.figure(planned.answered.figure), rows.c.v)
        first = func.min(rows.c.at)
        return self.read(
            select(rows.c.item, value.label("v"))
            .group_by(rows.c.item)
            .having(and_(first < start, value.is_not(None)))
            .order_by(first.desc(), rows.c.item)
            .limit(most)
        )

    def roles(self) -> Read:
        b = self.by().path(self.row)
        role = self.catalogue.dimension(ROLE).path(self.row)
        where = [*self.scoped(), b.is_not(None)]
        rows = (
            select(b.label("b"), role.label("role"))
            .select_from(self.row.source())
            .where(*where)
            .subquery("r")
        )
        return self.read(
            select(rows.c.b, _shared(rows.c.role).label("role")).group_by(rows.c.b)
        )

    def shifts(self) -> Read:
        role = self.catalogue.dimension(ROLE).path(self.row)
        model = self.row["model_code"]
        where = [
            *self.scoped(),
            role.is_not(None),
            model.is_not(None),
            self.row.to("thread").c.agent_id.is_(None),
        ]
        calls = (
            select(
                self.row["work_unit_id"].label("unit"),
                self.row.to("unit").c.started_at.label("started"),
                role.label("role"),
                model.label("model"),
                self.row["effort"].label("effort"),
                self.row["at"].label("at"),
            )
            .select_from(self.row.source())
            .where(*where)
            .subquery("r")
        )
        grouped = (calls.c.unit, calls.c.role, calls.c.model, calls.c.effort)
        runs = (
            select(
                *grouped,
                func.coalesce(func.max(calls.c.started), func.min(calls.c.at)).label(
                    "at"
                ),
                func.min(calls.c.at).label("first"),
            )
            .group_by(*grouped)
            .subquery("g")
        )
        ranked = select(
            *runs.c,
            func.row_number()
            .over(
                partition_by=runs.c.unit,
                order_by=(runs.c.first, runs.c.model, runs.c.effort),
            )
            .label("n"),
        ).subquery("f")
        order = (ranked.c.at, ranked.c.unit)
        followed = (
            select(
                ranked.c.role,
                ranked.c.model,
                ranked.c.effort,
                ranked.c.at,
                func.lag(ranked.c.model)
                .over(partition_by=ranked.c.role, order_by=order)
                .label("model_before"),
                func.lag(ranked.c.effort)
                .over(partition_by=ranked.c.role, order_by=order)
                .label("effort_before"),
            )
            .where(ranked.c.n == 1)
            .subquery("c")
        )
        return self.read(
            select(*followed.c)
            .where(
                followed.c.model_before.is_not(None),
                or_(
                    followed.c.model.is_distinct_from(followed.c.model_before),
                    followed.c.effort.is_distinct_from(followed.c.effort_before),
                ),
            )
            .order_by(followed.c.at, followed.c.role)
        )

    def sightings(self, dimension: Dimension) -> Read:
        value = dimension.path(self.row)
        rows = (
            select(value.label("v"), self.row["at"].label("at"))
            .select_from(self.row.source())
            .where(*self.scoped(), value.is_not(None))
            .subquery("r")
        )
        return self.read(
            select(rows.c.v, func.min(rows.c.at).label("at")).group_by(rows.c.v)
        )

    def counted(self, kind: Dimension, error: Dimension) -> Read:
        rows = (
            select(
                self.by().path(self.row).label("b"),
                kind.path(self.row).label("kind"),
                error.path(self.row).label("error"),
            )
            .select_from(self.row.source())
            .where(*self.scoped())
            .subquery("r")
        )
        return self.read(
            select(
                rows.c.b,
                rows.c.kind,
                func.max(rows.c.error).label("error"),
                func.count().label("n"),
            ).group_by(rows.c.b, rows.c.kind)
        )

    # ------------------------------------------------------------ the lanes'

    def spans(self) -> Read:
        b = self.by().path(self.row)
        at = self.row["at"]
        where = self.scoped()
        rows = (
            select(b.label("b"), at.label("at"))
            .select_from(self.row.source())
            .where(*where)
            .subquery("r")
        )
        return self.read(
            select(
                rows.c.b,
                func.min(rows.c.at).label("first"),
                func.max(rows.c.at).label("last"),
            ).group_by(rows.c.b)
        )

    def waits(self, least: float) -> Read:
        b = self.by().path(self.row)
        at, call = self.row["at"], self.row["call_id"]
        where = self.scoped()
        rows = (
            select(
                b.label("b"),
                self.row["transcript_id"].label("transcript_id"),
                call.label("call_id"),
                at.label("at"),
                self.row["past_ttl"].label("past_ttl"),
                self.row["waited_seconds"].label("waited_seconds"),
                func.lag(at).over(partition_by=b, order_by=(at, call)).label("since"),
            )
            .select_from(self.row.source())
            .where(*where)
            .subquery("r")
        )
        gap = func.extract("epoch", rows.c.at - rows.c.since)
        return self.read(
            select(*rows.c)
            .where(gap >= least)
            .order_by(rows.c.b, rows.c.at, rows.c.call_id)
        )

    def runs(self, dimension: Dimension, least: float) -> Read:
        columns = [
            self.by().path(self.row).label("b"),
            dimension.path(self.row).label("v"),
            self.row["transcript_id"].label("transcript_id"),
            self.row["at"].label("at"),
            self.row["call_id"].label("call_id"),
            self.row["cost"].label("cost"),
        ]
        if dimension.name is not None:
            columns.append(dimension.name(self.row).label("name"))
        rows = (
            select(*columns).select_from(self.row.source()).where(*self.scoped())
        ).subquery("r")
        r = rows.c

        def over(value: FunctionElement[Any]) -> ColumnElement[Any]:
            return value.over(partition_by=r.b, order_by=(r.at, r.call_id))

        lagged = select(
            *r,
            over(func.lag(r.at)).label("since"),
            over(func.lag(r.v)).label("was"),
            over(func.lag(r.transcript_id)).label("thread_was"),
            # The running count orders by this, so that it takes the rows in
            # the order the lags did, ties between them included.
            over(func.row_number()).label("i"),
        ).subquery("l")
        lag = lagged.c
        waited = func.coalesce(
            func.extract("epoch", lag.at - lag.since) >= least, false()
        )
        opens = or_(
            lag.since.is_(None),
            waited,
            lag.v.is_distinct_from(lag.was),
            lag.transcript_id.is_distinct_from(lag.thread_was),
        )
        numbered = select(
            *(lag[name] for name in ("b", "v", "transcript_id", "at", "cost")),
            *([lag.name] if "name" in lag else []),
            waited.label("waited"),
            func.sum(case((opens, 1), else_=0))
            .over(partition_by=lag.b, order_by=lag.i, rows=(None, 0))
            .label("run"),
        ).subquery("n")
        n = numbered.c
        return self.read(
            select(
                n.b,
                n.run,
                n.v,
                n.transcript_id,
                func.min(n.at).label("first"),
                func.max(n.at).label("last"),
                func.count().label("n"),
                func.sum(n.cost).label("cost"),
                func.bool_or(n.waited).label("waited"),
                *([func.max(n.name).label("name")] if "name" in n else []),
            )
            .group_by(n.b, n.run, n.v, n.transcript_id)
            .order_by(n.b, n.run)
        )

    def happened(self) -> Read:
        """The events of the lanes, each with its detail and the cost of
        the Call it is held on."""
        b = self.by().path(self.row)
        columns = [
            b.label("b"),
            *(
                self.row[name].label(name)
                for name in (
                    "at",
                    "kind_code",
                    "is_error",
                    "source_id",
                    "call_id",
                    "transcript_id",
                    "cost",
                    *(column for column, _ in DETAIL),
                )
            ),
        ]
        where = self.scoped()
        rows = (
            select(*columns).select_from(self.row.source()).where(*where).subquery("r")
        )
        return self.read(
            select(*rows.c).order_by(
                rows.c.b, rows.c.at, rows.c.kind_code, rows.c.source_id
            )
        )

    # ------------------------------------------------------------ the items'

    def grouped(
        self,
        part: Dimension,
        figures: Sequence[Figure],
        also: Sequence[ColumnElement[bool]],
        most: int | None,
        keys: Sequence[Value] | None = None,
    ) -> Read:
        """By each item of `part` the scope and `also` keep, its first and
        last moment and each figure taken together as it says, the earliest
        first, at most `most`, each with the count of all."""
        item = part.path(self.row)
        columns: list[ColumnElement[Any]] = [
            item.label("item"),
            self.row["at"].label("at"),
            *(
                figure.path(self.row).label(f"v{index}")
                for index, figure in enumerate(figures)
            ),
            *self.kinds(figures),
        ]
        if part.name is not None:
            columns.append(part.name(self.row).label("name"))
        where = [*self.scoped(), *also]
        if keys is not None:
            where.append(_among(item, keys))
        rows = (
            select(*columns).select_from(self.row.source()).where(*where).subquery("r")
        )
        first = func.min(rows.c.at)
        grouped: list[ColumnElement[Any]] = [
            rows.c.item,
            first.label("first"),
            func.max(rows.c.at).label("last"),
            *(
                _within(figure, rows.c[f"v{index}"]).label(f"v{index}")
                for index, figure in enumerate(figures)
            ),
            *(
                func.sum(rows.c[name]).label(name)
                for name in rows.c.keys()
                if name.startswith("k")
            ),
            func.count().over().label("total"),
        ]
        if "name" in rows.c:
            grouped.append(func.max(rows.c.name).label("name"))
        statement = select(*grouped).group_by(rows.c.item).order_by(first, rows.c.item)
        return self.read(statement if most is None else statement.limit(most))

    def own_key(self) -> list[ColumnElement[Any]]:
        """The columns a row's key as an item is formed from: its part's,
        where its fact's row is one; else, on the one fact whose row is no
        part, the events, its kind and the id of the row that records it."""
        part = self.row.fact.part
        if part is not None:
            return [self.catalogue.dimension(part).path(self.row)]
        return [self.row["kind_code"], self.row["source_id"]]

    def own(
        self,
        figures: Sequence[Figure],
        shown: Sequence[Dimension],
        also: Sequence[ColumnElement[bool]],
        most: int,
        scoped: bool = True,
        order: Sequence[ColumnElement[Any]] = (),
    ) -> Read:
        """The fact's rows as items, each its own: the columns its key is
        formed from, its moment, its thread, Session, Turn and Call, its
        place in its file where it has one, each figure and dimension shown
        on it, and an event's kind and detail; those the scope and `also`
        keep, or with `scoped` false those `also` keeps, each then saying
        whether the window and the scope hold it; in `order`, else the
        earliest first; at most `most`, each with the count of all."""
        key = self.own_key()
        at = self.row["at"]
        columns: list[ColumnElement[Any]] = [
            *(column.label(f"key{index}") for index, column in enumerate(key)),
            at.label("at"),
            *(
                self.row[name].label(name)
                for name in ("transcript_id", "session_id", "turn_seq", "call_id")
            ),
            *(
                figure.path(self.row).label(f"v{index}")
                for index, figure in enumerate(figures)
            ),
            *self.kinds(figures),
        ]
        if "position" in self.row.fact.source.c:
            columns.append(self.row["position"].label("position"))
        for index, dimension in enumerate(shown):
            columns.append(dimension.path(self.row).label(f"s{index}"))
            if dimension.name is not None:
                columns.append(dimension.name(self.row).label(f"s{index}_name"))
        if self.row.fact.key in self.catalogue.offered(EVENT_KIND):
            columns += [
                self.row[name].label(name)
                for name in ("kind_code", "is_error", *(column for column, _ in DETAIL))
            ]
        where = list(also)
        if scoped:
            where = [*self.scoped(), *where]
        else:
            columns.append(
                func.coalesce(and_(*self.scoped()), false()).label("in_scope")
            )
        return self.read(
            select(*columns, func.count().over().label("total"))
            .select_from(self.row.source())
            .where(*where)
            .order_by(*(order or (at, *key)))
            .limit(most)
        )

    def thread_events(self, conversation: uuid.UUID) -> Read:
        """The events of one thread over all time, each with its detail, in
        time order."""
        thread = self.row["transcript_id"] == conversation
        columns = [
            self.row[name].label(name)
            for name in (
                "at",
                "kind_code",
                "is_error",
                "source_id",
                "call_id",
                *(column for column, _ in DETAIL),
            )
        ]
        return self.read(
            select(*columns)
            .select_from(self.row.source())
            .where(thread)
            .order_by(self.row["at"], self.row["kind_code"], self.row["source_id"])
        )

    # ------------------------------------------------------------ the counts

    def attributes(self, keys: Sequence[str]) -> Read:
        """One row: for each of `keys`, `a<index>` its count of values among
        the rows; the fact's own part `n<index>`, its rows with one, and
        `z<index>`, whether any has none."""
        own = self.row.fact.part
        columns = [
            self.catalogue.dimension(key).path(self.row).label(f"a{index}")
            for index, key in enumerate(keys)
        ]
        where = self.scoped()
        rows = (
            select(*columns).select_from(self.row.source()).where(*where).subquery("r")
        )
        grouped = [index for index, key in enumerate(keys) if key != own]
        owned = [index for index, key in enumerate(keys) if key == own]
        inner: list[ColumnElement[Any]] = [
            func.grouping(rows.c[f"a{index}"]).label(f"g{index}") for index in grouped
        ]
        for index in owned:
            value = rows.c[f"a{index}"]
            inner += [
                func.count(value).label(f"n{index}"),
                func.bool_or(value.is_(None)).label(f"z{index}"),
            ]
        sets = [tuple_(rows.c[f"a{index}"]) for index in grouped]
        if owned:
            sets.append(tuple_())
        groups = (
            select(*inner)
            .select_from(rows)
            .group_by(func.grouping_sets(*sets))
            .subquery("g")
        )
        whole = and_(true(), *(groups.c[f"g{index}"] == 1 for index in grouped))
        outer: list[ColumnElement[Any]] = [
            func.count().filter(groups.c[f"g{index}"] == 0).label(f"a{index}")
            for index in grouped
        ]
        for index in owned:
            outer += [
                func.max(groups.c[f"n{index}"]).filter(whole).label(f"n{index}"),
                func.bool_or(groups.c[f"z{index}"]).filter(whole).label(f"z{index}"),
            ]
        return self.read(select(*outer).select_from(groups), ATTRIBUTES_LENGTH)

    def tallied(self, tallies: Sequence[Tally]) -> Read:
        """One row: for each tally, `t<index>` its count or its sum."""
        columns: list[ColumnElement[Any]] = []
        for index, tally in enumerate(tallies):
            kept = self.kept(tally.kept)
            if tally.figure is not None:
                path = self.catalogue.figure(tally.figure).path(self.row)
                columns.append(case((kept, path)).label(f"t{index}"))
            elif tally.grain is not None:
                item = self.catalogue.dimension(tally.grain).path(self.row)
                columns += [
                    kept.label(f"k{index}"),
                    case((kept, item)).label(f"t{index}"),
                ]
            else:
                columns.append(kept.label(f"t{index}"))
        where = self.scoped()
        rows = (
            select(*columns).select_from(self.row.source()).where(*where).subquery("r")
        )
        items = [
            index
            for index, tally in enumerate(tallies)
            if tally.figure is None and tally.grain is not None
        ]
        inner: list[ColumnElement[Any]] = []
        for index in items:
            inner += [
                func.grouping(rows.c[f"t{index}"]).label(f"g{index}"),
                rows.c[f"k{index}"],
                rows.c[f"t{index}"],
            ]
        for index, tally in enumerate(tallies):
            if index in items:
                continue
            value = rows.c[f"t{index}"]
            inner.append(
                (
                    func.sum(value)
                    if tally.figure is not None
                    else func.count().filter(value)
                ).label(f"t{index}")
            )
        sets = [
            tuple_(),
            *(tuple_(rows.c[f"k{index}"], rows.c[f"t{index}"]) for index in items),
        ]
        groups = (
            select(*inner)
            .select_from(rows)
            .group_by(func.grouping_sets(*sets))
            .subquery("g")
        )
        whole = and_(true(), *(groups.c[f"g{index}"] == 1 for index in items))
        outer = [
            (
                func.count().filter(groups.c[f"g{index}"] == 0, groups.c[f"k{index}"])
                if index in items
                else func.max(groups.c[f"t{index}"]).filter(whole)
            ).label(f"t{index}")
            for index in range(len(tallies))
        ]
        return self.read(select(*outer).select_from(groups))

    def valued(
        self,
        dimension: Dimension,
        figure: Figure | None,
        search: str | None,
        most: int | None,
    ) -> Read:
        """By each value of the dimension among the rows, `n` its rows and
        `v` its figure's sum, with its `name` where it has one; those whose
        name or key holds `search`, the case aside; in the order of their
        keys for a time, else the largest sum first, then the most rows;
        with the count of all as `total`, at most `most`."""
        columns: list[ColumnElement[Any]] = [dimension.path(self.row).label("k")]
        if dimension.name is not None:
            columns.append(dimension.name(self.row).label("name"))
        if figure is not None:
            columns.append(figure.path(self.row).label("v"))
        where = self.scoped()
        rows = (
            select(*columns).select_from(self.row.source()).where(*where).subquery("r")
        )
        grouped: list[ColumnElement[Any]] = [rows.c.k, func.count().label("n")]
        if "name" in rows.c:
            grouped.append(func.max(rows.c.name).label("name"))
        if "v" in rows.c:
            grouped.append(func.sum(rows.c.v).label("v"))
        statement = select(*grouped).group_by(rows.c.k)
        if search is not None:
            words: ColumnElement[str] = cast(rows.c.k, Text)
            if "name" in rows.c:
                words = func.concat(func.max(rows.c.name), " ", words)
            statement = statement.having(
                func.strpos(func.lower(words), search.casefold()) > 0
            )
        values = statement.subquery("v")
        order: list[Any] = (
            [values.c.k.asc().nulls_last()]
            if dimension.group == "time"
            else [
                *([values.c.v.desc().nulls_last()] if "v" in values.c else []),
                values.c.n.desc(),
                values.c.k.asc().nulls_last(),
            ]
        )
        return self.read(
            select(*values.c, func.count().over().label("total"))
            .order_by(*order)
            .limit(most)
        )

    def kinds(self, figures: Sequence[Figure]) -> list[ColumnElement[Any]]:
        """Each figure's split by the token kinds, where it has one."""
        return [
            path(self.row).label(f"k{index}_{kind}")
            for index, figure in enumerate(figures)
            if figure.kinds is not None
            for kind, path in figure.kinds.items()
        ]


def spans(found: Plan, catalogue: Catalogue, fact: str) -> Read:
    """By the By, the first and last moment of its rows of `fact` that the
    plan reads."""
    return _Builder(found, catalogue, fact).spans()


def waits(found: Plan, catalogue: Catalogue, fact: str, least: float) -> Read:
    """The rows of `fact` the plan reads that come `least` seconds or more
    after the one before them of their value of the By, each with that
    one's moment, by the By and in time order."""
    return _Builder(found, catalogue, fact).waits(least)


def runs(
    found: Plan, catalogue: Catalogue, fact: str, dimension: Dimension, least: float
) -> Read:
    """By the By, the runs of the rows of `fact` the plan reads: each
    stretch of consecutive rows of one value of `dimension` and one thread
    with no gap of `least` seconds or more in it, in time order, with its
    first and last moment, its rows, their cost, its value's name where the
    dimension has one, and whether such a gap comes before it."""
    return _Builder(found, catalogue, fact).runs(dimension, least)


def grouped(
    found: Plan,
    catalogue: Catalogue,
    fact: str,
    part: Dimension,
    figures: Sequence[Figure],
    most: int | None,
    keys: Sequence[Value] | None = None,
) -> Read:
    """By each item of `part` the plan reads of `fact`, or of those among
    `keys`, its first and last moment and each of `figures` taken together
    as it says, the earliest first, at most `most`."""
    return _Builder(found, catalogue, fact).grouped(part, figures, (), most, keys)


def own(
    found: Plan,
    catalogue: Catalogue,
    fact: str,
    figures: Sequence[Figure],
    shown: Sequence[Dimension],
    most: int,
) -> Read:
    """The rows of `fact` the plan reads, each an item of its own, the
    earliest first, at most `most`."""
    return _Builder(found, catalogue, fact).own(figures, shown, (), most)


def thread(
    found: Plan,
    catalogue: Catalogue,
    fact: str,
    figures: Sequence[Figure],
    shown: Sequence[Dimension],
    conversation: uuid.UUID,
    most: int,
) -> Read:
    """The rows of `fact` of one thread over all time with no chips, each
    an item of its own saying whether the plan's window and scope hold it,
    in their file's order, at most `most`."""
    builder = _Builder(replace(found, rows=None), catalogue, fact)
    return builder.own(
        figures,
        shown,
        [builder.row["transcript_id"] == conversation],
        most,
        scoped=False,
        order=[builder.row["position"], builder.row["call_id"]],
    )


def thread_events(found: Plan, catalogue: Catalogue, conversation: uuid.UUID) -> Read:
    """The events of one thread over all time, on the first fact that has
    their kind, in time order."""
    fact = catalogue.offered(EVENT_KIND)[0]
    return _Builder(found, catalogue, fact).thread_events(conversation)


def happened(found: Plan, catalogue: Catalogue) -> Read:
    """The events the plan reads, of the first fact that has their kind, by
    the By and in time order."""
    fact = catalogue.offered(EVENT_KIND)[0]
    return _Builder(found, catalogue, fact).happened()


def bucketed(found: Plan, catalogue: Catalogue, planned: Planned, most: int) -> Read:
    """The items of the measure's grain in each of the By's values the plan
    reads, at most `most`."""
    return _Builder(found, catalogue, planned.fact).bucketed(planned, most)


def members_before(
    found: Plan,
    catalogue: Catalogue,
    fact: str,
    start: datetime,
    excluded: Sequence[Value],
    most: int,
) -> Read:
    """The last `most` of the By's values with rows of `fact` whose place on
    the By's axis is before `start`, `excluded` aside, under the plan's
    scope over all time, the latest first."""
    return _Builder(_all_time(found), catalogue, fact).members_before(
        start, excluded, most
    )


def items_before(
    found: Plan,
    catalogue: Catalogue,
    planned: Planned,
    start: datetime,
    excluded: Sequence[Value],
    most: int,
) -> Read:
    """The last `most` items of the measure's grain to start before `start`,
    `excluded` aside, each with its figure over all its rows, under the
    plan's scope over all time, the latest first."""
    return _Builder(_all_time(found), catalogue, planned.fact).items_before(
        planned, start, excluded, most
    )


def roles(found: Plan, catalogue: Catalogue, fact: str) -> Read:
    """Each of the By's values the plan reads with the role its rows of
    `fact` share, none where they share none."""
    return _Builder(found, catalogue, fact).roles()


def shifts(found: Plan, catalogue: Catalogue) -> Read:
    """Each change in a role's configuration as it ran, under the plan's
    scope over all time, in the order of its moment, its unit's start, else
    its first Call's: a Work Unit with a role whose model or effort, those
    of its first Call on a main thread, differ from those of the unit of the
    same role before it, with those."""
    return _Builder(_all_time(found), catalogue, CALL.key).shifts()


def sightings(found: Plan, catalogue: Catalogue, dimension: str) -> Read:
    """Each value of the dimension with its first moment, on the first fact
    that offers it, under the plan's scope over all time."""
    fact = catalogue.offered(dimension)[0]
    return _Builder(_all_time(found), catalogue, fact).sightings(
        catalogue.dimension(dimension)
    )


def counted(found: Plan, catalogue: Catalogue, kind: str, error: str) -> Read:
    """By the By and the dimension `kind`, the rows the plan reads of the
    first fact that offers it, and whether any is one `error` holds."""
    fact = catalogue.offered(kind)[0]
    return _Builder(found, catalogue, fact).counted(
        catalogue.dimension(kind), catalogue.dimension(error)
    )


def attributes(
    found: Plan, catalogue: Catalogue, fact: str, keys: Sequence[str]
) -> Read:
    """Each of the dimensions `keys`' count of values among the rows of
    `fact` the plan reads, none counting as one."""
    return _Builder(found, catalogue, fact).attributes(keys)


def tallied(
    found: Plan, catalogue: Catalogue, fact: str, tallies: Sequence[Tally]
) -> Read:
    """Each tally's count or sum among the rows of `fact` the plan reads."""
    return _Builder(found, catalogue, fact).tallied(tallies)


def valued(
    found: Plan,
    catalogue: Catalogue,
    dimension: Dimension,
    figure: Figure | None,
    search: str | None,
    most: int | None,
) -> Read:
    """The values of the dimension among the rows the plan reads of the
    first fact that offers it, each with its rows and `figure`'s sum, where
    `figure` is that fact's."""
    fact = catalogue.offered(dimension.key)[0]
    summed = figure if figure is not None and figure.fact == fact else None
    return _Builder(found, catalogue, fact).valued(dimension, summed, search, most)


def _all_time(found: Plan) -> Plan:
    return replace(found, window=None, rows=None)


def ordered(catalogue: Catalogue, by: Dimension) -> Dimension | None:
    """The order dimension the By lies along: itself where it is one, else
    the first along its part."""
    if by.group == "order":
        return by
    return next(
        (
            dimension
            for dimension in catalogue.dimensions
            if dimension.group == "order" and dimension.base == by.key
        ),
        None,
    )


def _shared(value: ColumnElement[Any]) -> ColumnElement[Any]:
    """The one value every row of a group carries, none where a row carries
    none or another."""
    return case(
        (
            and_(func.count(value) == func.count(), func.min(value) == func.max(value)),
            func.min(value),
        )
    )


def _within(figure: Figure, value: ColumnElement[Any]) -> ColumnElement[Any]:
    """An item's figure, its rows' taken together as the figure says."""
    return func.max(value) if figure.within == "max" else func.sum(value)


def _threaded(row: Row) -> bool:
    """Whether the fact's rows lie in a conversation, which a filter on a
    dimension of another fact falls through."""
    return "transcript_id" in row.fact.source.c


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


def _among(path: ColumnElement[Any], values: Sequence[Value]) -> ColumnElement[bool]:
    """Whether the path's value is among `values`, bound as one array of the
    path's type, none among them matching a row with none."""
    known = [value for value in values if value is not None]
    matched = [
        *([path == any_(literal(known, ARRAY(path.type)))] if known else []),
        *([path.is_(None)] if len(known) < len(values) else []),
    ]
    return func.coalesce(or_(*matched), false()) if matched else false()


def _past(value: ColumnElement[Any], chip: OnItems) -> ColumnElement[bool]:
    """Whether `value` is past the condition's number; none is not."""
    compared = {
        "gt": value > chip.number,
        "ge": value >= chip.number,
        "lt": value < chip.number,
        "le": value <= chip.number,
    }[chip.operator]
    return func.coalesce(compared, false())


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
