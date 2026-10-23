"""The sync routes (design 1 §5.1): every request and response shape the
store's sidecar is written against, pinned beside the protocol's version."""

import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from dependency_injector import providers
from flask import Flask
from flask.testing import FlaskClient
from prometheus_client.metrics import MetricWrapperBase
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from werkzeug.test import TestResponse

from app import models
from app.database import scoped_session
from app.engine.bus import (
    DocumentModified,
    EngineEvent,
    ErrorsResolved,
    ManifestChanged,
    TreeHashMoved,
)
from app.engine.paths import sha256_hex
from app.models import Document, Environment, Project, SaveError, User
from app.models.reference import ErrorKind, ProjectState
from app.services.container import ServiceContainer
from app.services.sync_service import (
    HOOK_WAIT_SECONDS,
    SYNC_PROTOCOL_MAX,
    SYNC_PROTOCOL_MIN,
)
from app.services.sync_stream_service import (
    STREAM_CONNECTED,
    STREAM_CONNECTS_TOTAL,
    SyncStreamService,
)
from app.utils.lifecycle_coordinator import LifecycleCoordinator
from tests.support.fake_sidecar import (
    HOMELESS,
    STORE_ENVIRONMENT_ID,
    STRAY,
    SYNC_TOKEN,
    Check,
    FakeSidecar,
    sync_headers,
)

ANSWERED = """---
title: Which tent?
---

```decision id=D1
options:
  - Dome
  - Tunnel
answer: Dome
by: ada
at: 2026-10-12T09:40:00Z
```
"""

DECISION = """---
title: Which tent?
---

```decision id=D1
options:
  - Dome
  - Tunnel
recommend: Dome
```
"""

BROKEN = ANSWERED + "\n```question id=Q1\n"

DRAFT = "---\ntitle: Badge colours\n---\n\nWhich colours for the badges?\n"

RETITLED = "---\ntitle: Badge palette\n---\n\nWhich colours for the badges?\n"

MISSPELT_PLAN = '{"tickets": "MD-9"}\n'

COMPACT_PLAN = json.dumps(
    {
        "ticket": "MD-8",
        "repo": "pvginkel/MyDownloads",
        "tasks": [
            {
                "id": "fix",
                "title": "Fix the client for v4",
                "status": "in_progress",
                "notes": [],
            }
        ],
        "notes": [],
    }
)

FIX_PLAN = json.dumps(
    {"tasks": [{"id": "fix", "title": "Fix the client for v4", "status": "pending"}]}
)

DEFERRED = """---
title: Camp chores
---

```decision id=D1
options:
  - Dome
  - Tunnel
answer: deferred
by: agent
at: 2026-10-12T09:30:00Z
to: fix
```

```question id=Q1
answer: deferred
by: agent
at: 2026-10-12T09:30:00Z
to: plan
```
"""

HASH = "a" * 64

EVENTS = "/api/sync/events"

ROUTES = [
    ("PUT", "/api/sync/files/reference.json"),
    ("GET", "/api/sync/files/reference.json"),
    ("POST", "/api/sync/manifest"),
    ("GET", EVENTS),
    ("POST", "/api/sync/check"),
]
"""Each sync route, at a path that resolves; `_call`'s body is valid for
each."""

HEARTBEAT = ": heartbeat\n\n"

MANIFEST = "event: manifest\ndata: {}\n\n"


def _hello(manifest_hash: str) -> str:
    return (
        'event: hello\ndata: {"protocol": {"min": 1, "max": 1}, '
        f'"manifest_hash": "{manifest_hash}"}}\n\n'
    )


def _change(path: str, hash: str) -> str:
    return f'event: change\ndata: {{"path": "{path}", "hash": "{hash}"}}\n\n'


@contextmanager
def _stream(client: FlaskClient) -> Iterator[Iterator[str]]:
    """The change stream as the sidecar opens it, a frame at a time; leaving
    the block is the sidecar going."""
    response = client.get(EVENTS, headers=sync_headers(), buffered=False)
    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    assert response.headers["Cache-Control"] == "no-cache"
    try:
        yield (chunk.decode() for chunk in response.response)
    finally:
        response.close()


def _sample(metric: MetricWrapperBase, name: str) -> float:
    for family in metric.collect():
        for sample in family.samples:
            if sample.name == name:
                return sample.value
    return 0.0


def _stream_counts() -> tuple[float, float]:
    return (
        _sample(STREAM_CONNECTS_TOTAL, "pilot_sync_stream_connects_total"),
        _sample(STREAM_CONNECTED, "pilot_sync_stream_connected"),
    )


def _own_streams(
    container: ServiceContainer, coordinator: LifecycleCoordinator, **options: int
) -> None:
    """The stream route's streams, for this test, on a service of their own
    whose shutdown is not the app's."""
    streams = SyncStreamService(container.engine_bus(), coordinator, **options)
    container.sync_stream_service.override(providers.Object(streams))


def _pilot_headers(response: object) -> dict[str, str]:
    headers = response.headers  # type: ignore[attr-defined]
    return {name: value for name, value in headers if name.startswith("X-Pilot-")}


def _configure(container: ServiceContainer, **changes: object) -> None:
    """The app settings with `changes`, for this test."""
    settings = container.app_config().model_copy(update=changes)
    container.app_config.override(providers.Object(settings))


def _call(
    client: FlaskClient, method: str, url: str, headers: dict[str, str]
) -> TestResponse:
    return client.open(
        url,
        method=method,
        headers={**headers, "X-Pilot-Base-Hash": "none"},
        json={
            "tree": {},
            "shadow": {},
            "path": "reference.json",
            "hash": HASH,
            "wait_seconds": 0.0,
        },
    )


def _bear_item(
    container: ServiceContainer, project: Project, session: models.Session, text: str
) -> str:
    with scoped_session(container):
        container.document_service().bear_item(
            project, "decision", "Which tent?", session, text
        )
    return f"draft-{project.number}/items/1-which-tent.md"


def _bear_draft(container: ServiceContainer, project: Project) -> str:
    with scoped_session(container):
        container.document_service().bear_draft(project, DRAFT)
    return f"draft-{project.number}/project.md"


