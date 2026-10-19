"""The session routes: the records by page, and the stream's subscribe (design
2 §11.1, §11.2)."""

import json
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from queue import Empty
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.models import Turn, User
from app.models.reference import RecordKind, SessionState
from app.services.container import ServiceContainer
from app.services.session_record_service import SessionRecordService
from app.services.session_stream_service import STREAM_VIEWS
from app.services.sse_connection_manager import SSEConnection, SSEConnectionManager
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.supervisor import metric_value

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
