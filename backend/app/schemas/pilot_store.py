"""Schemas for `pilot-store`'s routes, the REST calls Pilot's MCP server makes
for the brain's tools (TD §4.5, F86)."""

import uuid
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.engine.paths import DRAFT
from app.schemas.timeline import HeldReason

Mark = Literal["done", "read", "reviewed"]
"""A mark `mark` makes (F86.3)."""

AddedKind = Literal[
    "decision",
    "question",
    "action",
    "notice",
    "document",
    "review",
    "work",
    "card_wait",
    "timed_wait",
]
"""A kind of item `add_item` is given (TD §4.5): a prose item's, a work
item's, or a wait's (F86.1)."""


def source_parts(value: str) -> tuple[str, str]:
    """A source, `<environment>:<path>` (DB decision 37), as its environment
    and its absolute path: an environment id has no colon, and a path starts
    with `/`."""
    environment, colon, path = value.partition(":")
    if (
        not colon
        or not environment
        or any(char.isspace() or char == "/" for char in environment)
        or not path.startswith("/")
    ):
        raise ValueError("a source is `<environment>:<absolute path>`")
    return environment, path


def _source(value: str) -> str:
    source_parts(value)
    return value


def _attachment_ref(value: str) -> str:
    """An attachment's id, else a source."""
    try:
        uuid.UUID(value)
    except ValueError:
        source_parts(value)
    return value


def _distinct(values: list[str]) -> list[str]:
    if len(set(values)) != len(values):
        raise ValueError("an attachment is named twice")
    return values


Source = Annotated[
    str,
    AfterValidator(_source),
    Field(
        description=(
            "The material's environment and its absolute path in it,"
            " `<environment>:<path>`: a file, or a folder's every file under it"
        ),
        examples=["pvginkel-example-1a2b3c:/work/Example/docs/design"],
    ),
]


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


def _answered_block(value: str) -> str:
    """A block `answer` takes: a block's id, or `project.md/<local id>`, a
    block of the draft, which has no item (F47.4)."""
    if not value.startswith(f"{DRAFT}/"):
        return _block_id(value)
    local = value.removeprefix(f"{DRAFT}/")
    if not local or any(char.isspace() for char in local):
        raise ValueError(f"a block of the draft is `{DRAFT}/<local id>`")
    return value


AnsweredBlockId = Annotated[
    str,
    AfterValidator(_answered_block),
    Field(
        description=(
            "The block's id, `<item id>/<local id>` (TD §4.9), or"
            " `project.md/<local id>` for a block of the draft, in its"
            " definition chat"
        ),
        examples=["0f8a1c2e-5b7d-4e3a-9c61-2d4f8b0e7a15/D1", "project.md/Q1"],
    ),
]


class AnswerRequestSchema(BaseModel):
    """A person's answer to a block, given in the chat, to record for them."""

    model_config = ConfigDict(extra="forbid")

    block: AnsweredBlockId
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


class AddItemRequestSchema(BaseModel):
    """An item to add, in `timeline.json`'s shape (TD §4.5, F86.1): a prose
    item, with its text or to fill, or a work item to start. Which of the
    fields a kind takes the service says."""

    model_config = ConfigDict(extra="forbid")

    kind: AddedKind = Field(description="The item's kind")
    title: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "The title it is born with in its file's front matter, where its"
            " Markdown gives none; a work item's line"
        ),
        examples=["Put the v4 key into OpenBao"],
    )
    markdown: str | None = Field(
        default=None,
        min_length=1,
        description="A prose item's whole text, minted with it",
        examples=["```action id=A1\n```\n"],
    )
    step: str | None = Field(
        default=None,
        min_length=1,
        description="The id of the plan's task it serves",
        examples=["pitch"],
    )
    urgent: bool = Field(default=False, description="A prose item that is urgent")
    for_: str | None = Field(
        default=None,
        alias="for",
        min_length=1,
        description="The handle of the person a prose item is for",
        examples=["ada"],
    )
    summary: str | None = Field(
        default=None,
        min_length=1,
        description="A prose item's summary",
        examples=["The key the importer needs."],
    )
    attachments: Annotated[
        list[Annotated[str, AfterValidator(_attachment_ref)]],
        AfterValidator(_distinct),
    ] = Field(
        default_factory=list,
        description=(
            "What it carries: attachments already made, by id, and material"
            " to copy in, `<environment>:<path>`"
        ),
        examples=[["pvginkel-example-1a2b3c:/work/Example/docs/survey.md"]],
    )
    repo: str | None = Field(
        default=None,
        pattern=r"^[^/\s]+/[^/\s]+$",
        description="The repository a work item runs in, `owner/Name`",
        examples=["pvginkel/Example"],
    )
    cwd: str | None = Field(
        default=None,
        min_length=1,
        description="A work item's working directory",
        examples=["/work/Example"],
    )
    brief: str | None = Field(
        default=None,
        min_length=1,
        description="A work item's brief, its first turn's text",
        examples=["Rename the badge."],
    )
    agent: str | None = Field(
        default=None, min_length=1, description="A work item's agent"
    )
    model: str | None = Field(
        default=None, min_length=1, description="A work item's model", examples=["opus"]
    )
    reasoning_effort: str | None = Field(
        default=None,
        min_length=1,
        description="A work item's reasoning effort",
        examples=["high"],
    )


class AttachRequestSchema(BaseModel):
    """Outside material to copy in, and the item it hangs on."""

    model_config = ConfigDict(extra="forbid")

    source: Source
    to: uuid.UUID | None = Field(
        default=None,
        description="The id of the item it hangs on",
        examples=["0f8a1c2e-5b7d-4e3a-9c61-2d4f8b0e7a15"],
    )


class AddedSchema(BaseModel):
    """The item added."""

    id: uuid.UUID = Field(description="Its id")
    path: str | None = Field(
        description="A prose item's file, its absolute path in the store; none for work",
        examples=["/work/Projects/camp/items/4-put-the-v4-key-into-openbao.md"],
    )
    state: Literal["starting", "held"] | None = Field(
        description="A work item's session as the gate left it; none for prose"
    )
    held: HeldReason | None = Field(
        description="Why the gate holds a held work item's start; none otherwise"
    )
    effect: str = Field(
        description="Its effect line, `<verb> · <what>` (F41)",
        examples=["Added · Action · Put the v4 key into OpenBao"],
    )


class AttachedSchema(BaseModel):
    """The attachments the material was copied into."""

    ids: list[uuid.UUID] = Field(
        description="Their ids, one per file, a folder's in its files' path order"
    )
    effect: str = Field(
        description="Its effect line, `<verb> · <what>` (F41)",
        examples=["Attached · design, 3 files"],
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
