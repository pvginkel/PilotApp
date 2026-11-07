"""A turn under an advisory lock of two keys (F94.4, F142.3): of two turns of
the same keys, the second waits for the first, across connections, and a
turn's transactions run on the one connection that holds its lock. On a
database of its own: a turn's lock is held by a connection of its own."""

import pytest
from flask import Flask
from sqlalchemy import func, select, text

from app.services.advisory_turn import advisory_turn, turn_key
from app.services.container import ServiceContainer
from tests.support.locks import (
    holding_connections,
    in_thread,
    lock_waits,
    pool_capacity,
)
from tests.support.supervisor import wait_until


def _take(
    container: ServiceContainer, first: int, second: int, taken: list[str]
) -> None:
    with advisory_turn(container.session_maker(), first, second):
        taken.append(f"{first}:{second}")


def _holders(container: ServiceContainer) -> list[int]:
    """The backends holding the advisory lock (7, 11), read on a connection
    of their own."""
    with container.session_maker()() as db:
        return list(
            db.scalars(
                text(
                    "SELECT pid FROM pg_locks WHERE locktype = 'advisory'"
                    " AND classid = 7 AND objid = 11 AND objsubid = 2 AND granted"
                )
            )
        )


def _backends(container: ServiceContainer) -> set[int]:
    """The backends of the app's database, each a connection open."""
    with container.session_maker()() as db:
        return set(
            db.scalars(
                text(
                    "SELECT pid FROM pg_stat_activity"
                    " WHERE datname = current_database()"
                )
            )
        )


def _state(container: ServiceContainer, pid: int) -> str:
    """The backend's state, `idle` or `idle in transaction` among them."""
    with container.session_maker()() as db:
        state: str = db.scalar(
            text("SELECT state FROM pg_stat_activity WHERE pid = :pid"), {"pid": pid}
        )
        return state


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

    def test_its_transactions_run_on_the_connection_holding_its_lock(
        self, committed_app: Flask
    ) -> None:
        container: ServiceContainer = committed_app.container

        with advisory_turn(container.session_maker(), 7, 11) as turn:
            with turn.transaction() as db:
                first = db.scalar(select(func.pg_backend_pid()))
            between = _state(container, first)
            with turn.transaction() as db:
                second = db.scalar(select(func.pg_backend_pid()))
            holders = _holders(container)

        assert first == second
        assert holders == [first]
        assert between == "idle"

    def test_the_lock_is_let_go_and_its_connection_kept_by_the_pool(
        self, committed_app: Flask
    ) -> None:
        container: ServiceContainer = committed_app.container

        with advisory_turn(container.session_maker(), 7, 11) as turn:
            with turn.transaction() as db:
                pid = db.scalar(select(func.pg_backend_pid()))

        assert pid in _backends(container)
        assert _holders(container) == []

    def test_a_transaction_that_raises_is_rolled_back_and_the_next_runs(
        self, committed_app: Flask
    ) -> None:
        container: ServiceContainer = committed_app.container

        with advisory_turn(container.session_maker(), 7, 11) as turn:
            with turn.transaction() as db:
                db.execute(text("CREATE TEMPORARY TABLE turn_rows (n integer)"))
            with pytest.raises(RuntimeError), turn.transaction() as db:
                db.execute(text("INSERT INTO turn_rows VALUES (1)"))
                raise RuntimeError("the transaction failed")
            with turn.transaction() as db:
                db.execute(text("INSERT INTO turn_rows VALUES (2)"))
                rows = list(db.scalars(text("SELECT n FROM turn_rows")))
                db.execute(text("DROP TABLE turn_rows"))

        assert rows == [2]

    def test_with_every_other_connection_of_the_pool_held_its_transactions_run(
        self, committed_app: Flask
    ) -> None:
        container: ServiceContainer = committed_app.container

        with holding_connections(container, pool_capacity(container) - 1):
            with advisory_turn(container.session_maker(), 7, 11) as turn:
                for _ in range(2):
                    with turn.transaction() as db:
                        assert db.scalar(select(1)) == 1


class TestTurnKey:
    def test_a_key_is_a_signed_32_bit_integer_drawn_from_its_parts_together(
        self,
    ) -> None:
        key = turn_key(b"person", b"project")

        assert key == turn_key(b"personproject")
        assert -(2**31) <= key < 2**31
        assert key != turn_key(b"person", b"other project")
