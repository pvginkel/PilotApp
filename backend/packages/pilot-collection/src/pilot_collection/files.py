"""The Files Pilot holds, and the classes the labeller gives them: the
calls' shapes (F158.5; DB §2.9, assertion 581).

A File is a Repository's and a path. Its class is the labeller's, from the
Repository's name and the path alone, none until it is classed; a collector
asks Pilot for the Files to class, every one or those with no class, and
hands back the class of each.
"""

from pydantic import BaseModel, ConfigDict, Field

from pilot_collection.publication import FilePath, Name


class HeldFileSchema(BaseModel):
    """A File Pilot holds."""

    repository: Name = Field(description="Its Repository's name")
    path: FilePath = Field(description="Its path within the repository")


class FilesQuerySchema(BaseModel):
    """Which Files: every one, or those with no class."""

    unclassed: bool = Field(
        default=False,
        description="True for the Files with no class; false for every File",
    )


class FilesSchema(BaseModel):
    """The Files asked for."""

    files: list[HeldFileSchema] = Field(
        description="Each File, by its Repository's name and its path"
    )


class FileClassSchema(BaseModel):
    """The class the labeller gives one File."""

    model_config = ConfigDict(extra="forbid")

    repository: Name = Field(description="The File's Repository's name")
    path: FilePath = Field(description="Its path within the repository")
    file_class: Name = Field(
        description="The File Class's code, one the labeller declares",
        examples=["code"],
    )


class FileClassesSchema(BaseModel):
    """The classes the labeller gave a collector's Files."""

    model_config = ConfigDict(extra="forbid")

    classes: list[FileClassSchema] = Field(description="Each File's class")
