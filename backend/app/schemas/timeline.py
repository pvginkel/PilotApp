"""Schemas for a project's timeline, read whole: its items in order, with what
their lines and open forms show (F8, F12, F13, F18, F31); and for a document
read on its own, an item's, the project's draft or its handbook (F28, F13.3,
F37.4, F129.4)."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from app.models.reference import AnswerChannel, BlockKind, SessionState, UserKind
from app.schemas.links import EnvironmentNameSchema

ItemKindCode = Literal[
    "opening",
    "decision",
    "confirmation",
    "question",
    "action",
    "notice",
    "document",
    "review",
    "archive_question",
    "work",
    "card_wait",
    "timed_wait",
]
"""Item Kind's codes (DB §2.4)."""


class HeldReason(StrEnum):
    """Why the gate holds a start (design 2 §13.4, §13.5; F26.1, F143.4,
    F59.2, F135.1, F135.4; DB 183, 266): a work item's the week's or the
    five-hour usage halt, its project paused, the controller unreachable, a
    work item's no slot free, a job's another job of its project before it,
    or a work item's another run on its conversation until that run's turn
    ends. Read at display, never stored (decision 53)."""

    WEEK_HALT = "week_halt"
    FIVE_HOUR_HALT = "five_hour_halt"
    PAUSED = "paused"
    CONTROLLER_UNREACHABLE = "controller_unreachable"
    SLOT = "slot"
    QUEUE = "queue"
    CONVERSATION = "conversation"


class StopCause(StrEnum):
    """Why a work item stopped when no person did. A stop made elsewhere, its
    environment stopped under its turn (design 2 §9.6; F71): it settled
    `stopped`, it settled `deleting`, the controller has it no longer, or it
    settled `error`; the `server` record that ended the turn holds it. A
    usage halt's hard stop, its nudge owed (F135.6; DB 269): the halt that
    holds it, the week's or the five-hour's, or neither once both lifted,
    read at display (decision 66)."""

    ENVIRONMENT_STOPPED = "environment_stopped"
    ENVIRONMENT_DELETING = "environment_deleting"
    ENVIRONMENT_GONE = "environment_gone"
    ENVIRONMENT_ERROR = "environment_error"
    WEEK_HALT = "week_halt"
    FIVE_HOUR_HALT = "five_hour_halt"
    USAGE_LIMIT = "usage_limit"


ItemForm = Literal["prose", "work", "wait"]
"""Item Kind's forms: which subtype an item is."""

