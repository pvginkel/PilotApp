"""/api/items: what the signed-in person does to a timeline's items — answer
a block, mark an action Done, mark a document Done, a notice Read, a review
Reviewed, and undo (F14, F17, F32.4); and the live event each sends (F80.2).
And an item's document read on its own (F28, F13.3)."""

import json
import uuid
from collections.abc import Iterator
from queue import Empty
from typing import Any

import pilot_dsl as dsl
import pytest
from flask.testing import FlaskClient
from sqlalchemy.orm import Session

from app import models
from app.engine.paths import tree_path
from app.models import Document, Environment, Item, Project, User
from app.models.reference import SessionState
from app.schemas.testing_record import InventedProjectCreateSchema
from app.services.container import ServiceContainer
from app.services.project_event_service import ProjectEventService
from app.services.sse_connection_manager import SSEConnection
from app.utils.after_commit import clear_after_commit_callbacks

ITEMS = "/api/items"

DECISION = """---
title: Which tent?
---

```decision id=D1
options:
  - Dome
  - Tunnel
```
"""

ACTION = """---
title: Put the key into OpenBao
---

```action id=A1
```
"""

RECOMMENDED = """---
title: Camp plan
---

```decision id=D1
options:
  - Dome
  - Tunnel
recommend: Dome
```

```question id=Q1
default: The lake
```
"""

UNREADY = """---
title: Camp chores
---

```question id=Q1
```

```question id=Q2
default: The lake
```
"""

NOTICE = "---\ntitle: The palette\n---\n\nBlue and green.\n"


def _sign_in(
    client: FlaskClient,
    subject: str = "subject-ada",
    roles: tuple[str, ...] = ("editor",),
) -> None:
    response = client.post(
        "/api/testing/auth/session",
        json={"subject": subject, "name": "Ada Example", "roles": list(roles)},
    )
    assert response.status_code == 201


@pytest.fixture
def camp(container: ServiceContainer, session: Session) -> Project:
    """A created project, with ada a member."""
    created = container.test_data_service().project(
        InventedProjectCreateSchema.model_validate({"name": "Camp", "members": ["ada"]})
    )
    return session.get_one(Project, created.id)


@pytest.fixture
def run(session: Session, camp: Project, environment: Environment) -> models.Session:
    """An idle work session of `camp`, which adds its items."""
    work = models.Session(
        project_id=camp.id,
        environment_id=environment.id,
        kind_code="work",
        cwd="/work/Camp",
        token_hash=uuid.uuid4().hex * 2,
        state_code=SessionState.IDLE,
    )
    session.add(work)
    session.flush()
    return work


def _bear(
    container: ServiceContainer,
    camp: Project,
    run: models.Session,
    kind: str,
    text: str,
) -> Item:
    return container.document_service().bear_item(camp, kind, "Which tent?", run, text)


def _block(session: Session, item: Item, local_id: str) -> dsl.Block:
    document = session.get_one(Document, item.id)
    assert document.published_text is not None
    return next(
        block
        for block in dsl.parse(document.published_text).blocks
        if block.local_id == local_id
    )


def _done(item: Item) -> tuple[str | None, uuid.UUID | None]:
    return item.done_cause_code, item.done_by_user_id


def _error(response: Any) -> str:
    error: str = response.get_json()["error"]
    return error


def _entry(client: FlaskClient, camp: Project, item: Item) -> dict[str, Any]:
    """The item's entry on its project's timeline."""
    items = client.get(f"/api/projects/{camp.id}/timeline").get_json()["items"]
    entry: dict[str, Any] = next(
        entry for entry in items if entry["id"] == str(item.id)
    )
    return entry


