"""`pilot-store`'s routes (TD §4.5, F86): the REST calls Pilot's MCP server
makes for the brain's tools, under the session's bearer, outside `/api/`,
pinned as the surface they are."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from dependency_injector import providers
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import (
    Attachment,
    Block,
    Chat,
    Document,
    Effect,
    Environment,
    Item,
    Project,
    Turn,
    User,
    WriterQuestion,
)
from app.models.reference import AnswerChannel, ChatKind, ProjectState, SessionState
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerClient
from app.services.pilot_server import token_hash
from app.services.session_record_service import read_records
from app.services.session_start_service import SessionStartService
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.fake_controller import ServedFakeController
from tests.support.starts import configured_starts
from tests.support.supervisor import Supervise

ITEMS = "/tools/pilot-store/items"
ATTACHMENTS = "/tools/pilot-store/attachments"
ANSWERS = "/tools/pilot-store/answers"
MARKS = "/tools/pilot-store/marks"
STOPS = "/tools/pilot-store/stops"
FINISH = "/tools/pilot-store/finish"
WRITER_QUESTIONS = "/tools/pilot-store/writer-questions"

TOKEN = "brain-token"

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

DRAFT = """---
title: Camp
---

```question id=Q1
```
"""

REGISTERED_TEXT = """Two asks about the camp.

```question id=Q1
```

