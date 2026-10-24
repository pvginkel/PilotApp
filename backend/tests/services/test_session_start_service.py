"""The session start of a work item placed by repository, in an environment of
Pilot's own its start creates (design 2 §13.2, §13.5, §7.1; F88.1, F125,
F143.1; decision 38; V05, V15, V19), and the work item it is (DB Work,
decision 3); the gate every start passes, the held start and its release
(§13.4, §8.2; F141.5; DB 229, 230; V16, V24).

The start's write and its loop's run are on the test's session: the run is
called as its loop calls it. `TestStartLoop` and `TestHeldLoop` run the loops
from the write's commit on a database of their own, as the supervisor does."""

import json
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import requests
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
from app.services.controller_client import HeadlessCreateRequest
from app.services.controller_outage import ControllerOutage
from app.services.environment_service import EnvironmentService
from app.services.fake_controller import (
    CLIENT_NAME,
    FakeControllerProblem,
    FinishOutcome,
)
from app.services.relay_service import CONTINUE, SEND_FAILED, SESSION_GONE, RelayService
from app.services.session_record_service import StoredRecord, read_records
from app.services.session_start_service import (
    START_FAILED,
    STARTING,
    SessionStartService,
)
from app.services.supervisor import LoopHandle
from app.services.timeline_service import work_status
from app.utils import after_commit as after_commit_module
from app.utils.after_commit import clear_after_commit_callbacks
from app.utils.lifecycle_coordinator import LifecycleCoordinator
from tests.support.fake_controller import (
    FAKE_CONTROLLER_TOKEN,
    ServedFakeController,
    client_of,
    raw_turn,
)
from tests.support.supervisor import LogWaiter, Supervise, listening, wait_until

REPO = "example/Example"
SLUG = "camp"
CWD = "/work/Example"
BRIEF = "Rename the badge."
STOP_AFTER = timedelta(minutes=30)
PREPARING = {"type": STARTING, "text": "Preparing camp…"}
STARTING_ENV = {"type": STARTING, "text": "Starting camp…"}
CREATING = {"type": STARTING, "text": "Creating the session…"}
CREATE_ENVIRONMENT = "POST /environments"
SUPERVISOR_LOGGER = "app.services.supervisor"
START_LOGGER = "app.services.session_start_service"


class _Recording(ServedFakeController):
    """The fake, keeping each environment create's body and the env id it
    made, and each headless create's body, and refusing every send with `502
    worker-unreachable` while `refuse_sends` is set. `during_provision`,
    `during_start`, `during_settle`, `during_create` and `during_snapshot`,
    when set, run once, as an environment's create, its start, its `wait`, a
    headless create or a session's snapshot is answered: another process's
    action then, or the controller going down after that call."""

    def __init__(self, keepalive_seconds: float) -> None:
        super().__init__(keepalive_seconds)
        self.environment_bodies: list[dict[str, Any]] = []
        self.created: list[str] = []
        self.create_bodies: list[dict[str, Any]] = []
        self.refuse_sends = False
        self.during_provision: Callable[[], None] | None = None
        self.during_start: Callable[[], None] | None = None
        self.during_create: Callable[[], None] | None = None
        self.during_settle: Callable[[], None] | None = None
        self.during_snapshot: Callable[[], None] | None = None

    def _create_environment(self, request: Request) -> Response:
        self.environment_bodies.append(request.get_json(silent=True) or {})
        hook, self.during_provision = self.during_provision, None
        if hook is not None:
            hook()
        response = super()._create_environment(request)
        self.created.append(json.loads(response.get_data())["envId"])
        return response

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

    def managed(self) -> list[dict[str, Any]]:
        """The fleet's environments Pilot's client manages, as the list
        filtered by it answers."""
        response = requests.get(
            f"{self.url}/environments",
            params={"managedBy": CLIENT_NAME},
            headers={"Authorization": f"Bearer {FAKE_CONTROLLER_TOKEN}"},
            timeout=5,
        )
        response.raise_for_status()
        items: list[dict[str, Any]] = response.json()["items"]
        return items


@pytest.fixture(autouse=True)
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


@pytest.fixture
def project(session: DbSession, person: User) -> Project:
    """An open project, `camp`, created by ``person``: the environments its
    work creates are named after its slug."""
    opened = Project(
        created_by_user_id=person.id, state_code=ProjectState.OPEN, slug=SLUG
    )
    session.add(opened)
    session.flush()
    return opened


@pytest.fixture
def fake(container: ServiceContainer) -> Iterator[_Recording]:
    """The fake controller, `container`'s client on it, with no environment:
    each fresh start creates its own."""
    served = _Recording(keepalive_seconds=0.2)
    client_of(container, served)
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


def _start_work(
    starts: SessionStartService,
    db: DbSession,
    project: Project,
    plan_task_id: str | None = None,
    *,
    repo: str = REPO,
) -> Work:
    work = starts.start_work(
        db,
        project.id,
        repo,
        title="Renaming the badge",
        brief=BRIEF,
        cwd=CWD,
        plan_task_id=plan_task_id,
    )
    clear_after_commit_callbacks()
    return work


def _start(
    starts: SessionStartService, db: DbSession, project: Project
) -> models.Session:
    """A work item's start written, its Session as it stands."""
    return _read(db, _start_work(starts, db, project).id)


def _run(starts: SessionStartService, run: models.Session) -> None:
    """The start loop's run, as its loop calls it."""
    starts.run(run.id, LoopHandle(f"start:{run.id}"))


def _brought_up(
    starts: SessionStartService, db: DbSession, project: Project
) -> models.Session:
    """A work item whose start ran to its environment's bring-up, its loop
    told to stop there: in an environment of its own, with no controller
    session."""
    run = _start(starts, db, project)
    stopped = LoopHandle(f"start:{run.id}")
    stopped._request_stop()
    starts.run(run.id, stopped)
    run = _read(db, run.id)
    assert run.environment_id is not None and run.controller_session is None
    return run


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


def _env(db: DbSession, run_id: uuid.UUID) -> str:
    """The id of the Session's Environment, which its start provided."""
    env_id = _read(db, run_id).environment_id
    assert env_id is not None
    return env_id


def _row(db: DbSession, env_id: str) -> Environment:
    return db.get_one(Environment, env_id, populate_existing=True)


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


def _sends(fake: ServedFakeController, env_id: str, name: str) -> int:
    return fake.calls.count(
        f"POST /environments/{env_id}/sessions/headless/{name}/messages"
    )


def _chat(
    db: DbSession, project: Project, environment: Environment, state: SessionState
) -> models.Session:
    """A Chat's Session in the store's environment, its brief written: no
    work item's."""
    run = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code="chat",
        cwd=CWD,
        token_hash=uuid.uuid4().hex,
        state_code=state,
        turns=1,
        turn_started_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()
    db.add(Turn(session_id=run.id, seq=1, message=BRIEF, started_at=datetime.now(UTC)))
    db.flush()
    return run


