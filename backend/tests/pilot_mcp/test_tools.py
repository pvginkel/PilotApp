"""`pilot-work`'s tools (F85, ruling D1, F85.3, F85.4, F85.5) and `pilot-store`'s
(F86) driven through a real MCP client to the API's routes: each one REST call
under the caller's bearer as it came, its answer the route's, and the route's
refusal the tool's error, its reason whole. And `pilot-projects`' (F150.5 to
F150.9), each one REST call to a route under `/api/`, behind the sign-in gate,
under the service user's token and never the caller's bearer (F150.13)."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any

import httpx
import pytest
from dependency_injector import providers
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession
from starlette.applications import Starlette

from app import models
from app.config import Settings
from app.engine.views import utc_time
from app.models import (
    Attachment,
    Block,
    Chat,
    Conversation,
    DebriefEntry,
    Document,
    Environment,
    Item,
    ItemAttachment,
    PlanTask,
    Project,
    ProjectMember,
    Turn,
    UsageReading,
    User,
    WindowShare,
    Work,
    WriterQuestion,
)
from app.models.reference import (
    AnswerChannel,
    AttachmentSource,
    ChatKind,
    CloseCause,
    ProjectState,
    SessionState,
    TaskStatus,
    TurnCause,
    UsageWindow,
)
from app.schemas.testing_record import InventedProjectCreateSchema
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerClient
from app.services.session_record_service import read_records
from pilot_mcp.api import (
    ENVIRONMENT_HEADER,
    POLL_SECONDS,
    SESSION_HEADER,
    WAIT_MS_DEFAULT,
    WAIT_MS_MAX,
)
from pilot_mcp.server import PROJECTS_PATH, STORE_PATH
from pilot_mcp.tools import STILL_RUNNING, TOOL_USE_ID_META
from tests.support.adoption import FIRST_MENUS
from tests.support.chats import ChatWriter, close_conversation, open_conversation
from tests.support.fake_controller import ServedFakeController
from tests.support.pilot_mcp import (
    API_URL,
    BEARER,
    CALLER_ENVIRONMENT,
    CALLER_SESSION,
    PROJECTS_HEADERS,
    PROJECTS_TOKEN,
    ApiRoutes,
    SteppedClock,
    TokenEndpoint,
    app_with_projects,
    call,
    error_text,
    http_client,
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

_WHY = "The reviewer found the migration's downgrade left the column"


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
                {
                    "code": "P1.code",
                    "label": "P1 · the client",
                    "state": "done",
                    "why": None,
                },
                {"code": "test", "label": "Test", "state": "pending", "why": None},
            ]
        }

    async def test_a_steps_why_reaches_its_route_and_is_answered(
        self, mcp_app: Starlette, routes: ApiRoutes, worker: models.Session
    ) -> None:
        """DB 327: a why on any step, sent as given; a step without one sends
        none."""
        steps = [_PUBLISHED[0], {**_PUBLISHED[1], "why": _WHY}]

        result = await call(mcp_app, "set_progress", {"steps": steps})

        assert not result.isError
        [(request, answer)] = routes.calls
        assert json.loads(request.content) == {"steps": steps}
        assert result.structuredContent == answer.json()
        assert [step["why"] for step in answer.json()["steps"]] == [None, _WHY]

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
            [{"code": "test", "label": "Test", "why": ""}],
            [{"code": "test", "label": "Test", "why": "w" * 121}],
            [{"code": f"s{n}", "label": "Step"} for n in range(101)],
            [{"code": "test", "label": "Test", "note": "x"}],
        ],
        ids=[
            "empty-code",
            "long-code",
            "empty-label",
            "long-label",
            "state",
            "empty-why",
            "long-why",
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


_ACCOUNTS = [
    {
        "section": "P1 · The client",
        "round": 1,
        "role": "code-writer",
        "duration": 2400,
        "words": "The client came out cleanly.",
    },
    {
        "section": "P1 · The client",
        "round": 2,
        "role": "code-reviewer",
        "duration": 600,
        "why": _WHY,
    },
    {
        "section": "Completion check",
        "round": 1,
        "role": "sweep",
        "duration": 0,
        "passed": True,
    },
]

_DEBRIEF = {"debrief": "It went well, if slowly.", "entries": _ACCOUNTS}

_SUBJECT = "Slice 058 · The search page"


def _entry(**overrides: object) -> dict[str, object]:
    return {
        "section": "P1 · The client",
        "round": 1,
        "role": "code-writer",
        "duration": 60,
        **overrides,
    }


@pytest.mark.anyio
class TestRegisterDebrief:
    async def test_the_debrief_is_stored_through_its_route_naming_no_call(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        worker: models.Session,
        session: DbSession,
    ) -> None:
        """The call records no effect, so its tool-use id goes nowhere."""
        result = await call(
            mcp_app,
            "register_debrief",
            _DEBRIEF,
            meta={TOOL_USE_ID_META: "toolu_01ABC"},
        )

        assert not result.isError
        [(request, answer)] = routes.calls
        assert (request.method, str(request.url)) == (
            "POST",
            f"{API_URL}/tools/pilot-work/debrief",
        )
        assert request.headers["authorization"] == BEARER["Authorization"]
        assert "tool-use-id" not in request.headers
        assert json.loads(request.content) == _DEBRIEF | {
            "subject": None,
            "completes": True,
        }
        assert answer.status_code == 201
        assert result.structuredContent == answer.json() == {"entries": 3}
        session.expire_all()
        assert session.get_one(Work, worker.id).debrief == _DEBRIEF["debrief"]
        assert [
            (entry.position, entry.role, entry.words, entry.passed, entry.why)
            for entry in session.scalars(
                select(DebriefEntry).order_by(DebriefEntry.position)
            )
        ] == [
            (1, "code-writer", "The client came out cleanly.", None, None),
            (2, "code-reviewer", None, None, _WHY),
            (3, "sweep", None, True, None),
        ]

    async def test_its_subject_and_whether_it_completes_it_reach_the_route(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        worker: models.Session,
        session: DbSession,
    ) -> None:
        """DB 608: the client posts both, so the route stores what the tool
        took."""
        arguments = _DEBRIEF | {"subject": _SUBJECT, "completes": False}

        result = await call(mcp_app, "register_debrief", arguments)

        assert not result.isError
        [(request, _)] = routes.calls
        assert json.loads(request.content) == arguments
        session.expire_all()
        work = session.get_one(Work, worker.id)
        assert (work.debrief_subject, work.debrief_completes) == (_SUBJECT, False)

    async def test_a_second_call_is_the_routes_refusal_its_reason_whole(
        self, mcp_app: Starlette, routes: ApiRoutes, worker: models.Session
    ) -> None:
        async with mcp_session(mcp_app) as (mcp, _):
            await mcp.call_tool("register_debrief", _DEBRIEF)
            result = await mcp.call_tool("register_debrief", _DEBRIEF)

        assert routes.calls[-1][1].status_code == 409
        assert error_text(result) == _refusal(routes, "register_debrief")
        assert error_text(result) == (
            f"Error executing tool register_debrief: Cannot register the debrief"
            f" of work item {worker.id} because it has its debrief already"
        )

    @pytest.mark.parametrize(
        "arguments",
        [
            {"debrief": "", "entries": [_entry()]},
            {"debrief": "   ", "entries": [_entry()]},
            {"debrief": "\n", "entries": [_entry()]},
            {"debrief": "d" * 16_001, "entries": [_entry()]},
            {"debrief": "Fine.", "entries": []},
            {"debrief": "Fine.", "entries": [_entry()] * 501},
            {"debrief": "Fine.", "entries": [_entry(section="")]},
            {"debrief": "Fine.", "entries": [_entry(section="s" * 121)]},
            {"debrief": "Fine.", "entries": [_entry(round=0)]},
            {"debrief": "Fine.", "entries": [_entry(round="2")]},
            {"debrief": "Fine.", "entries": [_entry(role="")]},
            {"debrief": "Fine.", "entries": [_entry(role="r" * 65)]},
            {"debrief": "Fine.", "entries": [_entry(duration=-1)]},
            {"debrief": "Fine.", "entries": [_entry(words="")]},
            {"debrief": "Fine.", "entries": [_entry(words="w" * 4_001)]},
            {"debrief": "Fine.", "entries": [_entry(passed="yes")]},
            {"debrief": "Fine.", "entries": [_entry(words="Fine.", passed=True)]},
            {"debrief": "Fine.", "entries": [_entry(why="")]},
            {"debrief": "Fine.", "entries": [_entry(why="w" * 121)]},
            {"debrief": "Fine.", "entries": [_entry(verdict="good")]},
            {"debrief": "Fine.", "entries": [_entry()], "subject": ""},
            {"debrief": "Fine.", "entries": [_entry()], "subject": "  "},
            {"debrief": "Fine.", "entries": [_entry()], "subject": "s" * 121},
            {"debrief": "Fine.", "entries": [_entry()], "completes": False},
            {"debrief": "Fine.", "entries": [_entry()], "completes": "no"},
        ],
        ids=[
            "empty-debrief",
            "blank-debrief",
            "newline-debrief",
            "long-debrief",
            "no-entries",
            "long-entries",
            "empty-section",
            "long-section",
            "round-0",
            "round-text",
            "empty-role",
            "long-role",
            "negative-duration",
            "empty-words",
            "long-words",
            "passed-text",
            "words-and-passed",
            "empty-why",
            "long-why",
            "extra-field",
            "empty-subject",
            "blank-subject",
            "long-subject",
            "not-completing-without-subject",
            "completes-text",
        ],
    )
    async def test_arguments_outside_the_limits_are_refused_without_calling_the_api(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        worker: models.Session,
        arguments: dict[str, object],
    ) -> None:
        result = await call(mcp_app, "register_debrief", arguments)

        assert error_text(result).startswith("Error executing tool register_debrief: ")
        assert routes.calls == []

    async def test_a_call_with_faults_names_each(
        self, mcp_app: Starlette, routes: ApiRoutes, worker: models.Session
    ) -> None:
        """DB 325: refused with the reason, each fault named, nothing stored."""
        arguments = {
            "debrief": "",
            "entries": [
                _entry(),
                _entry(role="r" * 65, duration=-1),
                _entry(words="Fine.", passed=True),
            ],
        }

        result = await call(mcp_app, "register_debrief", arguments)

        text = error_text(result)
        assert "4 validation errors" in text
        for fault in ("debrief", "entries.1.role", "entries.1.duration", "entries.2"):
            assert f"\n{fault}\n" in text
        assert "an entry gives at most one of words and passed" in text
        assert routes.calls == []

    async def test_completes_false_without_a_subject_says_why(
        self, mcp_app: Starlette, routes: ApiRoutes, worker: models.Session
    ) -> None:
        """DB 608: refused with the reason, nothing stored."""
        result = await call(
            mcp_app, "register_debrief", _DEBRIEF | {"completes": False}
        )

        assert error_text(result) == (
            "Error executing tool register_debrief: a debrief that does not"
            " complete names its subject"
        )
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
            "why": None,
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
                cause_code=TurnCause.BRIEF,
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
class TestCancelAsk:
    async def test_the_ask_is_called_off_for_the_person_through_its_route(
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
            "cancel_ask",
            {"item": str(item.id), "for": person.handle},
            meta={TOOL_USE_ID_META: "toolu_01"},
            path=STORE_PATH,
        )

        assert not result.isError
        assert result.structuredContent == {"effect": "Cancelled · Which tent?"}
        [(request, _)] = routes.calls
        assert str(request.url) == f"{API_URL}/tools/pilot-store/cancellations"
        assert json.loads(request.content) == {"item": str(item.id), "for": "ada"}
        assert request.headers["tool-use-id"] == "toolu_01"
        session.refresh(item)
        assert (item.done_cause_code, item.done_by_user_id) == ("cancelled", person.id)
        assert _effect(session, brain)["toolUseId"] == "toolu_01"

    async def test_without_for_it_is_refused_without_calling_the_api(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        container: ServiceContainer,
        brain: models.Session,
    ) -> None:
        item = _decision(session, container, brain)

        result = await call(
            mcp_app, "cancel_ask", {"item": str(item.id)}, path=STORE_PATH
        )

        assert "Field required" in error_text(result)
        assert routes.calls == []

    async def test_the_routes_refusal_is_the_tools_error_its_reason_whole(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        session: DbSession,
        container: ServiceContainer,
        person: models.User,
        brain: models.Session,
    ) -> None:
        project = session.get_one(models.Project, brain.project_id)
        notice = container.document_service().bear_item(
            project, "notice", "The lake is open", brain, "# The lake is open\n"
        )
        session.commit()

        result = await call(
            mcp_app,
            "cancel_ask",
            {"item": str(notice.id), "for": person.handle},
            path=STORE_PATH,
        )

        assert error_text(result) == _refusal(routes, "cancel_ask")
        assert error_text(result).endswith(
            "because a notice asks nothing, and takes its Read"
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
            Turn(
                session_id=run.id,
                seq=1,
                message="Go.",
                started_at=datetime.now(UTC),
                cause_code=TurnCause.BRIEF,
            )
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
        assert session.get_one(models.Item, run.id).done_at is None

    async def test_with_a_reason_the_work_item_is_closed_for_good(
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
            state_code=SessionState.STOPPED,
            turns=1,
            turn_started_at=datetime.now(UTC),
        )
        session.add(run)
        session.flush()
        session.add(
            Turn(
                session_id=run.id,
                seq=1,
                message="Go.",
                started_at=datetime.now(UTC),
                cause_code=TurnCause.BRIEF,
            )
        )
        container.record_service().place_work(project, run, "Pitching the tent")
        session.commit()
        reason = "Replaced by the pitching that takes the groundsheet in"

        result = await call(
            mcp_app,
            "stop_work",
            {"item": str(run.id), "reason": reason},
            path=STORE_PATH,
        )

        assert result.structuredContent == {"effect": "Closed · Pitching the tent"}
        [(request, _)] = routes.calls
        assert json.loads(request.content) == {"item": str(run.id), "reason": reason}
        item = session.get_one(models.Item, run.id, populate_existing=True)
        assert item.done_cause_code == "cancelled"
        assert session.get_one(models.Work, run.id).done_note == reason

    async def test_an_empty_reason_is_refused_before_the_api(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        brain: models.Session,
    ) -> None:
        result = await call(
            mcp_app,
            "stop_work",
            {"item": str(uuid.uuid4()), "reason": ""},
            path=STORE_PATH,
        )

        assert result.isError
        assert routes.calls == []


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

    async def test_a_work_items_environment_reaches_its_route_in_place_of_a_repository(
        self, mcp_app: Starlette, routes: ApiRoutes, brain: models.Session
    ) -> None:
        # F86.9. No controller is configured here: the route refuses it.
        item = {
            "kind": "work",
            "title": "Rotating the CI token",
            "environment": "example-example-1a2b3c",
            "cwd": "/work/Example",
            "brief": "Rotate the CI token.",
        }

        result = await call(mcp_app, "add_item", {"item": item}, path=STORE_PATH)

        [(request, answer)] = routes.calls
        assert json.loads(request.content) == item
        assert answer.status_code == 409
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
            {"kind": "work", "environment": "example example"},
            {"kind": "work", "environment": "example:/work"},
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
            session_id=job.id,
            seq=1,
            message="Pre-rule.",
            started_at=datetime.now(UTC),
            cause_code=TurnCause.BRIEF,
        )
    )
    session.commit()
    return job


def _make(container: ServiceContainer, **spec: Any) -> models.Project:
    spec.setdefault("members", ["ada"])
    return container.test_data_service().project(
        InventedProjectCreateSchema.model_validate(spec)
    )


def _adopted(container: ServiceContainer) -> models.Project:
    """The adopted Project of an invented group, as a publication that first
    names the group makes it, by the service user the surface calls as."""
    project_id = container.adoption_service().adopt(
        FIRST_MENUS, "The first menus", "The menus Ada wrote by hand."
    )
    return container.db_session().get_one(models.Project, project_id)


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

    async def test_an_adopted_project_is_listed_with_the_archived_ones_as_adopted(
        self, projects_app: Starlette, container: ServiceContainer
    ) -> None:
        """F128.2: an archived project in the state `adopted`."""
        _make(container, name="Recipe box")
        adopted = _adopted(container)

        archived, others = await _ask_each(
            projects_app, "list_projects", {"archived": True}, {}
        )

        assert not archived.isError
        (row,) = archived.structuredContent["projects"]
        assert (row["id"], row["name"], row["state"], row["status"]) == (
            str(adopted.id),
            "The first menus",
            "adopted",
            None,
        )
        assert row["folder"] == f"draft-{adopted.number}"
        assert [row["name"] for row in others.structuredContent["projects"]] == [
            "Recipe box"
        ]

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

    async def test_an_adopted_projects_head_is_read_as_an_archived_project_adopted(
        self, projects_app: Starlette, container: ServiceContainer
    ) -> None:
        adopted = _adopted(container)

        result = await _ask(projects_app, "get_project", {"project": str(adopted.id)})

        assert not result.isError
        head = result.structuredContent
        assert (head["id"], head["state"], head["archived"], head["status"]) == (
            str(adopted.id),
            "adopted",
            True,
            None,
        )
        assert (head["name"], head["members"]) == ("The first menus", [])

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


async def _ask_each(app: Starlette, tool: str, *asks: dict[str, Any]) -> list[Any]:
    """Calls to one tool of `pilot-projects`, one after another, in one
    session of the app, which serves one."""
    async with mcp_session(app, PROJECTS_HEADERS, PROJECTS_PATH) as (session, _):
        return [await session.call_tool(tool, arguments) for arguments in asks]


def _numbered(lines: list[str], first: int = 1) -> str:
    return "".join(f"{number}: {line}\n" for number, line in enumerate(lines, first))


def _canned(answer: dict[str, Any], token_endpoint: TokenEndpoint) -> Starlette:
    """The app with its projects surface, whose API answers every call with
    `answer`: a list longer than a suite's project holds."""
    return app_with_projects(
        httpx.MockTransport(lambda request: httpx.Response(200, json=answer)),
        token_endpoint,
    )


