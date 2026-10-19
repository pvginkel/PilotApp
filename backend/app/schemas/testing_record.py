"""Schemas for the testing endpoints that make the record's states the UI
cannot make: people, environments and projects."""

import uuid

from pydantic import BaseModel, Field

from app.models.reference import ProjectState, TaskStatus


class InventedPersonCreateSchema(BaseModel):
    """A person put on the record as the handle step puts one, never signed in."""

    handle: str = Field(description="The person's handle", examples=["ben"])
    name: str | None = Field(
        default=None,
        description="The full name; the handle stands as the name when null",
        examples=["Ben Example"],
    )


class InventedPersonSchema(BaseModel):
    handle: str = Field(examples=["ben"])
    name: str = Field(examples=["Ben Example"])
    avatar_slot: int = Field(
        description="The palette slot the person took", examples=[2]
    )


class InventedEnvironmentSchema(BaseModel):
    """An environment of the record, by its KubeCoder id and its name."""

    id: str = Field(
        description="The KubeCoder environment id", examples=["example-env-1"]
    )
    name: str = Field(description="The environment's name", examples=["Example-1"])


class InventedNoteSchema(BaseModel):
    """An open note on a step or on the plan."""

    id: str = Field(examples=["card-layout"])
    summary: str = Field(examples=["Cards are one column"])
    content: str = Field(examples=["Ben chose one column."])


class InventedTaskSchema(BaseModel):
    """A step of the plan."""

    id: str = Field(examples=["build"])
    title: str = Field(examples=["Build the recipe card page"])
    status: TaskStatus
    notes: list[InventedNoteSchema] = Field(default_factory=list)


class InventedProjectCreateSchema(BaseModel):
    """A project in the standing given, its transitions written by its first
    member when it was made."""

    name: str | None = Field(
        default=None,
        description="The draft's title, the project's name; a draft without one when null",
        examples=["Recipe box"],
    )
    state: ProjectState = Field(default=ProjectState.OPEN)
    archived: bool = Field(default=False)
    autopilot: bool = Field(
        default=False, description="Auto pilot on; a finished project has it off"
    )
    members: list[str] = Field(
        min_length=1,
        description=(
            "The members' handles, in the order they joined; the first created "
            "the project"
        ),
        examples=[["ada", "ben"]],
    )
    ticket: str | None = Field(
        default=None, description="The plan's ticket id", examples=["RB-12"]
    )
    repo: str | None = Field(
        default=None,
        description="The plan's repository",
        examples=["pvginkel/RecipeBox"],
    )
    tasks: list[InventedTaskSchema] = Field(
        default_factory=list, description="The plan's steps, in order"
    )
    notes: list[InventedNoteSchema] = Field(
        default_factory=list, description="The plan's own open notes"
    )
    open_items: int = Field(
        default=0,
        ge=0,
        description="How many open notices a session of the project adds",
    )
    environment_id: str | None = Field(
        default=None,
        description="The environment the session adding the open items runs in",
        examples=["example-env-1"],
    )


class InventedProjectSchema(BaseModel):
    id: uuid.UUID = Field(description="The project's id")