def _done_deferrals(
    container: ServiceContainer,
    project: Project,
    session: models.Session,
    person: User,
) -> tuple[str, str]:
    """The plan of `project` with the task `fix`, and a done item whose D1 is
    deferred to `fix` and Q1 to the plan. Returns the item's id and path."""
    with scoped_session(container) as db:
        container.plan_service().save(project, FIX_PLAN.encode())
        item = container.document_service().bear_item(
            project, "decision", "Camp chores", session, DEFERRED
        )
        container.record_service().done(item, person)
        path = f"draft-{project.number}/{db.get_one(Document, item.id).path}"
        return str(item.id), path


def _told(session: DbSession, path: str) -> str:
    """What the hook tells the agent of `path`'s Save Errors, in order."""
    return "".join(
        f"{path}:{error.line}: {error.message}\n"
        for error in session.scalars(
            select(SaveError).where(SaveError.path == path).order_by(SaveError.id)
        )
    )


def _assert_in_step(container: ServiceContainer, sidecar: FakeSidecar) -> None:
    """The sidecar's tree holds what the record says every path of the
    manifest must hold, beside the files the record never bore."""
    tree = container.tree_service()
    manifest = tree.manifest()
    assert sidecar.shadow == {entry.path: entry.hash for entry in manifest}
    assert {
        path: content
        for path, content in sidecar.tree.items()
        if path not in sidecar.notes
    } == {entry.path: tree.read(entry.path).content for entry in manifest}


class TestSyncProtocolVersion:
    def test_the_shapes_pinned_here_are_the_accepted_range(self) -> None:
        # A change to a shape these tests pin bumps SYNC_PROTOCOL_MAX and the
        # sidecar's own version in one commit, and SYNC_PROTOCOL_MIN with it
        # when the server cannot serve the old sidecar (design 1 §5.1).
        assert (SYNC_PROTOCOL_MIN, SYNC_PROTOCOL_MAX) == (1, 1)


class TestSyncGate:
    """The gate every sync route passes (design 1 §5.1)."""

    @pytest.mark.parametrize(("method", "url"), ROUTES)
    def test_a_call_without_the_bearer_is_401(
        self, session: DbSession, client: FlaskClient, method: str, url: str
    ) -> None:
        headers = {**sync_headers()}
        del headers["Authorization"]

        response = _call(client, method, url, headers)

        assert response.status_code == 401
        assert response.json["code"] == "AUTHENTICATION_REQUIRED"
        assert session.get(Environment, STORE_ENVIRONMENT_ID) is None

    @pytest.mark.parametrize(("method", "url"), ROUTES)
    def test_a_call_with_another_bearer_is_401(
        self, client: FlaskClient, method: str, url: str
    ) -> None:
        headers = {**sync_headers(), "Authorization": "Bearer another-token"}

        response = _call(client, method, url, headers)

        assert response.status_code == 401

    @pytest.mark.parametrize(("method", "url"), ROUTES)
    def test_every_call_is_401_while_the_token_is_empty(
        self,
        container: ServiceContainer,
        client: FlaskClient,
        method: str,
        url: str,
    ) -> None:
        _configure(container, sync_token="")

        for bearer in (f"Bearer {SYNC_TOKEN}", "Bearer ", "Bearer"):
            headers = {**sync_headers(), "Authorization": bearer}
            assert _call(client, method, url, headers).status_code == 401

    @pytest.mark.parametrize(("method", "url"), ROUTES)
    def test_a_call_from_another_environment_is_403_and_logged(
        self,
        session: DbSession,
        client: FlaskClient,
        caplog: pytest.LogCaptureFixture,
        method: str,
        url: str,
    ) -> None:
        headers = {**sync_headers(), "X-Pilot-Environment": "example-env-2"}

        with caplog.at_level(logging.WARNING):
            response = _call(client, method, url, headers)

        assert response.status_code == 403
        assert response.json["code"] == "AUTHORIZATION_FAILED"
        assert "'example-env-2'" in caplog.text
        assert session.get(Environment, "example-env-2") is None

    def test_a_call_naming_no_environment_is_403(self, client: FlaskClient) -> None:
        headers = {**sync_headers()}
        del headers["X-Pilot-Environment"]

        assert _call(client, *ROUTES[1], headers).status_code == 403

    def test_every_call_is_403_while_the_store_is_not_configured(
        self, container: ServiceContainer, client: FlaskClient
    ) -> None:
        _configure(container, store_environment_id="")

        for environment in (STORE_ENVIRONMENT_ID, ""):
            headers = {**sync_headers(), "X-Pilot-Environment": environment}
            assert _call(client, *ROUTES[1], headers).status_code == 403

    @pytest.mark.parametrize(("method", "url"), ROUTES)
    @pytest.mark.parametrize("version", ["0", "2", "one", "+1", ""])
    def test_a_version_outside_the_range_is_426_with_the_range(
        self,
        session: DbSession,
        client: FlaskClient,
        method: str,
        url: str,
        version: str,
    ) -> None:
        headers = {**sync_headers(), "X-Pilot-Sync-Protocol": version}

        response = _call(client, method, url, headers)

        assert response.status_code == 426
        assert response.json == {"min": SYNC_PROTOCOL_MIN, "max": SYNC_PROTOCOL_MAX}
        assert session.get(Environment, STORE_ENVIRONMENT_ID) is None

    def test_a_call_naming_no_version_is_426(self, client: FlaskClient) -> None:
        headers = {**sync_headers()}
        del headers["X-Pilot-Sync-Protocol"]

        response = _call(client, *ROUTES[0], headers)

        assert response.status_code == 426
        assert response.json == {"min": 1, "max": 1}

    def test_a_refused_put_acts_on_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
    ) -> None:
        path = _bear_item(container, project, project_session, ANSWERED)
        fake_sidecar.drain()
        document = session.scalars(select(Document)).one()
        _configure(container, sync_token="")

        response = fake_sidecar.put(path, b"# Another tent\n", None)

        assert response.status_code == 401
        session.refresh(document)
        assert document.ingested_text is None
        assert document.published_text == ANSWERED

    @pytest.mark.parametrize(("method", "url"), ROUTES)
    def test_the_first_call_through_makes_the_stores_environment(
        self, session: DbSession, client: FlaskClient, method: str, url: str
    ) -> None:
        with _call(client, method, url, sync_headers()) as response:
            assert response.status_code == 200

        store = session.get_one(Environment, STORE_ENVIRONMENT_ID)
        assert (store.name, store.exempt) == (STORE_ENVIRONMENT_ID, False)

    def test_a_call_leaves_the_stores_environment_as_it_is(
        self, session: DbSession, client: FlaskClient, environment: Environment
    ) -> None:
        assert _call(client, *ROUTES[1], sync_headers()).status_code == 200

        session.refresh(environment)
        assert (environment.name, environment.exempt) == ("Example-1", False)

    def test_the_routes_are_outside_the_oidc_gate(
        self, oidc_app: Flask, oidc_client: FlaskClient
    ) -> None:
        assert oidc_app.container.config().oidc_enabled

        response = oidc_client.get(ROUTES[1][1], headers=sync_headers())

        assert response.status_code == 200