@pytest.mark.anyio
@pytest.mark.usefixtures("person")
class TestListItems:
    async def test_the_open_items_are_listed_with_no_empty_field(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        person: User,
    ) -> None:
        recipes = _make(
            container, name="Recipe box", open_items=2, environment_id=environment.id
        )
        run = running_session(session, container, recipes, environment)
        opening, first, second, work = session.scalars(
            select(Item).where(Item.project_id == recipes.id).order_by(Item.seq)
        )
        first.urgent = True
        first.for_user_id = person.id
        second.done_at = datetime.now(UTC)
        second.done_cause_code = "marked"
        session.commit()

        result = await _ask(projects_app, "list_items", {"project": recipes.slug})

        assert not result.isError
        assert result.structuredContent == {
            "items": [
                {
                    "seq": 1,
                    "kind": "opening",
                    "title": "Recipe box",
                    "path": f"{recipes.slug}/items/1-recipe-box.md",
                    "created_at": utc_time(opening.created_at),
                },
                {
                    "seq": 2,
                    "kind": "notice",
                    "title": "Notice 1",
                    "path": f"{recipes.slug}/items/2-notice-1.md",
                    "created_at": utc_time(first.created_at),
                    "for": "ada",
                    "urgent": True,
                },
                {
                    "seq": 4,
                    "kind": "work",
                    "title": "Refining the camp",
                    "created_at": utc_time(work.created_at),
                },
            ],
            "totalCount": 3,
            "limitHit": False,
        }
        assert work.id == run.id
        [(request, answer)] = gated_routes.calls
        assert (request.method, str(request.url)) == (
            "GET",
            f"{API_URL}/api/projects/items?address={recipes.slug}&open=true",
        )
        assert answer.status_code == 200

    async def test_open_false_lists_the_done_items_too_with_their_cause(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        recipes = _make(
            container, name="Recipe box", open_items=1, environment_id=environment.id
        )
        notice = session.scalars(
            select(Item).where(Item.project_id == recipes.id, Item.seq == 2)
        ).one()
        notice.done_at = datetime.now(UTC)
        notice.done_cause_code = "marked"
        session.commit()

        result = await _ask(
            projects_app, "list_items", {"project": recipes.slug, "open": False}
        )

        assert [
            (item["seq"], item.get("done_cause"))
            for item in result.structuredContent["items"]
        ] == [(1, None), (2, "marked")]
        [(request, _)] = gated_routes.calls
        assert request.url.params["open"] == "false"

    async def test_a_kind_lists_its_items_alone(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        container: ServiceContainer,
        environment: Environment,
    ) -> None:
        recipes = _make(
            container, name="Recipe box", open_items=2, environment_id=environment.id
        )

        result = await _ask(
            projects_app, "list_items", {"project": str(recipes.id), "kind": "notice"}
        )

        assert [item["seq"] for item in result.structuredContent["items"]] == [2, 3]
        assert result.structuredContent["totalCount"] == 2
        [(request, _)] = gated_routes.calls
        assert str(request.url) == (
            f"{API_URL}/api/projects/items?address={recipes.id}&open=true&kind=notice"
        )

    @pytest.mark.parametrize(
        ("page", "seqs", "more"),
        [
            ({"limit": 2}, [1, 2], True),
            ({"offset": 1, "limit": 2}, [2, 3], True),
            ({"offset": 4, "limit": 2}, [5, 6], False),
            ({"offset": 5}, [6], False),
            ({"offset": 6}, [], False),
            ({}, [1, 2, 3, 4, 5, 6], False),
        ],
    )
    async def test_the_items_are_paged_as_the_files_are(
        self,
        projects_app: Starlette,
        container: ServiceContainer,
        environment: Environment,
        page: dict[str, int],
        seqs: list[int],
        more: bool,
    ) -> None:
        recipes = _make(
            container, name="Recipe box", open_items=5, environment_id=environment.id
        )

        result = await _ask(
            projects_app, "list_items", {"project": recipes.slug} | page
        )

        listed = result.structuredContent
        assert [item["seq"] for item in listed["items"]] == seqs
        assert (listed["totalCount"], listed["limitHit"]) == (6, more)

    async def test_a_page_is_a_hundred_items_and_a_thousand_at_most(
        self, token_endpoint: TokenEndpoint
    ) -> None:
        rows = [
            {
                "seq": seq,
                "kind": "notice",
                "title": None,
                "path": None,
                "created_at": "2026-10-12T09:00:00Z",
                "done_cause": None,
                "for_handle": None,
                "urgent": False,
            }
            for seq in range(1, 1501)
        ]
        app = _canned({"items": rows}, token_endpoint)

        default, clamped = await _ask_each(
            app,
            "list_items",
            {"project": "recipe-box"},
            {"project": "recipe-box", "limit": 5000},
        )

        assert [
            len(page.structuredContent["items"]) for page in (default, clamped)
        ] == [
            100,
            1000,
        ]
        assert clamped.structuredContent["items"][-1] == {
            "seq": 1000,
            "kind": "notice",
            "created_at": "2026-10-12T09:00:00Z",
        }
        assert (
            clamped.structuredContent["totalCount"],
            clamped.structuredContent["limitHit"],
        ) == (1500, True)

    async def test_a_draft_is_named_by_its_folder(
        self,
        projects_app: Starlette,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        draft = _make(container, state="draft")
        run = running_session(session, container, draft, environment, kind="chat")
        container.document_service().bear_item(draft, "notice", "The palette", run)
        session.commit()
        folder = f"draft-{draft.number}"

        result = await _ask(projects_app, "list_items", {"project": folder})

        assert [item["path"] for item in result.structuredContent["items"]] == [
            f"{folder}/items/1-the-palette.md"
        ]

    async def test_a_project_nothing_names_is_the_routes_refusal(
        self, projects_app: Starlette
    ) -> None:
        result = await _ask(projects_app, "list_items", {"project": "recipe-box"})

        assert error_text(result) == (
            "Error executing tool list_items: Project recipe-box was not found"
        )

    @pytest.mark.parametrize(
        "arguments",
        [
            {"project": ""},
            {"project": "recipe-box", "kind": "memo"},
            {"project": "recipe-box", "limit": 0},
            {"project": "recipe-box", "offset": -1},
        ],
    )
    async def test_an_argument_out_of_its_values_is_refused_before_any_call(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        arguments: dict[str, Any],
    ) -> None:
        result = await _ask(projects_app, "list_items", arguments)

        assert result.isError
        assert gated_routes.calls == []


@pytest.fixture
def recipes(container: ServiceContainer, session: DbSession) -> models.Project:
    """An open project with an attachment that is no text, committed."""
    project = _make(container, name="Recipe box")
    container.attachment_store().put(
        Attachment(
            project_id=project.id,
            batch=1,
            title="The badge",
            filename="badge.png",
            content_type="image/png",
            source_code=AttachmentSource.DRAFT,
            copied_at=datetime.now(UTC),
        ),
        b"\x89PNG\r\n\x1a\n",
    )
    session.commit()
    return project


@pytest.mark.anyio
@pytest.mark.usefixtures("person")
class TestListFiles:
    async def test_the_root_is_listed_without_a_path(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        container: ServiceContainer,
        recipes: models.Project,
    ) -> None:
        draft = _make(container, state="draft")
        _make(container, name="Old camp", state="finished", archived=True)

        result = await _ask(projects_app, "list_files", {})

        assert not result.isError
        assert result.structuredContent == {
            "files": [
                {"path": f"draft-{draft.number}/", "isDirectory": True},
                {"path": f"{recipes.slug}/", "isDirectory": True},
                {"path": "reference.json", "isDirectory": False},
            ],
            "totalCount": 3,
            "limitHit": False,
        }
        [(request, answer)] = gated_routes.calls
        assert (request.method, str(request.url)) == (
            "GET",
            f"{API_URL}/api/tree/entries?path=",
        )
        assert answer.status_code == 200

    async def test_a_listed_folder_is_listed_folders_first(
        self, projects_app: Starlette, recipes: models.Project
    ) -> None:
        result = await _ask(projects_app, "list_files", {"path": f"{recipes.slug}/"})

        assert result.structuredContent == {
            "files": [
                {"path": f"{recipes.slug}/attachments/", "isDirectory": True},
                {"path": f"{recipes.slug}/items/", "isDirectory": True},
                {"path": f"{recipes.slug}/chat.md", "isDirectory": False},
                {"path": f"{recipes.slug}/handbook.md", "isDirectory": False},
                {"path": f"{recipes.slug}/plan.json", "isDirectory": False},
                {"path": f"{recipes.slug}/project.md", "isDirectory": False},
                {"path": f"{recipes.slug}/timeline.json", "isDirectory": False},
            ],
            "totalCount": 7,
            "limitHit": False,
        }

    @pytest.mark.parametrize(
        ("page", "names", "more"),
        [
            ({"limit": 3}, ["attachments/", "items/", "chat.md"], True),
            ({"offset": 2, "limit": 2}, ["chat.md", "handbook.md"], True),
            ({"offset": 5, "limit": 2}, ["project.md", "timeline.json"], False),
            ({"offset": 7}, [], False),
        ],
    )
    async def test_a_listing_is_paged_by_offset_and_limit(
        self,
        projects_app: Starlette,
        recipes: models.Project,
        page: dict[str, int],
        names: list[str],
        more: bool,
    ) -> None:
        result = await _ask(projects_app, "list_files", {"path": recipes.slug} | page)

        listed = result.structuredContent
        assert [entry["path"] for entry in listed["files"]] == [
            f"{recipes.slug}/{name}" for name in names
        ]
        assert (listed["totalCount"], listed["limitHit"]) == (7, more)

    async def test_a_page_is_a_hundred_entries_and_a_thousand_at_most(
        self, token_endpoint: TokenEndpoint
    ) -> None:
        entries = [
            {"path": f"recipe-box/items/{n}-a.md", "is_directory": False}
            for n in range(1500)
        ]
        app = _canned({"entries": entries}, token_endpoint)

        default, clamped = await _ask_each(
            app,
            "list_files",
            {"path": "recipe-box/items"},
            {"path": "recipe-box/items", "limit": 1001},
        )

        assert [
            len(page.structuredContent["files"]) for page in (default, clamped)
        ] == [
            100,
            1000,
        ]
        assert (
            clamped.structuredContent["totalCount"],
            clamped.structuredContent["limitHit"],
        ) == (1500, True)

    @pytest.mark.parametrize(
        ("path", "refusal"),
        [
            ("bike-log", "Folder 'bike-log' was not found [not-found]"),
            (
                "reference.json",
                "Cannot list 'reference.json' because it is a file, not a folder"
                " [not-a-directory]",
            ),
            (
                "/work",
                "Path '/work' is outside the projects' files: a path runs from"
                " their root, as `<folder>/timeline.json` does, never from `/` and"
                " never above it [path-outside-projects]",
            ),
        ],
    )
    async def test_a_path_that_is_no_folder_is_the_routes_refusal(
        self, projects_app: Starlette, recipes: models.Project, path: str, refusal: str
    ) -> None:
        result = await _ask(projects_app, "list_files", {"path": path})

        assert error_text(result) == f"Error executing tool list_files: {refusal}"

    async def test_an_archived_projects_folder_is_not_listed(
        self, projects_app: Starlette, container: ServiceContainer
    ) -> None:
        camp = _make(container, name="Old camp", state="finished", archived=True)

        result = await _ask(projects_app, "list_files", {"path": camp.slug})

        assert error_text(result) == (
            f"Error executing tool list_files: Folder '{camp.slug}' was not found"
            " [not-found]"
        )

    async def test_the_tool_takes_no_environment(
        self, projects_app: Starlette, gated_routes: ApiRoutes
    ) -> None:
        result = await _ask(projects_app, "list_files", {"env": "example-1a2b3c"})

        assert not result.isError
        [(request, _)] = gated_routes.calls
        assert dict(request.url.params) == {"path": ""}
        assert request.headers[ENVIRONMENT_HEADER] == CALLER_ENVIRONMENT


@pytest.mark.anyio
@pytest.mark.usefixtures("person")
class TestFindFiles:
    async def test_the_files_a_glob_matches_are_found_in_path_order(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        container: ServiceContainer,
        recipes: models.Project,
    ) -> None:
        _make(container, name="Old camp", state="finished", archived=True)

        result = await _ask(
            projects_app, "find_files", {"path_pattern": "**/{plan,timeline}.json"}
        )

        assert not result.isError
        assert result.structuredContent == {
            "pattern": "**/{plan,timeline}.json",
            "files": [f"{recipes.slug}/plan.json", f"{recipes.slug}/timeline.json"],
            "totalCount": 2,
            "limitHit": False,
        }
        [(request, answer)] = gated_routes.calls
        assert (request.method, request.url.path, dict(request.url.params)) == (
            "GET",
            "/api/tree/matches",
            {"pattern": "**/{plan,timeline}.json"},
        )
        assert answer.status_code == 200

    async def test_the_matches_are_paged_by_offset_and_limit(
        self, projects_app: Starlette, recipes: models.Project
    ) -> None:
        pattern = f"{recipes.slug}/*"

        first, last = await _ask_each(
            projects_app,
            "find_files",
            {"path_pattern": pattern, "limit": 2},
            {"path_pattern": pattern, "offset": 3, "limit": 2},
        )

        assert first.structuredContent == {
            "pattern": pattern,
            "files": [f"{recipes.slug}/chat.md", f"{recipes.slug}/handbook.md"],
            "totalCount": 5,
            "limitHit": True,
        }
        assert last.structuredContent == {
            "pattern": pattern,
            "files": [f"{recipes.slug}/project.md", f"{recipes.slug}/timeline.json"],
            "totalCount": 5,
            "limitHit": False,
        }

    async def test_a_page_is_fifty_files_and_two_hundred_at_most(
        self, token_endpoint: TokenEndpoint
    ) -> None:
        paths = [f"recipe-box/items/{n}-a.md" for n in range(300)]
        app = _canned({"paths": paths}, token_endpoint)

        default, clamped = await _ask_each(
            app,
            "find_files",
            {"path_pattern": "**"},
            {"path_pattern": "**", "limit": 201},
        )

        assert [
            len(page.structuredContent["files"]) for page in (default, clamped)
        ] == [
            50,
            200,
        ]
        assert (
            clamped.structuredContent["totalCount"],
            clamped.structuredContent["limitHit"],
        ) == (300, True)

    @pytest.mark.parametrize(
        ("pattern", "refusal"),
        [
            (
                "**/[ab].md",
                "Invalid glob pattern: character class '[' at index 3 is not"
                " supported (supported: *, **, ?, {a,b}) [validation-error]",
            ),
            (
                "/work/**",
                "Pattern '/work/**' is outside the projects' files: a path runs"
                " from their root, as `<folder>/timeline.json` does, never from"
                " `/` and never above it [path-outside-projects]",
            ),
        ],
    )
    async def test_a_pattern_the_search_does_not_take_is_the_routes_refusal(
        self, projects_app: Starlette, pattern: str, refusal: str
    ) -> None:
        result = await _ask(projects_app, "find_files", {"path_pattern": pattern})

        assert error_text(result) == f"Error executing tool find_files: {refusal}"

    async def test_a_glob_that_matches_nothing_finds_no_file(
        self, projects_app: Starlette, recipes: models.Project
    ) -> None:
        result = await _ask(projects_app, "find_files", {"path_pattern": "*.md"})

        assert result.structuredContent == {
            "pattern": "*.md",
            "files": [],
            "totalCount": 0,
            "limitHit": False,
        }


@pytest.mark.anyio
@pytest.mark.usefixtures("person")
class TestReadFile:
    async def test_a_file_is_read_whole_with_its_lines_numbered(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        container: ServiceContainer,
        recipes: models.Project,
    ) -> None:
        path = f"{recipes.slug}/timeline.json"
        rendering = container.view_service().timeline(recipes)

        result = await _ask(projects_app, "read_file", {"path": path})

        assert not result.isError
        lines = rendering.text.splitlines()
        assert result.structuredContent == {
            "content": _numbered(lines),
            "sha256": rendering.hash,
            "totalCount": len(lines),
            "limitHit": False,
            "lineCut": False,
        }
        [(request, answer)] = gated_routes.calls
        assert (request.method, request.url.path, dict(request.url.params)) == (
            "GET",
            "/api/tree/text",
            {"path": path},
        )
        assert answer.status_code == 200

    async def test_a_range_and_a_tail_read_their_lines(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        container: ServiceContainer,
        recipes: models.Project,
    ) -> None:
        path = f"{recipes.slug}/timeline.json"
        lines = container.view_service().timeline(recipes).text.splitlines()

        ranged, tail = await _ask_each(
            projects_app,
            "read_file",
            {"path": path, "start_line": 3, "end_line": 5},
            {"path": path, "tail_lines": 2},
        )

        assert ranged.structuredContent["content"] == _numbered(lines[2:5], 3)
        assert tail.structuredContent["content"] == _numbered(
            lines[-2:], len(lines) - 1
        )
        assert [dict(request.url.params) for request, _ in gated_routes.calls] == [
            {"path": path, "start_line": "3", "end_line": "5"},
            {"path": path, "tail_lines": "2"},
        ]

    async def test_a_long_file_is_cut_at_the_line_limit(
        self,
        projects_app: Starlette,
        container: ServiceContainer,
        session: DbSession,
        recipes: models.Project,
    ) -> None:
        lines = [f"line {n}" for n in range(1, 2502)]
        container.attachment_store().put(
            Attachment(
                project_id=recipes.id,
                batch=1,
                title="The log",
                filename="log.txt",
                content_type="text/plain",
                source_code=AttachmentSource.DRAFT,
                copied_at=datetime.now(UTC),
            ),
            "".join(f"{line}\n" for line in lines).encode(),
        )
        session.commit()
        path = f"{recipes.slug}/attachments/1/log.txt"

        ranged, tail = await _ask_each(
            projects_app,
            "read_file",
            {"path": path, "start_line": 1},
            {"path": path, "tail_lines": 2501},
        )

        assert ranged.structuredContent | {"sha256": ""} == {
            "content": _numbered(lines[:2000]),
            "sha256": "",
            "totalCount": 2501,
            "limitHit": True,
            "lineCut": False,
        }
        assert tail.structuredContent["content"] == _numbered(lines[501:], 502)
        assert tail.structuredContent["limitHit"] is True

    @pytest.mark.parametrize(
        ("path", "refusal"),
        [
            (
                "{folder}/attachments/1/badge.png",
                "Cannot read '{folder}/attachments/1/badge.png' because it is not"
                " UTF-8 text, and a read answers text alone [not-text]",
            ),
            (
                "{folder}/items",
                "Cannot read '{folder}/items' because it is a folder, not a file"
                " [not-a-file]",
            ),
            (
                "{folder}/notes.md",
                "File '{folder}/notes.md' was not found [not-found]",
            ),
            (
                "/work/PilotProjects/{folder}/project.md",
                "Path '/work/PilotProjects/{folder}/project.md' is outside the"
                " projects' files: a path runs from their root, as"
                " `<folder>/timeline.json` does, never from `/` and never above it"
                " [path-outside-projects]",
            ),
        ],
    )
    async def test_a_path_that_is_no_text_file_is_the_routes_refusal(
        self, projects_app: Starlette, recipes: models.Project, path: str, refusal: str
    ) -> None:
        result = await _ask(
            projects_app, "read_file", {"path": path.format(folder=recipes.slug)}
        )

        assert error_text(result) == (
            f"Error executing tool read_file: {refusal.format(folder=recipes.slug)}"
        )

    async def test_a_tail_with_a_range_is_the_routes_refusal(
        self, projects_app: Starlette
    ) -> None:
        result = await _ask(
            projects_app,
            "read_file",
            {"path": "reference.json", "start_line": 1, "tail_lines": 2},
        )

        assert error_text(result) == (
            "Error executing tool read_file: Pass either `tail_lines` or"
            " `start_line` and `end_line`, not both: a tail is the file's last"
            " lines, a range the lines between two numbers"
        )

    async def test_an_archived_projects_file_is_not_read(
        self, projects_app: Starlette, container: ServiceContainer
    ) -> None:
        camp = _make(container, name="Old camp", state="finished", archived=True)

        result = await _ask(
            projects_app, "read_file", {"path": f"{camp.slug}/project.md"}
        )

        assert error_text(result) == (
            "Error executing tool read_file: File"
            f" '{camp.slug}/project.md' was not found [not-found]"
        )

    @pytest.mark.parametrize(
        "arguments",
        [
            {},
            {"path": ""},
            {"path": "reference.json", "start_line": 0},
            {"path": "reference.json", "end_line": 0},
            {"path": "reference.json", "tail_lines": 0},
        ],
    )
    async def test_an_argument_out_of_its_values_is_refused_before_any_call(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        arguments: dict[str, Any],
    ) -> None:
        result = await _ask(projects_app, "read_file", arguments)

        assert result.isError
        assert gated_routes.calls == []


BRIEF = "Sort the inbox.\n\nStart with the oldest card."


def _member_handles(session: DbSession, project: Project) -> list[str]:
    return list(
        session.scalars(
            select(User.handle)
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .where(ProjectMember.project_id == project.id)
            .order_by(ProjectMember.id)
        )
    )


@pytest.mark.anyio
@pytest.mark.usefixtures("person", "gated_starts")
class TestStartProject:
    """`start_project`, attended (F150.9; V18 to V20): the plus's create,
    called as the service user through the sign-in gate. With
    `tests/api/test_projects.py`, `TestCreateProjectByCall`, the successor of
    the refusal `tests/test_service_user.py` pinned under a bearer token."""

    async def test_the_draft_is_started_by_one_post_to_the_pluss_create_under_the_minted_token(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        token_endpoint: TokenEndpoint,
        session: DbSession,
        service_user: User,
        test_settings: Settings,
    ) -> None:
        result = await _ask(
            projects_app,
            "start_project",
            {"brief": BRIEF, "title": "Sort the inbox", "for": "ada"},
        )

        assert not result.isError, result
        [(request, answer)] = gated_routes.calls
        [minted] = token_endpoint.minted
        assert (request.method, str(request.url)) == (
            "POST",
            f"{API_URL}/api/projects",
        )
        assert json.loads(request.content) == {
            "words": BRIEF,
            "title": "Sort the inbox",
            "for": "ada",
        }
        assert request.headers["authorization"] == f"Bearer {minted}"
        assert (
            request.headers[ENVIRONMENT_HEADER],
            request.headers[SESSION_HEADER],
        ) == (CALLER_ENVIRONMENT, CALLER_SESSION)
        assert answer.status_code == 201
        draft = session.scalars(select(Project)).one()
        assert result.structuredContent == {
            "id": str(draft.id),
            "folder": f"draft-{draft.number}",
            "url": f"{test_settings.baseurl}/projects/draft-{draft.number}",
        }
        assert (draft.state_code, draft.name, draft.created_by_user_id) == (
            ProjectState.DRAFT,
            "Sort the inbox",
            service_user.id,
        )
        assert _member_handles(session, draft) == ["ada"]
        (chat,) = session.scalars(select(Chat)).all()
        assert (chat.project_id, chat.kind_code) == (draft.id, ChatKind.DEFINITION)
        turn = session.scalars(select(Turn)).one()
        assert (turn.session_id, turn.author_user_id, turn.words) == (
            chat.id,
            service_user.id,
            BRIEF,
        )
        assert turn.message.endswith(
            f"Started by a call from {CALLER_ENVIRONMENT}, for ada.\n"
            "Attachments so far: none.\n\n"
            "The message:\n"
            f"{BRIEF}"
        )

    async def test_a_brief_alone_sends_no_title_and_no_for(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        session: DbSession,
        container: ServiceContainer,
        person: User,
    ) -> None:
        container.people_service().switch_join_calls(person, False)

        result = await _ask(projects_app, "start_project", {"brief": BRIEF})

        assert not result.isError, result
        [(request, _)] = gated_routes.calls
        assert json.loads(request.content) == {"words": BRIEF}
        draft = session.scalars(select(Project)).one()
        assert (draft.name, _member_handles(session, draft)) == (None, [])
        assert session.scalars(select(Turn.words)).one() == BRIEF

    async def test_the_draft_it_answers_is_read_by_its_id_and_its_folder(
        self, projects_app: Starlette, session: DbSession
    ) -> None:
        async with mcp_session(projects_app, PROJECTS_HEADERS, PROJECTS_PATH) as (
            calls,
            _,
        ):
            started = (
                await calls.call_tool(
                    "start_project", {"brief": BRIEF, "title": "Sort the inbox"}
                )
            ).structuredContent
            head = await calls.call_tool("get_project", {"project": started["id"]})
            text = await calls.call_tool(
                "read_file", {"path": f"{started['folder']}/project.md"}
            )

        assert (
            head.structuredContent["id"],
            head.structuredContent["folder"],
            head.structuredContent["state"],
            head.structuredContent["members"],
            head.structuredContent["url"],
        ) == (started["id"], started["folder"], "draft", ["ada"], started["url"])
        assert text.structuredContent["content"] == _numbered(
            ["---", "title: Sort the inbox", "---"]
        )

    async def test_a_for_that_names_no_person_is_the_routes_refusal(
        self, projects_app: Starlette, gated_routes: ApiRoutes, session: DbSession
    ) -> None:
        result = await _ask(
            projects_app, "start_project", {"brief": BRIEF, "for": "nobody"}
        )

        assert error_text(result) == (
            "Error executing tool start_project: Person nobody was not found"
        )
        [(_, answer)] = gated_routes.calls
        assert answer.status_code == 404
        assert session.scalars(select(Project)).all() == []

    @pytest.mark.parametrize(
        "arguments",
        [
            {},
            {"brief": " \n"},
            {"brief": BRIEF, "title": " "},
            {"brief": BRIEF, "title": "Sort\nthe inbox"},
            {"brief": BRIEF, "for": ""},
        ],
    )
    async def test_no_brief_or_a_title_or_for_that_is_none_is_refused_before_any_call(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        token_endpoint: TokenEndpoint,
        arguments: dict[str, Any],
    ) -> None:
        result = await _ask(projects_app, "start_project", arguments)

        assert result.isError
        assert gated_routes.calls == []
        assert token_endpoint.forms == []


@pytest.mark.anyio
@pytest.mark.usefixtures("person")
@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("list_items", {"project": "recipe-box"}),
        ("list_conversations", {}),
        ("get_conversation", {"conversation": str(uuid.UUID(int=7))}),
        ("list_files", {}),
        ("find_files", {"path_pattern": "**"}),
        ("read_file", {"path": "reference.json"}),
    ],
)
async def test_each_read_is_one_call_under_the_minted_token_with_the_callers_headers(
    projects_app: Starlette,
    gated_routes: ApiRoutes,
    token_endpoint: TokenEndpoint,
    tool: str,
    arguments: dict[str, Any],
) -> None:
    await _ask(projects_app, tool, arguments)

    [(request, _)] = gated_routes.calls
    [minted] = token_endpoint.minted
    assert request.method == "GET"
    assert request.url.path.startswith("/api/")
    assert request.headers["authorization"] == f"Bearer {minted}"
    assert (request.headers[ENVIRONMENT_HEADER], request.headers[SESSION_HEADER]) == (
        CALLER_ENVIRONMENT,
        CALLER_SESSION,
    )


