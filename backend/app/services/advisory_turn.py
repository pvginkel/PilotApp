"""A turn under a PostgreSQL advisory lock of two keys, across threads and
processes alike: a member's pushes, a person's alarms, the store's reset
(F94.4, F142.3; design 2 §7.2).

A turn is one transaction, on the one connection its session holds, and the
lock is that transaction's (`pg_advisory_xact_lock`): the stages reach
PostgreSQL through a pooler in transaction mode, which hands each transaction
whichever server connection is free, so a lock held past its transaction
holds nothing there. A turn whose work runs in its session never waits on the
pool while it holds a connection."""

import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy import Integer, cast, func, literal, select
from sqlalchemy.orm import Session


@contextmanager
def advisory_turn(
    open_session: Callable[[], Session], first: int, second: int
) -> Iterator[Session]:
    """Hold the advisory lock `(first, second)` until the block ends, in the
    transaction of a session of its own, the one yielded: committed when the
    block ends, rolled back when it raises, the lock let go with it. A turn
    of the same two keys waits for it. The slot's lock takes one key
    (`start_gate.SLOT_LOCK`), so no turn meets it."""
    db = open_session()
    try:
        db.execute(
            select(
                func.pg_advisory_xact_lock(
                    cast(literal(first), Integer), cast(literal(second), Integer)
                )
            )
        )
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def let_go(db: Session) -> Iterator[None]:
    """A savepoint of `db`'s transaction, rolled back when the block ends:
    the locks the block took on a row or a table go with it, and whatever it
    wrote. Across a call out, a turn's transaction then holds its lock
    alone."""
    savepoint = db.begin_nested()
    try:
        yield
    finally:
        savepoint.rollback()


def turn_key(*parts: bytes) -> int:
    """A turn's second key drawn from `parts`, a signed 32-bit integer; two
    drawing the same one only take turns."""
    digest = hashlib.blake2b(b"".join(parts), digest_size=4)
    return int.from_bytes(digest.digest(), "big", signed=True)
