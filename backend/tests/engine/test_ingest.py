"""The engine's side of the file put: the parse gate, the merge by ownership
and the faults (design 1 §5.3, §6), driven as the sidecar drives it."""

import hashlib
import json
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import pilot_dsl as dsl
import pytest
from dependency_injector import providers
from flask import Flask
from psycopg.errors import LockNotAvailable
from sqlalchemy import func, select
from sqlalchemy import text as sql
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.engine.bus import (
    DocumentModified,
    EngineEvent,
    ErrorsRaised,
    ErrorsResolved,
    ProjectChanged,
    TreeHashMoved,
)
from app.engine.documents import DocumentService
from app.engine.ingest import Ingested, PathKind, WorkerVersion
from app.engine.paths import sha256_hex, tree_path
from app.engine.tree import TreeDocument, TreeFile
from app.exceptions import RecordNotFoundException
from app.extensions import db
from app.models import (
    Attachment,
    Block,
    Document,
    DocumentVersion,
    Environment,
    PlanTask,
    Project,
    SaveError,
    SessionRecord,
    User,
    Work,
)
from app.models.reference import (
    AttachmentSource,
    ErrorKind,
    ProjectState,
    SessionState,
    TaskStatus,
    UserKind,
    VersionCause,
)
from app.services.container import ServiceContainer
from app.services.effect_service import EffectService
from app.services.pilot_store_service import Brain
from tests.support.fake_sidecar import FakeSidecar, Put
from tests.support.starts import configured_starts
from tests.support.supervisor import Supervise
from tests.support.turns import end_turns, turn_in_flight

DRAFT = "---\ntitle: Badge colours\n---\n\nWhich colours for the badges?\n"

RETITLED = "---\ntitle: Badge palette\n---\n\nWhich colours for the badges?\n"

BROKEN = "```decision id=D1\noptions:\n  - Dome\n"

UNANSWERED = """---
title: Which tent?
---

```decision id=D1
options:
  - Dome
  - Tunnel
```
"""

ANSWERED = """---
title: Which tent?
---

```decision id=D1
options:
  - Dome
  - Tunnel
answer: Dome
by: ada
at: 2026-10-12T09:40:00Z
```
"""

HANDBOOK = """Keep it short.

```decision id=D1
options:
  - Dome
  - Tunnel
```
"""

SHORTER = HANDBOOK.replace("Keep it short.", "Keep it shorter.")

TWO_ASKS = UNANSWERED + "\n```question id=Q1\ndefault: The lake\n```\n"

TWO_ASKS_EDITED = TWO_ASKS.replace("The lake", "The river")

TENT_FRONT_MATTER = "---\ntitle: Which tent?\n---\n"

FROZEN = "block D1 reverted: answered by a person"

ANSWERED_AT = datetime(2026, 10, 12, 9, 40, tzinfo=UTC)

PLAN = (
    json.dumps(
        {
            "ticket": "MD-8",
            "repo": "pvginkel/MyDownloads",
            "tasks": [
                {
                    "id": "fix",
                    "title": "Fix the client for v4",
                    "status": "in_progress",
                    "notes": [],
                }
            ],
            "notes": [],
        },
        indent=2,
    )
    + "\n"
)
"""A plan as the engine renders it."""

COMPACT_PLAN = json.dumps(json.loads(PLAN))

MISSPELT_PLAN = '{"tickets": "MD-9"}\n'

MISSPELT = dsl.Fault(None, "`tickets` is not a key of the plan")

NOT_TEXT = dsl.Fault(
    None, "the plan is not text: a string holds `\\u0000` or an unpaired surrogate"
)


def _ingest(
    container: ServiceContainer,
    path: str,
    content: str | bytes,
    environment: Environment,
    base: str | None = None,
    session: models.Session | None = None,
) -> Ingested:
    data = content.encode() if isinstance(content, str) else content
    with scoped_session(container):
        return container.ingest_service().ingest(path, data, base, environment, session)


def _bear_draft(container: ServiceContainer, project: Project, text: str) -> Document:
    with scoped_session(container):
        return container.document_service().bear_draft(project, text)


def _errors(session: DbSession) -> list[tuple[str, str, ErrorKind, int | None, str]]:
    return [
        (error.environment_id, error.path, error.kind_code, error.line, error.message)
        for error in session.scalars(select(SaveError).order_by(SaveError.id))
    ]


def _task(
    session: DbSession, project: Project, task_id: str, *, removed: bool = False
) -> PlanTask:
    task = PlanTask(
        project_id=project.id,
        task_id=task_id,
        position=None if removed else 1,
        title=f"Task {task_id}",
        status_code=TaskStatus.PENDING,
        removed_at=datetime.now(UTC) if removed else None,
    )
    session.add(task)
    session.flush()
    return task


def _versions(
    session: DbSession, document: Document
) -> list[tuple[int, VersionCause, str | None, uuid.UUID | None]]:
    """The document's Versions in order: number, cause, text and Session."""
    return [
        (version.number, version.cause_code, version.text, version.session_id)
        for version in session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.number)
        )
    ]


def _open(session: DbSession, project: Project, slug: str) -> None:
    project.slug = slug
    project.state_code = ProjectState.OPEN
    session.flush()


class TestIngestServiceWorkerVersion:
    """A registered document's file read as its worker's turn left it."""

    def test_a_clean_text_has_no_fault_and_needs_no_title(
        self, container: ServiceContainer, project: Project
    ) -> None:
        text = "Two options for the camp.\n\n```question id=Q1\n```\n"

        version = container.ingest_service().worker_version(project, text.encode())

        assert version == WorkerVersion(text, ())

    def test_every_fault_in_line_order_its_bytes_its_own_and_the_records(
        self, session: DbSession, container: ServiceContainer, project: Project
    ) -> None:
        _task(session, project, "build")
        content = (
            b"---\nfor: nobody\nstep: build\n---\n\nCamp \xff notes.\n\n"
            b"```decision id=D1\nproposal: [\n```\n"
        )

        version = container.ingest_service().worker_version(project, content)

        text = content.decode(errors="replace")
        assert version.text == text
        own = list(dsl.parse(text).faults)
        assert own
        assert list(version.faults) == sorted(
            [
                dsl.Fault(2, "front matter: `for: nobody` names no handle"),
                dsl.Fault(
                    6,
                    "the file is not UTF-8 text: each sequence that is not, and"
                    " each NUL, is replaced by U+FFFD",
                ),
                *own,
            ],
            key=lambda fault: (fault.line is None, fault.line or 0),
        )

    def test_a_step_of_another_project_is_a_fault(
        self, container: ServiceContainer, project: Project
    ) -> None:
        content = b"---\nstep: build\n---\n\nCamp notes.\n"

        version = container.ingest_service().worker_version(project, content)

        assert version.faults == (
            dsl.Fault(2, "front matter: `step: build` names no task of the project"),
        )


class TestIngestServiceBornFaults:
    """The text an item of Pilot's own is to be born with, read as a save of
    it is."""

    def test_a_titled_clean_text_has_no_fault(
        self, session: DbSession, container: ServiceContainer, project: Project
    ) -> None:
        _task(session, project, "build")
        text = "---\ntitle: Camp notes\nstep: build\nfor: ada\n---\n\nNotes.\n"

        assert container.ingest_service().born_faults(project, text) == ()

    def test_every_fault_its_own_the_records_and_the_title_rules(
        self, container: ServiceContainer, project: Project
    ) -> None:
        text = "---\nfor: nobody\nstep: build\n---\n\n```decision id=D1\nproposal: [\n```\n"

        faults = container.ingest_service().born_faults(project, text)

        own = list(dsl.parse(text).faults)
        assert own
        assert list(faults) == sorted(
            [
                dsl.Fault(2, "front matter: `for: nobody` names no handle"),
                dsl.Fault(
                    3, "front matter: `step: build` names no task of the project"
                ),
                *own,
                dsl.Fault(
                    None,
                    "the item has no title: give it `title` in the front matter or"
                    " a first heading",
                ),
            ],
            key=lambda fault: (fault.line is None, fault.line or 0),
        )

    def test_a_first_heading_is_a_title(
        self, container: ServiceContainer, project: Project
    ) -> None:
        assert container.ingest_service().born_faults(project, "# Camp notes\n") == ()

    def test_a_persons_answer_is_a_fault_the_agents_is_not(
        self, container: ServiceContainer, project: Project
    ) -> None:
        text = (
            "# Camp\n\n"
            "```question id=Q1\nanswer: The lake\nby: agent\n```\n\n"
            "```question id=Q2\nanswer: The forest\nby: ada\n```\n"
        )

        faults = container.ingest_service().born_faults(project, text)

        assert faults == (
            dsl.Fault(
                10,
                "block Q2: `by: ada` is ada's answer, which the record does not hold",
            ),
        )


