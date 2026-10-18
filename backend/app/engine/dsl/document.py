"""What the block DSL reads out of a document's text (FM §4, design 1 §6.1).

Every line number is the file's, counted from 1.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class BlockKind(StrEnum):
    """The grammar's block kinds; their values are Block Kind's (DB §2.4)."""

    DECISION = "decision"
    QUESTION = "question"
    ACTION = "action"


@dataclass(frozen=True)
class Span:
    """The lines from `first` to `last`, both included."""

    first: int
    last: int


@dataclass(frozen=True)
class Fault:
    """One fault of a save, worded as the hook prints it; `line` is none for a
    fault of the document as a whole."""

    line: int | None
    message: str


@dataclass(frozen=True)
class Option:
    label: str
    text: str | None
    recommended: bool
    line: int


@dataclass(frozen=True)
class Block:
    """A fence whose info string names a block kind and its `id`.

    `lines` holds the span of every key of the body, by key. A value the
    grammar refuses is read as none, and its fault is the document's.
    """

    local_id: str
    kind: BlockKind
    fence: Span
    lines: Mapping[str, Span]
    confirmation: bool = False
    because: str | None = None
    proposal: str | None = None
    default: str | None = None
    check: str | None = None
    options: tuple[Option, ...] = ()
    answer: str | None = None
    by: str | None = None
    at: datetime | None = None
    note: str | None = None
    via: str | None = None
    to: str | None = None
    done: datetime | None = None


@dataclass(frozen=True)
class FrontMatter:
    """The front matter's keys the record reads; `span` covers both `---`
    lines, and is none for a document without front matter."""

    span: Span | None = None
    lines: Mapping[str, Span] = field(default_factory=dict)
    title: str | None = None
    summary: str | None = None
    step: str | None = None
    urgent: bool = False
    addressee: str | None = None
    slug: str | None = None


@dataclass(frozen=True)
class ParsedDocument:
    """A document's front matter, title and blocks, and the faults its text
    holds on its own: those that need the record are `validate()`'s.

    `title_heading_line` is the line of the first heading where that heading
    is the title, which a display strips from the body (decision 32).
    """

    front_matter: FrontMatter
    title: str | None
    title_heading_line: int | None
    blocks: tuple[Block, ...]
    faults: tuple[Fault, ...]
