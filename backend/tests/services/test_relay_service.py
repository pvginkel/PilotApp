"""The send and the relay (design 2 §9, §9.6; D004; F40.1's records, F40.4's
relay; V03, V06, V13, V15).

The send's tests and the relay's run on the test's session: the relay's run is
called as its loop calls it, once the fake holds the turn. The loop's tests run
it on a database of its own, from the send's commit, as the supervisor does."""

import json
import time
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from queue import Empty
from typing import Any, Literal

import pytest
from flask import Flask
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from werkzeug.wrappers import Request, Response

from app import models
from app.core_exceptions import ExternalServiceException
from app.database import scoped_session
from app.engine.bus import EngineEvent, ProjectChanged, WorkMoved
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import (
    Document,
    DocumentVersion,
    Environment,
    Item,
    Project,
    Turn,
    User,
)
from app.models.reference import RecordKind, SessionState, UserKind, VersionCause
from app.schemas.timeline import StopCause
from app.services.container import ServiceContainer
from app.services.controller_client import (
    ControllerClient,
    EnvironmentStatus,
    HeadlessCreateRequest,
)
from app.services.environment_service import SHUTDOWN_TIMER, EnvironmentService
from app.services.fake_controller import FakeControllerProblem, FinishOutcome
from app.services.pilot_server import PilotServer, token_hash
from app.services.relay_service import (
    CONTINUE,
    ENVIRONMENT_STOPPED,
    PARTIALS_FORWARDED_TOTAL,
    RELAYS_RUNNING,
    RESTARTING,
    SEND_FAILED,
    SESSION_GONE,
    RelayService,
)
from app.services.session_record_service import (
    RECORDS_WRITTEN_TOTAL,
    StoredRecord,
    read_records,
)
from app.services.sse_connection_manager import SSEConnection
from app.services.start_gate import WorkSlots
from app.services.supervisor import TIMER_RUNS_TOTAL, LoopHandle
from app.services.turn_end_read_service import READ_JOB, TurnEndReadService
from app.utils import after_commit as after_commit_module
from app.utils.after_commit import clear_after_commit_callbacks
from app.utils.lifecycle_coordinator import LifecycleCoordinator
from tests.support.fake_controller import ServedFakeController, client_of, raw_turn
from tests.support.supervisor import (
    LogWaiter,
    Supervise,
    listening,
    metric_value,
    wait_until,
)

ENV = "env-a"
NOTES = "/work/Example/notes.md"
MCP_URL = "https://pilot-mcp.example.com/mcp"
SUBJECT = "subject-ada"
STOP_AFTER = timedelta(minutes=30)
SUPERVISOR_LOGGER = "app.services.supervisor"


@pytest.fixture(autouse=True)
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


def _relay_service(
    container: ServiceContainer, supervise: Supervise, mcp_url: str | None = None
) -> tuple[RelayService, LifecycleCoordinator]:
    """The relays on a supervisor of their own; their re-creates hand Pilot's
    MCP server at `mcp_url`, none when it is None."""
    supervisor, coordinator = supervise(container)
    environments = EnvironmentService(
        container=container,
        supervisor=supervisor,
        stop_after_seconds=STOP_AFTER.total_seconds(),
        delete_after_seconds=timedelta(days=7).total_seconds(),
    )
    relays = RelayService(
        container=container,
        supervisor=supervisor,
        session_streams=container.session_stream_service(),
        environment_service=environments,
        work_slots=WorkSlots(work_max=3, project_max=3),
        pilot_server=PilotServer(mcp_url),
        turn_end_reads=TurnEndReadService(
            container=container,
            supervisor=supervisor,
            session_streams=container.session_stream_service(),
        ),
    )
    return relays, coordinator


@pytest.fixture
def relays(
    container: ServiceContainer,
    controller_client: ControllerClient,
    supervise: Supervise,
) -> RelayService:
    """The relays on the test's session; no loop of theirs ever runs."""
    return _relay_service(container, supervise)[0]


def _headless(fake: ServedFakeController, client: ControllerClient) -> str:
    """A running environment with one idle headless session; its name."""
    fake.add_environment(ENV, status="running")
    return client.create_headless_session(ENV, HeadlessCreateRequest()).name


@pytest.fixture
def controller_session(
    fake_controller: ServedFakeController, controller_client: ControllerClient
) -> str:
    return _headless(fake_controller, controller_client)


def _environment_row(
    db: DbSession, *, pod: datetime | None = None, due: datetime | None = None
) -> Environment:
    """The environment's row, as Pilot's own start left it, its claim on the pod
    that started at `pod`."""
    row = Environment(
        id=ENV,
        name="Env-A",
        exempt=False,
        last_state="running",
        server_started_at=datetime.now(UTC) - timedelta(hours=1),
        started_pod_at=pod,
        stop_due_at=due,
    )
    db.add(row)
    db.flush()
    return row


def _agent_session(
    db: DbSession,
    project: Project,
    controller_session: str | None,
    state: SessionState = SessionState.IDLE,
) -> models.Session:
    run = models.Session(
        project_id=project.id,
        environment_id=ENV,
        kind_code="work",
        cwd="/work/Example",
        controller_session=controller_session,
        token_hash=uuid.uuid4().hex,
        state_code=state,
    )
    db.add(run)
    db.flush()
    return run


@pytest.fixture
def idle(
    session: DbSession, project: Project, controller_session: str
) -> models.Session:
    """An idle Session on the fake's headless session, in an environment Pilot
    started, whose shutdown is armed."""
    _environment_row(session, due=datetime.now(UTC) + STOP_AFTER)
    return _agent_session(session, project, controller_session)


def _records(db: DbSession, run_id: uuid.UUID) -> list[StoredRecord]:
    return read_records(db, run_id, limit=1000)


def _is_partial(line: str) -> bool:
    try:
        return json.loads(line).get("type") == "stream_event"
    except ValueError:
        return False


def _recorded(lines: list[str], offsets: list[int]) -> list[tuple[int, Any]]:
    """The lines a relay records, each with its offset, as their records hold
    them."""
    return [
        (offset, json.loads(line))
        for offset, line in zip(offsets, lines, strict=True)
        if not _is_partial(line)
    ]


def _claude(db: DbSession, run_id: uuid.UUID) -> list[tuple[int | None, Any]]:
    return [
        (stored.record.raw_offset, stored.record.payload)
        for stored in _records(db, run_id)
        if stored.record.kind_code == RecordKind.CLAUDE
    ]


def _token(body: dict[str, Any]) -> str:
    """The token a headless create's body carries as `PILOT_TOKEN`."""
    (entry,) = body["env"]
    name, _, token = entry.partition("=")
    assert name == "PILOT_TOKEN"
    return token


def _relay(relays: RelayService, run: models.Session) -> None:
    """The relay's run, as its loop calls it."""
    relays.relay(run.id, LoopHandle(f"relay:{run.id}"))


def _send(
    relays: RelayService,
    db: DbSession,
    run: models.Session,
    message: str = "Rename the badge",
    author: User | None = None,
) -> Turn:
    turn = relays.send(
        db, run.id, message, author_user_id=None if author is None else author.id
    )
    clear_after_commit_callbacks()
    return turn


def _turn_of(
    fake: ServedFakeController,
    name: str,
    lines: list[str],
    outcome: FinishOutcome = "success",
    result: str = "Done.",
) -> list[int]:
    """The fake's turn: `claude` prints `lines`, then it ends as `outcome` says."""
    offsets = fake.play(ENV, name, lines)
    fake.finish(ENV, name, outcome, result)
    return offsets


@pytest.fixture
def connect(container: ServiceContainer) -> Iterator[Any]:
    """Opens a test connection and subscribes a view of the Session on it."""
    manager = container.sse_connection_manager()
    opened: list[SSEConnection] = []

    def open_view(run: models.Session, request_id: str = "req-1") -> SSEConnection:
        connection = manager.on_connect(request_id, SUBJECT)
        opened.append(connection)
        container.session_stream_service().subscribe(
            run.id, request_id, "chat", SUBJECT
        )
        return connection

    yield open_view
    for connection in opened:
        manager.on_disconnect(connection)


def _frames(connection: SSEConnection) -> list[dict[str, Any]]:
    """The `session` events queued on the connection, in order."""
    queued = []
    while True:
        try:
            frame = connection.next_frame(timeout=0)
        except Empty:
            return queued
        assert frame is not None
        queued.append(json.loads(frame.removeprefix("data: "))["payload"])


def _row(db: DbSession) -> Environment:
    return db.scalars(
        select(Environment)
        .where(Environment.id == ENV)
        .execution_options(populate_existing=True)
    ).one()


