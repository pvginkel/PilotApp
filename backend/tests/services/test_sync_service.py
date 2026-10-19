"""The sync service: the gate's refusals and the store's Environment, the
put's metrics, the manifest reconcile, and the hook's check (design 1 §5.1,
§5.5, §5.6, §5.7)."""

import json
import logging

import pytest
from dependency_injector import providers
from prometheus_client.metrics import MetricWrapperBase
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.engine.bus import EngineEvent, ErrorsResolved
from app.engine.ingest import PathKind
from app.engine.paths import sha256_hex
from app.engine.tree import ManifestEntry, TreeFile
from app.exceptions import (
    AuthenticationException,
    AuthorizationException,
    RecordNotFoundException,
    SyncProtocolUnsupportedException,
)
from app.models import Environment, Project, SaveError
from app.models.reference import ErrorKind
from app.services.container import ServiceContainer
from app.services.sync_service import (
    FAULTS_TOTAL,
    HOOK_WAIT_SECONDS,
    INGEST_SECONDS,
    RECONCILES_TOTAL,
    STALE_PUTS_TOTAL,
    CheckedError,
    Reconciled,
    SyncService,
)
from tests.support.fake_sidecar import STORE_ENVIRONMENT_ID, SYNC_TOKEN

BEARER = f"Bearer {SYNC_TOKEN}"

ANSWERED = """# Which tent?

```decision id=D1
options:
  - Dome
  - Tunnel
answer: Dome
by: ada
at: 2026-10-12T09:40:00Z
```
"""

BROKEN = ANSWERED + "\n```question id=Q1\n"

PLAN = json.dumps({"ticket": "MD-8", "tasks": [], "notes": []})

MISSPELT_PLAN = '{"tickets": "MD-9"}\n'

HASH = "a" * 64


def _sample(metric: MetricWrapperBase, name: str, **labels: str) -> float:
    for family in metric.collect():
        for sample in family.samples:
            if sample.name == name and sample.labels == labels:
                return sample.value
    return 0.0


def _ingests(kind: str, outcome: str) -> float:
    return _sample(
        INGEST_SECONDS, "pilot_sync_ingest_seconds_count", kind=kind, outcome=outcome
    )


def _faults(kind: str) -> float:
    return _sample(FAULTS_TOTAL, "pilot_sync_faults_total", kind=kind)


def _stale_puts() -> float:
    return _sample(STALE_PUTS_TOTAL, "pilot_sync_stale_puts_total")


def _reconciles() -> float:
    return _sample(RECONCILES_TOTAL, "pilot_sync_reconciles_total")


def _hook_waits() -> tuple[float, float]:
    return (
        _sample(HOOK_WAIT_SECONDS, "pilot_sync_hook_wait_seconds_count"),
        _sample(HOOK_WAIT_SECONDS, "pilot_sync_hook_wait_seconds_sum"),
    )


def _error(
    environment_id: str, path: str, kind: ErrorKind, line: int | None
) -> SaveError:
    return SaveError(
        environment_id=environment_id,
        path=path,
        kind_code=kind,
        line=line,
        message=f"{kind} on line {line}",
    )


def _sync(container: ServiceContainer) -> SyncService:
    service: SyncService = container.sync_service()
    return service


def _configure(container: ServiceContainer, **changes: object) -> None:
    settings = container.app_config().model_copy(update=changes)
    container.app_config.override(providers.Object(settings))


def _bear_item(
    container: ServiceContainer, project: Project, session: models.Session
) -> str:
    with scoped_session(container):
        container.document_service().bear_item(
            project, "decision", "Which tent?", session, ANSWERED
        )
    return f"draft-{project.number}/items/1-which-tent.md"


