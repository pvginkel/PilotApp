#!/usr/bin/env python3
"""Wait until the services the backend suite needs answer, or fail clearly.

The suite runner (tools/suite_runner/local.py at the repo root) runs this after
the backend install and before the suites. In CI the services are containers
in the validation Job's pod and start together with the suite, so they may not
answer yet. Locally they are the environment's sidecars, and this returns at
once.

It reads the same settings as the suite: .env, then .env.test over it.

- PostgreSQL at TEST_DATABASE_ADMIN_URL, the server the suite creates its
  databases on, until it accepts a login. A TCP connect is not enough: the
  server takes connections before it can serve them.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from sqlalchemy import make_url

TIMEOUT_SECONDS = 60
INTERVAL_SECONDS = 1

# Keep in step with tests/conftest_infrastructure.py.
DEFAULT_ADMIN_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/postgres"

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _wait(label: str, probe: Callable[[], None]) -> bool:
    """Call probe until it stops raising, for up to TIMEOUT_SECONDS."""
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while True:
        try:
            probe()
            return True
        except Exception as exc:
            if time.monotonic() >= deadline:
                print(
                    f"{label} did not answer within {TIMEOUT_SECONDS} s: {exc}",
                    file=sys.stderr,
                )
                return False
        time.sleep(INTERVAL_SECONDS)


def _wait_for_postgres() -> bool:
    url = make_url(os.environ.get("TEST_DATABASE_ADMIN_URL", DEFAULT_ADMIN_URL))
    # psycopg takes a plain conninfo, not SQLAlchemy's postgresql+psycopg URL.
    conninfo = url.set(drivername="postgresql").render_as_string(hide_password=False)

    def probe() -> None:
        with psycopg.connect(conninfo, connect_timeout=3) as conn:
            conn.execute("SELECT 1")

    label = f"PostgreSQL at {url.render_as_string(hide_password=True)}"
    return _wait(label, probe)


def main() -> int:
    env_file = _BACKEND_DIR / ".env"
    test_env_file = _BACKEND_DIR / ".env.test"
    if env_file.exists():
        load_dotenv(env_file)
    if test_env_file.exists():
        load_dotenv(test_env_file, override=True)

    ok = True
    ok = _wait_for_postgres() and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
