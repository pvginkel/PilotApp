"""Schemas for GET /api/dashboard/catalogue, what a view of the dashboard may
name, a part at a call (F154.4), with what the dashboard stores (F155); for
GET /api/dashboard/address, a view's state checked and written back in its
normal form (F159); for GET /api/dashboard/rows, a view's rows (F154.1); for
GET /api/dashboard/series and its events strip, a view's series (F163.3,
F164.6); for GET /api/dashboard/lanes, a view's lanes (F164.6); and for GET
/api/dashboard/items and a conversation's calls, a view's items (F165).
"""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.task_schema import TaskStatus

CataloguePart = Literal["dimensions", "measures", "time", "stored"]
Group = Literal["part", "attribute", "time", "order"]
Format = Literal["usd", "tokens", "count", "seconds", "share"]
Origin = Literal["pilot", "workflow", "person"]
StoredOrigin = Literal["workflow", "person"]


class CatalogueQuerySchema(BaseModel):
    """The part of the catalogue asked for."""

    part: CataloguePart = Field(
        description=(
            "`dimensions`: what a view is By, filtered on and colored by; "
            "`measures`: the facts, the figures, the aggregates, the grains "
            "and the ratios; `time`: the time ranges, the zone and the "
            "sitting's gap; `stored`: the saved views, the system's and a "
            "person's, the quick filters and the stored ratios"
        )
    )


class ValueSchema(BaseModel):
    """One value of a dimension's closed list."""

    code: str = Field(description="What a state names it by", examples=["api_error"])
    name: str = Field(description="Its label", examples=["API error"])
    line: str | None = Field(description="What it is, where its source says")
    position: int | None = Field(
        description="Its place in its list, where its source gives one"
    )
    is_error: bool | None = Field(
        description="An event kind's alone: whether an event of it counts as an error"
    )


class DimensionSchema(BaseModel):
    """What a view is By, filtered on and colored by."""

    key: str = Field(description="What a state names it by", examples=["project"])
    label: str = Field(examples=["Project"])
    group: Group = Field(
        description=(
            "A part of the work, an attribute, a time, or a part along an order"
        )
    )
    line: str = Field(description="What it is")
    null: str = Field(
        description="The label of a row with none", examples=["(No project)"]
    )
    facts: list[str] = Field(
        description="The facts that offer it, by their keys", examples=[["call"]]
    )
    values: list[ValueSchema] | None = Field(
        description="Its closed list; null where its values are open"
    )
    one: str | None = Field(
        description="A part's alone: the noun of one item of it", examples=["project"]
    )
    many: str | None = Field(
        description="A part's alone: the noun of several", examples=["projects"]
    )
    next: str | None = Field(
        description="The dimension a click on its row moves the By to"
    )
    next_null: str | None = Field(
        description="The dimension a click on the row with none moves the By to"
    )
    base: str | None = Field(
        description="An order dimension's alone: the part it puts in order"
    )
    focus: bool = Field(
        description="A part's alone: whether a view is opened on one of its values, as `f=`"
    )
    unit: Literal["day", "quota_week"] | None = Field(
        description=(
            "A time dimension's alone: the span of time one of its values is; "
            "null where its values come round again, as a weekday's and an "
            "hour's do, and no time falls on one"
        )
    )


class MarkerSchema(BaseModel):
    """A kind of marker a series draws."""

    key: str = Field(
        description="What a state's `mk=` names it by", examples=["claude_code_version"]
    )
    label: str = Field(examples=["Claude Code version"])
    line: str = Field(description="What it marks")
    dimension: str = Field(
        description="The dimension a value of which, first seen, it marks"
    )


class FactSchema(BaseModel):
    """What a measure counts or sums."""

    key: str = Field(examples=["call"])
    label: str = Field(examples=["Calls"])
    counts: str = Field(description="The figure that counts its rows")
    grain: str = Field(description="The grain one row of it is")


class FigureSchema(BaseModel):
    """A number of one row of its fact."""

    key: str = Field(description="What a measure names it by", examples=["cost"])
    label: str = Field(examples=["Cost"])
    fact: str = Field(description="Its fact's key")
    line: str = Field(description="What it is")
    format: Format = Field(description="What its number is")
    aggregate: str = Field(description="The aggregate a measure of it takes by default")
    aggregates: list[str] = Field(description="The aggregates a measure of it takes")
    token_kinds: list[str] | None = Field(
        description="The Token Kinds it splits by; null where it counts no tokens"
    )
    stacks: bool = Field(description="Whether a color may stack it")


