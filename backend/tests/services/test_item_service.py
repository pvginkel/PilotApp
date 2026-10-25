"""What a person does to an item on the timeline, by the item's id and a
block's local id (F30.7): each the record's own write (F32.4), its refusals
the caller's."""

import uuid

import pilot_dsl as dsl
import pytest
from sqlalchemy.orm import Session as DbSession

from app import models
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import Document, Item, Project, User
from app.services.auth_service import AuthContext
from app.services.container import ServiceContainer

ADA = AuthContext(
    subject="subject-ada", email=None, name="Ada Example", roles={"editor"}
)
"""The `person` fixture, signed in."""

NEWCOMER = AuthContext(
    subject="subject-newcomer", email=None, name="Nia Newcomer", roles={"editor"}
)
"""A person at their first sign-in, with no handle yet."""

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

NOTICE = "---\ntitle: The palette\n---\n\nBlue and green.\n"

NO_HANDLE = "you have not chosen your handle yet"


def _bear(
    container: ServiceContainer,
    project: Project,
    project_session: models.Session,
    kind: str,
    text: str,
) -> Item:
    return container.document_service().bear_item(
        project, kind, "Which tent?", project_session, text
    )


def _block(session: DbSession, item: Item, local_id: str) -> dsl.Block:
    document = session.get_one(Document, item.id)
    assert document.published_text is not None
    return next(
        block
        for block in dsl.parse(document.published_text).blocks
        if block.local_id == local_id
    )


def _work(
    session: DbSession, project: Project, project_session: models.Session
) -> Item:
    """An open work item, which has no text."""
    item = Item(
        project_id=project.id,
        seq=1,
        kind_code="work",
        title="Build the camp",
        created_by_session_id=project_session.id,
    )
    session.add(item)
    session.flush()
    return item


