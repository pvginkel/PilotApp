"""The relays' watchdog (design 2 §9.3, D004; V06, V17).

Each test runs the fleet consumer, the relays and the watchdog on one
supervisor, as STARTUP does, against a fake whose response stream for the
session the test names is wedged: it sends no `result` and never ends by
itself, so only the watchdog's restart moves the turn on."""

import json
import threading
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from flask import Flask
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.models import Environment, Project, Turn, User
from app.models.reference import RecordKind, SessionState, UserKind
from app.services.container import ServiceContainer
from app.services.controller_client import (
    ControllerClient,
    ControllerEnvironment,
    HeadlessCreateRequest,
    SessionView,
)
from app.services.environment_service import EnvironmentService
from app.services.fake_controller import FakeSession
from app.services.fleet_consumer import FLEET_STREAM_CONNECTED, FleetConsumer
from app.services.relay_service import RELAY_JOB, RELAYS_RUNNING, RelayService
from app.services.relay_watchdog import WATCHDOG_TIMER, RelayWatchdog
from app.services.session_record_service import read_records
from app.services.supervisor import TIMER_RUNS_TOTAL, LoopHandle, Supervisor
from app.utils.lifecycle_coordinator import LifecycleCoordinator
from tests.support.fake_controller import ServedFakeController, client_of, raw_turn
from tests.support.supervisor import (
    WAIT_SECONDS,
    LogWaiter,
    Supervise,
    listening,
    metric_value,
    wait_until,
)

ENV = "env-a"
WATCHDOG_LOGGER = "app.services.relay_watchdog"
RELAY_LOGGER = "app.services.relay_service"


class _Wedged(ServedFakeController):
    """The fake, whose next response stream of each session named in `wedge`
    sends the session's lines and then keepalives alone: no `result`, and no
    end until the client closes it."""

    def __init__(self, keepalive_seconds: float) -> None:
        super().__init__(keepalive_seconds)
        self.wedge: set[str] = set()

    def _response_frames(
        self,
        session: FakeSession,
        sent: int,
        deadline: float | None,
        drops: int,
    ) -> Iterator[bytes]:
        if session.name not in self.wedge:
            yield from super()._response_frames(session, sent, deadline, drops)
            return
        self.wedge.discard(session.name)
        for frame in super()._response_frames(session, sent, deadline, drops):
            if frame.startswith(b"event: result"):
                break
            yield frame
        while not self._closed:
            time.sleep(0.05)
            yield b": keepalive\n\n"


@pytest.fixture
def wedged(committed_app: Flask) -> Iterator[_Wedged]:
    fake = _Wedged(keepalive_seconds=0.2)
    client_of(committed_app.container, fake)
    fake.add_environment(ENV, status="running")
    try:
        yield fake
    finally:
        fake.close()


@pytest.fixture
def watch_log() -> Iterator[LogWaiter]:
    with listening(WATCHDOG_LOGGER, RELAY_LOGGER) as waiter:
        yield waiter


def _watch(
    container: ServiceContainer, supervise: Supervise
) -> tuple[RelayService, LifecycleCoordinator]:
    """The fleet consumer, the relays and the watchdog on one supervisor."""
    supervisor, coordinator = supervise(container)
    fleet = FleetConsumer(
        container=container,
        supervisor=supervisor,
        controller_outage=container.controller_outage(),
    )
    environments = EnvironmentService(
        container=container,
        supervisor=supervisor,
        stop_after_seconds=timedelta(minutes=30).total_seconds(),
        delete_after_seconds=timedelta(days=7).total_seconds(),
    )
    relays = RelayService(
        container=container,
        supervisor=supervisor,
        session_streams=container.session_stream_service(),
        environment_service=environments,
    )
    RelayWatchdog(supervisor=supervisor, fleet_consumer=fleet)
    return relays, coordinator


