"""A view's series (F154.1, F163.3, F164.2): a view in order or over time,
its rows those of the dimension it asks — in order the By's order dimension,
its members along their axis; over time the grain, the By playing no part —
answered down the one path the rows take (`rows`), the chips as they take
them, with what a series draws besides.

- The **points** are the dimension's values in the order of the axis: an
  order's members by their place, the earliest first; a time's by its key.
  The row of none is no point and is answered beside them. At most `ROWS`
  points are answered, the earliest, with the count of all.
- A **panel** is a measure as the series draws it: a sum or a count a column
  per point, stacked by the color; a measure over the items of a part other
  than the points' own the items' dots in each point, at most `DOTS`; any
  other, a ratio among them, one dot at each point.
- The **band** is the rolling median with its quartiles over the previous
  `Roll.read` values with one, drawn from the value with `Roll.before`
  values before it on: in order over the points, or the dots where the
  panel draws them; over time on a line over the dots alone; on a time whose
  values come round again, none. It reads first as many values before the
  range as it needs: the members whose place is before the window, or the
  items that started before it, each with its figure over all its rows,
  under the scope.
- The **outliers** are a panel's points, or its dots, by the screen's one
  rule (`outliers`), judged among the items of one role (F154.4): those
  whose rows share a role among the others of it, the rest together, and
  over time the points all together.
- A **marker** is where a value of a marker's dimension was first seen,
  under the scope over all time, each value after the first with the one it
  followed; or where a role's configuration changed as it ran, a Work
  Unit's model and effort, those of its first Call on a main thread, with
  those of the unit of the same role before it, at the unit's start, else
  its first Call's moment: those within the span of the axis, the latest
  `MARKERS` of each kind; none on a time whose values come round again.
- A panel's **median**, its dashed line, is that of its points or its dots,
  those holding the focus left out.
- Times are instants, which the page writes: a member's place, a week's or
  a day's span, a dot's and a marker's moment.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.dashboard import statements as statement
from app.dashboard.address import Address, AddressService, View
from app.dashboard.bounds import Bounds
from app.dashboard.catalogue import COUNT, Dimension, Marker
from app.dashboard.dimensions import ROLE
from app.dashboard.outliers import LEAST, outliers, quantile
from app.dashboard.planner import (
    Measured,
    Plan,
    Planned,
    PlannedRatio,
    Window,
    presentation,
    series_plan,
)
from app.dashboard.rows import (
    ROWS,
    ByRow,
    Color,
    Line,
    Measure,
    Rows,
    Shaper,
    answered,
    ran,
)
from app.dashboard.state import Roll, Sort, Value, measure_key
from app.dashboard.statements import Read, read_described
from app.dashboard.strip import strip_read

DOTS = 4_000
"""The dots a panel draws at most."""

MARKERS = 24
"""The markers of one kind a series answers at most, the latest."""

Kind = Literal["column", "point", "items"]


@dataclass(frozen=True)
class Band:
    """The rolling quartiles at a point or a dot."""

    first: float
    median: float
    third: float


@dataclass(frozen=True)
class Dot:
    """An item in a point: `point` the point's place among the points, its
    figure there, its first moment there, whether it is the focus, and the
    role its rows there share, none where they share none."""

    point: int
    key: Value
    label: str | None
    value: float
    at: datetime
    focus: bool
    role: str | None = None


@dataclass(frozen=True)
class Panel:
    """A measure as the series draws it: `outliers` the places of its
    outlying points, or dots; `band` the band at each, none where it draws
    none; `before` the values before the range it read first; `dots` its
    items in each point, where it draws them, and `cut` whether more were
    left out."""

    measure: Measure
    kind: Kind
    outliers: tuple[int, ...]
    band: tuple[Band | None, ...] | None
    before: int
    dots: tuple[Dot, ...] | None = None
    cut: bool = False


@dataclass(frozen=True)
class Point(ByRow):
    """A point: a row of the dimension asked, with its place on an order or
    its span of time."""

    axis: datetime | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None


@dataclass(frozen=True)
class Sighting:
    """A marker: where the value of its kind's dimension was first seen, and
    the value it followed."""

    kind: str
    value: Value
    before: Value
    at: datetime


@dataclass(frozen=True)
class Configuration:
    """The model and the effort a role ran with."""

    model: str
    effort: str | None


@dataclass(frozen=True)
class Shift:
    """A marker: where a role's configuration changed as it ran, at the
    start of the unit that ran on it, else its first Call's moment, and the
    one it followed."""

    kind: str
    role: str
    value: Configuration
    before: Configuration
    at: datetime


@dataclass(frozen=True)
class Series:
    """A view's series."""

    address: Address
    zone: str
    window: Window
    presentation: Literal["order", "time"]
    by: Dimension
    roll: Roll
    panels: tuple[Panel, ...]
    color: Color | None
    all: Line
    points: tuple[Point, ...]
    total_points: int
    off_axis: ByRow | None
    markers: tuple[Sighting | Shift, ...]