class TestSend:
    def test_a_send_answered_202_writes_the_turn_and_runs_the_session(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        idle: models.Session,
        person: User,
    ) -> None:
        before = datetime.now(UTC)

        turn = _send(relays, session, idle, "Rename the badge", author=person)

        assert fake_controller.calls[-1] == (
            f"POST /environments/{ENV}/sessions/headless/{controller_session}/messages"
        )
        assert fake_controller.session(ENV, controller_session).status == "busy"
        assert (turn.seq, turn.author_user_id, turn.message) == (
            1,
            person.id,
            "Rename the badge",
        )
        assert turn.started_at >= before
        assert (turn.ended_at, turn.error) == (None, None)
        [send] = _records(session, idle.id)
        assert (send.record.kind_code, send.turn, send.author, send.message) == (
            RecordKind.SEND,
            1,
            "ada",
            "Rename the badge",
        )
        assert idle.state_code == SessionState.RUNNING
        assert (idle.turn_started_at, idle.turn_ended_at) == (turn.started_at, None)
        assert idle.turns == 1
        assert idle.current_line == {
            "state": "thinking",
            "since": turn.started_at.isoformat(),
        }
        assert _row(session).stop_due_at is None

    def test_the_servers_own_turn_has_no_send_record(
        self, session: DbSession, relays: RelayService, idle: models.Session
    ) -> None:
        turn = _send(relays, session, idle, "continue")

        assert turn.author_user_id is None
        assert _records(session, idle.id) == []
        assert idle.state_code == SessionState.RUNNING

    @pytest.mark.parametrize(
        ("failure", "answer"),
        [
            ("unreachable", "502 worker-unreachable"),
            ("stopped", "409 conflict"),
        ],
    )
    def test_a_send_that_fails_before_the_202_writes_the_failed_turn(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        idle: models.Session,
        person: User,
        failure: str,
        answer: str,
    ) -> None:
        match failure:
            case "unreachable":
                fake_controller.unreachable(ENV)
            case "stopped":
                fake_controller.set_status(ENV, "stopped")
        due = _row(session).stop_due_at

        turn = _send(relays, session, idle, "Rename the badge", author=person)

        assert turn.error is not None and answer in turn.error
        assert turn.error.startswith("Cannot send a turn to session ")
        assert turn.ended_at is not None
        assert [
            (stored.record.kind_code, stored.turn, stored.record.payload)
            for stored in _records(session, idle.id)
        ] == [
            (RecordKind.SEND, 1, None),
            (RecordKind.SERVER, 1, {"type": SEND_FAILED, "reason": turn.error}),
        ]
        assert idle.state_code == SessionState.IDLE
        assert (idle.turn_started_at, idle.turn_ended_at) == (
            turn.started_at,
            turn.ended_at,
        )
        assert idle.turns == 1
        assert _row(session).stop_due_at == due

    def test_a_send_while_the_controller_has_a_turn_is_refused_and_writes_nothing(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        idle: models.Session,
        person: User,
    ) -> None:
        fake_controller.busy(ENV, controller_session)

        with pytest.raises(InvalidOperationException, match="a turn is in flight"):
            relays.send(session, idle.id, "Rename the badge", author_user_id=person.id)

        assert (
            session.scalars(select(Turn).where(Turn.session_id == idle.id)).all() == []
        )
        assert _records(session, idle.id) == []
        assert idle.state_code == SessionState.IDLE

    def test_a_send_refused_as_busy_with_no_turn_in_flight_starts_no_relay(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        idle: models.Session,
        person: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Refinement D2: the record has no Turn in flight, so no relay is
        # missing; `test_a_send_refused_as_busy_starts_the_missing_relay` has
        # the case with one.
        asked: list[str] = []
        monkeypatch.setattr(
            relays._supervisor,
            "start_loop",
            lambda job, run, key=None, **_: asked.append(f"{job}:{key}") or True,
        )
        fake_controller.busy(ENV, controller_session)

        with pytest.raises(InvalidOperationException, match="a turn is in flight"):
            relays.send(session, idle.id, "Rename the badge", author_user_id=person.id)

        assert asked == []
        assert _records(session, idle.id) == []

    def test_a_send_to_a_controller_session_that_is_gone_resumes_it_then_sends(
        self,
        session: DbSession,
        relays: RelayService,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        controller_session: str,
        idle: models.Session,
        person: User,
    ) -> None:
        idle.conversation_id = "conversation-1"
        idle.agent, idle.model = "worker", "claude-example-1"
        # The reaper took the idle session (§9.6).
        controller_client.end_session(ENV, controller_session)
        before = len(fake_controller.calls)

        turn = _send(relays, session, idle, "Rename the badge", author=person)

        [created] = fake_controller.sessions(ENV)
        assert created.name != controller_session
        assert created.session_id == "conversation-1"
        assert created.status == "busy"
        assert fake_controller.calls[before:] == [
            f"POST /environments/{ENV}/sessions/headless/{controller_session}/messages",
            f"POST /environments/{ENV}/sessions/headless",
            f"POST /environments/{ENV}/sessions/headless/{created.name}/messages",
        ]
        assert idle.controller_session == created.name
        assert (turn.seq, turn.error, turn.ended_at) == (1, None, None)
        [gone, sent] = _records(session, idle.id)
        assert (gone.record.kind_code, gone.turn) == (RecordKind.SERVER, None)
        assert gone.record.payload["type"] == SESSION_GONE
        assert "404 not-found" in gone.record.payload["reason"]
        assert (sent.record.kind_code, sent.turn) == (RecordKind.SEND, 1)
        assert idle.state_code == SessionState.RUNNING

    def test_a_resume_creates_with_the_sessions_options(
        self,
        session: DbSession,
        creating: tuple[RelayService, "_Creating"],
        project: Project,
    ) -> None:
        relays, fake = creating
        run = _agent_session(session, project, "claude-gone")
        run.conversation_id = "conversation-1"
        run.agent, run.model, run.reasoning_effort = "worker", "model-1", "high"

        turn = _send(relays, session, run, "Rename the badge")

        assert turn.error is None
        assert fake.create_bodies == [
            {
                "cwd": "/work/Example",
                "resume": "conversation-1",
                "agent": "worker",
                "model": "model-1",
                "reasoningEffort": "high",
            }
        ]

    def test_a_resume_hands_the_new_session_pilots_server_with_a_token_of_its_own(
        self,
        session: DbSession,
        container: ServiceContainer,
        supervise: Supervise,
        creating: tuple[RelayService, "_Creating"],
        project: Project,
    ) -> None:
        _, fake = creating
        relays = _relay_service(container, supervise, mcp_url=MCP_URL)[0]
        run = _agent_session(session, project, "claude-gone")
        run.conversation_id = "conversation-1"
        before = run.token_hash

        turn = _send(relays, session, run, "Rename the badge")

        assert turn.error is None
        (body,) = fake.create_bodies
        assert body["resume"] == "conversation-1"
        (entry,) = body["mcpConfig"]
        assert json.loads(entry)["mcpServers"]["pilot"]["url"] == MCP_URL
        assert "strictMcpConfig" not in body
        assert run.token_hash == token_hash(_token(body)) != before
        [gone] = [
            stored.record.payload
            for stored in _records(session, run.id)
            if stored.record.kind_code == RecordKind.SERVER
        ]
        assert _token(body) not in json.dumps(gone)

    def test_a_resume_the_controller_refuses_fails_the_turn_and_writes_nothing_else(
        self,
        session: DbSession,
        creating: tuple[RelayService, "_Creating"],
        project: Project,
    ) -> None:
        relays, fake = creating
        run = _agent_session(session, project, "claude-gone")
        fake.refuse_creates = True

        turn = _send(relays, session, run, "Rename the badge")

        assert turn.error is not None and "502 worker-unreachable" in turn.error
        assert turn.error.startswith("Cannot create a headless session in environment")
        assert [
            stored.record.payload["type"] for stored in _records(session, run.id)
        ] == [SEND_FAILED]
        assert run.controller_session == "claude-gone"
        assert fake.sessions(ENV) == []

    def test_turns_are_numbered_in_their_session(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        idle: models.Session,
    ) -> None:
        first = _send(relays, session, idle, "One")
        fake_controller.unreachable(ENV)
        second = _send(relays, session, idle, "Two")
        fake_controller.unreachable(ENV, on=False)

        assert (first.seq, second.seq) == (1, 2)
        assert second.error is not None
        assert idle.turns == 2
        assert idle.state_code == SessionState.RUNNING

        # The relay still finds the first, which the failed one follows.
        _turn_of(fake_controller, controller_session, raw_turn("turn_text"))
        _relay(relays, idle)

        assert first.ended_at is not None
        assert _records(session, idle.id)[-1].turn == 1

    def test_a_session_with_no_controller_session_is_refused(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        project: Project,
    ) -> None:
        _environment_row(session)
        run = _agent_session(session, project, None, SessionState.STARTING)

        with pytest.raises(InvalidOperationException):
            relays.send(session, run.id, "Rename the badge")

        assert (
            session.scalars(select(Turn).where(Turn.session_id == run.id)).all() == []
        )
        assert fake_controller.calls == []

    def test_an_unknown_session_is_refused(
        self, session: DbSession, relays: RelayService
    ) -> None:
        with pytest.raises(RecordNotFoundException):
            relays.send(session, uuid.uuid4(), "Rename the badge")


class TestSendTurn:
    def _brief(self, db: DbSession, run: models.Session) -> Turn:
        """The first Turn, written before the environment was up."""
        turn = Turn(
            session_id=run.id,
            seq=1,
            message="The brief",
            started_at=datetime.now(UTC) - timedelta(minutes=5),
        )
        db.add(turn)
        db.flush()
        return turn

    def test_a_turn_written_before_its_send_is_sent(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        project: Project,
    ) -> None:
        _environment_row(session, due=datetime.now(UTC) + STOP_AFTER)
        run = _agent_session(
            session, project, controller_session, SessionState.STARTING
        )
        starting = {"state": "starting", "since": "2026-01-01T12:00:00+00:00"}
        run.current_line = starting | {"text": "Creating the session…"}
        brief = self._brief(session, run)
        before = datetime.now(UTC)

        sent = relays.send_turn(session, brief.id)
        clear_after_commit_callbacks()

        assert sent is brief
        assert brief.started_at >= before
        assert (brief.ended_at, brief.error) == (None, None)
        assert fake_controller.session(ENV, controller_session).status == "busy"
        assert run.state_code == SessionState.RUNNING
        assert run.turn_started_at == brief.started_at
        assert run.turns == 1
        assert run.current_line == starting | {"text": "Creating the session…"}
        assert _records(session, run.id) == []
        assert _row(session).stop_due_at is None

    def test_one_whose_send_fails_has_its_error(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        project: Project,
    ) -> None:
        _environment_row(session)
        run = _agent_session(
            session, project, controller_session, SessionState.STARTING
        )
        brief = self._brief(session, run)
        fake_controller.unreachable(ENV)

        relays.send_turn(session, brief.id)

        assert brief.error is not None and "502 worker-unreachable" in brief.error
        assert brief.ended_at is not None
        [failed] = _records(session, run.id)
        assert (failed.record.kind_code, failed.turn) == (RecordKind.SERVER, 1)
        assert failed.record.payload == {"type": SEND_FAILED, "reason": brief.error}
        # What follows is the session start's: the Session is left as it was.
        assert run.state_code == SessionState.STARTING

    def test_a_turn_the_controller_has_already_is_not_sent_again(
        self,
        session: DbSession,
        relays: RelayService,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        controller_session: str,
        project: Project,
    ) -> None:
        _environment_row(session)
        run = _agent_session(
            session, project, controller_session, SessionState.STARTING
        )
        brief = self._brief(session, run)
        # The brief went out before a cut that lost its commit (§8.2).
        controller_client.send_message(ENV, controller_session, brief.message)
        before = len(fake_controller.calls)

        relays.send_turn(session, brief.id)
        clear_after_commit_callbacks()

        assert fake_controller.calls[before:] == [
            f"GET /environments/{ENV}/sessions/{controller_session}"
        ]
        assert (brief.ended_at, brief.error) == (None, None)
        assert run.state_code == SessionState.RUNNING

    def test_a_send_another_process_made_first_is_taken_as_sent(
        self,
        session: DbSession,
        container: ServiceContainer,
        supervise: Supervise,
        project: Project,
    ) -> None:
        fake = _Racing(keepalive_seconds=0.2)
        try:
            client = client_of(container, fake)
            relays, _ = _relay_service(container, supervise)
            name = _headless(fake, client)
            _environment_row(session)
            run = _agent_session(session, project, name, SessionState.STARTING)
            brief = self._brief(session, run)

            relays.send_turn(session, brief.id)
            clear_after_commit_callbacks()

            path = f"/environments/{ENV}/sessions"
            assert fake.calls[-3:] == [
                f"GET {path}/{name}",
                f"POST {path}/headless/{name}/messages",
                f"GET {path}/{name}",
            ]
            assert (brief.ended_at, brief.error) == (None, None)
            assert run.state_code == SessionState.RUNNING
            assert _records(session, run.id) == []
        finally:
            fake.close()

    def test_a_turn_another_process_made_running_is_left_as_it_is(
        self,
        session: DbSession,
        relays: RelayService,
        controller_client: ControllerClient,
        controller_session: str,
        project: Project,
    ) -> None:
        _environment_row(session)
        run = _agent_session(
            session, project, controller_session, SessionState.STARTING
        )
        brief = self._brief(session, run)
        controller_client.send_message(ENV, controller_session, brief.message)
        # Another process's send of it committed, and its relay wrote a line.
        working = {
            "state": "working",
            "since": "2026-01-01T12:00:00+00:00",
            "step": {"tool": "Bash", "input": {"command": "ls"}},
        }
        run.state_code = SessionState.RUNNING
        run.current_line = working
        started = brief.started_at
        session.flush()

        relays.send_turn(session, brief.id)
        clear_after_commit_callbacks()

        assert run.current_line == working
        assert brief.started_at == started
        assert run.turn_started_at is None

    def test_a_turn_a_stop_ended_while_its_send_went_out_is_in_flight_again(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        project: Project,
        person: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _environment_row(session)
        run = _agent_session(
            session, project, controller_session, SessionState.STARTING
        )
        brief = self._brief(session, run)
        deliver = relays._deliver_once

        def stopped_meanwhile(*args: Any) -> None:
            deliver(*args)
            run.state_code = SessionState.STOPPED
            run.stopped_by_user_id = person.id
            brief.ended_at = datetime.now(UTC)
            session.flush()

        monkeypatch.setattr(relays, "_deliver_once", stopped_meanwhile)

        relays.send_turn(session, brief.id)

        # The controller has it: its relay records it, and the interrupt ends it.
        assert {
            type(callback).__name__ for callback in after_commit_module._callbacks.get()
        } >= {"_RelayStart", "_InterruptStart"}
        clear_after_commit_callbacks()
        assert fake_controller.session(ENV, controller_session).status == "busy"
        assert (brief.ended_at, brief.error) == (None, None)
        assert (run.state_code, run.turn_ended_at) == (SessionState.STOPPED, None)

    def test_a_turn_another_process_relayed_to_its_end_under_a_stop_stays_ended(
        self,
        session: DbSession,
        relays: RelayService,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        controller_session: str,
        project: Project,
    ) -> None:
        _environment_row(session)
        run = _agent_session(session, project, controller_session, SessionState.STOPPED)
        brief = self._brief(session, run)
        controller_client.send_message(ENV, controller_session, brief.message)
        _turn_of(fake_controller, controller_session, raw_turn("turn_text"))
        run.state_code = SessionState.RUNNING
        _relay(relays, run)
        run.state_code = SessionState.STOPPED
        session.flush()
        ended = brief.ended_at

        relays.send_turn(session, brief.id)

        assert after_commit_module._callbacks.get() == ()
        assert brief.ended_at == ended is not None

    def test_an_unknown_turn_is_refused(
        self, session: DbSession, relays: RelayService
    ) -> None:
        with pytest.raises(RecordNotFoundException):
            relays.send_turn(session, 999_999)


class TestRelay:
    def test_each_line_but_a_stream_event_is_a_claude_record(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        idle: models.Session,
        person: User,
    ) -> None:
        lines = raw_turn("turn_subagent")
        _send(relays, session, idle, author=person)
        offsets = _turn_of(fake_controller, controller_session, lines)
        claude_before = metric_value(RECORDS_WRITTEN_TOTAL, kind="claude")

        _relay(relays, idle)

        recorded = _records(session, idle.id)
        assert _claude(session, idle.id) == _recorded(lines, offsets)
        assert all(
            stored.record.controller_session == controller_session and stored.turn == 1
            for stored in recorded[1:]
        )
        assert [stored.record.seq for stored in recorded] == list(
            range(1, len(recorded) + 1)
        )
        assert [stored.record.kind_code for stored in recorded] == (
            [RecordKind.SEND]
            + [RecordKind.CLAUDE] * len(_recorded(lines, offsets))
            + [RecordKind.RESULT]
        )
        assert metric_value(RECORDS_WRITTEN_TOTAL, kind="claude") == (
            claude_before + len(_recorded(lines, offsets))
        )
        assert metric_value(RELAYS_RUNNING) == 0

    def test_a_blank_or_non_json_line_is_a_record_of_its_text(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        idle: models.Session,
    ) -> None:
        _send(relays, session, idle)
        offsets = _turn_of(
            fake_controller,
            controller_session,
            ["", "Error: not a JSON line {", "42", '"a string"'],
        )

        _relay(relays, idle)

        assert _claude(session, idle.id) == [
            (offsets[0], ""),
            (offsets[1], "Error: not a JSON line {"),
            (offsets[2], "42"),
            (offsets[3], '"a string"'),
        ]

    def test_a_line_jsonb_refuses_is_a_record_of_its_text(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        idle: models.Session,
    ) -> None:
        nul = '{"type": "user", "content": [{"text": "a\\u0000b"}]}'
        nul_key = '{"type": "user", "a\\u0000b": 1}'
        lone = '{"type": "assistant", "text": "cut \\ud83d"}'
        paired = '{"type": "assistant", "text": "whole \\ud83d\\ude00"}'
        _send(relays, session, idle)
        offsets = _turn_of(
            fake_controller, controller_session, [nul, nul_key, lone, paired]
        )

        _relay(relays, idle)

        assert _claude(session, idle.id) == [
            (offsets[0], nul),
            (offsets[1], nul_key),
            (offsets[2], lone),
            (offsets[3], {"type": "assistant", "text": "whole \U0001f600"}),
        ]

    def test_the_main_threads_block_starts_and_text_deltas_reach_a_view(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        idle: models.Session,
        person: User,
        connect: Any,
    ) -> None:
        lines = raw_turn("turn_subagent")
        connection = connect(idle)
        _send(relays, session, idle, author=person)
        _turn_of(fake_controller, controller_session, lines)
        forwarded_before = metric_value(PARTIALS_FORWARDED_TOTAL)

        _relay(relays, idle)

        frames = _frames(connection)
        partials = [frame["data"] for frame in frames if frame["frame"] == "partial"]
        forwarded = [json.loads(line) for line in (lines[3], lines[18], lines[19])]
        assert partials == forwarded
        assert [p["event"]["type"] for p in partials] == [
            "content_block_start",
            "content_block_start",
            "content_block_delta",
        ]
        assert metric_value(PARTIALS_FORWARDED_TOTAL) == forwarded_before + 3
        seqs = [frame["data"]["seq"] for frame in frames if frame["frame"] == "record"]
        assert seqs == [stored.record.seq for stored in _records(session, idle.id)]
        assert frames[-1]["frame"] == "record"
        assert frames[-1]["data"]["kind"] == "result"
        # Each partial follows the records before its line.
        first = frames.index(
            {"session": str(idle.id), "frame": "partial", "data": partials[0]}
        )
        assert [frame["data"]["seq"] for frame in frames[:first]] == [1, 2, 3]

    @pytest.mark.parametrize(
        ("outcome", "result", "state", "error"),
        [
            ("success", "Done.", SessionState.IDLE, None),
            ("error", "The tests failed.", SessionState.IDLE, "The tests failed."),
            ("error", "", SessionState.IDLE, "The turn ended in an error"),
            ("interrupted", "", SessionState.STOPPED, None),
            (
                "spawn-failure",
                "claude would not start",
                SessionState.IDLE,
                "claude would not start",
            ),
            ("ended", "", SessionState.IDLE, "The turn ended in an error"),
        ],
    )
    def test_the_result_frame_ends_the_turn(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        idle: models.Session,
        outcome: FinishOutcome,
        result: str,
        state: SessionState,
        error: str | None,
    ) -> None:
        lines = raw_turn("turn_text")
        turn = _send(relays, session, idle)
        offsets = _turn_of(fake_controller, controller_session, lines, outcome, result)
        before = datetime.now(UTC)

        _relay(relays, idle)

        last = _records(session, idle.id)[-1]
        assert last.record.kind_code == RecordKind.RESULT
        assert last.turn == 1
        assert last.record.payload == {
            "turn": 1,
            "result": result,
            "isError": outcome in ("error", "spawn-failure", "ended"),
            "interrupted": outcome == "interrupted",
        }
        # The frame has no offset: it takes the stream's last raw frame's.
        assert last.record.raw_offset == offsets[-1]
        assert last.record.controller_session == controller_session
        assert turn.ended_at is not None and turn.ended_at >= before
        assert turn.error == error
        assert idle.state_code == state
        assert idle.turn_ended_at == turn.ended_at
        assert idle.turns == 1
        assert idle.current_line is None

    def test_a_send_committed_before_the_turns_end_keeps_the_session_running(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        idle: models.Session,
        person: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        lines = raw_turn("turn_text")
        first = _send(relays, session, idle, "One", author=person)
        first_offsets = _turn_of(fake_controller, controller_session, lines)
        sent: list[Turn] = []
        end_turn = relays._end_turn

        def send_first(*args: Any) -> None:
            # The controller's session is idle once its result is out: the
            # next send's `202` and commit come before the relay ends the turn.
            sent.append(_send(relays, session, idle, "Two", author=person))
            end_turn(*args)

        monkeypatch.setattr(relays, "_end_turn", send_first)
        _relay(relays, idle)
        monkeypatch.undo()

        [second] = sent
        assert first.ended_at is not None
        first_ended_at = first.ended_at
        assert second.error is None and second.ended_at is None
        assert idle.state_code == SessionState.RUNNING
        assert idle.current_line == {
            "state": "thinking",
            "since": second.started_at.isoformat(),
        }
        assert (idle.turns, idle.turn_started_at, idle.turn_ended_at) == (
            2,
            second.started_at,
            None,
        )
        assert _row(session).stop_due_at is None

        # The send's run again relays the next turn from the first's end.
        second_offsets = _turn_of(fake_controller, controller_session, lines)
        _relay(relays, idle)

        assert second.ended_at is not None
        # A Turn that ended already keeps its end.
        assert first.ended_at == first_ended_at
        assert idle.state_code == SessionState.IDLE
        results = [
            (stored.turn, stored.record.raw_offset)
            for stored in _records(session, idle.id)
            if stored.record.kind_code == RecordKind.RESULT
        ]
        assert results == [(1, first_offsets[-1]), (2, second_offsets[-1])]
        assert _claude(session, idle.id) == _recorded(
            lines + lines, first_offsets + second_offsets
        )

    def test_an_earlier_turn_whose_result_a_send_discarded_ends_with_the_next(
        self,
        session: DbSession,
        container: ServiceContainer,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        idle: models.Session,
        person: User,
    ) -> None:
        lines = raw_turn("turn_text")
        first = _send(relays, session, idle, "One", author=person)
        first_offsets = _turn_of(fake_controller, controller_session, lines)
        # The first turn's relay dropped after three lines. Before its rerun,
        # the next send's `202` discards the first turn's held result.
        for offset, payload in _recorded(lines, first_offsets)[:3]:
            container.session_record_service().append(
                idle.id,
                RecordKind.CLAUDE,
                payload=payload,
                turn_id=first.id,
                raw_offset=offset,
                controller_session=controller_session,
            )
        clear_after_commit_callbacks()
        second = _send(relays, session, idle, "Two", author=person)
        assert second.error is None
        second_offsets = _turn_of(fake_controller, controller_session, lines)

        _relay(relays, idle)

        assert first.ended_at is not None and first.error is None
        assert second.ended_at is not None
        assert idle.state_code == SessionState.IDLE
        assert idle.current_line is None
        assert (idle.turns, idle.turn_started_at, idle.turn_ended_at) == (
            2,
            second.started_at,
            second.ended_at,
        )
        assert _row(session).stop_due_at is not None
        stored = _records(session, idle.id)
        assert [
            (s.turn, s.record.raw_offset)
            for s in stored
            if s.record.kind_code == RecordKind.RESULT
        ] == [(2, second_offsets[-1])]
        # The raw stream marks no boundary between turns: what the first turn
        # printed after the drop falls in the second.
        turns = [s.turn for s in stored if s.record.kind_code == RecordKind.CLAUDE]
        assert turns == [1] * 3 + [2] * (len(turns) - 3)
        assert _claude(session, idle.id) == _recorded(
            lines + lines, first_offsets + second_offsets
        )

    def test_the_turns_end_cuts_its_documents_versions(
        self,
        session: DbSession,
        container: ServiceContainer,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        project: Project,
        idle: models.Session,
    ) -> None:
        documents = container.document_service()
        draft = documents.bear_draft(project, "# Badges\n")
        container.ingest_service().ingest(
            f"draft-{project.number}/project.md",
            b"# Badge colours\n",
            None,
            _row(session),
            idle,
        )
        assert draft.writing_session_id == idle.id
        _send(relays, session, idle)
        _turn_of(fake_controller, controller_session, raw_turn("turn_text"))

        _relay(relays, idle)

        versions = session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == draft.id)
            .order_by(DocumentVersion.number)
        ).all()
        assert [(v.cause_code, v.text, v.session_id) for v in versions] == [
            (VersionCause.BORN, "# Badges\n", None),
            (VersionCause.TURN, "# Badge colours\n", idle.id),
        ]
        assert draft.writing_session_id is None

    def test_the_turns_end_arms_the_shutdown_timer(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        idle: models.Session,
    ) -> None:
        _send(relays, session, idle)
        assert _row(session).stop_due_at is None
        _turn_of(fake_controller, controller_session, raw_turn("turn_text"))
        before = datetime.now(UTC)

        _relay(relays, idle)

        due = _row(session).stop_due_at
        assert due is not None
        assert before + STOP_AFTER <= due <= datetime.now(UTC) + STOP_AFTER

    def test_not_while_another_session_runs_there(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        project: Project,
        idle: models.Session,
    ) -> None:
        _agent_session(session, project, "claude-other", SessionState.RUNNING)
        _send(relays, session, idle)
        _turn_of(fake_controller, controller_session, raw_turn("turn_text"))

        _relay(relays, idle)

        assert idle.state_code == SessionState.IDLE
        assert _row(session).stop_due_at is None

    def test_it_opens_at_the_last_recorded_offset_and_records_nothing_twice(
        self,
        session: DbSession,
        container: ServiceContainer,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        idle: models.Session,
        person: User,
    ) -> None:
        lines = raw_turn("turn_tool")
        turn = _send(relays, session, idle, author=person)
        offsets = _turn_of(fake_controller, controller_session, lines)
        # An earlier run of the relay recorded the turn up to its tool call.
        earlier = _recorded(lines, offsets)[:3]
        for offset, payload in earlier:
            container.session_record_service().append(
                idle.id,
                RecordKind.CLAUDE,
                payload=payload,
                turn_id=turn.id,
                raw_offset=offset,
                controller_session=controller_session,
            )
        clear_after_commit_callbacks()

        _relay(relays, idle)

        opened = [call for call in fake_controller.calls if "/response?" in call]
        assert opened == [
            f"GET /environments/{ENV}/sessions/headless/{controller_session}"
            f"/response?format=raw&offset={earlier[-1][0]}"
        ]
        assert _claude(session, idle.id) == _recorded(lines, offsets)

    def test_the_first_line_names_the_sessions_conversation(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        idle: models.Session,
    ) -> None:
        lines = raw_turn("turn_text")
        _send(relays, session, idle)
        _turn_of(fake_controller, controller_session, lines)

        _relay(relays, idle)

        assert idle.conversation_id == json.loads(lines[0])["session_id"]

    def test_a_conversation_the_session_has_is_kept(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        idle: models.Session,
    ) -> None:
        idle.conversation_id = "conversation-1"
        _send(relays, session, idle)
        _turn_of(fake_controller, controller_session, raw_turn("turn_text"))

        _relay(relays, idle)

        assert idle.conversation_id == "conversation-1"

    def test_a_session_with_no_turn_in_flight_opens_no_stream(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        idle: models.Session,
    ) -> None:
        _relay(relays, idle)

        assert not any("/response?" in call for call in fake_controller.calls)
        assert _records(session, idle.id) == []


class _Creating(ServedFakeController):
    """The fake, keeping each headless create's body, and refusing every create
    with `502 worker-unreachable` while `refuse_creates` is set."""

    def __init__(self, keepalive_seconds: float) -> None:
        super().__init__(keepalive_seconds)
        self.create_bodies: list[dict[str, Any]] = []
        self.refuse_creates = False

    def _create_session(self, request: Request, env_id: str) -> Response:
        if self.refuse_creates:
            raise FakeControllerProblem(
                502, "worker-unreachable", f"the worker of {env_id} does not answer"
            )
        self.create_bodies.append(request.get_json(silent=True) or {})
        return super()._create_session(request, env_id)


@pytest.fixture
def creating(
    session: DbSession, container: ServiceContainer, supervise: Supervise
) -> Iterator[tuple[RelayService, _Creating]]:
    """The relays on `_Creating`, with the environment running and its row."""
    fake = _Creating(keepalive_seconds=0.2)
    client_of(container, fake)
    fake.add_environment(ENV, status="running")
    _environment_row(session)
    try:
        yield _relay_service(container, supervise)[0], fake
    finally:
        fake.close()


class _SendWatched(ServedFakeController):
    """The fake, calling `on_send` with the session's name as it answers each
    send, when it is set."""

    def __init__(self, keepalive_seconds: float) -> None:
        super().__init__(keepalive_seconds)
        self.on_send: Callable[[str], None] | None = None

    def _send(self, request: Request, env_id: str, name: str) -> Response:
        if self.on_send is not None:
            self.on_send(name)
        return super()._send(request, env_id, name)


class _GoneOnce(ServedFakeController):
    """The fake, running `after_404` once, as it refuses a send to a session it
    does not have: another process's action then."""

    def __init__(self, keepalive_seconds: float) -> None:
        super().__init__(keepalive_seconds)
        self.after_404: Callable[[], None] | None = None

    def _send(self, request: Request, env_id: str, name: str) -> Response:
        try:
            return super()._send(request, env_id, name)
        except FakeControllerProblem as problem:
            hook, self.after_404 = self.after_404, None
            if problem.status == 404 and hook is not None:
                hook()
            raise


class _Racing(ServedFakeController):
    """The fake, where another process's send lands right after the first
    status snapshot it answers."""

    def __init__(self, keepalive_seconds: float) -> None:
        super().__init__(keepalive_seconds)
        self._raced = False

    def _get_session(self, request: Request, env_id: str, name: str) -> Response:
        response = super()._get_session(request, env_id, name)
        if not self._raced:
            self._raced = True
            self.busy(env_id, name)
        return response


class _Replaying(ServedFakeController):
    """A controller that sends a session's raw file from its start, whatever
    the offset asked: what a relay meets when another process's relay has
    recorded the lines it reads."""

    def _response(self, request: Request, env_id: str, name: str) -> Response:
        environ = dict(request.environ, QUERY_STRING="format=raw&offset=0")
        return super()._response(Request(environ), env_id, name)


@pytest.fixture
def work_item(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
    idle: models.Session,
) -> models.Session:
    """`idle`, placed as a work item on `project`'s timeline."""
    container.record_service().place_work(project, idle, "Renaming the badge")
    clear_after_commit_callbacks()
    return idle


def _item_done(db: DbSession, run: models.Session) -> tuple[Any, ...]:
    item = db.get_one(Item, run.id, populate_existing=True)
    return item.done_at, item.done_cause_code, item.done_by_user_id


def _moves(events: list[EngineEvent]) -> list[EngineEvent]:
    """What the browsers hear of: the work items' moves and the projects'."""
    return [event for event in events if isinstance(event, WorkMoved | ProjectChanged)]


class _Opened:
    """A listener of the slot's open event, counting its calls."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1


def _opened(relays: RelayService) -> _Opened:
    """A listener of the relays' slot."""
    opened = _Opened()
    relays._slots.subscribe(opened)
    return opened


class TestRelayWorkItem:
    """A work item's turn's end (decision 44; DB Session State, F125)."""

    @pytest.mark.parametrize("outcome", ["success", "error", "interrupted"])
    def test_its_end_opens_the_slot_once_it_commits(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        work_item: models.Session,
        outcome: FinishOutcome,
    ) -> None:
        """F143.4: a work item ending opens the gate."""
        _send(relays, session, work_item)
        opened = _opened(relays)
        _turn_of(fake_controller, controller_session, raw_turn("turn_text"), outcome)

        _relay(relays, work_item)

        assert work_item.state_code != SessionState.RUNNING
        assert opened.calls == 1

    @pytest.mark.parametrize(
        ("outcome", "result", "state", "error"),
        [
            ("error", "The tests failed.", SessionState.FAILED, "The tests failed."),
            ("error", "", SessionState.FAILED, "The turn ended in an error"),
            (
                "spawn-failure",
                "claude would not start",
                SessionState.FAILED,
                "claude would not start",
            ),
            ("ended", "", SessionState.FAILED, "The turn ended in an error"),
            ("interrupted", "", SessionState.STOPPED, None),
        ],
    )
    def test_a_turn_that_did_not_end_well_leaves_the_item_open_waiting_on_you(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        project: Project,
        work_item: models.Session,
        engine_events: list[EngineEvent],
        outcome: FinishOutcome,
        result: str,
        state: SessionState,
        error: str | None,
    ) -> None:
        turn = _send(relays, session, work_item)
        _turn_of(
            fake_controller, controller_session, raw_turn("turn_text"), outcome, result
        )

        _relay(relays, work_item)

        # The badge counts it: the project's screens are read again (R20).
        assert _moves(engine_events)[-2:] == [
            WorkMoved(project.id, work_item.id),
            ProjectChanged(project.id),
        ]

        assert work_item.state_code == state
        assert turn.ended_at is not None
        assert turn.error == error
        # A turn's failure is its Turn's; the Session's error is a create's.
        assert work_item.error is None
        assert work_item.current_line is None
        assert _item_done(session, work_item) == (None, None, None)

    def test_a_turn_that_ended_well_makes_the_item_done(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        project: Project,
        work_item: models.Session,
        engine_events: list[EngineEvent],
    ) -> None:
        turn = _send(relays, session, work_item)
        _turn_of(fake_controller, controller_session, raw_turn("turn_text"))
        engine_events.clear()

        _relay(relays, work_item)

        assert work_item.state_code == SessionState.IDLE
        assert turn.error is None
        assert _item_done(session, work_item) == (turn.ended_at, "turn_ended", None)
        assert ProjectChanged(project.id) in engine_events

    @pytest.mark.parametrize(
        ("outcome", "read"),
        [("success", True), ("error", False), ("interrupted", False)],
    )
    def test_a_run_that_ended_well_has_its_documents_read_once_it_commits(
        self,
        session: DbSession,
        container: ServiceContainer,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        project: Project,
        work_item: models.Session,
        outcome: FinishOutcome,
        read: bool,
    ) -> None:
        # A stopped or failed run's documents await the end of its Resume's.
        container.document_service().register(project, work_item, NOTES)
        _send(relays, session, work_item)
        _turn_of(fake_controller, controller_session, raw_turn("turn_text"), outcome)

        _relay(relays, work_item)

        # Its read loop waits for a STARTUP that never fires here, and a
        # second request of it is none.
        requested = not relays._supervisor.start_loop(
            READ_JOB, lambda handle: None, key=str(work_item.id)
        )
        assert requested is read

    def test_each_record_that_moves_its_line_moves_the_item_alone(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        project: Project,
        work_item: models.Session,
        engine_events: list[EngineEvent],
    ) -> None:
        _send(relays, session, work_item)
        _turn_of(fake_controller, controller_session, raw_turn("turn_tool"))
        engine_events.clear()

        _relay(relays, work_item)

        moved = WorkMoved(project.id, work_item.id)
        # The tool call's block start, its `assistant` line, its result, the
        # text block's start and its `assistant` line move the line; the
        # `system`, `rate_limit_event` and `result` lines and the deltas do
        # not. The turn's end moves its state, and makes it done.
        assert _moves(engine_events) == [
            *[moved] * 5,
            ProjectChanged(project.id),
            moved,
        ]

    def test_a_calls_block_start_names_it_until_its_line_fills_its_input_in(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        work_item: models.Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """P-48 (V16): the line between two tool calls names the one whose
        input streams in."""
        _send(relays, session, work_item)
        _turn_of(fake_controller, controller_session, raw_turn("turn_tool"))
        lines: list[Any] = []
        moved = relays._moved

        def seen(run: models.Session, **kwargs: Any) -> None:
            lines.append(run.current_line)
            moved(run, **kwargs)

        monkeypatch.setattr(relays, "_moved", seen)

        _relay(relays, work_item)

        streaming, called = lines[:2]
        assert (streaming["state"], streaming["step"]) == (
            "working",
            {"tool": "Read", "input": None},
        )
        assert called == {
            "state": "working",
            "since": streaming["since"],
            "step": {"tool": "Read", "input": {"file_path": "/work/Example/README.md"}},
        }

    def test_a_resume_of_its_gone_controller_session_moves_the_item(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        project: Project,
        work_item: models.Session,
        engine_events: list[EngineEvent],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _send(relays, session, work_item)
        fake_controller.restart(ENV)
        fake_controller.set_status(ENV, "running")
        handle = LoopHandle(f"relay:{work_item.id}")
        resume = relays._resume

        def resume_once(*args: Any) -> None:
            resume(*args)
            handle._request_stop()

        monkeypatch.setattr(relays, "_resume", resume_once)
        engine_events.clear()

        relays.relay(work_item.id, handle)

        # The re-create leaves it idle, and the resume's Turn runs it again
        # on a line moved on: the browsers read the item and the project again
        # (F71).
        assert work_item.state_code == SessionState.RUNNING
        line = work_item.current_line
        assert line is not None and line["state"] == "thinking"
        assert _moves(engine_events) == [
            WorkMoved(project.id, work_item.id),
            ProjectChanged(project.id),
        ]

    def test_a_send_to_a_stopped_item_moves_its_state(
        self,
        container: ServiceContainer,
        relays: RelayService,
        project: Project,
        work_item: models.Session,
        engine_events: list[EngineEvent],
    ) -> None:
        work_item.state_code = SessionState.STOPPED

        with scoped_session(container) as db:
            relays.send(db, work_item.id, CONTINUE)

        assert work_item.state_code == SessionState.RUNNING
        assert _moves(engine_events) == [
            WorkMoved(project.id, work_item.id),
            ProjectChanged(project.id),
        ]

    def test_a_send_committed_before_the_turns_end_keeps_the_item_open(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        work_item: models.Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        lines = raw_turn("turn_text")
        _send(relays, session, work_item, "One")
        _turn_of(fake_controller, controller_session, lines)
        sent: list[Turn] = []
        end_turn = relays._end_turn

        def send_first(*args: Any) -> None:
            sent.append(_send(relays, session, work_item, CONTINUE))
            end_turn(*args)

        monkeypatch.setattr(relays, "_end_turn", send_first)
        _relay(relays, work_item)
        monkeypatch.undo()

        assert work_item.state_code == SessionState.RUNNING
        assert _item_done(session, work_item) == (None, None, None)

        # The server's own turn stays inside the one item (F26.7).
        _turn_of(fake_controller, controller_session, lines)
        _relay(relays, work_item)

        [second] = sent
        assert work_item.state_code == SessionState.IDLE
        assert _item_done(session, work_item) == (
            second.ended_at,
            "turn_ended",
            None,
        )
        assert session.scalars(select(Item)).all() == [
            session.get_one(Item, work_item.id)
        ]


def _stopped(run: models.Session, person: User | None = None) -> datetime:
    """`run` stopped under its turn, as a Stop writes it; the stop's time."""
    at = datetime.now(UTC)
    run.state_code = SessionState.STOPPED
    run.stopped_at = at
    run.stopped_by_user_id = None if person is None else person.id
    run.current_line = None
    return at


class TestStoppedUnderTheTurn:
    """A Session stopped under its turn keeps its relay to the turn's end
    (F67.1; V04)."""

    @pytest.mark.parametrize("outcome", ["interrupted", "success", "error"])
    def test_its_turn_is_relayed_to_its_end_and_it_stays_stopped(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        project: Project,
        work_item: models.Session,
        person: User,
        engine_events: list[EngineEvent],
        outcome: FinishOutcome,
    ) -> None:
        lines = raw_turn("turn_tool")
        turn = _send(relays, session, work_item)
        at = _stopped(work_item, person)
        offsets = _turn_of(fake_controller, controller_session, lines, outcome)
        engine_events.clear()

        _relay(relays, work_item)

        assert _claude(session, work_item.id) == _recorded(lines, offsets)
        last = _records(session, work_item.id)[-1]
        assert (last.record.kind_code, last.turn) == (RecordKind.RESULT, 1)
        assert turn.ended_at is not None
        assert work_item.turn_ended_at == turn.ended_at
        assert work_item.state_code == SessionState.STOPPED
        assert (work_item.stopped_at, work_item.stopped_by_user_id) == (at, person.id)
        # Its lines move no line: a stopped item shows its stop, and the
        # turn's end alone moves it.
        assert work_item.current_line is None
        assert _moves(engine_events) == [WorkMoved(project.id, work_item.id)]
        assert _item_done(session, work_item) == (None, None, None)
        assert ProjectChanged(project.id) not in engine_events

    def test_an_interrupted_turn_with_no_stop_is_stopped_by_no_one(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        work_item: models.Session,
        person: User,
    ) -> None:
        work_item.stopped_by_user_id = person.id
        turn = _send(relays, session, work_item)
        _turn_of(
            fake_controller, controller_session, raw_turn("turn_text"), "interrupted"
        )

        _relay(relays, work_item)

        assert work_item.state_code == SessionState.STOPPED
        assert (work_item.stopped_at, work_item.stopped_by_user_id) == (
            turn.ended_at,
            None,
        )

    def test_a_turn_the_controller_never_got_ends_unsent(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        work_item: models.Session,
    ) -> None:
        # A resume's "continue", written before its send, then a Stop.
        turn = Turn(
            session_id=work_item.id,
            seq=1,
            message=CONTINUE,
            started_at=datetime.now(UTC),
        )
        session.add(turn)
        session.flush()
        _stopped(work_item)
        _row(session).stop_due_at = None

        _relay(relays, work_item)

        assert _sends(fake_controller, controller_session) == 0
        assert fake_controller.session(ENV, controller_session).status == "idle"
        assert turn.ended_at is not None and turn.error is None
        assert work_item.turn_ended_at == turn.ended_at
        assert _records(session, work_item.id) == []
        assert work_item.state_code == SessionState.STOPPED
        assert _row(session).stop_due_at is not None

    def test_a_controller_session_gone_ends_its_turn_and_resumes_nothing(
        self,
        session: DbSession,
        relays: RelayService,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        controller_session: str,
        work_item: models.Session,
    ) -> None:
        turn = _send(relays, session, work_item)
        _stopped(work_item)
        fake_controller.restart(ENV)
        fake_controller.set_status(ENV, "running")
        before = len(fake_controller.calls)

        _relay(relays, work_item)

        assert not any("POST" in call for call in fake_controller.calls[before:])
        [gone] = [
            stored
            for stored in _records(session, work_item.id)
            if stored.record.kind_code == RecordKind.SERVER
        ]
        assert gone.turn is None and gone.record.payload["type"] == SESSION_GONE
        assert turn.ended_at is not None
        assert work_item.controller_session == controller_session
        assert work_item.state_code == SessionState.STOPPED

    def test_a_turn_ended_with_no_result_lets_go_of_the_documents_it_was_writing(
        self,
        session: DbSession,
        container: ServiceContainer,
        relays: RelayService,
        fake_controller: ServedFakeController,
        project: Project,
        work_item: models.Session,
    ) -> None:
        documents = container.document_service()
        draft = documents.bear_draft(project, "# Badges\n")
        container.ingest_service().ingest(
            f"draft-{project.number}/project.md",
            b"# Badge colours\n",
            None,
            _row(session),
            work_item,
        )
        _send(relays, session, work_item)
        _stopped(work_item)
        fake_controller.restart(ENV)
        fake_controller.set_status(ENV, "running")

        _relay(relays, work_item)

        assert draft.writing_session_id is None
        versions = session.scalars(
            select(DocumentVersion.cause_code)
            .where(DocumentVersion.document_id == draft.id)
            .order_by(DocumentVersion.number)
        ).all()
        assert versions == [VersionCause.BORN, VersionCause.TURN]


class _Settling(ServedFakeController):
    """The fake, where each read of an environment first meets the next of
    `script` — the status it moves to, or None for the environment gone — and
    is answered at once, wait or not."""

    def __init__(self, keepalive_seconds: float) -> None:
        super().__init__(keepalive_seconds)
        self.script: list[EnvironmentStatus | None] = []

    def _get_environment(self, request: Request, env_id: str) -> Response:
        if self.script:
            status = self.script.pop(0)
            if status is None:
                self.remove_environment(env_id)
            else:
                self.set_status(env_id, status)
        environ = dict(request.environ, QUERY_STRING="")
        return super()._get_environment(Request(environ), env_id)


def _servers(db: DbSession, run: models.Session) -> list[tuple[int | None, Any]]:
    """The Session's `server` records: each one's Turn and payload."""
    return [
        (stored.turn, stored.record.payload)
        for stored in _records(db, run.id)
        if stored.record.kind_code == RecordKind.SERVER
    ]


def _stopped_by_its_environment(
    run: models.Session, turn: Turn, cause: StopCause, reason: str
) -> list[tuple[int | None, Any]]:
    """`run` stopped as a stop made elsewhere leaves it, its turn `turn` ended
    by the server; the `server` record that ended it."""
    assert run.state_code == SessionState.STOPPED
    assert turn.ended_at is not None and turn.error is None
    assert (run.stopped_at, run.stopped_by_user_id) == (turn.ended_at, None)
    assert run.turn_ended_at == turn.ended_at
    assert run.current_line is None
    return [
        (1, {"type": ENVIRONMENT_STOPPED, "cause": cause, "reason": reason}),
    ]


class TestEnvironmentUnderATurn:
    """An environment that restarts, or is stopped elsewhere, under a work
    item's turn (F71, F26.1, F69.2; design 2 §9.6; V06, V19)."""

    @pytest.fixture
    def fake_controller(self) -> Iterator[_Settling]:
        fake = _Settling(keepalive_seconds=0.2)
        try:
            yield fake
        finally:
            fake.close()

    @pytest.fixture
    def turn(
        self, session: DbSession, relays: RelayService, work_item: models.Session
    ) -> Turn:
        """The work item's turn, in flight."""
        return _send(relays, session, work_item)

    @pytest.mark.parametrize(
        ("status", "cause"),
        [
            ("stopped", StopCause.ENVIRONMENT_STOPPED),
            ("deleting", StopCause.ENVIRONMENT_DELETING),
        ],
    )
    def test_an_environment_that_settles_stopped_stops_the_item(
        self,
        container: ServiceContainer,
        session: DbSession,
        relays: RelayService,
        fake_controller: _Settling,
        project: Project,
        work_item: models.Session,
        turn: Turn,
        engine_events: list[EngineEvent],
        status: EnvironmentStatus,
        cause: StopCause,
    ) -> None:
        fake_controller.set_status(ENV, status)
        engine_events.clear()

        _relay(relays, work_item)

        reason = f"environment {ENV} is {status}"
        assert _servers(session, work_item) == _stopped_by_its_environment(
            work_item, turn, cause, reason
        )
        assert [
            stored.record.kind_code
            for stored in _records(session, work_item.id)
            if stored.record.kind_code == RecordKind.RESULT
        ] == []
        # It waits on you, open, as a Stop leaves it.
        assert _item_done(session, work_item) == (None, None, None)
        work = container.timeline_service().work(work_item.id)
        assert (work.state, work.stopped_cause, work.stopped_by) == (
            SessionState.STOPPED,
            cause,
            None,
        )
        assert work.stopped_at == turn.ended_at
        assert _row(session).stop_due_at is not None
        assert _moves(engine_events) == [
            WorkMoved(project.id, work_item.id),
            ProjectChanged(project.id),
        ]

    def test_a_stop_made_elsewhere_opens_the_slot_once_it_commits(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: _Settling,
        work_item: models.Session,
        turn: Turn,
    ) -> None:
        """F143.4: a work item ending opens the gate."""
        fake_controller.set_status(ENV, "stopped")
        opened = _opened(relays)

        _relay(relays, work_item)

        assert work_item.state_code == SessionState.STOPPED
        assert opened.calls == 1

    def test_an_environment_the_resume_does_not_find_is_gone_and_stops_the_item(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: _Settling,
        controller_session: str,
        work_item: models.Session,
        turn: Turn,
    ) -> None:
        fake_controller.remove_environment(ENV)

        _relay(relays, work_item)

        [(at, payload)] = _servers(session, work_item)
        reason = payload["reason"]
        assert f"404 not-found: no environment {ENV}" in reason
        assert [(at, payload)] == _stopped_by_its_environment(
            work_item, turn, StopCause.ENVIRONMENT_GONE, reason
        )
        # Nothing of the resume is written: no `session-gone`, no next Turn.
        assert work_item.controller_session == controller_session
        assert work_item.turns == 1

    def test_an_environment_gone_while_waited_for_stops_the_item(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: _Settling,
        work_item: models.Session,
        turn: Turn,
    ) -> None:
        fake_controller.set_status(ENV, "stopping")
        fake_controller.script = [None]

        _relay(relays, work_item)

        [(at, payload)] = _servers(session, work_item)
        reason = payload["reason"]
        assert "404 not-found" in reason
        assert [(at, payload)] == _stopped_by_its_environment(
            work_item, turn, StopCause.ENVIRONMENT_GONE, reason
        )

    def test_a_restart_says_so_on_the_items_line_once(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: _Settling,
        project: Project,
        work_item: models.Session,
        turn: Turn,
        engine_events: list[EngineEvent],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_controller.set_status(ENV, "starting")
        fake_controller.script = ["provisioning", "starting", "stopped"]
        lines: list[Any] = []
        stopped_elsewhere = relays._stopped_elsewhere

        def seen_first(*args: Any) -> None:
            lines.append(work_item.current_line)
            stopped_elsewhere(*args)

        monkeypatch.setattr(relays, "_stopped_elsewhere", seen_first)
        engine_events.clear()

        _relay(relays, work_item)

        text = "Env-A is restarting…"
        [line] = lines
        assert (line["state"], line["text"]) == ("starting", text)
        [restarting, _stop] = _servers(session, work_item)
        assert restarting == (1, {"type": RESTARTING, "text": text})
        moved = WorkMoved(project.id, work_item.id)
        assert _moves(engine_events) == [moved, moved, ProjectChanged(project.id)]

    def test_a_stopping_environment_is_no_restart(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: _Settling,
        work_item: models.Session,
        turn: Turn,
    ) -> None:
        fake_controller.set_status(ENV, "stopping")
        fake_controller.script = ["stopping", "stopped"]

        _relay(relays, work_item)

        assert [payload["type"] for _, payload in _servers(session, work_item)] == [
            ENVIRONMENT_STOPPED
        ]

    def test_a_session_stopped_already_keeps_its_stop_and_its_turn_ends(
        self,
        container: ServiceContainer,
        session: DbSession,
        relays: RelayService,
        fake_controller: _Settling,
        project: Project,
        work_item: models.Session,
        turn: Turn,
        person: User,
        engine_events: list[EngineEvent],
    ) -> None:
        at = _stopped(work_item, person)
        fake_controller.set_status(ENV, "stopped")
        engine_events.clear()

        _relay(relays, work_item)

        assert turn.ended_at is not None
        assert work_item.state_code == SessionState.STOPPED
        assert (work_item.stopped_at, work_item.stopped_by_user_id) == (at, person.id)
        assert _servers(session, work_item) == [
            (
                1,
                {
                    "type": ENVIRONMENT_STOPPED,
                    "cause": StopCause.ENVIRONMENT_STOPPED,
                    "reason": f"environment {ENV} is stopped",
                },
            )
        ]
        # Its stop is the person's: its line names no other cause.
        assert container.timeline_service().work(work_item.id).stopped_cause is None
        assert ProjectChanged(project.id) not in engine_events

    def test_the_stop_lets_go_of_the_documents_it_was_writing(
        self,
        session: DbSession,
        container: ServiceContainer,
        relays: RelayService,
        fake_controller: _Settling,
        project: Project,
        work_item: models.Session,
    ) -> None:
        documents = container.document_service()
        draft = documents.bear_draft(project, "# Badges\n")
        container.ingest_service().ingest(
            f"draft-{project.number}/project.md",
            b"# Badge colours\n",
            None,
            _row(session),
            work_item,
        )
        _send(relays, session, work_item)
        fake_controller.set_status(ENV, "stopped")

        _relay(relays, work_item)

        assert draft.writing_session_id is None
        versions = session.scalars(
            select(DocumentVersion.cause_code)
            .where(DocumentVersion.document_id == draft.id)
            .order_by(DocumentVersion.number)
        ).all()
        assert versions == [VersionCause.BORN, VersionCause.TURN]

    def test_an_environment_that_settles_error_stops_the_item(
        self,
        container: ServiceContainer,
        session: DbSession,
        relays: RelayService,
        fake_controller: _Settling,
        project: Project,
        work_item: models.Session,
        turn: Turn,
        engine_events: list[EngineEvent],
    ) -> None:
        """P-46 as D2 rules it (V15): a fourth stop made elsewhere, the slot
        open at once."""
        fake_controller.set_status(ENV, "starting")
        fake_controller.script = ["starting", "error"]
        opened = _opened(relays)
        engine_events.clear()

        _relay(relays, work_item)

        [restarting, stop] = _servers(session, work_item)
        assert restarting[1]["type"] == RESTARTING
        assert [stop] == _stopped_by_its_environment(
            work_item,
            turn,
            StopCause.ENVIRONMENT_ERROR,
            f"environment {ENV} is in error",
        )
        work = container.timeline_service().work(work_item.id)
        assert (work.state, work.stopped_cause, work.stopped_by) == (
            SessionState.STOPPED,
            StopCause.ENVIRONMENT_ERROR,
            None,
        )
        assert opened.calls == 1
        assert _row(session).stop_due_at is not None
        assert ProjectChanged(project.id) in engine_events


class TestInterrupt:
    """The interrupt of a Session stopped under its turn (F67.1, F141.3)."""

    def _interrupt(self, relays: RelayService, run: models.Session) -> None:
        relays.interrupt(run.id, LoopHandle(f"interrupt:{run.id}"))

    def test_it_ends_the_turn_where_it_is(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        work_item: models.Session,
    ) -> None:
        _send(relays, session, work_item)
        _stopped(work_item)
        session.flush()

        self._interrupt(relays, work_item)

        headless = fake_controller.session(ENV, controller_session)
        assert headless.status == "idle"
        assert headless.result is not None and headless.result["interrupted"]

    @pytest.mark.parametrize("state", [SessionState.RUNNING, SessionState.IDLE])
    def test_a_session_not_stopped_is_left_alone(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        work_item: models.Session,
        state: SessionState,
    ) -> None:
        _send(relays, session, work_item)
        work_item.state_code = state
        session.flush()
        before = len(fake_controller.calls)

        self._interrupt(relays, work_item)

        assert fake_controller.calls[before:] == []

    def test_a_stopped_session_with_no_turn_in_flight_is_left_alone(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        work_item: models.Session,
    ) -> None:
        _stopped(work_item)
        session.flush()
        before = len(fake_controller.calls)

        self._interrupt(relays, work_item)

        assert fake_controller.calls[before:] == []

    @pytest.mark.parametrize("answer", ["none", "ingress"])
    def test_a_controller_that_does_not_answer_leaves_the_turn_to_run_out(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        work_item: models.Session,
        answer: Literal["none", "ingress"],
    ) -> None:
        _send(relays, session, work_item)
        _stopped(work_item)
        session.flush()
        fake_controller.outage(answer=answer)

        self._interrupt(relays, work_item)

        fake_controller.outage(on=False)
        assert fake_controller.session(ENV, controller_session).status == "busy"

    def test_a_controller_session_gone_has_no_turn_to_interrupt(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        work_item: models.Session,
    ) -> None:
        _send(relays, session, work_item)
        _stopped(work_item)
        session.flush()
        fake_controller.restart(ENV)
        fake_controller.set_status(ENV, "running")

        self._interrupt(relays, work_item)

        assert fake_controller.calls[-1] == (
            f"POST /environments/{ENV}/sessions/headless/"
            f"{work_item.controller_session}/interrupt"
        )

    def test_another_failure_raises_for_the_loop_to_run_again(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        work_item: models.Session,
    ) -> None:
        _send(relays, session, work_item)
        _stopped(work_item)
        session.flush()
        fake_controller.unreachable(ENV)

        with pytest.raises(ExternalServiceException, match="worker-unreachable"):
            self._interrupt(relays, work_item)


class TestRelaySkip:
    @pytest.fixture
    def replaying(self, container: ServiceContainer) -> Iterator[_Replaying]:
        fake = _Replaying(keepalive_seconds=0.2)
        client_of(container, fake)
        try:
            yield fake
        finally:
            fake.close()

    def test_a_line_the_record_has_is_skipped_and_wakes_the_hub(
        self,
        session: DbSession,
        container: ServiceContainer,
        supervise: Supervise,
        replaying: _Replaying,
        project: Project,
        person: User,
        connect: Any,
    ) -> None:
        relays, _ = _relay_service(container, supervise)
        name = _headless(replaying, container.controller_client())
        _environment_row(session)
        run = _agent_session(session, project, name)
        turn = _send(relays, session, run, author=person)
        lines = raw_turn("turn_tool")
        offsets = _turn_of(replaying, name, lines)
        connection = connect(run)
        # Another process's relay committed these: no wake here.
        for offset, payload in _recorded(lines, offsets)[:3]:
            container.session_record_service().append(
                run.id,
                RecordKind.CLAUDE,
                payload=payload,
                turn_id=turn.id,
                raw_offset=offset,
                controller_session=name,
            )
        clear_after_commit_callbacks()

        _relay(relays, run)

        assert _claude(session, run.id) == _recorded(lines, offsets)
        seqs = [
            frame["data"]["seq"]
            for frame in _frames(connection)
            if frame["frame"] == "record"
        ]
        assert seqs == list(range(2, len(_records(session, run.id)) + 1))


def _committed_session(
    container: ServiceContainer, controller_session: str
) -> tuple[uuid.UUID, uuid.UUID]:
    """A person, and an idle Session of theirs on the fake's headless session,
    committed; their ids."""
    with scoped_session(container) as db:
        person = User(
            kind_code=UserKind.PERSON,
            subject=SUBJECT,
            handle="ada",
            name="Ada Example",
            avatar_slot=1,
        )
        db.add(person)
        db.flush()
        project = Project(created_by_user_id=person.id)
        db.add(project)
        _environment_row(db)
        run = _agent_session(db, project, controller_session)
        return run.id, person.id


def _send_committed(
    container: ServiceContainer,
    relays: RelayService,
    run_id: uuid.UUID,
    author_id: uuid.UUID,
) -> None:
    with scoped_session(container) as db:
        turn = relays.send(db, run_id, "Rename the badge", author_user_id=author_id)
        assert turn.error is None


def _read(container: ServiceContainer, run_id: uuid.UUID) -> models.Session:
    with scoped_session(container) as db:
        run = db.get_one(models.Session, run_id)
        db.expunge(run)
        return run


def _claude_committed(
    container: ServiceContainer, run_id: uuid.UUID
) -> list[tuple[int | None, Any]]:
    with scoped_session(container) as db:
        return _claude(db, run_id)


class TestRelayLoop:
    @pytest.fixture
    def loop_log(self) -> Iterator[LogWaiter]:
        with listening(SUPERVISOR_LOGGER) as waiter:
            yield waiter

    @pytest.fixture
    def running(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
    ) -> tuple[RelayService, str, uuid.UUID, uuid.UUID]:
        """The relays after STARTUP, on a database of their own, and an idle
        Session: the service, the controller session's name, the Session's id
        and its person's."""
        container = committed_app.container
        relays, coordinator = _relay_service(container, supervise)
        name = _headless(fake_controller, committed_controller_client)
        run_id, person_id = _committed_session(container, name)
        coordinator.fire_startup()
        return relays, name, run_id, person_id

    def test_a_work_items_run_that_ends_well_has_its_documents_read(
        self,
        committed_app: Flask,
        fake_controller: ServedFakeController,
        running: tuple[RelayService, str, uuid.UUID, uuid.UUID],
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        relays, name, run_id, person_id = running
        fake_controller.put_file(ENV, NOTES, b"# Notes\n\nThe lake.\n")
        with scoped_session(container) as db:
            run = db.get_one(models.Session, run_id)
            project = db.get_one(Project, run.project_id)
            container.record_service().place_work(project, run, "Renaming the badge")
            item_id = container.document_service().register(project, run, NOTES).item.id
        _send_committed(container, relays, run_id, person_id)
        loop_log.wait_for(rf"Loop relay:{run_id} started")

        _turn_of(fake_controller, name, raw_turn("turn_text"))

        loop_log.wait_for(rf"Loop read:{run_id} ended")
        with scoped_session(container) as db:
            document = db.get_one(Document, item_id)
            assert document.published_text == "# Notes\n\nThe lake.\n"

    def test_a_send_starts_the_relay_which_records_the_turn_as_it_comes(
        self,
        committed_app: Flask,
        fake_controller: ServedFakeController,
        running: tuple[RelayService, str, uuid.UUID, uuid.UUID],
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        relays, name, run_id, person_id = running
        lines = raw_turn("turn_subagent")
        task = json.loads(lines[5])["message"]["content"][-1]

        _send_committed(container, relays, run_id, person_id)

        loop_log.wait_for(rf"Loop relay:{run_id} started")
        wait_until(lambda: metric_value(RELAYS_RUNNING) == 1, "relaying the turn")

        def state() -> str | None:
            line = _read(container, run_id).current_line
            return None if line is None else line["state"]

        # The init line … the sub-agent's call
        fake_controller.play(ENV, name, lines[:6])
        wait_until(lambda: state() == "waiting", "waiting on the sub-agent")
        line = _read(container, run_id).current_line
        assert line is not None
        assert line["step"] == {"tool": "Task", "input": task["input"]}
        assert line["agent"] == {
            "type": task["input"]["subagent_type"],
            "description": task["input"]["description"],
        }
        # … its result, the text block's start and its first delta
        fake_controller.play(ENV, name, lines[6:20])
        wait_until(lambda: state() == "writing", "writing")
        # … claude's own result line, which does not end the turn (D004)
        offsets = fake_controller.play(ENV, name, lines[20:])
        assert json.loads(lines[-1])["type"] == "result"
        wait_until(
            lambda: any(
                offset == offsets[-1]
                for offset, _ in _claude_committed(container, run_id)
            ),
            "claude's result line recorded",
        )
        run = _read(container, run_id)
        assert run.state_code == SessionState.RUNNING
        assert run.current_line is not None and run.current_line["state"] == "thinking"

        fake_controller.finish(ENV, name, "success", "Done.")

        wait_until(
            lambda: _read(container, run_id).state_code == SessionState.IDLE,
            "the turn ended",
        )
        assert _read(container, run_id).current_line is None
        loop_log.wait_for(rf"Loop relay:{run_id} ended")
        assert metric_value(RELAYS_RUNNING) == 0

    def test_a_dropped_stream_reopens_at_the_last_committed_offset(
        self,
        committed_app: Flask,
        fake_controller: ServedFakeController,
        running: tuple[RelayService, str, uuid.UUID, uuid.UUID],
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        relays, name, run_id, person_id = running
        lines = raw_turn("turn_tool")
        _send_committed(container, relays, run_id, person_id)
        first = fake_controller.play(ENV, name, lines[:11])
        wait_until(
            lambda: (
                _claude_committed(container, run_id) == _recorded(lines[:11], first)
            ),
            "the first half recorded",
        )

        fake_controller.drop_streams()

        loop_log.wait_for(rf"Loop relay:{run_id} raised; restarting in .* s")
        rest = fake_controller.play(ENV, name, lines[11:])
        fake_controller.finish(ENV, name, "success", "Done.")
        wait_until(
            lambda: _read(container, run_id).state_code == SessionState.IDLE,
            "the turn ended",
        )
        assert _claude_committed(container, run_id) == _recorded(lines, first + rest)
        path = f"GET /environments/{ENV}/sessions/headless/{name}/response"
        assert [call for call in fake_controller.calls if call.startswith(path)] == [
            f"{path}?format=raw&offset=0",
            f"{path}?format=raw&offset={first[-1]}",
        ]

    def test_the_next_turn_is_relayed_from_the_last_turns_end(
        self,
        committed_app: Flask,
        fake_controller: ServedFakeController,
        running: tuple[RelayService, str, uuid.UUID, uuid.UUID],
    ) -> None:
        container = committed_app.container
        relays, name, run_id, person_id = running
        lines = raw_turn("turn_text")
        _send_committed(container, relays, run_id, person_id)
        first = _turn_of(fake_controller, name, lines)
        wait_until(
            lambda: _read(container, run_id).state_code == SessionState.IDLE,
            "the first turn ended",
        )

        _send_committed(container, relays, run_id, person_id)
        second = _turn_of(fake_controller, name, lines)

        wait_until(
            lambda: (
                _read(container, run_id).turn_ended_at is not None
                and _read(container, run_id).turns == 2
                and _read(container, run_id).state_code == SessionState.IDLE
            ),
            "the second turn ended",
        )
        with scoped_session(container) as db:
            records = _records(db, run_id)
        results = [s for s in records if s.record.kind_code == RecordKind.RESULT]
        assert [(s.turn, s.record.raw_offset) for s in results] == [
            (1, first[-1]),
            (2, second[-1]),
        ]
        assert _claude_committed(container, run_id) == _recorded(
            lines + lines, first + second
        )


RELAY_LOGGER = "app.services.relay_service"


def _running_committed(
    container: ServiceContainer, run_id: uuid.UUID, message: str = "Rename the badge"
) -> None:
    """A Turn in flight on the Session, `running`, as a send's commit leaves it
    with no relay running: a restart's rows."""
    with scoped_session(container) as db:
        run = db.get_one(models.Session, run_id)
        now = datetime.now(UTC)
        run.turns += 1
        db.add(Turn(session_id=run_id, seq=run.turns, message=message, started_at=now))
        run.state_code = SessionState.RUNNING
        run.turn_started_at = now
        run.turn_ended_at = None
        run.current_line = {"state": "thinking", "since": now.isoformat()}


def _idle(container: ServiceContainer, run_id: uuid.UUID) -> None:
    wait_until(
        lambda: _read(container, run_id).state_code == SessionState.IDLE,
        "the turn ended",
    )


def _sends(fake: ServedFakeController, name: str) -> int:
    return fake.calls.count(
        f"POST /environments/{ENV}/sessions/headless/{name}/messages"
    )


def _streams(fake: ServedFakeController, name: str) -> int:
    """How many response streams of the headless session `name` were opened."""
    path = f"GET /environments/{ENV}/sessions/headless/{name}/response?"
    return sum(1 for call in fake.calls if call.startswith(path))


def _committed_records(
    container: ServiceContainer, run_id: uuid.UUID
) -> list[StoredRecord]:
    with scoped_session(container) as db:
        return _records(db, run_id)


def _committed_turns(container: ServiceContainer, run_id: uuid.UUID) -> list[Turn]:
    with scoped_session(container) as db:
        turns = list(
            db.scalars(select(Turn).where(Turn.session_id == run_id).order_by(Turn.seq))
        )
        db.expunge_all()
        return turns


class TestRestartRecovery:
    """A new supervisor over the rows a restart left (§8.2; V07, V18)."""

    @pytest.fixture
    def loop_log(self) -> Iterator[LogWaiter]:
        with listening(SUPERVISOR_LOGGER, RELAY_LOGGER) as waiter:
            yield waiter

    @pytest.fixture
    def rows(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
    ) -> tuple[str, uuid.UUID, uuid.UUID]:
        """An idle Session on the fake's headless session, committed: the
        session's name, the Session's id and its person's."""
        name = _headless(fake_controller, committed_controller_client)
        run_id, person_id = _committed_session(committed_app.container, name)
        return name, run_id, person_id

    def test_startup_relays_a_turn_that_ended_while_nothing_ran(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        rows: tuple[str, uuid.UUID, uuid.UUID],
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        name, run_id, _ = rows
        _running_committed(container, run_id)
        committed_controller_client.send_message(ENV, name, "Rename the badge")
        lines = raw_turn("turn_text")
        offsets = _turn_of(fake_controller, name, lines)
        _, coordinator = _relay_service(container, supervise)

        coordinator.fire_startup()

        loop_log.wait_for(rf"Resuming the relay of session {run_id}")
        _idle(container, run_id)
        assert _claude_committed(container, run_id) == _recorded(lines, offsets)
        [result] = [
            stored
            for stored in _committed_records(container, run_id)
            if stored.record.kind_code == RecordKind.RESULT
        ]
        assert (result.turn, result.record.payload["turn"]) == (1, 1)
        assert _sends(fake_controller, name) == 1

    def test_startup_sends_a_turn_the_controller_never_got_then_relays_it(
        self,
        committed_app: Flask,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        rows: tuple[str, uuid.UUID, uuid.UUID],
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        name, run_id, _ = rows
        _running_committed(container, run_id, CONTINUE)
        _, coordinator = _relay_service(container, supervise)

        coordinator.fire_startup()

        wait_until(
            lambda: fake_controller.session(ENV, name).status == "busy",
            "the turn sent",
        )
        lines = raw_turn("turn_text")
        offsets = _turn_of(fake_controller, name, lines)
        _idle(container, run_id)
        assert _sends(fake_controller, name) == 1
        assert _claude_committed(container, run_id) == _recorded(lines, offsets)

    def test_a_drain_mid_turn_leaves_the_rest_to_the_next_supervisor(
        self,
        committed_app: Flask,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        rows: tuple[str, uuid.UUID, uuid.UUID],
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        name, run_id, person_id = rows
        lines = raw_turn("turn_tool")
        relays, first = _relay_service(container, supervise)
        first.fire_startup()
        _send_committed(container, relays, run_id, person_id)
        offsets = fake_controller.play(ENV, name, lines[:11])
        recorded = _recorded(lines[:11], offsets)
        wait_until(
            lambda: _claude_committed(container, run_id) == recorded,
            "the first half recorded",
        )

        began = time.perf_counter()
        first.shutdown()

        assert time.perf_counter() - began < 20
        loop_log.wait_for(rf"Loop relay:{run_id} ended")
        assert _read(container, run_id).state_code == SessionState.RUNNING

        rest = _turn_of(fake_controller, name, lines[11:])
        _, second = _relay_service(container, supervise)
        second.fire_startup()

        _idle(container, run_id)
        assert _claude_committed(container, run_id) == _recorded(lines, offsets + rest)
        path = f"GET /environments/{ENV}/sessions/headless/{name}/response"
        assert [call for call in fake_controller.calls if call.startswith(path)] == [
            f"{path}?format=raw&offset=0",
            f"{path}?format=raw&offset={recorded[-1][0]}",
        ]

    def test_a_send_refused_as_busy_starts_the_missing_relay(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        rows: tuple[str, uuid.UUID, uuid.UUID],
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        name, run_id, person_id = rows
        relays, coordinator = _relay_service(container, supervise)
        coordinator.fire_startup()
        # A turn in flight whose relay this process does not run.
        _running_committed(container, run_id)
        committed_controller_client.send_message(ENV, name, "Rename the badge")

        with scoped_session(container) as db:
            with pytest.raises(InvalidOperationException):
                relays.send(db, run_id, "And the logo", author_user_id=person_id)

        loop_log.wait_for(rf"Loop relay:{run_id} started")
        lines = raw_turn("turn_text")
        offsets = _turn_of(fake_controller, name, lines)
        _idle(container, run_id)
        assert _claude_committed(container, run_id) == _recorded(lines, offsets)
        assert len(_committed_turns(container, run_id)) == 1

    def test_startup_interrupts_and_relays_the_turn_of_a_session_stopped_under_it(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        rows: tuple[str, uuid.UUID, uuid.UUID],
    ) -> None:
        container = committed_app.container
        name, run_id, _ = rows
        # A Stop committed, and the process gone before its interrupt.
        _running_committed(container, run_id)
        committed_controller_client.send_message(ENV, name, "Rename the badge")
        lines = raw_turn("turn_text")
        offsets = fake_controller.play(ENV, name, lines)
        with scoped_session(container) as db:
            _stopped(db.get_one(models.Session, run_id))
        _, coordinator = _relay_service(container, supervise)

        coordinator.fire_startup()

        wait_until(
            lambda: _committed_turns(container, run_id)[0].ended_at is not None,
            "the stopped turn ended",
        )
        result = fake_controller.session(ENV, name).result
        assert result is not None and result["interrupted"]
        assert _claude_committed(container, run_id) == _recorded(lines, offsets)
        assert _read(container, run_id).state_code == SessionState.STOPPED
        assert _sends(fake_controller, name) == 1


class TestEnvironmentRestartUnderARun:
    """F71 under a run (§9.6; V17)."""

    @pytest.fixture
    def relay_log(self) -> Iterator[LogWaiter]:
        with listening(SUPERVISOR_LOGGER, RELAY_LOGGER) as waiter:
            yield waiter

    @pytest.fixture
    def relaying(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
    ) -> tuple[str, uuid.UUID, list[str], list[int]]:
        """A Session's turn in flight, its first lines recorded by its relay:
        the controller session's name, the Session's id, the turn's lines and
        the recorded ones' offsets."""
        container = committed_app.container
        relays, coordinator = _relay_service(container, supervise)
        name = _headless(fake_controller, committed_controller_client)
        run_id, person_id = _committed_session(container, name)
        coordinator.fire_startup()
        _send_committed(container, relays, run_id, person_id)
        lines = raw_turn("turn_tool")
        offsets = fake_controller.play(ENV, name, lines[:11])
        wait_until(
            lambda: (
                _claude_committed(container, run_id) == _recorded(lines[:11], offsets)
            ),
            "the first lines recorded",
        )
        return name, run_id, lines, offsets

    def _assert_resumed(
        self,
        container: ServiceContainer,
        run_id: uuid.UUID,
        lines: list[str],
        offsets: list[int],
        second: list[int],
    ) -> None:
        """Turn 1 ended by the server, with no result; the server's record
        outside any Turn; Turn 2, "continue", relayed from offset 0 of the new
        controller session to its result."""
        records = _committed_records(container, run_id)
        first_turn = [s.record.seq for s in records if s.turn == 1]
        [gone] = [
            s
            for s in records
            if s.record.kind_code == RecordKind.SERVER
            and s.record.payload["type"] == SESSION_GONE
        ]
        assert gone.turn is None
        assert "404 not-found" in gone.record.payload["reason"]
        assert max(first_turn) < gone.record.seq
        assert all(s.turn == 2 for s in records if s.record.seq > gone.record.seq)
        assert [s.turn for s in records if s.record.kind_code == RecordKind.RESULT] == [
            2
        ]
        resumed = [
            (s.record.controller_session, s.record.raw_offset)
            for s in records
            if s.turn == 2 and s.record.kind_code == RecordKind.CLAUDE
        ]
        text = raw_turn("turn_text")
        assert resumed == [
            ("claude-2", offset) for offset, _ in _recorded(text, second)
        ]
        assert _claude_committed(container, run_id) == (
            _recorded(lines[:11], offsets) + _recorded(text, second)
        )
        [brief, carried_on] = _committed_turns(container, run_id)
        assert brief.ended_at is not None and brief.error is None
        assert (carried_on.message, carried_on.author_user_id) == (CONTINUE, None)
        assert carried_on.ended_at is not None
        run = _read(container, run_id)
        assert run.controller_session == "claude-2"
        assert run.conversation_id == json.loads(lines[0])["session_id"]

    def test_an_environment_restart_is_waited_for_then_resumed_and_continued(
        self,
        committed_app: Flask,
        fake_controller: ServedFakeController,
        relaying: tuple[str, uuid.UUID, list[str], list[int]],
        relay_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        name, run_id, lines, offsets = relaying

        fake_controller.restart(ENV)

        relay_log.wait_for(
            rf"Environment {ENV} is not running: waiting for it to settle"
        )
        wait_until(
            lambda: _line_text(container, run_id) == "Env-A is restarting…",
            "the line says it restarts",
        )
        assert _read(container, run_id).state_code == SessionState.RUNNING
        fake_controller.set_status(ENV, "running")
        relay_log.wait_for(
            rf"Session {run_id} lost controller session {name}; resumed as "
            rf"claude-2 in environment {ENV}"
        )
        wait_until(
            lambda: fake_controller.session(ENV, "claude-2").status == "busy",
            "the continue sent",
        )
        # The resume moved the line on, before its Turn was sent.
        line = _read(container, run_id).current_line
        assert line is not None and line["state"] == "thinking"
        assert (
            fake_controller.session(ENV, "claude-2").session_id
            == json.loads(lines[0])["session_id"]
        )
        second = _turn_of(fake_controller, "claude-2", raw_turn("turn_text"))
        _idle(container, run_id)

        self._assert_resumed(container, run_id, lines, offsets, second)
        assert [
            (s.turn, s.record.payload)
            for s in _committed_records(container, run_id)
            if s.record.kind_code == RecordKind.SERVER
            and s.record.payload["type"] == RESTARTING
        ] == [(1, {"type": RESTARTING, "text": "Env-A is restarting…"})]
        path = f"GET /environments/{ENV}/sessions/headless/claude-2/response"
        assert [c for c in fake_controller.calls if c.startswith(path)][0] == (
            f"{path}?format=raw&offset=0"
        )

    def test_a_controller_session_gone_under_a_run_is_resumed(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        relaying: tuple[str, uuid.UUID, list[str], list[int]],
        relay_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        name, run_id, lines, offsets = relaying

        committed_controller_client.end_session(ENV, name)

        relay_log.wait_for(rf"Session {run_id} lost controller session {name}; .*")
        wait_until(
            lambda: fake_controller.session(ENV, "claude-2").status == "busy",
            "the continue sent",
        )
        second = _turn_of(fake_controller, "claude-2", raw_turn("turn_text"))
        _idle(container, run_id)

        self._assert_resumed(container, run_id, lines, offsets, second)
        assert not relay_log.matching(r"Environment .* waiting for it to settle")

    def test_the_resumes_token_hash_is_committed_before_its_turn_is_sent(
        self,
        committed_app: Flask,
        supervise: Supervise,
        relay_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        fake = _SendWatched(keepalive_seconds=0.2)
        try:
            client = client_of(container, fake)
            relays, coordinator = _relay_service(container, supervise, mcp_url=MCP_URL)
            name = _headless(fake, client)
            run_id, person_id = _committed_session(container, name)
            coordinator.fire_startup()
            _send_committed(container, relays, run_id, person_id)
            before = _read(container, run_id).token_hash
            at_send: list[tuple[str, str]] = []
            fake.on_send = lambda sent: at_send.append(
                (sent, _read(container, run_id).token_hash)
            )

            client.end_session(ENV, name)

            relay_log.wait_for(rf"Session {run_id} lost controller session {name}; .*")
            wait_until(
                lambda: fake.session(ENV, "claude-2").status == "busy",
                "the continue sent",
            )
            token = _token(fake.session(ENV, "claude-2").create_body)
            assert at_send == [("claude-2", token_hash(token))]
            assert token_hash(token) != before
        finally:
            fake.close()

    def test_a_restart_before_the_first_line_resumes_with_the_ended_turns_message(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        relay_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        relays, coordinator = _relay_service(container, supervise)
        name = _headless(fake_controller, committed_controller_client)
        run_id, person_id = _committed_session(container, name)
        coordinator.fire_startup()
        _send_committed(container, relays, run_id, person_id)

        fake_controller.restart(ENV)

        relay_log.wait_for(
            rf"Environment {ENV} is not running: waiting for it to settle"
        )
        # No line was recorded: there is no conversation to carry on.
        assert _read(container, run_id).conversation_id is None
        fake_controller.set_status(ENV, "running")
        relay_log.wait_for(rf"Session {run_id} lost controller session {name}; .*")
        wait_until(
            lambda: fake_controller.session(ENV, "claude-2").status == "busy",
            "the brief sent again",
        )
        _turn_of(fake_controller, "claude-2", raw_turn("turn_text"))
        _idle(container, run_id)
        brief, again = _committed_turns(container, run_id)
        assert (again.message, again.author_user_id) == (brief.message, None)
        assert brief.message == "Rename the badge"

    def test_an_environment_stopped_under_a_run_stops_it(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        relaying: tuple[str, uuid.UUID, list[str], list[int]],
        relay_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        name, run_id, lines, offsets = relaying

        committed_controller_client.stop_environment(ENV)

        wait_until(
            lambda: _read(container, run_id).state_code == SessionState.STOPPED,
            "the session stopped",
        )
        run = _read(container, run_id)
        assert (run.stopped_by_user_id, run.current_line) == (None, None)
        assert run.controller_session == name
        last = _committed_records(container, run_id)[-1]
        assert (last.turn, last.record.payload["cause"]) == (
            1,
            StopCause.ENVIRONMENT_STOPPED,
        )
        [turn] = _committed_turns(container, run_id)
        assert turn.ended_at == run.stopped_at
        assert _claude_committed(container, run_id) == _recorded(lines[:11], offsets)
        assert fake_controller.sessions(ENV) == []
        assert relay_log.matching(rf"Session {run_id} stopped under its turn: .*")


def _line_text(container: ServiceContainer, run_id: uuid.UUID) -> str | None:
    line = _read(container, run_id).current_line
    return None if line is None else line.get("text")


class TestTwoProcesses:
    """Two supervisors on one database, as a roll's overlap runs them (§8.1;
    V14)."""

    def test_two_relays_of_one_turn_record_every_line_once(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
    ) -> None:
        container = committed_app.container
        name = _headless(fake_controller, committed_controller_client)
        run_id, _ = _committed_session(container, name)
        _running_committed(container, run_id)
        committed_controller_client.send_message(ENV, name, "Rename the badge")
        _, one = _relay_service(container, supervise)
        _, other = _relay_service(container, supervise)

        with listening(SUPERVISOR_LOGGER) as log:
            one.fire_startup()
            other.fire_startup()
            wait_until(lambda: metric_value(RELAYS_RUNNING) == 2, "both relaying")
            lines = raw_turn("turn_subagent")
            offsets = _turn_of(fake_controller, name, lines)
            _idle(container, run_id)
            log.wait_for(rf"Loop relay:{run_id} ended", count=2)

        records = _committed_records(container, run_id)
        assert [s.record.seq for s in records] == list(range(1, len(records) + 1))
        assert _claude_committed(container, run_id) == _recorded(lines, offsets)
        assert [s.record.kind_code for s in records].count(RecordKind.RESULT) == 1

    def test_two_relays_resume_a_gone_session_once(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
    ) -> None:
        container = committed_app.container
        name = _headless(fake_controller, committed_controller_client)
        run_id, _ = _committed_session(container, name)
        _running_committed(container, run_id)
        committed_controller_client.send_message(ENV, name, "Rename the badge")
        _, one = _relay_service(container, supervise)
        _, other = _relay_service(container, supervise)
        one.fire_startup()
        other.fire_startup()
        wait_until(lambda: metric_value(RELAYS_RUNNING) == 2, "both relaying")

        with listening(RELAY_LOGGER) as log:
            committed_controller_client.end_session(ENV, name)
            # A relay opens the stream only once its send was made or refused,
            # and a send after the turn's end starts a turn of its own.
            wait_until(
                lambda: _streams(fake_controller, "claude-2") >= 2,
                "both relays past their send",
            )
            _turn_of(fake_controller, "claude-2", raw_turn("turn_text"))
            _idle(container, run_id)

        assert len(log.matching(r"Session .* lost controller session .*")) == 1
        assert [s.name for s in fake_controller.sessions(ENV)] == ["claude-2"]
        # No line was recorded, so the Session has no conversation: the resume
        # sends the ended Turn's message again.
        assert [turn.message for turn in _committed_turns(container, run_id)] == [
            "Rename the badge",
            "Rename the badge",
        ]
        assert _sends(fake_controller, "claude-2") >= 1
        servers = [
            s
            for s in _committed_records(container, run_id)
            if s.record.kind_code == RecordKind.SERVER
        ]
        assert len(servers) == 1

    def test_a_send_after_another_process_resumed_the_session_sends_to_its_one(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        container = committed_app.container
        fake = _GoneOnce(keepalive_seconds=0.2)
        try:
            client = client_of(container, fake)
            relays, _ = _relay_service(container, supervise)
            name = _headless(fake, client)
            run_id, _ = _committed_session(container, name)
            client.end_session(ENV, name)

            def another_process_resumes() -> None:
                # Its resume committed between this send's 404 and its lock.
                created = client.create_headless_session(ENV, HeadlessCreateRequest())
                with scoped_session(container) as db:
                    run = db.get_one(models.Session, run_id)
                    run.controller_session = created.name

            fake.after_404 = another_process_resumes
            create = f"POST /environments/{ENV}/sessions/headless"
            creates = fake.calls.count(create)

            with scoped_session(container) as db:
                turn = relays.send(db, run_id, "Rename the badge")
                assert turn.error is None
        finally:
            fake.close()

        assert [(s.name, s.status) for s in fake.sessions(ENV)] == [
            ("claude-2", "busy")
        ]
        assert fake.calls.count(create) == creates + 1
        assert _read(container, run_id).controller_session == "claude-2"
        assert _committed_records(container, run_id) == []

    def test_two_shutdown_timers_stop_an_environment_once(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
    ) -> None:
        container = committed_app.container
        fake_controller.add_environment(ENV, status="running")
        with scoped_session(container) as db:
            _environment_row(
                db,
                pod=fake_controller.environment(ENV).pod_started_at,
                due=datetime.now(UTC) - timedelta(seconds=1),
            )
        _, one = _relay_service(container, supervise)
        _, other = _relay_service(container, supervise)
        ticks = metric_value(TIMER_RUNS_TOTAL, timer=SHUTDOWN_TIMER, outcome="ok")

        with listening("app.services.environment_service") as log:
            one.fire_startup()
            other.fire_startup()
            log.wait_for(rf"Stopped environment {ENV}, due .*")
            wait_until(
                lambda: (
                    metric_value(TIMER_RUNS_TOTAL, timer=SHUTDOWN_TIMER, outcome="ok")
                    >= ticks + 6
                ),
                "three ticks of each",
            )

        assert fake_controller.calls.count(f"POST /environments/{ENV}/stop") == 1
        assert len(log.matching(r"Stopped environment .*")) == 1
        assert _row_committed(container).server_started_at is None


def _row_committed(container: ServiceContainer) -> Environment:
    with scoped_session(container) as db:
        row = _row(db)
        db.expunge(row)
        return row
