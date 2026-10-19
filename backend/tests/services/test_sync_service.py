"""The sync service: the gate's refusals and the store's Environment, and the
put's metrics (design 1 §5.1, §5.7)."""

import json

import pytest
from dependency_injector import providers
from prometheus_client.metrics import MetricWrapperBase
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.engine.ingest import PathKind
from app.engine.paths import sha256_hex
from app.engine.tree import TreeFile
from app.exceptions import (
    AuthenticationException,
    AuthorizationException,
    RecordNotFoundException,
    SyncProtocolUnsupportedException,
)
from app.models import Environment, Project, SaveError
from app.services.container import ServiceContainer
from app.services.sync_service import (
    FAULTS_TOTAL,
    INGEST_SECONDS,
    STALE_PUTS_TOTAL,
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