class AggregateSchema(BaseModel):
    """How a measure takes the items of its grain together."""

    key: str = Field(examples=["median"])
    label: str = Field(examples=["Median"])
    line: str = Field(description="What it is")


class GrainSchema(BaseModel):
    """What a measure's items are: a part, or a fact's own row."""

    key: str = Field(examples=["conversation"])
    one: str = Field(description="The noun of one item", examples=["conversation"])
    many: str = Field(description="The noun of several", examples=["conversations"])
    figures: list[str] = Field(description="The figures an item of it carries")
    shows: list[str] = Field(
        description="The dimensions shown with an item that is one row of a fact"
    )


class RatioSchema(BaseModel):
    """Two measures, the first over the second."""

    key: str = Field(description="What a measure names it by, after `r:`")
    label: str = Field(examples=["Cost per call"])
    line: str | None = Field(description="What it is, where its source says")
    format: Format
    origin: Literal["workflow", "person"] | None = Field(
        description=(
            "A stored ratio's: loaded with the workflow's views, which no one "
            "edits or removes, or a person's; null for a built-in one"
        )
    )
    numerator: str = Field(
        description="A measure, as a state writes it", examples=["cost.sum"]
    )
    denominator: str = Field(
        description="A measure, as a state writes it", examples=["calls.count"]
    )


class SavedViewSchema(BaseModel):
    """A view kept under a name, for everyone: a system view, Pilot's own or
    the workflow's, or one a person saved."""

    id: uuid.UUID
    system: bool = Field(
        description="Whether it is a system view, which no one renames, replaces or removes"
    )
    origin: Origin = Field(description="Where it comes from")
    key: str | None = Field(
        description="A system view's key in its source; null for a person's"
    )
    name: str = Field(
        description="Its name, unique among the system views and among the others",
        examples=["Projects"],
    )
    address: str = Field(
        description="Its state in its normal form after `#dash/`, as it was saved",
        examples=["#dash/t=all&by=project&m=cost.sum&col=work_type"],
    )
    note: str | None = Field(description="A line of explanation shown with it")
    saved_at: datetime = Field(description="When it was last saved, or loaded")


class QuickFilterSchema(BaseModel):
    """A filter kept under a label, for everyone, that a view turns on by its
    key in `b=`."""

    id: uuid.UUID
    key: str = Field(description="What `b=` names it by", examples=["misses"])
    label: str = Field(examples=["Cache misses"])
    condition: str = Field(
        description="The chip it applies, as a view's state writes it after `c=`",
        examples=["miss:1"],
    )
    marks: bool = Field(
        description="Whether it marks what the chip keeps rather than filters to it"
    )
    amount: str | None = Field(
        description="The figure shown beside its count; null for none",
        examples=["miss_cost"],
    )
    note: str | None = Field(description="A line of explanation shown with it")
    saved_at: datetime = Field(description="When it was made")
    offered: bool = Field(
        description=(
            "Whether the catalogue offers it: false where its chip or its amount "
            "names what is gone, so that `b=` naming it drops it with a note"
        )
    )


class CustomRatioSchema(BaseModel):
    """A ratio of two measures kept under a name, for everyone: loaded with the
    workflow's views, or made by a person."""

    id: uuid.UUID
    system: bool = Field(
        description="Whether it was loaded, which no one changes or removes"
    )
    origin: StoredOrigin = Field(description="Where it comes from")
    key: str = Field(
        description=(
            "What a measure names it by, after `r:`; a person's begins `person_`, "
            "made from its first name and kept"
        ),
        examples=["person_cost_per_turn"],
    )
    name: str = Field(
        description="Its name, unique among the loaded ones and among a person's",
        examples=["Cost per turn"],
    )
    numerator: str = Field(
        description="The measure above the line, as a state writes it",
        examples=["reported_cost.sum"],
    )
    denominator: str = Field(
        description="The measure below the line, as a state writes it",
        examples=["turns.count"],
    )
    note: str | None = Field(description="A line of explanation shown with it")
    saved_at: datetime = Field(description="When it was last saved, or loaded")
    offered: bool = Field(
        description=(
            "Whether the catalogue offers it among the ratios: false where a side "
            "names what is gone, or a loaded one has a built-in ratio's key"
        )
    )


