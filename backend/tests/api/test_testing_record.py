"""/api/testing/{people,environments,projects,items}: the record's states the
UI cannot make (TEST-6), on every stage but prd, behind the API's sign-in
(D027): among them the handbook an open project is born with, an agent's
saves of the project's draft and handbook, Pilot's Done, a work item placed by
repository, started in an environment of Pilot's own the stage's own
controller creates, or by name in an environment of that controller's, its
worker's registrations and attachments with their
effects and the list of steps it publishes, a pre-ruling pass's questions to a registered document's
writer, the store's update and its lift, as `update-store` makes and asks
them, and the brain's waits, a card's transition past the endpoint's token,
the waits' timer's tick, a wait's run and its close, and the invented
scenario's load."""

import base64
import json
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from queue import Empty
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
    DebriefEntry,
    Document,
    DocumentVersion,
    Environment,
    Item,
    ItemAttachment,
    ItemSighting,
    PilotNote,
    ProgressStep,
    Project,
    ProjectMember,
    ResearchAssignment,
    StepTiming,
    StepTranscript,
    StoreUpdate,
    Transcript,
    Turn,
    User,
    Wait,
    WaitFiring,
    Walk,
    Work,
    WriterQuestion,
)
from app.models.reference import (
    ProgressState,
    ProjectState,
    SessionState,
    TurnCause,
    UserKind,
    VersionCause,
    WorkTrigger,
)
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
from app.services.sse_connection_manager import SSEConnection
from app.services.start_gate import WorkSlots
from app.services.store_update_service import unlifted, utc_time
from app.services.supervisor import LoopHandle
from app.services.turn_end_read_service import TurnEndReadService
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.chats import ChatWriter, open_chat
from tests.support.debriefs import FIGURES, pass_ended
from tests.support.fake_controller import ServedFakeController
from tests.support.fake_sidecar import STORE_ENVIRONMENT_ID
from tests.support.starts import configured_starts
from tests.support.store_updates import hold, lift
from tests.support.supervisor import Supervise
from tests.support.youtrack import youtrack_delivery

PEOPLE = "/api/testing/people"
SERVICE_USERS = "/api/testing/service-users"
FLEET = {"handle": "fleet", "name": "KubeCoder fleet", "subject": "subject-fleet"}
ENVIRONMENTS = "/api/testing/environments"
PROJECTS = "/api/testing/projects"
STORE_UPDATE = "/api/testing/store-update"
SCENARIOS = "/api/testing/scenarios"
WALKS = "/api/testing/walks"

TASKS = [{"id": "build", "title": "Build the camp", "status": "pending"}]

AT = "2026-10-20T09:00:00Z"


def _count(session: Session, model: Any) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def _items_path(project_id: uuid.UUID | str) -> str:
    return f"{PROJECTS}/{project_id}/items"


def _sightings_path(project_id: uuid.UUID | str) -> str:
    return f"{PROJECTS}/{project_id}/sightings"


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


def _progress_path(item_id: uuid.UUID | str) -> str:
    return f"/api/testing/items/{item_id}/progress"


def _debrief_path(item_id: uuid.UUID | str) -> str:
    return f"/api/testing/items/{item_id}/debrief"


def _notable_path(item_id: uuid.UUID | str) -> str:
    return f"/api/testing/items/{item_id}/notable"


def _worker_attachments_path(item_id: uuid.UUID | str) -> str:
    return f"/api/testing/items/{item_id}/worker-attachments"


def _writer_questions_path(item_id: uuid.UUID | str) -> str:
    return f"/api/testing/items/{item_id}/writer-questions"


def _clarification_path(item_id: uuid.UUID | str) -> str:
    return f"/api/testing/items/{item_id}/clarification"


def _notes_path(item_id: uuid.UUID | str) -> str:
    return f"/api/testing/items/{item_id}/notes"


def _alerts_path(item_id: uuid.UUID | str) -> str:
    return f"/api/testing/items/{item_id}/alerts"


def _chat_answers_path(project_id: uuid.UUID | str) -> str:
    return f"/api/testing/projects/{project_id}/chat/answers"


def _chat_cancellations_path(project_id: uuid.UUID | str) -> str:
    return f"/api/testing/projects/{project_id}/chat/cancellations"


def _chat_stops_path(project_id: uuid.UUID | str) -> str:
    return f"/api/testing/projects/{project_id}/chat/stops"


def _chat_finish_path(project_id: uuid.UUID | str) -> str:
    return f"/api/testing/projects/{project_id}/chat/finish"


def _waits_path(project_id: uuid.UUID | str) -> str:
    return f"{PROJECTS}/{project_id}/waits"


def _wait_run_path(item_id: uuid.UUID | str) -> str:
    return f"/api/testing/waits/{item_id}/run"


def _wait_close_path(item_id: uuid.UUID | str) -> str:
    return f"/api/testing/waits/{item_id}/close"


TRACKER_EVENTS = "/api/testing/tracker-events"
DUE = "/api/testing/waits/due"


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

NAMED = "example-other-1a2b3c"

