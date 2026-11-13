"""`pilot-work`'s tools (F85, ruling D1, F85.3, F85.4) and `pilot-store`'s
(F86) driven through a real MCP client to the API's routes: each one REST call
under the caller's bearer as it came, its answer the route's, and the route's
refusal the tool's error, its reason whole. And `pilot-projects`' (F150.6,
F150.7), each one REST call to a route under `/api/`, behind the sign-in gate,
under the service user's token and never the caller's bearer (F150.13)."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from dependency_injector import providers
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession
from starlette.applications import Starlette

from app import models
from app.config import Settings
from app.models import (
    Attachment,
    Block,
    Chat,
    Document,
    Environment,
    Item,
    ItemAttachment,
    PlanTask,
    Turn,
    UsageReading,
    WindowShare,
    WriterQuestion,
)
from app.models.reference import (
    AnswerChannel,
    ChatKind,
    ProjectState,
    SessionState,
    TaskStatus,
    UsageWindow,
)
from app.schemas.testing_record import InventedProjectCreateSchema
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerClient
from app.services.session_record_service import read_records
from pilot_mcp.api import ENVIRONMENT_HEADER, SESSION_HEADER
from pilot_mcp.server import PROJECTS_PATH, STORE_PATH
from pilot_mcp.tools import TOOL_USE_ID_META
from tests.support.fake_controller import ServedFakeController
from tests.support.pilot_mcp import (
    API_URL,
    BEARER,
    CALLER_ENVIRONMENT,
    CALLER_SESSION,
    PROJECTS_HEADERS,
    PROJECTS_TOKEN,
    ApiRoutes,
    TokenEndpoint,
    app_with_projects,
    call,
    error_text,
    mcp_session,
    running_session,
    service_token,
)
from tests.support.starts import configured_starts
from tests.support.supervisor import Supervise

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


_PUBLISHED = [
    {"code": "P1.code", "label": "P1 · the client", "state": "done"},
    {"code": "test", "label": "Test"},
]


@pytest.mark.anyio
class TestSetProgress:
    async def test_the_list_is_replaced_through_its_route_naming_no_call(
        self, mcp_app: Starlette, routes: ApiRoutes, worker: models.Session
    ) -> None:
        """The call records no effect, so its tool-use id goes nowhere."""
        result = await call(
            mcp_app,
            "set_progress",
            {"steps": _PUBLISHED},
            meta={TOOL_USE_ID_META: "toolu_01ABC"},
        )

        assert not result.isError
        [(request, answer)] = routes.calls
        assert (request.method, str(request.url)) == (
            "PUT",
            f"{API_URL}/tools/pilot-work/progress",
        )
        assert request.headers["authorization"] == BEARER["Authorization"]
        assert "tool-use-id" not in request.headers
        assert json.loads(request.content) == {"steps": _PUBLISHED}
        assert answer.status_code == 200
        assert result.structuredContent == answer.json()
        assert answer.json() == {
            "steps": [
                {"code": "P1.code", "label": "P1 · the client", "state": "done"},
                {"code": "test", "label": "Test", "state": "pending"},
            ]
        }

    async def test_a_repeated_code_is_the_routes_refusal_its_reason_whole(
        self, mcp_app: Starlette, routes: ApiRoutes, worker: models.Session
    ) -> None:
        result = await call(
            mcp_app, "set_progress", {"steps": [*_PUBLISHED, _PUBLISHED[1]]}
        )

        assert routes.calls[-1][1].status_code == 409
        assert error_text(result) == _refusal(routes, "set_progress")
        assert error_text(result) == (
            f"Error executing tool set_progress: Cannot set the progress of work"
            f" item {worker.id} because code test is repeated"
        )

    @pytest.mark.parametrize(
        "steps",
        [
            [{"code": "", "label": "Test"}],
            [{"code": "c" * 65, "label": "Test"}],
            [{"code": "test", "label": ""}],
            [{"code": "test", "label": "l" * 121}],
            [{"code": "test", "label": "Test", "state": "failed"}],
            [{"code": f"s{n}", "label": "Step"} for n in range(101)],
            [{"code": "test", "label": "Test", "note": "x"}],
        ],
        ids=[
            "empty-code",
            "long-code",
            "empty-label",
            "long-label",
            "state",
            "long-list",
            "extra-field",
        ],
    )
    async def test_steps_outside_the_limits_are_refused_without_calling_the_api(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        worker: models.Session,
        steps: list[dict[str, str]],
    ) -> None:
        result = await call(mcp_app, "set_progress", {"steps": steps})

        assert error_text(result).startswith("Error executing tool set_progress: ")
        assert routes.calls == []


@pytest.mark.anyio
class TestSetProgressStep:
    async def test_the_steps_state_is_set_through_its_route(
        self, mcp_app: Starlette, routes: ApiRoutes, worker: models.Session
    ) -> None:
        async with mcp_session(mcp_app) as (mcp, _):
            await mcp.call_tool("set_progress", {"steps": _PUBLISHED})
            result = await mcp.call_tool(
                "set_progress_step", {"code": "test", "state": "active"}
            )

        assert not result.isError
        request, answer = routes.calls[-1]
        assert (request.method, str(request.url)) == (
            "PATCH",
            f"{API_URL}/tools/pilot-work/progress",
        )
        assert request.headers["authorization"] == BEARER["Authorization"]
        assert json.loads(request.content) == {"code": "test", "state": "active"}
        assert result.structuredContent == answer.json()
        assert answer.json()["steps"][1] == {
            "code": "test",
            "label": "Test",
            "state": "active",
        }

    async def test_a_code_not_on_the_list_is_the_routes_refusal(
        self, mcp_app: Starlette, routes: ApiRoutes, worker: models.Session
    ) -> None:
        result = await call(
            mcp_app, "set_progress_step", {"code": "docs", "state": "done"}
        )

        assert routes.calls[-1][1].status_code == 404
        assert error_text(result) == (
            "Error executing tool set_progress_step: Progress step docs was not found"
        )

    @pytest.mark.parametrize(
        "arguments",
        [{"code": "test", "state": "skipped"}, {"code": "", "state": "done"}],
        ids=["state", "empty-code"],
    )
    async def test_arguments_the_route_would_refuse_are_refused_without_calling_it(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        worker: models.Session,
        arguments: dict[str, str],
    ) -> None:
        result = await call(mcp_app, "set_progress_step", arguments)

        assert error_text(result).startswith("Error executing tool set_progress_step: ")
        assert routes.calls == []


@pytest.mark.anyio
class TestTheToolUseId:
    """Claude Code sends each call's tool-use id in its `_meta`; the tool
    passes it to its route, whose effect's record names it."""

    async def test_the_calls_tool_use_id_reaches_its_effect(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        environment: Environment,
        worker: models.Session,
    ) -> None:
        session.add(
            Turn(
                session_id=worker.id,
                seq=1,
                message="Refine the camp.",
                started_at=datetime.now(UTC),
            )
        )
        session.commit()
        _file(fake_controller, environment)

        result = await call(
            mcp_app,
            "register_document",
            {"path": PATH},
            meta={TOOL_USE_ID_META: "toolu_01ABC"},
        )

        assert not result.isError
        [(request, _)] = routes.calls
        assert request.headers["tool-use-id"] == "toolu_01ABC"
        [record] = read_records(session, worker.id, limit=10)
        assert record.record.payload["toolUseId"] == "toolu_01ABC"

    async def test_a_call_without_one_sends_none(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        environment: Environment,
        worker: models.Session,
    ) -> None:
        _file(fake_controller, environment)

        result = await call(mcp_app, "attach_file", {"path": PATH})

        assert not result.isError
        [(request, _)] = routes.calls
        assert "tool-use-id" not in request.headers


