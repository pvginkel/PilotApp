"""What `pilot-projects` reads that no screen does (F150.5, F150.8): the index
of a project's `timeline.json`, and the tree's files, listed, found and read
as text.

Both are the tree as the record renders it (`TreeService`, `ViewService`),
never the store's disk, so a read is answered whether the store runs or not,
and an archived project's folder is no part of it. The file reads are
KubeCoder's fleet adapter's, one for one: its listing's order, its glob, its
numbered lines and its limits. A refusal ends with the adapter's name for it
in brackets, and its words are the outside's, since a session anywhere in the
fleet reads them.
"""

import hashlib
import json
from dataclasses import dataclass

from app.engine.paths import tree_path
from app.engine.tree import TreeService
from app.engine.views import ViewService
from app.exceptions import (
    InvalidOperationException,
    RecordNotFoundException,
    ValidationException,
)
from app.models import Project
from app.utils.path_glob import GlobSyntaxError, PathGlob

READ_MAX_BYTES = 128 * 1024
"""The most a read answers: a whole file's bytes, or a range's or a tail's
numbered content."""
READ_MAX_LINES = 2000
"""The most lines a range or a tail answers."""


@dataclass(frozen=True)
class IndexedItem:
    """An item as `timeline.json`'s index holds it, its `path` from the
    tree's root; `created_at` is the file's own stamp."""

    seq: int
    kind: str
    title: str | None
    path: str | None
    created_at: str
    done_cause: str | None
    for_handle: str | None
    urgent: bool


@dataclass(frozen=True)
class TreeEntry:
    """A file or a directory of a directory, its path from the tree's root; a
    directory's ends with `/`."""

    path: str
    is_directory: bool


@dataclass(frozen=True)
class TreeText:
    """A file read as text: the numbered lines, the whole file's hash and
    line count, and whether a range or a tail was cut at a limit."""

    content: str
    sha256: str
    total_count: int
    limit_hit: bool
    line_cut: bool


class TreeReadService:
    def __init__(self, tree_service: TreeService, view_service: ViewService) -> None:
        self.tree_service = tree_service
        self.view_service = view_service

    def items(
        self, project: Project, open_only: bool, kind: str | None
    ) -> list[IndexedItem]:
        """The index of the project's `timeline.json` as it is rendered now,
        a row per item in `seq` order: the open items alone with `open_only`,
        and those of `kind` alone where one is given."""
        index = json.loads(self.view_service.timeline(project).text)["items"]
        return [
            IndexedItem(
                seq=item["seq"],
                kind=item["kind"],
                title=item["title"],
                path=None if item["path"] is None else tree_path(project, item["path"]),
                created_at=item["created_at"],
                done_cause=None if item["done"] is None else item["done"]["cause"],
                for_handle=item["for"],
                urgent=item["urgent"],
            )
            for item in index
            if (item["done"] is None or not open_only)
            and (kind is None or item["kind"] == kind)
        ]

    def entries(self, path: str) -> list[TreeEntry]:
        """What the directory at `path` holds, directories first, each group
        in case-insensitive name order. The tree holds files alone: a
        directory is one a file's path runs through, and the root, the empty
        path.

        Raises:
            ValidationException: the path leaves the tree.
            InvalidOperationException: the path is a file's.
            RecordNotFoundException: nothing is at the path.
        """
        directory = _normal(path)
        paths = self.tree_service.paths()
        prefix = f"{directory}/" if directory else ""
        under = [found[len(prefix) :] for found in paths if found.startswith(prefix)]
        if not under:
            if directory in paths:
                raise InvalidOperationException(
                    f"list {path!r}", "it is a file, not a folder [not-a-directory]"
                )
            raise RecordNotFoundException("Folder", repr(path))
        directories = {rest.partition("/")[0] for rest in under if "/" in rest}
        files = [rest for rest in under if "/" not in rest]
        return [
            TreeEntry(f"{prefix}{name}/", True)
            for name in sorted(directories, key=_name_order)
        ] + [
            TreeEntry(f"{prefix}{name}", False)
            for name in sorted(files, key=_name_order)
        ]

    def matches(self, pattern: str) -> list[str]:
        """The files whose path from the tree's root matches the glob
        `pattern`, in path order.

        Raises:
            ValidationException: the pattern uses glob syntax that is not
                supported, or starts with `/`, where no path does.
        """
        try:
            glob = PathGlob(pattern)
        except GlobSyntaxError as exc:
            raise ValidationException(f"{exc} [validation-error]") from exc
        if pattern.startswith("/"):
            raise _outside("Pattern", pattern)
        return [path for path in self.tree_service.paths() if glob.matches(path)]

    def text(
        self,
        path: str,
        start_line: int | None,
        end_line: int | None,
        tail_lines: int | None,
    ) -> TreeText:
        """The file at `path` as text, its lines numbered: whole up to
        `READ_MAX_BYTES`; or the lines `start_line` to `end_line`, 1-based
        and inclusive, kept from the range's start; or its last `tail_lines`,
        kept from the file's end; a range and a tail cut at `READ_MAX_LINES`
        lines and `READ_MAX_BYTES` of content.

        Raises:
            ValidationException: a tail is asked with a range, or the path
                leaves the tree.
            InvalidOperationException: the path is a directory's; the file is
                not UTF-8 text; or it is read whole and is over
                `READ_MAX_BYTES`.
            RecordNotFoundException: nothing is at the path.
        """
        if tail_lines is not None and (start_line is not None or end_line is not None):
            raise ValidationException(
                "Pass either `tail_lines` or `start_line` and `end_line`, not both:"
                " a tail is the file's last lines, a range the lines between two"
                " numbers"
            )
        raw = self._bytes(path)
        operation = f"read {path!r}"
        text = _decode_text(raw)
        if text is None:
            raise InvalidOperationException(
                operation,
                "it is not UTF-8 text, and a read answers text alone [not-text]",
            )
        lines = _lines(text)
        if tail_lines is not None:
            content, limit_hit, line_cut = _capped(
                lines, max(1, len(lines) - tail_lines + 1), len(lines), keep_end=True
            )
        elif start_line is not None or end_line is not None:
            last = len(lines) if end_line is None else min(end_line, len(lines))
            content, limit_hit, line_cut = _capped(
                lines, start_line or 1, last, keep_end=False
            )
        elif len(raw) > READ_MAX_BYTES:
            raise InvalidOperationException(
                f"{operation} whole",
                f"it is {len(raw)} bytes and {len(lines)} lines, over the"
                f" {READ_MAX_BYTES}-byte (128 KB) limit of a whole read: ask for a"
                " line range with `start_line` and `end_line`, or the last lines"
                f" with `tail_lines`; either answers at most {READ_MAX_LINES} lines"
                " and 128 KB [file-too-large]",
            )
        else:
            content = "".join(
                _numbered(number, line) for number, line in enumerate(lines, 1)
            )
            limit_hit = line_cut = False
        return TreeText(
            content=content,
            sha256=hashlib.sha256(raw).hexdigest(),
            total_count=len(lines),
            limit_hit=limit_hit,
            line_cut=line_cut,
        )

    def _bytes(self, path: str) -> bytes:
        """The bytes of the file at `path`, one of the tree's paths."""
        file = _normal(path)
        paths = self.tree_service.paths()
        if file not in paths:
            if not file or any(found.startswith(f"{file}/") for found in paths):
                raise InvalidOperationException(
                    f"read {path!r}", "it is a folder, not a file [not-a-file]"
                )
            raise RecordNotFoundException("File", repr(path))
        return self.tree_service.read(file).content


