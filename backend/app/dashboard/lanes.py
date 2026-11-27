"""A view's lanes (F164.6, F164.8): the scope's calls on a clock axis, a lane
per member of the By, answered down the one path the rows take (`rows`),
the chips as they take them, with what a lane draws besides.

- A **lane** is a row of the By that holds Calls in the window and the
  scope, with every measure the rows answer on it, its first and last
  moment, its runs, its waits and its events, each in time order. The lanes
  are in the order they began, the earliest first, at most `LANES`, with the
  count of all. A threshold on the By's rows and the outlier rows' chip keep
  the lanes of the rows they keep.
- A **wait** is a gap of `WAIT` seconds or more between a lane's rows, from
  the one before it to the one that ends it, with that one's thread and
  Call; past the cache's lifetime where that Call waited past it, its own
  wait spanning the gap.
- A **run** is a stretch of a lane's consecutive rows of one value and one
  thread with no wait in it, from its first row's moment to the next run's
  first, or to its own last row's where a wait or the lane's end follows it
  (the mockup's `lanes`, "runs of calls coloured by the turn class's kind
  (start, work, gate, records, wait) or by the colour dimension"). Its value
  is the view's color's where the view names one the Calls carry, else its
  Segment's kind; the token kinds are no value of a row. The runs' color
  names the values its runs hold: a color's by their runs' cost, the largest
  first, past `COLORS` folded into one, as the rows' are; the Segment kinds
  in their list's order, none last. A run says its value by its place among
  those.
- An **event** is at its moment on its lane, with its key, its thread, the
  Call it is held on and that Call's cost, a cache miss's its cost, and its
  one short detail (D6).
- Past `MARKS` runs, waits and events in all, each lane's are **merged** at
  a resolution of the whole span's, the span over `RESOLUTION`, doubled
  until they are within it (the mockup's `lanes`, "past MAX_SEGMENTS,
  abutting segments merge up to a resolution of the whole window"): two runs
  where one ends as the next begins and either is shorter than the
  resolution or both are of one value and one thread, the merged one of the
  costlier's value and thread; two waits where less than the resolution
  lies between them; two events of a kind where less than it lies between
  the first of them and the next. A merged one says how many it holds, and
  an event that holds more than one no detail.
- The **kinds** are those the lanes hold, as the strip names them.
- Times are instants, which the page writes: the span, a lane's moments,
  each run's, wait's and event's, and each quota week that starts within the
  span.
"""

from __future__ import annotations

import functools
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.dashboard import statements as statement
from app.dashboard.address import Address, AddressService, View
from app.dashboard.assembly import EVENT_KIND
from app.dashboard.bounds import Bounds
from app.dashboard.catalogue import Catalogue, Dimension
from app.dashboard.dimensions import SEGMENT_KIND
from app.dashboard.facts import event_key
from app.dashboard.items import Detail, detail_of
from app.dashboard.planner import Plan, Window, plan
from app.dashboard.refusal import Fault, refused
from app.dashboard.rows import (
    COLORS,
    ByRow,
    Color,
    ColorValue,
    Line,
    Measure,
    answered,
    value_label,
)
from app.dashboard.state import TOKEN_KIND, State, Value
from app.dashboard.strip import SeenKind, seen_kinds

CALL = "call"
"""The fact whose rows a lane is: the Calls, and the Turns standing in."""

LANES = 200
"""The lanes an answer carries at most, the earliest."""

WAIT = 60.0
"""The seconds between a lane's rows from which the gap is a wait."""

MARKS = 12_000
"""The runs, waits and events the lanes carry in all before they are
merged."""

RESOLUTION = 4_000
"""The parts of the whole span the first merge's resolution is one of."""


@dataclass(frozen=True)
class Run:
    """A run of a lane's rows, `color` its value's place among the runs'
    color's values, `n` its rows, `cost` theirs, none where none has one;
    a merged run's value and thread those of the costlier of the two it was
    merged from."""

    starts_at: datetime
    ends_at: datetime
    color: int
    conversation: uuid.UUID | None
    n: int
    cost: float | None


@dataclass(frozen=True)
class Wait:
    """A gap between a lane's rows, `n` those merged into it."""

    starts_at: datetime
    ends_at: datetime
    conversation: uuid.UUID | None
    call: int | None
    past_ttl: bool
    n: int = 1


@dataclass(frozen=True)
class LaneEvent:
    """An event on a lane, `n` those of its kind merged into it, its detail
    none where it holds more than one; `cost` that of the Calls it is held
    on."""

    at: datetime
    kind: str
    is_error: bool
    key: str
    conversation: uuid.UUID | None
    call: int
    cost: float | None
    detail: Detail | None
    n: int = 1