DECISION = """---
title: Which tent?
---

```decision id=D1
options:
  - Dome
  - Tunnel
recommend: Dome
```
"""

CAMP_PLAN = """---
title: Camp plan
---

```decision id=D1
options:
  - Dome
  - Tunnel
recommend: Dome
```

```decision id=D2
options:
  - Lake
  - Forest
recommend: Lake
```
"""

REGISTERED = "/work/Example/docs/survey.md"

REGISTERED_TEXT = """---
title: Camp survey
---

```question id=Q1
```

```question id=Q2
```
"""


def _decision(
    session: DbSession, container: ServiceContainer, brain: models.Session
) -> Item:
    """A decision the brain added, committed."""
    project = session.get_one(models.Project, brain.project_id)
    item = container.document_service().bear_item(
        project, "decision", "Which tent?", brain, DECISION
    )
    session.commit()
    return item


def _effect(session: DbSession, brain: models.Session) -> dict[str, object]:
    """The payload of the brain's one record, its call's effect."""
    [record] = read_records(session, brain.id, limit=10)
    payload: dict[str, object] = record.record.payload
    return payload


@pytest.fixture
def placing(container: ServiceContainer, supervise: Supervise) -> None:
    """The container's start on a controller, its loops never run, through
    which a person's close of an item of Pilot's own places the job after
    it."""
    container.session_start_service.override(
        providers.Object(configured_starts(container, supervise))
    )