def kind(measured: Measured, by: Dimension) -> Kind:
    """How a series draws the measure By `by`."""
    if isinstance(measured, PlannedRatio):
        return "point"
    if measured.answered.aggregate in ("sum", COUNT):
        return "column"
    if measured.grain is None or measured.grain in (by.key, by.base):
        return "point"
    return "items"


def on_a_line(by: Dimension) -> bool:
    """Whether time falls on the axis: an order's, or a time's whose value
    is a span of it."""
    return by.group == "order" or by.unit is not None


def rolling(
    values: Sequence[float | None], roll: Roll, before: Sequence[float] = ()
) -> tuple[Band | None, ...]:
    """The band at each value in order: the quartiles of the previous
    `roll.read` values with one, `before` the values ahead of the first, and
    none where fewer than `roll.before` come before it."""
    seen = list(before)
    bands: list[Band | None] = []
    for value in values:
        if len(seen) >= roll.before:
            read = sorted(seen[-roll.read :])
            bands.append(
                Band(quantile(read, 0.25), quantile(read, 0.5), quantile(read, 0.75))
            )
        else:
            bands.append(None)
        if value is not None:
            seen.append(value)
    return tuple(bands)


def start_of(window: Window) -> datetime | None:
    """The instant the window starts at, none for all time, for none of it,
    and for a span open at its start."""
    if not window or any(start is None for start, _ in window):
        return None
    return min(start for start, _ in window if start is not None)


class SeriesService:
    """A view's series, from its state as the URL writes it."""

    def __init__(
        self, db: Session, address_service: AddressService, bounds: Bounds
    ) -> None:
        self.db = db
        self.address_service = address_service
        self.bounds = bounds

    def series(self, written: str, now: datetime | None = None) -> Series:
        """The series of the state `written`, its time as it stands at `now`.

        Raises:
            StateRefusedException: the state has a fault, or is not in order
                or over time
            QueryRefusedException: a statement passed the engine's bounds
        """
        view = self.address_service.view(written)
        state = view.address.state
        found = series_plan(state, view.catalogue, view.weeks, now or datetime.now(UTC))
        presented = presentation(state)
        with self.bounds.read(self.db, view.deadline) as db:
            return _Drawer(db, view, found).drawn(presented)


