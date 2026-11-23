"""The fake collector served over real HTTP, as the backend's reads meet the
real one."""

import threading
from collections.abc import Callable
from datetime import UTC, datetime

from pilot_collection.reading import ReadingSchema
from werkzeug.serving import make_server
from werkzeug.wrappers import Request, Response

from app.services.fake_collector import FakeCollector
from tests.support.publications import COLLECTOR_TOKEN

WRITTEN_AT = datetime(2026, 11, 9, 9, 52, 7, 123456, tzinfo=UTC)
"""When `invented_reading`'s file was last written."""


def invented_reading(
    session_id: str = "4f1c9e2a-7b3d-4a68-9c05-e1d2b3a4f567",
    agent_id: str | None = None,
    written_at: datetime = WRITTEN_AT,
) -> ReadingSchema:
    """A reading of one Call, which says what was asked and answers it."""
    return ReadingSchema.model_validate(
        {
            "session_id": session_id,
            "agent_id": agent_id,
            "file_size": 4096,
            "file_modified_at": written_at,
            "calls": [
                {
                    "message_id": "msg_0001",
                    "received": [
                        {
                            "kind": "user",
                            "at": written_at,
                            "writer": "person",
                            "text": "Halve the soup for two",
                        }
                    ],
                    "sent": [
                        {"kind": "text", "at": written_at, "text": "Two bowls, then."}
                    ],
                }
            ],
            "after": [],
        }
    )


class ServedFakeCollector(FakeCollector):
    """The fake, under the test settings' collector bearer, served on a free
    port of 127.0.0.1 by a thread of its own; `url` is its base URL.
    `on_ask` runs at each ask of a reading, before the fake takes it."""

    def __init__(self) -> None:
        super().__init__(COLLECTOR_TOKEN)
        self.on_ask: Callable[[], None] | None = None
        self._server = make_server("127.0.0.1", 0, self, threaded=True)
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="fake-collector", daemon=True
        )
        self._thread.start()

    def _reading(
        self, request: Request, session_id: str, agent_id: str | None
    ) -> Response:
        if self.on_ask is not None:
            self.on_ask()
        return super()._reading(request, session_id, agent_id)

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
