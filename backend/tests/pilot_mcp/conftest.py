"""Fixtures of the MCP process's tests: its app, its API the test app's routes,
a work item's or a chat's running Session whose bearer is `TOKEN`, and the app
with its projects surface configured, whose API is behind the sign-in gate."""

from datetime import UTC, datetime
from typing import Any

import pytest
from flask.testing import FlaskClient
from sqlalchemy.orm import Session as DbSession
from starlette.applications import Starlette

from app import models
from app.config import Settings
from app.models import Environment, Project, Turn, User
from app.services.container import ServiceContainer
from pilot_mcp.api import PilotStoreApi, PilotWorkApi
from pilot_mcp.server import build_app
from tests.support.pilot_mcp import (
    API_URL,
    ApiRoutes,
    TokenEndpoint,
    app_with_projects,
    running_session,
    service_token,
)


@pytest.fixture
def routes(client: FlaskClient) -> ApiRoutes:
    return ApiRoutes(client)


@pytest.fixture
def mcp_app(routes: ApiRoutes) -> Starlette:
    """The app the pod serves, its API the test app's routes, its projects
    surface not configured."""
    return build_app(
        PilotWorkApi(API_URL, transport=routes),
        PilotStoreApi(API_URL, transport=routes),
        None,
    )


@pytest.fixture
def gated_routes(oidc_client: FlaskClient) -> ApiRoutes:
    """The API behind its sign-in gate: the OIDC app's routes, which admit a
    token signed with the suite's key."""
    return ApiRoutes(oidc_client)


@pytest.fixture
def token_endpoint(
    test_settings: Settings, generate_test_jwt: Any, service_user: User
) -> TokenEndpoint:
    """The token endpoint, issuing the service user's token with the `editor`
    role."""
    return TokenEndpoint(
        lambda: service_token(
            test_settings,
            generate_test_jwt.private_key,
            service_user.subject,
            ("editor",),
        )
    )


@pytest.fixture
def projects_app(gated_routes: ApiRoutes, token_endpoint: TokenEndpoint) -> Starlette:
    """The app the pod serves with its projects surface configured, its API
    the gated routes and its credential the service user's."""
    return app_with_projects(gated_routes, token_endpoint)


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