@dataclass(frozen=True)
class Lane(ByRow):
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    runs: tuple[Run, ...] = ()
    waits: tuple[Wait, ...] = ()
    events: tuple[LaneEvent, ...] = ()


@dataclass(frozen=True)
class Lanes:
    """A view's lanes: `run_color` what their runs are colored by, each
    value's total its runs' cost; `resolution` the merge's in seconds, none
    where nothing is merged; `weeks` the instants a quota week starts at
    within the span."""

    address: Address
    zone: str
    window: Window
    by: Dimension
    measures: tuple[Measure, ...]
    color: Color | None
    all: Line
    lanes: tuple[Lane, ...]
    run_color: Color
    total_lanes: int
    starts_at: datetime | None
    ends_at: datetime | None
    weeks: tuple[datetime, ...]
    kinds: tuple[SeenKind, ...]
    wait_seconds: float
    resolution: float | None


def lanes_of(state: State) -> None:
    """Nothing where the view draws lanes; a refusal naming its `p` where
    it does not."""
    if state.presentation == "lanes":
        return
    raise refused(
        [
            Fault(
                part=f"p={state.presentation}",
                kind="p",
                wrong=f"the view draws {_DRAWN[state.presentation]}, and only a "
                "view in lanes has lanes",
                allowed="Lanes take p=lanes, with a By that is a part",
            )
        ]
    )


_DRAWN = {
    "rows": "rows",
    "order": "a series in order",
    "time": "a series over time",
    "table": "a table",
}


class LanesService:
    """A view's lanes, from its state as the URL writes it."""

    def __init__(
        self, db: Session, address_service: AddressService, bounds: Bounds
    ) -> None:
        self.db = db
        self.address_service = address_service
        self.bounds = bounds

    def lanes(self, written: str, now: datetime | None = None) -> Lanes:
        """The lanes of the state `written`, its time as it stands at `now`.

        Raises:
            StateRefusedException: the state has a fault, or is not in lanes
            QueryRefusedException: a statement passed the engine's bounds
        """
        view = self.address_service.view(written)
        state = view.address.state
        lanes_of(state)
        catalogue = view.catalogue
        found = plan(state, catalogue, view.weeks, now or datetime.now(UTC))
        with self.bounds.read(self.db, view.deadline) as db:
            shaper, read = answered(db, found, catalogue, view.address)
            shaped = shaper.shaped(every=True)
            rows = {row.key: row for row in shaped.rows}
            kept = tuple(shaper.rows) if len(shaper.rows) < len(read) else None
            narrowed = replace(found, rows=kept, marks=(), thresholds=(), outliers=None)
            spans = {
                row.b: (row.first, row.last)
                for row in db.execute(statement.spans(narrowed, catalogue, CALL).select)
                if row.b in rows
            }
            members = sorted(spans, key=lambda key: (spans[key][0], _order(key)))
            shown = members[:LANES]
            runs: dict[Value, list[Any]] = {key: [] for key in shown}
            waits: dict[Value, list[Wait]] = {key: [] for key in shown}
            events: dict[Value, list[LaneEvent]] = {key: [] for key in shown}
            colored = run_dimension(found, catalogue)
            if shown:
                laned = replace(narrowed, rows=tuple(shown))
                for row in db.execute(
                    statement.runs(laned, catalogue, CALL, colored, WAIT).select
                ):
                    runs[row.b].append(row)
                for row in db.execute(
                    statement.waits(laned, catalogue, CALL, WAIT).select
                ):
                    waits[row.b].append(_wait(row))
                if catalogue.offered(EVENT_KIND)[0] in catalogue.offered(found.by):
                    for row in db.execute(statement.happened(laned, catalogue).select):
                        events[row.b].append(_event(row))
        names = {
            value.code: value.name
            for value in catalogue.dimension(EVENT_KIND).values or ()
        }
        totals: dict[str, int] = {}
        errors: set[str] = set()
        for held in events.values():
            for event in held:
                totals[event.kind] = totals.get(event.kind, 0) + 1
                if event.is_error:
                    errors.add(event.kind)
        run_color, places = _run_color(colored, runs)
        laid = {key: _runs_of(held, places) for key, held in runs.items()}
        starts_at = min((spans[key][0] for key in shown), default=None)
        ends_at = max((spans[key][1] for key in shown), default=None)
        resolution, waits, events, laid = merged(
            waits, events, laid, starts_at, ends_at
        )
        return Lanes(
            address=view.address,
            zone=catalogue.zone,
            window=found.window,
            by=catalogue.dimension(found.by),
            measures=shaped.measures,
            color=shaped.color,
            all=shaped.all,
            lanes=tuple(
                Lane(
                    **{
                        name: getattr(rows[key], name)
                        for name in ByRow.__dataclass_fields__
                    },
                    starts_at=spans[key][0],
                    ends_at=spans[key][1],
                    runs=tuple(laid[key]),
                    waits=tuple(waits[key]),
                    events=tuple(events[key]),
                )
                for key in shown
            ),
            run_color=run_color,
            total_lanes=len(members),
            starts_at=starts_at,
            ends_at=ends_at,
            weeks=tuple(
                week.starts_at
                for week in view.weeks
                if starts_at is not None
                and ends_at is not None
                and starts_at < week.starts_at <= ends_at
            ),
            kinds=seen_kinds(totals, errors, names),
            wait_seconds=WAIT,
            resolution=resolution,
        )


