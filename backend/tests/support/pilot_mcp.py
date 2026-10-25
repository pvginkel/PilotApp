"""Pilot's MCP server driven as the pod runs it: a real MCP client over its
Streamable-HTTP transport, the app served in process, and its calls to the API
answered by the test app's own routes, in the test's database session."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from flask.testing import FlaskClient
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, InitializeResult
from sqlalchemy.orm import Session as DbSession
from starlette.applications import Starlette

from app import models
from app.models import Environment, Project
from app.models.reference import SessionState
from app.services.container import ServiceContainer
from app.services.pilot_server import token_hash

API_URL = "http://localhost:3501"

TOKEN = "worker-token"

BEARER = {"Authorization": f"Bearer {TOKEN}"}

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


def http_client(
    app: Starlette, headers: dict[str, str] | None = None
) -> httpx.AsyncClient:
    """An HTTP client of `app`, served in process: no port is bound."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=_MCP_URL, headers=headers
    )


@asynccontextmanager
async def mcp_session(
    app: Starlette, headers: dict[str, str] = BEARER
) -> AsyncIterator[tuple[ClientSession, InitializeResult]]:
    """An MCP client session with `app`, initialized, presenting `headers` on
    every request."""
    async with http_client(app, headers) as http, app.router.lifespan_context(app):
        async with streamable_http_client(f"{_MCP_URL}/mcp", http_client=http) as (
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
) -> CallToolResult:
    async with mcp_session(app, headers) as (session, _):
        return await session.call_tool(tool, arguments)


def error_text(result: CallToolResult) -> str:
    assert result.isError, "expected a tool error"
    return "".join(block.text for block in result.content if block.type == "text")
