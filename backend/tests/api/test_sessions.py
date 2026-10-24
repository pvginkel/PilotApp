"""The session routes: the records by page, the stream's subscribe (design 2
§11.1, §11.2), and a work item's Stop and Resume (F67)."""

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
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.models import Project, Turn, User
from app.models.reference import RecordKind, SessionState
from app.services.container import ServiceContainer
from app.services.environment_service import EnvironmentService
from app.services.relay_service import RelayService
from app.services.session_record_service import SessionRecordService
from app.services.session_start_service import SessionStartService
from app.services.session_stream_service import STREAM_VIEWS
from app.services.sse_connection_manager import SSEConnection, SSEConnectionManager
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.supervisor import Supervise, metric_value

LOCAL_ADMIN = "local-user"
SUBJECT = "subject-ada"

type Connect = Callable[..., SSEConnection]


@pytest.fixture(autouse=True)
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


@pytest.fixture
def records(container: ServiceContainer) -> SessionRecordService:
    return container.session_record_service()


@pytest.fixture
def connect(container: ServiceContainer) -> Iterator[Connect]:
    """Opens a test connection, the local admin's unless a subject is given;
    the teardown ends every one still open."""
    manager: SSEConnectionManager = container.sse_connection_manager()
    opened: list[SSEConnection] = []

    def open_one(request_id: str, subject: str | None = None) -> SSEConnection:
        connection = manager.on_connect(
            request_id, subject or LOCAL_ADMIN, local_admin=subject is None
        )
        opened.append(connection)
        return connection

    yield open_one
    for connection in opened:
        manager.on_disconnect(connection)


def frames(connection: SSEConnection) -> list[dict[str, Any]]:
    queued = []
    while True:
        try:
            frame = connection.next_frame(timeout=0)
        except Empty:
            return queued
        assert frame is not None
        queued.append(json.loads(frame.removeprefix("data: "))["payload"])


def sign_in(client: FlaskClient, subject: str) -> None:
    response = client.post(
        "/api/testing/auth/session", json={"subject": subject, "roles": ["editor"]}
    )
    assert response.status_code == 201, response.get_json()


def write(container: ServiceContainer, run: models.Session, words: str) -> None:
    with scoped_session(container):
        container.session_record_service().append(
            run.id, RecordKind.SERVER, payload={"text": words}
        )


