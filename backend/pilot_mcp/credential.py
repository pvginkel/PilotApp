"""The service user's token (F150.13): a client-credentials token of its
Keycloak client, which the projects surface's calls to the API carry, minted at
the token endpoint and minted again before it expires."""

import asyncio
import time
from collections.abc import Callable

import httpx
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel, ValidationError

MARGIN_SECONDS = 30.0
"""How long before a token expires its successor is minted: a call never
carries one with less left."""

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class _Minted(BaseModel):
    access_token: str
    expires_in: float


class ServiceCredential:
    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        """`transport` answers in place of the network and `clock` in place of
        the process's, in the suite."""
        self._token_url = token_url
        self._form = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
        self._http = httpx.AsyncClient(timeout=_TIMEOUT, transport=transport)
        self._clock = clock
        self._minting = asyncio.Lock()
        self._token: str | None = None
        self._mint_again_at = 0.0

    async def aclose(self) -> None:
        await self._http.aclose()

    async def authorization(self) -> str:
        """The `Authorization` of a call to the API, `Bearer <token>`: the
        token held, or one minted now where none is held or the held one is
        within `MARGIN_SECONDS` of its expiry.

        Raises:
            ToolError: the token endpoint did not answer, refused the client
                or answered no token.
        """
        async with self._minting:
            if self._token is None or self._clock() >= self._mint_again_at:
                asked_at = self._clock()
                minted = await self._mint()
                self._token = minted.access_token
                self._mint_again_at = asked_at + minted.expires_in - MARGIN_SECONDS
            return f"Bearer {self._token}"

    async def _mint(self) -> _Minted:
        try:
            response = await self._http.post(self._token_url, data=self._form)
        except httpx.RequestError as exc:
            raise ToolError(
                "Cannot call Pilot because its sign-in service at"
                f" {self._token_url} did not answer ({type(exc).__name__})"
            ) from exc
        if response.is_error:
            raise ToolError(
                "Cannot call Pilot because its sign-in service refused Pilot's"
                f" own client ({response.status_code} {response.reason_phrase})"
            )
        try:
            return _Minted.model_validate_json(response.content)
        except ValidationError as exc:
            raise ToolError(
                "Cannot call Pilot because its sign-in service answered no token"
            ) from exc
