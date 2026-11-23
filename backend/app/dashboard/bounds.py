"""The bounds every statement of the dashboard's engine runs under (F154.5).

- **A read-only transaction under a timeout**, of the engine's own: a read
  ends the caller's transaction first, so that it waits for its slot
  holding no connection of the database's, then opens one, read only, and
  rolls it back at its end. The timeout bounds the read whole, its wait for
  a slot and every statement it runs: each statement's `statement_timeout`
  is set, as it is sent, to what is left of it. The reads of one answer
  share one deadline, an entry's and the answer's own, so that an answer
  behind the proxies in front of `/api/` is given or refused before they
  stop waiting (nginx's `proxy_read_timeout`, 60 s). Both are set per
  transaction, `SET LOCAL` as `configure_engine()` sets JIT off
  (app/startup.py): the stages reach PostgreSQL through a pooler in
  transaction mode. In the suite the transaction is a savepoint of the
  test's, and its rollback restores the test's own settings.
- **`work_mem` is never raised**: every statement runs at the cluster's own,
  4MB in production, since past an instance's memory limit there is no
  refusal to give, PostgreSQL restarting and every app's connections
  dropping.
- **A refusal with a reason**: a statement past the timeout, PostgreSQL's
  57014, and one the cluster ended at its `temp_file_limit`, 53400, are each
  refused as what they are (`QueryRefusedException`).
- **Statements at once**: the engine's reads hold a slot each, at most
  `at_once` of them, fewer than the app's pool holds, so that a burst from
  several tabs and tools leaves the pool to the rest of the app; and since
  the cluster's limit on temporary files is per process, the slots also cap
  the disk a burst can take. A read that finds no slot free within the
  timeout is refused.
"""

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.exceptions import ConfigurationError, QueryRefusedException

TIMEOUT = "57014"
"""PostgreSQL's code for a statement cancelled, at its timeout among others."""

TEMP_FILE_LIMIT = "53400"
"""PostgreSQL's code for a limit of its configuration exceeded, the one on
temporary files among them."""


class Bounds:
    """The engine's bounds, the process's one: its timeout, and its slots,
    `at_once` of them, fewer than `pool`, the connections the app's pool
    holds."""

    def __init__(self, timeout_seconds: float, at_once: int, pool: int) -> None:
        if at_once >= pool:
            raise ConfigurationError(
                f"DASHBOARD_STATEMENTS_AT_ONCE is {at_once}, and the app's pool "
                f"holds {pool} connections: the engine's statements at once "
                "must leave the pool some"
            )
        self.timeout_seconds = timeout_seconds
        self.at_once = at_once
        self._slots = threading.BoundedSemaphore(at_once)

    def deadline(self) -> float:
        """The end of the timeout from now, on `time.monotonic()`'s clock,
        for the reads of one answer to share."""
        return time.monotonic() + self.timeout_seconds

    @contextmanager
    def read(self, db: Session, deadline: float | None = None) -> Iterator[Session]:
        """`db` in a read-only transaction of its own, once a slot is free,
        for the engine's statements, the wait and the statements together
        before `deadline`, the timeout from now where none is given; the
        caller's transaction committed first, so a caller with writes of its
        own makes them after. `QueryRefusedException` where the deadline had
        passed, no slot freed, or a statement ran past what was left of the
        deadline or the limit on temporary files."""
        db.commit()
        if deadline is None:
            deadline = self.deadline()
        left = deadline - time.monotonic()
        if left <= 0:
            raise self._timeout()
        if not self._slots.acquire(timeout=left):
            raise QueryRefusedException(
                "busy",
                f"the engine already runs its {self.at_once} statements at once "
                f"and none ended within {_seconds(self.timeout_seconds)}",
            )
        try:
            db.execute(text("SET TRANSACTION READ ONLY"))
            connection = db.connection()

            def bounded(
                conn: Connection,
                cursor: Any,
                statement: str,
                parameters: Any,
                context: Any,
                executemany: bool,
            ) -> None:
                # A statement_timeout of 0 is none at all: one sent with
                # nothing left of the read gets 1 ms.
                left = round((deadline - time.monotonic()) * 1000)
                cursor.execute(f"SET LOCAL statement_timeout = {max(left, 1)}")

            event.listen(connection, "before_cursor_execute", bounded)
            try:
                yield db
            except DBAPIError as error:
                refusal = self._refusal(error)
                if refusal is None:
                    raise
                raise refusal from error
            finally:
                event.remove(connection, "before_cursor_execute", bounded)
        finally:
            db.rollback()
            self._slots.release()

    def _refusal(self, error: DBAPIError) -> QueryRefusedException | None:
        code = getattr(error.orig, "sqlstate", None)
        if code == TIMEOUT:
            return self._timeout()
        if code == TEMP_FILE_LIMIT:
            return QueryRefusedException(
                "temp_file_limit",
                "a statement needed more temporary disk than the database "
                "allows one: a shorter time range or a narrower scope reads less",
            )
        return None

    def _timeout(self) -> QueryRefusedException:
        return QueryRefusedException(
            "timeout",
            "its read ran past the engine's timeout of "
            f"{_seconds(self.timeout_seconds)}: a shorter time range or a "
            "narrower scope reads less",
        )


def _seconds(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole} s" if whole == seconds else f"{seconds:g} s"
