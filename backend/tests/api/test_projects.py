"""/api/projects: the project list, the archived projects and a project's
head, as the signed-in person reads them (F1, F2, F3, D012); a draft made
from the plus (F46.1, F47.1), and their answers to its asks in place (F47.4);
and what they change of a project's standing, its transitions and their
membership (F4.1, F5, F6, F127, F128)."""

import base64
import uuid
from datetime import datetime
from typing import Any

import pytest
from flask.testing import FlaskClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.models import (
    Document,
    Environment,
    Item,
    Project,
    ProjectMember,
    ProjectTransition,
    User,
)
from app.models.reference import DocumentRole, SessionState, TransitionKind
from app.schemas.testing_record import InventedFileSchema, InventedProjectCreateSchema
from app.services.container import ServiceContainer
from tests.support.fake_sidecar import FakeSidecar

PROJECTS = "/api/projects"


def _sign_in(
    client: FlaskClient,
    subject: str = "subject-ada",
    roles: tuple[str, ...] = ("editor",),
) -> None:
    response = client.post(
        "/api/testing/auth/session",
        json={"subject": subject, "name": "Ada Example", "roles": list(roles)},
    )
    assert response.status_code == 201


def _run(
    session: Session, project: Project, environment: Environment
) -> models.Session:
    """An idle work session of `project`, which adds its items."""
    run = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code="work",
        cwd="/work/Camp",
        token_hash=uuid.uuid4().hex * 2,
        state_code=SessionState.IDLE,
    )
    session.add(run)
    session.flush()
    return run


def _make(container: ServiceContainer, **spec: Any) -> uuid.UUID:
    spec.setdefault("members", ["ada"])
    return (
        container.test_data_service()
        .project(InventedProjectCreateSchema.model_validate(spec))
        .id
    )