WORK_BY_NAME = {
    "environment": NAMED,
    "title": "Building the camp",
    "brief": "Build the camp.",
    "cwd": "/work/Other",
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


class TestCreateServiceUser:
    def test_it_makes_the_row_the_command_makes(
        self, client: FlaskClient, session: Session
    ) -> None:
        response = client.post(SERVICE_USERS, json=FLEET)

        assert response.status_code == 201
        assert response.get_json() == FLEET
        made = session.scalars(select(User).where(User.handle == "fleet")).one()
        assert (made.kind_code, made.name, made.subject, made.avatar_slot) == (
            UserKind.SERVICE,
            "KubeCoder fleet",
            "subject-fleet",
            None,
        )

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(FLEET | {"handle": "Fleet"}, id="a handle out of the pattern"),
            pytest.param(FLEET | {"name": " "}, id="a blank name"),
            pytest.param(FLEET | {"subject": ""}, id="a blank subject"),
            pytest.param(
                {"handle": "fleet", "name": "KubeCoder fleet"}, id="no subject"
            ),
        ],
    )
    def test_what_names_no_service_user_is_refused(
        self, client: FlaskClient, session: Session, body: dict[str, str]
    ) -> None:
        before = _count(session, User)

        assert client.post(SERVICE_USERS, json=body).status_code == 400
        assert _count(session, User) == before

    @pytest.mark.parametrize(
        ("body", "cause"),
        [
            pytest.param(
                FLEET | {"handle": "agent"}, "the handle is Pilot's", id="agent"
            ),
            pytest.param(
                FLEET | {"handle": "ada"}, "the handle is taken", id="a handle taken"
            ),
            pytest.param(
                FLEET | {"subject": "subject-ada"},
                "'ada' holds the subject 'subject-ada' already",
                id="a subject that is a User's",
            ),
        ],
    )
    def test_what_the_command_refuses_conflicts(
        self,
        client: FlaskClient,
        session: Session,
        person: User,
        body: dict[str, str],
        cause: str,
    ) -> None:
        response = client.post(SERVICE_USERS, json=body)

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            f"Cannot make the service user {body['handle']!r} because {cause}"
        )
        assert (
            session.scalars(
                select(User.handle).where(User.kind_code == UserKind.SERVICE)
            ).all()
            == []
        )


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
    @pytest.mark.parametrize("document", ["handbook", "journal"])
    def test_past_the_draft_it_is_born_with_its_handbook_and_its_journal_empty(
        self, client: FlaskClient, state: str, document: str
    ) -> None:
        project_id = _make(client, name="Camp", state=state)

        response = client.get(f"/api/projects/{project_id}/{document}")

        assert (response.status_code, response.get_json()) == (
            200,
            {"title": None, "body": [], "writing": False},
        )

    @pytest.mark.parametrize("document", ["handbook", "journal"])
    def test_a_draft_has_no_handbook_and_no_journal(
        self, client: FlaskClient, document: str
    ) -> None:
        project_id = _make(client, name="Camp", state="draft")

        assert client.get(f"/api/projects/{project_id}/{document}").status_code == 404

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
class TestReadSightings:
    def test_what_the_persons_open_membership_was_shown(
        self, client: FlaskClient, session: Session
    ) -> None:
        project_id = _make(client)
        response = client.post(
            _items_path(project_id),
            json={
                "kind": "decision",
                "title": "Which tent?",
                "text": DECISION,
                "by_pilot": True,
            },
        )
        item_id = response.get_json()["id"]
        member = session.scalars(
            select(ProjectMember).where(
                ProjectMember.project_id == uuid.UUID(project_id)
            )
        ).one()

        assert client.get(
            _sightings_path(project_id), query_string={"handle": "ada"}
        ).get_json() == {"item_ids": []}

        session.add(ItemSighting(member_id=member.id, item_id=uuid.UUID(item_id)))
        session.flush()
        response = client.get(
            _sightings_path(project_id), query_string={"handle": "ada"}
        )

        assert response.status_code == 200
        assert response.get_json() == {"item_ids": [item_id]}

    @pytest.mark.parametrize("handle", ["nobody", "ben"])
    def test_a_person_no_member_of_the_project_is_not_found(
        self, client: FlaskClient, ben: User, handle: str
    ) -> None:
        response = client.get(
            _sightings_path(_make(client)), query_string={"handle": handle}
        )

        assert response.status_code == 404

    def test_without_a_handle_it_is_refused(self, client: FlaskClient) -> None:
        response = client.get(_sightings_path(_make(client)))

        assert response.status_code == 400


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
@pytest.mark.parametrize("document", ["draft", "handbook", "journal"])
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
@pytest.mark.parametrize("document", ["handbook", "journal"])
def test_a_drafts_handbook_or_journal_save_is_not_found(
    client: FlaskClient, environment: Environment, document: str
) -> None:
    project_id = _make(client, state="draft", environment_id=environment.id)

    response = client.post(
        _document_saves_path(project_id, document), json={"text": "# Camp\n"}
    )

    assert response.status_code == 404
    assert response.get_json()["error"] == (
        f"{document.capitalize()} of project {project_id} was not found"
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
        usage_halts=container.usage_halts(),
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

    def test_it_places_a_work_item_in_an_environment_by_name_and_its_start_runs_there(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        served: None,
        session: Session,
        fake_controller: ServedFakeController,
    ) -> None:
        # F86.9: nothing made, taken, named or reset; the stopped one started.
        fake_controller.add_environment(NAMED, name="Other-1", repo="example/Other")
        project_id = _make(client, name="Camp")

        response = client.post(_work_path(project_id), json=WORK_BY_NAME)

        assert response.status_code == 201, response.get_json()
        work_id = uuid.UUID(response.get_json()["id"])
        run = session.get_one(models.Session, work_id)
        assert (run.state_code, run.environment_id, run.kind_code, run.cwd) == (
            SessionState.STARTING,
            NAMED,
            "work",
            "/work/Other",
        )
        assert session.get_one(Work, work_id).repo is None
        assert fake_controller.calls == [f"GET /environments/{NAMED}"]
        clear_after_commit_callbacks()

        container.session_start_service().run(work_id, LoopHandle(f"start:{work_id}"))

        run = session.get_one(models.Session, work_id, populate_existing=True)
        assert (run.state_code, run.environment_id) == (SessionState.RUNNING, NAMED)
        named = fake_controller.environment(NAMED)
        assert (named.name, named.resets, named.status) == ("Other-1", 0, "running")
        assert "POST /environments" not in fake_controller.calls
        assert [
            call
            for call in fake_controller.calls
            if call.endswith(("/rename", "/stop", "/reset", "/start"))
        ] == [f"POST /environments/{NAMED}/start"]
        work = _timeline_item(client, project_id, str(work_id))["work"]
        assert work["environment"] == {"id": NAMED, "name": "Other-1"}

    @pytest.mark.parametrize(
        "body",
        [
            {**WORK, "environment": "example-other-1a2b3c"},
            {"title": "Building the camp", "brief": "Build it.", "cwd": "/work/Camp"},
            {**WORK, "repo": None, "environment": ""},
        ],
        ids=["two-placements", "no-placement", "an-empty-environment"],
    )
    def test_a_body_that_names_not_exactly_one_placement_is_invalid(
        self,
        client: FlaskClient,
        served: None,
        session: Session,
        fake_controller: ServedFakeController,
        body: dict[str, Any],
    ) -> None:
        project_id = _make(client)

        response = client.post(_work_path(project_id), json=body)

        assert response.status_code == 400
        assert self._work_items(session) == []
        assert fake_controller.calls == []

    def test_an_environment_the_controller_does_not_have_is_404(
        self,
        client: FlaskClient,
        served: None,
        session: Session,
    ) -> None:
        project_id = _make(client)

        response = client.post(_work_path(project_id), json=WORK_BY_NAME)

        assert response.status_code == 404
        assert response.get_json()["error"] == f"Environment {NAMED} was not found"
        assert self._work_items(session) == []
        assert session.get(Environment, NAMED) is None

    def test_the_stores_environment_is_409(
        self,
        client: FlaskClient,
        served: None,
        session: Session,
        fake_controller: ServedFakeController,
    ) -> None:
        fake_controller.add_environment(STORE_ENVIRONMENT_ID, name="PilotProjects")
        project_id = _make(client)

        response = client.post(
            _work_path(project_id),
            json={**WORK_BY_NAME, "environment": STORE_ENVIRONMENT_ID},
        )

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            f"Cannot place a work item in {STORE_ENVIRONMENT_ID} because it is the"
            " store's environment, where no work item runs"
        )
        assert self._work_items(session) == []

    def test_a_controller_that_does_not_answer_the_read_of_the_environment_is_502(
        self,
        client: FlaskClient,
        served: None,
        session: Session,
        fake_controller: ServedFakeController,
    ) -> None:
        project_id = _make(client)
        fake_controller.close()

        response = client.post(_work_path(project_id), json=WORK_BY_NAME)

        assert response.status_code == 502
        assert self._work_items(session) == []

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
            {
                "work": {"id": response.get_json()["id"], "title": WORK["title"]},
                "undone": False,
            },
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

    def test_it_names_the_blocks_the_work_item_researches(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        served: None,
        session: Session,
    ) -> None:
        project_id = _make(client)
        document_id = self._cut_over(session, container, project_id)

        response = client.post(
            _work_path(project_id), json={**WORK, "researches": [f"{document_id}/D1"]}
        )

        assert response.status_code == 201, response.get_json()
        [research] = session.scalars(select(ResearchAssignment)).all()
        assert str(research.work_id) == response.get_json()["id"]
        assert session.get_one(models.Block, research.block_id).local_id == "D1"

    @pytest.mark.parametrize(
        ("research", "status"),
        [("A1", 409), ("D9", 404), ("D1 Q1", 400)],
        ids=["answered", "no-block", "no-block-id"],
    )
    def test_a_research_the_record_refuses_places_nothing(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        served: None,
        session: Session,
        research: str,
        status: int,
    ) -> None:
        project_id = _make(client)
        document_id = self._cut_over(session, container, project_id)

        response = client.post(
            _work_path(project_id),
            json={**WORK, "researches": [f"{document_id}/{research}"]},
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
    (SERVICE_USERS, FLEET),
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
    (_progress_path(NO_ROW), {"steps": []}),
    (
        _debrief_path(NO_ROW),
        {
            "debrief": "Hi",
            "entries": [{"section": "S", "round": 1, "role": "r", "duration": 0}],
        },
    ),
    (_notable_path(NO_ROW), {"text": "Its first stop."}),
    (
        _writer_questions_path(NO_ROW),
        {"questions": [{"block": "Q1", "question": "Which?"}]},
    ),
    (_clarification_path(NO_ROW), {"reply": "Lake Ilm."}),
    (_notes_path(NO_ROW), {"text": "Why."}),
    (_alerts_path(NO_ROW), {"text": "First.", "awaits": f"{NO_ROW}/D1"}),
    (
        _chat_answers_path(NO_ROW),
        {"block": f"{NO_ROW}/D1", "value": "Yes", "for": "ada"},
    ),
    (_chat_cancellations_path(NO_ROW), {"item": str(NO_ROW), "for": "ada"}),
    (_chat_stops_path(NO_ROW), {"item": str(NO_ROW), "reason": "Replaced"}),
    (_chat_finish_path(NO_ROW), {"archive": True}),
    (STORE_UPDATE, {}),
    (_waits_path(NO_ROW), {"kind": "card_wait", "title": "SR-4", "cards": ["SR-4"]}),
    (f"{TRACKER_EVENTS}/youtrack", youtrack_delivery()),
    (DUE, {}),
    (_wait_run_path(NO_ROW), {}),
    (_wait_close_path(NO_ROW), {"note": "Read"}),
    (SCENARIOS, {"projects": {"recipe-box": str(NO_ROW)}}),
    (WALKS, {}),
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
        cause_code=TurnCause.BRIEF,
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
class TestCreateProgress:
    @pytest.fixture
    def work_item(
        self,
        session: Session,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> models.Session:
        """A work item's Session, its turn running."""
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

    def test_it_replaces_the_list_as_the_worker_does_and_answers_it(
        self, client: FlaskClient, session: Session, work_item: models.Session
    ) -> None:
        published = client.post(
            _progress_path(work_item.id),
            json={
                "steps": [
                    {"code": "P1.code", "label": "P1 · code", "state": "done"},
                    {"code": "test", "label": "Test", "state": "active"},
                ]
            },
        )

        response = client.post(
            _progress_path(work_item.id),
            json={
                "steps": [
                    {"code": "P1.code", "label": "P1 · code"},
                    {"code": "test", "label": "Test"},
                    {"code": "docs", "label": "Docs"},
                ]
            },
        )

        assert published.status_code == 200, published.get_json()
        assert (response.status_code, response.get_json()) == (
            200,
            {
                "steps": [
                    {
                        "code": "P1.code",
                        "label": "P1 · code",
                        "state": "done",
                        "why": None,
                    },
                    {"code": "test", "label": "Test", "state": "active", "why": None},
                    {"code": "docs", "label": "Docs", "state": "pending", "why": None},
                ]
            },
        )
        assert [
            (step.code, step.state_code)
            for step in session.scalars(
                select(ProgressStep)
                .where(ProgressStep.work_id == work_item.id)
                .order_by(ProgressStep.position)
            )
        ] == [
            ("P1.code", ProgressState.DONE),
            ("test", ProgressState.ACTIVE),
            ("docs", ProgressState.PENDING),
        ]

    def test_no_steps_remove_the_list(
        self, client: FlaskClient, session: Session, work_item: models.Session
    ) -> None:
        client.post(
            _progress_path(work_item.id),
            json={"steps": [{"code": "test", "label": "Test"}]},
        )

        response = client.post(_progress_path(work_item.id), json={"steps": []})

        assert (response.status_code, response.get_json()) == (200, {"steps": []})
        assert _count(session, ProgressStep) == 0

    def test_a_steps_why_is_stored_and_answered_with_it(
        self, client: FlaskClient, session: Session, work_item: models.Session
    ) -> None:
        """DB 327: on any step, a step without one answering none."""
        why = "The reviewer found the downgrade left the column"

        response = client.post(
            _progress_path(work_item.id),
            json={
                "steps": [
                    {"code": "P1.code", "label": "P1 · code", "state": "done"},
                    {"code": "P1.code-2", "label": "P1 · code 2", "why": why},
                ]
            },
        )

        assert (response.status_code, response.get_json()) == (
            200,
            {
                "steps": [
                    {
                        "code": "P1.code",
                        "label": "P1 · code",
                        "state": "done",
                        "why": None,
                    },
                    {
                        "code": "P1.code-2",
                        "label": "P1 · code 2",
                        "state": "pending",
                        "why": why,
                    },
                ]
            },
        )
        assert [
            step.why
            for step in session.scalars(
                select(ProgressStep)
                .where(ProgressStep.work_id == work_item.id)
                .order_by(ProgressStep.position)
            )
        ] == [None, why]

    def test_a_steps_kind_conversations_duration_and_mark_are_taken_as_the_tools(
        self, client: FlaskClient, session: Session, work_item: models.Session
    ) -> None:
        """The real route's schema and service (F156.1, F156.2): the fields
        kept on the step, and a step that goes done with a kind and a duration
        timed."""
        thread = "6f1d2c9e-0b7a-4e58-9a31-5c8e2f4d7b06"
        step = {
            "code": "P1.code",
            "label": "P1 · code",
            "kind": "code-writer",
            "conversations": [thread],
        }

        listed = client.post(
            _progress_path(work_item.id),
            json={"steps": [{**step, "marked": False}]},
        )
        done = client.post(
            _progress_path(work_item.id),
            json={
                "steps": [{**step, "state": "done", "duration": 1440, "marked": True}]
            },
        )
        refused = client.post(
            _progress_path(work_item.id),
            json={"steps": [{**step, "state": "active", "duration": 5}]},
        )
        unknown = client.post(
            _progress_path(work_item.id), json={"steps": [{**step, "size": 3}]}
        )

        assert [
            response.status_code for response in (listed, done, refused, unknown)
        ] == [200, 200, 409, 400]
        assert refused.get_json()["error"] == (
            f"Cannot set the progress of work item {work_item.id} because step"
            " P1.code has a duration and is not done"
        )
        [stored] = session.scalars(select(ProgressStep)).all()
        assert (stored.kind_code, stored.marked, stored.listed_ahead) == (
            "code-writer",
            True,
            True,
        )
        assert [
            (naming.code, naming.session_id)
            for naming in session.scalars(select(StepTranscript))
        ] == [("P1.code", thread)]
        assert [
            (
                timing.work_id,
                timing.code,
                timing.kind_code,
                timing.duration,
                timing.listed_ahead,
                timing.marked,
                timing.repo,
            )
            for timing in session.scalars(select(StepTiming))
        ] == [(work_item.id, "P1.code", "code-writer", 1440, True, True, WORK_REPO)]

    def test_an_item_that_is_no_work_item_is_not_found(
        self, client: FlaskClient, item: Item
    ) -> None:
        for item_id in (item.id, uuid.uuid4()):
            response = client.post(_progress_path(item_id), json={"steps": []})

            assert response.status_code == 404

    def test_a_session_with_no_turn_running_is_refused(
        self, client: FlaskClient, session: Session, work_item: models.Session
    ) -> None:
        work_item.state_code = SessionState.STOPPED
        session.flush()

        response = client.post(
            _progress_path(work_item.id),
            json={"steps": [{"code": "test", "label": "Test"}]},
        )

        assert response.status_code == 403
        assert _count(session, ProgressStep) == 0

    def test_a_work_item_whose_start_gave_it_no_environment_conflicts(
        self, client: FlaskClient, session: Session, work_item: models.Session
    ) -> None:
        work_item.environment_id = None
        session.flush()

        response = client.post(_progress_path(work_item.id), json={"steps": []})

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            f"Cannot set the progress of work item {work_item.id} because work"
            f" item {work_item.id} has no environment yet"
        )

    def test_a_repeated_code_conflicts_and_changes_nothing(
        self, client: FlaskClient, session: Session, work_item: models.Session
    ) -> None:
        response = client.post(
            _progress_path(work_item.id),
            json={
                "steps": [
                    {"code": "test", "label": "Test"},
                    {"code": "test", "label": "Test again"},
                ]
            },
        )

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            f"Cannot set the progress of work item {work_item.id} because code"
            " test is repeated"
        )
        assert _count(session, ProgressStep) == 0

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"steps": [{"code": "", "label": "Test"}]},
            {"steps": [{"code": "test", "label": ""}]},
            {"steps": [{"code": "test", "label": "Test", "state": "failed"}]},
            {"steps": [{"code": "c" * 65, "label": "Test"}]},
            {"steps": [{"code": "test", "label": "l" * 121}]},
            {"steps": [{"code": "test", "label": "Test", "why": ""}]},
            {"steps": [{"code": "test", "label": "Test", "why": "w" * 121}]},
            {"steps": [{"code": "test", "label": "Test", "note": "x"}]},
            {"steps": [{"code": f"s{n}", "label": "Step"} for n in range(101)]},
        ],
        ids=[
            "no steps",
            "an empty code",
            "an empty label",
            "a state outside the three",
            "a code past 64",
            "a label past 120",
            "an empty why",
            "a why past 120",
            "a field it does not know",
            "a list past 100",
        ],
    )
    def test_a_body_the_worker_s_call_refuses_is_invalid(
        self,
        client: FlaskClient,
        session: Session,
        work_item: models.Session,
        body: dict[str, Any],
    ) -> None:
        response = client.post(_progress_path(work_item.id), json=body)

        assert response.status_code == 400
        assert _count(session, ProgressStep) == 0


