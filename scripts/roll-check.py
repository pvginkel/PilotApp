#!/usr/bin/env python3
"""The roll check: watch pilot-dev from before a push until its old pod is gone.

Usage:
    scripts/roll-check.py [--timeout SECONDS] -- <push command...>

For example, in the background:
    timeout 2100 scripts/roll-check.py -- git push origin main

pilot-dev rolls by starting the new pod beside the old one and retiring the old
one once the new one is ready (docs/slice-test-plan.md § The roll check). The
check rides the roll a push causes, and holds the push until it is measuring:

1. It lists pilot-dev's pods, up to three tries of 10 s each, and stops unless
   the listing names exactly one pod, the old one, in tmp/roll/old.
2. It reads the site (`/`, the UI's nginx, 200) and `/api/auth/self` (the
   backend through that nginx, 401: no session) every half second, each
   answer's UTC time, status and URL appended to tmp/roll/probes.
3. Once both URLs have answered, it runs the push command, its output passed
   through. A push that fails ends the check.
4. It lists the pods every 5 s, appended to tmp/roll/pods with the time, until
   the old pod is gone, its termination included, or until --timeout (1800 s)
   after the push.
5. It prints how often each URL gave each status, the failed reads' first and
   last times, and the pod the roll produced, also in tmp/roll/new.

Exit status:
    0  the old pod is gone and every read answered as expected
    1  a read failed: a status other than the URL's own (000 is no answer)
    2  the old pod outlived the check, every read as expected
    3  both: a read failed and the old pod outlived the check
    4  no check: the pod listing failed, or named no pod or two (a roll under
       way); the push was not run
    5  the push command failed; nothing was measured
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tmp" / "roll"

PROBES = {
    "https://pilot-dev.home/": 200,
    "https://pilot-dev.home/api/auth/self": 401,
}
"""Each URL the check reads, and the status it answers when nothing is wrong."""

LIST_PODS = [
    "cexec", "iac", "kubectl", "-n", "pilot-dev", "get", "pods",
    "-l", "app.kubernetes.io/name=pilot", "--no-headers", "--request-timeout=10s",
]  # fmt: skip
FIRST_LISTING_TRIES = 3
PROBE_INTERVAL = 0.5
PROBE_TIMEOUT = 5
LIST_INTERVAL = 5


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _now() -> str:
    return datetime.now(UTC).strftime("%H:%M:%S.%f")[:-3]


def _status(url: str) -> str:
    """The URL's status as curl's `%{http_code}` gives it, `000` for none."""
    try:
        with _opener.open(url, timeout=PROBE_TIMEOUT) as response:
            return str(response.status)
    except urllib.error.HTTPError as error:
        return str(error.code)
    except Exception:
        return "000"


class Probes:
    """Two readers, one per URL, appending every answer to tmp/roll/probes."""

    def __init__(self) -> None:
        self.answers: list[tuple[str, str, str]] = []
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.file = (OUT / "probes").open("a", buffering=1)
        self.threads = [
            threading.Thread(target=self._read, args=(url,), daemon=True)
            for url in PROBES
        ]

    def start(self) -> None:
        for thread in self.threads:
            thread.start()

    def _read(self, url: str) -> None:
        while not self.stop.is_set():
            status = _status(url)
            at = _now()
            with self.lock:
                self.answers.append((at, status, url))
                self.file.write(f"{at} {status} {url}\n")
            self.stop.wait(PROBE_INTERVAL)

    def measuring(self) -> bool:
        with self.lock:
            return {url for _, _, url in self.answers} == set(PROBES)

    def end(self) -> None:
        self.stop.set()
        for thread in self.threads:
            thread.join(PROBE_TIMEOUT + 1)
        self.file.close()

    def failed(self) -> list[tuple[str, str, str]]:
        with self.lock:
            return [a for a in self.answers if a[1] != str(PROBES[a[2]])]

    def tally(self) -> list[str]:
        with self.lock:
            counts = Counter((url, status) for _, status, url in self.answers)
        return [
            f"{count:7d} {url} {status}"
            for (url, status), count in sorted(counts.items())
        ]


def _pods() -> list[str] | None:
    """The pods' lines, or None when the listing failed."""
    result = subprocess.run(LIST_PODS, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line.strip()]


def _first_listing() -> list[str] | None:
    for attempt in range(1, FIRST_LISTING_TRIES + 1):
        pods = _pods()
        if pods is not None:
            return pods
        print(f"roll-check: pod listing {attempt} of {FIRST_LISTING_TRIES} failed")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("push", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    push = args.push[1:] if args.push[:1] == ["--"] else args.push
    if not push:
        parser.error("the push command is missing: ... -- <push command...>")

    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.iterdir():
        stale.unlink()

    pods = _first_listing()
    if pods is None or len(pods) != 1:
        if pods is None:
            print("roll-check: no check: the pod listing failed three times")
        else:
            print(f"roll-check: no check: {len(pods)} pods, not one")
            print("\n".join(pods))
        print("roll-check: the push was not run")
        return 4
    old = pods[0].split()[0]
    (OUT / "old").write_text(f"{old}\n")
    print(f"roll-check: the old pod is {old}")

    probes = Probes()
    probes.start()
    try:
        while not probes.measuring():
            time.sleep(0.1)
        print(f"roll-check: measuring since {_now()}; pushing: {' '.join(push)}")
        if subprocess.run(push, check=False).returncode != 0:
            print("roll-check: the push failed; nothing was measured")
            return 5

        deadline = time.monotonic() + args.timeout
        now: list[str] = pods
        gone = False
        with (OUT / "pods").open("a", buffering=1) as log:
            while time.monotonic() < deadline:
                listed = _pods()
                if listed is not None:
                    now = listed
                    at = datetime.now(UTC).strftime("%H:%M:%S")
                    log.writelines(f"{at} {line}\n" for line in listed)
                    if not any(line.split()[0] == old for line in listed):
                        gone = True
                        break
                time.sleep(LIST_INTERVAL)
    finally:
        probes.end()

    new = [line.split()[0] for line in now if line.split()[0] != old]
    (OUT / "new").write_text("".join(f"{name}\n" for name in new))
    print("roll-check: the reads, by URL and status:")
    print("\n".join(probes.tally()))
    failed = probes.failed()
    if failed:
        print(
            f"roll-check: {len(failed)} reads failed,"
            f" the first at {failed[0][0]}, the last at {failed[-1][0]}"
            " (tmp/roll/probes and tmp/roll/pods have each)"
        )
    if gone:
        print(f"roll-check: the old pod {old} is gone; the new pod: {' '.join(new)}")
    else:
        print(f"roll-check: the old pod {old} outlived the check ({args.timeout} s)")
    return (1 if failed else 0) | (0 if gone else 2)


if __name__ == "__main__":
    sys.exit(main())