@pytest.mark.anyio
class TestAnswer:
    @pytest.mark.usefixtures("placing")
    async def test_the_answer_is_recorded_for_the_person_through_its_route(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        container: ServiceContainer,
        person: models.User,
        brain: models.Session,
    ) -> None:
        item = _decision(session, container, brain)

        result = await call(
            mcp_app,
            "answer",
            {
                "block": f"{item.id}/D1",
                "value": "Dome",
                "for": person.handle,
                "note": "The dome, it stands up in five minutes.",
            },
            meta={TOOL_USE_ID_META: "toolu_01"},
            path=STORE_PATH,
        )

        assert not result.isError
        assert result.structuredContent == {"effect": "Answered · D1 · Which tent?"}
        [(request, _)] = routes.calls
        assert str(request.url) == f"{API_URL}/tools/pilot-store/answers"
        assert json.loads(request.content) == {
            "block": f"{item.id}/D1",
            "value": "Dome",
            "for": "ada",
            "note": "The dome, it stands up in five minutes.",
        }
        assert request.headers["tool-use-id"] == "toolu_01"
        block = session.scalars(select(Block).where(Block.document_id == item.id)).one()
        assert (block.answer, block.answered_by_user_id, block.via_code) == (
            "Dome",
            person.id,
            AnswerChannel.CHAT,
        )
        assert _effect(session, brain)["toolUseId"] == "toolu_01"

    async def test_a_block_that_is_no_blocks_id_is_refused_without_calling_the_api(
        self, mcp_app: Starlette, routes: ApiRoutes, brain: models.Session
    ) -> None:
        result = await call(
            mcp_app,
            "answer",
            {"block": "D1", "value": "Dome", "for": "ada"},
            path=STORE_PATH,
        )

        assert "String should match pattern" in error_text(result)
        assert routes.calls == []

    async def test_the_routes_refusal_is_the_tools_error_its_reason_whole(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        container: ServiceContainer,
        brain: models.Session,
    ) -> None:
        item = _decision(session, container, brain)

        result = await call(
            mcp_app,
            "answer",
            {"block": f"{item.id}/D1", "value": "Dome", "for": "nobody"},
            path=STORE_PATH,
        )

        assert error_text(result) == _refusal(routes, "answer")
        assert error_text(result) == (
            "Error executing tool answer: Person nobody was not found"
        )

    async def test_in_a_drafts_definition_chat_the_drafts_ask_is_answered(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        container: ServiceContainer,
        person: models.User,
        brain: models.Session,
    ) -> None:
        project = session.get_one(models.Project, brain.project_id)
        draft = container.document_service().bear_draft(
            project, "---\ntitle: Camp\n---\n\n```question id=Q1\n```\n"
        )
        session.add(
            Chat(
                id=brain.id,
                project_id=project.id,
                session_kind_code="chat",
                kind_code=ChatKind.DEFINITION,
            )
        )
        session.commit()

        result = await call(
            mcp_app,
            "answer",
            {"block": "project.md/Q1", "value": "The lake", "for": person.handle},
            path=STORE_PATH,
        )

        assert not result.isError
        assert result.structuredContent == {"effect": "Answered · Q1 · Camp"}
        block = session.scalars(
            select(Block).where(Block.document_id == draft.id)
        ).one()
        assert (block.answer, block.via_code) == ("The lake", AnswerChannel.CHAT)

    async def test_another_files_block_is_refused_without_calling_the_api(
        self, mcp_app: Starlette, routes: ApiRoutes, brain: models.Session
    ) -> None:
        result = await call(
            mcp_app,
            "answer",
            {"block": "handbook.md/Q1", "value": "Yes", "for": "ada"},
            path=STORE_PATH,
        )

        assert "String should match pattern" in error_text(result)
        assert routes.calls == []


@pytest.mark.anyio
class TestMark:
    @pytest.mark.usefixtures("placing")
    async def test_done_is_marked_for_the_person(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        container: ServiceContainer,
        person: models.User,
        brain: models.Session,
    ) -> None:
        project = session.get_one(models.Project, brain.project_id)
        item = container.document_service().bear_item(
            project, "document", "Camp plan", brain, CAMP_PLAN
        )
        session.commit()

        result = await call(
            mcp_app,
            "mark",
            {"item": str(item.id), "mark": "done", "for": person.handle},
            path=STORE_PATH,
        )

        assert result.structuredContent == {"effect": "Marked done · Camp plan"}
        [(request, _)] = routes.calls
        assert json.loads(request.content) == {
            "item": str(item.id),
            "mark": "done",
            "for": "ada",
        }
        session.refresh(item)
        assert item.done_by_user_id == person.id

    async def test_a_waits_close_sends_its_note(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        container: ServiceContainer,
        brain: models.Session,
    ) -> None:
        project = session.get_one(models.Project, brain.project_id)
        item = container.wait_service().add_card_wait(
            project, brain, "SR-4 lands", ["SR-4"], ["Done"], None
        )
        session.commit()
        note = "SR-4 read Done at 01:14; the card pass goes on"

        result = await call(
            mcp_app,
            "mark",
            {"item": str(item.id), "mark": "done", "note": note},
            path=STORE_PATH,
        )

        assert result.structuredContent == {"effect": "Marked done · SR-4 lands"}
        [(request, _)] = routes.calls
        assert json.loads(request.content) == {
            "item": str(item.id),
            "mark": "done",
            "note": note,
        }
        session.expire_all()
        assert session.get_one(models.Wait, item.id).done_note == note

    async def test_without_for_none_is_sent_and_read_is_the_routes_refusal(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        container: ServiceContainer,
        brain: models.Session,
    ) -> None:
        item = _decision(session, container, brain)

        result = await call(
            mcp_app, "mark", {"item": str(item.id), "mark": "read"}, path=STORE_PATH
        )

        [(request, _)] = routes.calls
        assert json.loads(request.content) == {"item": str(item.id), "mark": "read"}
        assert error_text(result) == (
            f"Error executing tool mark: Cannot mark item {item.id} read because"
            " Pilot's own mark is Done, on a document it settled whole: Read and"
            " Reviewed are a person's, named by `for`"
        )


