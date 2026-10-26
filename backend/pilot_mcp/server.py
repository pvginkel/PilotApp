"""Pilot's MCP server and its Streamable-HTTP app: `pilot-work`, a worker's
tools, at `/mcp`, and `pilot-store`, the brain's, at `/mcp/store`, two servers
named `pilot` in one app. Which a session is handed, and which its bearer may
call, its Session's kind says (`app/services/pilot_server.py`).

- Stateless: every call is a request of its own, so the process holds nothing
  between calls.
- DNS-rebinding protection off: its boundary is the bearer, not the Host
  header, which is the front door's name for it.
- A request with no bearer is refused here; which Session a bearer names, and
  what it may call, the API says (`app/services/pilot_work_service.py`,
  `app/services/pilot_store_service.py`).
- `GET /health/healthz` and `/health/readyz` answer without a bearer. Readiness
  is this process's alone: the API is a container of the same pod.
"""

import json
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from pilot_mcp.api import PilotStoreApi, PilotWorkApi
from pilot_mcp.tools import register_store_tools, register_work_tools

SERVER_NAME = "pilot"

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
    " the block's local id as its fence does. A call the record refuses changes"
    " nothing and answers the reason."
)

WORK_PATH = "/mcp"

STORE_PATH = "/mcp/store"
"""Under `pilot-work`'s, as the backend hands it (`STORE_PATH` of
`app/services/pilot_server.py`)."""

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


def _carries_bearer(scope: Scope) -> bool:
    """Whether the request's `Authorization` is `Bearer <token>`, as the API
    reads it."""
    for name, value in scope["headers"]:
        if name == b"authorization":
            return value.startswith(_BEARER) and bool(
                value.removeprefix(_BEARER).strip()
            )
    return False


class BearerRequired:
    """Refuses a request to any path but `public` that carries no bearer."""

    def __init__(self, app: ASGIApp, public: frozenset[str]) -> None:
        self._app = app
        self._public = public

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["path"] in self._public
            or _carries_bearer(scope)
        ):
            await self._app(scope, receive, send)
            return
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _NO_BEARER})


async def _ok(_request: Request) -> Response:
    return JSONResponse({"status": "ok"})


def _server(instructions: str, path: str) -> FastMCP:
    return FastMCP(
        name=SERVER_NAME,
        instructions=instructions,
        streamable_http_path=path,
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )


def build_app(work: PilotWorkApi, store: PilotStoreApi) -> Starlette:
    """The app the pod serves: both servers and the probes behind the bearer
    gate, each server's session manager running for the app's lifespan."""
    work_server = _server(WORK_INSTRUCTIONS, WORK_PATH)
    register_work_tools(work_server, work)
    store_server = _server(STORE_INSTRUCTIONS, STORE_PATH)
    register_store_tools(store_server, store)
    servers = (work_server, store_server)
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
    return app