```question id=Q2
```
"""


def _bearer(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _brain(
    db: DbSession,
    project: Project,
    environment: Environment,
    kind: str = "chat",
    state: SessionState = SessionState.RUNNING,
) -> models.Session:
    """A Session of `kind` whose bearer is `TOKEN`, its one Turn in flight."""
    now = datetime.now(UTC)
    run = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code=kind,
        cwd="/work/PilotProjects",
        token_hash=token_hash(TOKEN),
        state_code=state,
        turns=1,
        turn_started_at=now,
    )
    db.add(run)
    db.flush()
    db.add(Turn(session_id=run.id, seq=1, message="Go on.", started_at=now))
    db.flush()
    return run


def _decision(
    container: ServiceContainer, project: Project, run: models.Session
) -> Item:
    return container.document_service().bear_item(
        project, "decision", "Which tent?", run, DECISION
    )


def _registered(
    db: DbSession,
    container: ServiceContainer,
    project: Project,
    environment: Environment,
) -> Item:
    worker = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code="work",
        cwd="/work/Example",
        token_hash=token_hash("worker-token"),
        state_code=SessionState.IDLE,
    )
    db.add(worker)
    db.flush()
    documents = container.document_service()
    item = documents.register(project, worker, "/work/Example/survey.md").item
    documents.publish_read(db.get_one(Document, item.id), REGISTERED_TEXT, worker.id)
    return item


def _work(
    db: DbSession, container: ServiceContainer, project: Project
) -> models.Session:
    run = models.Session(
        project_id=project.id,
        kind_code="work",
        cwd="/work/Example",
        token_hash=token_hash("work-token"),
        state_code=SessionState.HELD,
        turns=1,
        turn_started_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()
    db.add(Turn(session_id=run.id, seq=1, message="Go.", started_at=datetime.now(UTC)))
    container.record_service().place_work(project, run, "Pitching the tent")
    return run


def _error(response: Any) -> str:
    error: str = response.get_json()["error"]
    return error


class TestPilotStoreRoutes:
    def test_the_surface_is_seven_routes_outside_the_api(self, app: Flask) -> None:
        routes = sorted(
            (rule.rule, sorted(rule.methods - {"HEAD", "OPTIONS"}))
            for rule in app.url_map.iter_rules()
            if rule.endpoint.startswith("pilot_store.")
        )

        assert routes == [
            (ANSWERS, ["POST"]),
            (ATTACHMENTS, ["POST"]),
            (FINISH, ["POST"]),
            (ITEMS, ["POST"]),
            (MARKS, ["POST"]),
            (STOPS, ["POST"]),
            (WRITER_QUESTIONS, ["POST"]),
        ]

    def test_the_routes_are_outside_the_oidc_gate(
        self,
        oidc_app: Flask,
        oidc_client: FlaskClient,
        session: DbSession,
        project: Project,
        environment: Environment,
    ) -> None:
        assert oidc_app.container.config().oidc_enabled
        run = _brain(session, project, environment)
        item = _decision(oidc_app.container, project, run)

        response = oidc_client.post(
            MARKS,
            json={"item": str(item.id), "mark": "read", "for": "ada"},
            headers=_bearer(),
        )

        assert response.status_code == 409


class TestTheGate:
    @pytest.mark.parametrize("route", [ANSWERS, MARKS, STOPS, FINISH, WRITER_QUESTIONS])
    def test_no_bearer_is_401_before_the_body_is_read(
        self, client: FlaskClient, route: str
    ) -> None:
        response = client.post(route, json={})

        assert response.status_code == 401
        assert _error(response) == (
            "Cannot call pilot-store because the request carries no bearer"
        )

    def test_a_bearer_no_session_has_is_401(self, client: FlaskClient) -> None:
        response = client.post(FINISH, headers=_bearer("an-unknown-token"))

        assert response.status_code == 401
        assert _error(response) == (
            "Cannot call pilot-store because no session has the request's bearer"
        )

    def test_a_work_items_bearer_is_403(
        self,
        client: FlaskClient,
        session: DbSession,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment, "work")

        response = client.post(FINISH, headers=_bearer())

        assert response.status_code == 403
        assert _error(response) == (
            f"Cannot call pilot-store because session {run.id} is a work session,"
            " not a chat's or a job's"
        )

    def test_a_session_whose_turn_has_ended_is_403(
        self,
        client: FlaskClient,
        session: DbSession,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment, state=SessionState.IDLE)

        response = client.post(FINISH, headers=_bearer())

        assert response.status_code == 403
        assert _error(response) == (
            f"Cannot call pilot-store because session {run.id} has no turn running"
        )


class TestAnswer:
    """`POST /tools/pilot-store/answers`: `answer(block, value, for, note?, to?)`."""

    @pytest.mark.usefixtures("started")
    def test_the_answer_is_200_with_its_effect_line_and_names_the_tool_use(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        person: User,
    ) -> None:
        run = _brain(session, project, environment)
        item = _decision(container, project, run)

        response = client.post(
            ANSWERS,
            json={
                "block": f"{item.id}/D1",
                "value": "Dome",
                "for": "ada",
                "note": "The dome.",
            },
            headers={**_bearer(), "Tool-Use-Id": "toolu_01"},
        )

        assert response.status_code == 200
        assert response.get_json() == {"effect": "Answered · D1 · Which tent?"}
        block = session.scalars(select(Block).where(Block.document_id == item.id)).one()
        assert (block.answer, block.answered_by_user_id, block.via_code) == (
            "Dome",
            person.id,
            AnswerChannel.CHAT,
        )
        [record] = read_records(session, run.id, limit=10)
        assert record.record.payload["toolUseId"] == "toolu_01"

    @pytest.mark.parametrize(
        "body",
        [
            {"block": "D1", "value": "Dome", "for": "ada"},
            {"block": "not-a-uuid/D1", "value": "Dome", "for": "ada"},
            {"block": "{item}/", "value": "Dome", "for": "ada"},
            {"block": "{item}/D 1", "value": "Dome", "for": "ada"},
            {"block": "{item}/D1", "value": "", "for": "ada"},
            {"block": "{item}/D1", "value": "Dome"},
            {"block": "{item}/D1", "value": "Dome", "for_": "ada"},
            {"block": "{item}/D1", "value": "Dome", "for": "ada", "via": "app"},
            {"block": "project.md/", "value": "Dome", "for": "ada"},
            {"block": "project.md/Q 1", "value": "Dome", "for": "ada"},
            {"block": "handbook.md/Q1", "value": "Dome", "for": "ada"},
        ],
        ids=[
            "a-local-id",
            "no-item-id",
            "no-local-id",
            "a-local-id-with-a-space",
            "an-empty-value",
            "no-for",
            "for-by-its-field-name",
            "another-key",
            "a-draft-block-with-no-local-id",
            "a-draft-block-with-a-space",
            "the-handbooks-block",
        ],
    )
    def test_a_body_that_is_not_a_block_an_answer_and_a_handle_is_400(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        body: dict[str, str],
    ) -> None:
        run = _brain(session, project, environment)
        item = _decision(container, project, run)

        response = client.post(
            ANSWERS,
            json={key: value.format(item=item.id) for key, value in body.items()},
            headers=_bearer(),
        )

        assert response.status_code == 400

    def test_a_handle_no_person_has_is_404(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)
        item = _decision(container, project, run)

        response = client.post(
            ANSWERS,
            json={"block": f"{item.id}/D1", "value": "Dome", "for": "nobody"},
            headers=_bearer(),
        )

        assert response.status_code == 404
        assert _error(response) == "Person nobody was not found"

    def test_an_answer_the_record_refuses_is_409(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)
        item = _decision(container, project, run)

        response = client.post(
            ANSWERS,
            json={"block": f"{item.id}/D1", "value": "Dome", "for": "ada", "to": "t1"},
            headers=_bearer(),
        )

        assert response.status_code == 409
        assert _error(response).endswith("`to` goes with `deferred` alone")

    def test_in_a_drafts_definition_chat_the_drafts_ask_is_200(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        container.document_service().bear_draft(project, DRAFT)
        run = _brain(session, project, environment)
        session.add(
            Chat(
                id=run.id,
                project_id=project.id,
                session_kind_code="chat",
                kind_code=ChatKind.DEFINITION,
            )
        )
        session.flush()

        response = client.post(
            ANSWERS,
            json={"block": "project.md/Q1", "value": "The lake", "for": "ada"},
            headers=_bearer(),
        )

        assert response.status_code == 200
        assert response.get_json() == {"effect": "Answered · Q1 · Camp"}

    def test_outside_a_drafts_definition_chat_the_drafts_ask_is_409(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        container.document_service().bear_draft(project, DRAFT)
        _brain(session, project, environment, "job")

        response = client.post(
            ANSWERS,
            json={"block": "project.md/Q1", "value": "The lake", "for": "ada"},
            headers=_bearer(),
        )

        assert response.status_code == 409
        assert _error(response).endswith(
            "`project.md` takes answers in its draft's definition chat alone"
        )


class TestMark:
    """`POST /tools/pilot-store/marks`: `mark(item, done | read | reviewed, for?)`."""

    def test_a_mark_is_200_with_its_effect_line(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        person: User,
    ) -> None:
        run = _brain(session, project, environment)
        item = container.document_service().bear_item(
            project, "notice", "The lake is open", run, "# The lake is open\n"
        )

        response = client.post(
            MARKS,
            json={"item": str(item.id), "mark": "read", "for": "ada"},
            headers=_bearer(),
        )

        assert response.status_code == 200
        assert response.get_json() == {"effect": "Marked read · The lake is open"}
        session.refresh(item)
        assert item.done_by_user_id == person.id

    @pytest.mark.parametrize(
        "body",
        [
            {"item": "not-a-uuid", "mark": "done"},
            {"item": "{item}", "mark": "answered"},
            {"item": "{item}"},
            {"item": "{item}", "mark": "done", "for": ""},
        ],
        ids=["no-item-id", "another-mark", "no-mark", "an-empty-for"],
    )
    def test_a_body_that_is_not_an_item_and_a_mark_is_400(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        body: dict[str, str],
    ) -> None:
        run = _brain(session, project, environment)
        item = _decision(container, project, run)

        response = client.post(
            MARKS,
            json={key: value.format(item=item.id) for key, value in body.items()},
            headers=_bearer(),
        )

        assert response.status_code == 400

    def test_an_item_of_another_project_is_404(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        person: User,
    ) -> None:
        _brain(session, project, environment)
        other = Project(created_by_user_id=person.id)
        session.add(other)
        session.flush()
        theirs = container.document_service().bear_item(
            other,
            "notice",
            "The lake is open",
            _work(session, container, other),
            "# The lake is open\n",
        )

        response = client.post(
            MARKS,
            json={"item": str(theirs.id), "mark": "read", "for": "ada"},
            headers=_bearer(),
        )

        assert response.status_code == 404
        assert _error(response) == f"Item {theirs.id} was not found"

    def test_read_without_for_is_409(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)
        item = _decision(container, project, run)

        response = client.post(
            MARKS, json={"item": str(item.id), "mark": "read"}, headers=_bearer()
        )

        assert response.status_code == 409


class TestStopWork:
    """`POST /tools/pilot-store/stops`: `stop_work(item)`."""

    def test_a_stop_is_200_with_its_effect_line(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        _brain(session, project, environment)
        work = _work(session, container, project)

        response = client.post(STOPS, json={"item": str(work.id)}, headers=_bearer())

        assert response.status_code == 200
        assert response.get_json() == {"effect": "Stopped · Pitching the tent"}
        session.refresh(work)
        assert work.state_code == SessionState.STOPPED

    def test_a_body_that_is_not_an_item_is_400(
        self,
        client: FlaskClient,
        session: DbSession,
        project: Project,
        environment: Environment,
    ) -> None:
        _brain(session, project, environment)

        response = client.post(STOPS, json={"item": "work"}, headers=_bearer())

        assert response.status_code == 400

    def test_an_unknown_item_is_404_and_a_prose_item_409(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)
        item = _decision(container, project, run)
        # Committed, so that the refused call's rollback keeps it.
        session.commit()
        unknown = "0f8a1c2e-5b7d-4e3a-9c61-2d4f8b0e7a15"

        missing = client.post(STOPS, json={"item": unknown}, headers=_bearer())
        prose = client.post(STOPS, json={"item": str(item.id)}, headers=_bearer())

        assert missing.status_code == 404
        assert prose.status_code == 409
        assert _error(prose) == "Cannot stop Which tent? because it is no work item"


class TestFinish:
    """`POST /tools/pilot-store/finish`: `finish()`."""

    def test_the_finish_is_200_with_its_effect_line(
        self,
        client: FlaskClient,
        session: DbSession,
        project: Project,
        environment: Environment,
    ) -> None:
        project.state_code = ProjectState.OPEN
        project.slug = "camp"
        project.name = "Camp"
        run = _brain(session, project, environment)

        response = client.post(FINISH, headers=_bearer())

        assert response.status_code == 200
        assert response.get_json() == {"effect": "Finished · Camp"}
        session.refresh(project)
        session.refresh(run)
        assert project.state_code == ProjectState.FINISHED
        assert run.state_code == SessionState.STOPPED

    def test_a_draft_is_409(
        self,
        client: FlaskClient,
        session: DbSession,
        project: Project,
        environment: Environment,
    ) -> None:
        _brain(session, project, environment)
        # Committed, so that the refused call's rollback keeps it.
        session.commit()

        response = client.post(FINISH, headers=_bearer())

        assert response.status_code == 409
        assert _error(response) == (
            "Cannot finish the untitled project because it is a draft"
        )
        assert session.scalars(select(Effect)).all() == []


class TestAskWriter:
    """`POST /tools/pilot-store/writer-questions`: `ask_writer(document, block,
    question)`."""

    def test_a_question_is_201_with_the_blocks_asked(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        _brain(session, project, environment, "job")
        item = _registered(session, container, project, environment)

        response = client.post(
            WRITER_QUESTIONS,
            json={
                "document": str(item.id),
                "block": f"{item.id}/Q2",
                "question": "Which lake?",
            },
            headers=_bearer(),
        )

        assert response.status_code == 201
        assert response.get_json() == {"blocks": ["Q2"]}
        [question] = session.scalars(select(WriterQuestion))
        assert question.question == "Which lake?"

    @pytest.mark.parametrize(
        "body",
        [
            {"document": "{item}", "block": "Q2", "question": "Which lake?"},
            {"document": "{item}", "block": "{item}/Q2", "question": ""},
            {"block": "{item}/Q2", "question": "Which lake?"},
        ],
        ids=["a-local-id", "an-empty-question", "no-document"],
    )
    def test_a_body_that_is_not_a_document_a_block_and_a_question_is_400(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        body: dict[str, str],
    ) -> None:
        _brain(session, project, environment, "job")
        item = _registered(session, container, project, environment)

        response = client.post(
            WRITER_QUESTIONS,
            json={key: value.format(item=item.id) for key, value in body.items()},
            headers=_bearer(),
        )

        assert response.status_code == 400

    def test_a_chats_question_is_403(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        _brain(session, project, environment, "chat")
        item = _registered(session, container, project, environment)

        response = client.post(
            WRITER_QUESTIONS,
            json={
                "document": str(item.id),
                "block": f"{item.id}/Q2",
                "question": "Which lake?",
            },
            headers=_bearer(),
        )

        assert response.status_code == 403

    def test_a_block_the_document_lacks_is_404_and_one_asked_again_409(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        _brain(session, project, environment, "job")
        item = _registered(session, container, project, environment)
        # Committed, so that a refused call's rollback keeps it.
        session.commit()

        def ask(local_id: str) -> Any:
            return client.post(
                WRITER_QUESTIONS,
                json={
                    "document": str(item.id),
                    "block": f"{item.id}/{local_id}",
                    "question": "Which?",
                },
                headers=_bearer(),
            )

        assert ask("Q9").status_code == 404
        assert ask("Q1").status_code == 201
        again = ask("Q1")
        assert again.status_code == 409
        assert _error(again).endswith(
            "because its writer was asked about block Q1 already"
        )


ELSEWHERE = "example-elsewhere"

DESIGN = "/work/Elsewhere/design"

WORK = {
    "kind": "work",
    "title": "Renaming the badge",
    "repo": "example/Example",
    "cwd": "/work/Example",
    "brief": "Rename the badge.",
}


@pytest.fixture
def started(
    container: ServiceContainer, supervise: Supervise
) -> Iterator[SessionStartService]:
    """The routes' start on a controller, its loops never run."""
    starts = configured_starts(container, supervise)
    container.session_start_service.override(providers.Object(starts))
    try:
        yield starts
    finally:
        container.session_start_service.reset_override()
        clear_after_commit_callbacks()


