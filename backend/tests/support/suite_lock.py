"""The test suite lock, the backend's side: a run on xdist's workers, as
``kc project test`` runs the suite, takes the lock a Playwright run takes
(frontend/tests/support/test-suite-lock.ts). Every environment of the project
runs on one 8-core node, and a suite on eight processes beside another
environment's Playwright run at four workers fails that run's tests on their
timeouts.

The lock is a flock on a file in the spec repo, whose checkout every
environment of the project mounts from one directory on that node: one kernel,
so the flock reaches across their pods, and it excludes the `flock` child that
holds a Playwright run's. The run holds it on an open file of its own, which
the kernel closes however the process ends, and the lock goes with it.
"""

import fcntl
import os
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from socket import gethostname
from typing import IO

import pytest

# The spec repo's checkout, at this path in every environment of the project.
# Never relative to this checkout: a run-slice phase runs the suite in a
# worktree under /work/scratch.
SPEC_REPO = Path("/work/PilotAppSpecs")

# test-suite-lock.ts's LOCK_FILE. The spec repo's git ignores /.locks/.
LOCK_FILE = SPEC_REPO / ".locks" / "test-suite.lock"

# How long a run tries for the lock before it says that it waits.
WAIT_NOTICE_SECONDS = 1.0

# How often a bounded wait tries for the lock again.
RETRY_SECONDS = 0.1

# The exit code of a run that gave up waiting: EX_TEMPFAIL, try again later,
# a Playwright run's too.
LOCK_TIMEOUT_EXIT_CODE = 75

# The `key: value` lines the holder writes into the lock's file.
HolderNote = dict[str, str]


class SuiteLockTimeout(Exception):
    def __init__(self, holder: HolderNote) -> None:
        super().__init__("Gave up waiting for the test suite lock")
        self.holder = holder


class HeldLock:
    """The lock, held on ``handle``: closing it lets the lock go, and so does
    dropping the last reference to this object."""

    def __init__(self, handle: IO[str]) -> None:
        self._handle = handle

    def release(self) -> None:
        self._handle.close()


def suite_lock_file(env: Mapping[str, str] = os.environ) -> Path | None:
    """The lock's file, or None where no lock is taken: outside KubeCoder, as
    in CI, or beside no spec repo."""
    if not env.get("KUBECODER_ENVIRONMENT_ID") or not SPEC_REPO.exists():
        return None
    return LOCK_FILE


def read_holder_note(file: Path) -> HolderNote:
    try:
        text = file.read_text()
    except FileNotFoundError:
        # No file yet: no holder has written one.
        return {}
    note: HolderNote = {}
    for line in text.split("\n"):
        key, separator, value = line.partition(": ")
        if key and separator:
            note[key] = value
    return note


def acquire_suite_lock(
    file: Path,
    *,
    wait_seconds: float | None,
    holder: HolderNote,
    on_wait: Callable[[HolderNote], None] | None = None,
) -> HeldLock:
    """Take the lock on ``file``, waiting at most ``wait_seconds``, or without
    a bound when it is None, and write ``holder`` into it once taken.
    ``on_wait`` hears the holder's note if the lock is not taken within
    WAIT_NOTICE_SECONDS. Raises SuiteLockTimeout when the wait runs out."""
    file.parent.mkdir(parents=True, exist_ok=True)
    handle = file.open("a")
    deadline = None if wait_seconds is None else time.monotonic() + wait_seconds
    notice = time.monotonic() + WAIT_NOTICE_SECONDS
    if not _take(handle, notice if deadline is None else min(notice, deadline)):
        if on_wait is not None and (deadline is None or deadline > notice):
            on_wait(read_holder_note(file))
        if not _take(handle, deadline):
            handle.close()
            raise SuiteLockTimeout(read_holder_note(file))
    file.write_text("".join(f"{key}: {value}\n" for key, value in holder.items()))
    return HeldLock(handle)


def _take(handle: IO[str], until: float | None) -> bool:
    """Take the lock on ``handle``: blocking without a bound when ``until`` is
    None, else trying again until the monotonic time ``until``."""
    if until is None:
        fcntl.flock(handle, fcntl.LOCK_EX)
        return True
    while True:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            remaining = until - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(RETRY_SECONDS, remaining))


def hold_suite_lock() -> HeldLock | None:
    """Take the test suite lock for this run, or none where none is taken.
    The run holds it for as long as it references the lock it is handed.
    PYTEST_SUITE_LOCK_WAIT bounds the wait in seconds; a run that gives up
    ends here with LOCK_TIMEOUT_EXIT_CODE, having run nothing."""
    file = suite_lock_file()
    if file is None:
        return None

    configured = os.environ.get("PYTEST_SUITE_LOCK_WAIT")
    wait_seconds = float(configured) if configured else None
    # Only a bounded wait gives up.
    limit = "" if wait_seconds is None else _format_seconds(wait_seconds)

    def say_waiting(holder: HolderNote) -> None:
        print(
            f"⏳ Waiting{limit and f' up to {limit}'} for the test suite lock, "
            f"held by {describe_holder(holder)}",
            flush=True,
        )

    try:
        lock = acquire_suite_lock(
            file,
            wait_seconds=wait_seconds,
            holder={
                "environment": os.environ["KUBECODER_ENVIRONMENT_ID"],
                "host": gethostname(),
                "pid": str(os.getpid()),
                "started": datetime.now(UTC)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
            },
            on_wait=say_waiting,
        )
    except SuiteLockTimeout as error:
        pytest.exit(
            f"⛔ Gave up after {limit} waiting for the test suite lock, held by "
            f"{describe_holder(error.holder)}. No test ran, so none failed: run "
            f"the suite again once that run is done ({file}). "
            f"Exit code {LOCK_TIMEOUT_EXIT_CODE}.",
            returncode=LOCK_TIMEOUT_EXIT_CODE,
        )
    print(f"🔒 Holding the test suite lock ({file})", flush=True)
    return lock


def describe_holder(holder: HolderNote, now: datetime | None = None) -> str:
    if not holder.get("environment"):
        return "a run that left no note"
    since = ""
    try:
        started = datetime.fromisoformat(holder.get("started", ""))
    except ValueError:
        pass
    else:
        elapsed = (now or datetime.now(UTC)) - started
        since = f", running for {max(0, round(elapsed.total_seconds() / 60))} min"
    return (
        f"the run in {holder['environment']} "
        f"(pid {holder.get('pid', '?')} on {holder.get('host', '?')}{since})"
    )


def _format_seconds(seconds: float) -> str:
    if seconds > 0 and seconds % 60 == 0:
        return f"{seconds / 60:g} min"
    return f"{seconds:g} s"
