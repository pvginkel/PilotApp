"""The testing-only session start, for the live check (design 2 §13.2; V19)."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from dependency_injector import providers
from flask.testing import FlaskClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.config import Settings, Stage
from app.models import Project
from app.models.reference import SessionState
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerClient
from app.services.environment_service import EnvironmentService
from app.services.relay_service import RelayService
from app.services.session_start_service import SessionStartService
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.fake_controller import ServedFakeController
from tests.support.supervisor import Supervise

PATH = "/api/testing/sessions"
ENV = "env-a"


@pytest.fixture(autouse=True)
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


@contextmanager
def _serving(
    container: ServiceContainer, supervise: Supervise, *, controller_configured: bool
) -> Iterator[None]:
    """The container's session start, on a supervisor of its own whose loops
    never run."""
    supervisor, _ = supervise(container)
    environments = EnvironmentService(
        container=container, supervisor=supervisor, stop_after_seconds=1800
    )
    starts = SessionStartService(
        container=container,
        supervisor=supervisor,
        session_streams=container.session_stream_service(),
        environment_service=environments,
        relay_service=RelayService(
            container=container,
            supervisor=supervisor,
            session_streams=container.session_stream_service(),
            environment_service=environments,
        ),
        controller_configured=controller_configured,
    )
    container.session_start_service.override(providers.Object(starts))
    try:
        yield
    finally:
        container.session_start_service.reset_last_overriding()


@pytest.fixture
def served(
    container: ServiceContainer,
    controller_client: ControllerClient,
    fake_controller: ServedFakeController,
    supervise: Supervise,
) -> Iterator[None]:
    """The route on the fake, which has the environment `ENV`, stopped."""
    fake_controller.add_environment(ENV, name="Env-A")
    with _serving(container, supervise, controller_configured=True):
        yield


def _body(project: Project, **changes: object) -> dict[str, object]:
    return {
        "project_id": str(project.id),
        "environment_id": ENV,
        "cwd": "/work/Example",
        "brief": "Rename the badge.",
        **changes,
    }


def _sessions(db: DbSession) -> list[models.Session]:
    return list(db.scalars(select(models.Session)))


class TestTestingSessionsApi:
    def test_it_starts_a_session_for_a_project_and_answers_its_id(
        self,
        client: FlaskClient,
        served: None,
        session: DbSession,
        project: Project,
    ) -> None:
        response = client.post(
            PATH, json=_body(project, agent="worker", model="opus", resume="conv-1")
        )

        assert response.status_code == 201
        (run,) = _sessions(session)
        assert response.get_json() == {"id": str(run.id)}
        assert run.state_code == SessionState.STARTING
        assert (run.project_id, run.environment_id, run.kind_code, run.cwd) == (
            project.id,
            ENV,
            "work",
            "/work/Example",
        )
        assert (run.agent, run.model, run.reasoning_effort, run.conversation_id) == (
            "worker",
            "opus",
            None,
            "conv-1",
        )

    def test_an_unknown_project_is_404(
        self, client: FlaskClient, served: None, session: DbSession, project: Project
    ) -> None:
        response = client.post(PATH, json=_body(project, project_id=str(uuid.uuid4())))

        assert response.status_code == 404
        assert _sessions(session) == []

    def test_an_environment_the_controller_lacks_is_502(
        self, client: FlaskClient, served: None, session: DbSession, project: Project
    ) -> None:
        response = client.post(PATH, json=_body(project, environment_id="env-missing"))

        assert response.status_code == 502
        assert _sessions(session) == []

    @pytest.mark.parametrize(
        "changes",
        [{"brief": ""}, {"cwd": ""}, {"environment_id": ""}, {"project_id": "x"}],
        ids=["no-brief", "no-cwd", "no-environment", "no-project-id"],
    )
    def test_an_invalid_body_is_400(
        self,
        client: FlaskClient,
        served: None,
        session: DbSession,
        project: Project,
        changes: dict[str, object],
    ) -> None:
        response = client.post(PATH, json=_body(project, **changes))

        assert response.status_code == 400
        assert _sessions(session) == []

    def test_no_controller_configured_is_409(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        supervise: Supervise,
        session: DbSession,
        project: Project,
    ) -> None:
        with _serving(container, supervise, controller_configured=False):
            response = client.post(PATH, json=_body(project))

        assert response.status_code == 409
        assert _sessions(session) == []

    @pytest.mark.parametrize(
        "update",
        [{"flask_env": "development"}, {"stage": Stage("prd")}],
        ids=["outside-testing-mode", "testing-on-prd"],
    )
    def test_it_is_refused_outside_testing_mode(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        served: None,
        test_settings: Settings,
        session: DbSession,
        project: Project,
        update: dict[str, object],
    ) -> None:
        container.config.override(test_settings.model_copy(update=update))
        try:
            response = client.post(PATH, json=_body(project))
        finally:
            container.config.reset_last_overriding()

        assert response.status_code == 400
        assert response.get_json()["code"] == "ROUTE_NOT_AVAILABLE"
        assert _sessions(session) == []
