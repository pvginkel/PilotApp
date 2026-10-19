"""The fake controller served over real HTTP, as the client meets the real one."""

import threading
from pathlib import Path

from werkzeug.serving import make_server

from app.services.fake_controller import FakeController

FAKE_CONTROLLER_TOKEN = "fake-controller-token"

_RAW = Path(__file__).resolve().parent.parent / "fixtures" / "raw"


def raw_turn(name: str) -> list[str]:
    """The lines of `tests/fixtures/raw/<name>.jsonl`, an invented turn in the
    shapes of `claude`'s stream-json."""
    return (_RAW / f"{name}.jsonl").read_text().splitlines()


class ServedFakeController(FakeController):
    """The fake, served on a free port of 127.0.0.1 by a thread of its own;
    `url` is its base URL."""

    def __init__(self, keepalive_seconds: float) -> None:
        super().__init__(FAKE_CONTROLLER_TOKEN, keepalive_seconds)
        self._server = make_server("127.0.0.1", 0, self, threaded=True)
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="fake-controller", daemon=True
        )
        self._thread.start()

    def close(self) -> None:
        super().close()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
