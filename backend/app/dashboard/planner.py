"""The planner (F154.1, "planned"): what a checked state's statements read —
the facts its measures need, the joins its By, its color, its drill and its
chips name, and each measure's grain (`architecture.md` Part 1, "From a
state to an answer", step 4). It reads the catalogue and the state alone;
`statements` builds the statements from a plan, and `rows` runs them under
the bounds.

- The **window** is the state's time as spans of instants, each from its
  start to the instant before which it ends: a range of days or of quota
  weeks as it stands at the call, a bound written as a date or a time of
  day read in the catalogue's zone; none for all time.
- The **scope** is what keeps a fact's row: each drill level, each chip
  that keeps a dimension's values, or all but them, and each condition on
  each item of a measure's grain, the item's figure over all its rows, kept
  where it passes or, negated, where it fails. A fact that lacks a filter's
  dimension, or an item condition's grain, keeps the rows of the
  conversations whose rows of the fact that has it pass, among that fact's
  rows in the window.
- The **marks** are the marked chips on values and on each item: they keep
  nothing, and mark the By's rows that hold a row they keep, and in each
  sum its part on those rows.
- A **threshold** on the By's rows keeps, or marks, the rows whose measure,
  a ratio among them, is past its number; the **outlier rows' chip** keeps,
  or marks, the rows whose first measure is an outlier among them. Both are
  judged on the rows in the process (`rows`), and where they keep fewer than
  all, the plan's `rows` narrows its statements to those kept.
- A **quick filter** that is on is its chip, marked where its row marks.
- A **measure** of a figure is its fact's: its items are its grain's, a
  part, none being its fact's own rows, and only the rows its own filters
  keep. It is refused where its fact has no By, and answered by its
  **stand-in** where one is: the first figure, on a fact that has the By,
  that stands for the measure's (`Figure.stands_for`) and takes its
  aggregate and its grain.
- A **ratio** is its two measures, each planned so; one by its key has the
  sides the catalogue writes.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from app.dashboard.address import fixed
from app.dashboard.catalogue import Catalogue
from app.dashboard.reading import read_chip, read_simple
from app.dashboard.refusal import Fault, refused
from app.dashboard.state import (
    Between,
    Bound,
    Chip,
    Focus,
    OnItems,
    OnRows,
    Pin,
    Preset,
    RatioKey,
    Simple,
    State,
    Time,
    Value,
    Weeks,
    WrittenRatio,
    chip_key,
    instant,
    measure_key,
    number,
    simple_key,
    write_value,
)
from app.services.quota_week_service import Period

Span = tuple[datetime | None, datetime | None]
"""A span of time from its start to the instant before which it ends, none
on a side being open there."""

Window = tuple[Span, ...] | None
"""The time a view reads, none being all time and no span none of it."""


@dataclass(frozen=True)
class Condition:
    """What keeps a row: a dimension's values, or all but them."""

    dimension: str
    values: tuple[Value, ...]
    negated: bool = False

    def written(self) -> str:
        """The condition as a chip writes it."""
        values = ",".join(write_value(value) for value in self.values)
        return f"{'!' if self.negated else ''}{self.dimension}:{values}"


Kept = Condition | OnItems
"""What keeps a fact's row: a dimension's values, or each item of a
measure's grain whose figure is past a number."""


def written(kept: Kept) -> str:
    """What keeps a row as a chip writes it, with no mark."""
    if isinstance(kept, Condition):
        return kept.written()
    return chip_key(replace(kept, marked=False))


@dataclass(frozen=True)
class Planned:
    """A measure of a figure: the fact that answers it, the part its items
    are, none being its fact's own rows, why it is refused, where it is, and
    the measure that stands in for it, where one does, which its fact's
    rows then answer."""

    measure: Simple
    fact: str
    grain: str | None
    refused: str | None = None
    stand_in: Simple | None = None

    @property
    def answered(self) -> Simple:
        """The measure its statements answer: its stand-in, else itself."""
        return self.stand_in or self.measure

    @property
    def answers(self) -> bool:
        """Whether its statements answer it, itself or its stand-in."""
        return self.refused is None or self.stand_in is not None


@dataclass(frozen=True)
class PlannedRatio:
    """A ratio, its sides each a measure planned."""

    measure: RatioKey | WrittenRatio
    numerator: Planned
    denominator: Planned


Measured = Planned | PlannedRatio


def sides(measured: Measured) -> tuple[Planned, ...]:
    """The measures of a figure a measure reads: a ratio's two, else itself."""
    if isinstance(measured, PlannedRatio):
        return (measured.numerator, measured.denominator)
    return (measured,)


@dataclass(frozen=True)
class Threshold:
    """A threshold on the By's rows: those whose measure is past `number`
    kept, or marked."""

    measured: Measured
    operator: str
    number: float
    marked: bool = False

    def passes(self, value: float | None) -> bool:
        """Whether a row's value of the measure is past the number: none is
        not."""
        if value is None:
            return False
        return {
            "gt": value > self.number,
            "ge": value >= self.number,
            "lt": value < self.number,
            "le": value <= self.number,
        }[self.operator]


