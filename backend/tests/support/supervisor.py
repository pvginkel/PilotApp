"""What a test of the long-lived jobs waits on: their threads' log lines, their
metrics, and conditions they bring about."""

import logging
import re
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager

from prometheus_client.metrics import MetricWrapperBase

from app.services.supervisor import Supervisor
from app.utils.lifecycle_coordinator import LifecycleCoordinator

# The longest a test waits for a thread to get somewhere.
WAIT_SECONDS = 5.0

type Supervise = Callable[..., tuple[Supervisor, LifecycleCoordinator]]
"""The `supervise` fixture: builds a supervisor on a lifecycle coordinator of
its own."""


class LogWaiter(logging.Handler):
    """A logger's records; a test waits for a message that matches a pattern."""

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


@contextmanager
def listening(*loggers: str) -> Generator[LogWaiter]:
    """A LogWaiter on these loggers, at INFO, while the block runs."""
    waiter = LogWaiter()
    levels = []
    for name in loggers:
        logger = logging.getLogger(name)
        levels.append((logger, logger.level))
        logger.setLevel(logging.INFO)
        logger.addHandler(waiter)
    try:
        yield waiter
    finally:
        for logger, level in levels:
            logger.removeHandler(waiter)
            logger.setLevel(level)


def metric_value(metric: MetricWrapperBase, **labels: str) -> float:
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


def wait_until(condition: Callable[[], bool], what: str) -> None:
    """Wait until `condition()` holds, which another thread brings about."""
    deadline = time.perf_counter() + WAIT_SECONDS
    while not condition():
        assert time.perf_counter() < deadline, f"not {what} in {WAIT_SECONDS} s"
        time.sleep(0.01)