@pytest.mark.usefixtures("person")
class TestGetItemDocument:
    def test_a_document_reads_as_its_timeline_entry_with_its_project(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
    ) -> None:
        item = _bear(container, camp, run, "document", RECOMMENDED)
        _sign_in(client)

        response = client.get(f"{ITEMS}/{item.id}/document")

        assert response.status_code == 200
        assert response.get_json() == {
            **_entry(client, camp, item),
            "project_id": str(camp.id),
        }

    def test_a_document_done_by_done_reads_as_done_fixed_it(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
        environment: Environment,
    ) -> None:
        item = _bear(container, camp, run, "document", RECOMMENDED)
        _sign_in(client)
        client.post(f"{ITEMS}/{item.id}/done")
        at_done = client.get(f"{ITEMS}/{item.id}/document").get_json()
        document = session.get_one(Document, item.id)
        assert document.published_text is not None
        container.ingest_service().ingest(
            tree_path(camp, document.path),
            f"{document.published_text}\nA lantern too.\n".encode(),
            container.tree_service().hash(camp, document),
            environment,
            run,
        )

        read = client.get(f"{ITEMS}/{item.id}/document").get_json()

        assert read["body"] == at_done["body"]
        assert _entry(client, camp, item)["body"][-1]["markdown"] == "A lantern too."
        assert read["done"]["cause"] == "marked"

    def test_an_unknown_item_is_not_found(self, client: FlaskClient) -> None:
        unknown = uuid.uuid4()
        _sign_in(client)

        response = client.get(f"{ITEMS}/{unknown}/document")

        assert response.status_code == 404
        assert _error(response) == f"Document of item {unknown} was not found"

    def test_work_has_no_document(
        self,
        client: FlaskClient,
        session: Session,
        camp: Project,
        run: models.Session,
    ) -> None:
        session.add(
            Item(
                id=run.id,
                project_id=camp.id,
                seq=2,
                kind_code="work",
                title="Build the camp",
                created_by_session_id=run.id,
            )
        )
        session.flush()
        _sign_in(client)

        response = client.get(f"{ITEMS}/{run.id}/document")

        assert response.status_code == 404
        assert _error(response) == f"Document of item {run.id} was not found"

    def test_an_id_that_is_no_uuid_is_not_found(self, client: FlaskClient) -> None:
        _sign_in(client)

        assert client.get(f"{ITEMS}/camp/document").status_code == 404

    def test_without_editor_it_is_refused(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
    ) -> None:
        item = _bear(container, camp, run, "notice", NOTICE)
        _sign_in(client, roles=())

        assert client.get(f"{ITEMS}/{item.id}/document").status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.get(f"{ITEMS}/{uuid.uuid4()}/document").status_code == 401


@pytest.mark.usefixtures("person")
class TestAnswerBlock:
    def test_the_answer_and_its_note_are_recorded(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
        person: User,
    ) -> None:
        item = _bear(container, camp, run, "decision", DECISION)
        _sign_in(client)

        response = client.post(
            f"{ITEMS}/{item.id}/blocks/D1/answer",
            json={"answer": "Tunnel", "note": "More room."},
        )

        assert response.status_code == 204
        assert response.data == b""
        block = _block(session, item, "D1")
        assert (block.answer, block.by, block.note) == ("Tunnel", "ada", "More room.")
        assert _done(item) == ("answered", person.id)

    def test_the_note_may_be_left_out(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
    ) -> None:
        item = _bear(container, camp, run, "decision", DECISION)
        _sign_in(client)

        response = client.post(
            f"{ITEMS}/{item.id}/blocks/D1/answer", json={"answer": "Dome"}
        )

        assert response.status_code == 204
        assert (
            _block(session, item, "D1").answer,
            _block(session, item, "D1").note,
        ) == (
            "Dome",
            None,
        )

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"answer": None},
            {"answer": 3},
            {"answer": "Dome", "note": 3},
            {"answer": "Dome", "via": "chat"},
            {"answer": "deferred", "to": "plan"},
        ],
    )
    def test_a_body_that_is_no_answer_is_invalid(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
        body: dict[str, Any],
    ) -> None:
        item = _bear(container, camp, run, "decision", DECISION)
        _sign_in(client)

        response = client.post(f"{ITEMS}/{item.id}/blocks/D1/answer", json=body)

        assert response.status_code == 400
        assert item.done_at is None

    def test_an_unknown_item_is_not_found(self, client: FlaskClient) -> None:
        unknown = uuid.uuid4()
        _sign_in(client)

        response = client.post(
            f"{ITEMS}/{unknown}/blocks/D1/answer", json={"answer": "Dome"}
        )

        assert response.status_code == 404
        assert _error(response) == f"Item {unknown} was not found"

    def test_an_id_that_is_no_uuid_is_not_found(self, client: FlaskClient) -> None:
        _sign_in(client)

        response = client.post(
            f"{ITEMS}/tent/blocks/D1/answer", json={"answer": "Dome"}
        )

        assert response.status_code == 404

    def test_a_block_the_item_lacks_is_not_found(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
    ) -> None:
        item = _bear(container, camp, run, "decision", DECISION)
        _sign_in(client)

        response = client.post(
            f"{ITEMS}/{item.id}/blocks/D9/answer", json={"answer": "Dome"}
        )

        assert response.status_code == 404
        assert _error(response) == f"Block {item.id}/D9 was not found"

    def test_an_answer_the_record_refuses_conflicts(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
    ) -> None:
        item = _bear(container, camp, run, "decision", DECISION)
        _sign_in(client)
        client.post(f"{ITEMS}/{item.id}/blocks/D1/answer", json={"answer": "Dome"})

        response = client.post(
            f"{ITEMS}/{item.id}/blocks/D1/answer", json={"answer": "Tunnel"}
        )

        assert response.status_code == 409
        assert _error(response).endswith("the item is done")

    def test_a_blank_answer_conflicts(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
    ) -> None:
        item = _bear(container, camp, run, "decision", DECISION)
        _sign_in(client)

        response = client.post(
            f"{ITEMS}/{item.id}/blocks/D1/answer", json={"answer": "  "}
        )

        assert response.status_code == 409
        assert _error(response).endswith("the answer is blank")

    def test_a_caller_without_a_handle_conflicts(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
    ) -> None:
        item = _bear(container, camp, run, "decision", DECISION)
        _sign_in(client, subject="subject-newcomer")

        response = client.post(
            f"{ITEMS}/{item.id}/blocks/D1/answer", json={"answer": "Dome"}
        )

        assert response.status_code == 409
        assert _error(response).endswith("you have not chosen your handle yet")

    def test_without_editor_it_is_refused(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
    ) -> None:
        item = _bear(container, camp, run, "decision", DECISION)
        _sign_in(client, roles=())

        response = client.post(
            f"{ITEMS}/{item.id}/blocks/D1/answer", json={"answer": "Dome"}
        )

        assert response.status_code == 403
        assert item.done_at is None

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.post(
            f"{ITEMS}/{uuid.uuid4()}/blocks/D1/answer", json={"answer": "Dome"}
        )

        assert response.status_code == 401