Judged = Literal["keep", "mark"]


@dataclass(frozen=True)
class Plan:
    """What a view's statements read: its time as the state names it and as
    a window, the By, the color, the focus, the scope, each measure, the
    marks, the thresholds on the By's rows and the outlier rows' chip, and
    `rows`, the By's values its statements are narrowed to, none where they
    are not."""

    time: Time
    window: Window
    by: str
    color: str | None
    focus: Focus | None
    scope: tuple[Kept, ...]
    measures: tuple[Measured, ...]
    marks: tuple[Kept, ...] = ()
    thresholds: tuple[Threshold, ...] = ()
    outliers: Judged | None = None
    rows: tuple[Value, ...] | None = None

    @property
    def simples(self) -> tuple[Planned, ...]:
        """Every measure of a figure the plan reads, a ratio's sides among
        them, once each: the view's in the order the state names them, then
        the thresholds'."""
        found: dict[Simple, Planned] = {}
        for measured in (
            *self.measures,
            *(threshold.measured for threshold in self.thresholds),
        ):
            for side in sides(measured):
                found.setdefault(side.measure, side)
        return tuple(found.values())

    @property
    def judges(self) -> bool:
        """Whether a threshold or the outlier rows' chip judges its rows."""
        return bool(self.thresholds) or self.outliers is not None


def plan(
    state: State, catalogue: Catalogue, weeks: Sequence[Period], now: datetime
) -> Plan:
    """The plan of a checked state's rows, its time as it stands at `now`,
    `weeks` the quota weeks the record holds in the order they start."""
    chips = state.chips + _quick_filters(state, catalogue, weeks)
    scope: list[Kept] = [
        Condition(level.dimension, (level.value,)) for level in state.levels
    ]
    marks: list[Kept] = []
    thresholds: list[Threshold] = []
    outliers: Judged | None = None
    for chip in chips:
        if isinstance(chip, Pin):
            condition = Condition(chip.dimension, chip.values, chip.negated)
            (marks if chip.marked else scope).append(condition)
        elif isinstance(chip, OnItems):
            (marks if chip.marked else scope).append(replace(chip, marked=False))
        elif isinstance(chip, OnRows):
            thresholds.append(
                Threshold(
                    _measured(chip.measure, state.by, catalogue, weeks),
                    chip.operator,
                    chip.number,
                    chip.marked,
                )
            )
        else:
            outliers = "keep" if outliers == "keep" or not chip.marked else "mark"
    return Plan(
        time=state.time,
        window=window(state.time, catalogue, weeks, now),
        by=state.by,
        color=state.color,
        focus=state.focus,
        scope=tuple(scope),
        measures=tuple(
            _measured(measure, state.by, catalogue, weeks) for measure in state.measures
        ),
        marks=tuple(marks),
        thresholds=tuple(thresholds),
        outliers=outliers,
    )


def series_plan(
    state: State, catalogue: Catalogue, weeks: Sequence[Period], now: datetime
) -> Plan:
    """The plan of a view's series, or its events strip: its rows by the
    dimension it asks (`asked`), the state's presentation one with a series
    (`presentation`)."""
    presentation(state)
    return plan(replace(state, by=asked(state, catalogue)), catalogue, weeks, now)


def presentation(state: State) -> Literal["order", "time"]:
    """The view's presentation, where it has a series; a refusal naming its
    `p` where it does not."""
    if state.presentation == "order" or state.presentation == "time":
        return state.presentation
    raise refused(
        [
            Fault(
                part=f"p={state.presentation}",
                kind="p",
                wrong=f"{_DRAWN[state.presentation]}, and only a view in order "
                "or over time has a series",
                allowed="A series takes p=order[,<order dimension>] or p=time,<grain>",
            )
        ]
    )


_DRAWN = {
    "rows": "the view draws rows",
    "lanes": "the view draws lanes",
    "table": "the view draws a table",
}


def asked(state: State, catalogue: Catalogue) -> str:
    """The dimension a view asks its rows by: in order its order dimension,
    over time its grain, else the By."""
    if state.presentation == "time" and state.axis is not None:
        return state.axis
    if state.presentation == "order":
        return state.axis or next(
            dimension.key
            for dimension in catalogue.dimensions
            if dimension.group == "order" and dimension.base == state.by
        )
    return state.by


def _quick_filters(
    state: State, catalogue: Catalogue, weeks: Sequence[Period]
) -> tuple[Chip, ...]:
    """The chip of each quick filter that is on, marked where its row
    marks."""
    held = {quick_filter.key: quick_filter for quick_filter in catalogue.quick_filters}
    return tuple(
        replace(
            read_chip(held[key].condition, catalogue, weeks), marked=held[key].marks
        )
        for key in state.quick_filters
    )


