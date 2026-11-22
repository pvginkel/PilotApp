"""A view's rows (F154.1, F154.3): every measure on each of the By's rows and
on the All row, with the split by the color, answered from Pilot's record at
the query down the one path — read, checked, written back as the answer's
address, planned, run under the bounds, shaped. The Rows and the Table draw
it.

- A row is a value of the By any statement reads; a measure's value on it
  none where it has no item there, and `n` its items with a value.
- A ratio is its numerator over its denominator on each row, none where the
  denominator is none or zero; a numerator with no item is 0 where it is a
  sum or a count and the denominator has items.
- The rows are in the sort the state names, else by the first measure, the
  largest first; a row with none in the column last. At most `ROWS` are
  answered, with the count of all.
- The color's values are those of the first measure that stacks, by its
  amount on the All row, the largest first, past `COLORS` folded into one;
  the token kinds in their order. Each row splits each measure that stacks
  over those values.
- A measure's `median` is the median of its rows' values, the rows that hold
  the focus left out: the peers' median the Rows draw a tick at.
- Times are instants with the engine's zone beside them, never text, which
  the page writes: the window's spans, and a key of the By or of the color
  that is a time.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.dashboard.address import Address, AddressService
from app.dashboard.assembly import ratio_format
from app.dashboard.bounds import Bounds
from app.dashboard.catalogue import COUNT, Catalogue, Dimension, Format
from app.dashboard.planner import Plan, Planned, PlannedRatio, Window, plan
from app.dashboard.state import (
    OWN_COLUMNS,
    TOKEN_KIND,
    RatioKey,
    Sort,
    Value,
    measure_key,
)
from app.dashboard.statements import Items, Scan, Statement, stacks, statements

ROWS = 2_000
"""The rows an answer carries at most."""

COLORS = 12
"""The color's values an answer names; the rest fold into one."""

TOKEN_KIND_LABEL = "Token kind"


@dataclass(frozen=True)
class Measure:
    """A measure as the rows answer it: `key` as the normal form writes it,
    `aggregate` and `grain` none for a ratio, `refused` why where it is."""

    key: str
    label: str
    format: Format
    aggregate: str | None
    grain: str | None
    stacks: bool
    refused: str | None
    median: float | None


@dataclass(frozen=True)
class ColorValue:
    """A value of the color, `others` the count of values folded into it,
    0 for a value of its own; `label` none where the key is its own."""

    key: Value
    label: str | None
    total: float | None
    others: int = 0


@dataclass(frozen=True)
class Color:
    key: str
    label: str
    values: tuple[ColorValue, ...]


@dataclass(frozen=True)
class Line:
    """The All row or a row of the By: each measure's value and its items
    with one, and each measure's split over the color's values, none for one
    that does not stack."""

    values: tuple[float | None, ...]
    n: tuple[int, ...]
    split: tuple[tuple[float, ...] | None, ...] | None


@dataclass(frozen=True)
class ByRow(Line):
    key: Value = None
    label: str | None = None
    focus: bool = False


@dataclass(frozen=True)
class Rows:
    """A view's rows."""

    address: Address
    zone: str
    window: Window
    by: Dimension
    measures: tuple[Measure, ...]
    color: Color | None
    all: Line
    rows: tuple[ByRow, ...]
    total_rows: int
    sort: Sort


@dataclass
class _Taken:
    """What the statements give of one row."""

    values: dict[int, tuple[Any, int]] = field(default_factory=dict)
    by_color: dict[int, dict[Value, Any]] = field(default_factory=dict)
    kinds: dict[int, dict[str, Any]] = field(default_factory=dict)
    name: str | None = None
    axis: Any = None
    focus: bool = False


class RowsService:
    """A view's rows, from its state as the URL writes it."""

    def __init__(
        self, db: Session, address_service: AddressService, bounds: Bounds
    ) -> None:
        self.db = db
        self.address_service = address_service
        self.bounds = bounds

    def rows(self, written: str, now: datetime | None = None) -> Rows:
        """The rows of the state `written`, its time as it stands at `now`.

        Raises:
            StateRefusedException: the state has a fault
            QueryRefusedException: a statement passed the engine's bounds
        """
        view = self.address_service.view(written)
        found = plan(
            view.address.state, view.catalogue, view.weeks, now or datetime.now(UTC)
        )
        if found.after:
            raise NotImplementedError(
                "The rows apply no threshold, item condition, outlier rows' "
                "chip, marked chip or quick filter yet: " + ", ".join(found.after)
            )
        built = statements(found, view.catalogue)
        with self.bounds.read(self.db) as db:
            answers = [
                (statement, db.execute(statement.select).all()) for statement in built
            ]
        return _Shaper(view.catalogue, found, view.address).shaped(answers)