STOCK = "How is the stock going?"
AUTOMATION = "example-automation-9f8e7d"

ANOTHERS_HEADERS = PROJECTS_HEADERS | {
    ENVIRONMENT_HEADER: AUTOMATION,
    SESSION_HEADER: "nightly",
}
"""What a session in another environment sends."""

NO_ENVIRONMENT = {"Authorization": PROJECTS_HEADERS["Authorization"]}
"""What an entry that names no caller sends."""


@pytest.fixture
def soup(container: ServiceContainer, session: DbSession) -> models.Project:
    """An open project, committed."""
    project = _make(container, name="Soup club")
    session.commit()
    return project


def _talk(
    db: DbSession,
    project: models.Project,
    opener: User,
    environment: str = CALLER_ENVIRONMENT,
    **spec: Any,
) -> models.Session:
    """A conversation `opener` opened from `environment`, its first turn
    ended. Committed, so that a refused call's rollback keeps it."""
    caller = db.get(Environment, environment)
    if caller is None:
        caller = Environment(id=environment, name=environment, exempt=False)
        db.add(caller)
        db.flush()
    run = open_conversation(db, project, caller, opener=opener, **spec)
    db.commit()
    return run


async def _ask_as(
    routes: ApiRoutes,
    endpoint: TokenEndpoint,
    headers: dict[str, str],
    tool: str,
    arguments: dict[str, Any],
) -> Any:
    """One call to `pilot-projects` from the caller `headers` names, through
    an app of its own on the same API: an app serves one session."""
    return await call(
        app_with_projects(routes, endpoint),
        tool,
        arguments,
        headers,
        path=PROJECTS_PATH,
    )


