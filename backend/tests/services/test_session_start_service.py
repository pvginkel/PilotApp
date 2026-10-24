"""The session start (design 2 §13.2, §7.1; F88.1, F125; decision 38; V05, V15,
V19), and a work item's (DB Work, decision 3); the gate every start passes, the
held start and its release (§13.4, §8.2; F141.5; DB 229, 230; V16, V24).

The start's write and its loop's run are on the test's session: the run is
called as its loop calls it. `TestStartLoop` and `TestHeldLoop` run the loops
from the write's commit on a database of their own, as the supervisor does."""

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from dependency_injector import providers
from flask import Flask
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from werkzeug.wrappers import Request, Response

from app import models
from app.database import scoped_session
from app.engine.bus import EngineEvent, ProjectChanged, WorkMoved
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import Environment, Item, PlanTask, Project, Turn, User, Work
from app.models.reference import (
    ProjectState,
    RecordKind,
    SessionState,
    TaskStatus,
    TransitionKind,
    UserKind,
)
from app.schemas.timeline import HeldReason
from app.services.auth_service import AuthContext
from app.services.container import ServiceContainer
from app.services.controller_client import (
    ControllerProblem,
    ControllerProblemType,
    HeadlessCreateRequest,
)
from app.services.controller_outage import ControllerOutage
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
from app.services.timeline_service import work_status
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
    with `502 worker-unreachable` while `refuse_sends` is set. `during_start`,
    `during_settle`, `during_create` and `during_snapshot`, when set, run once,
    as an environment's start, its `wait`, a create or a session's snapshot
    is answered: another process's action then, or the controller going down
    after that call."""

    def __init__(self, keepalive_seconds: float) -> None:
        super().__init__(keepalive_seconds)
        self.create_bodies: list[dict[str, Any]] = []
        self.refuse_sends = False
        self.during_start: Callable[[], None] | None = None
        self.during_create: Callable[[], None] | None = None
        self.during_settle: Callable[[], None] | None = None
        self.during_snapshot: Callable[[], None] | None = None

    def _start(self, request: Request, env_id: str) -> Response:
        hook, self.during_start = self.during_start, None
        if hook is not None:
            hook()
        return super()._start(request, env_id)

    def _get_session(self, request: Request, env_id: str, name: str) -> Response:
        hook, self.during_snapshot = self.during_snapshot, None
        if hook is not None:
            hook()
        return super()._get_session(request, env_id, name)

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
    outage: ControllerOutage | None = None,
) -> tuple[SessionStartService, EnvironmentService, LifecycleCoordinator]:
    """The start's services on a supervisor of their own, on the client's
    outage unless `outage` gives another, as a process of its own has."""
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
        controller_outage=outage or container.controller_outage(),
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


def _moves(events: list[EngineEvent]) -> list[EngineEvent]:
    """What the browsers hear of: the work items' moves and the projects'."""
    return [event for event in events if isinstance(event, WorkMoved | ProjectChanged)]


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


def _start_work(
    starts: SessionStartService,
    db: DbSession,
    project: Project,
    plan_task_id: str | None = None,
) -> Work:
    work = starts.start_work(
        db,
        project.id,
        ENV,
        title="Renaming the badge",
        brief=BRIEF,
        cwd=CWD,
        plan_task_id=plan_task_id,
    )
    clear_after_commit_callbacks()
    return work


class TestStartWork:
    def test_it_places_the_work_item_and_writes_its_sessions_start(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        work = _start_work(starts, session, project)

        item = session.get_one(Item, work.id)
        run = _read(session, work.id)
        assert (item.kind_code, item.title, item.seq) == (
            "work",
            "Renaming the badge",
            1,
        )
        assert item.created_by_session_id == run.id
        assert item.done_at is None
        assert (work.session_kind_code, work.autopilot) == ("work", project.autopilot)
        assert run.state_code == SessionState.STARTING
        assert (run.project_id, run.environment_id, run.kind_code, run.cwd) == (
            project.id,
            ENV,
            "work",
            CWD,
        )
        (brief,) = _turns(session, run.id)
        assert (brief.seq, brief.message, brief.author_user_id) == (1, BRIEF, None)
        assert _server(session, run.id) == [(None, STARTING_ENV)]

    def test_it_works_on_the_plans_task(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        session.add(
            PlanTask(
                project_id=project.id,
                task_id="badge",
                position=1,
                title="The badge",
                status_code=TaskStatus.PENDING,
            )
        )
        session.flush()

        work = _start_work(starts, session, project, "badge")

        assert session.get_one(Item, work.id).plan_task_id == "badge"

    def test_a_task_not_in_the_plan_is_not_found(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        with pytest.raises(RecordNotFoundException, match="Plan task"):
            _start_work(starts, session, project, "badge")

        assert session.scalars(select(Item)).all() == []

    def test_an_unknown_project_is_not_found(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
    ) -> None:
        with pytest.raises(RecordNotFoundException, match="Project"):
            starts.start_work(
                session, uuid.uuid4(), ENV, title="Renaming", brief=BRIEF, cwd=CWD
            )

        assert session.scalars(select(models.Session)).all() == []
        assert fake.calls == []

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
            _start_work(starts, session, project)

        assert session.scalars(select(Item)).all() == []
        assert fake.calls == []

    def test_a_failed_start_leaves_the_item_open_waiting_on_you(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        engine_events: list[EngineEvent],
    ) -> None:
        fake.capped(ENV)
        work = _start_work(starts, session, project)

        starts.run(work.id, LoopHandle(f"start:{work.id}"))

        _assert_failed(session, work.id)
        assert session.get_one(Item, work.id, populate_existing=True).done_at is None
        # The badge counts it: the project's screens are read again (R20).
        assert _moves(engine_events) == [
            WorkMoved(project.id, work.id),
            ProjectChanged(project.id),
        ]

    def test_each_phase_moves_the_item_and_the_brief_its_state(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        engine_events: list[EngineEvent],
    ) -> None:
        work = _start_work(starts, session, project)

        starts.run(work.id, LoopHandle(f"start:{work.id}"))

        moved = WorkMoved(project.id, work.id)
        # "Creating the session…", the session's start, then the brief's send,
        # which makes it `running`.
        assert _read(session, work.id).state_code == SessionState.RUNNING
        assert _moves(engine_events) == [
            moved,
            moved,
            moved,
            ProjectChanged(project.id),
        ]


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
        controller_outage: ControllerOutage,
    ) -> None:
        fake.unreachable(ENV)
        run = _start(starts, session, project)

        _run(starts, run)

        run = _assert_failed(session, run.id)
        assert run.error is not None and "worker-unreachable" in run.error
        assert run.controller_session is None
        # The controller answered, about one environment (review O2).
        assert not controller_outage.holds
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
        controller_outage: ControllerOutage,
    ) -> None:
        fake.refuse_sends = True
        run = _start(starts, session, project)

        _run(starts, run)

        (brief,) = _turns(session, run.id)
        assert brief.error is not None and "worker-unreachable" in brief.error
        assert not controller_outage.holds
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


def _held(
    starts: SessionStartService,
    db: DbSession,
    project: Project,
    *,
    kind_code: str = "work",
) -> models.Session:
    """A start the gate held, written as `_start` writes one."""
    run = starts.start_session(
        db, project.id, ENV, kind_code=kind_code, cwd=CWD, brief=BRIEF
    )
    clear_after_commit_callbacks()
    assert run.state_code == SessionState.HELD
    return run


def _release(starts: SessionStartService) -> None:
    """The release loop's run, as its loop calls it."""
    starts.release(LoopHandle("start:held"))


