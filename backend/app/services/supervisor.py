"""The supervisor: every long-lived job of the backend, as a thread of its process
(design 2 §6.1, §7).

A job is registered by name before STARTUP. It has a *reconcile*, run once at
STARTUP in a database session of its own before any of the job's loops start,
and *loops*: threads run by job and key (`relay:12`), one live loop per key, each
running until it returns. A loop that raises is restarted with backoff; one that
returns ended on purpose, unless it was asked to run again meanwhile. A *timer*
runs on the scheduler's tick, each run in a database session of its own.

Nothing drains to completion (design 2 §7.3): every job resumes from rows, so at
PREPARE_SHUTDOWN the supervisor tells every loop to stop and closes the I/O it
holds, and its shutdown waiter joins the threads within the coordinator's budget.
"""

import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from prometheus_client import Counter, Gauge
from sqlalchemy.orm import Session

from app.database import scoped_session
from app.exceptions import InvalidOperationException
from app.utils.lifecycle_coordinator import (
    LifecycleCoordinatorProtocol,
    LifecycleEvent,
)

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)

RESTART_BACKOFF_INITIAL_SECONDS = 1.0
RESTART_BACKOFF_MAX_SECONDS = 30.0

JOB_UP = Gauge(
    "pilot_job_up",
    "Loops of the job running now; a loop waiting out its restart's backoff is not",
    ["job"],
)
JOB_RESTARTS_TOTAL = Counter(
    "pilot_job_restarts_total",
    "Restarts of the job's loops after one raised",
    ["job"],
)
TIMER_RUNS_TOTAL = Counter(
    "pilot_timer_runs_total",
    "Runs of each timer, by outcome: ok, or error when the run raised",
    ["timer", "outcome"],
)


class Closeable(Protocol):
    def close(self) -> None: ...


type Reconcile = Callable[[Session], None]
type TimerRun = Callable[[Session], None]
type LoopRun = Callable[[LoopHandle], None]


