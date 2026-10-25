"""Documents born in the record and published with their derived caches."""

import threading
from datetime import UTC, datetime

import pytest
from flask import Flask
from psycopg.errors import LockNotAvailable
from sqlalchemy import func, select
from sqlalchemy import text as sql
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.engine.bus import EngineEvent, ProjectChanged, TreeHashMoved
from app.engine.documents import DocumentService, awaiting_read, awaits_read
from app.engine.paths import sha256_hex
from app.exceptions import InvalidOperationException
from app.extensions import db
from app.models import (
    Block,
    BlockOption,
    Document,
    DocumentVersion,
    Environment,
    Item,
    PlanTask,
    Project,
    SaveError,
    User,
)
from app.models.reference import (
    AnswerChannel,
    BlockKind,
    DocumentRole,
    ErrorKind,
    SessionState,
    TaskStatus,
    UserKind,
    VersionCause,
)
from app.services.container import ServiceContainer
from tests.support.locks import in_thread, lock_waits
from tests.support.supervisor import WAIT_SECONDS, wait_until

REGISTERED_PATH = "/work/Example/docs/refinement.md"

ONE_DECISION = """---
title: Which tent for the trip?
step: build
summary: Two nights at the lake.
urgent: true
for: ada
---

The forecast says rain on the second night.

```decision id=D1
options:
  - Dome: sleeps four
  - Tunnel: sleeps six
recommend: Dome
```
"""

ANSWERED = """# Which tent for the trip?

```decision id=D1
options:
  - Dome: sleeps four
  - Tunnel: sleeps six
recommend: Dome
answer: Tunnel
by: ada
at: 2026-10-12T09:40:00Z
note: The cousins are coming.
```

```question id=Q1
default: The lake car park
answer: deferred
by: agent
at: 2026-10-12T10:00:00Z
to: build
note: Ask once the route is fixed.
```

```action id=A1
answer: deferred
by: agent
to: plan
```
"""

CONFIRMATION = """# Ship the order form on Friday?

```decision id=C1
type: confirmation
because: irreversible
proposal: Ship the order form on Friday
check: the form loads at /order
```
"""

QUESTION = "# Where?\n\n```question id=Q1\ndefault: The lake\n```\n"

ACTION_DONE = """# Put the tent in the car

```action id=A1
options: [Works, "Doesn't"]
done: 2026-10-12T11:00:00Z
by: ada
via: chat
```
"""

BROKEN = "```decision id=D1\noptions:\n  - Dome\n"


@pytest.fixture
def build_task(session: DbSession, project: Project) -> PlanTask:
    """The task `build` of ``project``'s plan."""
    task = PlanTask(
        project_id=project.id,
        task_id="build",
        position=1,
        title="Build the camp",
        status_code=TaskStatus.PENDING,
    )
    session.add(task)
    session.flush()
    return task


def _blocks(session: DbSession, document_id: object) -> list[Block]:
    return list(
        session.scalars(
            select(Block)
            .where(Block.document_id == document_id)
            .order_by(Block.position)
        )
    )


def _options(session: DbSession, block: Block) -> list[BlockOption]:
    return list(
        session.scalars(
            select(BlockOption)
            .where(BlockOption.block_id == block.id)
            .order_by(BlockOption.position)
        )
    )


def _versions(session: DbSession, document: Document) -> list[DocumentVersion]:
    return list(
        session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.number)
        )
    )


def _agent(session: DbSession) -> User:
    return session.scalars(select(User).where(User.handle == "agent")).one()


