"""Schemas for a project's conversations as its people read them (F150.12):
the calling sessions' conversations with Pilot about the project, each by the
environment and the session that opened it."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.reference import CloseCause
from app.schemas.links import EnvironmentNameSchema


class ProjectConversationSchema(BaseModel):
    """One of a project's conversations."""

    id: uuid.UUID = Field(
        description=(
            "The conversation's id, its session's, whose records the session's "
            "records route reads"
        )
    )
    environment: EnvironmentNameSchema = Field(
        description="The environment whose session opened it"
    )
    session: str | None = Field(
        description="The name of the session that opened it; null where it named none"
    )
    opened_at: datetime = Field(description="When the conversation opened")
    closed_at: datetime | None = Field(
        description="When the conversation closed; null while it is open"
    )
    close_cause: CloseCause | None = Field(
        description=(
            "Why the conversation closed: `ended` by its caller, `timeout` after "
            "its last turn, `finished` at Finish, `reopened` at Reopen, "
            "`archived` at Archive, and never `created`; null while it is open"
        )
    )
    answering: bool = Field(
        description=(
            "Whether Pilot is answering in the conversation: its start held at "
            "the gate or under way, or a turn of it running, which the "
            "conversation's Stop stops; false once that ends, however it ends, "
            "and for a closed conversation. A move of it raises `project_changed`"
        )
    )


class ProjectConversationListSchema(BaseModel):
    """A project's conversations."""

    conversations: list[ProjectConversationSchema] = Field(
        description=(
            "The project's conversations, open and closed, whoever opened them, "
            "in the order they opened, the latest last"
        )
    )
