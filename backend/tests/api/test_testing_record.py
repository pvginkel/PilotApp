"""/api/testing/{people,environments,projects}: the record's states the UI
cannot make (TEST-6)."""

import uuid
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Environment, Item, Project, User

PEOPLE = "/api/testing/people"
ENVIRONMENTS = "/api/testing/environments"
PROJECTS = "/api/testing/projects"


def _count(session: Session, model: Any) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


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
        assert _count(session, Item) == 1

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

    def test_a_name_whose_draft_has_a_fault_is_refused(
        self, client: FlaskClient
    ) -> None:
        response = client.post(
            PROJECTS,
            json={"members": ["ada"], "name": "Box\n\n```question id=Q1\nnope: 1\n```"},
        )

        assert response.status_code == 409


class TestOutsideTesting:
    @pytest.mark.parametrize(
        ("path", "body"),
        [
            (PEOPLE, {"handle": "ben"}),
            (ENVIRONMENTS, {"id": "example-env-2", "name": "Example-2"}),
            (PROJECTS, {"members": ["ada"]}),
        ],
    )
    def test_every_endpoint_is_refused_in_production(
        self,
        app: Flask,
        client: FlaskClient,
        session: Session,
        monkeypatch: pytest.MonkeyPatch,
        path: str,
        body: dict[str, Any],
    ) -> None:
        monkeypatch.setattr(app.container.config(), "flask_env", "production")

        response = client.post(path, json=body)

        assert response.status_code == 400
        assert (_count(session, User), _count(session, Environment)) == (1, 0)
