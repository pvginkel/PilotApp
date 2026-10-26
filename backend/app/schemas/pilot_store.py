"""Schemas for `pilot-store`'s routes, the REST calls Pilot's MCP server makes
for the brain's tools (TD §4.5, F86)."""

import uuid
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

Mark = Literal["done", "read", "reviewed"]
"""A mark `mark` makes (F86.3)."""


def _block_id(value: str) -> str:
    """A block's id (TD §4.9): an item's id, a slash, and a local id."""
    item, slash, local = value.partition("/")
    if not slash or not local or any(char.isspace() for char in local):
        raise ValueError("a block's id is `<item id>/<local id>`")
    uuid.UUID(item)
    return value


BlockId = Annotated[
    str,
    AfterValidator(_block_id),
    Field(
        description="The block's id, `<item id>/<local id>` (TD §4.9)",
        examples=["0f8a1c2e-5b7d-4e3a-9c61-2d4f8b0e7a15/D1"],
    ),
]


class AnswerRequestSchema(BaseModel):
    """A person's answer to a block, given in the chat, to record for them."""

    model_config = ConfigDict(extra="forbid")

    block: BlockId
    value: str = Field(
        min_length=1,
        description=(
            "The answer: an option's label, `Agree`, `Yes`, `No`, free words, or"
            " `deferred` with `to`"
        ),
        examples=["Dome"],
    )
    for_: str = Field(
        alias="for",
        min_length=1,
        description="The handle of the person whose answer it is",
        examples=["ada"],
    )
    note: str | None = Field(
        default=None,
        description="Their words, as they gave them",
        examples=["The dome, it stands up in five minutes."],
    )
    to: str | None = Field(
        default=None,
        description=(
            "With `deferred`: the plan's task the block returns at, or `plan`"
        ),
        examples=["pitch"],
    )


class MarkRequestSchema(BaseModel):
    """A mark on an item, for a person or Pilot's own."""

    model_config = ConfigDict(extra="forbid")

    item: uuid.UUID = Field(
        description="The item's id", examples=["0f8a1c2e-5b7d-4e3a-9c61-2d4f8b0e7a15"]
    )
    mark: Mark = Field(
        description="Done on a document, Read on a notice, Reviewed on a review"
    )
    for_: str | None = Field(
        default=None,
        alias="for",
        min_length=1,
        description="The handle of the person the mark is for; without it, Pilot's",
        examples=["ada"],
    )


class StopRequestSchema(BaseModel):
    """A work item whose session to stop."""

    model_config = ConfigDict(extra="forbid")

    item: uuid.UUID = Field(
        description="The work item's id",
        examples=["0f8a1c2e-5b7d-4e3a-9c61-2d4f8b0e7a15"],
    )


class WriterQuestionRequestSchema(BaseModel):
    """A question to a registered document's writer about one of its blocks."""

    model_config = ConfigDict(extra="forbid")

    document: uuid.UUID = Field(
        description="The registered document's item id",
        examples=["0f8a1c2e-5b7d-4e3a-9c61-2d4f8b0e7a15"],
    )
    block: BlockId
    question: str = Field(
        min_length=1,
        description="The question, verbatim",
        examples=["Which cache does 'the cache' mean?"],
    )


class RecordedSchema(BaseModel):
    """What the call changed."""

    effect: str = Field(
        description="Its effect line, `<verb> · <what>` (F41)",
        examples=["Answered · D1 · Which tent?"],
    )


class WriterQuestionsSchema(BaseModel):
    """The document's blocks its writer is asked about."""

    blocks: list[str] = Field(
        description="Their local ids, in their order in the document",
        examples=[["D2", "D4"]],
    )
