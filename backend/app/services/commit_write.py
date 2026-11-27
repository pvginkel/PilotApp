"""The commits and the file edits a publication's Tool Calls made, written
with its facts in one transaction (F152.11, F158.4; DB §2.9, assertions 557
and 577 to 580).

A Commit held from its Tool Call and a File Edit are facts of the Tool Call:
the publication writes those of each Tool Call it names, only the rows that
differ, and they go with a Tool Call the file no longer names. A Commit read
from its Repository keeps what the read gave it: it stays the Commit of the
Tool Call whose call it was tied to while the call names it, by the rule
that tied them (`_tied`), and stays with no Tool Call once the call no longer
names it or the Tool Call goes. A commit a call names that a read gave
first, one no Tool Call holds, is tied to its Tool Call by the rule a read
ties by (`commit_tie`), whichever of the two arrived first; one whose hash
names a Commit another Tool Call holds is not held again, and is logged: a
Commit is made by one Tool Call once (DB 577).

A File is a Repository's and a path, made the first time a File Edit names
it, and never removed.
"""

import logging
from collections.abc import Sequence
from typing import Any

from pilot_collection.publication import (
    PublicationSchema,
    PublishedCallSchema,
    PublishedCommitSchema,
    PublishedToolCallSchema,
)
from sqlalchemy import (
    BigInteger,
    ColumnElement,
    Integer,
    Text,
    and_,
    any_,
    cast,
    delete,
    func,
    literal,
    or_,
    select,
    tuple_,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import Commit, File, FileEdit, Repository, ToolCall
from app.services.commit_tie import Held, Read, tie

logger = logging.getLogger(__name__)

EDITS = ("Edit", "Write")
"""The Tools whose successful call makes a File Edit (DB 579)."""

COMMITS_LOCK = 283
"""The advisory lock's class of the commits' turn: a read of a Repository's
history alone, a publication beside every other publication."""


def commits_turn(db: Session, *, read: bool = False) -> None:
    """Take the commits' turn, held until `db`'s transaction ends: a read's
    alone, so that what it ties no publication holds or removes meanwhile;
    a publication's beside every other publication's."""
    lock = func.pg_advisory_xact_lock if read else func.pg_advisory_xact_lock_shared
    db.execute(
        select(lock(cast(literal(COMMITS_LOCK), Integer), cast(literal(0), Integer)))
    )


def made_faults(publication: PublicationSchema) -> list[str]:
    """What in the call's commits and file edits contradicts the record's
    rules, each in a line: a file edit of a call that is no successful Edit
    or Write (DB 579), one file edited twice by one call, and one commit's
    hash given twice in the call (DB 577)."""
    found: list[str] = []
    made: set[tuple[str, str]] = set()
    for call in publication.calls:
        for requested in call.tool_calls:
            asked = f"call `{call.message_id}`: tool call `{requested.tool_use_id}`"
            if requested.file_edits and requested.tool not in EDITS:
                found.append(f"{asked}: a `{requested.tool}` call edits no file")
            elif requested.file_edits and requested.failed:
                found.append(f"{asked}: a failed call edits no file")
            edited: set[tuple[str, str]] = set()
            for edit in requested.file_edits:
                if (edit.repository, edit.path) in edited:
                    found.append(
                        f"{asked}: the file `{edit.path}` of `{edit.repository}`"
                        " is edited twice"
                    )
                edited.add((edit.repository, edit.path))
            for commit in requested.commits:
                if commit.sha is None:
                    continue
                if (commit.repository, commit.sha) in made:
                    found.append(
                        f"{asked}: the commit `{commit.sha}` of `{commit.repository}`"
                        " is given twice"
                    )
                made.add((commit.repository, commit.sha))
    return found


def _tied(
    row: Commit, wanted: list[PublishedCommitSchema], repositories: dict[str, int]
) -> PublishedCommitSchema | None:
    """The commit among its Tool Call's that a Commit read from its
    Repository is, by the rule that tied the two (DB 577): of its
    Repository, the one whose hash its own starts with, else the one whose
    subject it has; none where no commit is."""
    ours = [
        commit
        for commit in wanted
        if repositories[commit.repository] == row.repository_id
    ]
    by_sha = next(
        (
            commit
            for commit in ours
            if commit.sha is not None
            and row.sha is not None
            and row.sha.startswith(commit.sha)
        ),
        None,
    )
    if by_sha is not None:
        return by_sha
    return next((commit for commit in ours if commit.subject == row.subject), None)


class CommitWrite:
    """Writes a publication's commits and file edits, and the Repositories
    and Files they name, on the caller's transaction."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def repositories(self, publication: PublicationSchema) -> dict[str, int]:
        """The id of each Repository the call names, the Transcript's and
        those its commits and file edits are of, by its checkout's name; one
        Pilot has no row for is written. Written in the names' order, so
        that two publications wait on each other one way round only."""
        named: set[str] = set()
        if publication.repository is not None:
            named.add(publication.repository)
        for requested in _requested(publication.calls):
            named.update(commit.repository for commit in requested.commits)
            named.update(edit.repository for edit in requested.file_edits)
        if not named:
            return {}
        names = sorted(named)
        held = self._repositories(names)
        unmet = [name for name in names if name not in held]
        if unmet:
            self.db.execute(
                pg_insert(Repository).on_conflict_do_nothing(index_elements=["name"]),
                [{"name": name} for name in unmet],
            )
            held = self._repositories(names)
        return held

    def write(
        self,
        calls: list[PublishedCallSchema],
        made: dict[str, int],
        repositories: dict[str, int],
        transcript: str,
    ) -> None:
        """The commits and the file edits of each Tool Call the call names
        as the call has them; `made` is each one's id by its `tool_use_id`,
        `repositories` each Repository's by its name (`repositories`), and
        `transcript` names the Transcript in what is logged."""
        requested = [
            (made[tool_call.tool_use_id], tool_call) for tool_call in _requested(calls)
        ]
        if not requested:
            return
        ids = literal(
            [tool_call_id for tool_call_id, _ in requested], ARRAY(BigInteger)
        )
        self._commits(requested, ids, repositories, transcript)
        self._edits(requested, ids, repositories)

    def unmade(self, entity: type[Any], ids: Sequence[int]) -> None:
        """Delete the Commits that no read of their Repository completed of
        the Tool Calls of those ids, or of the Calls' of those ids where
        `entity` is a Call, which are about to go. One read from its
        Repository stays, and the key leaves it with no Tool Call."""
        named = literal(list(ids), ARRAY(BigInteger))
        made = (
            Commit.tool_call_id == any_(named)
            if entity is ToolCall
            else Commit.tool_call_id.in_(
                select(ToolCall.id).where(ToolCall.call_id == any_(named))
            )
        )
        self.db.execute(delete(Commit).where(made, Commit.lines_read_at.is_(None)))

    def _commits(
        self,
        requested: list[tuple[int, PublishedToolCallSchema]],
        ids: Any,
        repositories: dict[str, int],
        transcript: str,
    ) -> None:
        """Each Tool Call's Commits as its call names them. A read one keeps
        the commit it was tied by, and is left with no Tool Call where none
        is; one no read completed stays where a commit has its Repository,
        hash and subject, and goes otherwise. Of the commits left, one whose
        hash names a Commit a Tool Call holds is not held; a read Commit no
        Tool Call holds that the tie gives one becomes its Tool Call's; the
        rest are held new, in the call's order."""
        held: dict[int, list[Commit]] = {}
        for row in self.db.scalars(
            select(Commit).where(Commit.tool_call_id == any_(ids)).order_by(Commit.id)
        ):
            assert row.tool_call_id is not None
            held.setdefault(row.tool_call_id, []).append(row)
        new: list[tuple[int, str, PublishedCommitSchema]] = []
        for tool_call_id, tool_call in requested:
            wanted = list(tool_call.commits)
            rows = held.get(tool_call_id, [])
            for row in rows:
                if row.lines_read_at is None:
                    continue
                own = _tied(row, wanted, repositories)
                if own is None:
                    row.tool_call_id = None
                else:
                    wanted.remove(own)
            for row in rows:
                if row.lines_read_at is not None:
                    continue
                same = next(
                    (
                        commit
                        for commit in wanted
                        if (repositories[commit.repository], commit.sha, commit.subject)
                        == (row.repository_id, row.sha, row.subject)
                    ),
                    None,
                )
                if same is None:
                    self.db.delete(row)
                else:
                    wanted.remove(same)
            new.extend(
                (tool_call_id, tool_call.tool_use_id, commit) for commit in wanted
            )
        self.db.flush()
        if not new:
            return

        taken = self._taken(new, repositories)
        loose = self._loose(new, repositories)
        kept: list[tuple[int, str, PublishedCommitSchema]] = []
        for tool_call_id, tool_use_id, commit in new:
            repository_id = repositories[commit.repository]
            if commit.sha is not None and any(
                sha.startswith(commit.sha) for sha in taken.get(repository_id, [])
            ):
                logger.warning(
                    "Transcript %s: tool call %s names the commit %s of %s, which"
                    " Pilot holds as another's",
                    transcript,
                    tool_use_id,
                    commit.sha,
                    commit.repository,
                )
                continue
            kept.append((tool_call_id, tool_use_id, commit))
        by_request = {tool_call.tool_use_id: tool_call for _, tool_call in requested}
        tied: set[int] = set()
        for repository_id, rows in loose.items():
            ours = [
                (place, made)
                for place, made in enumerate(kept)
                if repositories[made[2].repository] == repository_id
            ]
            for named, made in tie(
                [
                    Held(
                        key=place,
                        sha=commit.sha,
                        subject=commit.subject,
                        requested_at=by_request[tool_use_id].requested_at,
                        returned_at=by_request[tool_use_id].returned_at,
                    )
                    for place, (_, tool_use_id, commit) in ours
                ],
                [_read(row) for row in rows],
            ):
                self.db.get_one(Commit, made.key).tool_call_id = kept[named.key][0]
                tied.add(named.key)
        for place, (tool_call_id, _, commit) in enumerate(kept):
            if place in tied:
                continue
            self.db.add(
                Commit(
                    repository_id=repositories[commit.repository],
                    sha=commit.sha,
                    subject=commit.subject,
                    tool_call_id=tool_call_id,
                )
            )
        self.db.flush()

    def _taken(
        self,
        new: list[tuple[int, str, PublishedCommitSchema]],
        repositories: dict[str, int],
    ) -> dict[int, list[str]]:
        """The hash of each Commit a Tool Call made, by its Repository's id,
        among those a new commit's hash names: a Commit is made by one Tool
        Call once (DB 577)."""
        named = _named(new, repositories)
        if not named:
            return {}
        taken: dict[int, list[str]] = {}
        for repository_id, sha in self.db.execute(
            select(Commit.repository_id, Commit.sha).where(
                Commit.tool_call_id.is_not(None), or_(*named)
            )
        ):
            assert sha is not None
            taken.setdefault(repository_id, []).append(sha)
        return taken

    def _loose(
        self,
        new: list[tuple[int, str, PublishedCommitSchema]],
        repositories: dict[str, int],
    ) -> dict[int, list[Commit]]:
        """The Commits a read of their Repository gave that no Tool Call
        holds, by their Repository's id, among those a new commit's hash
        names or whose subject it has: those a new commit may complete,
        locked so that one is tied once."""
        subjects = sorted(
            {(repositories[commit.repository], commit.subject) for _, _, commit in new}
        )
        loose: dict[int, list[Commit]] = {}
        for row in self.db.scalars(
            select(Commit)
            .where(
                Commit.tool_call_id.is_(None),
                Commit.lines_read_at.is_not(None),
                or_(
                    tuple_(Commit.repository_id, Commit.subject).in_(subjects),
                    *_named(new, repositories),
                ),
            )
            .order_by(Commit.id)
            .with_for_update()
        ):
            loose.setdefault(row.repository_id, []).append(row)
        return loose

    def _edits(
        self,
        requested: list[tuple[int, PublishedToolCallSchema]],
        ids: Any,
        repositories: dict[str, int],
    ) -> None:
        """Each Tool Call's File Edits as its call names them, by their
        File: a held one whose lines differ is written in place, one the
        call no longer names goes."""
        files = self.files(
            sorted(
                {
                    (repositories[edit.repository], edit.path)
                    for _, tool_call in requested
                    for edit in tool_call.file_edits
                }
            )
        )
        held = {
            (row.tool_call_id, row.file_id): row
            for row in self.db.scalars(
                select(FileEdit).where(FileEdit.tool_call_id == any_(ids))
            )
        }
        for tool_call_id, tool_call in requested:
            for edit in tool_call.file_edits:
                file_id = files[repositories[edit.repository], edit.path]
                row = held.pop((tool_call_id, file_id), None)
                if row is None:
                    self.db.add(
                        FileEdit(
                            tool_call_id=tool_call_id,
                            file_id=file_id,
                            lines_added=edit.lines_added,
                            lines_removed=edit.lines_removed,
                        )
                    )
                else:
                    row.lines_added = edit.lines_added
                    row.lines_removed = edit.lines_removed
        for row in held.values():
            self.db.delete(row)
        self.db.flush()

    def files(self, paths: list[tuple[int, str]]) -> dict[tuple[int, str], int]:
        """The id of each File by its Repository's id and its path, in
        their order; one Pilot has no row for is written, with no class."""
        if not paths:
            return {}
        held = self._held_files(paths)
        unmet = [path for path in paths if path not in held]
        if unmet:
            self.db.execute(
                pg_insert(File).on_conflict_do_nothing(
                    index_elements=["repository_id", "path"]
                ),
                [
                    {"repository_id": repository, "path": path}
                    for repository, path in unmet
                ],
            )
            held = self._held_files(paths)
        return held

    def _held_files(self, paths: list[tuple[int, str]]) -> dict[tuple[int, str], int]:
        """Read through two arrays, a first read of a Repository naming more
        paths than a statement takes parameters."""
        asked = select(
            func.unnest(
                literal([repository for repository, _ in paths], ARRAY(BigInteger))
            ).label("repository_id"),
            func.unnest(literal([path for _, path in paths], ARRAY(Text))).label(
                "path"
            ),
        ).subquery()
        return {
            (repository_id, path): file_id
            for file_id, repository_id, path in self.db.execute(
                select(File.id, File.repository_id, File.path).join(
                    asked,
                    and_(
                        asked.c.repository_id == File.repository_id,
                        asked.c.path == File.path,
                    ),
                )
            )
        }

    def _repositories(self, names: list[str]) -> dict[str, int]:
        return dict(
            self.db.execute(
                select(Repository.name, Repository.id).where(Repository.name.in_(names))
            ).all()
        )


def _named(
    new: list[tuple[int, str, PublishedCommitSchema]], repositories: dict[str, int]
) -> list[ColumnElement[bool]]:
    """Of each new commit that shows a hash, the Commits of its Repository
    whose hash starts with it."""
    return [
        and_(
            Commit.repository_id == repositories[commit.repository],
            Commit.sha.startswith(commit.sha),
        )
        for _, _, commit in new
        if commit.sha is not None
    ]


def _read(row: Commit) -> Read:
    assert row.sha is not None and row.made_at is not None
    return Read(key=row.id, sha=row.sha, subject=row.subject, made_at=row.made_at)


def _requested(calls: list[PublishedCallSchema]) -> list[PublishedToolCallSchema]:
    return [tool_call for call in calls for tool_call in call.tool_calls]
