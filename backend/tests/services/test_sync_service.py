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
from app.models import Environment, Project, SaveError, User
from app.models.reference import ErrorKind, ProjectState
from app.services.container import ServiceContainer
from app.services.controller_client import (
    ControllerClient,
    ControllerProblem,
    ControllerProblemType,
)
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
from tests.support.fake_controller import ServedFakeController
from tests.support.fake_sidecar import STORE_ENVIRONMENT_ID, SYNC_TOKEN

BEARER = f"Bearer {SYNC_TOKEN}"

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

BROKEN = ANSWERED + "\n```question id=Q1\n"

DEFERRED = """---
title: Camp chores
---

```question id=Q1
answer: deferred
by: agent
at: 2026-10-12T09:30:00Z
to: plan
```

```question id=Q2
answer: Before the trip
by: agent
at: 2026-10-12T09:30:00Z
```
"""

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


def _project(session: DbSession, person: User) -> Project:
    """Another draft, created by `person`."""
    draft = Project(created_by_user_id=person.id)
    session.add(draft)
    session.flush()
    return draft


def _open(session: DbSession, project: Project, slug: str) -> None:
    project.slug = slug
    project.state_code = ProjectState.OPEN
    session.flush()


def _deferral(
    container: ServiceContainer,
    project: Project,
    session: models.Session,
    person: User,
) -> str:
    """A done item of `project` whose Q1 is deferred to the plan; returns the
    block as a note names it."""
    with scoped_session(container):
        item = container.document_service().bear_item(
            project, "decision", "Camp chores", session, DEFERRED
        )
        container.record_service().done(item, person)
        return f"{item.id}/Q1"


