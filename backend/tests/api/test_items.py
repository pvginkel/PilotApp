"""/api/items: what the signed-in person does to a timeline's items — answer
a block, mark an action Done, mark a document Done, a notice Read, a review
Reviewed, and undo (F14, F17, F32.4), none of it on a document Pilot is
working on or a block it holds (DB 295); Stop and take over (F28.9); and the
live event each sends (F80.2). And an item's document read on its own (F28,
F13.3), and a person's request of a wait (F27.3)."""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from queue import Empty
from typing import Any

import pilot_dsl as dsl
import pytest
from dependency_injector import providers
from flask.testing import FlaskClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.engine.paths import tree_path
from app.models import (
    DebriefEntry,
    Document,
    Environment,
    Item,
    PilotNote,
    Project,
    User,
    WaitFiring,
    Work,
)
from app.models.reference import FiringCause, ProjectState, SessionState
from app.schemas.testing_record import InventedProjectCreateSchema
from app.schemas.timeline import ItemDocumentSchema
from app.services.container import ServiceContainer
from app.services.project_event_service import ProjectEventService
from app.services.sse_connection_manager import SSEConnection
from app.utils.after_commit import clear_after_commit_callbacks
from app.utils.sender import SENDER_HEADER
from tests.support.debriefs import placed_notice
from tests.support.pilot_notes import a_turn, noted
from tests.support.starts import configured_starts
from tests.support.supervisor import Supervise
from tests.support.working_on import Camp

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
    def test_a_document_is_answered_as_read_and_never_validated_again(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        item = _bear(container, camp, run, "document", RECOMMENDED)
        _sign_in(client)
        expected = container.timeline_service().item_document(item.id)

        def validated_again(*_: object, **__: object) -> None:
            raise AssertionError("the document was validated again")

        monkeypatch.setattr(ItemDocumentSchema, "model_validate", validated_again)
        monkeypatch.setattr(ItemDocumentSchema, "model_validate_json", validated_again)
        response = client.get(f"{ITEMS}/{item.id}/document")

        assert response.status_code == 200
        assert response.get_json() == expected.model_dump(mode="json")

    def test_a_document_reads_as_its_timeline_entry_with_its_project(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
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
            "text": session.get_one(Document, item.id).published_text,
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
        assert read["text"] == at_done["text"]
        assert "A lantern too." not in read["text"]
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


def _debriefed(
    container: ServiceContainer,
    session: Session,
    camp: Project,
    run: models.Session,
    *,
    done: bool,
) -> None:
    """The run's work item, its debrief given with two entries, its turn
    ended where `done`."""
    container.record_service().place_work(
        camp, run, "Build the camp", repo="example/Camp"
    )
    session.get_one(Work, run.id).debrief = "It went well, if slowly."
    session.add_all(
        [
            DebriefEntry(
                work_id=run.id,
                position=1,
                section="P1 · The client",
                round=1,
                role="code-writer",
                duration=540,
                words="Fine.",
            ),
            DebriefEntry(
                work_id=run.id,
                position=2,
                section="Completion check",
                round=2,
                role="sweep",
                duration=600,
                passed=False,
                why="The sweep went red",
            ),
        ]
    )
    session.flush()
    if done:
        container.record_service().work_done(
            run.id, datetime(2026, 11, 14, 9, 30, tzinfo=UTC)
        )


@pytest.mark.usefixtures("person")
class TestGetItemDebrief:
    def test_a_done_work_items_debrief_is_answered_in_its_sections(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
    ) -> None:
        _debriefed(container, session, camp, run, done=True)
        _sign_in(client)

        response = client.get(f"{ITEMS}/{run.id}/debrief")

        assert (response.status_code, response.get_json()) == (
            200,
            {
                "debrief": "It went well, if slowly.",
                "sections": [
                    {
                        "name": "P1 · The client",
                        "rounds": 1,
                        "duration": 540,
                        "entries": [
                            {
                                "round": 1,
                                "role": "code-writer",
                                "duration": 540,
                                "words": "Fine.",
                                "passed": None,
                                "why": None,
                            }
                        ],
                    },
                    {
                        "name": "Completion check",
                        "rounds": 1,
                        "duration": 600,
                        "entries": [
                            {
                                "round": 2,
                                "role": "sweep",
                                "duration": 600,
                                "words": None,
                                "passed": False,
                                "why": "The sweep went red",
                            }
                        ],
                    },
                ],
            },
        )

    def test_an_open_work_item_and_an_unknown_id_have_none(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
    ) -> None:
        """DB 329: no work item shows its debrief while it runs."""
        _debriefed(container, session, camp, run, done=False)
        _sign_in(client)

        for item_id in (run.id, uuid.uuid4()):
            response = client.get(f"{ITEMS}/{item_id}/debrief")

            assert response.status_code == 404
            assert _error(response) == f"Debrief of work item {item_id} was not found"

    def test_an_id_that_is_no_uuid_is_not_found(self, client: FlaskClient) -> None:
        _sign_in(client)

        assert client.get(f"{ITEMS}/camp/debrief").status_code == 404

    def test_without_editor_it_is_refused(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
    ) -> None:
        _debriefed(container, session, camp, run, done=True)
        _sign_in(client, roles=())

        assert client.get(f"{ITEMS}/{run.id}/debrief").status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.get(f"{ITEMS}/{uuid.uuid4()}/debrief").status_code == 401


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
class TestAnswerArchiveQuestion:
    """The archive question's buttons through the answer route (F5.6; DB 265)."""

    def _question(self, client: FlaskClient, camp: Project) -> dict[str, Any]:
        response = client.post(
            f"/api/projects/{camp.id}/transitions", json={"kind": "finished"}
        )
        assert response.status_code == 201
        items = client.get(f"/api/projects/{camp.id}/timeline").get_json()["items"]
        question: dict[str, Any] = items[-1]
        assert question["kind"] == "archive_question"
        return question

    def test_archive_answers_it_and_archives_the_project(
        self, client: FlaskClient, camp: Project
    ) -> None:
        _sign_in(client)
        question = self._question(client, camp)

        response = client.post(
            f"{ITEMS}/{question['id']}/blocks/D1/answer", json={"answer": "Archive"}
        )

        assert response.status_code == 204
        head = client.get(f"/api/projects/{camp.id}").get_json()
        assert (head["state"], head["archived"]) == ("finished", True)
        (entry,) = [
            entry
            for entry in client.get(f"/api/projects/{camp.id}/timeline").get_json()[
                "items"
            ]
            if entry["id"] == question["id"]
        ]
        assert (entry["done"]["cause"], entry["done"]["undo"]) == ("answered", False)

    def test_keep_answers_it_with_no_undo_and_the_project_stays(
        self, client: FlaskClient, camp: Project
    ) -> None:
        _sign_in(client)
        question = self._question(client, camp)

        response = client.post(
            f"{ITEMS}/{question['id']}/blocks/D1/answer", json={"answer": "Keep"}
        )

        assert response.status_code == 204
        head = client.get(f"/api/projects/{camp.id}").get_json()
        assert (head["state"], head["archived"], head["open_items"]) == (
            "finished",
            False,
            0,
        )
        undo = client.post(f"{ITEMS}/{question['id']}/undo")
        assert undo.status_code == 409
        assert "an archive question offers no undo" in _error(undo)

    def test_any_other_answer_is_refused(
        self, client: FlaskClient, camp: Project
    ) -> None:
        _sign_in(client)
        question = self._question(client, camp)

        response = client.post(
            f"{ITEMS}/{question['id']}/blocks/D1/answer", json={"answer": "Later"}
        )

        assert response.status_code == 409
        assert "an archive question is answered Archive or Keep" in _error(response)


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


OFFER = "I can store the key in OpenBao myself."


@pytest.fixture
def placing(container: ServiceContainer, supervise: Supervise) -> Iterator[None]:
    """The routes' session start configured, through which the press places
    Pilot's job."""
    container.session_start_service.override(
        providers.Object(configured_starts(container, supervise))
    )
    try:
        yield
    finally:
        container.session_start_service.reset_last_overriding()


def _offered(
    session: Session, container: ServiceContainer, camp: Project, run: models.Session
) -> tuple[Item, PilotNote]:
    """An action with Pilot's note on it offering work."""
    item = _bear(container, camp, run, "action", ACTION)
    return item, noted(session, item, "A1", a_turn(session, run), offer=OFFER)


@pytest.mark.usefixtures("person")
class TestTakeOffer:
    """The press of the offer of Pilot's note on an action (F168.7; DB 629)."""

    @pytest.mark.usefixtures("placing")
    def test_the_press_places_pilots_job_and_the_action_stays(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
        person: User,
    ) -> None:
        item, note = _offered(session, container, camp, run)
        _sign_in(client)

        response = client.post(
            f"{ITEMS}/{item.id}/blocks/A1/offer", json={"note_id": note.id}
        )

        assert response.status_code == 204
        session.refresh(note)
        assert note.offer_taken_by_user_id == person.id
        job = session.scalars(select(Work).where(Work.trigger_note_id == note.id)).one()
        entry = _entry(client, camp, item)
        assert entry["job"]["id"] == str(job.id)
        assert entry["job"]["title"] == "Starting the work offered on A1"
        (block,) = (part["block"] for part in entry["body"] if part["type"] == "block")
        assert block["pilots_note"]["offer_taken"] is True
        assert (_block(session, item, "A1").done, item.done_at) == (None, None)

    def test_a_second_press_conflicts(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
        person: User,
    ) -> None:
        item, note = _offered(session, container, camp, run)
        note.offer_taken_at, note.offer_taken_by_user_id = datetime.now(UTC), person.id
        session.flush()
        _sign_in(client)

        response = client.post(
            f"{ITEMS}/{item.id}/blocks/A1/offer", json={"note_id": note.id}
        )

        assert response.status_code == 409
        path = tree_path(camp, session.get_one(Document, item.id).path)
        assert _error(response) == (
            f"Cannot take the offer on A1 of {path} because the offer on A1 was"
            " taken already"
        )

    def test_a_note_the_block_lacks_is_not_found(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
    ) -> None:
        item, note = _offered(session, container, camp, run)
        _sign_in(client)

        response = client.post(
            f"{ITEMS}/{item.id}/blocks/A1/offer", json={"note_id": note.id + 1}
        )

        assert response.status_code == 404
        assert _error(response) == (
            f"Pilot Note {item.id}/A1/{note.id + 1} was not found"
        )

    @pytest.mark.parametrize("body", [{}, {"note_id": "A1"}, {"note_id": 1, "x": 1}])
    def test_a_body_that_names_no_note_is_invalid(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
        body: dict[str, Any],
    ) -> None:
        item, _ = _offered(session, container, camp, run)
        _sign_in(client)

        response = client.post(f"{ITEMS}/{item.id}/blocks/A1/offer", json=body)

        assert response.status_code == 400

    def test_without_editor_it_is_refused(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
    ) -> None:
        item, note = _offered(session, container, camp, run)
        _sign_in(client, roles=())

        response = client.post(
            f"{ITEMS}/{item.id}/blocks/A1/offer", json={"note_id": note.id}
        )

        assert response.status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.post(
            f"{ITEMS}/{uuid.uuid4()}/blocks/A1/offer", json={"note_id": 1}
        )

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
class TestSentAgain:
    """A close the same person sends a second time answers as the first did
    and changes nothing (slice 041's R1): a browser sends a request again on
    a new connection."""

    @pytest.mark.parametrize(
        ("kind", "text", "path", "body"),
        [
            ("decision", DECISION, "blocks/D1/answer", {"answer": "Dome"}),
            ("action", ACTION, "blocks/A1/done", {"note": "key-1"}),
            ("document", RECOMMENDED, "done", None),
            ("notice", NOTICE, "read", None),
            ("review", NOTICE, "reviewed", None),
        ],
    )
    def test_every_close_sent_again_is_answered_as_the_first(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
        person: User,
        kind: str,
        text: str,
        path: str,
        body: dict[str, str] | None,
    ) -> None:
        item = _bear(container, camp, run, kind, text)
        _sign_in(client)
        assert client.post(f"{ITEMS}/{item.id}/{path}", json=body).status_code == 204
        published = session.get_one(Document, item.id).published_text
        done = item.done_at

        response = client.post(f"{ITEMS}/{item.id}/{path}", json=body)

        assert response.status_code == 204
        assert response.data == b""
        assert session.get_one(Document, item.id).published_text == published
        assert (item.done_at, item.done_by_user_id) == (done, person.id)

    def test_archive_sent_again_on_the_archive_question_is_answered_as_the_first(
        self, client: FlaskClient, camp: Project
    ) -> None:
        _sign_in(client)
        response = client.post(
            f"/api/projects/{camp.id}/transitions", json={"kind": "finished"}
        )
        assert response.status_code == 201
        timeline = client.get(f"/api/projects/{camp.id}/timeline").get_json()
        answer = f"{ITEMS}/{timeline['items'][-1]['id']}/blocks/D1/answer"
        assert client.post(answer, json={"answer": "Archive"}).status_code == 204
        before = client.get(f"/api/projects/{camp.id}").get_json()

        response = client.post(answer, json={"answer": "Archive"})

        assert response.status_code == 204
        assert response.data == b""
        after = client.get(f"/api/projects/{camp.id}").get_json()
        assert (after["state"], after["archived"]) == ("finished", True)
        assert after == before


@pytest.mark.usefixtures("person")
class TestDebriefNoticeRead:
    """A member's Read of the debrief's notice, and its Undo (DB 613)."""

    def test_read_closes_it_as_theirs_and_undo_reopens_it(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
        person: User,
    ) -> None:
        container.record_service().place_work(camp, run, "Pitching the tent")
        notice = placed_notice(session, container, camp, run)
        _sign_in(client)

        read = client.post(f"{ITEMS}/{notice.id}/read")
        done = _entry(client, camp, notice)["done"]
        undone = client.post(f"{ITEMS}/{notice.id}/undo")

        assert (read.status_code, undone.status_code) == (204, 204)
        assert (done["cause"], done["by"]["handle"], done["undo"]) == (
            "marked",
            "ada",
            True,
        )
        assert _entry(client, camp, notice)["done"] is None
        assert _done(notice) == (None, None)


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


@pytest.mark.usefixtures("person")
class TestInAnArchivedProject:
    """An archived project takes Bring back alone (D012): every close of its
    items and an Undo conflict, naming the archive."""

    @pytest.mark.parametrize(
        ("kind", "text", "path", "body"),
        [
            ("decision", DECISION, "blocks/D1/answer", {"answer": "Dome"}),
            ("action", ACTION, "blocks/A1/done", {}),
            ("document", RECOMMENDED, "done", None),
            ("notice", NOTICE, "read", None),
            ("review", NOTICE, "reviewed", None),
        ],
    )
    def test_every_close_conflicts(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
        kind: str,
        text: str,
        path: str,
        body: dict[str, str] | None,
    ) -> None:
        item = _bear(container, camp, run, kind, text)
        camp.archived = True
        session.flush()
        _sign_in(client)

        response = client.post(f"{ITEMS}/{item.id}/{path}", json=body)

        assert response.status_code == 409
        assert _error(response).endswith("its project is archived")
        assert item.done_at is None

    def test_undo_conflicts(
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
        camp.archived = True
        session.flush()

        response = client.post(f"{ITEMS}/{item.id}/undo")

        assert response.status_code == 409
        assert _error(response).endswith("its project is archived")
        assert item.done_cause_code == "answered"


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

    @pytest.mark.parametrize(
        ("kind", "text", "path", "body"),
        [
            ("decision", DECISION, "blocks/D1/answer", {"answer": "Dome"}),
            ("notice", NOTICE, "read", None),
        ],
    )
    def test_a_write_names_the_page_that_sent_it(
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

        response = client.post(
            f"{ITEMS}/{item.id}/{path}", json=body, headers={SENDER_HEADER: "page1"}
        )

        assert response.status_code == 204
        assert _heard(second_browser) == [
            {
                "type": "project_changed",
                "payload": {"project_id": str(camp.id), "sender": "page1"},
            }
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


def _wait(
    container: ServiceContainer, session: Session, camp: Project, run: models.Session
) -> Item:
    """An open card wait of `camp`'s, opened."""
    camp.state_code = ProjectState.OPEN
    camp.slug = "camp"
    session.flush()
    return container.wait_service().add_card_wait(
        camp, run, "SR-4 is done", ["SR-4"], ["Done"], None
    )


def _requests(
    session: Session, wait: Item
) -> list[tuple[FiringCause, uuid.UUID | None]]:
    return [
        (firing.cause_code, firing.requested_by_user_id)
        for firing in session.scalars(
            select(WaitFiring).where(WaitFiring.wait_id == wait.id)
        )
    ]


@pytest.mark.usefixtures("person")
class TestRequest:
    """A person's request of a wait, its head's button (F27.3)."""

    def test_the_request_fires_the_wait(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
        person: User,
    ) -> None:
        wait = _wait(container, session, camp, run)
        _sign_in(client)

        response = client.post(f"{ITEMS}/{wait.id}/request")

        assert response.status_code == 204
        assert response.data == b""
        assert _requests(session, wait) == [(FiringCause.REQUESTED, person.id)]

    def test_a_wait_that_takes_no_request_now_conflicts(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
    ) -> None:
        wait = _wait(container, session, camp, run)
        _sign_in(client)
        client.post(f"{ITEMS}/{wait.id}/request")

        response = client.post(f"{ITEMS}/{wait.id}/request")

        assert response.status_code == 409
        assert _error(response) == (
            f"Cannot request a firing of item {wait.id} because Pilot is checking"
        )
        assert len(_requests(session, wait)) == 1

    def test_an_item_that_is_no_wait_conflicts(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
    ) -> None:
        item = _bear(container, camp, run, "notice", NOTICE)
        _sign_in(client)

        response = client.post(f"{ITEMS}/{item.id}/request")

        assert response.status_code == 409
        assert _error(response).endswith("a notice item takes no request")

    def test_an_unknown_item_is_not_found(self, client: FlaskClient) -> None:
        unknown = uuid.uuid4()
        _sign_in(client)

        response = client.post(f"{ITEMS}/{unknown}/request")

        assert response.status_code == 404
        assert _error(response) == f"Item {unknown} was not found"

    def test_a_caller_without_a_handle_conflicts(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
    ) -> None:
        wait = _wait(container, session, camp, run)
        _sign_in(client, subject="subject-newcomer")

        response = client.post(f"{ITEMS}/{wait.id}/request")

        assert response.status_code == 409
        assert _error(response).endswith("you have not chosen your handle yet")
        assert _requests(session, wait) == []

    def test_without_editor_it_is_refused(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
    ) -> None:
        wait = _wait(container, session, camp, run)
        _sign_in(client, roles=())

        assert client.post(f"{ITEMS}/{wait.id}/request").status_code == 403


PITCH = """# Where do we pitch?

```question id=Q1
```

```decision id=D1
options:
  - Lake
  - Hill
```
"""


@pytest.fixture
def working(container: ServiceContainer, session: Session, person: User) -> Camp:
    """A project's record of Pilot's work, ada a member."""
    return Camp(container, session)


def _under_its_pass(working: Camp) -> tuple[Item, models.Session]:
    """A document a worker registered, read, and its pass running."""
    run = working.worker()
    pitch = working.registered(run, PITCH)
    working.ended(run)
    return pitch, working.job_after(run)


class TestTakeOver:
    def test_it_stops_the_pass_and_the_document_is_the_callers(
        self,
        client: FlaskClient,
        working: Camp,
        person: User,
        second_browser: SSEConnection,
    ) -> None:
        pitch, job = _under_its_pass(working)
        _sign_in(client)
        clear_after_commit_callbacks()
        _heard(second_browser)

        response = client.post(f"{ITEMS}/{pitch.id}/take-over")

        assert response.status_code == 204
        assert response.data == b""
        working.session.refresh(job)
        assert (job.state_code, job.stopped_by_user_id) == (
            SessionState.STOPPED,
            person.id,
        )
        assert _entry(client, working.project, pitch)["pilots_work"] is None
        assert {
            "type": "project_changed",
            "payload": {"project_id": str(working.project.id)},
        } in _heard(second_browser)

    def test_a_document_pilot_is_not_working_on_is_refused_with_why(
        self, client: FlaskClient, working: Camp
    ) -> None:
        pitch, job = _under_its_pass(working)
        working.ended(job)
        _sign_in(client)

        response = client.post(f"{ITEMS}/{pitch.id}/take-over")

        assert response.status_code == 409
        assert _error(response) == (
            f"Cannot stop and take over item {pitch.id} because Pilot is not"
            " working on it"
        )

    def test_an_unknown_item_is_not_found(self, client: FlaskClient) -> None:
        _sign_in(client)

        response = client.post(f"{ITEMS}/{uuid.uuid4()}/take-over")

        assert response.status_code == 404

    def test_without_the_editor_role_it_is_forbidden(
        self, client: FlaskClient, working: Camp
    ) -> None:
        pitch, job = _under_its_pass(working)
        _sign_in(client, roles=())

        assert client.post(f"{ITEMS}/{pitch.id}/take-over").status_code == 403
        assert job.state_code == SessionState.RUNNING

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.post(f"{ITEMS}/{uuid.uuid4()}/request").status_code == 401
        response = oidc_client.post(f"{ITEMS}/{uuid.uuid4()}/take-over")

        assert response.status_code == 401


CUT_OVER = """# The cut-over

```action id=A1
answer: Pilot does it
by: agent
at: 2026-11-02T09:00:00Z
```
"""


def _run_waits(working: Camp) -> tuple[Item, Item]:
    """A claimed action whose work item asked the person a question, its
    turn and the job after it ended: the held document and the question."""
    writer = working.worker()
    cut_over = working.registered(writer, CUT_OVER)
    working.ended(writer)
    working.ended(working.job_after(writer))
    doing = working.worker(conversation="conversation-2")
    working.claim(cut_over, "A1", doing)
    question = working.registered(doing, PITCH)
    working.ended(doing)
    working.ended(working.job_after(doing))
    return cut_over, question


class TestCancel:
    def test_it_ends_the_run_and_the_action_is_the_callers(
        self,
        client: FlaskClient,
        working: Camp,
        person: User,
        second_browser: SSEConnection,
    ) -> None:
        cut_over, question = _run_waits(working)
        _sign_in(client)
        assert _entry(client, working.project, question)["cancel"] is not None
        clear_after_commit_callbacks()
        _heard(second_browser)

        response = client.post(f"{ITEMS}/{question.id}/cancel")

        assert response.status_code == 204
        assert response.data == b""
        working.session.refresh(question)
        assert _done(question) == ("cancelled", person.id)
        entry = _entry(client, working.project, cut_over)
        assert entry["pilots_work"] is None
        (block,) = [part["block"] for part in entry["body"] if part["type"] == "block"]
        assert block["claim"]["undone"] is True
        assert {
            "type": "project_changed",
            "payload": {"project_id": str(working.project.id)},
        } in _heard(second_browser)

    def test_a_document_whose_run_holds_nothing_is_refused_with_why(
        self, client: FlaskClient, working: Camp
    ) -> None:
        pitch, job = _under_its_pass(working)
        working.ended(job)
        _sign_in(client)

        response = client.post(f"{ITEMS}/{pitch.id}/cancel")

        assert response.status_code == 409
        assert _error(response) == (
            f"Cannot cancel item {pitch.id} because its run holds no block of"
            " another document"
        )

    def test_an_unknown_item_is_not_found(self, client: FlaskClient) -> None:
        _sign_in(client)

        response = client.post(f"{ITEMS}/{uuid.uuid4()}/cancel")

        assert response.status_code == 404

    def test_without_the_editor_role_it_is_forbidden(
        self, client: FlaskClient, working: Camp
    ) -> None:
        _, question = _run_waits(working)
        _sign_in(client, roles=())

        assert client.post(f"{ITEMS}/{question.id}/cancel").status_code == 403
        assert question.done_at is None

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.post(f"{ITEMS}/{uuid.uuid4()}/cancel")

        assert response.status_code == 401


class TestWhilePilotWorks:
    def test_an_answer_on_a_document_under_its_pass_is_refused_with_why(
        self, client: FlaskClient, working: Camp
    ) -> None:
        pitch, _ = _under_its_pass(working)
        _sign_in(client)

        response = client.post(
            f"{ITEMS}/{pitch.id}/blocks/D1/answer", json={"answer": "Lake"}
        )

        assert response.status_code == 409
        assert _error(response) == (
            f"Cannot answer block D1 of item {pitch.id} because Pilot is working"
            " on the item"
        )

    def test_an_answer_on_a_held_block_is_refused_with_why(
        self, client: FlaskClient, working: Camp
    ) -> None:
        pitch, job = _under_its_pass(working)
        working.ended(job)
        working.research(pitch, "Q1", working.worker(conversation="conversation-2"))
        _sign_in(client)

        response = client.post(
            f"{ITEMS}/{pitch.id}/blocks/Q1/answer", json={"answer": "The lake"}
        )

        assert response.status_code == 409
        assert _error(response).endswith("because Pilot is working on block Q1")


@pytest.mark.usefixtures("person")
class TestFold:
    """`POST /api/items/<id>/fold` and `/unfold` (F12.3; DB 316 to 321)."""

    def test_a_fold_shows_on_the_timeline_and_tells_every_page(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
        second_browser: SSEConnection,
    ) -> None:
        item = _bear(container, camp, run, "decision", DECISION)
        _sign_in(client)
        assert _entry(client, camp, item)["folded"] is False
        clear_after_commit_callbacks()
        _heard(second_browser)

        response = client.post(f"{ITEMS}/{item.id}/fold")

        assert response.status_code == 204
        assert response.data == b""
        entry = _entry(client, camp, item)
        assert (entry["folded"], entry["done"]) == (True, None)
        assert _heard(second_browser) == [
            {"type": "project_changed", "payload": {"project_id": str(camp.id)}}
        ]

    def test_an_unfold_shows_on_the_timeline_and_tells_every_page(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
        second_browser: SSEConnection,
    ) -> None:
        item = _bear(container, camp, run, "decision", DECISION)
        _sign_in(client)
        client.post(f"{ITEMS}/{item.id}/fold")
        clear_after_commit_callbacks()
        _heard(second_browser)

        response = client.post(f"{ITEMS}/{item.id}/unfold")

        assert response.status_code == 204
        assert response.data == b""
        assert _entry(client, camp, item)["folded"] is False
        assert _heard(second_browser) == [
            {"type": "project_changed", "payload": {"project_id": str(camp.id)}}
        ]

    @pytest.mark.parametrize("act", ["fold", "unfold"])
    def test_one_that_stands_already_is_taken_and_tells_no_page(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
        second_browser: SSEConnection,
        act: str,
    ) -> None:
        item = _bear(container, camp, run, "decision", DECISION)
        _sign_in(client)
        if act == "fold":
            client.post(f"{ITEMS}/{item.id}/fold")
        clear_after_commit_callbacks()
        _heard(second_browser)

        response = client.post(f"{ITEMS}/{item.id}/{act}")

        assert response.status_code == 204
        assert _entry(client, camp, item)["folded"] is (act == "fold")
        assert _heard(second_browser) == []

    def test_a_caller_without_a_handle_folds(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
    ) -> None:
        item = _bear(container, camp, run, "notice", NOTICE)
        _sign_in(client, subject="subject-newcomer")

        assert client.post(f"{ITEMS}/{item.id}/fold").status_code == 204
        assert client.post(f"{ITEMS}/{item.id}/unfold").status_code == 204

    def test_its_close_clears_it_and_its_undo_brings_it_back_unfolded(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
    ) -> None:
        item = _bear(container, camp, run, "decision", DECISION)
        _sign_in(client)
        client.post(f"{ITEMS}/{item.id}/fold")

        client.post(f"{ITEMS}/{item.id}/blocks/D1/answer", json={"answer": "Dome"})
        closed = _entry(client, camp, item)
        client.post(f"{ITEMS}/{item.id}/undo")

        assert (closed["folded"], closed["done"]["cause"]) == (False, "answered")
        entry = _entry(client, camp, item)
        assert (entry["folded"], entry["done"]) == (False, None)

    @pytest.mark.parametrize("act", ["fold", "unfold"])
    def test_a_done_item_conflicts(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        person: User,
        camp: Project,
        run: models.Session,
        act: str,
    ) -> None:
        item = _bear(container, camp, run, "notice", NOTICE)
        container.record_service().read(item, person)
        _sign_in(client)

        response = client.post(f"{ITEMS}/{item.id}/{act}")

        assert response.status_code == 409
        assert _error(response) == (
            f"Cannot {act} item {item.id} because the item is done"
        )

    @pytest.mark.parametrize("act", ["fold", "unfold"])
    def test_an_item_pilot_is_working_on_conflicts(
        self, client: FlaskClient, working: Camp, act: str
    ) -> None:
        pitch, _ = _under_its_pass(working)
        _sign_in(client)

        response = client.post(f"{ITEMS}/{pitch.id}/{act}")

        assert response.status_code == 409
        assert _error(response) == (
            f"Cannot {act} item {pitch.id} because Pilot is working on the item"
        )
        working.session.refresh(pitch)
        assert pitch.folded is False

    def test_a_folded_item_pilot_comes_to_work_on_keeps_its_fold(
        self, client: FlaskClient, working: Camp
    ) -> None:
        run = working.worker()
        pitch = working.registered(run, PITCH)
        working.ended(run)
        _sign_in(client)
        assert client.post(f"{ITEMS}/{pitch.id}/fold").status_code == 204

        job = working.job_after(run)
        pilots = _entry(client, working.project, pitch)
        working.ended(job)

        assert pilots["pilots_work"] is not None
        assert pilots["folded"] is True
        entry = _entry(client, working.project, pitch)
        assert (entry["pilots_work"], entry["folded"]) == (None, True)

    def test_an_archived_projects_item_conflicts(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        camp: Project,
        run: models.Session,
    ) -> None:
        item = _bear(container, camp, run, "notice", NOTICE)
        camp.archived = True
        session.flush()
        _sign_in(client)

        response = client.post(f"{ITEMS}/{item.id}/fold")

        assert response.status_code == 409
        assert _error(response) == (
            f"Cannot fold item {item.id} because its project is archived"
        )

    def test_the_opening_conflicts(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        person: User,
        camp: Project,
    ) -> None:
        opening = container.document_service().bear_opening(
            camp, "Camp", person, "Let's camp.\n"
        )
        _sign_in(client)

        response = client.post(f"{ITEMS}/{opening.id}/fold")

        assert response.status_code == 409
        assert _error(response) == (
            f"Cannot fold item {opening.id} because the opening does not fold"
        )

    @pytest.mark.parametrize("act", ["fold", "unfold"])
    def test_an_unknown_item_is_not_found(self, client: FlaskClient, act: str) -> None:
        _sign_in(client)

        assert client.post(f"{ITEMS}/{uuid.uuid4()}/{act}").status_code == 404

    @pytest.mark.parametrize("act", ["fold", "unfold"])
    def test_without_the_editor_role_it_is_forbidden(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        camp: Project,
        run: models.Session,
        act: str,
    ) -> None:
        item = _bear(container, camp, run, "notice", NOTICE)
        _sign_in(client, roles=())

        assert client.post(f"{ITEMS}/{item.id}/{act}").status_code == 403
        assert item.folded is False

    @pytest.mark.parametrize("act", ["fold", "unfold"])
    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient, act: str
    ) -> None:
        response = oidc_client.post(f"{ITEMS}/{uuid.uuid4()}/{act}")

        assert response.status_code == 401