def _stamp(at: datetime) -> str:
    """A time as the API writes it."""
    return at.isoformat().replace("+00:00", "Z")


def _standing(db: DbSession, run_id: uuid.UUID, **moved: Any) -> dict[str, Any]:
    """The conversation as the surface answers it, read from the rows."""
    run = db.get_one(models.Session, run_id, populate_existing=True)
    row = db.get_one(Conversation, run_id, populate_existing=True)
    return {
        "id": str(run_id),
        "project": str(row.project_id),
        "environment": row.caller_environment_id,
        "session": row.caller_session,
        "opened_at": _stamp(run.created_at),
        "closed_at": None if row.closed_at is None else _stamp(row.closed_at),
        "close_cause": row.close_cause_code,
        "turns": run.turns,
        "running": False,
    } | moved


def _never_was(tool: str, conversation_id: uuid.UUID) -> str:
    """The tool's error for a conversation no id names."""
    return f"Error executing tool {tool}: Conversation {conversation_id} was not found"


@pytest.mark.anyio
@pytest.mark.usefixtures("person", "gated_starts")
class TestStartConversation:
    """`start_conversation` (F150.10 to F150.12; V01, V04, V18): the
    conversation's opening, called as the service user through the sign-in
    gate, its second write."""

    async def test_the_conversation_is_opened_by_one_post_under_the_minted_token(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        token_endpoint: TokenEndpoint,
        session: DbSession,
        service_user: User,
        soup: models.Project,
    ) -> None:
        result = await _ask(
            projects_app, "start_conversation", {"project": soup.slug, "text": STOCK}
        )

        assert not result.isError, result
        [(request, answer)] = gated_routes.calls
        [minted] = token_endpoint.minted
        assert (request.method, str(request.url)) == (
            "POST",
            f"{API_URL}/api/conversations",
        )
        assert json.loads(request.content) == {"address": soup.slug, "words": STOCK}
        assert request.headers["authorization"] == f"Bearer {minted}"
        assert (
            request.headers[ENVIRONMENT_HEADER],
            request.headers[SESSION_HEADER],
        ) == (CALLER_ENVIRONMENT, CALLER_SESSION)
        assert answer.status_code == 201
        row = session.scalars(select(Conversation)).one()
        assert (row.project_id, row.caller_environment_id, row.caller_session) == (
            soup.id,
            CALLER_ENVIRONMENT,
            CALLER_SESSION,
        )
        assert result.structuredContent == _standing(session, row.id, running=True)
        assert result.structuredContent["turns"] == 1
        turn = session.scalars(select(Turn)).one()
        assert (turn.session_id, turn.author_user_id, turn.words) == (
            row.id,
            service_user.id,
            STOCK,
        )
        assert session.get_one(Environment, CALLER_ENVIRONMENT).name == (
            CALLER_ENVIRONMENT
        )
        assert session.scalars(select(Chat)).all() == []

    async def test_the_project_is_named_by_its_id_too(
        self, projects_app: Starlette, session: DbSession, soup: models.Project
    ) -> None:
        result = await _ask(
            projects_app, "start_conversation", {"project": str(soup.id), "text": STOCK}
        )

        assert not result.isError, result
        assert result.structuredContent["project"] == str(soup.id)

    async def test_a_later_session_there_finds_it_and_no_other_environment_reaches_it(
        self,
        projects_app: Starlette,
        session: DbSession,
        soup: models.Project,
        gated_routes: ApiRoutes,
        token_endpoint: TokenEndpoint,
    ) -> None:
        started = await _ask(
            projects_app, "start_conversation", {"project": soup.slug, "text": STOCK}
        )
        opened = started.structuredContent
        later = PROJECTS_HEADERS | {SESSION_HEADER: "the-next-morning"}

        found = await _ask_as(
            gated_routes, token_endpoint, later, "list_conversations", {}
        )
        read = await _ask_as(
            gated_routes,
            token_endpoint,
            later,
            "get_conversation",
            {"conversation": opened["id"]},
        )
        elsewhere = await _ask_as(
            gated_routes, token_endpoint, ANOTHERS_HEADERS, "list_conversations", {}
        )
        refused = await _ask_as(
            gated_routes,
            token_endpoint,
            ANOTHERS_HEADERS,
            "get_conversation",
            {"conversation": opened["id"]},
        )

        assert found.structuredContent == {"conversations": [opened]}
        assert read.structuredContent == opened
        assert read.structuredContent["session"] == CALLER_SESSION
        assert elsewhere.structuredContent == {"conversations": []}
        assert error_text(refused) == _never_was(
            "get_conversation", uuid.UUID(opened["id"])
        )

    async def test_a_draft_takes_none_and_is_the_routes_refusal(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        session: DbSession,
        container: ServiceContainer,
    ) -> None:
        draft = _make(container, state="draft")
        session.commit()

        result = await _ask(
            projects_app,
            "start_conversation",
            {"project": f"draft-{draft.number}", "text": STOCK},
        )

        assert error_text(result) == (
            "Error executing tool start_conversation: Cannot open a conversation"
            " with Pilot in the untitled project because its project is a draft"
        )
        assert error_text(result) == _refusal(gated_routes, "start_conversation")
        assert session.scalars(select(Conversation)).all() == []

    async def test_a_project_nothing_names_is_the_routes_refusal(
        self, projects_app: Starlette, gated_routes: ApiRoutes
    ) -> None:
        result = await _ask(
            projects_app, "start_conversation", {"project": "no-such", "text": STOCK}
        )

        assert error_text(result) == (
            "Error executing tool start_conversation: Project no-such was not found"
        )

    async def test_an_entry_that_sends_no_environment_opens_none(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        session: DbSession,
        soup: models.Project,
        token_endpoint: TokenEndpoint,
    ) -> None:
        result = await _ask_as(
            gated_routes,
            token_endpoint,
            NO_ENVIRONMENT,
            "start_conversation",
            {"project": soup.slug, "text": STOCK},
        )

        assert error_text(result) == (
            "Error executing tool start_conversation: Cannot open a conversation"
            " with Pilot because the call names no environment, and a conversation"
            " is its calling environment's"
        )
        [(_, answer)] = gated_routes.calls
        assert answer.status_code == 400
        assert session.scalars(select(Conversation)).all() == []

    @pytest.mark.parametrize(
        "arguments",
        [
            {},
            {"project": "soup-club"},
            {"text": STOCK},
            {"project": "", "text": STOCK},
            {"project": "soup-club", "text": " \n"},
        ],
    )
    async def test_no_project_or_no_words_is_refused_before_any_call(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        token_endpoint: TokenEndpoint,
        arguments: dict[str, Any],
    ) -> None:
        result = await _ask(projects_app, "start_conversation", arguments)

        assert result.isError
        assert gated_routes.calls == []
        assert token_endpoint.forms == []


