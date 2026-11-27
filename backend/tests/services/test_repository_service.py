"""The Repositories as a collector reads them from its clones of the mirror,
and the Files' classes (F152.11, F158.4, F158.5; DB §2.9, assertions 577,
578 and 581): Pilot's cursor, a read's commits tied to the Commits held from
their calls, the same tie from a publication that comes after the read, the
Commit a CI Build built, and the classes the labeller gives the Files.

The rules that protect the most: a commit read completes the Commit its call
made, by its hash or within the hour by its subject, once, whichever of the
two arrived first (`TestRead`, `TestPublishedAfter`), and a commit read
twice changes no row (`test_a_commit_read_again_changes_no_row`)."""

import logging
from datetime import timedelta
from typing import Any

import pytest
from pilot_collection.files import FileClassesSchema
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.exceptions import FileClassesInvalidException, RepositoryReadInvalidException
from app.models import (
    CIBuild,
    Commit,
    File,
    FileChange,
    FileClass,
    Repository,
    ToolCall,
    Transcript,
)
from app.services.commit_tie import HOUR, built_commit
from app.services.container import ServiceContainer
from app.services.publication_service import PublicationService
from app.services.repository_service import RepositoryService
from tests.support.database import Written, writes
from tests.support.labels import ci_build, declared
from tests.support.publications import call, commit, file_edit, tool_call, whole
from tests.support.repositories import (
    MADE_AT,
    READ_AT,
    REBASED,
    WHOLE,
    change,
    file_class,
    read_commit,
    repository_read,
)
from tests.support.transcripts import CAMP, OTHER

LOGGER = "app.services.repository_service"
WRITE_LOGGER = "app.services.commit_write"

SUBJECT = "Scale the stew for six"
AMENDED = "5c7e9a1b3d5f7092b4d6f8a0c2e4a6b8d0f2a4c6"


def _commit_call(place: int = 1, **overrides: Any) -> dict[str, Any]:
    """The `git commit` Tool Call at `place` that made the invented commit."""
    values: dict[str, Any] = {
        "first_argument": f'git commit -m "{SUBJECT}"',
        "commits": [commit()],
    }
    return tool_call(place, **values | overrides)


def _camp(*tool_calls: dict[str, Any], **overrides: Any) -> Any:
    """The main thread in the invented checkout, its one Call requesting
    those Tool Calls."""
    values: dict[str, Any] = {
        "repository": "RecipeBox",
        "calls": [call(1, tool_calls=list(tool_calls))],
    }
    return whole(**values | overrides)


def _commits(db: DbSession) -> list[tuple[Any, ...]]:
    """Each Commit Pilot holds: its hash, its subject, the `tool_use_id` of
    the Tool Call that made it, its author's time and when its lines were
    read."""
    return [
        tuple(row)
        for row in db.execute(
            select(
                Commit.sha,
                Commit.subject,
                ToolCall.tool_use_id,
                Commit.made_at,
                Commit.lines_read_at,
            )
            .outerjoin(ToolCall, ToolCall.id == Commit.tool_call_id)
            .order_by(Commit.id)
        )
    ]


def _changes(db: DbSession) -> list[tuple[Any, ...]]:
    """Each File Change: its Commit's hash, its File's path and its lines."""
    return [
        tuple(row)
        for row in db.execute(
            select(
                Commit.sha,
                File.path,
                FileChange.lines_added,
                FileChange.lines_removed,
            )
            .join(Commit, Commit.id == FileChange.commit_id)
            .join(File, File.id == FileChange.file_id)
            .order_by(Commit.sha, File.path)
        )
    ]


def _logged(caplog: pytest.LogCaptureFixture, logger: str = LOGGER) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == logger]


@pytest.fixture
def publications(container: ServiceContainer) -> PublicationService:
    return container.publication_service()


@pytest.fixture
def repositories(container: ServiceContainer) -> RepositoryService:
    return container.repository_service()