class _Drawer:
    def __init__(self, db: Session, view: View, found: Plan) -> None:
        self.db = db
        self.view = view
        self.catalogue = view.catalogue
        self.state = view.address.state
        self.plan = found
        self.by = self.catalogue.dimension(found.by)
        self.ends = {week.starts_at: week.ends_at for week in view.weeks}

    def drawn(self, presented: Literal["order", "time"]) -> Series:
        shaper, read = answered(self.db, self.plan, self.catalogue, self.view.address)
        rows = shaper.shaped(Sort("asc", "axis"), every=True)
        on = [row for row in rows.rows if row.key is not None]
        points = tuple(self.point(row, shaper) for row in on[:ROWS])
        start = start_of(self.plan.window) if on_a_line(self.by) else None
        members = self.members_before(start, read) if start is not None else {}
        roles = self.roles(points)
        panels = tuple(
            self.panel(index, measured, rows, points, start, members, roles)
            for index, measured in enumerate(self.plan.measures)
        )
        return Series(
            address=self.view.address,
            zone=self.catalogue.zone,
            window=self.plan.window,
            presentation=presented,
            by=self.by,
            roll=self.state.roll,
            panels=panels,
            color=rows.color,
            all=rows.all,
            points=points,
            total_points=len(on),
            off_axis=next((row for row in rows.rows if row.key is None), None),
            markers=self.markers(points),
        )

    # ------------------------------------------------------------ the points

    def point(self, row: ByRow, shaper: Shaper) -> Point:
        axis: datetime | None = None
        starts_at: datetime | None = None
        ends_at: datetime | None = None
        if self.by.group == "order":
            axis = shaper.rows[row.key].axis
        elif self.by.unit == "quota_week":
            assert isinstance(row.key, datetime)
            starts_at, ends_at = row.key, self.ends[row.key]
        elif self.by.unit == "day":
            assert isinstance(row.key, date)
            starts_at, ends_at = self.day(row.key), self.day(row.key + timedelta(1))
        return Point(
            values=row.values,
            n=row.n,
            split=row.split,
            marks=row.marks,
            key=row.key,
            label=row.label,
            focus=row.focus,
            marked=row.marked,
            axis=axis,
            starts_at=starts_at,
            ends_at=ends_at,
        )

    def day(self, day: date) -> datetime:
        zone = ZoneInfo(self.catalogue.zone)
        return datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC)

    # ------------------------------------------------------------ the panels

    def panel(
        self,
        index: int,
        measured: Measured,
        rows: Rows,
        points: Sequence[Point],
        start: datetime | None,
        members: Mapping[int, list[float]],
        roles: Sequence[str | None],
    ) -> Panel:
        drawn = kind(measured, self.by)
        measure = rows.measures[index]
        if drawn == "items" and isinstance(measured, Planned) and measured.answers:
            return self.items(measure, measured, points, start)
        values = [point.values[index] for point in points]
        before = members.get(index, [])
        return Panel(
            measure=replace(
                measure,
                median=_median(
                    value
                    for point, value in zip(points, values, strict=True)
                    if not point.focus
                ),
            ),
            kind=drawn,
            outliers=_outlying(values, roles),
            band=rolling(values, self.state.roll, before)
            if self.by.group == "order"
            else None,
            before=len(before),
        )

    def items(
        self,
        measure: Measure,
        planned: Planned,
        points: Sequence[Point],
        start: datetime | None,
    ) -> Panel:
        dots, cut = self.dots(planned, points)
        values = [dot.value for dot in dots]
        before = self.items_before(planned, start, dots) if start is not None else []
        return Panel(
            measure=replace(
                measure, median=_median(dot.value for dot in dots if not dot.focus)
            ),
            kind="items",
            outliers=_outlying(values, [dot.role for dot in dots]),
            band=rolling(values, self.state.roll, before)
            if on_a_line(self.by)
            else None,
            before=len(before),
            dots=dots,
            cut=cut,
        )

    def dots(
        self, planned: Planned, points: Sequence[Point]
    ) -> tuple[tuple[Dot, ...], bool]:
        if not points:
            return (), False
        place = {point.key: at for at, point in enumerate(points)}
        narrowed = replace(self.plan, rows=tuple(place), marks=())
        found = self.ran(
            statement.bucketed(narrowed, self.catalogue, planned, DOTS + 1)
        )
        focus = self.state.focus
        dots = tuple(
            Dot(
                point=place[row.b],
                key=row.item,
                label=row._mapping.get("name"),
                value=_number(row.v),
                at=row.at,
                focus=focus is not None
                and focus.dimension == planned.grain
                and row.item == focus.key,
                role=row._mapping.get("role"),
            )
            for row in found[:DOTS]
        )
        return dots, len(found) > DOTS

    def roles(self, points: Sequence[Point]) -> list[str | None]:
        """The role each point's rows share, read on the first fact a
        measure reads that offers the role; none for every point over time,
        a span of it being no item, where no fact offers the role, and
        where too few points stand for any to be an outlier."""
        offered = self.catalogue.offered(ROLE)
        fact = next(
            (
                planned.fact
                for planned in self.plan.simples
                if planned.answers and planned.fact in offered
            ),
            None,
        )
        if self.by.group != "order" or fact is None or len(points) < LEAST:
            return [None] * len(points)
        narrowed = replace(
            self.plan, rows=tuple(point.key for point in points), marks=()
        )
        shared = {
            row.b: row.role
            for row in self.ran(statement.roles(narrowed, self.catalogue, fact))
        }
        return [shared.get(point.key) for point in points]

    def items_before(
        self, planned: Planned, start: datetime, dots: Sequence[Dot]
    ) -> list[float]:
        found = self.ran(
            statement.items_before(
                self.plan,
                self.catalogue,
                planned,
                start,
                tuple(dict.fromkeys(dot.key for dot in dots)),
                self.reach(),
            )
        )
        return [_number(row.v) for row in reversed(found)]

    def members_before(
        self, start: datetime, read: Sequence[Value]
    ) -> dict[int, list[float]]:
        """Each panel's values of the members before the range, in their
        order on the axis, by the panel's place; none where no panel draws
        its band over the points."""
        if self.by.group != "order":
            return {}
        rolled = [
            index
            for index, measured in enumerate(self.plan.measures)
            if kind(measured, self.by) != "items"
        ]
        fact = next(
            (planned.fact for planned in self.plan.simples if planned.answers), None
        )
        if not rolled or fact is None:
            return {}
        keys = tuple(
            row.b
            for row in self.ran(
                statement.members_before(
                    self.plan,
                    self.catalogue,
                    fact,
                    start,
                    tuple(key for key in read if key is not None),
                    self.reach(),
                )
            )
        )
        if not keys:
            return {}
        warm = replace(
            self.plan, window=None, rows=keys, marks=(), thresholds=(), outliers=None
        )
        shaper = Shaper(self.catalogue, warm, self.view.address)
        shaper.take(ran(self.db, statement.statements(warm, self.catalogue)))
        members = sorted(shaper.rows.values(), key=lambda taken: taken.axis)
        return {
            index: [
                value
                for taken in members
                if (value := shaper.value(taken, warm.measures[index])[0]) is not None
            ]
            for index in rolled
        }

    def reach(self) -> int:
        """The values before the range the band reads at most."""
        return max(self.state.roll.read, self.state.roll.before)

    # ------------------------------------------------------------ the markers

    def markers(self, points: Sequence[Point]) -> tuple[Sighting | Shift, ...]:
        if not points or not on_a_line(self.by):
            return ()
        if self.by.group == "order":
            places = [point.axis for point in points if point.axis is not None]
        else:
            places = [
                moment
                for point in points
                for moment in (point.starts_at, point.ends_at)
                if moment is not None
            ]
        if not places:
            return ()
        low, high = min(places), max(places)
        found: list[Sighting | Shift] = []
        for marker in self.catalogue.markers:
            if marker.dimension is None:
                found += self.shifts(marker, low, high)
                continue
            if not self.catalogue.offered(marker.dimension):
                continue
            seen = sorted(
                self.ran(
                    statement.sightings(self.plan, self.catalogue, marker.dimension)
                ),
                key=lambda row: (row.at, str(row.v)),
            )
            changes = [
                Sighting(marker.key, row.v, previous.v, row.at)
                for previous, row in zip(seen, seen[1:], strict=False)
                if low <= row.at <= high
            ]
            found += changes[-MARKERS:]
        return tuple(found)

    def shifts(self, marker: Marker, low: datetime, high: datetime) -> list[Shift]:
        changed = [
            Shift(
                marker.key,
                row.role,
                Configuration(row.model, row.effort),
                Configuration(row.model_before, row.effort_before),
                row.at,
            )
            for row in self.ran(statement.shifts(self.plan, self.catalogue))
            if low <= row.at <= high
        ]
        return changed[-MARKERS:]

    def ran(self, read: Read) -> Sequence[Any]:
        return self.db.execute(read.select).all()