class TestStartWork:
    def test_it_places_the_work_item_by_repository_and_writes_its_start_with_no_environment(
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
        assert (work.session_kind_code, work.repo, work.autopilot) == (
            "work",
            REPO,
            project.autopilot,
        )
        assert run.state_code == SessionState.STARTING
        assert (run.project_id, run.environment_id, run.kind_code, run.cwd) == (
            project.id,
            None,
            "work",
            CWD,
        )
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
        # Its phase is the create's, once the environment has a name.
        assert _server(session, run.id) == []
        assert run.current_line is None
        assert fake.calls == []

    def test_its_repository_and_working_directory_are_taken_as_placed(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        # The brain's placement (F61.1): a sibling the repository's manifest
        # checks out.
        work = starts.start_work(
            session,
            project.id,
            "example/Ansible",
            title="Renaming the badge",
            brief=BRIEF,
            cwd="/work/DockerImages",
        )
        clear_after_commit_callbacks()

        assert work.repo == "example/Ansible"
        assert _read(session, work.id).cwd == "/work/DockerImages"

    def test_each_session_gets_a_token_of_its_own(
        self, starts: SessionStartService, session: DbSession, project: Project
    ) -> None:
        first = _start(starts, session, project)
        second = _start(starts, session, project)

        assert first.token_hash != second.token_hash

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
                session, uuid.uuid4(), REPO, title="Renaming", brief=BRIEF, cwd=CWD
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
        fake.capped()
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
        # "Preparing camp…", "Creating the session…", the session's start,
        # then the brief's send, which makes it `running`.
        assert _read(session, work.id).state_code == SessionState.RUNNING
        assert _moves(engine_events) == [
            moved,
            moved,
            moved,
            moved,
            ProjectChanged(project.id),
        ]


class TestRun:
    def test_it_creates_an_environment_of_pilots_own_creates_the_session_and_sends_the_brief(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        run = _start(starts, session, project)
        written = _turns(session, run.id)[0].started_at

        _run(starts, run)

        (env_id,) = fake.created
        assert _env(session, run.id) == env_id
        assert fake.environment_bodies == [
            {"repo": REPO, "managed": True, "name": SLUG}
        ]
        created = fake.environment(env_id)
        assert (created.status, created.name, created.repo, created.managed_by) == (
            "running",
            SLUG,
            REPO,
            CLIENT_NAME,
        )
        assert [each["envId"] for each in fake.managed()] == [env_id]
        row = _row(session, env_id)
        assert (row.name, row.repo, row.exempt) == (SLUG, REPO, False)
        assert row.server_created_at is not None
        # The create's `202` took the claim, and the settled pod is its own.
        assert row.server_started_at == row.server_created_at
        assert row.started_pod_at == created.pod_started_at is not None
        assert row.stop_due_at is None
        # A create ends in a running pod: no start follows it.
        assert f"POST /environments/{env_id}/start" not in fake.calls
        (headless,) = fake.sessions(env_id)
        assert headless.status == "busy"
        run = _read(session, run.id)
        assert run.state_code == SessionState.RUNNING
        assert run.controller_session == headless.name
        assert run.started_at is not None
        assert _server(session, run.id) == [(None, PREPARING), (None, CREATING)]
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
        assert _sends(fake, env_id, headless.name) == 1

    def test_the_line_says_preparing_the_environment_while_it_comes_up(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        run = _brought_up(starts, session, project)

        preparing = _records(session, run.id)[-1].record
        assert preparing.payload == PREPARING
        assert run.current_line == {
            "state": "starting",
            "since": preparing.at.isoformat(),
            "text": "Preparing camp…",
        }
        status = work_status(session, [run.id], unreachable=False)[run.id]
        assert status.environment is not None
        assert (status.environment.id, status.environment.name) == (
            run.environment_id,
            SLUG,
        )

    def test_a_name_the_fleet_holds_is_suffixed(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        # An operator's environment named after the slug, and another
        # project environment's `-2` (casefold, as KubeCoder compares).
        fake.add_environment("operators-env", name="Camp")
        fake.add_environment("second-env", name="camp-2")
        run = _start(starts, session, project)

        _run(starts, run)

        assert [body.get("name") for body in fake.environment_bodies] == [
            "camp",
            "camp-2",
            "camp-3",
        ]
        env_id = _env(session, run.id)
        assert _row(session, env_id).name == "camp-3"
        assert _server(session, run.id)[0] == (
            None,
            {"type": STARTING, "text": "Preparing camp-3…"},
        )
        # The environments it did not create are left as they are (F143.1).
        assert fake.environment("operators-env").name == "Camp"
        assert not [call for call in fake.calls if "operators-env" in call]

    def test_a_draft_projects_environment_is_unnamed(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        person: User,
    ) -> None:
        draft = Project(created_by_user_id=person.id)
        session.add(draft)
        session.flush()
        run = _start(starts, session, draft)

        _run(starts, run)

        assert fake.environment_bodies == [{"repo": REPO, "managed": True}]
        env_id = _env(session, run.id)
        # An unset name reads as the env id, as the fleet consumer stores it.
        assert _row(session, env_id).name == env_id
        assert _server(session, run.id)[0] == (
            None,
            {"type": STARTING, "text": f"Preparing {env_id}…"},
        )

    def test_the_create_carries_the_sessions_options(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        run = _start(starts, session, project)
        run.agent, run.model, run.reasoning_effort = "worker", "opus", "high"
        run.conversation_id = "conv-1"
        session.flush()

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
        run = _brought_up(starts, session, project)
        env_id = _env(session, run.id)
        name = (
            container.controller_client()
            .create_headless_session(env_id, HeadlessCreateRequest())
            .name
        )
        run.controller_session = name
        session.flush()
        before = len(fake.calls)

        _run(starts, run)

        assert fake.calls[before:] == [
            f"GET /environments/{env_id}/sessions/{name}",
            f"POST /environments/{env_id}/sessions/headless/{name}/messages",
        ]
        assert _read(session, run.id).state_code == SessionState.RUNNING
        assert _server(session, run.id) == [(None, PREPARING)]

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

        _run(starts, run)

        assert fake.calls == []
        assert _read(session, run.id).state_code == state

    def test_a_stop_between_the_phases_leaves_the_start_where_it_was(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        run = _brought_up(starts, session, project)

        env_id = _env(session, run.id)
        assert fake.environment(env_id).status == "running"
        assert fake.sessions(env_id) == []
        assert run.state_code == SessionState.STARTING
        assert _server(session, run.id) == [(None, PREPARING)]

        _run(starts, run)

        # It goes on in its environment: no second create.
        assert fake.calls.count(CREATE_ENVIRONMENT) == 1
        assert _read(session, run.id).state_code == SessionState.RUNNING
        assert _server(session, run.id) == [(None, PREPARING), (None, CREATING)]

    def test_a_start_whose_environments_bring_up_is_still_to_settle_awaits_it(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        # A start cut after its create's row committed, before its settle was
        # read: the claim's pod is unknown.
        run = _brought_up(starts, session, project)
        env_id = _env(session, run.id)
        row = _row(session, env_id)
        claimed = row.server_started_at
        row.started_pod_at = None
        session.flush()
        before = len(fake.calls)

        _run(starts, run)

        # Its settle awaited, never a second bring-up scheduled.
        assert fake.calls[before].startswith(f"GET /environments/{env_id}?wait=settled")
        assert f"POST /environments/{env_id}/start" not in fake.calls
        assert fake.calls.count(CREATE_ENVIRONMENT) == 1
        row = _row(session, env_id)
        assert row.server_started_at == claimed
        assert row.started_pod_at == fake.environment(env_id).pod_started_at
        assert _read(session, run.id).state_code == SessionState.RUNNING

    def test_a_stop_while_its_environment_is_created_leaves_that_one_stopped_and_free(
        self,
        container: ServiceContainer,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        person: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        work = _start_work(starts, session, project)
        client = container.controller_client()
        create = client.create_environment

        def stopped_meanwhile(*args: Any) -> Any:
            created = create(*args)
            starts.stop(session, work.id, person)
            session.flush()
            return created

        monkeypatch.setattr(client, "create_environment", stopped_meanwhile)

        _run(starts, _read(session, work.id))
        clear_after_commit_callbacks()

        run = _read(session, work.id)
        assert (run.state_code, run.environment_id) == (SessionState.STOPPED, None)
        (env_id,) = fake.created
        # Pilot's own, free, and holding no node slot.
        assert fake.environment(env_id).status == "stopped"
        row = _row(session, env_id)
        assert (row.repo, row.server_created_at is not None) == (REPO, True)
        assert (row.server_started_at, row.started_pod_at, row.stop_due_at) == (
            None,
            None,
            None,
        )
        assert fake.sessions(env_id) == []
        assert _server(session, run.id) == []


class TestRunFails:
    @pytest.mark.parametrize(
        ("refusal", "repo", "problem"),
        [
            ("capped", REPO, "409 admission-blocked"),
            ("not-whitelisted", REPO, "403 namespace-not-whitelisted"),
            ("invalid", "not-a-repository", "422 validation-error"),
        ],
    )
    def test_a_create_the_controller_refuses_fails_the_session_unretried(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        controller_outage: ControllerOutage,
        refusal: str,
        repo: str,
        problem: str,
    ) -> None:
        if refusal == "capped":
            fake.capped()
        elif refusal == "not-whitelisted":
            fake.not_whitelisted("example")
        run = _read(session, _start_work(starts, session, project, repo=repo).id)

        _run(starts, run)

        run = _assert_failed(session, run.id)
        assert run.error is not None and problem in run.error
        assert run.environment_id is None
        assert _server(session, run.id) == [
            (None, {"type": START_FAILED, "reason": run.error}),
        ]
        assert fake.calls.count(CREATE_ENVIRONMENT) == 1
        assert session.scalars(select(Environment)).all() == []
        assert not controller_outage.holds

    @pytest.mark.parametrize("status", ["error", "stopped"])
    def test_an_environment_that_settles_other_than_running_fails_the_session(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        status: str,
    ) -> None:
        fake.settle_creates(status)
        run = _start(starts, session, project)

        _run(starts, run)

        run = _assert_failed(session, run.id)
        assert run.error is not None and f"it settled {status}" in run.error
        assert _server(session, run.id) == [
            (None, PREPARING),
            (None, {"type": START_FAILED, "reason": run.error}),
        ]
        assert fake.create_bodies == []
        # Bound to its item, which shows Resume (D1).
        assert run.environment_id == fake.created[0]

    def test_a_session_create_the_controller_refuses_fails_the_session(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        controller_outage: ControllerOutage,
    ) -> None:
        fake.during_settle = lambda: fake.unreachable(fake.created[0])
        run = _start(starts, session, project)

        _run(starts, run)

        run = _assert_failed(session, run.id)
        assert run.error is not None and "worker-unreachable" in run.error
        assert run.controller_session is None
        # The controller answered, about one environment (review O2).
        assert not controller_outage.holds
        assert _server(session, run.id) == [
            (None, PREPARING),
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
            (None, PREPARING),
            (None, CREATING),
            (1, {"type": SEND_FAILED, "reason": brief.error}),
        ]

    @pytest.mark.parametrize("failure", ["create", "send"])
    def test_a_failed_start_has_the_environment_pilot_created_stopped(
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
            fake.during_settle = lambda: fake.unreachable(fake.created[0])
        else:
            fake.refuse_sends = True
        run = _start(starts, session, project)

        _run(starts, run)

        _assert_failed(session, run.id)
        env_id = _env(session, run.id)
        assert _row(session, env_id).stop_due_at is not None
        environments.run_shutdown_timer(session)
        assert fake.environment(env_id).status == "stopped"
        row = _row(session, env_id)
        assert (row.stop_due_at, row.server_started_at) == (None, None)

    def test_a_failed_start_leaves_the_timer_unarmed_while_another_session_runs_there(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        run = _brought_up(starts, session, project)
        env_id = _env(session, run.id)
        session.add(
            models.Session(
                project_id=project.id,
                environment_id=env_id,
                kind_code="work",
                cwd=CWD,
                token_hash=uuid.uuid4().hex,
                state_code=SessionState.RUNNING,
            )
        )
        session.flush()
        fake.refuse_sends = True

        _run(starts, run)

        _assert_failed(session, run.id)
        row = _row(session, env_id)
        assert row.server_started_at is not None and row.stop_due_at is None

    def test_a_failed_create_arms_no_timer(
        self,
        container: ServiceContainer,
        fake: _Recording,
        supervise: Supervise,
        session: DbSession,
        project: Project,
    ) -> None:
        starts, environments, _ = _services(
            container, supervise, stop_after=timedelta(0)
        )
        fake.capped()
        run = _start(starts, session, project)

        _run(starts, run)
        environments.run_shutdown_timer(session)

        _assert_failed(session, run.id)
        assert session.scalars(select(Environment)).all() == []
        assert [call for call in fake.calls if call.endswith("/stop")] == []


def _held(starts: SessionStartService, db: DbSession, project: Project) -> Work:
    """A work item whose start the gate held, written as `_start_work` writes
    one."""
    work = _start_work(starts, db, project)
    assert _read(db, work.id).state_code == SessionState.HELD
    return work


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
        controller_outage.call_unanswered()

        run = _start(starts, session, project)
        _run(starts, run)

        run = _read(session, run.id)
        assert run.state_code == SessionState.HELD
        assert (
            run.current_line,
            run.error,
            run.controller_session,
            run.environment_id,
        ) == (None, None, None, None)
        (brief,) = _turns(session, run.id)
        assert (brief.message, brief.ended_at, brief.error) == (BRIEF, None, None)
        assert _server(session, run.id) == []
        assert fake.calls == []

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

        assert run.state_code == SessionState.HELD
        assert _server(session, run.id) == []

    @pytest.mark.parametrize(
        ("paused", "reason"),
        [(True, HeldReason.PAUSED), (False, HeldReason.CONTROLLER_UNREACHABLE)],
    )
    def test_a_held_work_item_is_placed_its_line_saying_why_with_no_environment(
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
        # Held before its start provides one, it has none (DB 107).
        assert status.environment is None


class TestRunHeld:
    @pytest.mark.parametrize("answer", ["none", "ingress"])
    @pytest.mark.parametrize(
        ("call", "phases", "created", "claim"),
        [
            ("create", [], False, "no-environment"),
            ("settle", [PREPARING], False, "no-pod"),
            ("session", [PREPARING, CREATING], False, "pod"),
            ("snapshot", [PREPARING, CREATING], True, "pod"),
            ("send", [PREPARING, CREATING], True, "pod"),
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
        if call == "create":
            down()
        else:
            hooks = {
                "settle": "during_provision",
                "session": "during_settle",
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
        if claim == "no-environment":
            assert run.environment_id is None
        else:
            row = _row(session, _env(session, run.id))
            assert row.server_started_at is not None
            assert row.started_pod_at == (
                None if claim == "no-pod" else fake.environment(row.id).pod_started_at
            )
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
        controller_outage.call_unanswered()
        held = [_held(starts, session, project) for _ in range(2)]
        controller_outage.probe_answered()

        _release(starts)

        for work in held:
            run = _read(session, work.id)
            assert run.state_code == SessionState.STARTING
            # Its phase is the create's, which its loop makes.
            assert _server(session, run.id) == []
        assert fake.calls == []

    def test_a_held_resume_going_on_clears_its_environments_shutdown_timer(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        person: User,
        controller_outage: ControllerOutage,
    ) -> None:
        stopped = _stopped_item(starts, fake, session, project, person)
        env_id = _env(session, stopped.id)
        assert _row(session, env_id).stop_due_at is not None
        controller_outage.call_unanswered()
        starts.resume(session, stopped.id)
        clear_after_commit_callbacks()
        controller_outage.probe_answered()

        _release(starts)

        assert _read(session, stopped.id).state_code == SessionState.STARTING
        assert _row(session, env_id).stop_due_at is None

    def test_nothing_goes_on_while_the_outage_holds(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        controller_outage: ControllerOutage,
    ) -> None:
        controller_outage.call_unanswered()
        work = _held(starts, session, project)

        _release(starts)

        assert _read(session, work.id).state_code == SessionState.HELD

    def test_a_paused_projects_start_stays_held_and_a_chats_goes_on(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        environment: Environment,
        controller_outage: ControllerOutage,
    ) -> None:
        project.paused = True
        session.flush()
        controller_outage.call_unanswered()
        work = _held(starts, session, project)
        chat = _chat(session, project, environment, SessionState.HELD)
        controller_outage.probe_answered()

        _release(starts)

        assert _read(session, work.id).state_code == SessionState.HELD
        assert _read(session, chat.id).state_code == SessionState.STARTING
        # The store is not Pilot's own: its start is no create's.
        assert _server(session, chat.id) == [
            (None, {"type": STARTING, "text": "Starting Example-1…"})
        ]

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
        run = _read(session, _held(starts, session, project).id)
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
        assert _server(session, run.id) == [(None, PREPARING), (None, CREATING)]
        assert fake.calls.count(CREATE_ENVIRONMENT) == 1
        assert fake.create_bodies == [{"cwd": CWD}]
        assert _sends(fake, _env(session, run.id), name) == 1

    def test_a_start_held_while_its_environment_came_up_awaits_that_bring_up(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        controller_outage: ControllerOutage,
    ) -> None:
        # Its create's row committed, and its settle cut (review B3).
        fake.during_provision = fake.outage
        run = _start(starts, session, project)
        _run(starts, run)
        env_id = _env(session, run.id)
        claimed = _row(session, env_id).server_started_at
        assert claimed is not None and _row(session, env_id).started_pod_at is None
        fake.outage(on=False)
        controller_outage.probe_answered()

        _release(starts)
        _run(starts, run)

        assert _read(session, run.id).state_code == SessionState.RUNNING
        assert _server(session, run.id) == [
            (None, PREPARING),
            (None, PREPARING),
            (None, CREATING),
        ]
        # No second environment, and no start of this one.
        assert fake.calls.count(CREATE_ENVIRONMENT) == 1
        assert f"POST /environments/{env_id}/start" not in fake.calls
        row = _row(session, env_id)
        assert row.server_started_at == claimed
        assert row.started_pod_at == fake.environment(env_id).pod_started_at


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
        project = Project(
            created_by_user_id=person.id, state_code=ProjectState.OPEN, slug=SLUG
        )
        db.add(project)
        db.flush()
        return project.id


def _committed(container: ServiceContainer, run_id: uuid.UUID) -> models.Session:
    with scoped_session(container) as db:
        run = db.get_one(models.Session, run_id)
        db.expunge(run)
        return run


def _committed_env(container: ServiceContainer, run_id: uuid.UUID) -> str:
    env_id = _committed(container, run_id).environment_id
    assert env_id is not None
    return env_id


def _committed_work(
    starts: SessionStartService, container: ServiceContainer, project_id: uuid.UUID
) -> uuid.UUID:
    """A work item's start written and committed: its loop runs once it
    commits, where a supervisor runs."""
    with scoped_session(container) as db:
        return starts.start_work(
            db, project_id, REPO, title="Renaming", brief=BRIEF, cwd=CWD
        ).id


def _created_elsewhere(
    container: ServiceContainer, environments: EnvironmentService, run_id: uuid.UUID
) -> str:
    """The environment a process now gone created for the Session's start,
    its row and the Session's Environment committed, its bring-up's settle
    never read."""
    created = container.controller_client().create_environment(REPO, SLUG)
    with scoped_session(container) as db:
        environments.record_created(db, created, REPO)
        db.get_one(models.Session, run_id).environment_id = created.env_id
    return created.env_id


@pytest.fixture
def committed_fake(committed_app: Flask) -> Iterator[_Recording]:
    served = _Recording(keepalive_seconds=0.2)
    client_of(committed_app.container, served)
    try:
        yield served
    finally:
        served.close()


class TestStartLoop:
    @pytest.fixture
    def loop_log(self) -> Iterator[LogWaiter]:
        with listening(SUPERVISOR_LOGGER) as waiter:
            yield waiter

    def test_a_work_items_start_runs_from_its_commit_to_its_done_and_the_timers_stop(
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

        work_id = _committed_work(starts, container, project_id)

        loop_log.wait_for(rf"Loop start:{work_id} started")
        loop_log.wait_for(rf"Loop start:{work_id} ended")
        loop_log.wait_for(rf"Loop relay:{work_id} started")
        run = _committed(container, work_id)
        env_id = _committed_env(container, work_id)
        assert run.state_code == SessionState.RUNNING
        assert run.controller_session is not None
        committed_fake.play(env_id, run.controller_session, raw_turn("turn_text"))
        committed_fake.finish(env_id, run.controller_session, "success", "Done.")
        wait_until(
            lambda: _committed(container, work_id).state_code == SessionState.IDLE,
            "the brief's turn ended",
        )
        wait_until(
            lambda: committed_fake.environment(env_id).status == "stopped",
            "the shutdown timer stopped the environment",
        )
        with scoped_session(container) as db:
            kinds = [stored.record.kind_code for stored in _records(db, work_id)]
            item = db.get_one(Item, work_id)
            (brief,) = _turns(db, work_id)
            assert (item.done_at, item.done_cause_code, item.done_by_user_id) == (
                brief.ended_at,
                "turn_ended",
                None,
            )
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
        run_id = _committed_work(cut, container, project_id)
        _, _, coordinator = _services(container, supervise)

        with listening(START_LOGGER) as log:
            coordinator.fire_startup()
            log.wait_for(rf"Resuming the start of session {run_id}")

        loop_log.wait_for(rf"Loop relay:{run_id} started")
        run = _committed(container, run_id)
        assert run.state_code == SessionState.RUNNING
        assert run.controller_session is not None
        assert committed_fake.calls.count(CREATE_ENVIRONMENT) == 1
        assert committed_fake.create_bodies == [{"cwd": CWD}]
        assert (
            _sends(committed_fake, run.environment_id or "", run.controller_session)
            == 1
        )

    def test_startup_resumes_a_start_cut_after_its_create_and_creates_no_second_environment(
        self,
        committed_app: Flask,
        committed_fake: _Recording,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        project_id = _committed_project(container)
        cut, environments, _ = _services(container, supervise)
        run_id = _committed_work(cut, container, project_id)
        env_id = _created_elsewhere(container, environments, run_id)
        _, _, coordinator = _services(container, supervise)

        coordinator.fire_startup()

        loop_log.wait_for(rf"Loop relay:{run_id} started")
        assert _committed(container, run_id).state_code == SessionState.RUNNING
        assert committed_fake.calls.count(CREATE_ENVIRONMENT) == 1
        assert f"POST /environments/{env_id}/start" not in committed_fake.calls
        assert [each["envId"] for each in committed_fake.managed()] == [env_id]
        with scoped_session(container) as db:
            assert _row(db, env_id).started_pod_at == (
                committed_fake.environment(env_id).pod_started_at
            )

    def test_a_brief_the_controller_got_before_a_cut_is_not_sent_again(
        self,
        committed_app: Flask,
        committed_fake: _Recording,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        project_id = _committed_project(container)
        cut, environments, _ = _services(container, supervise)
        run_id = _committed_work(cut, container, project_id)
        # The cut process created the environment and the session and sent
        # the brief; the send's commit was lost.
        env_id = _created_elsewhere(container, environments, run_id)
        client = container.controller_client()
        name = client.create_headless_session(env_id, HeadlessCreateRequest()).name
        with scoped_session(container) as db:
            db.get_one(models.Session, run_id).controller_session = name
        client.send_message(env_id, name, BRIEF)
        _, _, coordinator = _services(container, supervise)

        coordinator.fire_startup()

        loop_log.wait_for(rf"Loop relay:{run_id} started")
        assert _committed(container, run_id).state_code == SessionState.RUNNING
        assert _sends(committed_fake, env_id, name) == 1
        committed_fake.play(env_id, name, raw_turn("turn_text"))
        committed_fake.finish(env_id, name, "success", "Done.")
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
        run_id = _committed_work(starts, container, project_id)
        client = container.controller_client()
        other: list[str] = []

        def another_process_creates() -> None:
            # Its create answered, and its commit, before this run's.
            env_id = _committed_env(container, run_id)
            other.append(
                client.create_headless_session(env_id, HeadlessCreateRequest()).name
            )
            with scoped_session(container) as db:
                db.get_one(models.Session, run_id).controller_session = other[0]

        committed_fake.during_create = another_process_creates

        starts.run(run_id, LoopHandle(f"start:{run_id}"))

        env_id = _committed_env(container, run_id)
        run = _committed(container, run_id)
        assert run.controller_session == other[0]
        assert run.started_at is None
        assert run.state_code == SessionState.RUNNING
        assert committed_fake.session(env_id, other[0]).status == "busy"
        orphan = [s.name for s in committed_fake.sessions(env_id) if s.name != other[0]]
        assert [committed_fake.session(env_id, n).status for n in orphan] == ["idle"]

    def test_a_failure_after_another_process_ran_the_session_changes_nothing(
        self,
        committed_app: Flask,
        committed_fake: _Recording,
        supervise: Supervise,
    ) -> None:
        container = committed_app.container
        starts, _, _ = _services(container, supervise)
        project_id = _committed_project(container)
        run_id = _committed_work(starts, container, project_id)

        def another_process_runs_it() -> None:
            with scoped_session(container) as db:
                run = db.get_one(models.Session, run_id)
                run.state_code = SessionState.RUNNING
                env_id = run.environment_id
            assert env_id is not None
            committed_fake.unreachable(env_id)

        committed_fake.during_create = another_process_runs_it

        starts.run(run_id, LoopHandle(f"start:{run_id}"))

        run = _committed(container, run_id)
        assert (run.state_code, run.error) == (SessionState.RUNNING, None)
        with scoped_session(container) as db:
            assert [payload for _, payload in _server(db, run_id)] == [
                PREPARING,
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
        run_id = _committed_work(starts, container, project_id)
        client = container.controller_client()
        other: list[str] = []
        lines: list[dict[str, Any] | None] = []

        def another_process_runs_it() -> None:
            # Its create and its brief's send committed, and at `idle` the
            # brief's turn ended, before this run's environment settles.
            env_id = _committed_env(container, run_id)
            name = client.create_headless_session(env_id, HeadlessCreateRequest()).name
            client.send_message(env_id, name, BRIEF)
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
                committed_fake.finish(env_id, name, "success", "Done.")

        committed_fake.during_settle = another_process_runs_it

        starts.run(run_id, LoopHandle(f"start:{run_id}"))

        env_id = _committed_env(container, run_id)
        run = _committed(container, run_id)
        assert (run.state_code, run.controller_session) == (state, other[0])
        assert run.current_line == lines[0]
        with scoped_session(container) as db:
            assert [payload for _, payload in _server(db, run_id)] == [PREPARING]
        assert [s.name for s in committed_fake.sessions(env_id)] == other
        assert _sends(committed_fake, env_id, other[0]) == 1

    def test_a_controller_session_another_process_recorded_while_its_environment_came_up_gets_the_brief(
        self,
        committed_app: Flask,
        committed_fake: _Recording,
        supervise: Supervise,
    ) -> None:
        container = committed_app.container
        starts, _, _ = _services(container, supervise)
        project_id = _committed_project(container)
        run_id = _committed_work(starts, container, project_id)
        client = container.controller_client()
        other: list[str] = []

        def another_process_creates_and_stops() -> None:
            # Its create committed, and its loop told to stop before the send.
            env_id = _committed_env(container, run_id)
            other.append(
                client.create_headless_session(env_id, HeadlessCreateRequest()).name
            )
            with scoped_session(container) as db:
                db.get_one(models.Session, run_id).controller_session = other[0]

        committed_fake.during_settle = another_process_creates_and_stops

        starts.run(run_id, LoopHandle(f"start:{run_id}"))

        env_id = _committed_env(container, run_id)
        run = _committed(container, run_id)
        assert (run.state_code, run.controller_session) == (
            SessionState.RUNNING,
            other[0],
        )
        with scoped_session(container) as db:
            assert [payload for _, payload in _server(db, run_id)] == [PREPARING]
        assert [s.name for s in committed_fake.sessions(env_id)] == other
        assert _sends(committed_fake, env_id, other[0]) == 1

    def test_an_environment_another_process_gave_the_session_first_stands_and_this_runs_is_stopped(
        self,
        committed_app: Flask,
        committed_fake: _Recording,
        supervise: Supervise,
    ) -> None:
        container = committed_app.container
        starts, environments, _ = _services(container, supervise)
        project_id = _committed_project(container)
        run_id = _committed_work(starts, container, project_id)
        other: list[str] = []

        def another_process_creates_first() -> None:
            # A roll's overlap (§8.1): its create and its row committed
            # before this run's create is answered.
            other.append(_created_elsewhere(container, environments, run_id))

        committed_fake.during_provision = another_process_creates_first

        starts.run(run_id, LoopHandle(f"start:{run_id}"))

        assert _committed_env(container, run_id) == other[0]
        (mine,) = [env_id for env_id in committed_fake.created if env_id != other[0]]
        assert committed_fake.environment(mine).status == "stopped"
        assert committed_fake.environment(mine).name == "camp-2"
        assert committed_fake.sessions(mine) == []
        with scoped_session(container) as db:
            row = _row(db, mine)
            assert (row.repo, row.server_started_at, row.stop_due_at) == (
                REPO,
                None,
                None,
            )
            assert [payload for _, payload in _server(db, run_id)] == []


class TestHeldLoop:
    @pytest.fixture
    def loop_log(self) -> Iterator[LogWaiter]:
        with listening(SUPERVISOR_LOGGER, START_LOGGER) as waiter:
            yield waiter

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
        coordinator.fire_startup()
        committed_fake.outage(answer="ingress")
        outage.call_unanswered()

        work_id = _committed_work(starts, container, project_id)

        assert _committed(container, work_id).state_code == SessionState.HELD
        committed_fake.outage(on=False)
        loop_log.wait_for(rf"Session {work_id} goes on from held")
        loop_log.wait_for(rf"Loop relay:{work_id} started")
        assert _committed(container, work_id).state_code == SessionState.RUNNING
        assert not outage.holds

    def test_a_start_that_meets_the_outage_after_its_create_resumes_from_its_rows_once_the_controller_answers(
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
        committed_fake.during_provision = committed_fake.outage

        run_id = _committed_work(starts, container, project_id)

        loop_log.wait_for(rf"Session {run_id} is held: .*")
        env_id = _committed_env(container, run_id)
        with scoped_session(container) as db:
            claimed = _row(db, env_id).server_started_at
        assert claimed is not None
        committed_fake.outage(on=False)
        loop_log.wait_for(rf"Loop relay:{run_id} started")
        run = _committed(container, run_id)
        assert run.state_code == SessionState.RUNNING
        assert run.controller_session is not None
        assert committed_fake.calls.count(CREATE_ENVIRONMENT) == 1
        with scoped_session(container) as db:
            row = _row(db, env_id)
            assert row.server_started_at == claimed
            assert (
                row.started_pod_at == committed_fake.environment(env_id).pod_started_at
            )
        assert committed_fake.create_bodies == [{"cwd": CWD}]
        assert _sends(committed_fake, env_id, run.controller_session) == 1

    def test_held_starts_go_on_in_the_order_they_were_asked(
        self,
        committed_app: Flask,
        committed_fake: _Recording,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        outage = container.controller_outage()
        # No loop of theirs runs: the supervisor never starts.
        starts, _, _ = _services(container, supervise)
        project_id = _committed_project(container)
        outage.call_unanswered()
        ids = [_committed_work(starts, container, project_id) for _ in range(3)]
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
            states = {_read(db, run_id).state_code for run_id in ids}
        assert states == {SessionState.STARTING}
        assert loop_log.matching(r"Session .* goes on from held") == [
            f"Session {run_id} goes on from held" for run_id in asked
        ]

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
        run_id = _committed_work(cut, container, project_id)
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
        outage = container.controller_outage()
        starts, _, coordinator = _services(container, supervise)
        project_id = _committed_project(container)
        coordinator.fire_startup()
        # The probe's tick finds the controller still out until the write is in.
        committed_fake.outage(answer="ingress")
        outage.call_unanswered()

        with scoped_session(container) as db:
            run_id = starts.start_work(
                db, project_id, REPO, title="Renaming", brief=BRIEF, cwd=CWD
            ).id
            # The controller answering again before this write's commit: the
            # release its off opened found nothing held. The pause cannot
            # lift so, as the write holds the project's row under a share lock.
            committed_fake.outage(on=False)
            outage.probe_answered()

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
            db.get_one(Project, project_id).paused = True
        coordinator.fire_startup()
        run_id = _committed_work(starts, container, project_id)
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


def _running(
    starts: SessionStartService, db: DbSession, project: Project
) -> models.Session:
    """A work item whose start ran to its brief's send: `running`."""
    run = _start(starts, db, project)
    _run(starts, run)
    clear_after_commit_callbacks()
    run = _read(db, run.id)
    assert run.state_code == SessionState.RUNNING
    return run


def _callbacks() -> set[str]:
    """The kinds of the callbacks waiting on the transaction's commit."""
    return {
        type(callback).__name__ for callback in after_commit_module._callbacks.get()
    }


def _turn_ends(
    starts: SessionStartService,
    fake: _Recording,
    run: models.Session,
    outcome: FinishOutcome,
) -> None:
    """The controller's turn ends as `outcome` says, and the relay records it
    to its `result`, as its loop does."""
    assert run.environment_id is not None and run.controller_session is not None
    fake.finish(
        run.environment_id, run.controller_session, outcome, "The tests failed."
    )
    starts._relays.relay(run.id, LoopHandle(f"relay:{run.id}"))


class TestStop:
    """A work item's Stop (F67.1; review A1; V04)."""

    def test_a_running_work_item_is_stopped_its_turn_left_to_its_relay(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        person: User,
        engine_events: list[EngineEvent],
    ) -> None:
        run = _running(starts, session, project)
        env_id = _env(session, run.id)
        engine_events.clear()
        before = datetime.now(UTC)

        stopped = starts.stop(session, run.id, person)

        assert stopped.state_code == SessionState.STOPPED
        assert stopped.stopped_by_user_id == person.id
        assert stopped.stopped_at is not None and stopped.stopped_at >= before
        assert stopped.current_line is None
        (brief,) = _turns(session, run.id)
        assert brief.ended_at is None and stopped.turn_ended_at is None
        # The interrupt runs once the stop commits.
        assert "_InterruptStart" in _callbacks()
        name = stopped.controller_session
        assert name is not None and fake.session(env_id, name).status == "busy"
        # Nothing else runs there: Pilot's environment's timer is armed.
        assert _row(session, env_id).stop_due_at is not None
        clear_after_commit_callbacks()

    def test_it_moves_the_item_and_its_state(
        self,
        container: ServiceContainer,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        person: User,
        engine_events: list[EngineEvent],
    ) -> None:
        run = _running(starts, session, project)
        engine_events.clear()

        with scoped_session(container) as db:
            starts.stop(db, run.id, person)

        assert _moves(engine_events) == [
            WorkMoved(project.id, run.id),
            ProjectChanged(project.id),
        ]

    def test_a_starting_work_item_is_stopped_and_its_loop_sends_nothing(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        person: User,
    ) -> None:
        work = _start_work(starts, session, project)

        starts.stop(session, work.id, person)
        assert "_InterruptStart" not in _callbacks()
        clear_after_commit_callbacks()
        _run(starts, _read(session, work.id))

        run = _read(session, work.id)
        assert (run.state_code, run.environment_id) == (SessionState.STOPPED, None)
        (brief,) = _turns(session, run.id)
        assert brief.ended_at == run.stopped_at == run.turn_ended_at
        assert fake.calls == []

    def test_a_held_work_item_is_stopped_and_nothing_of_it_starts_afterwards(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        person: User,
        controller_outage: ControllerOutage,
    ) -> None:
        controller_outage.call_unanswered()
        work = _held(starts, session, project)

        starts.stop(session, work.id, person)
        clear_after_commit_callbacks()
        controller_outage.probe_answered()
        _release(starts)
        _run(starts, _read(session, work.id))

        run = _read(session, work.id)
        assert run.state_code == SessionState.STOPPED
        (brief,) = _turns(session, run.id)
        assert brief.ended_at is not None
        assert fake.calls == []
        assert _server(session, run.id) == []

    def test_a_stop_while_its_session_is_created_sends_nothing(
        self,
        container: ServiceContainer,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        person: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        work = _start_work(starts, session, project)
        client = container.controller_client()
        create = client.create_headless_session

        def stopped_meanwhile(*args: Any) -> Any:
            created = create(*args)
            starts.stop(session, work.id, person)
            session.flush()
            return created

        monkeypatch.setattr(client, "create_headless_session", stopped_meanwhile)

        _run(starts, _read(session, work.id))
        clear_after_commit_callbacks()

        run = _read(session, work.id)
        assert (run.state_code, run.controller_session) == (SessionState.STOPPED, None)
        env_id = _env(session, run.id)
        (created,) = fake.sessions(env_id)
        assert _sends(fake, env_id, created.name) == 0

    @pytest.mark.parametrize(
        ("state", "refusal"),
        [
            (SessionState.IDLE, "its turn has ended"),
            (SessionState.STOPPED, "it is stopped already"),
            (SessionState.FAILED, "it has failed"),
            (SessionState.ENDED, "its session has ended"),
        ],
    )
    def test_a_work_item_neither_running_starting_nor_held_is_refused(
        self,
        starts: SessionStartService,
        session: DbSession,
        project: Project,
        person: User,
        state: SessionState,
        refusal: str,
    ) -> None:
        run = _start(starts, session, project)
        run.state_code = state
        session.flush()

        with pytest.raises(InvalidOperationException, match=refusal):
            starts.stop(session, run.id, person)

        assert _read(session, run.id).stopped_at is None

    def test_a_session_with_no_work_item_is_refused(
        self,
        starts: SessionStartService,
        session: DbSession,
        project: Project,
        environment: Environment,
        person: User,
    ) -> None:
        chat = _chat(session, project, environment, SessionState.RUNNING)

        with pytest.raises(InvalidOperationException, match="it is no work item"):
            starts.stop(session, chat.id, person)

    def test_an_unknown_session_is_not_found(
        self, starts: SessionStartService, session: DbSession, person: User
    ) -> None:
        with pytest.raises(RecordNotFoundException):
            starts.stop(session, uuid.uuid4(), person)


class TestStopProject:
    """Finish's and Archive's stop (F5.1, F128.1; V11)."""

    def test_every_session_running_starting_or_held_is_stopped(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        environment: Environment,
        person: User,
        controller_outage: ControllerOutage,
    ) -> None:
        running = _running(starts, session, project)
        starting = _start(starts, session, project)
        chat = _chat(session, project, environment, SessionState.STARTING)
        controller_outage.call_unanswered()
        held = _start(starts, session, project)
        controller_outage.probe_answered()
        idle = _start(starts, session, project)
        idle.state_code = SessionState.IDLE
        other = Project(created_by_user_id=person.id)
        session.add(other)
        session.flush()
        elsewhere = _start(starts, session, other)
        at = datetime.now(UTC)

        starts.stop_project(session, project, person, at)

        for stopped in (running.id, starting.id, chat.id, held.id):
            run = _read(session, stopped)
            assert (run.state_code, run.stopped_at, run.stopped_by_user_id) == (
                SessionState.STOPPED,
                at,
                person.id,
            )
        assert _read(session, idle.id).state_code == SessionState.IDLE
        assert _read(session, elsewhere.id).state_code == SessionState.STARTING
        # No controller call in the transaction: the interrupt follows its commit.
        assert "_InterruptStart" in _callbacks()
        clear_after_commit_callbacks()


def _stopped_item(
    starts: SessionStartService,
    fake: _Recording,
    db: DbSession,
    project: Project,
    person: User,
) -> models.Session:
    """A work item stopped under its turn, its relay having recorded the
    interrupt's `result`, with its conversation."""
    run = _running(starts, db, project)
    run.conversation_id = "conv-1"
    starts.stop(db, run.id, person)
    clear_after_commit_callbacks()
    _turn_ends(starts, fake, run, "interrupted")
    run = _read(db, run.id)
    assert run.state_code == SessionState.STOPPED
    assert run.turn_ended_at is not None
    return run


class TestResume:
    """A work item's Resume (F67.2, F26.7; R15's rule; review A1; V04, V05)."""

    def test_a_stopped_work_item_resumes_with_continue_through_the_start(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        person: User,
    ) -> None:
        stopped = _stopped_item(starts, fake, session, project, person)
        env_id = _env(session, stopped.id)
        name = stopped.controller_session
        records = len(_records(session, stopped.id))

        run = starts.resume(session, stopped.id)

        assert run.state_code == SessionState.STARTING
        brief, resumed = _turns(session, run.id)
        assert (resumed.seq, resumed.message, resumed.author_user_id) == (
            2,
            CONTINUE,
            None,
        )
        assert resumed.ended_at is None
        assert (run.turns, run.turn_started_at, run.turn_ended_at) == (
            2,
            resumed.started_at,
            None,
        )
        # Its controller session takes the turn: no phase of a start.
        assert len(_records(session, run.id)) == records
        assert run.current_line is None
        # The facts of the stop stay (DB s-15).
        assert (run.stopped_at, run.stopped_by_user_id) == (
            stopped.stopped_at,
            person.id,
        )
        assert "_LoopStart" in _callbacks()
        clear_after_commit_callbacks()

        _run(starts, run)

        run = _read(session, run.id)
        assert run.state_code == SessionState.RUNNING
        assert (run.controller_session, run.environment_id) == (name, env_id)
        assert name is not None and fake.session(env_id, name).status == "busy"
        assert _sends(fake, env_id, name) == 2
        # "running N min" counts from the Resume's send.
        assert run.started_at == _turns(session, run.id)[1].started_at
        assert session.scalars(select(Item)).all() == [session.get_one(Item, run.id)]
        assert fake.calls.count(CREATE_ENVIRONMENT) == 1

    def test_a_failed_start_with_no_environment_resumes_with_the_ended_turns_message_in_one_it_creates(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        # A failed start: the controller refused the environment's create.
        fake.capped()
        work = _start_work(starts, session, project)
        _run(starts, _read(session, work.id))
        assert _read(session, work.id).state_code == SessionState.FAILED
        fake.capped(on=False)

        run = starts.resume(session, work.id)
        clear_after_commit_callbacks()

        assert run.error is None
        _, resumed = _turns(session, run.id)
        assert resumed.message == BRIEF
        _run(starts, run)
        run = _read(session, run.id)
        assert run.state_code == SessionState.RUNNING
        env_id = _env(session, run.id)
        assert fake.created == [env_id]
        assert _server(session, run.id)[-2:] == [(None, PREPARING), (None, CREATING)]
        (created,) = fake.sessions(env_id)
        assert fake.create_bodies == [{"cwd": CWD}]
        assert _sends(fake, env_id, created.name) == 1

    def test_a_failed_turn_resumes_its_error_cleared(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
    ) -> None:
        run = _running(starts, session, project)
        run.conversation_id = "conv-1"
        _turn_ends(starts, fake, run, "error")
        assert _read(session, run.id).state_code == SessionState.FAILED

        resumed = starts.resume(session, run.id)
        clear_after_commit_callbacks()
        _run(starts, resumed)

        run = _read(session, run.id)
        assert run.state_code == SessionState.RUNNING
        assert [turn.message for turn in _turns(session, run.id)] == [BRIEF, CONTINUE]
        assert work_status(session, [run.id], unreachable=False)[run.id].error is None

    def test_while_the_gate_is_closed_it_is_held_and_runs_once_it_opens(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        person: User,
        controller_outage: ControllerOutage,
    ) -> None:
        stopped = _stopped_item(starts, fake, session, project, person)
        env_id = _env(session, stopped.id)
        name = stopped.controller_session
        assert name is not None
        controller_outage.call_unanswered()

        run = starts.resume(session, stopped.id)

        assert run.state_code == SessionState.HELD
        assert "_HeldWritten" in _callbacks()
        clear_after_commit_callbacks()
        _, resumed = _turns(session, run.id)
        assert (resumed.message, resumed.ended_at) == (CONTINUE, None)
        status = work_status(session, [run.id], unreachable=True)[run.id]
        assert status.held_reason == HeldReason.CONTROLLER_UNREACHABLE
        # Held in the environment it is bound to, its chip as the row stands.
        assert status.environment is not None
        assert (status.environment.id, status.environment.name) == (env_id, SLUG)
        assert _sends(fake, env_id, name) == 1

        controller_outage.probe_answered()
        _release(starts)
        _run(starts, run)

        assert _read(session, run.id).state_code == SessionState.RUNNING
        assert _sends(fake, env_id, name) == 2

    def test_in_a_paused_project_it_is_held(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        person: User,
    ) -> None:
        stopped = _stopped_item(starts, fake, session, project, person)
        project.paused = True
        session.flush()

        run = starts.resume(session, stopped.id)
        clear_after_commit_callbacks()

        assert run.state_code == SessionState.HELD
        assert work_status(session, [run.id], unreachable=False)[
            run.id
        ].held_reason == (HeldReason.PAUSED)

    def test_a_controller_session_gone_is_created_anew_with_its_conversation(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        person: User,
    ) -> None:
        stopped = _stopped_item(starts, fake, session, project, person)
        env_id = _env(session, stopped.id)
        gone = stopped.controller_session
        fake.restart(env_id)
        fake.set_status(env_id, "running")
        run = starts.resume(session, stopped.id)
        clear_after_commit_callbacks()

        _run(starts, run)

        run = _read(session, run.id)
        assert run.state_code == SessionState.RUNNING
        assert run.controller_session not in (None, gone)
        server = _server(session, run.id)
        assert server[-3][1]["type"] == SESSION_GONE
        assert "404 not-found" in server[-3][1]["reason"]
        assert server[-2:] == [(None, STARTING_ENV), (None, CREATING)]
        assert fake.create_bodies[-1] == {"cwd": CWD, "resume": "conv-1"}
        assert run.controller_session is not None
        assert _sends(fake, env_id, run.controller_session) == 1
        assert fake.calls.count(CREATE_ENVIRONMENT) == 1

    def test_an_environment_stopped_meanwhile_is_started_again(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        person: User,
    ) -> None:
        stopped = _stopped_item(starts, fake, session, project, person)
        env_id = _env(session, stopped.id)
        fake.set_status(env_id, "stopped")
        run = starts.resume(session, stopped.id)
        clear_after_commit_callbacks()

        _run(starts, run)

        run = _read(session, run.id)
        assert run.state_code == SessionState.RUNNING
        assert fake.environment(env_id).status == "running"
        assert "409 conflict" in _server(session, run.id)[-3][1]["reason"]
        assert f"POST /environments/{env_id}/start" in fake.calls
        # Pilot's start brought the pod up: its claim (P2).
        assert _row(session, env_id).started_pod_at == (
            fake.environment(env_id).pod_started_at
        )

    def test_an_environment_the_controller_will_not_start_fails_the_item(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        person: User,
    ) -> None:
        stopped = _stopped_item(starts, fake, session, project, person)
        env_id = _env(session, stopped.id)
        fake.set_status(env_id, "stopped")
        fake.capped(env_id)
        run = starts.resume(session, stopped.id)
        clear_after_commit_callbacks()

        _run(starts, run)

        run = _read(session, run.id)
        assert run.state_code == SessionState.FAILED
        assert run.error is not None and "environment limit" in run.error
        assert _server(session, run.id)[-2:] == [
            (None, STARTING_ENV),
            (None, {"type": START_FAILED, "reason": run.error}),
        ]
        assert fake.calls.count(CREATE_ENVIRONMENT) == 1

    def test_a_resume_meeting_the_outage_is_held_again(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        person: User,
        controller_outage: ControllerOutage,
    ) -> None:
        stopped = _stopped_item(starts, fake, session, project, person)
        run = starts.resume(session, stopped.id)
        clear_after_commit_callbacks()
        fake.outage(answer="ingress")

        _run(starts, run)

        assert _read(session, run.id).state_code == SessionState.HELD
        assert controller_outage.holds
        _, resumed = _turns(session, run.id)
        assert (resumed.ended_at, resumed.error) == (None, None)

    def test_a_resume_whose_send_fails_fails_the_item(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        person: User,
    ) -> None:
        stopped = _stopped_item(starts, fake, session, project, person)
        run = starts.resume(session, stopped.id)
        clear_after_commit_callbacks()
        fake.refuse_sends = True

        _run(starts, run)

        run = _read(session, run.id)
        assert run.state_code == SessionState.FAILED
        _, resumed = _turns(session, run.id)
        assert resumed.ended_at is not None and resumed.error is not None
        assert run.error == resumed.error

    def test_a_resume_in_an_environment_pilot_did_not_bring_up_arms_nothing(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        person: User,
    ) -> None:
        # Someone stopped and started the environment meanwhile: the pod
        # running there is not Pilot's start's, and its claim has ended.
        stopped = _stopped_item(starts, fake, session, project, person)
        env_id = _env(session, stopped.id)
        row = _row(session, env_id)
        row.server_started_at = row.started_pod_at = row.stop_due_at = None
        session.flush()
        run = starts.resume(session, stopped.id)
        clear_after_commit_callbacks()
        fake.refuse_sends = True

        _run(starts, run)

        assert _read(session, run.id).state_code == SessionState.FAILED
        row = _row(session, env_id)
        assert (row.server_started_at, row.stop_due_at) == (None, None)

    def test_it_moves_the_item_and_its_state(
        self,
        container: ServiceContainer,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        person: User,
        engine_events: list[EngineEvent],
    ) -> None:
        stopped = _stopped_item(starts, fake, session, project, person)
        engine_events.clear()

        with scoped_session(container) as db:
            starts.resume(db, stopped.id)

        assert _moves(engine_events) == [
            WorkMoved(project.id, stopped.id),
            ProjectChanged(project.id),
        ]

    @pytest.mark.parametrize(
        ("state", "refusal"),
        [
            (SessionState.HELD, "its start waits at the gate"),
            (SessionState.STARTING, "it is starting"),
            (SessionState.RUNNING, "it is running"),
            (SessionState.IDLE, "its turn has ended"),
            (SessionState.ENDED, "its session has ended"),
        ],
    )
    def test_a_work_item_neither_stopped_nor_failed_is_refused(
        self,
        starts: SessionStartService,
        session: DbSession,
        project: Project,
        state: SessionState,
        refusal: str,
    ) -> None:
        run = _start(starts, session, project)
        run.state_code = state
        session.flush()

        with pytest.raises(InvalidOperationException, match=refusal):
            starts.resume(session, run.id)

        assert len(_turns(session, run.id)) == 1

    def test_a_turn_still_ending_under_its_stop_is_refused(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        person: User,
    ) -> None:
        run = _running(starts, session, project)
        starts.stop(session, run.id, person)
        clear_after_commit_callbacks()

        with pytest.raises(
            InvalidOperationException, match="its stopped turn is still ending"
        ):
            starts.resume(session, run.id)

    @pytest.mark.parametrize(
        ("standing", "refusal"),
        [
            ({"state_code": ProjectState.FINISHED}, "its project is finished"),
            ({"archived": True}, "its project is archived"),
        ],
    )
    def test_a_finished_or_archived_project_refuses_it(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        person: User,
        standing: dict[str, Any],
        refusal: str,
    ) -> None:
        stopped = _stopped_item(starts, fake, session, project, person)
        for column, value in standing.items():
            setattr(project, column, value)
        session.flush()

        with pytest.raises(InvalidOperationException, match=refusal):
            starts.resume(session, stopped.id)

    def test_a_session_with_no_work_item_is_refused(
        self,
        starts: SessionStartService,
        session: DbSession,
        project: Project,
        environment: Environment,
    ) -> None:
        chat = _chat(session, project, environment, SessionState.STOPPED)

        with pytest.raises(InvalidOperationException, match="it is no work item"):
            starts.resume(session, chat.id)

    def test_no_controller_refuses_it(
        self,
        container: ServiceContainer,
        fake: _Recording,
        supervise: Supervise,
        session: DbSession,
        project: Project,
        person: User,
    ) -> None:
        starts = _services(container, supervise)[0]
        stopped = _stopped_item(starts, fake, session, project, person)
        unconfigured = _services(container, supervise, controller_configured=False)[0]

        with pytest.raises(InvalidOperationException, match="no controller"):
            unconfigured.resume(session, stopped.id)

    def test_an_unknown_session_is_not_found(
        self, starts: SessionStartService, session: DbSession
    ) -> None:
        with pytest.raises(RecordNotFoundException):
            starts.resume(session, uuid.uuid4())


class TestStopLoop:
    """A Stop's commit interrupts the turn, and its relay records it to its
    end (F67.1)."""

    def test_a_stopped_work_item_ends_its_turn_interrupted_and_stays_stopped(
        self,
        committed_app: Flask,
        committed_fake: _Recording,
        supervise: Supervise,
    ) -> None:
        container = committed_app.container
        starts, _, coordinator = _services(container, supervise)
        project_id = _committed_project(container)
        coordinator.fire_startup()
        work_id = _committed_work(starts, container, project_id)
        wait_until(
            lambda: _committed(container, work_id).state_code == SessionState.RUNNING,
            "the brief sent",
        )
        env_id = _committed_env(container, work_id)
        name = _committed(container, work_id).controller_session
        assert name is not None
        committed_fake.play(env_id, name, raw_turn("turn_text")[:3])

        with scoped_session(container) as db:
            person = db.scalars(select(User).where(User.handle == "ada")).one()
            starts.stop(db, work_id, person)

        def interrupted() -> bool:
            with scoped_session(container) as db:
                return all(turn.ended_at for turn in _turns(db, work_id))

        wait_until(interrupted, "the stopped turn ended")
        result = committed_fake.session(env_id, name).result
        assert result is not None and result["interrupted"]
        run = _committed(container, work_id)
        assert run.state_code == SessionState.STOPPED
        assert run.current_line is None
        with scoped_session(container) as db:
            assert db.get_one(Item, work_id).done_at is None


class TestStartInAClosedProject:
    """Nothing of a finished or an archived project starts (F5.1, F128.1)."""

    @pytest.mark.parametrize(
        ("standing", "refusal"),
        [
            ({"state_code": ProjectState.FINISHED}, "its project is finished"),
            ({"archived": True}, "its project is archived"),
        ],
    )
    def test_a_work_start_is_refused(
        self,
        starts: SessionStartService,
        fake: _Recording,
        session: DbSession,
        project: Project,
        standing: dict[str, Any],
        refusal: str,
    ) -> None:
        for column, value in standing.items():
            setattr(project, column, value)
        session.flush()

        with pytest.raises(InvalidOperationException, match=refusal):
            _start_work(starts, session, project)

        assert session.scalars(select(Item).where(Item.kind_code == "work")).all() == []
        assert fake.calls == []
