"""Pilot's MCP server and its Streamable-HTTP app, served at `/mcp`.

- Stateless: every call is a request of its own, so the process holds nothing
  between calls.
- DNS-rebinding protection off: its boundary is the bearer, not the Host
  header, which is the front door's name for it.
- A request with no bearer is refused here; which Session a bearer names, and
  what it may call, the API says (`app/services/pilot_work_service.py`).
- `GET /health/healthz` and `/health/readyz` answer without a bearer. Readiness
  is this process's alone: the API is a container of the same pod.
"""

import json

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from pilot_mcp.api import PilotWorkApi
from pilot_mcp.tools import register_tools

SERVER_NAME = "pilot"

INSTRUCTIONS = (
    "Pilot, the project manager that started this session to do a work item of"
    " its project. Write each decision document your work produces as a file"
    " under `/work`, register it with `register_document` and attach what backs"
    " it with `attach_file`, then end your turn: never wait for the answers."
    " Pilot reads each registered document again when your turn ends and puts it"
    " to the operator; once every one is answered, Pilot writes the answered"
    " files back in place and continues this conversation with a message naming"
    " them."
)

MCP_PATH = "/mcp"

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


def build_server(api: PilotWorkApi) -> FastMCP:
    mcp = FastMCP(
        name=SERVER_NAME,
        instructions=INSTRUCTIONS,
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )
    register_tools(mcp, api)
    for path in sorted(HEALTH_PATHS):
        mcp.custom_route(path, methods=["GET"])(_ok)
    return mcp


def build_app(api: PilotWorkApi) -> Starlette:
    """The app the pod serves: the MCP server behind the bearer gate."""
    app = build_server(api).streamable_http_app()
    app.add_middleware(BearerRequired, public=HEALTH_PATHS)
    return app
