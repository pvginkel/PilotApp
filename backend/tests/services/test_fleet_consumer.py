"""The fleet consumer: the Environment rows kept current from the fleet stream
(design 2 §13.1; F73.1). Each test runs it as the supervisor does, on a
database of its own, against the fake controller."""

from collections.abc import Callable, Generator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flask import Flask
from sqlalchemy import select
from werkzeug.wrappers import Request, Response

from app.database import scoped_session
from app.models import Environment
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerClient, HeadlessCreateRequest
from app.services.fleet_consumer import (
    FLEET_STREAM_CONNECTED,
    GONE,
    FleetConsumer,
)
from app.utils.lifecycle_coordinator import LifecycleCoordinator
from tests.support.fake_controller import ServedFakeController, client_of
from tests.support.supervisor import (
    LogWaiter,
    Supervise,
    listening,
    metric_value,
    wait_until,
)

CONSUMER_LOGGER = "app.services.fleet_consumer"
SUPERVISOR_LOGGER = "app.services.supervisor"


@pytest.fixture
def fleet_log() -> Generator[LogWaiter]:
    with listening(CONSUMER_LOGGER, SUPERVISOR_LOGGER) as waiter:
        yield waiter


type Consume = Callable[..., tuple[FleetConsumer, LifecycleCoordinator]]


@pytest.fixture
def consume(committed_app: Flask, supervise: Supervise) -> Consume:
    """Starts a fleet consumer on ``committed_app`` as STARTUP does, and waits
    until it has applied its first list."""

    def start(
        *, backoff: tuple[float, float] = (0.05, 0.2)
    ) -> tuple[FleetConsumer, LifecycleCoordinator]:
        supervisor, coordinator = supervise(committed_app.container, backoff=backoff)
        consumer = FleetConsumer(
            container=committed_app.container, supervisor=supervisor
        )
        coordinator.fire_startup()
        wait_until(_connected, "connected")
        return consumer, coordinator

    return start


def _connected() -> bool:
    return metric_value(FLEET_STREAM_CONNECTED) == 1


def _add(container: ServiceContainer, *rows: Environment) -> None:
    with scoped_session(container) as db:
        db.add_all(rows)


def _columns(container: ServiceContainer, env_id: str) -> dict[str, Any] | None:
    """The environment's row as committed; None with no row."""
    with scoped_session(container) as db:
        row = db.scalars(select(Environment).where(Environment.id == env_id)).first()
        if row is None:
            return None
        return {
            "name": row.name,
            "last_state": row.last_state,
            "last_seen_at": row.last_seen_at,
            "exempt": row.exempt,
            "server_started_at": row.server_started_at,
            "stop_due_at": row.stop_due_at,
        }


def _column(container: ServiceContainer, env_id: str, column: str) -> Any:
    columns = _columns(container, env_id)
    assert columns is not None
    return columns[column]


