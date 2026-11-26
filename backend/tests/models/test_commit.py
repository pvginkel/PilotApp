"""Commit, File, File Change and File Edit: what a row of the work a Tool
Call did in a Repository must hold (DB §2.9; assertions 557, 577 to 581)."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.models import (
    Commit,
    File,
    FileChange,
    FileClass,
    FileEdit,
    Repository,
    ToolCall,
)
from tests.support import labels, transcripts
from tests.support.database import violated_constraint
from tests.support.transcripts import STARTED

WHOLE = "3f9a2c1e7b04d6a51c8f2930d4e6b7a8c9d0e1f2"
"""An invented commit's whole hash."""


@pytest.fixture
def recipe_box(session: DbSession) -> Repository:
    row = Repository(name="RecipeBox")
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def specs(session: DbSession) -> Repository:
    row = Repository(name="RecipeBoxSpecs")
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def run_command(session: DbSession) -> ToolCall:
    """A `git commit` a main thread's first Call ran."""
    thread = transcripts.transcript(session, transcripts.component_version(session))
    return transcripts.tool_call(session, transcripts.call(session, thread, 1))


def _held(repository: Repository, made_by: ToolCall, **overrides: object) -> Commit:
    """A commit held from the call that made it, with no lines."""
    values: dict[str, object] = {
        "repository_id": repository.id,
        "sha": "3f9a2c1",
        "subject": "Scale the stew for six",
        "tool_call_id": made_by.id,
    }
    return Commit(**values | overrides)


def _read(repository: Repository, **overrides: object) -> Commit:
    """A commit its Repository's history gave, which no Transcript made."""
    values: dict[str, object] = {
        "repository_id": repository.id,
        "sha": WHOLE,
        "subject": "Merge the stew",
        "made_at": STARTED,
        "lines_read_at": STARTED + timedelta(days=1),
    }
    return Commit(**values | overrides)


def _count(db: DbSession, entity: type) -> int:
    return db.scalar(select(func.count()).select_from(entity)) or 0


class TestCommit:
    def test_one_held_from_its_call_has_no_lines_yet(
        self, session: DbSession, recipe_box: Repository, run_command: ToolCall
    ) -> None:
        session.add(_held(recipe_box, run_command))
        session.flush()

        held = session.scalars(select(Commit)).one()
        assert (held.made_at, held.lines_read_at) == (None, None)

    def test_one_held_from_a_call_that_showed_no_hash_has_none(
        self, session: DbSession, recipe_box: Repository, run_command: ToolCall
    ) -> None:
        session.add_all(
            [
                _held(recipe_box, run_command, sha=None),
                _held(recipe_box, run_command, sha=None),
            ]
        )
        session.flush()

        assert _count(session, Commit) == 2

    def test_one_no_transcript_made_is_its_repositorys_read(
        self, session: DbSession, recipe_box: Repository
    ) -> None:
        session.add(_read(recipe_box))
        session.flush()

        assert _count(session, Commit) == 1

    def test_one_neither_made_nor_read_is_refused(
        self, session: DbSession, recipe_box: Repository
    ) -> None:
        session.add(_read(recipe_box, made_at=None, lines_read_at=None))

        assert violated_constraint(session) == "ck_commits_source"

    @pytest.mark.parametrize(
        "lacking",
        [
            {"made_at": None},
            {"lines_read_at": None},
            {"sha": None},
        ],
        ids=["its author's time", "when its lines were read", "its whole hash"],
    )
    def test_a_read_gives_its_hash_its_time_and_its_lines_at_once(
        self,
        session: DbSession,
        recipe_box: Repository,
        run_command: ToolCall,
        lacking: dict[str, object],
    ) -> None:
        session.add(_read(recipe_box, tool_call_id=run_command.id, **lacking))

        assert violated_constraint(session) == "ck_commits_read"

    def test_a_hash_is_one_commit_of_its_repository(
        self, session: DbSession, recipe_box: Repository, run_command: ToolCall
    ) -> None:
        session.add(_held(recipe_box, run_command))
        session.flush()
        session.add(_held(recipe_box, run_command, subject="Plan the stew"))

        assert violated_constraint(session) == "commits_repository_id_sha_key"

    def test_one_hash_in_two_repositories_is_two_commits(
        self,
        session: DbSession,
        recipe_box: Repository,
        specs: Repository,
        run_command: ToolCall,
    ) -> None:
        session.add_all([_held(recipe_box, run_command), _held(specs, run_command)])
        session.flush()

        assert _count(session, Commit) == 2

    def test_a_read_one_stays_with_no_tool_call_when_its_tool_call_goes(
        self, session: DbSession, recipe_box: Repository, run_command: ToolCall
    ) -> None:
        session.add(_read(recipe_box, tool_call_id=run_command.id))
        session.flush()

        session.delete(run_command)
        session.flush()
        session.expire_all()

        assert session.scalars(select(Commit.tool_call_id)).all() == [None]

    def test_a_tool_call_does_not_go_before_its_commit_no_read_completed(
        self, session: DbSession, recipe_box: Repository, run_command: ToolCall
    ) -> None:
        """The publication's write removes such a Commit first: alone, the
        key would leave a Commit neither made nor read."""
        session.add(_held(recipe_box, run_command))
        session.flush()

        session.delete(run_command)

        assert violated_constraint(session) == "ck_commits_source"


