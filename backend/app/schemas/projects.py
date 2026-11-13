"""Schemas for /api/projects: the project list's tabs, a project's head, by its
id or its address, the project an address names, and the changes of its
standing."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.reference import ProjectState, TaskStatus


class ProjectStatus(StrEnum):
    """A project's status, its tab's one icon (F141.1; DB Project Status):
    derived on request, never stored, the list of its values the API's
    (decision 53)."""

    RUNNING = "running"
    WAITING_ON_YOU = "waiting_on_you"
    WAITING_ON_EVENT = "waiting_on_event"
    DONE = "done"
    IDLE = "idle"
    PAUSING = "pausing"
    PAUSED = "paused"


STATUS_DESCRIPTION = (
    "The project's status, one for every viewer (F141.1; DB 228): paused, or "
    "pausing while one of its sessions runs a turn; else running while a work "
    "item or a job runs, waiting_on_you while an open item waits on a member, "
    "waiting_on_event while a wait is open, done while every step of a plan is "
    "done, idle otherwise; null for a draft and a finished project"
)


ADDRESS_DESCRIPTION = (
    "The project's address, the name its pages' URLs take: its slug once Create "
    "project has given it one, else `draft-<number>`, its folder in the store's "
    "tree"
)


class ProjectListQuerySchema(BaseModel):
    """Which of the two lists: the project list, or the archived projects."""

    archived: bool = Field(
        default=False,
        description="True for the archived projects; false for every other",
    )


class ProjectLookupQuerySchema(BaseModel):
    """An address of a project, as a page's URL names it."""

    address: str = Field(
        min_length=1,
        description=(
            "The project's slug, a draft's `draft-<number>`, which goes on naming "
            "its project once Create project has given it its slug, or the "
            "project's id; an address that reads as an id is one"
        ),
        examples=["recipe-box", "draft-7"],
    )


class ProjectAddressSchema(BaseModel):
    """The project an address names, and the address it is at now: a
    `draft-<number>` or an id looked up is answered with the address its
    pages take."""

    id: uuid.UUID = Field(description="The project's id")
    address: str = Field(description=ADDRESS_DESCRIPTION, examples=["recipe-box"])


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


class BadgeSchema(BaseModel):
    """A tab's badge: the items waiting on the signed-in person (F1.4)."""

    count: int = Field(
        description=(
            "The project's open items waiting on the signed-in person: prose items "
            "but the opening, a notice only when it is urgent, a work item stopped "
            "or failed to start, never a wait; not those for another person"
        ),
        examples=[2],
    )
    urgent: bool = Field(description="Whether one of them is urgent")


class ProjectTabSchema(BaseModel):
    """What a project's tab in the list shows."""

    id: uuid.UUID = Field(description="The project's id")
    address: str = Field(description=ADDRESS_DESCRIPTION, examples=["recipe-box"])
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
    status: ProjectStatus | None = Field(description=STATUS_DESCRIPTION)
    member: bool = Field(
        description="Whether the signed-in person is a member of the project"
    )
    progress: PlanProgressSchema
    badge: BadgeSchema


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


class RunningWorkSchema(BaseModel):
    """A work item whose session runs, starts or waits at the gate."""

    id: uuid.UUID = Field(description="The work item's id, its session's")
    seq: int = Field(
        description="The work item's number on the project's timeline", examples=[12]
    )
    title: str | None = Field(
        description="The work item's title", examples=["Renaming the badge"]
    )
    environment: str | None = Field(
        description=(
            "The name of the environment its session runs in; null while the "
            "session has none, its start waiting at the gate"
        ),
        examples=["Recipe box 2"],
    )


class ProjectHeadSchema(BaseModel):
    """What a project's head, its popovers and its menu read."""

    id: uuid.UUID = Field(description="The project's id")
    address: str = Field(description=ADDRESS_DESCRIPTION, examples=["recipe-box"])
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
    status: ProjectStatus | None = Field(description=STATUS_DESCRIPTION)
    member: bool = Field(
        description="Whether the signed-in person is a member of the project"
    )
    members: list[MemberSchema] = Field(
        description="The members, in the order they joined"
    )
    progress: PlanProgressSchema
    tasks: list[PlanTaskSchema] = Field(description="The plan's steps, in order")
    notes: list[PlanNoteSchema] = Field(description="The plan's own open notes")
    running_work: list[RunningWorkSchema] = Field(
        description=(
            "The work items whose session runs, starts or waits at the gate, in "
            "timeline order: those whose sessions Finish and Archive stop (F5.1)"
        )
    )
    open_items: int = Field(
        description=(
            "The project's open items, the opening and `running_work` not counted: "
            "those Finish closes unanswered"
        ),
        examples=[3],
    )
    autopilot_may_take: int = Field(
        description=(
            "The open confirmations the switch would answer: unanswered "
            "confirmation blocks of open items whose reason does not ask under "
            "auto pilot (`because.asks_under_autopilot` false). Turning auto "
            "pilot on with any asks first whether to answer them (F4.2)"
        ),
        examples=[2],
    )
    create_refusal: str | None = Field(
        description=(
            "Why Create project cannot be pressed now (F48.1): Pilot writing in "
            "the definition chat, nothing drafted, or a draft with no valid slug; "
            "for an archived project or one past its draft, its standing. Null "
            "when it can be pressed; an ask the draft leaves open is no reason"
        ),
        examples=["Pilot is writing"],
    )
    url: str = Field(
        description="The project's page in the app",
        examples=["https://pilot.example.com/projects/recipe-box"],
    )


class TransitionRequestSchema(BaseModel):
    """A change of a project's standing the signed-in person makes."""

    kind: Literal[
        "opened",
        "finished",
        "reopened",
        "archived",
        "brought_back",
        "autopilot_on",
        "autopilot_off",
        "paused",
        "resumed",
    ] = Field(
        description=(
            "Which change: Create project, Finish, Reopen, Archive, Bring back, "
            "auto pilot switched on or off, or the project paused or resumed. "
            "It must follow from the project's standing: Create project from a "
            "draft its head's `create_refusal` does not refuse, Finish from "
            "open, Reopen from finished, Archive from unarchived, Bring back "
            "from archived, auto pilot on from off on an open project, off from "
            "on, the pause from not paused on an open project, the resume from "
            "paused; an archived project takes Bring back alone"
        ),
        examples=["finished"],
    )
    answer_confirmations: bool = Field(
        default=False,
        description=(
            "The switch's dialog's Yes, with `autopilot_on` alone: every open "
            "confirmation the switch would answer, the head's "
            "`autopilot_may_take`, answered Yes by the caller through "
            "`autopilot` as auto pilot turns on (F4.2)"
        ),
    )

    @model_validator(mode="after")
    def _yes_with_autopilot_on(self) -> "TransitionRequestSchema":
        if self.answer_confirmations and self.kind != "autopilot_on":
            raise ValueError("`answer_confirmations` goes with `autopilot_on` alone")
        return self
