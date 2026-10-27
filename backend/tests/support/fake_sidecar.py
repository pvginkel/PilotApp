"""The fake sidecar (design 1 §11): the store's tree and the sidecar's shadow
as dicts, the real sync routes driven through Flask's test client as the
store's sidecar drives them, with its bearer and the three headers, its change
stream read between steps and applied as the sidecar applies it, the manifest
reconcile run as the sidecar runs it, each project folder's write lock held
by a session whose saves its uploads carry, and the hook's release answered
with the text the agent is told."""

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from flask.testing import FlaskClient
from werkzeug.test import TestResponse

from app.services.sync_service import SYNC_PROTOCOL_MAX

SYNC_TOKEN = "example-sync-token"
"""The store's bearer, as the suite's app is configured with it."""

STORE_ENVIRONMENT_ID = "example-env-1"
"""The store environment's id, as the suite's app is configured with it."""

STRAY = "not a document of the record — files are born through `add_item`"
"""The local note on a file the record never bore (design 1 §5.5, D10)."""

HOMELESS = "Deferrals without a home (no plan note names these blocks):"
"""The heading the hook prints the deferrals without a home under (design 1
§5.6 step 4)."""


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
    notes the hook prints, by path. `writers` holds the session holding each
    project folder's write lock, by folder. `hello` is the change stream's
    first event, as it last opened.
    """

    def __init__(self, client: FlaskClient) -> None:
        self.client = client
        self.tree: dict[str, bytes] = {}
        self.shadow: dict[str, str] = {}
        self.notes: dict[str, str] = {}
        self.writers: dict[str, str] = {}
        self.hello: dict[str, Any] | None = None
        self._stream: TestResponse | None = None
        self._frames: Iterator[str] | None = None

    def close(self) -> None:
        """The change stream drops, if it is open."""
        if self._stream is not None:
            self._stream.close()
        self._stream = None
        self._frames = None

    def events(self) -> TestResponse:
        """`GET /api/sync/events` as the sidecar sends it, read a frame at a
        time; closing it is the sidecar going."""
        return self.client.get(
            "/api/sync/events", headers=sync_headers(), buffered=False
        )

    def put(
        self,
        path: str,
        content: bytes,
        base_hash: str | None,
        session: str | None = None,
    ) -> TestResponse:
        """`PUT /api/sync/files/<path>` as the sidecar sends it, `session` the
        one holding the path's project folder's write lock, if any."""
        headers = {
            **sync_headers(),
            "Content-Type": "application/octet-stream",
            "X-Pilot-Base-Hash": base_hash or "none",
        }
        if session is not None:
            headers["X-Pilot-Session"] = session
        return self.client.put(_url(path), data=content, headers=headers)

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

    def post_check(self, folder: str, wait_seconds: float) -> TestResponse:
        """`POST /api/sync/check` as the sidecar sends it."""
        return self.client.post(
            "/api/sync/check",
            json={"folder": folder, "wait_seconds": wait_seconds},
            headers=sync_headers(),
        )

    def lock(self, folder: str, session: str) -> None:
        """A hook takes the write lock of `folder` for `session`, which holds
        it until its release."""
        assert self.writers.get(folder, session) == session, (
            f"{folder} is held by another session"
        )
        self.writers[folder] = session

    def release(self, folder: str) -> str:
        """The hook's release after a tool call (design 1 §5.6): the sidecar
        uploads every file of `folder` whose hash is not the shadow's, as the
        save of the session holding the folder's lock; posts the folder's
        check; lets the lock go; and renders the answer as the hook prints it:
        each error as `<path>:<line>: <message>`, the line left out when it
        has none; then each local note of the folder as `<path>: <note>`, in
        path order; then the deferrals without a home under `HOMELESS`, each
        as `- <block> in <document> (<title>), to: <to>`. Empty when there is
        nothing to tell."""
        for path in sorted(self.tree):
            if path.startswith(f"{folder}/") and _sha256(
                self.tree[path]
            ) != self.shadow.get(path):
                self.upload(path)
        response = self.post_check(folder, 0.0)
        self.writers.pop(folder, None)
        assert response.status_code == 200, response.get_data(as_text=True)
        answer: dict[str, Any] = response.json
        lines = [
            f"{error['path']}: {error['message']}"
            if error["line"] is None
            else f"{error['path']}:{error['line']}: {error['message']}"
            for error in answer["errors"]
        ]
        lines.extend(
            f"{noted}: {note}"
            for noted, note in sorted(self.notes.items())
            if noted.startswith(f"{folder}/")
        )
        if answer["homeless_deferrals"]:
            lines.append(HOMELESS)
            lines.extend(
                f"- {deferral['block']} in {deferral['document']}"
                f" ({deferral['title']}), to: {deferral['to']}"
                for deferral in answer["homeless_deferrals"]
            )
        return "".join(f"{line}\n" for line in lines)

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
        base and the session holding its project folder's lock, writes the
        bytes the answer carries in place, and records the answer's hash. A
        path the server answers 404 stays in the tree with a local note, and
        the answer is none (design 1 §5.5, D10)."""
        folder, nested, _ = path.partition("/")
        response = self.put(
            path,
            self.tree[path],
            self.shadow.get(path),
            self.writers.get(folder) if nested else None,
        )
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

    def listen(self) -> None:
        """The sidecar opens its change stream, dropping the one it held, and
        takes its `hello`."""
        self.close()
        response = self.events()
        assert response.status_code == 200, response.get_data(as_text=True)
        self._stream = response
        self._frames = (chunk.decode() for chunk in response.response)
        event = self._next_event()
        assert event is not None and event[0] == "hello", event
        self.hello = event[1]

    def connect(self) -> dict[str, Any]:
        """The sidecar (re)connects: it opens its change stream, takes its
        `hello`, and reconciles (design 1 §5.8). Returns the reconcile's
        answer."""
        self.listen()
        return self.reconcile()

    def overflow(self) -> dict[str, Any]:
        """The watch overflows: the sidecar takes the tree, walked whole, as
        the tree the reconcile starts from, and reconciles (design 1 §5.8)."""
        return self.reconcile()

    def reconcile(self) -> dict[str, Any]:
        """Design 1 §5.5: every file whose hash on disk is not the shadow's
        goes up first; then the tree's hashes and the shadow's are posted;
        then each path to write down is fetched and written, and each path to
        delete removed from the tree and the shadow, its local note with it.
        Returns the server's answer."""
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
            self.notes.pop(path, None)
        return answer

    def drain(self) -> list[str]:
        """Apply what the change stream carried since the last drain, up to
        its heartbeat: fetch and write each `change`'s path whose hash
        differs from the shadow, the sidecar's own write echoed back
        ignored, and a path of no syncing project left for the reconcile;
        and reconcile on `manifest`. Returns the paths fetched for
        `change`s, in order."""
        fetched: list[str] = []
        while (event := self._next_event()) is not None:
            name, data = event
            if name == "manifest":
                self.reconcile()
            elif self.shadow.get(data["path"]) != data["hash"]:
                response = self.get(data["path"])
                if response.status_code == 404:
                    continue
                self._write(data["path"], response)
                fetched.append(data["path"])
        return fetched

    def text(self, path: str) -> str:
        """What the agent reads at `path`."""
        return self.tree[path].decode()

    def _next_event(self) -> tuple[str, dict[str, Any]] | None:
        """The change stream's next event, its name and its data; none at a
        heartbeat, when nothing is left to read."""
        assert self._frames is not None, "the change stream is not open"
        frame = next(self._frames, None)
        assert frame is not None, "the change stream ended"
        if frame.startswith(":"):
            return None
        fields = dict(line.split(": ", 1) for line in frame.strip("\n").split("\n"))
        assert set(fields) == {"event", "data"}, frame
        return fields["event"], json.loads(fields["data"])

    def _fetch(self, path: str) -> None:
        """Write the bytes `path` must hold, as the server answers them, and
        record their hash."""
        self._write(path, self.get(path))

    def _write(self, path: str, response: TestResponse) -> None:
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
