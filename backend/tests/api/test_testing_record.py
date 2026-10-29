"""/api/testing/{people,environments,projects,items}: the record's states the
UI cannot make (TEST-6), on every stage but prd, behind the API's sign-in
(D027): among them the handbook an open project is born with, an agent's
saves of the project's draft and handbook, Pilot's Done, a work item placed by
repository, started in an environment of Pilot's own the stage's own
controller creates, its worker's registrations and attachments with their
effects, and a pre-ruling pass's questions to a registered document's
writer."""

import base64
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from dependency_injector import providers
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.config import STAGES, Settings, Stage, default_stage
from app.config import Environment as SettingsEnvironment
from app.models import (
    Attachment,
    ClarificationRun,
    Document,
    DocumentVersion,
    Environment,
    Item,
    ItemAttachment,
    Project,
    Turn,
    User,
    Work,
    WriterQuestion,
)
from app.models.reference import ProjectState, SessionState, VersionCause, WorkTrigger
from app.schemas.testing_record import OPENING_WORDS
from app.services.chat_close_service import ChatCloseService
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerClient
from app.services.controller_outage import ControllerOutage
from app.services.environment_service import EnvironmentService
from app.services.fake_controller import CLIENT_NAME
from app.services.relay_service import RelayService
from app.services.session_record_service import read_records
from app.services.session_start_service import SessionStartService
from app.services.start_gate import WorkSlots
from app.services.supervisor import LoopHandle
from app.services.turn_end_read_service import TurnEndReadService
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.chats import ChatWriter, open_chat
from tests.support.fake_controller import ServedFakeController
from tests.support.fake_sidecar import STORE_ENVIRONMENT_ID
from tests.support.supervisor import Supervise

PEOPLE = "/api/testing/people"
ENVIRONMENTS = "/api/testing/environments"
PROJECTS = "/api/testing/projects"

TASKS = [{"id": "build", "title": "Build the camp", "status": "pending"}]

AT = "2026-10-20T09:00:00Z"


def _count(session: Session, model: Any) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def _items_path(project_id: uuid.UUID | str) -> str:
    return f"{PROJECTS}/{project_id}/items"


def _saves_path(item_id: uuid.UUID | str) -> str:
    return f"/api/testing/items/{item_id}/saves"


def _attachments_path(item_id: uuid.UUID | str) -> str:
    return f"/api/testing/items/{item_id}/attachments"


def _draft_attachments_path(project_id: uuid.UUID | str) -> str:
    return f"{PROJECTS}/{project_id}/attachments"


def _turn_ends_path(project_id: uuid.UUID | str) -> str:
    return f"{PROJECTS}/{project_id}/turn-ends"


def _document_saves_path(project_id: uuid.UUID | str, document: str) -> str:
    return f"{PROJECTS}/{project_id}/{document}/saves"


def _done_path(item_id: uuid.UUID | str) -> str:
    return f"/api/testing/items/{item_id}/done"


def _work_path(project_id: uuid.UUID | str) -> str:
    return f"{PROJECTS}/{project_id}/work"


def _registrations_path(item_id: uuid.UUID | str) -> str:
    return f"/api/testing/items/{item_id}/registrations"


def _worker_attachments_path(item_id: uuid.UUID | str) -> str:
    return f"/api/testing/items/{item_id}/worker-attachments"


def _writer_questions_path(item_id: uuid.UUID | str) -> str:
    return f"/api/testing/items/{item_id}/writer-questions"


def _clarification_path(item_id: uuid.UUID | str) -> str:
    return f"/api/testing/items/{item_id}/clarification"


def _chat_answers_path(project_id: uuid.UUID | str) -> str:
    return f"/api/testing/projects/{project_id}/chat/answers"


WORK_REPO = "example/Camp"

CUT_OVER = """# The cut-over

```action id=A1
answer: Pilot does it
by: agent
at: 2026-10-20T09:00:00Z
```

```decision id=D1
options:
  - Dome
  - Tunnel
```
"""

WORK = {
    "repo": WORK_REPO,
    "title": "Building the camp",
    "brief": "Build the camp.",
    "cwd": "/work/Camp",
}


def _file(filename: str, data: bytes, **fields: Any) -> dict[str, Any]:
    return {
        "title": "Sketch",
        "filename": filename,
        "content_type": "text/markdown",
        "content": base64.b64encode(data).decode(),
        **fields,
    }


def _make(client: FlaskClient, **spec: Any) -> str:
    spec.setdefault("members", ["ada"])
    response = client.post(PROJECTS, json=spec)
    assert response.status_code == 201, response.get_json()
    project_id: str = response.get_json()["id"]
    return project_id


def _place(client: FlaskClient, project_id: str, kind: str, text: str) -> str:
    response = client.post(
        _items_path(project_id),
        json={"kind": kind, "title": "Which tent?", "text": text},
    )
    assert response.status_code == 201, response.get_json()
    item_id: str = response.get_json()["id"]
    return item_id


def _timeline(client: FlaskClient, project_id: str) -> list[dict[str, Any]]:
    response = client.get(f"/api/projects/{project_id}/timeline")
    assert response.status_code == 200, response.get_json()
    items: list[dict[str, Any]] = response.get_json()["items"]
    return items


def _timeline_item(
    client: FlaskClient, project_id: str, item_id: str
) -> dict[str, Any]:
    return next(item for item in _timeline(client, project_id) if item["id"] == item_id)


def _within(actual: Any, expected: Any) -> bool:
    """Whether `actual` holds `expected`: a mapping's keys that `expected`
    names, compared the same way, and anything else equal."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _within(actual[key], value)
            for key, value in expected.items()
        )
    return bool(actual == expected)


@pytest.fixture
def ben(container: ServiceContainer) -> User:
    return container.test_data_service().person("ben", "Ben Example")


class TestCreatePerson:
    def test_a_person_with_the_next_slot(
        self, client: FlaskClient, person: User
    ) -> None:
        response = client.post(PEOPLE, json={"handle": "ben", "name": "Ben Example"})

        assert response.status_code == 201
        assert response.get_json() == {
            "handle": "ben",
            "name": "Ben Example",
            "avatar_slot": 2,
        }

    def test_without_a_name_the_handle_is_the_name(self, client: FlaskClient) -> None:
        response = client.post(PEOPLE, json={"handle": "ben"})

        assert response.get_json()["name"] == "ben"

    def test_a_handle_out_of_the_pattern_is_refused(self, client: FlaskClient) -> None:
        response = client.post(PEOPLE, json={"handle": "Ben"})

        assert response.status_code == 400
        assert response.get_json()["error"] == (
            "Cannot choose the handle 'Ben' because a handle holds only lower-case "
            "letters, digits and hyphens"
        )

    def test_a_request_without_a_handle_is_refused(self, client: FlaskClient) -> None:
        assert client.post(PEOPLE, json={"name": "Ben"}).status_code == 400

    def test_a_handle_taken_is_refused(self, client: FlaskClient, person: User) -> None:
        response = client.post(PEOPLE, json={"handle": "ada"})

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot choose the handle 'ada' because another person has it"
        )


class TestCreateEnvironment:
    def test_an_environment(self, client: FlaskClient, session: Session) -> None:
        response = client.post(
            ENVIRONMENTS, json={"id": "example-env-2", "name": "Example-2"}
        )

        assert response.status_code == 201
        assert response.get_json() == {"id": "example-env-2", "name": "Example-2"}
        assert session.get_one(Environment, "example-env-2").name == "Example-2"

    def test_a_request_without_a_name_is_refused(self, client: FlaskClient) -> None:
        assert (
            client.post(ENVIRONMENTS, json={"id": "example-env-2"}).status_code == 400
        )

    def test_an_id_taken_is_refused(
        self, client: FlaskClient, environment: Environment
    ) -> None:
        response = client.post(
            ENVIRONMENTS, json={"id": environment.id, "name": "Again"}
        )

        assert response.status_code == 409


@pytest.mark.usefixtures("person")
class TestCreateProject:
    def test_a_project_in_the_standing_given(
        self, client: FlaskClient, session: Session, environment: Environment
    ) -> None:
        response = client.post(
            PROJECTS,
            json={
                "name": "Recipe box",
                "state": "finished",
                "archived": True,
                "members": ["ada"],
                "ticket": "RB-12",
                "repo": "pvginkel/RecipeBox",
                "tasks": [
                    {"id": "scope", "title": "Agree the scope", "status": "done"}
                ],
                "open_items": 1,
                "environment_id": environment.id,
            },
        )

        assert response.status_code == 201
        project = session.get_one(Project, uuid.UUID(response.get_json()["id"]))
        assert (
            project.name,
            project.state_code.value,
            project.archived,
            project.ticket,
            project.repo,
        ) == ("Recipe box", "finished", True, "RB-12", "pvginkel/RecipeBox")
        assert sorted(item.kind_code for item in session.scalars(select(Item))) == [
            "notice",
            "opening",
        ]

    def test_the_defaults_make_an_open_project(
        self, client: FlaskClient, session: Session
    ) -> None:
        response = client.post(PROJECTS, json={"members": ["ada"]})

        project = session.get_one(Project, uuid.UUID(response.get_json()["id"]))
        assert (project.name, project.state_code.value, project.autopilot) == (
            None,
            "open",
            False,
        )

    @pytest.mark.parametrize(
        "spec",
        [
            {},
            {"members": []},
            {"members": ["ada"], "state": "closed"},
            {"members": ["ada"], "open_items": -1},
            {
                "members": ["ada"],
                "tasks": [{"id": "x", "title": "X", "status": "late"}],
            },
            {"members": ["ada"], "state": "finished", "autopilot": True},
            {"members": ["ada"], "ticket": "not a ticket"},
            {"members": ["ada"], "open_items": 1},
        ],
    )
    def test_a_spec_out_of_the_record_is_refused(
        self, client: FlaskClient, session: Session, spec: dict[str, Any]
    ) -> None:
        response = client.post(PROJECTS, json=spec)

        assert response.status_code == 400

    @pytest.mark.parametrize(
        "spec",
        [
            {"members": ["nobody"]},
            {"members": ["ada"], "environment_id": "nowhere"},
        ],
    )
    def test_what_is_not_on_the_record_is_not_found(
        self, client: FlaskClient, spec: dict[str, Any]
    ) -> None:
        assert client.post(PROJECTS, json=spec).status_code == 404

    def test_past_the_draft_it_is_born_with_its_opening_verbatim(
        self, client: FlaskClient, session: Session, ben: User
    ) -> None:
        words = "Let's camp.\n\n```decision id=D1\nnope: 1\n```\n\n~~~ never closed\n"

        project_id = _make(client, name="Camp", members=["ben", "ada"], opening=words)

        opening = session.scalars(
            select(Item).where(Item.project_id == uuid.UUID(project_id))
        ).one()
        assert (
            opening.kind_code,
            opening.title,
            opening.seq,
            opening.created_by_user_id,
            session.get_one(Document, opening.id).published_text,
        ) == ("opening", "Camp", 1, ben.id, words)

    def test_without_words_or_a_name_the_opening_is_the_invented_one(
        self, client: FlaskClient, session: Session
    ) -> None:
        project_id = _make(client)

        opening = session.scalars(
            select(Item).where(Item.project_id == uuid.UUID(project_id))
        ).one()
        assert (
            opening.title,
            session.get_one(Document, opening.id).published_text,
        ) == ("New project", OPENING_WORDS)

    @pytest.mark.parametrize("state", ["draft", "open"])
    def test_it_answers_its_folder_in_the_stores_tree(
        self, client: FlaskClient, session: Session, state: str
    ) -> None:
        response = client.post(PROJECTS, json={"members": ["ada"], "state": state})

        body = response.get_json()
        project = session.get_one(Project, uuid.UUID(body["id"]))
        assert body["folder"] == (
            f"draft-{project.number}" if state == "draft" else project.slug
        )

    def test_a_draft_has_no_opening(
        self, client: FlaskClient, session: Session
    ) -> None:
        _make(client, name="Camp", state="draft", opening="Let's camp.")

        assert _count(session, Item) == 0

    @pytest.mark.parametrize("state", ["open", "finished"])
    def test_past_the_draft_it_is_born_with_its_handbook_empty(
        self, client: FlaskClient, state: str
    ) -> None:
        project_id = _make(client, name="Camp", state=state)

        response = client.get(f"/api/projects/{project_id}/handbook")

        assert (response.status_code, response.get_json()) == (
            200,
            {"title": None, "body": [], "writing": False},
        )

    def test_a_draft_has_no_handbook(self, client: FlaskClient) -> None:
        project_id = _make(client, name="Camp", state="draft")

        assert client.get(f"/api/projects/{project_id}/handbook").status_code == 404

    def test_a_name_whose_draft_has_a_fault_is_refused(
        self, client: FlaskClient
    ) -> None:
        response = client.post(
            PROJECTS,
            json={"members": ["ada"], "name": "Box\n\n```question id=Q1\nnope: 1\n```"},
        )

        assert response.status_code == 409


DECISION = """```decision id=D1
options:
  - Dome: up in five minutes
  - Tunnel
recommend: Dome
```
"""


def _decision(answer_lines: str) -> str:
    return f"""---
