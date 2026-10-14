"""Smoke test: the app starts and answers its liveness probe.

Generated once and app-owned, like conftest.py. It gives a fresh app one test,
so `pytest` does not exit 5 ("no tests collected") and fail `poetry run check`
before the app has tests of its own.
"""

from flask.testing import FlaskClient


def test_liveness_answers(client: FlaskClient) -> None:
    # Not readyz: readiness includes checks a unit test has no process for,
    # such as the SSE gateway.
    assert client.get("/health/healthz").status_code == 200
