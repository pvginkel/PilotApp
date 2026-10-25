"""The MCP process's client of `pilot-work`'s routes: where it addresses them,
and an API that does not answer."""

import socket

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from app import models
from pilot_mcp.api import PilotWorkApi
from pilot_mcp.config import McpSettings
from tests.support.pilot_mcp import BEARER, ApiRoutes


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
