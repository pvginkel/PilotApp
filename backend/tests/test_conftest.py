"""The suite's own fixtures in tests/conftest.py: `pool_guard` fails a test
that leaves a nesting of the app's to it, and `statement_cap` one that leaves
a statement of the app's over its bound; and the detect-flakes mode it
registers in a session's run (tests/support/detect_flakes.py).

Each runs a test of its own on a pytester run inside this one, which takes
the two fixtures as they are, on the guard and the cap this run's session
fixtures installed. The app's code that nests or sends is a module compiled
as one of app/, none on disk, so that `backend_stack()` reads its frames as
the app's, on an engine of the inner run's own: that run has no app."""

from collections.abc import Callable
from pathlib import Path

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


# The mode as a session's run registers it, on a cap of 2.
_FLAKES_CONFTEST = """
from tests.support.detect_flakes import DetectFlakes


def pytest_configure(config):
    config.pluginmanager.register(DetectFlakes(cap=2), "detect_flakes")
"""

# On one process, in this order: the third test's first failure is the run's
# third, past the cap of 2.
_FLAKES = '''
from pathlib import Path


def _attempt(name: str) -> int:
    """How many times the test ran before, across the run's processes."""
    file = Path(__file__).parent / f"{name}.attempts"
    attempts = int(file.read_text()) if file.exists() else 0
    file.write_text(str(attempts + 1))
    return attempts


def test_a_passes_on_a_rerun() -> None:
    assert _attempt("a") > 0


def test_b_fails_every_attempt() -> None:
    _attempt("b")
    assert False


def test_c_fails_past_the_cap() -> None:
    _attempt("c")
    assert False
'''

_RED = (
    "🔁 The run is red: 1 test passed only on a rerun, named FLAKY above. "
    "A test named FAILED failed every attempt."
)

_BACKEND_DIR = Path(__file__).resolve().parent.parent


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


class TestDetectFlakes:
    @pytest.fixture
    def flakes(self, pytester: pytest.Pytester) -> pytest.Pytester:
        pytester.makeconftest(_FLAKES_CONFTEST)
        pytester.makepyfile(test_flakes=_FLAKES)
        return pytester

    @staticmethod
    def attempts(pytester: pytest.Pytester) -> dict[str, int]:
        """Each test's attempts, by its letter."""
        return {
            file.stem: int(file.read_text())
            for file in sorted(pytester.path.glob("*.attempts"))
        }

    def test_names_a_test_that_passed_only_on_a_rerun_and_keeps_the_run_red(
        self, flakes: pytest.Pytester
    ) -> None:
        result = flakes.runpytest("-p", "no:cacheprovider", "-k", "a_passes")

        assert self.attempts(flakes) == {"a": 2}
        assert result.ret == pytest.ExitCode.TESTS_FAILED
        result.stdout.fnmatch_lines(
            [
                "*= detect-flakes =*",
                "FLAKY test_flakes.py::test_a_passes_on_a_rerun - passed only on a rerun",
                _RED,
            ]
        )

    def test_reruns_a_failing_test_twice_and_none_past_the_cap_saying_so(
        self, flakes: pytest.Pytester
    ) -> None:
        result = flakes.runpytest("-p", "no:cacheprovider")

        assert self.attempts(flakes) == {"a": 2, "b": 3, "c": 1}
        assert result.parseoutcomes() == {"passed": 1, "failed": 2, "rerun": 3}
        assert result.ret == pytest.ExitCode.TESTS_FAILED
        result.stdout.fnmatch_lines(
            [
                "*= detect-flakes =*",
                "FLAKY test_flakes.py::test_a_passes_on_a_rerun - passed only on a rerun",
                "FAILED test_flakes.py::test_b_fails_every_attempt - failed every attempt",
                "NOT RERUN test_flakes.py::test_c_fails_past_the_cap"
                " - failed once, past the cap",
                _RED,
                "🔁 The cap of 2 failed tests a run was reached: past it, 1 test failed"
                " once and was not rerun, named NOT RERUN above.",
            ]
        )

    def test_keeps_a_run_on_xdist_workers_red_naming_its_tests_on_the_controller(
        self, flakes: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The run's conftest imports the mode from this backend's tests.
        monkeypatch.setenv("PYTHONPATH", str(_BACKEND_DIR))
        flakes.makepyfile(
            test_store="""
from pytest_rerunfailures import StatusDB


def test_d_a_worker_keeps_its_rerun_store_local(request) -> None:
    # Not the controller's, two calls a test away (detect_flakes.py).
    assert type(request.config.failures_db) is StatusDB
"""
        )

        result = flakes.runpytest_subprocess(
            "-p",
            "no:cacheprovider",
            "-n",
            "2",
            "-k",
            "a_passes or b_fails or d_a_worker",
        )

        assert self.attempts(flakes) == {"a": 2, "b": 3}
        assert result.parseoutcomes() == {"passed": 2, "failed": 1, "rerun": 3}
        assert result.ret == pytest.ExitCode.TESTS_FAILED
        result.stdout.fnmatch_lines(
            [
                "*= detect-flakes =*",
                "FLAKY test_flakes.py::test_a_passes_on_a_rerun - passed only on a rerun",
                "FAILED test_flakes.py::test_b_fails_every_attempt - failed every attempt",
                _RED,
            ]
        )
