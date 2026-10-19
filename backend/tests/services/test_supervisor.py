"""The supervisor: the long-lived jobs' runtime (design 2 §7; V07, V18)."""

import itertools
import logging
import re
import threading
import time
from collections.abc import Callable, Generator

import pytest
from flask import Flask
from prometheus_client.metrics import MetricWrapperBase
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import scoped_session
from app.exceptions import InvalidOperationException
from app.models import Environment
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerClient
from app.services.supervisor import (
    JOB_RESTARTS_TOTAL,
    JOB_UP,
    TIMER_RUNS_TOTAL,
    LoopHandle,
    Supervisor,
)
from app.utils.lifecycle_coordinator import LifecycleCoordinator

# The longest a test waits for a thread to get somewhere.
WAIT_SECONDS = 5.0

SUPERVISOR_LOGGER = "app.services.supervisor"


class _Calls:
    """What threads record, in order; a test waits for the count it expects."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self.items: list[object] = []

    def add(self, item: object) -> None:
        with self._condition:
            self.items.append(item)
            self._condition.notify_all()

    def wait_for(self, count: int) -> list[object]:
        with self._condition:
            assert self._condition.wait_for(
                lambda: len(self.items) >= count, WAIT_SECONDS
            ), f"{len(self.items)} of {count} calls: {self.items}"
            return list(self.items)


class _LogWaiter(logging.Handler):
    """The supervisor's log records; a test waits for a message that matches a
    pattern."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self._condition = threading.Condition()
        self._messages: list[str] = []
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        with self._condition:
            self._messages.append(record.getMessage())
            self.records.append(record)
            self._condition.notify_all()

    def wait_for(self, pattern: str, count: int = 1) -> None:
        with self._condition:
            assert self._condition.wait_for(
                lambda: len(self.matching(pattern)) >= count, WAIT_SECONDS
            ), f"no {count} of {pattern!r} in {self._messages}"

    def matching(self, pattern: str) -> list[str]:
        with self._condition:
            return [m for m in self._messages if re.fullmatch(pattern, m)]


@pytest.fixture
def supervisor_log() -> Generator[_LogWaiter]:
    waiter = _LogWaiter()
    logger = logging.getLogger(SUPERVISOR_LOGGER)
    level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(waiter)
    try:
        yield waiter
    finally:
        logger.removeHandler(waiter)
        logger.setLevel(level)


type Supervise = Callable[..., tuple[Supervisor, LifecycleCoordinator]]


@pytest.fixture
def supervise() -> Generator[Supervise]:
    """Builds a supervisor on a lifecycle coordinator of its own, whose
    shutdown the teardown runs if the test did not."""
    coordinators: list[LifecycleCoordinator] = []

    def build(
        container: ServiceContainer,
        *,
        controller_configured: bool = True,
        tick: float = 0.05,
        backoff: tuple[float, float] = (0.05, 0.2),
        budget: int = 20,
    ) -> tuple[Supervisor, LifecycleCoordinator]:
        coordinator = LifecycleCoordinator(graceful_shutdown_timeout=budget)
        coordinators.append(coordinator)
        supervisor = Supervisor(
            container=container,
            lifecycle_coordinator=coordinator,
            controller_configured=controller_configured,
            scheduler_tick_seconds=tick,
            restart_backoff_initial_seconds=backoff[0],
            restart_backoff_max_seconds=backoff[1],
        )
        return supervisor, coordinator

    yield build

    for coordinator in coordinators:
        if not coordinator.is_shutting_down():
            coordinator.shutdown()


def _value(metric: MetricWrapperBase, **labels: str) -> float:
    """A metric's value for these labels; 0 before the first."""
    return next(
        (
            sample.value
            for family in metric.collect()
            for sample in family.samples
            if sample.labels == labels and not sample.name.endswith("_created")
        ),
        0.0,
    )


def _restart_delays(log: _LogWaiter, name: str) -> list[float]:
    pattern = rf"Loop {re.escape(name)} raised; restarting in ([0-9.]+) s"
    return [
        float(match.group(1))
        for message in log.matching(pattern)
        if (match := re.fullmatch(pattern, message))
    ]


def _environment_ids(container: ServiceContainer) -> set[str]:
    with scoped_session(container) as db:
        return set(db.scalars(select(Environment.id)))


