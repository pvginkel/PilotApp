#!/usr/bin/env python3
"""The live proof of the store's sync: pilot-sync, the Go binary, run as a
plain process in this environment against the dev stack's backend.

Usage:
    scripts/sync-live-proof.py

The dev stack runs first (`scripts/dev.py`, docs/slice-test-plan.md §2). The
script builds the binary in the `go` tool container, loads the dev seed (which
recreates the dev database), and puts the dev backend in testing mode for the
store: it appends FLASK_ENV=testing, a throwaway SYNC_TOKEN and this
environment's KUBECODER_ENVIRONMENT_ID as STORE_ENVIRONMENT_ID to
backend/.env, which the backend restarts on (backend/scripts/dev-watch.sh).
It runs the binary on a temporary tree and data directory, with nothing in
its environment but the variables it reads, and its connection to the
backend through a proxy the script can cut. It shows five things, a PASS or a
FAIL line each:

1. A file edited in the tree reaches the record.
2. A record edit rewrites the file, and the sidecar does not send its own
   write back.
3. The hook's local check answers: a clean save, lines the record reverted,
   a stray file.
4. A dropped connection reconciles: edits made on both sides while it is
   down cross on the reconnect.
5. A `manifest` event reconciles: a record file deleted from the tree is
   written back down.

Whatever happens, backend/.env is put back byte for byte on exit, and the
script waits for the backend to restart on it. It exits 0 when everything
passed, 1 otherwise; a failed run keeps its temporary directory, the binary's
log in it.
"""

import contextlib
import hashlib
import http.client
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from email.message import Message
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / "backend" / ".env"
BACKEND_PORT = 3501
BACKEND = f"http://127.0.0.1:{BACKEND_PORT}"
# sidecar/internal/protocol.Version
PROTOCOL = "1"
ENVIRONMENT_VAR = "KUBECODER_ENVIRONMENT_ID"
# sidecar/internal/files.TempPrefix: the sidecar's own temporary files.
TEMP_PREFIX = ".pilot-sync-"

# The dev seed's (backend/app/services/test_data_service.py).
HANDBOOK = "recipe-box/handbook.md"
DRAFT = "draft-*/project.md"
OPENING = "recipe-box/items/1-*.md"
IMPORT_PLAN = "recipe-box/items/*-how-to-import-the-remaining-cards.md"
STRAY = "recipe-box/the-proofs-own-notes.md"

UNREACHABLE = (OSError, http.client.HTTPException)


class Failure(Exception):
    """A check that did not hold."""


def until[T](what: str, probe: Callable[[], T], timeout: float = 15.0) -> T:
    """probe's first truthy answer, asked every 0.1 s until timeout."""
    deadline = time.monotonic() + timeout
    while True:
        value = probe()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise Failure(f"{what}: not within {timeout:g} s")
        time.sleep(0.1)


def expect(holds: bool, what: str) -> None:
    if not holds:
        raise Failure(what)


def say(line: str = "") -> None:
    print(line, flush=True)


def indented(text: str) -> str:
    return (
        "\n".join(f"      | {line}" for line in text.splitlines()) or "      | (empty)"
    )


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass
class Response:
    status: int
    headers: Message
    body: bytes