class TestPutFile:
    """`PUT /api/sync/files/<path>` (design 1 §5.1, §5.3)."""

    def test_a_save_that_needs_no_change_is_204_with_its_hash(
        self,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
    ) -> None:
        path = _bear_item(container, project, project_session, ANSWERED)
        edited = ANSWERED.replace("# Which tent?", "# Which tent for the lake?")

        response = fake_sidecar.put(path, edited.encode(), sha256_hex(ANSWERED))

        assert response.status_code == 204
        assert response.get_data() == b""
        assert _pilot_headers(response) == {
            "X-Pilot-Hash": sha256_hex(edited),
            "X-Pilot-Faults": "0",
        }

    def test_a_save_the_file_must_change_for_is_200_with_its_bytes(
        self,
        session: DbSession,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
    ) -> None:
        path = _bear_item(container, project, project_session, ANSWERED)
        save = ANSWERED.replace("by: ada", "by: agent")

        response = fake_sidecar.put(path, save.encode(), sha256_hex(ANSWERED))

        assert response.status_code == 200
        assert response.mimetype == "application/octet-stream"
        assert response.get_data() == ANSWERED.encode()
        assert _pilot_headers(response) == {
            "X-Pilot-Hash": sha256_hex(ANSWERED),
            "X-Pilot-Faults": "1",
        }
        assert [
            (error.environment_id, error.path, error.kind_code, error.line)
            for error in session.scalars(select(SaveError))
        ] == [(STORE_ENVIRONMENT_ID, path, ErrorKind.REVERTED, 5)]

    def test_a_held_save_is_204_with_its_own_hash_and_faults(
        self,
        session: DbSession,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
    ) -> None:
        path = _bear_item(container, project, project_session, ANSWERED)
        broken = ANSWERED + "\n```question id=Q1\n"

        response = fake_sidecar.put(path, broken.encode(), sha256_hex(ANSWERED))

        errors = list(session.scalars(select(SaveError)))
        assert response.status_code == 204
        assert _pilot_headers(response) == {
            "X-Pilot-Hash": sha256_hex(broken),
            "X-Pilot-Faults": str(len(errors)),
        }
        assert errors
        assert {(error.environment_id, error.kind_code) for error in errors} == {
            (STORE_ENVIRONMENT_ID, ErrorKind.PARSE)
        }

    @pytest.mark.parametrize("base", [HASH, None])
    def test_a_base_that_is_not_the_tree_hash_is_stale_never_refused(
        self,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
        base: str | None,
    ) -> None:
        path = _bear_item(container, project, project_session, ANSWERED)
        edited = ANSWERED.replace("# Which tent?", "# Which tent for the lake?")

        response = fake_sidecar.put(path, edited.encode(), base)

        assert response.status_code == 204
        assert _pilot_headers(response) == {
            "X-Pilot-Hash": sha256_hex(edited),
            "X-Pilot-Faults": "0",
            "X-Pilot-Stale": "true",
        }

    def test_a_read_only_path_is_200_with_its_projection(
        self, container: ServiceContainer, fake_sidecar: FakeSidecar, project: Project
    ) -> None:
        path = f"draft-{project.number}/timeline.json"
        timeline = container.view_service().timeline(project)

        response = fake_sidecar.put(path, b"{}\n", timeline.hash)

        assert response.status_code == 200
        assert response.get_data() == timeline.text.encode()
        assert _pilot_headers(response) == {
            "X-Pilot-Hash": timeline.hash,
            "X-Pilot-Faults": "0",
        }

    def test_a_plan_in_another_formatting_is_200_canonical(
        self, container: ServiceContainer, fake_sidecar: FakeSidecar, project: Project
    ) -> None:
        path = f"draft-{project.number}/plan.json"

        response = fake_sidecar.put(path, COMPACT_PLAN.encode(), None)

        canonical = container.plan_service().render(project)
        assert response.status_code == 200
        assert response.get_data() == canonical.text.encode()
        assert json.loads(canonical.text) == json.loads(COMPACT_PLAN)
        assert _pilot_headers(response) == {
            "X-Pilot-Hash": canonical.hash,
            "X-Pilot-Faults": "0",
            "X-Pilot-Stale": "true",
        }

    @pytest.mark.parametrize(
        "path",
        [
            "example/notes.md",
            "draft-1/../reference.json",
            "draft-1/items/9-nothing.md",
        ],
    )
    def test_a_path_of_no_syncing_project_is_404(
        self, session: DbSession, fake_sidecar: FakeSidecar, path: str
    ) -> None:
        response = fake_sidecar.put(path, b"# Stray\n", None)

        assert response.status_code == 404
        assert response.json["code"] == "RECORD_NOT_FOUND"
        assert list(session.scalars(select(SaveError))) == []

    def test_a_body_over_the_limit_is_413(
        self, container: ServiceContainer, fake_sidecar: FakeSidecar, project: Project
    ) -> None:
        _configure(container, sync_put_max_bytes=16)
        path = f"draft-{project.number}/timeline.json"

        assert fake_sidecar.put(path, b"x" * 16, None).status_code == 200
        response = fake_sidecar.put(path, b"x" * 17, None)

        assert response.status_code == 413
        assert response.json["error"] == "Request Entity Too Large"

    @pytest.mark.parametrize("base", [None, "", "NONE", HASH.upper(), HASH[1:]])
    def test_a_base_hash_that_is_neither_a_hash_nor_none_is_400(
        self, client: FlaskClient, base: str | None
    ) -> None:
        headers = {**sync_headers()}
        if base is not None:
            headers["X-Pilot-Base-Hash"] = base

        response = client.put(
            "/api/sync/files/reference.json", headers=headers, data=b"{}\n"
        )

        assert response.status_code == 400


