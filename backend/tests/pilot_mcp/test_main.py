"""`python -m pilot_mcp`, the image's second entry point, as the pod runs it:
listening where its settings say, its probes up, its endpoint behind the
bearer, and shut down on SIGTERM."""

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

_BACKEND = Path(__file__).resolve().parents[2]

_START_SECONDS = 30


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _ready(url: str, process: subprocess.Popen[bytes]) -> httpx.Response:
    """`url`'s first answer, once the process listens."""
    deadline = time.monotonic() + _START_SECONDS
    while time.monotonic() < deadline:
        assert process.poll() is None, "the server exited before it listened"
        try:
            return httpx.get(url)
        except httpx.ConnectError:
            time.sleep(0.1)
    raise AssertionError(f"nothing listened at {url} in {_START_SECONDS} s")


class TestMain:
    def test_the_entry_point_serves_on_its_settings(self) -> None:
        port = _free_port()
        process = subprocess.Popen(
            [sys.executable, "-m", "pilot_mcp"],
            cwd=_BACKEND,
            env={
                **os.environ,
                "PILOT_MCP_HOST": "127.0.0.1",
                "PILOT_MCP_PORT": str(port),
            },
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            base = f"http://127.0.0.1:{port}"
            ready = _ready(f"{base}/health/readyz", process)
            refused = httpx.post(f"{base}/mcp", json={})
        finally:
            process.terminate()
            _, log = process.communicate(timeout=10)

        assert ready.status_code == 200
        assert refused.status_code == 401
        # uvicorn shuts down, then exits by the signal it caught.
        assert b"Application shutdown complete." in log
        assert process.returncode == -signal.SIGTERM
