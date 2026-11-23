"""The reader of a view's state (F154.1, F154.2): one path for the screen and
a tool alike. A state as the URL writes it is read part by part and checked
against the catalogue in every part; a state with faults is refused with
every fault at once (`StateRefusedException`), and one with none gives its
`State`, which `state.write` writes back in its normal form.

What a state names by key and is gone, a quick filter or a ratio, is dropped
with a note. What is no word of the language is a fault, and so is a part
the view cannot have, which the mockup's page settles silently: a
presentation its By lacks, a call selected outside the reader, values lit
with no color. A By that is a time or an order dimension is read as the
mockup reads it: over time at that grain, or its part in order.

A value is read by the type of its dimension's path: a whole number, an id,
a date, an instant with its zone, or a text; a dimension with a closed list
takes its codes alone, and the quota week the instant a week the record
holds starts at.
"""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Literal, cast

from sqlalchemy import Date, DateTime, Integer, Uuid

from app.dashboard.catalogue import COUNT, Catalogue, Dimension, Figure
from app.dashboard.refusal import Fault, listed, nearest, refused
from app.dashboard.state import (
    DIRECTIONS,
    DOTS,
    NO_COLOR,
    NULL,
    OPERATORS,
    OTHERS,
    OWN_COLUMNS,
    PARTS,
    PREFIX,
    PRESENTATIONS,
    REPEATED,
    SWITCHES,
    TOKEN_KIND,
    Between,
    Bound,
    Chip,
    Draw,
    Filter,
    Focus,
    Item,
    Level,
    Lit,
    Measure,
    OnItems,
    OnRows,
    Others,
    Outliers,
    Pin,
    Preset,
    RatioKey,
    Roll,
    Selected,
    Simple,
    Sort,
    State,
    Time,
    Value,
    Weeks,
    WrittenRatio,
    dec,
    instant,
    measure_key,
    write_value,
)
from app.services.quota_week_service import Period, label

WEEK = "qweek"
"""The dimension whose value is a quota week, by the instant it starts."""

EVENT_KIND = "event_kind"
"""The dimension whose values are the kinds of event a state draws."""

READER = "conversation"
"""The grain whose item opens in the reader, where a call is selected."""

TOP = "project"
"""The By of the parts' top level, under no drill level."""

Kind = Literal["integer", "id", "date", "instant", "text"]

_BOUND = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?")
_WHOLE = re.compile(r"-?\d+")
_LABEL = re.compile(r"(\d{4})-W(\d{2})")


@dataclass(frozen=True)
class Checked:
    """A state read and checked: what it means, and a note for each part
    it dropped."""

    state: State
    notes: tuple[str, ...]


@dataclass(frozen=True)
class _Part:
    at: int
    written: str
    key: str
    value: str


def split(written: str) -> list[tuple[str, str, str]]:
    """A state's parts as written, each with its key and its value; an
    address's `#dash/` before it read off."""
    if written.startswith(PREFIX):
        written = written[len(PREFIX) :]
    parts = []
    for part in written.split("&"):
        if part:
            key, _, value = part.partition("=")
            parts.append((part, key, value))
    return parts


def is_entry(written: str) -> bool:
    """Whether a state is an entry: its focus alone, which the app's way
    into the dashboard writes and the server fills in."""
    parts = split(written)
    return len(parts) == 1 and parts[0][1] == "f" and "=" in parts[0][0]


def read(written: str, catalogue: Catalogue, weeks: Sequence[Period]) -> Checked:
    """The state `written` means under `catalogue`, the quota weeks those the
    record holds in the order they start; `StateRefusedException` where it has a
    fault."""
    return _Reader(catalogue, weeks).read(written)


def read_simple(written: str, catalogue: Catalogue, weeks: Sequence[Period]) -> Simple:
    """One measure of a figure as a state writes it, a ratio's side among
    them; `StateRefusedException` where it has a fault."""
    reader = _Reader(catalogue, weeks)
    part = _Part(0, f"m={written}", "m", written)
    simple = reader.simple(part, written)
    reader.done()
    assert simple is not None
    return simple


def read_chip(written: str, catalogue: Catalogue, weeks: Sequence[Period]) -> Chip:
    """One chip as a state writes it, a quick filter's condition among them;
    `StateRefusedException` where it has a fault, a ratio by a key that is
    gone among them, since a chip alone has nothing to drop it from."""
    reader = _Reader(catalogue, weeks, alone=True)
    chip = reader.chip(_Part(0, f"c={written}", "c", written))
    reader.done()
    assert chip is not None
    return chip


