"""`pilot-work`'s tools driven through a real MCP client to the API's routes
(F85, ruling D1): each one REST call under the caller's bearer as it came,
its answer the route's, and the route's refusal the tool's error, its reason
whole."""

import json
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession
from starlette.applications import Starlette

from app import models
from app.models import Attachment, Document, Environment, Item, ItemAttachment
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerClient
from tests.support.fake_controller import ServedFakeController
from tests.support.pilot_mcp import (
    API_URL,
    BEARER,
    ApiRoutes,
    call,
    error_text,
    mcp_session,
    running_session,
)

PATH = "/work/Example/docs/refinement.md"

TEXT = "Two options for the camp.\n\n```question id=Q1\n```\n"


def _file(
    fake_controller: ServedFakeController,
    environment: Environment,
    path: str = PATH,
    text: str = TEXT,
) -> None:
    fake_controller.add_environment(environment.id)
    fake_controller.put_file(environment.id, path, text.encode())


def _refusal(routes: ApiRoutes, tool: str) -> str:
    """The tool's error the route's last refusal makes: its `error` whole."""
    _, answer = routes.calls[-1]
    assert answer.is_error
    return f"Error executing tool {tool}: {answer.json()['error']}"


def _registered(session: DbSession) -> list[Document]:
    return list(
        session.scalars(select(Document).where(Document.source_path == PATH)).all()
    )


@pytest.mark.anyio
class TestRegisterDocument:
    async def test_the_file_is_registered_through_its_route(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        environment: Environment,
        worker: models.Session,
    ) -> None:
        _file(fake_controller, environment)

        result = await call(mcp_app, "register_document", {"path": PATH})

        assert not result.isError
        [(request, answer)] = routes.calls
        assert (request.method, str(request.url)) == (
            "POST",
            f"{API_URL}/tools/pilot-work/documents",
        )
        assert request.headers["authorization"] == BEARER["Authorization"]
        assert json.loads(request.content) == {"path": PATH}
        assert answer.status_code == 201
        assert result.structuredContent == answer.json()
        item = session.get_one(Item, uuid.UUID(answer.json()["id"]))
        assert item.created_by_session_id == worker.id
        assert session.get_one(Document, item.id).source_path == PATH

    async def test_the_same_path_again_answers_the_same_id(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        environment: Environment,
        worker: models.Session,
    ) -> None:
        _file(fake_controller, environment)

        async with mcp_session(mcp_app) as (mcp, _):
            first = await mcp.call_tool("register_document", {"path": PATH})
            again = await mcp.call_tool("register_document", {"path": PATH})

        assert again.structuredContent == first.structuredContent
        assert [answer.status_code for _, answer in routes.calls] == [201, 200]

    @pytest.mark.parametrize(
        ("text", "reason"),
        [
            (
                "```question id=Q1\n",
                f"Cannot register document {PATH} because its text holds faults:"
                " line 1: ",
            ),
            (None, f"Cannot register document {PATH} because the controller answered"),
        ],
    )
    async def test_a_file_the_route_refuses_is_the_tools_error_its_reason_whole(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        environment: Environment,
        worker: models.Session,
        text: str | None,
        reason: str,
    ) -> None:
        fake_controller.add_environment(environment.id)
        if text is not None:
            fake_controller.put_file(environment.id, PATH, text.encode())

        result = await call(mcp_app, "register_document", {"path": PATH})

        assert routes.calls[-1][1].status_code == 409
        assert error_text(result) == _refusal(routes, "register_document")
        assert error_text(result).startswith(
            f"Error executing tool register_document: {reason}"
        )
        assert _registered(session) == []

    async def test_a_bearer_no_session_has_is_the_routes_refusal(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        worker: models.Session,
    ) -> None:
        result = await call(
            mcp_app,
            "register_document",
            {"path": PATH},
            headers={"Authorization": "Bearer another-token"},
        )

        [(request, answer)] = routes.calls
        assert request.headers["authorization"] == "Bearer another-token"
        assert answer.status_code == 401
        assert error_text(result) == (
            "Error executing tool register_document: Cannot call pilot-work because"
            " no session has the request's bearer"
        )

    async def test_a_session_that_is_not_a_work_items_is_the_routes_refusal(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        container: ServiceContainer,
        project: models.Project,
        environment: Environment,
    ) -> None:
        chat = running_session(session, container, project, environment, kind="chat")

        result = await call(mcp_app, "register_document", {"path": PATH})

        assert routes.calls[-1][1].status_code == 403
        assert error_text(result) == (
            "Error executing tool register_document: Cannot call pilot-work because"
            f" session {chat.id} is a chat session, not a work item's"
        )

    async def test_an_empty_path_is_refused_without_calling_the_api(
        self, mcp_app: Starlette, routes: ApiRoutes, worker: models.Session
    ) -> None:
        result = await call(mcp_app, "register_document", {"path": ""})

        assert "String should have at least 1 character" in error_text(result)
        assert routes.calls == []