class TestFile:
    def test_a_path_is_one_file_of_its_repository(
        self, session: DbSession, recipe_box: Repository, specs: Repository
    ) -> None:
        session.add_all(
            [
                File(repository_id=recipe_box.id, path="recipes/stew.md"),
                File(repository_id=specs.id, path="recipes/stew.md"),
            ]
        )
        session.flush()
        session.add(File(repository_id=recipe_box.id, path="recipes/stew.md"))

        assert violated_constraint(session) == "files_repository_id_path_key"

    def test_its_class_is_one_the_labeller_declares(
        self, session: DbSession, recipe_box: Repository
    ) -> None:
        labels.declared(session, FileClass, "recipe", counted=True)
        session.add(
            File(
                repository_id=recipe_box.id, path="recipes/stew.md", class_code="recipe"
            )
        )
        session.flush()
        session.add(
            File(repository_id=recipe_box.id, path="menu.md", class_code="banquet")
        )

        assert violated_constraint(session) == "files_class_code_fkey"


class TestFileChange:
    def _commit_and_file(
        self, session: DbSession, commit_in: Repository, file_in: Repository
    ) -> tuple[Commit, File]:
        made = _read(commit_in)
        changed = File(repository_id=file_in.id, path="recipes/stew.md")
        session.add_all([made, changed])
        session.flush()
        return made, changed

    def test_a_commit_changes_a_file_of_its_own_repository(
        self, session: DbSession, recipe_box: Repository
    ) -> None:
        made, changed = self._commit_and_file(session, recipe_box, recipe_box)
        session.add(
            FileChange(
                commit_id=made.id,
                file_id=changed.id,
                repository_id=recipe_box.id,
                lines_added=12,
                lines_removed=2,
            )
        )
        session.flush()

        assert _count(session, FileChange) == 1

    def test_its_file_is_of_its_commits_repository(
        self, session: DbSession, recipe_box: Repository, specs: Repository
    ) -> None:
        """DB 557."""
        made, changed = self._commit_and_file(session, recipe_box, specs)
        session.add(
            FileChange(
                commit_id=made.id,
                file_id=changed.id,
                repository_id=recipe_box.id,
                lines_added=12,
                lines_removed=2,
            )
        )

        assert violated_constraint(session) == "file_changes_file_id_repository_id_fkey"

    def test_its_lines_are_not_negative(
        self, session: DbSession, recipe_box: Repository
    ) -> None:
        made, changed = self._commit_and_file(session, recipe_box, recipe_box)
        session.add(
            FileChange(
                commit_id=made.id,
                file_id=changed.id,
                repository_id=recipe_box.id,
                lines_added=-1,
                lines_removed=2,
            )
        )

        assert violated_constraint(session) == "ck_file_changes_lines"

    def test_it_goes_with_its_commit(
        self, session: DbSession, recipe_box: Repository
    ) -> None:
        made, changed = self._commit_and_file(session, recipe_box, recipe_box)
        session.add(
            FileChange(
                commit_id=made.id,
                file_id=changed.id,
                repository_id=recipe_box.id,
                lines_added=12,
                lines_removed=2,
            )
        )
        session.flush()

        session.delete(made)
        session.flush()

        assert (_count(session, FileChange), _count(session, File)) == (0, 1)


class TestFileEdit:
    def test_it_goes_with_its_tool_call_and_its_file_stays(
        self, session: DbSession, specs: Repository, run_command: ToolCall
    ) -> None:
        """Its File may be of another Repository than its Transcript's (DB
        557)."""
        edited = File(repository_id=specs.id, path="plan.md")
        session.add(edited)
        session.flush()
        session.add(
            FileEdit(
                tool_call_id=run_command.id,
                file_id=edited.id,
                lines_added=3,
                lines_removed=1,
            )
        )
        session.flush()

        session.delete(run_command)
        session.flush()

        assert (_count(session, FileEdit), _count(session, File)) == (0, 1)

    def test_its_lines_are_not_negative(
        self, session: DbSession, recipe_box: Repository, run_command: ToolCall
    ) -> None:
        edited = File(repository_id=recipe_box.id, path="recipes/stew.md")
        session.add(edited)
        session.flush()
        session.add(
            FileEdit(
                tool_call_id=run_command.id,
                file_id=edited.id,
                lines_added=3,
                lines_removed=-1,
            )
        )

        assert violated_constraint(session) == "ck_file_edits_lines"
