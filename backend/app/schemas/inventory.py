"""Pilot's inventory: what a collector's walk compares the fleet's home
against (F152.2).

Each Transcript Pilot holds, by the ids a publication names it by, with its
collection record as its last publication left it; and the walk's two
settings, which the server holds.
"""

from pydantic import AwareDatetime, BaseModel, Field

from app.schemas.publication import Name, Size


class HeldTranscriptSchema(BaseModel):
    """A Transcript as Pilot holds it: what an appended publication of its
    file builds on, and how much of the file its last whole one read."""

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
