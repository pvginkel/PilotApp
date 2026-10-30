"""The fake notification bridge mounted under /api/testing/notification-bridge
(the Q1 ruling)."""

import threading
from collections.abc import Generator

import pytest
from dependency_injector import providers
from flask import Flask
from werkzeug.serving import make_server

from app.app_config import AppSettings
from app.config import Settings, Stage
from app.services.fake_notification_bridge import (
    FakeNotification,
    FakeNotificationBridge,
    FakeNotificationBridgeProblem,
)
from app.services.health_service import HealthService
from app.services.notification_bridge_client import (
    NotificationBridgeClient,
    NotificationBridgeRefused,
)
from tests.conftest_infrastructure import _create_test_app, _dispose_app

PREFIX = "/api/testing/notification-bridge"
TOKEN = "invented-mounted-token"


@pytest.fixture
def mounted(app: Flask) -> FakeNotificationBridge:
    """The fake the mount serves, with Ada's registration under ``TOKEN``."""
    fake = FakeNotificationBridge()
    fake.add_registration("ada", TOKEN)
    app.container.fake_notification_bridge.override(providers.Object(fake))
    return fake


@pytest.fixture
def backend_url(app: Flask, mounted: FakeNotificationBridge) -> Generator[str]:
    """The session's app served over HTTP, as Playwright's backend is."""
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        mounted.close()
        server.shutdown()
        server.server_close()
        thread.join()


class TestTestingNotificationBridgeApi:
    def test_it_serves_the_fakes_routes_and_verbs_in_testing_mode(
        self, app: Flask, mounted: FakeNotificationBridge
    ) -> None:
        client = app.test_client()

        added = client.post(
            f"{PREFIX}/fake/add-registration", json={"name": "bea", "token": "b"}
        )
        submitted = client.post(
            f"{PREFIX}/v1/submit",
            json={"sequence_id": "s", "message": "m"},
            headers={"Authorization": "Bearer b"},
        )
        refused = client.post(f"{PREFIX}/v1/dismiss", json={"sequence_id": "s"})
        shown = client.post(f"{PREFIX}/fake/shown", json={"name": "bea"})
        health = client.get(f"{PREFIX}/healthz")

        assert added.status_code == 204
        assert (submitted.status_code, submitted.get_json()) == (200, {"ntfy": "ok"})
        assert refused.status_code == 401
        assert list(shown.get_json()) == ["s"]
        assert (health.status_code, health.text) == (200, "ok")

    def test_the_client_submits_dismisses_and_sends_through_the_mount(
        self, app: Flask, mounted: FakeNotificationBridge, backend_url: str
    ) -> None:
        client = NotificationBridgeClient(
            f"{backend_url}{PREFIX}",
            HealthService(
                app.container.lifecycle_coordinator(), app.container.config()
            ),
        )

        client.submit(TOKEN, "project-1", message="Running", priority="min")
        client.submit(TOKEN, "project-2", message="1 waiting", priority="high")
        client.dismiss(TOKEN, "project-1")
        client.send_one_shot(TOKEN, message="Pilot will notify you here")
        with pytest.raises(NotificationBridgeRefused):
            client.dismiss("invented-unknown-token", "project-2")

        assert mounted.shown("ada") == {
            "project-2": FakeNotification(
                "project-2", "high", None, "1 waiting", None, True
            )
        }
        assert [n.message for n in mounted.one_shots("ada")] == [
            "Pilot will notify you here"
        ]
        assert client.check_readiness().passed

    @pytest.mark.parametrize(
        "update",
        [{"flask_env": "development"}, {"stage": Stage("prd")}],
        ids=["outside-testing-mode", "testing-on-prd"],
    )
    def test_it_is_refused_outside_testing_mode(
        self,
        app: Flask,
        mounted: FakeNotificationBridge,
        test_settings: Settings,
        update: dict[str, object],
    ) -> None:
        app.container.config.override(test_settings.model_copy(update=update))

        response = app.test_client().post(
            f"{PREFIX}/fake/add-registration", json={"name": "bea", "token": "b"}
        )

        assert response.status_code == 400
        assert response.get_json()["code"] == "ROUTE_NOT_AVAILABLE"
        with pytest.raises(FakeNotificationBridgeProblem, match="no registration bea"):
            mounted.shown("bea")

    def test_a_production_app_starts_with_it_and_refuses_it(
        self, test_settings: Settings
    ) -> None:
        production = _create_test_app(
            test_settings.model_copy(
                update={"flask_env": "production", "stage": Stage("prd")}
            ),
            AppSettings(),
        )
        try:
            response = production.test_client().get(f"{PREFIX}/healthz")
        finally:
            _dispose_app(production)

        assert response.status_code == 400
