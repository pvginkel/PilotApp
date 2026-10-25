"""The MCP process's client of `pilot-work`'s routes: where it addresses them,
an API that does not answer, and an error answer that is not its envelope."""

import socket

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from app import models
from pilot_mcp.api import PilotWorkApi
from pilot_mcp.config import McpSettings
from tests.support.pilot_mcp import API_URL, BEARER, ApiRoutes


def _closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.mark.anyio
class TestPilotWorkApi:
    async def test_the_routes_are_under_the_settings_url(
        self, routes: ApiRoutes, worker: models.Session
    ) -> None:
        api = PilotWorkApi(str(McpSettings().api_url), transport=routes)

        with pytest.raises(ToolError):
            await api.attach_file(BEARER["Authorization"], "/work/missing", None)
        await api.aclose()

        [(request, _)] = routes.calls
        assert str(request.url) == "http://localhost:3501/tools/pilot-work/attachments"

    async def test_an_api_that_does_not_answer_is_a_tool_error_naming_it(
        self,
    ) -> None:
        url = f"http://127.0.0.1:{_closed_port()}"
        api = PilotWorkApi(url)

        with pytest.raises(ToolError) as refused:
            await api.register_document(BEARER["Authorization"], "/work/a.md")
        await api.aclose()

        assert str(refused.value) == (
            f"Cannot call pilot-work because Pilot's API at {url} did not answer"
            " (ConnectError)"
        )

    @pytest.mark.parametrize(
        ("status", "content_type", "body"),
        [
            (405, "text/html", b"<html><body><h1>405 Not Allowed</h1></body></html>"),
            (422, "application/json", b'[{"loc": ["path"], "msg": "field required"}]'),
        ],
        ids=["not-the-api", "spectree"],
    )
    async def test_an_error_answer_that_is_not_its_envelope_is_a_tool_error_naming_its_status(
        self, status: int, content_type: str, body: bytes
    ) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                status, headers={"Content-Type": content_type}, content=body
            )
        )
        api = PilotWorkApi(API_URL, transport=transport)

        with pytest.raises(ToolError) as refused:
            await api.register_document(BEARER["Authorization"], "/work/a.md")
        await api.aclose()

        assert str(refused.value) == (
            f"Pilot's API answered {status} {httpx.codes.get_reason_phrase(status)},"
            " not its error envelope"
        )
