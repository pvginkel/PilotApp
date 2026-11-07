"""The test suite lock (tests/support/suite_lock.py): a run on xdist's workers
takes the lock a Playwright run takes, held until the run ends, and none
outside KubeCoder."""

import os
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from tests import conftest
from tests.support import suite_lock
from tests.support.locks import in_thread
from tests.support.suite_lock import (
    HolderNote,
    SuiteLockTimeout,
    acquire_suite_lock,
    describe_holder,
    hold_suite_lock,
    read_holder_note,
    suite_lock_file,
)

_BACKEND_DIR = Path(__file__).resolve().parent.parent

# Invented holders.
FIRST: HolderNote = {
    "environment": "pytest-first",
    "host": "first-host",
    "pid": "101",
    "started": "2026-01-01T10:00:00.000Z",
}
SECOND: HolderNote = {
    "environment": "pytest-second",
    "host": "second-host",
    "pid": "202",
    "started": "2026-01-01T10:20:00.000Z",
}


def _is_locked(file: Path) -> bool:
    """Whether `flock`, as a Playwright run takes the lock, finds it held."""
    return subprocess.run(["flock", "--nonblock", str(file), "true"]).returncode != 0


@pytest.fixture
def lock_file(tmp_path: Path) -> Path:
    file = tmp_path / ".locks" / "test-suite.lock"
    file.parent.mkdir()
    return file


