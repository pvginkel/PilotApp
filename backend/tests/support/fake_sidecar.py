"""The fake sidecar (design 1 §11): the store's tree and the sidecar's shadow
as dicts, the real sync routes driven through Flask's test client as the
store's sidecar drives them, with its bearer and the three headers, and the
change events the bus delivers applied as the sidecar applies them."""

from dataclasses import dataclass
from urllib.parse import quote

from flask.testing import FlaskClient
from werkzeug.test import TestResponse

from app.engine.bus import EngineBus, EngineEvent, TreeHashMoved
from app.services.sync_service import SYNC_PROTOCOL_MAX

SYNC_TOKEN = "example-sync-token"
"""The store's bearer, as the suite's app is configured with it."""

STORE_ENVIRONMENT_ID = "example-env-1"
"""The store environment's id, as the suite's app is configured with it."""


@dataclass(frozen=True)
class Put:
    """What a sync PUT answered: `content` the bytes the file must now hold,
    none on a 204; `hash` the hash it holds once answered; `faults` the count
    of Save Errors the save raised on the path."""

    status: int
    content: bytes | None
    hash: str
    stale: bool
    faults: int


class FakeSidecar:
    """The sidecar of the store's environment, with `/work/Projects` as
    `tree`: path to bytes, the paths from the tree's root.

    `shadow` holds each path's hash as last synced. `events` is every event
    the bus delivered since the sidecar started, in order.
    """

    def __init__(self, client: FlaskClient, bus: EngineBus) -> None:
        self.client = client
        self.bus = bus
        self.tree: dict[str, bytes] = {}
        self.shadow: dict[str, str] = {}
        self.events: list[EngineEvent] = []
        self._drained = 0
        bus.subscribe(self.events.append)

    def close(self) -> None:
        self.bus.unsubscribe(self.events.append)

    def put(self, path: str, content: bytes, base_hash: str | None) -> TestResponse:
        """`PUT /api/sync/files/<path>` as the sidecar sends it."""
        return self.client.put(
            _url(path),
            data=content,
            headers={
                **sync_headers(),
                "Content-Type": "application/octet-stream",
                "X-Pilot-Base-Hash": base_hash or "none",
            },
        )

    def get(self, path: str) -> TestResponse:
        """`GET /api/sync/files/<path>` as the sidecar sends it."""
        return self.client.get(_url(path), headers=sync_headers())

    def save(self, path: str, content: str | bytes) -> Put:
        """The agent writes `path`: the sidecar puts the file with its shadow
        hash as the base, writes the bytes the answer carries in place, and
        records the answer's hash."""
        data = content.encode() if isinstance(content, str) else content
        self.tree[path] = data
        response = self.put(path, data, self.shadow.get(path))
        assert response.status_code in (200, 204), response.get_data(as_text=True)
        answer = Put(
            status=response.status_code,
            content=response.get_data() if response.status_code == 200 else None,
            hash=response.headers["X-Pilot-Hash"],
            stale=response.headers.get("X-Pilot-Stale") == "true",
            faults=int(response.headers["X-Pilot-Faults"]),
        )
        if answer.content is not None:
            self.tree[path] = answer.content
        self.shadow[path] = answer.hash
        return answer

    def drain(self) -> list[str]:
        """Apply the change events delivered since the last drain: fetch and
        write each path whose hash differs from the shadow; an event of the
        sidecar's own write is ignored. Returns the paths fetched, in
        order."""
        fetched: list[str] = []
        while self._drained < len(self.events):
            event = self.events[self._drained]
            self._drained += 1
            if not isinstance(event, TreeHashMoved):
                continue
            if self.shadow.get(event.path) == event.hash:
                continue
            response = self.get(event.path)
            assert response.status_code == 200, response.get_data(as_text=True)
            self.tree[event.path] = response.get_data()
            self.shadow[event.path] = response.headers["X-Pilot-Hash"]
            fetched.append(event.path)
        return fetched

    def text(self, path: str) -> str:
        """What the agent reads at `path`."""
        return self.tree[path].decode()


def sync_headers() -> dict[str, str]:
    """The headers every call of the store's sidecar carries."""
    return {
        "Authorization": f"Bearer {SYNC_TOKEN}",
        "X-Pilot-Environment": STORE_ENVIRONMENT_ID,
        "X-Pilot-Sync-Protocol": str(SYNC_PROTOCOL_MAX),
    }


def _url(path: str) -> str:
    return f"/api/sync/files/{quote(path)}"
