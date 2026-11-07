"""A turn under an advisory lock of two keys (F94.4, F142.3): of two turns of
the same keys, the second waits for the first, across connections; the lock
is the turn's transaction's, and what a block let go holds no lock past it.
On a database of its own: a turn's lock is held by a connection of its own."""

import pytest
from flask import Flask
from sqlalchemy import func, select, text

from app.services.advisory_turn import advisory_turn, let_go, turn_key
from app.services.container import ServiceContainer
from tests.support.locks import (
    holding_connections,
    in_thread,
    lock_waits,
    pool_capacity,
    turn_holders,
)
from tests.support.supervisor import wait_until


def _take(
    container: ServiceContainer, first: int, second: int, taken: list[str]
) -> None:
    with advisory_turn(container.session_maker(), first, second):
        taken.append(f"{first}:{second}")


def _rows(container: ServiceContainer) -> list[int]:
    with container.session_maker()() as db:
        return list(db.scalars(text("SELECT n FROM turn_rows ORDER BY n")))


@pytest.fixture
def rows(committed_app: Flask) -> ServiceContainer:
    """The committed app's container, its database with a table `turn_rows`."""
    container: ServiceContainer = committed_app.container
    with container.session_maker()() as db:
        db.execute(text("CREATE TABLE turn_rows (n integer)"))
        db.commit()
    return container


class TestAdvisoryTurn:
    def test_a_turn_of_the_same_keys_waits_for_the_one_held(
        self, committed_app: Flask
    ) -> None:
        container: ServiceContainer = committed_app.container
        taken: list[str] = []

        with advisory_turn(container.session_maker(), 7, 11):
            second = in_thread(lambda: _take(container, 7, 11, taken))
            wait_until(lambda: lock_waits(container) == 1, "the second turn waiting")
            taken.append("held")
        second.result()

        assert taken == ["held", "7:11"]

    def test_a_turn_of_other_keys_does_not_wait(self, committed_app: Flask) -> None:
        container: ServiceContainer = committed_app.container
        taken: list[str] = []

        with advisory_turn(container.session_maker(), 7, 11):
            in_thread(lambda: _take(container, 7, 12, taken)).result()
            in_thread(lambda: _take(container, 8, 11, taken)).result()

        assert taken == ["7:12", "8:11"]

    def test_the_turn_ends_with_its_block_when_the_block_raises(
        self, committed_app: Flask
    ) -> None:
        container: ServiceContainer = committed_app.container
        taken: list[str] = []

        try:
            with advisory_turn(container.session_maker(), 7, 11):
                raise RuntimeError("the block failed")
        except RuntimeError:
            pass
        in_thread(lambda: _take(container, 7, 11, taken)).result()

        assert taken == ["7:11"]

    def test_its_lock_is_its_transactions_let_go_when_the_transaction_ends(
        self, committed_app: Flask
    ) -> None:
        """A transaction holds the lock, and nothing past its end: what a
        pooler in transaction mode, which hands each transaction whichever
        server connection is free, keeps."""
        container: ServiceContainer = committed_app.container

        with advisory_turn(container.session_maker(), 7, 11) as db:
            held = turn_holders(container, 7)
            db.commit()
            after = turn_holders(container, 7)

        assert held == [("idle in transaction", [])]
        assert after == []

    def test_its_work_is_committed_when_the_block_ends_and_undone_when_it_raises(
        self, rows: ServiceContainer
    ) -> None:
        with advisory_turn(rows.session_maker(), 7, 11) as db:
            db.execute(text("INSERT INTO turn_rows VALUES (1)"))
        with (
            pytest.raises(RuntimeError),
            advisory_turn(rows.session_maker(), 7, 11) as db,
        ):
            db.execute(text("INSERT INTO turn_rows VALUES (2)"))
            raise RuntimeError("the block failed")

        assert _rows(rows) == [1]
        assert turn_holders(rows, 7) == []

    def test_with_every_other_connection_of_the_pool_held_its_work_runs(
        self, committed_app: Flask
    ) -> None:
        container: ServiceContainer = committed_app.container

        with holding_connections(container, pool_capacity(container) - 1):
            with advisory_turn(container.session_maker(), 7, 11) as db:
                assert db.scalar(select(1)) == 1


class TestLetGo:
    def test_what_its_block_read_and_wrote_goes_and_the_turns_lock_stays(
        self, rows: ServiceContainer
    ) -> None:
        with advisory_turn(rows.session_maker(), 7, 11) as db:
            pid = db.scalar(select(func.pg_backend_pid()))
            with let_go(db):
                db.execute(text("INSERT INTO turn_rows VALUES (1)"))
                assert db.scalar(select(func.pg_backend_pid())) == pid
                inside = turn_holders(rows, 7)
            after = turn_holders(rows, 7)

        assert inside == [("idle in transaction", ["turn_rows"])]
        assert after == [("idle in transaction", [])]
        assert _rows(rows) == []

    def test_it_rolls_back_when_its_block_raises(self, rows: ServiceContainer) -> None:
        with advisory_turn(rows.session_maker(), 7, 11) as db:
            with pytest.raises(RuntimeError), let_go(db):
                db.execute(text("INSERT INTO turn_rows VALUES (1)"))
                raise RuntimeError("the block failed")
            db.execute(text("INSERT INTO turn_rows VALUES (2)"))

        assert _rows(rows) == [2]


class TestTurnKey:
    def test_a_key_is_a_signed_32_bit_integer_drawn_from_its_parts_together(
        self,
    ) -> None:
        key = turn_key(b"person", b"project")

        assert key == turn_key(b"personproject")
        assert -(2**31) <= key < 2**31
        assert key != turn_key(b"person", b"other project")
