"""The send and the relay (design 2 §9, §9.6; D004; F40.1's records, F40.4's
relay; V03, V06, V13, V15).

The send's tests and the relay's run on the test's session: the relay's run is
called as its loop calls it, once the fake holds the turn. The loop's tests run
it on a database of its own, from the send's commit, as the supervisor does."""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from queue import Empty
from typing import Any

import pytest
from flask import Flask
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from werkzeug.wrappers import Request, Response

from app import models
from app.database import scoped_session
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import DocumentVersion, Environment, Project, Turn, User
from app.models.reference import RecordKind, SessionState, UserKind, VersionCause
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerClient, HeadlessCreateRequest
from app.services.environment_service import EnvironmentService
from app.services.fake_controller import FinishOutcome
from app.services.relay_service import (
    PARTIALS_FORWARDED_TOTAL,
    RELAYS_RUNNING,
    SEND_FAILED,
    RelayService,
)
from app.services.session_record_service import (
    RECORDS_WRITTEN_TOTAL,
    StoredRecord,
    read_records,
)
from app.services.sse_connection_manager import SSEConnection
from app.services.supervisor import LoopHandle
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
SUBJECT = "subject-ada"
STOP_AFTER = timedelta(minutes=30)
SUPERVISOR_LOGGER = "app.services.supervisor"


@pytest.fixture(autouse=True)
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


def _relay_service(
    container: ServiceContainer, supervise: Supervise
) -> tuple[RelayService, LifecycleCoordinator]:
    supervisor, coordinator = supervise(container)
    environments = EnvironmentService(
        container=container,
        supervisor=supervisor,
        stop_after_seconds=STOP_AFTER.total_seconds(),
    )
    relays = RelayService(
        container=container,
        supervisor=supervisor,
        session_streams=container.session_stream_service(),
        environment_service=environments,
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


def _environment_row(db: DbSession, *, due: datetime | None = None) -> Environment:
    """The environment's row, as Pilot's own start left it."""
    row = Environment(
        id=ENV,
        name="Env-A",
        exempt=False,
        last_state="running",
        server_started_at=datetime.now(UTC) - timedelta(hours=1),
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
            ("busy", "409 session-busy"),
            ("unreachable", "502 worker-unreachable"),
            ("stopped", "409 conflict"),
            ("unknown", "404 not-found"),
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
            case "busy":
                fake_controller.busy(ENV, controller_session)
            case "unreachable":
                fake_controller.unreachable(ENV)
            case "stopped":
                fake_controller.set_status(ENV, "stopped")
            case "unknown":
                idle.controller_session = "claude-unknown"
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

    def test_turns_are_numbered_in_their_session(
        self,
        session: DbSession,
        relays: RelayService,
        fake_controller: ServedFakeController,
        controller_session: str,
        idle: models.Session,
    ) -> None:
        first = _send(relays, session, idle, "One")
        # The controller has the first in flight: the second fails.
        second = _send(relays, session, idle, "Two")

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


class _Replaying(ServedFakeController):
    """A controller that sends a session's raw file from its start, whatever
    the offset asked: what a relay meets when another process's relay has
    recorded the lines it reads."""

    def _response(self, request: Request, env_id: str, name: str) -> Response:
        environ = dict(request.environ, QUERY_STRING="format=raw&offset=0")
        return super()._response(Request(environ), env_id, name)


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
