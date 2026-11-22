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
- The **scope** is what keeps a fact's row: each drill level, and each chip
  that keeps a dimension's values, or all but them. A fact that lacks a
  filter's dimension keeps the rows of the conversations whose rows of the
  first fact that has it pass, among that fact's rows in the window.
- A **measure** of a figure is its fact's: its items are its grain's, a
  part, none being its fact's own rows, and only the rows its own filters
  keep. It is refused where its fact has no By.
- A **ratio** is its two measures, each planned so; one by its key has the
  sides the catalogue writes.
- The chips the statements do not apply, a threshold on the By's rows, a
  condition on each item, the outlier rows' chip and a marked chip, and the
  quick filters that are on, the plan carries as the state writes them.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.dashboard.address import fixed
from app.dashboard.catalogue import Catalogue
from app.dashboard.reading import read_simple
from app.dashboard.state import (
    Between,
    Bound,
    Focus,
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
    enc,
    instant,
    measure_key,
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


@dataclass(frozen=True)
class Planned:
    """A measure of a figure: the fact that answers it, the part its items
    are, none being its fact's own rows, and why it is refused, where it is."""

    measure: Simple
    fact: str
    grain: str | None
    refused: str | None = None


@dataclass(frozen=True)
class PlannedRatio:
    """A ratio, its sides each a measure planned."""

    measure: RatioKey | WrittenRatio
    numerator: Planned
    denominator: Planned


Measured = Planned | PlannedRatio


@dataclass(frozen=True)
class Plan:
    """What a view's statements read: its time as the state names it and as
    a window, the By, the color, the focus, the scope, each measure, and the
    chips and quick filters the statements leave to what follows them."""

    time: Time
    window: Window
    by: str
    color: str | None
    focus: Focus | None
    scope: tuple[Condition, ...]
    measures: tuple[Measured, ...]
    after: tuple[str, ...]

    @property
    def simples(self) -> tuple[Planned, ...]:
        """Every measure of a figure the plan reads, a ratio's sides among
        them, once each, in the order the state names them."""
        found: dict[Simple, Planned] = {}
        for measured in self.measures:
            sides = (
                (measured.numerator, measured.denominator)
                if isinstance(measured, PlannedRatio)
                else (measured,)
            )
            for side in sides:
                found.setdefault(side.measure, side)
        return tuple(found.values())


def plan(
    state: State, catalogue: Catalogue, weeks: Sequence[Period], now: datetime
) -> Plan:
    """The plan of a checked state's rows, its time as it stands at `now`,
    `weeks` the quota weeks the record holds in the order they start."""
    scope = tuple(
        Condition(level.dimension, (level.value,)) for level in state.levels
    ) + tuple(
        Condition(chip.dimension, chip.values, chip.negated)
        for chip in state.chips
        if isinstance(chip, Pin) and not chip.marked
    )
    after = tuple(
        chip_key(chip)
        for chip in state.chips
        if not isinstance(chip, Pin) or chip.marked
    ) + tuple(f"b={enc(key)}" for key in state.quick_filters)
    return Plan(
        time=state.time,
        window=window(state.time, catalogue, weeks, now),
        by=state.by,
        color=state.color,
        focus=state.focus,
        scope=scope,
        measures=tuple(
            _measured(measure, state.by, catalogue, weeks) for measure in state.measures
        ),
        after=after,
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
    refused = None
    if fact.key not in catalogue.offered(by):
        refused = f"{figure.key} is a figure of {fact.many}, which have no {by}"
    return Planned(measure, fact.key, measure.grain, refused)


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
    or why it is refused; `joins`, its statements as `statements.described`
    gives them; and the chips and quick filters its statements leave."""
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
    query["scope"] = [condition.written() for condition in found.scope]
    query["measures"] = [_described(measured) for measured in found.measures]
    query["statements"] = list(joins)
    if found.after:
        query["after"] = list(found.after)
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
    return entry
