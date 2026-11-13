"""Pilot's MCP server and its Streamable-HTTP app: `pilot-work`, a worker's
tools, at `/mcp`, and `pilot-store`, the brain's, at `/mcp/store`, two servers
named `pilot` in one app, and `pilot-projects`, any session's, at
`/mcp/projects` (F150.1). Which of the first two a session is handed, and
which its bearer may call, its Session's kind says
(`app/services/pilot_server.py`); the third is registered fleet-wide, under a
name of its own, so that no session holds two servers of one name.

- Stateless: every call is a request of its own, so the process holds nothing
  between calls but the service user's token (`credential.py`).
- DNS-rebinding protection off: its boundary is the bearer, not the Host
  header, which is the front door's name for it.
- A request to the first two with no bearer is refused here; which Session a
  bearer names, and what it may call, the API says
  (`app/services/pilot_work_service.py`, `app/services/pilot_store_service.py`).
- A request to `/mcp/projects` is let in only with the surface's shared token
  as its bearer, checked here: the API never sees it. With the surface not
  configured, every request to it is refused, and nothing else is.
- `GET /health/healthz` and `/health/readyz` answer without a bearer. Readiness
  is this process's alone: the API is a container of the same pod.
"""

import hmac
import json
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from pilot_mcp.api import PilotProjectsApi, PilotStoreApi, PilotWorkApi
from pilot_mcp.tools import (
    register_projects_tools,
    register_store_tools,
    register_work_tools,
)

SERVER_NAME = "pilot"

PROJECTS_SERVER_NAME = "pilot-projects"

WORK_INSTRUCTIONS = (
    "Pilot, the project manager that started this session to do a work item of"
    " its project. Write each decision document your work produces as a file"
    " under `/work`, register it with `register_document` and attach what backs"
    " it with `attach_file`, then end your turn: never wait for the answers."
    " Pilot reads each registered document again when your turn ends and puts it"
    " to the operator; once every one is answered, Pilot writes the answered"
    " files back in place and continues this conversation with a message naming"
    " them."
)

STORE_INSTRUCTIONS = (
    "Pilot, the project manager, whose brain this session is, for the one project"
    " `$PILOT_PROJECT` names. These tools are the one door to Pilot's record"
    " beyond the files of the project's folder: each acts on that project alone,"
    " and only while your turn runs. An `item` is an item's id and a `block` a"
    " block's, `<item id>/<local id>`: the item's id as `timeline.json` gives it,"
    " the block's local id as its fence does; `add_item` alone takes the item"
    " itself, in `timeline.json`'s shape. A call the record refuses changes"
    " nothing and answers the reason."
)

PROJECTS_INSTRUCTIONS = (
    "Pilot, the project manager, and its projects. These tools read a project"
    " Pilot manages, its documents and its items, and start one. Load the skill"
    " `kubecoder:pilot-usage` before you use them: it maps a project's files and"
    " says which of them answers which question."
)

WORK_PATH = "/mcp"

STORE_PATH = "/mcp/store"
"""Under `pilot-work`'s, as the backend hands it (`STORE_PATH` of
`app/services/pilot_server.py`)."""

PROJECTS_PATH = "/mcp/projects"

HEALTH_PATHS = frozenset({"/health/healthz", "/health/readyz"})

_BEARER = b"Bearer "

_NO_BEARER = json.dumps(
    {
        "error": "Cannot call Pilot's MCP server because the request carries no bearer",
        "details": {
            "message": "Send the session's PILOT_TOKEN as `Authorization: Bearer <token>`"
        },
        "code": "AUTHENTICATION_REQUIRED",
    }
).encode()


_NOT_THE_TOKEN = json.dumps(
    {
        "error": (
            "Cannot call Pilot's projects because the request does not carry"
            " their token"
        ),
        "details": {
            "message": "Send PILOT_PROJECTS_TOKEN as `Authorization: Bearer <token>`"
        },
        "code": "AUTHENTICATION_REQUIRED",
    }
).encode()