@pytest.mark.usefixtures("person")
class TestMarkActionDone:
    def test_done_and_its_paste_back_are_recorded(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
        person: User,
    ) -> None:
        item = _bear(container, camp, run, "action", ACTION)
        _sign_in(client)

        response = client.post(
            f"{ITEMS}/{item.id}/blocks/A1/done", json={"note": "Stored at kv/camp"}
        )

        assert response.status_code == 204
        block = _block(session, item, "A1")
        assert (block.by, block.note) == ("ada", "Stored at kv/camp")
        assert block.done is not None
        assert _done(item) == ("answered", person.id)

    def test_the_paste_back_may_be_left_out(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
    ) -> None:
        item = _bear(container, camp, run, "action", ACTION)
        _sign_in(client)

        response = client.post(f"{ITEMS}/{item.id}/blocks/A1/done", json={})

        assert response.status_code == 204
        assert _block(session, item, "A1").note is None

    @pytest.mark.parametrize("body", [{"note": 3}, {"note": "Done", "answer": "Dome"}])
    def test_a_body_that_is_no_done_is_invalid(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
        body: dict[str, Any],
    ) -> None:
        item = _bear(container, camp, run, "action", ACTION)
        _sign_in(client)

        response = client.post(f"{ITEMS}/{item.id}/blocks/A1/done", json=body)

        assert response.status_code == 400
        assert item.done_at is None

    def test_an_unknown_item_is_not_found(self, client: FlaskClient) -> None:
        unknown = uuid.uuid4()
        _sign_in(client)

        response = client.post(f"{ITEMS}/{unknown}/blocks/A1/done", json={})

        assert response.status_code == 404
        assert _error(response) == f"Item {unknown} was not found"

    def test_a_block_the_item_lacks_is_not_found(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
    ) -> None:
        item = _bear(container, camp, run, "action", ACTION)
        _sign_in(client)

        response = client.post(f"{ITEMS}/{item.id}/blocks/A9/done", json={})

        assert response.status_code == 404
        assert _error(response) == f"Block {item.id}/A9 was not found"

    def test_done_on_a_block_that_is_no_action_conflicts(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
    ) -> None:
        item = _bear(container, camp, run, "decision", DECISION)
        _sign_in(client)

        response = client.post(f"{ITEMS}/{item.id}/blocks/D1/done", json={})

        assert response.status_code == 409
        assert _error(response).endswith("block D1 is a decision, not an action")

    def test_a_caller_without_a_handle_conflicts(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
    ) -> None:
        item = _bear(container, camp, run, "action", ACTION)
        _sign_in(client, subject="subject-newcomer")

        response = client.post(f"{ITEMS}/{item.id}/blocks/A1/done", json={})

        assert response.status_code == 409
        assert _error(response).endswith("you have not chosen your handle yet")

    def test_without_editor_it_is_refused(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
    ) -> None:
        item = _bear(container, camp, run, "action", ACTION)
        _sign_in(client, roles=())

        response = client.post(f"{ITEMS}/{item.id}/blocks/A1/done", json={})

        assert response.status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.post(f"{ITEMS}/{uuid.uuid4()}/blocks/A1/done", json={})

        assert response.status_code == 401


