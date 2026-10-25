"""Pilot's MCP server, handed to every headless session Pilot creates (TD §4.5;
F84, F87).

Each create mints a token of its own. Its plaintext goes into the create's
`env` as `PILOT_TOKEN=<token>` and nowhere else: no row, log line or record.
The create's `mcpConfig` gets one inline entry naming the server, its bearer
`${PILOT_TOKEN}`, which `claude` expands from the environment of the process
the controller spawns, so the token is in neither argv nor a file.
`strictMcpConfig` is left unset, and the session keeps its environment's own
servers. The token's sha256 is the Session's `token_hash`, which its creator
writes with the controller session the create made. With no server's URL
configured, a create carries neither the token nor the entry.
"""

import hashlib
import json
import secrets
from dataclasses import dataclass

from app.services.controller_client import HeadlessCreateRequest

TOKEN_VARIABLE = "PILOT_TOKEN"

SERVER_KEY = "pilot"
"""The server's `mcpServers` key: `claude` names each of its tools
`mcp__pilot__<tool>`."""


def token_hash(token: str) -> str:
    """The token's sha256 as the record keeps it, lowercase hex."""
    return hashlib.sha256(token.encode()).hexdigest()


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
            url: The server's endpoint as a session reaches it; None hands a
                create no server
        """
        self._url = url

    def inject(self, request: HeadlessCreateRequest) -> Injected:
        """`request` with a token minted for it, and the server named in its
        `mcpConfig` with the token as its bearer."""
        token = secrets.token_urlsafe(32)
        if self._url is None:
            return Injected(request, token_hash(token))
        registration = {
            "mcpServers": {
                SERVER_KEY: {
                    "type": "http",
                    "url": self._url,
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
