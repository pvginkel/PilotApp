"""Schemas for `pilot-work`'s routes, the REST calls Pilot's MCP server makes
for a worker session's tools (TD §4.5)."""

import uuid
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models.reference import ProgressState

MAX_STEP_CODE = 64
MAX_STEP_LABEL = 120
MAX_STEP_WHY = 120
MAX_STEPS = 100
MAX_STEP_KIND = 64
MAX_STEP_DURATION = 2**31 - 1
MAX_STEP_CONVERSATION = 64
MAX_STEP_CONVERSATIONS = 100
"""The limits of a work item's list of steps (F85.3, DB 327), which the
schema of `progress_steps`, `step_kinds` and `step_transcripts` does not
hold; `MAX_STEP_DURATION` is the range of `step_timings.duration`."""

Conversation = Annotated[
    str, StringConstraints(min_length=1, max_length=MAX_STEP_CONVERSATION)
]
"""Claude Code's session id of a conversation a step names."""

MAX_DEBRIEF = 16_000
MAX_DEBRIEF_ENTRIES = 500
MAX_ENTRY_SECTION = 120
MAX_ENTRY_ROLE = 64
MAX_ENTRY_WORDS = 4_000
MAX_ENTRY_WHY = 120
MAX_ENTRY_NUMBER = 2**31 - 1
MAX_DEBRIEF_SUBJECT = 120
MAX_DEBRIEF_FIGURES = 8_000
"""The limits of a work item's debrief (DB 325, 608, 635), which the schema of
`work` and `debrief_entries` does not hold; `MAX_ENTRY_NUMBER` is the range of
the columns of a round and a duration."""


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


class AttachFileRequestSchema(BaseModel):
    """Material a worker wrote, to copy into the record."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        min_length=1,
        description=(
            "The file's or the folder's absolute path in the session's"
            " environment, under `/work`: a folder's every file under it"
        ),
        examples=["/work/Example/docs/survey"],
    )
    to: uuid.UUID | None = Field(
        default=None,
        description=(
            "The id of the item the material backs, of the session's project;"
            " without it, the session's own work item"
        ),
        examples=["0f8a1c2e-5b7d-4e3a-9c61-2d4f8b0e7a15"],
    )


class AttachedFilesSchema(BaseModel):
    """The attachments the material was copied into."""

    ids: list[uuid.UUID] = Field(
        description="Their ids, a folder's in its files' path order",
        examples=[["5c2e9a1f-7b3d-4f6e-8a20-1d9c4b7e3f58"]],
    )


class ProgressStepRequestSchema(BaseModel):
    """A step of the list, as the call gives it."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        min_length=1,
        max_length=MAX_STEP_CODE,
        description="The run's name for the step, unique in the list",
        examples=["P3.review-2"],
    )
    label: str = Field(
        min_length=1,
        max_length=MAX_STEP_LABEL,
        description="The step's words on the tile",
        examples=["P3 · second review"],
    )
    state: ProgressState | None = Field(
        default=None,
        description=(
            "Where the step stands; without it, a code on the list keeps its"
            " state and a new one starts `pending`"
        ),
        examples=["active"],
    )
    why: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_STEP_WHY,
        description=(
            "A short line shown under the step's label; without it, the step has none"
        ),
        examples=["The reviewer found the migration's downgrade left the column"],
    )
    kind: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_STEP_KIND,
        description=(
            "The kind the workflow gives the step, stored and shown as given;"
            " without it, the step has none"
        ),
        examples=["code-writer"],
    )
    duration: int | None = Field(
        default=None,
        ge=0,
        le=MAX_STEP_DURATION,
        strict=True,
        description=(
            "On a step the call leaves `done`, the whole seconds its work took"
            " by the run's own measure"
        ),
        examples=[1440],
    )
    marked: bool | None = Field(
        default=None,
        strict=True,
        description=(
            "Whether the workflow holds the step to be in trouble; without it,"
            " the step has no mark"
        ),
        examples=[False],
    )
    conversations: list[Conversation] | None = Field(
        default=None,
        max_length=MAX_STEP_CONVERSATIONS,
        description=(
            "The conversations that did the step's work, each by Claude Code's"
            " session id; without it, the step names none"
        ),
        examples=[["6f1d2c9e-0b7a-4e58-9a31-5c8e2f4d7b06"]],
    )

    @field_validator("kind")
    @classmethod
    def _names_a_kind(cls, kind: str | None) -> str | None:
        """The store keeps a blank text as none
        (`app/utils/empty_string_normalization.py`)."""
        if kind is not None and not kind.strip():
            raise ValueError("a kind has words")
        return kind

    @field_validator("conversations")
    @classmethod
    def _names_each_once(cls, conversations: list[str] | None) -> list[str] | None:
        """A step names a conversation once (`step_transcripts`' key), and
        the store keeps a blank text as none."""
        for conversation in conversations or []:
            if not conversation.strip():
                raise ValueError("a conversation has an id")
        if conversations is not None and len(set(conversations)) < len(conversations):
            raise ValueError("a conversation is repeated")
        return conversations


class SetProgressRequestSchema(BaseModel):
    """The work item's list of steps, to replace the one standing."""

    model_config = ConfigDict(extra="forbid")

    steps: list[ProgressStepRequestSchema] = Field(
        max_length=MAX_STEPS,
        description="The steps in order; none removes the list",
    )