title: Which tent?
---

```decision id=D1
options:
  - Dome
  - Tunnel
{answer_lines}```
"""


@pytest.mark.usefixtures("person", "ben")
class TestCreateItem:
    @pytest.mark.parametrize(
        ("kind", "text", "expected"),
        [
            pytest.param(
                "decision",
                DECISION,
                {
                    "kind": "decision",
                    "title": "Which tent?",
                    "body": [
                        {
                            "type": "block",
                            "block": {
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
                                "answer": None,
                            },
                        }
                    ],
                },
                id="a decision with a recommended option",
            ),
            pytest.param(
                "decision",
                "```decision id=D1\nproposal: Take the dome\n```\n",
                {
                    "kind": "decision",
                    "body": [
                        {
                            "type": "block",
                            "block": {"proposal": "Take the dome", "options": []},
                        }
                    ],
                },
                id="a decision with a proposal",
            ),
            pytest.param(
                "decision",
                "```decision id=C1\ntype: confirmation\nproposal: Push the release"
                "\nbecause: auto-pilot-off\n```\n",
                {
                    "kind": "confirmation",
                    "body": [
                        {
                            "type": "block",
                            "block": {
                                "confirmation": True,
                                "proposal": "Push the release",
                                "because": {"code": "auto-pilot-off"},
                            },
                        }
                    ],
                },
                id="a confirmation",
            ),
            pytest.param(
                "question",
                "```question id=Q1\ndefault: The lake\n```\n",
                {
                    "kind": "question",
                    "body": [
                        {
                            "type": "block",
                            "block": {"kind": "question", "default": "The lake"},
                        }
                    ],
                },
                id="a question with a default",
            ),
            pytest.param(
                "action",
                "```action id=A1\noptions:\n  - Works\n  - Doesn't\n```\n",
                {
                    "kind": "action",
                    "body": [
                        {
                            "type": "block",
                            "block": {
                                "kind": "action",
                                "options": [
                                    {
                                        "label": "Works",
                                        "text": None,
                                        "recommended": False,
                                    },
                                    {
                                        "label": "Doesn't",
                                        "text": None,
                                        "recommended": False,
                                    },
                                ],
                            },
                        }
                    ],
                },
                id="an action with options",
            ),
            pytest.param(
                "action",
                "Put the key into OpenBao.\n\n```action id=A1\n```\n",
                {
                    "kind": "action",
                    "body": [
                        {"type": "prose", "markdown": "Put the key into OpenBao."},
                        {"type": "block", "block": {"kind": "action", "options": []}},
                    ],
                },
                id="an action without options",
            ),
            pytest.param(
                "notice",
                "Blue and green.\n",
                {
                    "kind": "notice",
                    "urgent": False,
                    "for_user": None,
                    "done": None,
                    "body": [{"type": "prose", "markdown": "Blue and green."}],
                },
                id="a notice",
            ),
            pytest.param(
                "notice",
                "---\nurgent: true\n---\n\nA storm comes.\n",
                {"kind": "notice", "urgent": True},
                id="an urgent item",
            ),
            pytest.param(
                "notice",
                "---\nfor: ben\n---\n\nYour bike is ready.\n",
                {"for_user": {"kind": "person", "handle": "ben"}},
                id="an item for the second user",
            ),
            pytest.param(
                "decision",
                _decision(f"answer: Dome\nby: agent\nat: {AT}\n"),
                {
                    "body": [
                        {
                            "type": "block",
                            "block": {"answer": "Dome", "by": {"kind": "agent"}},
                        }
                    ]
                },
                id="a block Pilot settled",
            ),
            pytest.param(
                "decision",
                _decision(f"answer: deferred\nto: build\nby: agent\nat: {AT}\n"),
                {
                    "body": [
                        {
                            "type": "block",
                            "block": {
                                "answer": "deferred",
                                "by": {"kind": "agent"},
                                "deferral": {"to": "build", "title": "Build the camp"},
                            },
                        }
                    ]
                },
                id="a block Pilot deferred",
            ),
        ],
    )
    def test_an_item_of_each_kind_reads_on_the_timeline(
        self,
        client: FlaskClient,
        environment: Environment,
        kind: str,
        text: str,
        expected: dict[str, Any],
    ) -> None:
        project_id = _make(
            client,
            name="Camp",
            members=["ada", "ben"],
            tasks=TASKS,
            environment_id=environment.id,
        )

        item_id = _place(client, project_id, kind, text)

        item = _timeline_item(client, project_id, item_id)
        body = item["body"]
        assert _within(
            {**item, "body": dict(enumerate(body))},
            {**expected, "body": dict(enumerate(expected.get("body", [])))},
        ), item
        assert len(body) == len(expected.get("body", body))

    def test_the_item_is_the_sessions_and_takes_its_title(
        self, client: FlaskClient, session: Session, environment: Environment
    ) -> None:
        project_id = _make(client, environment_id=environment.id)

        item_id = _place(client, project_id, "notice", "Blue and green.\n")

        item = session.get_one(Item, uuid.UUID(item_id))
        assert item.created_by_session_id is not None
        assert session.get_one(Document, item.id).published_text == (
            "---\ntitle: Which tent?\n---\nBlue and green.\n"
        )

    @pytest.mark.parametrize(
        "body",
        [
            {"kind": "opening", "title": "Camp", "text": "Hi"},
            {"kind": "work", "title": "Camp", "text": "Hi"},
            {"kind": "notice", "title": "", "text": "Hi"},
            {"kind": "notice", "title": "Camp"},
        ],
    )
    def test_a_body_out_of_the_record_is_invalid(
        self, client: FlaskClient, environment: Environment, body: dict[str, str]
    ) -> None:
        project_id = _make(client, environment_id=environment.id)

        assert client.post(_items_path(project_id), json=body).status_code == 400

    def test_an_unknown_project_is_not_found(self, client: FlaskClient) -> None:
        response = client.post(
            _items_path(uuid.uuid4()),
            json={"kind": "notice", "title": "Camp", "text": "Hi"},
        )

        assert response.status_code == 404

    def test_a_project_without_a_session_conflicts(
        self, client: FlaskClient, session: Session
    ) -> None:
        project_id = _make(client)

        response = client.post(
            _items_path(project_id),
            json={"kind": "notice", "title": "Camp", "text": "Hi"},
        )

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            f"Cannot add an item to project {project_id} because the project has "
            "no session: make it with an environment_id"
        )
        assert _count(session, Item) == 1

    def test_an_item_by_pilot_is_added_by_a_job_of_the_projects_needing_no_session(
        self, client: FlaskClient, session: Session
    ) -> None:
        project_id = _make(client)

        response = client.post(
            _items_path(project_id),
            json={
                "kind": "question",
                "title": "Which lake?",
                "text": "```question id=Q1\n```\n",
                "by_pilot": True,
            },
        )

        assert response.status_code == 201, response.get_json()
        item = session.get_one(Item, uuid.UUID(response.get_json()["id"]))
        added_by = session.get_one(models.Session, item.created_by_session_id)
        assert (added_by.kind_code, added_by.project_id, added_by.state_code) == (
            "job",
            item.project_id,
            SessionState.IDLE,
        )
        assert session.get(Work, added_by.id) is None

    def test_a_text_with_a_fault_conflicts(
        self, client: FlaskClient, session: Session, environment: Environment
    ) -> None:
        project_id = _make(client, environment_id=environment.id)

        response = client.post(
            _items_path(project_id),
            json={
                "kind": "decision",
                "title": "Camp",
                "text": "```decision id=D1\nnope: 1\n```\n",
            },
        )

        assert response.status_code == 409
        assert _count(session, Item) == 1


@pytest.mark.usefixtures("person")
class TestCreateSave:
    def test_a_save_with_a_fault_is_held_and_the_item_a_concept(
        self, client: FlaskClient, environment: Environment
    ) -> None:
        project_id = _make(client, environment_id=environment.id)
        item_id = _place(client, project_id, "notice", "Blue and green.\n")

        response = client.post(_saves_path(item_id), json={"text": "Red.\n"})

        assert response.status_code == 200
        assert response.get_json() == {
            "held": True,
            "faults": [
                {
                    "line": None,
                    "message": "the item has no title: give it `title` in the front "
                    "matter or a first heading",
                }
            ],
        }
        item = _timeline_item(client, project_id, item_id)
        assert (item["concept"], item["body"]) == (
            True,
            [{"type": "prose", "markdown": "Blue and green.", "section": None}],
        )

    def test_a_clean_save_is_published(
        self, client: FlaskClient, environment: Environment
    ) -> None:
        project_id = _make(client, environment_id=environment.id)
        item_id = _place(client, project_id, "notice", "Blue and green.\n")
        client.post(_saves_path(item_id), json={"text": "Red.\n"})

        response = client.post(
            _saves_path(item_id), json={"text": "---\ntitle: Palette\n---\nRed.\n"}
        )

        assert response.get_json() == {"held": False, "faults": []}
        item = _timeline_item(client, project_id, item_id)
        assert (item["concept"], item["title"], item["body"]) == (
            False,
            "Palette",
            [{"type": "prose", "markdown": "Red.", "section": None}],
        )

    def test_a_save_of_the_opening_is_reverted(
        self, client: FlaskClient, environment: Environment
    ) -> None:
        project_id = _make(client, environment_id=environment.id, opening="Let's camp.")
        opening = _timeline(client, project_id)[0]

        response = client.post(_saves_path(opening["id"]), json={"text": "Let's not."})

        body = response.get_json()
        assert (body["held"], len(body["faults"])) == (False, 1)
        assert _timeline(client, project_id)[0]["words"] == "Let's camp."

    def test_a_body_without_a_text_is_invalid(
        self, client: FlaskClient, environment: Environment
    ) -> None:
        project_id = _make(client, environment_id=environment.id)
        item_id = _place(client, project_id, "notice", "Blue and green.\n")

        assert client.post(_saves_path(item_id), json={}).status_code == 400

    def test_an_unknown_item_is_not_found(self, client: FlaskClient) -> None:
        response = client.post(_saves_path(uuid.uuid4()), json={"text": "Red."})

        assert response.status_code == 404

    def test_an_archived_projects_item_is_not_found(
        self, client: FlaskClient, session: Session, environment: Environment
    ) -> None:
        project_id = _make(client, archived=True, environment_id=environment.id)
        opening = session.scalars(
            select(Item).where(Item.project_id == uuid.UUID(project_id))
        ).one()

        response = client.post(_saves_path(opening.id), json={"text": "Red."})

        assert response.status_code == 404

    def test_a_project_without_a_session_conflicts(
        self, client: FlaskClient, session: Session
    ) -> None:
        project_id = _make(client)
        opening = session.scalars(
            select(Item).where(Item.project_id == uuid.UUID(project_id))
        ).one()

        response = client.post(_saves_path(opening.id), json={"text": "Red."})

        assert response.status_code == 409


@pytest.mark.usefixtures("person")
class TestCreateAttachments:
    def test_one_file_hangs_as_the_projects_first_batch_and_streams(
        self, client: FlaskClient, environment: Environment
    ) -> None:
        project_id = _make(client, environment_id=environment.id)
        item_id = _place(client, project_id, "notice", "Blue and green.\n")

        response = client.post(
            _attachments_path(item_id),
            json={"files": [_file("sketch.md", b"# Sketch\n")]},
        )

        assert response.status_code == 201
        body = response.get_json()
        assert (body["batch"], len(body["ids"])) == (1, 1)
        streamed = client.get(f"/api/attachments/{body['ids'][0]}")
        assert (streamed.status_code, streamed.data) == (200, b"# Sketch\n")

    def test_files_of_one_call_share_a_batch_the_next_call_the_next(
        self, client: FlaskClient, session: Session, environment: Environment
    ) -> None:
        project_id = _make(client, environment_id=environment.id)
        item_id = _place(client, project_id, "notice", "Blue and green.\n")

        first = client.post(
            _attachments_path(item_id),
            json={"files": [_file("a.md", b"A"), _file("b.png", b"B")]},
        ).get_json()
        second = client.post(
            _attachments_path(item_id), json={"files": [_file("a.md", b"C")]}
        ).get_json()

        assert (first["batch"], second["batch"]) == (1, 2)
        assert [
            session.get_one(Attachment, uuid.UUID(attachment_id)).filename
            for attachment_id in first["ids"]
        ] == ["a.md", "b.png"]

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({}, id="no files"),
            pytest.param({"files": []}, id="an empty list"),
            pytest.param({"files": [_file("docs/a.md", b"A")]}, id="a slash"),
            pytest.param({"files": [_file(".", b"A")]}, id="dot"),
            pytest.param({"files": [_file("..", b"A")]}, id="dot dot"),
            pytest.param({"files": [_file("", b"A")]}, id="no name"),
            pytest.param({"files": [_file("a\x00.md", b"A")]}, id="a NUL"),
            pytest.param(
                {"files": [_file("a.md", b"A"), _file("a.md", b"B")]},
                id="a name twice",
            ),
            pytest.param({"files": [_file("a.md", b"A", title="")]}, id="no title"),
            pytest.param(
                {"files": [_file("a.md", b"A", content_type="")]}, id="no type"
            ),
            pytest.param(
                {"files": [_file("a.md", b"A", content="QQ")]}, id="unpadded base64"
            ),
            pytest.param(
                {"files": [_file("a.md", b"A", content="!!!!")]}, id="not base64"
            ),
        ],
    )
    def test_a_body_out_of_the_record_is_invalid(
        self,
        client: FlaskClient,
        session: Session,
        environment: Environment,
        body: dict[str, Any],
    ) -> None:
        project_id = _make(client, environment_id=environment.id)
        item_id = _place(client, project_id, "notice", "Blue and green.\n")

        response = client.post(_attachments_path(item_id), json=body)

        assert response.status_code == 400
        assert _count(session, Attachment) == 0

    def test_a_file_of_16_mib_is_taken_and_one_byte_more_refused(
        self, client: FlaskClient, session: Session, environment: Environment
    ) -> None:
        project_id = _make(client, environment_id=environment.id)
        item_id = _place(client, project_id, "notice", "Blue and green.\n")
        cap = 16 * 1024 * 1024

        over = client.post(
            _attachments_path(item_id),
            json={"files": [_file("big.bin", bytes(cap + 1))]},
        )
        at = client.post(
            _attachments_path(item_id), json={"files": [_file("big.bin", bytes(cap))]}
        )

        assert (over.status_code, at.status_code) == (400, 201)
        assert session.scalars(select(Attachment.size)).one() == cap

    def test_an_unknown_item_is_not_found(self, client: FlaskClient) -> None:
        response = client.post(
            _attachments_path(uuid.uuid4()), json={"files": [_file("a.md", b"A")]}
        )

        assert response.status_code == 404

    def test_a_project_without_a_session_conflicts(
        self, client: FlaskClient, session: Session
    ) -> None:
        project_id = _make(client)
        opening = session.scalars(
            select(Item).where(Item.project_id == uuid.UUID(project_id))
        ).one()

        response = client.post(
            _attachments_path(opening.id), json={"files": [_file("a.md", b"A")]}
        )

        assert response.status_code == 409


@pytest.mark.usefixtures("person")
class TestCreateDraftAttachments:
    def test_files_of_a_draft_hang_on_nothing_listed_and_streamed(
        self, client: FlaskClient, session: Session, environment: Environment
    ) -> None:
        draft_id = _make(client, state="draft", environment_id=environment.id)

        response = client.post(
            _draft_attachments_path(draft_id),
            json={"files": [_file("sketch.md", b"# Sketch\n"), _file("b.md", b"B")]},
        )

        assert response.status_code == 201
        body = response.get_json()
        assert (body["batch"], len(body["ids"])) == (1, 2)
        assert _count(session, ItemAttachment) == 0
        timeline = client.get(f"/api/projects/{draft_id}/timeline").get_json()
        assert [
            attachment["filename"] for attachment in timeline["unhung_attachments"]
        ] == ["b.md", "sketch.md"]
        streamed = client.get(f"/api/attachments/{body['ids'][0]}")
        assert (streamed.status_code, streamed.data) == (200, b"# Sketch\n")

    def test_a_project_past_its_draft_conflicts(
        self, client: FlaskClient, session: Session, environment: Environment
    ) -> None:
        project_id = _make(client, environment_id=environment.id)

        response = client.post(
            _draft_attachments_path(project_id), json={"files": [_file("a.md", b"A")]}
        )

        assert response.status_code == 409
        assert _count(session, Attachment) == 0

    def test_an_unknown_project_is_not_found(self, client: FlaskClient) -> None:
        response = client.post(
            _draft_attachments_path(uuid.uuid4()),
            json={"files": [_file("a.md", b"A")]},
        )

        assert response.status_code == 404

    def test_a_body_with_no_file_is_invalid(
        self, client: FlaskClient, environment: Environment
    ) -> None:
        draft_id = _make(client, state="draft", environment_id=environment.id)

        response = client.post(_draft_attachments_path(draft_id), json={"files": []})

        assert response.status_code == 400


@pytest.mark.usefixtures("person")
class TestCreateTurnEnd:
    def test_pilot_writes_no_longer_and_its_change_is_an_edit(
        self, client: FlaskClient, session: Session, environment: Environment
    ) -> None:
        project_id = _make(client, environment_id=environment.id)
        item_id = _place(client, project_id, "notice", "Blue and green.\n")
        client.post(_saves_path(item_id), json={"text": "# Which tent?\n\nRed.\n"})
        saved = _timeline_item(client, project_id, item_id)

        response = client.post(_turn_ends_path(project_id))

        assert (response.status_code, response.data) == (204, b"")
        ended = _timeline_item(client, project_id, item_id)
        turn = session.scalars(
            select(DocumentVersion).where(
                DocumentVersion.document_id == uuid.UUID(item_id),
                DocumentVersion.cause_code == VersionCause.TURN,
            )
        ).one()
        assert (saved["writing"], saved["edited_at"]) == (True, None)
        assert ended["writing"] is False
        assert datetime.fromisoformat(ended["edited_at"]) == turn.created_at

    def test_a_turn_that_saved_nothing_changes_nothing(
        self, client: FlaskClient, environment: Environment
    ) -> None:
        project_id = _make(client, environment_id=environment.id)
        item_id = _place(client, project_id, "notice", "Blue and green.\n")
        before = _timeline_item(client, project_id, item_id)

        response = client.post(_turn_ends_path(project_id))

        assert response.status_code == 204
        assert _timeline_item(client, project_id, item_id) == before

    def test_an_unknown_project_is_not_found(self, client: FlaskClient) -> None:
        response = client.post(_turn_ends_path(uuid.uuid4()))

        assert response.status_code == 404

    def test_a_project_without_a_session_conflicts(self, client: FlaskClient) -> None:
        response = client.post(_turn_ends_path(_make(client)))

        assert response.status_code == 409


@pytest.mark.usefixtures("person")
@pytest.mark.parametrize("document", ["draft", "handbook"])
class TestCreateProjectDocumentSave:
    def test_a_clean_save_is_published_and_pilot_writes_it(
        self, client: FlaskClient, environment: Environment, document: str
    ) -> None:
        project_id = _make(client, name="Camp", environment_id=environment.id)

        response = client.post(
            _document_saves_path(project_id, document),
            json={"text": "# Camp\n\nTwo tents.\n"},
        )

        assert (response.status_code, response.get_json()) == (
            200,
            {"held": False, "faults": []},
        )
        assert client.get(f"/api/projects/{project_id}/{document}").get_json() == {
            "title": "Camp",
            "body": [{"type": "prose", "markdown": "Two tents.", "section": None}],
            "writing": True,
        }

    def test_a_save_with_a_fault_is_held_and_reads_as_last_published(
        self, client: FlaskClient, environment: Environment, document: str
    ) -> None:
        project_id = _make(client, name="Camp", environment_id=environment.id)
        before = client.get(f"/api/projects/{project_id}/{document}").get_json()

        response = client.post(
            _document_saves_path(project_id, document),
            json={"text": "# Camp\n\n```decision id=D1\nnope: 1\n```\n"},
        )

        body = response.get_json()
        assert (response.status_code, body["held"], len(body["faults"])) == (
            200,
            True,
            1,
        )
        after = client.get(f"/api/projects/{project_id}/{document}").get_json()
        assert after == {**before, "writing": True}

    def test_a_body_without_a_text_is_invalid(
        self, client: FlaskClient, environment: Environment, document: str
    ) -> None:
        project_id = _make(client, environment_id=environment.id)

        response = client.post(_document_saves_path(project_id, document), json={})

        assert response.status_code == 400

    def test_an_unknown_project_is_not_found(
        self, client: FlaskClient, document: str
    ) -> None:
        unknown = uuid.uuid4()

        response = client.post(
            _document_saves_path(unknown, document), json={"text": "Red."}
        )

        assert response.status_code == 404
        assert response.get_json()["error"] == f"Project {unknown} was not found"

    def test_an_archived_project_is_not_found(
        self, client: FlaskClient, environment: Environment, document: str
    ) -> None:
        project_id = _make(client, archived=True, environment_id=environment.id)

        response = client.post(
            _document_saves_path(project_id, document), json={"text": "# Camp\n"}
        )

        assert response.status_code == 404

    def test_a_project_without_a_session_conflicts(
        self, client: FlaskClient, document: str
    ) -> None:
        project_id = _make(client)

        response = client.post(
            _document_saves_path(project_id, document), json={"text": "# Camp\n"}
        )

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            f"Cannot save the {document} of project {project_id} because the "
            "project has no session: make it with an environment_id"
        )


@pytest.mark.usefixtures("person")
def test_a_drafts_handbook_save_is_not_found(
    client: FlaskClient, environment: Environment
) -> None:
    project_id = _make(client, state="draft", environment_id=environment.id)

    response = client.post(
        _document_saves_path(project_id, "handbook"), json={"text": "# Camp\n"}
    )

    assert response.status_code == 404
    assert response.get_json()["error"] == (
        f"Handbook of project {project_id} was not found"
    )


SETTLED_WHOLE = """```decision id=D1
proposal: Cook on the fire.
answer: Agree
by: agent
at: 2026-10-20T09:00:00Z
```