class TestSupervisorStartup:
    def test_a_jobs_reconcile_runs_once_before_its_loops(
        self,
        committed_app: Flask,
        supervise: Supervise,
        supervisor_log: _LogWaiter,
    ) -> None:
        supervisor, coordinator = supervise(committed_app.container)
        calls = _Calls()
        release = threading.Event()

        def loop(handle: LoopHandle) -> None:
            calls.add(handle.name)

        def reconcile(db: Session) -> None:
            db.add(Environment(id="reconciled-env", name="Reconciled", exempt=False))
            calls.add("reconcile")
            assert supervisor.start_loop("probe", loop, key="from-reconcile")
            assert release.wait(WAIT_SECONDS)

        supervisor.register_job("probe", needs_controller=False, reconcile=reconcile)
        assert supervisor.start_loop("probe", loop, key="early")

        coordinator.fire_startup()
        calls.wait_for(1)
        supervisor_log.wait_for(r"Reconciling job probe")
        assert supervisor.start_loop("probe", loop, key="during")
        release.set()

        items = calls.wait_for(4)
        assert items[0] == "reconcile"
        assert sorted(map(str, items[1:])) == [
            "probe:during",
            "probe:early",
            "probe:from-reconcile",
        ]
        assert items.count("reconcile") == 1
        # The reconcile's session committed.
        assert "reconciled-env" in _environment_ids(committed_app.container)

    def test_a_reconcile_that_raises_is_logged_and_its_loops_start(
        self, app: Flask, supervise: Supervise, caplog: pytest.LogCaptureFixture
    ) -> None:
        supervisor, coordinator = supervise(app.container)
        calls = _Calls()

        def reconcile(db: Session) -> None:
            raise RuntimeError("the controller is away")

        supervisor.register_job("broken", needs_controller=False, reconcile=reconcile)
        supervisor.start_loop("broken", lambda handle: calls.add(handle.name))

        with caplog.at_level(logging.ERROR, logger=SUPERVISOR_LOGGER):
            coordinator.fire_startup()
            assert calls.wait_for(1) == ["broken"]

        [record] = [r for r in caplog.records if r.name == SUPERVISOR_LOGGER]
        assert record.getMessage() == (
            "Reconcile of job broken raised; its loops start regardless"
        )
        assert record.exc_info is not None

    def test_registration_closes_at_startup(
        self, app: Flask, supervise: Supervise
    ) -> None:
        supervisor, coordinator = supervise(app.container)
        coordinator.fire_startup()

        with pytest.raises(InvalidOperationException, match="register job late"):
            supervisor.register_job("late", needs_controller=False)
        with pytest.raises(InvalidOperationException, match="register timer late"):
            supervisor.register_timer("late", lambda db: None, needs_controller=False)