DEBRIEF = {
    "debrief": "It went well, if slowly.",
    "entries": [
        {
            "section": "P1 · The client",
            "round": 1,
            "role": "code-writer",
            "duration": 540,
            "words": "Fine.",
        },
        {
            "section": "P1 · The client",
            "round": 2,
            "role": "code-reviewer",
            "duration": 0,
            "why": "The downgrade left the column",
        },
        {
            "section": "Completion check",
            "round": 1,
            "role": "sweep",
            "duration": 600,
            "passed": False,
        },
    ],
}
"""A stage session's debrief, invented, as its call gives it."""


@pytest.mark.usefixtures("person")
class TestCreateDebrief:
    @pytest.fixture
    def work_item(
        self,
        session: Session,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> models.Session:
        """A work item's Session, its turn running."""
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

    def test_it_stores_the_debrief_as_the_worker_does_and_answers_its_count(
        self, client: FlaskClient, session: Session, work_item: models.Session
    ) -> None:
        response = client.post(_debrief_path(work_item.id), json=DEBRIEF)

        assert (response.status_code, response.get_json()) == (201, {"entries": 3})
        work = session.get_one(Work, work_item.id)
        assert (work.debrief, work.debrief_subject, work.debrief_completes) == (
            DEBRIEF["debrief"],
            None,
            True,
        )
        assert [
            (
                entry.position,
                entry.section,
                entry.round,
                entry.role,
                entry.duration,
                entry.words,
                entry.passed,
                entry.why,
            )
            for entry in session.scalars(
                select(DebriefEntry)
                .where(DebriefEntry.work_id == work_item.id)
                .order_by(DebriefEntry.position)
            )
        ] == [
            (1, "P1 · The client", 1, "code-writer", 540, "Fine.", None, None),
            (
                2,
                "P1 · The client",
                2,
                "code-reviewer",
                0,
                None,
                None,
                "The downgrade left the column",
            ),
            (3, "Completion check", 1, "sweep", 600, None, False, None),
        ]

    def test_it_stores_its_subject_and_whether_it_completes_it(
        self, client: FlaskClient, session: Session, work_item: models.Session
    ) -> None:
        """DB 608, as the worker's call stores them."""
        response = client.post(
            _debrief_path(work_item.id),
            json=DEBRIEF
            | {"subject": "Slice 058 · The search page", "completes": False},
        )

        assert response.status_code == 201
        work = session.get_one(Work, work_item.id)
        assert (work.debrief_subject, work.debrief_completes) == (
            "Slice 058 · The search page",
            False,
        )
        assert work.debrief_figures is None

    def test_it_stores_the_loops_figures(
        self, client: FlaskClient, session: Session, work_item: models.Session
    ) -> None:
        """DB 635, as the worker's call stores them."""
        response = client.post(
            _debrief_path(work_item.id), json=DEBRIEF | {"figures": FIGURES}
        )

        assert response.status_code == 201
        assert session.get_one(Work, work_item.id).debrief_figures == FIGURES

    def test_a_second_conflicts_and_changes_nothing(
        self, client: FlaskClient, session: Session, work_item: models.Session
    ) -> None:
        client.post(_debrief_path(work_item.id), json=DEBRIEF)

        response = client.post(
            _debrief_path(work_item.id),
            json={"debrief": "Again.", "entries": DEBRIEF["entries"][:1]},
        )

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            f"Cannot register the debrief of work item {work_item.id} because it"
            " has its debrief already"
        )
        assert session.get_one(Work, work_item.id).debrief == DEBRIEF["debrief"]
        assert _count(session, DebriefEntry) == 3

    def test_an_item_that_is_no_work_item_is_not_found(
        self, client: FlaskClient, item: Item
    ) -> None:
        for item_id in (item.id, uuid.uuid4()):
            response = client.post(_debrief_path(item_id), json=DEBRIEF)

            assert response.status_code == 404

    def test_a_session_with_no_turn_running_is_refused(
        self, client: FlaskClient, session: Session, work_item: models.Session
    ) -> None:
        work_item.state_code = SessionState.IDLE
        session.flush()

        response = client.post(_debrief_path(work_item.id), json=DEBRIEF)

        assert response.status_code == 403
        assert _count(session, DebriefEntry) == 0

    def test_a_work_item_whose_start_gave_it_no_environment_conflicts(
        self, client: FlaskClient, session: Session, work_item: models.Session
    ) -> None:
        work_item.environment_id = None
        session.flush()

        response = client.post(_debrief_path(work_item.id), json=DEBRIEF)

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            f"Cannot register the debrief of work item {work_item.id} because"
            f" work item {work_item.id} has no environment yet"
        )

    @pytest.mark.parametrize(
        "body",
        [
            {"debrief": "", "entries": DEBRIEF["entries"]},
            {"debrief": "  ", "entries": DEBRIEF["entries"]},
            {"debrief": "Fine.", "entries": []},
            {"debrief": "Fine.", "entries": [{**DEBRIEF["entries"][0], "round": 0}]},
            {
                "debrief": "Fine.",
                "entries": [{**DEBRIEF["entries"][0], "passed": True}],
            },
            {
                "debrief": "Fine.",
                "entries": [{**DEBRIEF["entries"][0], "step": "P1.code"}],
            },
            {"debrief": "Fine.", "entries": DEBRIEF["entries"], "subject": " "},
            {"debrief": "Fine.", "entries": DEBRIEF["entries"], "completes": False},
            {"debrief": "Fine.", "entries": DEBRIEF["entries"], "figures": " "},
            {"debrief": "Fine.", "entries": DEBRIEF["entries"], "figures": "f" * 8_001},
        ],
        ids=[
            "an empty debrief",
            "a blank debrief",
            "no entries",
            "a round of 0",
            "words and passed",
            "a field it does not know",
            "a blank subject",
            "not completing without a subject",
            "blank figures",
            "long figures",
        ],
    )
    def test_a_body_the_worker_s_call_refuses_is_invalid(
        self,
        client: FlaskClient,
        session: Session,
        work_item: models.Session,
        body: dict[str, Any],
    ) -> None:
        response = client.post(_debrief_path(work_item.id), json=body)

        assert response.status_code == 400
        assert session.get_one(Work, work_item.id).debrief is None
        assert _count(session, DebriefEntry) == 0


