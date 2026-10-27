"""`pilot-work`'s tools (F85, ruling D1) and `pilot-store`'s (F86) driven
through a real MCP client to the API's routes: each one REST call under the
caller's bearer as it came, its answer the route's, and the route's refusal the
tool's error, its reason whole."""

import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession
from starlette.applications import Starlette

from app import models
from app.models import (
    Attachment,
    Block,
    Chat,
    Document,
    Environment,
    Item,
    ItemAttachment,
    Turn,
    WriterQuestion,
)
from app.models.reference import AnswerChannel, ChatKind, ProjectState, SessionState
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerClient
from app.services.session_record_service import read_records
from pilot_mcp.server import STORE_PATH
from pilot_mcp.tools import TOOL_USE_ID_META
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


@pytest.mark.anyio
class TestAnswer:
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
        session.refresh(project)
        assert project.state_code == ProjectState.FINISHED


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
            {
                "document": str(item.id),
                "block": f"{item.id}/Q2",
                "question": "Which lake?",
            },
            path=STORE_PATH,
        )

        assert result.structuredContent == {"blocks": ["Q2"]}
        [(request, _)] = routes.calls
        assert str(request.url) == f"{API_URL}/tools/pilot-store/writer-questions"
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
            {
                "document": str(item.id),
                "block": f"{item.id}/Q2",
                "question": "Which lake?",
            },
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

    async def test_a_wait_is_the_routes_refusal(
        self, mcp_app: Starlette, routes: ApiRoutes, brain: models.Session
    ) -> None:
        result = await call(
            mcp_app,
            "add_item",
            {"item": {"kind": "timed_wait", "title": "Tomorrow"}},
            path=STORE_PATH,
        )

        assert error_text(result) == _refusal(routes, "add_item")
        assert error_text(result) == (
            "Error executing tool add_item: Cannot add a timed_wait item because"
            " Pilot takes no waits yet"
        )

    @pytest.mark.parametrize(
        "item",
        [
            {"kind": "opening", "title": "Camp"},
            {"kind": "notice", "title": "Camp", "cards": ["MD-8"]},
            {"kind": "notice", "title": "Camp", "attachments": ["camp.md"]},
            {"kind": "work", "repo": "Example"},
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
