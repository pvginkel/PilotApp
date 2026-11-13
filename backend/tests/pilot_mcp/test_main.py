"""`python -m pilot_mcp`, the image's second entry point, as the pod runs it:
listening where its settings say, its probes up, its endpoint behind the
bearer, and shut down on SIGTERM; its projects surface closed while its
settings are unset, and behind its token once they are set."""

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


_PROJECTS = {
    "PILOT_MCP_PROJECTS_TOKEN": "a-shared-token",
    "PILOT_MCP_TOKEN_URL": "https://auth.example.com/realms/test/token",
    "PILOT_MCP_SERVICE_CLIENT_ID": "pilot-test-service",
    "PILOT_MCP_SERVICE_CLIENT_SECRET": "a-client-secret",
}
"""The projects surface's four settings."""

_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}

_ACCEPT = {"Accept": "application/json, text/event-stream"}


def _serve(port: int, settings: dict[str, str]) -> subprocess.Popen[bytes]:
    """The entry point on `port`, with `settings` and none of the projects
    surface's but those among them."""
    inherited = {
        name: value for name, value in os.environ.items() if name not in _PROJECTS
    }
    return subprocess.Popen(
        [sys.executable, "-m", "pilot_mcp"],
        cwd=_BACKEND,
        env={
            **inherited,
            "PILOT_MCP_HOST": "127.0.0.1",
            "PILOT_MCP_PORT": str(port),
            **settings,
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _initialize(base: str, token: str) -> httpx.Response:
    return httpx.post(
        f"{base}/mcp/projects",
        json=_INITIALIZE,
        headers={**_ACCEPT, "Authorization": f"Bearer {token}"},
    )


class TestMain:
    def test_the_entry_point_serves_on_its_settings(self) -> None:
        port = _free_port()
        process = _serve(port, {})
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

    def test_without_its_settings_the_projects_surface_alone_is_closed(self) -> None:
        port = _free_port()
        settings = {
            name: value
            for name, value in _PROJECTS.items()
            if name != "PILOT_MCP_SERVICE_CLIENT_SECRET"
        }
        process = _serve(port, settings)
        try:
            base = f"http://127.0.0.1:{port}"
            ready = _ready(f"{base}/health/readyz", process)
            closed = _initialize(base, "a-shared-token")
            other = httpx.post(
                f"{base}/mcp",
                json=_INITIALIZE,
                headers={**_ACCEPT, "Authorization": "Bearer a-sessions-token"},
            )
        finally:
            process.terminate()
            _, log = process.communicate(timeout=10)

        assert ready.status_code == 200
        assert closed.status_code == 503
        assert other.status_code == 200
        assert (
            b"The projects surface refuses every call:"
            b" PILOT_MCP_SERVICE_CLIENT_SECRET unset"
        ) in log
        assert b"a-shared-token" not in log

    def test_with_its_settings_the_projects_surface_is_behind_its_token(self) -> None:
        port = _free_port()
        process = _serve(port, _PROJECTS)
        try:
            base = f"http://127.0.0.1:{port}"
            _ready(f"{base}/health/readyz", process)
            refused = _initialize(base, "another-token")
            admitted = _initialize(base, "a-shared-token")
        finally:
            process.terminate()
            _, log = process.communicate(timeout=10)

        assert refused.status_code == 401
        assert admitted.status_code == 200
        assert b"pilot-projects" in admitted.content
        assert b"refuses every call" not in log
        assert b"a-client-secret" not in log
