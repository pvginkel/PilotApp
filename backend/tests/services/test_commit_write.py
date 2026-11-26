"""A Tool Call's commits and file edits, written with a publication's facts:
a commit held at once from its call, with its Repository, its subject and its
hash and no lines, and a File Edit for each successful Edit or Write, both
facts of the Tool Call, written where they differ and gone with it; what a
read of its Repository gave a Commit stays (F152.11, F158.4; DB §2.9,
assertions 557 and 577 to 580).

The rules that protect the most: a Commit read from its Repository is never
removed or rewritten by a publication (`TestRead`), and a hash Pilot holds as
another Tool Call's is not held twice (`TestClaimed`)."""

import logging
from datetime import timedelta
from typing import Any

import pytest
from pilot_collection.publication import PublicationSchema
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.exceptions import PublicationInvalidException
from app.models import Commit, File, FileChange, FileEdit, Repository, ToolCall
from app.services.container import ServiceContainer
from app.services.publication_service import PublicationService
from tests.support.database import Written, writes
from tests.support.publications import (
    appended,
    call,
    commit,
    file_edit,
    tool_call,
    whole,
)
from tests.support.transcripts import CAMP, OTHER, STARTED

LOGGER = "app.services.commit_write"

SUBJECT = "Scale the stew for six"
"""The invented commit's subject, as `commit` gives it."""

WHOLE = "3f9a2c1e7b04d6a51c8f2930d4e6b7a8c9d0e1f2"
"""The invented commit's whole hash, which its abbreviated one starts."""

REBASED = "8e1d4b2a6c90f3e57d1b2a4c6e8f0a1b3c5d7e9f"
"""The hash the invented commit took when it was rebased."""

READ_AT = STARTED + timedelta(days=1)
"""When a read of the Repository completed the invented commit."""


def _commit_call(place: int = 1, **overrides: Any) -> dict[str, Any]:
    """The `git commit` Tool Call at `place` that made the invented commit."""
    values: dict[str, Any] = {
        "first_argument": f'git commit -m "{SUBJECT}"',
        "commits": [commit()],
    }
    return tool_call(place, **values | overrides)


def _edit_call(place: int = 2, **overrides: Any) -> dict[str, Any]:
    """The Edit at `place` of the invented recipe."""
    values: dict[str, Any] = {
        "tool": "Edit",
        "first_argument": "/work/RecipeBox/recipes/stew.md",
        "file_edits": [file_edit()],
    }
    return tool_call(place, **values | overrides)


def _camp(*tool_calls: dict[str, Any], **overrides: Any) -> PublicationSchema:
    """The main thread in the invented checkout, its one Call requesting
    those Tool Calls."""
    values: dict[str, Any] = {
        "repository": "RecipeBox",
        "calls": [call(1, tool_calls=list(tool_calls))],
    }
    return whole(**values | overrides)


def _commits(db: DbSession) -> list[tuple[Any, ...]]:
    """Each Commit Pilot holds: its Repository's name, its hash, its
    subject, the `tool_use_id` of the Tool Call that made it and when its
    lines were read."""
    return [
        tuple(row)
        for row in db.execute(
            select(
                Repository.name,
                Commit.sha,
                Commit.subject,
                ToolCall.tool_use_id,
                Commit.lines_read_at,
            )
            .join(Repository, Repository.id == Commit.repository_id)
            .outerjoin(ToolCall, ToolCall.id == Commit.tool_call_id)
            .order_by(Commit.id)
        )
    ]


def _edits(db: DbSession) -> list[tuple[Any, ...]]:
    """Each File Edit Pilot holds: its Tool Call's `tool_use_id`, its File's
    Repository's name and path, and its lines."""
    return [
        tuple(row)
        for row in db.execute(
            select(
                ToolCall.tool_use_id,
                Repository.name,
                File.path,
                FileEdit.lines_added,
                FileEdit.lines_removed,
            )
            .join(ToolCall, ToolCall.id == FileEdit.tool_call_id)
            .join(File, File.id == FileEdit.file_id)
            .join(Repository, Repository.id == File.repository_id)
            .order_by(ToolCall.tool_use_id, File.path)
        )
    ]


