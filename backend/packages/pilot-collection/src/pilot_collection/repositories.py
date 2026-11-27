"""The Repositories Pilot holds, as a collector reads them from its clones of
the mirror: the calls' shapes (F152.11, F158.4; DB §2.9, assertions 577 and
578).

Pilot is the cursor (F152.1): it hands a collector every Repository it holds,
each with the hash of every Commit a read of it gave, so that the collector
reads from its clone only the commits Pilot lacks, a restart included. A read
of one Repository carries those commits, each with its whole hash, its
author's time, its subject and its lines per file under git's rename
detection, and when they were read.
"""

from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from pilot_collection.publication import Count, FilePath, Name

WholeSha = Annotated[str, StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
"""A commit's whole hash as git prints it, SHA-1's or SHA-256's."""


class HeldRepositorySchema(BaseModel):
    """A Repository Pilot holds, and what a read of it gave."""

    name: Name = Field(description="The name of its checkout under `/work`")
    read: list[WholeSha] = Field(
        description=(
            "The whole hash of every Commit a read of it gave, in their order:"
            " a commit of its history not here is one Pilot lacks"
        )
    )


class RepositoriesSchema(BaseModel):
    """Every Repository Pilot holds."""

    repositories: list[HeldRepositorySchema] = Field(
        description="Every Repository Pilot holds, by name"
    )


class _Read(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadFileChangeSchema(_Read):
    """A change one commit made to one file, as git's rename detection
    gives it: a moved file's on its new path, a deleted file's lines as
    removed."""

    path: FilePath = Field(description="The file's path within the repository")
    lines_added: Count = Field(description="The lines the commit added to it")
    lines_removed: Count = Field(description="The lines the commit removed from it")


class ReadCommitSchema(_Read):
    """A commit of the Repository's history, as its clone gives it."""

    sha: WholeSha = Field(description="Its whole hash")
    made_at: AwareDatetime = Field(
        description="Its author's time, which a rebase keeps"
    )
    subject: str = Field(description="Its message's first line, as `%s` gives it")
    files: list[ReadFileChangeSchema] = Field(
        description="Its changes, one per file; none for a merge commit"
    )


class RepositoryReadSchema(_Read):
    """What a read of one Repository's clone gave: the commits Pilot
    lacked."""

    repository: Name = Field(description="The Repository's name, as Pilot holds it")
    read_at: AwareDatetime = Field(description="When their lines were read")
    commits: list[ReadCommitSchema] = Field(description="The commits read")