@pytest.mark.usefixtures("person")
class TestWriteNotable:
    """`POST /api/testing/items/<id>/notable`: Pilot's lines on a work item's
    debrief, as the pass's `write_notable` writes them (DB 636)."""

    @pytest.fixture
    def work_item(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> models.Session:
        """A work item's Session, its turn running, its debrief given."""
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
        assert client.post(_debrief_path(run.id), json=DEBRIEF).status_code == 201
        return run

    def test_it_writes_the_lines_and_a_later_call_replaces_them(
        self, client: FlaskClient, session: Session, work_item: models.Session
    ) -> None:
        first = client.post(
            _notable_path(work_item.id), json={"text": "Its first stop."}
        )

        assert (first.status_code, first.get_json()) == (200, {"outcome": "written"})
        assert session.get_one(Work, work_item.id).debrief_notable == "Its first stop."

        second = client.post(
            _notable_path(work_item.id), json={"text": "- A second stop."}
        )

        assert (second.status_code, second.get_json()) == (
            200,
            {"outcome": "replaced"},
        )
        session.expire_all()
        assert session.get_one(Work, work_item.id).debrief_notable == "- A second stop."

    def test_lines_on_a_work_its_notice_carries_show_in_its_row_of_the_tree(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        project: Project,
        work_item: models.Session,
    ) -> None:
        """DB 611: written after the notice stands, as a Retry's pass writes
        them."""
        container.record_service().work_done(work_item.id, datetime.now(UTC))
        pass_ended(session, container, project, work_item)

        response = client.post(
            _notable_path(work_item.id), json={"text": "Its first stop."}
        )

        assert response.status_code == 200
        timeline = json.loads(container.view_service().timeline(project).text)
        assert [(row["kind"], row.get("notable")) for row in timeline["items"]][
            -2:
        ] == [("work", None), ("debrief_notice", ["Its first stop."])]
        assert [row["title"] for row in timeline["items"]][-2] == "Pre-ruling"

    def test_no_work_item_of_the_id_is_not_found(self, client: FlaskClient) -> None:
        response = client.post(_notable_path(uuid.uuid4()), json={"text": "Hi"})

        assert response.status_code == 404

    def test_a_work_item_that_gave_no_debrief_conflicts(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = models.Session(
            project_id=project.id,
            environment_id=environment.id,
            kind_code="work",
            cwd="/work/Camp",
            token_hash="3" * 64,
            state_code=SessionState.RUNNING,
        )
        session.add(run)
        session.flush()
        container.record_service().place_work(project, run, "Building the camp")
        # Committed, so that the refused call's rollback keeps it.
        session.commit()

        response = client.post(_notable_path(run.id), json={"text": "Hi"})

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            f"Cannot write Pilot's lines on the debrief of work item {run.id}"
            " because it gave no debrief"
        )
        assert session.get_one(Work, run.id).debrief_notable is None

    @pytest.mark.parametrize(
        "body",
        [{}, {"text": ""}, {"text": " \n"}, {"text": "n" * 16_001}],
        ids=["no text", "empty", "blank", "long"],
    )
    def test_a_body_the_pass_s_call_refuses_is_invalid(
        self,
        client: FlaskClient,
        session: Session,
        work_item: models.Session,
        body: dict[str, Any],
    ) -> None:
        response = client.post(_notable_path(work_item.id), json=body)

        assert response.status_code == 400
        assert session.get_one(Work, work_item.id).debrief_notable is None


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

    def test_a_passs_questions_are_asked_in_one_job_turn_and_its_blocks_say_so(
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
        assert [
            part["block"]["id"]
            for part in line["body"]
            if part["type"] == "block" and part["block"]["writer_asked"]
        ] == ["Q1", "Q2"]

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
class TestCreateNotesAndAlerts:
    @pytest.fixture
    def documents(
        self,
        session: Session,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> tuple[Item, Item]:
        """Two open documents of the project, committed so that a refused
        call's rollback keeps them."""
        bear = container.document_service().bear_item
        camp = bear(project, "document", "Camp plan", project_session, QUESTIONED)
        site = bear(project, "document", "Camp site", project_session, QUESTIONED)
        session.commit()
        return camp, site

    def test_a_note_is_written_in_a_passs_turn_and_read_on_its_block(
        self,
        client: FlaskClient,
        session: Session,
        project: Project,
        documents: tuple[Item, Item],
    ) -> None:
        camp, _ = documents

        response = client.post(
            _notes_path(camp.id),
            json={
                "block": "Q1",
                "text": "The north shore flooded.",
                "suggested_answer": "Lake Ilm",
                "suggested_note": "Dry ground",
            },
        )

        assert response.status_code == 200
        assert response.get_json() == {"outcome": "written"}
        [job] = session.scalars(
            select(models.Session).where(models.Session.kind_code == "job")
        )
        assert (job.project_id, job.state_code) == (project.id, SessionState.IDLE)
        [turn] = session.scalars(select(Turn).where(Turn.session_id == job.id))
        assert turn.ended_at is not None
        [note] = session.scalars(select(PilotNote))
        assert note.turn_id == turn.id
        line = _timeline_item(client, str(project.id), str(camp.id))
        assert {
            part["block"]["id"]: _within(
                part["block"]["pilots_note"],
                {
                    "text": "The north shore flooded.",
                    "suggested_answer": "Lake Ilm",
                    "suggested_note": "Dry ground",
                    "differs": False,
                },
            )
            for part in line["body"]
            if part["type"] == "block"
        } == {"Q1": True, "Q2": False}

    def test_a_note_on_the_item_as_a_whole_and_its_withdrawal(
        self,
        client: FlaskClient,
        project: Project,
        documents: tuple[Item, Item],
    ) -> None:
        camp, _ = documents

        written = client.post(_notes_path(camp.id), json={"text": "Read it first."})
        shown = _timeline_item(client, str(project.id), str(camp.id))["pilots_note"]
        withdrawn = client.post(_notes_path(camp.id), json={})

        assert written.get_json() == {"outcome": "written"}
        assert _within(shown, {"text": "Read it first.", "late": False})
        assert withdrawn.get_json() == {"outcome": "withdrawn"}
        assert (
            _timeline_item(client, str(project.id), str(camp.id))["pilots_note"] is None
        )

    def test_an_alert_is_written_in_a_passs_turn_and_read_on_its_item(
        self,
        client: FlaskClient,
        project: Project,
        documents: tuple[Item, Item],
    ) -> None:
        camp, site = documents

        response = client.post(
            _alerts_path(camp.id),
            json={"text": "Pick the site first.", "awaits": f"{site.id}/Q2"},
        )

        assert response.status_code == 200
        assert response.get_json() == {"outcome": "written"}
        assert _timeline_item(client, str(project.id), str(camp.id))["send_alert"] == {
            "text": "Pick the site first.",
            "awaits": {"item": str(site.id), "title": "Camp site", "block": "Q2"},
        }

    def test_what_the_tools_refuse_conflicts_and_an_unknown_item_is_not_found(
        self, client: FlaskClient, documents: tuple[Item, Item]
    ) -> None:
        camp, _ = documents

        unknown = client.post(_notes_path(uuid.uuid4()), json={"text": "Why."})
        no_block = client.post(_notes_path(camp.id), json={"block": "Q9", "text": "?"})
        none_stands = client.post(_notes_path(camp.id), json={"block": "Q1"})
        half = client.post(_alerts_path(camp.id), json={"text": "First."})

        assert (unknown.status_code, no_block.status_code) == (404, 404)
        assert (none_stands.status_code, half.status_code) == (409, 409)
        assert none_stands.get_json()["error"].endswith(
            f"because no note of Pilot's stands on {camp.id}/Q1"
        )

    @pytest.mark.parametrize(
        ("path", "body"),
        [
            (_notes_path, {"block": ""}),
            (_notes_path, {"text": ""}),
            (_notes_path, {"answer": "Yes"}),
            (_alerts_path, {"text": "First.", "awaits": "D1"}),
        ],
        ids=["an-empty-block", "empty-text", "an-unknown-field", "a-bare-local-id"],
    )
    def test_a_body_that_is_not_a_note_or_an_alert_is_invalid(
        self,
        client: FlaskClient,
        documents: tuple[Item, Item],
        path: Callable[[uuid.UUID], str],
        body: dict[str, Any],
    ) -> None:
        response = client.post(path(documents[0].id), json=body)

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
        assert run_line["title"] == "Clarify refinement.md"
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
        assert (run_line["title"], run_line["done"]) == ("Clarify refinement.md", None)
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
class TestCreateChatCancellation:
    def _placed(self, client: FlaskClient, environment: Environment) -> tuple[str, str]:
        """A project with a decision a job of Pilot's own added, and the
        item's id."""
        project_id = _make(client, environment_id=environment.id)
        response = client.post(
            _items_path(project_id),
            json={
                "kind": "decision",
                "title": "Which tent?",
                "text": CHAT_DECISION,
                "by_pilot": True,
            },
        )
        assert response.status_code == 201, response.get_json()
        return project_id, response.get_json()["id"]

    def _chat(
        self,
        session: Session,
        container: ServiceContainer,
        project_id: str,
        person: User,
    ) -> models.Session:
        """The project's chat open, a message of `person`'s in flight,
        committed so that a refused call's rollback keeps it."""
        chat = open_chat(session, session.get_one(Project, uuid.UUID(project_id)))
        ChatWriter(session, container.session_record_service(), chat).message(
            person, "Never mind the tent."
        )
        chat.state_code = SessionState.RUNNING
        session.commit()
        return chat

    def test_the_ask_is_called_off_through_the_chat_done_cancelled_with_no_undo(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        person: User,
        environment: Environment,
    ) -> None:
        project_id, item_id = self._placed(client, environment)
        chat = self._chat(session, container, project_id, person)

        response = client.post(
            _chat_cancellations_path(project_id),
            json={"item": item_id, "for": "ada", "tool_use_id": "toolu_01"},
        )

        assert response.status_code == 201
        assert response.get_json() == {"effect": "Cancelled · Which tent?"}
        [record] = [
            stored.record
            for stored in read_records(session, chat.id, limit=10)
            if stored.record.kind_code == "server"
        ]
        assert record.payload["toolUseId"] == "toolu_01"
        done = _timeline_item(client, project_id, item_id)["done"]
        assert (done["cause"], done["by"]["handle"], done["undo"]) == (
            "cancelled",
            "ada",
            False,
        )

    def test_an_unknown_project_item_or_person_is_not_found(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        person: User,
        environment: Environment,
    ) -> None:
        project_id, item_id = self._placed(client, environment)
        self._chat(session, container, project_id, person)
        body = {"item": item_id, "for": "ada"}

        unknown = client.post(_chat_cancellations_path(uuid.uuid4()), json=body)
        no_item = client.post(
            _chat_cancellations_path(project_id),
            json={**body, "item": str(uuid.uuid4())},
        )
        nobody = client.post(
            _chat_cancellations_path(project_id), json={**body, "for": "zed"}
        )

        assert (unknown.status_code, no_item.status_code, nobody.status_code) == (
            404,
            404,
            404,
        )

    def test_a_project_with_no_chat_open_and_an_ask_the_record_refuses_conflict(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        person: User,
        environment: Environment,
    ) -> None:
        project_id, item_id = self._placed(client, environment)
        theirs = _place(client, project_id, "decision", CHAT_DECISION)
        body = {"item": item_id, "for": "ada"}

        closed = client.post(_chat_cancellations_path(project_id), json=body)
        self._chat(session, container, project_id, person)
        refused = client.post(
            _chat_cancellations_path(project_id), json={**body, "item": theirs}
        )

        assert (closed.status_code, refused.status_code) == (409, 409)
        assert closed.get_json()["error"].endswith(
            "because the project has no chat open"
        )
        assert refused.get_json()["error"].endswith("because it is no ask Pilot added")

    @pytest.mark.parametrize(
        "body",
        [{"item": "D1", "for": "ada"}, {"item": "{item}"}],
        ids=["not-an-items-id", "no-person"],
    )
    def test_a_body_that_is_not_an_item_and_a_handle_is_invalid(
        self, client: FlaskClient, environment: Environment, body: dict[str, Any]
    ) -> None:
        project_id, item_id = self._placed(client, environment)
        body = {**body, "item": body["item"].replace("{item}", item_id)}

        response = client.post(_chat_cancellations_path(project_id), json=body)

        assert response.status_code == 400


class TestCreateChatStop:
    REASON = "Replaced by the building that takes the latrine in"

    def _placed(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        person: User,
        environment: Environment,
        *,
        chat: bool = True,
    ) -> tuple[str, str]:
        """A project with a stopped work item, its chat open with a message
        of `person`'s in flight, committed so that a refused call's rollback
        keeps them; the project's id and the work item's."""
        project_id = _make(client, environment_id=environment.id)
        project = session.get_one(Project, uuid.UUID(project_id))
        now = datetime.now(UTC)
        run = models.Session(
            project_id=project.id,
            kind_code="work",
            cwd="/work/Camp",
            token_hash=uuid.uuid4().hex,
            state_code=SessionState.STOPPED,
            turns=1,
            turn_started_at=now,
            turn_ended_at=now,
        )
        session.add(run)
        session.flush()
        session.add(
            Turn(
                session_id=run.id,
                seq=1,
                message="Go.",
                started_at=now,
                ended_at=now,
                cause_code=TurnCause.BRIEF,
            )
        )
        container.record_service().place_work(project, run, "Building the camp")
        if chat:
            opened = open_chat(session, project)
            ChatWriter(session, container.session_record_service(), opened).message(
                person, "The other one builds it."
            )
            opened.state_code = SessionState.RUNNING
        session.commit()
        return project_id, str(run.id)

    def test_with_a_reason_the_work_item_is_closed_for_good_through_the_chat(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        person: User,
        environment: Environment,
    ) -> None:
        project_id, work_id = self._placed(
            client, session, container, person, environment
        )

        response = client.post(
            _chat_stops_path(project_id),
            json={"item": work_id, "reason": self.REASON, "tool_use_id": "toolu_01"},
        )

        assert response.status_code == 201, response.get_json()
        assert response.get_json() == {"effect": "Closed · Building the camp"}
        entry = _timeline_item(client, project_id, work_id)
        assert (
            entry["done"]["cause"],
            entry["done"]["by"]["kind"],
            entry["done"]["undo"],
            entry["work"]["note"],
        ) == ("cancelled", "agent", False, self.REASON)

    def test_an_unknown_project_or_item_is_not_found(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        person: User,
        environment: Environment,
    ) -> None:
        project_id, work_id = self._placed(
            client, session, container, person, environment
        )
        body = {"item": work_id, "reason": self.REASON}

        unknown = client.post(_chat_stops_path(uuid.uuid4()), json=body)
        no_item = client.post(
            _chat_stops_path(project_id), json={**body, "item": str(uuid.uuid4())}
        )

        assert (unknown.status_code, no_item.status_code) == (404, 404)

    def test_a_project_with_no_chat_open_and_a_stop_the_record_refuses_conflict(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        person: User,
        environment: Environment,
    ) -> None:
        closed_id, closed_work = self._placed(
            client, session, container, person, environment, chat=False
        )
        project_id, work_id = self._placed(
            client, session, container, person, environment
        )

        closed = client.post(
            _chat_stops_path(closed_id), json={"item": closed_work, "reason": "Moot"}
        )
        refused = client.post(_chat_stops_path(project_id), json={"item": work_id})

        assert (closed.status_code, refused.status_code) == (409, 409)
        assert closed.get_json()["error"].endswith(
            "because the project has no chat open"
        )
        assert refused.get_json()["error"].endswith("because it is stopped already")

    @pytest.mark.parametrize(
        "body",
        [{"item": "W1"}, {"item": "{item}", "reason": ""}],
        ids=["not-an-items-id", "an-empty-reason"],
    )
    def test_a_body_that_is_not_an_item_and_a_reason_is_invalid(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        person: User,
        environment: Environment,
        body: dict[str, Any],
    ) -> None:
        project_id, work_id = self._placed(
            client, session, container, person, environment
        )
        body = {**body, "item": body["item"].replace("{item}", work_id)}

        response = client.post(_chat_stops_path(project_id), json=body)

        assert response.status_code == 400


@pytest.mark.usefixtures("person")
class TestCreateChatFinish:
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
            person, "We are done."
        )
        if running:
            chat.state_code = SessionState.RUNNING
        session.commit()
        return chat

    def test_with_archive_the_project_is_finished_and_archived_no_question_placed(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        person: User,
        environment: Environment,
    ) -> None:
        project_id = _make(client, name="Camp", environment_id=environment.id)
        chat = self._chat(session, container, project_id, person)

        response = client.post(
            _chat_finish_path(project_id),
            json={"archive": True, "tool_use_id": "toolu_01"},
        )

        assert response.status_code == 201
        assert response.get_json() == {"effect": "Finished and archived · Camp"}
        [record] = [
            stored.record
            for stored in read_records(session, chat.id, limit=10)
            if stored.record.kind_code == "server"
        ]
        assert record.payload["toolUseId"] == "toolu_01"
        project = session.get_one(Project, uuid.UUID(project_id))
        assert (project.state_code, project.archived) == (ProjectState.FINISHED, True)
        kinds = [
            item["kind"]
            for item in client.get(f"/api/projects/{project_id}/timeline").get_json()[
                "items"
            ]
        ]
        assert "archive_question" not in kinds

    def test_without_it_the_project_is_finished_and_asked_whether_to_archive(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        person: User,
        environment: Environment,
    ) -> None:
        project_id = _make(client, name="Camp", environment_id=environment.id)
        self._chat(session, container, project_id, person)

        response = client.post(_chat_finish_path(project_id), json={})

        assert response.status_code == 201
        assert response.get_json() == {"effect": "Finished · Camp"}
        project = session.get_one(Project, uuid.UUID(project_id))
        assert (project.state_code, project.archived) == (ProjectState.FINISHED, False)
        timeline = client.get(f"/api/projects/{project_id}/timeline").get_json()
        assert timeline["items"][-1]["kind"] == "archive_question"

    def test_an_unknown_project_is_not_found(self, client: FlaskClient) -> None:
        response = client.post(_chat_finish_path(uuid.uuid4()), json={})

        assert response.status_code == 404

    def test_no_chat_open_none_in_flight_or_an_archived_project_conflicts(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        person: User,
        environment: Environment,
    ) -> None:
        project_id = _make(client, environment_id=environment.id)

        closed = client.post(_chat_finish_path(project_id), json={})
        chat = self._chat(session, container, project_id, person, running=False)
        idle = client.post(_chat_finish_path(project_id), json={})
        chat.state_code = SessionState.RUNNING
        session.get_one(Project, uuid.UUID(project_id)).archived = True
        session.commit()
        archived = client.post(_chat_finish_path(project_id), json={})

        assert (closed.status_code, idle.status_code, archived.status_code) == (
            409,
            409,
            409,
        )
        assert closed.get_json()["error"].endswith(
            "because the project has no chat open"
        )
        assert idle.get_json()["error"].endswith(
            "because its chat has no turn in flight"
        )
        assert archived.get_json()["error"].endswith(
            "because it is archived, and an archived project takes Bring back alone"
        )

    @pytest.mark.parametrize(
        "body",
        [{"archive": "soon"}, {"archive": True, "by": "ada"}],
        ids=["not-a-flag", "an-unknown-field"],
    )
    def test_a_body_that_is_not_a_finish_is_invalid(
        self, client: FlaskClient, environment: Environment, body: dict[str, Any]
    ) -> None:
        project_id = _make(client, environment_id=environment.id)

        response = client.post(_chat_finish_path(project_id), json=body)

        assert response.status_code == 400


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value)


class TestCreateStoreUpdate:
    """The store's update as `update-store` makes it and asks its lift
    (F144.5): the row alone, which the server takes up from the record."""

    def test_an_update_is_made_its_hold_standing(
        self, client: FlaskClient, session: Session
    ) -> None:
        before = datetime.now(UTC)

        response = client.post(STORE_UPDATE, json={})

        assert response.status_code == 201
        body = response.get_json()
        made = unlifted(session)
        assert made is not None
        assert before <= made.made_at <= datetime.now(UTC)
        assert {**body, "made_at": _at(body["made_at"])} == {
            "id": made.id,
            "made_at": made.made_at,
            "stopped_at": None,
            "reset_at": None,
            "reconciled_at": None,
            "lift_requested_at": None,
            "lifted_at": None,
            "error": None,
        }

    def test_a_second_while_one_is_unlifted_conflicts(
        self, client: FlaskClient, session: Session
    ) -> None:
        standing = hold(session)
        # The refused request rolls back to here.
        session.commit()

        response = client.post(STORE_UPDATE, json={"lift": False})

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot update the store because an update is under way since "
            f"{utc_time(standing.made_at)}"
        )
        assert _count(session, StoreUpdate) == 1

    def test_the_lift_is_asked_of_the_unlifted_update(
        self, client: FlaskClient, session: Session
    ) -> None:
        standing = hold(session)
        before = datetime.now(UTC)

        response = client.post(STORE_UPDATE, json={"lift": True})

        assert response.status_code == 200
        body = response.get_json()
        session.refresh(standing)
        assert standing.lift_requested_at is not None
        assert before <= standing.lift_requested_at <= datetime.now(UTC)
        assert standing.lifted_at is None
        assert (
            body["id"],
            _at(body["made_at"]),
            _at(body["lift_requested_at"]),
            body["lifted_at"],
        ) == (standing.id, standing.made_at, standing.lift_requested_at, None)

    def test_a_lift_with_no_update_under_way_conflicts(
        self, client: FlaskClient, session: Session
    ) -> None:
        lift(session, hold(session))
        session.commit()

        response = client.post(STORE_UPDATE, json={"lift": True})

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot lift the store's update because no update is under way"
        )
        assert _count(session, StoreUpdate) == 1
        assert unlifted(session) is None

    def test_a_body_that_is_not_one_is_invalid(
        self, client: FlaskClient, session: Session
    ) -> None:
        response = client.post(STORE_UPDATE, json={"lift": "maybe"})

        assert response.status_code == 400
        assert _count(session, StoreUpdate) == 0


