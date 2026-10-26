"""Fixtures of the MCP process's tests: its app, its API the test app's routes,
and a work item's or a chat's running Session whose bearer is `TOKEN`."""

from datetime import UTC, datetime

import pytest
from flask.testing import FlaskClient
from sqlalchemy.orm import Session as DbSession
from starlette.applications import Starlette

from app import models
from app.models import Environment, Project, Turn
from app.services.container import ServiceContainer
from pilot_mcp.api import PilotStoreApi, PilotWorkApi
from pilot_mcp.server import build_app
from tests.support.pilot_mcp import API_URL, ApiRoutes, running_session


@pytest.fixture
def routes(client: FlaskClient) -> ApiRoutes:
    return ApiRoutes(client)


@pytest.fixture
def mcp_app(routes: ApiRoutes) -> Starlette:
    """The app the pod serves, its API the test app's routes."""
    return build_app(
        PilotWorkApi(API_URL, transport=routes),
        PilotStoreApi(API_URL, transport=routes),
    )


@pytest.fixture
def worker(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
    environment: Environment,
) -> models.Session:
    """A work item's running Session, whose bearer is `TOKEN`."""
    return running_session(session, container, project, environment)


@pytest.fixture
def brain(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
    environment: Environment,
) -> models.Session:
    """The project's chat, running, whose bearer is `TOKEN`, its turn in
    flight."""
    chat = running_session(session, container, project, environment, kind="chat")
    session.add(
        Turn(session_id=chat.id, seq=1, message="Go on.", started_at=datetime.now(UTC))
    )
    session.commit()
    return chat