class TestGetFile:
    """`GET /api/sync/files/<path>` (design 1 §5.1)."""

    def test_a_document_is_its_bytes_and_hash(
        self,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
    ) -> None:
        path = _bear_item(container, project, project_session, ANSWERED)

        response = fake_sidecar.get(path)

        assert response.status_code == 200
        assert response.mimetype == "application/octet-stream"
        assert response.get_data() == ANSWERED.encode()
        assert _pilot_headers(response) == {"X-Pilot-Hash": sha256_hex(ANSWERED)}

    def test_a_held_document_is_its_ingest(
        self,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
    ) -> None:
        path = _bear_item(container, project, project_session, ANSWERED)
        broken = ANSWERED + "\n```question id=Q1\n"
        fake_sidecar.save(path, broken)

        response = fake_sidecar.get(path)

        assert response.get_data() == broken.encode()
        assert _pilot_headers(response) == {"X-Pilot-Hash": sha256_hex(broken)}

    def test_a_view_is_its_projection(
        self, container: ServiceContainer, fake_sidecar: FakeSidecar
    ) -> None:
        reference = container.view_service().reference()

        response = fake_sidecar.get("reference.json")

        assert response.status_code == 200
        assert response.get_data() == reference.text.encode()
        assert _pilot_headers(response) == {"X-Pilot-Hash": reference.hash}

    def test_a_path_of_no_syncing_project_is_404(
        self, fake_sidecar: FakeSidecar
    ) -> None:
        response = fake_sidecar.get("example/notes.md")

        assert response.status_code == 404
        assert response.json["code"] == "RECORD_NOT_FOUND"


class TestManifest:
    """`POST /api/sync/manifest` (design 1 §5.1, §5.5)."""

    def test_the_answer_is_the_manifest_and_the_three_lists(
        self,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
    ) -> None:
        path = _bear_item(container, project, project_session, ANSWERED)
        folder = f"draft-{project.number}"
        plan = container.plan_service().render(project).hash
        timeline = container.view_service().timeline(project).hash
        reference = container.view_service().reference().hash
        shadow = {
            path: sha256_hex(ANSWERED),
            "old-project/project.md": HASH,
            "reference.json": reference,
        }

        response = fake_sidecar.post_manifest(
            {path: HASH, "reference.json": reference}, shadow
        )

        assert response.status_code == 200
        assert response.json == {
            "manifest": [
                {"path": path, "hash": sha256_hex(ANSWERED), "readonly": False},
                {"path": f"{folder}/plan.json", "hash": plan, "readonly": False},
                {"path": f"{folder}/timeline.json", "hash": timeline, "readonly": True},
                {"path": "reference.json", "hash": reference, "readonly": True},
            ],
            "send_up": [path],
            "write_down": [
                {"path": path, "hash": sha256_hex(ANSWERED), "readonly": False},
                {"path": f"{folder}/plan.json", "hash": plan, "readonly": False},
                {"path": f"{folder}/timeline.json", "hash": timeline, "readonly": True},
            ],
            "delete": ["old-project/project.md"],
        }

    @pytest.mark.parametrize(
        "body",
        [
            {"tree": {}},
            {"shadow": {}},
            {"tree": [], "shadow": {}},
            {"tree": {"reference.json": HASH.upper()}, "shadow": {}},
            {"tree": {}, "shadow": {"reference.json": "none"}},
        ],
    )
    def test_a_body_that_is_not_the_two_maps_of_hashes_is_400(
        self, client: FlaskClient, body: dict[str, object]
    ) -> None:
        response = client.post("/api/sync/manifest", json=body, headers=sync_headers())

        assert response.status_code == 400

    def test_a_body_that_is_not_json_is_400(self, client: FlaskClient) -> None:
        response = client.post(
            "/api/sync/manifest", data=b"tree", headers=sync_headers()
        )

        assert response.status_code == 400