class _Shaper:
    def __init__(self, catalogue: Catalogue, found: Plan, address: Address) -> None:
        self.catalogue = catalogue
        self.plan = found
        self.address = address
        self.simples = found.simples
        self.rows: dict[Value, _Taken] = {}
        self.all = _Taken()
        self.names: dict[Value, Any] = {}

    def shaped(self, answers: Sequence[tuple[Statement, Sequence[Any]]]) -> Rows:
        for statement, found in answers:
            for row in found:
                if isinstance(statement, Scan):
                    self.scanned(statement, row)
                else:
                    self.itemised(statement, row)
        for taken in self.rows.values():
            for index, cells in taken.by_color.items():
                whole = self.all.by_color.setdefault(index, {})
                for value, amount in cells.items():
                    whole[value] = whole.get(value, 0) + (amount or 0)
        state = self.address.state
        by = self.catalogue.dimension(self.plan.by)
        stacked = [
            stacks(planned, self.plan.color, self.catalogue)
            if isinstance(planned, Planned)
            else False
            for planned in self.plan.measures
        ]
        color = self.color(stacked)
        lines = {
            key: self.line(taken, color, stacked) for key, taken in self.rows.items()
        }
        rows = [
            ByRow(
                values=line.values,
                n=line.n,
                split=line.split,
                key=key,
                label=_label(by, key, self.rows[key].name),
                focus=self.rows[key].focus,
            )
            for key, line in lines.items()
        ]
        sort = state.sort or Sort("desc", measure_key(state.measures[0]))
        rows = _sorted(
            rows,
            sort,
            state.measures,
            {key: one.axis for key, one in self.rows.items()},
        )
        peers = [row for row in rows if not row.focus]
        measures = tuple(
            self.measure(index, measured, stacked[index], peers)
            for index, measured in enumerate(self.plan.measures)
        )
        return Rows(
            address=self.address,
            zone=self.catalogue.zone,
            window=self.plan.window,
            by=by,
            measures=measures,
            color=color,
            all=self.line(self.all, color, stacked),
            rows=tuple(rows[:ROWS]),
            total_rows=len(rows),
            sort=sort,
        )

    # ------------------------------------------------------------ what the statements give

    def scanned(self, statement: Scan, row: Any) -> None:
        mapping = row._mapping
        g = mapping["g"]
        if statement.colored and g == 0:
            taken = self.rows.setdefault(mapping["b"], _Taken())
            key = mapping["c"]
            if "c_name" in mapping:
                self.names[key] = mapping["c_name"]
            for index in statement.splits:
                taken.by_color.setdefault(index, {})[key] = mapping[f"s{index}"]
            return
        whole = g == (3 if statement.colored else 1)
        taken = self.all if whole else self.rows.setdefault(mapping["b"], _Taken())
        if not whole:
            if "b_name" in mapping:
                taken.name = mapping["b_name"]
            if "axis" in mapping:
                taken.axis = mapping["axis"]
            if "focus" in mapping:
                taken.focus = taken.focus or bool(mapping["focus"])
        for index in statement.measures:
            taken.values[index] = (mapping[f"v{index}"], mapping[f"n{index}"])
        for index in statement.kinds:
            figure = self.catalogue.figure(self.simples[index].measure.figure)
            assert figure.kinds is not None
            taken.kinds[index] = {
                kind: mapping[f"k{index}_{kind}"] for kind in figure.kinds
            }

    def itemised(self, statement: Items, row: Any) -> None:
        mapping = row._mapping
        whole = mapping["g"] == 1
        taken = self.all if whole else self.rows.setdefault(mapping["b"], _Taken())
        for index in statement.measures:
            taken.values[index] = (mapping[f"v{index}"], mapping[f"n{index}"])

    # ------------------------------------------------------------ the color

    def color(self, stacked: Sequence[bool]) -> Color | None:
        key = self.plan.color
        if key is None:
            return None
        lead = next(
            (
                self.simples.index(planned)
                for planned, stacks_ in zip(self.plan.measures, stacked, strict=True)
                if stacks_ and isinstance(planned, Planned)
            ),
            None,
        )
        if key == TOKEN_KIND:
            kinds = self._kinds()
            totals = self.all.kinds.get(lead, {}) if lead is not None else {}
            return Color(
                TOKEN_KIND,
                TOKEN_KIND_LABEL,
                tuple(
                    ColorValue(kind, None, _number(totals.get(kind)))
                    for kind in (kinds if lead is not None else ())
                ),
            )
        dimension = self.catalogue.dimension(key)
        amounts = {
            value: _number(amount) or 0.0
            for value, amount in (
                self.all.by_color.get(lead, {}) if lead is not None else {}
            ).items()
        }
        ordered = sorted(amounts, key=lambda value: (-amounts[value], _order(value)))
        kept, rest = ordered[:COLORS], ordered[COLORS:]
        if len(rest) == 1:
            kept, rest = ordered, []
        values = [
            ColorValue(
                value, _label(dimension, value, self.names.get(value)), amounts[value]
            )
            for value in kept
        ]
        if rest:
            values.append(
                ColorValue(
                    None,
                    f"{len(rest)} other values",
                    sum(amounts[value] for value in rest),
                    others=len(rest),
                )
            )
        return Color(dimension.key, dimension.label, tuple(values))

    def _kinds(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                kind
                for figure in self.catalogue.figures
                if figure.kinds is not None
                for kind in figure.kinds
            )
        )

    # ------------------------------------------------------------ the lines

    def line(self, taken: _Taken, color: Color | None, stacked: Sequence[bool]) -> Line:
        values: list[float | None] = []
        counts: list[int] = []
        splits: list[tuple[float, ...] | None] = []
        for measured, stacks_ in zip(self.plan.measures, stacked, strict=True):
            value, n = self.value(taken, measured)
            values.append(value)
            counts.append(n)
            splits.append(
                self.split(taken, measured, color) if stacks_ and color else None
            )
        return Line(
            tuple(values),
            tuple(counts),
            tuple(splits) if color is not None else None,
        )

    def value(
        self, taken: _Taken, measured: Planned | PlannedRatio
    ) -> tuple[float | None, int]:
        if isinstance(measured, Planned):
            return self.simple(taken, measured)
        top, _ = self.simple(taken, measured.numerator)
        bottom, n = self.simple(taken, measured.denominator)
        if top is None and n and measured.numerator.measure.aggregate in ("sum", COUNT):
            top = 0.0
        if top is None or not bottom:
            return None, n
        return top / bottom, n

    def simple(self, taken: _Taken, planned: Planned) -> tuple[float | None, int]:
        value, n = taken.values.get(self.simples.index(planned), (None, 0))
        return (_number(value) if n else None), n

    def split(
        self, taken: _Taken, measured: Planned | PlannedRatio, color: Color
    ) -> tuple[float, ...]:
        assert isinstance(measured, Planned)
        index = self.simples.index(measured)
        if color.key == TOKEN_KIND:
            kinds = taken.kinds.get(index, {})
            return tuple(
                _number(kinds.get(str(value.key))) or 0.0 for value in color.values
            )
        cells = taken.by_color.get(index, {})
        named = {value.key for value in color.values if not value.others}
        return tuple(
            _number(
                sum(amount or 0 for key, amount in cells.items() if key not in named)
            )
            or 0.0
            if value.others
            else _number(cells.get(value.key)) or 0.0
            for value in color.values
        )

    def measure(
        self,
        index: int,
        measured: Planned | PlannedRatio,
        stacks_: bool,
        peers: Sequence[ByRow],
    ) -> Measure:
        known = [value for row in peers if (value := row.values[index]) is not None]
        median = statistics.median(known) if known else None
        if isinstance(measured, PlannedRatio):
            if isinstance(measured.measure, RatioKey):
                ratio = self.catalogue.ratio(measured.measure.key)
                label, format_ = ratio.label, ratio.format
            else:
                label = measured.measure.name
                format_ = ratio_format(
                    self.catalogue,
                    measured.numerator.measure,
                    measured.denominator.measure,
                )
            return Measure(
                key=measure_key(measured.measure),
                label=label,
                format=format_,
                aggregate=None,
                grain=None,
                stacks=False,
                refused=measured.numerator.refused or measured.denominator.refused,
                median=median,
            )
        figure = self.catalogue.figure(measured.measure.figure)
        return Measure(
            key=measure_key(measured.measure),
            label=figure.label,
            format=figure.format,
            aggregate=measured.measure.aggregate,
            grain=measured.grain,
            stacks=stacks_,
            refused=measured.refused,
            median=median,
        )


