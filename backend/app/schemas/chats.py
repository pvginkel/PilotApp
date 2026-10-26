"""Schemas for a person's message to a project's brain (F38.3; design 3
§5.3), and for a project's chats as a person reads them (F40.3, F43)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.reference import ChatKind, CloseCause, SessionState


class ChatMessageRequestSchema(BaseModel):
    """A person's message to the project's brain."""

    words: str = Field(
        description=(
            "The person's words, sent verbatim, a quote travelling inside them "
            'as a tag: `<quoted_item id="<item id>">…</quoted_item id="…">` or '
            '`<quoted_block id="<item id>/<local id>">…</quoted_block id="…">` '
            "(F38.3)"
        )
    )

    @field_validator("words")
    @classmethod
    def _says_something(cls, words: str) -> str:
        if not words.strip():
            raise ValueError("a message has words")
        return words


class ChatTurnSchema(BaseModel):
    """The message's Turn in the project's chat."""

    chat: uuid.UUID = Field(
        description="The chat's id, its session's, whose records show the message"
    )
    seq: int = Field(description="The Turn's number in the chat's session")
    state: SessionState = Field(
        description=(
            "The chat's session's state: `held` while the gate holds its start, "
            "`starting` while it comes up, `running` once the message went out, "
            "`idle` when its send failed"
        )
    )
    error: str | None = Field(
        description="Why the message's send failed (F125); null unless it did"
    )


class ChatSchema(BaseModel):
    """One of a project's chats."""

    id: uuid.UUID = Field(
        description=(
            "The chat's id, its session's, whose records the session's records "
            "route reads"
        )
    )
    kind: ChatKind = Field(
        description="`definition`, the draft's chat, or `project`, a project's chat"
    )
    opened_at: datetime = Field(description="When the chat opened")
    closed_at: datetime | None = Field(
        description="When the chat closed; null while it is open"
    )
    close_cause: CloseCause | None = Field(
        description=(
            "Why the chat closed: `timeout` after its last turn, `created` at "
            "Create project, `finished` at Finish, `reopened` at Reopen; null "
            "while it is open"
        )
    )


class ChatReadSchema(BaseModel):
    """The caller's place in the project's chat (F43)."""

    read_at: datetime | None = Field(
        description=(
            "When the caller last saw the project's chat to its end, on any "
            "device; null before they first did"
        )
    )
    unread: bool = Field(
        description="Whether a reply of Pilot's came in the project's chats after it"
    )


class ChatListSchema(ChatReadSchema):
    """A project's chats, and the caller's place in them."""

    chats: list[ChatSchema] = Field(
        description=(
            "The project's chats: the definition chat first where one exists, "
            "then the project's chats in the order they opened, the latest last"
        )
    )
