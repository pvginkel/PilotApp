"""The hub: a Session's live frames on the browsers' SSE connections (design 2
§11.1, §11.3), read off test connections' queues."""

import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from queue import Empty
from typing import Any

import pytest
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.exceptions import AuthorizationException
from app.models import Environment, Project, Turn
from app.models.reference import RecordKind, SessionState
from app.services.container import ServiceContainer
from app.services.session_record_service import (
    SessionRecordService,
    read_records,
    to_record_schema,
)
from app.services.session_stream_service import (
    STREAM_VIEWS,
    SessionStreamService,
    StreamNotConnectedException,
)
from app.services.sse_connection_manager import SSEConnection, SSEConnectionManager
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.supervisor import metric_value

SUBJECT = "subject-ada"

type Connect = Callable[..., SSEConnection]


@pytest.fixture(autouse=True)
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


@pytest.fixture
def manager(container: ServiceContainer) -> SSEConnectionManager:
    return container.sse_connection_manager()


@pytest.fixture
def streams(container: ServiceContainer) -> SessionStreamService:
    return container.session_stream_service()


@pytest.fixture
def connect(manager: SSEConnectionManager) -> Iterator[Connect]:
    """Opens a test connection, as the stream route registers one; the teardown
    ends every one still open, which drops their views."""
    opened: list[SSEConnection] = []

    def open_one(
        request_id: str, subject: str | None = SUBJECT, *, local_admin: bool = False
    ) -> SSEConnection:
        connection = manager.on_connect(request_id, subject, local_admin=local_admin)
        opened.append(connection)
        return connection

    yield open_one
    for connection in opened:
        manager.on_disconnect(connection)


def frames(connection: SSEConnection) -> list[dict[str, Any]]:
    """The `session` events queued on the connection, in order."""
    queued = []
    while True:
        try:
            frame = connection.next_frame(timeout=0)
        except Empty:
            return queued
        assert frame is not None
        event = json.loads(frame.removeprefix("data: "))
        assert event["type"] == "session"
        queued.append(event["payload"])


def seqs(payloads: list[dict[str, Any]]) -> list[int]:
    return [p["data"]["seq"] for p in payloads if p["frame"] == "record"]


def write(container: ServiceContainer, run: models.Session, words: str) -> None:
    """One `server` record, in a transaction of its own."""
    with scoped_session(container):
        container.session_record_service().append(
            run.id, RecordKind.SERVER, payload={"text": words}
        )


def frames_data(
    container: ServiceContainer, run: models.Session, seq: int
) -> dict[str, Any]:
    """The record's `data`, as the records route's page has it."""
    [stored] = read_records(container.db_session(), run.id, after=seq - 1, limit=1)
    return to_record_schema(stored).model_dump(mode="json")