def _label(dimension: Dimension, key: Value, name: str | None) -> str | None:
    """A value's label: its closed list's name, its name in the record, or
    the dimension's label of none; none where the key is its own."""
    if key is None:
        return dimension.null
    if dimension.values is not None:
        for value in dimension.values:
            if value.code == str(key):
                return value.name
    return name


def _number(value: Decimal | float | int | None) -> float | None:
    return None if value is None else float(value)


def _order(value: Value) -> tuple[bool, str]:
    return (value is None, "" if value is None else str(value))


def _sorted(
    rows: list[ByRow],
    sort: Sort,
    measures: Sequence[Any],
    axes: dict[Value, Any],
) -> list[ByRow]:
    """The rows in `sort`, those with none in its column last, each tie by
    its key."""
    keys = [measure_key(measure) for measure in measures]
    if sort.column in OWN_COLUMNS:

        def column(row: ByRow) -> Any:
            if sort.column == "label":
                return (row.label if row.label is not None else str(row.key)).casefold()
            if sort.column == "n":
                return row.n[0] if row.n else None
            axis = axes.get(row.key)
            return axis if axis is not None else row.key
    else:
        at = keys.index(sort.column)

        def column(row: ByRow) -> Any:
            return row.values[at]

    ordered = sorted(rows, key=lambda row: _order(row.key))
    known = [row for row in ordered if column(row) is not None]
    unknown = [row for row in ordered if column(row) is None]
    known.sort(key=column, reverse=sort.direction == "desc")
    return known + unknown