class TestAddItem:
    def test_a_prose_item_is_201_with_its_path_and_effect_line(
        self,
        client: FlaskClient,
        session: DbSession,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)

        response = client.post(
            ITEMS,
            json={"kind": "notice", "title": "The lake", "for": "ada"},
            headers={**_bearer(), "Tool-Use-Id": "toolu_01"},
        )

        assert response.status_code == 201
        [item] = session.scalars(select(Item)).all()
        assert response.get_json() == {
            "id": str(item.id),
            "path": f"/work/Projects/draft-{project.number}/items/1-the-lake.md",
            "state": None,
            "held": None,
            "effect": "Added · Notice · The lake",
        }
        [record] = read_records(session, run.id, limit=10)
        assert record.record.payload["toolUseId"] == "toolu_01"

    def test_a_work_item_is_201_with_its_state_as_the_gate_left_it(
        self,
        client: FlaskClient,
        session: DbSession,
        started: SessionStartService,
        project: Project,
        environment: Environment,
    ) -> None:
        project.paused = True
        _brain(session, project, environment)

        response = client.post(ITEMS, json=WORK, headers=_bearer())

        assert response.status_code == 201
        [item] = session.scalars(select(Item)).all()
        assert response.get_json() == {
            "id": str(item.id),
            "path": None,
            "state": "held",
            "held": "paused",
            "effect": "Added · Work · Renaming the badge",
        }

    @pytest.mark.parametrize(
        "body",
        [
            {"kind": "opening", "title": "Camp"},
            {"kind": "notice", "title": ""},
            {"kind": "notice", "title": "Camp", "attachments": ["camp.md"]},
            {"kind": "notice", "title": "Camp", "attachments": ["e:/a", "e:/a"]},
            {"kind": "work", "repo": "Example"},
            {"kind": "notice", "title": "Camp", "cards": ["MD-8"]},
        ],
    )
    def test_a_body_that_is_not_an_item_is_400(
        self,
        client: FlaskClient,
        session: DbSession,
        project: Project,
        environment: Environment,
        body: dict[str, Any],
    ) -> None:
        _brain(session, project, environment)

        response = client.post(ITEMS, json=body, headers=_bearer())

        assert response.status_code == 400
        assert session.scalars(select(Item)).all() == []

    def test_a_wait_is_409(
        self,
        client: FlaskClient,
        session: DbSession,
        project: Project,
        environment: Environment,
    ) -> None:
        _brain(session, project, environment)

        response = client.post(
            ITEMS, json={"kind": "card_wait", "title": "MD-8 done"}, headers=_bearer()
        )

        assert response.status_code == 409
        assert _error(response) == (
            "Cannot add a card_wait item because Pilot takes no waits yet"
        )

    def test_a_text_with_a_fault_is_409_and_a_task_not_in_the_plan_404(
        self,
        client: FlaskClient,
        session: DbSession,
        started: SessionStartService,
        project: Project,
        environment: Environment,
    ) -> None:
        _brain(session, project, environment)
        # Committed, so that the first refusal's rollback keeps the session.
        session.commit()

        faulty = client.post(
            ITEMS, json={"kind": "notice", "markdown": "Prose.\n"}, headers=_bearer()
        )
        stray = client.post(ITEMS, json={**WORK, "step": "nowhere"}, headers=_bearer())

        assert faulty.status_code == 409
        assert _error(faulty).startswith(
            "Cannot add a notice item because its text holds faults: the item has no"
            " title"
        )
        assert stray.status_code == 404
        assert _error(stray) == f"Plan task {project.id}/nowhere was not found"

    def test_without_a_controller_a_work_item_is_409(
        self,
        client: FlaskClient,
        session: DbSession,
        project: Project,
        environment: Environment,
    ) -> None:
        _brain(session, project, environment)

        response = client.post(ITEMS, json=WORK, headers=_bearer())

        assert response.status_code == 409
        assert _error(response) == (
            "Cannot place a work item of example/Example because no controller is"
            " configured"
        )