def _files(db: DbSession) -> list[tuple[Any, ...]]:
    """Each File Pilot holds: its Repository's name, its path and its
    class."""
    return [
        tuple(row)
        for row in db.execute(
            select(Repository.name, File.path, File.class_code)
            .join(Repository, Repository.id == File.repository_id)
            .order_by(File.id)
        )
    ]


def _read(db: DbSession, sha: str = WHOLE) -> Commit:
    """The one held Commit as a read of its Repository completes it: its
    whole hash, its author's time, a File Change and when its lines were
    read."""
    row = db.scalars(select(Commit)).one()
    row.sha = sha
    row.made_at = STARTED
    row.lines_read_at = READ_AT
    changed = File(repository_id=row.repository_id, path="recipes/soup.md")
    db.add(changed)
    db.flush()
    db.add(
        FileChange(
            commit_id=row.id,
            file_id=changed.id,
            repository_id=row.repository_id,
            lines_added=12,
            lines_removed=2,
        )
    )
    db.flush()
    return row


def _changes(db: DbSession) -> int:
    return db.scalar(select(func.count()).select_from(FileChange)) or 0


def _logged(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == LOGGER]


@pytest.fixture
def publications(container: ServiceContainer) -> PublicationService:
    return container.publication_service()


class TestHeld:
    """A commit held at once from the call that made it (F152.11, F158.4)."""

    def test_it_is_held_with_its_repository_subject_and_hash_and_no_lines(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp(_commit_call()))

        assert _commits(session) == [
            ("RecipeBox", "3f9a2c1", SUBJECT, "toolu_0001", None)
        ]
        assert session.scalars(select(Commit.made_at)).one() is None
        assert _changes(session) == 0

    def test_one_whose_call_showed_no_hash_is_held_with_none(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp(_commit_call(commits=[commit(sha=None)])))

        assert _commits(session) == [("RecipeBox", None, SUBJECT, "toolu_0001", None)]

    def test_a_call_that_made_several_holds_them_in_its_outputs_order(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """The second in the spec repo, which Pilot first meets here: a
        Commit may be of another Repository than its Transcript's (DB
        580)."""
        publications.publish(
            _camp(
                _commit_call(
                    commits=[
                        commit(),
                        commit(repository="RecipeBoxSpecs", subject="Plan the stew"),
                    ]
                )
            )
        )

        assert _commits(session) == [
            ("RecipeBox", "3f9a2c1", SUBJECT, "toolu_0001", None),
            ("RecipeBoxSpecs", "3f9a2c1", "Plan the stew", "toolu_0001", None),
        ]

    def test_a_call_that_made_none_holds_none(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp(tool_call(1)))

        assert _commits(session) == []


class TestEdited:
    """A File Edit for each successful Edit or Write of a path a Repository
    keeps, with its lines (P-348; DB 579)."""

    def test_an_edit_is_held_with_its_lines_on_its_file(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp(_edit_call()))

        assert _edits(session) == [("toolu_0002", "RecipeBox", "recipes/stew.md", 3, 1)]
        assert _files(session) == [("RecipeBox", "recipes/stew.md", None)]

    def test_a_write_of_a_new_file_makes_its_file(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(
            _camp(
                _edit_call(
                    tool="Write",
                    file_edits=[
                        file_edit(
                            path="tests/test_stew.py", lines_added=40, lines_removed=0
                        )
                    ],
                )
            )
        )

        assert _edits(session) == [
            ("toolu_0002", "RecipeBox", "tests/test_stew.py", 40, 0)
        ]

    def test_two_calls_editing_one_file_are_two_edits_of_one_file(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(
            _camp(_edit_call(2), _edit_call(3, file_edits=[file_edit(lines_added=1)]))
        )

        assert _edits(session) == [
            ("toolu_0002", "RecipeBox", "recipes/stew.md", 3, 1),
            ("toolu_0003", "RecipeBox", "recipes/stew.md", 1, 1),
        ]
        assert len(_files(session)) == 1

    def test_a_file_another_repository_keeps_is_that_ones(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """DB 557: a File Edit's File may be of another Repository than its
        Transcript's."""
        publications.publish(
            _camp(
                _edit_call(
                    file_edits=[file_edit(repository="RecipeBoxSpecs", path="plan.md")]
                )
            )
        )

        assert _files(session) == [("RecipeBoxSpecs", "plan.md", None)]

    def test_one_path_in_two_repositories_is_two_files(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(
            _camp(
                _edit_call(2),
                _edit_call(3, file_edits=[file_edit(repository="RecipeBoxSpecs")]),
            )
        )

        assert _files(session) == [
            ("RecipeBox", "recipes/stew.md", None),
            ("RecipeBoxSpecs", "recipes/stew.md", None),
        ]


class TestRepublished:
    """A publication of a Transcript Pilot holds writes the commits and the
    edits that differ, and removes those its Tool Calls no longer name."""

    def test_one_named_again_unchanged_writes_none_of_them(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp(_commit_call(1), _edit_call(2)))

        with writes(session) as wrote:
            publications.publish(_camp(_commit_call(1), _edit_call(2)))

        assert wrote == {"transcripts": Written(updated=1)}

    def test_a_commit_whose_hash_showed_since_is_held_with_it(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp(_commit_call(commits=[commit(sha=None)])))

        publications.publish(_camp(_commit_call()))

        assert _commits(session) == [
            ("RecipeBox", "3f9a2c1", SUBJECT, "toolu_0001", None)
        ]

    def test_an_edit_whose_lines_differ_is_written_in_place(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp(_edit_call()))

        with writes(session) as wrote:
            publications.publish(
                _camp(
                    _edit_call(file_edits=[file_edit(lines_added=8, lines_removed=0)])
                )
            )

        assert wrote["file_edits"] == Written(updated=1)
        assert _edits(session) == [("toolu_0002", "RecipeBox", "recipes/stew.md", 8, 0)]

    def test_what_a_tool_call_no_longer_names_goes_and_the_file_stays(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp(_commit_call(1), _edit_call(2)))

        publications.publish(
            _camp(_commit_call(1, commits=[]), _edit_call(2, file_edits=[]))
        )

        assert (_commits(session), _edits(session)) == ([], [])
        assert _files(session) == [("RecipeBox", "recipes/stew.md", None)]

    def test_a_tool_call_the_file_no_longer_names_takes_them_with_it(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp(_commit_call(1), _edit_call(2)))

        publications.publish(_camp(tool_call(3)))

        assert (_commits(session), _edits(session)) == ([], [])

    def test_a_call_the_file_lost_takes_its_tool_calls_with_them(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(
            _camp(
                calls=[
                    call(1, tool_calls=[_commit_call(1), _edit_call(2)]),
                    call(2),
                ]
            )
        )

        publications.publish(_camp(calls=[call(2)]))

        assert (_commits(session), _edits(session)) == ([], [])

    def test_a_tool_call_found_under_another_call_keeps_them(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(
            _camp(calls=[call(1, tool_calls=[_commit_call(1), _edit_call(2)]), call(2)])
        )
        held = session.scalars(select(Commit.id)).one()

        with writes(session) as wrote:
            publications.publish(
                _camp(
                    calls=[
                        call(1),
                        call(2, tool_calls=[_commit_call(1), _edit_call(2)]),
                    ]
                )
            )

        assert "commits" not in wrote
        assert "file_edits" not in wrote
        assert session.scalars(select(Commit.id)).one() == held


class TestRead:
    """What a read of its Repository gave a Commit stays: its whole hash,
    its author's time, its File Changes and when they were read (P11)."""

    def test_one_named_again_keeps_what_the_read_gave(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp(_commit_call()))
        _read(session)

        with writes(session) as wrote:
            publications.publish(_camp(_commit_call()))

        assert wrote == {"transcripts": Written(updated=1)}
        assert _commits(session) == [
            ("RecipeBox", WHOLE, SUBJECT, "toolu_0001", READ_AT)
        ]
        assert _changes(session) == 1

    def test_one_rebased_and_tied_by_its_subject_keeps_its_new_hash(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp(_commit_call()))
        _read(session, REBASED)

        publications.publish(_camp(_commit_call()))

        assert _commits(session) == [
            ("RecipeBox", REBASED, SUBJECT, "toolu_0001", READ_AT)
        ]

    def test_one_its_call_no_longer_names_stays_with_no_tool_call(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp(_commit_call()))
        _read(session)

        publications.publish(_camp(_commit_call(commits=[])))

        assert _commits(session) == [("RecipeBox", WHOLE, SUBJECT, None, READ_AT)]
        assert _changes(session) == 1

    def test_one_whose_call_names_another_stays_and_the_other_is_held(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp(_commit_call()))
        _read(session)

        publications.publish(
            _camp(
                _commit_call(commits=[commit(subject="Season the stew", sha="9d0e1f2")])
            )
        )

        assert _commits(session) == [
            ("RecipeBox", WHOLE, SUBJECT, None, READ_AT),
            ("RecipeBox", "9d0e1f2", "Season the stew", "toolu_0001", None),
        ]

    def test_one_whose_tool_call_goes_stays_with_no_tool_call(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp(_commit_call()))
        _read(session)

        publications.publish(_camp(tool_call(3)))

        assert _commits(session) == [("RecipeBox", WHOLE, SUBJECT, None, READ_AT)]
        assert _changes(session) == 1

    def test_one_whose_call_the_file_lost_stays_with_no_tool_call(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(
            _camp(calls=[call(1, tool_calls=[_commit_call()]), call(2)])
        )
        _read(session)

        publications.publish(_camp(calls=[call(2)]))

        assert _commits(session) == [("RecipeBox", WHOLE, SUBJECT, None, READ_AT)]


class TestAppended:
    """An appended call writes the commits and the edits of the Tool Calls
    it carries, from its boundary on, and leaves those before it."""

    def test_those_from_its_boundary_on_are_written_and_those_before_stand(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(
            _camp(
                calls=[
                    call(1, tool_calls=[_commit_call(1)]),
                    call(2, tool_calls=[_edit_call(2)]),
                ]
            )
        )
        held = session.scalars(select(Commit.id)).one()

        publications.publish(
            appended(
                call=2,
                repository="RecipeBox",
                calls=[
                    call(
                        2,
                        tool_calls=[
                            _edit_call(2, file_edits=[file_edit(lines_added=5)])
                        ],
                    ),
                    call(
                        3,
                        tool_calls=[
                            _commit_call(
                                3,
                                commits=[
                                    commit(subject="Season the stew", sha="9d0e1f2")
                                ],
                            )
                        ],
                    ),
                ],
            )
        )

        assert _commits(session) == [
            ("RecipeBox", "3f9a2c1", SUBJECT, "toolu_0001", None),
            ("RecipeBox", "9d0e1f2", "Season the stew", "toolu_0003", None),
        ]
        assert session.scalars(select(Commit.id).order_by(Commit.id)).first() == held
        assert _edits(session) == [("toolu_0002", "RecipeBox", "recipes/stew.md", 5, 1)]


class TestReplayedAtRest:
    """A commit or an edit the replay at rest writes is a row the appended
    calls left other than the file read whole gives (F152.16)."""

    def test_an_edit_it_adds_is_logged_with_the_transcript(
        self,
        session: DbSession,
        publications: PublicationService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        publications.publish(_camp(calls=[call(1, tool_calls=[_commit_call(1)])]))
        publications.publish(
            appended(
                call=2,
                repository="RecipeBox",
                calls=[call(2, tool_calls=[_edit_call(2, file_edits=[])])],
            )
        )

        with caplog.at_level(logging.WARNING, "app.services.publication_service"):
            publications.publish(
                _camp(
                    file_size=61_000,
                    file_modified_at=(STARTED + timedelta(minutes=30)).isoformat(),
                    calls=[
                        call(1, tool_calls=[_commit_call(1)]),
                        call(2, tool_calls=[_edit_call(2)]),
                    ],
                )
            )

        assert [
            record.getMessage()
            for record in caplog.records
            if record.name == "app.services.publication_service"
        ] == [
            f"The replay at rest of transcript {CAMP}, 12888 of its 61000 bytes"
            " taken in parts, wrote rows that differ from what Pilot held:"
            " file_edits 1"
        ]


class TestClaimed:
    """A Commit is made by one Tool Call once (DB 577): a commit whose hash
    Pilot holds as another's is not held again."""

    def test_a_hash_another_conversations_tool_call_holds_is_left_to_it(
        self,
        session: DbSession,
        publications: PublicationService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        publications.publish(_camp(_commit_call(), session_id=OTHER))

        with caplog.at_level(logging.WARNING, LOGGER):
            publications.publish(_camp(_commit_call(), _edit_call()))

        assert _commits(session) == [
            ("RecipeBox", "3f9a2c1", SUBJECT, "toolu_0001", None)
        ]
        made_by = session.scalars(
            select(ToolCall.transcript_id).join(
                Commit, Commit.tool_call_id == ToolCall.id
            )
        ).one()
        assert (
            made_by
            != session.scalars(
                select(ToolCall.transcript_id).where(
                    ToolCall.tool_use_id == "toolu_0002"
                )
            ).one()
        )
        assert _logged(caplog) == [
            f"Transcript {CAMP}: tool call toolu_0001"
            " names the commit 3f9a2c1 of RecipeBox, which Pilot holds as another's"
        ]
        assert len(_edits(session)) == 1

    def test_the_same_hash_in_another_repository_is_another_commit(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp(_commit_call(), session_id=OTHER))

        publications.publish(
            _camp(_commit_call(commits=[commit(repository="RecipeBoxSpecs")]))
        )

        assert len(_commits(session)) == 2


class TestRefused:
    """A call whose commits or edits contradict the record's rules is
    refused, and nothing is written."""

    @pytest.mark.parametrize(
        ("requested", "fault"),
        [
            (
                _edit_call(tool="Bash"),
                "call `msg_0001`: tool call `toolu_0002`: a `Bash` call edits no file",
            ),
            (
                _edit_call(failed=True),
                "call `msg_0001`: tool call `toolu_0002`: a failed call edits no file",
            ),
            (
                _edit_call(file_edits=[file_edit(), file_edit(lines_added=9)]),
                "call `msg_0001`: tool call `toolu_0002`: the file `recipes/stew.md`"
                " of `RecipeBox` is edited twice",
            ),
            (
                _commit_call(commits=[commit(), commit(subject="Plan the stew")]),
                "call `msg_0001`: tool call `toolu_0001`: the commit `3f9a2c1` of"
                " `RecipeBox` is given twice",
            ),
        ],
    )
    def test_a_fault_refuses_the_call(
        self,
        session: DbSession,
        publications: PublicationService,
        requested: dict[str, Any],
        fault: str,
    ) -> None:
        with pytest.raises(PublicationInvalidException) as refused:
            publications.publish(_camp(requested))

        assert fault in str(refused.value)
        assert (_commits(session), _edits(session), _files(session)) == ([], [], [])

    def test_one_hash_under_two_tool_calls_is_a_fault(
        self, publications: PublicationService
    ) -> None:
        with pytest.raises(PublicationInvalidException) as refused:
            publications.publish(_camp(_commit_call(1), _commit_call(2)))

        assert (
            "call `msg_0001`: tool call `toolu_0002`: the commit `3f9a2c1` of"
            " `RecipeBox` is given twice"
        ) in str(refused.value)

    def test_the_same_files_edit_by_two_calls_and_hashes_with_none_are_no_fault(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(
            _camp(
                _commit_call(1, commits=[commit(sha=None), commit(sha=None)]),
                _edit_call(2),
                _edit_call(3),
            )
        )

        assert len(_commits(session)) == 2
        assert len(_edits(session)) == 2