class TestSuiteLock:
    def test_keeps_a_second_run_waiting_tells_it_whose_run_holds_it_and_lets_it_give_up(
        self, lock_file: Path
    ) -> None:
        first = acquire_suite_lock(lock_file, wait_seconds=1, holder=FIRST)
        try:
            heard: list[HolderNote] = []
            with pytest.raises(SuiteLockTimeout) as gave_up:
                acquire_suite_lock(
                    lock_file, wait_seconds=2, holder=SECOND, on_wait=heard.append
                )

            assert gave_up.value.holder == FIRST
            assert heard == [FIRST]
            assert (
                describe_holder(FIRST, datetime(2026, 1, 1, 10, 12, tzinfo=UTC))
                == "the run in pytest-first (pid 101 on first-host, running for 12 min)"
            )
        finally:
            first.release()

    def test_goes_to_the_next_run_once_the_holder_lets_it_go(
        self, lock_file: Path
    ) -> None:
        first = acquire_suite_lock(lock_file, wait_seconds=1, holder=FIRST)
        first.release()

        second = acquire_suite_lock(lock_file, wait_seconds=5, holder=SECOND)
        try:
            assert read_holder_note(lock_file) == SECOND
        finally:
            second.release()

    def test_keeps_a_run_with_no_bound_waiting_until_the_holder_lets_it_go(
        self, lock_file: Path
    ) -> None:
        first = acquire_suite_lock(lock_file, wait_seconds=1, holder=FIRST)
        heard: list[HolderNote] = []
        noticed = threading.Event()

        def on_wait(holder: HolderNote) -> None:
            heard.append(holder)
            noticed.set()

        waiting = in_thread(
            lambda: acquire_suite_lock(
                lock_file, wait_seconds=None, holder=SECOND, on_wait=on_wait
            )
        )
        try:
            assert noticed.wait(5)
            assert heard == [FIRST]
            # Past the notice, and past what a bound of one second would have
            # allowed.
            waiting.thread.join(1.5)
            assert waiting.thread.is_alive()
        finally:
            first.release()

        second = waiting.result()
        try:
            assert read_holder_note(lock_file) == SECOND
        finally:
            second.release()

    def test_waits_for_a_playwright_run_and_keeps_one_waiting(
        self, lock_file: Path
    ) -> None:
        # A Playwright run's holder, as test-suite-lock.ts spawns it.
        playwright = subprocess.Popen(
            ["flock", str(lock_file), "sh", "-c", "echo locked && exec cat"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        assert playwright.stdin is not None and playwright.stdout is not None
        try:
            assert playwright.stdout.readline() == b"locked\n"
            with pytest.raises(SuiteLockTimeout):
                acquire_suite_lock(lock_file, wait_seconds=0, holder=SECOND)
        finally:
            playwright.stdin.close()
            playwright.wait()

        lock = acquire_suite_lock(lock_file, wait_seconds=0, holder=SECOND)
        try:
            assert _is_locked(lock_file)
        finally:
            lock.release()
        assert not _is_locked(lock_file)

    def test_dies_with_a_holder_that_is_killed(self, lock_file: Path) -> None:
        # A run of its own, holding the lock until it is killed.
        script = (
            "import time\n"
            "from pathlib import Path\n"
            "from tests.support.suite_lock import acquire_suite_lock\n"
            f"lock = acquire_suite_lock(Path({str(lock_file)!r}), wait_seconds=5,"
            f" holder={FIRST!r})\n"
            "print('held', flush=True)\n"
            "time.sleep(60)\n"
        )
        holder = subprocess.Popen(
            [sys.executable, "-c", script],
            cwd=_BACKEND_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert holder.stdout is not None and holder.stderr is not None
        try:
            line = holder.stdout.readline()
            assert line == "held\n", holder.stderr.read()
            assert _is_locked(lock_file)
        finally:
            holder.kill()
            holder.wait()

        assert not _is_locked(lock_file)

    def test_is_held_by_this_run_taken_in_its_controller(
        self, request: pytest.FixtureRequest
    ) -> None:
        file = suite_lock_file()
        if file is None or not hasattr(request.config, "workerinput"):
            pytest.skip("no lock outside KubeCoder, nor on one process")

        assert _is_locked(file)
        note = read_holder_note(file)
        assert note["environment"] == os.environ["KUBECODER_ENVIRONMENT_ID"]
        # The workers are the controller's children.
        assert note["pid"] == str(os.getppid())

    def test_is_taken_only_inside_kubecoder(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        assert suite_lock_file({}) is None

        monkeypatch.setattr(suite_lock, "SPEC_REPO", tmp_path / "PilotAppSpecs")
        assert suite_lock_file({"KUBECODER_ENVIRONMENT_ID": "pytest-this"}) is None


class TestHoldSuiteLock:
    @pytest.fixture(autouse=True)
    def inside_kubecoder(
        self, monkeypatch: pytest.MonkeyPatch, lock_file: Path
    ) -> None:
        monkeypatch.setattr(suite_lock, "SPEC_REPO", lock_file.parent.parent)
        monkeypatch.setattr(suite_lock, "LOCK_FILE", lock_file)
        monkeypatch.setenv("KUBECODER_ENVIRONMENT_ID", "pytest-this")
        monkeypatch.delenv("PYTEST_SUITE_LOCK_WAIT", raising=False)

    def test_holds_the_lock_for_this_run_and_names_it(
        self, lock_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        lock = hold_suite_lock()
        assert lock is not None
        try:
            assert _is_locked(lock_file)
            note = read_holder_note(lock_file)
            assert note["environment"] == "pytest-this"
            assert note["pid"] == str(os.getpid())
            assert describe_holder(note).startswith(
                f"the run in pytest-this (pid {os.getpid()} on "
            )
            assert describe_holder(note).endswith(", running for 0 min)")
        finally:
            lock.release()
        assert capsys.readouterr().out == (
            f"🔒 Holding the test suite lock ({lock_file})\n"
        )

    def test_gives_up_after_its_bound_having_run_nothing(
        self,
        lock_file: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("PYTEST_SUITE_LOCK_WAIT", "2")
        first = acquire_suite_lock(lock_file, wait_seconds=0, holder=FIRST)
        try:
            with pytest.raises(pytest.exit.Exception) as gave_up:
                hold_suite_lock()
        finally:
            first.release()

        held_by = "held by the run in pytest-first (pid 101 on first-host, running for"
        assert gave_up.value.returncode == 75
        assert gave_up.value.msg.startswith(
            f"⛔ Gave up after 2 s waiting for the test suite lock, {held_by}"
        )
        assert gave_up.value.msg.endswith(f"({lock_file}). Exit code 75.")
        assert capsys.readouterr().out.startswith(
            f"⏳ Waiting up to 2 s for the test suite lock, {held_by}"
        )

    def test_takes_none_outside_kubecoder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("KUBECODER_ENVIRONMENT_ID")

        assert hold_suite_lock() is None

    def test_is_taken_by_no_run_on_one_process(self, lock_file: Path) -> None:
        # A targeted `uv run pytest tests/...`, as conftest's hook reads its
        # config.
        config = SimpleNamespace(
            stash=pytest.Stash(),
            getoption={"dist": "no", "collectonly": False}.get,
        )
        conftest.pytest_sessionstart(
            cast(pytest.Session, SimpleNamespace(config=config))
        )

        assert len(config.stash) == 0
        assert not _is_locked(lock_file)
