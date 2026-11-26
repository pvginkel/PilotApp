"""Pilot's inventory: what a collector's walk compares the fleet's home
against, and what it hands the labeller (F152.2).

Each Transcript Pilot holds, by the ids a publication names it by, with its
collection record as its last publication left it and the labeller's version
and stamp its labels were written under; each conversation a Session of
Pilot's ran, collected or not, with what the labeller is handed with it
(`labeller.md` § What Pilot hands with a conversation); and the walk's two
settings, which the server holds.

The labeller's stamp covers what is handed with a conversation, its lists and
their order among it, so a conversation is handed in one form at every walk:
every list present, empty where Pilot holds nothing for it.
"""

import uuid

from pydantic import AwareDatetime, BaseModel, Field

from pilot_collection.publication import Name, Size


class HeldTranscriptSchema(BaseModel):
    """A Transcript as Pilot holds it: what an appended publication of its
    file builds on, how much of the file its last whole one read, and what
    its labels were written under."""

    session_id: Name = Field(description="Claude Code's id of the main thread")
    agent_id: Name | None = Field(
        description="Claude Code's id of the sub-agent, none on a main thread"
    )
    file_size: Size = Field(
        description="The file's size in bytes at its last publication"
    )
    file_modified_at: AwareDatetime = Field(
        description="The file's time at its last publication, to the microsecond"
    )
    replayed_size: Size = Field(
        description=(
            "The file's size in bytes at its last whole publication: short of"
            " `file_size` while appended publications were taken since"
        )
    )
    collector: Name = Field(
        description="The collector's version that read it at its last publication"
    )
    labeller: Name | None = Field(
        description=(
            "The labeller's own version that wrote its labels, whole; none"
            " while no labelling was published for it"
        ),
        examples=["1.0.0"],
    )
    stamp: Name | None = Field(
        description=(
            "The labeller's stamp handed back with its labels, of all it read"
            " for them besides the file; none where its last publication"
            " carried no labelling"
        )
    )


class SessionHoldSchema(BaseModel):
    """A period in which Pilot kept a Session from running."""

    kind: Name = Field(description="Its Hold Kind's code")
    started_at: AwareDatetime = Field(description="When it started")
    ended_at: AwareDatetime | None = Field(
        description="When it ended, none while it holds"
    )


class SessionTurnSchema(BaseModel):
    """A message Pilot sent a Session."""

    started_at: AwareDatetime = Field(description="When it was sent")
    cause: Name = Field(description="Its Turn Cause's code")


class HeldSessionSchema(BaseModel):
    """A Session of Pilot's on a conversation, as the labeller is handed it."""

    id: uuid.UUID = Field(description="Pilot's id of the Session")
    kind: Name = Field(description="Its Session Kind's code")
    created_at: AwareDatetime = Field(description="When Pilot made it")
    brief: str | None = Field(
        description=(
            "The first 400 characters of its first Turn that no person wrote;"
            " none while it has none"
        )
    )
    repo: str | None = Field(
        description="Its Work's repository, else its Project's; none where neither has one"
    )
    clarification: bool = Field(description="Whether its Work is a Clarification Run")
    holds: list[SessionHoldSchema] = Field(
        description="Its Holds, in the order they started"
    )
    turns: list[SessionTurnSchema] = Field(description="Its Turns, in the order sent")


class HeldDocumentSchema(BaseModel):
    """A Document a Session of the conversation put: one it registered, or
    one of Pilot's own it added."""

    id: uuid.UUID = Field(description="Pilot's id of the Document")
    session: uuid.UUID = Field(description="The Session that put it")
    source_path: str | None = Field(
        description="Where it was registered from, none for one of Pilot's own"
    )


class HeldConversationSchema(BaseModel):
    """What the labeller is handed with one conversation Pilot ran."""

    session_id: Name = Field(
        description="Claude Code's id of the conversation's main thread"
    )
    sessions: list[HeldSessionSchema] = Field(
        description="Pilot's Sessions on it, in `created_at` order"
    )
    documents: list[HeldDocumentSchema] = Field(
        description="The Documents those Sessions put, in the order they were made"
    )


class InventorySchema(BaseModel):
    """What Pilot holds, whole, and the walk's two settings."""

    walk_interval_seconds: float = Field(
        description="Seconds from one walk of the collector's to its next"
    )
    settling_seconds: float = Field(
        description=(
            "Seconds a file stands unchanged before a Transcript whose"
            " `replayed_size` is short of its `file_size` is published whole,"
            " its replay at rest"
        )
    )
    transcripts: list[HeldTranscriptSchema] = Field(
        description=(
            "Every Transcript Pilot holds, a main thread's and a sub-agent's,"
            " by `session_id`, a main thread before its sub-agents'"
        )
    )
    conversations: list[HeldConversationSchema] = Field(
        description=(
            "Every conversation a Session of Pilot's ran, collected or not, by"
            " `session_id`: their ids are the conversations the labeller's"
            " `pilot` header names; one not here Pilot ran no Session on"
        )
    )
