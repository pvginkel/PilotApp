"""Schemas for `pilot-work`'s routes, the REST calls Pilot's MCP server makes
for a worker session's tools (TD §4.5)."""

import uuid

from pydantic import BaseModel, ConfigDict, Field


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
