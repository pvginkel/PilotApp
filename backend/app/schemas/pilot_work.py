"""Schemas for `pilot-work`'s routes, the REST calls Pilot's MCP server makes
for a worker session's tools (TD §4.5)."""

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.reference import ProgressState

MAX_STEP_CODE = 64
MAX_STEP_LABEL = 120
MAX_STEPS = 100
"""The limits of a work item's list of steps (F85.3), which the schema of
`progress_steps` does not hold."""


class RegisterDocumentRequestSchema(BaseModel):
    """A document a worker wrote, to register."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        min_length=1,
        description=(
            "The file's absolute path in the session's environment, under `/work`"
        ),
        examples=["/work/Example/docs/refinement.md"],
    )


class RegisteredDocumentSchema(BaseModel):
    """The registered document."""

    id: uuid.UUID = Field(
        description="Its item's id on the project's timeline",
        examples=["0f8a1c2e-5b7d-4e3a-9c61-2d4f8b0e7a15"],
    )


class AttachFileRequestSchema(BaseModel):
    """Material a worker wrote, to copy into the record."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        min_length=1,
        description=(
            "The file's or the folder's absolute path in the session's"
            " environment, under `/work`: a folder's every file under it"
        ),
        examples=["/work/Example/docs/survey"],
    )
    to: uuid.UUID | None = Field(
        default=None,
        description=(
            "The id of the item the material backs, of the session's project;"
            " without it, the session's own work item"
        ),
        examples=["0f8a1c2e-5b7d-4e3a-9c61-2d4f8b0e7a15"],
    )


class AttachedFilesSchema(BaseModel):
    """The attachments the material was copied into."""

    ids: list[uuid.UUID] = Field(
        description="Their ids, a folder's in its files' path order",
        examples=[["5c2e9a1f-7b3d-4f6e-8a20-1d9c4b7e3f58"]],
    )


class ProgressStepRequestSchema(BaseModel):
    """A step of the list, as the call gives it."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        min_length=1,
        max_length=MAX_STEP_CODE,
        description="The run's name for the step, unique in the list",
        examples=["P3.review-2"],
    )
    label: str = Field(
        min_length=1,
        max_length=MAX_STEP_LABEL,
        description="The step's words on the tile",
        examples=["P3 · second review"],
    )
    state: ProgressState | None = Field(
        default=None,
        description=(
            "Where the step stands; without it, a code on the list keeps its"
            " state and a new one starts `pending`"
        ),
        examples=["active"],
    )


class SetProgressRequestSchema(BaseModel):
    """The work item's list of steps, to replace the one standing."""

    model_config = ConfigDict(extra="forbid")

    steps: list[ProgressStepRequestSchema] = Field(
        max_length=MAX_STEPS,
        description="The steps in order; none removes the list",
    )


class SetProgressStepRequestSchema(BaseModel):
    """One step's state, to set."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        min_length=1,
        max_length=MAX_STEP_CODE,
        description="The code of a step on the list",
        examples=["P3.review-2"],
    )
    state: ProgressState = Field(
        description="Where the step stands now", examples=["done"]
    )


class ProgressStepSchema(BaseModel):
    """A step of the work item's list."""

    code: str = Field(
        description="The run's name for the step", examples=["P3.review-2"]
    )
    label: str = Field(
        description="The step's words on the tile", examples=["P3 · second review"]
    )
    state: ProgressState = Field(description="Where it stands", examples=["active"])


class ProgressSchema(BaseModel):
    """The work item's list of steps as it stands."""

    steps: list[ProgressStepSchema] = Field(description="Its steps, in order")