@pytest.mark.usefixtures("person")
class TestMarks:
    """Done on a document, Read on a notice, Reviewed on a review."""

    @pytest.mark.parametrize(
        ("kind", "text", "mark"),
        [
            ("notice", NOTICE, "read"),
            ("review", NOTICE, "reviewed"),
            ("document", RECOMMENDED, "done"),
        ],
    )
    def test_the_mark_is_recorded(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
        person: User,
        kind: str,
        text: str,
        mark: str,
    ) -> None:
        item = _bear(container, camp, run, kind, text)
        _sign_in(client)

        response = client.post(f"{ITEMS}/{item.id}/{mark}")

        assert response.status_code == 204
        assert response.data == b""
        assert _done(item) == ("marked", person.id)

    def test_done_answers_the_recommendations(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
    ) -> None:
        item = _bear(container, camp, run, "document", RECOMMENDED)
        _sign_in(client)

        client.post(f"{ITEMS}/{item.id}/done")

        assert [
            (block.answer, block.by, block.via)
            for block in (_block(session, item, "D1"), _block(session, item, "Q1"))
        ] == [("Dome", "ada", "recommended"), ("The lake", "ada", "recommended")]

    @pytest.mark.parametrize(
        ("kind", "text", "mark", "cause"),
        [
            ("review", NOTICE, "read", "a review item is not marked Read"),
            ("notice", NOTICE, "reviewed", "a notice item is not marked Reviewed"),
            ("decision", DECISION, "done", "a decision item is not done by Done"),
            (
                "document",
                UNREADY,
                "done",
                "these blocks have neither an answer nor a recommendation: Q1",
            ),
        ],
    )
    def test_a_mark_the_record_refuses_conflicts(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
        kind: str,
        text: str,
        mark: str,
        cause: str,
    ) -> None:
        item = _bear(container, camp, run, kind, text)
        _sign_in(client)

        response = client.post(f"{ITEMS}/{item.id}/{mark}")

        assert response.status_code == 409
        assert _error(response).endswith(cause)
        assert item.done_at is None

    @pytest.mark.parametrize("mark", ["read", "reviewed", "done"])
    def test_an_unknown_item_is_not_found(self, client: FlaskClient, mark: str) -> None:
        unknown = uuid.uuid4()
        _sign_in(client)

        response = client.post(f"{ITEMS}/{unknown}/{mark}")

        assert response.status_code == 404
        assert _error(response) == f"Item {unknown} was not found"

    @pytest.mark.parametrize("mark", ["read", "reviewed", "done"])
    def test_a_caller_without_a_handle_conflicts(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
        mark: str,
    ) -> None:
        item = _bear(container, camp, run, "notice", NOTICE)
        _sign_in(client, subject="subject-newcomer")

        response = client.post(f"{ITEMS}/{item.id}/{mark}")

        assert response.status_code == 409
        assert _error(response).endswith("you have not chosen your handle yet")

    @pytest.mark.parametrize("mark", ["read", "reviewed", "done"])
    def test_without_editor_it_is_refused(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
        mark: str,
    ) -> None:
        item = _bear(container, camp, run, "notice", NOTICE)
        _sign_in(client, roles=())

        assert client.post(f"{ITEMS}/{item.id}/{mark}").status_code == 403

    @pytest.mark.parametrize("mark", ["read", "reviewed", "done"])
    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient, mark: str
    ) -> None:
        assert oidc_client.post(f"{ITEMS}/{uuid.uuid4()}/{mark}").status_code == 401


