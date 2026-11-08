"""What a block of a test sends on a session's connection: each statement as
the code built it, and its text as sent."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session as DbSession


@dataclass
class Sent:
    built: list[Any] = field(default_factory=list)
    """Each statement executed, the object the code built."""
    texts: list[str] = field(default_factory=list)
    """Each statement's text as sent, an IN list's ids filled in."""


@contextmanager
def sent(session: DbSession) -> Iterator[Sent]:
    """The statements sent on `session`'s connection inside the block."""
    connection = session.connection()
    captured = Sent()

    def execute(_conn: Any, element: Any, *_: Any) -> None:
        captured.built.append(element)

    def cursor(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        captured.texts.append(statement)

    event.listen(connection, "before_execute", execute)
    event.listen(connection, "before_cursor_execute", cursor)
    try:
        yield captured
    finally:
        event.remove(connection, "before_execute", execute)
        event.remove(connection, "before_cursor_execute", cursor)
