"""The MCP process's clients of `pilot-work`'s and `pilot-store`'s routes and
of the API's own for `pilot-projects`: where they address them, an API that
does not answer, and an error answer that is not its envelope."""

import socket
from typing import get_args

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from app import models
from app.models.reference import ProgressState
from app.models.reference import ProjectState as RecordedProjectState
from app.schemas import pilot_work
from app.schemas.projects import ProjectStatus as ApiProjectStatus
from app.schemas.timeline import HeldReason, ItemKindCode
from pilot_mcp import api as pilot_mcp_api
from pilot_mcp.api import (
    Added,
    Caller,
    ItemKind,
    PilotProjectsApi,
    PilotStoreApi,
    PilotWorkApi,
    ProjectState,
    ProjectStatus,
    StepState,
)
from pilot_mcp.config import McpSettings
from tests.support.pilot_mcp import (
    API_URL,
    BEARER,
    ApiRoutes,
    TokenEndpoint,
    credential,
)


def _closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_an_added_work_items_held_takes_every_reason_the_gate_holds_its_start() -> None:
    """A new work item resumes no conversation, is no job and is no job's or
    Chat's to hold for the store's update: the gate holds its start for
    every other reason."""
    [reasons, _] = get_args(Added.model_fields["held"].annotation)

    assert set(get_args(reasons)) == {
        reason.value
        for reason in HeldReason
        if reason
        not in (HeldReason.QUEUE, HeldReason.CONVERSATION, HeldReason.STORE_UPDATE)
    }


def test_a_steps_state_takes_every_progress_state() -> None:
    assert set(get_args(StepState)) == {state.value for state in ProgressState}


def test_a_projects_state_and_status_take_every_value_the_api_answers() -> None:
    assert set(get_args(ProjectState)) == {
        state.value for state in RecordedProjectState
    }
    assert set(get_args(ProjectStatus)) == {status.value for status in ApiProjectStatus}


def test_a_listed_items_kind_takes_every_kind_the_api_indexes() -> None:
    assert get_args(ItemKind) == get_args(ItemKindCode)


def test_the_pages_are_the_fleets_file_tools() -> None:
    """KubeCoder's `mcp-server/src/kubecoder_mcp/tools/file.py` (F150.5)."""
    assert (
        pilot_mcp_api.LIST_LIMIT_DEFAULT,
        pilot_mcp_api.LIST_LIMIT_MAX,
        pilot_mcp_api.FIND_LIMIT_DEFAULT,
        pilot_mcp_api.FIND_LIMIT_MAX,
    ) == (100, 1000, 50, 200)


@pytest.mark.parametrize("limit", ["MAX_STEP_CODE", "MAX_STEP_LABEL", "MAX_STEPS"])
def test_a_steps_limits_are_its_routes(limit: str) -> None:
    assert getattr(pilot_mcp_api, limit) == getattr(pilot_work, limit)


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
            await api.finish(BEARER["Authorization"], None, archive=False)
        await api.aclose()

        [(request, _)] = routes.calls
        assert str(request.url) == "http://localhost:3501/tools/pilot-store/finish"

    async def test_an_api_that_does_not_answer_is_a_tool_error_naming_it(
        self,
    ) -> None:
        url = f"http://127.0.0.1:{_closed_port()}"
        api = PilotStoreApi(url)

        with pytest.raises(ToolError) as refused:
            await api.finish(BEARER["Authorization"], None, archive=False)
        await api.aclose()

        assert str(refused.value) == (
            f"Cannot call pilot-store because Pilot's API at {url} did not answer"
            " (ConnectError)"
        )


_CALLER = Caller(environment="example-recipebox-1a2b3c", session=None)


def _held_token() -> TokenEndpoint:
    return TokenEndpoint(lambda: "a-token")


@pytest.mark.anyio
class TestPilotProjectsApi:
    async def test_the_routes_are_under_api_at_the_settings_url(self) -> None:
        asked: list[httpx.Request] = []

        def answer(request: httpx.Request) -> httpx.Response:
            asked.append(request)
            return httpx.Response(200, json={"projects": []})

        api = PilotProjectsApi(
            str(McpSettings().api_url),
            credential(_held_token()),
            transport=httpx.MockTransport(answer),
        )

        await api.list_projects(_CALLER, archived=False)
        await api.aclose()

        [request] = asked
        assert str(request.url) == "http://localhost:3501/api/projects?archived=false"
        assert request.headers["authorization"] == "Bearer a-token"

    async def test_an_api_that_does_not_answer_is_a_tool_error_naming_it(
        self,
    ) -> None:
        url = f"http://127.0.0.1:{_closed_port()}"
        api = PilotProjectsApi(url, credential(_held_token()))

        with pytest.raises(ToolError) as refused:
            await api.get_project(_CALLER, "recipe-box")
        await api.aclose()

        assert str(refused.value) == (
            f"Cannot call pilot-projects because Pilot's API at {url} did not answer"
            " (ConnectError)"
        )

    async def test_an_error_answer_that_is_not_its_envelope_is_a_tool_error_naming_its_status(
        self,
    ) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                502, headers={"Content-Type": "text/html"}, content=b"<html></html>"
            )
        )
        api = PilotProjectsApi(API_URL, credential(_held_token()), transport=transport)

        with pytest.raises(ToolError) as refused:
            await api.get_project(_CALLER, "recipe-box")
        await api.aclose()

        assert str(refused.value) == (
            "Pilot's API answered 502 Bad Gateway, not its error envelope"
        )

    async def test_no_call_is_made_while_no_token_is_minted(self) -> None:
        asked: list[httpx.Request] = []

        def answer(request: httpx.Request) -> httpx.Response:
            asked.append(request)
            return httpx.Response(200, json={"projects": []})

        refusing = httpx.MockTransport(lambda request: httpx.Response(401, json={}))
        api = PilotProjectsApi(
            API_URL, credential(refusing), transport=httpx.MockTransport(answer)
        )

        with pytest.raises(ToolError, match="refused Pilot's own client"):
            await api.list_projects(_CALLER, archived=False)
        await api.aclose()

        assert asked == []
