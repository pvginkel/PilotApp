"""Schemas for /api/tree: the store's tree as the record renders it, a
directory's entries, the files a glob matches and a file read as text
(F150.5)."""

from pydantic import BaseModel, Field

_PATH = (
    "from the tree's root, as `recipe-box/items/3-the-palette.md` is; one that "
    "starts with `/` or climbs above the root is refused"
)


class TreeEntriesQuerySchema(BaseModel):
    """The directory to list."""

    path: str = Field(
        default="",
        description=f"The directory's path {_PATH}; empty, the default, for the root",
        examples=["recipe-box/items"],
    )


class TreeEntrySchema(BaseModel):
    """A file or a directory of the tree."""

    path: str = Field(
        description="Its path from the tree's root; a directory's ends with `/`",
        examples=["recipe-box/items/"],
    )
    is_directory: bool = Field(description="Whether it is a directory")


class TreeEntriesSchema(BaseModel):
    """What a directory of the tree holds."""

    entries: list[TreeEntrySchema] = Field(
        description=(
            "Its directories, then its files, each group in case-insensitive name order"
        )
    )


class TreeMatchesQuerySchema(BaseModel):
    """The glob to match the tree's files against."""

    pattern: str = Field(
        min_length=1,
        description=(
            "A glob matched against each file's path from the tree's root: `*` any "
            "characters but `/`, `**` any path segments, `?` one character, "
            "`{a,b}` either alternative"
        ),
        examples=["**/timeline.json", "recipe-box/items/*.md"],
    )


class TreeMatchesSchema(BaseModel):
    """The files of the tree a glob matches."""

    paths: list[str] = Field(
        description="Each file's path from the tree's root, in path order"
    )


class TreeTextQuerySchema(BaseModel):
    """The file to read, and the lines of it."""

    path: str = Field(
        min_length=1,
        description=f"The file's path {_PATH}",
        examples=["recipe-box/timeline.json"],
    )
    start_line: int | None = Field(
        default=None, ge=1, description="The first line to read, from 1"
    )
    end_line: int | None = Field(
        default=None, ge=1, description="The last line to read, inclusive"
    )
    tail_lines: int | None = Field(
        default=None,
        ge=1,
        description="The count of the file's last lines to read; not with a range",
    )


class TreeTextSchema(BaseModel):
    """A file of the tree read as text."""

    content: str = Field(
        description="The lines read, each `N: line` under its number in the file",
        examples=["1: # Recipe box\n"],
    )
    sha256: str = Field(description="The SHA-256 of the whole file's bytes, in hex")
    total_count: int = Field(description="The count of the file's lines")
    limit_hit: bool = Field(
        description="Whether a range or a tail was cut at 2,000 lines or 128 KB"
    )
    line_cut: bool = Field(
        description=(
            "Whether the content is one line cut short, a line over 128 KB on its own"
        )
    )
