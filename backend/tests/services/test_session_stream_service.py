"""The hub: a Session's live frames on the browsers' SSE connections (design 2
§11.1, §11.3), read off test connections' queues."""

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
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
    PARTIAL_WINDOW_SECONDS,
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


@dataclass
class _Timer:
    seconds: float
    run: Callable[[], None]
    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True


@dataclass
class _Time:
    """The hub's clock, which a test moves, and the timers it started, which a
    test runs."""

    now: float = 1000.0
    timers: list[_Timer] = field(default_factory=list)

    def clock(self) -> float:
        return self.now

    def start_timer(self, seconds: float, run: Callable[[], None]) -> _Timer:
        timer = _Timer(seconds, run)
        self.timers.append(timer)
        return timer

    def pass_(self, seconds: float) -> None:
        self.now += seconds


def block_start(index: int = 0) -> dict[str, Any]:
    return {
        "type": "stream_event",
        "parent_tool_use_id": None,
        "uuid": f"start-{index}",
        "event": {
            "type": "content_block_start",
            "index": index,
            "content_block": {"type": "text", "text": ""},
        },
    }


def text_delta(text: str, index: int = 0) -> dict[str, Any]:
    return {
        "type": "stream_event",
        "parent_tool_use_id": None,
        "uuid": f"delta-{text}",
        "event": {
            "type": "content_block_delta",
            "index": index,
            "delta": {"type": "text_delta", "text": text},
        },
    }


