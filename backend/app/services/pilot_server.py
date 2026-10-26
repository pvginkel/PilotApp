"""Pilot's MCP server, handed to every headless session Pilot creates (TD §4.5;
F84, F87).

Each create mints a token of its own. Its plaintext goes into the create's
`env` as `PILOT_TOKEN=<token>` and nowhere else: no row, log line or record.
The create's `mcpConfig` gets one inline entry naming the server at the
endpoint of the create's surface, `pilot-work` at the server's URL and
`pilot-store` at `<URL>/store`, its bearer `${PILOT_TOKEN}`, which `claude`
expands from the environment of the process the controller spawns, so the
token is in neither argv nor a file. `strictMcpConfig` is left unset, and the
session keeps its environment's own servers. The token's sha256 is the
Session's `token_hash`, which its creator writes with the controller session
the create made. With no server's URL configured, a create carries neither the
token nor the entry.
"""

import hashlib
import json
import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.exceptions import AuthenticationException
from app.models import Session as AgentSession
from app.models import SessionKind
from app.models.reference import Surface
from app.services.controller_client import HeadlessCreateRequest
from app.services.session_scope import ScopedCreate

TOKEN_VARIABLE = "PILOT_TOKEN"

SERVER_KEY = "pilot"
"""The server's `mcpServers` key, whichever its surface: `claude` names each of
its tools `mcp__pilot__<tool>`."""

STORE_PATH = "/store"
"""`pilot-store`'s endpoint under `pilot-work`'s, as the MCP process serves
them (`pilot_mcp/server.py`)."""


_BEARER = "Bearer "


def token_hash(token: str) -> str:
    """The token's sha256 as the record keeps it, lowercase hex."""
    return hashlib.sha256(token.encode()).hexdigest()


def bearer_session(
    db: Session, authorization: str | None, surface: Surface
) -> tuple[AgentSession, Surface]:
    """The Session whose bearer `authorization` carries, and its kind's
    surface, for a call to `surface`'s routes.

    Raises:
        AuthenticationException: no bearer, or one no Session has.
    """
    if authorization is None or not authorization.startswith(_BEARER):
        raise AuthenticationException(
            f"Cannot call {surface} because the request carries no bearer"
        )
    found = db.execute(
        select(AgentSession, SessionKind.surface)
        .join(SessionKind, SessionKind.code == AgentSession.kind_code)
        .where(
            AgentSession.token_hash == token_hash(authorization.removeprefix(_BEARER))
        )
    ).one_or_none()
    if found is None:
        raise AuthenticationException(
            f"Cannot call {surface} because no session has the request's bearer"
        )
    session, its_surface = found
    return session, Surface(its_surface)


@dataclass(frozen=True)
class Injected:
    """A headless create with Pilot's server handed to it."""

    request: HeadlessCreateRequest
    """The create's body, its `env` holding the token's plaintext."""
    token_hash: str


class PilotServer:
    """Hands Pilot's MCP server, at `url`, to each headless create."""

    def __init__(self, url: str | None) -> None:
        """Hand the server at `url` to each create.

        Args:
            url: `pilot-work`'s endpoint as a session reaches it, `pilot-store`'s
                under it; None hands a create no server
        """
        self._url = url

    def inject(self, create: ScopedCreate) -> Injected:
        """`create`'s request with a token minted for it, and the server of its
        surface named in its `mcpConfig` with the token as its bearer."""
        token = secrets.token_urlsafe(32)
        request = create.request
        if self._url is None:
            return Injected(request, token_hash(token))
        registration = {
            "mcpServers": {
                SERVER_KEY: {
                    "type": "http",
                    "url": self._endpoint(self._url, create.surface),
                    "headers": {"Authorization": f"Bearer ${{{TOKEN_VARIABLE}}}"},
                }
            }
        }
        return Injected(
            request.model_copy(
                update={
                    "env": [*(request.env or []), f"{TOKEN_VARIABLE}={token}"],
                    "mcp_config": [
                        *(request.mcp_config or []),
                        json.dumps(registration),
                    ],
                }
            ),
            token_hash(token),
        )

    @staticmethod
    def _endpoint(url: str, surface: Surface) -> str:
        match surface:
            case Surface.WORK:
                return url
            case Surface.STORE:
                return f"{url.rstrip('/')}{STORE_PATH}"
