"""The collector's clones of the Gitblit mirror (F152.11, F158.4): a bare
clone of each Repository Pilot holds, on the collector's own storage, and
the commits of its history that Pilot lacks, each with its whole hash, its
author's time, its subject and its lines per file.

A Repository's address on the mirror is `<url>/<owner>/<name>.git`, the URL
and the owners the settings'; the owners are tried in their order and the
first that holds it is cloned, with no credential. A clone is made in a
folder of its own and renamed into place once whole, so that one cut short
is never read; a clone held is fetched, every branch as the mirror has it.

Pilot is the cursor (F152.1): what is read of a Repository is every commit
of its clone's branches that Pilot does not list as read, all of them where
it lists none. A commit's lines per file are git's under its rename
detection: a moved file's on its new path, with the lines changed in it and
none where it only moved; a deleted file's as removed; a binary file's none;
and a merge commit has no change.
"""

import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pilot_collection.repositories import (
    HeldRepositorySchema,
    ReadCommitSchema,
    ReadFileChangeSchema,
    RepositoryReadSchema,
)

from pilot_collector.settings import Settings

GIT_SECONDS = 900.0
"""Seconds a call of git may take, a first clone of a whole history
included."""

READ_BYTES = 32_000_000
"""The bytes of commits past which a read of one Repository goes on in a
call of its own: Pilot refuses a body over its `MAX_UPLOAD_SIZE_MB`, 50 MB
by default."""

_FORMAT = "%H%x00%P%x00%aI%x00%s"
"""A commit's head as `git log -z` prints it: its whole hash, its parents,
its author's time and its subject, each ended by a NUL."""

_CHANGE = re.compile(rb"\n?(\d+|-)\t(\d+|-)\t(.*)", re.DOTALL)
"""A file's line of `--numstat -z`: its lines added and removed, `-` for a
binary file, and its path, which a rename leaves empty and gives as the
next two fields, the old path and the new."""

_SAID = 2_000
"""The characters of what git said that a message quotes."""

_ALONE = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
}
"""What git runs under: no configuration but a clone's own, so that what it
prints is what these calls ask for on any host, and no prompt, so that a
Repository that asks for a credential fails at once."""


class Unread(Exception):
    """A Repository's clone could not be made, fetched or read; the message
    says why."""


class Clones:
    """The bare clones of the mirror's Repositories, in the folder the
    settings name, each as `<name>.git`."""

    def __init__(self, settings: Settings) -> None:
        self._url = settings.COLLECTOR_MIRROR_URL.rstrip("/")
        self._owners = settings.COLLECTOR_MIRROR_OWNERS
        self._folder = settings.COLLECTOR_CLONES

    def read(self, held: HeldRepositorySchema) -> list[RepositoryReadSchema]:
        """The commits of the Repository's history that `held` does not
        list as read, its clone cloned or fetched first, oldest first, in as
        many reads as `READ_BYTES` splits them over; none where it lists
        every one.

        Raises:
            Unread: Its clone could not be made, fetched or read.
        """
        clone = self._fetched(held.name)
        read = set(held.read)
        new = [
            sha
            for sha in _git(clone, "rev-list", "--branches", "--reverse")
            .decode()
            .split()
            if sha not in read
        ]
        if not new:
            return []
        logged = _git(
            clone,
            "log",
            "--stdin",
            "--no-walk=unsorted",
            "-z",
            "--numstat",
            "--find-renames",
            "--diff-merges=off",
            f"--format={_FORMAT}",
            given="\n".join(new),
        )
        return reads(held.name, datetime.now(UTC), commits(logged))

    def _fetched(self, name: str) -> Path:
        """The Repository's clone, fetched where the folder holds it, else
        cloned from the first owner on the mirror that holds it.

        Raises:
            Unread: No owner holds it, or git failed.
        """
        if "/" in name or name in (".", ".."):
            raise Unread(f"`{name}` is no name of one folder")
        clone = self._folder / f"{name}.git"
        if clone.is_dir():
            _git(
                clone,
                "fetch",
                "--quiet",
                "--prune",
                "origin",
                "+refs/heads/*:refs/heads/*",
            )
            return clone
        partial = self._folder / f"{name}.git.partial"
        self._folder.mkdir(parents=True, exist_ok=True)
        failed: list[str] = []
        for owner in self._owners:
            shutil.rmtree(partial, ignore_errors=True)
            try:
                _git(
                    None,
                    "clone",
                    "--bare",
                    "--quiet",
                    "--",
                    f"{self._url}/{owner}/{name}.git",
                    str(partial),
                )
            except Unread as error:
                failed.append(f"{owner}: {error}")
                continue
            partial.rename(clone)
            return clone
        shutil.rmtree(partial, ignore_errors=True)
        raise Unread(f"no owner on the mirror holds it: {'; '.join(failed)}"[:_SAID])


