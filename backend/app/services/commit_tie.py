"""The tie of a commit held from its call to the commit its Repository's
history gives (F152.11, F158.4; DB assertion 577, decision 79.39), and the
Commit a CI Build built (DB §2.9, CI Build's `commit?`).

A commit read from the history completes the held one whose hash it starts
with; else the one whose subject it has and whose call its author's time lies
within the hour of, no more than an hour before the call was requested or
after it returned. A hash wins over a subject, and each is tied once: every
hash is settled before any subject, so that of an amended commit's two calls
the one whose hash matches has it. The rule is one, whichever of the two
arrived first: a read meets the held commits, a publication the read
Commits no Tool Call holds.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ScalarSelect, func, or_, select

from app.models import CIBuild, Commit

HOUR = timedelta(hours=1)
"""How far from its call a rebased commit's author's time may lie (DB
decision 79.39)."""


@dataclass(frozen=True)
class Held:
    """A commit held from its call, `key` naming it to the caller."""

    key: int
    sha: str | None
    subject: str
    requested_at: datetime
    returned_at: datetime | None


@dataclass(frozen=True)
class Read:
    """A commit its Repository's history gives, `key` naming it to the
    caller."""

    key: int
    sha: str
    subject: str
    made_at: datetime


def tie(held: Sequence[Held], read: Sequence[Read]) -> list[tuple[Held, Read]]:
    """Each held commit a read one completes, with it, all of one
    Repository. By hash, each read commit in its order takes the held one
    whose hash it starts with, the longest hash first; then by subject, each
    held commit left in its call's order takes the read one left of its
    subject made earliest within the hour of its call."""
    by_sha: dict[str, list[Held]] = {}
    for waiting in held:
        if waiting.sha is not None:
            by_sha.setdefault(waiting.sha, []).append(waiting)
    lengths = sorted({len(sha) for sha in by_sha}, reverse=True)
    tied: list[tuple[Held, Read]] = []
    taken: set[int] = set()
    left: list[Read] = []
    for made in read:
        named = next(
            (
                candidate
                for length in lengths
                for candidate in by_sha.get(made.sha[:length], [])
                if candidate.key not in taken
            ),
            None,
        )
        if named is None:
            left.append(made)
        else:
            tied.append((named, made))
            taken.add(named.key)

    by_subject: dict[str, list[Read]] = {}
    for made in sorted(left, key=lambda made: made.made_at):
        by_subject.setdefault(made.subject, []).append(made)
    for waiting in sorted(held, key=lambda waiting: waiting.requested_at):
        if waiting.key in taken:
            continue
        returned = waiting.returned_at or waiting.requested_at
        candidates = by_subject.get(waiting.subject, [])
        found = next(
            (
                candidate
                for candidate in candidates
                if waiting.requested_at - HOUR <= candidate.made_at <= returned + HOUR
            ),
            None,
        )
        if found is not None:
            candidates.remove(found)
            tied.append((waiting, found))
            taken.add(waiting.key)
    return tied


def built_commit() -> ScalarSelect[int]:
    """The id of the Commit the CI Build of the enclosing query built, by
    the hash its wait named, whichever of the two arrived first: one whose
    hash starts with it, or a held one whose abbreviated hash it starts
    with, a read one first; none where no Commit has that hash."""
    return (
        select(Commit.id)
        .where(
            Commit.sha.is_not(None),
            or_(
                func.starts_with(Commit.sha, CIBuild.commit_sha),
                func.starts_with(CIBuild.commit_sha, Commit.sha),
            ),
        )
        .order_by(Commit.lines_read_at.is_(None), Commit.id)
        .limit(1)
        .correlate(CIBuild)
        .scalar_subquery()
    )
