"""The after-commit callbacks' run: taken off the list before the first runs,
so that a callback whose own commit runs the callbacks, as a `scoped_session`
it opens does at its exit, runs neither itself nor the others again."""

from collections.abc import Iterator

import pytest

from app.utils.after_commit import (
    after_commit,
    clear_after_commit_callbacks,
    run_after_commit_callbacks,
)


@pytest.fixture(autouse=True)
def _cleared() -> Iterator[None]:
    clear_after_commit_callbacks()
    try:
        yield
    finally:
        clear_after_commit_callbacks()


def test_a_callback_whose_own_commit_runs_the_callbacks_runs_once() -> None:
    runs: list[str] = []

    def first() -> None:
        runs.append("first")
        # What a `scoped_session` opened here runs at its own commit.
        run_after_commit_callbacks()

    after_commit(first)
    after_commit(lambda: runs.append("second"))

    run_after_commit_callbacks()

    assert runs == ["first", "second"]


def test_what_a_callbacks_own_commit_registered_runs_at_that_commit() -> None:
    runs: list[str] = []

    def outer() -> None:
        runs.append("outer")
        after_commit(lambda: runs.append("inner"))
        run_after_commit_callbacks()

    after_commit(outer)

    run_after_commit_callbacks()

    assert runs == ["outer", "inner"]