class TestDocumentServiceBirth:
    def test_a_draft_is_born_empty(
        self, session: DbSession, container: ServiceContainer, project: Project
    ) -> None:
        draft = container.document_service().bear_draft(project)

        assert draft.path == "project.md"
        assert draft.project_id == project.id
        assert draft.role_code is DocumentRole.DRAFT
        assert draft.published_text == ""
        assert draft.published_hash == sha256_hex("")
        assert draft.published_at is not None
        assert draft.ingested_text is None
        [version] = _versions(session, draft)
        assert (version.number, version.cause_code) == (1, VersionCause.BORN)
        assert (version.text, version.hash) == ("", sha256_hex(""))
        assert version.session_id is None
        assert project.name is None

    def test_a_templated_draft_names_the_project(
        self, container: ServiceContainer, project: Project
    ) -> None:
        container.document_service().bear_draft(
            project, "---\ntitle: Badge colours\n---\n"
        )

        assert project.name == "Badge colours"

    def test_a_project_has_one_draft(
        self, container: ServiceContainer, project: Project
    ) -> None:
        documents = container.document_service()
        documents.bear_draft(project)

        with pytest.raises(IntegrityError) as raised:
            documents.bear_draft(project)

        # The second draft's path and role are each the first's.
        assert raised.value.orig.diag.constraint_name in {
            "uq_documents_project_path",
            "uq_documents_project_role",
        }

    def test_the_handbook_names_nothing(
        self, session: DbSession, container: ServiceContainer, project: Project
    ) -> None:
        handbook = container.document_service().bear_handbook(
            project, "# Working here\n\nKeep it short.\n"
        )

        assert handbook.path == "handbook.md"
        assert handbook.role_code is DocumentRole.HANDBOOK
        assert handbook.published_text == "# Working here\n\nKeep it short.\n"
        assert [v.cause_code for v in _versions(session, handbook)] == [
            VersionCause.BORN
        ]
        assert project.name is None

    def test_a_prose_item_is_born_with_the_next_seq(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        documents = container.document_service()
        first = documents.bear_item(project, "notice", "The palette", project_session)
        second = documents.bear_item(
            project, "decision", "Which colour?", project_session
        )

        assert (first.seq, second.seq) == (1, 2)
        assert (first.kind_code, first.title) == ("notice", "The palette")
        assert first.created_by_session_id == project_session.id
        assert first.created_by_user_id is None
        document = session.get_one(Document, second.id)
        assert document.path == "items/2-which-colour.md"
        assert document.project_id is None
        assert document.published_text == "---\ntitle: Which colour?\n---\n"
        [version] = _versions(session, document)
        assert version.cause_code is VersionCause.BORN
        assert version.session_id == project_session.id

    def test_an_items_number_is_not_zero_filled(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        session.add(
            Item(
                project_id=project.id,
                seq=9,
                kind_code="notice",
                title="An earlier notice",
                created_by_session_id=project_session.id,
            )
        )
        session.flush()

        item = container.document_service().bear_item(
            project, "notice", "The palette", project_session
        )

        assert item.seq == 10
        assert session.get_one(Document, item.id).path == "items/10-the-palette.md"

    def test_the_next_seq_is_one_past_the_projects_last_item(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        documents = container.document_service()
        assert documents.next_seq(project) == 1
        session.add(
            Item(
                project_id=project.id,
                seq=9,
                kind_code="work",
                title="Renaming",
                created_by_session_id=project_session.id,
            )
        )
        session.flush()

        assert documents.next_seq(project) == 10

    @pytest.mark.parametrize(
        ("title", "path"),
        [
            ("TheTVDB v4 or TVmaze?", "items/1-thetvdb-v4-or-tvmaze.md"),
            ("Crème brûlée — twice", "items/1-creme-brulee-twice.md"),
            ("¿?", "items/1.md"),
            (
                "The quick brown fox jumps over the lazy dog and keeps on running away",
                "items/1-the-quick-brown-fox-jumps-over-the-lazy-dog-and-keeps-on.md",
            ),
            (
                "the quick brown fox jumps over the lazy dog and keeps on runner",
                "items/1-the-quick-brown-fox-jumps-over-the-lazy-dog-and-keeps-on.md",
            ),
            ("x" * 80, f"items/1-{'x' * 60}.md"),
        ],
    )
    def test_an_items_file_is_named_by_its_title(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        title: str,
        path: str,
    ) -> None:
        item = container.document_service().bear_item(
            project, "notice", title, project_session
        )

        assert session.get_one(Document, item.id).path == path

    @pytest.mark.parametrize("kind", ["work", "card_wait", "opening", "palette"])
    def test_only_a_prose_kind_pilot_adds_is_born(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        kind: str,
    ) -> None:
        with pytest.raises(InvalidOperationException) as raised:
            container.document_service().bear_item(
                project, kind, "The palette", project_session
            )

        assert raised.value.message == (
            f"Cannot add a {kind} item to project {project.id}"
            f" because {kind} is not a kind of prose item Pilot adds"
        )
        assert session.scalar(select(func.count()).select_from(Item)) == 0

    @pytest.mark.parametrize(
        ("text", "born"),
        [
            pytest.param("", "---\ntitle: The palette\n---\n", id="empty"),
            pytest.param(
                "Blue and green.\n",
                "---\ntitle: The palette\n---\nBlue and green.\n",
                id="prose",
            ),
            pytest.param(
                "# Two colours\n\nBlue and green.\n",
                "---\ntitle: The palette\n---\n# Two colours\n\nBlue and green.\n",
                id="heading",
            ),
            pytest.param(
                "---\nurgent: true\n---\nBlue and green.\n",
                "---\ntitle: The palette\nurgent: true\n---\nBlue and green.\n",
                id="front-matter",
            ),
            pytest.param(
                "---\r\nurgent: true\r\n---\r\nBlue and green.\r\n",
                "---\r\ntitle: The palette\r\nurgent: true\r\n---\r\n"
                "Blue and green.\r\n",
                id="crlf",
            ),
        ],
    )
    def test_pilots_own_item_is_born_with_its_title_in_its_front_matter(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        text: str,
        born: str,
    ) -> None:
        item = container.document_service().bear_item(
            project, "notice", "The palette", project_session, text
        )

        document = session.get_one(Document, item.id)
        assert document.published_text == born
        assert item.title == "The palette"
        assert _versions(session, document)[0].text == born

    def test_a_title_its_front_matter_gives_is_kept_at_birth(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        text = "---\ntitle: Two colours\n---\nBlue and green.\n"

        item = container.document_service().bear_item(
            project, "notice", "The palette", project_session, text
        )

        document = session.get_one(Document, item.id)
        assert document.published_text == text
        assert item.title == "Two colours"
        assert document.path == "items/1-the-palette.md"

    def test_an_item_born_with_its_text_reads_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
        project_session: models.Session,
        build_task: PlanTask,
    ) -> None:
        item = container.document_service().bear_item(
            project, "notice", "Tent", project_session, ONE_DECISION
        )

        assert item.kind_code == "decision"
        assert item.title == "Which tent for the trip?"
        assert (item.plan_task_id, item.urgent, item.for_user_id) == (
            "build",
            True,
            person.id,
        )
        assert session.get_one(Document, item.id).summary == "Two nights at the lake."
        assert [b.local_id for b in _blocks(session, item.id)] == ["D1"]

    def test_the_opening_is_a_persons_words_under_its_given_title(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
    ) -> None:
        words = "---\ntitle: Something else\n---\n# A heading\n\nWe need a badge.\n"
        opening = container.document_service().bear_opening(
            project, "Badge colours", person, words
        )

        assert (opening.seq, opening.kind_code) == (1, "opening")
        assert opening.title == "Badge colours"
        assert opening.created_by_user_id == person.id
        assert opening.created_by_session_id is None
        document = session.get_one(Document, opening.id)
        assert document.path == "items/1-badge-colours.md"
        assert document.published_text == words
        assert document.summary is None
        [version] = _versions(session, document)
        assert version.session_id is None

    @pytest.mark.parametrize("words", [ONE_DECISION, BROKEN])
    def test_the_opening_is_born_unread_with_no_blocks(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
        words: str,
    ) -> None:
        opening = container.document_service().bear_opening(
            project, "Badge colours", person, words
        )

        assert (opening.kind_code, opening.title) == ("opening", "Badge colours")
        assert (opening.plan_task_id, opening.urgent, opening.for_user_id) == (
            None,
            False,
            None,
        )
        assert session.get_one(Document, opening.id).published_text == words
        assert _blocks(session, opening.id) == []

    def test_a_born_text_with_a_fault_is_refused(
        self, session: DbSession, container: ServiceContainer, project: Project
    ) -> None:
        with pytest.raises(InvalidOperationException) as raised:
            container.document_service().bear_draft(project, BROKEN)

        assert raised.value.message.startswith(
            f"Cannot publish draft-{project.number}/project.md because its text"
            " holds a fault: line 1: a fence opened with ``` is not closed"
        )
        assert session.scalar(select(func.count()).select_from(Document)) == 0

    def test_an_item_born_with_a_fault_is_not_minted(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        with pytest.raises(InvalidOperationException) as raised:
            container.document_service().bear_item(
                project, "decision", "Which tent?", project_session, BROKEN
            )

        assert raised.value.message.startswith(
            f"Cannot publish draft-{project.number}/items/1-which-tent.md"
        )
        session.flush()
        assert session.scalar(select(func.count()).select_from(Item)) == 0

    def test_a_drafts_birth_moves_its_path_after_the_commit(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
    ) -> None:
        with scoped_session(container):
            container.document_service().bear_draft(project)
            assert engine_events == []

        assert engine_events == [
            TreeHashMoved(f"draft-{project.number}/project.md", sha256_hex(""))
        ]

    def test_a_titled_drafts_birth_moves_the_timeline(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
    ) -> None:
        text = "---\ntitle: Badge colours\n---\n"
        with scoped_session(container):
            container.document_service().bear_draft(project, text)

        folder = f"draft-{project.number}"
        assert engine_events == [
            TreeHashMoved(f"{folder}/project.md", sha256_hex(text)),
            TreeHashMoved(
                f"{folder}/timeline.json",
                container.view_service().timeline(project).hash,
            ),
            ProjectChanged(project.id),
        ]

    def test_the_handbooks_birth_moves_its_path_alone(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
    ) -> None:
        with scoped_session(container):
            container.document_service().bear_handbook(project, "Keep it short.\n")

        assert engine_events == [
            TreeHashMoved(
                f"draft-{project.number}/handbook.md", sha256_hex("Keep it short.\n")
            )
        ]

    def test_an_items_birth_moves_its_path_and_the_timeline(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
    ) -> None:
        with scoped_session(container):
            container.document_service().bear_item(
                project, "notice", "The palette", project_session
            )

        folder = f"draft-{project.number}"
        assert engine_events == [
            TreeHashMoved(
                f"{folder}/items/1-the-palette.md",
                sha256_hex("---\ntitle: The palette\n---\n"),
            ),
            TreeHashMoved(
                f"{folder}/timeline.json",
                container.view_service().timeline(project).hash,
            ),
            ProjectChanged(project.id),
        ]


def _committed_run(app: Flask) -> tuple[object, object]:
    """A draft project and a work Session of it, committed: their ids."""
    with scoped_session(app.container) as session:
        person = User(
            kind_code=UserKind.PERSON,
            subject="subject-ada",
            handle="ada",
            name="Ada Example",
            avatar_slot=1,
        )
        session.add(person)
        session.flush()
        project = Project(created_by_user_id=person.id)
        session.add(project)
        session.add(Environment(id="example-env-1", name="Example-1", exempt=False))
        session.flush()
        run = models.Session(
            project_id=project.id,
            environment_id="example-env-1",
            kind_code="work",
            cwd="/work/Example",
            token_hash="1" * 64,
            state_code=SessionState.RUNNING,
        )
        session.add(run)
        session.flush()
        return project.id, run.id


class TestDocumentServiceRegister:
    def test_a_registered_document_is_minted_with_no_text(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        documents = container.document_service()
        documents.bear_item(project, "notice", "The palette", project_session)

        registration = documents.register(project, project_session, REGISTERED_PATH)

        item = registration.item
        assert registration.minted
        assert (item.project_id, item.seq, item.kind_code, item.title) == (
            project.id,
            2,
            "review",
            None,
        )
        assert (item.created_by_session_id, item.created_by_user_id) == (
            project_session.id,
            None,
        )
        assert item.done_at is None
        document = session.get_one(Document, item.id)
        assert (
            document.path,
            document.source_environment_id,
            document.source_path,
        ) == ("inbox/2-refinement.md", environment.id, REGISTERED_PATH)
        assert (document.published_text, document.ingested_text) == (None, None)
        assert (document.summary, document.written_back_at) == (None, None)
        assert _versions(session, document) == []
        assert _blocks(session, document.id) == []
        assert awaits_read(item, document)

    @pytest.mark.parametrize(
        ("source_path", "path"),
        [
            (
                "/work/Example/TheTVDB v4 or TVmaze.md",
                "inbox/1-thetvdb-v4-or-tvmaze.md",
            ),
            ("/work/Example/Crème brûlée.md", "inbox/1-creme-brulee.md"),
            ("/work/Example/notes", "inbox/1-notes.md"),
            ("/work/Example/¿?.md", "inbox/1.md"),
            ("/work/Example/" + "x" * 80 + ".md", f"inbox/1-{'x' * 60}.md"),
        ],
    )
    def test_its_file_in_the_tree_is_named_by_its_files_name(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        source_path: str,
        path: str,
    ) -> None:
        registration = container.document_service().register(
            project, project_session, source_path
        )

        assert session.get_one(Document, registration.item.id).path == path

    def test_a_path_registered_again_in_the_run_is_the_same_item(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        documents = container.document_service()
        first = documents.register(project, project_session, REGISTERED_PATH)

        again = documents.register(project, project_session, REGISTERED_PATH)
        other = documents.register(project, project_session, "/work/Example/other.md")

        assert (again.item.id, again.minted) == (first.item.id, False)
        assert (other.item.seq, other.minted) == (2, True)
        assert session.scalar(select(func.count()).select_from(Item)) == 2

    def test_a_later_runs_registration_of_the_path_is_a_new_item(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
        person: User,
    ) -> None:
        documents = container.document_service()
        answered = documents.register(project, project_session, REGISTERED_PATH).item
        answered.done_at = datetime.now(UTC)
        answered.done_cause_code = "finished"
        answered.done_by_user_id = person.id
        continuation = models.Session(
            project_id=project.id,
            environment_id=environment.id,
            kind_code="work",
            cwd="/work/Example",
            token_hash="2" * 64,
            state_code=SessionState.RUNNING,
        )
        session.add(continuation)
        session.flush()

        registration = documents.register(project, continuation, REGISTERED_PATH)

        assert registration.minted
        assert registration.item.id != answered.id
        assert registration.item.created_by_session_id == continuation.id
        assert answered.done_cause_code == "finished"

    def test_a_registration_moves_the_timeline_and_no_path_of_the_tree(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
    ) -> None:
        with scoped_session(container):
            container.document_service().register(
                project, project_session, REGISTERED_PATH
            )

        assert engine_events == [
            TreeHashMoved(
                f"draft-{project.number}/timeline.json",
                container.view_service().timeline(project).hash,
            ),
            ProjectChanged(project.id),
        ]

    def test_a_registration_waits_for_the_projects_row(
        self, committed_app: Flask
    ) -> None:
        project_id, run_id = _committed_run(committed_app)
        container = committed_app.container
        with committed_app.app_context():
            engine = db.engine

        with engine.connect() as holder:
            holder.execute(
                sql("SELECT id FROM projects WHERE id = :id FOR KEY SHARE"),
                {"id": project_id},
            )
            with (
                pytest.raises(OperationalError) as raised,
                scoped_session(container) as session,
            ):
                session.execute(sql("SET LOCAL lock_timeout = '200ms'"))
                container.document_service().register(
                    session.get_one(Project, project_id),
                    session.get_one(models.Session, run_id),
                    REGISTERED_PATH,
                )
            holder.rollback()

        assert isinstance(raised.value.orig, LockNotAvailable)
        with scoped_session(container) as session:
            assert session.scalar(select(func.count()).select_from(Item)) == 0

    def test_a_path_registered_twice_at_once_is_minted_once(
        self, committed_app: Flask, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_id, run_id = _committed_run(committed_app)
        container = committed_app.container
        locked, release = threading.Event(), threading.Event()
        next_seq = DocumentService.next_seq
        threads: list[threading.Thread] = []

        def held_next_seq(self: DocumentService, project: Project) -> int:
            seq = next_seq(self, project)
            if threading.current_thread() is threads[0]:
                locked.set()
                assert release.wait(WAIT_SECONDS)
            return seq

        def register() -> tuple[object, bool]:
            with scoped_session(container) as session:
                registration = container.document_service().register(
                    session.get_one(Project, project_id),
                    session.get_one(models.Session, run_id),
                    REGISTERED_PATH,
                )
                return registration.item.id, registration.minted

        monkeypatch.setattr(DocumentService, "next_seq", held_next_seq)
        first = in_thread(register)
        threads.append(first.thread)
        try:
            assert locked.wait(WAIT_SECONDS)
            second = in_thread(register)
            wait_until(lambda: lock_waits(container) == 1, "the second waiting")
        finally:
            release.set()

        first_id, minted = first.result()
        assert minted
        assert second.result() == (first_id, False)
        with scoped_session(container) as session:
            assert session.scalar(select(func.count()).select_from(Item)) == 1

    def test_its_first_text_gives_it_its_file_and_shows_on_the_timeline(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
    ) -> None:
        with scoped_session(container):
            documents = container.document_service()
            item_id = documents.register(
                project, project_session, REGISTERED_PATH
            ).item.id
        engine_events.clear()
        text = "# Refinement\n\nTwo options.\n"

        with scoped_session(container) as db_session:
            documents = container.document_service()
            documents.publish(db_session.get_one(Document, item_id), text)

        folder = f"draft-{project.number}"
        assert engine_events == [
            TreeHashMoved(f"{folder}/inbox/1-refinement.md", sha256_hex(text)),
            TreeHashMoved(
                f"{folder}/timeline.json",
                container.view_service().timeline(project).hash,
            ),
            ProjectChanged(project.id),
        ]
        assert (
            container.tree_service().read(f"{folder}/inbox/1-refinement.md").content
            == text.encode()
        )


class TestAwaitsRead:
    def test_a_registered_document_awaits_its_read_while_open_with_no_text(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        documents = container.document_service()
        item = documents.register(project, project_session, REGISTERED_PATH).item
        document = session.get_one(Document, item.id)
        assert awaits_read(item, document)

        item.done_at = datetime.now(UTC)
        item.done_cause_code = "finished"
        item.done_by_user_id = person.id
        assert not awaits_read(item, document)

    def test_a_document_with_a_text_awaits_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        documents = container.document_service()
        own = documents.bear_item(project, "notice", "The palette", project_session)
        registered = documents.bear_item(project, "review", "Notes", project_session)
        registered_document = session.get_one(Document, registered.id)
        registered_document.source_environment_id = environment.id
        registered_document.source_path = REGISTERED_PATH

        assert not awaits_read(own, session.get_one(Document, own.id))
        assert not awaits_read(registered, registered_document)

    def test_a_document_whose_read_failed_awaits_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        documents = container.document_service()
        item = documents.register(project, project_session, REGISTERED_PATH).item
        document = session.get_one(Document, item.id)

        documents.fail_read(document)

        assert not awaits_read(item, document)


class TestAwaitingRead:
    def test_the_condition_holds_for_the_documents_the_predicate_does(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        documents = container.document_service()
        awaiting = documents.register(project, project_session, REGISTERED_PATH).item
        failed = documents.register(project, project_session, "/work/E/f.md").item
        documents.fail_read(session.get_one(Document, failed.id))
        read = documents.register(project, project_session, "/work/E/r.md").item
        documents.publish_read(
            session.get_one(Document, read.id), QUESTION, project_session.id
        )
        closed = documents.register(project, project_session, "/work/E/c.md").item
        closed.done_at = datetime.now(UTC)
        closed.done_cause_code = "finished"
        closed.done_by_user_id = person.id
        own = documents.bear_item(project, "notice", "The palette", project_session)
        session.flush()

        matching = session.scalars(
            select(Item.id)
            .join(Document, Document.id == Item.id)
            .where(awaiting_read())
        ).all()

        assert matching == [awaiting.id]
        assert [
            awaits_read(item, session.get_one(Document, item.id))
            for item in (awaiting, failed, read, closed, own)
        ] == [True, False, False, False, False]


class TestDocumentServicePublishRead:
    @pytest.mark.usefixtures("build_task")
    def test_the_file_is_published_as_written_its_first_version_registered(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        documents = container.document_service()
        item = documents.register(project, project_session, REGISTERED_PATH).item
        document = session.get_one(Document, item.id)

        documents.publish_read(document, ONE_DECISION, project_session.id)

        assert document.published_text == ONE_DECISION
        assert document.summary == "Two nights at the lake."
        assert (
            item.kind_code,
            item.title,
            item.plan_task_id,
            item.urgent,
            item.for_user_id,
        ) == ("decision", "Which tent for the trip?", "build", True, person.id)
        assert [block.local_id for block in _blocks(session, document.id)] == ["D1"]
        [version] = _versions(session, document)
        assert (
            version.number,
            version.cause_code,
            version.text,
            version.session_id,
        ) == (1, VersionCause.REGISTERED, ONE_DECISION, project_session.id)
        assert not awaits_read(item, document)

    def test_it_gives_the_document_its_file_in_the_tree_live(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
    ) -> None:
        with scoped_session(container) as session:
            documents = container.document_service()
            item = documents.register(project, project_session, REGISTERED_PATH).item
        engine_events.clear()

        with scoped_session(container) as session:
            documents.publish_read(
                session.get_one(Document, item.id), QUESTION, project_session.id
            )

        path = f"draft-{project.number}/inbox/1-refinement.md"
        assert TreeHashMoved(path, sha256_hex(QUESTION)) in engine_events
        assert ProjectChanged(project.id) in engine_events
        assert container.tree_service().read(path).content == QUESTION.encode()

    def test_a_text_with_a_fault_is_refused_and_nothing_written(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        documents = container.document_service()
        item = documents.register(project, project_session, REGISTERED_PATH).item
        document = session.get_one(Document, item.id)

        with pytest.raises(InvalidOperationException):
            documents.publish_read(document, BROKEN, project_session.id)

        assert document.published_text is None
        assert _versions(session, document) == []
        assert awaits_read(item, document)


class TestDocumentServiceFailRead:
    def test_the_document_keeps_no_text_and_says_so_live(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
    ) -> None:
        with scoped_session(container) as session:
            documents = container.document_service()
            item = documents.register(project, project_session, REGISTERED_PATH).item
        engine_events.clear()
        before = datetime.now(UTC)

        with scoped_session(container) as session:
            document = session.get_one(Document, item.id)
            documents.fail_read(document)

        assert document.read_failed_at is not None
        assert before <= document.read_failed_at <= datetime.now(UTC)
        assert (document.published_text, document.source_path) == (
            None,
            REGISTERED_PATH,
        )
        assert _versions(session, document) == []
        # Its file is nowhere: the tree and timeline.json are unmoved.
        assert engine_events == [ProjectChanged(project.id)]

    def test_a_document_with_a_text_has_no_failed_read(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        documents = container.document_service()
        item = documents.register(project, project_session, REGISTERED_PATH).item
        document = session.get_one(Document, item.id)
        documents.publish_read(document, QUESTION, project_session.id)

        with pytest.raises(IntegrityError, match="ck_documents_read_failed"):
            documents.fail_read(document)


class TestDocumentServicePublish:
    def test_publish_sets_the_published_text_and_cuts_no_version(
        self, session: DbSession, container: ServiceContainer, project: Project
    ) -> None:
        documents = container.document_service()
        draft = documents.bear_draft(project)
        born_at = draft.published_at

        documents.publish(draft, "Some prose.\n")

        assert draft.published_text == "Some prose.\n"
        assert draft.published_hash == sha256_hex("Some prose.\n")
        assert born_at is not None and draft.published_at is not None
        assert draft.published_at > born_at
        assert draft.ingested_text is None
        assert len(_versions(session, draft)) == 1

    def test_a_publish_moves_the_documents_tree_hash(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
    ) -> None:
        documents = container.document_service()
        draft = documents.bear_draft(project)
        with scoped_session(container):
            pass
        engine_events.clear()

        with scoped_session(container):
            documents.publish(draft, "Some prose.\n")
            assert engine_events == []

        assert engine_events == [
            TreeHashMoved(
                f"draft-{project.number}/project.md", sha256_hex("Some prose.\n")
            )
        ]

    def test_a_publish_of_the_same_text_moves_nothing(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
    ) -> None:
        documents = container.document_service()
        draft = documents.bear_draft(project, "Some prose.\n")
        with scoped_session(container):
            pass
        engine_events.clear()

        with scoped_session(container):
            documents.publish(draft, "Some prose.\n")

        assert engine_events == []

    def test_a_held_path_keeps_its_tree_hash(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        environment: Environment,
    ) -> None:
        documents = container.document_service()
        draft = documents.bear_draft(project)
        draft.ingested_text = BROKEN
        draft.ingested_hash = sha256_hex(BROKEN)
        draft.ingested_at = datetime.now(UTC)
        session.add(
            SaveError(
                environment_id=environment.id,
                path=f"draft-{project.number}/project.md",
                kind_code=ErrorKind.PARSE,
                line=1,
                message="a fence opened with ``` is not closed",
            )
        )
        with scoped_session(container):
            pass
        engine_events.clear()

        with scoped_session(container):
            documents.publish(draft, "Some prose.\n")

        assert draft.published_text == "Some prose.\n"
        assert engine_events == []

    def test_a_held_items_publish_changes_its_project_alone(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        documents = container.document_service()
        item = documents.bear_item(project, "notice", "The palette", project_session)
        document = session.get_one(Document, item.id)
        document.ingested_text = BROKEN
        document.ingested_hash = sha256_hex(BROKEN)
        document.ingested_at = datetime.now(UTC)
        session.add(
            SaveError(
                environment_id=environment.id,
                path=f"draft-{project.number}/items/1-the-palette.md",
                kind_code=ErrorKind.PARSE,
                line=1,
                message="a fence opened with ``` is not closed",
            )
        )
        with scoped_session(container):
            pass
        engine_events.clear()

        with scoped_session(container):
            documents.publish(document, "---\ntitle: The palette\n---\n\nBlue.\n")

        assert engine_events == [ProjectChanged(project.id)]

    def test_an_items_publish_of_the_same_text_changes_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
    ) -> None:
        documents = container.document_service()
        item = documents.bear_item(project, "notice", "The palette", project_session)
        document = session.get_one(Document, item.id)
        with scoped_session(container):
            pass
        engine_events.clear()

        with scoped_session(container):
            documents.publish(document, "---\ntitle: The palette\n---\n")

        assert engine_events == []

    def test_a_text_with_a_fault_is_not_published(
        self, container: ServiceContainer, project: Project
    ) -> None:
        documents = container.document_service()
        draft = documents.bear_draft(project, "Some prose.\n")

        with pytest.raises(InvalidOperationException):
            documents.publish(draft, BROKEN)

        assert draft.published_text == "Some prose.\n"

    def test_the_drafts_title_names_the_project(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
    ) -> None:
        documents = container.document_service()
        draft = documents.bear_draft(project)
        folder = f"draft-{project.number}"

        def published(text: str) -> list[str]:
            with scoped_session(container):
                pass
            engine_events.clear()
            with scoped_session(container):
                documents.publish(draft, text)
            return [e.path for e in engine_events if isinstance(e, TreeHashMoved)]

        assert published("---\ntitle: Badge colours\n---\nProse.\n") == [
            f"{folder}/project.md",
            f"{folder}/timeline.json",
        ]
        assert project.name == "Badge colours"
        assert published("# Badges\n\nProse.\n") == [
            f"{folder}/project.md",
            f"{folder}/timeline.json",
        ]
        assert project.name == "Badges"
        assert published("# Badges\n\nMore prose.\n") == [f"{folder}/project.md"]
        assert published("Prose.\n") == [
            f"{folder}/project.md",
            f"{folder}/timeline.json",
        ]
        assert project.name is None

    def test_an_items_caches_follow_its_front_matter(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
        project_session: models.Session,
        build_task: PlanTask,
    ) -> None:
        documents = container.document_service()
        item = documents.bear_item(project, "notice", "Tent", project_session)
        document = session.get_one(Document, item.id)

        documents.publish(document, ONE_DECISION)

        assert item.title == "Which tent for the trip?"
        assert item.plan_task_id == "build"
        assert item.urgent is True
        assert item.for_user_id == person.id
        assert document.summary == "Two nights at the lake."

        documents.publish(document, ONE_DECISION.split("---\n", 2)[2])

        assert item.plan_task_id is None
        assert item.urgent is False
        assert item.for_user_id is None
        assert document.summary is None

    def test_an_items_title_is_its_texts_alone(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        documents = container.document_service()
        item = documents.bear_item(project, "notice", "The palette", project_session)
        document = session.get_one(Document, item.id)

        documents.publish(document, "---\ntitle: Two colours\n---\n# Blue\n")
        assert item.title == "Two colours"

        documents.publish(document, "# Blue and green\n")
        assert item.title == "Blue and green"

    def test_a_registered_documents_title_is_none_while_its_text_gives_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        documents = container.document_service()
        item = documents.bear_item(project, "notice", "The palette", project_session)
        document = session.get_one(Document, item.id)
        document.source_environment_id = environment.id
        document.source_path = "/work/Example/palette.md"

        documents.publish(document, "Blue and green.\n")
        session.flush()
        assert item.title is None

        documents.publish(document, "# Two colours\n\nBlue and green.\n")
        assert item.title == "Two colours"

        documents.publish(document, "Blue and green.\n")
        session.flush()
        assert item.title is None

    @pytest.mark.parametrize(
        ("text", "kind"),
        [
            ("Blue and green.\n", "notice"),
            (ONE_DECISION.split("---\n", 2)[2], "decision"),
            (QUESTION, "question"),
            (ACTION_DONE, "action"),
            (CONFIRMATION, "confirmation"),
            (ANSWERED, "document"),
        ],
    )
    def test_an_items_kind_follows_its_blocks(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
        project_session: models.Session,
        build_task: PlanTask,
        text: str,
        kind: str,
    ) -> None:
        documents = container.document_service()
        item = documents.bear_item(project, "notice", "The palette", project_session)

        documents.publish(session.get_one(Document, item.id), text)

        assert item.kind_code == kind

    @pytest.mark.parametrize("text", [ONE_DECISION, BROKEN])
    def test_the_openings_text_is_published_unread(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
        build_task: PlanTask,
        text: str,
    ) -> None:
        documents = container.document_service()
        opening = documents.bear_opening(
            project, "Badge colours", person, "We need a badge.\n"
        )
        document = session.get_one(Document, opening.id)

        documents.publish(document, text)

        assert document.published_text == text
        assert (opening.kind_code, opening.title) == ("opening", "Badge colours")
        assert (opening.plan_task_id, opening.urgent, opening.for_user_id) == (
            None,
            False,
            None,
        )
        assert document.summary is None
        assert _blocks(session, opening.id) == []

    def test_the_timeline_moves_with_what_it_shows(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
    ) -> None:
        documents = container.document_service()
        item = documents.bear_item(project, "notice", "The palette", project_session)
        document = session.get_one(Document, item.id)
        path = f"draft-{project.number}/items/1-the-palette.md"
        with scoped_session(container):
            pass
        engine_events.clear()

        with scoped_session(container):
            documents.publish(document, "# Two colours\n")
        assert engine_events == [
            TreeHashMoved(path, sha256_hex("# Two colours\n")),
            TreeHashMoved(
                f"draft-{project.number}/timeline.json",
                container.view_service().timeline(project).hash,
            ),
            ProjectChanged(project.id),
        ]

        engine_events.clear()
        with scoped_session(container):
            documents.publish(document, "# Two colours\n\nBlue and green.\n")
        assert engine_events == [
            TreeHashMoved(path, sha256_hex("# Two colours\n\nBlue and green.\n")),
            ProjectChanged(project.id),
        ]

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param(
                "# The palette\n\n```question id=Q1\ndefault: Blue\n```\n", id="kind"
            ),
            pytest.param("# Two colours\n\nBlue and green.\n", id="title"),
            pytest.param(
                "---\nstep: build\n---\n# The palette\n\nBlue and green.\n", id="step"
            ),
            pytest.param(
                "---\nurgent: true\n---\n# The palette\n\nBlue and green.\n",
                id="urgent",
            ),
            pytest.param(
                "---\nfor: ada\n---\n# The palette\n\nBlue and green.\n", id="for"
            ),
            pytest.param(
                "---\nsummary: Two colours.\n---\n# The palette\n\nBlue and green.\n",
                id="summary",
            ),
        ],
    )
    def test_each_cache_the_timeline_shows_moves_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
        build_task: PlanTask,
        text: str,
    ) -> None:
        documents = container.document_service()
        item = documents.bear_item(
            project,
            "notice",
            "The palette",
            project_session,
            "# The palette\n\nBlue and green.\n",
        )
        document = session.get_one(Document, item.id)
        with scoped_session(container):
            pass
        engine_events.clear()

        with scoped_session(container):
            documents.publish(document, text)

        folder = f"draft-{project.number}"
        assert engine_events == [
            TreeHashMoved(f"{folder}/items/1-the-palette.md", sha256_hex(text)),
            TreeHashMoved(
                f"{folder}/timeline.json",
                container.view_service().timeline(project).hash,
            ),
            ProjectChanged(project.id),
        ]


class TestDocumentServiceBlocks:
    def test_blocks_are_read_from_the_text(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
        build_task: PlanTask,
    ) -> None:
        draft = container.document_service().bear_draft(project, ANSWERED)

        decision, question, action = _blocks(session, draft.id)
        assert (decision.local_id, decision.position, decision.kind_code) == (
            "D1",
            1,
            BlockKind.DECISION,
        )
        assert decision.answer == "Tunnel"
        assert decision.answered_by_user_id == person.id
        assert decision.answered_at == datetime(2026, 10, 12, 9, 40, tzinfo=UTC)
        assert decision.note == "The cousins are coming."
        assert decision.via_code is AnswerChannel.APP
        assert decision.deferred_to_task_id is None
        assert [
            (o.label, o.text, o.recommended) for o in _options(session, decision)
        ] == [
            ("Dome", "sleeps four", True),
            ("Tunnel", "sleeps six", False),
        ]
        assert (question.kind_code, question.default_value) == (
            BlockKind.QUESTION,
            "The lake car park",
        )
        assert question.answer == "deferred"
        assert question.answered_by_user_id == _agent(session).id
        assert question.via_code is None
        assert question.deferred_to_task_id == "build"
        assert (action.position, action.answer) == (3, "deferred")
        assert action.deferred_to_task_id is None
        assert _options(session, action) == []

    def test_a_confirmation_keeps_its_reason_and_its_check(
        self, session: DbSession, container: ServiceContainer, project: Project
    ) -> None:
        draft = container.document_service().bear_draft(project, CONFIRMATION)

        [block] = _blocks(session, draft.id)
        assert block.confirmation is True
        assert block.because_code == "irreversible"
        assert block.proposal == "Ship the order form on Friday"
        # F30.8 is Later: `check` is kept and nothing acts on it.
        assert block.check_text == "the form loads at /order"
        assert block.answer is None

    def test_an_actions_done_is_read(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
    ) -> None:
        draft = container.document_service().bear_draft(project, ACTION_DONE)

        [block] = _blocks(session, draft.id)
        assert block.done_at == datetime(2026, 10, 12, 11, 0, tzinfo=UTC)
        assert block.answered_by_user_id == person.id
        assert block.via_code is AnswerChannel.CHAT
        assert [(o.label, o.text) for o in _options(session, block)] == [
            ("Works", None),
            ("Doesn't", None),
        ]

    def test_blocks_are_rewritten_in_place(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
        build_task: PlanTask,
    ) -> None:
        documents = container.document_service()
        draft = documents.bear_draft(project, ANSWERED)
        ids = {b.local_id: b.id for b in _blocks(session, draft.id)}
        question = ANSWERED.split("```question", 1)[1].split("```\n", 1)[0]
        decision = ANSWERED.split("```decision", 1)[1].split("```\n", 1)[0]
        reordered = (
            f"```question{question}```\n\n"
            f"```decision{decision.replace('answer: Tunnel', 'answer: Dome')}```\n"
        )

        documents.publish(draft, reordered)

        rows = _blocks(session, draft.id)
        assert [(b.local_id, b.position) for b in rows] == [("Q1", 1), ("D1", 2)]
        assert [b.id for b in rows] == [ids["Q1"], ids["D1"]]
        assert rows[1].answer == "Dome"
        assert session.get(Block, ids["A1"]) is None

    def test_a_dropped_block_goes_with_its_options(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
        build_task: PlanTask,
    ) -> None:
        documents = container.document_service()
        draft = documents.bear_draft(project, ANSWERED)
        decision = _blocks(session, draft.id)[0]

        documents.publish(draft, QUESTION)

        assert [b.local_id for b in _blocks(session, draft.id)] == ["Q1"]
        assert (
            session.scalar(
                select(func.count())
                .select_from(BlockOption)
                .where(BlockOption.block_id == decision.id)
            )
            == 0
        )

    def test_options_are_rewritten_only_when_they_change(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
        build_task: PlanTask,
    ) -> None:
        documents = container.document_service()
        draft = documents.bear_draft(project, ANSWERED)
        decision = _blocks(session, draft.id)[0]
        kept = [o.id for o in _options(session, decision)]

        documents.publish(draft, ANSWERED.replace("by: ada", "by: ada\nvia: chat"))
        assert [o.id for o in _options(session, decision)] == kept

        documents.publish(
            draft, ANSWERED.replace("recommend: Dome", "recommend: Tunnel")
        )
        options = _options(session, decision)
        assert [(o.label, o.recommended) for o in options] == [
            ("Dome", False),
            ("Tunnel", True),
        ]
        assert not set(kept) & {o.id for o in options}


class TestDocumentServiceLock:
    def test_lock_reads_the_document_and_its_owner_as_committed(
        self, committed_app: Flask
    ) -> None:
        container = committed_app.container
        with scoped_session(container) as session:
            person = User(
                kind_code=UserKind.PERSON,
                subject="subject-ada",
                handle="ada",
                name="Ada Example",
                avatar_slot=1,
            )
            session.add(person)
            session.flush()
            project = Project(created_by_user_id=person.id)
            session.add(project)
            session.add(Environment(id="example-env-1", name="Example-1", exempt=False))
            session.flush()
            run = models.Session(
                project_id=project.id,
                environment_id="example-env-1",
                kind_code="work",
                cwd="/work/Example",
                token_hash="1" * 64,
                state_code=SessionState.RUNNING,
            )
            session.add(run)
            session.flush()
            documents = container.document_service()
            draft_id = documents.bear_draft(project, "# Badges\n").id
            item_id = documents.bear_item(project, "notice", "The palette", run).id

        with committed_app.app_context():
            engine = db.engine
        with scoped_session(container) as session:
            draft = session.get_one(Document, draft_id)
            item = session.get_one(Item, item_id)
            owner = session.get_one(Project, draft.project_id)
            with engine.begin() as other:
                other.execute(
                    sql(
                        "UPDATE documents SET published_text = 'x', published_hash = 'x'"
                        " WHERE id = :id"
                    ),
                    {"id": draft_id},
                )
                other.execute(
                    sql("UPDATE projects SET name = 'Palette' WHERE id = :id"),
                    {"id": owner.id},
                )
                other.execute(
                    sql("UPDATE items SET title = 'Colours' WHERE id = :id"),
                    {"id": item_id},
                )
            assert owner.name == "Badges"

            documents = container.document_service()
            documents.lock(draft)
            documents.lock(session.get_one(Document, item_id))

            assert draft.published_text == "x"
            assert owner.name == "Palette"
            assert item.title == "Colours"


class TestDocumentServiceOwner:
    def test_a_project_documents_owner_is_its_project(
        self, container: ServiceContainer, project: Project
    ) -> None:
        draft = container.document_service().bear_draft(project)

        assert container.document_service().owner(draft) == (project, None)

    def test_a_prose_items_owner_is_its_project_and_item(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        documents = container.document_service()
        item = documents.bear_item(project, "notice", "The palette", project_session)

        assert documents.owner(session.get_one(Document, item.id)) == (project, item)


class TestDocumentServiceVersions:
    def test_a_version_is_numbered_after_the_highest(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        documents = container.document_service()
        draft = documents.bear_draft(project, "# Badges\n")
        documents.publish(draft, "# Badge colours\n")

        documents.cut_version(draft, VersionCause.TURN, project_session.id)
        documents.cut_version(draft, VersionCause.DONE)

        assert [
            (version.number, version.cause_code, version.text, version.session_id)
            for version in _versions(session, draft)
        ] == [
            (1, VersionCause.BORN, "# Badges\n", None),
            (2, VersionCause.TURN, "# Badge colours\n", project_session.id),
            (3, VersionCause.DONE, "# Badge colours\n", None),
        ]
        assert _versions(session, draft)[2].hash == sha256_hex("# Badge colours\n")


def _save(
    container: ServiceContainer,
    environment: Environment,
    path: str,
    text: str,
    run: models.Session,
) -> None:
    container.ingest_service().ingest(path, text.encode(), None, environment, run)


class TestDocumentServiceTurnEnded:
    def test_a_turn_end_clears_the_writing_and_versions_what_moved(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        documents = container.document_service()
        draft = documents.bear_draft(project, "# Badges\n")
        _save(
            container,
            environment,
            f"draft-{project.number}/project.md",
            "# Badge colours\n",
            project_session,
        )
        assert draft.writing_session_id == project_session.id

        held = documents.turn_ended(project_session)

        assert held == []
        assert (draft.writing_session_id, draft.writing_since) == (None, None)
        assert [
            (version.number, version.cause_code, version.text, version.session_id)
            for version in _versions(session, draft)
        ] == [
            (1, VersionCause.BORN, "# Badges\n", None),
            (2, VersionCause.TURN, "# Badge colours\n", project_session.id),
        ]

    def test_no_version_where_the_published_hash_did_not_move(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        documents = container.document_service()
        draft = documents.bear_draft(project, "# Badges\n")
        _save(
            container,
            environment,
            f"draft-{project.number}/project.md",
            "# Badges\n",
            project_session,
        )

        assert documents.turn_ended(project_session) == []

        assert draft.writing_session_id is None
        assert len(_versions(session, draft)) == 1

    def test_a_record_write_since_the_last_version_is_versioned(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
        person: User,
    ) -> None:
        documents = container.document_service()
        text = "# Badges\n\n```question id=Q1\ndefault: Blue\n```\n"
        draft = documents.bear_draft(project, text)
        _save(
            container,
            environment,
            f"draft-{project.number}/project.md",
            text,
            project_session,
        )
        container.record_service().answer(draft, "Q1", person, "Green")

        documents.turn_ended(project_session)

        assert [
            (version.cause_code, version.text) for version in _versions(session, draft)
        ] == [(VersionCause.BORN, text), (VersionCause.TURN, draft.published_text)]

    def test_a_held_path_is_returned_and_not_versioned(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        documents = container.document_service()
        draft = documents.bear_draft(project, "# Badges\n")
        item = documents.bear_item(project, "notice", "The palette", project_session)
        handbook = documents.bear_handbook(project)
        folder = f"draft-{project.number}"
        _save(container, environment, f"{folder}/project.md", BROKEN, project_session)
        _save(
            container,
            environment,
            f"{folder}/items/1-the-palette.md",
            BROKEN,
            project_session,
        )
        _save(
            container, environment, f"{folder}/handbook.md", "Short.\n", project_session
        )

        held = documents.turn_ended(project_session)

        assert held == [f"{folder}/items/1-the-palette.md", f"{folder}/project.md"]
        assert [len(_versions(session, draft)), len(_versions(session, handbook))] == [
            1,
            2,
        ]
        assert len(_versions(session, session.get_one(Document, item.id))) == 1
        assert {
            document.writing_session_id
            for document in (draft, handbook, session.get_one(Document, item.id))
        } == {None}

    def test_another_sessions_documents_are_left_as_they_are(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        other = models.Session(
            project_id=project.id,
            environment_id=environment.id,
            kind_code="work",
            cwd="/work/Example",
            token_hash="2" * 64,
            state_code=SessionState.RUNNING,
        )
        session.add(other)
        session.flush()
        documents = container.document_service()
        draft = documents.bear_draft(project, "# Badges\n")
        handbook = documents.bear_handbook(project)
        folder = f"draft-{project.number}"
        _save(
            container,
            environment,
            f"{folder}/project.md",
            "# Palette\n",
            project_session,
        )
        _save(container, environment, f"{folder}/handbook.md", BROKEN, other)
        writing_since = handbook.writing_since

        assert documents.turn_ended(project_session) == []

        assert draft.writing_session_id is None
        assert (handbook.writing_session_id, handbook.writing_since) == (
            other.id,
            writing_since,
        )
        assert len(_versions(session, handbook)) == 1

    def test_a_second_turn_end_finds_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        documents = container.document_service()
        draft = documents.bear_draft(project, "# Badges\n")
        _save(
            container,
            environment,
            f"draft-{project.number}/project.md",
            BROKEN,
            project_session,
        )
        assert documents.turn_ended(project_session) == [
            f"draft-{project.number}/project.md"
        ]

        assert documents.turn_ended(project_session) == []
        assert len(_versions(session, draft)) == 1
