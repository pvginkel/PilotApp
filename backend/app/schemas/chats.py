"""Schemas for a person's message to a project's brain (F38.3; design 3
§5.3)."""

import uuid

from pydantic import BaseModel, Field, field_validator

from app.models.reference import SessionState


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