@pytest.mark.anyio
@pytest.mark.usefixtures("person", "gated_starts")
class TestSend:
    async def test_a_message_while_a_turn_is_in_flight_is_the_routes_refusal(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        session: DbSession,
        soup: models.Project,
    ) -> None:
        async with mcp_session(projects_app, PROJECTS_HEADERS, PROJECTS_PATH) as (
            calls,
            _,
        ):
            started = await calls.call_tool(
                "start_conversation", {"project": soup.slug, "text": STOCK}
            )
            result = await calls.call_tool(
                "send",
                {
                    "conversation": started.structuredContent["id"],
                    "text": "And the bread?",
                },
            )

        assert error_text(result) == (
            "Error executing tool send: Cannot send a message to Pilot in Soup club"
            " because a turn of its conversation is in flight"
        )
        _, answer = gated_routes.calls[-1]
        assert answer.status_code == 409
        assert session.scalars(select(Turn.words)).all() == [STOCK]

    async def test_a_message_is_one_post_to_its_conversation_and_answers_its_turn(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        token_endpoint: TokenEndpoint,
        session: DbSession,
        service_user: User,
        soup: models.Project,
    ) -> None:
        """Its conversation's start failed, so the message starts it afresh,
        with no controller's send to fake."""
        run = _talk(session, soup, service_user, state=SessionState.FAILED)

        result = await _ask(
            projects_app,
            "send",
            {"conversation": str(run.id), "text": "And the bread?"},
        )

        assert not result.isError, result
        assert result.structuredContent == {"turn": 2}
        [(request, answer)] = gated_routes.calls
        [minted] = token_endpoint.minted
        assert (request.method, str(request.url)) == (
            "POST",
            f"{API_URL}/api/conversations/{run.id}/messages",
        )
        assert json.loads(request.content) == {"words": "And the bread?"}
        assert request.headers["authorization"] == f"Bearer {minted}"
        assert (
            request.headers[ENVIRONMENT_HEADER],
            request.headers[SESSION_HEADER],
        ) == (CALLER_ENVIRONMENT, CALLER_SESSION)
        assert answer.status_code == 201
        turn = session.scalars(select(Turn).where(Turn.seq == 2)).one()
        assert (turn.session_id, turn.author_user_id, turn.words) == (
            run.id,
            service_user.id,
            "And the bread?",
        )

    async def test_a_message_whose_send_failed_is_the_tools_error(
        self, token_endpoint: TokenEndpoint
    ) -> None:
        conversation = uuid.uuid4()
        failed = "Cannot send a message to the session because its environment is gone"
        app = _canned(
            {"conversation": str(conversation), "seq": 3, "error": failed},
            token_endpoint,
        )

        result = await _ask(
            app, "send", {"conversation": str(conversation), "text": "Still there?"}
        )

        assert error_text(result) == f"Error executing tool send: {failed}"

    async def test_a_closed_conversation_takes_none(
        self,
        projects_app: Starlette,
        session: DbSession,
        service_user: User,
        soup: models.Project,
    ) -> None:
        run = _talk(session, soup, service_user)
        close_conversation(session, run, datetime.now(UTC), CloseCause.ENDED)
        session.commit()

        result = await _ask(
            projects_app, "send", {"conversation": str(run.id), "text": "Still there?"}
        )

        assert error_text(result) == (
            "Error executing tool send: Cannot send a message to Pilot in Soup club"
            " because its conversation is closed"
        )

    @pytest.mark.parametrize(
        "headers", [ANOTHERS_HEADERS, NO_ENVIRONMENT], ids=["another", "none"]
    )
    async def test_another_environments_is_refused_as_one_no_id_names(
        self,
        projects_app: Starlette,
        session: DbSession,
        service_user: User,
        soup: models.Project,
        headers: dict[str, str],
        gated_routes: ApiRoutes,
        token_endpoint: TokenEndpoint,
    ) -> None:
        run = _talk(session, soup, service_user)
        never = uuid.uuid4()

        anothers = await _ask_as(
            gated_routes,
            token_endpoint,
            headers,
            "send",
            {"conversation": str(run.id), "text": "Mine now."},
        )
        unknown = await _ask(
            projects_app, "send", {"conversation": str(never), "text": "Mine now."}
        )

        assert error_text(anothers) == _never_was("send", run.id)
        assert error_text(unknown) == _never_was("send", never)
        assert session.scalars(select(Turn.words)).all() == ["Hello."]

    @pytest.mark.parametrize(
        "arguments",
        [
            {},
            {"conversation": str(uuid.UUID(int=7))},
            {"conversation": str(uuid.UUID(int=7)), "text": " "},
            {"conversation": "soup-club", "text": "Hi"},
        ],
    )
    async def test_no_conversation_or_no_words_is_refused_before_any_call(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        token_endpoint: TokenEndpoint,
        arguments: dict[str, Any],
    ) -> None:
        result = await _ask(projects_app, "send", arguments)

        assert result.isError
        assert gated_routes.calls == []
        assert token_endpoint.forms == []