class TestStartThroughTheGate:
    def test_with_the_controller_unreachable_the_start_is_held_and_runs_nothing(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        controller_outage: ControllerOutage,
    ) -> None:
        _run(starts, _start(starts, session, project))
        due = datetime.now(UTC) + timedelta(minutes=5)
        _row(session).stop_due_at = due
        session.flush()
        controller_outage.call_unanswered()
        before = len(fake.calls)

        run = _start(starts, session, project)
        _run(starts, run)

        run = _read(session, run.id)
        assert run.state_code == SessionState.HELD
        assert (run.current_line, run.error, run.controller_session) == (
            None,
            None,
            None,
        )
        (brief,) = _turns(session, run.id)
        assert (brief.message, brief.ended_at, brief.error) == (BRIEF, None, None)
        assert _server(session, run.id) == []
        assert fake.calls[before:] == []
        # A held start does not hold the environment's timer.
        assert _row(session).stop_due_at == due

    def test_in_a_paused_project_the_start_is_held(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        project.paused = True
        session.flush()

        run = _start(starts, session, project)

        assert _read(session, run.id).state_code == SessionState.HELD
        assert _server(session, run.id) == []

    def test_a_chats_start_is_never_held_for_the_pause(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        controller_outage: ControllerOutage,
    ) -> None:
        project.paused = True
        session.flush()

        chat = starts.start_session(
            session, project.id, ENV, kind_code="chat", cwd=CWD, brief=BRIEF
        )
        controller_outage.call_unanswered()
        held = starts.start_session(
            session, project.id, ENV, kind_code="chat", cwd=CWD, brief=BRIEF
        )
        clear_after_commit_callbacks()

        assert _read(session, chat.id).state_code == SessionState.STARTING
        assert _server(session, chat.id) == [(None, STARTING_ENV)]
        # The outage holds a Chat's start as it holds every other.
        assert _read(session, held.id).state_code == SessionState.HELD

    @pytest.mark.parametrize(
        ("paused", "reason"),
        [(True, HeldReason.PAUSED), (False, HeldReason.CONTROLLER_UNREACHABLE)],
    )
    def test_a_held_work_item_is_placed_its_line_saying_why(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        controller_outage: ControllerOutage,
        paused: bool,
        reason: HeldReason,
    ) -> None:
        project.paused = paused
        session.flush()
        if not paused:
            controller_outage.call_unanswered()

        work = _start_work(starts, session, project)

        assert session.get_one(Item, work.id).done_at is None
        status = work_status(session, [work.id], unreachable=controller_outage.holds)[
            work.id
        ]
        assert (status.state, status.held_reason) == (SessionState.HELD, reason)
        assert status.current_line is None

    def test_its_first_touch_while_the_controller_does_not_answer_names_the_environment_by_its_id(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        controller_outage: ControllerOutage,
    ) -> None:
        fake.outage()

        run = starts.start_session(
            session, project.id, "env-new", kind_code="work", cwd=CWD, brief=BRIEF
        )
        clear_after_commit_callbacks()

        assert controller_outage.holds
        assert _read(session, run.id).state_code == SessionState.HELD
        row = session.get_one(Environment, "env-new")
        # Exempt until the fleet consumer's report says otherwise: the timer
        # arms nothing on a row the controller never described.
        assert (row.name, row.exempt, row.last_state) == ("env-new", True, None)


class TestRunHeld:
    @pytest.mark.parametrize("answer", ["none", "ingress"])
    @pytest.mark.parametrize(
        ("call", "phases", "created", "claim"),
        [
            ("start", [STARTING_ENV], False, "none"),
            ("settle", [STARTING_ENV], False, "no-pod"),
            ("create", [STARTING_ENV, CREATING], False, "pod"),
            ("snapshot", [STARTING_ENV, CREATING], True, "pod"),
            ("send", [STARTING_ENV, CREATING], True, "pod"),
        ],
    )
    def test_a_start_whose_call_the_controller_does_not_answer_is_held_where_its_rows_stand(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        controller_outage: ControllerOutage,
        engine_events: list[EngineEvent],
        answer: str,
        call: str,
        phases: list[dict[str, str]],
        created: bool,
        claim: str,
    ) -> None:
        def down() -> None:
            fake.outage(answer=answer)

        run = _start(starts, session, project)
        if call == "start":
            down()
        else:
            hooks = {
                "settle": "during_start",
                "create": "during_settle",
                "snapshot": "during_create",
                "send": "during_snapshot",
            }
            setattr(fake, hooks[call], down)

        _run(starts, run)

        run = _read(session, run.id)
        assert (run.state_code, run.error) == (SessionState.HELD, None)
        assert (run.controller_session is not None) is created
        (brief,) = _turns(session, run.id)
        assert (brief.ended_at, brief.error) == (None, None)
        assert [payload for _, payload in _server(session, run.id)] == phases
        row = _row(session)
        assert {
            "none": (None, None),
            "no-pod": (row.server_started_at, None),
            "pod": (row.server_started_at, fake.environment(ENV).pod_started_at),
        }[claim] == (row.server_started_at, row.started_pod_at)
        if claim != "none":
            assert row.server_started_at is not None
        assert controller_outage.holds
        assert _moves(engine_events)[-2:] == [
            WorkMoved(project.id, run.id),
            ProjectChanged(project.id),
        ]


class TestRelease:
    def test_once_the_gate_opens_every_held_start_goes_on(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        controller_outage: ControllerOutage,
    ) -> None:
        _run(starts, _start(starts, session, project))
        controller_outage.call_unanswered()
        held = [_held(starts, session, project) for _ in range(2)]
        _row(session).stop_due_at = datetime.now(UTC) + timedelta(minutes=5)
        session.flush()
        controller_outage.probe_answered()

        _release(starts)

        for run in held:
            run = _read(session, run.id)
            assert run.state_code == SessionState.STARTING
            assert _server(session, run.id) == [(None, STARTING_ENV)]
            assert run.current_line is not None
        assert _row(session).stop_due_at is None

    def test_nothing_goes_on_while_the_outage_holds(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        controller_outage: ControllerOutage,
    ) -> None:
        controller_outage.call_unanswered()
        run = _held(starts, session, project)

        _release(starts)

        assert _read(session, run.id).state_code == SessionState.HELD

    def test_a_paused_projects_start_stays_held_and_a_chats_goes_on(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        controller_outage: ControllerOutage,
    ) -> None:
        project.paused = True
        session.flush()
        controller_outage.call_unanswered()
        work = _held(starts, session, project)
        chat = _held(starts, session, project, kind_code="chat")
        controller_outage.probe_answered()

        _release(starts)

        assert _read(session, work.id).state_code == SessionState.HELD
        assert _read(session, chat.id).state_code == SessionState.STARTING

    @pytest.mark.parametrize("state", [SessionState.STARTING, SessionState.FAILED])
    def test_a_session_no_longer_held_is_left_alone(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        controller_outage: ControllerOutage,
        state: SessionState,
    ) -> None:
        controller_outage.call_unanswered()
        run = _held(starts, session, project)
        run.state_code = state
        session.flush()
        controller_outage.probe_answered()

        _release(starts)

        assert _read(session, run.id).state_code == state
        assert _server(session, run.id) == []

    def test_a_start_held_once_its_session_was_created_goes_on_to_its_brief_alone(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        controller_outage: ControllerOutage,
    ) -> None:
        fake.during_snapshot = fake.outage
        run = _start(starts, session, project)
        _run(starts, run)
        name = _read(session, run.id).controller_session
        assert name is not None
        fake.outage(on=False)
        controller_outage.probe_answered()

        _release(starts)
        _run(starts, run)

        run = _read(session, run.id)
        assert (run.state_code, run.controller_session) == (SessionState.RUNNING, name)
        assert _server(session, run.id) == [(None, STARTING_ENV), (None, CREATING)]
        assert fake.create_bodies == [{"cwd": CWD}]
        assert _sends(fake, name) == 1

    def test_a_start_held_before_its_session_was_created_starts_its_environment_again(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        controller_outage: ControllerOutage,
    ) -> None:
        # Its `202` recorded, and its settle cut (review O1).
        fake.during_start = fake.outage
        run = _start(starts, session, project)
        _run(starts, run)
        claimed = _row(session).server_started_at
        assert claimed is not None and _row(session).started_pod_at is None
        fake.outage(on=False)
        controller_outage.probe_answered()

        _release(starts)
        _run(starts, run)

        assert _read(session, run.id).state_code == SessionState.RUNNING
        assert _server(session, run.id) == [
            (None, STARTING_ENV),
            (None, STARTING_ENV),
            (None, CREATING),
        ]
        # The `200` keeps the claim, and takes the settled pod as its own.
        row = _row(session)
        assert row.server_started_at == claimed
        assert row.started_pod_at == fake.environment(ENV).pod_started_at


class TestProbe:
    def test_while_the_outage_does_not_hold_it_calls_nothing(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        controller_outage: ControllerOutage,
    ) -> None:
        # A call would go unanswered, and turn the outage on.
        fake.outage()

        starts.run_probe(session)

        assert not controller_outage.holds

    def test_the_controllers_answer_turns_the_outage_off(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        controller_outage: ControllerOutage,
    ) -> None:
        controller_outage.call_unanswered()

        starts.run_probe(session)

        assert not controller_outage.holds

    @pytest.mark.parametrize("answer", ["none", "ingress"])
    def test_a_controller_still_out_keeps_it_on(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        controller_outage: ControllerOutage,
        answer: str,
    ) -> None:
        controller_outage.call_unanswered()
        since = controller_outage.since
        fake.outage(answer=answer)

        starts.run_probe(session)

        assert controller_outage.since == since


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

    def test_a_work_items_start_runs_to_its_turns_end_and_its_done(
        self,
        committed_app: Flask,
        committed_fake: _Recording,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        starts, _, coordinator = _services(container, supervise)
        project_id = _committed_project(container)
        coordinator.fire_startup()

        with scoped_session(container) as db:
            work_id = starts.start_work(
                db, project_id, ENV, title="Renaming", brief=BRIEF, cwd=CWD
            ).id

        loop_log.wait_for(rf"Loop relay:{work_id} started")
        run = _committed(container, work_id)
        assert run.controller_session is not None
        committed_fake.play(ENV, run.controller_session, raw_turn("turn_text"))
        committed_fake.finish(ENV, run.controller_session, "success", "Done.")
        wait_until(
            lambda: _committed(container, work_id).state_code == SessionState.IDLE,
            "the brief's turn ended",
        )
        with scoped_session(container) as db:
            item = db.get_one(Item, work_id)
            (brief,) = _turns(db, work_id)
            assert (item.done_at, item.done_cause_code, item.done_by_user_id) == (
                brief.ended_at,
                "turn_ended",
                None,
            )

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


class TestHeldLoop:
    @pytest.fixture
    def loop_log(self) -> Iterator[LogWaiter]:
        with listening(SUPERVISOR_LOGGER, START_LOGGER) as waiter:
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

    def test_a_work_item_started_while_the_controller_is_unreachable_runs_once_it_answers(
        self,
        committed_app: Flask,
        committed_fake: _Recording,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        outage = container.controller_outage()
        starts, _, coordinator = _services(container, supervise)
        project_id = _committed_project(container)
        _add_environment(container)
        coordinator.fire_startup()
        committed_fake.outage(answer="ingress")
        outage.call_unanswered()

        with scoped_session(container) as db:
            work_id = starts.start_work(
                db, project_id, ENV, title="Renaming", brief=BRIEF, cwd=CWD
            ).id

        assert _committed(container, work_id).state_code == SessionState.HELD
        committed_fake.outage(on=False)
        loop_log.wait_for(rf"Session {work_id} goes on from held")
        loop_log.wait_for(rf"Loop relay:{work_id} started")
        assert _committed(container, work_id).state_code == SessionState.RUNNING
        assert not outage.holds

    def test_a_start_that_meets_the_outage_resumes_from_its_rows_once_the_controller_answers(
        self,
        committed_app: Flask,
        committed_fake: _Recording,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        starts, _, coordinator = _services(container, supervise)
        project_id = _committed_project(container)
        coordinator.fire_startup()
        committed_fake.during_start = committed_fake.outage

        with scoped_session(container) as db:
            run_id = starts.start_session(
                db, project_id, ENV, kind_code="work", cwd=CWD, brief=BRIEF
            ).id

        loop_log.wait_for(rf"Session {run_id} is held: .*")
        with scoped_session(container) as db:
            claimed = _row(db).server_started_at
        assert claimed is not None
        committed_fake.outage(on=False)
        loop_log.wait_for(rf"Loop relay:{run_id} started")
        run = _committed(container, run_id)
        assert run.state_code == SessionState.RUNNING
        assert run.controller_session is not None
        with scoped_session(container) as db:
            row = _row(db)
            assert row.server_started_at == claimed
            assert row.started_pod_at == committed_fake.environment(ENV).pod_started_at
        assert committed_fake.create_bodies == [{"cwd": CWD}]
        assert _sends(committed_fake, run.controller_session) == 1

    def test_held_starts_go_on_in_the_order_they_were_asked(
        self,
        committed_app: Flask,
        committed_fake: _Recording,
        supervise: Supervise,
    ) -> None:
        container = committed_app.container
        outage = container.controller_outage()
        # No loop of theirs runs: the supervisor never starts.
        starts, _, _ = _services(container, supervise)
        project_id = _committed_project(container)
        outage.call_unanswered()
        ids = []
        for _ in range(3):
            with scoped_session(container) as db:
                ids.append(
                    starts.start_session(
                        db, project_id, ENV, kind_code="work", cwd=CWD, brief=BRIEF
                    ).id
                )
        # Asked in an order neither their writes' nor their ids'.
        asked = [ids[1], ids[2], ids[0]]
        first = datetime.now(UTC)
        with scoped_session(container) as db:
            for offset, run_id in enumerate(asked):
                run = db.get_one(models.Session, run_id)
                run.created_at = first + timedelta(seconds=offset)
        outage.probe_answered()

        starts.release(LoopHandle("start:held"))

        with scoped_session(container) as db:
            begun = {run_id: _records(db, run_id)[0].record.at for run_id in ids}
            states = {_read(db, run_id).state_code for run_id in ids}
        assert states == {SessionState.STARTING}
        assert sorted(ids, key=begun.__getitem__) == asked

    def test_startup_resumes_the_held_starts(
        self,
        committed_app: Flask,
        committed_fake: _Recording,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        project_id = _committed_project(container)
        # A process that met the outage and was gone before it ended.
        cut_outage = ControllerOutage()
        cut_outage.call_unanswered()
        cut, _, _ = _services(container, supervise, outage=cut_outage)
        with scoped_session(container) as db:
            run_id = cut.start_session(
                db, project_id, ENV, kind_code="work", cwd=CWD, brief=BRIEF
            ).id
        assert _committed(container, run_id).state_code == SessionState.HELD
        # A fresh process starts with the outage off.
        _, _, coordinator = _services(container, supervise, outage=ControllerOutage())

        coordinator.fire_startup()

        loop_log.wait_for(rf"Session {run_id} goes on from held")
        loop_log.wait_for(rf"Loop relay:{run_id} started")
        assert _committed(container, run_id).state_code == SessionState.RUNNING

    def test_a_held_write_asks_the_gate_again_once_it_commits(
        self,
        committed_app: Flask,
        committed_fake: _Recording,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        starts, _, coordinator = _services(container, supervise)
        project_id = _committed_project(container)
        with scoped_session(container) as db:
            db.get_one(Project, project_id).paused = True
        coordinator.fire_startup()

        with scoped_session(container) as db:
            run_id = starts.start_session(
                db, project_id, ENV, kind_code="work", cwd=CWD, brief=BRIEF
            ).id
            # The pause lifted, committed before this write's commit: the
            # release it opened found nothing held.
            other: DbSession = container.session_maker()()
            try:
                other.get_one(Project, project_id).paused = False
                other.commit()
            finally:
                other.close()

        loop_log.wait_for(rf"Session {run_id} goes on from held")
        loop_log.wait_for(rf"Loop relay:{run_id} started")

    def test_a_resume_lets_the_projects_held_starts_go_on_once_it_commits(
        self,
        committed_app: Flask,
        committed_fake: _Recording,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        """The pause lifted from the project's icon (F141.2, F141.5)."""
        container = committed_app.container
        starts, _, coordinator = _services(container, supervise)
        project_id = _committed_project(container)
        with scoped_session(container) as db:
            project = db.get_one(Project, project_id)
            project.state_code = ProjectState.OPEN
            project.slug = "camp"
            project.paused = True
        coordinator.fire_startup()
        with scoped_session(container) as db:
            run_id = starts.start_session(
                db, project_id, ENV, kind_code="work", cwd=CWD, brief=BRIEF
            ).id
        assert _committed(container, run_id).state_code == SessionState.HELD
        ada = AuthContext(
            subject="subject-ada", email=None, name="Ada Example", roles={"editor"}
        )

        container.session_start_service.override(providers.Object(starts))
        try:
            with scoped_session(container):
                container.project_service().transition(
                    ada, project_id, TransitionKind.RESUMED
                )
        finally:
            container.session_start_service.reset_last_overriding()

        loop_log.wait_for(rf"Session {run_id} goes on from held")
        loop_log.wait_for(rf"Loop relay:{run_id} started")
        assert _committed(container, run_id).state_code == SessionState.RUNNING


def _add_environment(container: ServiceContainer) -> None:
    with scoped_session(container) as db:
        db.add(Environment(id=ENV, name="Env-A", exempt=False))