class TimeRangeSchema(BaseModel):
    """A time range a state names by a key."""

    key: str = Field(examples=["d7"])
    label: str = Field(examples=["Last 7 days"])
    line: str = Field(description="What it holds")


class CatalogueResponseSchema(BaseModel):
    """One part of the catalogue: the fields of the part asked for are set,
    the others null."""

    part: CataloguePart
    dimensions: list[DimensionSchema] | None = Field(
        default=None,
        description="`dimensions`: every dimension, in the catalogue's order",
    )
    markers: list[MarkerSchema] | None = Field(
        default=None, description="`dimensions`: every kind of marker"
    )
    facts: list[FactSchema] | None = Field(default=None, description="`measures`")
    figures: list[FigureSchema] | None = Field(default=None, description="`measures`")
    aggregates: list[AggregateSchema] | None = Field(
        default=None, description="`measures`"
    )
    grains: list[GrainSchema] | None = Field(default=None, description="`measures`")
    ratios: list[RatioSchema] | None = Field(
        default=None,
        description="`measures`: the built-in ratios, then the stored ones",
    )
    ranges: list[TimeRangeSchema] | None = Field(default=None, description="`time`")
    zone: str | None = Field(
        default=None,
        description="`time`: the zone the day, the weekday and the hour are derived in",
        examples=["Europe/Amsterdam"],
    )
    sitting_gap_seconds: float | None = Field(
        default=None, description="`time`: the gap that ends a sitting, in seconds"
    )
    saved_views: list[SavedViewSchema] | None = Field(
        default=None,
        description=(
            "`stored`: the system views, then those a person saved, each list by name"
        ),
    )
    quick_filters: list[QuickFilterSchema] | None = Field(
        default=None,
        description="`stored`: every quick filter, in the order they were made",
    )
    custom_ratios: list[CustomRatioSchema] | None = Field(
        default=None,
        description=(
            "`stored`: every stored ratio, the loaded ones, then a person's, each "
            "list by name"
        ),
    )


class AddressQuerySchema(BaseModel):
    """A view's state to check."""

    state: str = Field(
        description=(
            "The view's state as the URL writes it after `#dash/`, `#dash/` "
            "before it or not; an entry, its focus alone (`f=<dimension>:<key>`), "
            "is filled in from the record"
        ),
        examples=["t=qw&by=project&m=cost.sum&col=none"],
    )
    fix_time: bool = Field(
        default=False,
        description=(
            "Write the time range as it stands now: a range of days as its two "
            "dates, a range of quota weeks as their keys"
        ),
    )


class AddressResponseSchema(BaseModel):
    """A view's state, read and checked."""

    address: str = Field(
        description="The view's address, its state in its normal form after `#dash/`",
        examples=["#dash/t=qw&by=project&m=cost.sum&col=none"],
    )
    look: list[str] = Field(
        description=(
            "Its look-only parts as the address writes them, which no answer "
            "of the engine reads"
        ),
        examples=[["rel=1"]],
    )
    notes: list[str] = Field(
        description="A note for each part it dropped, a quick filter or a ratio that is gone"
    )


Key = int | uuid.UUID | datetime | date | str | None
"""A value of a dimension, typed as its dimension reads it: a whole number,
an id, an instant, a date, a text; null for the row with none."""


class StateQuerySchema(BaseModel):
    """A view's state, as the URL writes it."""

    state: str = Field(
        description=(
            "The view's state as the URL writes it after `#dash/`, `#dash/` "
            "before it or not; an entry, its focus alone, is filled in from "
            "the record"
        ),
        examples=["t=qw&by=project&m=cost.sum&col=none"],
    )


class SpanSchema(BaseModel):
    """A span of the time a view reads, its end the instant before which it
    ends."""

    start: datetime | None = Field(description="Its start; null, open")
    end: datetime | None = Field(description="Its end, exclusive; null, open")