DoneCauseCode = Literal[
    "answered", "marked", "settled", "turn_ended", "finished", "withdrawn"
]
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
        description=(
            "Who did it; null when the server did, at a turn's end, or on the "
            "Undo that withdrew a job before its brief went out"
        )
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
    asks_under_autopilot: bool = Field(
        description=(
            "Whether it asks under auto pilot too; false for a reason the switch "
            "answers, whose open confirmation carries the auto pilot mark while "
            "auto pilot is off (F4.2, F4.4)"
        )
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


class ChatPlaceSchema(BaseModel):
    """Where in a chat a block's answer was recorded, which *In the chat* goes
    to (F42.3)."""

    chat: uuid.UUID = Field(
        description=(
            "The chat's id, its session's, whose records the session's records "
            "route reads"
        )
    )
    seq: int = Field(
        description=(
            "The number, in the chat's records, of the `server` record placing "
            "the latest `answered` effect on the block"
        )
    )


class ClaimedWorkSchema(BaseModel):
    """The work item a claimed action is given to: the one its latest naming
    names (DB 260)."""

    id: uuid.UUID = Field(description="The work item's id, its line's address")
    title: str = Field(
        description="The work item's title, as its line shows it",
        examples=["Rotating the CI token"],
    )


class ClaimSchema(BaseModel):
    """An action Pilot claimed and has not done (F21.6): open, Pilot's, waiting
    on no person."""

    work: ClaimedWorkSchema | None = Field(
        description=(
            "The work item that does it, the latest named for it on its "
            "`add_item`; null while none is"
        )
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
    in_chat: ChatPlaceSchema | None = Field(
        description=(
            "Where the answer was recorded in a chat (F42.3): the record of the "
            "latest `answered` effect on the block; null unless `via` is `chat` "
            "and that effect's call ran in a chat"
        )
    )
    done: datetime | None = Field(description="When the action was marked Done")
    claim: ClaimSchema | None = Field(
        description=(
            "Pilot does it: the action's claim, `answer: Pilot does it`, `by` "
            "Pilot, until its Done; null for every other block"
        )
    )
    deferral: DeferralSchema | None = Field(
        description="Where a deferred block went; null unless `answer` is `deferred`"
    )
    writer_asked: bool = Field(
        description=(
            "Whether Pilot asked the registered document's writer about the block "
            "(F52.2), which its line says; false for every other block"
        )
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
    """A file hung on an item, or a draft's on none, reader's material (F36),
    which its stream `/api/attachments/<id>` serves without its title or
    stored type."""

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


class LineStepSchema(BaseModel):
    """The latest tool call of a current line."""

    tool: str | None = Field(description="The call's `name`", examples=["Read"])
    input: Any = Field(
        description=(
            "The call's `input`, as the line has it; null while it streams in, "
            "before the call's line"
        ),
        examples=[{"file_path": "/work/Camp/plan.json"}],
    )


class LineAgentSchema(BaseModel):
    """The sub-agent a current line waits on, from its `Task` call."""

    type: str | None = Field(
        description="The call's `subagent_type`", examples=["Explore"]
    )
    description: str | None = Field(
        description="The call's `description`", examples=["Survey the tent makers"]
    )


class CurrentLineSchema(BaseModel):
    """A work item's one current line while a turn of its Session is in flight,
    which the client words as it words the chat's cue (F26.2; design 2 §9.5)."""

    state: Literal["starting", "thinking", "writing", "working", "waiting"] = Field(
        description=(
            "What the turn is doing: the session coming up, thinking, writing a "
            "main-thread text block, running a tool call, or waiting on a sub-agent"
        )
    )
    since: datetime = Field(description="When that state, or the latest step, began")
    step: LineStepSchema | None = Field(
        description="The latest tool call; null before the first"
    )
    agent: LineAgentSchema | None = Field(
        description="The sub-agent; null unless `state` is `waiting`"
    )
    text: str | None = Field(
        description=(
            "The server's own words while the session comes up, or comes back "
            "while its environment restarts; null unless `state` is `starting`"
        ),
        examples=["Starting Camp-1…", "Camp-1 is restarting…"],
    )


class RetriedSchema(BaseModel):
    """The job a person's Retry of a failed or stopped job placed."""

    id: uuid.UUID = Field(description="The new job's work item")
    at: datetime = Field(description="When Retry was pressed, the new job placed")


class WorkSchema(BaseModel):
    """A work item's Session, as its line and its head show it (F26, F12)."""

    state: SessionState = Field(
        description=(
            "Its Session's state: `held` while the gate holds its start, `starting` "
            "while it comes up, `running` while a turn is in flight, `idle` once its "
            "turn ended, `stopped` and `failed` waiting on you, `ended` once its "
            "controller session is gone"
        )
    )
    current_line: CurrentLineSchema | None = Field(
        description="Its one current line; null while no turn is in flight"
    )
    environment: EnvironmentNameSchema | None = Field(
        description=(
            "The environment it runs in, as its row stands: its env chip and the "
            "chip's link; null until its start provides one"
        )
    )
    started_at: datetime | None = Field(
        description=(
            'When its run began, which "running N min" counts from: the '
            "controller confirmed its session, or took its Resume's turn; null "
            "before"
        )
    )
    error: str | None = Field(
        description=(
            "Why it failed: a failed start's error, or the error its latest turn "
            "ended in; null unless `state` is `failed` (F125)"
        )
    )
    autopilot: bool = Field(
        description="The auto pilot setting its start was briefed under (F4.3)"
    )
    pilots_own: bool = Field(
        description=(
            "Whether it is Pilot's own work, a background job in the store "
            "(F59.1): its line has its session log and neither an environment "
            "chip nor Stop / Resume, which the server refuses (F26.3), and "
            "Retry once it failed or stopped until it is retried; false for a "
            "worker's run"
        )
    )
    held_reason: HeldReason | None = Field(
        description=(
            "Why the gate holds its start, which its line says: a work "
            "item's the week's or the five-hour usage halt, its project "
            "paused, the controller unreachable, no slot free, or, a job's, "
            "another job of its project before it; null unless `state` is "
            "`held`, and while the gate opens for it (F26.1, F141.5, F143.4, "
            "F59.2, F135.1, F135.4)"
        )
    )
    held_running: int | None = Field(
        description=(
            "The running work items that leave it no slot, which its line "
            'counts, "Waiting for a slot · N running": those across every '
            "project, or its project's own, whichever maximum closed the "
            "gate; null unless `held_reason` is `slot` (F143.4)"
        )
    )
    stopped_at: datetime | None = Field(
        description=(
            'When it was stopped, its "Stopped · <time>"; null unless `state` is '
            "`stopped` (F26.1, F69.2)"
        )
    )
    stopped_by: UserSchema | None = Field(
        description=(
            "Who stopped it, by Stop, Finish or Archive, or Pilot, through its "
            "tool or a usage halt's hard stop; null when no one of Pilot's "
            "did, and unless `state` is `stopped` (F69.2, F135.6)"
        )
    )
    stopped_cause: StopCause | None = Field(
        description=(
            "Why it stopped, which its stopped line and its session log's "
            "tail say: its environment stopped under it, a stop made "
            "elsewhere, stopped, being deleted, gone, or in error; or a usage "
            "halt's hard stop, by Pilot, its nudge owed, the halt that holds "
            "it now, the week's or the five-hour's, or `usage_limit` once "
            "neither does; null when someone stopped it otherwise, and unless "
            "`state` is `stopped` (F26.1, F69.2, F71, F135.6)"
        )
    )
    retried: RetriedSchema | None = Field(
        description=(
            "The job a person's Retry of this failed or stopped job placed, at "
            "the project's next place, which its line names: it offers Retry no "
            "more, and no badge counts it (F94.5); null while it is not retried"
        )
    )


class WriterQuestionSchema(BaseModel):
    """A question Pilot asked a registered document's writer about one of its
    blocks (F52.2), with the writer's answer to it."""

    block: str = Field(description="The asked block's local id", examples=["D2"])
    question: str = Field(
        description="The question, verbatim",
        examples=["Which cache does 'the cache' mean?"],
    )
    asked_at: datetime = Field(description="When it was asked")
    heading: str = Field(
        description=(
            "The heading the clarification run asked the writer to answer it "
            "under, as its first turn wrote it: `## <local id>`, or `## <path> "
            "<local id>` where another document asked about has a block of that "
            "local id"
        ),
        examples=["## D2"],
    )
    reply: str | None = Field(
        description=(
            "The writer's reply under that heading, to the next heading of the "
            "same or a higher level; null until the reply comes, and where it does "
            "not keep the heading or holds nothing under it"
        ),
        examples=["The OpenAPI cache the frontend reads."],
    )


class ClarificationSchema(BaseModel):
    """One pre-ruling pass's questions to a registered document's writer and
    the writer's reply, which the overlay shows as one section, "Pilot asked
    the writer · <stamp>" (F52.2; DB 257)."""

    asked_at: datetime = Field(
        description="The section's stamp: when the pass first asked about the document"
    )
    questions: list[WriterQuestionSchema] = Field(
        description="The questions, in their blocks' order"
    )
    reply: str | None = Field(
        description=(
            "The writer's reply, whole: the clarification run's turn's final text, "
            "which may answer other documents' questions too; null until its turn "
            "ends with one"
        )
    )
    replied_at: datetime | None = Field(
        description="When the reply came, the run's turn's end; null until it does"
    )
    split: bool = Field(
        description=(
            "Whether the reply kept the asked shape, every question's `reply` "
            "holding its part: shown per block, else whole; false while there is "
            "no reply"
        )
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
        description=(
            "The opening's author (F18.1), and Pilot for an archive question, the "
            "server's at a finish (F5.6); null for every other item"
        )
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
            "The text's own words past its front matter, every block's included "
            "but its answer lines, whatever a display collapses and whatever is "
            "answered: under about 150 a document draws inline, "
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
    awaiting_read: bool = Field(
        description=(
            "Whether it is a registered document whose file has not been read yet: "
            "it is read at the end of the turn that registered it, and until then "
            "it has no text, `body` is null, and it takes no close (F85.1)"
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
    asked_writer_about: list[str] = Field(
        description=(
            "The local ids of the blocks Pilot asked a registered document's "
            'writer about, in their order, which its line names: "Pilot asked the '
            'writer about D2 and D4" (F86.8); empty for every other item'
        ),
        examples=[["D2", "D4"]],
    )
    clarifications: list[ClarificationSchema] = Field(
        description=(
            "Pilot's questions to a registered document's writer and the "
            "writer's reply (F52.2): one per pre-ruling pass that asked about its "
            "blocks, in the order first asked; empty for every other item"
        )
    )
    work: WorkSchema | None = Field(
        description=(
            "A work item's Session, which the SSE event `work_moved` carries as it "
            "moves; null for every other kind"
        )
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
    ready_after: uuid.UUID | None = Field(
        description=(
            "The setup's work item, under which the line \"The project is ready — "
            'resume the project to start it." stands: while the project is open '
            "and paused by the pause Create project wrote, Pilot's `paused` right "
            "after `opened` with no `resumed` since, and its setup, its latest "
            "Retry's where it was retried, is done at its turn's end (D083); null "
            "otherwise, a person's pause included"
        )
    )
    unhung_attachments: list[AttachmentSchema] = Field(
        description=(
            "The attachments hung on no item, by batch and file name: a draft's "
            "material, attached in its definition chat, until Create project hangs "
            "it on the opening (F36.6, F46.3); none past Create"
        )
    )


class ItemDocumentSchema(TimelineItemSchema):
    """An item's document read on its own, as the overlay draws it (F28): its
    timeline entry, but that a document done by Done reads as Done fixed it
    (F13.3), its `title`, `summary`, `body`, `word_count` and `read_minutes`
    from the text of its `done` Version."""

    project_id: uuid.UUID = Field(description="The project whose timeline holds it")


class ProjectDocumentSchema(BaseModel):
    """The project's draft, `project.md`, or its handbook, `handbook.md`,
    read only, as the overlay draws it (F37.4, F129.4)."""

    title: str | None = Field(
        description=(
            "The text's title, from its front matter or its first heading; null "
            "where it gives none"
        ),
        examples=["Recipe box"],
    )
    body: list[BodyPartSchema] = Field(
        description=(
            "Its text as drawn: its prose parts and blocks in order, without the "
            "front matter and a first heading that is its title; empty for a text "
            "with nothing more, as the handbook is born (F129.2), which the "
            "screens show as *Empty*"
        )
    )
    writing: bool = Field(
        description=(
            "Whether a session's running turn is saving the text, which Pilot's "
            "dots show at its end (F35); cleared at the turn's end, which no live "
            "event announces"
        )
    )
