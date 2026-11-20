"""The catalogue: what a view of the dashboard may name (F154.4), and how each
name reads Pilot's record (F154.3).

It is assembled, never written down (`assembly.assemble`): from Pilot's code
what is Pilot's own or the collector's fact, and from the record's rows the
vocabularies. Every entry is a row of one of the shapes here, whichever
source gave it, so a source that declares more adds rows and no shape.

- A **fact** is what a measure counts or sums: its `source` a table of the
  record or a union of a few, one row a thing that happened.
- A **join** reaches one table from a fact's row, many rows to one, so that a
  row is never lost or doubled. A **path** is an expression over one row: the
  fact's own columns (`Row[...]`) and the tables its joins reach (`Row.to`).
  A fact offers what every column its path reads is on.
- A **dimension** is what a view is By, filtered on and colored by: a part
  of the work, an attribute, a time, or a part along an order.
- A **figure** is a number of one fact's row; a view's measure is a figure
  under an aggregate at a grain. A **grain** is any part, or a fact's own row.
- A **ratio** is two measures, each as a view's state writes it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Literal

from sqlalchemy import ColumnElement, FromClause

Group = Literal["part", "attribute", "time", "order"]
Format = Literal["usd", "tokens", "count", "seconds", "share"]
Within = Literal["sum", "max"]


class Unreachable(Exception):
    """A path read a column its fact's rows do not have."""

    def __init__(self, fact: str, column: str) -> None:
        super().__init__(f"The fact {fact} has no column {column}")
        self.fact = fact
        self.column = column


@dataclass(frozen=True)
class Fact:
    """What a measure counts or sums. `source` is its rows, with `at` the
    moment of each; `counts` the figure that counts them; `part` the part
    one row is, none where a row is no part of the work, and `shows` then
    the dimensions shown with one row."""

    key: str
    label: str
    one: str
    many: str
    source: FromClause
    counts: str
    part: str | None = None
    shows: tuple[str, ...] = ()


@dataclass(frozen=True)
class Join:
    """One table a fact's row reaches, many rows to one. `on` reads the row
    it starts from, and takes the joins before it by reading them."""

    key: str
    table: FromClause
    on: Callable[[Row], ColumnElement[bool]]


class Row:
    """One row of a fact as a path reads it. Reading a join's table takes the
    join, and the joins it starts from before it."""

    def __init__(self, fact: Fact, joins: Mapping[str, Join]) -> None:
        self.fact = fact
        self._joins = joins
        self._taken: dict[str, ColumnElement[bool]] = {}

    def __getitem__(self, column: str) -> ColumnElement[Any]:
        """A column of the fact's own row."""
        if column not in self.fact.source.c:
            raise Unreachable(self.fact.key, column)
        return self.fact.source.c[column]

    def to(self, key: str) -> FromClause:
        """The table the join `key` reaches from this row."""
        if key not in self._taken:
            on = self._joins[key].on(self)
            self._taken[key] = on
        return self._joins[key].table

    @property
    def taken(self) -> tuple[str, ...]:
        """The joins read so far, each after those it starts from."""
        return tuple(self._taken)

    def source(self) -> FromClause:
        """The fact's rows with the joins read so far, a row kept where a
        join reaches nothing."""
        source = self.fact.source
        for key, on in self._taken.items():
            source = source.outerjoin(self._joins[key].table, on)
        return source


Path = Callable[[Row], ColumnElement[Any]]


@dataclass(frozen=True)
class Value:
    """One value of a dimension's closed list: a row of a vocabulary of the
    record, or a value Pilot's code declares. `line` says what it is and
    `position` is its place in its list, where its source gives them;
    `is_error` whether an event of the kind counts as an error, on an event
    kind alone."""

    code: str
    name: str
    line: str | None = None
    position: int | None = None
    is_error: bool | None = None


@dataclass(frozen=True)
class Dimension:
    """What a view is By, filtered on and colored by. `path` is its key over
    one row and `name` its label there, where the key is an id; `null` the
    label of a row with none. `values` is its closed list, none where its
    values are open.

    A part has the nouns of one and of many, as a grain is named; `next` is
    the By a click on its row moves to and `next_null` the one from the row
    with none. An order dimension is a part along an axis: `base` the part,
    `axis` each member's place.
    """

    key: str
    label: str
    group: Group
    line: str
    path: Path
    name: Path | None = None
    null: str = "(None)"
    values: tuple[Value, ...] | None = None
    one: str | None = None
    many: str | None = None
    next: str | None = None
    next_null: str | None = None
    base: str | None = None
    axis: Path | None = None
    figures: tuple[str, ...] = ()
    shows: tuple[str, ...] = ()
    """A part's alone: the figures an item of it carries and, on an item
    that is one row of a fact, the dimensions shown with it."""