class RowsDimensionSchema(BaseModel):
    """The dimension the rows are By."""

    key: str = Field(examples=["project"])
    label: str = Field(examples=["Project"])
    group: Group


class StandInSchema(BaseModel):
    """The measure answered in a refused one's place."""

    key: str = Field(
        description="It as the view's normal form writes a measure",
        examples=["kind_cost.sum"],
    )
    label: str = Field(description="Its figure's label, or its ratio's")


class RowsMeasureSchema(BaseModel):
    """A measure as the rows answer it, in the view's order."""

    key: str = Field(
        description="The measure as the view's normal form writes it",
        examples=["cost.median.conversation"],
    )
    label: str = Field(description="Its figure's label, or its ratio's")
    format: Format = Field(description="The format of what is answered")
    aggregate: str | None = Field(description="Its aggregate; null for a ratio")
    grain: str | None = Field(
        description=(
            "The part its items are; null for its fact's own rows, and for a ratio"
        )
    )
    stacks: bool = Field(
        description="Whether it splits by the color, each row's `split` holding it"
    )
    refused: str | None = Field(
        description=(
            "Why the By refuses it, where it does: its values are its "
            "stand-in's, or null where none stands in"
        )
    )
    stand_in: StandInSchema | None = Field(
        description="The measure answered in its place, where it is refused"
    )
    median: float | None = Field(
        description=(
            "The median of its rows' values, the rows holding the focus left "
            "out: the peers' median"
        )
    )


class ColorValueSchema(BaseModel):
    """A value of the color."""

    key: Key = Field(
        description="The value, typed as its dimension reads it; null for none, or for the values folded"
    )
    label: str | None = Field(description="Its label; null where the key is its own")
    total: float | None = Field(
        description="The first stacked measure's amount on the All row"
    )
    others: int = Field(
        description="The count of values folded into it; 0 for a value of its own"
    )


class ColorSchema(BaseModel):
    """The color the stacked measures split by."""

    key: str = Field(description="A dimension's key, or `token_kind`")
    label: str
    values: list[ColorValueSchema] = Field(
        description=(
            "Its values, by the first stacked measure's amount, the largest "
            "first, or the token kinds in their order; empty where no measure "
            "stacks"
        )
    )


class LineSchema(BaseModel):
    """The All row: each measure's value, in the view's order."""

    values: list[float | None] = Field(
        description="Each measure's value; null where it has no item here"
    )
    n: list[int] = Field(description="Each measure's items with a value here")
    split: list[list[float] | None] | None = Field(
        description=(
            "With a color, each measure's amounts over the color's values, in "
            "their order; null for a measure that does not stack"
        )
    )
    marks: list[float | None] | None = Field(
        description=(
            "Where a chip marks values or each item, each measure's part on "
            "the rows it marks, 0 on a row not marked, the All row's the sum "
            "of its rows'; null for a measure that does not add up"
        )
    )


class ByRowSchema(LineSchema):
    """A row of the By."""

    key: Key = Field(description="The By's value, typed as the By reads it")
    label: str | None = Field(
        description="Its label; null where the key is its own, as a date or a time"
    )
    focus: bool = Field(description="Whether it holds the view's focus")
    marked: bool = Field(
        description=(
            "Whether every mark holds on it: each marked threshold, the "
            "outlier rows' chip where it marks, and a row a marked chip keeps"
        )
    )


class SortSchema(BaseModel):
    """The order of the rows."""

    direction: Literal["asc", "desc"]
    column: str = Field(
        description="A measure as the normal form writes it, or label, axis or n"
    )


class RowsResponseSchema(BaseModel):
    """A view's rows."""

    address: str = Field(
        description="The view's address, its state in its normal form after `#dash/`"
    )
    look: list[str] = Field(
        description="Its look-only parts as the address writes them"
    )
    notes: list[str] = Field(description="A note for each part it dropped")
    zone: str = Field(
        description="The zone the view's days, weekdays and hours are in",
        examples=["Europe/Amsterdam"],
    )
    window: list[SpanSchema] | None = Field(
        description="The time it reads; null for all time, empty for none of it"
    )
    by: RowsDimensionSchema
    measures: list[RowsMeasureSchema]
    color: ColorSchema | None
    all: LineSchema
    rows: list[ByRowSchema] = Field(
        description=(
            "The By's rows, in the sort: those a threshold or the outlier "
            "rows' chip keeps, where one does"
        )
    )
    total_rows: int = Field(description="The By's rows, those answered and the rest")
    sort: SortSchema


