"""A view's lanes (F164.6, F164.8): the scope's calls on a clock axis, a lane
per member of the By, answered down the one path the rows take (`rows`),
the chips as they take them, with what a lane draws besides.

- A **lane** is a row of the By that holds Calls in the window and the
  scope, with every measure the rows answer on it, its first and last
  moment, its waits and its events, each in time order. The lanes are in
  the order they began, the earliest first, at most `LANES`, with the count
  of all. A threshold on the By's rows and the outlier rows' chip keep the
  lanes of the rows they keep.
- A **wait** is a gap of `WAIT` seconds or more between a lane's rows, from
  the one before it to the one that ends it, with that one's thread and
  Call; past the cache's lifetime where that Call waited past it, its own
  wait spanning the gap.
- An **event** is at its moment on its lane, with its key, its thread, the
  Call it is held on and that Call's cost, a cache miss's its cost, and its
  one short detail (D6).
- Past `MARKS` waits and events in all, each lane's are **merged** at a
  resolution of the whole span's, the span over `RESOLUTION`, doubled until
  they are within it (the mockup's `lanes`, "past MAX_SEGMENTS, abutting
  segments merge up to a resolution of the whole window"): two waits where
  less than the resolution lies between them, two events of a kind where
  less than it lies between the first of them and the next. A merged one
  says how many it holds, and an event that holds more than one no detail.
  The segments, runs of calls by what they did, are the labeller's (slice
  052's).
- The **kinds** are those the lanes hold, as the strip names them.
- Times are instants, which the page writes: the span, a lane's moments,
  each wait's and event's, and each quota week that starts within the span.
"""

from __future__ import annotations

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
from app.dashboard.catalogue import Dimension
from app.dashboard.facts import event_key
from app.dashboard.items import Detail, detail_of
from app.dashboard.planner import Window, plan
from app.dashboard.refusal import Fault, refused
from app.dashboard.rows import ByRow, Color, Line, Measure, answered
from app.dashboard.state import State, Value
from app.dashboard.strip import SeenKind, seen_kinds

CALL = "call"
"""The fact whose rows a lane is: the Calls, and the Turns standing in."""

LANES = 200
"""The lanes an answer carries at most, the earliest."""

WAIT = 60.0
"""The seconds between a lane's rows from which the gap is a wait."""

MARKS = 12_000
"""The waits and events the lanes carry in all before they are merged."""

RESOLUTION = 4_000
"""The parts of the whole span the first merge's resolution is one of."""


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
    waits: tuple[Wait, ...] = ()
    events: tuple[LaneEvent, ...] = ()


@dataclass(frozen=True)
class Lanes:
    """A view's lanes: `resolution` the merge's in seconds, none where
    nothing is merged; `weeks` the instants a quota week starts at within
    the span."""

    address: Address
    zone: str
    window: Window
    by: Dimension
    measures: tuple[Measure, ...]
    color: Color | None
    all: Line
    lanes: tuple[Lane, ...]
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
            waits: dict[Value, list[Wait]] = {key: [] for key in shown}
            events: dict[Value, list[LaneEvent]] = {key: [] for key in shown}
            if shown:
                laned = replace(narrowed, rows=tuple(shown))
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
        starts_at = min((spans[key][0] for key in shown), default=None)
        ends_at = max((spans[key][1] for key in shown), default=None)
        resolution, waits, events = merged(waits, events, starts_at, ends_at)
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
                    waits=tuple(waits[key]),
                    events=tuple(events[key]),
                )
                for key in shown
            ),
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


def merged(
    waits: dict[Value, list[Wait]],
    events: dict[Value, list[LaneEvent]],
    starts_at: datetime | None,
    ends_at: datetime | None,
) -> tuple[float | None, dict[Value, list[Wait]], dict[Value, list[LaneEvent]]]:
    """The lanes' waits and events, merged where they are more than `MARKS`
    in all, with the resolution they were merged at, none where they were
    not."""

    def count(
        waits: dict[Value, list[Wait]], events: dict[Value, list[LaneEvent]]
    ) -> int:
        return sum(map(len, waits.values())) + sum(map(len, events.values()))

    if count(waits, events) <= MARKS or starts_at is None or ends_at is None:
        return None, waits, events
    span = (ends_at - starts_at).total_seconds()
    if span <= 0:
        return None, waits, events
    resolution = span / RESOLUTION
    while True:
        joined = {key: _waits(held, resolution) for key, held in waits.items()}
        folded = {key: _events(held, resolution) for key, held in events.items()}
        if count(joined, folded) <= MARKS or resolution >= span:
            return resolution, joined, folded
        resolution *= 2


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
    folded: list[LaneEvent] = []
    last: dict[str, int] = {}
    previous: dict[str, datetime] = {}
    for event in events:
        at = last.get(event.kind)
        if (
            at is not None
            and (event.at - previous[event.kind]).total_seconds() < resolution
        ):
            run = folded[at]
            folded[at] = replace(
                run,
                n=run.n + event.n,
                cost=None
                if run.cost is None and event.cost is None
                else (run.cost or 0.0) + (event.cost or 0.0),
                detail=None,
            )
        else:
            last[event.kind] = len(folded)
            folded.append(event)
        previous[event.kind] = event.at
    return folded


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
    lane's rows are, the gap from which one is a wait, and each read, its
    spans', its waits' and its events'; none for a view in another
    presentation."""
    state = view.address.state
    if state.presentation != "lanes":
        return None
    catalogue = view.catalogue
    found = plan(state, catalogue, view.weeks, now)
    return {
        "fact": CALL,
        "wait_seconds": WAIT,
        "spans": statement.read_described(statement.spans(found, catalogue, CALL)),
        "waits": statement.read_described(
            statement.waits(found, catalogue, CALL, WAIT)
        ),
        "events": statement.read_described(statement.happened(found, catalogue)),
    }