CARD_WAIT = {
    "kind": "card_wait",
    "title": "ANS-312 is done",
    "cards": ["ANS-312"],
    "states": ["Done"],
}


def _wait(client: FlaskClient, project_id: str, **spec: Any) -> str:
    response = client.post(_waits_path(project_id), json={**CARD_WAIT, **spec})
    assert response.status_code == 201, response.get_json()
    wait_id: str = response.get_json()["id"]
    return wait_id


def _deliver(client: FlaskClient, **changes: Any) -> Any:
    return client.post(f"{TRACKER_EVENTS}/youtrack", json=youtrack_delivery(**changes))


@pytest.mark.usefixtures("person")
class TestCreateWait:
    def test_a_card_wait_is_added_by_the_project_s_session(
        self, client: FlaskClient, environment: Environment
    ) -> None:
        project_id = _make(client, environment_id=environment.id)

        response = client.post(_waits_path(project_id), json=CARD_WAIT)

        assert response.status_code == 201
        item = _timeline_item(client, project_id, response.get_json()["id"])
        assert _within(
            item,
            {
                "kind": "card_wait",
                "form": "wait",
                "title": "ANS-312 is done",
                "done": None,
                "wait": {
                    "cards": ["ANS-312"],
                    "states": ["Done"],
                    "due_at": None,
                    "firings": [],
                    "request": {"label": "Check now", "open": True, "refusal": None},
                    "note": None,
                },
            },
        ), item

    def test_a_timed_wait_placed_before_now_is_past_due(
        self, client: FlaskClient, environment: Environment
    ) -> None:
        project_id = _make(client, environment_id=environment.id)

        wait_id = _wait(
            client,
            project_id,
            kind="timed_wait",
            cards=None,
            states=None,
            due_at="2026-10-20T09:05:00Z",
            placed_at=AT,
        )

        item = _timeline_item(client, project_id, wait_id)
        assert (item["created_at"], item["wait"]["due_at"]) == (
            AT,
            "2026-10-20T09:05:00Z",
        )

    @pytest.mark.parametrize(
        "spec",
        [
            {"cards": None},
            {"due_at": AT},
            {"kind": "timed_wait"},
            {"kind": "timed_wait", "cards": None, "states": None},
            {"title": ""},
        ],
    )
    def test_a_body_with_a_field_of_the_other_kind_or_missing_is_invalid(
        self,
        client: FlaskClient,
        session: Session,
        environment: Environment,
        spec: dict[str, Any],
    ) -> None:
        project_id = _make(client, environment_id=environment.id)

        response = client.post(_waits_path(project_id), json={**CARD_WAIT, **spec})

        assert response.status_code == 400
        assert _count(session, Wait) == 0

    @pytest.mark.parametrize(
        "spec",
        [
            {
                "kind": "timed_wait",
                "cards": None,
                "states": None,
                "due_at": "2099-10-20T09:05:00",
            },
            {"placed_at": "2026-10-20T09:00:00"},
        ],
    )
    def test_a_time_without_its_offset_is_invalid(
        self,
        client: FlaskClient,
        session: Session,
        environment: Environment,
        spec: dict[str, Any],
    ) -> None:
        project_id = _make(client, environment_id=environment.id)

        response = client.post(_waits_path(project_id), json={**CARD_WAIT, **spec})

        assert response.status_code == 400
        assert _count(session, Wait) == 0

    def test_an_unknown_project_is_not_found(self, client: FlaskClient) -> None:
        response = client.post(_waits_path(NO_ROW), json=CARD_WAIT)

        assert response.status_code == 404

    def test_a_wait_the_add_refuses_conflicts(
        self, client: FlaskClient, environment: Environment
    ) -> None:
        project_id = _make(client, environment_id=environment.id)

        response = client.post(
            _waits_path(project_id), json={**CARD_WAIT, "states": []}
        )

        assert response.status_code == 409
        assert response.get_json()["error"].endswith("its `states` list is empty")


