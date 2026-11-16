"""Schemas for a calling session's conversation with Pilot about a project
(F150.10, F150.11; DB Conversation)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.reference import CloseCause


def _says_something(words: str) -> str:
    if not words.strip():
        raise ValueError("a message has words")
    return words


class ConversationOpenRequestSchema(BaseModel):
    """A conversation's opening: the project and the caller's first message."""

    address: str = Field(
        min_length=1,
        description=(
            "The project's slug, a draft's `draft-<number>`, which goes on naming "
            "its project once Create project has given it its slug, or the "
            "project's id; an address that reads as an id is one"
        ),
        examples=["recipe-box"],
    )
    words: str = Field(description="The caller's first message, sent verbatim")

    _words = field_validator("words")(_says_something)


class ConversationMessageRequestSchema(BaseModel):
    """A caller's next message in its conversation."""

    words: str = Field(description="The caller's words, sent verbatim")

    _words = field_validator("words")(_says_something)


class ConversationListQuerySchema(BaseModel):
    """Which of the caller's conversations to list."""

    address: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "The address of the one project whose conversations to list, as the "
            "opening takes it; every project's without it"
        ),
        examples=["recipe-box"],
    )


class ConversationSchema(BaseModel):
    """A conversation as its caller reads it."""

    id: uuid.UUID = Field(description="The conversation's id, its session's")
    project_id: uuid.UUID = Field(description="The project it is about")
    environment: str = Field(
        description="The id of the environment whose session opened it"
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
    turns: int = Field(description="The count of its turns so far")
    in_flight: bool = Field(
        description=(
            "Whether a turn of it is in flight, when it takes no message: its "
            "start held at the gate or under way, a turn running, or a stopped "
            "one still ending"
        )
    )


class ConversationListSchema(BaseModel):
    """The conversations a caller's environment opened."""

    conversations: list[ConversationSchema] = Field(
        description="The conversations, open and closed, in the order they opened"
    )


class ConversationTurnSchema(BaseModel):
    """The message's Turn in the conversation."""

    conversation: uuid.UUID = Field(description="The conversation's id")
    seq: int = Field(description="The Turn's number in the conversation")
    error: str | None = Field(
        description="Why the message's send failed (F125); null unless it did"
    )
