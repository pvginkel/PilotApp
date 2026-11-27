"""The Repositories as a collector reads them from its clones of the mirror,
and the Files' classes as the labeller gives them (F152.11, F158.4, F158.5;
DB §2.9, assertions 577, 578 and 581).

Pilot is the cursor (F152.1): what a collector reads of a Repository's
history next is decided by the Commits a read of it gave, which Pilot hands
it, so that its memory holds nothing Pilot cannot give back. A read's commits
complete the Commits held from their calls by the tie (`commit_tie`), and
are otherwise Commits no Transcript made; a commit Pilot holds read already
changes no row.
"""

import logging
from collections.abc import Iterable

from pilot_collection.files import (
    FileClassesSchema,
    FilesSchema,
    HeldFileSchema,
)
from pilot_collection.repositories import (
    HeldRepositorySchema,
    ReadCommitSchema,
    RepositoriesSchema,
    RepositoryReadSchema,
)
from sqlalchemy import BigInteger, Text, and_, any_, func, literal, select, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from app.exceptions import FileClassesInvalidException, RepositoryReadInvalidException
from app.models import Commit, File, FileChange, FileClass, Repository, ToolCall
from app.services.commit_tie import Held, Read, tie
from app.services.commit_write import CommitWrite, commits_turn

logger = logging.getLogger(__name__)


def read_faults(read: RepositoryReadSchema) -> list[str]:
    """What in the read contradicts itself, each in a line: a commit given
    twice, and a file changed twice by one commit."""
    found: list[str] = []
    shas: set[str] = set()
    for commit in read.commits:
        if commit.sha in shas:
            found.append(f"the commit `{commit.sha}` is given twice")
        shas.add(commit.sha)
        paths: set[str] = set()
        for change in commit.files:
            if change.path in paths:
                found.append(
                    f"the commit `{commit.sha}` changes the file `{change.path}` twice"
                )
            paths.add(change.path)
    return found