def run_dimension(found: Plan, catalogue: Catalogue) -> Dimension:
    """What the lanes' runs are colored by: the view's color where it names
    one the Calls carry, else the Segment's kind."""
    color = found.color
    if color is not None and color != TOKEN_KIND and CALL in catalogue.offered(color):
        return catalogue.dimension(color)
    return catalogue.dimension(SEGMENT_KIND)


def merged(
    waits: dict[Value, list[Wait]],
    events: dict[Value, list[LaneEvent]],
    runs: dict[Value, list[Run]],
    starts_at: datetime | None,
    ends_at: datetime | None,
) -> tuple[
    float | None,
    dict[Value, list[Wait]],
    dict[Value, list[LaneEvent]],
    dict[Value, list[Run]],
]:
    """The lanes' waits, events and runs, merged where they are more than
    `MARKS` in all, with the resolution they were merged at, none where they
    were not."""

    def count(*marks: dict[Value, list[Any]]) -> int:
        return sum(len(held) for each in marks for held in each.values())

    if count(waits, events, runs) <= MARKS or starts_at is None or ends_at is None:
        return None, waits, events, runs
    span = (ends_at - starts_at).total_seconds()
    if span <= 0:
        return None, waits, events, runs
    resolution = span / RESOLUTION
    while True:
        joined = {key: _waits(held, resolution) for key, held in waits.items()}
        folded = {key: _events(held, resolution) for key, held in events.items()}
        ran = {key: _runs(held, resolution) for key, held in runs.items()}
        if count(joined, folded, ran) <= MARKS or resolution >= span:
            return resolution, joined, folded, ran
        resolution *= 2


def _runs(runs: Sequence[Run], resolution: float) -> list[Run]:
    joined: list[Run] = []
    for run in runs:
        last = joined[-1] if joined else None
        if (
            last is not None
            and last.ends_at == run.starts_at
            and (
                _length(last) < resolution
                or _length(run) < resolution
                or (last.color, last.conversation) == (run.color, run.conversation)
            )
        ):
            costlier = run if (run.cost or 0.0) > (last.cost or 0.0) else last
            joined[-1] = replace(
                costlier,
                starts_at=last.starts_at,
                ends_at=run.ends_at,
                n=last.n + run.n,
                cost=_added(last.cost, run.cost),
            )
        else:
            joined.append(run)
    return joined


def _length(run: Run) -> float:
    return (run.ends_at - run.starts_at).total_seconds()


def _added(first: float | None, second: float | None) -> float | None:
    if first is None and second is None:
        return None
    return (first or 0.0) + (second or 0.0)


def _waits(waits: Sequence[Wait], resolution: float) -> list[Wait]:
    joined: list[Wait] = []
    for wait in waits:
        last = joined[-1] if joined else None
        if (
            last is not None
            and (wait.starts_at - last.ends_at).total_seconds() < resolution
        ):
            joined[-1] = replace(
                wait,
                starts_at=last.starts_at,
                past_ttl=last.past_ttl or wait.past_ttl,
                n=last.n + wait.n,
            )
        else:
            joined.append(wait)
    return joined