class TestAttachFile:
    def test_the_material_is_201_with_its_ids_and_effect_line(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        fake_controller.add_environment(ELSEWHERE)
        fake_controller.put_file(ELSEWHERE, f"{DESIGN}/README.md", b"# The design\n")
        run = _brain(session, project, environment)
        item = _decision(container, project, run)

        response = client.post(
            ATTACHMENTS,
            json={"source": f"{ELSEWHERE}:{DESIGN}", "to": str(item.id)},
            headers=_bearer(),
        )

        assert response.status_code == 201
        [attachment] = session.scalars(select(Attachment)).all()
        assert response.get_json() == {
            "ids": [str(attachment.id)],
            "effect": "Attached · The design",
        }
        assert attachment.source_environment_id == ELSEWHERE

    @pytest.mark.parametrize(
        "body",
        [
            {"source": "/work/Elsewhere/design"},
            {"source": "example-elsewhere:design"},
            {"source": f"{ELSEWHERE}:{DESIGN}", "to": "camp"},
        ],
    )
    def test_a_body_that_is_not_a_source_and_an_item_is_400(
        self,
        client: FlaskClient,
        session: DbSession,
        project: Project,
        environment: Environment,
        body: dict[str, str],
    ) -> None:
        _brain(session, project, environment)

        assert client.post(ATTACHMENTS, json=body, headers=_bearer()).status_code == 400

    def test_without_to_is_409_and_an_unknown_environment_404(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _brain(session, project, environment)
        item = _decision(container, project, run)
        # Committed, so that the first refusal's rollback keeps the session.
        session.commit()

        untargeted = client.post(
            ATTACHMENTS, json={"source": f"{ELSEWHERE}:{DESIGN}"}, headers=_bearer()
        )
        unknown = client.post(
            ATTACHMENTS,
            json={"source": f"{ELSEWHERE}:{DESIGN}", "to": str(item.id)},
            headers=_bearer(),
        )

        assert untargeted.status_code == 409
        assert unknown.status_code == 404
        assert _error(unknown) == f"Environment {ELSEWHERE} was not found"