class RepositoryService:
    """Answers a collector's cursor, takes its reads of a Repository and the
    Files' classes, on the caller's transaction."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def repositories(self) -> RepositoriesSchema:
        """Every Repository Pilot holds, by name, each with the whole hash
        of every Commit a read of it gave in their order, in two reads."""
        read: dict[int, list[str]] = {}
        for repository_id, sha in self.db.execute(
            select(Commit.repository_id, Commit.sha)
            .where(Commit.lines_read_at.is_not(None))
            .order_by(Commit.sha)
        ):
            assert sha is not None
            read.setdefault(repository_id, []).append(sha)
        return RepositoriesSchema(
            repositories=[
                HeldRepositorySchema(name=name, read=read.get(repository_id, []))
                for repository_id, name in self.db.execute(
                    select(Repository.id, Repository.name).order_by(Repository.name)
                )
            ]
        )

    def read(self, read: RepositoryReadSchema) -> None:
        """Take what a read of one Repository's history gave, in the
        commits' turn, so that no publication holds or removes a Commit
        meanwhile.

        Each commit Pilot does not hold read completes the held Commit the
        tie gives it, which takes its whole hash, its author's time, its
        File Changes and the read's time; one the tie gives none is a Commit
        no Transcript made, with the same. A commit Pilot holds read already
        changes no row. A File a change names that Pilot has no row for is
        written, with no class. What was taken is logged.

        Raises:
            RepositoryReadInvalidException: the call has faults, or names a
                Repository Pilot does not hold; nothing is written.
        """
        found = read_faults(read)
        repository_id = self.db.scalar(
            select(Repository.id).where(Repository.name == read.repository)
        )
        if repository_id is None:
            found.insert(0, "Pilot holds no such repository")
        if found:
            raise RepositoryReadInvalidException(read.repository, found)
        assert repository_id is not None
        commits_turn(self.db, read=True)
        before = set(
            self.db.scalars(
                select(Commit.sha).where(
                    Commit.repository_id == repository_id,
                    Commit.lines_read_at.is_not(None),
                    Commit.sha
                    == any_(
                        literal([commit.sha for commit in read.commits], ARRAY(Text))
                    ),
                )
            )
        )
        given = [commit for commit in read.commits if commit.sha not in before]
        if not given:
            logger.info(
                "Read %s: %d commits, every one held already",
                read.repository,
                len(read.commits),
            )
            return

        waiting = {
            row.id: (row, requested_at, returned_at)
            for row, requested_at, returned_at in self.db.execute(
                select(Commit, ToolCall.requested_at, ToolCall.returned_at)
                .join(ToolCall, ToolCall.id == Commit.tool_call_id)
                .where(
                    Commit.repository_id == repository_id,
                    Commit.lines_read_at.is_(None),
                )
                .order_by(Commit.id)
            )
        }
        tied = tie(
            [
                Held(
                    key=row.id,
                    sha=row.sha,
                    subject=row.subject,
                    requested_at=requested_at,
                    returned_at=returned_at,
                )
                for row, requested_at, returned_at in waiting.values()
            ],
            [
                Read(
                    key=place,
                    sha=commit.sha,
                    subject=commit.subject,
                    made_at=commit.made_at,
                )
                for place, commit in enumerate(given)
            ],
        )
        completed: dict[int, Commit] = {}
        by_hash = 0
        for held, made in tied:
            commit = given[made.key]
            row = waiting[held.key][0]
            if held.sha is not None and commit.sha.startswith(held.sha):
                by_hash += 1
            row.sha = commit.sha
            row.made_at = commit.made_at
            row.lines_read_at = read.read_at
            completed[made.key] = row
        for place, commit in enumerate(given):
            if place not in completed:
                completed[place] = Commit(
                    repository_id=repository_id,
                    sha=commit.sha,
                    subject=commit.subject,
                    made_at=commit.made_at,
                    lines_read_at=read.read_at,
                )
                self.db.add(completed[place])
        self.db.flush()
        self._changes(repository_id, given, completed)
        logger.info(
            "Read %s: %d commits, %d held already; of the %d taken, %d completed"
            " the commit of their call by its hash and %d by its subject, and %d"
            " no transcript made",
            read.repository,
            len(read.commits),
            len(before),
            len(given),
            by_hash,
            len(tied) - by_hash,
            len(given) - len(tied),
        )

    def files(self, *, unclassed: bool) -> FilesSchema:
        """Every File Pilot holds, or those with no class, by its
        Repository's name and its path."""
        query = select(Repository.name, File.path).join(
            Repository, Repository.id == File.repository_id
        )
        if unclassed:
            query = query.where(File.class_code.is_(None))
        return FilesSchema(
            files=[
                HeldFileSchema(repository=repository, path=path)
                for repository, path in self.db.execute(
                    query.order_by(Repository.name, File.path)
                )
            ]
        )

    def classify(self, classes: FileClassesSchema) -> None:
        """Give each File the call names the class it names, writing only
        the classes that differ, their number logged.

        Raises:
            FileClassesInvalidException: the call names a File twice, a File
                Pilot does not hold or a class the labeller does not declare;
                nothing is written.
        """
        given: dict[tuple[str, str], str] = {}
        found: list[str] = []
        for named in classes.classes:
            key = (named.repository, named.path)
            if key in given:
                found.append(
                    f"the file `{named.path}` of `{named.repository}` is given twice"
                )
            given[key] = named.file_class
        held = self._held(given)
        found += [
            f"the file `{path}` of `{repository}`: Pilot holds no such file"
            for repository, path in given
            if (repository, path) not in held
        ]
        codes = set(given.values())
        declared = set(
            self.db.scalars(
                select(FileClass.code).where(
                    FileClass.code.in_(sorted(codes)), FileClass.position.is_not(None)
                )
            )
        )
        found += [
            f"`file_class` `{code}`: no value the labeller declares"
            for code in sorted(codes - declared)
        ]
        if found:
            raise FileClassesInvalidException(found)
        differ = [
            (file_id, given[key])
            for key, (file_id, code) in held.items()
            if code != given[key]
        ]
        if differ:
            changed = select(
                func.unnest(
                    literal([file_id for file_id, _ in differ], ARRAY(BigInteger))
                ).label("id"),
                func.unnest(literal([code for _, code in differ], ARRAY(Text))).label(
                    "code"
                ),
            ).subquery()
            self.db.execute(
                update(File)
                .where(File.id == changed.c.id)
                .values(class_code=changed.c.code),
                execution_options={"synchronize_session": False},
            )
        logger.info(
            "Took the classes of %d files: %d of them differed",
            len(given),
            len(differ),
        )

    def _held(
        self, given: Iterable[tuple[str, str]]
    ) -> dict[tuple[str, str], tuple[int, str | None]]:
        """The id and class of each File named, by its Repository's name
        and its path."""
        named = sorted(given)
        if not named:
            return {}
        asked = select(
            func.unnest(
                literal([repository for repository, _ in named], ARRAY(Text))
            ).label("repository"),
            func.unnest(literal([path for _, path in named], ARRAY(Text))).label(
                "path"
            ),
        ).subquery()
        return {
            (repository, path): (file_id, code)
            for repository, path, file_id, code in self.db.execute(
                select(Repository.name, File.path, File.id, File.class_code)
                .join(Repository, Repository.id == File.repository_id)
                .join(
                    asked,
                    and_(
                        asked.c.repository == Repository.name,
                        asked.c.path == File.path,
                    ),
                )
            )
        }

    def _changes(
        self,
        repository_id: int,
        given: list[ReadCommitSchema],
        completed: dict[int, Commit],
    ) -> None:
        """Each taken commit's File Changes, its Files met in one sorted
        write."""
        files = CommitWrite(self.db).files(
            sorted(
                {
                    (repository_id, change.path)
                    for commit in given
                    for change in commit.files
                }
            )
        )
        changes = [
            {
                "commit_id": completed[place].id,
                "file_id": files[repository_id, change.path],
                "repository_id": repository_id,
                "lines_added": change.lines_added,
                "lines_removed": change.lines_removed,
            }
            for place, commit in enumerate(given)
            for change in commit.files
        ]
        if changes:
            self.db.execute(FileChange.__table__.insert(), changes)
