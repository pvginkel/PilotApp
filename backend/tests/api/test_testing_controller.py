"""The fake controller mounted under /api/testing/controller (design 2 §12)."""

import threading
from collections.abc import Generator

import pytest
from dependency_injector import providers
from flask import Flask
from werkzeug.serving import make_server

from app.app_config import AppSettings
from app.config import Settings, Stage
from app.services.controller_client import (
    ControllerClient,
    HeadlessCreateRequest,
    RawFrame,
    ResultFrame,
    SessionsFrame,
)
from app.services.controller_outage import ControllerOutage
from app.services.fake_controller import FakeController, FakeControllerProblem
from app.services.health_service import HealthService
from tests.conftest_infrastructure import _create_test_app, _dispose_app

PREFIX = "/api/testing/controller"
TOKEN = "mounted-token"


@pytest.fixture
def mounted(app: Flask) -> FakeController:
    """The fake the mount serves, its credential ``TOKEN``."""
    fake = FakeController(TOKEN, keepalive_seconds=0.1)
    app.container.fake_controller.override(providers.Object(fake))
    return fake


@pytest.fixture
def backend_url(app: Flask, mounted: FakeController) -> Generator[str]:
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


class TestTestingControllerApi:
    def test_it_serves_the_fakes_routes_and_verbs_in_testing_mode(
        self, app: Flask, mounted: FakeController
    ) -> None:
        client = app.test_client()

        added = client.post(f"{PREFIX}/fake/add-environment", json={"env_id": "env-1"})
        listing = client.get(
            f"{PREFIX}/environments", headers={"Authorization": f"Bearer {TOKEN}"}
        )
        refused = client.get(f"{PREFIX}/environments")

        assert added.status_code == 204
        assert listing.status_code == 200
        assert [e["envId"] for e in listing.get_json()["items"]] == ["env-1"]
        assert refused.status_code == 401

    def test_the_client_drives_a_turn_through_the_mount(
        self, app: Flask, mounted: FakeController, backend_url: str
    ) -> None:
        mounted.add_environment("env-1")
        client = ControllerClient(
            f"{backend_url}{PREFIX}",
            TOKEN,
            HealthService(
                app.container.lifecycle_coordinator(), app.container.config()
            ),
            ControllerOutage(),
        )

        with client.open_fleet_stream() as fleet:
            seed = next(iter(fleet))
        assert client.start_environment("env-1").started is True
        name = client.create_headless_session("env-1", HeadlessCreateRequest()).name
        client.send_message("env-1", name, "Check the badge.")
        mounted.play("env-1", name, ["a line"])
        mounted.finish("env-1", name)
        with client.open_response_stream("env-1", name, 0) as stream:
            frames = list(stream)

        assert seed == SessionsFrame("env-1", ())
        assert frames[0] == RawFrame(7, "a line")
        assert isinstance(frames[1], ResultFrame)
        assert client.check_readiness().passed

    def test_the_client_writes_reads_and_lists_files_through_the_mount(
        self, app: Flask, mounted: FakeController, backend_url: str
    ) -> None:
        mounted.add_environment("env-1")
        client = ControllerClient(
            f"{backend_url}{PREFIX}",
            TOKEN,
            HealthService(
                app.container.lifecycle_coordinator(), app.container.config()
            ),
            ControllerOutage(),
        )

        client.write_file("env-1", "/work/Example/a.md", b"# Answered\n")
        content = client.read_file("env-1", "/work/Example/a.md")
        files = client.list_folder_files("env-1", "/work")

        assert content.data == b"# Answered\n"
        assert mounted.file_text("env-1", "/work/Example/a.md") == "# Answered\n"
        assert files == ["/work/Example/a.md"]

    @pytest.mark.parametrize(
        "update",
        [{"flask_env": "development"}, {"stage": Stage("prd")}],
        ids=["outside-testing-mode", "testing-on-prd"],
    )
    def test_it_is_refused_outside_testing_mode(
        self,
        app: Flask,
        mounted: FakeController,
        test_settings: Settings,
        update: dict[str, object],
    ) -> None:
        app.container.config.override(test_settings.model_copy(update=update))

        response = app.test_client().post(
            f"{PREFIX}/fake/add-environment", json={"env_id": "env-1"}
        )

        assert response.status_code == 400
        assert response.get_json()["code"] == "ROUTE_NOT_AVAILABLE"
        with pytest.raises(FakeControllerProblem, match="no environment env-1"):
            mounted.environment("env-1")

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
            response = production.test_client().get(f"{PREFIX}/readyz")
        finally:
            _dispose_app(production)

        assert response.status_code == 400