```question id=Q1
default: Two nights
answer: deferred
by: agent
at: 2026-10-20T09:01:00Z
to: plan
```
"""
"""A document Pilot settled and deferred whole."""

PILOT = {
    "kind": "agent",
    "handle": "agent",
    "name": "Pilot",
    "initials": "P",
    "avatar_slot": None,
}


@pytest.mark.usefixtures("person")
class TestCreateDone:
    def test_pilot_marks_a_document_it_settled_whole_done_from_the_start(
        self, client: FlaskClient, session: Session, environment: Environment
    ) -> None:
        project_id = _make(client, environment_id=environment.id)
        item_id = _place(client, project_id, "document", SETTLED_WHOLE)

        response = client.post(_done_path(item_id))

        assert (response.status_code, response.data) == (204, b"")
        done = _timeline_item(client, project_id, item_id)["done"]
        assert (done["cause"], done["by"]) == ("settled", PILOT)
        assert session.scalars(
            select(DocumentVersion.cause_code)
            .where(DocumentVersion.document_id == uuid.UUID(item_id))
            .order_by(DocumentVersion.number)
        ).all() == [VersionCause.BORN, VersionCause.DONE]

    def test_a_document_with_a_block_unanswered_conflicts(
        self, client: FlaskClient, environment: Environment
    ) -> None:
        project_id = _make(client, environment_id=environment.id)
        item_id = _place(
            client,
            project_id,
            "document",
            SETTLED_WHOLE.replace(
                "answer: deferred\nby: agent\nat: 2026-10-20T09:01:00Z\nto: plan\n",
                "",
            ),
        )

        response = client.post(_done_path(item_id))

        assert response.status_code == 409
        assert response.get_json()["error"].endswith(
            "Pilot marks done only a document it settled whole, and these blocks "
            "are unanswered: Q1"
        )
        assert _timeline_item(client, project_id, item_id)["done"] is None

    def test_a_done_document_conflicts(
        self, client: FlaskClient, environment: Environment
    ) -> None:
        project_id = _make(client, environment_id=environment.id)
        item_id = _place(client, project_id, "document", SETTLED_WHOLE)
        client.post(_done_path(item_id))

        assert client.post(_done_path(item_id)).status_code == 409

    def test_an_item_that_is_no_document_conflicts(
        self, client: FlaskClient, environment: Environment
    ) -> None:
        project_id = _make(client, environment_id=environment.id)
        item_id = _place(client, project_id, "notice", "Blue and green.\n")

        response = client.post(_done_path(item_id))

        assert response.status_code == 409
        assert response.get_json()["error"].endswith(
            "a notice item is not done by Done"
        )

    def test_an_unknown_item_is_not_found(self, client: FlaskClient) -> None:
        unknown = uuid.uuid4()

        response = client.post(_done_path(unknown))

        assert response.status_code == 404
        assert response.get_json()["error"] == f"Item {unknown} was not found"

    def test_a_project_without_a_session_conflicts(
        self, client: FlaskClient, session: Session
    ) -> None:
        project_id = _make(client)
        opening = session.scalars(
            select(Item).where(Item.project_id == uuid.UUID(project_id))
        ).one()

        response = client.post(_done_path(opening.id))

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            f"Cannot mark item {opening.id} done because the project has no "
            "session: make it with an environment_id"
        )


def _starts(
    container: ServiceContainer, supervise: Supervise, *, controller_configured: bool
) -> SessionStartService:
    """The session starts, on a supervisor of their own whose loops never run."""
    supervisor, _ = supervise(container)
    environments = EnvironmentService(
        container=container,
        supervisor=supervisor,
        stop_after_seconds=1800,
        delete_after_seconds=604800,
    )
    slots = WorkSlots(work_max=3, project_max=3)
    return SessionStartService(
        container=container,
        supervisor=supervisor,
        session_streams=container.session_stream_service(),
        environment_service=environments,
        relay_service=RelayService(
            container=container,
            supervisor=supervisor,
            session_streams=container.session_stream_service(),
            environment_service=environments,
            work_slots=slots,
            pilot_server=container.pilot_server(),
            turn_end_reads=TurnEndReadService(
                container=container,
                supervisor=supervisor,
                session_streams=container.session_stream_service(),
            ),
            chat_closes=ChatCloseService(
                container=container,
                supervisor=supervisor,
                session_streams=container.session_stream_service(),
                close_after_seconds=3300,
            ),
        ),
        controller_outage=container.controller_outage(),
        work_slots=slots,
        pilot_server=container.pilot_server(),
        controller_configured=controller_configured,
        store_environment_id=STORE_ENVIRONMENT_ID,
    )


@pytest.mark.usefixtures("person")
class TestCreateWork:
    @pytest.fixture(autouse=True)
    def _no_callbacks(self) -> Iterator[None]:
        clear_after_commit_callbacks()
        yield
        clear_after_commit_callbacks()

    @pytest.fixture
    def served(
        self,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
    ) -> Iterator[None]:
        """The route on the fake, which has no environment: the start creates
        its own."""
        container.session_start_service.override(
            providers.Object(_starts(container, supervise, controller_configured=True))
        )
        try:
            yield
        finally:
            container.session_start_service.reset_last_overriding()

    @staticmethod
    def _work_items(session: Session) -> list[Item]:
        return list(session.scalars(select(Item).where(Item.kind_code == "work")))

    def test_it_places_a_work_item_by_repository_and_starts_it(
        self,
        client: FlaskClient,
        served: None,
        session: Session,
        fake_controller: ServedFakeController,
    ) -> None:
        project_id = _make(client, name="Camp", tasks=TASKS)

        response = client.post(_work_path(project_id), json={**WORK, "step": "build"})

        assert response.status_code == 201, response.get_json()
        work_id = response.get_json()["id"]
        item = _timeline_item(client, project_id, work_id)
        assert _within(
            item,
            {
                "kind": "work",
                "form": "work",
                "title": "Building the camp",
                "step": {"id": "build", "title": "Build the camp"},
                "done": None,
            },
        ), item
        run = session.get_one(models.Session, uuid.UUID(work_id))
        # Its environment is the start's to provide, once the request commits.
        assert (run.state_code, run.environment_id, run.kind_code, run.cwd) == (
            SessionState.STARTING,
            None,
            "work",
            "/work/Camp",
        )
        work = session.get_one(Work, run.id)
        assert (work.repo, work.autopilot) == (WORK_REPO, False)
        assert item["work"]["environment"] is None
        assert fake_controller.calls == []

    def test_its_start_creates_an_environment_of_the_repository(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        served: None,
        session: Session,
        fake_controller: ServedFakeController,
    ) -> None:
        project_id = _make(client, name="Camp")
        response = client.post(_work_path(project_id), json=WORK)
        assert response.status_code == 201, response.get_json()
        work_id = uuid.UUID(response.get_json()["id"])
        clear_after_commit_callbacks()

        container.session_start_service().run(work_id, LoopHandle(f"start:{work_id}"))

        run = session.get_one(models.Session, work_id, populate_existing=True)
        assert run.state_code == SessionState.RUNNING
        assert run.environment_id is not None
        created = fake_controller.environment(run.environment_id)
        slug = session.get_one(Project, uuid.UUID(project_id)).slug
        assert (created.repo, created.managed_by, created.name) == (
            WORK_REPO,
            CLIENT_NAME,
            slug,
        )
        work = _timeline_item(client, project_id, str(work_id))["work"]
        assert work["environment"] == {"id": run.environment_id, "name": slug}

    def test_with_the_controller_unreachable_it_places_the_work_item_held(
        self,
        client: FlaskClient,
        served: None,
        session: Session,
        controller_outage: ControllerOutage,
        fake_controller: ServedFakeController,
    ) -> None:
        project_id = _make(client)
        controller_outage.call_unanswered()

        response = client.post(_work_path(project_id), json=WORK)

        assert response.status_code == 201, response.get_json()
        work_id = response.get_json()["id"]
        run = session.get_one(models.Session, uuid.UUID(work_id))
        assert (run.state_code, run.environment_id) == (SessionState.HELD, None)
        work = _timeline_item(client, project_id, work_id)["work"]
        assert (work["state"], work["held_reason"], work["environment"]) == (
            "held",
            "controller_unreachable",
            None,
        )
        assert fake_controller.calls == []

    def test_in_a_paused_project_it_places_the_work_item_held(
        self, client: FlaskClient, served: None, session: Session
    ) -> None:
        project_id = _make(client)
        session.get_one(Project, uuid.UUID(project_id)).paused = True
        session.flush()

        response = client.post(_work_path(project_id), json=WORK)

        assert response.status_code == 201, response.get_json()
        work = _timeline_item(client, project_id, response.get_json()["id"])["work"]
        assert (work["state"], work["held_reason"]) == ("held", "paused")

    def test_with_no_slot_free_it_places_the_work_item_held(
        self,
        client: FlaskClient,
        served: None,
        session: Session,
        fake_controller: ServedFakeController,
    ) -> None:
        project_id = _make(client)
        session.add_all(
            models.Session(
                project_id=uuid.UUID(project_id),
                kind_code="work",
                cwd="/work/Example",
                token_hash=uuid.uuid4().hex,
                state_code=SessionState.RUNNING,
            )
            for _ in range(3)
        )
        session.flush()

        response = client.post(_work_path(project_id), json=WORK)

        assert response.status_code == 201, response.get_json()
        work = _timeline_item(client, project_id, response.get_json()["id"])["work"]
        assert (work["state"], work["held_reason"], work["held_running"]) == (
            "held",
            "slot",
            3,
        )
        assert fake_controller.calls == []

    def test_without_a_step_it_works_on_none(
        self, client: FlaskClient, served: None, session: Session
    ) -> None:
        project_id = _make(client)

        response = client.post(_work_path(project_id), json=WORK)

        assert response.status_code == 201, response.get_json()
        (item,) = self._work_items(session)
        assert item.plan_task_id is None

    @pytest.mark.parametrize(
        "changes",
        [{"title": ""}, {"brief": ""}, {"cwd": ""}, {"repo": ""}],
        ids=["no-title", "no-brief", "no-cwd", "no-repository"],
    )
    def test_a_body_out_of_the_record_is_invalid(
        self,
        client: FlaskClient,
        served: None,
        session: Session,
        changes: dict[str, str],
    ) -> None:
        project_id = _make(client)

        response = client.post(_work_path(project_id), json={**WORK, **changes})

        assert response.status_code == 400
        assert self._work_items(session) == []

    @staticmethod
    def _cut_over(
        session: Session, container: ServiceContainer, project_id: str
    ) -> uuid.UUID:
        """A document a worker of the project registered, read at its run's
        end: an action Pilot claimed, and a decision."""
        project = session.get_one(Project, uuid.UUID(project_id))
        session.add(Environment(id="example-camp-1", name="Camp-1", exempt=False))
        worker = models.Session(
            project_id=project.id,
            environment_id="example-camp-1",
            kind_code="work",
            cwd="/work/Camp",
            token_hash="9" * 64,
            state_code=SessionState.IDLE,
        )
        session.add(worker)
        session.flush()
        documents = container.document_service()
        item = documents.register(project, worker, "/work/Camp/cut-over.md").item
        documents.publish_read(session.get_one(Document, item.id), CUT_OVER, worker.id)
        return item.id

    def test_it_names_the_claimed_actions_the_work_item_does(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        served: None,
        session: Session,
    ) -> None:
        project_id = _make(client)
        document_id = self._cut_over(session, container, project_id)

        response = client.post(
            _work_path(project_id), json={**WORK, "claims": [f"{document_id}/A1"]}
        )

        assert response.status_code == 201, response.get_json()
        blocks = [
            part["block"]
            for part in _timeline_item(client, project_id, str(document_id))["body"]
            if part["type"] == "block"
        ]
        assert [block["claim"] for block in blocks] == [
            {"work": {"id": response.get_json()["id"], "title": WORK["title"]}},
            None,
        ]

    @pytest.mark.parametrize(
        ("claim", "status"),
        [("D1", 409), ("A9", 404), ("A1 A2", 400)],
        ids=["no-action", "no-block", "no-block-id"],
    )
    def test_a_claim_the_record_refuses_places_nothing(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        served: None,
        session: Session,
        claim: str,
        status: int,
    ) -> None:
        project_id = _make(client)
        document_id = self._cut_over(session, container, project_id)

        response = client.post(
            _work_path(project_id),
            json={**WORK, "claims": [f"{document_id}/{claim}"]},
        )

        assert response.status_code == status
        assert self._work_items(session) == []

    def test_an_unknown_project_is_not_found(
        self, client: FlaskClient, served: None, session: Session
    ) -> None:
        response = client.post(_work_path(uuid.uuid4()), json=WORK)

        assert response.status_code == 404
        assert session.scalars(select(models.Session)).all() == []

    def test_a_step_not_in_the_plan_is_not_found(
        self, client: FlaskClient, served: None, session: Session
    ) -> None:
        project_id = _make(client, tasks=TASKS)

        response = client.post(_work_path(project_id), json={**WORK, "step": "cook"})

        assert response.status_code == 404
        assert response.get_json()["error"] == (
            f"Plan task {project_id}/cook was not found"
        )
        assert self._work_items(session) == []
        assert session.scalars(select(models.Session)).all() == []

    def test_an_environment_id_is_no_placement(
        self, client: FlaskClient, served: None, session: Session
    ) -> None:
        project_id = _make(client)
        body = {key: value for key, value in WORK.items() if key != "repo"}

        response = client.post(
            _work_path(project_id), json={**body, "environment_id": "example-env-1"}
        )

        assert response.status_code == 400
        assert self._work_items(session) == []

    @pytest.mark.parametrize(
        ("standing", "refusal"),
        [({"state": "finished"}, "finished"), ({"archived": True}, "archived")],
    )
    def test_a_finished_or_archived_project_is_409(
        self,
        client: FlaskClient,
        served: None,
        session: Session,
        standing: dict[str, Any],
        refusal: str,
    ) -> None:
        project_id = _make(client, **standing)

        response = client.post(_work_path(project_id), json=WORK)

        assert response.status_code == 409
        assert f"its project is {refusal}" in response.get_json()["error"]
        assert self._work_items(session) == []

    def test_no_controller_configured_is_409(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        supervise: Supervise,
        session: Session,
    ) -> None:
        project_id = _make(client)
        container.session_start_service.override(
            providers.Object(_starts(container, supervise, controller_configured=False))
        )
        try:
            response = client.post(_work_path(project_id), json=WORK)
        finally:
            container.session_start_service.reset_last_overriding()

        assert response.status_code == 409
        assert self._work_items(session) == []


# A fixed id that names no row: it lands in the test ids, which every xdist
# worker must collect alike.
NO_ROW = uuid.UUID("00000000-0000-4000-8000-000000000000")

ENDPOINTS = [
    (PEOPLE, {"handle": "ben"}),
    (ENVIRONMENTS, {"id": "example-env-2", "name": "Example-2"}),
    (PROJECTS, {"members": ["ada"]}),
    (_items_path(NO_ROW), {"kind": "notice", "title": "Camp", "text": "Hi"}),
    (_saves_path(NO_ROW), {"text": "Hi"}),
    (_attachments_path(NO_ROW), {"files": [_file("a.md", b"Hi")]}),
    (_draft_attachments_path(NO_ROW), {"files": [_file("a.md", b"Hi")]}),
    (_turn_ends_path(NO_ROW), {}),
    (_document_saves_path(NO_ROW, "draft"), {"text": "Hi"}),
    (_document_saves_path(NO_ROW, "handbook"), {"text": "Hi"}),
    (_done_path(NO_ROW), {}),
    (_work_path(NO_ROW), WORK),
    (_registrations_path(NO_ROW), {"path": "/work/Camp/notes.md"}),
    (_worker_attachments_path(NO_ROW), {"path": "/work/Camp/notes.md"}),
    (
        _writer_questions_path(NO_ROW),
        {"questions": [{"block": "Q1", "question": "Which?"}]},
    ),
    (_clarification_path(NO_ROW), {"reply": "Lake Ilm."}),
    (
        _chat_answers_path(NO_ROW),
        {"block": f"{NO_ROW}/D1", "value": "Yes", "for": "ada"},
    ),
]


REGISTERED = "/work/Camp/docs/refinement.md"


@pytest.mark.usefixtures("person")
class TestCreateRegistration:
    @pytest.fixture
    def work_item(
        self,
        session: Session,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> models.Session:
        """A work item's Session running in an environment the fake holds,
        where its worker wrote the document's file."""
        fake_controller.add_environment(environment.id, status="running")
        fake_controller.put_file(
            environment.id, REGISTERED, b"# Two sites\n\n```question id=Q1\n```\n"
        )
        run = models.Session(
            project_id=project.id,
            environment_id=environment.id,
            kind_code="work",
            cwd="/work/Camp",
            token_hash="2" * 64,
            state_code=SessionState.RUNNING,
        )
        session.add(run)
        session.flush()
        container.record_service().place_work(
            project, run, "Building the camp", repo=WORK_REPO
        )
        return run

    def test_it_registers_the_file_as_the_sessions_worker_does(
        self, client: FlaskClient, session: Session, work_item: models.Session
    ) -> None:
        response = client.post(
            _registrations_path(work_item.id), json={"path": REGISTERED}
        )

        assert response.status_code == 201
        item_id = uuid.UUID(response.get_json()["id"])
        document = session.get_one(Document, item_id)
        assert (
            document.source_environment_id,
            document.source_path,
            document.published_text,
        ) == (work_item.environment_id, REGISTERED, None)
        assert session.get_one(Item, item_id).created_by_session_id == work_item.id
        again = client.post(
            _registrations_path(work_item.id), json={"path": REGISTERED}
        )
        assert (again.status_code, again.get_json()) == (200, {"id": str(item_id)})

    def test_a_tool_use_id_names_the_effect_in_the_turn_in_flight(
        self, client: FlaskClient, session: Session, work_item: models.Session
    ) -> None:
        _turn_in_flight(session, work_item)

        response = client.post(
            _registrations_path(work_item.id),
            json={"path": REGISTERED, "tool_use_id": "toolu_01"},
        )

        assert response.status_code == 201
        [record] = read_records(session, work_item.id, limit=10)
        assert record.record.payload["toolUseId"] == "toolu_01"
        assert record.record.payload["effect"]["verb"] == "Registered"

    def test_an_item_that_is_no_work_item_is_not_found(
        self, client: FlaskClient, item: Item
    ) -> None:
        for item_id in (item.id, uuid.uuid4()):
            response = client.post(
                _registrations_path(item_id), json={"path": REGISTERED}
            )

            assert response.status_code == 404

    def test_a_work_item_whose_start_gave_it_no_environment_conflicts(
        self, client: FlaskClient, session: Session, work_item: models.Session
    ) -> None:
        work_item.environment_id = None
        session.flush()

        response = client.post(
            _registrations_path(work_item.id), json={"path": REGISTERED}
        )

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            f"Cannot register document {REGISTERED} because work item"
            f" {work_item.id} has no environment yet"
        )

    def test_a_file_that_cannot_be_registered_conflicts_with_the_reason(
        self, client: FlaskClient, work_item: models.Session
    ) -> None:
        path = "/work/Camp/docs/missing.md"

        response = client.post(_registrations_path(work_item.id), json={"path": path})

        assert response.status_code == 409
        assert response.get_json()["error"].startswith(
            f"Cannot register document {path} because the controller answered 404"
        )

    def test_an_empty_path_is_invalid(
        self, client: FlaskClient, work_item: models.Session
    ) -> None:
        response = client.post(_registrations_path(work_item.id), json={"path": ""})

        assert response.status_code == 400

    def test_a_controller_that_does_not_answer_is_502(
        self,
        client: FlaskClient,
        fake_controller: ServedFakeController,
        work_item: models.Session,
    ) -> None:
        fake_controller.outage()

        response = client.post(
            _registrations_path(work_item.id), json={"path": REGISTERED}
        )

        assert response.status_code == 502