def _outlying(
    values: Sequence[float | None], roles: Sequence[str | None]
) -> tuple[int, ...]:
    """The places of the outlying values, each judged among the values of
    its role, those of none among each other."""
    among: dict[str | None, dict[int, float]] = {}
    for place, (value, role) in enumerate(zip(values, roles, strict=True)):
        if value is not None:
            among.setdefault(role, {})[place] = value
    return tuple(
        sorted(place for judged in among.values() for place in outliers(judged))
    )


def _median(values: Any) -> float | None:
    known = [value for value in values if value is not None]
    return statistics.median(known) if known else None


def _number(value: Decimal | float | int) -> float:
    return float(value)


def described(view: View, now: datetime) -> dict[str, Any] | None:
    """A view in order or over time as the file of states holds its series:
    the dimension asked, the band's length, each panel's drawing and what
    its band rolls over, the statements of its rows as `statements.described`
    gives them, the statements of its dots, its markers' kinds, each with the
    fact it reads, and its events strip's; none for a view with no series."""
    state = view.address.state
    if state.presentation not in ("order", "time"):
        return None
    found = series_plan(state, view.catalogue, view.weeks, now)
    catalogue = view.catalogue
    by = catalogue.dimension(found.by)
    panels = []
    dots = []
    for measured in found.measures:
        drawn = kind(measured, by)
        rolls: str | None = None
        if drawn == "items" and isinstance(measured, Planned) and measured.answers:
            dots.append(
                {
                    "measure": measure_key(measured.measure),
                    **read_described(
                        statement.bucketed(found, catalogue, measured, DOTS + 1)
                    ),
                    "items": measured.grain,
                }
            )
            rolls = "dots" if on_a_line(by) else None
        elif by.group == "order":
            rolls = "points"
        panels.append(
            {"measure": measure_key(measured.measure), "kind": drawn, "band": rolls}
        )
    entry: dict[str, Any] = {
        "by": found.by,
        "roll": [state.roll.read, state.roll.before],
        "panels": panels,
        "statements": statement.described(found, catalogue),
    }
    if dots:
        entry["dots"] = dots
    entry["markers"] = (
        [
            {
                "kind": marker.key,
                **read_described(
                    statement.shifts(found, catalogue)
                    if marker.dimension is None
                    else statement.sightings(found, catalogue, marker.dimension)
                ),
            }
            for marker in catalogue.markers
            if marker.dimension is None or catalogue.offered(marker.dimension)
        ]
        if on_a_line(by)
        else None
    )
    counted = strip_read(found, catalogue)
    entry["events"] = counted if isinstance(counted, str) else read_described(counted)
    return entry
