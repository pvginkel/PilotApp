"""Schemas for a project's timeline, read whole: its items in order, with what
their lines and open forms show (F8, F12, F13, F18, F31)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.models.reference import AnswerChannel, BlockKind, UserKind

ItemKindCode = Literal[
    "opening",
    "decision",
    "confirmation",
    "question",
    "action",
    "notice",
    "document",
    "review",
    "work",
    "card_wait",
    "timed_wait",
]
"""Item Kind's codes (DB §2.4)."""

ItemForm = Literal["prose", "work", "wait"]
"""Item Kind's forms: which subtype an item is."""

DoneCauseCode = Literal["answered", "marked", "settled", "turn_ended", "finished"]
"""Done Cause's codes (DB §2.4)."""


class UserSchema(BaseModel):
    """A person, or Pilot, as an avatar draws them (F106, F132)."""

    kind: UserKind = Field(description="A person, or Pilot itself")
    handle: str = Field(description="The handle; Pilot's is `agent`", examples=["ada"])
    name: str = Field(
        description="The full name, the avatar's tooltip", examples=["Ada Example"]
    )
    initials: str = Field(description="The avatar's initials", examples=["AE"])
    avatar_slot: int | None = Field(
        description="The avatar's palette slot, from 1; null for Pilot", examples=[1]
    )


class StepSchema(BaseModel):
    """The plan task an item serves, whose title its step divider carries (F9)."""

    id: str = Field(description="The task's id in `plan.json`", examples=["build"])
    title: str = Field(
        description="The task's title, live from the plan; a removed task's last",
        examples=["Build the recipe card page"],
    )


class DoneSchema(BaseModel):
    """How a done item came to be done: its done line (F13)."""

    at: datetime = Field(description="When the item was done")
    cause: DoneCauseCode = Field(description="How it came to be done")
    by: UserSchema | None = Field(
        description="Who did it; null when the server did, at a turn's end"
    )
    undo: bool = Field(
        description=(
            "Whether the record takes Undo now: a prose item, done by a cause that "
            "offers it, whose answers no session has taken (F14.1)"
        )
    )


class OptionSchema(BaseModel):
    """A choice a block offers."""

    label: str = Field(examples=["Dome"])
    text: str | None = Field(
        description="The option's one line; null for a bare label",
        examples=["Up in five minutes"],
    )
    recommended: bool = Field(description="Whether the block recommends it")


class ConfirmationReasonSchema(BaseModel):
    """The ground on which a confirmation asks (F22.1)."""

    code: str = Field(examples=["rider"])
    name: str = Field(
        description="The reason's name in the grants table, not the card's words",
        examples=["Rider"],
    )
    description: str = Field(
        description="When the agent uses the reason, one line, not the card's tooltip"
    )


class DeferralSchema(BaseModel):
    """Where a deferred block went (decision 47)."""

    to: str = Field(
        description="The task's id, or `plan` for the project's end", examples=["ship"]
    )
    title: str | None = Field(
        description=(
            "The task's title, live from the plan, a removed task's last; null for "
            "`plan`"
        ),
        examples=["Ship it"],
    )


class SectionSchema(BaseModel):
    """A block's own section (F30.9), which a display may draw as one line
    (F31.5)."""

    heading: str = Field(
        description="The heading's text, without its `#` marks",
        examples=["Which tent?"],
    )


class BlockSchema(BaseModel):
    """An ask in its item's text, with its definition and its answer (F30, F31)."""

    id: str = Field(
        description="The block's local id, unique within its item", examples=["D1"]
    )
    kind: BlockKind = Field(description="The block's kind")
    confirmation: bool = Field(description="Whether the decision is a confirmation")
    because: ConfirmationReasonSchema | None = Field(
        description="A confirmation's reason; null for any other block"
    )
    proposal: str | None = Field(
        description="A decision's one proposal; null where it offers options"
    )
    default: str | None = Field(description="A question's default answer")
    check: str | None = Field(description="What Pilot checks after the answer")
    options: list[OptionSchema] = Field(description="The choices, in their order")
    answer: str | None = Field(
        description=(
            "The answer: an option's label, `Agree`, `Yes`, `No`, free words or "
            "`deferred`; null while unanswered and on an action marked Done"
        ),
        examples=["Dome"],
    )
    by: UserSchema | None = Field(description="Who answered, or marked the action Done")
    at: datetime | None = Field(description="When it was answered")
    note: str | None = Field(
        description="Why it was answered so, or what was pasted back (F17.4)"
    )
    via: AnswerChannel | None = Field(
        description=(
            "How the answer reached the record: `app` for a person's unless the "
            "text names another; null for Pilot's unless it names one, and while "
            "unanswered"
        )
    )
    done: datetime | None = Field(description="When the action was marked Done")
    deferral: DeferralSchema | None = Field(
        description="Where a deferred block went; null unless `answer` is `deferred`"
    )
    section: SectionSchema | None = Field(
        description=(
            "The block's own section: from the nearest heading before it, the "
            "title's counting as none, to the next heading of the same or a higher "
            "level, or the text's end, where that holds no other block; null where "
            "it has none. The prose parts in it carry the block's id as their "
            "`section`"
        )
    )