def commits(logged: bytes) -> list[ReadCommitSchema]:
    """The commits `git log -z --numstat` printed, each's head under
    `_FORMAT`, in their order: a merge commit with no change."""
    fields = logged.split(b"\0")
    found: list[ReadCommitSchema] = []
    at = 0
    while at + 4 <= len(fields):
        sha, parents, made_at, subject = fields[at : at + 4]
        at += 4
        changes: list[ReadFileChangeSchema] = []
        while at < len(fields) and (change := _CHANGE.fullmatch(fields[at])):
            added, removed, path = change.groups()
            at += 1
            if not path:
                path = fields[at + 1]
                at += 2
            changes.append(
                ReadFileChangeSchema(
                    path=path.decode(errors="replace"),
                    lines_added=_lines(added),
                    lines_removed=_lines(removed),
                )
            )
        found.append(
            ReadCommitSchema(
                sha=sha.decode(),
                made_at=datetime.fromisoformat(made_at.decode()),
                subject=subject.decode(errors="replace"),
                files=[] if len(parents.split()) > 1 else changes,
            )
        )
    return found


def reads(
    repository: str,
    read_at: datetime,
    found: Sequence[ReadCommitSchema],
    budget: int = READ_BYTES,
) -> list[RepositoryReadSchema]:
    """The commits `found` of `repository`, read at `read_at`, in their
    order, as reads of at most `budget` bytes of commits each, a commit
    past it alone in one."""
    split: list[RepositoryReadSchema] = []
    batch: list[ReadCommitSchema] = []
    size = 0
    for commit in found:
        taken = len(commit.model_dump_json()) + 1
        if batch and size + taken > budget:
            split.append(
                RepositoryReadSchema(
                    repository=repository, read_at=read_at, commits=batch
                )
            )
            batch, size = [], 0
        batch.append(commit)
        size += taken
    if batch:
        split.append(
            RepositoryReadSchema(repository=repository, read_at=read_at, commits=batch)
        )
    return split


def _lines(count: bytes) -> int:
    """A numstat count of lines; none for a binary file's `-`."""
    return 0 if count == b"-" else int(count)


def _git(clone: Path | None, *arguments: str, given: str | None = None) -> bytes:
    """What git wrote to its stdout, run on `clone` where one is named, with
    `given` on its stdin.

    Raises:
        Unread: Git cannot be run, failed, or gave no answer within
            `GIT_SECONDS`.
    """
    command = ["git", *([] if clone is None else ["-C", str(clone)]), *arguments]
    try:
        done = subprocess.run(
            command,
            input=None if given is None else given.encode(),
            capture_output=True,
            timeout=GIT_SECONDS,
            check=False,
            env=os.environ | _ALONE,
        )
    except subprocess.TimeoutExpired:
        raise Unread(
            f"`git {arguments[0]}` gave no answer within {GIT_SECONDS:g} s"
        ) from None
    except OSError as error:
        raise Unread(f"git cannot be run: {error}") from error
    if done.returncode != 0:
        said = done.stderr.decode(errors="replace").strip().splitlines()
        raise Unread(
            f"`git {arguments[0]}` exited {done.returncode}:"
            f" {said[-1] if said else 'it wrote nothing to its stderr'}"[:_SAID]
        )
    return done.stdout