class TestSyncService:
    def test_admit_lets_the_store_through_and_makes_its_environment(
        self, session: DbSession, container: ServiceContainer
    ) -> None:
        # No controller is configured: the id names the store.
        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "2")

        store = session.get_one(Environment, STORE_ENVIRONMENT_ID)
        assert (store.id, store.name, store.exempt) == (
            STORE_ENVIRONMENT_ID,
            STORE_ENVIRONMENT_ID,
            False,
        )

    def test_admit_with_a_controller_makes_the_stores_environment_from_its_report(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
    ) -> None:
        _configure(container, controller_url=fake_controller.url)
        fake_controller.add_environment(
            STORE_ENVIRONMENT_ID, name="Store", status="running", exempt=True
        )

        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "2")
        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "2")

        store = session.get_one(Environment, STORE_ENVIRONMENT_ID)
        assert (store.name, store.exempt, store.last_state) == (
            "Store",
            True,
            "running",
        )
        assert fake_controller.calls == [f"GET /environments/{STORE_ENVIRONMENT_ID}"]

    def test_admit_with_a_controller_leaves_an_environment_that_exists(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        environment: Environment,
    ) -> None:
        _configure(container, controller_url=fake_controller.url)

        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "2")

        session.refresh(environment)
        assert (environment.name, environment.exempt) == ("Example-1", False)
        assert fake_controller.calls == []

    def test_admit_with_a_controller_that_does_not_report_the_store_makes_no_row(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
    ) -> None:
        _configure(container, controller_url=fake_controller.url)

        with pytest.raises(ControllerProblem) as raised:
            _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "2")

        assert raised.value.problem_type is ControllerProblemType.NOT_FOUND
        assert session.get(Environment, STORE_ENVIRONMENT_ID) is None

    def test_the_store_the_sync_admits_is_started_and_never_armed(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
    ) -> None:
        _configure(container, controller_url=fake_controller.url)
        fake_controller.add_environment(
            STORE_ENVIRONMENT_ID, status="stopped", exempt=True
        )
        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "2")
        environments = container.environment_service()

        settled = environments.start(STORE_ENVIRONMENT_ID)
        environments.run_shutdown_timer(session)

        assert settled.status == "running"
        store = session.scalars(
            select(Environment)
            .where(Environment.id == STORE_ENVIRONMENT_ID)
            .execution_options(populate_existing=True)
        ).one()
        assert store.server_started_at is not None
        assert store.stop_due_at is None
        assert f"POST /environments/{STORE_ENVIRONMENT_ID}/start" in (
            fake_controller.calls
        )
        assert f"POST /environments/{STORE_ENVIRONMENT_ID}/stop" not in (
            fake_controller.calls
        )

    def test_admit_leaves_an_environment_that_exists(
        self,
        session: DbSession,
        container: ServiceContainer,
        environment: Environment,
    ) -> None:
        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "2")
        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "2")

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
            _sync(container).admit(authorization, STORE_ENVIRONMENT_ID, "2")

        assert session.get(Environment, STORE_ENVIRONMENT_ID) is None

    def test_admit_refuses_every_call_while_the_token_is_empty(
        self, container: ServiceContainer
    ) -> None:
        _configure(container, sync_token="")

        for authorization in (BEARER, "Bearer ", None):
            with pytest.raises(AuthenticationException):
                _sync(container).admit(authorization, STORE_ENVIRONMENT_ID, "2")

    def test_admit_refuses_a_bearer_that_is_not_ascii(
        self, container: ServiceContainer
    ) -> None:
        with pytest.raises(AuthenticationException):
            _sync(container).admit("Bearer tökén", STORE_ENVIRONMENT_ID, "2")

    @pytest.mark.parametrize("environment_id", [None, "", "example-env-2"])
    def test_admit_refuses_another_environment(
        self,
        session: DbSession,
        container: ServiceContainer,
        environment_id: str | None,
    ) -> None:
        with pytest.raises(AuthorizationException) as refused:
            _sync(container).admit(BEARER, environment_id, "2")

        assert repr(environment_id) in refused.value.message
        assert session.scalars(select(Environment)).all() == []

    def test_admit_refuses_every_call_while_the_store_is_not_configured(
        self, container: ServiceContainer
    ) -> None:
        _configure(container, store_environment_id="")

        for environment_id in ("", STORE_ENVIRONMENT_ID):
            with pytest.raises(AuthorizationException):
                _sync(container).admit(BEARER, environment_id, "2")

    @pytest.mark.parametrize("protocol", [None, "", "1", "3", "one", "+2", " 2", "2.0"])
    def test_admit_refuses_a_version_outside_the_range(
        self, session: DbSession, container: ServiceContainer, protocol: str | None
    ) -> None:
        with pytest.raises(SyncProtocolUnsupportedException) as refused:
            _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, protocol)

        assert (refused.value.minimum, refused.value.maximum) == (2, 2)
        assert session.get(Environment, STORE_ENVIRONMENT_ID) is None

    def test_put_keys_its_save_errors_by_the_stores_environment(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        path = _bear_item(container, project, project_session)
        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "2")

        answer = _sync(container).put(path, BROKEN.encode(), sha256_hex(ANSWERED), None)

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
        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "2")
        before = (_ingests("document", "published"), _stale_puts())
        edited = ANSWERED.replace("# Which tent?", "# Which tent for the lake?")

        answer = _sync(container).put(path, edited.encode(), sha256_hex(ANSWERED), None)

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
        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "2")
        before = (_ingests("document", "reverted"), _faults("reverted"))
        save = ANSWERED.replace("by: ada", "by: agent")

        answer = _sync(container).put(path, save.encode(), sha256_hex(ANSWERED), None)

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
        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "2")
        before = (_ingests("document", "held"), _faults("parse"), _faults("reverted"))

        answer = _sync(container).put(path, BROKEN.encode(), sha256_hex(ANSWERED), None)

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
        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "2")
        before = (_ingests("plan", "published"), _ingests("plan", "held"))

        published = _sync(container).put(path, PLAN.encode(), None, None)
        held = _sync(container).put(path, MISSPELT_PLAN.encode(), published.hash, None)

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
        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "2")
        before = (_ingests("view", "readonly"), _stale_puts())

        answer = _sync(container).put(
            f"draft-{project.number}/timeline.json", b"{}\n", None, None
        )

        assert (answer.kind, answer.stale) == (PathKind.VIEW, True)
        assert (_ingests("view", "readonly"), _stale_puts()) == (
            before[0] + 1,
            before[1] + 1,
        )

    def test_put_refuses_a_path_of_no_syncing_project(
        self, container: ServiceContainer
    ) -> None:
        _sync(container).admit(BEARER, STORE_ENVIRONMENT_ID, "2")
        before = _stale_puts()

        with pytest.raises(RecordNotFoundException):
            _sync(container).put("example/notes.md", b"# Stray\n", None, None)

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
        # The item and the chat as synced, an older timeline as synced, the
        # plan gone from disk, and in the shadow a path of a folder no longer
        # synced.
        tree = {
            item: hashes[item],
            f"{folder}/chat.md": hashes[f"{folder}/chat.md"],
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
        sync.admit(BEARER, STORE_ENVIRONMENT_ID, "2")
        held = sync.put(item, BROKEN.encode(), sha256_hex(ANSWERED), None)
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
            sync.admit(BEARER, STORE_ENVIRONMENT_ID, "2")
            held = sync.put(path, MISSPELT_PLAN.encode(), None, None)
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

        assert len(manifest) == 5
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

    def test_check_reports_the_folders_errors_and_deletes_its_reverted_alone(
        self,
        session: DbSession,
        container: ServiceContainer,
        environment: Environment,
        project: Project,
        person: User,
    ) -> None:
        _open(session, _project(session, person), "camp")
        draft = f"draft-{project.number}"
        other = Environment(id="example-env-2", name="Example-2", exempt=False)
        session.add(other)
        session.add_all(
            [
                _error(STORE_ENVIRONMENT_ID, "camp/b.md", ErrorKind.REVERTED, 4),
                _error(STORE_ENVIRONMENT_ID, "camp/b.md", ErrorKind.PARSE, 9),
                _error(STORE_ENVIRONMENT_ID, "camp/a.md", ErrorKind.PARSE, None),
                _error(STORE_ENVIRONMENT_ID, f"{draft}/a.md", ErrorKind.REVERTED, 3),
                _error(STORE_ENVIRONMENT_ID, "campsite/a.md", ErrorKind.REVERTED, 5),
                _error(other.id, "camp/a.md", ErrorKind.REVERTED, 2),
            ]
        )
        session.flush()
        sync = _sync(container)

        first = sync.check("camp", 0.0)
        second = sync.check("camp", 0.0)
        drafts = sync.check(draft, 0.0)

        assert first.errors == [
            CheckedError("camp/a.md", ErrorKind.PARSE, None, "parse on line None"),
            CheckedError("camp/b.md", ErrorKind.REVERTED, 4, "reverted on line 4"),
            CheckedError("camp/b.md", ErrorKind.PARSE, 9, "parse on line 9"),
        ]
        assert second.errors == [first.errors[0], first.errors[2]]
        assert drafts.errors == [
            CheckedError(f"{draft}/a.md", ErrorKind.REVERTED, 3, "reverted on line 3")
        ]
        assert sorted(
            (error.environment_id, error.path, error.kind_code)
            for error in session.scalars(select(SaveError))
        ) == [
            ("example-env-1", "camp/a.md", ErrorKind.PARSE),
            ("example-env-1", "camp/b.md", ErrorKind.PARSE),
            ("example-env-1", "campsite/a.md", ErrorKind.REVERTED),
            ("example-env-2", "camp/a.md", ErrorKind.REVERTED),
        ]

    @pytest.mark.parametrize("folder", ["campsite", "{archived}"])
    def test_check_of_a_folder_of_no_syncing_project_reports_its_errors_alone(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
        folder: str,
    ) -> None:
        archived = _project(session, person)
        archived.archived = True
        session.flush()
        folder = folder.format(archived=f"draft-{archived.number}")
        path = f"{folder}/a.md"
        _deferral(container, project, project_session, person)
        draft = f"draft-{project.number}/a.md"
        session.add_all(
            [
                _error(STORE_ENVIRONMENT_ID, path, ErrorKind.REVERTED, 1),
                _error(STORE_ENVIRONMENT_ID, path, ErrorKind.PARSE, 2),
                _error(STORE_ENVIRONMENT_ID, "reference.json", ErrorKind.REVERTED, 3),
                _error(STORE_ENVIRONMENT_ID, draft, ErrorKind.REVERTED, 4),
            ]
        )
        session.flush()

        first = _sync(container).check(folder, 0.0)
        second = _sync(container).check(folder, 0.0)

        assert first.errors == [
            CheckedError(path, ErrorKind.REVERTED, 1, "reverted on line 1"),
            CheckedError(path, ErrorKind.PARSE, 2, "parse on line 2"),
        ]
        assert first.homeless_deferrals == []
        assert second.errors == [first.errors[1]]
        assert sorted(
            (error.path, error.kind_code)
            for error in session.scalars(select(SaveError))
        ) == sorted(
            [
                (path, ErrorKind.PARSE),
                ("reference.json", ErrorKind.REVERTED),
                (draft, ErrorKind.REVERTED),
            ]
        )

    def test_check_reports_the_projects_deferrals_alone(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        other = _project(session, person)
        mine = _deferral(container, project, project_session, person)
        theirs = _deferral(container, other, project_session, person)
        _open(session, other, "camp")
        sync = _sync(container)

        answers = [
            sync.check(folder, 0.0).homeless_deferrals
            for folder in (f"draft-{project.number}", "camp")
        ]

        assert [
            [(deferral.block, deferral.document) for deferral in answer]
            for answer in answers
        ] == [
            [(mine, f"draft-{project.number}/items/1-camp-chores.md")],
            [(theirs, "camp/items/1-camp-chores.md")],
        ]

    def test_check_observes_the_hooks_wait(
        self, container: ServiceContainer, environment: Environment
    ) -> None:
        count, total = _hook_waits()

        _sync(container).check("example", 0.25)
        _sync(container).check("example", 1.5)

        assert _hook_waits() == (count + 2, total + 1.75)
