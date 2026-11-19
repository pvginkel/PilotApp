"""A transcript's file on the home: where Claude Code files a thread under
the home's `projects`, and the ids its place gives it.

A main thread's file is `<folder>/<session_id>.jsonl`, the folder named for
the directory the conversation began in. A sub-agent's is
`<folder>/<session_id>/subagents/agent-<agent_id>.jsonl`, and one a workflow
started lies deeper, under `subagents/workflows/<workflow>/`. Nothing else
under `projects` is a transcript: a workflow's `journal.jsonl`, a sub-agent's
`.meta.json` and the outputs saved under `tool-results/` among them.

An output too large for its result is saved as
`<folder>/<session_id>/tool-results/<name>`, beside the conversation's
sub-agents, and the result names it by its path as the session's own process
sees the home.

A walk lists every transcript with a `stat` (F152.2) and follows no symlink:
a sub-agent's file linked into another session's folder is its own
session's, where the walk meets the file itself.
"""

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

_EPOCH = datetime.fromtimestamp(0, UTC)

_SUFFIX = ".jsonl"
_SUB_AGENTS = "subagents"
_AGENT = "agent-"
_SAVED = "tool-results"


@dataclass(frozen=True)
class Transcript:
    """One thread's file: the home's `projects` it is filed under, its
    path, Claude Code's id of its conversation's main thread and, on a
    sub-agent's thread, of the sub-agent."""

    projects: Path
    path: Path
    session_id: str
    agent_id: str | None = None

    @property
    def name(self) -> str:
        """The transcript as a message names it."""
        if self.agent_id is None:
            return self.session_id
        return f"{self.session_id}/{self.agent_id}"


def transcript(projects: Path, path: Path) -> Transcript | None:
    """The transcript the file at `path` under `projects` is, by its place;
    none for a file that is no transcript's."""
    *folders, name = path.relative_to(projects).parts
    if not name.endswith(_SUFFIX):
        return None
    stem = name.removesuffix(_SUFFIX)
    if len(folders) == 1:
        return Transcript(projects, path, stem)
    if (
        len(folders) >= 3
        and folders[2] == _SUB_AGENTS
        and stem.startswith(_AGENT)
        and stem != _AGENT
    ):
        return Transcript(projects, path, folders[1], stem.removeprefix(_AGENT))
    return None


@dataclass(frozen=True)
class Listed:
    """A transcript as a walk lists it: its file's size and time by a
    `stat`."""

    transcript: Transcript
    file_size: int
    file_modified_at: datetime


def modified_at(status: os.stat_result) -> datetime:
    """A file's time as Pilot holds one: cut to the microsecond, the same
    at every `stat` of a file that did not change."""
    return _EPOCH + timedelta(microseconds=status.st_mtime_ns // 1000)


def _files(folder: str, depth: int) -> Iterator[os.DirEntry[str]]:
    """The files in the folders a transcript can lie in, from `folder` down,
    which is `depth` folders under `projects`: of a session's folder its
    `subagents` alone, and no symlink. A folder under `projects` gone since
    it was listed holds none."""
    try:
        entries = os.scandir(folder)
    except FileNotFoundError:
        if depth == 0:
            raise
        return
    with entries:
        for entry in entries:
            if entry.is_symlink():
                continue
            if not entry.is_dir(follow_symlinks=False):
                yield entry
            elif depth != 2 or entry.name == _SUB_AGENTS:
                yield from _files(entry.path, depth + 1)


def transcripts(projects: Path) -> list[Listed]:
    """Every transcript under `projects`, a main thread's and a sub-agent's,
    a workflow's among them, each with a `stat`. A file gone since its
    folder was listed is not on the home.

    Raises:
        FileNotFoundError: There is no folder `projects`.
    """
    listed: list[Listed] = []
    for entry in _files(str(projects), 0):
        found = transcript(projects, Path(entry.path))
        if found is None:
            continue
        try:
            status = entry.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue
        listed.append(Listed(found, status.st_size, modified_at(status)))
    return listed


def saved_output(projects: Path, named: str) -> Path | None:
    """Where under `projects` the saved output lies that a result names as
    `named`, its path on the session's own home: by that path's last four
    parts, whatever the home's folder is there. None for a path that is no
    saved output's."""
    parts = PurePosixPath(named).parts[-4:]
    if len(parts) != 4 or parts[2] != _SAVED or {"/", ".."} & set(parts):
        return None
    return projects.joinpath(*parts)