@pytest.mark.anyio
class TestAttachFile:
    async def test_without_to_the_file_hangs_on_the_sessions_work_item(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        environment: Environment,
        worker: models.Session,
    ) -> None:
        _file(fake_controller, environment)

        result = await call(mcp_app, "attach_file", {"path": PATH})

        assert not result.isError
        [(request, answer)] = routes.calls
        assert (request.method, str(request.url)) == (
            "POST",
            f"{API_URL}/tools/pilot-work/attachments",
        )
        assert request.headers["authorization"] == BEARER["Authorization"]
        assert json.loads(request.content) == {"path": PATH}
        assert answer.status_code == 201
        assert result.structuredContent == answer.json()
        [attachment_id] = answer.json()["ids"]
        hung = session.scalars(
            select(ItemAttachment.item_id).where(
                ItemAttachment.attachment_id == uuid.UUID(attachment_id)
            )
        ).all()
        assert hung == [worker.id]

    async def test_to_names_the_item_it_hangs_on(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        environment: Environment,
        worker: models.Session,
    ) -> None:
        _file(fake_controller, environment)
        async with mcp_session(mcp_app) as (mcp, _):
            registered = await mcp.call_tool("register_document", {"path": PATH})
            assert registered.structuredContent is not None
            to = registered.structuredContent["id"]
            result = await mcp.call_tool("attach_file", {"path": PATH, "to": to})

        request, answer = routes.calls[-1]
        assert json.loads(request.content) == {"path": PATH, "to": to}
        [attachment_id] = answer.json()["ids"]
        hung = session.scalars(
            select(ItemAttachment.item_id).where(
                ItemAttachment.attachment_id == uuid.UUID(attachment_id)
            )
        ).all()
        assert hung == [uuid.UUID(to)]
        assert result.structuredContent == {"ids": [attachment_id]}

    async def test_a_folder_answers_one_id_per_file_in_path_order(
        self,
        mcp_app: Starlette,
        session: DbSession,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        environment: Environment,
        worker: models.Session,
    ) -> None:
        fake_controller.add_environment(environment.id)
        fake_controller.put_file(environment.id, "/work/Example/out/b/c.md", b"C")
        fake_controller.put_file(environment.id, "/work/Example/out/a.md", b"# A\n")

        result = await call(mcp_app, "attach_file", {"path": "/work/Example/out"})

        assert result.structuredContent is not None
        assert [
            session.get_one(Attachment, uuid.UUID(id_)).source_path
            for id_ in result.structuredContent["ids"]
        ] == ["/work/Example/out/a.md", "/work/Example/out/b/c.md"]

    async def test_a_to_not_of_the_project_is_the_routes_refusal(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        environment: Environment,
        worker: models.Session,
    ) -> None:
        _file(fake_controller, environment)
        to = uuid.uuid4()

        result = await call(mcp_app, "attach_file", {"path": PATH, "to": str(to)})

        assert routes.calls[-1][1].status_code == 404
        assert error_text(result) == (
            f"Error executing tool attach_file: Item {to} was not found"
        )

    async def test_a_file_the_route_cannot_copy_is_the_tools_error_its_reason_whole(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        environment: Environment,
        worker: models.Session,
    ) -> None:
        fake_controller.add_environment(environment.id)

        result = await call(mcp_app, "attach_file", {"path": PATH})

        assert routes.calls[-1][1].status_code == 409
        assert error_text(result) == _refusal(routes, "attach_file")
        assert error_text(result).startswith(
            f"Error executing tool attach_file: Cannot attach {PATH} because the"
            " controller answered 404 not-found: "
        )
        assert session.scalar(select(func.count()).select_from(Attachment)) == 0

    @pytest.mark.parametrize(
        "arguments", [{"path": ""}, {"path": PATH, "to": "not-an-id"}]
    )
    async def test_arguments_the_route_would_refuse_are_refused_without_calling_it(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        worker: models.Session,
        arguments: dict[str, str],
    ) -> None:
        result = await call(mcp_app, "attach_file", arguments)

        assert error_text(result).startswith("Error executing tool attach_file: ")
        assert routes.calls == []
