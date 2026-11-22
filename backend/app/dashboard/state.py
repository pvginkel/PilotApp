"""A view's state (F159): the view whole, as the URL carries it after
`#dash/`, in the grammar the mockup rules (`design/mockup/dashboard/state.js`)
and with what the record adds to it: the band's length (`roll`, F154.1), the
outlier rows' chip (`@outliers`), and a note for a quick filter or a ratio
named by a key that is gone (`reading`).

The state is a view's only form. The shapes here are its reading, which
`reading.read` gives after checking every part against the catalogue, and
`write` gives it back in its normal form, so that two spellings of one view
are one address:

    t=<range>|wk,<week's key>,…|c,<from>,<to>   by=<dimension>
    p=order[,<order dimension>]|time,<grain>|lanes|table     (rows: absent)
    m=<measure>, in order    dr=<level>, outermost first    c=<chip>, in order
    b=<quick filter>,…    col=<dimension>|token_kind|none    o=<dir>,<column>
    d=items    sel=<value>    ig=<grain>    it=<grain>,<key>    call=<call>
    f=<dimension>:<key>    rel=1    mk=<kind>,…|none    dw=<part>:<value>,…
    roll=<items read>,<items before it draws>    lit=<value>,…    ev=[-]<kind>,…
    z=<from>,<to>

    measure := <figure>.<aggregate>[.<grain>][(<filter>;…)] | r:<key>
               | r:<name>:<simple>/<simple>
    filter  := [!]<dimension>=<value>|<value>…
    level   := <part>:<value>[@<dimension drilled from>]
    chip    := [~][!]<dimension>:<value>,… | [~]@rows,<op>,<number>,<simple>
               | [~][!]@items,<op>,<number>,<simple> | [~]@outliers

A value is percent-encoded as `enc` writes it, and a bare `~` is none. A
week's key is the instant it starts; a bound of `c` a date or a time of day
in the catalogue's zone, a date-only end holding its day.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Literal
from urllib.parse import quote, unquote

PREFIX = "#dash/"
"""What an address carries before its state."""

NULL = "~"
"""A value of none, as a state writes it."""

TOKEN_KIND = "token_kind"
"""The color that splits a figure of tokens by its kinds."""

NO_COLOR = "none"

PRESENTATIONS = ("rows", "order", "time", "lanes", "table")
DOTS = ("all", "out", "none")
SWITCHES = ("cols", "med", "band")
"""The parts of what a series draws that are on unless turned off."""
OPERATORS = ("gt", "ge", "lt", "le")
DIRECTIONS = ("asc", "desc")
OWN_COLUMNS = ("label", "axis", "n")
"""The columns a sort names besides the view's measures: the By's own, its
place on an axis and the count of its items."""

PARTS = (
    "t",
    "by",
    "p",
    "m",
    "dr",
    "c",
    "b",
    "col",
    "o",
    "d",
    "sel",
    "ig",
    "it",
    "call",
    "f",
    "rel",
    "mk",
    "dw",
    "roll",
    "lit",
    "ev",
    "z",
)
"""A state's parts, in the order the normal form writes them."""

REPEATED = ("m", "dr", "c")
"""The parts a state holds more than once, each in its place."""

LOOK = ("d", "rel", "mk", "dw", "lit", "ev", "z")
"""The look-only parts: no answer of the engine reads them, so a change of
one changes only what the page draws of the answers it holds."""


def enc(value: object) -> str:
    """A value as a state writes it: percent-encoded as the mockup's page
    encodes it, `encodeURIComponent` with ! ' ( ) * ~ encoded too."""
    return quote(_text(value), safe="").replace("~", "%7E")


def write_value(value: Value) -> str:
    return NULL if value is None else enc(value)


def _text(value: object) -> str:
    if isinstance(value, datetime):
        return instant(value)
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def instant(moment: datetime) -> str:
    """An instant in UTC, its seconds always and their fraction where it has
    one: `2026-11-19T10:00:00Z`."""
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")


def dec(written: str) -> str:
    """A value as written, percent-decoded; `ValueError` where a `%` encodes
    no character, or the bytes no UTF-8 text."""
    if _ESCAPE.search(written):
        raise ValueError(written)
    return unquote(written, errors="strict")


Value = int | str | uuid.UUID | date | datetime | None
"""A dimension's value, typed as its path reads it: a whole number, a text,
an id, a date, an instant; none for the row with none."""


@dataclass(frozen=True)
class Preset:
    """A time range by its key in the catalogue."""

    key: str


@dataclass(frozen=True)
class Weeks:
    """Quota weeks, each by the instant it starts."""

    starts: tuple[datetime, ...]


Bound = date | datetime
"""A bound of a range between two times: a date, or a time of day with no
zone, both the catalogue's zone's."""


@dataclass(frozen=True)
class Between:
    """The time from one bound to the other, an end that is a date holding
    its day; none on a side, open there."""

    start: Bound | None
    end: Bound | None