@pytest.mark.anyio
@pytest.mark.usefixtures("person")
class TestGetConversation:
    async def test_it_is_read_through_its_route_as_it_stands(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        session: DbSession,
        service_user: User,
        soup: models.Project,
    ) -> None:
        run = _talk(
            session,
            soup,
            service_user,
            caller_session="monday",
            opened_at=datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
        )
        close_conversation(
            session, run, datetime(2026, 10, 12, 9, 30, tzinfo=UTC), CloseCause.TIMEOUT
        )
        session.commit()

        result = await _ask(
            projects_app, "get_conversation", {"conversation": str(run.id)}
        )

        assert not result.isError, result
        assert result.structuredContent == {
            "id": str(run.id),
            "project": str(soup.id),
            "environment": CALLER_ENVIRONMENT,
            "session": "monday",
            "opened_at": "2026-10-12T09:00:00Z",
            "closed_at": "2026-10-12T09:30:00Z",
            "close_cause": "timeout",
            "turns": 1,
            "running": False,
        }
        [(request, answer)] = gated_routes.calls
        assert (request.method, str(request.url)) == (
            "GET",
            f"{API_URL}/api/conversations/{run.id}",
        )
        assert answer.status_code == 200

    async def test_one_with_a_turn_in_flight_reads_running(
        self,
        projects_app: Starlette,
        session: DbSession,
        service_user: User,
        soup: models.Project,
    ) -> None:
        run = _talk(session, soup, service_user, state=SessionState.RUNNING)

        result = await _ask(
            projects_app, "get_conversation", {"conversation": str(run.id)}
        )

        assert result.structuredContent == _standing(session, run.id, running=True)

    @pytest.mark.parametrize(
        "headers", [ANOTHERS_HEADERS, NO_ENVIRONMENT], ids=["another", "none"]
    )
    async def test_another_environments_is_refused_as_one_no_id_names(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        session: DbSession,
        service_user: User,
        soup: models.Project,
        headers: dict[str, str],
        token_endpoint: TokenEndpoint,
    ) -> None:
        run = _talk(session, soup, service_user)
        never = uuid.uuid4()

        anothers = await _ask_as(
            gated_routes,
            token_endpoint,
            headers,
            "get_conversation",
            {"conversation": str(run.id)},
        )
        unknown = await _ask(
            projects_app, "get_conversation", {"conversation": str(never)}
        )

        assert error_text(anothers) == _never_was("get_conversation", run.id)
        assert error_text(unknown) == _never_was("get_conversation", never)
        assert [answer.status_code for _, answer in gated_routes.calls] == [404, 404]

    @pytest.mark.parametrize("arguments", [{}, {"conversation": "soup-club"}])
    async def test_what_is_no_id_is_refused_before_any_call(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        arguments: dict[str, Any],
    ) -> None:
        result = await _ask(projects_app, "get_conversation", arguments)

        assert result.isError
        assert gated_routes.calls == []