class TestSupervisorLoops:
    def test_a_key_runs_one_live_loop(
        self, app: Flask, supervise: Supervise, supervisor_log: _LogWaiter
    ) -> None:
        supervisor, coordinator = supervise(app.container)
        supervisor.register_job("keyed", needs_controller=False)
        coordinator.fire_startup()
        calls = _Calls()
        release = threading.Event()

        def loop(handle: LoopHandle) -> None:
            calls.add(handle.name)
            release.wait(WAIT_SECONDS)

        assert supervisor.start_loop("keyed", loop, key=1)
        calls.wait_for(1)
        assert not supervisor.start_loop("keyed", loop, key=1)
        assert supervisor.start_loop("keyed", loop, key=2)
        calls.wait_for(2)
        assert _value(JOB_UP, job="keyed") == 2

        release.set()
        supervisor_log.wait_for(r"Loop keyed:1 ended")
        supervisor_log.wait_for(r"Loop keyed:2 ended")
        assert calls.items == ["keyed:1", "keyed:2"]
        assert _value(JOB_UP, job="keyed") == 0

        # The key is free once its loop has ended.
        assert supervisor.start_loop("keyed", loop, key=1)
        assert calls.wait_for(3)[2] == "keyed:1"

    def test_a_loop_that_returns_ended_on_purpose(
        self, app: Flask, supervise: Supervise, supervisor_log: _LogWaiter
    ) -> None:
        supervisor, coordinator = supervise(app.container)
        supervisor.register_job("once", needs_controller=False)
        coordinator.fire_startup()
        calls = _Calls()

        assert supervisor.start_loop("once", lambda handle: calls.add(handle.name))

        supervisor_log.wait_for(r"Loop once ended")
        assert calls.items == ["once"]
        assert supervisor_log.matching(r"Loop once started") == ["Loop once started"]
        assert _value(JOB_RESTARTS_TOTAL, job="once") == 0
        assert _value(JOB_UP, job="once") == 0

    def test_a_loop_that_raises_restarts_with_doubling_backoff_to_its_cap(
        self, app: Flask, supervise: Supervise, supervisor_log: _LogWaiter
    ) -> None:
        supervisor, coordinator = supervise(app.container, backoff=(0.05, 0.2))
        supervisor.register_job("flaky", needs_controller=False)
        coordinator.fire_startup()
        started: list[float] = []

        def loop(handle: LoopHandle) -> None:
            started.append(time.perf_counter())
            if len(started) <= 5:
                raise RuntimeError(f"drop {len(started)}")

        assert supervisor.start_loop("flaky", loop)

        supervisor_log.wait_for(r"Loop flaky ended")
        delays = _restart_delays(supervisor_log, "flaky")
        assert delays == [0.05, 0.1, 0.2, 0.2, 0.2]
        gaps = [later - earlier for earlier, later in itertools.pairwise(started)]
        assert all(gap >= delay for gap, delay in zip(gaps, delays, strict=True)), gaps
        assert _value(JOB_RESTARTS_TOTAL, job="flaky") == 5
        assert _value(JOB_UP, job="flaky") == 0

    def test_a_run_as_long_as_the_cap_resets_the_backoff(
        self, app: Flask, supervise: Supervise, supervisor_log: _LogWaiter
    ) -> None:
        supervisor, coordinator = supervise(app.container, backoff=(0.05, 0.2))
        supervisor.register_job("steady", needs_controller=False)
        coordinator.fire_startup()
        runs = _Calls()

        def loop(handle: LoopHandle) -> None:
            runs.add(handle.name)
            if len(runs.items) == 3:
                time.sleep(0.25)
            if len(runs.items) <= 3:
                raise RuntimeError("drop")

        assert supervisor.start_loop("steady", loop)

        supervisor_log.wait_for(r"Loop steady ended")
        assert _restart_delays(supervisor_log, "steady") == [0.05, 0.1, 0.05]

    def test_the_backoff_starts_at_one_second(
        self, app: Flask, supervisor_log: _LogWaiter
    ) -> None:
        coordinator = LifecycleCoordinator(graceful_shutdown_timeout=20)
        supervisor = Supervisor(
            container=app.container,
            lifecycle_coordinator=coordinator,
            controller_configured=True,
            scheduler_tick_seconds=10,
        )
        supervisor.register_job("default", needs_controller=False)
        coordinator.fire_startup()
        started: list[float] = []

        def loop(handle: LoopHandle) -> None:
            started.append(time.perf_counter())
            if len(started) == 1:
                raise RuntimeError("drop")

        try:
            assert supervisor.start_loop("default", loop)
            supervisor_log.wait_for(r"Loop default ended")
        finally:
            coordinator.shutdown()

        assert _restart_delays(supervisor_log, "default") == [1.0]
        assert started[1] - started[0] >= 1.0

    def test_the_restart_is_logged_with_its_error(
        self, app: Flask, supervise: Supervise, supervisor_log: _LogWaiter
    ) -> None:
        supervisor, coordinator = supervise(app.container)
        supervisor.register_job("relay", needs_controller=False)
        coordinator.fire_startup()
        runs = _Calls()

        def loop(handle: LoopHandle) -> None:
            runs.add(handle.name)
            if len(runs.items) == 1:
                raise RuntimeError("the stream dropped")

        assert supervisor.start_loop("relay", loop, key=7)
        supervisor_log.wait_for(r"Loop relay:7 ended")

        messages = [
            (record.levelno, record.getMessage(), record.exc_info is not None)
            for record in supervisor_log.records
        ]
        assert messages == [
            (logging.INFO, "Loop relay:7 started", False),
            (logging.ERROR, "Loop relay:7 raised; restarting in 0.05 s", True),
            (logging.INFO, "Loop relay:7 ended", False),
        ]