Time = Preset | Weeks | Between


@dataclass(frozen=True)
class Filter:
    """A measure's own filter: a dimension's values, or all but them."""

    dimension: str
    values: tuple[Value, ...]
    negated: bool = False


@dataclass(frozen=True)
class Simple:
    """A figure under an aggregate, its items those of `grain`, none being
    its fact's own, and only the rows its filters keep."""

    figure: str
    aggregate: str
    grain: str | None = None
    filters: tuple[Filter, ...] = ()


@dataclass(frozen=True)
class RatioKey:
    """A ratio of the catalogue, built in or stored."""

    key: str


@dataclass(frozen=True)
class WrittenRatio:
    """A ratio written out in the state, with its name."""

    name: str
    numerator: Simple
    denominator: Simple


Measure = Simple | RatioKey | WrittenRatio


@dataclass(frozen=True)
class Level:
    """A level of the drill stack: a part's value, and the dimension asked
    on screen when it was drilled into, which a step back up restores."""

    dimension: str
    value: Value
    drilled_from: str | None = None


@dataclass(frozen=True)
class Pin:
    """A chip on a dimension's values: it keeps them, or all but them
    (`negated`), or marks them (`marked`)."""

    dimension: str
    values: tuple[Value, ...]
    negated: bool = False
    marked: bool = False


@dataclass(frozen=True)
class OnRows:
    """A threshold on the By's rows: those whose `measure` is past
    `number`, kept or marked."""

    operator: str
    number: float
    measure: Simple
    marked: bool = False


@dataclass(frozen=True)
class OnItems:
    """A condition on each item of the measure's grain."""

    operator: str
    number: float
    measure: Simple
    negated: bool = False
    marked: bool = False


@dataclass(frozen=True)
class Outliers:
    """The outlier rows' chip: the By's rows whose first measure is an
    outlier among them, kept or marked."""

    marked: bool = False


Chip = Pin | OnRows | OnItems | Outliers


@dataclass(frozen=True)
class Sort:
    direction: Literal["asc", "desc"]
    column: str


@dataclass(frozen=True)
class Selected:
    """The row of the By the drawer lists, `value` none for the row with
    none."""

    value: Value


@dataclass(frozen=True)
class Item:
    """An item the drawer opens: a conversation in the reader, another
    grain's its calls."""

    grain: str
    key: Value


@dataclass(frozen=True)
class Focus:
    """The piece of work the view is opened on."""

    dimension: str
    key: Value


@dataclass(frozen=True)
class Draw:
    """What a series draws besides its markers: `dots` none while they are
    automatic."""

    dots: Literal["all", "out", "none"] | None = None
    cols: bool = True
    med: bool = True
    band: bool = True


@dataclass(frozen=True)
class Roll:
    """The rolling median's and its band's length: the items it reads, and
    the items before it draws (F154.1)."""

    read: int = 10
    before: int = 15


@dataclass(frozen=True)
class Others:
    """The color's other values, as the legend lights them: `…`."""

    WRITTEN = "…"


OTHERS = Others()

Lit = Value | Others


@dataclass(frozen=True)
class State:
    """A view's whole state, every part as its reading gives it."""

    time: Time = Preset("qw")
    by: str = "project"
    presentation: Literal["rows", "order", "time", "lanes", "table"] = "rows"
    axis: str | None = None
    """In order, its order dimension where it is not the By's first; over
    time, its grain."""
    measures: tuple[Measure, ...] = (Simple("cost", "sum"),)
    levels: tuple[Level, ...] = ()
    chips: tuple[Chip, ...] = ()
    quick_filters: tuple[str, ...] = ()
    color: str | None = None
    sort: Sort | None = None
    drawer: bool = False
    selected: Selected | None = None
    item_grain: str | None = None
    item: Item | None = None
    call: int | None = None
    focus: Focus | None = None
    relative: bool = False
    markers: tuple[str, ...] | None = None
    """The kinds of marker shown, none being every kind."""
    draw: Draw = field(default_factory=Draw)
    roll: Roll = field(default_factory=Roll)
    lit: tuple[Lit, ...] | None = None
    """The color's values lit, none being all."""
    events: tuple[tuple[str, bool], ...] | None = None
    """The kinds of event drawn as they depart from the presentation's
    default, each with whether it is drawn; none, every kind at its
    default."""
    zoom: tuple[float, float] | None = None
    """The window of the lanes or of a series on a line, in epoch seconds."""


def simple_key(simple: Simple) -> str:
    """A measure of a figure as the normal form writes it."""
    grain = f".{simple.grain}" if simple.grain is not None else ""
    filters = ";".join(
        ("!" if one.negated else "")
        + one.dimension
        + "="
        + "|".join(write_value(value) for value in one.values)
        for one in simple.filters
    )
    return f"{simple.figure}.{simple.aggregate}{grain}" + (
        f"({filters})" if filters else ""
    )