class RollSchema(BaseModel):
    """The rolling median's and its band's length."""

    read: int = Field(description="The values with one it reads", examples=[10])
    before: int = Field(
        description="The values with one before it that it draws from",
        examples=[15],
    )


class BandSchema(BaseModel):
    """The rolling quartiles at a point or a dot."""

    first: float
    median: float
    third: float


class DotSchema(BaseModel):
    """An item of a panel's grain in a point."""

    point: int = Field(description="The point's place among the points, from 0")
    key: Key = Field(description="The item, typed as its part reads it")
    label: str | None = Field(description="Its name; null where the key is its own")
    value: float = Field(description="Its figure in the point")
    at: datetime = Field(description="Its first moment in the point")
    focus: bool = Field(description="Whether it is the view's focus")


class PanelSchema(RowsMeasureSchema):
    """A measure as a series draws it, in the view's order; its `median` the
    points', or the dots', those holding the focus left out."""

    kind: Literal["column", "point", "items"] = Field(
        description=(
            "A column per point, a sum or a count, stacked by the color; the "
            "items' dots in each point, a measure over a part's items other "
            "than the points' own; else one dot at each point, a ratio among them"
        )
    )
    outliers: list[int] = Field(
        description="The places of its outlying points, or of its dots, from 0"
    )
    band: list[BandSchema | None] | None = Field(
        description=(
            "The band at each point, or each dot, null before it draws; null "
            "where it draws none"
        )
    )
    before: int = Field(
        description="The values before the range the band read before the first"
    )
    dots: list[DotSchema] | None = Field(
        description=(
            "Its items in each point, in the points' order, then by their first "
            "moments; null where it draws no dots"
        )
    )
    cut: bool = Field(description="Whether dots past those answered were left out")


class PointSchema(ByRowSchema):
    """A point of a series, a row of the dimension it asks."""

    axis: datetime | None = Field(
        description="In order, the member's place on its axis"
    )
    starts_at: datetime | None = Field(
        description="Over time by a span of time, the point's start"
    )
    ends_at: datetime | None = Field(
        description="Over time by a span of time, the point's end, exclusive"
    )


class SightingSchema(BaseModel):
    """A marker: where a value of its kind's dimension was first seen."""

    kind: str = Field(description="Its kind's key", examples=["claude_code_version"])
    value: Key = Field(description="The value first seen", examples=["2.1.318"])
    before: Key = Field(description="The value it followed", examples=["2.1.317"])
    at: datetime = Field(description="Its first moment")


class SeriesResponseSchema(BaseModel):
    """A view's series."""

    address: str = Field(
        description="The view's address, its state in its normal form after `#dash/`"
    )
    look: list[str] = Field(
        description="Its look-only parts as the address writes them"
    )
    notes: list[str] = Field(description="A note for each part it dropped")
    zone: str = Field(
        description="The zone the view's days, weekdays and hours are in",
        examples=["Europe/Amsterdam"],
    )
    window: list[SpanSchema] | None = Field(
        description="The time it reads; null for all time, empty for none of it"
    )
    presentation: Literal["order", "time"]
    by: RowsDimensionSchema = Field(
        description="The dimension it asks: in order its order dimension, over time its grain"
    )
    roll: RollSchema
    measures: list[PanelSchema]
    color: ColorSchema | None
    all: LineSchema
    points: list[PointSchema] = Field(
        description=(
            "The dimension's values in the order of the axis, the earliest "
            "first, those a threshold or the outlier rows' chip keeps"
        )
    )
    total_points: int = Field(description="The points, those answered and the rest")
    off_axis: ByRowSchema | None = Field(
        description="The row with none, which is no point"
    )
    markers: list[SightingSchema] = Field(
        description=(
            "Within the span of the axis, by kind, each in the order first seen"
        )
    )


class SeenKindSchema(BaseModel):
    """A kind of event the strip holds."""

    key: str = Field(examples=["api_error"])
    label: str = Field(examples=["API error"])
    is_error: bool = Field(description="Whether an event of it counts as an error")
    total: int = Field(description="Its events over every bucket")


