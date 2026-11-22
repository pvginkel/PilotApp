"""Schemas for /api/dashboard's writes of what the dashboard stores (F155):
the saved views, the quick filters and the custom ratios everyone shares, and
a person's favourites, their stars and their dimensions."""

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.dashboard import SavedViewSchema

VIEW_NAME = 80
"""The longest name of a saved view, as the screen's field takes it."""

NAME = 60
"""The longest name of a ratio, or label of a quick filter."""

NOTE = 200
"""The longest note shown with what is stored."""

ViewName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=VIEW_NAME)
]
Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME)
]
Note = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NOTE)
]
Menu = Literal["by", "color"]


class SaveViewSchema(BaseModel):
    """A view's whole state to save for everyone under a name."""

    name: ViewName = Field(
        description=(
            "Its name: a view a person saved under it is replaced; a system "
            "view's may be the same"
        ),
        examples=["Opus this week"],
    )
    state: str = Field(
        description=(
            "The view's state as the URL writes it after `#dash/`, `#dash/` "
            "before it or not; kept in its normal form"
        ),
        examples=["t=qw&by=project&m=cost.sum&c=model:claude-opus-5-5"],
    )
    note: Note | None = Field(
        default=None, description="A line of explanation shown with it"
    )


class SaveViewResponseSchema(BaseModel):
    """A view saved, and what of its state was dropped."""

    view: SavedViewSchema
    notes: list[str] = Field(
        description=(
            "One for each part of the state dropped: a quick filter or a ratio "
            "it named by a key that is gone"
        )
    )


class RenameViewSchema(BaseModel):
    """A saved view's new name."""

    name: ViewName = Field(
        description="Its new name, which no other view a person saved has",
        examples=["Opus last week"],
    )


class FavouritesSchema(BaseModel):
    """The signed-in person's favourites."""

    views: list[uuid.UUID] = Field(
        description="The views they starred, by their ids, in the order starred"
    )
    by: list[str] = Field(
        description="Their favourite dimensions in By's list, by key",
        examples=[["project", "model"]],
    )
    color: list[str] = Field(
        description="Their favourite colors in Color's list, by key",
        examples=[["work_type", "token_kind"]],
    )


class DimensionFavouriteSchema(BaseModel):
    """A dimension in one of the two lists, By's or Color's."""

    menu: Menu = Field(description="The list: By's or Color's")
    dimension: str = Field(
        min_length=1,
        description=(
            "The dimension's key; in Color's list a part's, an attribute's or "
            "`token_kind`"
        ),
        examples=["project"],
    )


class AddQuickFilterSchema(BaseModel):
    """A quick filter to make for everyone."""

    label: Name = Field(description="Its words", examples=["Opus only"])
    chip: str = Field(
        min_length=1,
        description=(
            "The chip it applies, as a view's state writes it after `c=`; one "
            "written to mark (`~` before it) makes a quick filter that marks"
        ),
        examples=["model:claude-opus-5-5"],
    )
    amount: str | None = Field(
        default=None,
        description="The figure whose sum shows beside its count; null for none",
        examples=["cost"],
    )
    note: Note | None = Field(
        default=None, description="A line of explanation shown with it"
    )


class CustomRatioWriteSchema(BaseModel):
    """A ratio a person makes or changes, for everyone."""

    name: Name = Field(
        description="Its name, which no other ratio a person made has",
        examples=["Cost per turn"],
    )
    numerator: str = Field(
        min_length=1,
        description="The measure above the line, as a state writes it after `m=`",
        examples=["reported_cost.sum"],
    )
    denominator: str = Field(
        min_length=1,
        description="The measure below the line, as a state writes it after `m=`",
        examples=["turns.count"],
    )
    note: Note | None = Field(
        default=None, description="A line of explanation shown with it"
    )
