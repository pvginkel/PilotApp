"""/api/testing/{people,environments,projects,items}: the record's states the
UI cannot make (TEST-6), on every stage but prd, behind the API's sign-in
(D027): among them the handbook an open project is born with, an agent's
saves of the project's draft and handbook, and Pilot's Done."""

import base64
import uuid
from datetime import datetime
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import STAGES, Settings, Stage, default_stage
from app.config import Environment as SettingsEnvironment
from app.models import (
    Attachment,
    Document,
    DocumentVersion,
    Environment,
    Item,
    Project,
    User,
)
from app.models.reference import ProjectState, VersionCause
from app.schemas.testing_record import OPENING_WORDS
from app.services.container import ServiceContainer

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


def _turn_ends_path(project_id: uuid.UUID | str) -> str:
    return f"{PROJECTS}/{project_id}/turn-ends"


def _document_saves_path(project_id: uuid.UUID | str, document: str) -> str:
    return f"{PROJECTS}/{project_id}/{document}/saves"


def _done_path(item_id: uuid.UUID | str) -> str:
    return f"/api/testing/items/{item_id}/done"


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


ENDPOINTS = [
    (PEOPLE, {"handle": "ben"}),
    (ENVIRONMENTS, {"id": "example-env-2", "name": "Example-2"}),
    (PROJECTS, {"members": ["ada"]}),
    (_items_path(uuid.uuid4()), {"kind": "notice", "title": "Camp", "text": "Hi"}),
    (_saves_path(uuid.uuid4()), {"text": "Hi"}),
    (_attachments_path(uuid.uuid4()), {"files": [_file("a.md", b"Hi")]}),
    (_turn_ends_path(uuid.uuid4()), {}),
    (_document_saves_path(uuid.uuid4(), "draft"), {"text": "Hi"}),
    (_document_saves_path(uuid.uuid4(), "handbook"), {"text": "Hi"}),
    (_done_path(uuid.uuid4()), {}),
]


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
