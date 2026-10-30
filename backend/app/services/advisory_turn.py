"""A turn under a PostgreSQL advisory lock of two keys: the sends of one
standing notification on one phone take turns, across threads and processes
alike (F94.4, F142.3; design 2 §7.2)."""

import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy import Integer, cast, func, literal, select
from sqlalchemy.orm import Session


@contextmanager
def advisory_turn(
    open_session: Callable[[], Session], first: int, second: int
) -> Iterator[None]:
    """Hold the advisory lock `(first, second)` until the block ends, by a
    transaction of its own on a session of its own that holds nothing else; a
    turn of the same two keys waits for it. The slot's lock takes one key
    (`start_gate.SLOT_LOCK`), so no turn meets it."""
    lock = open_session()
    try:
        lock.execute(
            select(
                func.pg_advisory_xact_lock(
                    cast(literal(first), Integer), cast(literal(second), Integer)
                )
            )
        )
        yield
    finally:
        lock.close()


def turn_key(*parts: bytes) -> int:
    """A turn's second key drawn from `parts`, a signed 32-bit integer; two
    drawing the same one only take turns."""
    digest = hashlib.blake2b(b"".join(parts), digest_size=4)
    return int.from_bytes(digest.digest(), "big", signed=True)