class SetProgressStepRequestSchema(BaseModel):
    """One step's state, to set."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        min_length=1,
        max_length=MAX_STEP_CODE,
        description="The code of a step on the list",
        examples=["P3.review-2"],
    )
    state: ProgressState = Field(
        description="Where the step stands now", examples=["done"]
    )


class ProgressStepSchema(BaseModel):
    """A step of the work item's list."""

    code: str = Field(
        description="The run's name for the step", examples=["P3.review-2"]
    )
    label: str = Field(
        description="The step's words on the tile", examples=["P3 · second review"]
    )
    state: ProgressState = Field(description="Where it stands", examples=["active"])
    why: str | None = Field(
        description="The short line under its label; none where not given",
        examples=["The reviewer found the migration's downgrade left the column"],
    )


class ProgressSchema(BaseModel):
    """The work item's list of steps as it stands."""

    steps: list[ProgressStepSchema] = Field(description="Its steps, in order")


class DebriefEntryRequestSchema(BaseModel):
    """One account of the debrief, as the call gives it: every value the
    run's, stored and shown as given (DB 325, 326)."""

    model_config = ConfigDict(extra="forbid")

    section: str = Field(
        min_length=1,
        max_length=MAX_ENTRY_SECTION,
        description="The name of the part of the run it ran in",
        examples=["P3 · The client"],
    )
    round: int = Field(
        ge=1,
        le=MAX_ENTRY_NUMBER,
        strict=True,
        description="Its round of that part, 1 or more",
        examples=[2],
    )
    role: str = Field(
        min_length=1,
        max_length=MAX_ENTRY_ROLE,
        description="Whose account it is",
        examples=["code-reviewer"],
    )
    duration: int = Field(
        ge=0,
        le=MAX_ENTRY_NUMBER,
        strict=True,
        description="The time its turn took, in whole seconds",
        examples=[540],
    )
    words: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_ENTRY_WORDS,
        description="The account, in its own words; none with `passed`",
        examples=["The review went quickly; one finding, and a fair one."],
    )
    passed: bool | None = Field(
        default=None,
        strict=True,
        description="A pass or a fail in place of words; none with `words`",
        examples=[False],
    )
    why: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_ENTRY_WHY,
        description="Why the round it opens was needed",
        examples=["The reviewer found the migration's downgrade left the column"],
    )

    @model_validator(mode="after")
    def _words_or_a_result(self) -> Self:
        if self.words is not None and self.passed is not None:
            raise ValueError("an entry gives at most one of words and passed")
        return self


class RegisterDebriefRequestSchema(BaseModel):
    """The work item's debrief, to store once."""

    model_config = ConfigDict(extra="forbid")

    debrief: str = Field(
        min_length=1,
        max_length=MAX_DEBRIEF,
        description="The session's own account of how the run went",
        examples=["It went well, if slowly: the second review was worth it."],
    )
    entries: list[DebriefEntryRequestSchema] = Field(
        min_length=1,
        max_length=MAX_DEBRIEF_ENTRIES,
        description="The run's accounts, in order",
    )
    subject: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_DEBRIEF_SUBJECT,
        description=(
            "What the debrief is an account of, as the workflow names it, compared"
            " whole within the project: one subject's debriefs come together in one"
            " notice, titled with it; none where not given"
        ),
        examples=["Slice 058 · The search page"],
    )
    completes: bool = Field(
        default=True,
        strict=True,
        description=(
            "Whether the debrief completes its subject's account; false where a"
            " later debrief of the same subject completes it, which takes a subject"
        ),
        examples=[False],
    )
    figures: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_DEBRIEF_FIGURES,
        description=(
            "The loop's figures as the workflow gives them, opaque text handed"
            " whole to the pass after the work item's turn and shown nowhere;"
            " none where not given"
        ),
        examples=["Phases: 8. Rounds: 11. Consults: 2. Duration: 4h 12m."],
    )

    @field_validator("debrief")
    @classmethod
    def _says_something(cls, debrief: str) -> str:
        """The store keeps a blank text as none
        (`app/utils/empty_string_normalization.py`), and a Work's entries
        stand only beside its debrief (DB 323)."""
        if not debrief.strip():
            raise ValueError("a debrief has words")
        return debrief

    @field_validator("subject")
    @classmethod
    def _names_something(cls, subject: str | None) -> str | None:
        """The store keeps a blank text as none, and a subject is not empty
        where given (DB 608)."""
        if subject is not None and not subject.strip():
            raise ValueError("a subject has words")
        return subject

    @field_validator("figures")
    @classmethod
    def _figures_say_something(cls, figures: str | None) -> str | None:
        """The store keeps a blank text as none, and the figures are not
        empty where given (DB 635)."""
        if figures is not None and not figures.strip():
            raise ValueError("the figures have words")
        return figures

    @model_validator(mode="after")
    def _a_debrief_left_to_a_later_one_names_its_subject(self) -> Self:
        if not self.completes and self.subject is None:
            raise ValueError("a debrief that does not complete names its subject")
        return self


class RegisteredDebriefSchema(BaseModel):
    """The debrief stored."""

    entries: int = Field(description="The number of its entries", examples=[36])