class TestManifestSequences:
    """Design 1 §5.8's (re)connect and overflow, through the fake sidecar."""

    def test_a_first_connect_writes_every_path_down(
        self,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear_item(container, project, project_session, ANSWERED)
        draft = _bear_draft(container, project)
        folder = f"draft-{project.number}"

        answer = fake_sidecar.connect()

        assert set(fake_sidecar.tree) == {
            draft,
            item,
            f"{folder}/plan.json",
            f"{folder}/timeline.json",
            "reference.json",
        }
        assert answer["write_down"] == answer["manifest"]
        assert (answer["send_up"], answer["delete"]) == ([], [])
        _assert_in_step(container, fake_sidecar)

    def test_a_reconnect_sends_up_the_agents_saves_and_writes_down_the_records(
        self,
        session: DbSession,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item = _bear_item(container, project, project_session, DECISION)
        draft = _bear_draft(container, project)
        fake_sidecar.connect()
        # The stream drops: the agent edits the draft, the operator answers
        # the decision, and the sidecar hears of neither.
        fake_sidecar.write(draft, RETITLED)
        with scoped_session(container):
            document = session.scalars(
                select(Document).where(Document.path == "items/1-which-tent.md")
            ).one()
            container.record_service().answer(document, "D1", person, "Tunnel")

        answer = fake_sidecar.connect()

        assert (
            session.scalars(
                select(Document.published_text).where(Document.path == "project.md")
            ).one()
            == RETITLED
        )
        assert fake_sidecar.text(draft) == RETITLED
        assert "answer: Tunnel" in fake_sidecar.text(item)
        written = [entry["path"] for entry in answer["write_down"]]
        assert item in written
        assert draft not in written
        assert (answer["send_up"], answer["delete"]) == ([], [])
        _assert_in_step(container, fake_sidecar)

    def test_an_archived_projects_folder_is_deleted_and_a_stray_file_kept(
        self,
        session: DbSession,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        person: User,
    ) -> None:
        other = Project(created_by_user_id=person.id)
        session.add(other)
        session.flush()
        _bear_draft(container, project)
        _bear_draft(container, other)
        fake_sidecar.connect()
        archived = f"draft-{other.number}"
        synced = sorted(
            path for path in fake_sidecar.shadow if path.startswith(archived)
        )
        stray = f"{archived}/notes.md"
        fake_sidecar.write(stray, "# Notes\n")
        with scoped_session(container):
            other.archived = True

        answer = fake_sidecar.connect()

        assert answer["delete"] == synced
        assert [path for path in fake_sidecar.tree if path.startswith(archived)] == [
            stray
        ]
        assert fake_sidecar.notes == {stray: STRAY}
        _assert_in_step(container, fake_sidecar)

    def test_a_folder_that_takes_its_slug_moves_whole(
        self,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
    ) -> None:
        draft = _bear_draft(container, project)
        fake_sidecar.connect()
        folder = f"draft-{project.number}"
        with scoped_session(container):
            project.slug = "badge-colours"
            project.state_code = ProjectState.OPEN

        answer = fake_sidecar.connect()

        assert answer["delete"] == [
            f"{folder}/plan.json",
            draft,
            f"{folder}/timeline.json",
        ]
        assert [entry["path"] for entry in answer["write_down"]] == [
            "badge-colours/plan.json",
            "badge-colours/project.md",
            "badge-colours/timeline.json",
        ]
        assert fake_sidecar.text("badge-colours/project.md") == DRAFT
        _assert_in_step(container, fake_sidecar)

    def test_a_file_the_record_never_bore_stays_with_a_note(
        self,
        session: DbSession,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
    ) -> None:
        _bear_draft(container, project)
        fake_sidecar.connect()
        stray = f"draft-{project.number}/notes.md"
        fake_sidecar.write(stray, "# Notes\n")

        answers = [fake_sidecar.connect(), fake_sidecar.connect()]

        assert fake_sidecar.text(stray) == "# Notes\n"
        assert stray not in fake_sidecar.shadow
        assert fake_sidecar.notes == {stray: STRAY}
        assert [
            (answer["send_up"], answer["write_down"], answer["delete"])
            for answer in answers
        ] == [([], [], []), ([], [], [])]
        assert session.scalars(select(SaveError)).all() == []

    def test_a_file_the_agent_deleted_is_written_back(
        self,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
    ) -> None:
        draft = _bear_draft(container, project)
        fake_sidecar.connect()
        fake_sidecar.remove(draft)

        answer = fake_sidecar.connect()

        assert [entry["path"] for entry in answer["write_down"]] == [draft]
        assert fake_sidecar.text(draft) == DRAFT
        _assert_in_step(container, fake_sidecar)

    def test_a_held_document_stays_as_the_agent_left_it(
        self,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear_item(container, project, project_session, ANSWERED)
        fake_sidecar.connect()
        fake_sidecar.save(item, BROKEN)

        answer = fake_sidecar.connect()

        assert answer["write_down"] == []
        assert fake_sidecar.text(item) == BROKEN
        assert container.tree_service().held_path(item)
        _assert_in_step(container, fake_sidecar)

    def test_a_held_plan_comes_back_canonical_and_resolved(
        self,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        engine_events: list[EngineEvent],
    ) -> None:
        path = f"draft-{project.number}/plan.json"
        _bear_draft(container, project)
        fake_sidecar.connect()
        assert fake_sidecar.save(path, MISSPELT_PLAN).faults == 1

        answer = fake_sidecar.connect()

        rendering = container.plan_service().render(project)
        assert [entry["path"] for entry in answer["write_down"]] == [path]
        assert fake_sidecar.text(path) == rendering.text
        assert not container.tree_service().held_path(path)
        assert engine_events[-1] == ErrorsResolved(project.id, path)
        _assert_in_step(container, fake_sidecar)

    def test_an_overflow_sends_up_every_change_and_reconciles(
        self,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear_item(container, project, project_session, ANSWERED)
        draft = _bear_draft(container, project)
        fake_sidecar.connect()
        edited = ANSWERED.replace("# Which tent?", "# Which tent for the lake?")
        # The watch overflows: these writes reach the sidecar as no event.
        fake_sidecar.write(item, edited)
        fake_sidecar.write(draft, RETITLED)

        answer = fake_sidecar.overflow()

        assert container.tree_service().read(item).content == edited.encode()
        assert container.tree_service().read(draft).content == RETITLED.encode()
        # The item's new title moved the timeline.
        assert [entry["path"] for entry in answer["write_down"]] == [
            f"draft-{project.number}/timeline.json"
        ]
        assert answer["send_up"] == []
        _assert_in_step(container, fake_sidecar)


class TestEvents:
    """`GET /api/sync/events` (design 1 §5.4)."""

    def test_hello_comes_first_with_the_range_and_the_manifest_hash(
        self, container: ServiceContainer, client: FlaskClient, project: Project
    ) -> None:
        _bear_draft(container, project)
        manifest_hash = container.sync_service().manifest_hash()

        with _stream(client) as frames:
            assert next(frames) == _hello(manifest_hash)
            assert next(frames) == HEARTBEAT

    def test_a_change_follows_every_tree_hash_moved_once_committed(
        self,
        container: ServiceContainer,
        client: FlaskClient,
        project: Project,
        project_session: models.Session,
        engine_events: list[EngineEvent],
    ) -> None:
        with _stream(client) as frames:
            next(frames)
            path = _bear_item(container, project, project_session, ANSWERED)
            moved = [
                event for event in engine_events if isinstance(event, TreeHashMoved)
            ]

            assert [event.path for event in moved] == [
                path,
                f"draft-{project.number}/timeline.json",
            ]
            assert [next(frames) for _ in moved] == [
                _change(event.path, event.hash) for event in moved
            ]
            assert next(frames) == HEARTBEAT

    def test_a_rolled_back_transaction_sends_nothing(
        self, container: ServiceContainer, client: FlaskClient
    ) -> None:
        with _stream(client) as frames:
            next(frames)
            with pytest.raises(RuntimeError), scoped_session(container):
                container.engine_bus().emit(TreeHashMoved("draft-1/project.md", HASH))
                raise RuntimeError("the transaction fails")

            assert next(frames) == HEARTBEAT

    def test_the_manifest_event_is_a_manifest(
        self, container: ServiceContainer, client: FlaskClient
    ) -> None:
        with _stream(client) as frames:
            next(frames)
            with scoped_session(container):
                container.engine_bus().emit(ManifestChanged())

            assert next(frames) == MANIFEST
            assert next(frames) == HEARTBEAT

    def test_the_document_events_are_not_the_streams(
        self, container: ServiceContainer, client: FlaskClient, project: Project
    ) -> None:
        with _stream(client) as frames:
            next(frames)
            with scoped_session(container):
                container.engine_bus().emit(
                    DocumentModified(project.id, "draft-1/project.md")
                )

            assert next(frames) == HEARTBEAT

    def test_an_idle_stream_writes_a_heartbeat_comment(
        self, container: ServiceContainer, client: FlaskClient
    ) -> None:
        heartbeat = container.app_config().sync_heartbeat_seconds

        with _stream(client) as frames:
            next(frames)
            started = time.perf_counter()

            assert next(frames) == HEARTBEAT
            assert time.perf_counter() - started >= heartbeat
            assert next(frames) == HEARTBEAT

    def test_the_stream_ends_on_prepare_shutdown_and_lets_no_new_one_in(
        self, container: ServiceContainer, client: FlaskClient
    ) -> None:
        coordinator = LifecycleCoordinator(graceful_shutdown_timeout=1)
        _own_streams(container, coordinator)

        with _stream(client) as frames:
            assert next(frames).startswith("event: hello\n")
            coordinator.shutdown()

            assert next(frames, None) is None
        with _stream(client) as frames:
            assert next(frames, None) is None

    def test_a_stream_that_falls_behind_ends_and_never_blocks_the_commit(
        self, container: ServiceContainer, client: FlaskClient
    ) -> None:
        coordinator = LifecycleCoordinator(graceful_shutdown_timeout=1)
        _own_streams(container, coordinator, queue_max_events=2)

        with _stream(client) as frames:
            next(frames)
            with scoped_session(container):
                for number in range(3):
                    container.engine_bus().emit(
                        TreeHashMoved(f"draft-{number + 1}/project.md", HASH)
                    )

            assert next(frames, None) is None

    def test_connects_and_the_open_stream_are_observed(
        self, client: FlaskClient
    ) -> None:
        connects, connected = _stream_counts()

        with _stream(client) as frames:
            next(frames)
            assert _stream_counts() == (connects + 1, connected + 1)

        assert _stream_counts() == (connects + 1, connected)

    def test_a_head_of_the_stream_leaves_no_stream_open(
        self, client: FlaskClient
    ) -> None:
        connects, connected = _stream_counts()

        response = client.head(EVENTS, headers=sync_headers())
        # Closed as the server closes it once sent: its body never started,
        # so the generator's `finally` never runs.
        response.close()

        assert response.status_code == 200
        assert _stream_counts() == (connects + 1, connected)

    def test_a_refused_stream_is_the_status_itself(self, client: FlaskClient) -> None:
        headers = {**sync_headers()}
        del headers["Authorization"]
        connects = _stream_counts()

        response = client.get(EVENTS, headers=headers)

        assert response.status_code == 401
        assert response.mimetype == "application/json"
        assert _stream_counts() == connects


class TestEventsSequences:
    """Design 1 §5.8, the change stream through the fake sidecar."""

    def test_a_connect_takes_hello_then_reconciles(
        self,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
    ) -> None:
        _bear_draft(container, project)
        manifest_hash = container.sync_service().manifest_hash()

        fake_sidecar.connect()

        assert fake_sidecar.hello == {
            "protocol": {"min": SYNC_PROTOCOL_MIN, "max": SYNC_PROTOCOL_MAX},
            "manifest_hash": manifest_hash,
        }
        assert fake_sidecar.drain() == []
        _assert_in_step(container, fake_sidecar)

    def test_the_sidecars_own_write_echoes_back_ignored(
        self,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
    ) -> None:
        draft = _bear_draft(container, project)
        fake_sidecar.connect()

        fake_sidecar.save(draft, RETITLED)

        assert fake_sidecar.drain() == [f"draft-{project.number}/timeline.json"]
        _assert_in_step(container, fake_sidecar)

    def test_a_manifest_event_reconciles(
        self,
        session: DbSession,
        container: ServiceContainer,
        client: FlaskClient,
        fake_sidecar: FakeSidecar,
        project: Project,
        person: User,
    ) -> None:
        other = Project(created_by_user_id=person.id)
        session.add(other)
        session.flush()
        _bear_draft(container, project)
        _bear_draft(container, other)
        fake_sidecar.connect()
        fake_sidecar.drain()
        with scoped_session(container):
            other.archived = True
        assert fake_sidecar.drain() == []

        assert client.post("/api/testing/sync/manifest").status_code == 204
        fake_sidecar.drain()

        archived = f"draft-{other.number}/"
        assert not [path for path in fake_sidecar.tree if path.startswith(archived)]
        _assert_in_step(container, fake_sidecar)


class TestCheck:
    """`POST /api/sync/check` (design 1 §5.1, §5.6)."""

    def test_the_answer_is_checked_the_errors_and_the_deferrals(
        self,
        session: DbSession,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item = _bear_item(container, project, project_session, ANSWERED)
        block, done = _done_deferrals(container, project, project_session, person)
        plan = f"draft-{project.number}/plan.json"
        fake_sidecar.save(item, ANSWERED.replace("by: ada", "by: agent"))
        fake_sidecar.save(plan, MISSPELT_PLAN)
        reverted, held = (
            session.scalars(
                select(SaveError.message).where(SaveError.kind_code == kind)
            ).one()
            for kind in (ErrorKind.REVERTED, ErrorKind.PARSE)
        )

        response = fake_sidecar.post_check(item, sha256_hex(ANSWERED), 0.1)

        assert response.status_code == 200
        assert response.json == {
            "checked": True,
            "errors": [
                {"path": item, "kind": "reverted", "line": 5, "message": reverted},
                {"path": plan, "kind": "parse", "line": None, "message": held},
            ],
            "homeless_deferrals": [
                {
                    "block": f"{block}/D1",
                    "document": done,
                    "title": "Camp chores",
                    "to": "fix",
                },
                {
                    "block": f"{block}/Q1",
                    "document": done,
                    "title": "Camp chores",
                    "to": "plan",
                },
            ],
        }

    def test_the_answer_is_the_files_project_folders_alone(
        self,
        session: DbSession,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        other = Project(created_by_user_id=person.id)
        session.add(other)
        session.flush()
        mine = _bear_item(container, project, project_session, ANSWERED)
        _bear_item(container, other, project_session, ANSWERED)
        my_block, my_done = _done_deferrals(container, project, project_session, person)
        their_block, their_draft = _done_deferrals(
            container, other, project_session, person
        )
        with scoped_session(container):
            other.slug = "camp"
            other.state_code = ProjectState.OPEN
        theirs = "camp/items/1-which-tent.md"
        their_done = their_draft.replace(f"draft-{other.number}/", "camp/")
        reverting = ANSWERED.replace("by: ada", "by: agent")
        fake_sidecar.save(mine, reverting)
        fake_sidecar.save(theirs, reverting)

        answers = [
            fake_sidecar.post_check(path, sha256_hex(ANSWERED), 0.0).json
            for path in (mine, mine, theirs, theirs)
        ]

        assert [
            [(error["path"], error["kind"]) for error in answer["errors"]]
            for answer in answers
        ] == [[(mine, "reverted")], [], [(theirs, "reverted")], []]
        assert [
            [
                (deferral["block"], deferral["document"])
                for deferral in answer["homeless_deferrals"]
            ]
            for answer in answers
        ] == [
            [(f"{my_block}/D1", my_done), (f"{my_block}/Q1", my_done)],
            [(f"{my_block}/D1", my_done), (f"{my_block}/Q1", my_done)],
            [(f"{their_block}/D1", their_done), (f"{their_block}/Q1", their_done)],
            [(f"{their_block}/D1", their_done), (f"{their_block}/Q1", their_done)],
        ]

    @pytest.mark.parametrize(
        ("path", "sibling"),
        [
            ("reference.json", "notes.md"),
            ("example/notes.md", "example/plan.json"),
            ("{archived}/items/1-which-tent.md", "{archived}/plan.json"),
        ],
    )
    def test_a_path_under_no_syncing_folder_is_answered_its_own_errors_alone(
        self,
        session: DbSession,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
        person: User,
        path: str,
        sibling: str,
    ) -> None:
        archived = Project(created_by_user_id=person.id)
        session.add(archived)
        session.flush()
        mine = _bear_item(container, project, project_session, ANSWERED)
        _done_deferrals(container, project, project_session, person)
        fake_sidecar.save(mine, ANSWERED.replace("by: ada", "by: agent"))
        with scoped_session(container):
            archived.archived = True
        path, sibling = (
            name.format(archived=f"draft-{archived.number}") for name in (path, sibling)
        )
        session.add_all(
            SaveError(
                environment_id=STORE_ENVIRONMENT_ID,
                path=at,
                kind_code=kind,
                line=1,
                message="a fault",
            )
            for at, kind in (
                (path, ErrorKind.REVERTED),
                (path, ErrorKind.PARSE),
                (sibling, ErrorKind.REVERTED),
            )
        )
        session.flush()

        answers = [fake_sidecar.post_check(path, HASH, 0.0).json for _ in range(2)]

        assert [
            [(error["path"], error["kind"]) for error in answer["errors"]]
            for answer in answers
        ] == [[(path, "reverted"), (path, "parse")], [(path, "parse")]]
        assert [answer["homeless_deferrals"] for answer in answers] == [[], []]
        assert sorted(
            (at, kind)
            for at, kind in session.execute(select(SaveError.path, SaveError.kind_code))
        ) == sorted(
            [
                (mine, ErrorKind.REVERTED),
                (path, ErrorKind.PARSE),
                (sibling, ErrorKind.REVERTED),
            ]
        )

    def test_a_deferral_in_a_registered_document_with_no_title_has_none(
        self,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        environment: Environment,
        project_session: models.Session,
        person: User,
    ) -> None:
        untitled = DEFERRED.replace("---\ntitle: Camp chores\n---\n", "")
        with scoped_session(container) as db:
            container.plan_service().save(project, FIX_PLAN.encode())
            documents = container.document_service()
            item = documents.bear_item(
                project, "decision", "Camp chores", project_session, DEFERRED
            )
            document = db.get_one(Document, item.id)
            document.source_environment_id = environment.id
            document.source_path = "/work/Example/chores.md"
            documents.publish(document, untitled)
            container.record_service().done(item, person)
            block = str(item.id)
            path = f"draft-{project.number}/{document.path}"

        response = fake_sidecar.post_check(path, sha256_hex(untitled), 0.1)

        assert response.status_code == 200
        assert response.json["homeless_deferrals"] == [
            {"block": f"{block}/D1", "document": path, "title": None, "to": "fix"},
            {"block": f"{block}/Q1", "document": path, "title": None, "to": "plan"},
        ]

    def test_the_reverted_errors_answered_are_deleted_and_the_parse_errors_stand(
        self,
        session: DbSession,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear_item(container, project, project_session, ANSWERED)
        plan = f"draft-{project.number}/plan.json"
        fake_sidecar.save(item, ANSWERED.replace("by: ada", "by: agent"))
        fake_sidecar.save(plan, MISSPELT_PLAN)

        answers = [fake_sidecar.post_check(plan, HASH, 0.0).json for _ in range(2)]

        assert [
            [(error["path"], error["kind"]) for error in answer["errors"]]
            for answer in answers
        ] == [[(item, "reverted"), (plan, "parse")], [(plan, "parse")]]
        assert session.scalars(select(SaveError.kind_code)).all() == [ErrorKind.PARSE]

    def test_a_document_checks_its_tree_hash_and_its_latest_save(
        self,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        caplog: pytest.LogCaptureFixture,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear_item(container, project, project_session, ANSWERED)
        edited = ANSWERED.replace("# Which tent?", "# Which tent for the lake?")
        reverting = edited.replace("by: ada", "by: agent")

        with caplog.at_level(logging.WARNING):
            clean = fake_sidecar.save(item, edited).status
            clean_checked = fake_sidecar.check(item).checked
            reverted = fake_sidecar.save(item, reverting).status
            rewritten = fake_sidecar.text(item)
            # The merged bytes the sidecar wrote, and the save it sent.
            reverted_checked = [
                fake_sidecar.check(item).checked,
                fake_sidecar.post_check(item, sha256_hex(reverting), 0.0).json[
                    "checked"
                ],
            ]
            held = fake_sidecar.save(item, BROKEN).status
            held_checked = fake_sidecar.check(item).checked

        assert (clean, reverted, held) == (204, 200, 204)
        assert rewritten == edited
        assert (clean_checked, reverted_checked, held_checked) == (
            True,
            [True, True],
            True,
        )
        assert caplog.text == ""

    def test_a_hash_the_server_does_not_hold_is_not_checked_and_logged(
        self,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        caplog: pytest.LogCaptureFixture,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear_item(container, project, project_session, ANSWERED)

        with caplog.at_level(logging.WARNING):
            response = fake_sidecar.post_check(item, HASH, 0.0)

        assert response.json["checked"] is False
        assert f"Sync check of {item}: the store's sidecar has {HASH} acked" in (
            caplog.text
        )

    def test_a_plan_checks_its_rendering_and_while_held_any_hash(
        self,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
    ) -> None:
        plan = f"draft-{project.number}/plan.json"
        _bear_draft(container, project)

        assert fake_sidecar.save(plan, COMPACT_PLAN).status == 200
        canonical = fake_sidecar.check(plan).checked
        # The save the canonical rendering replaced is stored nowhere.
        compact = fake_sidecar.post_check(plan, sha256_hex(COMPACT_PLAN), 0.0)
        assert fake_sidecar.save(plan, MISSPELT_PLAN).faults == 1
        held = [
            fake_sidecar.check(plan).checked,
            fake_sidecar.post_check(plan, HASH, 0.0).json["checked"],
        ]
        fake_sidecar.connect()
        written_down = fake_sidecar.post_check(plan, sha256_hex(MISSPELT_PLAN), 0.0)

        assert (canonical, compact.json["checked"]) == (True, False)
        assert held == [True, True]
        assert written_down.json["checked"] is False
        assert fake_sidecar.check(plan).checked

    def test_a_view_checks_its_projection(
        self, container: ServiceContainer, fake_sidecar: FakeSidecar, project: Project
    ) -> None:
        timeline = f"draft-{project.number}/timeline.json"
        fake_sidecar.connect()

        assert fake_sidecar.check(timeline).checked
        assert fake_sidecar.check("reference.json").checked
        assert fake_sidecar.post_check(timeline, HASH, 0.0).json["checked"] is False

    @pytest.mark.parametrize(
        "path", ["example/notes.md", "draft-1/notes.md", "draft-1/../reference.json"]
    )
    def test_a_path_the_tree_does_not_resolve_is_not_checked(
        self, fake_sidecar: FakeSidecar, path: str
    ) -> None:
        response = fake_sidecar.post_check(path, HASH, 0.0)

        assert response.status_code == 200
        assert response.json["checked"] is False

    def test_the_hooks_wait_is_observed(self, fake_sidecar: FakeSidecar) -> None:
        count = _sample(HOOK_WAIT_SECONDS, "pilot_sync_hook_wait_seconds_count")

        fake_sidecar.post_check("reference.json", HASH, 0.125)

        assert (
            _sample(HOOK_WAIT_SECONDS, "pilot_sync_hook_wait_seconds_count")
            == count + 1
        )

    @pytest.mark.parametrize(
        "body",
        [
            {"hash": HASH, "wait_seconds": 0.0},
            {"path": "reference.json", "wait_seconds": 0.0},
            {"path": "reference.json", "hash": HASH},
            {"path": "reference.json", "hash": HASH.upper(), "wait_seconds": 0.0},
            {"path": "reference.json", "hash": HASH, "wait_seconds": -0.1},
            {"path": "reference.json", "hash": HASH, "wait_seconds": "soon"},
        ],
    )
    def test_a_body_that_is_not_a_check_is_400(
        self, client: FlaskClient, body: dict[str, object]
    ) -> None:
        response = client.post("/api/sync/check", json=body, headers=sync_headers())

        assert response.status_code == 400

    def test_a_refused_check_deletes_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear_item(container, project, project_session, ANSWERED)
        fake_sidecar.save(item, ANSWERED.replace("by: ada", "by: agent"))
        _configure(container, sync_token="")

        response = fake_sidecar.post_check(item, sha256_hex(ANSWERED), 0.0)

        assert response.status_code == 401
        assert session.scalars(select(SaveError.kind_code)).all() == [
            ErrorKind.REVERTED
        ]


class TestCheckSequences:
    """Design 1 §5.6, the hook's check through the fake sidecar: what the
    agent is told after an edit."""

    def test_a_reverted_line_is_told_once(
        self,
        session: DbSession,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear_item(container, project, project_session, ANSWERED)
        fake_sidecar.connect()
        fake_sidecar.save(item, ANSWERED.replace("by: ada", "by: agent"))
        told = _told(session, item)

        checks = [fake_sidecar.check(item), fake_sidecar.check(item)]

        assert told.startswith(f"{item}:5: ")
        assert checks == [Check(True, told), Check(True, "")]

    def test_a_parse_error_is_told_until_a_clean_save(
        self,
        session: DbSession,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear_item(container, project, project_session, ANSWERED)
        fake_sidecar.connect()
        fake_sidecar.save(item, BROKEN)
        told = _told(session, item)

        held = [fake_sidecar.check(item), fake_sidecar.check(item)]
        fake_sidecar.save(item, ANSWERED.replace("# Which tent?", "# Which tent now?"))

        assert told
        assert held == [Check(True, told), Check(True, told)]
        assert fake_sidecar.check(item) == Check(True, "")

    def test_the_local_notes_are_told_after_the_errors(
        self,
        session: DbSession,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear_item(container, project, project_session, ANSWERED)
        stray = f"draft-{project.number}/notes.md"
        fake_sidecar.write(stray, "# Notes\n")
        fake_sidecar.connect()
        fake_sidecar.save(item, ANSWERED.replace("by: ada", "by: agent"))
        told = _told(session, item)

        checks = [fake_sidecar.check(stray), fake_sidecar.check(item)]

        assert checks == [
            Check(False, f"{told}{stray}: {STRAY}\n"),
            Check(True, f"{stray}: {STRAY}\n"),
        ]

    def test_a_deferral_without_a_home_is_told_until_a_note_names_it(
        self,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        block, document = _done_deferrals(container, project, project_session, person)
        plan = f"draft-{project.number}/plan.json"
        fake_sidecar.connect()
        noted = json.loads(FIX_PLAN)
        noted["tasks"][0]["notes"] = [
            {
                "id": "n1",
                "summary": "Pick the tent",
                "content": "Once the client runs.",
                "refs": [f"{block}/D1"],
            }
        ]

        told = fake_sidecar.check(plan).text
        fake_sidecar.save(plan, json.dumps(noted))
        homed_one = fake_sidecar.check(plan).text
        # Striking the note leaves the block its home: the note was dealt with.
        fake_sidecar.save(plan, FIX_PLAN)
        struck = fake_sidecar.check(plan).text
        noted["notes"] = [
            {
                "id": "n2",
                "summary": "Sweep before the finish",
                "content": "Settle what waited.",
                "refs": [f"{block}/Q1"],
            }
        ]
        fake_sidecar.save(plan, json.dumps(noted))

        assert told == (
            f"{HOMELESS}\n"
            f"- {block}/D1 in {document} (Camp chores), to: fix\n"
            f"- {block}/Q1 in {document} (Camp chores), to: plan\n"
        )
        assert (
            homed_one
            == struck
            == (f"{HOMELESS}\n- {block}/Q1 in {document} (Camp chores), to: plan\n")
        )
        assert fake_sidecar.check(plan) == Check(True, "")
