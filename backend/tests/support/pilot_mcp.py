"""Pilot's MCP server driven as the pod runs it: a real MCP client over its
Streamable-HTTP transport, the app served in process, and its calls to the API
answered by the test app's own routes, in the test's database session; the
projects surface with its token endpoint, a fake of Keycloak's."""

import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import parse_qsl

import httpx
import jwt
from flask.testing import FlaskClient
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, InitializeResult
from sqlalchemy.orm import Session as DbSession
from starlette.applications import Starlette

from app import models
from app.config import Settings
from app.models import Environment, Project
from app.models.reference import SessionState
from app.services.container import ServiceContainer
from app.services.pilot_server import token_hash
from pilot_mcp.api import (
    ENVIRONMENT_HEADER,
    SESSION_HEADER,
    PilotProjectsApi,
    PilotStoreApi,
    PilotWorkApi,
)
from pilot_mcp.credential import ServiceCredential
from pilot_mcp.server import WORK_PATH, ProjectsSurface, build_app

API_URL = "http://localhost:3501"

TOKEN = "worker-token"

BEARER = {"Authorization": f"Bearer {TOKEN}"}

PROJECTS_TOKEN = "projects-token-of-the-suite"

CALLER_ENVIRONMENT = "example-recipebox-1a2b3c"
CALLER_SESSION = "refine-the-cards"

PROJECTS_HEADERS = {
    "Authorization": f"Bearer {PROJECTS_TOKEN}",
    ENVIRONMENT_HEADER: CALLER_ENVIRONMENT,
    SESSION_HEADER: CALLER_SESSION,
}
"""What a session's entry for `pilot-projects` sends on every request."""

TOKEN_URL = "https://auth.example.com/realms/test/protocol/openid-connect/token"
CLIENT_ID = "pilot-test-service"
CLIENT_SECRET = "client-secret-of-the-suite"

_MCP_URL = "http://pilot-mcp.test"

_NOT_FORWARDED = ("host", "content-length")


def running_session(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
    environment: Environment,
    kind: str = "work",
) -> models.Session:
    """A running Session of `kind` whose bearer is `TOKEN`; a work one with
    its Work. Committed, so that a refused call's rollback keeps it."""
    run = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code=kind,
        cwd="/work/Example",
        token_hash=token_hash(TOKEN),
        state_code=SessionState.RUNNING,
    )
    session.add(run)
    session.flush()
    if kind == "work":
        container.record_service().place_work(project, run, "Refining the camp")
    session.commit()
    return run


class ApiRoutes(httpx.AsyncBaseTransport):
    """The API on the pod's loopback, in process: each request the MCP
    process makes is answered by the test app's client. `calls` holds each
    request with its answer."""

    def __init__(self, client: FlaskClient) -> None:
        self._client = client
        self.calls: list[tuple[httpx.Request, httpx.Response]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        answer = self._client.open(
            request.url.path,
            query_string=request.url.query.decode(),
            method=request.method,
            headers={
                name: value
                for name, value in request.headers.items()
                if name not in _NOT_FORWARDED
            },
            data=await request.aread(),
        )
        response = httpx.Response(
            answer.status_code,
            headers={"Content-Type": answer.content_type},
            content=answer.get_data(),
        )
        self.calls.append((request, response))
        return response


def service_token(
    settings: Settings, private_key: Any, subject: str, roles: tuple[str, ...]
) -> str:
    """A client-credentials token of the service user's client as Keycloak
    issues one: the client's service account its subject, the stage's client
    its audience, `roles` that client's, and no name or email. Signed with
    the suite's key, which the OIDC app's JWKS holds."""
    now = int(time.time())
    token: str = jwt.encode(
        {
            "sub": subject,
            "iss": settings.oidc_issuer_url,
            "aud": settings.oidc_audience,
            "iat": now,
            "exp": now + 300,
            "jti": uuid.uuid4().hex,
            "resource_access": {settings.oidc_audience: {"roles": list(roles)}},
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key-id"},
    )
    return token


class TokenEndpoint(httpx.AsyncBaseTransport):
    """Keycloak's token endpoint, faked: a client-credentials request of
    `CLIENT_ID` with `CLIENT_SECRET` is answered with a token `mint` makes,
    expiring in `expires_in` seconds, any other refused as Keycloak refuses
    it. `forms` holds each request's form and `minted` each token issued."""

    def __init__(self, mint: Callable[[], str], expires_in: int = 300) -> None:
        self._mint = mint
        self.expires_in = expires_in
        self.forms: list[dict[str, str]] = []
        self.minted: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        assert (request.method, str(request.url)) == ("POST", TOKEN_URL)
        form = dict(parse_qsl((await request.aread()).decode()))
        self.forms.append(form)
        if form != {
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        }:
            return httpx.Response(
                401,
                json={
                    "error": "unauthorized_client",
                    "error_description": "Invalid client or Invalid client credentials",
                },
            )
        token = self._mint()
        self.minted.append(token)
        return httpx.Response(
            200,
            json={
                "access_token": token,
                "expires_in": self.expires_in,
                "token_type": "Bearer",
            },
        )


def credential(endpoint: httpx.AsyncBaseTransport) -> ServiceCredential:
    """The service user's credential, minted at `endpoint`."""
    return ServiceCredential(TOKEN_URL, CLIENT_ID, CLIENT_SECRET, transport=endpoint)


def app_with_projects(
    routes: httpx.AsyncBaseTransport, endpoint: httpx.AsyncBaseTransport
) -> Starlette:
    """The app the pod serves with its projects surface configured: its door's
    token `PROJECTS_TOKEN`, its credential minted at `endpoint`, and its API
    `routes`."""
    return build_app(
        PilotWorkApi(API_URL, transport=routes),
        PilotStoreApi(API_URL, transport=routes),
        ProjectsSurface(
            token=PROJECTS_TOKEN,
            api=PilotProjectsApi(API_URL, credential(endpoint), transport=routes),
        ),
    )


def http_client(
    app: Starlette, headers: dict[str, str] | None = None
) -> httpx.AsyncClient:
    """An HTTP client of `app`, served in process: no port is bound."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=_MCP_URL, headers=headers
    )


@asynccontextmanager
async def mcp_session(
    app: Starlette, headers: dict[str, str] = BEARER, path: str = WORK_PATH
) -> AsyncIterator[tuple[ClientSession, InitializeResult]]:
    """An MCP client session with the server `app` serves at `path`,
    initialized, presenting `headers` on every request."""
    async with http_client(app, headers) as http, app.router.lifespan_context(app):
        async with streamable_http_client(f"{_MCP_URL}{path}", http_client=http) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                yield session, initialized


async def call(
    app: Starlette,
    tool: str,
    arguments: dict[str, Any],
    headers: dict[str, str] = BEARER,
    meta: dict[str, Any] | None = None,
    path: str = WORK_PATH,
) -> CallToolResult:
    """One `tools/call` to the server at `path`, with `meta` as its `_meta`,
    as Claude Code sends its tool-use id."""
    async with mcp_session(app, headers, path) as (session, _):
        return await session.call_tool(tool, arguments, meta=meta)


def error_text(result: CallToolResult) -> str:
    assert result.isError, "expected a tool error"
    return "".join(block.text for block in result.content if block.type == "text")
