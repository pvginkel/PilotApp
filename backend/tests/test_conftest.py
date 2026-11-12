"""The suite's own fixtures in tests/conftest.py: `pool_guard` fails a test
that leaves a nesting of the app's to it, and `statement_cap` one that leaves
a statement of the app's over its bound.

Each runs a test of its own on a pytester run inside this one, which takes
the two fixtures as they are, on the guard and the cap this run's session
fixtures installed. The app's code that nests or sends is a module compiled
as one of app/, none on disk, so that `backend_stack()` reads its frames as
the app's, on an engine of the inner run's own: that run has no app."""

from collections.abc import Callable

import pytest
from flask import Flask

from app.extensions import db

pytest_plugins = ["pytester"]

_CONFTEST = '''
from collections.abc import Generator

import pytest
from sqlalchemy import Engine, create_engine

from tests.conftest import pool_guard, statement_cap  # noqa: F401


@pytest.fixture(scope="session")
def pool_guard_installed() -> Generator[None]:
    """The run's around this one."""
    yield


@pytest.fixture(scope="session")
def statement_cap_installed() -> Generator[None]:
    """The run's around this one."""
    yield


@pytest.fixture
def engine() -> Generator[Engine]:
    engine = create_engine({url!r})
    try:
        yield engine
    finally:
        engine.dispose()
'''

_TESTS = '''
from pathlib import Path

from sqlalchemy import Engine

import app
from app.utils.statement_cap import CAP

_APP_CODE = """
def nest(engine):
    with engine.connect(), engine.connect():
        pass


def send(engine, statement):
    with engine.connect() as connection:
        connection.exec_driver_sql(statement)
"""

the_apps: dict = {}
exec(compile(_APP_CODE, str(Path(app.__file__).parent / "faults.py"), "exec"), the_apps)


def test_it_leaves_a_nesting(engine: Engine) -> None:
    the_apps["nest"](engine)


def test_it_leaves_a_long_statement(engine: Engine) -> None:
    the_apps["send"](engine, "SELECT 1 -- " + "-" * CAP)
'''


@pytest.fixture
def run_one(
    app: Flask, pytester: pytest.Pytester
) -> Callable[[str], pytest.TestReport]:
    """Runs the test `name` of `_TESTS` on the session app's database, and
    gives its teardown's report."""
    with app.app_context():
        url = db.engine.url.render_as_string(hide_password=False)
    pytester.makeconftest(_CONFTEST.format(url=url))
    pytester.makepyfile(test_faults=_TESTS)

    def run(name: str) -> pytest.TestReport:
        reprec = pytester.inline_run("-p", "no:cacheprovider", "-k", name)
        reports = reprec.getreports("pytest_runtest_logreport")
        assert [(r.when, r.outcome) for r in reports[:2]] == [
            ("setup", "passed"),
            ("call", "passed"),
        ]
        [teardown] = reports[2:]
        return teardown

    return run


class TestSuiteFixtures:
    def test_the_pool_guard_fails_a_test_that_leaves_a_nesting(
        self, run_one: Callable[[str], pytest.TestReport]
    ) -> None:
        teardown = run_one("test_it_leaves_a_nesting")

        assert teardown.failed
        assert (
            "checked out a second connection of a pool while it held one"
            in teardown.longreprtext
        )
        assert "app/faults.py:3 in nest" in teardown.longreprtext

    def test_the_statement_cap_fails_a_test_that_leaves_a_long_statement(
        self, run_one: Callable[[str], pytest.TestReport]
    ) -> None:
        teardown = run_one("test_it_leaves_a_long_statement")

        assert teardown.failed
        assert (
            "A statement of 2,012 characters, over its bound of 2,000, sent at:"
            in teardown.longreprtext
        )
        assert "app/faults.py:9 in send" in teardown.longreprtext