_NOT_CONFIGURED = json.dumps(
    {
        "error": (
            "Cannot call Pilot's projects because this Pilot is not set up to"
            " serve them"
        ),
        "details": {
            "message": (
                "Its token or the client it calls its API with is missing from"
                " its deployment"
            )
        },
        "code": "SERVICE_UNAVAILABLE",
    }
).encode()


def _bearer(scope: Scope) -> bytes | None:
    """The token of the request's `Authorization`, `Bearer <token>` as the
    API reads it; None where it carries none."""
    for name, value in scope["headers"]:
        if name == b"authorization":
            if not value.startswith(_BEARER):
                return None
            return value.removeprefix(_BEARER).strip() or None
    return None


async def _refuse(send: Send, status: int, body: bytes) -> None:
    headers = [(b"content-type", b"application/json")]
    if status == 401:
        headers.append((b"www-authenticate", b"Bearer"))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class BearerRequired:
    """Refuses a request to any path but `public` that carries no bearer."""

    def __init__(self, app: ASGIApp, public: frozenset[str]) -> None:
        self._app = app
        self._public = public

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["path"] in self._public
            or _bearer(scope) is not None
        ):
            await self._app(scope, receive, send)
            return
        await _refuse(send, 401, _NO_BEARER)


class ProjectsDoor:
    """Lets a request to `path`, or under it, in only with `token` as its
    bearer, compared in constant time; with no `token`, the surface not
    configured, it refuses every one. A request to any other path passes."""

    def __init__(self, app: ASGIApp, path: str, token: str | None) -> None:
        self._app = app
        self._path = path
        self._under = f"{path}/"
        self._token = None if token is None else token.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not (
            scope["path"] == self._path or scope["path"].startswith(self._under)
        ):
            await self._app(scope, receive, send)
            return
        if self._token is None:
            await _refuse(send, 503, _NOT_CONFIGURED)
            return
        presented = _bearer(scope)
        if presented is None or not hmac.compare_digest(presented, self._token):
            await _refuse(send, 401, _NOT_THE_TOKEN)
            return
        await self._app(scope, receive, send)


@dataclass(frozen=True)
class ProjectsSurface:
    """`pilot-projects` as configured: its shared token, out of its repr, and
    its client of the API."""

    token: str = field(repr=False)
    api: PilotProjectsApi


async def _ok(_request: Request) -> Response:
    return JSONResponse({"status": "ok"})


def _server(name: str, instructions: str, path: str) -> FastMCP:
    return FastMCP(
        name=name,
        instructions=instructions,
        streamable_http_path=path,
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )


def build_app(
    work: PilotWorkApi, store: PilotStoreApi, projects: ProjectsSurface | None
) -> Starlette:
    """The app the pod serves: the servers and the probes behind the bearer
    gate, `pilot-projects` behind its door, each server's session manager
    running for the app's lifespan. With no `projects`, the surface not
    configured, its door refuses every request to it."""
    work_server = _server(SERVER_NAME, WORK_INSTRUCTIONS, WORK_PATH)
    register_work_tools(work_server, work)
    store_server = _server(SERVER_NAME, STORE_INSTRUCTIONS, STORE_PATH)
    register_store_tools(store_server, store)
    servers = [work_server, store_server]
    if projects is not None:
        projects_server = _server(
            PROJECTS_SERVER_NAME, PROJECTS_INSTRUCTIONS, PROJECTS_PATH
        )
        register_projects_tools(projects_server, projects.api)
        servers.append(projects_server)
    routes = [
        route for server in servers for route in server.streamable_http_app().routes
    ]

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with AsyncExitStack() as running:
            for server in servers:
                await running.enter_async_context(server.session_manager.run())
            yield

    app = Starlette(
        routes=[
            *routes,
            *(Route(path, _ok, methods=["GET"]) for path in sorted(HEALTH_PATHS)),
        ],
        lifespan=lifespan,
    )
    app.add_middleware(BearerRequired, public=HEALTH_PATHS)
    # Added last, so outermost: a request to the surface meets its door
    # first, and the bearer gate's refusal never answers for it.
    app.add_middleware(
        ProjectsDoor,
        path=PROJECTS_PATH,
        token=None if projects is None else projects.token,
    )
    return app
