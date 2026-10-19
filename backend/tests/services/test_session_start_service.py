"""The session start (design 2 §13.2, §7.1; F88.1, F125; decision 38; V05, V15,
V19).

The start's write and its loop's run are on the test's session: the run is
called as its loop calls it. `TestStartLoop` runs the loop from the write's
commit on a database of its own, as the supervisor does, to the turn's end and
the shutdown timer's stop."""

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flask import Flask
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from werkzeug.wrappers import Request, Response

from app import models
from app.database import scoped_session
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import Environment, Project, Turn, User
from app.models.reference import RecordKind, SessionState, UserKind
from app.services.container import ServiceContainer
from app.services.controller_client import (
    ControllerProblem,
    ControllerProblemType,
    HeadlessCreateRequest,
)
from app.services.environment_service import EnvironmentService
from app.services.fake_controller import FakeControllerProblem
from app.services.relay_service import SEND_FAILED, RelayService
from app.services.session_record_service import StoredRecord, read_records
from app.services.session_start_service import (
    START_FAILED,
    STARTING,
    SessionOptions,
    SessionStartService,
)
from app.services.supervisor import LoopHandle
from app.utils.after_commit import clear_after_commit_callbacks
from app.utils.lifecycle_coordinator import LifecycleCoordinator
from tests.support.fake_controller import ServedFakeController, client_of, raw_turn
from tests.support.supervisor import LogWaiter, Supervise, listening, wait_until

ENV = "env-a"
CWD = "/work/Example"
BRIEF = "Rename the badge."
STOP_AFTER = timedelta(minutes=30)
STARTING_ENV = {"type": STARTING, "text": "Starting Env-A…"}
CREATING = {"type": STARTING, "text": "Creating the session…"}
SUPERVISOR_LOGGER = "app.services.supervisor"


class _Recording(ServedFakeController):
    """The fake, keeping each headless create's body, and refusing every send
    with `502 worker-unreachable` while `refuse_sends` is set. `during_create`
    and `during_settle`, when set, run once, as a create or an environment's
    `wait` is answered: another process's action then."""

    def __init__(self, keepalive_seconds: float) -> None:
        super().__init__(keepalive_seconds)
        self.create_bodies: list[dict[str, Any]] = []
        self.refuse_sends = False
        self.during_create: Callable[[], None] | None = None
        self.during_settle: Callable[[], None] | None = None

    def _get_environment(self, request: Request, env_id: str) -> Response:
        if "wait" in request.args:
            hook, self.during_settle = self.during_settle, None
            if hook is not None:
                hook()
        return super()._get_environment(request, env_id)

    def _create_session(self, request: Request, env_id: str) -> Response:
        self.create_bodies.append(request.get_json(silent=True) or {})
        hook, self.during_create = self.during_create, None
        if hook is not None:
            hook()
        return super()._create_session(request, env_id)

    def _send(self, request: Request, env_id: str, name: str) -> Response:
        if self.refuse_sends:
            raise FakeControllerProblem(
                502, "worker-unreachable", f"the worker of {env_id} does not answer"
            )
        return super()._send(request, env_id, name)


@pytest.fixture(autouse=True)
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


@pytest.fixture
def fake(container: ServiceContainer) -> Iterator[_Recording]:
    """The fake controller, `container`'s client on it, with the environment
    `ENV`, stopped."""
    served = _Recording(keepalive_seconds=0.2)
    client_of(container, served)
    served.add_environment(ENV, name="Env-A")
    try:
        yield served
    finally:
        served.close()


def _services(
    container: ServiceContainer,
    supervise: Supervise,
    *,
    stop_after: timedelta = STOP_AFTER,
    controller_configured: bool = True,
) -> tuple[SessionStartService, EnvironmentService, LifecycleCoordinator]:
    supervisor, coordinator = supervise(container)
    environments = EnvironmentService(
        container=container,
        supervisor=supervisor,
        stop_after_seconds=stop_after.total_seconds(),
    )
    relays = RelayService(
        container=container,
        supervisor=supervisor,
        session_streams=container.session_stream_service(),
        environment_service=environments,
    )
    starts = SessionStartService(
        container=container,
        supervisor=supervisor,
        session_streams=container.session_stream_service(),
        environment_service=environments,
        relay_service=relays,
        controller_configured=controller_configured,
    )
    return starts, environments, coordinator