@pytest.mark.anyio
class TestStopWork:
    async def test_a_work_items_session_is_stopped_by_pilot(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        container: ServiceContainer,
        project: models.Project,
        brain: models.Session,
    ) -> None:
        run = models.Session(
            project_id=project.id,
            kind_code="work",
            cwd="/work/Example",
            token_hash="2" * 64,
            state_code=SessionState.HELD,
            turns=1,
            turn_started_at=datetime.now(UTC),
        )
        session.add(run)
        session.flush()
        session.add(
            Turn(session_id=run.id, seq=1, message="Go.", started_at=datetime.now(UTC))
        )
        container.record_service().place_work(project, run, "Pitching the tent")
        session.commit()

        result = await call(
            mcp_app, "stop_work", {"item": str(run.id)}, path=STORE_PATH
        )

        assert result.structuredContent == {"effect": "Stopped · Pitching the tent"}
        [(request, _)] = routes.calls
        assert json.loads(request.content) == {"item": str(run.id)}
        session.refresh(run)
        assert run.state_code == SessionState.STOPPED


@pytest.mark.anyio
class TestFinish:
    async def test_the_project_is_finished_by_pilot(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        project: models.Project,
        brain: models.Session,
    ) -> None:
        project.state_code = ProjectState.OPEN
        project.slug = "camp"
        project.name = "Camp"
        session.commit()

        result = await call(mcp_app, "finish", {}, path=STORE_PATH)

        assert result.structuredContent == {"effect": "Finished · Camp"}
        [(request, _)] = routes.calls
        assert str(request.url) == f"{API_URL}/tools/pilot-store/finish"
        assert json.loads(request.content) == {"archive": False}
        session.refresh(project)
        assert (project.state_code, project.archived) == (ProjectState.FINISHED, False)

    async def test_with_archive_the_project_is_finished_and_archived(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        project: models.Project,
        brain: models.Session,
    ) -> None:
        project.state_code = ProjectState.OPEN
        project.slug = "camp"
        project.name = "Camp"
        session.commit()

        result = await call(mcp_app, "finish", {"archive": True}, path=STORE_PATH)

        assert result.structuredContent == {"effect": "Finished and archived · Camp"}
        [(request, _)] = routes.calls
        assert json.loads(request.content) == {"archive": True}
        session.refresh(project)
        assert (project.state_code, project.archived) == (ProjectState.FINISHED, True)


@pytest.mark.anyio
class TestAskWriter:
    async def test_a_jobs_question_is_recorded_and_answers_the_blocks_asked(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        container: ServiceContainer,
        project: models.Project,
        environment: Environment,
    ) -> None:
        item = _registered_document(session, container, project, environment)
        job = _job(session, container, project, environment)

        result = await call(
            mcp_app,
            "ask_writer",
            {"block": f"{item.id}/Q2", "question": "Which lake?"},
            path=STORE_PATH,
        )

        assert result.structuredContent == {"blocks": ["Q2"]}
        [(request, _)] = routes.calls
        assert str(request.url) == f"{API_URL}/tools/pilot-store/writer-questions"
        # The block's id names its document (R8).
        assert json.loads(request.content) == {
            "block": f"{item.id}/Q2",
            "question": "Which lake?",
        }
        [question] = session.scalars(select(WriterQuestion))
        assert question.question == "Which lake?"
        assert read_records(session, job.id, limit=10) == []

    async def test_a_chats_question_is_the_routes_refusal(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        container: ServiceContainer,
        project: models.Project,
        environment: Environment,
        brain: models.Session,
    ) -> None:
        item = _registered_document(session, container, project, environment)

        result = await call(
            mcp_app,
            "ask_writer",
            {"block": f"{item.id}/Q2", "question": "Which lake?"},
            path=STORE_PATH,
        )

        assert routes.calls[-1][1].status_code == 403
        assert error_text(result) == (
            f"Error executing tool ask_writer: Cannot ask the writer about block"
            f" {item.id}/Q2 because session {brain.id} is a chat session: the"
            " pre-ruling pass, a job's, asks"
        )


ELSEWHERE = "example-elsewhere"

NOTES = "/work/Elsewhere/notes.md"