class TestGetSessionRecords:
    def test_it_answers_each_kind_in_the_record_shape(
        self,
        session: DbSession,
        client: FlaskClient,
        records: SessionRecordService,
        person: User,
        project_session: models.Session,
    ) -> None:
        records.append(project_session.id, RecordKind.SERVER, payload={"text": "Up"})
        turn = Turn(
            session_id=project_session.id,
            seq=1,
            author_user_id=person.id,
            message="What next?",
            started_at=datetime.now(UTC),
        )
        session.add(turn)
        session.flush()
        records.append(project_session.id, RecordKind.SEND, turn_id=turn.id)
        records.append(
            project_session.id,
            RecordKind.CLAUDE,
            payload={"type": "assistant", "message": {"content": []}},
            turn_id=turn.id,
            raw_offset=512,
            controller_session="pilot-1",
        )
        records.append(
            project_session.id,
            RecordKind.CLAUDE,
            payload="not json",
            turn_id=turn.id,
            raw_offset=521,
            controller_session="pilot-1",
        )
        records.append(
            project_session.id,
            RecordKind.RESULT,
            payload={
                "turn": 1,
                "result": "Done",
                "isError": False,
                "interrupted": False,
            },
            turn_id=turn.id,
            raw_offset=521,
            controller_session="pilot-1",
        )

        response = client.get(f"/api/sessions/{project_session.id}/records")

        assert response.status_code == 200
        body = response.get_json()
        assert body["ended"] is False
        for record in body["records"]:
            assert datetime.fromisoformat(record.pop("at")).tzinfo is not None
        assert body["records"] == [
            {"seq": 1, "turn": None, "kind": "server", "payload": {"text": "Up"}},
            {
                "seq": 2,
                "turn": 1,
                "kind": "send",
                "author": "ada",
                "message": "What next?",
            },
            {
                "seq": 3,
                "turn": 1,
                "kind": "claude",
                "payload": {"type": "assistant", "message": {"content": []}},
                "raw_offset": 512,
            },
            {
                "seq": 4,
                "turn": 1,
                "kind": "claude",
                "payload": "not json",
                "raw_offset": 521,
            },
            {
                "seq": 5,
                "turn": 1,
                "kind": "result",
                "payload": {
                    "turn": 1,
                    "result": "Done",
                    "isError": False,
                    "interrupted": False,
                },
            },
        ]

    def test_it_pages_after_a_record_number(
        self,
        client: FlaskClient,
        records: SessionRecordService,
        project_session: models.Session,
    ) -> None:
        for n in range(5):
            records.append(project_session.id, RecordKind.SERVER, payload={"n": n})

        response = client.get(
            f"/api/sessions/{project_session.id}/records?after=2&limit=2"
        )

        assert response.status_code == 200
        assert [r["seq"] for r in response.get_json()["records"]] == [3, 4]

    def test_a_page_holds_200_records_by_default_and_1000_at_most(
        self,
        client: FlaskClient,
        records: SessionRecordService,
        project_session: models.Session,
    ) -> None:
        for n in range(201):
            records.append(project_session.id, RecordKind.SERVER, payload={"n": n})
        url = f"/api/sessions/{project_session.id}/records"

        assert len(client.get(url).get_json()["records"]) == 200
        assert len(client.get(f"{url}?limit=1000").get_json()["records"]) == 201
        assert client.get(f"{url}?limit=1001").status_code == 400

    @pytest.mark.parametrize(
        "query", ["after=-1", "limit=0", "after=one", "limit=", "from=3"]
    )
    def test_it_refuses_a_bad_query(
        self, client: FlaskClient, project_session: models.Session, query: str
    ) -> None:
        response = client.get(f"/api/sessions/{project_session.id}/records?{query}")

        assert response.status_code == 400

    def test_a_page_with_the_last_record_of_an_ended_session_ends(
        self,
        session: DbSession,
        client: FlaskClient,
        records: SessionRecordService,
        project_session: models.Session,
    ) -> None:
        for n in range(3):
            records.append(project_session.id, RecordKind.SERVER, payload={"n": n})
        project_session.state_code = SessionState.ENDED
        session.flush()
        url = f"/api/sessions/{project_session.id}/records"

        assert client.get(f"{url}?after=0&limit=2").get_json()["ended"] is False
        assert client.get(f"{url}?after=2&limit=2").get_json()["ended"] is True
        assert client.get(f"{url}?after=3").get_json() == {"records": [], "ended": True}

    def test_it_answers_404_for_an_unknown_session(self, client: FlaskClient) -> None:
        response = client.get(f"/api/sessions/{uuid.uuid4()}/records")

        assert response.status_code == 404

    def test_it_answers_404_for_a_path_that_is_no_session_id(
        self, client: FlaskClient
    ) -> None:
        assert client.get("/api/sessions/not-a-uuid/records").status_code == 404


