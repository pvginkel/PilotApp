"""What a test on a committed database waits on: a transaction run in a
thread of its own, and the connections waiting on a lock."""

import threading
from collections.abc import Callable
from typing import Any

from sqlalchemy import text

from app.database import scoped_session
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
    """The connections of the app's database waiting on a lock."""
    with scoped_session(container) as db:
        waits: int = db.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE datname = current_database() AND wait_event_type = 'Lock'"
            )
        )
        return waits
