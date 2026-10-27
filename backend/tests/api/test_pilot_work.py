"""`pilot-work`'s routes (TD §4.5, F85): the REST calls Pilot's MCP server
makes for a worker session's tools, under the session's bearer, outside `/api/`
(review 2), pinned as the surface they are."""

import uuid
from datetime import UTC, datetime

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import (
    Attachment,
    Document,
    Environment,
    Item,
    ItemAttachment,
    Project,
    Turn,
)
from app.models.reference import SessionState
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerClient
from app.services.pilot_server import token_hash
from app.services.session_record_service import read_records
from tests.support.fake_controller import ServedFakeController, client_of

DOCUMENTS = "/tools/pilot-work/documents"

ATTACHMENTS = "/tools/pilot-work/attachments"

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
    state: SessionState = SessionState.RUNNING,
) -> models.Session:
    """A Session of `kind` whose bearer is `TOKEN`, running unless `state`
    says otherwise; a work one with its Work."""
    run = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code=kind,
        cwd="/work/Example",
        token_hash=token_hash(TOKEN),
        state_code=state,
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
    def test_the_surface_is_two_routes_outside_the_api(self, app: Flask) -> None:
        routes = sorted(
            (rule.rule, sorted(rule.methods - {"HEAD", "OPTIONS"}))
            for rule in app.url_map.iter_rules()
            if rule.endpoint.startswith("pilot_work.")
        )

        assert routes == [(ATTACHMENTS, ["POST"]), (DOCUMENTS, ["POST"])]

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

    def test_a_stopped_session_is_403_and_mints_nothing(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(
            session, container, project, environment, state=SessionState.STOPPED
        )
        _file(fake_controller, environment)

        response = client.post(DOCUMENTS, json={"path": PATH}, headers=_bearer())

        assert response.status_code == 403
        assert response.get_json()["error"] == (
            f"Cannot call pilot-work because session {run.id} has no turn running"
        )
        assert session.scalars(select(Document)).all() == []

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


class TestAttachFile:
    """`POST /tools/pilot-work/attachments`: `attach_file(path, to?)`."""

    def test_a_folder_attached_is_201_with_its_attachments_ids(
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
        fake_controller.add_environment(environment.id)
        fake_controller.put_file(environment.id, "/work/Example/out/a.md", b"# A\n")
        fake_controller.put_file(environment.id, "/work/Example/out/b/c.md", b"C")

        response = client.post(
            ATTACHMENTS, json={"path": "/work/Example/out"}, headers=_bearer()
        )

        assert response.status_code == 201
        body = response.get_json()
        assert list(body) == ["ids"]
        attachments = [
            session.get_one(Attachment, uuid.UUID(id_)) for id_ in body["ids"]
        ]
        assert [
            (attachment.filename, attachment.source_path, attachment.batch)
            for attachment in attachments
        ] == [
            ("a.md", "/work/Example/out/a.md", 1),
            ("b/c.md", "/work/Example/out/b/c.md", 1),
        ]
        assert {attachment.created_by_session_id for attachment in attachments} == {
            run.id
        }

    def test_to_names_the_item_they_hang_on(
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
        registered = client.post(DOCUMENTS, json={"path": PATH}, headers=_bearer())
        to = registered.get_json()["id"]

        response = client.post(
            ATTACHMENTS, json={"path": PATH, "to": to}, headers=_bearer()
        )

        assert response.status_code == 201
        [attachment_id] = response.get_json()["ids"]
        hung = session.scalars(
            select(ItemAttachment.attachment_id).where(
                ItemAttachment.item_id == uuid.UUID(to)
            )
        ).all()
        assert hung == [uuid.UUID(attachment_id)]

    def test_an_item_not_of_the_sessions_project_is_404(
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
        to = uuid.uuid4()

        response = client.post(
            ATTACHMENTS, json={"path": PATH, "to": str(to)}, headers=_bearer()
        )

        assert response.status_code == 404
        assert response.get_json()["error"] == f"Item {to} was not found"

    def test_no_bearer_is_401(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        _session(session, container, project, environment)

        response = client.post(ATTACHMENTS, json={"path": PATH})

        assert response.status_code == 401
        assert response.get_json()["error"] == (
            "Cannot call pilot-work because the request carries no bearer"
        )

    def test_a_session_that_is_not_a_work_items_is_403(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        _session(session, container, project, environment, kind="chat")

        response = client.post(ATTACHMENTS, json={"path": PATH}, headers=_bearer())

        assert response.status_code == 403

    def test_a_session_whose_turn_has_ended_is_403_and_attaches_nothing(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(
            session, container, project, environment, state=SessionState.IDLE
        )
        _file(fake_controller, environment)

        response = client.post(ATTACHMENTS, json={"path": PATH}, headers=_bearer())

        assert response.status_code == 403
        assert response.get_json()["error"] == (
            f"Cannot call pilot-work because session {run.id} has no turn running"
        )
        assert session.scalars(select(Attachment)).all() == []

    @pytest.mark.parametrize(
        "body",
        [{}, {"path": ""}, {"path": PATH, "to": "x"}, {"path": PATH, "as": "x"}],
    )
    def test_a_body_that_is_not_a_path_and_an_item_is_400(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        body: dict[str, str],
    ) -> None:
        _session(session, container, project, environment)

        response = client.post(ATTACHMENTS, json=body, headers=_bearer())

        assert response.status_code == 400

    def test_a_file_that_cannot_be_copied_is_409_with_the_reason(
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

        response = client.post(ATTACHMENTS, json={"path": PATH}, headers=_bearer())

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            f"Cannot attach {PATH} because the controller answered 404 not-found:"
            f" no such file or directory: {PATH!r}"
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

        response = client.post(ATTACHMENTS, json={"path": PATH}, headers=_bearer())

        assert response.status_code == 502
        assert "503 environment-unreadable" in response.get_json()["error"]


class TestTheToolUseId:
    """The `Tool-Use-Id` header Pilot's MCP server passes names the call in
    its effect's record (F41)."""

    def _turn_in_flight(self, session: DbSession, run: models.Session) -> None:
        session.add(
            Turn(
                session_id=run.id,
                seq=1,
                message="Refine the camp.",
                started_at=datetime.now(UTC),
            )
        )
        session.flush()

    def test_a_registration_names_its_call(
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
        self._turn_in_flight(session, run)
        _file(fake_controller, environment)

        response = client.post(
            DOCUMENTS,
            json={"path": PATH},
            headers=_bearer() | {"Tool-Use-Id": "toolu_01ABC"},
        )

        assert response.status_code == 201
        [record] = read_records(session, run.id, limit=10)
        assert record.record.payload == {
            "type": "effect",
            "toolUseId": "toolu_01ABC",
            "effect": {
                "verb": "Registered",
                "label": "inbox/2",
                "itemId": response.get_json()["id"],
            },
        }

    def test_an_attachment_without_the_header_names_no_call(
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
        self._turn_in_flight(session, run)
        _file(fake_controller, environment)

        response = client.post(ATTACHMENTS, json={"path": PATH}, headers=_bearer())

        assert response.status_code == 201
        [record] = read_records(session, run.id, limit=10)
        assert record.record.payload["toolUseId"] is None
        assert record.record.payload["effect"]["verb"] == "Attached"
