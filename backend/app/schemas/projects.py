"""Schemas for /api/projects: the project list's tabs and a project's head."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.reference import ProjectState, TaskStatus


class ProjectListQuerySchema(BaseModel):
    """Which of the two lists: the project list, or the archived projects."""

    archived: bool = Field(
        default=False,
        description="True for the archived projects; false for every other",
    )


class PlanProgressSchema(BaseModel):
    """Where the plan stands, as the head's step and a tab's status line read it."""

    done: int = Field(description="The plan's steps done", examples=[2])
    total: int = Field(
        description="The plan's steps, removed ones not counted", examples=[5]
    )
    in_progress: list[str] = Field(
        description="The titles of the steps in progress, in the plan's order",
        examples=[["Build the recipe card page"]],
    )


class ProjectTabSchema(BaseModel):
    """What a project's tab in the list shows."""

    id: uuid.UUID = Field(description="The project's id")
    name: str | None = Field(
        description="The draft's title; null while the draft has none",
        examples=["Recipe box"],
    )
    ticket: str | None = Field(
        description="The ticket id, from the plan; null when it has none",
        examples=["RB-12"],
    )
    state: ProjectState = Field(description="The project's state")
    finished_at: datetime | None = Field(
        description="When the project finished; null unless its state is finished"
    )
    member: bool = Field(
        description="Whether the signed-in person is a member of the project"
    )
    progress: PlanProgressSchema


class ProjectListResponseSchema(BaseModel):
    """The projects of one list, in the order they were created."""

    projects: list[ProjectTabSchema]


class MemberSchema(BaseModel):
    """A member, as an avatar draws them (F106, F132)."""

    handle: str = Field(description="The member's handle", examples=["ada"])
    name: str = Field(
        description="The full name, the avatar's tooltip", examples=["Ada Example"]
    )
    initials: str = Field(description="The avatar's initials", examples=["AE"])
    avatar_slot: int = Field(
        description="The avatar's palette slot, from 1", examples=[1]
    )


class PlanNoteSchema(BaseModel):
    """An open note the agent keeps on a step or on the plan."""

    id: str = Field(
        description="The note's id in `plan.json`", examples=["card-layout"]
    )
    summary: str = Field(examples=["Cards are one column"])
    content: str = Field(
        examples=["Ben chose one column, the ingredients above the method."]
    )


class PlanTaskSchema(BaseModel):
    """A step of the plan, with its open notes."""

    id: str = Field(description="The step's id in `plan.json`", examples=["build"])
    title: str = Field(examples=["Build the recipe card page"])
    status: TaskStatus = Field(description="The step's status")
    notes: list[PlanNoteSchema] = Field(description="The step's open notes")


class ProjectHeadSchema(BaseModel):
    """What a project's head, its popovers and its menu read."""

    id: uuid.UUID = Field(description="The project's id")
    name: str | None = Field(
        description="The draft's title; null while the draft has none",
        examples=["Recipe box"],
    )
    ticket: str | None = Field(
        description="The ticket id, from the plan; null when it has none",
        examples=["RB-12"],
    )
    repo: str | None = Field(
        description="The repository, from the plan; null when it has none",
        examples=["pvginkel/RecipeBox"],
    )
    state: ProjectState = Field(description="The project's state")
    archived: bool = Field(description="Whether the project is archived")
    autopilot: bool = Field(description="Whether auto pilot is on")
    member: bool = Field(
        description="Whether the signed-in person is a member of the project"
    )
    members: list[MemberSchema] = Field(
        description="The members, in the order they joined"
    )
    progress: PlanProgressSchema
    tasks: list[PlanTaskSchema] = Field(description="The plan's steps, in order")
    notes: list[PlanNoteSchema] = Field(description="The plan's own open notes")
    open_items: int = Field(
        description=(
            "The project's open items, the opening not counted: those Finish "
            "closes unanswered"
        ),
        examples=[3],
    )