class TestFleetConsumer:
    def test_each_connect_subscribes_then_lists_and_applies_the_list(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        consume: Consume,
        fleet_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        fake_controller.add_environment(
            "env-a", name="Alpha", status="running", exempt=True
        )
        fake_controller.add_environment("env-c", status="running")
        _add(
            container,
            Environment(id="env-a", name="Old name", exempt=False),
            Environment(id="env-b", name="Bravo", exempt=False, last_state="running"),
        )
        before = datetime.now(UTC)

        consume()

        assert fake_controller.calls[:2] == ["GET /stream", "GET /environments"]
        a = _columns(container, "env-a")
        assert a is not None
        assert (a["name"], a["last_state"], a["exempt"]) == ("Alpha", "running", True)
        assert a["last_seen_at"] >= before
        # A row the list does not name is gone; a listed one Pilot has no row
        # for gets none.
        assert _column(container, "env-b", "last_state") == GONE
        assert _columns(container, "env-c") is None
        assert fleet_log.matching(r"Fleet stream connected.*") == [
            "Fleet stream connected; 2 environments listed"
        ]

    def test_an_environment_the_list_cannot_describe_keeps_its_row(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        consume: Consume,
    ) -> None:
        container = committed_app.container
        fake_controller.add_environment("env-a", status="running")
        fake_controller.unprojectable("env-a")
        _add(
            container,
            Environment(id="env-a", name="Alpha", exempt=False, last_state="running"),
        )

        consume()

        assert _column(container, "env-a", "last_state") == "running"

    def test_a_state_frame_updates_the_row(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        consume: Consume,
    ) -> None:
        container = committed_app.container
        fake_controller.add_environment("env-a", name="Alpha", status="running")
        _add(container, Environment(id="env-a", name="Alpha", exempt=False))
        consume()
        listed_at = _column(container, "env-a", "last_seen_at")

        fake_controller.set_status("env-a", "stopped")

        wait_until(
            lambda: _column(container, "env-a", "last_state") == "stopped",
            "stopped",
        )
        assert _column(container, "env-a", "last_seen_at") > listed_at

    def test_an_exempt_environment_has_no_deadline(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        consume: Consume,
    ) -> None:
        container = committed_app.container
        fake_controller.add_environment("env-a", status="running")
        started = datetime.now(UTC) - timedelta(hours=1)
        _add(
            container,
            Environment(
                id="env-a",
                name="Alpha",
                exempt=False,
                server_started_at=started,
                stop_due_at=datetime.now(UTC) + timedelta(minutes=5),
            ),
        )
        consume()
        assert _column(container, "env-a", "stop_due_at") is not None

        fake_controller.set_exempt("env-a", True)

        wait_until(lambda: _column(container, "env-a", "exempt"), "exempt")
        assert _column(container, "env-a", "stop_due_at") is None
        assert _column(container, "env-a", "server_started_at") == started

    def test_a_gone_frame_marks_the_row_gone(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        consume: Consume,
    ) -> None:
        container = committed_app.container
        fake_controller.add_environment("env-a", status="running")
        _add(container, Environment(id="env-a", name="Alpha", exempt=False))
        consumer, _ = consume()
        wait_until(lambda: consumer.sessions("env-a") == (), "seeded")

        fake_controller.remove_environment("env-a")

        wait_until(lambda: _column(container, "env-a", "last_state") == GONE, "gone")
        assert consumer.sessions("env-a") is None

    def test_it_keeps_each_environments_latest_session_set(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        consume: Consume,
    ) -> None:
        fake_controller.add_environment("env-a", status="running")
        consumer, _ = consume()
        wait_until(lambda: consumer.sessions("env-a") == (), "seeded")
        assert consumer.sessions("env-x") is None

        created = committed_controller_client.create_headless_session(
            "env-a", HeadlessCreateRequest(cwd="/work/Example")
        )

        wait_until(lambda: bool(consumer.sessions("env-a")), "the new session set")
        [view] = consumer.sessions("env-a") or ()
        assert (view.name, view.mode, view.working) == (created.name, "headless", False)

    def test_the_list_is_applied_before_the_frames_that_came_meanwhile(
        self, committed_app: Flask, consume: Consume
    ) -> None:
        container = committed_app.container
        fake = _ListHook()
        try:
            client_of(container, fake)
            fake.add_environment("env-a", status="running")
            _add(container, Environment(id="env-a", name="Alpha", exempt=False))
            # The environment departs after the list has read it, before the
            # list reaches the consumer: its `gone` frame waits on the stream.
            fake.during_list = lambda: fake.remove_environment("env-a")

            consume()

            wait_until(
                lambda: _column(container, "env-a", "last_state") == GONE, "gone"
            )
        finally:
            fake.close()

    def test_a_dropped_stream_reconnects_and_lists_again(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        consume: Consume,
        fleet_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        fake_controller.add_environment("env-a", status="running")
        _add(container, Environment(id="env-a", name="Alpha", exempt=False))
        consume(backoff=(0.5, 1.0))

        fake_controller.drop_streams()
        # Lost with the stream: only the reconnect's list brings it.
        fake_controller.set_status("env-a", "stopped")

        fleet_log.wait_for(r"Loop fleet raised; restarting in 0.5 s")
        fleet_log.wait_for(r"Fleet stream connected; 1 environments listed", count=2)
        assert _column(container, "env-a", "last_state") == "stopped"
        assert fake_controller.calls.count("GET /environments") == 2

    def test_shutdown_ends_it_and_says_it_is_disconnected(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        consume: Consume,
        fleet_log: LogWaiter,
    ) -> None:
        fake_controller.add_environment("env-a", status="running")
        consumer, coordinator = consume()
        wait_until(lambda: consumer.sessions("env-a") == (), "seeded")

        coordinator.shutdown()

        fleet_log.wait_for(r"Loop fleet ended")
        assert not fleet_log.matching(r"Loop fleet raised.*")
        assert metric_value(FLEET_STREAM_CONNECTED) == 0
        assert consumer.sessions("env-a") is None

    def test_without_a_controller_it_does_not_connect(
        self,
        committed_app: Flask,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        fleet_log: LogWaiter,
    ) -> None:
        supervisor, coordinator = supervise(
            committed_app.container, controller_configured=False
        )
        FleetConsumer(container=committed_app.container, supervisor=supervisor)

        coordinator.fire_startup()

        assert fleet_log.matching(r"No controller configured.*") == [
            "No controller configured (CONTROLLER_URL unset): the jobs and timers "
            "that need one do not start (fleet)"
        ]
        coordinator.shutdown()
        assert fake_controller.calls == []
        assert metric_value(FLEET_STREAM_CONNECTED) == 0


class _ListHook(ServedFakeController):
    """The fake, running `during_list` once after it has read the list it
    answers."""

    def __init__(self) -> None:
        super().__init__(keepalive_seconds=0.2)
        self.during_list: Callable[[], None] | None = None

    def _list_environments(self, request: Request) -> Response:
        response = super()._list_environments(request)
        hook, self.during_list = self.during_list, None
        if hook is not None:
            hook()
        return response