class TestIngestServicePaths:
    @pytest.mark.parametrize(
        "path",
        [
            "draft-999999/project.md",
            "badge-colours/project.md",
            "project.md",
            "",
            "{folder}",
            "{folder}/",
            "{folder}/notes.md",
            "{folder}/attachments/1/missing.png",
            "{folder}/items/1-which-tent.md",
        ],
    )
    def test_a_path_the_store_does_not_sync_stores_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        path: str,
    ) -> None:
        draft = _bear_draft(container, project, DRAFT)
        path = path.format(folder=f"draft-{project.number}")

        with pytest.raises(RecordNotFoundException) as raised:
            _ingest(container, path, "Some prose.\n", environment)

        assert raised.value.message == f"Path {path} was not found"
        assert draft.ingested_text is None
        assert _errors(session) == []

    def test_an_archived_projects_folder_is_not_synced(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        _bear_draft(container, project, DRAFT)
        project.archived = True
        session.flush()

        with pytest.raises(RecordNotFoundException):
            _ingest(container, f"draft-{project.number}/project.md", DRAFT, environment)

    def test_an_open_projects_folder_is_its_slug(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        draft = _bear_draft(container, project, DRAFT)
        _open(session, project, "badge-colours")

        _ingest(container, "badge-colours/project.md", RETITLED, environment)
        assert draft.published_text == RETITLED
        with pytest.raises(RecordNotFoundException):
            _ingest(
                container, f"draft-{project.number}/project.md", RETITLED, environment
            )

    def test_the_timeline_is_answered_with_its_projection(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        draft = _bear_draft(container, project, DRAFT)
        timeline = container.view_service().timeline(project)

        answer = _ingest(
            container,
            f"draft-{project.number}/timeline.json",
            '{"edited": true}\n',
            environment,
            base=timeline.hash,
        )

        assert answer == Ingested(
            kind=PathKind.VIEW,
            content=timeline.text.encode(),
            hash=timeline.hash,
            stale=False,
            held=False,
            faults=(),
        )
        assert draft.ingested_text is None
        assert _errors(session) == []

    def test_reference_json_is_answered_with_its_projection(
        self, session: DbSession, container: ServiceContainer, environment: Environment
    ) -> None:
        reference = container.view_service().reference()

        answer = _ingest(container, "reference.json", "{}\n", environment)

        assert answer == Ingested(
            kind=PathKind.VIEW,
            content=reference.text.encode(),
            hash=reference.hash,
            stale=True,
            held=False,
            faults=(),
        )
        assert _errors(session) == []

    def test_an_attachment_is_answered_with_its_copy(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        content = b"# Palette\n"
        session.add(
            Attachment(
                project_id=project.id,
                batch=2,
                title="Palette",
                filename="palette.md",
                content_type="text/markdown",
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                content=content,
                source_code=AttachmentSource.DRAFT,
                copied_at=datetime.now(UTC),
            )
        )
        session.flush()

        answer = _ingest(
            container,
            f"draft-{project.number}/attachments/2/palette.md",
            "# Palette, edited\n",
            environment,
        )

        assert answer.content == content
        assert answer.hash == hashlib.sha256(content).hexdigest()
        assert _errors(session) == []

    def test_a_read_only_save_of_its_projection_needs_no_write(
        self, container: ServiceContainer, project: Project, environment: Environment
    ) -> None:
        timeline = container.view_service().timeline(project)

        answer = _ingest(
            container,
            f"draft-{project.number}/timeline.json",
            timeline.text,
            environment,
            base=timeline.hash,
        )

        assert answer.content is None


class TestIngestServiceGate:
    def test_a_clean_save_is_stored_and_published(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        draft = _bear_draft(container, project, DRAFT)

        answer = _ingest(
            container,
            f"draft-{project.number}/project.md",
            RETITLED,
            environment,
            base=sha256_hex(DRAFT),
        )

        assert answer == Ingested(
            kind=PathKind.DOCUMENT,
            content=None,
            hash=sha256_hex(RETITLED),
            stale=False,
            held=False,
            faults=(),
        )
        assert draft.ingested_text == RETITLED
        assert draft.ingested_hash == sha256_hex(RETITLED)
        assert draft.ingested_at is not None
        assert draft.published_text == RETITLED
        assert draft.published_hash == sha256_hex(RETITLED)
        assert project.name == "Badge palette"
        assert _errors(session) == []

    def test_a_save_with_a_fault_is_held(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        draft = _bear_draft(container, project, ANSWERED)
        published_at = draft.published_at
        path = f"draft-{project.number}/project.md"
        save = RETITLED + BROKEN

        answer = _ingest(container, path, save, environment, base=sha256_hex(ANSWERED))

        assert answer == Ingested(
            kind=PathKind.DOCUMENT,
            content=None,
            hash=sha256_hex(save),
            stale=False,
            held=True,
            faults=(dsl.Fault(6, "a fence opened with ``` is not closed"),),
        )
        assert draft.ingested_text == save
        assert draft.published_text == ANSWERED
        assert draft.published_hash == sha256_hex(ANSWERED)
        assert draft.published_at == published_at
        assert project.name == "Which tent?"
        assert [block.answer for block in session.scalars(select(Block))] == ["Dome"]
        assert _errors(session) == [
            (
                environment.id,
                path,
                ErrorKind.PARSE,
                6,
                "a fence opened with ``` is not closed",
            )
        ]

    def test_a_service_users_handle_names_no_one(
        self,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        service_user: User,
    ) -> None:
        """No item is for a service user, and it answers nothing (DB 338)."""
        _bear_draft(container, project, DRAFT)
        save = "---\nfor: fleet\n---\n\n```question id=Q1\nby: fleet\n```\n"

        answer = _ingest(
            container, f"draft-{project.number}/project.md", save, environment
        )

        assert answer.faults == (
            dsl.Fault(2, "front matter: `for: fleet` names no handle"),
            dsl.Fault(6, "block Q1: `by: fleet` names no handle"),
        )

    def test_every_fault_of_a_held_save_stands(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        _bear_draft(container, project, DRAFT)
        save = (
            "---\nfor: nobody\n---\n\n"
            "```decision id=D1\noptions: 3\n```\n\n"
            "```question id=Q1\nby: nobody\n```\n"
        )

        answer = _ingest(
            container, f"draft-{project.number}/project.md", save, environment
        )

        assert answer.faults == (
            dsl.Fault(2, "front matter: `for: nobody` names no handle"),
            dsl.Fault(6, "block D1: `options` is not a list"),
            dsl.Fault(10, "block Q1: `by: nobody` names no handle"),
        )
        assert [(kind, line) for _, _, kind, line, _ in _errors(session)] == [
            (ErrorKind.PARSE, 2),
            (ErrorKind.PARSE, 6),
            (ErrorKind.PARSE, 10),
        ]

    def test_each_save_replaces_the_paths_parse_errors(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        draft = _bear_draft(container, project, DRAFT)
        path = f"draft-{project.number}/project.md"

        for lead in ("", "Intro.\n\n", "Intro.\n\nMore.\n\n"):
            _ingest(container, path, lead + BROKEN, environment)

        assert [line for _, _, _, line, _ in _errors(session)] == [5]
        _ingest(container, path, RETITLED, environment)
        assert _errors(session) == []
        assert draft.published_text == RETITLED

    def test_a_save_leaves_reverted_errors_and_other_paths_standing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        _bear_draft(container, project, DRAFT)
        path = f"draft-{project.number}/project.md"
        handbook = f"draft-{project.number}/handbook.md"
        other = Environment(id="example-env-2", name="Example-2", exempt=False)
        session.add(other)
        session.flush()
        _ingest(container, path, BROKEN, other)
        session.add_all(
            SaveError(
                environment_id=environment.id,
                path=error_path,
                kind_code=kind,
                line=1,
                message="a fault",
            )
            for error_path, kind in (
                (path, ErrorKind.REVERTED),
                (handbook, ErrorKind.PARSE),
            )
        )
        session.flush()

        _ingest(container, path, RETITLED, environment)

        assert [(env, p, kind) for env, p, kind, _, _ in _errors(session)] == [
            (environment.id, path, ErrorKind.REVERTED),
            (environment.id, handbook, ErrorKind.PARSE),
        ]

    @pytest.mark.parametrize(
        ("front_matter", "fault"),
        [
            (
                "step: nowhere",
                "front matter: `step: nowhere` names no task of the project",
            ),
            ("for: nobody", "front matter: `for: nobody` names no handle"),
            (
                "slug: Badge Colours",
                "front matter: `slug: Badge Colours` is not lower-case letters,"
                " digits and hyphens",
            ),
            ("slug: tents", "front matter: `slug: tents` is taken by another project"),
        ],
    )
    def test_a_front_matter_reference_naming_nothing_holds_the_save(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
        environment: Environment,
        front_matter: str,
        fault: str,
    ) -> None:
        other = Project(created_by_user_id=person.id)
        session.add(other)
        session.flush()
        _open(session, other, "tents")
        draft = _bear_draft(container, project, DRAFT)
        save = f"---\ntitle: Badge palette\n{front_matter}\n---\n"

        answer = _ingest(
            container, f"draft-{project.number}/project.md", save, environment
        )

        assert answer.held
        assert answer.faults == (dsl.Fault(3, fault),)
        assert draft.published_text == DRAFT

    def test_references_the_record_holds_are_no_fault(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        _task(session, project, "build", removed=True)
        draft = _bear_draft(container, project, DRAFT)
        save = "---\ntitle: Badges\nstep: build\nfor: ada\nslug: badges\n---\n"

        answer = _ingest(
            container, f"draft-{project.number}/project.md", save, environment
        )

        assert not answer.held
        assert draft.published_text == save

    def test_the_drafts_missing_slug_is_no_fault(
        self, container: ServiceContainer, project: Project, environment: Environment
    ) -> None:
        draft = _bear_draft(container, project, "")

        answer = _ingest(
            container, f"draft-{project.number}/project.md", DRAFT, environment
        )

        assert not answer.held
        assert draft.published_text == DRAFT

    def test_an_open_projects_own_slug_is_no_fault(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        draft = _bear_draft(container, project, DRAFT)
        _open(session, project, "badges")
        save = "---\ntitle: Badge palette\nslug: badges\n---\n"

        answer = _ingest(container, "badges/project.md", save, environment)

        assert not answer.held
        assert draft.published_text == save

    @pytest.mark.parametrize(
        "save",
        [
            pytest.param(UNANSWERED.replace(TENT_FRONT_MATTER, ""), id="one-block"),
            pytest.param("Rain is due.\n", id="prose"),
            pytest.param(
                UNANSWERED.replace(TENT_FRONT_MATTER, "") + "```question id=Q1\n```\n",
                id="two-blocks",
            ),
        ],
    )
    @pytest.mark.parametrize("registered", [False, True], ids=["own", "registered"])
    def test_a_save_pilot_makes_of_an_item_needs_a_title(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
        save: str,
        registered: bool,
    ) -> None:
        with scoped_session(container):
            item = container.document_service().bear_item(
                project, "decision", "Which tent?", project_session, ANSWERED
            )
        document = session.get_one(Document, item.id)
        if registered:
            document.source_environment_id = environment.id
            document.source_path = "/work/Example/tents.md"
            session.flush()

        answer = _ingest(
            container,
            f"draft-{project.number}/items/1-which-tent.md",
            save,
            environment,
        )

        assert answer.held
        assert answer.faults == (
            dsl.Fault(
                None,
                "the item has no title: give it `title` in the front matter"
                " or a first heading",
            ),
        )
        assert document.published_text == ANSWERED
        assert item.title == "Which tent?"

    @pytest.mark.parametrize(
        ("because", "faults"),
        [
            ("irreversible", ()),
            (
                "hurry",
                (
                    dsl.Fault(
                        5,
                        "block C1: `because: hurry` is not a confirmation reason"
                        " (auto-pilot-off, irreversible, product-hold, rider,"
                        " self-approval, standing-grant); the reasons are in"
                        " `reference.json`",
                    ),
                ),
            ),
        ],
    )
    def test_a_confirmations_reason_is_one_the_record_holds(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
        because: str,
        faults: tuple[dsl.Fault, ...],
    ) -> None:
        with scoped_session(container):
            item = container.document_service().bear_item(
                project, "decision", "Ship the badges?", project_session
            )
        save = (
            "# Ship the badges?\n\n```decision id=C1\ntype: confirmation\n"
            f"because: {because}\nproposal: Ship the badges on Friday\n```\n"
        )

        answer = _ingest(
            container,
            f"draft-{project.number}/items/1-ship-the-badges.md",
            save,
            environment,
        )

        assert answer.held is bool(faults)
        assert answer.faults == faults
        published = session.get_one(Document, item.id).published_text
        assert published == ("---\ntitle: Ship the badges?\n---\n" if faults else save)

    @pytest.mark.parametrize(
        "answer_lines",
        [
            "answer: deferred\nby: agent\nto: build\n",
            "answer: deferred\nby: ada\nat: 2026-10-12T09:40:00Z\nto: build\n",
        ],
    )
    def test_a_to_carried_unchanged_is_not_checked_again(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        answer_lines: str,
    ) -> None:
        published = (
            f"# Where?\n\n```question id=Q1\ndefault: The lake\n{answer_lines}```\n"
        )
        task = _task(session, project, "build")
        draft = _bear_draft(container, project, published)
        task.position = None
        task.removed_at = datetime.now(UTC)
        session.flush()
        save = published.replace("# Where?", "# Where do we camp?")

        answer = _ingest(
            container, f"draft-{project.number}/project.md", save, environment
        )

        assert not answer.held
        assert draft.published_text == save

    def test_a_to_the_save_changes_is_checked_against_the_plan(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        published = "```question id=Q1\nanswer: deferred\nby: agent\nto: build\n```\n"
        _task(session, project, "build")
        _task(session, project, "pack", removed=True)
        draft = _bear_draft(container, project, published)

        answer = _ingest(
            container,
            f"draft-{project.number}/project.md",
            published.replace("to: build", "to: pack"),
            environment,
        )

        assert answer.faults == (
            dsl.Fault(
                4, "block Q1: `to: pack` names neither `plan` nor a task in the plan"
            ),
        )
        assert draft.published_text == published

    @pytest.mark.parametrize(
        ("content", "fault"),
        [
            pytest.param(
                UNANSWERED.replace("  - Dome\n", '  - "Dome\\0"\n'),
                dsl.Fault(
                    7,
                    "block D1: the body is not text: a key or value holds NUL or"
                    " an unpaired surrogate",
                ),
                id="not-text",
            ),
            pytest.param(
                "```decision id=D1\noptions: " + "[" * 3000 + "]" * 3000 + "\n```\n",
                dsl.Fault(2, "block D1: the body is nested too deep to read"),
                id="nested-too-deep",
            ),
        ],
    )
    def test_a_save_the_reader_cannot_read_is_held(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        content: str,
        fault: dsl.Fault,
    ) -> None:
        draft = _bear_draft(container, project, DRAFT)
        path = f"draft-{project.number}/project.md"

        answer = _ingest(container, path, content, environment)

        assert (answer.held, answer.faults) == (True, (fault,))
        assert _errors(session) == [
            (environment.id, path, ErrorKind.PARSE, fault.line, fault.message)
        ]
        assert draft.ingested_text == content
        assert draft.published_text == DRAFT

    @pytest.mark.parametrize(
        ("content", "line", "text"),
        [
            (b"Caf\xe9 au lait.\n", 1, "Caf� au lait.\n"),
            (b"One.\nTw\x00o.\n", 2, "One.\nTw�o.\n"),
            # The fault stands at the first bad byte, a NUL before the
            # sequence that is not UTF-8.
            (b"A\x00\nB\n\xe9\n", 1, "A�\nB\n�\n"),
            # A truncated sequence is replaced whole.
            (b"One.\na\xe2\x82b\n", 2, "One.\na�b\n"),
        ],
    )
    def test_bytes_that_are_not_text_are_held_replaced(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        content: bytes,
        line: int,
        text: str,
    ) -> None:
        draft = _bear_draft(container, project, DRAFT)

        answer = _ingest(
            container, f"draft-{project.number}/project.md", content, environment
        )

        assert answer == Ingested(
            kind=PathKind.DOCUMENT,
            content=text.encode(),
            hash=sha256_hex(text),
            stale=True,
            held=True,
            faults=(
                dsl.Fault(
                    line,
                    "the file is not UTF-8 text: each sequence that is not, and"
                    " each NUL, is replaced by U+FFFD",
                ),
            ),
        )
        assert draft.ingested_text == text
        assert draft.published_text == DRAFT


class TestIngestServiceStale:
    def test_a_base_of_the_published_hash_is_not_stale(
        self, container: ServiceContainer, project: Project, environment: Environment
    ) -> None:
        _bear_draft(container, project, DRAFT)

        answer = _ingest(
            container,
            f"draft-{project.number}/project.md",
            RETITLED,
            environment,
            base=sha256_hex(DRAFT),
        )

        assert not answer.stale

    def test_no_base_is_stale(
        self, container: ServiceContainer, project: Project, environment: Environment
    ) -> None:
        _bear_draft(container, project, DRAFT)

        answer = _ingest(
            container, f"draft-{project.number}/project.md", DRAFT, environment
        )

        assert answer.stale
        assert answer.content is None

    def test_a_fix_up_of_a_held_save_is_not_stale(
        self, container: ServiceContainer, project: Project, environment: Environment
    ) -> None:
        _bear_draft(container, project, DRAFT)
        path = f"draft-{project.number}/project.md"
        held = _ingest(container, path, BROKEN, environment, base=sha256_hex(DRAFT))

        answer = _ingest(container, path, RETITLED, environment, base=held.hash)

        assert held.hash == sha256_hex(BROKEN)
        assert not answer.stale

    def test_the_published_hash_is_stale_while_the_path_is_held(
        self, container: ServiceContainer, project: Project, environment: Environment
    ) -> None:
        _bear_draft(container, project, DRAFT)
        path = f"draft-{project.number}/project.md"
        _ingest(container, path, BROKEN, environment, base=sha256_hex(DRAFT))

        answer = _ingest(container, path, RETITLED, environment, base=sha256_hex(DRAFT))

        assert answer.stale


class TestIngestServiceMerge:
    def test_a_record_line_the_save_changes_is_reverted(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        draft = _bear_draft(container, project, ANSWERED)
        path = f"draft-{project.number}/project.md"
        save = ANSWERED.replace("answer: Dome", "answer: Tunnel")

        answer = _ingest(container, path, save, environment, base=sha256_hex(ANSWERED))

        message = "block D1: `answer:` is the record's, ada's answer; reverted"
        assert answer == Ingested(
            kind=PathKind.DOCUMENT,
            content=ANSWERED.encode(),
            hash=sha256_hex(ANSWERED),
            stale=False,
            held=False,
            faults=(dsl.Fault(9, message),),
        )
        assert draft.ingested_text == save
        assert draft.published_text == ANSWERED
        assert _errors(session) == [
            (environment.id, path, ErrorKind.REVERTED, 9, message)
        ]

    def test_a_definition_under_a_persons_answer_is_reverted(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        with scoped_session(container):
            item = container.document_service().bear_item(
                project, "decision", "Which tent?", project_session, ANSWERED
            )
        path = f"draft-{project.number}/items/1-which-tent.md"
        save = ANSWERED.replace("  - Tunnel\n", "  - Tunnel: sleeps two\n")

        answer = _ingest(container, path, save, environment)

        assert answer.content == ANSWERED.encode()
        assert answer.faults == (dsl.Fault(5, FROZEN),)
        assert session.get_one(Document, item.id).published_text == ANSWERED
        assert _errors(session) == [
            (environment.id, path, ErrorKind.REVERTED, 5, FROZEN)
        ]

    def test_undo_unfreezes_the_block(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
        person: User,
    ) -> None:
        with scoped_session(container):
            item = container.document_service().bear_item(
                project, "decision", "Which tent?", project_session, UNANSWERED
            )
        document = session.get_one(Document, item.id)
        path = f"draft-{project.number}/items/1-which-tent.md"
        save = UNANSWERED.replace("  - Tunnel\n", "  - Tunnel: sleeps two\n")
        with scoped_session(container):
            container.record_service().answer(document, "D1", person, "Dome")
        answered = document.published_text
        assert answered is not None
        frozen = _ingest(container, path, save, environment)
        with scoped_session(container):
            container.record_service().undo(item)

        thawed = _ingest(container, path, save, environment)

        assert frozen.faults == (dsl.Fault(5, FROZEN),)
        assert frozen.content == answered.encode()
        assert thawed.faults == ()
        assert document.published_text == save

    def test_a_registered_documents_prose_is_reverted_once_a_person_answered(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        published = ANSWERED.replace(
            TENT_FRONT_MATTER, TENT_FRONT_MATTER + "\nRain is due.\n"
        )
        with scoped_session(container):
            item = container.document_service().bear_item(
                project, "decision", "Which tent?", project_session, published
            )
        document = session.get_one(Document, item.id)
        document.source_environment_id = environment.id
        document.source_path = "/work/Example/tents.md"
        session.flush()
        retitled = "title: Which tent for the lake?"
        save = published.replace("Rain is due.", "Sun all week.").replace(
            "title: Which tent?", retitled
        )

        answer = _ingest(
            container,
            f"draft-{project.number}/items/1-which-tent.md",
            save,
            environment,
        )

        merged = published.replace("title: Which tent?", retitled)
        prose = "the body prose reverted: a person has answered in the document"
        assert answer.content == merged.encode()
        assert answer.faults == (dsl.Fault(5, prose),)
        assert document.published_text == merged
        assert item.title == "Which tent for the lake?"

    def test_a_title_moved_into_a_reverted_heading_stays_in_the_front_matter(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        published = ANSWERED.replace(
            TENT_FRONT_MATTER, TENT_FRONT_MATTER + "\nRain is due.\n"
        )
        with scoped_session(container):
            item = container.document_service().bear_item(
                project, "decision", "Which tent?", project_session, published
            )
        document = session.get_one(Document, item.id)
        document.source_environment_id = environment.id
        document.source_path = "/work/Example/tents.md"
        session.flush()
        save = published.replace(TENT_FRONT_MATTER, "# Which tent?\n")

        answer = _ingest(
            container,
            f"draft-{project.number}/items/1-which-tent.md",
            save,
            environment,
        )

        prose = "the body prose reverted: a person has answered in the document"
        assert answer.content == published.encode()
        assert answer.faults == (dsl.Fault(4, prose),)
        assert document.published_text == published
        assert item.title == "Which tent?"

    def test_a_block_a_non_draft_drops_is_restored(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        with scoped_session(container):
            handbook = container.document_service().bear_handbook(project, HANDBOOK)

        answer = _ingest(
            container,
            f"draft-{project.number}/handbook.md",
            "Keep it shorter.\n",
            environment,
        )

        restored = HANDBOOK.replace("Keep it short.", "Keep it shorter.")
        assert answer.content == restored.encode()
        assert answer.faults == (
            dsl.Fault(3, "block D1: only the draft's blocks may be removed; restored"),
        )
        assert handbook.published_text == restored

    def test_a_block_the_draft_drops_goes(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        draft = _bear_draft(container, project, ANSWERED)

        answer = _ingest(
            container,
            f"draft-{project.number}/project.md",
            "# Which tent?\n",
            environment,
        )

        assert answer.content is None
        assert answer.faults == ()
        assert draft.published_text == "# Which tent?\n"
        assert list(session.scalars(select(Block))) == []

    @pytest.mark.parametrize(
        ("save", "faults"),
        [
            pytest.param(
                ANSWERED.replace("  - Tunnel\n", "  - Tunnel: sleeps two\n"),
                (dsl.Fault(5, FROZEN),),
                id="answered-frozen",
            ),
            pytest.param(
                "# Which tent?\n",
                (
                    dsl.Fault(
                        3, "block D1: only the draft's blocks may be removed; restored"
                    ),
                ),
                id="dropped-restored",
            ),
        ],
    )
    def test_past_create_the_project_document_is_no_draft(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        save: str,
        faults: tuple[dsl.Fault, ...],
    ) -> None:
        """A person's answered block freezes, and no block goes, from Create
        project on (F47.4, F32.7)."""
        draft = _bear_draft(container, project, ANSWERED)
        _open(session, project, "tents")

        answer = _ingest(container, "tents/project.md", save, environment)

        assert not answer.held
        assert answer.faults == faults
        assert answer.content is not None
        assert draft.published_text == answer.content.decode()
        assert [block.local_id for block in session.scalars(select(Block))] == ["D1"]

    def test_past_create_its_slug_is_read_by_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """No later save moves the folder (DB decision 1), nor is its slug a
        fault."""
        draft = _bear_draft(container, project, DRAFT)
        _open(session, project, "badges")
        save = "---\ntitle: Badge palette\nslug: Not A Slug\n---\n"

        answer = _ingest(container, "badges/project.md", save, environment)

        assert (answer.held, answer.faults) == (False, ())
        assert draft.published_text == save
        assert (project.slug, project.name) == ("badges", "Badge palette")
        assert isinstance(
            container.tree_service().resolve("badges/project.md"), TreeDocument
        )

    def test_an_agent_edit_of_the_opening_is_reverted(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
        environment: Environment,
    ) -> None:
        with scoped_session(container):
            opening = container.document_service().bear_opening(
                project, "Badges", person, "We need badges.\n"
            )
        path = f"draft-{project.number}/items/1-badges.md"

        answer = _ingest(container, path, "We need badges soon.\n", environment)

        assert answer.content == b"We need badges.\n"
        assert answer.faults == (
            dsl.Fault(1, "the opening is the record's: the save is reverted"),
        )
        assert session.get_one(Document, opening.id).published_text == (
            "We need badges.\n"
        )

    @pytest.mark.parametrize(
        ("save", "line"),
        [
            ("We need badges\n```decision id=D1\noptions:\n  - Dome\n", 1),
            ("We need badges.\n```question id=Q1\nnote: [a]\n```\n", None),
            (b"We need \x00badges.\n", 1),
            ("We need badges.\n```question id=Q1\nby: nobody\n```\n", None),
        ],
    )
    def test_a_faulty_save_of_the_opening_is_reverted_never_held(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
        environment: Environment,
        save: str | bytes,
        line: int | None,
    ) -> None:
        with scoped_session(container):
            opening = container.document_service().bear_opening(
                project, "Badges", person, "We need badges.\n"
            )
        path = f"draft-{project.number}/items/1-badges.md"

        answer = _ingest(container, path, save, environment)

        reverted = "the opening is the record's: the save is reverted"
        assert (answer.held, answer.content) == (False, b"We need badges.\n")
        assert answer.faults == (dsl.Fault(line, reverted),)
        assert _errors(session) == [
            (environment.id, path, ErrorKind.REVERTED, line, reverted)
        ]
        assert session.get_one(Document, opening.id).published_text == (
            "We need badges.\n"
        )
        assert list(session.scalars(select(Block))) == []

    def test_an_opening_holding_an_unclosed_fence_saved_as_is_is_kept(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
        environment: Environment,
    ) -> None:
        words = "We need badges.\n```decision id=D1\n"
        with scoped_session(container):
            container.document_service().bear_opening(project, "Badges", person, words)
        path = f"draft-{project.number}/items/1-badges.md"

        answer = _ingest(container, path, words, environment)

        assert (answer.held, answer.content, answer.faults) == (False, None, ())
        assert _errors(session) == []

    def test_the_writing_columns_take_the_saves_session(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        draft = _bear_draft(container, project, DRAFT)
        path = f"draft-{project.number}/project.md"
        turn_in_flight(session, project_session)

        _ingest(container, path, BROKEN, environment, session=project_session)
        since = draft.writing_since
        _ingest(container, path, RETITLED, environment, session=project_session)

        assert draft.ingested_session_id == project_session.id
        assert draft.writing_session_id == project_session.id
        assert since is not None
        assert draft.writing_since == since

    def test_a_save_of_another_session_takes_the_writing_columns(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        later = models.Session(
            project_id=project.id,
            environment_id=environment.id,
            kind_code="work",
            cwd="/work/Example",
            token_hash="2" * 64,
            state_code=SessionState.RUNNING,
        )
        session.add(later)
        session.flush()
        draft = _bear_draft(container, project, DRAFT)
        path = f"draft-{project.number}/project.md"
        turn_in_flight(session, project_session)
        turn_in_flight(session, later)

        _ingest(container, path, BROKEN, environment, session=project_session)
        since = draft.writing_since
        _ingest(container, path, RETITLED, environment, session=later)

        assert draft.ingested_session_id == later.id
        assert draft.writing_session_id == later.id
        assert since is not None
        assert draft.writing_since is not None
        assert draft.writing_since > since

    def test_a_save_with_no_session_writes_none(
        self, container: ServiceContainer, project: Project, environment: Environment
    ) -> None:
        draft = _bear_draft(container, project, DRAFT)

        _ingest(container, f"draft-{project.number}/project.md", RETITLED, environment)

        assert draft.ingested_session_id is None
        assert draft.writing_session_id is None
        assert draft.writing_since is None


ACTION = """---
title: Put the key into OpenBao
---

```action id=A1
```
"""

DONE = ACTION.replace(
    "```action id=A1\n",
    "```action id=A1\ndone: 2026-11-05T10:30:00Z\nby: agent\n"
    "note: Put in; the deploy read it\n",
)


@pytest.fixture
def placing(container: ServiceContainer, supervise: Supervise) -> None:
    """The container's start on a controller, its loops never run, through
    which a close places the job after it."""
    container.session_start_service.override(
        providers.Object(configured_starts(container, supervise))
    )


def _brain(db: DbSession, project: Project, environment: Environment) -> models.Session:
    """A chat of the project's, a session of Pilot's own."""
    chat = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code="chat",
        cwd="/work/PilotProjects",
        token_hash="2" * 64,
        state_code=SessionState.RUNNING,
    )
    db.add(chat)
    db.flush()
    return chat


def _jobs_after(db: DbSession, item_id: uuid.UUID) -> list[uuid.UUID]:
    return list(db.scalars(select(Work.id).where(Work.trigger_item_id == item_id)))


@pytest.mark.usefixtures("placing")
class TestIngestServiceOwnItemDone:
    """A save of an item of Pilot's own that writes its last open block's
    `done` closes it, Pilot's, cause `settled`, with no job after it (P-181,
    P-182)."""

    def test_the_save_that_writes_its_last_open_blocks_done_closes_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        brain = _brain(session, project, environment)
        with scoped_session(container):
            item = container.document_service().bear_item(
                project, "action", "Put the key into OpenBao", brain, ACTION
            )
        path = tree_path(project, session.get_one(Document, item.id).path)

        answer = _ingest(
            container, path, DONE, environment, base=sha256_hex(ACTION), session=brain
        )

        assert (answer.held, answer.faults) == (False, ())
        assert session.get_one(Document, item.id).published_text == DONE
        agent = session.scalars(
            select(User).where(User.kind_code == UserKind.AGENT)
        ).one()
        assert item.done_at is not None
        assert (item.done_cause_code, item.done_by_user_id) == ("settled", agent.id)
        assert _jobs_after(session, item.id) == []

    def test_a_held_save_closes_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        brain = _brain(session, project, environment)
        with scoped_session(container):
            item = container.document_service().bear_item(
                project, "action", "Put the key into OpenBao", brain, ACTION
            )
        path = tree_path(project, session.get_one(Document, item.id).path)

        answer = _ingest(container, path, DONE + BROKEN, environment, session=brain)

        assert answer.held
        assert item.done_at is None

    def test_an_item_a_workers_session_added_stays_open(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        with scoped_session(container):
            item = container.document_service().bear_item(
                project, "action", "Put the key into OpenBao", project_session, ACTION
            )
        path = tree_path(project, session.get_one(Document, item.id).path)

        answer = _ingest(container, path, DONE, environment, base=sha256_hex(ACTION))

        assert answer.held is False
        assert item.done_at is None


class TestIngestServiceLateSave:
    """A save credited to a session with no turn in flight, its turn ended
    before the save landed, stays that session's: it cuts the session's
    `turn` Version at once and leaves no session writing the document
    (P-103's ruling; D077)."""

    @pytest.mark.parametrize("turned", ["ended", "none"])
    def test_it_cuts_its_sessions_version_at_once(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
        turned: str,
    ) -> None:
        draft = _bear_draft(container, project, DRAFT)
        if turned == "ended":
            turn_in_flight(session, project_session)
            end_turns(session, project_session)
        before = datetime.now(UTC)

        _ingest(
            container,
            f"draft-{project.number}/project.md",
            RETITLED,
            environment,
            session=project_session,
        )

        after = datetime.now(UTC)
        assert (
            draft.ingested_session_id,
            draft.writing_session_id,
            draft.writing_since,
        ) == (project_session.id, None, None)
        assert _versions(session, draft) == [
            (1, VersionCause.BORN, DRAFT, None),
            (2, VersionCause.TURN, RETITLED, project_session.id),
        ]
        cut = session.scalars(
            select(DocumentVersion.created_at).where(
                DocumentVersion.document_id == draft.id, DocumentVersion.number == 2
            )
        ).one()
        # The document's Edited time is its latest `turn` Version's (F28.7).
        assert before <= cut <= after

    def test_a_save_that_moves_no_text_cuts_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        draft = _bear_draft(container, project, DRAFT)

        _ingest(
            container,
            f"draft-{project.number}/project.md",
            DRAFT,
            environment,
            session=project_session,
        )

        assert (draft.ingested_session_id, draft.writing_session_id) == (
            project_session.id,
            None,
        )
        assert _versions(session, draft) == [(1, VersionCause.BORN, DRAFT, None)]

    def test_a_held_save_cuts_nothing_and_stands_held(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        """No turn end is left to follow it up (F79): it shows held until a
        session of the project meets its fault."""
        draft = _bear_draft(container, project, DRAFT)
        path = f"draft-{project.number}/project.md"

        answer = _ingest(container, path, BROKEN, environment, session=project_session)

        assert answer.held
        assert (draft.ingested_session_id, draft.writing_session_id) == (
            project_session.id,
            None,
        )
        assert _versions(session, draft) == [(1, VersionCause.BORN, DRAFT, None)]
        assert container.tree_service().held_path(path)

    def test_a_record_write_since_the_last_version_is_in_its_version(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        environment: Environment,
        project_session: models.Session,
        person: User,
    ) -> None:
        """As at a turn's end: its Version is of the published text, moved
        since the last Version whoever moved it; the Edited time it moves is
        told to the browsers."""
        text = "# Badges\n\n```question id=Q1\ndefault: Blue\n```\n"
        draft = _bear_draft(container, project, text)
        with scoped_session(container):
            container.record_service().answer(draft, "Q1", person, "Green")
        answered = draft.published_text
        assert answered is not None
        path = f"draft-{project.number}/project.md"
        engine_events.clear()

        _ingest(container, path, answered, environment, session=project_session)

        assert _versions(session, draft) == [
            (1, VersionCause.BORN, text, None),
            (2, VersionCause.TURN, answered, project_session.id),
        ]
        assert engine_events == [
            DocumentModified(project.id, path),
            ProjectChanged(project.id),
        ]

    def test_a_held_save_after_a_record_write_cuts_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
        person: User,
    ) -> None:
        """The published text moved since the last Version, a person's answer:
        a held save cuts no Version of it."""
        text = "# Badges\n\n```question id=Q1\ndefault: Blue\n```\n"
        draft = _bear_draft(container, project, text)
        with scoped_session(container):
            container.record_service().answer(draft, "Q1", person, "Green")
        path = f"draft-{project.number}/project.md"

        answer = _ingest(container, path, BROKEN, environment, session=project_session)

        assert answer.held
        assert _versions(session, draft) == [(1, VersionCause.BORN, text, None)]

    def test_another_sessions_writing_stands(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        """The late save writes no document, nor lets go of one another
        session's turn is writing."""
        writing = models.Session(
            project_id=project.id,
            environment_id=environment.id,
            kind_code="work",
            cwd="/work/Example",
            token_hash="2" * 64,
            state_code=SessionState.RUNNING,
        )
        session.add(writing)
        session.flush()
        turn_in_flight(session, writing)
        draft = _bear_draft(container, project, DRAFT)
        path = f"draft-{project.number}/project.md"
        _ingest(container, path, BROKEN, environment, session=writing)
        since = draft.writing_since

        _ingest(container, path, RETITLED, environment, session=project_session)

        assert (
            draft.ingested_session_id,
            draft.writing_session_id,
            draft.writing_since,
        ) == (project_session.id, writing.id, since)
        assert _versions(session, draft) == [
            (1, VersionCause.BORN, DRAFT, None),
            (2, VersionCause.TURN, RETITLED, project_session.id),
        ]

    def test_after_its_turns_end_on_a_document_the_turn_saved_its_own_version(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        """A turn's end that commits before the late save cuts the turn's
        save; the late save then cuts its own, both the session's."""
        draft = _bear_draft(container, project, DRAFT)
        path = f"draft-{project.number}/project.md"
        turn_in_flight(session, project_session)
        _ingest(container, path, RETITLED, environment, session=project_session)
        end_turns(session, project_session)
        with scoped_session(container):
            container.document_service().turn_ended(project_session)
        later = RETITLED.replace("Which colours", "Which two colours")

        _ingest(container, path, later, environment, session=project_session)

        assert draft.writing_session_id is None
        assert _versions(session, draft) == [
            (1, VersionCause.BORN, DRAFT, None),
            (2, VersionCause.TURN, RETITLED, project_session.id),
            (3, VersionCause.TURN, later, project_session.id),
        ]


class TestIngestServiceEvents:
    def test_a_clean_save_moves_its_path_and_what_the_timeline_shows(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        environment: Environment,
    ) -> None:
        _bear_draft(container, project, DRAFT)
        engine_events.clear()
        path = f"draft-{project.number}/project.md"

        _ingest(container, path, RETITLED, environment)

        assert engine_events == [
            TreeHashMoved(path, sha256_hex(RETITLED)),
            TreeHashMoved(
                f"draft-{project.number}/timeline.json",
                container.view_service().timeline(project).hash,
            ),
            ProjectChanged(project.id),
            DocumentModified(project.id, path),
        ]

    def test_a_held_save_moves_its_path_to_the_ingest(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        environment: Environment,
    ) -> None:
        _bear_draft(container, project, DRAFT)
        engine_events.clear()
        path = f"draft-{project.number}/project.md"

        _ingest(container, path, BROKEN, environment)
        first = list(engine_events)
        engine_events.clear()
        _ingest(container, path, BROKEN, environment)

        assert first == [
            TreeHashMoved(path, sha256_hex(BROKEN)),
            DocumentModified(project.id, path),
            ErrorsRaised(project.id, path),
        ]
        assert engine_events == [
            DocumentModified(project.id, path),
            ErrorsRaised(project.id, path),
        ]

    def test_a_clean_save_after_a_held_one_resolves_its_errors(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        environment: Environment,
    ) -> None:
        _bear_draft(container, project, DRAFT)
        path = f"draft-{project.number}/project.md"
        _ingest(container, path, BROKEN, environment)
        engine_events.clear()

        _ingest(container, path, DRAFT, environment)

        assert engine_events == [
            TreeHashMoved(path, sha256_hex(DRAFT)),
            DocumentModified(project.id, path),
            ErrorsResolved(project.id, path),
        ]

    def test_a_save_that_changes_nothing_is_modified_alone(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        environment: Environment,
    ) -> None:
        _bear_draft(container, project, DRAFT)
        engine_events.clear()
        path = f"draft-{project.number}/project.md"

        _ingest(container, path, DRAFT, environment)

        assert engine_events == [DocumentModified(project.id, path)]

    def test_the_save_that_takes_a_document_changes_its_project(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        """Pilot's dots show from the save that makes its session the
        document's writer, whatever the save changed (F35)."""
        _bear_draft(container, project, DRAFT)
        turn_in_flight(session, project_session)
        engine_events.clear()
        path = f"draft-{project.number}/project.md"

        _ingest(container, path, DRAFT, environment, session=project_session)
        taken = list(engine_events)
        engine_events.clear()
        _ingest(container, path, DRAFT, environment, session=project_session)

        assert taken == [DocumentModified(project.id, path), ProjectChanged(project.id)]
        assert engine_events == [DocumentModified(project.id, path)]

    def test_a_read_only_save_raises_nothing(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        environment: Environment,
    ) -> None:
        _ingest(container, f"draft-{project.number}/timeline.json", "{}\n", environment)

        assert engine_events == []

    def test_an_items_held_save_and_its_resolve_change_its_project(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        with scoped_session(container):
            container.document_service().bear_item(
                project, "decision", "Which tent?", project_session, UNANSWERED
            )
        path = f"draft-{project.number}/items/1-which-tent.md"
        engine_events.clear()

        _ingest(container, path, BROKEN, environment)
        held = list(engine_events)
        engine_events.clear()
        _ingest(container, path, BROKEN, environment)
        held_again = list(engine_events)
        engine_events.clear()
        _ingest(container, path, UNANSWERED, environment)

        assert held == [
            TreeHashMoved(path, sha256_hex(BROKEN)),
            DocumentModified(project.id, path),
            ErrorsRaised(project.id, path),
            ProjectChanged(project.id),
        ]
        assert held_again == [
            DocumentModified(project.id, path),
            ErrorsRaised(project.id, path),
        ]
        assert engine_events == [
            TreeHashMoved(path, sha256_hex(UNANSWERED)),
            DocumentModified(project.id, path),
            ErrorsResolved(project.id, path),
            ProjectChanged(project.id),
        ]

    def test_an_items_clean_save_changes_its_project(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        with scoped_session(container):
            container.document_service().bear_item(
                project, "decision", "Which tent?", project_session, UNANSWERED
            )
        path = f"draft-{project.number}/items/1-which-tent.md"
        saved = UNANSWERED + "\nTwo nights at the lake.\n"
        engine_events.clear()

        _ingest(container, path, saved, environment)

        assert engine_events == [
            TreeHashMoved(path, sha256_hex(saved)),
            ProjectChanged(project.id),
            DocumentModified(project.id, path),
        ]


class TestIngestServiceSequences:
    """Design 1 §5.8's sequences, through the fake sidecar."""

    def test_the_agent_writes_a_file(
        self,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
    ) -> None:
        with scoped_session(container):
            container.document_service().bear_item(
                project, "decision", "Which tent?", project_session, ANSWERED
            )
        path = f"draft-{project.number}/items/1-which-tent.md"
        timeline = f"draft-{project.number}/timeline.json"
        assert fake_sidecar.drain() == [path, timeline]
        edited = ANSWERED.replace(
            "title: Which tent?", "title: Which tent for the lake?"
        )

        answer = fake_sidecar.save(path, edited)

        assert answer == Put(
            status=204, content=None, hash=sha256_hex(edited), stale=False, faults=0
        )
        assert fake_sidecar.drain() == [timeline]
        assert fake_sidecar.text(path) == edited
        assert fake_sidecar.text(timeline) == (
            container.view_service().timeline(project).text
        )

    def test_a_reverted_line_is_written_back(
        self,
        session: DbSession,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        with scoped_session(container):
            container.document_service().bear_item(
                project, "decision", "Which tent?", project_session, ANSWERED
            )
        fake_sidecar.drain()
        path = f"draft-{project.number}/items/1-which-tent.md"

        answer = fake_sidecar.save(path, ANSWERED.replace("by: ada", "by: agent"))

        assert answer.content == ANSWERED.encode()
        assert fake_sidecar.text(path) == ANSWERED
        assert fake_sidecar.shadow[path] == sha256_hex(ANSWERED)
        assert _errors(session) == [
            (environment.id, path, ErrorKind.REVERTED, 5, FROZEN)
        ]
        assert fake_sidecar.drain() == []

    def test_the_records_write_reaches_the_file(
        self,
        session: DbSession,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
    ) -> None:
        with scoped_session(container):
            item = container.document_service().bear_item(
                project, "decision", "Which tent?", project_session, UNANSWERED
            )
        fake_sidecar.drain()
        path = f"draft-{project.number}/items/1-which-tent.md"

        _write_answer(container, session.get_one(Document, item.id))

        assert fake_sidecar.drain() == [path]
        assert fake_sidecar.text(path) == ANSWERED

    def test_a_record_write_while_held_rides_the_next_clean_save(
        self,
        session: DbSession,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
    ) -> None:
        with scoped_session(container):
            item = container.document_service().bear_item(
                project, "decision", "Which tent?", project_session, UNANSWERED
            )
        fake_sidecar.drain()
        path = f"draft-{project.number}/items/1-which-tent.md"
        broken = UNANSWERED + "\n```question id=Q1\n"
        fake_sidecar.save(path, broken)
        assert container.tree_service().held_path(path)

        _write_answer(container, session.get_one(Document, item.id))
        assert fake_sidecar.drain() == []
        assert fake_sidecar.text(path) == broken
        fixed = UNANSWERED.replace(
            TENT_FRONT_MATTER, TENT_FRONT_MATTER + "\nRain is due.\n"
        )
        answer = fake_sidecar.save(path, fixed)

        merged = ANSWERED.replace(
            TENT_FRONT_MATTER, TENT_FRONT_MATTER + "\nRain is due.\n"
        )
        assert answer.stale is False
        assert not container.tree_service().held_path(path)
        assert answer.content == merged.encode()
        assert fake_sidecar.text(path) == merged
        assert answer.faults == 1
        assert [
            (kind, line, message) for _, _, kind, line, message in _errors(session)
        ] == [(ErrorKind.REVERTED, 7, FROZEN)]

    def test_a_save_behind_a_projection_in_flight_is_stale_and_merged(
        self,
        session: DbSession,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
    ) -> None:
        with scoped_session(container):
            item = container.document_service().bear_item(
                project, "decision", "Which tent?", project_session, UNANSWERED
            )
        fake_sidecar.drain()
        path = f"draft-{project.number}/items/1-which-tent.md"
        _write_answer(container, session.get_one(Document, item.id))

        edited = UNANSWERED.replace(
            TENT_FRONT_MATTER, TENT_FRONT_MATTER + "\nRain is due.\n"
        )
        answer = fake_sidecar.save(path, edited)
        fake_sidecar.drain()

        merged = ANSWERED.replace(
            TENT_FRONT_MATTER, TENT_FRONT_MATTER + "\nRain is due.\n"
        )
        assert answer.stale is True
        assert answer.content == merged.encode()
        assert fake_sidecar.text(path) == merged


def _write_answer(container: ServiceContainer, document: Document) -> None:
    """The record's write of ada's answer to D1, as P7's answer write splices
    it."""
    assert document.published_text is not None
    with scoped_session(container):
        container.document_service().publish(
            document,
            dsl.write_answer(
                document.published_text,
                "D1",
                answer="Dome",
                by="ada",
                at=ANSWERED_AT,
                via=dsl.AnswerChannel.APP,
            ),
        )


class TestIngestServicePlan:
    """Design 1 §5.3 step 3: a save of `plan.json` writes the rows, or holds
    and changes nothing; no text of it is stored."""

    def test_a_canonical_save_writes_the_rows_and_needs_no_write(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        base = container.plan_service().render(project).hash

        answer = _ingest(container, _plan_path(project), PLAN, environment, base=base)

        assert answer == Ingested(
            kind=PathKind.PLAN,
            content=None,
            hash=sha256_hex(PLAN),
            stale=False,
            held=False,
            faults=(),
        )
        assert project.ticket == "MD-8"
        fix = session.get_one(PlanTask, (project.id, "fix"))
        assert (fix.position, fix.status_code) == (1, TaskStatus.IN_PROGRESS)
        assert _errors(session) == []

    def test_a_save_in_another_formatting_is_answered_canonical(
        self, container: ServiceContainer, project: Project, environment: Environment
    ) -> None:
        base = container.plan_service().render(project).hash

        answer = _ingest(
            container, _plan_path(project), COMPACT_PLAN, environment, base=base
        )

        assert answer == Ingested(
            kind=PathKind.PLAN,
            content=PLAN.encode(),
            hash=sha256_hex(PLAN),
            stale=False,
            held=False,
            faults=(),
        )

    def test_a_held_save_changes_nothing_and_acknowledges_its_hash(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        path = _plan_path(project)
        _ingest(container, path, PLAN, environment)
        documents = session.scalar(select(func.count()).select_from(Document))

        answer = _ingest(
            container, path, MISSPELT_PLAN, environment, base=sha256_hex(PLAN)
        )

        assert answer == Ingested(
            kind=PathKind.PLAN,
            content=None,
            hash=sha256_hex(MISSPELT_PLAN),
            stale=False,
            held=True,
            faults=(MISSPELT,),
        )
        assert _errors(session) == [
            (environment.id, path, ErrorKind.PARSE, None, MISSPELT.message)
        ]
        assert project.ticket == "MD-8"
        assert session.get_one(PlanTask, (project.id, "fix")).removed_at is None
        assert container.tree_service().read(path) == TreeFile(
            PLAN.encode(), sha256_hex(PLAN)
        )
        assert session.scalar(select(func.count()).select_from(Document)) == documents

    def test_each_save_replaces_the_paths_parse_errors(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        path = _plan_path(project)
        draft = f"draft-{project.number}/project.md"
        other = Environment(id="example-env-2", name="Example-2", exempt=False)
        session.add(other)
        session.add_all(
            SaveError(
                environment_id=other.id,
                path=error_path,
                kind_code=ErrorKind.PARSE,
                message="an old fault",
            )
            for error_path in (path, draft)
        )
        session.flush()

        _ingest(container, path, '{"tasks": 1, "notes": 2}', environment)
        _ingest(container, path, MISSPELT_PLAN, environment)
        assert _errors(session) == [
            (other.id, draft, ErrorKind.PARSE, None, "an old fault"),
            (environment.id, path, ErrorKind.PARSE, None, MISSPELT.message),
        ]
        _ingest(container, path, PLAN, environment)
        assert _errors(session) == [
            (other.id, draft, ErrorKind.PARSE, None, "an old fault")
        ]

    def test_a_save_of_text_no_row_can_hold_is_held(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        path = _plan_path(project)
        save = '{"\\u0000": "Fi\\ud800x"}\n'

        answer = _ingest(container, path, save, environment)

        assert answer == Ingested(
            kind=PathKind.PLAN,
            content=None,
            hash=sha256_hex(save),
            stale=True,
            held=True,
            faults=(NOT_TEXT,),
        )
        assert _errors(session) == [
            (environment.id, path, ErrorKind.PARSE, None, NOT_TEXT.message)
        ]

    def test_a_base_other_than_the_rendering_is_stale(
        self, container: ServiceContainer, project: Project, environment: Environment
    ) -> None:
        path = _plan_path(project)

        assert _ingest(container, path, PLAN, environment).stale
        _ingest(container, path, MISSPELT_PLAN, environment, base=sha256_hex(PLAN))
        # No text of a plan save is stored, so the tree hash stays the
        # rendering's while the save is held: a fix-up's base is stale.
        fix_up = _ingest(
            container, path, PLAN, environment, base=sha256_hex(MISSPELT_PLAN)
        )
        assert fix_up == Ingested(
            kind=PathKind.PLAN,
            content=None,
            hash=sha256_hex(PLAN),
            stale=True,
            held=False,
            faults=(),
        )

    def test_an_archived_projects_plan_is_not_synced(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        project.archived = True
        session.flush()

        with pytest.raises(RecordNotFoundException):
            _ingest(container, _plan_path(project), PLAN, environment)
        assert session.scalars(select(PlanTask)).all() == []


class TestIngestServicePlanEvents:
    def test_a_save_moves_the_plans_tree_hash_and_its_project(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        environment: Environment,
    ) -> None:
        path = _plan_path(project)

        _ingest(container, path, PLAN, environment)

        # timeline.json shows nothing a plan save writes, and the plan is no
        # document: no *modified*. The screens show its steps.
        assert engine_events == [
            TreeHashMoved(path, sha256_hex(PLAN)),
            ProjectChanged(project.id),
        ]

    def test_a_held_save_raises_its_errors(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        environment: Environment,
    ) -> None:
        path = _plan_path(project)

        _ingest(container, path, MISSPELT_PLAN, environment)

        assert engine_events == [ErrorsRaised(project.id, path)]

    def test_a_clean_save_after_a_held_one_resolves_its_errors(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        environment: Environment,
    ) -> None:
        path = _plan_path(project)
        _ingest(container, path, PLAN, environment)
        _ingest(container, path, MISSPELT_PLAN, environment)
        engine_events.clear()

        _ingest(container, path, COMPACT_PLAN, environment)

        assert engine_events == [ErrorsResolved(project.id, path)]

    def test_a_save_that_changes_nothing_raises_nothing(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        environment: Environment,
    ) -> None:
        path = _plan_path(project)
        _ingest(container, path, PLAN, environment)
        engine_events.clear()

        _ingest(container, path, COMPACT_PLAN, environment)

        assert engine_events == []


class TestIngestServicePlanSequences:
    """The agent writes `plan.json`, through the fake sidecar."""

    def test_a_save_in_another_formatting_comes_back_canonical(
        self, fake_sidecar: FakeSidecar, project: Project
    ) -> None:
        path = _plan_path(project)

        fake_sidecar.save(path, COMPACT_PLAN)

        assert fake_sidecar.text(path) == PLAN
        assert fake_sidecar.shadow[path] == sha256_hex(PLAN)
        assert fake_sidecar.drain() == []

    def test_a_held_save_stays_on_disk_as_written(
        self,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
    ) -> None:
        path = _plan_path(project)
        fake_sidecar.save(path, PLAN)
        fake_sidecar.drain()

        answer = fake_sidecar.save(path, MISSPELT_PLAN)

        assert (answer.status, answer.faults) == (204, 1)
        assert container.tree_service().held_path(path)
        assert fake_sidecar.text(path) == MISSPELT_PLAN
        assert fake_sidecar.shadow[path] == sha256_hex(MISSPELT_PLAN)
        assert fake_sidecar.drain() == []


class TestIngestServiceWriteDown:
    """What the reconcile's write-down does to the record (design 1 §5.5 step
    2)."""

    def test_a_held_plan_written_down_resolves_its_errors(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        environment: Environment,
    ) -> None:
        path = _plan_path(project)
        _ingest(container, path, MISSPELT_PLAN, environment)
        engine_events.clear()

        with scoped_session(container):
            container.ingest_service().write_down([path])

        assert _errors(session) == []
        assert engine_events == [ErrorsResolved(project.id, path)]

    def test_a_held_document_written_down_keeps_its_errors(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        environment: Environment,
    ) -> None:
        _bear_draft(container, project, DRAFT)
        path = f"draft-{project.number}/project.md"
        _ingest(container, path, BROKEN, environment)
        errors = _errors(session)
        engine_events.clear()

        with scoped_session(container):
            container.ingest_service().write_down([path])

        assert errors
        assert _errors(session) == errors
        assert engine_events == []

    def test_a_plan_not_held_or_not_written_down_is_left_as_it_is(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        environment: Environment,
    ) -> None:
        held = Project(created_by_user_id=project.created_by_user_id)
        session.add(held)
        session.flush()
        _ingest(container, _plan_path(held), MISSPELT_PLAN, environment)
        errors = _errors(session)
        engine_events.clear()

        with scoped_session(container):
            container.ingest_service().write_down([_plan_path(project)])

        assert errors
        assert _errors(session) == errors
        assert engine_events == []


def _plan_path(project: Project) -> str:
    return f"draft-{project.number}/plan.json"


ENVIRONMENT_ID = "example-env-1"


def _committed_handbook(app: Flask) -> tuple[str, uuid.UUID]:
    """A draft project with its handbook, committed: the handbook's path and
    its id."""
    container = app.container
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
        session.add(Environment(id=ENVIRONMENT_ID, name="Example-1", exempt=False))
        session.flush()
        handbook = container.document_service().bear_handbook(project, HANDBOOK)
        return f"draft-{project.number}/handbook.md", handbook.id


def _committed_run(app: Flask, document_id: uuid.UUID) -> uuid.UUID:
    """A Session of the document's project with a Turn in flight, committed:
    its id."""
    with scoped_session(app.container) as session:
        run = models.Session(
            project_id=session.get_one(Document, document_id).project_id,
            environment_id=ENVIRONMENT_ID,
            kind_code="chat",
            cwd="/work/PilotProjects",
            token_hash="1" * 64,
            state_code=SessionState.RUNNING,
        )
        session.add(run)
        session.flush()
        turn_in_flight(session, run)
        return run.id


def _committed_item(app: Flask, run_id: uuid.UUID) -> tuple[str, uuid.UUID]:
    """A document of two asks the Session `run_id` bore in its project,
    committed: its tree path and its id."""
    container = app.container
    with scoped_session(container) as session:
        run = session.get_one(models.Session, run_id)
        project = session.get_one(Project, run.project_id)
        item = container.document_service().bear_item(
            project, "document", "Which tent?", run, TWO_ASKS
        )
        return tree_path(project, session.get_one(Document, item.id).path), item.id


def _save(
    app: Flask, path: str, content: str, run_id: uuid.UUID | None = None
) -> Ingested:
    """The save of `path` on the handbook's hash, credited to the Session
    `run_id`."""
    container = app.container
    with scoped_session(container) as session:
        return container.ingest_service().ingest(
            path,
            content.encode(),
            sha256_hex(HANDBOOK),
            session.get_one(Environment, ENVIRONMENT_ID),
            None if run_id is None else session.get_one(models.Session, run_id),
        )


def _end_turn(app: Flask, run_id: uuid.UUID) -> None:
    """The Session's turn ended as the relay ends it: under the Session's
    lock, its Turns ended and the engine's turn end."""
    container = app.container
    with scoped_session(container) as session:
        run = container.session_record_service().lock_session(run_id)
        end_turns(session, run)
        container.document_service().turn_ended(run)


class _Save(threading.Thread):
    def __init__(
        self, app: Flask, path: str, content: str, run_id: uuid.UUID | None = None
    ) -> None:
        super().__init__()
        self.app, self.path, self.content, self.run_id = app, path, content, run_id
        self.answer: Ingested | None = None
        self.error: Exception | None = None

    def run(self) -> None:
        try:
            self.answer = _save(self.app, self.path, self.content, self.run_id)
        except Exception as error:
            self.error = error


class _TurnEnd(threading.Thread):
    def __init__(self, app: Flask, run_id: uuid.UUID) -> None:
        super().__init__()
        self.app, self.run_id = app, run_id
        self.error: Exception | None = None

    def run(self) -> None:
        try:
            _end_turn(self.app, self.run_id)
        except Exception as error:
            self.error = error


def _committed_versions(
    app: Flask, document_id: uuid.UUID
) -> list[tuple[VersionCause, str | None, uuid.UUID | None]]:
    with scoped_session(app.container) as session:
        return [
            (cause, text, session_id)
            for _, cause, text, session_id in _versions(
                session, session.get_one(Document, document_id)
            )
        ]


def _writing(app: Flask, document_id: uuid.UUID) -> uuid.UUID | None:
    with scoped_session(app.container) as session:
        return session.get_one(Document, document_id).writing_session_id


class TestIngestServiceRowLock:
    """Two saves of one document never interleave (TD §8.5)."""

    def test_an_ingest_waits_for_the_documents_row(self, committed_app: Flask) -> None:
        path, document_id = _committed_handbook(committed_app)
        container = committed_app.container
        with committed_app.app_context():
            engine = db.engine

        with engine.connect() as holder:
            # FOR KEY SHARE conflicts with the ingest's FOR UPDATE and not with
            # the UPDATE that writes its ingest: only the lock the ingest takes
            # before it reads waits on it.
            holder.execute(
                sql("SELECT id FROM documents WHERE id = :id FOR KEY SHARE"),
                {"id": document_id},
            )
            with (
                pytest.raises(OperationalError) as raised,
                scoped_session(container) as session,
            ):
                session.execute(sql("SET LOCAL lock_timeout = '200ms'"))
                container.ingest_service().ingest(
                    path,
                    b"Keep it shorter.\n",
                    sha256_hex(HANDBOOK),
                    session.get_one(Environment, ENVIRONMENT_ID),
                    None,
                )
            holder.rollback()

        assert isinstance(raised.value.orig, LockNotAvailable)
        with scoped_session(container) as session:
            assert session.get_one(Document, document_id).ingested_text is None

    def test_two_saves_from_one_base_serialize(
        self, committed_app: Flask, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path, document_id = _committed_handbook(committed_app)
        adds_q1 = HANDBOOK + "\n```question id=Q1\ndefault: The lake\n```\n"
        edits_prose = HANDBOOK.replace("Keep it short.", "Keep it shorter.")
        first = _Save(committed_app, path, adds_q1)
        second = _Save(committed_app, path, edits_prose)
        holding, release = threading.Event(), threading.Event()
        lock = DocumentService.lock

        def held_lock(self: DocumentService, document: Document) -> None:
            lock(self, document)
            if threading.current_thread() is first:
                holding.set()
                assert release.wait(5)

        monkeypatch.setattr(DocumentService, "lock", held_lock)
        first.start()
        try:
            assert holding.wait(5)
            second.start()
            _wait_for_a_lock_wait(committed_app)
        finally:
            release.set()
            first.join(5)
            second.join(5)

        assert first.error is None
        assert second.error is None
        assert first.answer == Ingested(
            kind=PathKind.DOCUMENT,
            content=None,
            hash=sha256_hex(adds_q1),
            stale=False,
            held=False,
            faults=(),
        )
        merged = adds_q1.replace("Keep it short.", "Keep it shorter.")
        assert second.answer == Ingested(
            kind=PathKind.DOCUMENT,
            content=merged.encode(),
            hash=sha256_hex(merged),
            stale=True,
            held=False,
            faults=(
                dsl.Fault(
                    9, "block Q1: only the draft's blocks may be removed; restored"
                ),
            ),
        )
        with scoped_session(committed_app.container) as session:
            assert session.get_one(Document, document_id).published_text == merged

    def test_a_save_of_an_item_of_pilots_own_waits_for_the_projects_row(
        self, committed_app: Flask
    ) -> None:
        """The lock a close takes, before the Session's and the document's."""
        _, handbook_id = _committed_handbook(committed_app)
        run_id = _committed_run(committed_app, handbook_id)
        path, item_id = _committed_item(committed_app, run_id)
        container = committed_app.container
        with committed_app.app_context():
            engine = db.engine
        with scoped_session(container) as session:
            project_id = session.get_one(Document, handbook_id).project_id

        with engine.connect() as holder:
            # As for a document's row: only the save's own lock conflicts.
            holder.execute(
                sql("SELECT id FROM projects WHERE id = :id FOR KEY SHARE"),
                {"id": project_id},
            )
            with (
                pytest.raises(OperationalError) as raised,
                scoped_session(container) as session,
            ):
                session.execute(sql("SET LOCAL lock_timeout = '200ms'"))
                container.ingest_service().ingest(
                    path,
                    TWO_ASKS_EDITED.encode(),
                    sha256_hex(TWO_ASKS),
                    session.get_one(Environment, ENVIRONMENT_ID),
                    session.get_one(models.Session, run_id),
                )
            holder.rollback()

        assert isinstance(raised.value.orig, LockNotAvailable)
        with scoped_session(container) as session:
            assert session.get_one(Document, item_id).ingested_text is None

    def test_a_plan_save_waits_for_the_projects_row(self, committed_app: Flask) -> None:
        path, document_id = _committed_handbook(committed_app)
        path = path.replace("handbook.md", "plan.json")
        container = committed_app.container
        with committed_app.app_context():
            engine = db.engine
        with scoped_session(container) as session:
            project_id = session.get_one(Document, document_id).project_id

        with engine.connect() as holder:
            # As for a document's row: only the save's own lock conflicts.
            holder.execute(
                sql("SELECT id FROM projects WHERE id = :id FOR KEY SHARE"),
                {"id": project_id},
            )
            with (
                pytest.raises(OperationalError) as raised,
                scoped_session(container) as session,
            ):
                session.execute(sql("SET LOCAL lock_timeout = '200ms'"))
                container.ingest_service().ingest(
                    path,
                    PLAN.encode(),
                    None,
                    session.get_one(Environment, ENVIRONMENT_ID),
                    None,
                )
            holder.rollback()

        assert isinstance(raised.value.orig, LockNotAvailable)
        with scoped_session(container) as session:
            assert session.scalars(select(PlanTask)).all() == []

    def test_a_write_down_waits_for_the_projects_row(
        self, committed_app: Flask
    ) -> None:
        path, document_id = _committed_handbook(committed_app)
        path = path.replace("handbook.md", "plan.json")
        container = committed_app.container
        with committed_app.app_context():
            engine = db.engine
        _save(committed_app, path, MISSPELT_PLAN)
        with scoped_session(container) as session:
            project_id = session.get_one(Document, document_id).project_id

        with engine.connect() as holder:
            holder.execute(
                sql("SELECT id FROM projects WHERE id = :id FOR UPDATE"),
                {"id": project_id},
            )
            with (
                pytest.raises(OperationalError) as raised,
                scoped_session(container) as session,
            ):
                session.execute(sql("SET LOCAL lock_timeout = '200ms'"))
                container.ingest_service().write_down([path])
            holder.rollback()

        assert isinstance(raised.value.orig, LockNotAvailable)
        with scoped_session(container) as session:
            assert container.tree_service().held_path(path)

    def test_a_sessions_save_takes_its_sessions_row_before_the_documents(
        self, committed_app: Flask
    ) -> None:
        """Every end of a Turn takes the Session's row before its documents'
        (`RelayService._end_turn`): the save takes them in that order."""
        path, document_id = _committed_handbook(committed_app)
        run_id = _committed_run(committed_app, document_id)
        with committed_app.app_context():
            engine = db.engine
        save = _Save(committed_app, path, SHORTER, run_id)

        with engine.connect() as holder, engine.connect() as other:
            holder.execute(
                sql("SELECT id FROM sessions WHERE id = :id FOR UPDATE"),
                {"id": run_id},
            )
            save.start()
            try:
                _wait_for_a_lock_wait(committed_app)
                # The waiting save holds no lock on the document's row.
                other.execute(
                    sql("SELECT id FROM documents WHERE id = :id FOR UPDATE NOWAIT"),
                    {"id": document_id},
                )
                other.rollback()
            finally:
                holder.rollback()
                save.join(5)

        assert save.error is None
        assert _writing(committed_app, document_id) == run_id

    def test_a_save_behind_its_turns_end_finds_the_turn_ended(
        self, committed_app: Flask
    ) -> None:
        """The turn's end commits first: the save is late, its Version cut at
        once, and no session writes the document."""
        path, document_id = _committed_handbook(committed_app)
        run_id = _committed_run(committed_app, document_id)
        with committed_app.app_context():
            engine = db.engine
        save = _Save(committed_app, path, SHORTER, run_id)

        with engine.connect() as holder:
            holder.execute(
                sql("SELECT id FROM sessions WHERE id = :id FOR UPDATE"),
                {"id": run_id},
            )
            holder.execute(
                sql("UPDATE turns SET ended_at = now() WHERE session_id = :id"),
                {"id": run_id},
            )
            save.start()
            try:
                _wait_for_a_lock_wait(committed_app)
            finally:
                holder.commit()
                save.join(5)

        assert save.error is None
        assert _writing(committed_app, document_id) is None
        assert _committed_versions(committed_app, document_id) == [
            (VersionCause.BORN, HANDBOOK, None),
            (VersionCause.TURN, SHORTER, run_id),
        ]

    def test_a_turn_end_behind_a_save_finds_the_document_written(
        self, committed_app: Flask, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The save commits first: it writes the document in the turn, and
        the turn's end cuts the one Version, of the save's text."""
        path, document_id = _committed_handbook(committed_app)
        run_id = _committed_run(committed_app, document_id)
        save = _Save(committed_app, path, SHORTER, run_id)
        turn_end = _TurnEnd(committed_app, run_id)
        holding, release = threading.Event(), threading.Event()
        lock = DocumentService.lock

        def held_lock(self: DocumentService, document: Document) -> None:
            lock(self, document)
            if threading.current_thread() is save:
                holding.set()
                assert release.wait(5)

        monkeypatch.setattr(DocumentService, "lock", held_lock)
        save.start()
        try:
            assert holding.wait(5)
            turn_end.start()
            _wait_for_a_lock_wait(committed_app)
        finally:
            release.set()
            save.join(5)
            turn_end.join(5)

        assert save.error is None
        assert turn_end.error is None
        assert _writing(committed_app, document_id) is None
        assert _committed_versions(committed_app, document_id) == [
            (VersionCause.BORN, HANDBOOK, None),
            (VersionCause.TURN, SHORTER, run_id),
        ]

    def test_a_save_while_its_brain_answers_waits_for_the_answer(
        self, committed_app: Flask, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The brain's answer takes its Session's row before the document's,
        as the save does: a save of the document while the brain answers in
        it waits for the answer, and neither deadlocks."""
        _, document_id = _committed_handbook(committed_app)
        run_id = _committed_run(committed_app, document_id)
        path, item_id = _committed_item(committed_app, run_id)
        container = committed_app.container
        save = _Save(committed_app, path, TWO_ASKS_EDITED, run_id)
        record = EffectService.record

        def saving_record(
            self: EffectService, *args: Any, **kwargs: Any
        ) -> SessionRecord | None:
            save.start()
            _wait_for_a_lock_wait(committed_app)
            return record(self, *args, **kwargs)

        monkeypatch.setattr(EffectService, "record", saving_record)
        try:
            with scoped_session(container) as session:
                run = session.get_one(models.Session, run_id)
                container.pilot_store_service().answer(
                    Brain(run.id, run.project_id, run.kind_code),
                    f"{item_id}/D1",
                    "Dome",
                    "ada",
                    note=None,
                    to=None,
                    tool_use_id=None,
                )
        finally:
            save.join(5)

        assert save.error is None
        with scoped_session(container) as session:
            document = session.get_one(Document, item_id)
            assert document.ingested_session_id == run_id
            assert "default: The river" in (document.published_text or "")
            assert (
                session.scalars(
                    select(Block.answer).where(
                        Block.document_id == item_id, Block.local_id == "D1"
                    )
                ).one()
                == "Dome"
            )


def _wait_for_a_lock_wait(app: Flask) -> None:
    """Return once a backend of the app's database waits on a lock."""
    with app.app_context():
        engine = db.engine
    deadline = time.perf_counter() + 5
    with engine.connect() as connection:
        while True:
            waiting = connection.execute(
                sql(
                    "SELECT count(*) FROM pg_stat_activity"
                    " WHERE datname = current_database()"
                    " AND wait_event_type = 'Lock'"
                )
            ).scalar_one()
            # pg_stat_activity is read once per transaction.
            connection.rollback()
            if waiting:
                return
            assert time.perf_counter() < deadline, "no save waited on the lock"
            threading.Event().wait(0.01)