@pytest.mark.usefixtures("person")
class TestListProjects:
    def test_the_tabs_of_every_unarchived_project(
        self, client: FlaskClient, container: ServiceContainer, session: Session
    ) -> None:
        container.test_data_service().person("ben", "Ben Example")
        draft = _make(container, state="draft")
        recipes = _make(
            container,
            name="Recipe box",
            ticket="RB-12",
            members=["ben"],
            tasks=[
                {"id": "scope", "title": "Agree the scope", "status": "done"},
                {
                    "id": "build",
                    "title": "Build the card page",
                    "status": "in_progress",
                },
                {"id": "ship", "title": "Ship it", "status": "pending"},
            ],
        )
        finished = _make(container, name="Bike log", state="finished")
        _make(container, name="Photo album", archived=True)
        finished_at = session.scalars(
            select(ProjectTransition.at).where(
                ProjectTransition.project_id == finished,
                ProjectTransition.kind_code == TransitionKind.FINISHED,
            )
        ).one()
        _sign_in(client)

        response = client.get(PROJECTS)

        assert response.status_code == 200
        body = response.get_json()
        assert datetime.fromisoformat(body["projects"][2]["finished_at"]) == finished_at
        body["projects"][2]["finished_at"] = "<the finish>"
        assert body == {
            "projects": [
                {
                    "id": str(draft),
                    "name": None,
                    "ticket": None,
                    "state": "draft",
                    "finished_at": None,
                    "status": None,
                    "member": True,
                    "progress": {"done": 0, "total": 0, "in_progress": []},
                    "badge": {"count": 0, "urgent": False},
                },
                {
                    "id": str(recipes),
                    "name": "Recipe box",
                    "ticket": "RB-12",
                    "state": "open",
                    "finished_at": None,
                    "status": "idle",
                    "member": False,
                    "progress": {
                        "done": 1,
                        "total": 3,
                        "in_progress": ["Build the card page"],
                    },
                    "badge": {"count": 0, "urgent": False},
                },
                {
                    "id": str(finished),
                    "name": "Bike log",
                    "ticket": None,
                    "state": "finished",
                    "finished_at": "<the finish>",
                    "status": None,
                    "member": True,
                    "progress": {"done": 0, "total": 0, "in_progress": []},
                    "badge": {"count": 0, "urgent": False},
                },
            ]
        }

    def test_a_tab_counts_the_items_waiting_on_the_caller(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        environment: Environment,
    ) -> None:
        container.test_data_service().person("ben", "Ben Example")
        camp = session.get_one(Project, _make(container, name="Camp"))
        run = _run(session, camp, environment)
        for title, front_matter in (
            ("Where?", ""),
            ("Storm", "urgent: true\n"),
            ("Opens in May", ""),
            ("Boots?", "for: ben\n"),
        ):
            container.document_service().bear_item(
                camp,
                "notice" if title in ("Storm", "Opens in May") else "question",
                title,
                run,
                f"---\ntitle: {title}\n{front_matter}---\n",
            )
        _sign_in(client)

        (tab,) = client.get(PROJECTS).get_json()["projects"]

        assert tab["badge"] == {"count": 2, "urgent": True}

    def test_archived_reads_the_archived_projects(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        _make(container, name="Kept")
        album = _make(container, name="Photo album", archived=True)
        _sign_in(client)

        response = client.get(PROJECTS, query_string={"archived": "true"})

        assert response.status_code == 200
        assert [tab["id"] for tab in response.get_json()["projects"]] == [str(album)]

    def test_no_project_is_an_empty_list(self, client: FlaskClient) -> None:
        _sign_in(client)

        assert client.get(PROJECTS).get_json() == {"projects": []}

    def test_a_person_at_their_first_sign_in_is_a_member_of_none(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        _make(container, name="Theirs")
        _sign_in(client, subject="subject-newcomer")

        (tab,) = client.get(PROJECTS).get_json()["projects"]

        assert tab["member"] is False

    def test_an_archived_that_is_no_boolean_is_refused(
        self, client: FlaskClient
    ) -> None:
        _sign_in(client)

        response = client.get(PROJECTS, query_string={"archived": "sometimes"})

        assert response.status_code == 400

    def test_without_editor_it_is_refused(self, client: FlaskClient) -> None:
        _sign_in(client, roles=())

        assert client.get(PROJECTS).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.get(PROJECTS).status_code == 401


@pytest.mark.usefixtures("person")
class TestGetProject:
    def test_the_head_of_a_project(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        environment: Environment,
    ) -> None:
        container.test_data_service().person("ben", "ben")
        recipes = _make(
            container,
            name="Recipe box",
            ticket="RB-12",
            repo="pvginkel/RecipeBox",
            autopilot=True,
            members=["ben", "ada"],
            tasks=[
                {"id": "scope", "title": "Agree the scope", "status": "done"},
                {
                    "id": "build",
                    "title": "Build the card page",
                    "status": "in_progress",
                    "notes": [
                        {
                            "id": "card-layout",
                            "summary": "Cards are one column",
                            "content": "Ben chose one column.",
                        }
                    ],
                },
                {"id": "ship", "title": "Ship it", "status": "pending"},
            ],
            notes=[
                {
                    "id": "print-view",
                    "summary": "A print view is the plan's question",
                    "content": "No task covers printing yet.",
                }
            ],
            open_items=2,
            environment_id=environment.id,
        )
        _sign_in(client)

        response = client.get(f"{PROJECTS}/{recipes}")

        assert response.status_code == 200
        assert response.get_json() == {
            "id": str(recipes),
            "name": "Recipe box",
            "ticket": "RB-12",
            "repo": "pvginkel/RecipeBox",
            "state": "open",
            "archived": False,
            "autopilot": True,
            "status": "idle",
            "member": True,
            "members": [
                {"handle": "ben", "name": "ben", "initials": "B", "avatar_slot": 2},
                {
                    "handle": "ada",
                    "name": "Ada Example",
                    "initials": "AE",
                    "avatar_slot": 1,
                },
            ],
            "progress": {"done": 1, "total": 3, "in_progress": ["Build the card page"]},
            "tasks": [
                {
                    "id": "scope",
                    "title": "Agree the scope",
                    "status": "done",
                    "notes": [],
                },
                {
                    "id": "build",
                    "title": "Build the card page",
                    "status": "in_progress",
                    "notes": [
                        {
                            "id": "card-layout",
                            "summary": "Cards are one column",
                            "content": "Ben chose one column.",
                        }
                    ],
                },
                {"id": "ship", "title": "Ship it", "status": "pending", "notes": []},
            ],
            "notes": [
                {
                    "id": "print-view",
                    "summary": "A print view is the plan's question",
                    "content": "No task covers printing yet.",
                }
            ],
            "running_work": [],
            "open_items": 2,
        }

    def test_the_running_work_is_named_for_the_finish_dialog(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        environment: Environment,
    ) -> None:
        recipes = _make(
            container, name="Recipe box", open_items=1, environment_id=environment.id
        )
        project = session.get_one(Project, recipes)
        run = _run(session, project, environment)
        run.state_code = SessionState.RUNNING
        container.record_service().place_work(project, run, "Building the card page")
        _sign_in(client)

        body = client.get(f"{PROJECTS}/{recipes}").get_json()

        assert body["running_work"] == [
            {"id": str(run.id), "title": "Building the card page"}
        ]
        assert body["open_items"] == 1

    def test_an_archived_project_reads_as_it_was_left(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        album = _make(container, name="Photo album", state="finished", archived=True)
        _sign_in(client)

        body = client.get(f"{PROJECTS}/{album}").get_json()

        assert (body["state"], body["archived"], body["autopilot"]) == (
            "finished",
            True,
            False,
        )

    def test_an_unknown_project_is_not_found(self, client: FlaskClient) -> None:
        _sign_in(client)
        unknown = uuid.uuid4()

        response = client.get(f"{PROJECTS}/{unknown}")

        assert response.status_code == 404
        assert response.get_json()["error"] == f"Project {unknown} was not found"

    def test_an_id_that_is_no_uuid_is_not_found(self, client: FlaskClient) -> None:
        _sign_in(client)

        assert client.get(f"{PROJECTS}/recipe-box").status_code == 404

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        recipes = _make(container, name="Recipe box")
        _sign_in(client, roles=())

        assert client.get(f"{PROJECTS}/{recipes}").status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.get(f"{PROJECTS}/{uuid.uuid4()}").status_code == 401


_DECISION = """---
title: Which tent?
step: build
---

# Which tent?

The dome stands up in five minutes.

```decision id=D1
options:
  - Dome: up in five minutes
  - Tunnel
recommend: Dome
```
"""


def _stamped(body: dict[str, Any], path: tuple[str | int, ...]) -> datetime:
    """The time at `path` in `body`, replaced by a placeholder."""
    *parents, key = path
    holder: Any = body
    for parent in parents:
        holder = holder[parent]
    moment = datetime.fromisoformat(holder[key])
    holder[key] = "<time>"
    return moment


@pytest.mark.usefixtures("person")
class TestGetTimeline:
    def test_the_timeline_of_a_project(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        environment: Environment,
        person: User,
    ) -> None:
        container.test_data_service().person("ben", "Ben Example")
        camp = session.get_one(
            Project,
            _make(
                container,
                name="Camp",
                tasks=[{"id": "build", "title": "Build the camp", "status": "pending"}],
                opening="Let's camp.\n",
            ),
        )
        run = _run(session, camp, environment)
        documents = container.document_service()
        opening = session.scalars(select(Item).where(Item.project_id == camp.id)).one()
        decision = documents.bear_item(camp, "decision", "Which tent?", run, _DECISION)
        container.record_service().answer(
            session.get_one(Document, decision.id),
            "D1",
            person,
            "Tunnel",
            note="More room.",
        )
        notice = documents.bear_item(
            camp,
            "notice",
            "Storm",
            run,
            "---\ntitle: Storm\nurgent: true\nfor: ben\n---\n\nA storm comes.\n",
        )
        _sign_in(client)

        response = client.get(f"{PROJECTS}/{camp.id}/timeline")

        assert response.status_code == 200
        body = response.get_json()
        assert [
            _stamped(body, ("items", index, "created_at")) for index in range(3)
        ] == [opening.created_at, decision.created_at, notice.created_at]
        assert _stamped(body, ("items", 1, "done", "at")) == decision.done_at
        assert (
            _stamped(body, ("items", 1, "body", 1, "block", "at")) == decision.done_at
        )
        ada = {
            "kind": "person",
            "handle": "ada",
            "name": "Ada Example",
            "initials": "AE",
            "avatar_slot": 1,
        }
        assert body == {
            "finished_at": None,
            "items": [
                {
                    "id": str(opening.id),
                    "seq": 1,
                    "kind": "opening",
                    "form": "prose",
                    "title": "Camp",
                    "file_name": None,
                    "created_at": "<time>",
                    "step": None,
                    "urgent": False,
                    "for_user": None,
                    "done": None,
                    "concept": False,
                    "author": ada,
                    "words": "Let's camp.\n",
                    "body": None,
                    "summary": None,
                    "word_count": None,
                    "read_minutes": None,
                    "writing": False,
                    "awaiting_read": False,
                    "edited_at": None,
                    "attachments": [],
                    "asked_writer_about": [],
                    "work": None,
                },
                {
                    "id": str(decision.id),
                    "seq": 2,
                    "kind": "decision",
                    "form": "prose",
                    "title": "Which tent?",
                    "file_name": None,
                    "created_at": "<time>",
                    "step": {"id": "build", "title": "Build the camp"},
                    "urgent": False,
                    "for_user": None,
                    "done": {
                        "at": "<time>",
                        "cause": "answered",
                        "by": ada,
                        "undo": True,
                    },
                    "concept": False,
                    "author": None,
                    "words": None,
                    "body": [
                        {
                            "type": "prose",
                            "markdown": "The dome stands up in five minutes.",
                            "section": None,
                        },
                        {
                            "type": "block",
                            "block": {
                                "id": "D1",
                                "kind": "decision",
                                "confirmation": False,
                                "because": None,
                                "proposal": None,
                                "default": None,
                                "check": None,
                                "options": [
                                    {
                                        "label": "Dome",
                                        "text": "up in five minutes",
                                        "recommended": True,
                                    },
                                    {
                                        "label": "Tunnel",
                                        "text": None,
                                        "recommended": False,
                                    },
                                ],
                                "answer": "Tunnel",
                                "by": ada,
                                "at": "<time>",
                                "note": "More room.",
                                "via": "app",
                                "in_chat": None,
                                "done": None,
                                "deferral": None,
                                "section": None,
                            },
                        },
                    ],
                    "summary": None,
                    "word_count": 24,
                    "read_minutes": 1,
                    "writing": False,
                    "awaiting_read": False,
                    "edited_at": None,
                    "attachments": [],
                    "asked_writer_about": [],
                    "work": None,
                },
                {
                    "id": str(notice.id),
                    "seq": 3,
                    "kind": "notice",
                    "form": "prose",
                    "title": "Storm",
                    "file_name": None,
                    "created_at": "<time>",
                    "step": None,
                    "urgent": True,
                    "for_user": {
                        "kind": "person",
                        "handle": "ben",
                        "name": "Ben Example",
                        "initials": "BE",
                        "avatar_slot": 2,
                    },
                    "done": None,
                    "concept": False,
                    "author": None,
                    "words": None,
                    "body": [
                        {"type": "prose", "markdown": "A storm comes.", "section": None}
                    ],
                    "summary": None,
                    "word_count": 3,
                    "read_minutes": 1,
                    "writing": False,
                    "awaiting_read": False,
                    "edited_at": None,
                    "attachments": [],
                    "asked_writer_about": [],
                    "work": None,
                },
            ],
            "unhung_attachments": [],
        }

    def test_a_work_items_entry_carries_its_session(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        environment: Environment,
    ) -> None:
        camp = session.get_one(Project, _make(container, name="Camp"))
        run = _run(session, camp, environment)
        container.record_service().place_work(camp, run, "Build the camp")
        run.state_code = SessionState.RUNNING
        run.started_at = datetime.fromisoformat("2026-10-24T09:00:00+00:00")
        run.current_line = {
            "state": "working",
            "since": "2026-10-24T09:01:00+00:00",
            "step": {"tool": "Read", "input": {"file_path": "/work/Camp/plan.json"}},
        }
        session.flush()
        _sign_in(client)

        body = client.get(f"{PROJECTS}/{camp.id}/timeline").get_json()

        _opening, work = body["items"]
        assert (
            _stamped(work, ("work", "started_at")),
            _stamped(work, ("work", "current_line", "since")),
        ) == (run.started_at, datetime.fromisoformat("2026-10-24T09:01:00+00:00"))
        assert work["work"] == {
            "state": "running",
            "current_line": {
                "state": "working",
                "since": "<time>",
                "step": {
                    "tool": "Read",
                    "input": {"file_path": "/work/Camp/plan.json"},
                },
                "agent": None,
                "text": None,
            },
            "environment": {"id": environment.id, "name": "Example-1"},
            "started_at": "<time>",
            "error": None,
            "autopilot": False,
            "held_reason": None,
            "held_running": None,
            "stopped_at": None,
            "stopped_by": None,
            "stopped_cause": None,
        }

    def test_a_block_s_own_section_rides_with_its_text(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        environment: Environment,
    ) -> None:
        camp = session.get_one(Project, _make(container, name="Camp"))
        container.document_service().bear_item(
            camp,
            "document",
            "Camp kit",
            _run(session, camp, environment),
            "# Camp kit\n\nWhat we bring.\n\n## Which tent?\n\n"
            "```question id=Q1\n```\n",
        )
        _sign_in(client)

        body = client.get(f"{PROJECTS}/{camp.id}/timeline").get_json()

        parts = body["items"][1]["body"]
        assert [
            (part["type"], part.get("markdown"), part.get("section")) for part in parts
        ] == [
            ("prose", "What we bring.", None),
            ("prose", "## Which tent?", "Q1"),
            ("block", None, None),
        ]
        assert parts[2]["block"]["section"] == {"heading": "Which tent?"}

    def test_a_documents_summary_writing_and_attachments_ride_with_it(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        environment: Environment,
    ) -> None:
        camp = _make(container, name="Camp", environment_id=environment.id)
        data = container.test_data_service()
        item = data.item(
            camp,
            "review",
            "Camp kit",
            "---\ntitle: Camp kit\nsummary: What we bring.\n---\n\nBoots.\n",
        )
        data.save(
            item.id,
            "---\ntitle: Camp kit\nsummary: What we bring.\n---\n\nBoots, a tent.\n",
        )
        (sketch,) = data.attach(
            item.id,
            [
                InventedFileSchema.model_validate(
                    {
                        "title": "Sketch",
                        "filename": "sketch.md",
                        "content_type": "text/markdown",
                        "content": base64.b64encode(b"# Sketch\n").decode(),
                    }
                )
            ],
        )
        _sign_in(client)

        body = client.get(f"{PROJECTS}/{camp}/timeline").get_json()

        line = body["items"][1]
        assert _stamped(line, ("attachments", 0, "copied_at")) == sketch.copied_at
        assert {
            key: line[key]
            for key in (
                "summary",
                "word_count",
                "read_minutes",
                "writing",
                "edited_at",
                "attachments",
            )
        } == {
            "summary": "What we bring.",
            "word_count": 3,
            "read_minutes": 1,
            "writing": True,
            "edited_at": None,
            "attachments": [
                {
                    "id": str(sketch.id),
                    "title": "Sketch",
                    "filename": "sketch.md",
                    "content_type": "text/markdown",
                    "size": 9,
                    "batch": 1,
                    "copied_at": "<time>",
                    "source": f"{environment.id}:/work/Invented/sketch.md",
                }
            ],
        }

    def test_a_finished_project_has_its_finish(
        self, client: FlaskClient, container: ServiceContainer, session: Session
    ) -> None:
        bikes = _make(container, name="Bike log", state="finished")
        finished_at = session.scalars(
            select(ProjectTransition.at).where(
                ProjectTransition.project_id == bikes,
                ProjectTransition.kind_code == TransitionKind.FINISHED,
            )
        ).one()
        _sign_in(client)

        body = client.get(f"{PROJECTS}/{bikes}/timeline").get_json()

        assert datetime.fromisoformat(body["finished_at"]) == finished_at
        assert [item["kind"] for item in body["items"]] == ["opening"]

    def test_an_unknown_project_is_not_found(self, client: FlaskClient) -> None:
        _sign_in(client)
        unknown = uuid.uuid4()

        response = client.get(f"{PROJECTS}/{unknown}/timeline")

        assert response.status_code == 404
        assert response.get_json()["error"] == f"Project {unknown} was not found"

    def test_an_id_that_is_no_uuid_is_not_found(self, client: FlaskClient) -> None:
        _sign_in(client)

        assert client.get(f"{PROJECTS}/camp/timeline").status_code == 404

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        camp = _make(container, name="Camp")
        _sign_in(client, roles=())

        assert client.get(f"{PROJECTS}/{camp}/timeline").status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.get(f"{PROJECTS}/{uuid.uuid4()}/timeline").status_code == 401


@pytest.mark.usefixtures("person")
class TestGetProjectDocuments:
    """The project's draft, `project.md`, and its handbook, read only."""

    def test_the_handbook_born_at_create_reads_empty_the_draft_its_name(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        camp = _make(container, name="Camp")
        _sign_in(client)

        handbook = client.get(f"{PROJECTS}/{camp}/handbook")
        draft = client.get(f"{PROJECTS}/{camp}/draft")

        assert (handbook.status_code, handbook.get_json()) == (
            200,
            {"title": None, "body": [], "writing": False},
        )
        assert (draft.status_code, draft.get_json()) == (
            200,
            {"title": "Camp", "body": [], "writing": False},
        )

    @pytest.mark.parametrize("document", ["draft", "handbook"])
    def test_a_save_reads_as_drawn_while_pilot_writes_it(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        environment: Environment,
        document: str,
    ) -> None:
        camp = _make(container, name="Camp", environment_id=environment.id)
        container.test_data_service().save_project_document(
            camp, DocumentRole(document), "# Camp\n\nTwo tents.\n"
        )
        _sign_in(client)

        response = client.get(f"{PROJECTS}/{camp}/{document}")

        assert response.status_code == 200
        assert response.get_json() == {
            "title": "Camp",
            "body": [{"type": "prose", "markdown": "Two tents.", "section": None}],
            "writing": True,
        }

    def test_a_drafts_handbook_is_not_found(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        draft = _make(container, state="draft")
        _sign_in(client)

        response = client.get(f"{PROJECTS}/{draft}/handbook")

        assert response.status_code == 404
        assert response.get_json()["error"] == (
            f"Handbook of project {draft} was not found"
        )

    @pytest.mark.parametrize("document", ["draft", "handbook"])
    def test_an_unknown_project_is_not_found(
        self, client: FlaskClient, document: str
    ) -> None:
        _sign_in(client)
        unknown = uuid.uuid4()

        response = client.get(f"{PROJECTS}/{unknown}/{document}")

        assert response.status_code == 404
        assert response.get_json()["error"] == f"Project {unknown} was not found"

    @pytest.mark.parametrize("document", ["draft", "handbook"])
    def test_an_id_that_is_no_uuid_is_not_found(
        self, client: FlaskClient, document: str
    ) -> None:
        _sign_in(client)

        assert client.get(f"{PROJECTS}/camp/{document}").status_code == 404

    @pytest.mark.parametrize("document", ["draft", "handbook"])
    def test_without_editor_it_is_refused(
        self, client: FlaskClient, container: ServiceContainer, document: str
    ) -> None:
        camp = _make(container, name="Camp")
        _sign_in(client, roles=())

        assert client.get(f"{PROJECTS}/{camp}/{document}").status_code == 403

    @pytest.mark.parametrize("document", ["draft", "handbook"])
    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient, document: str
    ) -> None:
        response = oidc_client.get(f"{PROJECTS}/{uuid.uuid4()}/{document}")

        assert response.status_code == 401


DRAFT_ASKS = """---
title: Camp
---

```question id=Q1
default: The lake
```

```action id=A1
```
"""


def _drafted(container: ServiceContainer, environment: Environment) -> uuid.UUID:
    """A draft whose `project.md` Pilot wrote with two asks."""
    draft = _make(container, state="draft", environment_id=environment.id)
    container.test_data_service().save_project_document(
        draft, DocumentRole.DRAFT, DRAFT_ASKS
    )
    return draft


def _draft_block(client: FlaskClient, project_id: uuid.UUID, local_id: str) -> Any:
    body = client.get(f"{PROJECTS}/{project_id}/draft").get_json()["body"]
    return next(
        part["block"]
        for part in body
        if part["type"] == "block" and part["block"]["id"] == local_id
    )


@pytest.mark.usefixtures("person")
class TestAnswerDraftBlock:
    """A person's answer to the draft's ask, in place (F47.4)."""

    def test_the_answer_is_written_into_the_draft(
        self, client: FlaskClient, container: ServiceContainer, environment: Environment
    ) -> None:
        draft = _drafted(container, environment)
        _sign_in(client)

        response = client.post(
            f"{PROJECTS}/{draft}/draft/blocks/Q1/answer",
            json={"answer": "The forest", "note": "Shade."},
        )

        assert response.status_code == 204
        block = _draft_block(client, draft, "Q1")
        assert (
            block["answer"],
            block["by"]["handle"],
            block["via"],
            block["note"],
        ) == (
            "The forest",
            "ada",
            "app",
            "Shade.",
        )

    def test_past_create_project_md_takes_no_answer(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        camp = _make(container, name="Camp")
        _sign_in(client)

        response = client.post(
            f"{PROJECTS}/{camp}/draft/blocks/Q1/answer", json={"answer": "The lake"}
        )

        assert response.status_code == 409
        assert response.get_json()["error"].endswith(
            "because the project is no draft: its `project.md` takes no answer"
        )

    def test_an_unknown_project_or_ask_is_not_found(
        self, client: FlaskClient, container: ServiceContainer, environment: Environment
    ) -> None:
        draft = _drafted(container, environment)
        _sign_in(client)

        unknown = client.post(
            f"{PROJECTS}/{uuid.uuid4()}/draft/blocks/Q1/answer",
            json={"answer": "The lake"},
        )
        no_ask = client.post(
            f"{PROJECTS}/{draft}/draft/blocks/Q9/answer", json={"answer": "The lake"}
        )

        assert (unknown.status_code, no_ask.status_code) == (404, 404)

    def test_a_body_that_is_no_answer_is_refused(
        self, client: FlaskClient, container: ServiceContainer, environment: Environment
    ) -> None:
        draft = _drafted(container, environment)
        _sign_in(client)

        response = client.post(f"{PROJECTS}/{draft}/draft/blocks/Q1/answer", json={})

        assert response.status_code == 400

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, container: ServiceContainer, environment: Environment
    ) -> None:
        draft = _drafted(container, environment)
        _sign_in(client, roles=())

        response = client.post(
            f"{PROJECTS}/{draft}/draft/blocks/Q1/answer", json={"answer": "The lake"}
        )

        assert response.status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.post(
            f"{PROJECTS}/{uuid.uuid4()}/draft/blocks/Q1/answer",
            json={"answer": "The lake"},
        )

        assert response.status_code == 401


@pytest.mark.usefixtures("person")
class TestMarkDraftActionDone:
    """Done on the draft's action without options, in place (F47.4)."""

    def test_the_done_is_written_into_the_draft_with_the_paste_back(
        self, client: FlaskClient, container: ServiceContainer, environment: Environment
    ) -> None:
        draft = _drafted(container, environment)
        _sign_in(client)

        response = client.post(
            f"{PROJECTS}/{draft}/draft/blocks/A1/done", json={"note": "Pitched."}
        )

        assert response.status_code == 204
        block = _draft_block(client, draft, "A1")
        assert (block["done"] is not None, block["by"]["handle"], block["note"]) == (
            True,
            "ada",
            "Pitched.",
        )

    def test_a_question_takes_no_done(
        self, client: FlaskClient, container: ServiceContainer, environment: Environment
    ) -> None:
        draft = _drafted(container, environment)
        _sign_in(client)

        response = client.post(f"{PROJECTS}/{draft}/draft/blocks/Q1/done", json={})

        assert response.status_code == 409
        assert response.get_json()["error"].endswith(
            "because block Q1 is a question, not an action"
        )

    def test_past_create_it_is_refused(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        camp = _make(container, name="Camp")
        _sign_in(client)

        response = client.post(f"{PROJECTS}/{camp}/draft/blocks/A1/done", json={})

        assert response.status_code == 409

    def test_an_unknown_project_is_not_found(self, client: FlaskClient) -> None:
        _sign_in(client)

        response = client.post(
            f"{PROJECTS}/{uuid.uuid4()}/draft/blocks/A1/done", json={}
        )

        assert response.status_code == 404

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, container: ServiceContainer, environment: Environment
    ) -> None:
        draft = _drafted(container, environment)
        _sign_in(client, roles=())

        response = client.post(f"{PROJECTS}/{draft}/draft/blocks/A1/done", json={})

        assert response.status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.post(
            f"{PROJECTS}/{uuid.uuid4()}/draft/blocks/A1/done", json={}
        )

        assert response.status_code == 401


@pytest.mark.usefixtures("person")
class TestAddTransition:
    def test_finish_answers_the_head_with_its_new_standing(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        environment: Environment,
        session: Session,
        person: User,
    ) -> None:
        recipes = _make(
            container,
            name="Recipe box",
            autopilot=True,
            open_items=2,
            environment_id=environment.id,
        )
        _sign_in(client)

        response = client.post(
            f"{PROJECTS}/{recipes}/transitions", json={"kind": "finished"}
        )

        assert response.status_code == 201
        body = response.get_json()
        assert body["id"] == str(recipes)
        assert (
            body["state"],
            body["archived"],
            body["autopilot"],
            body["member"],
            body["open_items"],
        ) == ("finished", False, False, True, 0)
        assert [
            (transition.kind_code, transition.by_user_id)
            for transition in session.scalars(
                select(ProjectTransition)
                .where(ProjectTransition.project_id == recipes)
                .order_by(ProjectTransition.at, ProjectTransition.id)
            )
        ][-2:] == [
            (TransitionKind.FINISHED, person.id),
            (TransitionKind.AUTOPILOT_OFF, person.id),
        ]
        assert {
            item.done_cause_code
            for item in session.scalars(
                select(Item).where(
                    Item.project_id == recipes, Item.kind_code != "opening"
                )
            )
        } == {"finished"}

    @pytest.mark.parametrize(
        ("spec", "kind", "standing"),
        [
            ({"state": "finished"}, "reopened", ("open", False, False)),
            ({"state": "finished"}, "archived", ("finished", True, False)),
            (
                {"autopilot": True, "archived": True},
                "brought_back",
                ("open", False, True),
            ),
            ({}, "autopilot_on", ("open", False, True)),
            ({"autopilot": True}, "autopilot_off", ("open", False, False)),
        ],
    )
    def test_every_kind_a_person_makes(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        spec: dict[str, Any],
        kind: str,
        standing: tuple[str, bool, bool],
    ) -> None:
        recipes = _make(container, name="Recipe box", **spec)
        _sign_in(client)

        response = client.post(f"{PROJECTS}/{recipes}/transitions", json={"kind": kind})

        assert response.status_code == 201
        body = response.get_json()
        assert (body["state"], body["archived"], body["autopilot"]) == standing

    def test_a_pause_and_a_resume_answer_the_head_with_its_status(
        self, client: FlaskClient, container: ServiceContainer, session: Session
    ) -> None:
        recipes = _make(container, name="Recipe box", autopilot=True)
        _sign_in(client)

        paused = client.post(
            f"{PROJECTS}/{recipes}/transitions", json={"kind": "paused"}
        )
        again = client.post(
            f"{PROJECTS}/{recipes}/transitions", json={"kind": "paused"}
        )
        resumed = client.post(
            f"{PROJECTS}/{recipes}/transitions", json={"kind": "resumed"}
        )

        assert (paused.status_code, again.status_code, resumed.status_code) == (
            201,
            409,
            201,
        )
        assert [
            (body["status"], body["autopilot"])
            for body in (paused.get_json(), resumed.get_json())
        ] == [("paused", True), ("idle", True)]
        assert again.get_json()["error"] == (
            "Cannot pause Recipe box because it is paused already"
        )
        assert [
            transition.kind_code
            for transition in session.scalars(
                select(ProjectTransition)
                .where(ProjectTransition.project_id == recipes)
                .order_by(ProjectTransition.at, ProjectTransition.id)
            )
        ][-2:] == [TransitionKind.PAUSED, TransitionKind.RESUMED]

    def test_archive_and_bring_back_move_the_folder_out_of_the_stores_tree_and_back(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
    ) -> None:
        recipes = _make(container, name="Recipe box")
        fake_sidecar.connect()
        fake_sidecar.drain()
        synced = set(fake_sidecar.tree)
        _sign_in(client)

        archived = client.post(
            f"{PROJECTS}/{recipes}/transitions", json={"kind": "archived"}
        )
        fake_sidecar.drain()

        assert archived.status_code == 201
        assert set(fake_sidecar.tree) == {"reference.json"} != synced

        brought_back = client.post(
            f"{PROJECTS}/{recipes}/transitions", json={"kind": "brought_back"}
        )
        fake_sidecar.drain()

        assert brought_back.status_code == 201
        tree = container.tree_service()
        assert fake_sidecar.tree == {
            entry.path: tree.read(entry.path).content for entry in tree.manifest()
        }
        assert set(fake_sidecar.tree) == synced

    @pytest.mark.parametrize(
        "body",
        [{"kind": "opened"}, {"kind": "pausing"}, {"kind": None}, {}],
    )
    def test_a_kind_no_person_makes_is_refused(
        self, client: FlaskClient, container: ServiceContainer, body: dict[str, Any]
    ) -> None:
        recipes = _make(container, name="Recipe box", state="draft")
        _sign_in(client)

        response = client.post(f"{PROJECTS}/{recipes}/transitions", json=body)

        assert response.status_code == 400

    def test_a_kind_the_standing_does_not_allow_is_a_conflict(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        recipes = _make(container, name="Recipe box", archived=True)
        _sign_in(client)

        response = client.post(
            f"{PROJECTS}/{recipes}/transitions", json={"kind": "finished"}
        )

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot finish Recipe box because it is archived, and an archived "
            "project takes Bring back alone"
        )

    def test_a_caller_without_a_handle_is_a_conflict(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        recipes = _make(container, name="Recipe box")
        _sign_in(client, subject="subject-newcomer")

        response = client.post(
            f"{PROJECTS}/{recipes}/transitions", json={"kind": "autopilot_on"}
        )

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot turn auto pilot on for Recipe box because you have not chosen "
            "your handle yet"
        )

    def test_an_unknown_project_is_not_found(self, client: FlaskClient) -> None:
        _sign_in(client)
        unknown = uuid.uuid4()

        response = client.post(
            f"{PROJECTS}/{unknown}/transitions", json={"kind": "finished"}
        )

        assert response.status_code == 404
        assert response.get_json()["error"] == f"Project {unknown} was not found"

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        recipes = _make(container, name="Recipe box")
        _sign_in(client, roles=())

        response = client.post(
            f"{PROJECTS}/{recipes}/transitions", json={"kind": "finished"}
        )

        assert response.status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.post(
            f"{PROJECTS}/{uuid.uuid4()}/transitions", json={"kind": "finished"}
        )

        assert response.status_code == 401


def _open_memberships(session: Session, project_id: uuid.UUID, person: User) -> int:
    return len(
        session.scalars(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == person.id,
                ProjectMember.left_at.is_(None),
            )
        ).all()
    )


@pytest.mark.usefixtures("person")
class TestCreateProject:
    def test_the_plus_answers_the_drafts_head_and_writes_its_folder(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
    ) -> None:
        fake_sidecar.connect()
        fake_sidecar.drain()
        _sign_in(client)

        response = client.post(PROJECTS)
        fake_sidecar.drain()

        assert response.status_code == 201, response.get_json()
        body = response.get_json()
        assert body == {
            "id": body["id"],
            "name": None,
            "ticket": None,
            "repo": None,
            "state": "draft",
            "archived": False,
            "autopilot": False,
            "status": None,
            "member": True,
            "members": [
                {
                    "handle": "ada",
                    "name": "Ada Example",
                    "initials": "AE",
                    "avatar_slot": 1,
                }
            ],
            "progress": {"done": 0, "total": 0, "in_progress": []},
            "tasks": [],
            "notes": [],
            "running_work": [],
            "open_items": 0,
        }
        draft = session.get_one(Project, uuid.UUID(body["id"]))
        assert fake_sidecar.tree[f"draft-{draft.number}/project.md"] == b""
        tree = container.tree_service()
        assert fake_sidecar.tree == {
            entry.path: tree.read(entry.path).content for entry in tree.manifest()
        }
        listed = client.get(PROJECTS).get_json()["projects"]
        assert [
            (tab["id"], tab["name"], tab["state"], tab["member"]) for tab in listed
        ] == [(body["id"], None, "draft", True)]

    def test_a_caller_without_a_handle_is_a_conflict(
        self, client: FlaskClient, session: Session
    ) -> None:
        _sign_in(client, subject="subject-newcomer")

        response = client.post(PROJECTS)

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot start a new project because you have not chosen your handle yet"
        )
        assert session.scalars(select(Project)).all() == []

    def test_without_editor_it_is_refused(self, client: FlaskClient) -> None:
        _sign_in(client, roles=())

        response = client.post(PROJECTS)

        assert response.status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.post(PROJECTS)

        assert response.status_code == 401


@pytest.mark.usefixtures("person")
class TestJoinProject:
    def test_joining_answers_the_head_with_the_caller_a_member(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        person: User,
    ) -> None:
        container.test_data_service().person("ben", "Ben Example")
        recipes = _make(container, name="Recipe box", members=["ben"])
        _sign_in(client)

        response = client.post(f"{PROJECTS}/{recipes}/membership")

        assert response.status_code == 201
        body = response.get_json()
        assert body["member"] is True
        assert [member["handle"] for member in body["members"]] == ["ben", "ada"]
        assert _open_memberships(session, recipes, person) == 1

    def test_a_member_joining_again_is_a_conflict(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        recipes = _make(container, name="Recipe box")
        _sign_in(client)

        response = client.post(f"{PROJECTS}/{recipes}/membership")

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot join Recipe box because you are a member already"
        )

    def test_an_archived_project_is_a_conflict(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        container.test_data_service().person("ben", "Ben Example")
        recipes = _make(container, name="Recipe box", members=["ben"], archived=True)
        _sign_in(client)

        assert client.post(f"{PROJECTS}/{recipes}/membership").status_code == 409

    def test_a_caller_without_a_handle_is_a_conflict(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        recipes = _make(container, name="Recipe box")
        _sign_in(client, subject="subject-newcomer")

        response = client.post(f"{PROJECTS}/{recipes}/membership")

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot join Recipe box because you have not chosen your handle yet"
        )

    def test_an_unknown_project_is_not_found(self, client: FlaskClient) -> None:
        _sign_in(client)

        response = client.post(f"{PROJECTS}/{uuid.uuid4()}/membership")

        assert response.status_code == 404

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        recipes = _make(container, name="Recipe box")
        _sign_in(client, roles=())

        assert client.post(f"{PROJECTS}/{recipes}/membership").status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.post(f"{PROJECTS}/{uuid.uuid4()}/membership")

        assert response.status_code == 401


@pytest.mark.usefixtures("person")
class TestLeaveProject:
    def test_leaving_answers_the_head_with_the_caller_no_member(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        person: User,
    ) -> None:
        container.test_data_service().person("ben", "Ben Example")
        recipes = _make(container, name="Recipe box", members=["ben", "ada"])
        _sign_in(client)

        response = client.delete(f"{PROJECTS}/{recipes}/membership")

        assert response.status_code == 200
        body = response.get_json()
        assert body["member"] is False
        assert [member["handle"] for member in body["members"]] == ["ben"]
        assert _open_memberships(session, recipes, person) == 0

    def test_a_person_who_is_no_member_leaving_is_a_conflict(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        container.test_data_service().person("ben", "Ben Example")
        recipes = _make(container, name="Recipe box", members=["ben"])
        _sign_in(client)

        response = client.delete(f"{PROJECTS}/{recipes}/membership")

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot leave Recipe box because you are no member"
        )

    def test_an_archived_project_is_a_conflict(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        recipes = _make(container, name="Recipe box", archived=True)
        _sign_in(client)

        assert client.delete(f"{PROJECTS}/{recipes}/membership").status_code == 409

    def test_a_caller_without_a_handle_is_a_conflict(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        recipes = _make(container, name="Recipe box")
        _sign_in(client, subject="subject-newcomer")

        response = client.delete(f"{PROJECTS}/{recipes}/membership")

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot leave Recipe box because you have not chosen your handle yet"
        )

    def test_an_unknown_project_is_not_found(self, client: FlaskClient) -> None:
        _sign_in(client)

        response = client.delete(f"{PROJECTS}/{uuid.uuid4()}/membership")

        assert response.status_code == 404

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        recipes = _make(container, name="Recipe box")
        _sign_in(client, roles=())

        assert client.delete(f"{PROJECTS}/{recipes}/membership").status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.delete(f"{PROJECTS}/{uuid.uuid4()}/membership")

        assert response.status_code == 401
