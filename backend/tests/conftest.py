"""Pytest configuration and fixtures.

Infrastructure fixtures (app, client, session, OIDC, SSE) are defined in
conftest_infrastructure.py. This file re-exports them and adds app-specific
domain fixtures.

A fixture defined here after the import replaces the template's fixture of
the same name. To change the settings the test apps are built from, replace
``test_settings`` or ``test_app_settings``. With a database they are
session-scoped, because the app is, and a replacement keeps that scope.

A process the suite starts builds its app from the environment and ``.env``
alone, not from these fixtures (``tests/test_openapi_cache.py`` builds one
for the OpenAPI document). A setting the app cannot start without, which
only a fixture here gives, gets a default for those processes at the top of
this file, after the imports: ``os.environ.setdefault("MY_SETTING", "value")``.
Without one the suite passes where ``.env`` sets it, and fails in CI.
"""

from collections.abc import Generator

import pytest
from dependency_injector import providers
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy.orm import Session as DbSession

from app import models
from app.app_config import AppSettings
from app.engine.bus import EngineEvent
from app.models import Document, Environment, Item, Project, User
from app.models.reference import DocumentRole, SessionState, UserKind
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerClient
from app.services.controller_outage import ControllerOutage
from app.services.supervisor import Supervisor
from app.services.web_push import WebPushService
from app.utils.after_commit import clear_after_commit_callbacks
from app.utils.lifecycle_coordinator import LifecycleCoordinator
from app.utils.pool_guard import PoolGuard
from app.utils.statement_cap import StatementCap

# Import all infrastructure fixtures
from tests.conftest_infrastructure import *  # noqa: F403
from tests.support.fake_controller import (
    ServedFakeController,
    client_of,
)
from tests.support.fake_push_service import (
    ServedFakePushService,
    mint_vapid_key,
    web_push_of,
)
from tests.support.fake_sidecar import STORE_ENVIRONMENT_ID, SYNC_TOKEN, FakeSidecar
from tests.support.suite_lock import HeldLock, hold_suite_lock
from tests.support.supervisor import Supervise

# The run's test suite lock, held while the run's config references it.
_SUITE_LOCK = pytest.StashKey[HeldLock | None]()

_POOL_GUARD = PoolGuard()

_STATEMENT_CAP = StatementCap()


def pytest_sessionstart(session: pytest.Session) -> None:
    """A run on xdist's workers, as ``kc project test`` runs the suite, takes
    the test suite lock (tests/support/suite_lock.py) and holds it until the
    run ends. A run on one process takes none."""
    config = session.config
    # xdist's own test of a distributed run, whose workers carry `workerinput`.
    # It starts them in its own pytest_sessionstart, which runs last.
    if (
        not hasattr(config, "workerinput")
        and config.getoption("dist", "no") != "no"
        and not config.getoption("collectonly")
    ):
        config.stash[_SUITE_LOCK] = hold_suite_lock()


@pytest.fixture(scope="session", autouse=True)
def pool_guard_installed() -> Generator[None]:
    """The pool guard (app/utils/pool_guard.py) on every pool, for the
    run."""
    _POOL_GUARD.install()
    try:
        yield
    finally:
        _POOL_GUARD.uninstall()


@pytest.fixture(autouse=True)
def pool_guard(pool_guard_installed: None) -> Generator[PoolGuard]:
    """Fails the test where a thread checked out a second connection of a
    pool while it held one: in the test, its fixtures, or a thread a test
    before it left running, whose stacks say so. A test that has the app
    nest drains it from the guard this hands it."""
    yield _POOL_GUARD
    nestings = _POOL_GUARD.drain()
    if nestings:
        pytest.fail("\n\n".join(n.describe() for n in nestings), pytrace=False)


@pytest.fixture(scope="session", autouse=True)
def statement_cap_installed() -> Generator[None]:
    """The statement cap (app/utils/statement_cap.py) on every engine, for
    the run."""
    _STATEMENT_CAP.install()
    try:
        yield
    finally:
        _STATEMENT_CAP.uninstall()


@pytest.fixture(autouse=True)
def statement_cap(statement_cap_installed: None) -> Generator[StatementCap]:
    """Fails the test where the app sent a statement over its bound: in the
    test, its fixtures, or a thread a test before it left running, whose
    stack says so. A test that has the app send one drains it from the cap
    this hands it."""
    yield _STATEMENT_CAP
    statements = _STATEMENT_CAP.drain()
    if statements:
        pytest.fail("\n\n".join(s.describe() for s in statements), pytrace=False)


@pytest.fixture(scope="session")
def test_app_settings() -> AppSettings:
    """The app settings, with the store's sync configured as the fake sidecar
    calls it."""
    # The fake sidecar reads its change stream up to a heartbeat.
    return AppSettings(
        sync_token=SYNC_TOKEN,
        store_environment_id=STORE_ENVIRONMENT_ID,
        sync_heartbeat_seconds=0.01,
    )


@pytest.fixture(autouse=True)
def controller_outage(app: Flask, session_app_isolation: None) -> ControllerOutage:
    """The session app's outage for this test alone, off: the container's
    Singleton outlives the test, and a test that turns it leaves the next
    one as it found it. The isolation's teardown takes the override off. The
    condition service, a Singleton on it, is built afresh on it."""
    outage = ControllerOutage()
    app.container.controller_outage.override(providers.Object(outage))
    app.container.condition_service.reset()
    return outage