@pytest.mark.anyio
class TestAddItem:
    async def test_a_prose_item_is_added_through_its_route_with_what_it_was_given(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        brain: models.Session,
    ) -> None:
        result = await call(
            mcp_app,
            "add_item",
            {"item": {"kind": "notice", "title": "The lake", "for": "ada"}},
            meta={TOOL_USE_ID_META: "toolu_07"},
            path=STORE_PATH,
        )

        assert not result.isError
        [(request, answer)] = routes.calls
        assert (request.method, str(request.url)) == (
            "POST",
            f"{API_URL}/tools/pilot-store/items",
        )
        assert json.loads(request.content) == {
            "kind": "notice",
            "title": "The lake",
            "for": "ada",
        }
        assert request.headers["tool-use-id"] == "toolu_07"
        assert answer.status_code == 201
        assert result.structuredContent == answer.json()
        [item] = session.scalars(select(Item)).all()
        assert answer.json()["id"] == str(item.id)
        assert answer.json()["effect"] == "Added · Notice · The lake"

    async def test_a_work_items_claims_reach_its_route_as_given(
        self, mcp_app: Starlette, routes: ApiRoutes, brain: models.Session
    ) -> None:
        claim = f"{uuid.uuid4()}/A1"
        item = {
            "kind": "work",
            "title": "Rotating the CI token",
            "repo": "example/Example",
            "cwd": "/work/Example",
            "brief": "Rotate the CI token.",
            "claims": [claim],
        }

        result = await call(mcp_app, "add_item", {"item": item}, path=STORE_PATH)

        [(request, answer)] = routes.calls
        assert json.loads(request.content) == item
        assert answer.status_code == 404
        assert error_text(result) == _refusal(routes, "add_item")

    @pytest.mark.parametrize(
        ("item", "sent"),
        [
            (
                {
                    "kind": "card_wait",
                    "title": "SR-4 lands",
                    "cards": ["SR-4"],
                    "states": ["Done", "Won't fix"],
                    "step": "night",
                },
                None,
            ),
            (
                {
                    "kind": "timed_wait",
                    "title": "ESO refreshes",
                    "due_at": "2099-10-25T20:30:00+02:00",
                },
                {
                    "kind": "timed_wait",
                    "title": "ESO refreshes",
                    "due_at": "2099-10-25T20:30:00+02:00",
                },
            ),
        ],
        ids=["card-wait", "timed-wait"],
    )
    async def test_a_wait_is_added_through_its_route_as_given(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        brain: models.Session,
        item: dict[str, Any],
        sent: dict[str, Any] | None,
    ) -> None:
        if "step" in item:
            session.add(
                PlanTask(
                    project_id=brain.project_id,
                    task_id="night",
                    position=1,
                    title="The night shift",
                    status_code=TaskStatus.PENDING,
                )
            )
            session.commit()

        result = await call(mcp_app, "add_item", {"item": item}, path=STORE_PATH)

        assert not result.isError
        [(request, answer)] = routes.calls
        assert json.loads(request.content) == (item if sent is None else sent)
        assert answer.status_code == 201
        assert result.structuredContent == answer.json()
        [added] = session.scalars(select(Item)).all()
        assert added.kind_code == item["kind"]
        assert session.get(models.Wait, added.id) is not None

    async def test_a_work_items_researches_reach_its_route_as_given(
        self, mcp_app: Starlette, routes: ApiRoutes, brain: models.Session
    ) -> None:
        research = f"{uuid.uuid4()}/D1"
        item = {
            "kind": "work",
            "title": "Checking which hosts take the key",
            "repo": "example/Example",
            "cwd": "/work/Example",
            "brief": "Check which hosts take the new key.",
            "researches": [research],
        }

        result = await call(mcp_app, "add_item", {"item": item}, path=STORE_PATH)

        [(request, answer)] = routes.calls
        assert json.loads(request.content) == item
        assert answer.status_code == 404
        assert error_text(result) == _refusal(routes, "add_item")

    async def test_a_waits_refusal_is_the_routes(
        self, mcp_app: Starlette, routes: ApiRoutes, brain: models.Session
    ) -> None:
        result = await call(
            mcp_app,
            "add_item",
            {
                "item": {
                    "kind": "card_wait",
                    "title": "SR-4 lands",
                    "cards": [],
                    "states": ["Done"],
                }
            },
            path=STORE_PATH,
        )

        assert error_text(result) == _refusal(routes, "add_item")
        assert error_text(result) == (
            "Error executing tool add_item: Cannot add a card_wait item because"
            " its `cards` list is empty"
        )

    @pytest.mark.parametrize(
        ("week", "five_hour", "held"),
        [(0.95, 0.1, "week_halt"), (0.1, 0.8, "five_hour_halt")],
    )
    async def test_a_work_item_held_by_a_usage_halt_is_answered_held(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        brain: models.Session,
        placing: None,
        week: float,
        five_hour: float,
        held: str,
    ) -> None:
        now = datetime.now(UTC)
        reading = UsageReading(taken_at=now, received_at=now, stale=False)
        session.add(reading)
        session.flush()
        session.add_all(
            WindowShare(
                reading_id=reading.id,
                window_code=window,
                share=share,
                resets_at=now + timedelta(days=1),
            )
            for window, share in (
                (UsageWindow.SEVEN_DAY, week),
                (UsageWindow.FIVE_HOUR, five_hour),
            )
        )
        session.commit()
        item = {
            "kind": "work",
            "title": "Rotating the CI token",
            "repo": "example/Example",
            "cwd": "/work/Example",
            "brief": "Rotate the CI token.",
        }

        result = await call(mcp_app, "add_item", {"item": item}, path=STORE_PATH)

        assert not result.isError
        [(_, answer)] = routes.calls
        assert answer.status_code == 201
        assert result.structuredContent == answer.json()
        assert answer.json()["state"] == "held"
        assert answer.json()["held"] == held

    @pytest.mark.parametrize(
        "item",
        [
            {"kind": "opening", "title": "Camp"},
            {"kind": "timed_wait", "title": "Soon", "due_at": "2099-10-25T18:30:00"},
            {"kind": "card_wait", "title": "Soon", "cards": [""], "states": ["Done"]},
            {"kind": "notice", "title": "Camp", "attachments": ["camp.md"]},
            {"kind": "work", "repo": "Example"},
            {"kind": "work", "title": "Rotating", "claims": ["A1"]},
            {"kind": "work", "title": "Checking", "researches": ["D1"]},
        ],
    )
    async def test_an_item_outside_its_shape_is_refused_without_calling_the_api(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        brain: models.Session,
        item: dict[str, object],
    ) -> None:
        result = await call(mcp_app, "add_item", {"item": item}, path=STORE_PATH)

        assert result.isError
        assert routes.calls == []


