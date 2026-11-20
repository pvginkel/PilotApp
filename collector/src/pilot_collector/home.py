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

A walk lists every transcript with a `stat` (F152.2), a regular file alone,
and follows no symlink: a sub-agent's file linked into another session's
folder is its own session's, where the walk meets the file itself. A
transcript found by its ids is one a walk lists.
"""

import errno
import logging
import os
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

logger = logging.getLogger(__name__)

PROJECTS = "projects"
"""The folder of the home that holds the transcripts."""

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
    """The regular files in the folders a transcript can lie in, from
    `folder` down, which is `depth` folders under `projects`: of a session's
    folder its `subagents` alone, and no symlink, pipe or device. A folder
    under `projects` gone since it was listed holds none, and so does one
    that cannot be listed, which is logged."""
    try:
        entries = os.scandir(folder)
    except OSError as error:
        if depth == 0:
            raise
        if not isinstance(error, FileNotFoundError):
            logger.warning(
                "The folder %s cannot be listed, so no transcript in it is: %s",
                folder,
                error,
            )
        return
    with entries:
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_file(follow_symlinks=False):
                yield entry
            elif entry.is_dir(follow_symlinks=False) and (
                depth != 2 or entry.name == _SUB_AGENTS
            ):
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


def _is_a_name(named: str) -> bool:
    """Whether an id can name one file or folder: it is one part of a
    path."""
    return named not in ("", ".", "..") and "/" not in named and "\0" not in named


def find(projects: Path, session_id: str, agent_id: str | None = None) -> Listed | None:
    """The transcript of those ids under `projects` as a walk lists it, with
    a `stat`: a main thread's or, with `agent_id`, a sub-agent's. None where
    the home has no file a walk lists under those ids.

    Raises:
        FileNotFoundError: There is no folder `projects`.
    """
    if not _is_a_name(session_id) or not (agent_id is None or _is_a_name(agent_id)):
        return None
    with os.scandir(projects) as folders:
        for folder in folders:
            if folder.is_symlink() or not folder.is_dir(follow_symlinks=False):
                continue
            if agent_id is None:
                found = _main_thread(projects, folder.path, session_id)
            else:
                found = _sub_agent(projects, folder.path, session_id, agent_id)
            if found is not None:
                return found
    return None


def _no_such_name(error: OSError) -> bool:
    """Whether a lookup by a name failed for there being no file of that
    name: none there, a file where a folder would be, or a name too long
    for one."""
    return error.errno in (errno.ENOENT, errno.ENOTDIR, errno.ENAMETOOLONG)


def _main_thread(projects: Path, folder: str, session_id: str) -> Listed | None:
    path = Path(folder, f"{session_id}{_SUFFIX}")
    try:
        status = os.lstat(path)
    except OSError as error:
        if _no_such_name(error):
            return None
        raise
    if stat.S_ISLNK(status.st_mode) or stat.S_ISDIR(status.st_mode):
        return None
    return Listed(
        Transcript(projects, path, session_id), status.st_size, modified_at(status)
    )


def _sub_agent(
    projects: Path, folder: str, session_id: str, agent_id: str
) -> Listed | None:
    session = os.path.join(folder, session_id)
    try:
        status = os.lstat(session)
    except OSError as error:
        if _no_such_name(error):
            return None
        raise
    if not stat.S_ISDIR(status.st_mode):
        return None
    for entry in _files(session, 2):
        found = transcript(projects, Path(entry.path))
        if found is None or found.agent_id != agent_id:
            continue
        try:
            status = entry.stat(follow_symlinks=False)
        except FileNotFoundError:
            return None
        return Listed(found, status.st_size, modified_at(status))
    return None


def saved_output(projects: Path, named: str) -> Path | None:
    """Where under `projects` the saved output lies that a result names as
    `named`, its path on the session's own home: by that path's last four
    parts, whatever the home's folder is there. None for a path that is no
    saved output's."""
    parts = PurePosixPath(named).parts[-4:]
    if len(parts) != 4 or parts[2] != _SAVED or {"/", ".."} & set(parts):
        return None
    return projects.joinpath(*parts)
