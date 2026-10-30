"""The MCP process's clients of `pilot-work`'s and `pilot-store`'s routes:
where they address them, an API that does not answer, and an error answer that
is not its envelope."""

import socket
from typing import get_args

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from app import models
from app.schemas.timeline import HeldReason
from pilot_mcp.api import Added, PilotStoreApi, PilotWorkApi
from pilot_mcp.config import McpSettings
from tests.support.pilot_mcp import API_URL, BEARER, ApiRoutes


def _closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_an_added_work_items_held_takes_every_reason_the_gate_holds_its_start() -> None:
    """A new work item resumes no conversation and is no job: the gate holds
    its start for every other reason."""
    [reasons, _] = get_args(Added.model_fields["held"].annotation)

    assert set(get_args(reasons)) == {
        reason.value
        for reason in HeldReason
        if reason not in (HeldReason.QUEUE, HeldReason.CONVERSATION)
    }


@pytest.mark.anyio
class TestPilotWorkApi:
    async def test_the_routes_are_under_the_settings_url(
        self, routes: ApiRoutes, worker: models.Session
    ) -> None:
        api = PilotWorkApi(str(McpSettings().api_url), transport=routes)

        with pytest.raises(ToolError):
            await api.attach_file(BEARER["Authorization"], None, "/work/missing", None)
        await api.aclose()

        [(request, _)] = routes.calls
        assert str(request.url) == "http://localhost:3501/tools/pilot-work/attachments"

    async def test_an_api_that_does_not_answer_is_a_tool_error_naming_it(
        self,
    ) -> None:
        url = f"http://127.0.0.1:{_closed_port()}"
        api = PilotWorkApi(url)

        with pytest.raises(ToolError) as refused:
            await api.register_document(BEARER["Authorization"], None, "/work/a.md")
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
            await api.register_document(BEARER["Authorization"], None, "/work/a.md")
        await api.aclose()

        assert str(refused.value) == (
            f"Pilot's API answered {status} {httpx.codes.get_reason_phrase(status)},"
            " not its error envelope"
        )


@pytest.mark.anyio
class TestPilotStoreApi:
    async def test_the_routes_are_under_the_settings_url(
        self, routes: ApiRoutes, worker: models.Session
    ) -> None:
        api = PilotStoreApi(str(McpSettings().api_url), transport=routes)

        with pytest.raises(ToolError):
            await api.finish(BEARER["Authorization"], None)
        await api.aclose()

        [(request, _)] = routes.calls
        assert str(request.url) == "http://localhost:3501/tools/pilot-store/finish"

    async def test_an_api_that_does_not_answer_is_a_tool_error_naming_it(
        self,
    ) -> None:
        url = f"http://127.0.0.1:{_closed_port()}"
        api = PilotStoreApi(url)

        with pytest.raises(ToolError) as refused:
            await api.finish(BEARER["Authorization"], None)
        await api.aclose()

        assert str(refused.value) == (
            f"Cannot call pilot-store because Pilot's API at {url} did not answer"
            " (ConnectError)"
        )