@pytest.mark.anyio
class TestAttachOutsideMaterial:
    async def test_the_material_is_copied_through_its_route(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        brain: models.Session,
    ) -> None:
        fake_controller.add_environment(ELSEWHERE)
        fake_controller.put_file(ELSEWHERE, NOTES, b"# Camp notes\n")
        item = _decision(session, container, brain)

        result = await call(
            mcp_app,
            "attach_file",
            {"source": f"{ELSEWHERE}:{NOTES}", "to": str(item.id)},
            path=STORE_PATH,
        )

        assert not result.isError
        [(request, answer)] = routes.calls
        assert str(request.url) == f"{API_URL}/tools/pilot-store/attachments"
        assert json.loads(request.content) == {
            "source": f"{ELSEWHERE}:{NOTES}",
            "to": str(item.id),
        }
        assert answer.status_code == 201
        assert result.structuredContent == answer.json()
        [attachment] = session.scalars(select(Attachment)).all()
        assert answer.json() == {
            "ids": [str(attachment.id)],
            "effect": "Attached · Camp notes",
        }

    async def test_without_to_none_is_sent_and_it_is_the_routes_refusal(
        self, mcp_app: Starlette, routes: ApiRoutes, brain: models.Session
    ) -> None:
        result = await call(
            mcp_app, "attach_file", {"source": f"{ELSEWHERE}:{NOTES}"}, path=STORE_PATH
        )

        [(request, _)] = routes.calls
        assert json.loads(request.content) == {"source": f"{ELSEWHERE}:{NOTES}"}
        assert error_text(result) == _refusal(routes, "attach_file")

    @pytest.mark.parametrize("source", [NOTES, f"{ELSEWHERE}:notes.md", ""])
    async def test_a_source_that_is_no_source_is_refused_without_calling_the_api(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        brain: models.Session,
        source: str,
    ) -> None:
        result = await call(mcp_app, "attach_file", {"source": source}, path=STORE_PATH)

        assert result.isError
        assert routes.calls == []


@pytest.mark.anyio
class TestTheStoresBearer:
    async def test_a_work_items_bearer_is_the_routes_refusal(
        self, mcp_app: Starlette, routes: ApiRoutes, worker: models.Session
    ) -> None:
        result = await call(mcp_app, "finish", {}, path=STORE_PATH)

        assert routes.calls[-1][1].status_code == 403
        assert error_text(result) == (
            "Error executing tool finish: Cannot call pilot-store because session"
            f" {worker.id} is a work session, not a chat's or a job's"
        )


def _registered_document(
    session: DbSession,
    container: ServiceContainer,
    project: models.Project,
    environment: Environment,
) -> Item:
    """A document a worker registered, read at its run's end, committed."""
    worker = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code="work",
        cwd="/work/Example",
        token_hash="3" * 64,
        state_code=SessionState.IDLE,
    )
    session.add(worker)
    session.flush()
    documents = container.document_service()
    item = documents.register(project, worker, REGISTERED).item
    documents.publish_read(
        session.get_one(Document, item.id), REGISTERED_TEXT, worker.id
    )
    session.commit()
    return item


def _job(
    session: DbSession,
    container: ServiceContainer,
    project: models.Project,
    environment: Environment,
) -> models.Session:
    """The project's job, running, whose bearer is `TOKEN`, its turn in
    flight."""
    job = running_session(session, container, project, environment, kind="job")
    session.add(
        Turn(
            session_id=job.id, seq=1, message="Pre-rule.", started_at=datetime.now(UTC)
        )
    )
    session.commit()
    return job


def _make(container: ServiceContainer, **spec: Any) -> models.Project:
    spec.setdefault("members", ["ada"])
    return container.test_data_service().project(
        InventedProjectCreateSchema.model_validate(spec)
    )


async def _ask(app: Starlette, tool: str, arguments: dict[str, Any]) -> Any:
    """One call to `pilot-projects` as a session's entry makes it."""
    return await call(app, tool, arguments, PROJECTS_HEADERS, path=PROJECTS_PATH)


