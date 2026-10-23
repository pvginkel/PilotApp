"""The fake controller served over real HTTP, as the client meets the real one."""

import threading
from pathlib import Path

from dependency_injector import providers
from werkzeug.serving import make_server

from app.services.container import ServiceContainer
from app.services.controller_client import ControllerClient
from app.services.fake_controller import FakeController
from app.services.health_service import HealthService
from tests.support.tls import InventedCa

FAKE_CONTROLLER_TOKEN = "fake-controller-token"

_RAW = Path(__file__).resolve().parent.parent / "fixtures" / "raw"


def raw_turn(name: str) -> list[str]:
    """The lines of `tests/fixtures/raw/<name>.jsonl`, an invented turn in the
    shapes of `claude`'s stream-json."""
    return (_RAW / f"{name}.jsonl").read_text().splitlines()


class ServedFakeController(FakeController):
    """The fake, served on a free port of 127.0.0.1 by a thread of its own;
    `url` is its base URL. With `tls` it serves HTTPS under that authority's
    certificate."""

    def __init__(self, keepalive_seconds: float, tls: InventedCa | None = None) -> None:
        super().__init__(FAKE_CONTROLLER_TOKEN, keepalive_seconds)
        ssl_context = None
        if tls is not None:
            ssl_context = (str(tls.cert_file), str(tls.key_file))
        self._server = make_server(
            "127.0.0.1", 0, self, threaded=True, ssl_context=ssl_context
        )
        scheme = "http" if tls is None else "https"
        self.url = f"{scheme}://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="fake-controller", daemon=True
        )
        self._thread.start()

    def close(self) -> None:
        super().close()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()


def client_of(
    container: ServiceContainer, fake_controller: ServedFakeController
) -> ControllerClient:
    """The real client on ``fake_controller``, made ``container``'s client. Its
    readiness check is on a health service of its own."""
    client = ControllerClient(
        base_url=fake_controller.url,
        token=FAKE_CONTROLLER_TOKEN,
        health_service=HealthService(
            lifecycle_coordinator=container.lifecycle_coordinator(),
            settings=container.config(),
        ),
        outage=container.controller_outage(),
    )
    container.controller_client.override(providers.Object(client))
    return client