@pytest.mark.usefixtures("person")
class TestCreateTrackerEvent:
    """A card's transition delivered past the endpoint's token (R8)."""

    def test_the_card_waits_it_matches_fire_with_no_token(
        self, client: FlaskClient, session: Session, environment: Environment
    ) -> None:
        project_id = _make(client, environment_id=environment.id)
        wait_id = _wait(client, project_id)

        response = _deliver(client)

        assert response.status_code == 200
        assert response.get_json() == {"fired": 1}
        [firing] = _timeline_item(client, project_id, wait_id)["wait"]["firings"]
        assert _within(
            firing,
            {
                "cause": "transition",
                "transition": {
                    "card": "ANS-312",
                    "from_state": "In Progress",
                    "to_state": "Done",
                    "by": "pieter",
                },
                "outcome": "pilots_turn",
            },
        ), firing

    def test_a_delivery_that_matches_no_wait_fires_none(
        self, client: FlaskClient, session: Session, environment: Environment
    ) -> None:
        _wait(client, _make(client, environment_id=environment.id))

        response = _deliver(client, card="ANS-313")

        assert (response.status_code, response.get_json()) == (200, {"fired": 0})
        assert _count(session, WaitFiring) == 0

    def test_a_body_the_adapter_cannot_read_is_invalid(
        self, client: FlaskClient
    ) -> None:
        response = client.post(f"{TRACKER_EVENTS}/youtrack", data=b"not json")

        assert response.status_code == 400

    def test_an_unknown_tracker_is_not_found(self, client: FlaskClient) -> None:
        response = client.post(f"{TRACKER_EVENTS}/jira", json=youtrack_delivery())

        assert response.status_code == 404


