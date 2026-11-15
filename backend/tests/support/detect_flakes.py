"""The detect-flakes mode (F122.7), the backend's side: in every run a session
makes, a failing test is rerun twice, the run's summary names each test that
passed only on a rerun apart from the tests that failed every attempt, and the
run stays red. A session's run is one where the test suite lock is taken
(suite_lock.py's suite_lock_file): inside KubeCoder, beside the spec repo, so
never CI's, which reruns nothing. A run on one process, a targeted
``uv run pytest tests/...``, takes no lock and is in the mode too.

pytest-rerunfailures reruns the tests, on a ``flaky`` marker given to each.
Two of its own options do not serve: --fail-on-flaky keeps no run on xdist's
workers red, reading the controller's items, which ran nowhere, so this plugin
keeps it red from the reports; and --max-suite-reruns counts reruns, where the
cap counts failed tests, so the marker's condition rules out the rerun of a
test that failed past the cap. Each test's first failure claims a slot, a file
created in a directory the controller makes, so that the count spans the run's
processes. On xdist's workers, the rerun plugin's store goes local
(pytest_sessionstart). tests/test_conftest.py pins it on runs of its own.
"""

from functools import partial
from pathlib import Path
from shutil import rmtree
from tempfile import mkdtemp
from typing import Any

import pytest
from pytest_rerunfailures import ClientStatusDB, StatusDB

# How many times a failing test is rerun.
RERUNS = 2

# How many failing tests a run reruns; past them, a failing test is not
# rerun. The operator, 2026-11-15: "Cap at 10" (PilotAppSpecs,
# tools/cost-dashboard/asks/t15-rerun-cap.md). detect-flakes.ts's RERUN_CAP.
RERUN_CAP = 10

# Whether a test that failed is rerun: within the cap or not, set at its first
# failure.
_WITHIN_CAP = pytest.StashKey[bool]()

# The key under which a worker is handed the directory of the slots.
_SLOTS = "detect_flakes_slots"


def _rerun_within_cap(item: pytest.Item) -> bool:
    """The flaky marker's condition: a test is rerun unless it failed past the
    cap."""
    return item.stash.get(_WITHIN_CAP, True)


class DetectFlakes:
    """The mode, registered as a plugin on the controller and on every worker."""

    def __init__(self, cap: int = RERUN_CAP) -> None:
        self.cap = cap
        self._slots = Path()
        self._owns_slots = False
        self._is_worker = False
        # By node id, in the order the reports came.
        self._reran: dict[str, None] = {}
        self._failed: dict[str, None] = {}
        self._past_cap: dict[str, None] = {}

    def pytest_configure(self, config: pytest.Config) -> None:
        workerinput = getattr(config, "workerinput", None)
        self._is_worker = workerinput is not None
        if workerinput is not None:
            self._slots = Path(workerinput[_SLOTS])
        else:
            self._slots = Path(mkdtemp(prefix="pytest-detect-flakes-"))
            self._owns_slots = True

    @pytest.hookimpl(trylast=True)
    def pytest_sessionstart(self, session: pytest.Session) -> None:
        """On a worker, the rerun plugin's status store a run on one process
        has. Its store on xdist's workers serves only the rerun of a test whose
        worker crashed, at two calls to the controller a test, which its server
        reads a byte at a time: some 5 ms a test on eight processes, 36 s of
        the backend's run. A crashed worker's test fails, as without the
        mode."""
        config = session.config
        store = getattr(config, "failures_db", None)
        if self._is_worker and isinstance(store, ClientStatusDB):
            store.sock.close()
            config.failures_db = StatusDB()  # type: ignore[attr-defined]

    @pytest.hookimpl(optionalhook=True)
    def pytest_configure_node(self, node: Any) -> None:
        """xdist's, on the controller: a worker claims the controller's slots."""
        node.workerinput[_SLOTS] = str(self._slots)

    def pytest_unconfigure(self) -> None:
        if self._owns_slots:
            rmtree(self._slots, ignore_errors=True)

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        for item in items:
            item.add_marker(
                pytest.mark.flaky(
                    reruns=RERUNS, condition=partial(_rerun_within_cap, item)
                )
            )

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_makereport(
        self, item: pytest.Item
    ) -> Any:  # a generator of pluggy's: the report, sent back in
        report: pytest.TestReport = yield
        if report.failed and _WITHIN_CAP not in item.stash:
            item.stash[_WITHIN_CAP] = self._claim()
        if report.failed and not item.stash.get(_WITHIN_CAP, True):
            # Carried to the controller with the report.
            report.detect_flakes_past_cap = True  # type: ignore[attr-defined]
        return report

    def _claim(self) -> bool:
        """Claim one of the cap's slots for a test's first failure, or none
        once every slot is claimed."""
        for slot in range(self.cap):
            try:
                (self._slots / str(slot)).touch(exist_ok=False)
            except FileExistsError:
                continue
            return True
        return False

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.outcome == "rerun":
            self._reran[report.nodeid] = None
        elif report.failed:
            self._failed[report.nodeid] = None
            if getattr(report, "detect_flakes_past_cap", False):
                self._past_cap[report.nodeid] = None

    def _flaky(self) -> list[str]:
        """The tests that passed only on a rerun."""
        return [nodeid for nodeid in self._reran if nodeid not in self._failed]

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session: pytest.Session) -> None:
        # A test that passed only on a rerun keeps the run red.
        if (
            not self._is_worker
            and self._flaky()
            and session.exitstatus == pytest.ExitCode.OK
        ):
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def pytest_terminal_summary(self, terminalreporter: Any) -> None:
        if self._is_worker:
            return
        flaky = self._flaky()
        every_attempt = [nodeid for nodeid in self._failed if nodeid in self._reran]
        past_cap = list(self._past_cap)
        if not (flaky or every_attempt or past_cap):
            return
        write = terminalreporter.write_line
        terminalreporter.write_sep("=", "detect-flakes")
        for nodeid in flaky:
            write(f"FLAKY {nodeid} - passed only on a rerun", yellow=True)
        for nodeid in every_attempt:
            write(f"FAILED {nodeid} - failed every attempt", red=True)
        for nodeid in past_cap:
            write(f"NOT RERUN {nodeid} - failed once, past the cap", red=True)
        if flaky:
            write(
                f"🔁 The run is red: {_tests(len(flaky))} passed only on a rerun, "
                "named FLAKY above. A test named FAILED failed every attempt."
            )
        if past_cap:
            one = len(past_cap) == 1
            write(
                f"🔁 The cap of {self.cap} failed tests a run was reached: past it, "
                f"{_tests(len(past_cap))} failed once and "
                f"{'was' if one else 'were'} not rerun, named NOT RERUN above."
            )


def _tests(count: int) -> str:
    return "1 test" if count == 1 else f"{count} tests"
