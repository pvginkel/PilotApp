"""/api/testing/dashboard-bounds: the dashboard engine's timeout (F154.5),
set on the running app, for the specs that meet the engine's refusal of a
read."""

from collections.abc import Iterator

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app.services.container import ServiceContainer

BOUNDS = "/api/testing/dashboard-bounds"
ROWS = "/api/dashboard/rows"
STATE = "t=all&by=project&m=cost.sum"

# Shorter than any read takes: each is refused at its start.
NONE_LEFT = 1e-9


@pytest.fixture(autouse=True)
def _booted_bounds(client: FlaskClient) -> Iterator[None]:
    """The session app's engine back at the timeout it booted with."""
    yield
    assert client.put(BOUNDS, json={}).status_code == 200


class TestPutDashboardBounds:
    def test_the_reads_from_then_on_take_the_timeout(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        response = client.put(BOUNDS, json={"timeout_seconds": NONE_LEFT})

        assert response.status_code == 200
        assert response.get_json() == {"timeout_seconds": NONE_LEFT}
        assert container.dashboard_bounds().timeout_seconds == NONE_LEFT
        refused = client.get(ROWS, query_string={"state": STATE})
        assert refused.status_code == 409
        assert refused.get_json()["code"] == "QUERY_TIMEOUT"
        assert "ran past the engine's timeout of 1e-09 s" in refused.get_json()["error"]

    def test_a_timeout_left_out_is_the_one_the_app_booted_with(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        booted = container.app_config().dashboard_statement_timeout_seconds
        client.put(BOUNDS, json={"timeout_seconds": NONE_LEFT})

        response = client.put(BOUNDS, json={})

        assert response.get_json() == {"timeout_seconds": booted}
        assert container.dashboard_bounds().timeout_seconds == booted
        assert client.get(ROWS, query_string={"state": STATE}).status_code == 200

    @pytest.mark.parametrize("timeout", [0, -1, "soon"])
    def test_a_timeout_not_above_zero_is_refused(
        self, client: FlaskClient, container: ServiceContainer, timeout: object
    ) -> None:
        booted = container.app_config().dashboard_statement_timeout_seconds

        response = client.put(BOUNDS, json={"timeout_seconds": timeout})

        assert response.status_code == 400
        assert container.dashboard_bounds().timeout_seconds == booted

    def test_it_is_refused_in_production(
        self,
        app: Flask,
        client: FlaskClient,
        container: ServiceContainer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        booted = container.app_config().dashboard_statement_timeout_seconds
        monkeypatch.setattr(app.container.config(), "flask_env", "production")

        response = client.put(BOUNDS, json={"timeout_seconds": NONE_LEFT})

        assert response.status_code == 400
        monkeypatch.undo()
        assert container.dashboard_bounds().timeout_seconds == booted
