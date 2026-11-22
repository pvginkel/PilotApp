"""Schemas for GET /api/dashboard/catalogue, what a view of the dashboard may
name, a part at a call (F154.4), with what the dashboard stores (F155); and
for GET /api/dashboard/address, a view's state checked and written back in
its normal form (F159)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

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
