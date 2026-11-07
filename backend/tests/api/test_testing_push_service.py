"""The fake push service mounted under /api/testing/push-service (TEST-1)."""

import threading
from collections.abc import Generator

import pytest
from dependency_injector import providers
from flask import Flask
from sqlalchemy.orm import Session
from werkzeug.serving import make_server

from app.app_config import AppSettings
from app.config import Settings, Stage
from app.models import User
from app.services.fake_push_service import FakePush, FakePushService
from app.services.push_subscription_service import PushSubscriptionService
from app.services.web_push import Push, VapidKey, WebPushService
from tests.conftest_infrastructure import _create_test_app, _dispose_app

PREFIX = "/api/testing/push-service"


@pytest.fixture
def mounted(app: Flask) -> FakePushService:
    """The fake the mount serves."""
    fake = FakePushService()
    app.container.fake_push_service.override(providers.Object(fake))
    return fake


@pytest.fixture
def backend_url(app: Flask, mounted: FakePushService) -> Generator[str]:
    """The session's app served over HTTP, as Playwright's backend is."""
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class TestTestingPushServiceApi:
    def test_it_issues_subscriptions_under_its_own_prefix(
        self, app: Flask, mounted: FakePushService, vapid_key: str
    ) -> None:
        client = app.test_client()

        subscribed = client.post(
            f"{PREFIX}/fake/subscribe",
            json={"application_server_key": VapidKey(vapid_key).public_key},
        )
        endpoint = subscribed.get_json()["endpoint"]
        pushes = client.post(f"{PREFIX}/fake/pushes", json={"endpoint": endpoint})

        assert subscribed.status_code == 200
        assert endpoint.startswith(f"http://localhost{PREFIX}/push/")
        assert (pushes.status_code, pushes.get_json()) == (200, [])

    def test_the_backend_pushes_to_a_browser_through_the_mount(
        self,
        session: Session,
        person: User,
        web_push_service: WebPushService,
        mounted: FakePushService,
        backend_url: str,
    ) -> None:
        browser = mounted.subscribe(
            web_push_service.public_key or "", origin=f"{backend_url}{PREFIX}"
        )
        PushSubscriptionService(session).subscribe(
            person, browser.endpoint, browser.keys.p256dh, browser.keys.auth
        )
        push = Push("Garden sensors", "Pick the board", "project-1", backend_url, True)

        assert web_push_service.push(person.id, push, session)

        assert mounted.pushes(browser.endpoint) == [
            FakePush(
                "Garden sensors",
                "Pick the board",
                "project-1",
                backend_url,
                True,
                "high",
                86400,
            )
        ]

    @pytest.mark.parametrize(
        "update",
        [{"flask_env": "development"}, {"stage": Stage("prd")}],
        ids=["outside-testing-mode", "testing-on-prd"],
    )
    def test_it_is_refused_outside_testing_mode(
        self,
        app: Flask,
        mounted: FakePushService,
        test_settings: Settings,
        vapid_key: str,
        update: dict[str, object],
    ) -> None:
        app.container.config.override(test_settings.model_copy(update=update))

        response = app.test_client().post(
            f"{PREFIX}/fake/subscribe",
            json={"application_server_key": VapidKey(vapid_key).public_key},
        )

        assert response.status_code == 400
        assert response.get_json()["code"] == "ROUTE_NOT_AVAILABLE"

    def test_a_production_app_refuses_it(self, test_settings: Settings) -> None:
        production = _create_test_app(
            test_settings.model_copy(
                update={"flask_env": "production", "stage": Stage("prd")}
            ),
            AppSettings(),
        )
        try:
            response = production.test_client().post(f"{PREFIX}/fake/reset")
        finally:
            _dispose_app(production)

        assert response.status_code == 400