@pytest.mark.anyio
@pytest.mark.usefixtures("person")
class TestListConversations:
    async def test_the_environments_are_listed_open_and_closed_in_the_order_they_opened(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        session: DbSession,
        container: ServiceContainer,
        service_user: User,
        soup: models.Project,
    ) -> None:
        bikes = _make(container, name="Bike log")
        later = _talk(
            session,
            bikes,
            service_user,
            caller_session="tuesday",
            opened_at=datetime(2026, 10, 13, 9, 0, tzinfo=UTC),
        )
        earlier = _talk(
            session,
            soup,
            service_user,
            caller_session="monday",
            opened_at=datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
        )
        close_conversation(
            session,
            earlier,
            datetime(2026, 10, 12, 9, 30, tzinfo=UTC),
            CloseCause.ENDED,
        )
        _talk(session, soup, service_user, AUTOMATION)

        result = await _ask(projects_app, "list_conversations", {})

        assert not result.isError, result
        assert result.structuredContent == {
            "conversations": [
                _standing(session, earlier.id),
                _standing(session, later.id),
            ]
        }
        assert [
            (row["session"], row["close_cause"])
            for row in result.structuredContent["conversations"]
        ] == [("monday", "ended"), ("tuesday", None)]
        [(request, _)] = gated_routes.calls
        assert (request.method, str(request.url)) == (
            "GET",
            f"{API_URL}/api/conversations",
        )

    async def test_a_project_lists_its_conversations_alone(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        session: DbSession,
        container: ServiceContainer,
        service_user: User,
        soup: models.Project,
    ) -> None:
        bikes = _make(container, name="Bike log")
        _talk(session, soup, service_user)
        bike = _talk(session, bikes, service_user)

        result = await _ask(projects_app, "list_conversations", {"project": bikes.slug})

        assert [row["id"] for row in result.structuredContent["conversations"]] == [
            str(bike.id)
        ]
        [(request, _)] = gated_routes.calls
        assert str(request.url) == f"{API_URL}/api/conversations?address={bikes.slug}"

    @pytest.mark.parametrize(
        "headers", [ANOTHERS_HEADERS, NO_ENVIRONMENT], ids=["another", "none"]
    )
    async def test_no_other_environments_is_listed(
        self,
        projects_app: Starlette,
        session: DbSession,
        service_user: User,
        soup: models.Project,
        headers: dict[str, str],
        gated_routes: ApiRoutes,
        token_endpoint: TokenEndpoint,
    ) -> None:
        _talk(session, soup, service_user)

        result = await _ask_as(
            gated_routes, token_endpoint, headers, "list_conversations", {}
        )

        assert result.structuredContent == {"conversations": []}

    async def test_a_project_nothing_names_is_the_routes_refusal(
        self, projects_app: Starlette, gated_routes: ApiRoutes
    ) -> None:
        result = await _ask(projects_app, "list_conversations", {"project": "no-such"})

        assert error_text(result) == (
            "Error executing tool list_conversations: Project no-such was not found"
        )

    async def test_an_empty_project_is_refused_before_any_call(
        self, projects_app: Starlette, gated_routes: ApiRoutes
    ) -> None:
        result = await _ask(projects_app, "list_conversations", {"project": ""})

        assert result.isError
        assert gated_routes.calls == []


@pytest.mark.anyio
@pytest.mark.usefixtures("person", "gated_starts")
class TestInterrupt:
    async def test_the_turn_in_flight_is_stopped_and_the_conversation_kept(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        session: DbSession,
        soup: models.Project,
    ) -> None:
        async with mcp_session(projects_app, PROJECTS_HEADERS, PROJECTS_PATH) as (
            calls,
            _,
        ):
            started = await calls.call_tool(
                "start_conversation", {"project": soup.slug, "text": STOCK}
            )
            run_id = uuid.UUID(started.structuredContent["id"])
            result = await calls.call_tool("interrupt", {"conversation": str(run_id)})

        assert not result.isError, result
        request, answer = gated_routes.calls[-1]
        assert (request.method, str(request.url), answer.status_code) == (
            "POST",
            f"{API_URL}/api/conversations/{run_id}/interrupt",
            200,
        )
        run = session.get_one(models.Session, run_id, populate_existing=True)
        assert run.state_code == SessionState.STOPPED
        assert result.structuredContent["id"] == str(run_id)
        assert (
            result.structuredContent["closed_at"],
            result.structuredContent["close_cause"],
        ) == (None, None)

    async def test_with_no_turn_in_flight_it_changes_nothing(
        self,
        projects_app: Starlette,
        session: DbSession,
        service_user: User,
        soup: models.Project,
    ) -> None:
        run = _talk(session, soup, service_user)

        result = await _ask(projects_app, "interrupt", {"conversation": str(run.id)})

        assert result.structuredContent == _standing(session, run.id)
        assert session.get_one(models.Session, run.id).state_code == SessionState.IDLE

    @pytest.mark.parametrize(
        "headers", [ANOTHERS_HEADERS, NO_ENVIRONMENT], ids=["another", "none"]
    )
    async def test_another_environments_runs_on_and_is_refused_as_one_no_id_names(
        self,
        projects_app: Starlette,
        session: DbSession,
        service_user: User,
        soup: models.Project,
        headers: dict[str, str],
        gated_routes: ApiRoutes,
        token_endpoint: TokenEndpoint,
    ) -> None:
        run = _talk(session, soup, service_user, state=SessionState.RUNNING)
        never = uuid.uuid4()

        anothers = await _ask_as(
            gated_routes,
            token_endpoint,
            headers,
            "interrupt",
            {"conversation": str(run.id)},
        )
        unknown = await _ask(projects_app, "interrupt", {"conversation": str(never)})

        assert error_text(anothers) == _never_was("interrupt", run.id)
        assert error_text(unknown) == _never_was("interrupt", never)
        assert session.get_one(
            models.Session, run.id, populate_existing=True
        ).state_code == (SessionState.RUNNING)


@pytest.mark.anyio
@pytest.mark.usefixtures("person", "gated_starts")
class TestEndConversation:
    async def test_it_is_closed_ended_by_one_post(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        session: DbSession,
        service_user: User,
        soup: models.Project,
    ) -> None:
        run = _talk(session, soup, service_user)

        result = await _ask(
            projects_app, "end_conversation", {"conversation": str(run.id)}
        )

        assert not result.isError, result
        [(request, answer)] = gated_routes.calls
        assert (request.method, str(request.url), answer.status_code) == (
            "POST",
            f"{API_URL}/api/conversations/{run.id}/end",
            200,
        )
        row = session.get_one(Conversation, run.id, populate_existing=True)
        assert row.close_cause_code is CloseCause.ENDED
        assert result.structuredContent == _standing(session, run.id)
        assert result.structuredContent["close_cause"] == "ended"

    async def test_an_ended_conversation_takes_no_message(
        self,
        projects_app: Starlette,
        session: DbSession,
        service_user: User,
        soup: models.Project,
    ) -> None:
        run = _talk(session, soup, service_user)

        async with mcp_session(projects_app, PROJECTS_HEADERS, PROJECTS_PATH) as (
            calls,
            _,
        ):
            await calls.call_tool("end_conversation", {"conversation": str(run.id)})
            result = await calls.call_tool(
                "send", {"conversation": str(run.id), "text": "One more thing."}
            )

        assert error_text(result) == (
            "Error executing tool send: Cannot send a message to Pilot in Soup club"
            " because its conversation is closed"
        )

    async def test_ending_one_closed_already_succeeds_and_changes_nothing(
        self,
        projects_app: Starlette,
        session: DbSession,
        service_user: User,
        soup: models.Project,
    ) -> None:
        run = _talk(session, soup, service_user)
        closed_at = datetime(2026, 10, 12, 9, 30, tzinfo=UTC)
        close_conversation(session, run, closed_at, CloseCause.FINISHED)
        session.commit()

        result = await _ask(
            projects_app, "end_conversation", {"conversation": str(run.id)}
        )

        assert not result.isError, result
        assert (
            result.structuredContent["closed_at"],
            result.structuredContent["close_cause"],
        ) == ("2026-10-12T09:30:00Z", "finished")

    @pytest.mark.parametrize(
        "headers", [ANOTHERS_HEADERS, NO_ENVIRONMENT], ids=["another", "none"]
    )
    async def test_another_environments_stays_open_and_is_refused_as_one_no_id_names(
        self,
        projects_app: Starlette,
        session: DbSession,
        service_user: User,
        soup: models.Project,
        headers: dict[str, str],
        gated_routes: ApiRoutes,
        token_endpoint: TokenEndpoint,
    ) -> None:
        run = _talk(session, soup, service_user)
        never = uuid.uuid4()

        anothers = await _ask_as(
            gated_routes,
            token_endpoint,
            headers,
            "end_conversation",
            {"conversation": str(run.id)},
        )
        unknown = await _ask(
            projects_app, "end_conversation", {"conversation": str(never)}
        )

        assert error_text(anothers) == _never_was("end_conversation", run.id)
        assert error_text(unknown) == _never_was("end_conversation", never)
        assert (
            session.get_one(Conversation, run.id, populate_existing=True).closed_at
            is None
        )


@pytest.fixture
def clock() -> SteppedClock:
    return SteppedClock()


@pytest.fixture
def held_app(
    gated_routes: ApiRoutes, token_endpoint: TokenEndpoint, clock: SteppedClock
) -> Starlette:
    """The app with its projects surface, a held call waiting by `clock`."""
    return app_with_projects(gated_routes, token_endpoint, clock)


@pytest.fixture
def asked(
    session: DbSession,
    container: ServiceContainer,
    service_user: User,
    soup: models.Project,
) -> ChatWriter:
    """A conversation the service user opened from the caller's environment,
    its first message's turn in flight. Committed."""
    caller = Environment(id=CALLER_ENVIRONMENT, name="RecipeBox-2", exempt=False)
    session.add(caller)
    session.flush()
    run = open_conversation(session, soup, caller, state=SessionState.RUNNING)
    writer = ChatWriter(session, container.session_record_service(), run)
    writer.message(service_user, STOCK)
    session.commit()
    return writer


Progress = list[tuple[float, float | None, str | None]]