class TestRepositories:
    """Pilot is the cursor: what a collector reads next is what a read has
    not given."""

    def test_a_record_with_none_answers_none(
        self, repositories: RepositoryService
    ) -> None:
        assert repositories.repositories().model_dump() == {"repositories": []}

    def test_each_is_named_with_every_hash_a_read_gave(
        self,
        session: DbSession,
        publications: PublicationService,
        repositories: RepositoryService,
    ) -> None:
        publications.publish(
            _camp(
                _commit_call(),
                _commit_call(2, commits=[commit(sha="9d0e1f2", subject="Plan")]),
                tool_call(3, commits=[commit(repository="RecipeBoxSpecs")]),
            )
        )
        repositories.read(repository_read(read_commit(), read_commit(sha=AMENDED)))

        assert repositories.repositories().model_dump() == {
            "repositories": [
                {"name": "RecipeBox", "read": [WHOLE, AMENDED]},
                {"name": "RecipeBoxSpecs", "read": []},
            ]
        }


class TestRead:
    """A read's commit completes the Commit held from its call, else is one
    no Transcript made (DB 577)."""

    def test_one_completes_the_held_commit_whose_hash_it_starts_with(
        self,
        session: DbSession,
        publications: PublicationService,
        repositories: RepositoryService,
    ) -> None:
        publications.publish(_camp(_commit_call()))

        repositories.read(
            repository_read(
                read_commit(files=[change(), change(path="recipes/soup.md")])
            )
        )

        assert _commits(session) == [(WHOLE, SUBJECT, "toolu_0001", MADE_AT, READ_AT)]
        assert _changes(session) == [
            (WHOLE, "recipes/soup.md", 12, 2),
            (WHOLE, "recipes/stew.md", 12, 2),
        ]

    def test_a_rebased_one_completes_it_by_its_subject_within_the_hour(
        self,
        session: DbSession,
        publications: PublicationService,
        repositories: RepositoryService,
    ) -> None:
        publications.publish(_camp(_commit_call()))
        made_at = MADE_AT + HOUR

        repositories.read(repository_read(read_commit(sha=REBASED, made_at=made_at)))

        assert _commits(session) == [(REBASED, SUBJECT, "toolu_0001", made_at, READ_AT)]

    def test_one_past_the_hour_is_one_no_transcript_made(
        self,
        session: DbSession,
        publications: PublicationService,
        repositories: RepositoryService,
    ) -> None:
        publications.publish(_camp(_commit_call()))
        made_at = MADE_AT + 2 * HOUR

        repositories.read(repository_read(read_commit(sha=REBASED, made_at=made_at)))

        assert _commits(session) == [
            ("3f9a2c1", SUBJECT, "toolu_0001", None, None),
            (REBASED, SUBJECT, None, made_at, READ_AT),
        ]
        assert _changes(session) == [(REBASED, "recipes/stew.md", 12, 2)]

    def test_of_an_amended_commits_two_calls_the_one_with_its_hash_has_it(
        self,
        session: DbSession,
        publications: PublicationService,
        repositories: RepositoryService,
    ) -> None:
        publications.publish(
            _camp(_commit_call(), _commit_call(2, commits=[commit(sha="5c7e9a1")]))
        )

        repositories.read(repository_read(read_commit(sha=AMENDED)))

        assert _commits(session) == [
            ("3f9a2c1", SUBJECT, "toolu_0001", None, None),
            (AMENDED, SUBJECT, "toolu_0002", MADE_AT, READ_AT),
        ]

    def test_a_merge_commit_is_read_and_changed_no_file(
        self,
        session: DbSession,
        publications: PublicationService,
        repositories: RepositoryService,
    ) -> None:
        publications.publish(_camp(_commit_call()))

        repositories.read(repository_read(read_commit(files=[])))

        assert _commits(session) == [(WHOLE, SUBJECT, "toolu_0001", MADE_AT, READ_AT)]
        assert _changes(session) == []

    def test_a_file_a_call_edited_is_the_file_a_commit_changed(
        self,
        session: DbSession,
        publications: PublicationService,
        repositories: RepositoryService,
    ) -> None:
        publications.publish(
            _camp(
                tool_call(
                    1, tool="Edit", first_argument="stew.md", file_edits=[file_edit()]
                )
            )
        )

        repositories.read(
            repository_read(read_commit(), read_commit(sha=REBASED, subject="Plan"))
        )

        assert session.scalars(select(File.path)).all() == ["recipes/stew.md"]
        assert _changes(session) == [
            (WHOLE, "recipes/stew.md", 12, 2),
            (REBASED, "recipes/stew.md", 12, 2),
        ]

    def test_a_commit_read_again_changes_no_row(
        self,
        session: DbSession,
        publications: PublicationService,
        repositories: RepositoryService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        publications.publish(_camp(_commit_call()))
        repositories.read(repository_read(read_commit()))
        caplog.clear()

        with writes(session) as wrote, caplog.at_level(logging.INFO, LOGGER):
            repositories.read(
                repository_read(
                    read_commit(made_at=(MADE_AT + HOUR).isoformat(), files=[]),
                    read_at=(READ_AT + timedelta(days=1)).isoformat(),
                )
            )

        assert wrote == {}
        assert _commits(session) == [(WHOLE, SUBJECT, "toolu_0001", MADE_AT, READ_AT)]
        assert _logged(caplog) == ["Read RecipeBox: 1 commits, every one held already"]

    def test_what_it_took_is_logged(
        self,
        session: DbSession,
        publications: PublicationService,
        repositories: RepositoryService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        publications.publish(
            _camp(_commit_call(), _commit_call(2, commits=[commit(sha=None)]))
        )
        repositories.read(repository_read(read_commit()))
        caplog.clear()

        with caplog.at_level(logging.INFO, LOGGER):
            repositories.read(
                repository_read(
                    read_commit(),
                    read_commit(sha=REBASED),
                    read_commit(sha=AMENDED, subject="Plan"),
                )
            )

        assert _logged(caplog) == [
            "Read RecipeBox: 3 commits, 1 held already; of the 2 taken, 0 completed"
            " the commit of their call by its hash and 1 by its subject, and 1 no"
            " transcript made"
        ]

    @pytest.mark.parametrize(
        ("read", "fault"),
        [
            (
                repository_read(read_commit(), repository="RecipeBoxSpecs"),
                "Pilot holds no such repository",
            ),
            (
                repository_read(read_commit(), read_commit(subject="Plan")),
                f"the commit `{WHOLE}` is given twice",
            ),
            (
                repository_read(read_commit(files=[change(), change(lines_added=1)])),
                f"the commit `{WHOLE}` changes the file `recipes/stew.md` twice",
            ),
        ],
        ids=["an unknown repository", "a commit twice", "a file twice"],
    )
    def test_a_fault_refuses_the_call(
        self,
        session: DbSession,
        publications: PublicationService,
        repositories: RepositoryService,
        read: Any,
        fault: str,
    ) -> None:
        publications.publish(_camp(_commit_call()))

        with (
            writes(session) as wrote,
            pytest.raises(RepositoryReadInvalidException) as refused,
        ):
            repositories.read(read)

        assert refused.value.faults == [fault]
        assert wrote == {}


class TestPublishedAfter:
    """A call published after the read of its commit ties it as the read
    would have: whichever of the two arrived first (DB 577)."""

    def test_its_commit_takes_the_read_one_by_its_hash(
        self,
        session: DbSession,
        publications: PublicationService,
        repositories: RepositoryService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        publications.publish(_camp(tool_call(1)))
        repositories.read(repository_read(read_commit()))

        with caplog.at_level(logging.WARNING, WRITE_LOGGER):
            publications.publish(_camp(_commit_call()))

        assert _commits(session) == [(WHOLE, SUBJECT, "toolu_0001", MADE_AT, READ_AT)]
        assert _changes(session) == [(WHOLE, "recipes/stew.md", 12, 2)]
        assert _logged(caplog, WRITE_LOGGER) == []

    def test_a_rebased_one_is_taken_by_its_subject_within_the_hour(
        self,
        session: DbSession,
        publications: PublicationService,
        repositories: RepositoryService,
    ) -> None:
        publications.publish(_camp(tool_call(1)))
        made_at = MADE_AT - HOUR
        repositories.read(repository_read(read_commit(sha=REBASED, made_at=made_at)))

        publications.publish(_camp(_commit_call()))

        assert _commits(session) == [(REBASED, SUBJECT, "toolu_0001", made_at, READ_AT)]

    def test_one_past_the_hour_is_held_with_no_lines(
        self,
        session: DbSession,
        publications: PublicationService,
        repositories: RepositoryService,
    ) -> None:
        publications.publish(_camp(tool_call(1)))
        made_at = MADE_AT + 2 * HOUR
        repositories.read(repository_read(read_commit(sha=REBASED, made_at=made_at)))

        publications.publish(_camp(_commit_call()))

        assert _commits(session) == [
            (REBASED, SUBJECT, None, made_at, READ_AT),
            ("3f9a2c1", SUBJECT, "toolu_0001", None, None),
        ]

    def test_of_its_commits_the_one_with_the_hash_has_it(
        self,
        session: DbSession,
        publications: PublicationService,
        repositories: RepositoryService,
    ) -> None:
        publications.publish(_camp(tool_call(1)))
        repositories.read(repository_read(read_commit(sha=AMENDED)))

        publications.publish(
            _camp(_commit_call(), _commit_call(2, commits=[commit(sha="5c7e9a1")]))
        )

        assert _commits(session) == [
            (AMENDED, SUBJECT, "toolu_0002", MADE_AT, READ_AT),
            ("3f9a2c1", SUBJECT, "toolu_0001", None, None),
        ]

    def test_one_another_tool_call_holds_is_left_to_it(
        self,
        session: DbSession,
        publications: PublicationService,
        repositories: RepositoryService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        publications.publish(_camp(_commit_call(), session_id=OTHER))
        repositories.read(repository_read(read_commit()))

        with caplog.at_level(logging.WARNING, WRITE_LOGGER):
            publications.publish(_camp(_commit_call()))

        assert len(_commits(session)) == 1
        assert (
            session.scalars(
                select(Transcript.session_id)
                .join(ToolCall, ToolCall.transcript_id == Transcript.id)
                .join(Commit, Commit.tool_call_id == ToolCall.id)
            ).one()
            == OTHER
        )
        assert _logged(caplog, WRITE_LOGGER) == [
            f"Transcript {CAMP}: tool call toolu_0001 names the commit 3f9a2c1 of"
            " RecipeBox, which Pilot holds as another's"
        ]


class TestBuilt:
    """A CI Build reaches the Commit it built by the hash its wait named,
    whichever of the two arrived first (DB §2.9, CI Build's `commit?`)."""

    def _built(self, db: DbSession) -> int | None:
        return db.scalar(select(built_commit()).select_from(CIBuild))

    def test_one_held_after_the_build_is_reached_and_stays_once_read(
        self,
        session: DbSession,
        publications: PublicationService,
        repositories: RepositoryService,
    ) -> None:
        ci_build(session, commit_sha=WHOLE)
        assert self._built(session) is None

        publications.publish(_camp(_commit_call()))
        held = session.scalars(select(Commit.id)).one()
        assert self._built(session) == held

        repositories.read(repository_read(read_commit()))
        assert self._built(session) == held

    def test_one_read_before_the_build_is_reached_by_an_abbreviated_hash(
        self, session: DbSession, repositories: RepositoryService
    ) -> None:
        session.add(Repository(name="RecipeBox"))
        session.flush()
        repositories.read(repository_read(read_commit()))

        ci_build(session, commit_sha="3f9a2c1")

        assert self._built(session) == session.scalars(select(Commit.id)).one()

    def test_one_no_commit_has_the_hash_of_reaches_none(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp(_commit_call()))

        ci_build(session, commit_sha=AMENDED)

        assert self._built(session) is None


class TestFiles:
    """The Files a collector has the labeller class, and the classes it
    gives them (F158.5)."""

    def _classes(self, db: DbSession) -> list[tuple[str, str | None]]:
        return [
            (path, code)
            for path, code in db.execute(
                select(File.path, File.class_code).order_by(File.path)
            )
        ]

    @pytest.fixture
    def held(
        self,
        session: DbSession,
        publications: PublicationService,
        repositories: RepositoryService,
    ) -> None:
        """Three Files of two Repositories, a recipe classed."""
        declared(session, FileClass, "recipe", counted=True)
        declared(session, FileClass, "shopping_list", counted=False)
        publications.publish(
            _camp(
                tool_call(
                    1,
                    tool="Edit",
                    first_argument="stew.md",
                    file_edits=[
                        file_edit(),
                        file_edit(path="lists/market.md"),
                        file_edit(repository="RecipeBoxSpecs", path="plan.md"),
                    ],
                )
            )
        )
        repositories.classify(
            FileClassesSchema.model_validate({"classes": [file_class()]})
        )

    @pytest.mark.usefixtures("held")
    def test_every_file_is_handed_by_its_repository_and_path(
        self, repositories: RepositoryService
    ) -> None:
        assert repositories.files(unclassed=False).model_dump() == {
            "files": [
                {"repository": "RecipeBox", "path": "lists/market.md"},
                {"repository": "RecipeBox", "path": "recipes/stew.md"},
                {"repository": "RecipeBoxSpecs", "path": "plan.md"},
            ]
        }

    @pytest.mark.usefixtures("held")
    def test_those_with_no_class_are_handed_alone(
        self, repositories: RepositoryService
    ) -> None:
        assert repositories.files(unclassed=True).model_dump() == {
            "files": [
                {"repository": "RecipeBox", "path": "lists/market.md"},
                {"repository": "RecipeBoxSpecs", "path": "plan.md"},
            ]
        }

    @pytest.mark.usefixtures("held")
    def test_only_the_classes_that_differ_are_written(
        self, session: DbSession, repositories: RepositoryService
    ) -> None:
        classes = FileClassesSchema.model_validate(
            {
                "classes": [
                    file_class(),
                    file_class(path="lists/market.md", file_class="shopping_list"),
                ]
            }
        )

        with writes(session) as wrote:
            repositories.classify(classes)

        assert wrote == {"files": Written(updated=1)}
        assert self._classes(session) == [
            ("lists/market.md", "shopping_list"),
            ("plan.md", None),
            ("recipes/stew.md", "recipe"),
        ]

    @pytest.mark.usefixtures("held")
    def test_a_class_is_replaced_and_a_file_not_named_keeps_its_own(
        self, session: DbSession, repositories: RepositoryService
    ) -> None:
        repositories.classify(
            FileClassesSchema.model_validate(
                {"classes": [file_class(file_class="shopping_list")]}
            )
        )

        assert self._classes(session) == [
            ("lists/market.md", None),
            ("plan.md", None),
            ("recipes/stew.md", "shopping_list"),
        ]

    @pytest.mark.usefixtures("held")
    def test_every_fault_refuses_the_call(
        self, session: DbSession, repositories: RepositoryService
    ) -> None:
        session.add(
            FileClass(
                code="printout",
                name="Printout",
                description="A printout no longer declared.",
                counted=False,
            )
        )
        session.flush()
        classes = FileClassesSchema.model_validate(
            {
                "classes": [
                    file_class(file_class="shopping_list"),
                    file_class(),
                    file_class(path="recipes/pie.md"),
                    file_class(path="lists/market.md", file_class="printout"),
                ]
            }
        )

        with (
            writes(session) as wrote,
            pytest.raises(FileClassesInvalidException) as refused,
        ):
            repositories.classify(classes)

        assert refused.value.faults == [
            "the file `recipes/stew.md` of `RecipeBox` is given twice",
            "the file `recipes/pie.md` of `RecipeBox`: Pilot holds no such file",
            "`file_class` `printout`: no value the labeller declares",
        ]
        assert wrote == {}
        assert self._classes(session)[2] == ("recipes/stew.md", "recipe")