def call(
    method: str,
    url: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> Response:
    request = urllib.request.Request(
        url, data=body, method=method, headers=headers or {}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return Response(response.status, response.headers, response.read())
    except urllib.error.HTTPError as error:
        return Response(error.code, error.headers, error.read())


def call_json(
    method: str, url: str, document: object, headers: dict[str, str] | None = None
) -> Response:
    return call(
        method,
        url,
        body=json.dumps(document).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
    )


class Store:
    """The sync routes as the store's sidecar calls them, with its bearer,
    and the sync's testing endpoints, which set off record-side moves."""

    def __init__(self, token: str, environment: str) -> None:
        self.headers = {
            "Authorization": f"Bearer {token}",
            "X-Pilot-Environment": environment,
            "X-Pilot-Sync-Protocol": PROTOCOL,
        }

    def get(self, path: str) -> Response:
        return call("GET", f"{BACKEND}/api/sync/files/{path}", headers=self.headers)

    def record(self, path: str) -> tuple[str, bytes]:
        """What the record holds at path: its tree hash and its bytes."""
        response = self.get(path)
        expect(response.status == 200, f"GET {path}: {response.status}")
        return response.headers["X-Pilot-Hash"], response.body

    def manifest(self, hashes: dict[str, str]) -> list[dict[str, object]]:
        response = call_json(
            "POST",
            f"{BACKEND}/api/sync/manifest",
            {"tree": hashes, "shadow": hashes},
            headers=self.headers,
        )
        expect(response.status == 200, f"POST manifest: {response.status}")
        return json.loads(response.body)["manifest"]

    def answer(self, path: str, block: str, answer: str, user: str) -> str:
        """A person's answer to a block, written by the record; the file's
        tree hash once answered."""
        response = call_json(
            "POST",
            f"{BACKEND}/api/testing/sync/answer",
            {"path": path, "block": block, "answer": answer, "user": user},
        )
        expect(
            response.status == 200,
            f"answer {block} of {path}: {response.status} {response.body!r}",
        )
        return json.loads(response.body)["hash"]

    def announce_manifest(self) -> Response:
        return call("POST", f"{BACKEND}/api/testing/sync/manifest")


class Tree:
    """The tree pilot-sync keeps, as the agent sees it."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def file(self, path: str) -> Path:
        return self.root / path

    def read(self, path: str) -> bytes | None:
        try:
            return self.file(path).read_bytes()
        except FileNotFoundError:
            return None

    def hash(self, path: str) -> str | None:
        content = self.read(path)
        return None if content is None else sha256(content)

    def write(self, path: str, content: bytes) -> None:
        self.file(path).write_bytes(content)

    def hashes(self) -> dict[str, str]:
        found = {}
        for directory, _, names in os.walk(self.root):
            for name in names:
                if name.startswith(TEMP_PREFIX):
                    continue
                file = Path(directory, name)
                found[file.relative_to(self.root).as_posix()] = sha256(
                    file.read_bytes()
                )
        return found

    def find(self, pattern: str) -> str:
        matches = sorted(self.root.glob(pattern))
        expect(len(matches) == 1, f"{pattern}: {len(matches)} files in the tree")
        return matches[0].relative_to(self.root).as_posix()


FIELD = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S*)')


class SidecarLog:
    """pilot-sync's log, slog's text lines, read as records of their fields."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def records(self) -> list[dict[str, str]]:
        lines = self.path.read_text(errors="replace").splitlines()
        return [
            {
                key: json.loads(value) if value.startswith('"') else value
                for key, value in FIELD.findall(line)
            }
            for line in lines
        ]

    def mark(self) -> int:
        return len(self.records())

    def find(self, msg: str, since: int, **fields: str) -> list[dict[str, str]]:
        return [
            record
            for record in self.records()[since:]
            if record.get("msg") == msg
            and all(record.get(key) == value for key, value in fields.items())
        ]


class Link:
    """pilot-sync's connection to the backend: a TCP proxy on a local port.
    `cut` ends every connection it carries and refuses new ones until
    `restore`."""

    def __init__(self, target: int) -> None:
        self.target = target
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port: int = self.listener.getsockname()[1]
        self.up = True
        self.lock = threading.Lock()
        self.carried: set[socket.socket] = set()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                client, _ = self.listener.accept()
            except OSError:
                return
            try:
                upstream = socket.create_connection(("127.0.0.1", self.target))
            except OSError:
                client.close()
                continue
            with self.lock:
                carried = self.up
                if carried:
                    self.carried |= {client, upstream}
            if not carried:
                client.close()
                upstream.close()
                continue
            for source, sink in ((client, upstream), (upstream, client)):
                threading.Thread(
                    target=self._carry, args=(source, sink), daemon=True
                ).start()

    def _carry(self, source: socket.socket, sink: socket.socket) -> None:
        # Each socket is closed by the thread that reads it, once both are
        # shut down.
        with contextlib.suppress(OSError):
            while data := source.recv(65536):
                sink.sendall(data)
        for end in (source, sink):
            with contextlib.suppress(OSError):
                end.shutdown(socket.SHUT_RDWR)
        with self.lock:
            self.carried.discard(source)
        source.close()

    def cut(self) -> None:
        with self.lock:
            self.up = False
            for end in self.carried:
                with contextlib.suppress(OSError):
                    end.shutdown(socket.SHUT_RDWR)

    def restore(self) -> None:
        with self.lock:
            self.up = True

    def close(self) -> None:
        self.cut()
        with contextlib.suppress(OSError):
            self.listener.shutdown(socket.SHUT_RDWR)
        self.listener.close()


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def run(command: str, cwd: Path) -> None:
    result = subprocess.run(command.split(), cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = "\n".join((result.stdout + result.stderr).splitlines()[-20:])
        raise Failure(f"{command} exited {result.returncode}:\n{indented(tail)}")


def start_sidecar(
    binary: Path, work: Path, link: Link, local_port: int, token: str, environment: str
) -> subprocess.Popen[bytes]:
    """pilot-sync on the tree and data directory of work, with nothing in its
    environment but the variables it reads, logging to work/pilot-sync.log."""
    with (work / "pilot-sync.log").open("wb") as output:
        return subprocess.Popen(
            [str(binary)],
            env={
                "PILOT_URL": f"http://127.0.0.1:{link.port}",
                "PILOT_SYNC_TOKEN": token,
                ENVIRONMENT_VAR: environment,
                "PILOT_SYNC_LOCAL_PORT": str(local_port),
                "PILOT_SYNC_TREE_ROOT": str(work / "tree"),
                "PILOT_SYNC_DATA_DIR": str(work / "data"),
            },
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
        )


def backend_stage() -> str | None:
    try:
        return json.loads(call("GET", f"{BACKEND}/health/readyz").body)["stage"]
    except UNREACHABLE:
        return None


class Backend:
    """The dev backend, configured for the store through backend/.env."""

    def __init__(self, store: Store, token: str, environment: str) -> None:
        self.store = store
        self.settings = (
            "FLASK_ENV=testing\n"
            f"SYNC_TOKEN={token}\n"
            f"STORE_ENVIRONMENT_ID={environment}\n"
        )
        self.original: bytes | None = None
        self.configured = False

    def configure(self) -> None:
        self.original = ENV_FILE.read_bytes() if ENV_FILE.exists() else None
        base = self.original or b""
        if base and not base.endswith(b"\n"):
            base += b"\n"
        self.configured = True
        # python-dotenv keeps a key's last line, so these override the file's.
        ENV_FILE.write_bytes(base + self.settings.encode())
        until("the dev backend restarts in testing mode", self._serves_store, 90)

    def put_back(self) -> None:
        if not self.configured:
            return
        if self.original is None:
            ENV_FILE.unlink()
        else:
            ENV_FILE.write_bytes(self.original)
        self.configured = False
        until("the dev backend restarts on its own .env", self._refuses_store, 90)

    def _serves_store(self) -> bool:
        try:
            if self.store.get("reference.json").status != 200:
                return False
            return self.store.announce_manifest().status == 204
        except UNREACHABLE:
            return False

    def _refuses_store(self) -> bool:
        try:
            return self.store.get("reference.json").status == 401
        except UNREACHABLE:
            return False


@dataclass
class Proof:
    store: Store
    tree: Tree
    log: SidecarLog
    link: Link
    local_port: int
    details: list[str] = field(default_factory=list)

    def check(self, path: str) -> Response:
        """The hook's check of path, as the hook calls it."""
        query = urllib.parse.quote(str(self.tree.file(path)), safe="/")
        return call("GET", f"http://127.0.0.1:{self.local_port}/check?path={query}")

    def in_step(self) -> str:
        """The tree is the record's projection: every path of the manifest
        on disk with its hash, a read-only one mode 0444, and no other
        file."""
        disk = self.tree.hashes()
        manifest = self.store.manifest(disk)
        listed = {str(entry["path"]): entry for entry in manifest}
        off = sorted(
            path for path, entry in listed.items() if disk.get(path) != entry["hash"]
        )
        expect(not off, f"off the record: {off}")
        extra = sorted(set(disk) - set(listed))
        expect(not extra, f"not the record's: {extra}")
        views = [path for path, entry in listed.items() if entry["readonly"]]
        writable = sorted(
            path
            for path in views
            if self.tree.file(path).stat().st_mode & 0o777 != 0o444
        )
        expect(not writable, f"read-only views not 0444: {writable}")
        return f"{len(listed)} files, {len(views)} read-only views 0444"

    def tree_reaches_record(self) -> str:
        mark = self.log.mark()
        line = b"- A line the live proof wrote in the tree.\n"
        edited = self.tree.read(HANDBOOK)
        if edited is None:
            raise Failure(f"{HANDBOOK} is not in the tree")
        self.tree.write(HANDBOOK, edited + line)
        until(
            "the record holds the edit", lambda: line in self.store.record(HANDBOOK)[1]
        )
        synced = until(
            "pilot-sync logs it synced",
            lambda: self.log.find("synced", mark, path=HANDBOOK),
        )
        record_hash, _ = self.store.record(HANDBOOK)
        expect(
            self.tree.hash(HANDBOOK) == record_hash,
            f"{HANDBOOK} on disk is not the record's",
        )
        return f"{HANDBOOK}, the record's hash {record_hash[:12]}, synced {synced[0]['hash'][:12]}"

    def record_rewrites_file(self) -> str:
        draft = self.tree.find(DRAFT)
        mark = self.log.mark()
        answer = "Sowing, watering and the first frost"
        record_hash = self.store.answer(draft, "Q1", answer, "ada")
        until(
            "the file holds the record's hash",
            lambda: self.tree.hash(draft) == record_hash,
        )
        content = self.tree.read(draft) or b""
        expect(
            f"answer: {answer}\nby: ada\n".encode() in content, "no answer in the file"
        )
        until(
            "pilot-sync logs it written down",
            lambda: self.log.find("written down", mark, path=draft),
        )
        # The watch's echo of the write settles within its 50 ms debounce.
        time.sleep(1.0)
        sent = [
            record
            for record in self.log.records()[mark:]
            if record.get("path") == draft and record.get("msg") != "written down"
        ]
        expect(not sent, f"pilot-sync acted on its own write: {sent}")
        return (
            f"{draft} Q1 answered by ada, the file at {record_hash[:12]}, not sent back"
        )

    def hook_check_answers(self) -> str:
        health = call("GET", f"http://127.0.0.1:{self.local_port}/healthz")
        expect(health.status == 200 and health.body == b"ok\n", "/healthz")

        mark = self.log.mark()
        clean = self.check(HANDBOOK)
        clean_text = clean.body.decode()
        expect(clean.status == 200, f"check {HANDBOOK}: {clean.status}")
        expect(not clean_text.startswith("not yet checked"), clean_text)
        until(
            "pilot-sync logs it checked and agreed",
            lambda: self.log.find("checked", mark, path=HANDBOOK, agreed="true"),
        )
        self.details += [f"    a clean save, {HANDBOOK}:", indented(clean_text)]

        opening = self.tree.find(OPENING)
        published = self.tree.read(opening) or b""
        self.tree.write(opening, published + b"\nA line the opening never had.\n")
        reverted = self.check(opening)
        reverted_text = reverted.body.decode()
        expect(reverted.status == 200, f"check {opening}: {reverted.status}")
        expect(f"{opening}:" in reverted_text, f"no reverted line: {reverted_text!r}")
        expect(self.tree.read(opening) == published, f"{opening} is not reverted")
        self.details += [
            f"    lines the record reverted, {opening}:",
            indented(reverted_text),
        ]

        self.tree.write(STRAY, b"# Notes no item bore\n")
        stray = self.check(STRAY)
        stray_text = stray.body.decode()
        expect(stray.status == 200, f"check {STRAY}: {stray.status}")
        expect(
            f"{STRAY}: not a document of the record" in stray_text,
            f"no stray note: {stray_text!r}",
        )
        self.details += [f"    a stray file, {STRAY}:", indented(stray_text)]
        self.tree.file(STRAY).unlink()
        return "/healthz ok; the clean save checked, the revert and the stray printed"

    def dropped_connection_reconciles(self) -> str:
        imports = self.tree.find(IMPORT_PLAN)
        mark = self.log.mark()
        self.link.cut()
        # Restored whatever happens while it is cut, so a failure here is
        # this step's alone.
        try:
            until(
                "pilot-sync sees the stream drop",
                lambda: self.log.find("the change stream dropped: reconnecting", mark),
            )
            line = b"- A line the live proof wrote while the connection was down.\n"
            self.tree.write(HANDBOOK, (self.tree.read(HANDBOOK) or b"") + line)
            answer = "Photograph it and type it the same week"
            record_hash = self.store.answer(imports, "Q1", answer, "ben")
            time.sleep(2.0)
            expect(
                line not in self.store.record(HANDBOOK)[1],
                "the tree's edit crossed while the connection was down",
            )
            expect(
                self.tree.hash(imports) != record_hash,
                "the record's edit crossed while the connection was down",
            )
            reopened = self.log.mark()
        finally:
            self.link.restore()
        until(
            "the change stream reopens",
            lambda: self.log.find("the change stream is open", reopened),
            45,
        )
        until(
            "the record holds the tree's edit",
            lambda: line in self.store.record(HANDBOOK)[1],
        )
        until(
            "the tree holds the record's edit",
            lambda: self.tree.hash(imports) == record_hash,
        )
        reconciled = until(
            "pilot-sync logs the reconcile",
            lambda: self.log.find("reconciled", reopened),
        )[0]
        return (
            f"{HANDBOOK} up, {imports} down; reconciled sent_up={reconciled['sent_up']}"
            f" written_down={reconciled['written_down']}"
        )

    def manifest_reconciles(self) -> str:
        mark = self.log.mark()
        self.tree.file(HANDBOOK).unlink()
        time.sleep(1.5)
        expect(
            self.tree.read(HANDBOOK) is None,
            f"{HANDBOOK} came back before the manifest event",
        )
        expect(not self.log.find("reconciled", mark), "a reconcile ran unasked")
        announced = self.store.announce_manifest()
        expect(announced.status == 204, f"manifest event: {announced.status}")
        record_hash, _ = self.store.record(HANDBOOK)
        until(
            "the deleted file is written back down",
            lambda: self.tree.hash(HANDBOOK) == record_hash,
        )
        reconciled = until(
            "pilot-sync logs the reconcile",
            lambda: self.log.find("reconciled", mark),
        )[0]
        return (
            f"{HANDBOOK} deleted, written back down at {record_hash[:12]};"
            f" reconciled written_down={reconciled['written_down']}"
        )


def prove(work: Path, environment: str) -> bool:
    token = secrets.token_hex(24)
    store = Store(token, environment)
    backend = Backend(store, token, environment)
    sidecar: subprocess.Popen[bytes] | None = None
    link: Link | None = None
    passed = 0
    steps = 5
    # The closing checks and the put-back, apart from the steps.
    closed = True
    try:
        binary = work / "pilot-sync"
        run(
            f"cexec go env CGO_ENABLED=0 go build -o {binary} ./cmd/pilot-sync",
            ROOT / "sidecar",
        )
        say("  built pilot-sync")
        run(
            "cexec modern-app uv run cli load-test-data --yes-i-am-sure",
            ROOT / "backend",
        )
        say("  loaded the dev seed")
        backend.configure()
        say(
            f"  the dev backend serves the store in testing mode, stage {backend_stage()}"
        )

        link = Link(BACKEND_PORT)
        local_port = free_port()
        sidecar = start_sidecar(binary, work, link, local_port, token, environment)
        tree = Tree(work / "tree")
        log = SidecarLog(work / "pilot-sync.log")
        first = until(
            "pilot-sync's first reconcile", lambda: log.find("reconciled", 0), 30
        )[0]
        proof = Proof(store, tree, log, link, local_port)
        say(
            f"  pilot-sync's first reconcile wrote {first['written_down']} files down;"
            f" the tree is the record's projection: {proof.in_step()}"
        )

        say()
        for number, title, step in (
            (
                1,
                "A file edited in the tree reaches the record",
                proof.tree_reaches_record,
            ),
            (2, "A record edit rewrites the file", proof.record_rewrites_file),
            (3, "The hook's local check answers", proof.hook_check_answers),
            (4, "A dropped connection reconciles", proof.dropped_connection_reconciles),
            (5, "A `manifest` event reconciles", proof.manifest_reconciles),
        ):
            proof.details = []
            try:
                outcome = step()
            except (Failure, *UNREACHABLE) as failure:
                exited = sidecar.poll()
                if exited is not None:
                    failure = Failure(f"{failure} (pilot-sync exited {exited})")
                say(f"FAIL {number}. {title}: {failure}")
            else:
                passed += 1
                say(f"PASS {number}. {title}: {outcome}")
            for detail in proof.details:
                say(detail)

        say()
        say(f"  the tree is the record's projection: {proof.in_step()}")
        sidecar.send_signal(signal.SIGTERM)
        exited = sidecar.wait(10)
        expect(exited == 0, f"pilot-sync exited {exited} on SIGTERM")
        say("  pilot-sync stopped on SIGTERM, exit 0")
    except (Failure, *UNREACHABLE) as failure:
        say(f"FAIL: {failure}")
        closed = False
    finally:
        if sidecar is not None and sidecar.poll() is None:
            sidecar.kill()
            sidecar.wait()
        if link is not None:
            link.close()
        if backend.configured:
            try:
                backend.put_back()
                say(
                    "  backend/.env put back; the dev backend restarted on it,"
                    f" stage {backend_stage()}"
                )
            except Failure as failure:
                say(f"FAIL: {failure}")
                closed = False
    say()
    say(f"{passed} of {steps} passed")
    return closed and passed == steps


def main() -> int:
    environment = os.environ.get(ENVIRONMENT_VAR, "")
    if not environment:
        say(f"FAIL: {ENVIRONMENT_VAR} is not set")
        return 1
    if backend_stage() is None:
        say(
            f"FAIL: the dev backend does not answer on :{BACKEND_PORT}: start the dev"
            " stack first (scripts/dev.py, docs/slice-test-plan.md §2)"
        )
        return 1
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    work = Path(tempfile.mkdtemp(prefix="pilot-sync-proof-"))
    say(f"pilot-sync live proof, against {BACKEND}, in {work}")
    passed = False
    try:
        passed = prove(work, environment)
    finally:
        if passed:
            shutil.rmtree(work)
        else:
            say(f"kept {work}: pilot-sync's log is {work / 'pilot-sync.log'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