async def _hold(
    app: Starlette,
    arguments: dict[str, Any],
    headers: dict[str, str] = PROJECTS_HEADERS,
) -> tuple[Any, Progress]:
    """One `get_response` as a session's entry makes it, with the progress
    it was sent meanwhile: the seconds waited, of how many, and the words."""
    progress: Progress = []

    async def told(waited: float, wait: float | None, message: str | None) -> None:
        progress.append((waited, wait, message))

    async with mcp_session(app, headers, PROJECTS_PATH) as (calls, _):
        result = await calls.call_tool(
            "get_response", arguments, progress_callback=told
        )
    return result, progress


def _paths(routes: ApiRoutes) -> list[str]:
    return [f"{request.method} {request.url.path}" for request, _ in routes.calls]


def _always_running(
    token_endpoint: TokenEndpoint, clock: SteppedClock, idle_asks: int = 0
) -> Starlette:
    """The app with its projects surface, a held call waiting by `clock`,
    whose API answers a conversation with a turn in flight and its reply
    `running`, for as long as a suite cannot hold a route's; its first
    `idle_asks` answers of where the conversation stands say none is."""
    asks = 0

    def answer(request: httpx.Request) -> httpx.Response:
        nonlocal asks
        if request.url.path.endswith("/response"):
            return httpx.Response(
                200, json={"turn": None, "state": "running", "text": None}
            )
        asks += 1
        return httpx.Response(200, json={"in_flight": asks > idle_asks})

    return app_with_projects(httpx.MockTransport(answer), token_endpoint, clock)


@pytest.mark.anyio
@pytest.mark.usefixtures("person")
class TestGetResponse:
    """`get_response` (F150.10; V01, V02): the conversation's long poll, held
    in the MCP process, which asks the API where the conversation stands in
    requests each answered at once and reports progress meanwhile."""

    async def test_a_turn_that_has_ended_is_answered_at_once(
        self,
        held_app: Starlette,
        gated_routes: ApiRoutes,
        token_endpoint: TokenEndpoint,
        session: DbSession,
        clock: SteppedClock,
        asked: ChatWriter,
    ) -> None:
        asked.text("Reading the plan.")
        asked.text("It simmers.")
        asked.result("It simmers.")
        session.commit()

        result, progress = await _hold(held_app, {"conversation": str(asked.run.id)})

        assert not result.isError, result
        assert result.structuredContent == {
            "turn": 1,
            "state": "done",
            "text": "Reading the plan.\n\n---\n\nIt simmers.",
        }
        assert _paths(gated_routes) == [
            f"GET /api/conversations/{asked.run.id}",
            f"GET /api/conversations/{asked.run.id}/response",
        ]
        [minted] = token_endpoint.minted
        for request, _ in gated_routes.calls:
            assert request.headers["authorization"] == f"Bearer {minted}"
            assert (
                request.headers[ENVIRONMENT_HEADER],
                request.headers[SESSION_HEADER],
            ) == (CALLER_ENVIRONMENT, CALLER_SESSION)
        assert (clock.slept, progress) == ([], [])

    async def test_it_holds_until_the_turn_ends_and_answers_it(
        self,
        held_app: Starlette,
        gated_routes: ApiRoutes,
        session: DbSession,
        clock: SteppedClock,
        asked: ChatWriter,
    ) -> None:
        def end() -> None:
            asked.text("It simmers.")
            asked.result("It simmers.")
            session.commit()

        clock.at(60, end)

        result, progress = await _hold(held_app, {"conversation": str(asked.run.id)})

        assert result.structuredContent == {
            "turn": 1,
            "state": "done",
            "text": "It simmers.",
        }
        assert clock.time == 60
        assert progress == [(30.0, WAIT_MS_DEFAULT / 1000, STILL_RUNNING)]
        asks = _paths(gated_routes)
        assert asks[-1] == f"GET /api/conversations/{asked.run.id}/response"
        assert set(asks[:-1]) == {f"GET /api/conversations/{asked.run.id}"}
        assert len(asks) == 60 / POLL_SECONDS + 2

    async def test_a_wait_longer_than_five_minutes_reports_progress_twice_a_minute(
        self,
        held_app: Starlette,
        gated_routes: ApiRoutes,
        session: DbSession,
        clock: SteppedClock,
        asked: ChatWriter,
    ) -> None:
        """Claude Code ends a tool call that sent no response or progress
        for 300 s, and the surface's entry sets no timeout of its own (V02).
        No request to the API is held: each ask is answered at once, under a
        timeout of its own, and the wait is the process's between them."""
        asked.text("Reading the plan.")
        session.commit()

        result, progress = await _hold(
            held_app, {"conversation": str(asked.run.id), "wait_ms": 360_000}
        )

        assert result.structuredContent == {
            "turn": None,
            "state": "running",
            "text": "Reading the plan.",
        }
        assert clock.time == 360
        waited = [seconds for seconds, _, _ in progress]
        assert waited == [30.0 * tick for tick in range(1, 12)]
        gaps = [later - earlier for earlier, later in pairwise([0.0, *waited, 360.0])]
        assert max(gaps) <= 60
        assert {(wait, message) for _, wait, message in progress} == {
            (360.0, STILL_RUNNING)
        }
        assert max(clock.slept) <= POLL_SECONDS
        *asks, read = gated_routes.calls
        assert len(asks) == 360 / POLL_SECONDS
        assert {request.extensions["timeout"]["read"] for request, _ in asks} == {20.0}
        assert _paths(gated_routes)[-1] == (
            f"GET /api/conversations/{asked.run.id}/response"
        )
        assert read[1].status_code == 200

    async def test_a_larger_ask_than_an_hour_is_clamped_to_the_hour(
        self, token_endpoint: TokenEndpoint, clock: SteppedClock
    ) -> None:
        result, progress = await _hold(
            _always_running(token_endpoint, clock),
            {"conversation": str(uuid.uuid4()), "wait_ms": 2 * WAIT_MS_MAX},
        )

        assert not result.isError, result
        assert result.structuredContent == {
            "turn": None,
            "state": "running",
            "text": None,
        }
        assert clock.time == 3600 == WAIT_MS_MAX / 1000
        assert {wait for _, wait, _ in progress} == {3600.0}
        assert progress[-1][0] == 3570.0

    async def test_with_no_wait_given_it_holds_fifteen_minutes(
        self, token_endpoint: TokenEndpoint, clock: SteppedClock
    ) -> None:
        result, _ = await _hold(
            _always_running(token_endpoint, clock), {"conversation": str(uuid.uuid4())}
        )

        assert result.structuredContent["state"] == "running"
        assert clock.time == 900 == WAIT_MS_DEFAULT / 1000

    async def test_a_wait_of_nothing_answers_a_running_turn_at_once(
        self,
        held_app: Starlette,
        gated_routes: ApiRoutes,
        clock: SteppedClock,
        asked: ChatWriter,
    ) -> None:
        result, progress = await _hold(
            held_app, {"conversation": str(asked.run.id), "wait_ms": 0}
        )

        assert result.structuredContent == {
            "turn": None,
            "state": "running",
            "text": None,
        }
        assert _paths(gated_routes) == [
            f"GET /api/conversations/{asked.run.id}/response"
        ]
        assert (clock.slept, progress) == ([], [])

    async def test_a_turn_started_between_its_ask_and_its_read_is_waited_on(
        self, token_endpoint: TokenEndpoint, clock: SteppedClock
    ) -> None:
        """The conversation is asked and stands idle, and its reply, read
        next, is `running`: `running` is answered only once the wait is
        over."""
        result, _ = await _hold(
            _always_running(token_endpoint, clock, idle_asks=1),
            {"conversation": str(uuid.uuid4()), "wait_ms": 10_000},
        )

        assert result.structuredContent["state"] == "running"
        assert clock.time == 10

    async def test_a_wait_below_nothing_is_refused_before_any_call(
        self, held_app: Starlette, gated_routes: ApiRoutes, asked: ChatWriter
    ) -> None:
        result, _ = await _hold(
            held_app, {"conversation": str(asked.run.id), "wait_ms": -1}
        )

        assert result.isError
        assert gated_routes.calls == []

    @pytest.mark.parametrize(
        "headers", [ANOTHERS_HEADERS, NO_ENVIRONMENT], ids=["another", "none"]
    )
    async def test_another_environments_is_refused_as_one_no_id_names(
        self,
        held_app: Starlette,
        gated_routes: ApiRoutes,
        token_endpoint: TokenEndpoint,
        clock: SteppedClock,
        asked: ChatWriter,
        headers: dict[str, str],
    ) -> None:
        never = uuid.uuid4()
        anothers_app = app_with_projects(gated_routes, token_endpoint, clock)

        anothers, _ = await _hold(
            anothers_app, {"conversation": str(asked.run.id)}, headers
        )
        unknown, _ = await _hold(held_app, {"conversation": str(never)})

        assert error_text(anothers) == _never_was("get_response", asked.run.id)
        assert error_text(unknown) == _never_was("get_response", never)
        assert clock.slept == []

    async def test_its_progress_and_its_answer_are_events_of_the_calls_own_stream(
        self,
        held_app: Starlette,
        clock: SteppedClock,
        asked: ChatWriter,
    ) -> None:
        """The call is answered as server-sent events (V02): each progress
        notification an event of the POST's own response, under the token
        the call gave, before the answer. Nothing but that stream reaches a
        caller, the server holding no session between requests."""
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "get_response",
                "arguments": {"conversation": str(asked.run.id), "wait_ms": 90_000},
                "_meta": {"progressToken": "held-1"},
            },
        }
        headers = PROJECTS_HEADERS | {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }

        async with (
            http_client(held_app) as http,
            held_app.router.lifespan_context(held_app),
        ):
            response = await http.post(
                PROJECTS_PATH, content=json.dumps(body).encode(), headers=headers
            )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        *told, answer = [
            json.loads(line.removeprefix("data:"))
            for line in response.text.splitlines()
            if line.startswith("data:")
        ]
        assert [(event["method"], event["params"]) for event in told] == [
            (
                "notifications/progress",
                {
                    "progressToken": "held-1",
                    "progress": waited,
                    "total": 90.0,
                    "message": STILL_RUNNING,
                },
            )
            for waited in (30.0, 60.0)
        ]
        assert answer["id"] == 1
        assert answer["result"]["structuredContent"] == {
            "turn": None,
            "state": "running",
            "text": None,
        }
        assert clock.time == 90
