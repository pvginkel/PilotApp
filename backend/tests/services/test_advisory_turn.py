"""A turn under an advisory lock of two keys (F94.4, F142.3): of two turns of
the same keys, the second waits for the first, across connections. On a
database of its own: a turn's lock is held by a connection of its own."""

from flask import Flask

from app.services.advisory_turn import advisory_turn, turn_key
from app.services.container import ServiceContainer
from tests.support.locks import in_thread, lock_waits
from tests.support.supervisor import wait_until


def _take(
    container: ServiceContainer, first: int, second: int, taken: list[str]
) -> None:
    with advisory_turn(container.session_maker(), first, second):
        taken.append(f"{first}:{second}")


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


class TestTurnKey:
    def test_a_key_is_a_signed_32_bit_integer_drawn_from_its_parts_together(
        self,
    ) -> None:
        key = turn_key(b"person", b"project")

        assert key == turn_key(b"personproject")
        assert -(2**31) <= key < 2**31
        assert key != turn_key(b"person", b"other project")
