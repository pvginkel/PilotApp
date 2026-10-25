"""`pilot-work`'s routes (TD §4.5, F85): the REST calls Pilot's MCP server
makes for a worker session's tools, under the session's bearer, outside `/api/`
(review 2), pinned as the surface they are."""

import uuid

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import Document, Environment, Item, Project
from app.models.reference import SessionState
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerClient
from app.services.pilot_server import token_hash
from tests.support.fake_controller import ServedFakeController, client_of

DOCUMENTS = "/tools/pilot-work/documents"

TOKEN = "worker-token"

PATH = "/work/Example/docs/refinement.md"

TEXT = "Two options for the camp.\n\n```question id=Q1\n```\n"


def _bearer(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _session(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
    environment: Environment,
    kind: str = "work",
) -> models.Session:
    """A running Session of `kind` whose bearer is `TOKEN`; a work one with
    its Work."""
    run = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code=kind,
        cwd="/work/Example",
        token_hash=token_hash(TOKEN),
        state_code=SessionState.RUNNING,
    )
    session.add(run)
    session.flush()
    if kind == "work":
        container.record_service().place_work(project, run, "Refining the camp")
    return run


def _file(fake_controller: ServedFakeController, environment: Environment) -> None:
    fake_controller.add_environment(environment.id)
    fake_controller.put_file(environment.id, PATH, TEXT.encode())


class TestPilotWorkRoutes:
    def test_the_surface_is_one_route_outside_the_api(self, app: Flask) -> None:
        routes = sorted(
            (rule.rule, sorted(rule.methods - {"HEAD", "OPTIONS"}))
            for rule in app.url_map.iter_rules()
            if rule.endpoint.startswith("pilot_work.")
        )

        assert routes == [(DOCUMENTS, ["POST"])]

    def test_the_routes_are_outside_the_oidc_gate(
        self,
        oidc_app: Flask,
        oidc_client: FlaskClient,
        session: DbSession,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        assert oidc_app.container.config().oidc_enabled
        client_of(oidc_app.container, fake_controller)
        _session(session, oidc_app.container, project, environment)
        _file(fake_controller, environment)

        response = oidc_client.post(DOCUMENTS, json={"path": PATH}, headers=_bearer())

        assert response.status_code == 201


class TestRegisterDocument:
    """`POST /tools/pilot-work/documents`: `register_document(path)`."""

    def test_a_file_registered_is_201_with_its_items_id(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        _file(fake_controller, environment)

        response = client.post(DOCUMENTS, json={"path": PATH}, headers=_bearer())

        assert response.status_code == 201
        body = response.get_json()
        assert list(body) == ["id"]
        item = session.get_one(Item, uuid.UUID(body["id"]))
        assert (item.project_id, item.kind_code, item.created_by_session_id) == (
            project.id,
            "review",
            run.id,
        )
        assert session.get_one(Document, item.id).source_path == PATH

    def test_the_path_registered_again_is_200_with_the_same_id(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        _session(session, container, project, environment)
        _file(fake_controller, environment)
        first = client.post(DOCUMENTS, json={"path": PATH}, headers=_bearer())

        again = client.post(DOCUMENTS, json={"path": PATH}, headers=_bearer())

        assert again.status_code == 200
        assert again.get_json() == first.get_json()

    @pytest.mark.parametrize(
        ("headers", "error"),
        [
            ({}, "Cannot call pilot-work because the request carries no bearer"),
            (
                _bearer("an-unknown-token"),
                "Cannot call pilot-work because no session has the request's bearer",
            ),
        ],
    )
    def test_no_bearer_or_an_unknown_one_is_401(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        headers: dict[str, str],
        error: str,
    ) -> None:
        _session(session, container, project, environment)

        response = client.post(DOCUMENTS, json={"path": PATH}, headers=headers)

        assert response.status_code == 401
        assert response.get_json()["error"] == error

    def test_a_session_that_is_not_a_work_items_is_403(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment, kind="chat")

        response = client.post(DOCUMENTS, json={"path": PATH}, headers=_bearer())

        assert response.status_code == 403
        assert response.get_json()["error"] == (
            f"Cannot call pilot-work because session {run.id} is a chat session,"
            " not a work item's"
        )

    def test_the_gate_answers_before_the_body_is_read(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        response = client.post(DOCUMENTS, json={"paths": [PATH]})

        assert response.status_code == 401

    @pytest.mark.parametrize("body", [{}, {"path": ""}, {"path": PATH, "to": "x"}])
    def test_a_body_that_is_not_a_path_is_400(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        body: dict[str, str],
    ) -> None:
        _session(session, container, project, environment)

        response = client.post(DOCUMENTS, json=body, headers=_bearer())

        assert response.status_code == 400

    def test_a_file_that_cannot_be_registered_is_409_with_the_reason(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        _session(session, container, project, environment)
        fake_controller.add_environment(environment.id)
        fake_controller.put_file(environment.id, PATH, b"```question id=Q1\n")

        response = client.post(DOCUMENTS, json={"path": PATH}, headers=_bearer())

        assert response.status_code == 409
        error = response.get_json()["error"]
        assert error.startswith(
            f"Cannot register document {PATH} because its text holds faults: line 1: "
        )

    def test_a_controller_that_cannot_read_the_environment_is_502(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        _session(session, container, project, environment)
        _file(fake_controller, environment)
        fake_controller.unreadable(environment.id)

        response = client.post(DOCUMENTS, json={"path": PATH}, headers=_bearer())

        assert response.status_code == 502
        assert "503 environment-unreadable" in response.get_json()["error"]