class TestSubscribeSessionStream:
    def test_it_subscribes_the_callers_connection(
        self,
        container: ServiceContainer,
        client: FlaskClient,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        connection = connect("req-1")

        response = client.post(
            f"/api/sessions/{project_session.id}/stream",
            json={"request_id": "req-1", "view": "chat"},
        )
        write(container, project_session, "Live")

        assert response.status_code == 204
        [payload] = frames(connection)
        assert payload["frame"] == "record"
        assert payload["data"]["payload"] == {"text": "Live"}

    def test_a_signed_in_user_subscribes_their_own_connection(
        self,
        container: ServiceContainer,
        client: FlaskClient,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        sign_in(client, SUBJECT)
        connection = connect("req-ada", SUBJECT)

        response = client.post(
            f"/api/sessions/{project_session.id}/stream",
            json={"request_id": "req-ada", "view": "chat"},
        )
        write(container, project_session, "For Ada")

        assert response.status_code == 204
        assert len(frames(connection)) == 1

    def test_it_answers_409_not_connected_with_no_connection_on_this_process(
        self, client: FlaskClient, project_session: models.Session
    ) -> None:
        response = client.post(
            f"/api/sessions/{project_session.id}/stream",
            json={"request_id": "req-elsewhere", "view": "chat"},
        )

        assert response.status_code == 409
        assert response.get_json()["code"] == "NOT_CONNECTED"

    def test_it_answers_403_for_another_users_connection(
        self,
        container: ServiceContainer,
        client: FlaskClient,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        sign_in(client, SUBJECT)
        theirs = connect("req-grace", "subject-grace")

        response = client.post(
            f"/api/sessions/{project_session.id}/stream",
            json={"request_id": "req-grace", "view": "chat"},
        )
        write(container, project_session, "Not for Ada")

        assert response.status_code == 403
        assert frames(theirs) == []

    def test_the_local_admin_may_not_subscribe_a_users_connection(
        self,
        client: FlaskClient,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        connect("req-grace", "subject-grace")

        response = client.post(
            f"/api/sessions/{project_session.id}/stream",
            json={"request_id": "req-grace", "view": "chat"},
        )

        assert response.status_code == 403

    def test_it_answers_404_for_an_unknown_session(
        self, client: FlaskClient, connect: Connect
    ) -> None:
        connect("req-1")

        response = client.post(
            f"/api/sessions/{uuid.uuid4()}/stream",
            json={"request_id": "req-1", "view": "chat"},
        )

        assert response.status_code == 404
        assert metric_value(STREAM_VIEWS) == 0

    @pytest.mark.parametrize(
        "body",
        [
            {"request_id": "req-1"},
            {"view": "chat"},
            {"request_id": "", "view": "chat"},
            {"request_id": "req-1", "view": ""},
            {"request_id": "req-1", "view": "v" * 256},
            {"request_id": "req-1", "view": "chat", "after": 3},
        ],
    )
    def test_it_refuses_a_bad_body(
        self,
        client: FlaskClient,
        connect: Connect,
        project_session: models.Session,
        body: dict[str, Any],
    ) -> None:
        connect("req-1")

        response = client.post(f"/api/sessions/{project_session.id}/stream", json=body)

        assert response.status_code == 400
        assert metric_value(STREAM_VIEWS) == 0


class TestUnsubscribeSessionStream:
    def test_one_delete_leaves_the_connections_other_view(
        self,
        container: ServiceContainer,
        client: FlaskClient,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        connection = connect("req-1")
        url = f"/api/sessions/{project_session.id}/stream"
        for view in ("chat", "overlay"):
            assert (
                client.post(url, json={"request_id": "req-1", "view": view}).status_code
                == 204
            )

        first = client.delete(url, json={"request_id": "req-1", "view": "chat"})
        write(container, project_session, "Still open")

        assert first.status_code == 204
        assert len(frames(connection)) == 1

        second = client.delete(url, json={"request_id": "req-1", "view": "overlay"})
        write(container, project_session, "Closed")

        assert second.status_code == 204
        assert frames(connection) == []
        assert metric_value(STREAM_VIEWS) == 0

    def test_delete_is_idempotent(
        self, client: FlaskClient, connect: Connect, project_session: models.Session
    ) -> None:
        connect("req-1")
        url = f"/api/sessions/{project_session.id}/stream"
        client.post(url, json={"request_id": "req-1", "view": "chat"})

        for _ in range(2):
            response = client.delete(url, json={"request_id": "req-1", "view": "chat"})
            assert response.status_code == 204
        gone = client.delete(url, json={"request_id": "req-gone", "view": "chat"})

        assert gone.status_code == 204

    def test_it_answers_403_for_another_users_connection(
        self,
        container: ServiceContainer,
        client: FlaskClient,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        theirs = connect("req-grace", "subject-grace")
        container.session_stream_service().subscribe(
            project_session.id, "req-grace", "chat", "subject-grace"
        )
        sign_in(client, SUBJECT)

        response = client.delete(
            f"/api/sessions/{project_session.id}/stream",
            json={"request_id": "req-grace", "view": "chat"},
        )
        write(container, project_session, "Still Grace's")

        assert response.status_code == 403
        assert len(frames(theirs)) == 1

    def test_it_answers_404_for_an_unknown_session(self, client: FlaskClient) -> None:
        response = client.delete(
            f"/api/sessions/{uuid.uuid4()}/stream",
            json={"request_id": "req-1", "view": "chat"},
        )

        assert response.status_code == 404

    def test_it_refuses_a_bad_body(
        self, client: FlaskClient, project_session: models.Session
    ) -> None:
        response = client.delete(
            f"/api/sessions/{project_session.id}/stream", json={"view": "chat"}
        )

        assert response.status_code == 400


class TestReplacedConnection:
    def test_a_replaced_connection_starts_with_no_view(
        self,
        container: ServiceContainer,
        client: FlaskClient,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        connect("req-1")
        client.post(
            f"/api/sessions/{project_session.id}/stream",
            json={"request_id": "req-1", "view": "chat"},
        )

        replacement = connect("req-1")
        write(container, project_session, "After the reconnect")

        assert frames(replacement) == []
        assert metric_value(STREAM_VIEWS) == 0


class TestTheEditorGate:
    def test_the_routes_refuse_a_caller_without_the_editor_role(
        self, app: Flask, client: FlaskClient, project_session: models.Session
    ) -> None:
        response = client.post(
            "/api/testing/auth/session", json={"subject": SUBJECT, "roles": []}
        )
        assert response.status_code == 201
        url = f"/api/sessions/{project_session.id}"
        body = {"request_id": "req-1", "view": "chat"}

        assert client.get(f"{url}/records").status_code == 403
        assert client.post(f"{url}/stream", json=body).status_code == 403
        assert client.delete(f"{url}/stream", json=body).status_code == 403


def _work_item(
    container: ServiceContainer,
    session: DbSession,
    project: Project,
    run: models.Session,
    state: SessionState,
) -> models.Session:
    """`run` placed as a work item, in `state`, its brief's turn ended
    unless it runs."""
    container.record_service().place_work(project, run, "Build the camp")
    now = datetime.now(UTC)
    session.add(
        Turn(
            session_id=run.id,
            seq=1,
            message="The brief",
            started_at=now,
            ended_at=None if state == SessionState.RUNNING else now,
        )
    )
    run.state_code = state
    run.turns = 1
    session.flush()
    clear_after_commit_callbacks()
    return run


def _starts(
    container: ServiceContainer, supervise: Supervise, *, controller_configured: bool
) -> SessionStartService:
    """The session starts, on a supervisor of their own whose loops never run."""
    supervisor, _ = supervise(container)
    environments = EnvironmentService(
        container=container, supervisor=supervisor, stop_after_seconds=1800
    )
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
        ),
        controller_outage=container.controller_outage(),
        controller_configured=controller_configured,
    )


@pytest.fixture
def starts(container: ServiceContainer, supervise: Supervise) -> Iterator[None]:
    """The routes' session starts with a controller configured."""
    container.session_start_service.override(
        providers.Object(_starts(container, supervise, controller_configured=True))
    )
    try:
        yield
    finally:
        container.session_start_service.reset_last_overriding()


class TestStopSession:
    def test_it_stops_the_work_item_and_answers_its_status(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        project: Project,
        project_session: models.Session,
    ) -> None:
        run = _work_item(
            container, session, project, project_session, SessionState.RUNNING
        )
        sign_in(client, SUBJECT)

        response = client.post(f"/api/sessions/{run.id}/stop")

        assert response.status_code == 200, response.get_json()
        body = response.get_json()
        assert (body["state"], body["current_line"]) == ("stopped", None)
        assert body["stopped_at"] is not None
        assert body["stopped_by"]["handle"] == "ada"
        assert session.get_one(models.Session, run.id).stopped_by_user_id == person.id

    @pytest.mark.parametrize(
        ("state", "refusal"),
        [
            (SessionState.IDLE, "its turn has ended"),
            (SessionState.STOPPED, "it is stopped already"),
        ],
    )
    def test_a_work_item_it_cannot_stop_is_409(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        project: Project,
        project_session: models.Session,
        state: SessionState,
        refusal: str,
    ) -> None:
        run = _work_item(container, session, project, project_session, state)
        sign_in(client, SUBJECT)

        response = client.post(f"/api/sessions/{run.id}/stop")

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            f"Cannot stop Build the camp because {refusal}"
        )

    def test_a_session_with_no_work_item_is_409(
        self,
        client: FlaskClient,
        person: User,
        project_session: models.Session,
    ) -> None:
        sign_in(client, SUBJECT)

        response = client.post(f"/api/sessions/{project_session.id}/stop")

        assert response.status_code == 409

    def test_a_caller_without_a_handle_is_409(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        project: Project,
        project_session: models.Session,
    ) -> None:
        run = _work_item(
            container, session, project, project_session, SessionState.RUNNING
        )
        sign_in(client, "subject-newcomer")

        response = client.post(f"/api/sessions/{run.id}/stop")

        assert response.status_code == 409
        assert "you have not chosen your handle yet" in response.get_json()["error"]

    def test_an_unknown_session_is_404(self, client: FlaskClient, person: User) -> None:
        sign_in(client, SUBJECT)

        response = client.post(f"/api/sessions/{uuid.uuid4()}/stop")

        assert response.status_code == 404

    def test_without_the_editor_role_it_is_403(
        self, client: FlaskClient, project_session: models.Session
    ) -> None:
        response = client.post(
            "/api/testing/auth/session", json={"subject": SUBJECT, "roles": []}
        )
        assert response.status_code == 201

        response = client.post(f"/api/sessions/{project_session.id}/stop")

        assert response.status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.post(f"/api/sessions/{uuid.uuid4()}/stop")

        assert response.status_code == 401


@pytest.mark.usefixtures("starts")
class TestResumeSession:
    def test_it_resumes_the_work_item_through_the_gate(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        project: Project,
        project_session: models.Session,
    ) -> None:
        run = _work_item(
            container, session, project, project_session, SessionState.STOPPED
        )
        sign_in(client, SUBJECT)

        response = client.post(f"/api/sessions/{run.id}/resume")

        assert response.status_code == 200, response.get_json()
        body = response.get_json()
        assert (body["state"], body["held_reason"]) == ("starting", None)
        assert body["current_line"]["text"] == "Starting Example-1…"
        assert [
            turn.message
            for turn in session.scalars(
                select(Turn).where(Turn.session_id == run.id).order_by(Turn.seq)
            )
        ] == ["The brief", "The brief"]

    def test_in_a_paused_project_it_answers_the_work_item_held(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        project: Project,
        project_session: models.Session,
    ) -> None:
        run = _work_item(
            container, session, project, project_session, SessionState.FAILED
        )
        project.paused = True
        session.flush()
        sign_in(client, SUBJECT)

        response = client.post(f"/api/sessions/{run.id}/resume")

        assert response.status_code == 200
        body = response.get_json()
        assert (body["state"], body["held_reason"], body["error"]) == (
            "held",
            "paused",
            None,
        )

    def test_a_work_item_it_cannot_resume_is_409(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        project: Project,
        project_session: models.Session,
    ) -> None:
        run = _work_item(
            container, session, project, project_session, SessionState.RUNNING
        )
        sign_in(client, SUBJECT)

        response = client.post(f"/api/sessions/{run.id}/resume")

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot resume Build the camp because it is running"
        )

    def test_an_unknown_session_is_404(self, client: FlaskClient, person: User) -> None:
        sign_in(client, SUBJECT)

        response = client.post(f"/api/sessions/{uuid.uuid4()}/resume")

        assert response.status_code == 404

    def test_without_the_editor_role_it_is_403(
        self, client: FlaskClient, project_session: models.Session
    ) -> None:
        response = client.post(
            "/api/testing/auth/session", json={"subject": SUBJECT, "roles": []}
        )
        assert response.status_code == 201

        response = client.post(f"/api/sessions/{project_session.id}/resume")

        assert response.status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.post(f"/api/sessions/{uuid.uuid4()}/resume")

        assert response.status_code == 401