class TestSupervisorTimers:
    def test_each_timer_runs_every_tick_in_a_session_of_its_own(
        self,
        committed_app: Flask,
        supervise: Supervise,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        supervisor, coordinator = supervise(committed_app.container, tick=0.05)
        failing = _Calls()
        writing = _Calls()

        def failing_timer(db: Session) -> None:
            failing.add("run")
            db.add(
                Environment(
                    id=f"failing-{len(failing.items)}", name="Failing", exempt=False
                )
            )
            db.flush()
            raise RuntimeError("the timer's action failed")

        def writing_timer(db: Session) -> None:
            writing.add("run")
            db.add(
                Environment(
                    id=f"written-{len(writing.items)}", name="Written", exempt=False
                )
            )

        supervisor.register_timer(
            "failing-timer", failing_timer, needs_controller=False
        )
        supervisor.register_timer(
            "writing-timer", writing_timer, needs_controller=False
        )

        with caplog.at_level(logging.ERROR, logger=SUPERVISOR_LOGGER):
            coordinator.fire_startup()
            writing.wait_for(2)
            coordinator.shutdown()

        ids = _environment_ids(committed_app.container)
        assert {"written-1", "written-2"} <= ids
        assert not {id_ for id_ in ids if id_.startswith("failing-")}
        assert _value(TIMER_RUNS_TOTAL, timer="failing-timer", outcome="error") >= 2
        assert _value(TIMER_RUNS_TOTAL, timer="failing-timer", outcome="ok") == 0
        assert _value(TIMER_RUNS_TOTAL, timer="writing-timer", outcome="ok") >= 2
        errors = [r for r in caplog.records if r.name == SUPERVISOR_LOGGER]
        assert errors
        assert {r.getMessage() for r in errors} == {"Timer failing-timer raised"}
        assert all(r.exc_info is not None for r in errors)

    def test_the_scheduler_finishes_the_timer_in_hand_and_stops(
        self, app: Flask, supervise: Supervise
    ) -> None:
        supervisor, coordinator = supervise(app.container)
        calls = _Calls()
        release = threading.Event()
        stopping = threading.Event()

        def timer(db: Session) -> None:
            calls.add("run")
            release.wait(WAIT_SECONDS)
            calls.add("done")

        watching = threading.Event()

        def watch(handle: LoopHandle) -> None:
            watching.set()
            handle.wait(WAIT_SECONDS * 2)
            stopping.set()

        supervisor.register_timer("slow-timer", timer, needs_controller=False)
        supervisor.register_job("watch", needs_controller=False)
        supervisor.start_loop("watch", watch)
        coordinator.fire_startup()
        calls.wait_for(1)
        assert watching.wait(WAIT_SECONDS)

        shutdown = threading.Thread(target=coordinator.shutdown)
        shutdown.start()
        assert stopping.wait(WAIT_SECONDS)
        release.set()
        shutdown.join(WAIT_SECONDS)

        assert not shutdown.is_alive()
        assert calls.items == ["run", "done"]


class TestSupervisorShutdown:
    def test_prepare_shutdown_stops_every_loop_within_the_budget(
        self,
        app: Flask,
        supervise: Supervise,
        supervisor_log: _LogWaiter,
        controller_client: ControllerClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        supervisor, coordinator = supervise(app.container, backoff=(5, 30))
        for job in ("fleet", "sleeper", "failing", "queued"):
            supervisor.register_job(job, needs_controller=False)
        calls = _Calls()
        streaming = threading.Event()

        def fleet(handle: LoopHandle) -> None:
            with (
                controller_client.open_fleet_stream() as stream,
                handle.holding(stream),
            ):
                streaming.set()
                for _frame in stream:
                    pass
            calls.add("fleet")

        def sleeper(handle: LoopHandle) -> None:
            assert handle.wait(60)
            calls.add("sleeper")

        def failing(handle: LoopHandle) -> None:
            raise RuntimeError("drop")

        coordinator.fire_startup()
        supervisor.start_loop("fleet", fleet)
        supervisor.start_loop("sleeper", sleeper)
        supervisor.start_loop("failing", failing)
        assert streaming.wait(WAIT_SECONDS)
        supervisor_log.wait_for(r"Loop failing raised; restarting in 5 s")

        caplog.clear()
        with caplog.at_level(logging.WARNING):
            began = time.perf_counter()
            coordinator.shutdown()
            elapsed = time.perf_counter() - began

        assert elapsed < 3
        assert sorted(map(str, calls.items)) == ["fleet", "sleeper"]
        for name in ("fleet", "sleeper", "failing"):
            assert supervisor_log.matching(rf"Loop {name} ended")
        assert not supervisor_log.matching(r"Loop fleet raised.*")
        assert not [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING
            and r.name in (SUPERVISOR_LOGGER, "app.utils.lifecycle_coordinator")
        ]
        # It accepts no new job.
        assert not supervisor.start_loop("queued", lambda handle: calls.add("late"))

    def test_a_loop_waiting_for_startup_is_dropped_at_shutdown(
        self, app: Flask, supervise: Supervise, supervisor_log: _LogWaiter
    ) -> None:
        supervisor, coordinator = supervise(app.container)
        supervisor.register_job("never", needs_controller=False)
        calls = _Calls()

        assert supervisor.start_loop("never", lambda handle: calls.add("ran"))
        coordinator.shutdown()
        coordinator.fire_startup()

        assert supervisor_log.matching(r"Supervisor stopping 0 loops")
        assert calls.items == []
        assert not supervisor_log.matching(r"Loop never started")

    def test_io_held_after_the_stop_is_closed_at_once(
        self, app: Flask, supervise: Supervise
    ) -> None:
        supervisor, coordinator = supervise(app.container)
        supervisor.register_job("late", needs_controller=False)
        calls = _Calls()

        class _Resource:
            def close(self) -> None:
                calls.add("closed")

        running = threading.Event()

        def loop(handle: LoopHandle) -> None:
            running.set()
            handle.wait(WAIT_SECONDS * 2)
            with handle.holding(_Resource()):
                calls.add("holding")

        coordinator.fire_startup()
        supervisor.start_loop("late", loop)
        assert running.wait(WAIT_SECONDS)
        coordinator.shutdown()

        assert calls.items == ["closed", "holding"]

    def test_the_waiter_gives_up_at_the_budget(
        self, app: Flask, supervise: Supervise, caplog: pytest.LogCaptureFixture
    ) -> None:
        supervisor, coordinator = supervise(app.container, budget=1)
        supervisor.register_job("stuck", needs_controller=False)
        stuck = threading.Event()
        running = threading.Event()

        def loop(handle: LoopHandle) -> None:
            running.set()
            stuck.wait(WAIT_SECONDS * 2)

        coordinator.fire_startup()
        supervisor.start_loop("stuck", loop)
        assert running.wait(WAIT_SECONDS)

        caplog.clear()
        try:
            with caplog.at_level(logging.WARNING):
                began = time.perf_counter()
                coordinator.shutdown()
                elapsed = time.perf_counter() - began
        finally:
            stuck.set()

        assert 0.9 <= elapsed < 3
        warnings = [r.getMessage() for r in caplog.records]
        assert (
            "Supervisor's threads still running at the shutdown deadline: job-stuck"
            in warnings
        )
        assert "Supervisor was not ready within timeout" in warnings


class TestSupervisorWithoutController:
    def test_the_jobs_that_need_a_controller_do_not_start(
        self, app: Flask, supervise: Supervise, supervisor_log: _LogWaiter
    ) -> None:
        supervisor, coordinator = supervise(app.container, controller_configured=False)
        calls = _Calls()
        plain_ticks = _Calls()

        supervisor.register_job(
            "fleet",
            needs_controller=True,
            reconcile=lambda db: calls.add("fleet reconciled"),
        )
        supervisor.register_job(
            "plain",
            needs_controller=False,
            reconcile=lambda db: calls.add("plain reconciled"),
        )
        supervisor.register_timer(
            "shutdown-timer",
            lambda db: calls.add("shutdown-timer ran"),
            needs_controller=True,
        )
        supervisor.register_timer(
            "plain-timer", lambda db: plain_ticks.add("ran"), needs_controller=False
        )
        assert not supervisor.start_loop("fleet", lambda handle: calls.add("fleet"))

        coordinator.fire_startup()
        plain_ticks.wait_for(3)
        assert supervisor.start_loop("plain", lambda handle: calls.add("plain"))
        assert not supervisor.start_loop("fleet", lambda handle: calls.add("fleet"))
        supervisor_log.wait_for(r"Loop plain ended")

        assert calls.items == ["plain reconciled", "plain"]
        assert supervisor_log.matching(r"No controller configured.*") == [
            "No controller configured (CONTROLLER_URL unset): the jobs and timers "
            "that need one do not start (fleet, shutdown-timer)"
        ]

    def test_with_a_controller_they_start_and_nothing_is_said(
        self, app: Flask, supervise: Supervise, supervisor_log: _LogWaiter
    ) -> None:
        supervisor, coordinator = supervise(app.container, controller_configured=True)
        calls = _Calls()

        def reconcile(db: Session) -> None:
            supervisor.start_loop("fleet", lambda handle: calls.add("fleet"))

        supervisor.register_job("fleet", needs_controller=True, reconcile=reconcile)
        supervisor.register_timer(
            "shutdown-timer",
            lambda db: calls.add("shutdown-timer"),
            needs_controller=True,
        )

        coordinator.fire_startup()

        assert set(map(str, calls.wait_for(2))) == {"fleet", "shutdown-timer"}
        assert not supervisor_log.matching(r"No controller configured.*")