def partials(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    assert all(p["frame"] == "partial" for p in payloads)
    return [p["data"] for p in payloads]


class TestTheTextWindow:
    """A turn's text is one `partial` frame per window at most (F40.4), on a
    clock and timers the test holds."""

    @pytest.fixture
    def time(self) -> _Time:
        return _Time()

    @pytest.fixture
    def streams(
        self,
        streams: SessionStreamService,
        time: _Time,
        monkeypatch: pytest.MonkeyPatch,
    ) -> SessionStreamService:
        """The hubs, on the test's clock and timers."""
        monkeypatch.setattr(streams, "_clock", time.clock)
        monkeypatch.setattr(streams, "_start_timer", time.start_timer)
        return streams

    @pytest.fixture
    def connection(
        self,
        streams: SessionStreamService,
        connect: Connect,
        project_session: models.Session,
    ) -> SSEConnection:
        connection = connect("req-1")
        streams.subscribe(project_session.id, "req-1", "chat", SUBJECT)
        return connection

    def test_a_blocks_start_and_its_first_delta_go_out_at_once_as_they_are(
        self,
        streams: SessionStreamService,
        time: _Time,
        connection: SSEConnection,
        project_session: models.Session,
    ) -> None:
        streams.forward_partial(project_session.id, block_start())
        streams.forward_partial(project_session.id, text_delta("The dome "))

        assert partials(frames(connection)) == [block_start(), text_delta("The dome ")]
        assert time.timers == []

    def test_the_deltas_inside_one_window_go_out_as_one_frame_at_its_end(
        self,
        streams: SessionStreamService,
        time: _Time,
        connection: SSEConnection,
        project_session: models.Session,
    ) -> None:
        streams.forward_partial(project_session.id, text_delta("The dome "))
        frames(connection)

        time.pass_(0.05)
        assert streams.forward_partial(project_session.id, text_delta("is ")) is True
        time.pass_(0.05)
        streams.forward_partial(project_session.id, text_delta("lighter, "))
        time.pass_(0.05)
        streams.forward_partial(project_session.id, text_delta("and dry."))

        assert frames(connection) == []
        [timer] = time.timers
        assert timer.seconds == pytest.approx(PARTIAL_WINDOW_SECONDS - 0.05)

        time.pass_(0.05)
        timer.run()

        # The window's first delta, as `claude` printed it, with the text of
        # the three.
        joined = text_delta("is ")
        joined["event"]["delta"]["text"] = "is lighter, and dry."
        assert partials(frames(connection)) == [joined]

    def test_a_held_frame_opens_the_next_window(
        self,
        streams: SessionStreamService,
        time: _Time,
        connection: SSEConnection,
        project_session: models.Session,
    ) -> None:
        streams.forward_partial(project_session.id, text_delta("One "))
        time.pass_(0.1)
        streams.forward_partial(project_session.id, text_delta("two "))
        time.pass_(0.1)
        time.timers[0].run()
        frames(connection)

        # Inside the window the held frame opened: held to its end.
        time.pass_(0.15)
        streams.forward_partial(project_session.id, text_delta("three "))
        assert frames(connection) == []
        assert time.timers[1].seconds == pytest.approx(PARTIAL_WINDOW_SECONDS - 0.15)
        time.pass_(0.05)
        time.timers[1].run()
        assert partials(frames(connection)) == [text_delta("three ")]

        # After a window with no text in it: at once.
        time.pass_(PARTIAL_WINDOW_SECONDS)
        streams.forward_partial(project_session.id, text_delta("four."))
        assert partials(frames(connection)) == [text_delta("four.")]
        assert len(time.timers) == 2

    def test_a_record_flushes_the_text_before_it(
        self,
        container: ServiceContainer,
        streams: SessionStreamService,
        time: _Time,
        connection: SSEConnection,
        project_session: models.Session,
    ) -> None:
        streams.forward_partial(project_session.id, text_delta("The dome "))
        time.pass_(0.05)
        streams.forward_partial(project_session.id, text_delta("is "))
        streams.forward_partial(project_session.id, text_delta("lighter."))
        frames(connection)

        write(container, project_session, "The dome is lighter.")

        text, record = frames(connection)
        joined = text_delta("is ")
        joined["event"]["delta"]["text"] = "is lighter."
        assert (text["frame"], text["data"]) == ("partial", joined)
        assert (record["frame"], record["data"]["seq"]) == ("record", 1)
        [timer] = time.timers
        assert timer.cancelled

    def test_a_wake_with_no_record_leaves_the_text_held(
        self,
        streams: SessionStreamService,
        time: _Time,
        connection: SSEConnection,
        project_session: models.Session,
    ) -> None:
        streams.forward_partial(project_session.id, text_delta("The dome "))
        streams.forward_partial(project_session.id, text_delta("is lighter."))
        frames(connection)

        streams.wake(project_session.id)

        assert frames(connection) == []
        assert not time.timers[0].cancelled

    def test_the_next_blocks_start_flushes_the_last_ones_text(
        self,
        streams: SessionStreamService,
        time: _Time,
        connection: SSEConnection,
        project_session: models.Session,
    ) -> None:
        streams.forward_partial(project_session.id, block_start())
        streams.forward_partial(project_session.id, text_delta("The dome "))
        time.pass_(0.05)
        streams.forward_partial(project_session.id, text_delta("is lighter."))
        frames(connection)

        streams.forward_partial(project_session.id, block_start(1))

        assert partials(frames(connection)) == [
            text_delta("is lighter."),
            block_start(1),
        ]
        assert time.timers[0].cancelled

        # The flushed text opened a window, which holds the next block's.
        streams.forward_partial(project_session.id, text_delta("The tunnel ", 1))
        assert frames(connection) == []
        time.pass_(PARTIAL_WINDOW_SECONDS)
        time.timers[1].run()
        assert partials(frames(connection)) == [text_delta("The tunnel ", 1)]

    def test_a_timer_cancelled_too_late_leaves_the_next_windows_text(
        self,
        container: ServiceContainer,
        streams: SessionStreamService,
        time: _Time,
        connection: SSEConnection,
        project_session: models.Session,
    ) -> None:
        streams.forward_partial(project_session.id, text_delta("One "))
        streams.forward_partial(project_session.id, text_delta("two "))
        write(container, project_session, "One two")
        streams.forward_partial(project_session.id, text_delta("three."))
        frames(connection)
        first, second = time.timers

        first.run()
        assert frames(connection) == []

        second.run()
        assert partials(frames(connection)) == [text_delta("three.")]

    def test_a_timer_that_runs_after_its_text_went_out_pushes_nothing(
        self,
        container: ServiceContainer,
        streams: SessionStreamService,
        time: _Time,
        connection: SSEConnection,
        project_session: models.Session,
    ) -> None:
        streams.forward_partial(project_session.id, text_delta("One "))
        streams.forward_partial(project_session.id, text_delta("two."))
        write(container, project_session, "One two.")
        frames(connection)

        time.timers[0].run()

        assert frames(connection) == []

    def test_end_follows_the_held_text(
        self,
        session: DbSession,
        streams: SessionStreamService,
        time: _Time,
        connection: SSEConnection,
        project_session: models.Session,
    ) -> None:
        streams.forward_partial(project_session.id, text_delta("One "))
        streams.forward_partial(project_session.id, text_delta("two."))
        frames(connection)
        project_session.state_code = SessionState.ENDED
        session.flush()

        streams.wake(project_session.id)

        assert frames(connection) == [
            {
                "session": str(project_session.id),
                "frame": "partial",
                "data": text_delta("two."),
            },
            {"session": str(project_session.id), "frame": "end"},
        ]

    def test_the_text_held_for_views_that_went_reaches_no_later_view(
        self,
        manager: SSEConnectionManager,
        streams: SessionStreamService,
        time: _Time,
        connection: SSEConnection,
        connect: Connect,
        project_session: models.Session,
    ) -> None:
        streams.forward_partial(project_session.id, text_delta("One "))
        streams.forward_partial(project_session.id, text_delta("two."))
        manager.on_disconnect(connection)
        later = connect("req-2")
        streams.subscribe(project_session.id, "req-2", "chat", SUBJECT)

        time.timers[0].run()

        assert frames(later) == []

    def test_each_session_has_a_window_of_its_own(
        self,
        session: DbSession,
        streams: SessionStreamService,
        time: _Time,
        connection: SSEConnection,
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
        streams.subscribe(other.id, "req-1", "chat", SUBJECT)

        streams.forward_partial(project_session.id, text_delta("Here "))
        streams.forward_partial(other.id, text_delta("There "))

        assert [(p["session"], p["data"]) for p in frames(connection)] == [
            (str(project_session.id), text_delta("Here ")),
            (str(other.id), text_delta("There ")),
        ]
        assert time.timers == []


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
            message="The chat's brief.\n\nPlease look at the badge.",
            words="Please look at the badge.",
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