def measure_key(measure: Measure) -> str:
    """A measure as the normal form writes it, and a sort names its column."""
    if isinstance(measure, RatioKey):
        return f"r:{measure.key}"
    if isinstance(measure, WrittenRatio):
        return (
            f"r:{enc(measure.name)}:{simple_key(measure.numerator)}"
            f"/{simple_key(measure.denominator)}"
        )
    return simple_key(measure)


def chip_key(chip: Chip) -> str:
    """A chip as the normal form writes it."""
    marked = "~" if chip.marked else ""
    if isinstance(chip, Outliers):
        return f"{marked}@outliers"
    if isinstance(chip, OnRows):
        return f"{marked}@rows,{chip.operator},{number(chip.number)},{simple_key(chip.measure)}"
    negated = "!" if chip.negated else ""
    if isinstance(chip, OnItems):
        return (
            f"{marked}{negated}@items,{chip.operator},{number(chip.number)},"
            f"{simple_key(chip.measure)}"
        )
    values = ",".join(write_value(value) for value in chip.values)
    return f"{marked}{negated}{chip.dimension}:{values}"


def number(value: float) -> str:
    """A number as the normal form writes it: a whole one without its
    fraction."""
    return str(int(value)) if value == int(value) else repr(value)


def bound(value: Bound | None) -> str:
    """A bound of a range as the normal form writes it, its seconds only
    where they are not zero."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        form = "%Y-%m-%dT%H:%M:%S" if value.second else "%Y-%m-%dT%H:%M"
        return enc(value.strftime(form))
    return enc(value.isoformat())


def _time(time: Time) -> str:
    if isinstance(time, Preset):
        return time.key
    if isinstance(time, Weeks):
        return ",".join(["wk", *(enc(start) for start in time.starts)])
    return f"c,{bound(time.start)},{bound(time.end)}"


def _parts(state: State) -> list[tuple[str, str]]:
    parts: list[tuple[str, str]] = [("t", _time(state.time)), ("by", state.by)]
    if state.presentation != "rows":
        axis = f",{state.axis}" if state.axis is not None else ""
        parts.append(("p", f"{state.presentation}{axis}"))
    parts += [("m", measure_key(measure)) for measure in state.measures]
    parts += [
        (
            "dr",
            f"{level.dimension}:{write_value(level.value)}"
            + (f"@{level.drilled_from}" if level.drilled_from else ""),
        )
        for level in state.levels
    ]
    parts += [("c", chip_key(chip)) for chip in state.chips]
    if state.quick_filters:
        parts.append(("b", ",".join(enc(key) for key in state.quick_filters)))
    parts.append(("col", state.color or NO_COLOR))
    if state.sort is not None:
        parts.append(("o", f"{state.sort.direction},{enc(state.sort.column)}"))
    if state.drawer:
        parts.append(("d", "items"))
    if state.selected is not None:
        parts.append(("sel", write_value(state.selected.value)))
    if state.item_grain is not None:
        parts.append(("ig", state.item_grain))
    if state.item is not None:
        parts.append(("it", f"{state.item.grain},{write_value(state.item.key)}"))
    if state.call is not None:
        parts.append(("call", str(state.call)))
    if state.focus is not None:
        parts.append(("f", f"{state.focus.dimension}:{write_value(state.focus.key)}"))
    if state.relative:
        parts.append(("rel", "1"))
    if state.markers is not None:
        parts.append(("mk", ",".join(state.markers) or "none"))
    draw = [f"dots:{state.draw.dots}"] if state.draw.dots else []
    draw += [f"{switch}:off" for switch in SWITCHES if not getattr(state.draw, switch)]
    if draw:
        parts.append(("dw", ",".join(draw)))
    if state.roll != Roll():
        parts.append(("roll", f"{state.roll.read},{state.roll.before}"))
    if state.lit is not None:
        parts.append(("lit", ",".join(_lit(value) for value in state.lit)))
    if state.events is not None:
        parts.append(
            (
                "ev",
                ",".join(
                    ("" if drawn else "-") + enc(kind) for kind, drawn in state.events
                ),
            )
        )
    if state.zoom is not None:
        parts.append(("z", f"{number(state.zoom[0])},{number(state.zoom[1])}"))
    return parts


def _lit(value: Lit) -> str:
    return enc(Others.WRITTEN) if isinstance(value, Others) else write_value(value)


def write(state: State) -> str:
    """The state in its normal form: each part in its place, each value as
    `enc` writes it, a part at its default left out but `t`, `by`, `m` and
    `col`."""
    return "&".join(f"{key}={value}" for key, value in _parts(state))


def look(state: State) -> tuple[str, ...]:
    """The state's look-only parts as its normal form writes them."""
    return tuple(f"{key}={value}" for key, value in _parts(state) if key in LOOK)
