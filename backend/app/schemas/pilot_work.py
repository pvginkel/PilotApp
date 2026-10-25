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
