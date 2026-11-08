"""The pool guard: where a thread checks out a second connection of a pool
while it holds one, the stacks of both checkouts.

A thread that does waits on the pool for a connection while it keeps one of
it. As many such threads at once as the pool holds wait on each other until
the pool's timeout: slice 038's member turns did, five at once on a
Playwright backend's 2 + 3, and showed only as random 10 s reds in the
frontend suite. The guard fails a test on the class where it happens, with
both stacks: a backend test (tests/conftest.py), and a Playwright spec, whose
backend runs it under POOL_GUARD and hands its nestings to the spec's
teardown (app/api/testing_pool_guard.py).

Only a pool that bounds its connections, a `QueuePool`, is watched: a
`NullPool` opens one per checkout and never makes a thread wait.

In the backend suite, a test on `session` hands every caller its one
connection, so the guard sees the tests on `committed_app`, whose sessions
are real. There a nesting is the app's where the two checkouts' stacks part
in the app's code, `app/` or `pilot_mcp/`: a function of it that holds the
one while it takes the other. Where they part in a test, the test holds the
one itself, as a row lock's test does to stand in for another process, and
the guard lets it be. In a Playwright backend no test holds a connection,
and every nesting is the app's: wherever the stacks part, and where they
share no frame, as a request's do whose session a hook before its view
checked out. One the app may make names the function they part in in
`EXEMPT`, with the reason it cannot fill the pool.
"""

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import event
from sqlalchemy.pool import Pool, QueuePool

from app.utils.stacks import APP, Frame, backend_stack, format_stack

# A function, as `<path from backend/>:<qualname>`, that may hold one
# connection while it takes another, and why that cannot fill the pool.
EXEMPT: dict[str, str] = {
    "app/services/store_updater.py:StoreUpdater._reset": (
        "The reset holds its turn's connection while its phases and the "
        "store's reset take theirs, on the job store-update's one loop: one "
        "thread of a process at most waits for a second, on whatever "
        "connection another thread gives back."
    ),
}


def _parting(held: tuple[Frame, ...], taken: tuple[Frame, ...]) -> Frame | None:
    """The frame the two stacks part in: the last function they share, at
    whichever line; None when they share none."""
    parting = None
    for one, other in zip(held, taken, strict=False):
        if (one[0], one[2]) != (other[0], other[2]):
            break
        parting = other
        if one[1] != other[1]:
            break
    return parting


@dataclass(frozen=True)
class _Hold:
    pool: Pool
    thread: int
    stack: tuple[Frame, ...]


@dataclass(frozen=True)
class Nesting:
    """A thread's second checkout of a pool while it held a connection of
    it."""

    thread: str
    held: tuple[Frame, ...]
    taken: tuple[Frame, ...]

    def describe(self) -> str:
        return (
            f"Thread {self.thread} checked out a second connection of a pool "
            f"while it held one.\n"
            f"  The connection it held, checked out at:\n{format_stack(self.held)}\n"
            f"  The second, checked out at:\n{format_stack(self.taken)}"
        )


class PoolGuard:
    """Every `QueuePool`'s checkouts and checkins, from `install()` on; the
    nestings found since the last `drain()` whose stacks part in the code
    under `watched`, the paths from backend/ it starts with, and in no
    function `exempt` names. With `watched` None, every nesting but the
    exempt, a backend's own process's."""

    def __init__(
        self,
        watched: tuple[str, ...] | None = APP,
        exempt: Mapping[str, str] = EXEMPT,
    ) -> None:
        self._watched = watched
        self._exempt = exempt
        self._lock = threading.Lock()
        self._holds: dict[Any, _Hold] = {}
        self._nestings: list[Nesting] = []
        self.installed = False

    def install(self) -> None:
        event.listen(Pool, "checkout", self._checkout)
        event.listen(Pool, "checkin", self._checkin)
        event.listen(Pool, "detach", self._checkin)
        self.installed = True

    def uninstall(self) -> None:
        event.remove(Pool, "checkout", self._checkout)
        event.remove(Pool, "checkin", self._checkin)
        event.remove(Pool, "detach", self._checkin)
        self.installed = False

    def drain(self) -> list[Nesting]:
        with self._lock:
            nestings, self._nestings = self._nestings, []
        return nestings

    def _checkout(self, _dbapi_connection: Any, record: Any, proxy: Any) -> None:
        pool = proxy._pool
        if not isinstance(pool, QueuePool):
            return
        thread = threading.get_ident()
        stack = backend_stack()
        with self._lock:
            held = next(
                (
                    hold
                    for other, hold in self._holds.items()
                    if other is not record
                    and hold.pool is pool
                    and hold.thread == thread
                ),
                None,
            )
            self._holds[record] = _Hold(pool, thread, stack)
            if held is not None and self._faults(held.stack, stack):
                self._nestings.append(
                    Nesting(threading.current_thread().name, held.stack, stack)
                )

    def _checkin(self, _dbapi_connection: Any, record: Any) -> None:
        with self._lock:
            self._holds.pop(record, None)

    def _faults(self, held: tuple[Frame, ...], taken: tuple[Frame, ...]) -> bool:
        parting = _parting(held, taken)
        if parting is None:
            return self._watched is None
        return (
            self._watched is None or parting[0].startswith(self._watched)
        ) and f"{parting[0]}:{parting[2]}" not in self._exempt