class BucketSchema(BaseModel):
    """A point's events."""

    key: Key = Field(description="The point's key, typed as the dimension reads it")
    counts: list[int] = Field(description="Each kind's events, in the kinds' order")
    errors: int = Field(description="Its events that count as errors")


class StripResponseSchema(BaseModel):
    """A series' events strip."""

    address: str = Field(
        description="The view's address, its state in its normal form after `#dash/`"
    )
    look: list[str] = Field(
        description="Its look-only parts as the address writes them"
    )
    notes: list[str] = Field(description="A note for each part it dropped")
    zone: str = Field(examples=["Europe/Amsterdam"])
    window: list[SpanSchema] | None = Field(
        description="The time it reads; null for all time, empty for none of it"
    )
    by: RowsDimensionSchema = Field(description="The dimension the series asks")
    kinds: list[SeenKindSchema] = Field(
        description="The kinds it holds, the errors first, each group by its count"
    )
    buckets: list[BucketSchema] = Field(description="The points that hold an event")
    refused: str | None = Field(
        description="Why it holds none, where the events lack the dimension"
    )


class WaitSchema(BaseModel):
    """A gap between a lane's rows."""

    starts_at: datetime = Field(description="The moment of the row before it")
    ends_at: datetime = Field(description="The moment of the row that ends it")
    conversation: uuid.UUID | None = Field(
        description="The thread of the row that ends it; null for a Turn standing in"
    )
    call: int | None = Field(
        description="The Call that ends it; null for a Turn standing in"
    )
    past_ttl: bool = Field(
        description=(
            "Whether that Call waited past the cache's lifetime, its own wait "
            "spanning the gap"
        )
    )
    n: int = Field(description="The waits merged into it")


class EventDetailSchema(BaseModel):
    """An event's one short detail, from the fact behind it; each part null
    where its fact has none, as one not read yet."""

    qualifier: str | None = Field(
        description=(
            "A stored event's one qualifier as its source gives it: an API "
            "error's status"
        ),
        examples=["529"],
    )
    tool: str | None = Field(
        description="The tool whose output was saved, or whose use was denied",
        examples=["Bash"],
    )
    characters: int | None = Field(
        description="A saved output's full size, in characters", examples=[90000]
    )
    denial: str | None = Field(description="A denial's kind", examples=["rule"])
    command: str | None = Field(description="A failed hook's command")
    trigger: str | None = Field(description="A compaction's trigger", examples=["auto"])
    model: str | None = Field(
        description="A fallback's model: the one that answered in the asked one's place"
    )


class LaneEventSchema(BaseModel):
    """An event on a lane."""

    at: datetime
    kind: str = Field(examples=["api_error"])
    is_error: bool = Field(description="Whether its kind counts as an error")
    key: str = Field(
        description="Its key as an item: its kind and the id of the row that records it",
        examples=["api_error:12"],
    )
    conversation: uuid.UUID | None = Field(description="Its thread")
    call: int = Field(description="The Call it is held on")
    cost: float | None = Field(
        description="The cost of the Calls it is held on, a cache miss's its cost"
    )
    detail: EventDetailSchema | None = Field(
        description="Its detail; null where it holds more than one"
    )
    n: int = Field(description="The events of its kind merged into it")


class LaneSchema(ByRowSchema):
    """A lane: a row of the By that holds Calls in the window and the scope."""

    starts_at: datetime | None = Field(description="Its first row's moment")
    ends_at: datetime | None = Field(description="Its last row's moment")
    waits: list[WaitSchema] = Field(description="In time order")
    events: list[LaneEventSchema] = Field(description="In time order")