class TestSyncService:
    def test_admit_lets_the_store_through_and_makes_its_environment(
        self, session: DbSession, container: ServiceContainer
    ) -> None:
        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "1")

        store = session.get_one(Environment, STORE_ENVIRONMENT_ID)
        assert (store.id, store.name, store.exempt) == (
            STORE_ENVIRONMENT_ID,
            STORE_ENVIRONMENT_ID,
            False,
        )

    def test_admit_leaves_an_environment_that_exists(
        self,
        session: DbSession,
        container: ServiceContainer,
        environment: Environment,
    ) -> None:
        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "1")
        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "1")

        session.refresh(environment)
        assert environment.name == "Example-1"
        assert session.scalars(select(Environment)).all() == [environment]

    @pytest.mark.parametrize(
        "authorization",
        [None, "", SYNC_TOKEN, f"Bearer {SYNC_TOKEN}x", "Bearer another", "Basic x"],
    )
    def test_admit_refuses_a_call_without_the_bearer(
        self, session: DbSession, container: ServiceContainer, authorization: str | None
    ) -> None:
        with pytest.raises(AuthenticationException):
            _sync(container).admit(authorization, STORE_ENVIRONMENT_ID, "1")

        assert session.get(Environment, STORE_ENVIRONMENT_ID) is None

    def test_admit_refuses_every_call_while_the_token_is_empty(
        self, container: ServiceContainer
    ) -> None:
        _configure(container, sync_token="")

        for authorization in (BEARER, "Bearer ", None):
            with pytest.raises(AuthenticationException):
                _sync(container).admit(authorization, STORE_ENVIRONMENT_ID, "1")

    def test_admit_refuses_a_bearer_that_is_not_ascii(
        self, container: ServiceContainer
    ) -> None:
        with pytest.raises(AuthenticationException):
            _sync(container).admit("Bearer tökén", STORE_ENVIRONMENT_ID, "1")

    @pytest.mark.parametrize("environment_id", [None, "", "example-env-2"])
    def test_admit_refuses_another_environment(
        self,
        session: DbSession,
        container: ServiceContainer,
        environment_id: str | None,
    ) -> None:
        with pytest.raises(AuthorizationException) as refused:
            _sync(container).admit(BEARER, environment_id, "1")

        assert repr(environment_id) in refused.value.message
        assert session.scalars(select(Environment)).all() == []

    def test_admit_refuses_every_call_while_the_store_is_not_configured(
        self, container: ServiceContainer
    ) -> None:
        _configure(container, store_environment_id="")

        for environment_id in ("", STORE_ENVIRONMENT_ID):
            with pytest.raises(AuthorizationException):
                _sync(container).admit(BEARER, environment_id, "1")

    @pytest.mark.parametrize("protocol", [None, "", "0", "2", "one", "+1", " 1", "1.0"])
    def test_admit_refuses_a_version_outside_the_range(
        self, session: DbSession, container: ServiceContainer, protocol: str | None
    ) -> None:
        with pytest.raises(SyncProtocolUnsupportedException) as refused:
            _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, protocol)

        assert (refused.value.minimum, refused.value.maximum) == (1, 1)
        assert session.get(Environment, STORE_ENVIRONMENT_ID) is None

    def test_put_keys_its_save_errors_by_the_stores_environment(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        path = _bear_item(container, project, project_session)
        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "1")

        answer = _sync(container).put(path, BROKEN.encode(), sha256_hex(ANSWERED))

        assert answer.held
        assert {
            (error.environment_id, error.path)
            for error in session.scalars(select(SaveError))
        } == {(STORE_ENVIRONMENT_ID, path)}

    def test_put_observes_a_published_save(
        self,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        path = _bear_item(container, project, project_session)
        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "1")
        before = (_ingests("document", "published"), _stale_puts())
        edited = ANSWERED.replace("# Which tent?", "# Which tent for the lake?")

        answer = _sync(container).put(path, edited.encode(), sha256_hex(ANSWERED))

        assert (answer.kind, answer.held, answer.faults) == (
            PathKind.DOCUMENT,
            False,
            (),
        )
        assert (_ingests("document", "published"), _stale_puts()) == (
            before[0] + 1,
            before[1],
        )

    def test_put_observes_a_reverted_save_and_its_faults(
        self,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        path = _bear_item(container, project, project_session)
        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "1")
        before = (_ingests("document", "reverted"), _faults("reverted"))
        save = ANSWERED.replace("by: ada", "by: agent")

        answer = _sync(container).put(path, save.encode(), sha256_hex(ANSWERED))

        assert len(answer.faults) == 1
        assert (_ingests("document", "reverted"), _faults("reverted")) == (
            before[0] + 1,
            before[1] + 1,
        )

    def test_put_observes_a_held_save_and_its_faults(
        self,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        path = _bear_item(container, project, project_session)
        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "1")
        before = (_ingests("document", "held"), _faults("parse"), _faults("reverted"))

        answer = _sync(container).put(path, BROKEN.encode(), sha256_hex(ANSWERED))

        assert answer.faults
        assert (
            _ingests("document", "held"),
            _faults("parse"),
            _faults("reverted"),
        ) == (before[0] + 1, before[1] + len(answer.faults), before[2])

    def test_put_observes_a_plan(
        self, container: ServiceContainer, project: Project
    ) -> None:
        path = f"draft-{project.number}/plan.json"
        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "1")
        before = (_ingests("plan", "published"), _ingests("plan", "held"))

        published = _sync(container).put(path, PLAN.encode(), None)
        held = _sync(container).put(path, MISSPELT_PLAN.encode(), published.hash)

        assert (published.kind, held.kind, held.held) == (
            PathKind.PLAN,
            PathKind.PLAN,
            True,
        )
        assert (_ingests("plan", "published"), _ingests("plan", "held")) == (
            before[0] + 1,
            before[1] + 1,
        )

    def test_put_observes_a_read_only_path_and_a_stale_base(
        self, container: ServiceContainer, project: Project
    ) -> None:
        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "1")
        before = (_ingests("view", "readonly"), _stale_puts())

        answer = _sync(container).put(
            f"draft-{project.number}/timeline.json", b"{}\n", None
        )

        assert (answer.kind, answer.stale) == (PathKind.VIEW, True)
        assert (_ingests("view", "readonly"), _stale_puts()) == (
            before[0] + 1,
            before[1] + 1,
        )

    def test_put_refuses_a_path_of_no_syncing_project(
        self, container: ServiceContainer
    ) -> None:
        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "1")
        before = _stale_puts()

        with pytest.raises(RecordNotFoundException):
            _sync(container).put("example/notes.md", b"# Stray\n", None)

        assert _stale_puts() == before

    def test_get_is_the_trees_bytes_and_hash(
        self,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        path = _bear_item(container, project, project_session)

        assert _sync(container).get(path) == TreeFile(
            ANSWERED.encode(), sha256_hex(ANSWERED)
        )

    def test_get_refuses_a_path_of_no_syncing_project(
        self, container: ServiceContainer
    ) -> None:
        with pytest.raises(RecordNotFoundException):
            _sync(container).get("example/notes.md")

    def test_reconcile_answers_the_three_lists_by_one_rule(
        self,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear_item(container, project, project_session)
        folder = f"draft-{project.number}"
        manifest = container.tree_service().manifest()
        hashes = {entry.path: entry.hash for entry in manifest}
        # The item as synced, an older timeline as synced, the plan gone from
        # disk, and in the shadow a path of a folder no longer synced.
        tree = {
            item: hashes[item],
            f"{folder}/timeline.json": HASH,
            "reference.json": hashes["reference.json"],
        }
        shadow = {**tree, "old-project/project.md": HASH}

        answer = _sync(container).reconcile(tree, shadow)

        assert answer == Reconciled(
            manifest=manifest,
            send_up=[],
            write_down=[
                entry
                for entry in manifest
                if entry.path in (f"{folder}/plan.json", f"{folder}/timeline.json")
            ],
            delete=["old-project/project.md"],
        )
        assert answer.write_down[1] == ManifestEntry(
            f"{folder}/timeline.json", hashes[f"{folder}/timeline.json"], True
        )

    def test_reconcile_lists_a_file_the_record_never_bore_nowhere(
        self, container: ServiceContainer, project: Project
    ) -> None:
        stray = f"draft-{project.number}/notes.md"
        tree = {entry.path: entry.hash for entry in container.tree_service().manifest()}

        answer = _sync(container).reconcile({**tree, stray: HASH}, tree)

        assert (answer.send_up, answer.write_down, answer.delete) == ([], [], [])

    def test_reconcile_logs_what_was_not_sent_up_and_acts_on_nothing(
        self,
        container: ServiceContainer,
        caplog: pytest.LogCaptureFixture,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear_item(container, project, project_session)
        tree = {entry.path: entry.hash for entry in container.tree_service().manifest()}
        on_disk = sha256_hex(ANSWERED.replace("Dome", "Tunnel"))

        with caplog.at_level(logging.WARNING):
            answer = _sync(container).reconcile({**tree, item: on_disk}, tree)

        assert answer.send_up == [item]
        assert [entry.path for entry in answer.write_down] == [item]
        assert f"had not sent up {item}" in caplog.text
        assert container.tree_service().read(item).content == ANSWERED.encode()

    def test_reconcile_leaves_a_held_document_whose_disk_holds_its_ingest(
        self,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear_item(container, project, project_session)
        sync = _sync(container)
        sync.admit(BEARER, STORE_ENVIRONMENT_ID, "1")
        held = sync.put(item, BROKEN.encode(), sha256_hex(ANSWERED))
        tree = {entry.path: entry.hash for entry in container.tree_service().manifest()}

        answer = sync.reconcile(tree, tree)

        assert tree[item] == held.hash == sha256_hex(BROKEN)
        assert answer.write_down == []
        assert container.tree_service().held_path(item)

    def test_reconcile_writes_a_held_plan_down_canonical_and_resolves_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
    ) -> None:
        path = f"draft-{project.number}/plan.json"
        with scoped_session(container):
            sync = _sync(container)
            sync.admit(BEARER, STORE_ENVIRONMENT_ID, "1")
            held = sync.put(path, MISSPELT_PLAN.encode(), None)
        tree = {entry.path: entry.hash for entry in container.tree_service().manifest()}
        engine_events.clear()

        with scoped_session(container):
            answer = _sync(container).reconcile({**tree, path: held.hash}, tree)

        assert answer.write_down == [
            ManifestEntry(path, container.plan_service().render(project).hash, False)
        ]
        assert session.scalars(select(SaveError)).all() == []
        assert engine_events == [ErrorsResolved(project.id, path)]

    def test_every_reconcile_is_counted(self, container: ServiceContainer) -> None:
        before = _reconciles()

        _sync(container).reconcile({}, {})
        _sync(container).reconcile({}, {})

        assert _reconciles() == before + 2

    def test_manifest_hash_hashes_the_manifests_entries_in_path_order(
        self, container: ServiceContainer, project: Project
    ) -> None:
        with scoped_session(container):
            container.document_service().bear_draft(project, "# Badges\n")
        manifest = container.tree_service().manifest()
        listing = "".join(
            f"{entry.path}\0{entry.hash}\0{int(entry.readonly)}\n" for entry in manifest
        )

        assert len(manifest) == 4
        assert _sync(container).manifest_hash() == sha256_hex(listing)

    def test_manifest_hash_moves_with_the_manifest(
        self, container: ServiceContainer, project: Project
    ) -> None:
        with scoped_session(container):
            container.document_service().bear_draft(project, "# Badges\n")
        first = _sync(container).manifest_hash()
        with scoped_session(container):
            project.archived = True

        assert _sync(container).manifest_hash() != first
        reference = container.view_service().reference().hash
        assert _sync(container).manifest_hash() == sha256_hex(
            "\0".join(["reference.json", reference, "1"]) + "\n"
        )

    def test_check_reports_the_stores_errors_and_deletes_the_reverted_alone(
        self,
        session: DbSession,
        container: ServiceContainer,
        environment: Environment,
    ) -> None:
        other = Environment(id="example-env-2", name="Example-2", exempt=False)
        session.add(other)
        session.add_all(
            [
                _error(STORE_ENVIRONMENT_ID, "camp/b.md", ErrorKind.REVERTED, 4),
                _error(STORE_ENVIRONMENT_ID, "camp/b.md", ErrorKind.PARSE, 9),
                _error(STORE_ENVIRONMENT_ID, "camp/a.md", ErrorKind.PARSE, None),
                _error(other.id, "camp/a.md", ErrorKind.REVERTED, 2),
            ]
        )
        session.flush()

        first = _sync(container).check("camp/a.md", HASH, 0.0)
        second = _sync(container).check("camp/a.md", HASH, 0.0)

        assert first.errors == [
            CheckedError("camp/a.md", ErrorKind.PARSE, None, "parse on line None"),
            CheckedError("camp/b.md", ErrorKind.REVERTED, 4, "reverted on line 4"),
            CheckedError("camp/b.md", ErrorKind.PARSE, 9, "parse on line 9"),
        ]
        assert second.errors == [first.errors[0], first.errors[2]]
        assert sorted(
            (error.environment_id, error.kind_code)
            for error in session.scalars(select(SaveError))
        ) == [
            ("example-env-1", ErrorKind.PARSE),
            ("example-env-1", ErrorKind.PARSE),
            ("example-env-2", ErrorKind.REVERTED),
        ]

    def test_check_agrees_with_a_documents_tree_hash_and_its_latest_save(
        self,
        container: ServiceContainer,
        caplog: pytest.LogCaptureFixture,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear_item(container, project, project_session)
        sync = _sync(container)
        sync.admit(BEARER, STORE_ENVIRONMENT_ID, "1")
        save = ANSWERED.replace("by: ada", "by: agent")
        merged = sync.put(item, save.encode(), sha256_hex(ANSWERED))

        with caplog.at_level(logging.INFO):
            agreed = [
                sync.check(item, disk_hash, 0.0).checked
                for disk_hash in (merged.hash, sha256_hex(save))
            ]

        assert merged.hash == sha256_hex(ANSWERED) != sha256_hex(save)
        assert agreed == [True, True]
        assert caplog.text == ""

    def test_check_logs_a_hash_the_server_does_not_hold(
        self,
        container: ServiceContainer,
        caplog: pytest.LogCaptureFixture,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear_item(container, project, project_session)

        with caplog.at_level(logging.WARNING):
            answer = _sync(container).check(item, HASH, 0.0)

        assert not answer.checked
        assert f"Sync check of {item}: the store's sidecar has {HASH} acked" in (
            caplog.text
        )

    def test_check_of_a_path_the_store_does_not_sync_is_not_checked(
        self,
        container: ServiceContainer,
        caplog: pytest.LogCaptureFixture,
        project: Project,
    ) -> None:
        stray = f"draft-{project.number}/notes.md"

        with caplog.at_level(logging.INFO):
            answer = _sync(container).check(stray, HASH, 0.0)

        assert not answer.checked
        assert [
            (record.levelname, record.getMessage()) for record in caplog.records
        ] == [("INFO", f"Sync check of {stray}: not a path the store syncs")]

    def test_check_observes_the_hooks_wait(
        self, container: ServiceContainer, environment: Environment
    ) -> None:
        count, total = _hook_waits()

        _sync(container).check("reference.json", HASH, 0.25)
        _sync(container).check("reference.json", HASH, 1.5)

        assert _hook_waits() == (count + 2, total + 1.75)