def _turn_in_flight(session: Session, run: models.Session) -> Turn:
    """The work item's brief, sent and not ended."""
    turn = Turn(
        session_id=run.id,
        seq=1,
        message="Build the camp.",
        started_at=datetime.now(UTC),
    )
    session.add(turn)
    session.flush()
    return turn


SURVEY = "/work/Camp/docs/survey"


@pytest.mark.usefixtures("person")
class TestCreateWorkerAttachment:
    @pytest.fixture
    def work_item(
        self,
        session: Session,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> models.Session:
        """A work item's Session running in an environment the fake holds,
        its brief in flight, where its worker wrote a folder of two files."""
        fake_controller.add_environment(environment.id, status="running")
        fake_controller.put_file(environment.id, f"{SURVEY}/sites.md", b"# Sites\n")
        fake_controller.put_file(environment.id, f"{SURVEY}/costs.csv", b"a,b\n")
        run = models.Session(
            project_id=project.id,
            environment_id=environment.id,
            kind_code="work",
            cwd="/work/Camp",
            token_hash="2" * 64,
            state_code=SessionState.RUNNING,
        )
        session.add(run)
        session.flush()
        container.record_service().place_work(
            project, run, "Building the camp", repo=WORK_REPO
        )
        _turn_in_flight(session, run)
        return run

    def test_it_attaches_the_folder_as_the_sessions_worker_does_with_its_effect(
        self, client: FlaskClient, session: Session, work_item: models.Session
    ) -> None:
        response = client.post(
            _worker_attachments_path(work_item.id),
            json={"path": SURVEY, "tool_use_id": "toolu_01"},
        )

        assert response.status_code == 201
        ids = [uuid.UUID(id_) for id_ in response.get_json()["ids"]]
        attachments = [session.get_one(Attachment, id_) for id_ in ids]
        assert [attachment.filename for attachment in attachments] == [
            "costs.csv",
            "sites.md",
        ]
        assert (
            session.scalars(
                select(ItemAttachment.item_id).where(
                    ItemAttachment.attachment_id.in_(ids)
                )
            ).all()
            == [work_item.id] * 2
        )
        [record] = read_records(session, work_item.id, limit=10)
        assert record.record.payload == {
            "type": "effect",
            "toolUseId": "toolu_01",
            "effect": {
                "verb": "Attached",
                "label": "survey, 2 files",
                "itemId": str(work_item.id),
            },
        }

    def test_to_names_the_item_it_hangs_on(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        project: Project,
        work_item: models.Session,
    ) -> None:
        notice = container.document_service().bear_item(
            project, "notice", "Sites", work_item, "# Sites\n"
        )

        response = client.post(
            _worker_attachments_path(work_item.id),
            json={"path": f"{SURVEY}/sites.md", "to": str(notice.id)},
        )

        assert response.status_code == 201
        [id_] = response.get_json()["ids"]
        assert session.scalars(
            select(ItemAttachment.item_id).where(
                ItemAttachment.attachment_id == uuid.UUID(id_)
            )
        ).all() == [notice.id]

    def test_an_item_that_is_no_work_item_is_not_found(
        self, client: FlaskClient, item: Item
    ) -> None:
        for item_id in (item.id, uuid.uuid4()):
            response = client.post(
                _worker_attachments_path(item_id), json={"path": SURVEY}
            )

            assert response.status_code == 404

    def test_a_path_that_cannot_be_copied_conflicts_with_the_reason(
        self, client: FlaskClient, work_item: models.Session
    ) -> None:
        path = "/work/Camp/docs/missing.md"

        response = client.post(
            _worker_attachments_path(work_item.id), json={"path": path}
        )

        assert response.status_code == 409
        assert response.get_json()["error"].startswith(f"Cannot attach {path}")

    def test_an_empty_path_is_invalid(
        self, client: FlaskClient, work_item: models.Session
    ) -> None:
        response = client.post(
            _worker_attachments_path(work_item.id), json={"path": ""}
        )

        assert response.status_code == 400


QUESTIONED = "```question id=Q1\n```\n\n```question id=Q2\n```\n"


@pytest.mark.usefixtures("person")
class TestCreateWriterQuestions:
    @pytest.fixture
    def document(
        self,
        session: Session,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> Item:
        """A document a worker registered, read at its run's end, committed
        so that a refused call's rollback keeps it."""
        run = models.Session(
            project_id=project.id,
            environment_id=environment.id,
            kind_code="work",
            cwd="/work/Camp",
            token_hash="2" * 64,
            state_code=SessionState.IDLE,
        )
        session.add(run)
        session.flush()
        documents = container.document_service()
        item = documents.register(project, run, REGISTERED).item
        documents.publish_read(session.get_one(Document, item.id), QUESTIONED, run.id)
        session.commit()
        return item

    def test_a_passs_questions_are_asked_in_one_job_turn_and_its_line_says_so(
        self,
        client: FlaskClient,
        session: Session,
        project: Project,
        document: Item,
    ) -> None:
        response = client.post(
            _writer_questions_path(document.id),
            json={
                "questions": [
                    {"block": "Q2", "question": "Which lake?"},
                    {"block": "Q1", "question": "Which site?"},
                ]
            },
        )

        assert response.status_code == 201
        assert response.get_json() == {"blocks": ["Q1", "Q2"]}
        [job] = session.scalars(
            select(models.Session).where(models.Session.kind_code == "job")
        )
        assert (job.project_id, job.state_code) == (project.id, SessionState.IDLE)
        [turn] = session.scalars(select(Turn).where(Turn.session_id == job.id))
        assert turn.ended_at is not None
        assert [
            (question.turn_id, question.question)
            for question in session.scalars(
                select(WriterQuestion).order_by(WriterQuestion.id)
            )
        ] == [(turn.id, "Which lake?"), (turn.id, "Which site?")]
        line = _timeline_item(client, str(project.id), str(document.id))
        assert line["asked_writer_about"] == ["Q1", "Q2"]

    def test_an_unknown_item_or_block_is_not_found(
        self, client: FlaskClient, document: Item
    ) -> None:
        unknown = client.post(
            _writer_questions_path(uuid.uuid4()),
            json={"questions": [{"block": "Q1", "question": "Which?"}]},
        )
        no_block = client.post(
            _writer_questions_path(document.id),
            json={"questions": [{"block": "Q9", "question": "Which?"}]},
        )

        assert (unknown.status_code, no_block.status_code) == (404, 404)

    def test_a_block_asked_about_already_conflicts(
        self, client: FlaskClient, session: Session, document: Item
    ) -> None:
        body = {"questions": [{"block": "Q1", "question": "Which?"}]}
        assert (
            client.post(_writer_questions_path(document.id), json=body).status_code
            == 201
        )

        response = client.post(_writer_questions_path(document.id), json=body)

        assert response.status_code == 409
        assert response.get_json()["error"].endswith(
            "because its writer was asked about block Q1 already"
        )

    @pytest.mark.parametrize(
        "body",
        [
            {"questions": []},
            {"questions": [{"block": "", "question": "Which?"}]},
            {"questions": [{"block": "Q1", "question": ""}]},
        ],
        ids=["no-question", "an-empty-block", "an-empty-question"],
    )
    def test_a_body_that_is_not_questions_is_invalid(
        self, client: FlaskClient, document: Item, body: dict[str, Any]
    ) -> None:
        response = client.post(_writer_questions_path(document.id), json=body)

        assert response.status_code == 400


@pytest.mark.usefixtures("person")
class TestCreateClarification:
    @pytest.fixture
    def document(
        self,
        session: Session,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> Item:
        """A document a worker's run registered, read at its run's end,
        committed so that a refused call's rollback keeps it."""
        run = models.Session(
            project_id=project.id,
            environment_id=environment.id,
            kind_code="work",
            conversation_id="conv-camp",
            cwd="/work/Camp",
            token_hash="2" * 64,
            state_code=SessionState.IDLE,
        )
        session.add(run)
        session.flush()
        container.record_service().place_work(project, run, "Writing the refinement")
        documents = container.document_service()
        item = documents.register(project, run, REGISTERED).item
        documents.publish_read(session.get_one(Document, item.id), QUESTIONED, run.id)
        session.commit()
        return item

    def test_the_reply_is_the_documents_clarification_split_per_block(
        self,
        client: FlaskClient,
        session: Session,
        project: Project,
        document: Item,
    ) -> None:
        client.post(
            _writer_questions_path(document.id),
            json={
                "questions": [
                    {"block": "Q2", "question": "Which lake?"},
                    {"block": "Q1", "question": "Which site?"},
                ]
            },
        )

        response = client.post(
            _clarification_path(document.id),
            json={"reply": "## Q1\nThe north shore.\n\n## Q2\nLake Ilm."},
        )

        assert response.status_code == 201
        run_id = uuid.UUID(response.get_json()["id"])
        run = session.get_one(models.Session, run_id)
        assert (run.kind_code, run.conversation_id) == ("work", "conv-camp")
        assert session.get_one(Work, run_id).trigger_code is None
        [asking] = session.scalars(
            select(Work).where(Work.trigger_code == WorkTrigger.WORKER_TURN_ENDED)
        )
        assert asking.trigger_item_id == document.created_by_session_id
        line = _timeline_item(client, str(project.id), str(document.id))
        [clarification] = line["clarifications"]
        assert [
            (each["block"], each["reply"]) for each in clarification["questions"]
        ] == [("Q1", "The north shore."), ("Q2", "Lake Ilm.")]
        assert clarification["split"] is True
        run_line = _timeline_item(client, str(project.id), str(run_id))
        assert run_line["title"] == f"Clarify {REGISTERED}"
        assert run_line["done"]["cause"] == "turn_ended"

    def test_an_unknown_item_is_not_found(self, client: FlaskClient) -> None:
        response = client.post(
            _clarification_path(uuid.uuid4()), json={"reply": "Lake Ilm."}
        )

        assert response.status_code == 404

    @pytest.mark.usefixtures("controller_client", "fake_controller")
    def test_with_no_reply_the_run_is_placed_to_start_through_the_gate(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        supervise: Supervise,
        session: Session,
        project: Project,
        document: Item,
    ) -> None:
        clear_after_commit_callbacks()
        container.session_start_service.override(
            providers.Object(_starts(container, supervise, controller_configured=True))
        )
        try:
            client.post(
                _writer_questions_path(document.id),
                json={"questions": [{"block": "Q1", "question": "Which site?"}]},
            )

            response = client.post(_clarification_path(document.id), json={})
            again = client.post(_clarification_path(document.id), json={})
        finally:
            container.session_start_service.reset_last_overriding()
            clear_after_commit_callbacks()

        assert response.status_code == 201
        run_id = uuid.UUID(response.get_json()["id"])
        run = session.get_one(models.Session, run_id)
        assert (run.conversation_id, run.state_code) == (
            "conv-camp",
            SessionState.STARTING,
        )
        clarification = session.get_one(ClarificationRun, run_id)
        assert (clarification.reply, clarification.replied_at) == (None, None)
        run_line = _timeline_item(client, str(project.id), str(run_id))
        assert (run_line["title"], run_line["done"]) == (f"Clarify {REGISTERED}", None)
        [line] = _timeline_item(client, str(project.id), str(document.id))[
            "clarifications"
        ]
        assert (line["reply"], [each["block"] for each in line["questions"]]) == (
            None,
            ["Q1"],
        )
        assert again.status_code == 409

    def test_a_document_asked_nothing_or_replied_to_already_conflicts(
        self, client: FlaskClient, document: Item
    ) -> None:
        asked_nothing = client.post(
            _clarification_path(document.id), json={"reply": "Lake Ilm."}
        )
        client.post(
            _writer_questions_path(document.id),
            json={"questions": [{"block": "Q1", "question": "Which site?"}]},
        )
        assert (
            client.post(
                _clarification_path(document.id), json={"reply": "North."}
            ).status_code
            == 201
        )

        again = client.post(_clarification_path(document.id), json={"reply": "South."})

        assert (asked_nothing.status_code, again.status_code) == (409, 409)
        assert asked_nothing.get_json()["error"].endswith(
            "because its writer was asked nothing"
        )
        assert again.get_json()["error"].endswith(
            "because the pass that asked has its clarification run already"
        )

    @pytest.mark.parametrize(
        "body", [{"reply": ""}, {"reply": 7}], ids=["an-empty-one", "no-text"]
    )
    def test_a_reply_that_is_no_text_is_invalid(
        self, client: FlaskClient, document: Item, body: dict[str, Any]
    ) -> None:
        response = client.post(_clarification_path(document.id), json=body)

        assert response.status_code == 400


CHAT_DECISION = """```decision id=D1
options:
  - Dome
  - Tunnel
```
"""


@pytest.mark.usefixtures("person")
class TestCreateChatAnswer:
    @pytest.fixture
    def placed(
        self, client: FlaskClient, session: Session, environment: Environment
    ) -> tuple[str, str]:
        """A project with a decision on its timeline, and the item's id."""
        project_id = _make(client, environment_id=environment.id)
        return project_id, _place(client, project_id, "decision", CHAT_DECISION)

    def _chat(
        self,
        session: Session,
        container: ServiceContainer,
        project_id: str,
        person: User,
        *,
        running: bool = True,
    ) -> models.Session:
        """The project's chat open, a message of `person`'s in flight while
        `running`, committed so that a refused call's rollback keeps it."""
        chat = open_chat(session, session.get_one(Project, uuid.UUID(project_id)))
        ChatWriter(session, container.session_record_service(), chat).message(
            person, "The dome."
        )
        if running:
            chat.state_code = SessionState.RUNNING
        session.commit()
        return chat

    def test_the_answer_is_recorded_through_the_chat_its_effect_the_place_in_the_chat_goes_to(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        person: User,
        placed: tuple[str, str],
    ) -> None:
        project_id, item_id = placed
        chat = self._chat(session, container, project_id, person)

        response = client.post(
            _chat_answers_path(project_id),
            json={
                "block": f"{item_id}/D1",
                "value": "Dome",
                "for": "ada",
                "note": "The dome, it stands up in five minutes.",
                "tool_use_id": "toolu_01",
            },
        )

        assert response.status_code == 201
        assert response.get_json() == {"effect": "Answered · D1 · Which tent?"}
        [record] = [
            stored.record
            for stored in read_records(session, chat.id, limit=10)
            if stored.record.kind_code == "server"
        ]
        assert record.payload["toolUseId"] == "toolu_01"
        [block] = [
            part["block"]
            for part in _timeline_item(client, project_id, item_id)["body"]
            if part["type"] == "block"
        ]
        assert (block["answer"], block["via"], block["note"]) == (
            "Dome",
            "chat",
            "The dome, it stands up in five minutes.",
        )
        assert block["in_chat"] == {"chat": str(chat.id), "seq": record.seq}

    def test_an_unknown_project_block_or_person_is_not_found(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        person: User,
        placed: tuple[str, str],
    ) -> None:
        project_id, item_id = placed
        self._chat(session, container, project_id, person)
        body = {"block": f"{item_id}/D1", "value": "Dome", "for": "ada"}

        unknown = client.post(_chat_answers_path(uuid.uuid4()), json=body)
        no_block = client.post(
            _chat_answers_path(project_id), json={**body, "block": f"{item_id}/D9"}
        )
        nobody = client.post(
            _chat_answers_path(project_id), json={**body, "for": "zed"}
        )

        assert (unknown.status_code, no_block.status_code, nobody.status_code) == (
            404,
            404,
            404,
        )

    def test_a_project_with_no_chat_open_or_none_in_flight_conflicts(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        person: User,
        placed: tuple[str, str],
    ) -> None:
        project_id, item_id = placed
        body = {"block": f"{item_id}/D1", "value": "Dome", "for": "ada"}

        closed = client.post(_chat_answers_path(project_id), json=body)
        self._chat(session, container, project_id, person, running=False)
        idle = client.post(_chat_answers_path(project_id), json=body)

        assert (closed.status_code, idle.status_code) == (409, 409)
        assert closed.get_json()["error"].endswith(
            "because the project has no chat open"
        )
        assert idle.get_json()["error"].endswith(
            "because its chat has no turn in flight"
        )

    @pytest.mark.parametrize(
        "body",
        [
            {"block": "D1", "value": "Dome", "for": "ada"},
            {"block": "{item}/D1", "value": "", "for": "ada"},
            {"block": "{item}/D1", "value": "Dome"},
            {"block": "{item}/D1", "value": "Dome", "for": "ada", "by": "ada"},
        ],
        ids=["not-a-blocks-id", "no-answer", "no-person", "an-unknown-field"],
    )
    def test_a_body_that_is_not_an_answer_is_invalid(
        self, client: FlaskClient, placed: tuple[str, str], body: dict[str, Any]
    ) -> None:
        project_id, item_id = placed
        body = {**body, "block": body["block"].replace("{item}", item_id)}

        response = client.post(_chat_answers_path(project_id), json=body)

        assert response.status_code == 400


@pytest.mark.usefixtures("person")
class TestTheStage:
    @pytest.mark.parametrize(
        ("flask_env", "stage"),
        [
            pytest.param("testing", "prd", id="prd"),
            pytest.param(
                "production",
                default_stage("production"),
                id="unset outside testing and development",
            ),
        ],
    )
    @pytest.mark.parametrize(("path", "body"), ENDPOINTS)
    def test_every_endpoint_is_refused_on_prd(
        self,
        app: Flask,
        client: FlaskClient,
        session: Session,
        monkeypatch: pytest.MonkeyPatch,
        flask_env: str,
        stage: str,
        path: str,
        body: dict[str, Any],
    ) -> None:
        monkeypatch.setattr(app.container.config(), "flask_env", flask_env)
        monkeypatch.setattr(app.container.config(), "stage", Stage(stage))
        before = [_count(session, model) for model in (User, Environment, Project)]

        response = client.post(path, json=body)

        assert response.status_code == 400
        assert response.get_json()["error"] == (
            "The record's testing endpoints are not available on prd"
        )
        assert [
            _count(session, model) for model in (User, Environment, Project)
        ] == before

    def test_a_deployment_that_forgets_stage_loads_as_prd(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("STAGE", raising=False)

        settings = Settings.load(
            SettingsEnvironment(_env_file=None, FLASK_ENV="production")
        )

        assert settings.stage.value == "prd"

    @pytest.mark.parametrize("stage", [stage for stage in STAGES if stage != "prd"])
    def test_every_other_stage_answers_outside_testing_mode(
        self,
        app: Flask,
        client: FlaskClient,
        session: Session,
        monkeypatch: pytest.MonkeyPatch,
        stage: str,
    ) -> None:
        monkeypatch.setattr(app.container.config(), "flask_env", "production")
        monkeypatch.setattr(app.container.config(), "stage", Stage(stage))

        response = client.post(PROJECTS, json={"members": ["ada"]})

        assert response.status_code == 201
        assert (
            session.get_one(Project, uuid.UUID(response.get_json()["id"])).state_code
            is ProjectState.OPEN
        )

    @pytest.mark.parametrize(
        ("method", "path", "body"),
        [
            ("POST", "/api/testing/auth/session", {"subject": "subject-ada"}),
            ("POST", "/api/testing/sync/manifest", None),
            ("PUT", "/api/testing/links", {}),
        ],
    )
    def test_every_other_testing_endpoint_stays_behind_testing_mode(
        self,
        app: Flask,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
        method: str,
        path: str,
        body: dict[str, Any] | None,
    ) -> None:
        monkeypatch.setattr(app.container.config(), "flask_env", "production")
        monkeypatch.setattr(app.container.config(), "stage", Stage("dev"))

        response = client.open(path, method=method, json=body)

        assert response.status_code == 400
        assert response.get_json()["error"] == (
            "This endpoint is only available when the server is running in testing mode"
        )


class TestTheSignIn:
    @pytest.fixture(autouse=True)
    def deployed(self, oidc_app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
        """The dev stage as deployed: production mode, sign-in on."""
        monkeypatch.setattr(oidc_app.container.config(), "flask_env", "production")
        monkeypatch.setattr(oidc_app.container.config(), "stage", Stage("dev"))

    @pytest.mark.parametrize(("path", "body"), ENDPOINTS)
    def test_without_a_token_every_endpoint_is_unauthenticated(
        self, oidc_client: FlaskClient, path: str, body: dict[str, Any]
    ) -> None:
        assert oidc_client.post(path, json=body).status_code == 401

    @pytest.mark.parametrize(("path", "body"), ENDPOINTS)
    def test_without_editor_every_endpoint_is_refused(
        self,
        oidc_client: FlaskClient,
        generate_test_jwt: Any,
        path: str,
        body: dict[str, Any],
    ) -> None:
        token = generate_test_jwt(roles=["reader"])

        response = oidc_client.post(
            path, json=body, headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 403

    def test_an_editor_is_answered(
        self, oidc_client: FlaskClient, generate_test_jwt: Any, session: Session
    ) -> None:
        token = generate_test_jwt(roles=["editor"])

        response = oidc_client.post(
            PEOPLE,
            json={"handle": "ben", "name": "Ben Example"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        assert session.scalars(select(User).where(User.handle == "ben")).one()
