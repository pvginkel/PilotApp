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

KEY = 60
"""The longest key of a view or a ratio of the workflow's file."""

MAX_LOADED = 200
"""The most views, and the most ratios, one load of the workflow's takes."""

LOADED_KEY = r"^[a-z][a-z0-9_]*$"
"""A key of the workflow's file: lower-case letters, digits and underscores,
a letter first, as a ratio's key stands after `r:` in a view's state."""

ONE_LINE = r"^[^\r\n]*$"
"""A loaded name, one line: the load's stand-in for a name it frees holds a
line break (`DashboardStoreService._load`)."""

LoadedKey = Annotated[str, StringConstraints(pattern=LOADED_KEY, max_length=KEY)]
LoadedViewName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=VIEW_NAME, pattern=ONE_LINE
    ),
]
LoadedRatioName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=NAME, pattern=ONE_LINE
    ),
]


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


class WorkflowViewSchema(BaseModel):
    """A view of the workflow's file."""

    key: LoadedKey = Field(
        description=(
            "The key the file names it by, which matches it to its system view "
            "at every load, so that a renamed one keeps its stars"
        ),
        examples=["errands"],
    )
    name: LoadedViewName = Field(
        description="Its name, one line, which no other system view has",
        examples=["Errands"],
    )
    state: str = Field(
        min_length=1,
        description=(
            "The view's state as the URL writes it after `#dash/`, `#dash/` "
            "before it or not; kept in its normal form. It may name a ratio of "
            "the same load by `r:<key>`"
        ),
        examples=["t=l8&by=project&m=cost.sum&m=r:per_serving&col=model"],
    )
    note: Note | None = Field(
        default=None, description="A line of explanation shown with it"
    )


class WorkflowRatioSchema(BaseModel):
    """A ratio of the workflow's file."""

    key: LoadedKey = Field(
        description=(
            "The key the file names it by, which a view's state names it by "
            "after `r:`: no built-in ratio's, and not beginning `person_`"
        ),
        examples=["per_serving"],
    )
    name: LoadedRatioName = Field(
        description="Its name, one line, which no other loaded ratio has",
        examples=["Cost per serving"],
    )
    numerator: str = Field(
        min_length=1,
        description="The measure above the line, as a state writes it after `m=`",
        examples=["cost.sum"],
    )
    denominator: str = Field(
        min_length=1,
        description="The measure below the line, as a state writes it after `m=`",
        examples=["calls.count"],
    )
    note: Note | None = Field(
        default=None, description="A line of explanation shown with it"
    )


class WorkflowLoadSchema(BaseModel):
    """The entries of the workflow's file of views and ratios, whole."""

    views: list[WorkflowViewSchema] = Field(
        max_length=MAX_LOADED,
        description="Every view of the file, each key once",
    )
    ratios: list[WorkflowRatioSchema] = Field(
        max_length=MAX_LOADED,
        description="Every ratio of the file, each key once",
    )


class LoadCountsSchema(BaseModel):
    """What a load wrote of one kind of row."""

    added: int = Field(description="The rows it added")
    changed: int = Field(description="The rows it changed in place")
    removed: int = Field(description="The rows it removed")


class WorkflowLoadedSchema(BaseModel):
    """What a load of the workflow's views and ratios wrote."""

    views: LoadCountsSchema
    ratios: LoadCountsSchema
    notes: list[str] = Field(
        description=(
            "One for each part of a view's state dropped, after the view it is "
            "in: a quick filter or a ratio it named by a key that is gone"
        )
    )