@dataclass(frozen=True)
class Figure:
    """A number of one row of its fact. `within` is how an item takes its
    rows together, their sum or their largest; `aggregate` the aggregate a
    measure of it takes where it names none. `kinds` is the figure split by
    Token Kind, a path each, on a figure that counts tokens; `stacks` whether
    a color may stack it."""

    key: str
    label: str
    fact: str
    line: str
    format: Format
    path: Path
    within: Within = "sum"
    aggregate: str = "sum"
    kinds: Mapping[str, Path] | None = None
    stacks: bool = True


@dataclass(frozen=True)
class Aggregate:
    """How a measure takes the items of its grain together."""

    key: str
    label: str
    line: str


@dataclass(frozen=True)
class Grain:
    """What a measure's items are: a part, or a fact's own row. `figures`
    are those an item of it carries and `shows` the dimensions shown with an
    item that is one row of a fact."""

    key: str
    one: str
    many: str
    figures: tuple[str, ...]
    shows: tuple[str, ...]


@dataclass(frozen=True)
class Ratio:
    """Two measures, each as a view's state writes it (F155.4), the first
    over the second. A built-in one names nothing of a workflow."""

    key: str
    label: str
    line: str
    format: Format
    numerator: str
    denominator: str


@dataclass(frozen=True)
class TimeRange:
    """A time range a view's state names by a key: the last `count` of
    `unit`, the running one included, ending `back` of them before it; no
    unit, all time. A day is the zone's."""

    key: str
    label: str
    line: str
    unit: Literal["day", "quota_week"] | None = None
    count: int = 1
    back: int = 0


COUNT = "count"
"""The aggregate that counts a grain's items, which only a fact's counting
figure takes."""


@dataclass(frozen=True)
class Catalogue:
    """Everything a view may name, as one assembly gave it. `zone` is the
    zone the day, the weekday and the hour are derived in, and `sitting_gap`
    the gap that ends a sitting (DB decision 80.3)."""

    zone: str
    sitting_gap: timedelta
    facts: tuple[Fact, ...]
    joins: tuple[Join, ...]
    dimensions: tuple[Dimension, ...]
    figures: tuple[Figure, ...]
    aggregates: tuple[Aggregate, ...]
    ratios: tuple[Ratio, ...]
    ranges: tuple[TimeRange, ...]
    _joins: Mapping[str, Join] = field(init=False, repr=False, compare=False)
    _offered: Mapping[str, tuple[str, ...]] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        for kind, entries in (
            ("fact", self.facts),
            ("join", self.joins),
            ("dimension", self.dimensions),
            ("figure", self.figures),
            ("aggregate", self.aggregates),
            ("ratio", self.ratios),
            ("time range", self.ranges),
        ):
            keys = [entry.key for entry in entries]
            twice = sorted({key for key in keys if keys.count(key) > 1})
            if twice:
                raise ValueError(f"The catalogue holds the {kind} {twice[0]} twice")
        object.__setattr__(self, "_joins", {join.key: join for join in self.joins})
        object.__setattr__(
            self,
            "_offered",
            {
                dimension.key: tuple(
                    fact.key for fact in self.facts if self._reads(fact, dimension)
                )
                for dimension in self.dimensions
            },
        )

    def _reads(self, fact: Fact, dimension: Dimension) -> bool:
        row = self.row(fact)
        try:
            for path in (dimension.path, dimension.name, dimension.axis):
                if path is not None:
                    path(row)
        except Unreachable:
            return False
        return True

    def row(self, fact: Fact) -> Row:
        """A row of `fact` for paths to read."""
        return Row(fact, self._joins)

    def fact(self, key: str) -> Fact:
        return _one(self.facts, key)

    def dimension(self, key: str) -> Dimension:
        return _one(self.dimensions, key)

    def figure(self, key: str) -> Figure:
        return _one(self.figures, key)

    def ratio(self, key: str) -> Ratio:
        return _one(self.ratios, key)

    def offered(self, dimension: str) -> tuple[str, ...]:
        """The facts that offer the dimension, those whose rows every column
        its paths read is on, in the facts' order."""
        return self._offered[dimension]

    def aggregates_of(self, figure: Figure) -> tuple[str, ...]:
        """The aggregates a measure of the figure takes: every one on its
        fact's counting figure, every one but the count on another."""
        counts = self.fact(figure.fact).counts == figure.key
        return tuple(
            aggregate.key
            for aggregate in self.aggregates
            if counts or aggregate.key != COUNT
        )

    @property
    def grains(self) -> tuple[Grain, ...]:
        """Every part, and the own row of a fact whose row is no part."""
        parts = tuple(
            Grain(
                part.key,
                part.one or part.key,
                part.many or part.key,
                part.figures,
                part.shows,
            )
            for part in self.dimensions
            if part.group == "part"
        )
        own = tuple(
            Grain(fact.key, fact.one, fact.many, (), fact.shows)
            for fact in self.facts
            if fact.part is None
        )
        return parts + own


def _one[Entry: (Fact, Dimension, Figure, Ratio)](
    entries: tuple[Entry, ...], key: str
) -> Entry:
    for entry in entries:
        if entry.key == key:
            return entry
    raise KeyError(key)