class LoopHandle:
    """A loop's stop signal, and the I/O the stop closes."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._held: list[Closeable] = []

    @property
    def stopping(self) -> bool:
        """Whether the loop has been told to stop."""
        return self._stop.is_set()

    def wait(self, seconds: float) -> bool:
        """Sleep `seconds`, or until the loop is told to stop; True if it was."""
        return self._stop.wait(seconds)

    @contextmanager
    def holding[T: Closeable](self, resource: T) -> Iterator[T]:
        """Close `resource` if the loop is told to stop while it is held.

        A controller stream's `close()` wakes the read blocked on it, and its
        iteration ends without raising. A resource held after the stop is closed
        at once.
        """
        with self._lock:
            stopped = self._stop.is_set()
            if not stopped:
                self._held.append(resource)
        if stopped:
            resource.close()
        try:
            yield resource
        finally:
            with self._lock:
                self._held = [held for held in self._held if held is not resource]

    def _request_stop(self) -> None:
        with self._lock:
            self._stop.set()
        self._close_held()

    def _close_held(self) -> bool:
        """Close what the run holds now; whether it held anything."""
        with self._lock:
            held, self._held = self._held, []
        for resource in held:
            resource.close()
        return bool(held)


@dataclass
class _Job:
    name: str
    needs_controller: bool
    reconcile: Reconcile | None
    reconciled: bool = False
    # The loops requested before the reconcile ran, by loop name.
    pending: dict[str, LoopRun] = field(default_factory=dict)


@dataclass
class _Timer:
    name: str
    run: TimerRun
    needs_controller: bool


class _Loop:
    def __init__(
        self, job: str, name: str, run: LoopRun, target: Callable[["_Loop"], None]
    ) -> None:
        self.job = job
        self.name = name
        self.run = run
        self.handle = LoopHandle(name)
        # Set by a request to run again; cleared, under the supervisor's lock,
        # as each run starts.
        self.again = False
        self.thread = threading.Thread(
            target=target, args=(self,), name=f"job-{name}", daemon=True
        )


class Supervisor:
    """Runs the long-lived jobs: their reconciles, loops and timers."""

    def __init__(
        self,
        container: "ServiceContainer",
        lifecycle_coordinator: LifecycleCoordinatorProtocol,
        controller_configured: bool,
        scheduler_tick_seconds: float,
        restart_backoff_initial_seconds: float = RESTART_BACKOFF_INITIAL_SECONDS,
        restart_backoff_max_seconds: float = RESTART_BACKOFF_MAX_SECONDS,
    ) -> None:
        """Register with the lifecycle coordinator; nothing runs before STARTUP.

        Args:
            container: Gives each reconcile and timer run its database session
            lifecycle_coordinator: Starts the jobs at STARTUP, stops them at
                PREPARE_SHUTDOWN and waits for them within its budget
            controller_configured: False holds back every job and timer that
                needs the controller
            scheduler_tick_seconds: The wait between two rounds of the timers
            restart_backoff_initial_seconds: A raising loop's first restart delay,
                doubled on every restart
            restart_backoff_max_seconds: The delay's cap. A run that lasted at
                least this long sets the next delay back to the initial one
        """
        self._container = container
        self._controller_configured = controller_configured
        self._tick = scheduler_tick_seconds
        self._backoff_initial = restart_backoff_initial_seconds
        self._backoff_max = restart_backoff_max_seconds
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._started = False
        self._jobs: dict[str, _Job] = {}
        self._timers: list[_Timer] = []
        self._loops: dict[str, _Loop] = {}
        self._threads: list[threading.Thread] = []

        lifecycle_coordinator.register_lifecycle_notification(self._on_lifecycle_event)
        lifecycle_coordinator.register_shutdown_waiter(
            "Supervisor", self._wait_for_jobs
        )

    def register_job(
        self, job: str, *, needs_controller: bool, reconcile: Reconcile | None = None
    ) -> None:
        """Register a job before STARTUP; its reconcile may start its loops.

        Raises:
            InvalidOperationException: If STARTUP has fired
        """
        with self._lock:
            if self._started:
                raise InvalidOperationException(
                    f"register job {job}", "the supervisor has started"
                )
            self._jobs[job] = _Job(job, needs_controller, reconcile)

    def register_timer(
        self, timer: str, run: TimerRun, *, needs_controller: bool
    ) -> None:
        """Register a timer before STARTUP, run on every tick in registration order.

        Raises:
            InvalidOperationException: If STARTUP has fired
        """
        with self._lock:
            if self._started:
                raise InvalidOperationException(
                    f"register timer {timer}", "the supervisor has started"
                )
            self._timers.append(_Timer(timer, run, needs_controller))

    def start_loop(
        self,
        job: str,
        run: LoopRun,
        key: str | int | None = None,
        *,
        again: bool = False,
    ) -> bool:
        """Run `run` as the loop `job:key` (`job` when there is no key).

        Before the job's reconcile has run the loop waits for it, and starts once
        the reconcile at STARTUP is done: the suite and the CLI never fire
        STARTUP, so there it never starts. A request for a name that has a live
        or waiting loop is a no-op: a loop past its last action whose thread has
        not yet ended still counts as live. With `again`, a request for a name
        that has a live loop has that loop run its run once more after the
        current run returns, so a run starts after every such request.

        Returns:
            Whether this request started the loop, set it waiting, or set a
            live loop to run again; False for a no-op, at and after
            PREPARE_SHUTDOWN, and for a job that needs the controller when none
            is configured
        """
        name = job if key is None else f"{job}:{key}"
        with self._lock:
            entry = self._jobs[job]
            if self._stop.is_set() or (
                entry.needs_controller and not self._controller_configured
            ):
                return False
            live = self._loops.get(name)
            if live is not None and again:
                live.again = True
                return True
            if live is not None or name in entry.pending:
                return False
            if entry.reconciled:
                self._spawn(entry, name, run)
            else:
                entry.pending[name] = run
            return True

    def interrupt_loop(self, job: str, key: str | int | None = None) -> bool:
        """Close the I/O the live loop `job:key`'s run holds, without stopping
        the loop: a controller stream's iteration ends without raising, and the
        run carries on from there.

        Returns:
            Whether the loop is live and its run held I/O, which is now closed
        """
        name = job if key is None else f"{job}:{key}"
        with self._lock:
            loop = self._loops.get(name)
        return loop is not None and loop.handle._close_held()

    def _spawn(self, job: _Job, name: str, run: LoopRun) -> None:
        # Under self._lock.
        loop = _Loop(job.name, name, run, self._run_loop)
        self._loops[name] = loop
        loop.thread.start()

    def _run_loop(self, loop: _Loop) -> None:
        logger.info("Loop %s started", loop.name)
        delay = self._backoff_initial
        try:
            while True:
                with self._lock:
                    loop.again = False
                began = time.perf_counter()
                failure: Exception | None = None
                JOB_UP.labels(job=loop.job).inc()
                try:
                    loop.run(loop.handle)
                except Exception as error:
                    failure = error
                finally:
                    JOB_UP.labels(job=loop.job).dec()
                if failure is None:
                    # The check and the release are one step under the lock:
                    # a request after it starts a loop of its own.
                    with self._lock:
                        if not loop.again or loop.handle.stopping:
                            del self._loops[loop.name]
                            return
                    logger.info("Loop %s runs again", loop.name)
                    continue
                if loop.handle.stopping:
                    logger.error(
                        "Loop %s raised while stopping", loop.name, exc_info=failure
                    )
                    return
                if time.perf_counter() - began >= self._backoff_max:
                    delay = self._backoff_initial
                logger.error(
                    "Loop %s raised; restarting in %g s",
                    loop.name,
                    delay,
                    exc_info=failure,
                )
                if loop.handle.wait(delay):
                    return
                JOB_RESTARTS_TOTAL.labels(job=loop.job).inc()
                delay = min(delay * 2, self._backoff_max)
        finally:
            with self._lock:
                if self._loops.get(loop.name) is loop:
                    del self._loops[loop.name]
            logger.info("Loop %s ended", loop.name)

    def _on_lifecycle_event(self, event: LifecycleEvent) -> None:
        match event:
            case LifecycleEvent.STARTUP:
                self._startup()
            case LifecycleEvent.PREPARE_SHUTDOWN:
                self._stop_jobs()

    def _startup(self) -> None:
        # The reconciles run off the coordinator's thread: create_app() fires
        # STARTUP, and the server serves only once it returns.
        with self._lock:
            self._started = True
            for target, name in (
                (self._reconcile_jobs, "supervisor-startup"),
                (self._schedule, "supervisor-scheduler"),
            ):
                thread = threading.Thread(target=target, name=name, daemon=True)
                self._threads.append(thread)
                thread.start()
        if not self._controller_configured:
            held = [job.name for job in self._jobs.values() if job.needs_controller]
            held += [timer.name for timer in self._timers if timer.needs_controller]
            logger.info(
                "No controller configured (CONTROLLER_URL unset): the jobs and "
                "timers that need one do not start (%s)",
                ", ".join(held) or "none registered",
            )

    def _reconcile_jobs(self) -> None:
        for job in self._jobs.values():
            if self._stop.is_set():
                return
            if job.needs_controller and not self._controller_configured:
                continue
            reconcile = job.reconcile
            if reconcile is not None:
                logger.info("Reconciling job %s", job.name)
                try:
                    with scoped_session(self._container) as db:
                        reconcile(db)
                except Exception:
                    logger.exception(
                        "Reconcile of job %s raised; its loops start regardless",
                        job.name,
                    )
            with self._lock:
                job.reconciled = True
                for name, run in job.pending.items():
                    self._spawn(job, name, run)
                job.pending.clear()

    def _schedule(self) -> None:
        timers = [
            timer
            for timer in self._timers
            if self._controller_configured or not timer.needs_controller
        ]
        while not self._stop.is_set():
            for timer in timers:
                if self._stop.is_set():
                    return
                try:
                    with scoped_session(self._container) as db:
                        timer.run(db)
                except Exception:
                    TIMER_RUNS_TOTAL.labels(timer=timer.name, outcome="error").inc()
                    logger.exception("Timer %s raised", timer.name)
                else:
                    TIMER_RUNS_TOTAL.labels(timer=timer.name, outcome="ok").inc()
            self._stop.wait(self._tick)

    def _stop_jobs(self) -> None:
        with self._lock:
            self._stop.set()
            loops = list(self._loops.values())
            for job in self._jobs.values():
                job.pending.clear()
        logger.info("Supervisor stopping %d loops", len(loops))
        for loop in loops:
            loop.handle._request_stop()

    def _wait_for_jobs(self, timeout: float) -> bool:
        deadline = time.perf_counter() + timeout
        with self._lock:
            threads = self._threads + [loop.thread for loop in self._loops.values()]
        for thread in threads:
            thread.join(max(0.0, deadline - time.perf_counter()))
        running = [thread.name for thread in threads if thread.is_alive()]
        if running:
            logger.warning(
                "Supervisor's threads still running at the shutdown deadline: %s",
                ", ".join(running),
            )
        return not running