@pytest.mark.usefixtures("person")
class TestUndo:
    def test_undo_of_an_answer_opens_the_item_and_clears_it(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
    ) -> None:
        item = _bear(container, camp, run, "decision", DECISION)
        _sign_in(client)
        client.post(f"{ITEMS}/{item.id}/blocks/D1/answer", json={"answer": "Dome"})

        response = client.post(f"{ITEMS}/{item.id}/undo")

        assert response.status_code == 204
        assert response.data == b""
        assert _done(item) == (None, None)
        assert _block(session, item, "D1").answer is None

    def test_undo_of_another_persons_mark(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
    ) -> None:
        ben = container.test_data_service().person("ben", "Ben Example")
        item = _bear(container, camp, run, "notice", NOTICE)
        container.record_service().read(item, ben)
        _sign_in(client)

        response = client.post(f"{ITEMS}/{item.id}/undo")

        assert response.status_code == 204
        assert _done(item) == (None, None)

    def test_undo_the_record_refuses_conflicts(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
    ) -> None:
        item = _bear(container, camp, run, "decision", DECISION)
        _sign_in(client)

        response = client.post(f"{ITEMS}/{item.id}/undo")

        assert response.status_code == 409
        assert _error(response).endswith("the item is not done")

    def test_an_unknown_item_is_not_found(self, client: FlaskClient) -> None:
        unknown = uuid.uuid4()
        _sign_in(client)

        response = client.post(f"{ITEMS}/{unknown}/undo")

        assert response.status_code == 404
        assert _error(response) == f"Item {unknown} was not found"

    def test_without_editor_it_is_refused(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
        person: User,
    ) -> None:
        item = _bear(container, camp, run, "notice", NOTICE)
        container.record_service().read(item, person)
        _sign_in(client, roles=())

        assert client.post(f"{ITEMS}/{item.id}/undo").status_code == 403
        assert item.done_at is not None

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.post(f"{ITEMS}/{uuid.uuid4()}/undo").status_code == 401


@pytest.fixture
def second_browser(
    container: ServiceContainer, person: User
) -> Iterator[SSEConnection]:
    """ada's connection in another browser, with the live event's service on
    the app's bus."""
    clear_after_commit_callbacks()
    bus = container.engine_bus()
    manager = container.sse_connection_manager()
    service = ProjectEventService(container, bus, manager)
    connection = manager.on_connect("ada-other-browser", person.subject)
    yield connection
    manager.on_disconnect(connection)
    bus.unsubscribe(service.deliver)
    clear_after_commit_callbacks()


def _heard(connection: SSEConnection) -> list[dict[str, Any]]:
    queued = []
    while True:
        try:
            frame = connection.next_frame(timeout=0)
        except Empty:
            return queued
        assert frame is not None
        queued.append(json.loads(frame.removeprefix("data: ")))


@pytest.mark.usefixtures("person")
class TestTheLiveEvent:
    @pytest.mark.parametrize(
        ("kind", "text", "path", "body"),
        [
            ("decision", DECISION, "blocks/D1/answer", {"answer": "Dome"}),
            ("action", ACTION, "blocks/A1/done", {"note": "Stored"}),
            ("document", RECOMMENDED, "done", None),
            ("notice", NOTICE, "read", None),
            ("review", NOTICE, "reviewed", None),
        ],
    )
    def test_a_write_is_heard_once_in_another_browser(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
        second_browser: SSEConnection,
        kind: str,
        text: str,
        path: str,
        body: dict[str, str] | None,
    ) -> None:
        item = _bear(container, camp, run, kind, text)
        _sign_in(client)
        clear_after_commit_callbacks()
        _heard(second_browser)

        response = client.post(f"{ITEMS}/{item.id}/{path}", json=body)

        assert response.status_code == 204
        assert _heard(second_browser) == [
            {"type": "project_changed", "payload": {"project_id": str(camp.id)}}
        ]

    def test_undo_is_heard_in_another_browser(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
        second_browser: SSEConnection,
    ) -> None:
        item = _bear(container, camp, run, "decision", DECISION)
        _sign_in(client)
        client.post(f"{ITEMS}/{item.id}/blocks/D1/answer", json={"answer": "Dome"})
        _heard(second_browser)

        client.post(f"{ITEMS}/{item.id}/undo")

        assert _heard(second_browser) == [
            {"type": "project_changed", "payload": {"project_id": str(camp.id)}}
        ]

    def test_a_refused_write_is_heard_nowhere(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
        second_browser: SSEConnection,
    ) -> None:
        item = _bear(container, camp, run, "decision", DECISION)
        _sign_in(client)
        clear_after_commit_callbacks()
        _heard(second_browser)

        response = client.post(f"{ITEMS}/{item.id}/undo")

        assert response.status_code == 409
        assert _heard(second_browser) == []

    def test_finish_is_heard_in_another_browser(
        self,
        client: FlaskClient,
        camp: Project,
        second_browser: SSEConnection,
    ) -> None:
        _sign_in(client)
        clear_after_commit_callbacks()
        _heard(second_browser)

        response = client.post(
            f"/api/projects/{camp.id}/transitions", json={"kind": "finished"}
        )

        assert response.status_code == 201
        assert _heard(second_browser) == [
            {"type": "project_changed", "payload": {"project_id": str(camp.id)}}
        ]