@pytest.fixture
def starts(
    container: ServiceContainer, fake: _Recording, supervise: Supervise
) -> SessionStartService:
    """The session starts on the test's session; no loop of theirs ever runs."""
    return _services(container, supervise)[0]


def _start(
    starts: SessionStartService,
    db: DbSession,
    project: Project,
    options: SessionOptions | None = None,
) -> models.Session:
    run = starts.start_session(
        db,
        project.id,
        ENV,
        kind_code="work",
        cwd=CWD,
        brief=BRIEF,
        options=options,
    )
    clear_after_commit_callbacks()
    return run


def _run(starts: SessionStartService, run: models.Session) -> None:
    """The start loop's run, as its loop calls it."""
    starts.run(run.id, LoopHandle(f"start:{run.id}"))


def _records(db: DbSession, run_id: uuid.UUID) -> list[StoredRecord]:
    return read_records(db, run_id, limit=1000)


def _server(db: DbSession, run_id: uuid.UUID) -> list[tuple[int | None, Any]]:
    """The Session's `server` records: each one's Turn's number and payload."""
    return [
        (stored.turn, stored.record.payload)
        for stored in _records(db, run_id)
        if stored.record.kind_code == RecordKind.SERVER
    ]


def _turns(db: DbSession, run_id: uuid.UUID) -> list[Turn]:
    return list(
        db.scalars(
            select(Turn)
            .where(Turn.session_id == run_id)
            .order_by(Turn.seq)
            .execution_options(populate_existing=True)
        )
    )


def _read(db: DbSession, run_id: uuid.UUID) -> models.Session:
    return db.get_one(models.Session, run_id, populate_existing=True)


def _row(db: DbSession) -> Environment:
    return db.get_one(Environment, ENV, populate_existing=True)


def _assert_failed(
    db: DbSession, run_id: uuid.UUID, reason: str | None = None
) -> models.Session:
    """The Session `failed` (F125): its error, its brief no longer in flight,
    no current line."""
    run = _read(db, run_id)
    assert run.state_code == SessionState.FAILED
    assert run.error is not None
    if reason is not None:
        assert run.error == reason
    assert run.current_line is None
    (brief,) = _turns(db, run_id)
    assert brief.ended_at is not None
    assert run.turn_ended_at == brief.ended_at
    return run


