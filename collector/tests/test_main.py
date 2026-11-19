"""The collector as a process."""

import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

from tests.support import filed, typed

_SETTINGS = ("COLLECTOR_PILOT_URL", "COLLECTOR_TOKEN", "COLLECTOR_HOME")


def _started(**settings: str) -> subprocess.Popen[str]:
    """`python -m pilot_collector` under those settings and no others of
    the collector's."""
    environment = {
        name: value for name, value in os.environ.items() if name not in _SETTINGS
    }
    return subprocess.Popen(
        [sys.executable, "-m", "pilot_collector"],
        env=environment | settings,
        stderr=subprocess.PIPE,
        text=True,
    )


class TestTheProcess:
    def test_it_walks_until_it_is_told_to_stop(self, tmp_path: Path) -> None:
        """Nothing listens where it calls, so each walk ends at its
        inventory; SIGTERM ends the process between walks."""
        filed(tmp_path / "projects", [typed(0)])
        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            process = _started(
                COLLECTOR_PILOT_URL=f"http://127.0.0.1:{taken.getsockname()[1]}",
                COLLECTOR_TOKEN="an-invented-collector-token",
                COLLECTOR_HOME=str(tmp_path),
            )
            try:
                assert process.stderr is not None
                logged = process.stderr.readline()
                process.send_signal(signal.SIGTERM)
                exited = process.wait(timeout=10)
            finally:
                process.kill()
                process.wait()

        assert "WARNING pilot_collector.walk: The walk ended early: Pilot did not" in (
            logged
        )
        assert exited == 0

    def test_it_does_not_start_without_its_settings(self) -> None:
        process = _started()
        _, said = process.communicate(timeout=10)

        assert process.returncode == 1
        for name in _SETTINGS:
            assert f"{name}\n  Field required" in said
