"""/api/projects: the project list, the archived projects and a project's
head, as the signed-in person reads them (F1, F2, F3, D2)."""

import uuid
from datetime import datetime
from typing import Any

import pytest
from flask.testing import FlaskClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Environment, ProjectTransition
from app.models.reference import TransitionKind
from app.schemas.testing_record import InventedProjectCreateSchema
from app.services.container import ServiceContainer

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
                    "member": True,
                    "progress": {"done": 0, "total": 0, "in_progress": []},
                },
                {
                    "id": str(recipes),
                    "name": "Recipe box",
                    "ticket": "RB-12",
                    "state": "open",
                    "finished_at": None,
                    "member": False,
                    "progress": {
                        "done": 1,
                        "total": 3,
                        "in_progress": ["Build the card page"],
                    },
                },
                {
                    "id": str(finished),
                    "name": "Bike log",
                    "ticket": None,
                    "state": "finished",
                    "finished_at": "<the finish>",
                    "member": True,
                    "progress": {"done": 0, "total": 0, "in_progress": []},
                },
            ]
        }

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
            "open_items": 2,
        }

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