class _Reader:
    def __init__(
        self, catalogue: Catalogue, weeks: Sequence[Period], alone: bool = False
    ) -> None:
        self.catalogue = catalogue
        self.alone = alone
        self.weeks = tuple(weeks)
        self.starts = {week.starts_at: week for week in self.weeks}
        self.dimensions = {
            dimension.key: dimension for dimension in catalogue.dimensions
        }
        self.figures = {figure.key: figure for figure in catalogue.figures}
        self.grains = {grain.key: grain for grain in catalogue.grains}
        self.faults: list[tuple[int, Fault]] = []
        self.notes: list[str] = []
        self.kinds: dict[str, Kind] = {}

    # ------------------------------------------------------------ faults

    def fault(
        self,
        part: _Part,
        wrong: str,
        near: Iterable[str] = (),
        allowed: str | None = None,
    ) -> None:
        self.faults.append(
            (part.at, Fault(part.written, part.key, wrong, tuple(near), allowed))
        )

    def done(self) -> None:
        if self.faults:
            ordered = sorted(self.faults, key=lambda fault: fault[0])
            raise refused([fault for _, fault in ordered])

    def decoded(self, part: _Part, written: str) -> str | None:
        try:
            return dec(written)
        except ValueError:
            self.fault(
                part,
                f'"{written}" holds a "%" that encodes no character',
                allowed="A value's reserved characters are percent-encoded, "
                "as in %2C for a comma",
            )
            return None

    # ------------------------------------------------------------ the state

    def read(self, written: str) -> Checked:
        parts = self.parts(written)
        one = {
            key: found[0]
            for key, found in parts.items()
            if key not in REPEATED and found
        }
        levels = tuple(
            level
            for part in parts.get("dr", [])
            if (level := self.level(part)) is not None
        )
        by, presentation, axis = self.presented(one, levels)
        measures, gone = self.measures(parts.get("m", []))
        state = State(
            time=(self.time(one["t"]) if "t" in one else None) or Preset("qw"),
            by=by,
            presentation=presentation,
            axis=axis,
            measures=measures,
            levels=levels,
            chips=tuple(
                chip
                for part in parts.get("c", [])
                if (chip := self.chip(part)) is not None
            ),
            quick_filters=self.quick_filters(one["b"]) if "b" in one else (),
            color=self.color(one["col"]) if "col" in one else None,
        )
        state = replace(
            state,
            sort=self.sort(one["o"], state.measures, gone) if "o" in one else None,
            drawer=self.drawer(one["d"]) if "d" in one else False,
            selected=self.selected(one["sel"], state) if "sel" in one else None,
            item_grain=self.grain_named(one["ig"]) if "ig" in one else None,
            item=self.item(one["it"]) if "it" in one else None,
            focus=self.focus(one["f"]) if "f" in one else None,
            relative=self.relative(one["rel"]) if "rel" in one else False,
            markers=self.markers(one["mk"]) if "mk" in one else None,
            draw=self.draw(one["dw"]) if "dw" in one else Draw(),
            roll=self.roll(one["roll"]) if "roll" in one else Roll(),
            lit=self.lit(one["lit"], state.color) if "lit" in one else None,
            events=self.events(one["ev"]) if "ev" in one else None,
            zoom=self.zoom(one["z"]) if "z" in one else None,
        )
        if "call" in one:
            state = replace(state, call=self.call(one["call"], state.item))
        self.done()
        return Checked(state, tuple(self.notes))

    def parts(self, written: str) -> dict[str, list[_Part]]:
        parts: dict[str, list[_Part]] = {}
        for at, (whole, key, value) in enumerate(split(written)):
            part = _Part(at, whole, key, value)
            if "=" not in whole:
                self.fault(
                    replace(part, key="part"),
                    f'"{whole}" has no "="',
                    allowed="A part reads <key>=<value>, as in by=project",
                )
            elif key not in PARTS:
                self.fault(
                    replace(part, key="part"),
                    f'"{key}" is no part of a state',
                    nearest(key, PARTS),
                )
            else:
                parts.setdefault(key, []).append(part)
        for key, found in parts.items():
            if key not in REPEATED and len(found) > 1:
                for part in found[1:]:
                    self.fault(
                        part,
                        f"{key} stands {len(found)} times, and a state has one",
                    )
        return parts

    # ------------------------------------------------------------ values

    def kind(self, dimension: Dimension) -> Kind:
        if dimension.key not in self.kinds:
            offered = self.catalogue.offered(dimension.key)
            found: Kind = "text"
            if offered:
                row = self.catalogue.row(self.catalogue.fact(offered[0]))
                written = dimension.path(row).type
                if isinstance(written, Integer):
                    found = "integer"
                elif isinstance(written, Uuid):
                    found = "id"
                elif isinstance(written, DateTime):
                    found = "instant"
                elif isinstance(written, Date):
                    found = "date"
            self.kinds[dimension.key] = found
        return self.kinds[dimension.key]

    def value(
        self, part: _Part, dimension: Dimension, written: str
    ) -> tuple[bool, Value]:
        """A value of `dimension` as written, and whether it reads."""
        if written == NULL:
            return True, None
        text = self.decoded(part, written)
        if text is None:
            return False, None
        kind = self.kind(dimension)
        if dimension.values is not None:
            codes = [value.code for value in dimension.values]
            if text not in codes:
                self.fault(
                    part,
                    f'"{text}" is no value of {dimension.key}',
                    _near_value(text, dimension),
                    _values_allowed(dimension.key, codes),
                )
                return False, None
            return True, int(text) if kind == "integer" else text
        if dimension.key == WEEK:
            week = self.week(part, text)
            return week is not None, week
        return self.typed(part, dimension.key, kind, text)

    def typed(self, part: _Part, key: str, kind: Kind, text: str) -> tuple[bool, Value]:
        if kind == "integer":
            if _WHOLE.fullmatch(text):
                return True, int(text)
            self.fault(part, f'{key} takes a whole number, not "{text}"')
        elif kind == "id":
            try:
                return True, uuid.UUID(text)
            except ValueError:
                self.fault(part, f'{key} takes an id, a UUID, not "{text}"')
        elif kind == "date":
            try:
                return True, date.fromisoformat(text)
            except ValueError:
                self.fault(part, f'{key} takes a date, YYYY-MM-DD, not "{text}"')
        elif kind == "instant":
            moment = _instant(text)
            if moment is not None:
                return True, moment
            self.fault(
                part,
                f"{key} takes an instant with its offset, as in "
                f'2026-11-19T10:00:00Z, not "{text}"',
            )
        else:
            return True, text
        return False, None

    def week(self, part: _Part, text: str) -> datetime | None:
        moment = _instant(text)
        if moment is not None and moment in self.starts:
            return moment
        near: list[str] = []
        labelled = _LABEL.fullmatch(text)
        if labelled:
            named = (int(labelled[1]), int(labelled[2]))
            near = [
                instant(week.starts_at)
                for week in self.weeks
                if label(week.starts_at, week.ends_at) == named
            ]
            wrong = (
                f'"{text}" is a quota week\'s label, which two weeks may share, '
                "not its key"
            )
        else:
            if moment is not None:
                near = [
                    instant(week.starts_at)
                    for week in self.weeks
                    if week.starts_at <= moment < week.ends_at
                ]
            wrong = f'"{text}" is no quota week\'s key'
        example = instant(self.weeks[0].starts_at) if self.weeks else None
        self.fault(
            part,
            wrong,
            near,
            "A quota week's key is the instant it starts"
            + (f", as in {example}" if example else ""),
        )
        return None

    # ------------------------------------------------------------ time

    def time(self, part: _Part) -> Time | None:
        head, *rest = part.value.split(",")
        if head == "wk":
            starts = []
            for written in rest:
                text = self.decoded(part, written)
                if text is not None and (week := self.week(part, text)) is not None:
                    starts.append(week)
            if not rest:
                self.fault(part, "wk names no quota week")
            return Weeks(tuple(sorted(set(starts))))
        if head == "c":
            if len(rest) != 2:
                self.fault(part, "c takes two bounds, its start and its end")
                return None
            (read_start, start), (read_end, end) = (
                self.bound(part, written) for written in rest
            )
            if not any(rest):
                self.fault(part, "c names neither a start nor an end")
            elif start is not None and end is not None and _start(start) >= _end(end):
                self.fault(part, "the range ends before it starts")
            if not (read_start and read_end):
                return None
            return Between(start, end)
        keys = [time_range.key for time_range in self.catalogue.ranges]
        if head not in keys or rest:
            self.fault(
                part,
                f'"{part.value}" is no time range',
                nearest(part.value, keys),
                f"A range is {listed(keys, 'or')}",
            )
            return None
        return Preset(head)

    def bound(self, part: _Part, written: str) -> tuple[bool, Bound | None]:
        """A bound as written, none where it is left open, and whether it
        reads."""
        text = self.decoded(part, written)
        if text is None:
            return False, None
        if not text:
            return True, None
        if _BOUND.fullmatch(text):
            try:
                if len(text) == 10:
                    return True, date.fromisoformat(text)
                return True, datetime.fromisoformat(text.replace(" ", "T"))
            except ValueError:
                pass
        self.fault(
            part,
            f'"{text}" is no date or time',
            allowed="A bound reads YYYY-MM-DD, or YYYY-MM-DDTHH:MM[:SS] with a "
            f"time of day, in {self.catalogue.zone}",
        )
        return False, None

    # ------------------------------------------------------------ By and presentation

    def presented(
        self, one: dict[str, _Part], levels: tuple[Level, ...]
    ) -> tuple[str, Literal["rows", "order", "time", "lanes", "table"], str | None]:
        by = TOP
        presentation = "rows"
        axis: str | None = None
        if "by" in one:
            part = one["by"]
            dimension = self.dimensions.get(part.value)
            if dimension is None:
                self.fault(
                    part,
                    f'"{part.value}" is no dimension',
                    nearest(part.value, self.dimensions),
                    "By takes a part or an attribute; the catalogue's dimensions "
                    "list them",
                )
            elif dimension.group == "time":
                by, presentation, axis = self.under(levels), "time", dimension.key
            elif dimension.group == "order":
                assert dimension.base is not None
                by, presentation, axis = dimension.base, "order", dimension.key
            else:
                by = dimension.key
        if "p" in one:
            presentation, axis = self.presentation(one["p"], by)
        elif presentation == "order":
            axis = self.order_axis(by, axis)
        return (
            by,
            cast(Literal["rows", "order", "time", "lanes", "table"], presentation),
            axis,
        )

    def under(self, levels: tuple[Level, ...]) -> str:
        """The By of the parts' level under the drill stack: the next level
        down from its last."""
        if not levels:
            return TOP
        last = levels[-1]
        dimension = self.dimensions[last.dimension]
        below = (
            dimension.next_null
            if last.value is None and dimension.next_null
            else dimension.next
        )
        return below or last.dimension

    def orders(self, by: str) -> list[str]:
        return [
            dimension.key
            for dimension in self.catalogue.dimensions
            if dimension.group == "order" and dimension.base == by
        ]

    def order_axis(self, by: str, axis: str | None) -> str | None:
        orders = self.orders(by)
        return None if not orders or orders[0] == axis else axis

    def presentation(self, part: _Part, by: str) -> tuple[str, str | None]:
        head, *rest = part.value.split(",")
        if head not in PRESENTATIONS:
            self.fault(
                part,
                f'"{head}" is no presentation',
                nearest(head, PRESENTATIONS),
                f"A presentation is {listed(PRESENTATIONS, 'or')}",
            )
            return "rows", None
        if len(rest) > (1 if head in ("order", "time") else 0):
            self.fault(part, f'"{part.value}" has more after {head} than it takes')
            return head, None
        axis = rest[0] if rest else None
        dimension = self.dimensions.get(by)
        if head == "lanes" and dimension is not None and dimension.group != "part":
            self.fault(
                part,
                f"{by} is no part, and a lane is a part's",
                allowed="Lanes take a By that is a part: "
                + listed(self.keys("part"), "or"),
            )
        if head == "order":
            orders = self.orders(by)
            if dimension is not None and not orders:
                bases = sorted(
                    {
                        base
                        for one in self.catalogue.dimensions
                        if (base := one.base) is not None
                    }
                )
                self.fault(
                    part,
                    f"{by} has no order",
                    allowed=f"In order takes a By that has one: {listed(bases, 'or')}",
                )
            elif axis is not None and orders and axis not in orders:
                self.fault(
                    part,
                    f'"{axis}" is no order of {by}',
                    nearest(axis, orders),
                    f"{by} is in order by {listed(orders, 'or')}",
                )
            return head, self.order_axis(by, axis)
        if head == "time":
            grains = self.keys("time")
            if axis is None:
                return head, grains[0]
            if axis not in grains:
                self.fault(
                    part,
                    f'"{axis}" is no time dimension',
                    nearest(axis, grains),
                    f"Over time takes {listed(grains, 'or')}",
                )
            return head, axis
        return head, None

    def keys(self, *groups: str) -> list[str]:
        return [
            dimension.key
            for dimension in self.catalogue.dimensions
            if dimension.group in groups
        ]

    def ask(self, state: State) -> Dimension | None:
        """The dimension the view asks its rows by: the By, its order
        dimension in order, the grain over time."""
        if state.presentation == "time" and state.axis is not None:
            return self.dimensions.get(state.axis)
        if state.presentation == "order":
            orders = self.orders(state.by)
            key = state.axis or (orders[0] if orders else state.by)
            return self.dimensions.get(key)
        return self.dimensions.get(state.by)

    # ------------------------------------------------------------ measures

    def measures(self, parts: list[_Part]) -> tuple[tuple[Measure, ...], set[str]]:
        measures: list[Measure] = []
        gone: set[str] = set()
        for part in parts:
            measure = self.measure(part, part.value, gone)
            if measure is not None:
                measures.append(measure)
        if parts and not measures and gone:
            self.notes.append(
                f"{parts[-1].written}: the view keeps no measure, so it takes "
                f"{measure_key(State().measures[0])}."
            )
        return tuple(measures) or State().measures, gone

    def measure(
        self, part: _Part, written: str, gone: set[str], dropped: str = "measure"
    ) -> Measure | None:
        """A measure, a ratio among them; one by a key that is gone added to
        `gone` and dropped with a note that names what is dropped with it."""
        if not written.startswith("r:"):
            return self.simple(part, written)
        rest = written[2:]
        name, colon, sides = rest.partition(":")
        if not colon:
            keys = [ratio.key for ratio in self.catalogue.ratios]
            if rest in keys:
                return RatioKey(rest)
            if not rest:
                self.fault(part, "r: names no ratio")
                return None
            near = nearest(rest, keys)
            if self.alone:
                self.fault(
                    part,
                    f'no ratio has the key "{rest}"',
                    near,
                    "The catalogue's measures list the ratios",
                )
                return None
            gone.add(written)
            self.notes.append(
                f'{part.written}: no ratio has the key "{rest}", so the {dropped} is '
                "dropped."
                + (
                    f" Did you mean {listed([f'"{key}"' for key in near], 'or')}?"
                    if near
                    else ""
                )
            )
            return None
        named = self.decoded(part, name)
        numerator, slash, denominator = sides.partition("/")
        if not slash or "/" in denominator:
            self.fault(
                part,
                "a ratio written out reads r:<name>:<measure>/<measure>",
            )
            return None
        top = self.simple(part, numerator)
        bottom = self.simple(part, denominator)
        if named is None or top is None or bottom is None:
            return None
        return WrittenRatio(named, top, bottom)

    def simple(self, part: _Part, written: str) -> Simple | None:
        head, bracket, inside = written.partition("(")
        if bracket and not inside.endswith(")"):
            self.fault(
                part, f'"{written}" opens a filter that does not close at its end'
            )
            return None
        pieces = head.split(".")
        if len(pieces) > 3 or not pieces[0]:
            self.fault(
                part,
                f'"{written}" is no measure',
                allowed="A measure reads <figure>.<aggregate>[.<grain>]",
            )
            return None
        figure = self.figures.get(pieces[0])
        if figure is None:
            self.fault(
                part,
                f'"{pieces[0]}" is no figure',
                nearest(pieces[0], self.figures),
                "The catalogue's measures list the figures",
            )
            return None
        aggregate = self.aggregate(part, figure, pieces[1] if len(pieces) > 1 else None)
        reached, grain = (
            self.grain(part, figure, pieces[2]) if len(pieces) > 2 else (True, None)
        )
        filters = (
            tuple(
                one
                for written_filter in inside[:-1].split(";")
                if written_filter
                and (one := self.filter(part, written_filter)) is not None
            )
            if bracket
            else ()
        )
        if aggregate is None or not reached:
            return None
        return Simple(figure.key, aggregate, grain, filters)

    def aggregate(self, part: _Part, figure: Figure, written: str | None) -> str | None:
        if written is None or written == "":
            return figure.aggregate
        known = [aggregate.key for aggregate in self.catalogue.aggregates]
        taken = list(self.catalogue.aggregates_of(figure))
        if written in taken:
            return written
        counting = self.catalogue.fact(figure.fact).counts
        allowed = f"{figure.key} takes {listed(taken)}" + (
            f", and {counting}.count counts its fact's items"
            if COUNT not in taken
            else ""
        )
        if written in known:
            self.fault(
                part,
                f"{written} counts a fact's items, on its counting figure alone",
                allowed=allowed,
            )
        else:
            self.fault(
                part, f'"{written}" is no aggregate', nearest(written, known), allowed
            )
        return None

    def grain(
        self, part: _Part, figure: Figure, written: str
    ) -> tuple[bool, str | None]:
        """The grain written, none where it is the figure's fact's own, and
        whether the figure reaches it."""
        fact = self.catalogue.fact(figure.fact)
        base = fact.part or fact.key
        reached = [
            grain
            for grain in self.grains
            if grain == fact.key
            or (grain in self.dimensions and fact.key in self.catalogue.offered(grain))
        ]
        if written not in self.grains:
            self.fault(
                part,
                f'"{written}" is no grain',
                nearest(written, self.grains),
                f"{figure.key} takes the grains {listed(reached)}",
            )
            return False, None
        if written not in reached:
            self.fault(
                part,
                f"{figure.key} is a figure of {fact.many}, which have no {written}",
                allowed=f"{figure.key} takes the grains {listed(reached)}",
            )
            return False, None
        return True, None if written == base else written

    def filter(self, part: _Part, written: str) -> Filter | None:
        negated = written.startswith("!")
        body = written[1:] if negated else written
        key, equals, values = body.partition("=")
        if not equals:
            self.fault(
                part,
                f'"{written}" is no filter',
                allowed="A measure's filter reads [!]<dimension>=<value>|<value>…",
            )
            return None
        dimension = self.filtered(part, key)
        if dimension is None:
            return None
        read = [self.value(part, dimension, value) for value in values.split("|")]
        if not all(ok for ok, _ in read):
            return None
        return Filter(dimension.key, tuple(value for _, value in read), negated)

    def filtered(self, part: _Part, key: str) -> Dimension | None:
        """The dimension a filter names: an order dimension's, its part."""
        dimension = self.dimensions.get(key)
        if dimension is None:
            self.fault(
                part,
                f'"{key}" is no dimension',
                nearest(key, self.dimensions),
                "The catalogue's dimensions list them",
            )
            return None
        if dimension.group == "order" and dimension.base is not None:
            return self.dimensions[dimension.base]
        return dimension

    # ------------------------------------------------------------ the scope

    def level(self, part: _Part) -> Level | None:
        key, colon, rest = part.value.partition(":")
        if not colon:
            self.fault(part, "a drill level reads <part>:<value>@<dimension>")
            return None
        value, at, drilled_from = (
            rest.rpartition("@") if "@" in rest else (rest, "", "")
        )
        dimension = self.dimensions.get(key)
        parts = self.keys("part")
        if dimension is None or dimension.group != "part":
            if dimension is None:
                self.fault(part, f'"{key}" is no dimension', nearest(key, parts))
            else:
                self.fault(
                    part,
                    f"{key} is no part, and a drill level is a part's value",
                    allowed=f"A filter on it is a chip, c={key}:<value>",
                )
            return None
        if at and drilled_from and drilled_from not in self.dimensions:
            self.fault(
                part,
                f'"{drilled_from}" is no dimension',
                nearest(drilled_from, self.dimensions),
            )
            return None
        ok, read = self.value(part, dimension, value)
        if not ok:
            return None
        return Level(dimension.key, read, drilled_from or None)

    def chip(self, part: _Part) -> Chip | None:
        written = part.value
        marked = negated = False
        while written[:1] in ("~", "!"):
            marked = marked or written[0] == "~"
            negated = negated or written[0] == "!"
            written = written[1:]
        if written.startswith("@"):
            return self.measured(part, written[1:], marked, negated)
        key, colon, values = written.partition(":")
        if not colon:
            self.fault(part, f'"{part.value}" is no chip')
            return None
        dimension = self.filtered(part, key)
        if dimension is None:
            return None
        read = [self.value(part, dimension, value) for value in values.split(",")]
        if not all(ok for ok, _ in read):
            return None
        return Pin(dimension.key, tuple(value for _, value in read), negated, marked)

    def measured(
        self, part: _Part, written: str, marked: bool, negated: bool
    ) -> Chip | None:
        kind, *rest = written.split(",")
        kinds = ("rows", "items", "outliers")
        if kind not in kinds:
            self.fault(
                part,
                f'"@{kind}" is no chip',
                ["@" + near for near in nearest(kind, kinds)],
            )
            return None
        if negated and kind != "items":
            self.fault(
                part,
                f"@{kind} keeps or marks the By's rows, and is never negated",
            )
            return None
        if kind == "outliers":
            if rest:
                self.fault(part, "@outliers takes nothing after it")
                return None
            return Outliers(marked)
        if len(rest) < 3:
            self.fault(part, f"@{kind} reads @{kind},<op>,<number>,<measure>")
            return None
        operator, written_number, *measure = rest
        if operator not in OPERATORS:
            self.fault(
                part,
                f'"{operator}" is no operator',
                nearest(operator, OPERATORS),
                f"An operator is {listed(OPERATORS, 'or')}",
            )
        threshold = _number(written_number)
        if threshold is None:
            self.fault(part, f'"{written_number}" is no number')
        written_measure = ",".join(measure)
        if kind == "rows":
            on_rows = self.measure(part, written_measure, set(), "chip")
            if operator not in OPERATORS or threshold is None or on_rows is None:
                return None
            return OnRows(operator, threshold, on_rows, marked)
        simple = self.simple(part, written_measure)
        if operator not in OPERATORS or threshold is None or simple is None:
            return None
        return OnItems(operator, threshold, simple, negated, marked)

    def quick_filters(self, part: _Part) -> tuple[str, ...]:
        keys = [quick_filter.key for quick_filter in self.catalogue.quick_filters]
        kept = []
        for written in part.value.split(","):
            key = self.decoded(part, written) if written else None
            if key is None:
                continue
            if key in keys:
                kept.append(key)
                continue
            near = nearest(key, keys)
            self.notes.append(
                f'{part.written}: no quick filter has the key "{key}", so it is '
                "dropped."
                + (
                    f" Did you mean {listed([f'"{one}"' for one in near], 'or')}?"
                    if near
                    else ""
                )
            )
        return tuple(sorted(set(kept)))

    def color(self, part: _Part) -> str | None:
        if part.value == NO_COLOR:
            return None
        if part.value == TOKEN_KIND:
            return TOKEN_KIND
        dimension = self.dimensions.get(part.value)
        offered = [*self.keys("part", "attribute"), TOKEN_KIND, NO_COLOR]
        if dimension is None or dimension.group not in ("part", "attribute"):
            self.fault(
                part,
                f'"{part.value}" is no color'
                + (f", being a {dimension.group} dimension" if dimension else ""),
                nearest(part.value, offered),
                "A color is a part, an attribute, token_kind or none",
            )
            return None
        return dimension.key

    def focus(self, part: _Part) -> Focus | None:
        key, colon, written = part.value.partition(":")
        foci = [
            dimension.key for dimension in self.catalogue.dimensions if dimension.focus
        ]
        if not colon:
            self.fault(part, "a focus reads <dimension>:<key>")
            return None
        dimension = self.dimensions.get(key)
        if dimension is None or not dimension.focus:
            self.fault(
                part,
                f'"{key}" is no focus',
                nearest(key, foci),
                f"A focus is {listed(foci, 'or')}",
            )
            return None
        if written == NULL:
            self.fault(part, f"a focus names one {dimension.one or key}, never none")
            return None
        ok, value = self.value(part, dimension, written)
        return Focus(dimension.key, value) if ok else None

    # ------------------------------------------------------------ the drawer

    def sort(
        self, part: _Part, measures: tuple[Measure, ...], gone: set[str]
    ) -> Sort | None:
        direction, comma, written = part.value.partition(",")
        if not comma:
            self.fault(part, "a sort reads <asc|desc>,<column>")
            return None
        column = self.decoded(part, written)
        if direction not in DIRECTIONS:
            self.fault(
                part,
                f'"{direction}" is no direction',
                nearest(direction, DIRECTIONS),
                "A sort is asc or desc",
            )
        if column is None:
            return None
        if column in gone:
            self.notes.append(
                f"{part.written}: the sort is on a measure dropped, so it is "
                "dropped too."
            )
            return None
        columns = [*OWN_COLUMNS, *(measure_key(measure) for measure in measures)]
        if column not in columns:
            quiet = _Reader(self.catalogue, self.weeks)
            read = quiet.measure(_Part(0, "", "m", column), column, set())
            if read is not None and not quiet.faults and measure_key(read) in columns:
                column = measure_key(read)
            else:
                self.fault(
                    part,
                    f'"{column}" is no column of the view',
                    nearest(column, columns),
                    f"Its columns are {listed(columns)}",
                )
                return None
        if direction not in DIRECTIONS:
            return None
        return Sort(cast(Literal["asc", "desc"], direction), column)

    def drawer(self, part: _Part) -> bool:
        if part.value != "items":
            self.fault(part, f'"{part.value}" is no drawer', allowed="d takes items")
        return True

    def selected(self, part: _Part, state: State) -> Selected | None:
        dimension = self.ask(state)
        if dimension is None:
            return None
        ok, value = self.value(part, dimension, part.value)
        return Selected(value) if ok else None

    def grain_named(self, part: _Part) -> str | None:
        if part.value in self.grains:
            return part.value
        self.fault(
            part,
            f'"{part.value}" is no grain',
            nearest(part.value, self.grains),
            f"A grain is {listed(list(self.grains), 'or')}",
        )
        return None

    def item(self, part: _Part) -> Item | None:
        grain, comma, written = part.value.partition(",")
        if not comma:
            self.fault(part, "an item reads <grain>,<its key>")
            return None
        if self.grain_named(replace(part, value=grain)) is None:
            return None
        dimension = self.dimensions.get(grain)
        if dimension is None:
            text = self.decoded(part, written)
            return Item(grain, text) if text is not None else None
        ok, value = self.value(part, dimension, written)
        return Item(grain, value) if ok else None

    def call(self, part: _Part, item: Item | None) -> int | None:
        if item is None or item.grain != READER:
            self.fault(
                part,
                "a call is selected in the reader, which a conversation's item opens",
                allowed="call takes it=conversation,<id> beside it",
            )
            return None
        ok, value = self.typed(part, "call", "integer", part.value)
        return value if ok and isinstance(value, int) else None

    # ------------------------------------------------------------ the look

    def relative(self, part: _Part) -> bool:
        if part.value not in ("0", "1"):
            self.fault(part, f'"{part.value}" is no switch', allowed="rel takes 1")
        return part.value == "1"

    def markers(self, part: _Part) -> tuple[str, ...]:
        if part.value == "none":
            return ()
        offered = [marker.key for marker in self.catalogue.markers]
        kinds = []
        for kind in part.value.split(","):
            if kind in offered:
                kinds.append(kind)
            elif kind:
                self.fault(
                    part,
                    f'"{kind}" is no kind of marker',
                    nearest(kind, offered),
                    f"A kind of marker is {listed(offered, 'or')}"
                    if offered
                    else "A kind of marker is the version of a component the "
                    "record holds, and it holds none",
                )
        return tuple(sorted(set(kinds)))

    def draw(self, part: _Part) -> Draw:
        dots: Literal["all", "out", "none"] | None = None
        switches = dict.fromkeys(SWITCHES, True)
        for written in part.value.split(","):
            name, _, setting = written.partition(":")
            if name == "dots" and setting in DOTS:
                dots = cast(Literal["all", "out", "none"], setting)
            elif name in SWITCHES and setting in ("on", "off"):
                switches[name] = setting == "on"
            elif name == "dots" or name in SWITCHES:
                allowed = listed(DOTS, "or") if name == "dots" else "on or off"
                self.fault(
                    part,
                    f'"{setting}" is no setting of {name}',
                    allowed=f"{name} takes {allowed}",
                )
            else:
                self.fault(
                    part,
                    f'"{name}" is no part of what a series draws',
                    nearest(name, ("dots", *SWITCHES)),
                )
        return Draw(dots, switches["cols"], switches["med"], switches["band"])

    def roll(self, part: _Part) -> Roll:
        written = part.value.split(",")
        if len(written) == 2 and all(re.fullmatch(r"[1-9]\d*", one) for one in written):
            return Roll(int(written[0]), int(written[1]))
        self.fault(
            part,
            f'"{part.value}" is no length of the band',
            allowed="It takes two whole numbers above 0, the items it reads and "
            "the items before it draws",
        )
        return Roll()

    def lit(self, part: _Part, color: str | None) -> tuple[Lit, ...] | None:
        if color is None:
            self.fault(
                part,
                "lit lights the color's values, and the view has no color",
                allowed="It takes col=<dimension> or col=token_kind beside it",
            )
            return None
        lit: dict[str, Lit] = {}
        for written in part.value.split(","):
            if not written:
                continue
            text = self.decoded(part, written)
            if text is None:
                continue
            if text == Others.WRITTEN:
                lit[written] = OTHERS
            elif color == TOKEN_KIND:
                kinds = self.token_kinds()
                if text in kinds:
                    lit[written] = text
                else:
                    self.fault(
                        part,
                        f'"{text}" is no token kind',
                        nearest(text, kinds),
                        f"A token kind is {listed(kinds, 'or')}",
                    )
            else:
                ok, value = self.value(part, self.dimensions[color], written)
                if ok:
                    lit[write_value(value)] = value
        return tuple(lit[key] for key in sorted(lit)) or None

    def token_kinds(self) -> list[str]:
        return list(
            dict.fromkeys(
                kind
                for figure in self.catalogue.figures
                if figure.kinds is not None
                for kind in figure.kinds
            )
        )

    def events(self, part: _Part) -> tuple[tuple[str, bool], ...] | None:
        dimension = self.dimensions[EVENT_KIND]
        codes = [value.code for value in dimension.values or ()]
        drawn: dict[str, bool] = {}
        for written in part.value.split(","):
            if not written:
                continue
            off = written.startswith("-")
            kind = self.decoded(part, written[1:] if off else written)
            if kind is None:
                continue
            if kind not in codes:
                self.fault(
                    part,
                    f'"{kind}" is no kind of event',
                    _near_value(kind, dimension),
                    "The catalogue's dimensions list the values of event_kind",
                )
                continue
            drawn[kind] = not off
        return tuple(sorted(drawn.items())) or None

    def zoom(self, part: _Part) -> tuple[float, float] | None:
        match [_number(one) for one in part.value.split(",")]:
            case [float() as low, float() as high] if low < high:
                return low, high
        self.fault(
            part,
            f'"{part.value}" is no window',
            allowed="A window is two epoch seconds, the first the earlier",
        )
        return None


def _number(text: str) -> float | None:
    """A number as a state writes it, none where it is no finite one: the
    normal form writes no NaN or infinity."""
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _instant(text: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def _start(bound: Bound) -> datetime:
    if isinstance(bound, datetime):
        return bound
    return datetime.combine(bound, datetime.min.time())


def _end(bound: Bound) -> datetime:
    if isinstance(bound, datetime):
        return bound
    return datetime.combine(
        date.fromordinal(bound.toordinal() + 1), datetime.min.time()
    )


def _near_value(text: str, dimension: Dimension) -> tuple[str, ...]:
    """A closed list's codes nearest the text, by their codes or their
    names."""
    values = dimension.values or ()
    by_code = nearest(text, [value.code for value in values])
    by_name = nearest(text, [value.name for value in values])
    named = {value.name: value.code for value in values}
    return tuple(dict.fromkeys([*by_code, *(named[name] for name in by_name)]))[:3]


def _values_allowed(key: str, codes: Sequence[str]) -> str:
    if len(codes) <= 12:
        return f"The values of {key} are {listed(list(codes))}"
    return f"The catalogue's dimensions list the values of {key}"