@pytest.mark.usefixtures("person")
class TestCreateDueFirings:
    def test_every_open_timed_wait_past_its_due_time_fires_once(
        self, client: FlaskClient, session: Session, environment: Environment
    ) -> None:
        project_id = _make(client, environment_id=environment.id)
        wait_id = _wait(
            client,
            project_id,
            kind="timed_wait",
            cards=None,
            states=None,
            due_at="2026-10-20T09:05:00Z",
            placed_at=AT,
        )

        first = client.post(DUE)
        again = client.post(DUE)

        assert (first.status_code, first.get_json()) == (200, {"fired": 1})
        assert again.get_json() == {"fired": 0}
        [firing] = _timeline_item(client, project_id, wait_id)["wait"]["firings"]
        assert (firing["cause"], firing["outcome"]) == ("due", "pilots_turn")


@pytest.mark.usefixtures("person")
class TestCreateWaitRun:
    @pytest.fixture(autouse=True)
    def _no_callbacks(self) -> Iterator[None]:
        clear_after_commit_callbacks()
        yield
        clear_after_commit_callbacks()

    @pytest.fixture
    def starts(
        self, container: ServiceContainer, supervise: Supervise
    ) -> Iterator[None]:
        """The start the run is placed through, its loops never run."""
        container.session_start_service.override(
            providers.Object(configured_starts(container, supervise))
        )
        try:
            yield
        finally:
            container.session_start_service.reset_override()

    @pytest.mark.usefixtures("starts")
    def test_a_fired_wait_s_run_is_placed(
        self, client: FlaskClient, environment: Environment
    ) -> None:
        project_id = _make(client, environment_id=environment.id)
        wait_id = _wait(client, project_id)
        _deliver(client)

        response = client.post(_wait_run_path(wait_id))

        assert response.status_code == 201
        run = _timeline_item(client, project_id, response.get_json()["id"])
        assert (run["kind"], run["title"], run["work"]["pilots_own"]) == (
            "work",
            'Checking "ANS-312 is done"',
            True,
        )
        assert _timeline_item(client, project_id, wait_id)["wait"]["request"] == {
            "label": "Check now",
            "open": False,
            "refusal": "Pilot is checking",
        }

    @pytest.mark.usefixtures("starts")
    def test_a_wait_with_no_run_due_conflicts(
        self, client: FlaskClient, environment: Environment
    ) -> None:
        wait_id = _wait(client, _make(client, environment_id=environment.id))

        response = client.post(_wait_run_path(wait_id))

        assert response.status_code == 409
        assert "no run of it is due" in response.get_json()["error"]

    def test_with_no_controller_it_conflicts(
        self, client: FlaskClient, environment: Environment
    ) -> None:
        wait_id = _wait(client, _make(client, environment_id=environment.id))
        _deliver(client)

        response = client.post(_wait_run_path(wait_id))

        assert response.status_code == 409

    def test_an_unknown_wait_is_not_found(self, client: FlaskClient) -> None:
        assert client.post(_wait_run_path(NO_ROW)).status_code == 404


