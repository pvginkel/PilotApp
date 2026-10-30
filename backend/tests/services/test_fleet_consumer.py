"""The fleet consumer: the Environment rows kept current from the fleet stream
(design 2 §13.1; F73.1), the stream down the controller unreachable (§13.4),
and the usage readings recorded from it (design 4 §6; DB 274). Each test runs it as the supervisor does, on a database of its own,
against the fake controller."""

from collections.abc import Callable, Generator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flask import Flask
from sqlalchemy import select
from werkzeug.wrappers import Request, Response

from app.database import scoped_session
from app.models import Environment, UsageReading, WindowShare
from app.models.reference import UsageWindow
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerClient, HeadlessCreateRequest
from app.services.fleet_consumer import (
    FLEET_STREAM_CONNECTED,
    GONE,
    FleetConsumer,
)
from app.services.usage_service import READING_AGE
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
USAGE_LOGGER = "app.services.usage_service"

TAKEN_AT = datetime(2026, 10, 8, 23, 40, tzinfo=UTC)
WEEK_RESETS_AT = datetime(2026, 10, 9, 7, tzinfo=UTC)


@pytest.fixture
def fleet_log() -> Generator[LogWaiter]:
    with listening(CONSUMER_LOGGER, SUPERVISOR_LOGGER, USAGE_LOGGER) as waiter:
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
            container=committed_app.container,
            supervisor=supervisor,
            controller_outage=committed_app.container.controller_outage(),
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
            "started_pod_at": row.started_pod_at,
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

    @pytest.mark.parametrize("report", ["stopped", "gone"])
    def test_a_report_leaves_the_claim_as_it_is(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        consume: Consume,
        report: str,
    ) -> None:
        # D12: the claim ends at the tick's or a start's check of the pod, and
        # the consumer writes none of the starter's columns.
        container = committed_app.container
        fake_controller.add_environment("env-a", status="running")
        claim = {
            "server_started_at": datetime.now(UTC) - timedelta(hours=1),
            "started_pod_at": fake_controller.environment("env-a").pod_started_at,
            "stop_due_at": datetime.now(UTC) + timedelta(minutes=5),
        }
        _add(container, Environment(id="env-a", name="Alpha", exempt=False, **claim))
        consume()

        if report == "stopped":
            fake_controller.set_status("env-a", "stopped")
        else:
            fake_controller.remove_environment("env-a")

        wait_until(lambda: _column(container, "env-a", "last_state") == report, report)
        columns = _columns(container, "env-a")
        assert columns is not None
        assert {column: columns[column] for column in claim} == claim

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

    def test_it_keeps_each_environments_latest_state(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        consume: Consume,
    ) -> None:
        fake_controller.add_environment("env-a", status="running")
        consumer, _ = consume()
        listed = consumer.environment("env-a")
        assert listed is not None and listed.status == "running"
        assert listed.pod is not None and listed.pod.restart_count == 0
        assert consumer.environment("env-x") is None

        fake_controller.restart("env-a")

        def restarts() -> int | None:
            environment = consumer.environment("env-a")
            if environment is None or environment.pod is None:
                return None
            return environment.pod.restart_count

        wait_until(lambda: restarts() == 1, "the restart's state frame")

        fake_controller.remove_environment("env-a")

        wait_until(lambda: consumer.environment("env-a") is None, "gone")

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
        # The log line comes before the stream's `fleet_stream_up()`.
        wait_until(
            lambda: not container.controller_outage().holds,
            "the outage off at the reconnect",
        )

    @pytest.mark.parametrize("answer", ["none", "ingress"])
    def test_the_stream_down_holds_the_outage_on_until_it_reconnects(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        consume: Consume,
        fleet_log: LogWaiter,
        answer: str,
    ) -> None:
        outage = committed_app.container.controller_outage()
        consume(backoff=(0.1, 0.2))
        assert not outage.holds

        fake_controller.outage(answer=answer)

        fleet_log.wait_for(r"Loop fleet raised; restarting in .*", count=2)
        assert outage.holds
        # The probe's answer turns nothing off while the stream is down.
        outage.probe_answered()
        assert outage.holds
        fake_controller.outage(on=False)
        wait_until(lambda: not outage.holds, "the outage off at the reconnect")
        assert _connected()

    def test_a_stream_that_cannot_open_turns_the_outage_on(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        fleet_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        outage = container.controller_outage()
        fake_controller.outage()
        supervisor, coordinator = supervise(container, backoff=(0.1, 0.2))
        FleetConsumer(
            container=container, supervisor=supervisor, controller_outage=outage
        )

        coordinator.fire_startup()

        wait_until(lambda: outage.holds, "the outage on")
        fake_controller.outage(on=False)
        wait_until(_connected, "connected")
        wait_until(lambda: not outage.holds, "the outage off at the connect")

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
        assert not committed_app.container.controller_outage().holds
        assert consumer.sessions("env-a") is None
        assert consumer.environment("env-a") is None

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
        FleetConsumer(
            container=committed_app.container,
            supervisor=supervisor,
            controller_outage=committed_app.container.controller_outage(),
        )

        coordinator.fire_startup()

        assert fleet_log.matching(r"No controller configured.*") == [
            "No controller configured (CONTROLLER_URL unset): the jobs and timers "
            "that need one do not start (fleet)"
        ]
        coordinator.shutdown()
        assert fake_controller.calls == []
        assert metric_value(FLEET_STREAM_CONNECTED) == 0


type Recorded = tuple[datetime, bool, dict[UsageWindow, float]]


def _readings(container: ServiceContainer) -> list[Recorded]:
    """The Usage Readings recorded, oldest first: when taken, whether stale,
    and each window's share."""
    with scoped_session(container) as db:
        readings = db.scalars(select(UsageReading).order_by(UsageReading.id)).all()
        shares = db.scalars(select(WindowShare)).all()
        return [
            (
                reading.taken_at,
                reading.stale,
                {s.window_code: s.share for s in shares if s.reading_id == reading.id},
            )
            for reading in readings
        ]


def _recorded(container: ServiceContainer, count: int) -> list[Recorded]:
    """Wait until `count` readings are recorded; the readings."""
    wait_until(lambda: len(_readings(container)) >= count, f"{count} recorded")
    return _readings(container)


class TestUsageReadings:
    def test_the_connects_seed_is_recorded_and_the_route_is_not_read(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        consume: Consume,
    ) -> None:
        fake_controller.usage(five_hour=0.08, seven_day=0.77, taken_at=TAKEN_AT)

        consume()

        assert _recorded(committed_app.container, 1) == [
            (
                TAKEN_AT,
                False,
                {UsageWindow.FIVE_HOUR: 0.08, UsageWindow.SEVEN_DAY: 0.77},
            )
        ]
        assert "GET /usage" not in fake_controller.calls
        assert metric_value(READING_AGE) == 0

    def test_each_change_is_recorded_and_its_age_read(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        consume: Consume,
    ) -> None:
        container = committed_app.container
        consume()
        week = UsageWindow.SEVEN_DAY

        fake_controller.usage(seven_day=0.9, taken_at=TAKEN_AT)
        _recorded(container, 1)
        # A poll that moves only `takenAt` pushes nothing.
        fake_controller.usage(seven_day=0.9, taken_at=TAKEN_AT + timedelta(minutes=10))
        fake_controller.usage_stale("token-expired")
        _recorded(container, 2)
        stale_age = metric_value(READING_AGE)
        fake_controller.usage(seven_day=0.85, taken_at=TAKEN_AT + timedelta(minutes=20))

        assert _recorded(container, 3) == [
            (TAKEN_AT, False, {week: 0.9}),
            (TAKEN_AT + timedelta(minutes=10), True, {week: 0.9}),
            (TAKEN_AT + timedelta(minutes=20), False, {week: 0.85}),
        ]
        assert (
            stale_age
            >= (datetime.now(UTC) - (TAKEN_AT + timedelta(minutes=10))).total_seconds()
            - 60
        )
        wait_until(lambda: metric_value(READING_AGE) == 0, "fresh again")

    def test_a_restarted_controllers_seed_leaves_the_latest_as_it_is(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        consume: Consume,
        fleet_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        week = UsageWindow.SEVEN_DAY
        fake_controller.usage(seven_day=0.9, taken_at=TAKEN_AT)
        consume(backoff=(0.1, 0.2))
        _recorded(container, 1)

        fake_controller.controller_restarted()

        fleet_log.wait_for(r"Fleet stream connected.*", count=2)
        fleet_log.wait_for(
            r"Usage reading without figures \(no-reading-yet\): "
            r"the latest recorded stands"
        )
        # Its first answer, the figures recorded already, is not recorded.
        fake_controller.usage(seven_day=0.9, taken_at=TAKEN_AT + timedelta(hours=1))
        fleet_log.wait_for(r"Usage reading taken at .*: unchanged since .*")
        fake_controller.usage(seven_day=0.95, taken_at=TAKEN_AT + timedelta(hours=2))

        assert _recorded(container, 2) == [
            (TAKEN_AT, False, {week: 0.9}),
            (TAKEN_AT + timedelta(hours=2), False, {week: 0.95}),
        ]

    def test_a_reconnects_seed_is_compared_with_the_last_recorded(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        consume: Consume,
        fleet_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        week = UsageWindow.SEVEN_DAY
        fake_controller.usage(seven_day=0.5, taken_at=TAKEN_AT)
        consume(backoff=(0.5, 1.0))
        _recorded(container, 1)

        # Changed while the stream is down: the reconnect's seed brings it.
        fake_controller.drop_streams()
        fake_controller.usage(seven_day=0.6, taken_at=TAKEN_AT + timedelta(minutes=10))
        missed = _recorded(container, 2)
        # Unchanged since: the next reconnect's seed records nothing.
        fake_controller.drop_streams()
        fleet_log.wait_for(r"Usage reading taken at .*: unchanged since .*")
        fake_controller.usage(seven_day=0.7, taken_at=TAKEN_AT + timedelta(minutes=20))

        assert missed[1] == (TAKEN_AT + timedelta(minutes=10), False, {week: 0.6})
        assert [shares[week] for _, _, shares in _recorded(container, 3)] == [
            0.5,
            0.6,
            0.7,
        ]

    @pytest.mark.parametrize(
        ("last_share", "recorded_shares"),
        [(0.5, [0.5, 0.6]), (0.4, [0.4, 0.5, 0.6])],
        ids=["the-same-figures", "other-figures"],
    )
    def test_after_a_restart_the_seed_is_compared_with_the_last_recorded(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        consume: Consume,
        fleet_log: LogWaiter,
        last_share: float,
        recorded_shares: list[float],
    ) -> None:
        # The process before this one recorded the week at `last_share`.
        container = committed_app.container
        with scoped_session(container) as db:
            reading = UsageReading(taken_at=TAKEN_AT, received_at=TAKEN_AT, stale=False)
            db.add(reading)
            db.flush()
            db.add(
                WindowShare(
                    reading_id=reading.id,
                    window_code=UsageWindow.SEVEN_DAY,
                    share=last_share,
                    resets_at=WEEK_RESETS_AT,
                )
            )
        fake_controller.usage(
            seven_day=0.5,
            seven_day_resets_at=WEEK_RESETS_AT,
            taken_at=TAKEN_AT + timedelta(hours=1),
        )

        consume()
        fleet_log.wait_for(r"Usage reading (\d+ recorded|taken at .*: unchanged).*")
        fake_controller.usage(seven_day=0.6, taken_at=TAKEN_AT + timedelta(hours=2))

        recorded = _recorded(container, len(recorded_shares))
        assert [shares[UsageWindow.SEVEN_DAY] for _, _, shares in recorded] == (
            recorded_shares
        )


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
