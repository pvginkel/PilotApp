"""Schemas for a page's beat (F147; DB 312)."""

import uuid

from pydantic import BaseModel, Field


class AppPageBeatSchema(BaseModel):
    """A page's beat: the project it shows."""

    project_id: uuid.UUID | None = Field(
        description=(
            "The project the page shows: its timeline, one of its documents or "
            "one of its tabs; null on any other page, the project list or the "
            "profile page"
        ),
    )


class AppPageSchema(BaseModel):
    """A page, as its first beat wrote it."""

    id: uuid.UUID = Field(
        description="The page's id, which it names in every beat after and in its away",
    )