class LanesResponseSchema(BaseModel):
    """A view's lanes."""

    address: str = Field(
        description="The view's address, its state in its normal form after `#dash/`"
    )
    look: list[str] = Field(
        description="Its look-only parts as the address writes them"
    )
    notes: list[str] = Field(description="A note for each part it dropped")
    zone: str = Field(examples=["Europe/Amsterdam"])
    window: list[SpanSchema] | None = Field(
        description="The time it reads; null for all time, empty for none of it"
    )
    by: RowsDimensionSchema
    measures: list[RowsMeasureSchema]
    color: ColorSchema | None
    all: LineSchema
    lanes: list[LaneSchema] = Field(
        description=(
            "The By's rows that hold Calls, the earliest first, those a "
            "threshold or the outlier rows' chip keeps"
        )
    )
    total_lanes: int = Field(description="The lanes, those answered and the rest")
    starts_at: datetime | None = Field(description="The first lane's first moment")
    ends_at: datetime | None = Field(description="The lanes' last moment")
    weeks: list[datetime] = Field(
        description="The instants a quota week starts at within the span"
    )
    kinds: list[SeenKindSchema] = Field(
        description="The kinds of event the lanes hold, the errors first"
    )
    wait_seconds: float = Field(
        description="The gap between a lane's rows from which it is a wait"
    )
    resolution: float | None = Field(
        description=(
            "The seconds within which waits and events were merged, past the "
            "bound on how many the lanes carry; null where none were"
        )
    )


class ItemColumnSchema(BaseModel):
    """A figure an item carries."""

    key: str = Field(examples=["cost"])
    label: str = Field(examples=["Cost"])
    format: Format
    kinds: list[str] | None = Field(
        description="The token kinds it splits by, where it has them"
    )


class ShownSchema(BaseModel):
    """The value of a dimension shown with an item."""

    key: Key = Field(description="The value, typed as its dimension reads it")
    label: str | None = Field(description="Its label; null where the key is its own")


class ItemSchema(BaseModel):
    """An item."""

    key: Key = Field(
        description=(
            "The item, typed as its grain reads it: an event's key is its kind "
            "and the id of the row that records it; null on a Turn standing in "
            "for its Calls"
        )
    )
    label: str | None = Field(description="Its name; null where the key is its own")
    first: datetime | None = Field(description="Its first row's moment")
    last: datetime | None = Field(description="Its last row's moment")
    values: list[float | None] = Field(
        description="Each of the grain's figures, taken together over its rows"
    )
    kinds: list[list[float] | None] = Field(
        description="Each figure's split by its token kinds, null for one without"
    )
    shown: list[ShownSchema] = Field(
        description="Each dimension the grain shows, on an item that is one row"
    )
    focus: bool = Field(description="Whether it is the view's focus")
    conversation: uuid.UUID | None = Field(
        description="An item that is one row: its thread"
    )
    session: uuid.UUID | None = Field(
        description="An item that is one row: its Session of Pilot's"
    )
    turn_seq: int | None = Field(description="An item that is one row: its Turn")
    call: int | None = Field(description="An item that is one row: its Call")
    detail: EventDetailSchema | None = Field(description="An event's detail")


class SelectedSchema(BaseModel):
    """The row of the view the items are of."""

    key: Key = Field(description="Its key, null for the row with none")


class OpenedSchema(BaseModel):
    """The item whose calls the items are."""

    grain: str = Field(examples=["conversation"])
    key: Key


class ItemsResponseSchema(BaseModel):
    """A view's items."""

    address: str = Field(
        description="The view's address, its state in its normal form after `#dash/`"
    )
    look: list[str] = Field(
        description="Its look-only parts as the address writes them"
    )
    notes: list[str] = Field(description="A note for each part it dropped")
    zone: str = Field(examples=["Europe/Amsterdam"])
    window: list[SpanSchema] | None = Field(
        description="The time it reads; null for all time, empty for none of it"
    )
    grain: GrainSchema
    by: RowsDimensionSchema = Field(
        description="The dimension the view asks its rows by"
    )
    selected: SelectedSchema | None = Field(
        description="The row the items are of; null for every row"
    )
    opened: OpenedSchema | None = Field(
        description="The item whose calls they are, where one is opened"
    )
    figures: list[ItemColumnSchema] = Field(description="What each item carries")
    shows: list[RowsDimensionSchema] = Field(
        description="The dimensions shown with an item that is one row"
    )
    items: list[ItemSchema] = Field(description="The earliest first")
    total: int = Field(description="The items, those answered and the rest")


class CallEventSchema(BaseModel):
    """An event of a call."""

    key: str = Field(examples=["api_error:12"])
    kind: str = Field(examples=["api_error"])
    label: str = Field(examples=["API error"])
    is_error: bool
    at: datetime
    detail: EventDetailSchema


