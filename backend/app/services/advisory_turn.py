"""A turn under a PostgreSQL advisory lock of two keys, across threads and
processes alike: a member's pushes, a person's alarms, the store's reset
(F94.4, F142.3; design 2 §7.2).

A turn holds one pooled connection, the one its lock is on, and its
transactions run on it (`Turn.transaction`), so that a turn that opens no
other session never waits on the pool while it holds a connection."""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Integer, cast, func, literal, select
from sqlalchemy.orm import Session, sessionmaker


class Turn:
    """A turn's connection, which holds its lock."""

    def __init__(
        self, session_maker: sessionmaker[Session], connection: Connection
    ) -> None:
        self._session_maker = session_maker
        self._connection = connection

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """A transaction of its own on the turn's connection: committed when
        the block ends, rolled back when it raises. Between two, the
        connection holds no transaction open, the lock alone."""
        db = self._session_maker(bind=self._connection)
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


@contextmanager
def advisory_turn(
    session_maker: sessionmaker[Session], first: int, second: int
) -> Iterator[Turn]:
    """Hold the advisory lock `(first, second)` until the block ends, on a
    connection of its own, which holds no transaction open between the
    turn's; a turn of the same two keys waits for it. The lock is let go
    before the connection goes back to the pool. The slot's lock takes one
    key (`start_gate.SLOT_LOCK`), so no turn meets it."""
    keys = (cast(literal(first), Integer), cast(literal(second), Integer))
    with session_maker() as unbound:
        engine = unbound.get_bind().engine
    with engine.connect() as connection:
        connection.execute(select(func.pg_advisory_lock(*keys)))
        connection.commit()
        try:
            yield Turn(session_maker, connection)
        finally:
            connection.execute(select(func.pg_advisory_unlock(*keys)))
            connection.commit()


def turn_key(*parts: bytes) -> int:
    """A turn's second key drawn from `parts`, a signed 32-bit integer; two
    drawing the same one only take turns."""
    digest = hashlib.blake2b(b"".join(parts), digest_size=4)
    return int.from_bytes(digest.digest(), "big", signed=True)