@pytest.fixture
def person(session: DbSession) -> User:
    """A person who has signed in."""
    user = User(
        kind_code=UserKind.PERSON,
        subject="subject-ada",
        handle="ada",
        name="Ada Example",
        avatar_slot=1,
    )
    session.add(user)
    session.flush()
    return user


@pytest.fixture
def project(session: DbSession, person: User) -> Project:
    """A draft, created by ``person``."""
    draft = Project(created_by_user_id=person.id)
    session.add(draft)
    session.flush()
    return draft


@pytest.fixture
def environment(session: DbSession) -> Environment:
    """An environment Pilot has touched: the store's."""
    touched = Environment(id=STORE_ENVIRONMENT_ID, name="Example-1", exempt=False)
    session.add(touched)
    session.flush()
    return touched


@pytest.fixture
def project_session(
    session: DbSession, project: Project, environment: Environment
) -> models.Session:
    """A work Session of ``project``, running in ``environment``."""
    # The infrastructure's star import shadows the model's name here.
    run = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code="work",
        cwd="/work/Example",
        token_hash="1" * 64,
        state_code=SessionState.RUNNING,
    )
    session.add(run)
    session.flush()
    return run


@pytest.fixture
def item(session: DbSession, project: Project, project_session: models.Session) -> Item:
    """The first Item of ``project``, a decision ``project_session`` added."""
    entry = Item(
        project_id=project.id,
        seq=1,
        kind_code="decision",
        title="Which colour for the badge?",
        created_by_session_id=project_session.id,
    )
    session.add(entry)
    session.flush()
    return entry


@pytest.fixture
def draft_document(session: DbSession, project: Project) -> Document:
    """``project``'s draft, with no text yet."""
    draft = Document(
        path="project.md",
        project_id=project.id,
        role_code=DocumentRole.DRAFT,
    )
    session.add(draft)
    session.flush()
    return draft


@pytest.fixture
def fake_sidecar(
    client: FlaskClient, environment: Environment
) -> Generator[FakeSidecar]:
    """The store's sidecar, with an empty tree, calling the sync routes
    through ``client``; its change stream is open from the start, so it
    drains what the engine's bus delivers during the test."""
    clear_after_commit_callbacks()
    sidecar = FakeSidecar(client)
    sidecar.listen()
    try:
        yield sidecar
    finally:
        sidecar.close()
        clear_after_commit_callbacks()


@pytest.fixture
def engine_events(container: ServiceContainer) -> Generator[list[EngineEvent]]:
    """Every event the engine's bus delivers during the test, in order.

    The bus delivers once a commit runs the ``after_commit()`` callbacks: a
    request's teardown, or ``scoped_session(container)``. Callbacks a test
    leaves uncommitted are dropped at both ends.
    """
    events: list[EngineEvent] = []
    bus = container.engine_bus()
    clear_after_commit_callbacks()
    bus.subscribe(events.append)
    try:
        yield events
    finally:
        bus.unsubscribe(events.append)
        clear_after_commit_callbacks()


@pytest.fixture
def fake_controller() -> Generator[ServedFakeController]:
    """The KubeCoder controller's fake, served over HTTP with no environment;
    the test drives it through its verbs. Its keepalive is 0.2 s."""
    fake = ServedFakeController(keepalive_seconds=0.2)
    try:
        yield fake
    finally:
        fake.close()


@pytest.fixture
def controller_client(
    container: ServiceContainer, fake_controller: ServedFakeController
) -> ControllerClient:
    """The real client, talking to ``fake_controller``: the container's client
    for the test."""
    return client_of(container, fake_controller)


@pytest.fixture
def committed_controller_client(
    committed_app: Flask, fake_controller: ServedFakeController
) -> ControllerClient:
    """The real client, talking to ``fake_controller``: ``committed_app``'s
    container's client."""
    return client_of(committed_app.container, fake_controller)


@pytest.fixture
def fake_push_service() -> Generator[ServedFakePushService]:
    """The push service's fake, served over HTTP with no subscription; the
    test subscribes its browsers there."""
    fake = ServedFakePushService()
    try:
        yield fake
    finally:
        fake.close()


@pytest.fixture
def vapid_key() -> str:
    """A stage's VAPID key, minted for the test."""
    return mint_vapid_key()


@pytest.fixture
def web_push_service(container: ServiceContainer, vapid_key: str) -> WebPushService:
    """The real web push service under ``vapid_key``: the container's for the
    test."""
    return web_push_of(container, vapid_key)


@pytest.fixture
def supervise() -> Generator[Supervise]:
    """Builds a supervisor on a lifecycle coordinator of its own, whose
    shutdown the teardown runs if the test did not."""
    coordinators: list[LifecycleCoordinator] = []

    def build(
        container: ServiceContainer,
        *,
        controller_configured: bool = True,
        tick: float = 0.05,
        backoff: tuple[float, float] = (0.05, 0.2),
        budget: int = 20,
    ) -> tuple[Supervisor, LifecycleCoordinator]:
        coordinator = LifecycleCoordinator(graceful_shutdown_timeout=budget)
        coordinators.append(coordinator)
        supervisor = Supervisor(
            container=container,
            lifecycle_coordinator=coordinator,
            controller_configured=controller_configured,
            scheduler_tick_seconds=tick,
            restart_backoff_initial_seconds=backoff[0],
            restart_backoff_max_seconds=backoff[1],
        )
        return supervisor, coordinator

    yield build

    for coordinator in coordinators:
        if not coordinator.is_shutting_down():
            coordinator.shutdown()
