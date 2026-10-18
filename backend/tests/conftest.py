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
from sqlalchemy.orm import Session as DbSession

from app import models
from app.engine.bus import EngineEvent
from app.models import Document, Environment, Item, Project, User
from app.models.reference import DocumentRole, SessionState, UserKind
from app.services.container import ServiceContainer
from app.utils.after_commit import clear_after_commit_callbacks

# Import all infrastructure fixtures
from tests.conftest_infrastructure import *  # noqa: F403
from tests.support.fake_sidecar import FakeSidecar


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
    """An environment Pilot has touched."""
    touched = Environment(id="example-env-1", name="Example-1", exempt=False)
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
    container: ServiceContainer, environment: Environment
) -> Generator[FakeSidecar]:
    """The store's sidecar, ``environment``'s, with an empty tree; the
    events it drains are those the bus delivers during the test."""
    clear_after_commit_callbacks()
    sidecar = FakeSidecar(container, environment)
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