def _events(events: Sequence[LaneEvent], resolution: float) -> list[LaneEvent]:
    """The events folded by kind, each merged event's cost that of the
    Calls it is held on, each Call's once however many of its events it
    holds."""
    folded: list[LaneEvent] = []
    last: dict[str, int] = {}
    previous: dict[str, datetime] = {}
    calls: dict[int, set[int]] = {}
    for event in events:
        at = last.get(event.kind)
        if (
            at is not None
            and (event.at - previous[event.kind]).total_seconds() < resolution
        ):
            run = folded[at]
            cost = run.cost
            if event.call not in calls[at]:
                calls[at].add(event.call)
                cost = (
                    None
                    if run.cost is None and event.cost is None
                    else (run.cost or 0.0) + (event.cost or 0.0)
                )
            folded[at] = replace(run, n=run.n + event.n, cost=cost, detail=None)
        else:
            last[event.kind] = len(folded)
            calls[len(folded)] = {event.call}
            folded.append(event)
        previous[event.kind] = event.at
    return folded


def _run_color(
    dimension: Dimension, runs: dict[Value, list[Any]]
) -> tuple[Color, dict[Value, int]]:
    """The runs' color, from the runs as the statement gives them, and each
    value's place among its values, a value folded the place of the one
    they are folded into."""
    totals: dict[Value, float | None] = {}
    names: dict[Value, Any] = {}
    for held in runs.values():
        for row in held:
            totals[row.v] = _added(totals.get(row.v), _number(row.cost))
            if "name" in row._fields:
                names[row.v] = row.name
    if dimension.key == SEGMENT_KIND:
        place = {
            value.code: index for index, value in enumerate(dimension.values or ())
        }
        kept = sorted(
            totals,
            key=lambda value: (
                value is None,
                place.get(str(value), len(place)),
                _order(value),
            ),
        )
        rest: list[Value] = []
    else:
        ordered = sorted(
            totals, key=lambda value: (-(totals[value] or 0.0), _order(value))
        )
        kept, rest = ordered[:COLORS], ordered[COLORS:]
        if len(rest) == 1:
            kept, rest = ordered, []
    values = [
        ColorValue(
            value, value_label(dimension, value, names.get(value)), totals[value]
        )
        for value in kept
    ]
    places = {value: index for index, value in enumerate(kept)}
    if rest:
        values.append(
            ColorValue(
                None,
                f"{len(rest)} other values",
                functools.reduce(_added, (totals[value] for value in rest)),
                others=len(rest),
            )
        )
        places |= dict.fromkeys(rest, len(kept))
    return Color(dimension.key, dimension.label, tuple(values)), places


def _runs_of(rows: Sequence[Any], places: dict[Value, int]) -> list[Run]:
    """A lane's runs from the statement's rows, in time order: each runs on
    to the next one's first moment, unless a wait opens that one."""
    return [
        Run(
            starts_at=row.first,
            ends_at=row.last if after is None or after.waited else after.first,
            color=places[row.v],
            conversation=row.transcript_id,
            n=row.n,
            cost=_number(row.cost),
        )
        for row, after in zip(rows, [*rows[1:], None], strict=True)
    ]


def _wait(row: Any) -> Wait:
    gap = (row.at - row.since).total_seconds()
    return Wait(
        starts_at=row.since,
        ends_at=row.at,
        conversation=row.transcript_id,
        call=row.call_id,
        past_ttl=bool(row.past_ttl)
        and row.waited_seconds is not None
        and row.waited_seconds >= gap - 1,
    )


def _event(row: Any) -> LaneEvent:
    return LaneEvent(
        at=row.at,
        kind=row.kind_code,
        is_error=row.is_error,
        key=event_key(row.kind_code, row.source_id),
        conversation=row.transcript_id,
        call=row.call_id,
        cost=_number(row.cost),
        detail=detail_of(row._mapping),
    )


def _number(value: Decimal | float | None) -> float | None:
    return None if value is None else float(value)


def _order(value: Value) -> tuple[bool, str]:
    return (value is None, "" if value is None else str(value))


def described(view: View, now: datetime) -> dict[str, Any] | None:
    """A view in lanes as the file of states holds its lanes: the fact a
    lane's rows are, the gap from which one is a wait, what its runs are
    colored by, and each read, its spans', its runs', its waits' and its
    events'; none for a view in another presentation."""
    state = view.address.state
    if state.presentation != "lanes":
        return None
    catalogue = view.catalogue
    found = plan(state, catalogue, view.weeks, now)
    colored = run_dimension(found, catalogue)
    return {
        "fact": CALL,
        "wait_seconds": WAIT,
        "run_color": colored.key,
        "spans": statement.read_described(statement.spans(found, catalogue, CALL)),
        "runs": statement.read_described(
            statement.runs(found, catalogue, CALL, colored, WAIT)
        ),
        "waits": statement.read_described(
            statement.waits(found, catalogue, CALL, WAIT)
        ),
        "events": statement.read_described(statement.happened(found, catalogue)),
    }
