"""The service user's token (F150.13): minted at the token endpoint with the
client's credentials, held while it lasts, and minted again before it
expires."""

import asyncio

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from pilot_mcp.credential import MARGIN_SECONDS, ServiceCredential
from tests.support.pilot_mcp import (
    CLIENT_ID,
    CLIENT_SECRET,
    TOKEN_URL,
    TokenEndpoint,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _endpoint(expires_in: int = 300) -> TokenEndpoint:
    """A token endpoint issuing `token-1`, `token-2`, … in turn."""
    issued = iter(range(1, 100))
    return TokenEndpoint(lambda: f"token-{next(issued)}", expires_in)


def _credential(
    endpoint: httpx.AsyncBaseTransport,
    clock: _Clock | None = None,
    secret: str = CLIENT_SECRET,
) -> ServiceCredential:
    return ServiceCredential(
        TOKEN_URL, CLIENT_ID, secret, transport=endpoint, clock=clock or _Clock()
    )


@pytest.mark.anyio
class TestServiceCredential:
    async def test_the_first_call_mints_with_the_clients_credentials(self) -> None:
        endpoint = _endpoint()
        credential = _credential(endpoint)

        authorization = await credential.authorization()
        await credential.aclose()

        assert authorization == "Bearer token-1"
        assert endpoint.forms == [
            {
                "grant_type": "client_credentials",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            }
        ]

    async def test_the_token_is_held_until_the_margin_before_its_expiry(self) -> None:
        endpoint = _endpoint(expires_in=300)
        clock = _Clock()
        credential = _credential(endpoint, clock)
        await credential.authorization()

        clock.now += 300 - MARGIN_SECONDS - 1
        held = await credential.authorization()
        await credential.aclose()

        assert held == "Bearer token-1"
        assert endpoint.minted == ["token-1"]

    async def test_it_is_minted_again_at_the_margin_before_its_expiry(self) -> None:
        endpoint = _endpoint(expires_in=300)
        clock = _Clock()
        credential = _credential(endpoint, clock)
        await credential.authorization()

        clock.now += 300 - MARGIN_SECONDS
        second = await credential.authorization()
        clock.now += 300 - MARGIN_SECONDS - 1
        still_second = await credential.authorization()
        clock.now += 1
        third = await credential.authorization()
        await credential.aclose()

        assert (second, still_second, third) == (
            "Bearer token-2",
            "Bearer token-2",
            "Bearer token-3",
        )

    async def test_a_token_shorter_lived_than_the_margin_is_minted_at_every_call(
        self,
    ) -> None:
        endpoint = _endpoint(expires_in=int(MARGIN_SECONDS))
        credential = _credential(endpoint)

        tokens = [await credential.authorization() for _ in range(2)]
        await credential.aclose()

        assert tokens == ["Bearer token-1", "Bearer token-2"]

    async def test_calls_at_once_mint_one_token(self) -> None:
        endpoint = _endpoint()
        credential = _credential(endpoint)

        tokens = await asyncio.gather(*(credential.authorization() for _ in range(5)))
        await credential.aclose()

        assert set(tokens) == {"Bearer token-1"}
        assert endpoint.minted == ["token-1"]

    async def test_a_refused_client_is_a_tool_error_that_names_no_secret(self) -> None:
        endpoint = _endpoint()
        credential = _credential(endpoint, secret="not-the-secret")

        with pytest.raises(ToolError) as refused:
            await credential.authorization()
        await credential.aclose()

        assert str(refused.value) == (
            "Cannot call Pilot because its sign-in service refused Pilot's own"
            " client (401 Unauthorized)"
        )
        assert endpoint.minted == []

    async def test_after_a_refusal_the_next_call_asks_again(self) -> None:
        answers = iter(
            [
                httpx.Response(503, text="Service Unavailable"),
                httpx.Response(
                    200, json={"access_token": "token-1", "expires_in": 300}
                ),
            ]
        )
        credential = _credential(httpx.MockTransport(lambda request: next(answers)))

        with pytest.raises(ToolError, match="503 Service Unavailable"):
            await credential.authorization()
        authorization = await credential.authorization()
        await credential.aclose()

        assert authorization == "Bearer token-1"

    async def test_an_endpoint_that_does_not_answer_is_a_tool_error_naming_it(
        self,
    ) -> None:
        def unreachable(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host", request=request)

        credential = _credential(httpx.MockTransport(unreachable))

        with pytest.raises(ToolError) as refused:
            await credential.authorization()
        await credential.aclose()

        assert str(refused.value) == (
            f"Cannot call Pilot because its sign-in service at {TOKEN_URL} did not"
            " answer (ConnectError)"
        )

    @pytest.mark.parametrize(
        "answer",
        [
            httpx.Response(200, json={"expires_in": 300}),
            httpx.Response(200, json={"access_token": "token-1"}),
            httpx.Response(200, text="<html>Sign in</html>"),
        ],
        ids=["no-token", "no-expiry", "not-json"],
    )
    async def test_an_answer_that_is_no_token_is_a_tool_error(
        self, answer: httpx.Response
    ) -> None:
        credential = _credential(httpx.MockTransport(lambda request: answer))

        with pytest.raises(ToolError) as refused:
            await credential.authorization()
        await credential.aclose()

        assert str(refused.value) == (
            "Cannot call Pilot because its sign-in service answered no token"
        )