@pytest.mark.anyio
@pytest.mark.usefixtures("person")
class TestListProjects:
    async def test_the_projects_are_listed_through_the_list_route(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        token_endpoint: TokenEndpoint,
        container: ServiceContainer,
    ) -> None:
        draft = _make(container, state="draft")
        recipes = _make(container, name="Recipe box")
        bikes = _make(container, name="Bike log", paused=True)
        album = _make(container, name="Photo album", state="finished")
        _make(container, name="Old camp", archived=True)

        result = await _ask(projects_app, "list_projects", {})

        assert not result.isError
        assert result.structuredContent == {
            "projects": [
                {
                    "id": str(draft.id),
                    "folder": f"draft-{draft.number}",
                    "name": None,
                    "state": "draft",
                    "status": None,
                },
                {
                    "id": str(recipes.id),
                    "folder": recipes.slug,
                    "name": "Recipe box",
                    "state": "open",
                    "status": "idle",
                },
                {
                    "id": str(bikes.id),
                    "folder": bikes.slug,
                    "name": "Bike log",
                    "state": "open",
                    "status": "paused",
                },
                {
                    "id": str(album.id),
                    "folder": album.slug,
                    "name": "Photo album",
                    "state": "finished",
                    "status": None,
                },
            ]
        }
        [(request, answer)] = gated_routes.calls
        assert (request.method, str(request.url)) == (
            "GET",
            f"{API_URL}/api/projects?archived=false",
        )
        assert answer.status_code == 200

    async def test_archived_lists_the_archived_projects_alone(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        container: ServiceContainer,
    ) -> None:
        _make(container, name="Recipe box")
        camp = _make(container, name="Old camp", state="finished", archived=True)

        result = await _ask(projects_app, "list_projects", {"archived": True})

        assert [row["id"] for row in result.structuredContent["projects"]] == [
            str(camp.id)
        ]
        [(request, _)] = gated_routes.calls
        assert str(request.url) == f"{API_URL}/api/projects?archived=true"

    async def test_the_call_goes_under_the_minted_token_never_the_callers_bearer(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        token_endpoint: TokenEndpoint,
    ) -> None:
        await _ask(projects_app, "list_projects", {})

        [(request, answer)] = gated_routes.calls
        [minted] = token_endpoint.minted
        assert request.headers["authorization"] == f"Bearer {minted}"
        assert PROJECTS_TOKEN not in request.headers["authorization"]
        assert answer.status_code == 200

    async def test_one_token_serves_the_calls_while_it_lasts(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        token_endpoint: TokenEndpoint,
    ) -> None:
        async with mcp_session(projects_app, PROJECTS_HEADERS, PROJECTS_PATH) as (
            session,
            _,
        ):
            await session.call_tool("list_projects", {})
            await session.call_tool("list_projects", {"archived": True})

        [minted] = token_endpoint.minted
        assert [
            request.headers["authorization"] for request, _ in gated_routes.calls
        ] == [f"Bearer {minted}"] * 2

    async def test_the_caller_travels_on_as_its_two_headers(
        self, projects_app: Starlette, gated_routes: ApiRoutes
    ) -> None:
        await _ask(projects_app, "list_projects", {})

        [(request, _)] = gated_routes.calls
        assert (
            request.headers[ENVIRONMENT_HEADER],
            request.headers[SESSION_HEADER],
        ) == (CALLER_ENVIRONMENT, CALLER_SESSION)

    @pytest.mark.parametrize(
        "session_header", [{}, {SESSION_HEADER: ""}], ids=["absent", "empty"]
    )
    async def test_a_headless_callers_session_is_none(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        session_header: dict[str, str],
    ) -> None:
        headers = {
            "Authorization": PROJECTS_HEADERS["Authorization"],
            ENVIRONMENT_HEADER: CALLER_ENVIRONMENT,
            **session_header,
        }

        result = await call(
            projects_app, "list_projects", {}, headers, path=PROJECTS_PATH
        )

        assert not result.isError
        [(request, _)] = gated_routes.calls
        assert request.headers[ENVIRONMENT_HEADER] == CALLER_ENVIRONMENT
        assert SESSION_HEADER not in request.headers

    @pytest.mark.parametrize(
        ("roles", "signed_by_the_issuer", "refusal"),
        [
            ((), True, 403),
            (("editor",), False, 401),
        ],
        ids=["no-editor-role", "another-issuers-key"],
    )
    async def test_a_token_the_gate_refuses_is_the_tools_error(
        self,
        gated_routes: ApiRoutes,
        test_settings: Settings,
        generate_test_jwt: Any,
        roles: tuple[str, ...],
        signed_by_the_issuer: bool,
        refusal: int,
    ) -> None:
        """The call is behind the sign-in gate (F150.13): the door's token
        opens nothing there."""
        token = (
            service_token(
                test_settings, generate_test_jwt.private_key, "subject-fleet", roles
            )
            if signed_by_the_issuer
            else generate_test_jwt(roles=list(roles), invalid_signature=True)
        )
        app = app_with_projects(gated_routes, TokenEndpoint(lambda: token))

        result = await _ask(app, "list_projects", {})

        [(_, answer)] = gated_routes.calls
        assert answer.status_code == refusal
        assert error_text(result) == _refusal(gated_routes, "list_projects")


