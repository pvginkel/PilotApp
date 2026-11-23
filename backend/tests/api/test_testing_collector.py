"""The fake collector mounted under /api/testing/collector (F122.5): a
backend whose COLLECTOR_URL is its own mount reads a conversation's reading
from it, with no process added."""

import threading
import uuid
from collections.abc import Generator

import pytest
from dependency_injector import providers
from flask import Flask
from werkzeug.serving import make_server

from app.config import Settings, Stage
from app.dashboard.readings import Gone, ReadingsService, Served
from app.models import Transcript
from app.services.fake_collector import FakeCollector
from tests.support.fake_collector import invented_reading
from tests.support.publications import COLLECTOR_TOKEN

PREFIX = "/api/testing/collector"
MAIN = "4f1c9e2a-7b3d-4a68-9c05-e1d2b3a4f567"


@pytest.fixture
def mounted(app: Flask) -> FakeCollector:
    """The fake the mount serves."""
    fake = FakeCollector(COLLECTOR_TOKEN)
    app.container.fake_collector.override(providers.Object(fake))
    return fake


@pytest.fixture
def backend_url(app: Flask, mounted: FakeCollector) -> Generator[str]:
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


class TestTestingCollectorApi:
    def test_the_backend_reads_a_reading_through_its_own_mount(
        self, mounted: FakeCollector, backend_url: str
    ) -> None:
        reading = invented_reading()
        mounted.serve(reading)
        service = ReadingsService(
            f"{backend_url}{PREFIX}", COLLECTOR_TOKEN, None, 64 * 1024 * 1024
        )
        thread = Transcript(id=uuid.uuid4(), session_id=MAIN, agent_id=None)

        first = service.read(thread)
        again = service.read(thread)
        mounted.gone(MAIN)

        assert first == again == Served(reading)
        assert [ask.status for ask in mounted.asks()] == [200, 304]
        assert service.read(thread) == Gone()

    def test_its_verbs_are_served_under_its_prefix(
        self, app: Flask, mounted: FakeCollector
    ) -> None:
        client = app.test_client()

        served = client.post(
            f"{PREFIX}/fake/serve",
            json={"reading": invented_reading().model_dump(mode="json")},
        )
        asks = client.post(f"{PREFIX}/fake/asks")

        assert served.status_code == 204
        assert (asks.status_code, asks.get_json()) == (200, [])

    @pytest.mark.parametrize(
        "update",
        [{"flask_env": "development"}, {"stage": Stage("prd")}],
        ids=["outside-testing-mode", "testing-on-prd"],
    )
    def test_it_is_refused_outside_testing_mode(
        self,
        app: Flask,
        mounted: FakeCollector,
        test_settings: Settings,
        update: dict[str, object],
    ) -> None:
        app.container.config.override(test_settings.model_copy(update=update))

        reading = app.test_client().get(f"{PREFIX}/readings/{MAIN}")
        verb = app.test_client().post(f"{PREFIX}/fake/asks")

        assert reading.status_code == verb.status_code == 400
        assert verb.get_json()["code"] == "ROUTE_NOT_AVAILABLE"