def _measured(
    measure: Simple | RatioKey | WrittenRatio,
    by: str,
    catalogue: Catalogue,
    weeks: Sequence[Period],
) -> Measured:
    if isinstance(measure, Simple):
        return _planned(measure, by, catalogue)
    if isinstance(measure, RatioKey):
        ratio = catalogue.ratio(measure.key)
        numerator = read_simple(ratio.numerator, catalogue, weeks)
        denominator = read_simple(ratio.denominator, catalogue, weeks)
    else:
        numerator, denominator = measure.numerator, measure.denominator
    return PlannedRatio(
        measure,
        _planned(numerator, by, catalogue),
        _planned(denominator, by, catalogue),
    )


def _planned(measure: Simple, by: str, catalogue: Catalogue) -> Planned:
    figure = catalogue.figure(measure.figure)
    fact = catalogue.fact(figure.fact)
    offered = catalogue.offered(by)
    if fact.key in offered:
        return Planned(measure, fact.key, measure.grain)
    refused = f"{figure.key} is a figure of {fact.many}, which have no {by}"
    stand_in = _stand_in(measure, offered, catalogue)
    if stand_in is None:
        return Planned(measure, fact.key, measure.grain, refused)
    return Planned(
        measure,
        catalogue.figure(stand_in.figure).fact,
        measure.grain,
        refused,
        stand_in,
    )


def _stand_in(
    measure: Simple, offered: Sequence[str], catalogue: Catalogue
) -> Simple | None:
    """The measure that stands in for `measure` on a fact among `offered`:
    the first figure that stands for its figure there and takes its
    aggregate and its grain, under its filters."""
    for figure in catalogue.figures:
        if figure.stands_for != measure.figure or figure.fact not in offered:
            continue
        if measure.aggregate not in catalogue.aggregates_of(figure):
            continue
        if measure.grain is not None and figure.fact not in catalogue.offered(
            measure.grain
        ):
            continue
        return replace(measure, figure=figure.key)
    return None


def window(
    time: Time, catalogue: Catalogue, weeks: Sequence[Period], now: datetime
) -> Window:
    """The time `time` names as it stands at `now`: a range of days or of
    quota weeks as `address.fixed` fixes it, a range of quota weeks the
    record does not reach none of it, all time none."""
    zone = ZoneInfo(catalogue.zone)
    time = fixed(time, catalogue, weeks, now)
    if isinstance(time, Preset):
        named = next(one for one in catalogue.ranges if one.key == time.key)
        return None if named.unit is None else ()
    if isinstance(time, Weeks):
        spans: list[tuple[datetime, datetime]] = []
        for week in weeks:
            if week.starts_at not in time.starts:
                continue
            if spans and spans[-1][1] == week.starts_at:
                spans[-1] = (spans[-1][0], week.ends_at)
            else:
                spans.append((week.starts_at, week.ends_at))
        return tuple(spans)
    assert isinstance(time, Between)
    return ((_moment(time.start, zone, False), _moment(time.end, zone, True)),)


def _moment(bound: Bound | None, zone: ZoneInfo, end: bool) -> datetime | None:
    """A bound read in `zone` as an instant in UTC: a date its midnight, or
    the next one's where it ends a range, so that it holds its day."""
    if bound is None:
        return None
    if isinstance(bound, datetime):
        return bound.replace(tzinfo=zone).astimezone(UTC)
    day: date = bound + timedelta(days=1) if end else bound
    return datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC)


def described(found: Plan, joins: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """The plan as the file of states holds the query a state means: its
    time, a range by its key as written, else its spans' instants; its By,
    color and scope; each measure with its fact and the part its items are,
    or why it is refused and what stands in for it; `joins`, its statements
    as `statements.described` gives them; and its marks, its thresholds,
    each with what it keeps or marks, and the outlier rows' chip."""
    query: dict[str, Any] = {
        "time": (
            found.time.key
            if isinstance(found.time, Preset)
            else [
                [None if moment is None else instant(moment) for moment in span]
                for span in found.window or ()
            ]
        ),
        "by": found.by,
        "color": found.color,
    }
    if found.focus is not None:
        query["focus"] = f"{found.focus.dimension}:{write_value(found.focus.key)}"
    query["scope"] = [written(kept) for kept in found.scope]
    query["measures"] = [_described(measured) for measured in found.measures]
    query["statements"] = list(joins)
    if found.marks:
        query["marks"] = [written(kept) for kept in found.marks]
    if found.thresholds:
        query["thresholds"] = [
            {
                "marks" if threshold.marked else "keeps": (
                    f"{threshold.operator},{number(threshold.number)}"
                ),
                "measure": _described(threshold.measured),
            }
            for threshold in found.thresholds
        ]
    if found.outliers is not None:
        query["outliers"] = found.outliers
    return query


def _described(measured: Measured) -> dict[str, Any]:
    if isinstance(measured, PlannedRatio):
        return {
            "measure": measure_key(measured.measure),
            "over": [_described(measured.numerator), _described(measured.denominator)],
        }
    entry: dict[str, Any] = {
        "measure": simple_key(measured.measure),
        "fact": measured.fact,
    }
    if measured.grain is not None:
        entry["items"] = measured.grain
    if measured.refused is not None:
        entry["refused"] = measured.refused
    if measured.stand_in is not None:
        entry["stand_in"] = simple_key(measured.stand_in)
    return entry