def _session_rows(container: ServiceContainer, name: str) -> uuid.UUID:
    """An idle Session on the headless session `name`, committed; its id."""
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
        db.add(
            Environment(
                id=ENV,
                name="Env-A",
                exempt=False,
                last_state="running",
                server_started_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
        db.flush()
        run = models.Session(
            project_id=project.id,
            environment_id=ENV,
            kind_code="work",
            cwd="/work/Example",
            controller_session=name,
            token_hash=uuid.uuid4().hex,
            state_code=SessionState.IDLE,
        )
        db.add(run)
        db.flush()
        return run.id


def _read(container: ServiceContainer, run_id: uuid.UUID) -> models.Session:
    with scoped_session(container) as db:
        run = db.get_one(models.Session, run_id)
        db.expunge(run)
        return run


def _claude(container: ServiceContainer, run_id: uuid.UUID) -> list[int | None]:
    """The offsets of the Session's `claude` records."""
    with scoped_session(container) as db:
        return [
            stored.record.raw_offset
            for stored in read_records(db, run_id, limit=1000)
            if stored.record.kind_code == RecordKind.CLAUDE
        ]


def _recorded(lines: list[str], offsets: list[int]) -> list[int | None]:
    return [
        offset
        for offset, line in zip(offsets, lines, strict=True)
        if json.loads(line).get("type") != "stream_event"
    ]


def _idle(container: ServiceContainer, run_id: uuid.UUID) -> None:
    wait_until(
        lambda: _read(container, run_id).state_code == SessionState.IDLE,
        "the turn ended",
    )


def _has_busy(fake: ServedFakeController, name: str) -> bool:
    return any(s.name == name and s.status == "busy" for s in fake.sessions(ENV))


def _client(container: ServiceContainer) -> ControllerClient:
    """The container's client, on the wedged fake."""
    client: ControllerClient = container.controller_client()
    return client


def _ticks() -> float:
    return metric_value(TIMER_RUNS_TOTAL, timer=WATCHDOG_TIMER, outcome="ok")


class TestRelayWatchdog:
    @pytest.fixture
    def relaying(
        self,
        committed_app: Flask,
        wedged: _Wedged,
        supervise: Supervise,
    ) -> tuple[str, uuid.UUID, list[str], list[int]]:
        """A turn in flight whose relay holds the wedged stream, its first
        lines recorded: the controller session's name, the Session's id, the
        turn's lines and the played lines' offsets."""
        container = committed_app.container
        name = (
            _client(container)
            .create_headless_session(ENV, HeadlessCreateRequest())
            .name
        )
        run_id = _session_rows(container, name)
        relays, coordinator = _watch(container, supervise)
        coordinator.fire_startup()
        wait_until(lambda: metric_value(FLEET_STREAM_CONNECTED) == 1, "connected")
        wedged.wedge.add(name)
        with scoped_session(container) as db:
            assert relays.send(db, run_id, "Rename the badge").error is None
        wait_until(lambda: metric_value(RELAYS_RUNNING) == 1, "relaying")
        lines = raw_turn("turn_tool")
        offsets = wedged.play(ENV, name, lines[:11])
        wait_until(
            lambda: _claude(container, run_id) == _recorded(lines[:11], offsets),
            "the first lines recorded",
        )
        return name, run_id, lines, offsets

    def test_it_is_a_timer_that_needs_the_controller(
        self, app: Flask, supervise: Supervise
    ) -> None:
        supervisor, coordinator = supervise(app.container, controller_configured=False)
        fleet = FleetConsumer(
            container=app.container,
            supervisor=supervisor,
            controller_outage=app.container.controller_outage(),
        )
        RelayWatchdog(supervisor=supervisor, fleet_consumer=fleet)

        with listening("app.services.supervisor") as log:
            coordinator.fire_startup()

        assert log.matching(r"No controller configured.*") == [
            "No controller configured (CONTROLLER_URL unset): the jobs and timers "
            f"that need one do not start (fleet, {WATCHDOG_TIMER})"
        ]

    def test_a_turn_whose_session_stopped_working_has_its_relay_restarted(
        self,
        committed_app: Flask,
        wedged: _Wedged,
        relaying: tuple[str, uuid.UUID, list[str], list[int]],
        watch_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        name, run_id, lines, offsets = relaying
        rest = wedged.play(ENV, name, lines[11:])
        wait_until(
            lambda: _claude(container, run_id) == _recorded(lines, offsets + rest),
            "the turn's lines recorded",
        )
        # The turn ends; the wedged stream never says so.
        wedged.finish(ENV, name, "success", "Done.")

        watch_log.wait_for(
            rf"Restarted the relay of session {run_id}: its session {name} is not "
            "working"
        )
        _idle(container, run_id)
        assert _claude(container, run_id) == _recorded(lines, offsets + rest)
        path = f"GET /environments/{ENV}/sessions/headless/{name}/response"
        assert [call for call in wedged.calls if call.startswith(path)] == [
            f"{path}?format=raw&offset=0",
            f"{path}?format=raw&offset={_recorded(lines, offsets + rest)[-1]}",
        ]

    def test_a_running_environment_without_the_session_has_its_relay_restarted(
        self,
        committed_app: Flask,
        wedged: _Wedged,
        relaying: tuple[str, uuid.UUID, list[str], list[int]],
        watch_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        name, run_id, _, _ = relaying

        _client(container).end_session(ENV, name)

        watch_log.wait_for(
            rf"Restarted the relay of session {run_id}: environment {ENV} has no "
            rf"session {name}"
        )
        watch_log.wait_for(rf"Session {run_id} lost controller session {name}; .*")
        wait_until(lambda: _has_busy(wedged, "claude-2"), "the continue sent")
        wedged.play(ENV, "claude-2", raw_turn("turn_text"))
        wedged.finish(ENV, "claude-2", "success", "Done.")
        _idle(container, run_id)
        assert _read(container, run_id).controller_session == "claude-2"

    def test_an_environment_whose_pod_restarted_has_its_relay_restarted(
        self,
        committed_app: Flask,
        wedged: _Wedged,
        relaying: tuple[str, uuid.UUID, list[str], list[int]],
        watch_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        name, run_id, _, _ = relaying
        # The watchdog has seen the environment's restart count.
        ticks = _ticks()
        wait_until(lambda: _ticks() >= ticks + 2, "two ticks")

        wedged.restart(ENV)

        watch_log.wait_for(
            rf"Restarted the relay of session {run_id}: environment {ENV} restarted"
        )
        watch_log.wait_for(rf"Environment {ENV} is not running: waiting for it to .*")
        wedged.set_status(ENV, "running")
        wait_until(lambda: _has_busy(wedged, "claude-2"), "the continue sent")
        wedged.play(ENV, "claude-2", raw_turn("turn_text"))
        wedged.finish(ENV, "claude-2", "success", "Done.")
        _idle(container, run_id)

    def test_an_environment_stopped_elsewhere_has_its_relay_restarted(
        self,
        committed_app: Flask,
        wedged: _Wedged,
        relaying: tuple[str, uuid.UUID, list[str], list[int]],
        watch_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        _, run_id, _, _ = relaying

        # The wedged stream outlives the pod: only the watchdog moves it on.
        _client(container).stop_environment(ENV)

        watch_log.wait_for(
            rf"Restarted the relay of session {run_id}: environment {ENV} is "
            "(stopping|stopped)"
        )
        wait_until(
            lambda: _read(container, run_id).state_code == SessionState.STOPPED,
            "the session stopped",
        )
        assert _read(container, run_id).stopped_by_user_id is None

    def test_a_turn_still_working_is_left_alone(
        self,
        committed_app: Flask,
        relaying: tuple[str, uuid.UUID, list[str], list[int]],
        watch_log: LogWaiter,
    ) -> None:
        ticks = _ticks()

        wait_until(lambda: _ticks() >= ticks + 4, "four ticks")

        assert watch_log.matching(r"Restarted the relay .*") == []

    def test_a_relay_this_process_does_not_run_is_left_alone(
        self,
        committed_app: Flask,
        wedged: _Wedged,
        supervise: Supervise,
        watch_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        name = (
            _client(container)
            .create_headless_session(ENV, HeadlessCreateRequest())
            .name
        )
        run_id = _session_rows(container, name)
        with scoped_session(container) as db:
            db.get_one(models.Session, run_id).state_code = SessionState.RUNNING
        # Another process relays it: here, the watchdog and the fleet alone.
        supervisor, coordinator = supervise(container)
        fleet = FleetConsumer(
            container=container,
            supervisor=supervisor,
            controller_outage=container.controller_outage(),
        )
        RelayWatchdog(supervisor=supervisor, fleet_consumer=fleet)
        coordinator.fire_startup()
        ticks = _ticks()

        wait_until(lambda: _ticks() >= ticks + 4, "four ticks")

        assert fleet.sessions(ENV) is not None
        assert watch_log.matching(r"Restarted the relay .*") == []


class _Fleet(FleetConsumer):
    """The fleet consumer as each test sets it: each environment's state and
    session set."""

    def __init__(self, container: ServiceContainer, supervisor: Supervisor) -> None:
        super().__init__(
            container=container,
            supervisor=supervisor,
            controller_outage=container.controller_outage(),
        )
        self.states: dict[str, ControllerEnvironment] = {}
        self.views: dict[str, tuple[SessionView, ...]] = {}

    def environment(self, env_id: str) -> ControllerEnvironment | None:
        return self.states.get(env_id)

    def sessions(self, env_id: str) -> tuple[SessionView, ...] | None:
        return self.views.get(env_id)


def _state(
    env_id: str, status: str = "running", restarts: int = 0
) -> ControllerEnvironment:
    return ControllerEnvironment.model_validate(
        {
            "envId": env_id,
            "repo": "example/Example",
            "status": status,
            "pod": {"restartCount": restarts},
            "setupRunning": False,
            "capabilities": {"capacityExempt": {"enabled": False}},
        }
    )


def _view(name: str, working: bool) -> SessionView:
    return SessionView(
        name=name, title="An example", state="running", mode="headless", working=working
    )


class _Relay:
    """A relay loop of the Session's that holds a stream until the watchdog
    closes it."""

    def __init__(self, supervisor: Supervisor, run_id: uuid.UUID) -> None:
        self.holding = threading.Event()
        self.closed = threading.Event()
        supervisor.start_loop(RELAY_JOB, self._run, key=str(run_id))
        assert self.holding.wait(WAIT_SECONDS)

    def _run(self, handle: LoopHandle) -> None:
        with handle.holding(self):
            self.holding.set()
            self.closed.wait(WAIT_SECONDS)

    def close(self) -> None:
        self.closed.set()


class TestRun:
    """One tick at a time, on the Session's rows and the fleet as the test sets
    it."""

    @pytest.fixture
    def watched(
        self,
        app: Flask,
        session: DbSession,
        project_session: models.Session,
        supervise: Supervise,
    ) -> tuple[RelayWatchdog, _Fleet, _Relay, str]:
        """The watchdog, its fleet, the running Session's relay, and the
        Session's environment, running with the session working."""
        project_session.controller_session = "claude-1"
        session.flush()
        supervisor, coordinator = supervise(app.container, controller_configured=False)
        supervisor.register_job(RELAY_JOB, needs_controller=False)
        fleet = _Fleet(app.container, supervisor)
        watchdog = RelayWatchdog(supervisor=supervisor, fleet_consumer=fleet)
        coordinator.fire_startup()
        env_id = project_session.environment_id
        fleet.states[env_id] = _state(env_id)
        fleet.views[env_id] = (_view("claude-1", working=True),)
        return watchdog, fleet, _Relay(supervisor, project_session.id), env_id

    def test_a_session_not_working_on_two_ticks_has_its_relay_restarted(
        self,
        session: DbSession,
        watched: tuple[RelayWatchdog, _Fleet, _Relay, str],
        watch_log: LogWaiter,
    ) -> None:
        watchdog, fleet, relay, env_id = watched
        fleet.views[env_id] = (_view("claude-1", working=False),)

        watchdog.run(session)
        assert not relay.closed.is_set()
        watchdog.run(session)

        assert relay.closed.is_set()
        assert len(watch_log.matching(r"Restarted the relay .*: its session .*")) == 1

    def test_one_tick_amiss_then_well_restarts_nothing(
        self,
        session: DbSession,
        watched: tuple[RelayWatchdog, _Fleet, _Relay, str],
    ) -> None:
        watchdog, fleet, relay, env_id = watched
        for working in (False, True, False):
            fleet.views[env_id] = (_view("claude-1", working=working),)
            watchdog.run(session)

        assert not relay.closed.is_set()

    def test_a_running_environment_without_the_session_on_two_ticks_restarts_it(
        self,
        session: DbSession,
        watched: tuple[RelayWatchdog, _Fleet, _Relay, str],
        watch_log: LogWaiter,
    ) -> None:
        watchdog, fleet, relay, env_id = watched
        fleet.views[env_id] = (_view("claude-9", working=True),)

        watchdog.run(session)
        watchdog.run(session)

        assert relay.closed.is_set()
        assert watch_log.matching(r"Restarted the relay .*: environment .* has no .*")

    def test_an_environment_not_running_without_the_session_restarts_nothing(
        self,
        session: DbSession,
        watched: tuple[RelayWatchdog, _Fleet, _Relay, str],
    ) -> None:
        watchdog, fleet, relay, env_id = watched
        fleet.states[env_id] = _state(env_id, status="starting")
        fleet.views[env_id] = ()

        for _ in range(3):
            watchdog.run(session)

        assert not relay.closed.is_set()

    @pytest.mark.parametrize("status", ["stopping", "stopped", "deleting"])
    def test_an_environment_stopped_elsewhere_restarts_it_at_once(
        self,
        session: DbSession,
        watched: tuple[RelayWatchdog, _Fleet, _Relay, str],
        watch_log: LogWaiter,
        status: str,
    ) -> None:
        watchdog, fleet, relay, env_id = watched
        fleet.states[env_id] = _state(env_id, status=status)
        fleet.views[env_id] = ()

        watchdog.run(session)

        assert relay.closed.is_set()
        assert watch_log.matching(
            rf"Restarted the relay .*: environment {env_id} is {status}"
        )

    @pytest.mark.parametrize("in_flight", [True, False])
    def test_a_session_stopped_is_watched_while_its_turn_is_in_flight(
        self,
        session: DbSession,
        project_session: models.Session,
        watched: tuple[RelayWatchdog, _Fleet, _Relay, str],
        in_flight: bool,
    ) -> None:
        watchdog, fleet, relay, env_id = watched
        project_session.state_code = SessionState.STOPPED
        now = datetime.now(UTC)
        session.add(
            Turn(
                session_id=project_session.id,
                seq=1,
                message="Build the camp",
                started_at=now,
                ended_at=None if in_flight else now,
            )
        )
        session.flush()
        fleet.states[env_id] = _state(env_id, status="stopped")

        watchdog.run(session)

        assert relay.closed.is_set() is in_flight

    def test_a_restart_count_that_moved_restarts_it_at_once(
        self,
        session: DbSession,
        watched: tuple[RelayWatchdog, _Fleet, _Relay, str],
        watch_log: LogWaiter,
    ) -> None:
        watchdog, fleet, relay, env_id = watched
        watchdog.run(session)
        fleet.states[env_id] = _state(env_id, status="starting", restarts=1)

        watchdog.run(session)

        assert relay.closed.is_set()
        assert watch_log.matching(
            rf"Restarted the relay .*: environment {env_id} restarted"
        )

    def test_the_first_count_seen_is_no_restart(
        self,
        session: DbSession,
        watched: tuple[RelayWatchdog, _Fleet, _Relay, str],
    ) -> None:
        watchdog, fleet, relay, env_id = watched
        fleet.states[env_id] = _state(env_id, restarts=3)

        watchdog.run(session)

        assert not relay.closed.is_set()

    def test_a_stream_that_is_down_restarts_nothing(
        self,
        session: DbSession,
        watched: tuple[RelayWatchdog, _Fleet, _Relay, str],
    ) -> None:
        watchdog, fleet, relay, env_id = watched
        fleet.states.clear()
        fleet.views.clear()

        for _ in range(3):
            watchdog.run(session)

        assert not relay.closed.is_set()

    def test_a_session_not_running_is_not_watched(
        self,
        session: DbSession,
        project_session: models.Session,
        watched: tuple[RelayWatchdog, _Fleet, _Relay, str],
    ) -> None:
        watchdog, fleet, relay, env_id = watched
        project_session.state_code = SessionState.IDLE
        session.flush()
        fleet.views[env_id] = (_view("claude-1", working=False),)

        for _ in range(3):
            watchdog.run(session)

        assert not relay.closed.is_set()
