"""What a test on a committed database waits on: a transaction run in a
thread of its own, the connections waiting on a lock, and the app's pool."""

import threading
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from typing import Any

from sqlalchemy import Engine, text

from app.services.container import ServiceContainer
from tests.support.supervisor import WAIT_SECONDS


class Outcome:
    """`run`, on a thread of its own from the outcome's construction."""

    def __init__(self, run: Callable[[], Any]) -> None:
        self._value: Any = None
        self._error: BaseException | None = None
        self.thread = threading.Thread(target=self._run, args=(run,), daemon=True)
        self.thread.start()

    def _run(self, run: Callable[[], Any]) -> None:
        try:
            self._value = run()
        except BaseException as error:
            self._error = error

    def result(self) -> Any:
        """What `run` returned, once it has; what it raised, raised again."""
        self.thread.join(WAIT_SECONDS)
        assert not self.thread.is_alive(), "the thread did not finish"
        if self._error is not None:
            raise self._error
        return self._value


def in_thread(run: Callable[[], Any]) -> Outcome:
    return Outcome(run)


def lock_waits(container: ServiceContainer) -> int:
    """The connections of the app's database waiting on a lock.

    Read on a session, a connection and a transaction of its own, not the
    container's `db_session`, so that a test can poll it from inside its own
    `scoped_session`, whose lock a nested `scoped_session` would commit away.
    """
    with container.session_maker()() as db:
        waits: int = db.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE datname = current_database() AND wait_event_type = 'Lock'"
            )
        )
        return waits


def pool_capacity(container: ServiceContainer) -> int:
    """The most connections the app's pool hands out at once."""
    config = container.config()
    return config.db_pool_size + config.db_pool_max_overflow


@contextmanager
def holding_connections(container: ServiceContainer, count: int) -> Iterator[None]:
    """`count` of the app's pooled connections checked out, idle, until the
    block ends."""
    engine: Engine = container.session_maker().kw["bind"]
    with ExitStack() as held:
        for _ in range(count):
            held.enter_context(engine.connect())
        yield