@pytest.mark.anyio
@pytest.mark.usefixtures("person")
class TestGetProject:
    async def test_the_head_is_read_through_its_route_without_the_plans_content(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        test_settings: Settings,
    ) -> None:
        container.test_data_service().person("ben", "Ben Example")
        recipes = _make(
            container,
            name="Recipe box",
            autopilot=True,
            members=["ben", "ada"],
            tasks=[
                {"id": "scope", "title": "Agree the scope", "status": "done"},
                {
                    "id": "build",
                    "title": "Build the card page",
                    "status": "in_progress",
                    "notes": [
                        {
                            "id": "card-layout",
                            "summary": "Cards are one column",
                            "content": "Ben chose one column.",
                        }
                    ],
                },
            ],
            notes=[
                {
                    "id": "print-view",
                    "summary": "A print view is the plan's question",
                    "content": "No task covers printing yet.",
                }
            ],
            open_items=2,
            environment_id=environment.id,
        )
        run = running_session(session, container, recipes, environment)
        work = session.get_one(Item, run.id)

        result = await _ask(projects_app, "get_project", {"project": recipes.slug})

        assert not result.isError
        assert result.structuredContent == {
            "id": str(recipes.id),
            "folder": recipes.slug,
            "name": "Recipe box",
            "state": "open",
            "archived": False,
            "status": "running",
            "autopilot": True,
            "members": ["ben", "ada"],
            "progress": {"done": 1, "total": 2, "in_progress": ["Build the card page"]},
            "running_work": [
                {
                    "seq": work.seq,
                    "title": "Refining the camp",
                    "environment": environment.name,
                }
            ],
            "open_items": 2,
            "url": f"{test_settings.baseurl}/projects/{recipes.slug}",
        }
        [(request, answer)] = gated_routes.calls
        assert (request.method, str(request.url)) == (
            "GET",
            f"{API_URL}/api/projects/head?address={recipes.slug}",
        )
        assert answer.status_code == 200
        assert {"tasks", "notes"} <= set(answer.json())

    async def test_a_work_item_that_waits_to_start_names_no_environment(
        self,
        projects_app: Starlette,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        recipes = _make(container, name="Recipe box")
        run = running_session(session, container, recipes, environment)
        run.state_code = SessionState.HELD
        run.environment_id = None
        session.commit()

        result = await _ask(projects_app, "get_project", {"project": recipes.slug})

        [work] = result.structuredContent["running_work"]
        assert (work["title"], work["environment"]) == ("Refining the camp", None)

    async def test_a_project_is_named_by_its_id(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        container: ServiceContainer,
    ) -> None:
        recipes = _make(container, name="Recipe box")

        result = await _ask(projects_app, "get_project", {"project": str(recipes.id)})

        assert result.structuredContent["folder"] == recipes.slug
        [(request, _)] = gated_routes.calls
        assert str(request.url) == f"{API_URL}/api/projects/head?address={recipes.id}"

    async def test_a_draft_is_named_by_its_folder(
        self,
        projects_app: Starlette,
        container: ServiceContainer,
        test_settings: Settings,
    ) -> None:
        draft = _make(container, state="draft")
        folder = f"draft-{draft.number}"

        result = await _ask(projects_app, "get_project", {"project": folder})

        head = result.structuredContent
        assert (head["id"], head["folder"], head["state"], head["status"]) == (
            str(draft.id),
            folder,
            "draft",
            None,
        )
        assert head["url"] == f"{test_settings.baseurl}/projects/{folder}"

    async def test_an_archived_projects_head_is_read(
        self, projects_app: Starlette, container: ServiceContainer
    ) -> None:
        camp = _make(container, name="Old camp", state="finished", archived=True)

        result = await _ask(projects_app, "get_project", {"project": camp.slug})

        head = result.structuredContent
        assert (head["id"], head["archived"]) == (str(camp.id), True)

    async def test_the_service_user_is_no_member(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        container: ServiceContainer,
    ) -> None:
        recipes = _make(container, name="Recipe box")

        result = await _ask(projects_app, "get_project", {"project": recipes.slug})

        assert result.structuredContent["members"] == ["ada"]
        [(_, answer)] = gated_routes.calls
        assert answer.json()["member"] is False

    async def test_a_project_nothing_names_is_the_routes_refusal(
        self, projects_app: Starlette, gated_routes: ApiRoutes
    ) -> None:
        result = await _ask(projects_app, "get_project", {"project": "recipe-box"})

        assert error_text(result) == (
            "Error executing tool get_project: Project recipe-box was not found"
        )
        [(_, answer)] = gated_routes.calls
        assert answer.status_code == 404

    async def test_no_project_is_refused_before_any_call(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        token_endpoint: TokenEndpoint,
    ) -> None:
        result = await _ask(projects_app, "get_project", {"project": ""})

        assert result.isError
        assert gated_routes.calls == []
        assert token_endpoint.forms == []