@pytest.mark.usefixtures("person")
class TestItemServiceAnswer:
    def test_the_callers_answer_and_note_are_the_records(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item = _bear(container, project, project_session, "decision", DECISION)

        container.item_service().answer(ADA, item.id, "D1", "Tunnel", "More room.")

        block = _block(session, item, "D1")
        assert (block.answer, block.by, block.note, block.via) == (
            "Tunnel",
            "ada",
            "More room.",
            "app",
        )
        assert (item.done_cause_code, item.done_by_user_id) == ("answered", person.id)

    def test_an_item_for_another_person_is_answered(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        container.test_data_service().person("ben", "Ben Example")
        item = _bear(
            container,
            project,
            project_session,
            "decision",
            DECISION.replace("title: Which tent?", "title: Which tent?\nfor: ben"),
        )

        container.item_service().answer(ADA, item.id, "D1", "Dome", None)

        assert _block(session, item, "D1").by == "ada"

    def test_an_unknown_item_is_not_found(self, container: ServiceContainer) -> None:
        unknown = uuid.uuid4()

        with pytest.raises(RecordNotFoundException) as missing:
            container.item_service().answer(ADA, unknown, "D1", "Dome", None)

        assert missing.value.message == f"Item {unknown} was not found"

    def test_a_block_the_item_lacks_is_not_found(
        self,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear(container, project, project_session, "decision", DECISION)

        with pytest.raises(RecordNotFoundException) as missing:
            container.item_service().answer(ADA, item.id, "D9", "Dome", None)

        assert missing.value.message == f"Block {item.id}/D9 was not found"

    def test_a_work_item_has_no_block(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _work(session, project, project_session)

        with pytest.raises(RecordNotFoundException) as missing:
            container.item_service().answer(ADA, item.id, "D1", "Dome", None)

        assert missing.value.message == f"Block {item.id}/D1 was not found"

    def test_the_opening_has_no_block(
        self, container: ServiceContainer, project: Project, person: User
    ) -> None:
        opening = container.document_service().bear_opening(
            project, "Which tent?", person, DECISION
        )

        with pytest.raises(RecordNotFoundException) as missing:
            container.item_service().answer(ADA, opening.id, "D1", "Dome", None)

        assert missing.value.message == f"Block {opening.id}/D1 was not found"

    def test_a_caller_without_a_handle_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear(container, project, project_session, "decision", DECISION)

        with pytest.raises(InvalidOperationException) as refused:
            container.item_service().answer(NEWCOMER, item.id, "D1", "Dome", None)

        assert refused.value.cause == NO_HANDLE
        assert _block(session, item, "D1").answer is None

    def test_the_records_refusal_reaches_the_caller(
        self,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear(container, project, project_session, "decision", DECISION)
        container.item_service().answer(ADA, item.id, "D1", "Dome", None)

        with pytest.raises(InvalidOperationException) as refused:
            container.item_service().answer(ADA, item.id, "D1", "Tunnel", None)

        assert refused.value.cause == "the item is done"


@pytest.mark.usefixtures("person")
class TestItemServiceDoneAction:
    def test_done_with_the_paste_back_is_the_records(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item = _bear(container, project, project_session, "action", ACTION)

        container.item_service().done_action(ADA, item.id, "A1", "Stored at kv/camp")

        block = _block(session, item, "A1")
        assert (block.by, block.note) == ("ada", "Stored at kv/camp")
        assert block.done is not None
        assert (item.done_cause_code, item.done_by_user_id) == ("answered", person.id)

    def test_an_unknown_item_is_not_found(self, container: ServiceContainer) -> None:
        unknown = uuid.uuid4()

        with pytest.raises(RecordNotFoundException) as missing:
            container.item_service().done_action(ADA, unknown, "A1", None)

        assert missing.value.message == f"Item {unknown} was not found"

    def test_a_work_item_has_no_block(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _work(session, project, project_session)

        with pytest.raises(RecordNotFoundException) as missing:
            container.item_service().done_action(ADA, item.id, "A1", None)

        assert missing.value.message == f"Block {item.id}/A1 was not found"

    def test_a_caller_without_a_handle_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear(container, project, project_session, "action", ACTION)

        with pytest.raises(InvalidOperationException) as refused:
            container.item_service().done_action(NEWCOMER, item.id, "A1", None)

        assert refused.value.cause == NO_HANDLE
        assert _block(session, item, "A1").done is None

    def test_the_records_refusal_reaches_the_caller(
        self,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear(container, project, project_session, "decision", DECISION)

        with pytest.raises(InvalidOperationException) as refused:
            container.item_service().done_action(ADA, item.id, "D1", None)

        assert refused.value.cause == "block D1 is a decision, not an action"


@pytest.mark.usefixtures("person")
class TestItemServiceDone:
    def test_done_records_the_recommendations(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        item = _bear(container, project, project_session, "document", RECOMMENDED)

        container.item_service().done(ADA, item.id)

        assert [
            (block.answer, block.by, block.via)
            for block in (_block(session, item, "D1"), _block(session, item, "Q1"))
        ] == [("Dome", "ada", "recommended"), ("The lake", "ada", "recommended")]
        assert (item.done_cause_code, item.done_by_user_id) == ("marked", person.id)

    def test_an_unknown_item_is_not_found(self, container: ServiceContainer) -> None:
        unknown = uuid.uuid4()

        with pytest.raises(RecordNotFoundException) as missing:
            container.item_service().done(ADA, unknown)

        assert missing.value.message == f"Item {unknown} was not found"

    def test_a_caller_without_a_handle_is_refused(
        self,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear(container, project, project_session, "document", RECOMMENDED)

        with pytest.raises(InvalidOperationException) as refused:
            container.item_service().done(NEWCOMER, item.id)

        assert refused.value.cause == NO_HANDLE
        assert item.done_at is None

    def test_the_records_refusal_reaches_the_caller(
        self,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear(container, project, project_session, "decision", DECISION)

        with pytest.raises(InvalidOperationException) as refused:
            container.item_service().done(ADA, item.id)

        assert refused.value.cause == "a decision item is not done by Done"


@pytest.mark.usefixtures("person")
class TestItemServiceMarks:
    @pytest.mark.parametrize(
        ("kind", "mark"), [("notice", "read"), ("review", "reviewed")]
    )
    def test_a_mark_is_the_records(
        self,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
        kind: str,
        mark: str,
    ) -> None:
        item = _bear(container, project, project_session, kind, NOTICE)

        getattr(container.item_service(), mark)(ADA, item.id)

        assert (item.done_cause_code, item.done_by_user_id) == ("marked", person.id)

    @pytest.mark.parametrize("mark", ["read", "reviewed"])
    def test_an_unknown_item_is_not_found(
        self, container: ServiceContainer, mark: str
    ) -> None:
        unknown = uuid.uuid4()

        with pytest.raises(RecordNotFoundException) as missing:
            getattr(container.item_service(), mark)(ADA, unknown)

        assert missing.value.message == f"Item {unknown} was not found"

    @pytest.mark.parametrize(
        ("kind", "mark"), [("notice", "read"), ("review", "reviewed")]
    )
    def test_a_caller_without_a_handle_is_refused(
        self,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        kind: str,
        mark: str,
    ) -> None:
        item = _bear(container, project, project_session, kind, NOTICE)

        with pytest.raises(InvalidOperationException) as refused:
            getattr(container.item_service(), mark)(NEWCOMER, item.id)

        assert refused.value.cause == NO_HANDLE
        assert item.done_at is None

    @pytest.mark.parametrize(
        ("kind", "mark", "cause"),
        [
            ("review", "read", "a review item is not marked Read"),
            ("notice", "reviewed", "a notice item is not marked Reviewed"),
        ],
    )
    def test_the_records_refusal_reaches_the_caller(
        self,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        kind: str,
        mark: str,
        cause: str,
    ) -> None:
        item = _bear(container, project, project_session, kind, NOTICE)

        with pytest.raises(InvalidOperationException) as refused:
            getattr(container.item_service(), mark)(ADA, item.id)

        assert refused.value.cause == cause


@pytest.mark.usefixtures("person")
class TestItemServiceUndo:
    def test_undo_opens_the_item_and_clears_its_answer(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear(container, project, project_session, "decision", DECISION)
        container.item_service().answer(ADA, item.id, "D1", "Dome", None)

        container.item_service().undo(item.id)

        assert (item.done_at, item.done_cause_code, item.done_by_user_id) == (
            None,
            None,
            None,
        )
        assert _block(session, item, "D1").answer is None

    def test_an_unknown_item_is_not_found(self, container: ServiceContainer) -> None:
        unknown = uuid.uuid4()

        with pytest.raises(RecordNotFoundException) as missing:
            container.item_service().undo(unknown)

        assert missing.value.message == f"Item {unknown} was not found"

    def test_the_records_refusal_reaches_the_caller(
        self,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _bear(container, project, project_session, "decision", DECISION)

        with pytest.raises(InvalidOperationException) as refused:
            container.item_service().undo(item.id)

        assert refused.value.cause == "the item is not done"
