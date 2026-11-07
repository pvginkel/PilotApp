"""The pool guard (app/utils/pool_guard.py), watching this file's code on the
session app's pool: a thread's second checkout while it holds one is a
nesting, with both stacks, where the two part in the watched code and in no
function exempt; a backend's guard, watching all, takes every nesting."""

from collections.abc import Iterator

import pytest
from flask import Flask
from sqlalchemy import Engine

from app.extensions import db
from app.utils.pool_guard import PoolGuard
from tests.support.locks import in_thread

_HERE = "tests/test_pool_guard.py"


@pytest.fixture
def engine(app: Flask) -> Engine:
    with app.app_context():
        return db.engine


def _guard(**exempt: str) -> PoolGuard:
    return PoolGuard(
        watched=(_HERE,), exempt={f"{_HERE}:{k}": v for k, v in exempt.items()}
    )


@pytest.fixture
def guard() -> Iterator[PoolGuard]:
    guard = _guard()
    guard.install()
    try:
        yield guard
    finally:
        guard.uninstall()


def _nest(engine: Engine) -> None:
    with engine.connect(), engine.connect():
        pass


class TestPoolGuard:
    def test_a_second_checkout_while_one_is_held_is_a_nesting_with_both_stacks(
        self, guard: PoolGuard, engine: Engine
    ) -> None:
        _nest(engine)

        [nesting] = guard.drain()
        assert nesting.thread == "MainThread"
        assert nesting.held[-1][::2] == nesting.taken[-1][::2] == (_HERE, "_nest")
        assert f"{_HERE}:{nesting.taken[-1][1]} in _nest" in nesting.describe()
        assert guard.drain() == []

    def test_checkouts_one_after_the_other_are_none(
        self, guard: PoolGuard, engine: Engine
    ) -> None:
        with engine.connect():
            pass
        with engine.connect():
            pass

        assert guard.drain() == []

    def test_a_connection_another_thread_holds_is_none(
        self, guard: PoolGuard, engine: Engine
    ) -> None:
        with engine.connect():
            in_thread(lambda: engine.connect().close()).result()

        assert guard.drain() == []

    def test_to_the_suites_guard_a_nesting_parting_in_a_test_is_none(
        self, engine: Engine
    ) -> None:
        guard = PoolGuard()
        guard.install()
        try:
            _nest(engine)
        finally:
            guard.uninstall()

        assert guard.drain() == []

    def test_to_a_backends_guard_a_nesting_anywhere_is_one(
        self, engine: Engine
    ) -> None:
        guard = PoolGuard(watched=None)
        guard.install()
        try:
            _nest(engine)
        finally:
            guard.uninstall()

        assert len(guard.drain()) == 1

    def test_a_nesting_in_an_exempt_function_is_none(self, engine: Engine) -> None:
        guard = _guard(_nest="invented")
        guard.install()
        try:
            _nest(engine)
        finally:
            guard.uninstall()

        assert guard.drain() == []