class TestStartSession:
    def test_it_writes_the_session_starting_and_its_brief_before_the_environment_is_up(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        options = SessionOptions(
            agent="worker", model="opus", reasoning_effort="high", resume="conv-1"
        )

        run = _start(starts, session, project, options)

        run = _read(session, run.id)
        assert run.state_code == SessionState.STARTING
        assert (run.project_id, run.environment_id, run.kind_code, run.cwd) == (
            project.id,
            ENV,
            "work",
            CWD,
        )
        assert (run.agent, run.model, run.reasoning_effort) == (
            "worker",
            "opus",
            "high",
        )
        assert run.conversation_id == "conv-1"
        assert run.controller_session is None and run.started_at is None
        assert len(run.token_hash) == 64
        int(run.token_hash, 16)
        (brief,) = _turns(session, run.id)
        assert (brief.seq, brief.message, brief.author_user_id) == (1, BRIEF, None)
        assert brief.ended_at is None
        assert (run.turns, run.turn_started_at, run.turn_ended_at) == (
            1,
            brief.started_at,
            None,
        )
        (record,) = _records(session, run.id)
        assert (record.turn, record.record.payload) == (None, STARTING_ENV)
        assert run.current_line == {
            "state": "starting",
            "since": record.record.at.isoformat(),
            "text": "Starting Env-A…",
        }
        assert fake.environment(ENV).status == "stopped"
        assert fake.calls == [f"GET /environments/{ENV}"]

    def test_pilots_first_touch_makes_the_environments_row(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        _start(starts, session, project)

        row = _row(session)
        assert (row.name, row.last_state, row.server_started_at) == (
            "Env-A",
            "stopped",
            None,
        )

    def test_it_clears_the_environments_shutdown_timer(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        session.add(
            Environment(
                id=ENV,
                name="Env-A",
                exempt=False,
                server_started_at=datetime.now(UTC) - timedelta(hours=1),
                stop_due_at=datetime.now(UTC) + STOP_AFTER,
            )
        )
        session.flush()

        _start(starts, session, project)

        assert _row(session).stop_due_at is None
        assert fake.calls == []

    def test_each_session_gets_a_token_of_its_own(
        self, starts: SessionStartService, session: DbSession, project: Project
    ) -> None:
        first = _start(starts, session, project)
        second = _start(starts, session, project)

        assert first.token_hash != second.token_hash

    def test_an_unknown_project_is_not_found(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
    ) -> None:
        with pytest.raises(RecordNotFoundException):
            starts.start_session(
                session, uuid.uuid4(), ENV, kind_code="work", cwd=CWD, brief=BRIEF
            )

        assert session.scalars(select(models.Session)).all() == []
        assert fake.calls == []

    def test_an_environment_the_controller_lacks_is_not_found(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        with pytest.raises(ControllerProblem) as raised:
            starts.start_session(
                session,
                project.id,
                "env-missing",
                kind_code="work",
                cwd=CWD,
                brief=BRIEF,
            )

        assert raised.value.problem_type is ControllerProblemType.NOT_FOUND
        assert session.scalars(select(models.Session)).all() == []
        assert session.get(Environment, "env-missing") is None

    def test_no_controller_refuses_it(
        self,
        container: ServiceContainer,
        fake: _Recording,
        supervise: Supervise,
        session: DbSession,
        project: Project,
    ) -> None:
        starts = _services(container, supervise, controller_configured=False)[0]

        with pytest.raises(InvalidOperationException, match="no controller"):
            _start(starts, session, project)

        assert session.scalars(select(models.Session)).all() == []
        assert fake.calls == []


class TestRun:
    def test_it_brings_the_environment_up_creates_the_session_and_sends_the_brief(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        run = _start(starts, session, project)
        written = _turns(session, run.id)[0].started_at

        _run(starts, run)

        assert fake.environment(ENV).status == "running"
        assert _row(session).server_started_at is not None
        (created,) = fake.sessions(ENV)
        assert created.status == "busy"
        run = _read(session, run.id)
        assert run.state_code == SessionState.RUNNING
        assert run.controller_session == created.name
        assert run.started_at is not None
        assert _server(session, run.id) == [(None, STARTING_ENV), (None, CREATING)]
        creating = _records(session, run.id)[-1].record
        # The send keeps the start's line until the stream's first line.
        assert run.current_line == {
            "state": "starting",
            "since": creating.at.isoformat(),
            "text": "Creating the session…",
        }
        (brief,) = _turns(session, run.id)
        assert brief.started_at > written and brief.ended_at is None
        assert run.turn_started_at == brief.started_at
        assert _row(session).stop_due_at is None
        assert (
            f"POST /environments/{ENV}/sessions/headless/{created.name}/messages"
            in (fake.calls)
        )

    def test_the_create_carries_the_sessions_options(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        options = SessionOptions(
            agent="worker", model="opus", reasoning_effort="high", resume="conv-1"
        )
        run = _start(starts, session, project, options)

        _run(starts, run)

        assert fake.create_bodies == [
            {
                "cwd": CWD,
                "resume": "conv-1",
                "agent": "worker",
                "model": "opus",
                "reasoningEffort": "high",
            }
        ]

    def test_a_fresh_session_resumes_nothing(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        _run(starts, _start(starts, session, project))

        assert fake.create_bodies == [{"cwd": CWD}]

    def test_a_session_already_created_has_its_brief_sent_alone(
        self,
        container: ServiceContainer,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        # A run cut after the create: its rows say the session exists.
        run = _start(starts, session, project)
        fake.set_status(ENV, "running")
        name = (
            container.controller_client()
            .create_headless_session(ENV, HeadlessCreateRequest())
            .name
        )
        run.controller_session = name
        session.flush()
        before = len(fake.calls)

        _run(starts, run)

        assert fake.calls[before:] == [
            f"GET /environments/{ENV}/sessions/{name}",
            f"POST /environments/{ENV}/sessions/headless/{name}/messages",
        ]
        assert _read(session, run.id).state_code == SessionState.RUNNING
        assert _server(session, run.id) == [(None, STARTING_ENV)]

    @pytest.mark.parametrize(
        "state", [SessionState.RUNNING, SessionState.FAILED, SessionState.ENDED]
    )
    def test_a_session_no_longer_starting_is_left_alone(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        state: SessionState,
    ) -> None:
        run = _start(starts, session, project)
        run.state_code = state
        session.flush()
        before = len(fake.calls)

        _run(starts, run)

        assert fake.calls[before:] == []
        assert _read(session, run.id).state_code == state

    def test_a_stop_between_the_phases_leaves_the_start_where_it_was(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        run = _start(starts, session, project)
        stopped = LoopHandle(f"start:{run.id}")
        stopped._request_stop()

        starts.run(run.id, stopped)

        assert fake.environment(ENV).status == "running"
        assert fake.sessions(ENV) == []
        run = _read(session, run.id)
        assert run.state_code == SessionState.STARTING
        assert _server(session, run.id) == [(None, STARTING_ENV)]

        _run(starts, run)

        assert _read(session, run.id).state_code == SessionState.RUNNING
        assert _server(session, run.id) == [(None, STARTING_ENV), (None, CREATING)]


class TestRunFails:
    def test_admission_blocked_fails_the_session(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        fake.capped(ENV)
        run = _start(starts, session, project)

        _run(starts, run)

        run = _assert_failed(session, run.id)
        assert run.error is not None and "environment limit" in run.error
        assert _server(session, run.id) == [
            (None, STARTING_ENV),
            (None, {"type": START_FAILED, "reason": run.error}),
        ]
        assert fake.create_bodies == []

    @pytest.mark.parametrize("status", ["error", "stopped"])
    def test_an_environment_that_settles_other_than_running_fails_the_session(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        status: str,
    ) -> None:
        fake.settle_starts(ENV, status)
        run = _start(starts, session, project)

        _run(starts, run)

        run = _assert_failed(session, run.id)
        assert run.error is not None and f"it settled {status}" in run.error
        assert _server(session, run.id) == [
            (None, STARTING_ENV),
            (None, {"type": START_FAILED, "reason": run.error}),
        ]
        assert fake.create_bodies == []

    def test_a_create_the_controller_refuses_fails_the_session(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        fake.unreachable(ENV)
        run = _start(starts, session, project)

        _run(starts, run)

        run = _assert_failed(session, run.id)
        assert run.error is not None and "worker-unreachable" in run.error
        assert run.controller_session is None
        assert _server(session, run.id) == [
            (None, STARTING_ENV),
            (None, CREATING),
            (None, {"type": START_FAILED, "reason": run.error}),
        ]

    def test_a_brief_whose_send_fails_fails_the_session_with_the_turns_error(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        fake.refuse_sends = True
        run = _start(starts, session, project)

        _run(starts, run)

        (brief,) = _turns(session, run.id)
        assert brief.error is not None and "worker-unreachable" in brief.error
        run = _assert_failed(session, run.id, brief.error)
        assert run.controller_session is not None
        # The send's own record says so, in the brief's Turn.
        assert _server(session, run.id) == [
            (None, STARTING_ENV),
            (None, CREATING),
            (1, {"type": SEND_FAILED, "reason": brief.error}),
        ]

    @pytest.mark.parametrize("failure", ["create", "send"])
    def test_a_failed_start_has_the_environment_pilot_started_stopped(
        self,
        container: ServiceContainer,
        fake: _Recording,
        supervise: Supervise,
        session: DbSession,
        project: Project,
        failure: str,
    ) -> None:
        # Review r1, B2 (F125): no time to stand idle, so the next tick is due.
        starts, environments, _ = _services(
            container, supervise, stop_after=timedelta(0)
        )
        if failure == "create":
            fake.unreachable(ENV)
        else:
            fake.refuse_sends = True
        run = _start(starts, session, project)

        _run(starts, run)

        _assert_failed(session, run.id)
        assert _row(session).stop_due_at is not None
        environments.run_shutdown_timer(session)
        assert fake.environment(ENV).status == "stopped"
        row = _row(session)
        assert (row.stop_due_at, row.server_started_at) == (None, None)

    def test_a_failed_start_leaves_the_timer_unarmed_while_another_session_runs_there(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        other = _start(starts, session, project)
        other.state_code = SessionState.RUNNING
        fake.unreachable(ENV)
        run = _start(starts, session, project)

        _run(starts, run)

        _assert_failed(session, run.id)
        row = _row(session)
        assert row.server_started_at is not None and row.stop_due_at is None

    def test_a_start_pilot_did_not_make_arms_nothing(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        fake.set_status(ENV, "running")
        fake.unreachable(ENV)
        run = _start(starts, session, project)

        _run(starts, run)

        _assert_failed(session, run.id)
        row = _row(session)
        assert (row.server_started_at, row.stop_due_at) == (None, None)


def _committed_project(container: ServiceContainer) -> uuid.UUID:
    with scoped_session(container) as db:
        person = User(
            kind_code=UserKind.PERSON,
            subject="subject-ada",
            handle="ada",
            name="Ada Example",
            avatar_slot=1,
        )
        db.add(person)
        db.flush()
        project = Project(created_by_user_id=person.id)
        db.add(project)
        db.flush()
        return project.id


def _committed(container: ServiceContainer, run_id: uuid.UUID) -> models.Session:
    with scoped_session(container) as db:
        run = db.get_one(models.Session, run_id)
        db.expunge(run)
        return run


class TestStartLoop:
    @pytest.fixture
    def loop_log(self) -> Iterator[LogWaiter]:
        with listening(SUPERVISOR_LOGGER) as waiter:
            yield waiter

    @pytest.fixture
    def committed_fake(self, committed_app: Flask) -> Iterator[_Recording]:
        served = _Recording(keepalive_seconds=0.2)
        client_of(committed_app.container, served)
        served.add_environment(ENV, name="Env-A")
        try:
            yield served
        finally:
            served.close()

    def test_a_start_runs_from_its_commit_to_the_turns_end_and_the_timers_stop(
        self,
        committed_app: Flask,
        committed_fake: _Recording,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        starts, _, coordinator = _services(
            container, supervise, stop_after=timedelta(seconds=0.2)
        )
        project_id = _committed_project(container)
        coordinator.fire_startup()

        with scoped_session(container) as db:
            run_id = starts.start_session(
                db, project_id, ENV, kind_code="work", cwd=CWD, brief=BRIEF
            ).id

        loop_log.wait_for(rf"Loop start:{run_id} started")
        loop_log.wait_for(rf"Loop start:{run_id} ended")
        loop_log.wait_for(rf"Loop relay:{run_id} started")
        run = _committed(container, run_id)
        assert run.state_code == SessionState.RUNNING
        assert run.controller_session is not None
        committed_fake.play(ENV, run.controller_session, raw_turn("turn_text"))
        committed_fake.finish(ENV, run.controller_session, "success", "Done.")
        wait_until(
            lambda: _committed(container, run_id).state_code == SessionState.IDLE,
            "the brief's turn ended",
        )
        wait_until(
            lambda: committed_fake.environment(ENV).status == "stopped",
            "the shutdown timer stopped the environment",
        )
        with scoped_session(container) as db:
            kinds = [stored.record.kind_code for stored in _records(db, run_id)]
        assert kinds[:2] == [RecordKind.SERVER, RecordKind.SERVER]
        assert kinds[-1] == RecordKind.RESULT
        assert set(kinds[2:-1]) == {RecordKind.CLAUDE}

    def test_startup_resumes_a_start_that_was_cut(
        self,
        committed_app: Flask,
        committed_fake: _Recording,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        project_id = _committed_project(container)
        # A process that wrote the Session and was gone before its loop ran.
        cut, _, _ = _services(container, supervise)
        with scoped_session(container) as db:
            run_id = cut.start_session(
                db, project_id, ENV, kind_code="work", cwd=CWD, brief=BRIEF
            ).id
        _, _, coordinator = _services(container, supervise)

        with listening(START_LOGGER) as log:
            coordinator.fire_startup()
            log.wait_for(rf"Resuming the start of session {run_id}")

        loop_log.wait_for(rf"Loop relay:{run_id} started")
        run = _committed(container, run_id)
        assert run.state_code == SessionState.RUNNING
        assert run.controller_session is not None
        assert committed_fake.create_bodies == [{"cwd": CWD}]
        assert _sends(committed_fake, run.controller_session) == 1

    def test_a_brief_the_controller_got_before_a_cut_is_not_sent_again(
        self,
        committed_app: Flask,
        committed_fake: _Recording,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        project_id = _committed_project(container)
        cut, _, _ = _services(container, supervise)
        with scoped_session(container) as db:
            run_id = cut.start_session(
                db, project_id, ENV, kind_code="work", cwd=CWD, brief=BRIEF
            ).id
        # The cut process created the session and sent the brief; the send's
        # commit was lost.
        committed_fake.set_status(ENV, "running")
        client = container.controller_client()
        name = client.create_headless_session(ENV, HeadlessCreateRequest()).name
        with scoped_session(container) as db:
            db.get_one(models.Session, run_id).controller_session = name
        client.send_message(ENV, name, BRIEF)
        _, _, coordinator = _services(container, supervise)

        coordinator.fire_startup()

        loop_log.wait_for(rf"Loop relay:{run_id} started")
        assert _committed(container, run_id).state_code == SessionState.RUNNING
        assert _sends(committed_fake, name) == 1
        committed_fake.play(ENV, name, raw_turn("turn_text"))
        committed_fake.finish(ENV, name, "success", "Done.")
        wait_until(
            lambda: _committed(container, run_id).state_code == SessionState.IDLE,
            "the brief's turn ended",
        )

    def test_a_controller_session_another_process_recorded_first_stands(
        self,
        committed_app: Flask,
        committed_fake: _Recording,
        supervise: Supervise,
    ) -> None:
        container = committed_app.container
        starts, _, _ = _services(container, supervise)
        project_id = _committed_project(container)
        with scoped_session(container) as db:
            run_id = starts.start_session(
                db, project_id, ENV, kind_code="work", cwd=CWD, brief=BRIEF
            ).id
        client = container.controller_client()
        other: list[str] = []

        def another_process_creates() -> None:
            # Its create answered, and its commit, before this run's.
            other.append(
                client.create_headless_session(ENV, HeadlessCreateRequest()).name
            )
            with scoped_session(container) as db:
                db.get_one(models.Session, run_id).controller_session = other[0]

        committed_fake.during_create = another_process_creates

        starts.run(run_id, LoopHandle(f"start:{run_id}"))

        run = _committed(container, run_id)
        assert run.controller_session == other[0]
        assert run.started_at is None
        assert run.state_code == SessionState.RUNNING
        assert committed_fake.session(ENV, other[0]).status == "busy"
        orphan = [s.name for s in committed_fake.sessions(ENV) if s.name != other[0]]
        assert [committed_fake.session(ENV, n).status for n in orphan] == ["idle"]

    def test_a_failure_after_another_process_ran_the_session_changes_nothing(
        self,
        committed_app: Flask,
        committed_fake: _Recording,
        supervise: Supervise,
    ) -> None:
        container = committed_app.container
        starts, _, _ = _services(container, supervise)
        project_id = _committed_project(container)
        with scoped_session(container) as db:
            run_id = starts.start_session(
                db, project_id, ENV, kind_code="work", cwd=CWD, brief=BRIEF
            ).id

        def another_process_runs_it() -> None:
            with scoped_session(container) as db:
                db.get_one(models.Session, run_id).state_code = SessionState.RUNNING
            committed_fake.unreachable(ENV)

        committed_fake.during_create = another_process_runs_it

        starts.run(run_id, LoopHandle(f"start:{run_id}"))

        run = _committed(container, run_id)
        assert (run.state_code, run.error) == (SessionState.RUNNING, None)
        with scoped_session(container) as db:
            assert [payload for _, payload in _server(db, run_id)] == [
                STARTING_ENV,
                CREATING,
            ]

    @pytest.mark.parametrize("state", [SessionState.RUNNING, SessionState.IDLE])
    def test_a_session_another_process_moved_on_while_its_environment_came_up_is_left_alone(
        self,
        committed_app: Flask,
        committed_fake: _Recording,
        supervise: Supervise,
        state: SessionState,
    ) -> None:
        container = committed_app.container
        starts, _, _ = _services(container, supervise)
        project_id = _committed_project(container)
        with scoped_session(container) as db:
            run_id = starts.start_session(
                db, project_id, ENV, kind_code="work", cwd=CWD, brief=BRIEF
            ).id
        client = container.controller_client()
        other: list[str] = []
        lines: list[dict[str, Any] | None] = []

        def another_process_runs_it() -> None:
            # Its create and its brief's send committed, and at `idle` the
            # brief's turn ended, before this run's environment start returns.
            name = client.create_headless_session(ENV, HeadlessCreateRequest()).name
            client.send_message(ENV, name, BRIEF)
            other.append(name)
            now = datetime.now(UTC)
            lines.append(
                {"state": "thinking", "since": now.isoformat()}
                if state == SessionState.RUNNING
                else None
            )
            with scoped_session(container) as db:
                run = db.get_one(models.Session, run_id)
                run.controller_session = name
                run.state_code = state
                run.current_line = lines[0]
                if state == SessionState.IDLE:
                    _turns(db, run_id)[0].ended_at = now
            if state == SessionState.IDLE:
                committed_fake.finish(ENV, name, "success", "Done.")

        committed_fake.during_settle = another_process_runs_it

        starts.run(run_id, LoopHandle(f"start:{run_id}"))

        run = _committed(container, run_id)
        assert (run.state_code, run.controller_session) == (state, other[0])
        assert run.current_line == lines[0]
        with scoped_session(container) as db:
            assert [payload for _, payload in _server(db, run_id)] == [STARTING_ENV]
        assert [s.name for s in committed_fake.sessions(ENV)] == other
        assert _sends(committed_fake, other[0]) == 1

    def test_a_controller_session_another_process_recorded_while_its_environment_came_up_gets_the_brief(
        self,
        committed_app: Flask,
        committed_fake: _Recording,
        supervise: Supervise,
    ) -> None:
        container = committed_app.container
        starts, _, _ = _services(container, supervise)
        project_id = _committed_project(container)
        with scoped_session(container) as db:
            run_id = starts.start_session(
                db, project_id, ENV, kind_code="work", cwd=CWD, brief=BRIEF
            ).id
        client = container.controller_client()
        other: list[str] = []

        def another_process_creates_and_stops() -> None:
            # Its create committed, and its loop told to stop before the send.
            other.append(
                client.create_headless_session(ENV, HeadlessCreateRequest()).name
            )
            with scoped_session(container) as db:
                db.get_one(models.Session, run_id).controller_session = other[0]

        committed_fake.during_settle = another_process_creates_and_stops

        starts.run(run_id, LoopHandle(f"start:{run_id}"))

        run = _committed(container, run_id)
        assert (run.state_code, run.controller_session) == (
            SessionState.RUNNING,
            other[0],
        )
        with scoped_session(container) as db:
            assert [payload for _, payload in _server(db, run_id)] == [STARTING_ENV]
        assert [s.name for s in committed_fake.sessions(ENV)] == other
        assert _sends(committed_fake, other[0]) == 1


START_LOGGER = "app.services.session_start_service"


def _sends(fake: ServedFakeController, name: str) -> int:
    return fake.calls.count(
        f"POST /environments/{ENV}/sessions/headless/{name}/messages"
    )