@pytest.mark.usefixtures("person")
class TestCreateWaitClose:
    NOTE = "ANS-312 read Done at 09:40; the rollout goes on"

    def test_the_wait_is_done_with_its_note(
        self, client: FlaskClient, environment: Environment
    ) -> None:
        project_id = _make(client, environment_id=environment.id)
        wait_id = _wait(client, project_id)

        response = client.post(_wait_close_path(wait_id), json={"note": self.NOTE})

        assert (response.status_code, response.data) == (204, b"")
        item = _timeline_item(client, project_id, wait_id)
        assert (item["done"]["cause"], item["done"]["by"], item["wait"]["note"]) == (
            "marked",
            PILOT,
            self.NOTE,
        )

    def test_a_missing_note_is_invalid(
        self, client: FlaskClient, environment: Environment
    ) -> None:
        wait_id = _wait(client, _make(client, environment_id=environment.id))

        assert client.post(_wait_close_path(wait_id), json={}).status_code == 400

    def test_a_done_wait_conflicts(
        self, client: FlaskClient, environment: Environment
    ) -> None:
        wait_id = _wait(client, _make(client, environment_id=environment.id))
        client.post(_wait_close_path(wait_id), json={"note": self.NOTE})

        response = client.post(_wait_close_path(wait_id), json={"note": "Again"})

        assert response.status_code == 409
        assert response.get_json()["error"].endswith("the item is done")

    def test_an_unknown_wait_is_not_found(self, client: FlaskClient) -> None:
        response = client.post(_wait_close_path(NO_ROW), json={"note": self.NOTE})

        assert response.status_code == 404


@pytest.mark.usefixtures("service_user")
class TestCreateScenario:
    def test_the_scenario(
        self, client: FlaskClient, session: Session, project: Project
    ) -> None:
        response = client.post(
            SCENARIOS, json={"projects": {"recipe-box": str(project.id)}}
        )

        assert response.status_code == 201
        halving, counting, gears = response.get_json()["transcripts"]
        assert [set(thread) for thread in (halving, counting, gears)] == [
            {"session_id", "agent_id", "adopted_by"}
        ] * 3
        assert (halving["agent_id"], gears["agent_id"]) == (None, None)
        assert counting["session_id"] == halving["session_id"]
        assert counting["agent_id"] is not None
        assert session.execute(
            select(Transcript.session_id, Transcript.agent_id).order_by(
                Transcript.file_modified_at
            )
        ).all() == [
            (counting["session_id"], counting["agent_id"]),
            (halving["session_id"], None),
            (gears["session_id"], None),
        ]
        run = session.scalars(
            select(models.Session).where(
                models.Session.conversation_id == halving["session_id"]
            )
        ).one()
        assert run.project_id == project.id

    def test_the_conversation_of_the_scenarios_group_is_adopted_by_its_project(
        self, client: FlaskClient, session: Session, project: Project
    ) -> None:
        """F152.8: what a spec finds the group's project in the Archived list
        by."""
        response = client.post(
            SCENARIOS, json={"projects": {"recipe-box": str(project.id)}}
        )

        halving, counting, gears = response.get_json()["transcripts"]
        adopted = session.scalars(
            select(Project).where(Project.adopted_group == "bike-log-first-rides")
        ).one()
        assert gears["adopted_by"] == {
            "id": str(adopted.id),
            "name": "Bike log: the first rides",
        }
        assert (halving["adopted_by"], counting["adopted_by"]) == (None, None)
        assert (adopted.state_code, adopted.archived) == (ProjectState.ADOPTED, True)

    def test_a_stage_with_no_service_user_is_a_conflict(
        self,
        client: FlaskClient,
        session: Session,
        project: Project,
        service_user: User,
    ) -> None:
        service_user.kind_code = UserKind.PERSON
        service_user.avatar_slot = 3
        session.flush()

        response = client.post(
            SCENARIOS, json={"projects": {"recipe-box": str(project.id)}}
        )

        assert response.status_code == 409
        assert response.get_json()["code"] == "NO_SERVICE_USER"
        assert response.get_json()["error"] == (
            "Cannot make the adopted project of the group 'bike-log-first-rides'"
            " because the stage has no service user to make it"
        )

    def test_a_second_load_replaces_the_first(
        self, client: FlaskClient, session: Session, project: Project
    ) -> None:
        body = {"projects": {"recipe-box": str(project.id)}}

        first = client.post(SCENARIOS, json=body)
        second = client.post(SCENARIOS, json=body)

        assert second.status_code == 201
        assert second.get_json() == first.get_json()
        assert _count(session, Transcript) == 3

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({}, id="no projects"),
            pytest.param({"projects": {"recipe-box": "camp"}}, id="no id"),
        ],
    )
    def test_a_request_out_of_shape_is_refused(
        self, client: FlaskClient, session: Session, body: dict[str, Any]
    ) -> None:
        assert client.post(SCENARIOS, json=body).status_code == 400
        assert _count(session, Transcript) == 0

    def test_a_project_the_scenario_has_no_turn_on_is_refused(
        self, client: FlaskClient, session: Session, project: Project
    ) -> None:
        response = client.post(
            SCENARIOS, json={"projects": {"bike-log": str(project.id)}}
        )

        assert response.status_code == 400
        assert response.get_json()["error"] == (
            "Cannot load the scenario because `projects` gives a project for "
            "`bike-log`, and the scenario's Turns of Pilot's are on `recipe-box`"
        )
        assert _count(session, Transcript) == 0

    def test_an_unknown_project_is_not_found(
        self, client: FlaskClient, session: Session
    ) -> None:
        response = client.post(
            SCENARIOS, json={"projects": {"recipe-box": str(NO_ROW)}}
        )

        assert response.status_code == 404
        assert _count(session, Transcript) == 0


class TestCreateWalk:
    @pytest.fixture
    def ada(self, container: ServiceContainer, person: User) -> Iterator[SSEConnection]:
        """A connection of the person's."""
        manager = container.sse_connection_manager()
        connection = manager.on_connect("ada-1", person.subject)
        yield connection
        manager.on_disconnect(connection)

    @staticmethod
    def _events(connection: SSEConnection) -> list[dict[str, Any]]:
        queued = []
        while True:
            try:
                frame = connection.next_frame(timeout=0)
            except Empty:
                return queued
            assert frame is not None
            queued.append(json.loads(frame.removeprefix("data: ")))

    def test_a_walk_is_ended_as_a_collector_tells_its_end(
        self, client: FlaskClient, session: Session, ada: SSEConnection
    ) -> None:
        response = client.post(WALKS)

        assert response.status_code == 201
        [ended_at] = session.scalars(select(Walk.ended_at)).all()
        assert response.get_json() == {
            "ended_at": ended_at.isoformat().replace("+00:00", "Z"),
            "announced": False,
        }
        assert self._events(ada) == []

    @pytest.mark.usefixtures("service_user")
    def test_the_walk_after_a_scenarios_load_raises_the_event_and_the_next_none(
        self, client: FlaskClient, project: Project, ada: SSEConnection
    ) -> None:
        """F152.14: what a spec that loaded a scenario sees the event by."""
        loaded = client.post(
            SCENARIOS, json={"projects": {"recipe-box": str(project.id)}}
        )
        assert loaded.status_code == 201
        assert self._events(ada) == []

        first = client.post(WALKS).get_json()

        assert first["announced"] is True
        assert self._events(ada) == [
            {"type": "collection_changed", "payload": {"as_of": first["ended_at"]}}
        ]

        second = client.post(WALKS).get_json()

        assert second["announced"] is False
        assert self._events(ada) == []


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
        counted = (User, Environment, Project, StoreUpdate)
        before = [_count(session, model) for model in counted]

        response = client.post(path, json=body)

        assert response.status_code == 400
        assert response.get_json()["error"] == (
            "The record's testing endpoints are not available on prd"
        )
        assert [_count(session, model) for model in counted] == before

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
