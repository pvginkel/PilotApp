"""Schemas of the testing-only session start."""

import uuid

from pydantic import BaseModel, Field


class TestingSessionStartSchema(BaseModel):
    """A work Session to start for a project, in an environment of the
    configured controller."""

    project_id: uuid.UUID = Field(description="The Project the Session works")
    environment_id: str = Field(
        min_length=1,
        description="The controller's id of the environment it runs in",
        examples=["example-env-1"],
    )
    cwd: str = Field(
        min_length=1,
        description="The headless session's working directory",
        examples=["/work/Example"],
    )
    brief: str = Field(
        min_length=1,
        description="The first Turn's message",
        examples=["Rename the badge."],
    )
    agent: str | None = Field(default=None, description="The agent name to create with")
    model: str | None = Field(default=None, description="The model to create with")
    reasoning_effort: str | None = Field(
        default=None, description="The reasoning effort to create with"
    )
    resume: str | None = Field(
        default=None, description="A Claude conversation id to resume"
    )


class TestingSessionStartedSchema(BaseModel):
    """The Session the start wrote, `starting`."""

    id: uuid.UUID = Field(description="The Session's id")
