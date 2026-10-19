"""The fake sidecar (design 1 §11): the store's tree and the sidecar's shadow
as dicts, the real sync routes driven through Flask's test client as the
store's sidecar drives them, with its bearer and the three headers, the change
events the bus delivers applied as the sidecar applies them, and the manifest
reconcile run as the sidecar runs it."""

import hashlib
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from flask.testing import FlaskClient
from werkzeug.test import TestResponse

from app.engine.bus import EngineBus, EngineEvent, TreeHashMoved
from app.services.sync_service import SYNC_PROTOCOL_MAX

SYNC_TOKEN = "example-sync-token"
"""The store's bearer, as the suite's app is configured with it."""

STORE_ENVIRONMENT_ID = "example-env-1"
"""The store environment's id, as the suite's app is configured with it."""

STRAY = "not a document of the record — files are born through `add_item`"
"""The local note on a file the record never bore (design 1 §5.5, D10)."""


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

    `shadow` holds each path's hash as last synced. `notes` holds the local
    notes the hook prints, by path. `events` is every event the bus delivered
    since the sidecar started, in order.
    """

    def __init__(self, client: FlaskClient, bus: EngineBus) -> None:
        self.client = client
        self.bus = bus
        self.tree: dict[str, bytes] = {}
        self.shadow: dict[str, str] = {}
        self.notes: dict[str, str] = {}
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

    def post_manifest(
        self, tree: dict[str, str], shadow: dict[str, str]
    ) -> TestResponse:
        """`POST /api/sync/manifest` as the sidecar sends it."""
        return self.client.post(
            "/api/sync/manifest",
            json={"tree": tree, "shadow": shadow},
            headers=sync_headers(),
        )

    def write(self, path: str, content: str | bytes) -> None:
        """The agent writes `path` while the sidecar is not looking: nothing
        goes up until it next reconciles."""
        self.tree[path] = content.encode() if isinstance(content, str) else content

    def remove(self, path: str) -> None:
        """The agent deletes `path` while the sidecar is not looking; a local
        note on it goes with it."""
        del self.tree[path]
        self.notes.pop(path, None)

    def upload(self, path: str) -> Put | None:
        """The sidecar puts the file at `path` with its shadow hash as the
        base, writes the bytes the answer carries in place, and records the
        answer's hash. A path the server answers 404 stays in the tree with a
        local note, and the answer is none (design 1 §5.5, D10)."""
        response = self.put(path, self.tree[path], self.shadow.get(path))
        if response.status_code == 404:
            self.notes[path] = STRAY
            return None
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
        self.notes.pop(path, None)
        return answer

    def save(self, path: str, content: str | bytes) -> Put:
        """The agent writes `path` and the sidecar uploads it, a path the
        server takes."""
        self.write(path, content)
        answer = self.upload(path)
        assert answer is not None, f"{path} is not a path of the record"
        return answer

    def connect(self) -> dict[str, Any]:
        """The sidecar (re)connects: it reconciles (design 1 §5.8)."""
        return self.reconcile()

    def overflow(self) -> dict[str, Any]:
        """The watch overflows: the sidecar takes the tree, walked whole, as
        the tree the reconcile starts from, and reconciles (design 1 §5.8)."""
        return self.reconcile()

    def reconcile(self) -> dict[str, Any]:
        """Design 1 §5.5: every file whose hash on disk is not the shadow's
        goes up first; then the tree's hashes and the shadow's are posted;
        then each path to write down is fetched and written, and each path to
        delete removed from the tree and the shadow. Returns the server's
        answer."""
        for path in sorted(self.tree):
            if _sha256(self.tree[path]) != self.shadow.get(path):
                self.upload(path)
        response = self.post_manifest(
            {path: _sha256(content) for path, content in self.tree.items()},
            dict(self.shadow),
        )
        assert response.status_code == 200, response.get_data(as_text=True)
        answer: dict[str, Any] = response.json
        for entry in answer["write_down"]:
            self._fetch(entry["path"])
        for path in answer["delete"]:
            self.tree.pop(path, None)
            del self.shadow[path]
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
            self._fetch(event.path)
            fetched.append(event.path)
        return fetched

    def text(self, path: str) -> str:
        """What the agent reads at `path`."""
        return self.tree[path].decode()

    def _fetch(self, path: str) -> None:
        """Write the bytes `path` must hold, as the server answers them, and
        record their hash."""
        response = self.get(path)
        assert response.status_code == 200, response.get_data(as_text=True)
        self.tree[path] = response.get_data()
        self.shadow[path] = response.headers["X-Pilot-Hash"]
        self.notes.pop(path, None)


def sync_headers() -> dict[str, str]:
    """The headers every call of the store's sidecar carries."""
    return {
        "Authorization": f"Bearer {SYNC_TOKEN}",
        "X-Pilot-Environment": STORE_ENVIRONMENT_ID,
        "X-Pilot-Sync-Protocol": str(SYNC_PROTOCOL_MAX),
    }


def _url(path: str) -> str:
    return f"/api/sync/files/{quote(path)}"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
