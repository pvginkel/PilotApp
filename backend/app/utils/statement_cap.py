"""The statement cap: a statement the app sends longer than its bound, with
its text, its length and where it was sent.

Slice 036's reading of what Pilot is working on sent statements of 5 to 15
KB to every timeline, head and project-list read, which PostgreSQL took 7 to
17 ms to plan and under 1 ms to run, and which showed only as a slower
frontend suite (P-243). The cap fails a test on any statement over
`CAP` characters: a backend test (tests/conftest.py), and a Playwright spec,
whose backend runs it under STATEMENT_CAP and hands what it kept to the
spec's teardown (app/api/testing_statement_cap.py).

A statement's length is its compiled text's, before SQLAlchemy fills an
expanding IN list with its ids or an insert with its batch of rows, which
lengthen the text sent by their count; a statement sent as text, through
`exec_driver_sql`, is measured as sent. A statement kept whole over `CAP`
carries its own bound beside it in the code, as the execution option
`max_statement_length`, and fails above that bound: `_holding()` in
app/services/working_on.py does.

In the backend suite, a statement is the app's where the innermost frame of
the backend's own code that sends it is in `app/` or `pilot_mcp/`. One a
test sends itself, a migration test's read of the schema among them, is the
test's, and the cap lets it be. In a Playwright backend no test sends a
statement, and every statement is the app's.
"""

import threading
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, event

from app.utils.stacks import APP, Frame, backend_stack, format_stack

CAP = 2_000


@dataclass(frozen=True)
class LongStatement:
    """A statement sent over its bound."""

    text: str
    bound: int
    sent: tuple[Frame, ...]

    def describe(self) -> str:
        return (
            f"A statement of {len(self.text):,} characters, over its bound of "
            f"{self.bound:,}, sent at:\n{format_stack(self.sent)}\n{self.text}"
        )


class StatementCap:
    """Every statement each engine sends, from `install()` on; those over
    their bound since the last `drain()` whose innermost frame of the
    backend's own code is under `watched`, the paths from backend/ it starts
    with. With `watched` None, every statement over its bound, a backend's
    own process's."""

    def __init__(self, watched: tuple[str, ...] | None = APP) -> None:
        self._watched = watched
        self._lock = threading.Lock()
        self._kept: list[LongStatement] = []
        self.installed = False

    def install(self) -> None:
        event.listen(Engine, "before_cursor_execute", self._before_cursor_execute)
        self.installed = True

    def uninstall(self) -> None:
        event.remove(Engine, "before_cursor_execute", self._before_cursor_execute)
        self.installed = False

    def drain(self) -> list[LongStatement]:
        with self._lock:
            kept, self._kept = self._kept, []
        return kept

    def _before_cursor_execute(
        self,
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        context: Any,
        _executemany: bool,
    ) -> None:
        compiled = context.compiled
        text = statement if compiled is None else compiled.string
        bound = context.execution_options.get("max_statement_length", CAP)
        if len(text) <= bound:
            return
        sent = backend_stack()
        if self._watched is not None and not (
            sent and sent[-1][0].startswith(self._watched)
        ):
            return
        with self._lock:
            self._kept.append(LongStatement(text, bound, sent))