class CallSchema(ItemSchema):
    """A call of a conversation."""

    position: int | None = Field(description="Its place in its file, from 1")
    in_scope: bool = Field(description="Whether the view's window and scope hold it")
    events: list[CallEventSchema] = Field(description="In time order")


class CallsResponseSchema(BaseModel):
    """A conversation's calls over all time, with no chips."""

    address: str = Field(
        description="The view's address, its state in its normal form after `#dash/`"
    )
    look: list[str] = Field(
        description="Its look-only parts as the address writes them"
    )
    notes: list[str] = Field(description="A note for each part it dropped")
    zone: str = Field(examples=["Europe/Amsterdam"])
    window: list[SpanSchema] | None = Field(
        description="The time the view reads, which `in_scope` holds a call to"
    )
    conversation: uuid.UUID
    figures: list[ItemColumnSchema] = Field(description="What each call carries")
    shows: list[RowsDimensionSchema] = Field(
        description="The dimensions shown with each call"
    )
    calls: list[CallSchema] = Field(description="In their file's order")
    total: int = Field(description="The calls, those answered and the rest")


class CountsStartedSchema(BaseModel):
    """A task started that answers a view's counts over the stream the page
    holds, to the caller alone."""

    task_id: str = Field(description="The task, as its events name it")
    status: TaskStatus = Field(description="The task's status as it starts")
    address: str = Field(
        description="The view's address, its state in its normal form after `#dash/`"
    )
    look: list[str] = Field(
        description="Its look-only parts as the address writes them"
    )
    notes: list[str] = Field(description="A note for each part it dropped")


class AttributeCountSchema(BaseModel):
    """A dimension's count of values in a view's scope."""

    dimension: str = Field(description="The dimension's key", examples=["project"])
    count: int = Field(
        description=(
            "Its values in the scope under every chip, its own included, none "
            "counting as one; an order dimension its part's"
        )
    )


class AttributeCountsSchema(BaseModel):
    """By's counts of a view: the task's result, every dimension's in the
    catalogue's order, and each progress update's `data`, a fact's as they
    are counted."""

    counts: list[AttributeCountSchema]


class QuickFilterCountSchema(BaseModel):
    """A quick filter's count in a view's scope, under the quick filters
    that are on."""

    key: str = Field(description="The quick filter's key", examples=["misses"])
    count: int = Field(
        description=(
            "What it keeps: the rows of the fact its condition is on, the items "
            "of its grain among them, or the By's rows"
        )
    )
    amount: float | None = Field(
        description=(
            "Its figure's sum over what it keeps, 0 where nothing it keeps has "
            "the figure; null where it names none"
        )
    )


class QuickFilterCountsSchema(BaseModel):
    """The quick filters' counts and amounts of a view: the task's result,
    in the catalogue's order."""

    quick_filters: list[QuickFilterCountSchema]


class ValuesQuerySchema(StateQuerySchema):
    """A view's state, the attribute whose values are listed, and the words
    they are searched by."""

    dimension: str = Field(description="The attribute's key", examples=["project"])
    search: str | None = Field(
        None,
        description="Words a value's label or key holds, the case aside",
        examples=["recipe"],
    )


class AttributeValueSchema(BaseModel):
    """One value of an attribute in a view's scope."""

    key: Key = Field(description="The value, typed as its dimension reads it")
    label: str | None = Field(
        description="Its label; null where the key is its own, as a date or a time"
    )
    count: int = Field(description="The rows of its fact that hold it")
    cost: float | None = Field(
        description="Their cost; null where its fact has no cost"
    )


class ValuesResponseSchema(BaseModel):
    """An attribute's values in a view's scope, without its own chips."""

    address: str = Field(
        description="The view's address, its state in its normal form after `#dash/`"
    )
    look: list[str] = Field(
        description="Its look-only parts as the address writes them"
    )
    notes: list[str] = Field(description="A note for each part it dropped")
    zone: str = Field(examples=["Europe/Amsterdam"])
    dimension: RowsDimensionSchema
    values: list[AttributeValueSchema] = Field(
        description=(
            "The largest cost first, else the most rows, a time's in their "
            "order; at most 200"
        )
    )
    total: int = Field(
        description="The values the search keeps, those answered and the rest"
    )