class ProsePartSchema(BaseModel):
    """Markdown between blocks, drawn as GFM (F29.1)."""

    type: Literal["prose"]
    markdown: str = Field(examples=["The dome stands up in five minutes."])
    section: str | None = Field(
        description=(
            "The local id of the block whose own section (F30.9) holds this "
            "Markdown; null outside every section. A section's parts and its block "
            "stand together in the body, its heading the first line of its first part"
        ),
        examples=["D1"],
    )


class BlockPartSchema(BaseModel):
    """A block, in its place in the text."""

    type: Literal["block"]
    block: BlockSchema


BodyPartSchema = Annotated[
    ProsePartSchema | BlockPartSchema, Field(discriminator="type")
]


class AttachmentSchema(BaseModel):
    """A file hung on an item, reader's material (F36), which its stream
    `/api/attachments/<id>` serves without its title or stored type."""

    id: uuid.UUID = Field(description="The attachment's id, its stream's address")
    title: str = Field(examples=["Recipe card sketch"])
    filename: str = Field(
        description="The file's name, the one its download takes",
        examples=["sketch.md"],
    )
    content_type: str = Field(
        description="The content type it was copied with", examples=["text/markdown"]
    )
    size: int = Field(description="Its size in bytes", examples=[2048])
    batch: int = Field(
        description=(
            "The project's attach call it came in, from 1: the files of one call, "
            "a folder among them, share it (F37.1)"
        ),
        examples=[1],
    )
    copied_at: datetime = Field(description="When it was copied into the record")
    source: str | None = Field(
        description=(
            "Where it was copied from, `<environment>:<path>` (F36.1); null for the "
            "copy of the draft"
        ),
        examples=["kc-recipes:/work/Recipes/sketch.md"],
    )


class TimelineItemSchema(BaseModel):
    """An entry on the timeline, with what its line and its open form show."""

    id: uuid.UUID = Field(description="The item's id")
    seq: int = Field(description="Its place in the timeline, from 1", examples=[3])
    kind: ItemKindCode = Field(description="The item's kind")
    form: ItemForm = Field(description="Which subtype the item is")
    title: str | None = Field(
        description=(
            "The line's title; null for a registered document while its text gives none"
        ),
        examples=["Which tent?"],
    )
    file_name: str | None = Field(
        description=(
            "A registered document's file name, from its source path, which its line "
            "shows while `title` is null (F35); null for any other item"
        ),
        examples=["refinement.md"],
    )
    created_at: datetime = Field(description="When the item was placed")
    step: StepSchema | None = Field(description="The plan task it serves, if any")
    urgent: bool = Field(description="Whether it is urgent (F10)")
    for_user: UserSchema | None = Field(
        description="The person it is for (F107); null for everyone"
    )
    done: DoneSchema | None = Field(description="Its done line; null while open")
    concept: bool = Field(
        description=(
            "Whether the latest save of its text is held, its text shown as last "
            "published until a parseable save arrives (F78)"
        )
    )
    author: UserSchema | None = Field(
        description="The opening's author (F18.1); null for every other item"
    )
    words: str | None = Field(
        description="The opening's words, verbatim; null for every other item"
    )
    body: list[BodyPartSchema] | None = Field(
        description=(
            "A prose item's text but the opening's, as drawn: its prose parts and "
            "blocks in order, split at each block's own section's edges, without "
            "the front matter and a first heading that is its title; null for the "
            "opening, work and waits"
        )
    )
    summary: str | None = Field(
        description=(
            "The front matter's `summary`, which a card and the overlay's lead show "
            "(F34); null where the text gives none, and for the opening, work and "
            "waits"
        ),
        examples=["Three tents compared; the dome wins on weight."],
    )
    word_count: int | None = Field(
        description=(
            "The text's own words past its front matter, every block's included, "
            "whatever a display collapses: under about 150 a document draws inline, "
            "else it leaves a card (F24.1); null where `body` is"
        ),
        examples=[412],
    )
    read_minutes: int | None = Field(
        description=(
            "The text's reading time at 230 words a minute, rounded, at least 1: a "
            'review\'s "N min read" (F25.1); null where `body` is'
        ),
        examples=[2],
    )
    writing: bool = Field(
        description=(
            "Whether a session's running turn is saving the text, which Pilot's "
            "dots show at its end (F35); cleared at the turn's end, which no live "
            "event announces"
        )
    )
    edited_at: datetime | None = Field(
        description=(
            "*Edited <time>* (F28.7): the time of the latest `turn` Version that "
            "follows the first Version whose text, as drawn, holds anything; null "
            "where no such Version follows it, and where `body` is null"
        )
    )
    attachments: list[AttachmentSchema] = Field(
        description="The files hung on the item, in their order, on every kind (F17.5)"
    )


class TimelineSchema(BaseModel):
    """A project's timeline, whole."""

    finished_at: datetime | None = Field(
        description=(
            "When the project finished, its end divider's stamp; null unless it is "
            "finished"
        )
    )
    items: list[TimelineItemSchema] = Field(description="The items, in their order")