class TestSubscribe:
    def test_a_view_receives_each_record_committed_after_it(
        self,
        container: ServiceContainer,
        streams: SessionStreamService,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        connection = connect("req-1")
        streams.subscribe(project_session.id, "req-1", "chat", SUBJECT)

        write(container, project_session, "Starting Example-1…")

        [payload] = frames(connection)
        assert payload["session"] == str(project_session.id)
        assert payload["frame"] == "record"
        data = payload["data"]
        assert data["seq"] == 1
        assert data["kind"] == "server"
        assert data["turn"] is None
        assert data["payload"] == {"text": "Starting Example-1…"}
        assert datetime.fromisoformat(data["at"]).tzinfo is not None

    def test_a_record_committed_before_the_subscribe_is_the_pages(
        self,
        container: ServiceContainer,
        streams: SessionStreamService,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        write(container, project_session, "Before")
        connection = connect("req-1")
        streams.subscribe(project_session.id, "req-1", "chat", SUBJECT)

        write(container, project_session, "After")

        assert seqs(frames(connection)) == [2]

    def test_it_refuses_a_request_id_with_no_connection_on_this_process(
        self, streams: SessionStreamService, project_session: models.Session
    ) -> None:
        with pytest.raises(StreamNotConnectedException) as refused:
            streams.subscribe(project_session.id, "req-elsewhere", "chat", SUBJECT)

        assert refused.value.error_code == "NOT_CONNECTED"
        assert metric_value(STREAM_VIEWS) == 0

    def test_it_refuses_another_users_connection(
        self,
        container: ServiceContainer,
        streams: SessionStreamService,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        connection = connect("req-theirs", "subject-grace")

        with pytest.raises(AuthorizationException):
            streams.subscribe(project_session.id, "req-theirs", "chat", SUBJECT)

        write(container, project_session, "Not for Ada")
        assert frames(connection) == []
        assert metric_value(STREAM_VIEWS) == 0

    def test_it_refuses_a_connection_bound_to_no_subject(
        self,
        streams: SessionStreamService,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        connect("req-unbound", None)

        with pytest.raises(AuthorizationException):
            streams.subscribe(project_session.id, "req-unbound", "chat", None)

    def test_the_local_admins_connection_is_anyones(
        self,
        container: ServiceContainer,
        streams: SessionStreamService,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        connection = connect("req-admin", "local-user", local_admin=True)
        streams.subscribe(project_session.id, "req-admin", "chat", "local-user")

        write(container, project_session, "Hello")

        assert seqs(frames(connection)) == [1]

    def test_two_connections_each_receive_every_record_once(
        self,
        container: ServiceContainer,
        streams: SessionStreamService,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        first, second = connect("req-1"), connect("req-2")
        streams.subscribe(project_session.id, "req-1", "chat", SUBJECT)
        streams.subscribe(project_session.id, "req-2", "overlay", SUBJECT)

        write(container, project_session, "One")
        write(container, project_session, "Two")

        assert seqs(frames(first)) == [1, 2]
        assert seqs(frames(second)) == [1, 2]

    def test_another_sessions_records_do_not_reach_the_view(
        self,
        session: DbSession,
        container: ServiceContainer,
        streams: SessionStreamService,
        connect: Connect,
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        other = models.Session(
            project_id=project.id,
            environment_id=environment.id,
            kind_code="chat",
            cwd="/work/Example",
            token_hash="2" * 64,
            state_code=SessionState.RUNNING,
        )
        session.add(other)
        session.flush()
        connection = connect("req-1")
        streams.subscribe(project_session.id, "req-1", "chat", SUBJECT)

        write(container, other, "Elsewhere")

        assert frames(connection) == []


class TestTheCommit:
    """A subscriber never sees a record before its transaction commits (§10)."""

    def test_no_frame_before_the_commit(
        self,
        container: ServiceContainer,
        streams: SessionStreamService,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        connection = connect("req-1")
        streams.subscribe(project_session.id, "req-1", "chat", SUBJECT)

        with scoped_session(container):
            container.session_record_service().append(
                project_session.id, RecordKind.SERVER, payload={"text": "Pending"}
            )
            assert frames(connection) == []

        assert seqs(frames(connection)) == [1]

    def test_no_frame_for_a_rollback(
        self,
        container: ServiceContainer,
        streams: SessionStreamService,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        connection = connect("req-1")
        streams.subscribe(project_session.id, "req-1", "chat", SUBJECT)

        with pytest.raises(RuntimeError), scoped_session(container):
            container.session_record_service().append(
                project_session.id, RecordKind.SERVER, payload={"text": "Lost"}
            )
            raise RuntimeError("the transaction fails")

        assert frames(connection) == []

    def test_a_transactions_records_go_out_in_order_on_its_one_wake(
        self,
        container: ServiceContainer,
        streams: SessionStreamService,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        connection = connect("req-1")
        streams.subscribe(project_session.id, "req-1", "chat", SUBJECT)

        with scoped_session(container):
            records: SessionRecordService = container.session_record_service()
            for n in range(3):
                records.append(project_session.id, RecordKind.SERVER, payload={"n": n})

        assert seqs(frames(connection)) == [1, 2, 3]


class TestWake:
    def test_a_wake_pushes_what_another_writer_committed_and_nothing_twice(
        self,
        session: DbSession,
        container: ServiceContainer,
        streams: SessionStreamService,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        connection = connect("req-1")
        streams.subscribe(project_session.id, "req-1", "chat", SUBJECT)
        # Another pod's writer: committed, and no wake here.
        records: SessionRecordService = container.session_record_service()
        records.append(project_session.id, RecordKind.SERVER, payload={"n": 1})
        records.append(project_session.id, RecordKind.SERVER, payload={"n": 2})
        session.flush()
        clear_after_commit_callbacks()

        streams.wake(project_session.id)
        streams.wake(project_session.id)

        assert seqs(frames(connection)) == [1, 2]

    def test_a_wake_without_a_hub_reads_nothing(
        self,
        container: ServiceContainer,
        streams: SessionStreamService,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        connection = connect("req-1")

        write(container, project_session, "Unseen")
        streams.wake(project_session.id)

        assert frames(connection) == []

    @pytest.mark.parametrize("state", [SessionState.ENDED, SessionState.FAILED])
    def test_end_follows_the_last_record_once(
        self,
        session: DbSession,
        container: ServiceContainer,
        streams: SessionStreamService,
        connect: Connect,
        project_session: models.Session,
        state: SessionState,
    ) -> None:
        connection = connect("req-1")
        streams.subscribe(project_session.id, "req-1", "chat", SUBJECT)

        with scoped_session(container):
            container.session_record_service().append(
                project_session.id, RecordKind.SERVER, payload={"text": "Done"}
            )
            project_session.state_code = state
        streams.wake(project_session.id)

        assert frames(connection) == [
            {
                "session": str(project_session.id),
                "frame": "record",
                "data": frames_data(container, project_session, 1),
            },
            {"session": str(project_session.id), "frame": "end"},
        ]

    @pytest.mark.parametrize(
        "state",
        [SessionState.RUNNING, SessionState.IDLE, SessionState.STOPPED],
    )
    def test_a_stream_that_continues_has_no_end(
        self,
        session: DbSession,
        container: ServiceContainer,
        streams: SessionStreamService,
        connect: Connect,
        project_session: models.Session,
        state: SessionState,
    ) -> None:
        connection = connect("req-1")
        streams.subscribe(project_session.id, "req-1", "chat", SUBJECT)
        project_session.state_code = state
        session.flush()

        write(container, project_session, "More to come")

        assert [p["frame"] for p in frames(connection)] == ["record"]


class TestForwardPartial:
    LINE = {
        "type": "stream_event",
        "parent_tool_use_id": None,
        "event": {"type": "content_block_delta", "delta": {"type": "text_delta"}},
    }

    def test_a_partial_goes_out_verbatim_after_the_records_before_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        streams: SessionStreamService,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        connection = connect("req-1")
        streams.subscribe(project_session.id, "req-1", "chat", SUBJECT)
        container.session_record_service().append(
            project_session.id, RecordKind.SERVER, payload={"text": "Before"}
        )
        session.flush()
        clear_after_commit_callbacks()

        assert streams.forward_partial(project_session.id, self.LINE) is True

        record, partial = frames(connection)
        assert record["frame"] == "record"
        assert partial == {
            "session": str(project_session.id),
            "frame": "partial",
            "data": self.LINE,
        }

    def test_with_no_view_a_partial_goes_nowhere(
        self,
        streams: SessionStreamService,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        connection = connect("req-1")

        assert streams.forward_partial(project_session.id, self.LINE) is False
        assert frames(connection) == []


class TestViews:
    def test_two_views_on_one_connection_one_delete_leaves_the_other(
        self,
        container: ServiceContainer,
        streams: SessionStreamService,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        connection = connect("req-1")
        streams.subscribe(project_session.id, "req-1", "chat", SUBJECT)
        streams.subscribe(project_session.id, "req-1", "overlay", SUBJECT)
        assert metric_value(STREAM_VIEWS) == 2

        streams.unsubscribe(project_session.id, "req-1", "chat", SUBJECT)
        write(container, project_session, "Still open")

        assert seqs(frames(connection)) == [1]
        assert metric_value(STREAM_VIEWS) == 1

        streams.unsubscribe(project_session.id, "req-1", "overlay", SUBJECT)
        write(container, project_session, "Nobody looks")

        assert frames(connection) == []
        assert metric_value(STREAM_VIEWS) == 0

    def test_a_view_subscribed_twice_is_one_view(
        self,
        container: ServiceContainer,
        streams: SessionStreamService,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        connection = connect("req-1")
        streams.subscribe(project_session.id, "req-1", "chat", SUBJECT)
        streams.subscribe(project_session.id, "req-1", "chat", SUBJECT)

        write(container, project_session, "Once")

        assert seqs(frames(connection)) == [1]
        assert metric_value(STREAM_VIEWS) == 1

    def test_unsubscribe_is_idempotent(
        self,
        streams: SessionStreamService,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        connect("req-1")
        streams.subscribe(project_session.id, "req-1", "chat", SUBJECT)

        streams.unsubscribe(project_session.id, "req-1", "chat", SUBJECT)
        streams.unsubscribe(project_session.id, "req-1", "chat", SUBJECT)
        streams.unsubscribe(project_session.id, "req-gone", "chat", SUBJECT)

        assert metric_value(STREAM_VIEWS) == 0

    def test_unsubscribe_refuses_another_users_connection(
        self,
        container: ServiceContainer,
        streams: SessionStreamService,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        connection = connect("req-theirs", "subject-grace")
        streams.subscribe(project_session.id, "req-theirs", "chat", "subject-grace")

        with pytest.raises(AuthorizationException):
            streams.unsubscribe(project_session.id, "req-theirs", "chat", SUBJECT)

        write(container, project_session, "Still Grace's")
        assert seqs(frames(connection)) == [1]

    def test_a_connection_that_goes_takes_its_views(
        self,
        manager: SSEConnectionManager,
        streams: SessionStreamService,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        connection = connect("req-1")
        streams.subscribe(project_session.id, "req-1", "chat", SUBJECT)
        streams.subscribe(project_session.id, "req-1", "overlay", SUBJECT)

        manager.on_disconnect(connection)

        assert metric_value(STREAM_VIEWS) == 0
        assert (
            streams.forward_partial(project_session.id, {"type": "stream_event"})
            is False
        )

    def test_a_replaced_connection_starts_with_no_view(
        self,
        container: ServiceContainer,
        streams: SessionStreamService,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        connect("req-1")
        streams.subscribe(project_session.id, "req-1", "chat", SUBJECT)

        replacement = connect("req-1")
        write(container, project_session, "After the reconnect")

        assert frames(replacement) == []
        assert metric_value(STREAM_VIEWS) == 0

    def test_a_connection_that_goes_leaves_the_other_connections_views(
        self,
        manager: SSEConnectionManager,
        container: ServiceContainer,
        streams: SessionStreamService,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        leaving, staying = connect("req-1"), connect("req-2")
        streams.subscribe(project_session.id, "req-1", "chat", SUBJECT)
        streams.subscribe(project_session.id, "req-2", "chat", SUBJECT)

        manager.on_disconnect(leaving)
        write(container, project_session, "Still here")

        assert seqs(frames(staying)) == [1]
        assert metric_value(STREAM_VIEWS) == 1


class TestSendRecords:
    def test_a_send_goes_out_with_its_turns_author_and_words(
        self,
        session: DbSession,
        container: ServiceContainer,
        streams: SessionStreamService,
        connect: Connect,
        person: models.User,
        project_session: models.Session,
    ) -> None:
        turn = Turn(
            session_id=project_session.id,
            seq=1,
            author_user_id=person.id,
            message="Please look at the badge.",
            started_at=datetime.now(UTC),
        )
        session.add(turn)
        session.flush()
        connection = connect("req-1")
        streams.subscribe(project_session.id, "req-1", "chat", SUBJECT)

        with scoped_session(container):
            container.session_record_service().append(
                project_session.id, RecordKind.SEND, turn_id=turn.id
            )

        [payload] = frames(connection)
        data = payload["data"]
        assert (data["kind"], data["turn"], data["author"], data["message"]) == (
            "send",
            1,
            "ada",
            "Please look at the badge.",
        )
        assert "payload" not in data