def _outside(what: str, path: str) -> ValidationException:
    return ValidationException(
        f"{what} {path!r} is outside the projects' files: a path runs from their"
        " root, as `<folder>/timeline.json` does, never from `/` and never above"
        " it [path-outside-projects]"
    )


def _normal(path: str) -> str:
    """`path` from the tree's root, its empty and `.` segments dropped and
    each `..` taken; the root is the empty path.

    Raises:
        ValidationException: the path starts at `/` or climbs above the root.
    """
    if path.startswith("/"):
        raise _outside("Path", path)
    kept: list[str] = []
    for segment in path.split("/"):
        if segment in ("", "."):
            continue
        if segment != "..":
            kept.append(segment)
        elif kept:
            kept.pop()
        else:
            raise _outside("Path", path)
    return "/".join(kept)


def _name_order(name: str) -> tuple[str, str]:
    return name.casefold(), name


def _decode_text(raw: bytes) -> str | None:
    """The file's text, or None when it is not text: not UTF-8, or holding a
    NUL byte."""
    if b"\0" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _lines(text: str) -> list[str]:
    """`text` split on newline, a final newline ending the last line rather
    than opening another."""
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


def _numbered(number: int, line: str) -> str:
    """One line as the content holds it: `N: line` ending in a newline."""
    return f"{number}: {line}\n"


def _cut_line(number: int, line: str, keep_end: bool) -> str:
    """Line `number`, over the byte limit on its own, numbered and cut to fit
    it: its start, or its end when `keep_end`, on a character boundary."""
    budget = READ_MAX_BYTES - len(_numbered(number, "").encode())
    raw = line.encode()
    kept = raw[len(raw) - budget :] if keep_end else raw[:budget]
    # A byte slice of valid UTF-8 is invalid only in the one character it
    # splits.
    return _numbered(number, kept.decode("utf-8", errors="ignore"))


def _capped(
    lines: list[str], first: int, last: int, keep_end: bool
) -> tuple[str, bool, bool]:
    """Lines `first` to `last`, 1-based and inclusive, numbered and cut to
    `READ_MAX_LINES` lines and `READ_MAX_BYTES` of content, from the range's
    start, or from its end when `keep_end`. Returns the content, whether it
    was cut, and whether its one line was cut because that line alone is over
    the byte limit."""
    numbers = range(first, last + 1)
    kept: list[str] = []
    size = 0
    for number in reversed(numbers) if keep_end else numbers:
        if len(kept) == READ_MAX_LINES:
            break
        rendered = _numbered(number, lines[number - 1])
        cost = len(rendered.encode())
        if size + cost > READ_MAX_BYTES:
            if not kept:
                return _cut_line(number, lines[number - 1], keep_end), True, True
            break
        kept.append(rendered)
        size += cost
    if keep_end:
        kept.reverse()
    return "".join(kept), len(kept) < len(numbers), False
