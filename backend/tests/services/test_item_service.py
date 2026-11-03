"""What a person does to an item on the timeline, by the item's id and a
block's local id (F30.7): each the record's own write (F32.4), its refusals
the caller's; and a person's request of a wait (F27.3)."""

import uuid

import pilot_dsl as dsl
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.engine.paths import tree_path
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import Document, Item, Project, ProjectTransition, User, WaitFiring
from app.models.reference import FiringCause, ProjectState, SessionState, TransitionKind
from app.schemas.testing_record import InventedProjectCreateSchema
from app.services.auth_service import AuthContext
from app.services.container import ServiceContainer
from app.services.item_service import (
    HOLDING_UNREAD,
    HOLDS_NOTHING,
    NOT_A_RUNS,
    NOT_PILOTS,
    PILOTS_ITEM,
    RUN_IN_FLIGHT,
    UNREAD,
    WAITS_ON,
)
from app.services.timeline_service import waiting
from app.services.working_on import holds
from tests.support.working_on import Camp

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


def _finished(session: DbSession, container: ServiceContainer) -> tuple[Project, Item]:
    """An open project of ada's finished by her, and its archive question."""
    made = container.test_data_service().project(
        InventedProjectCreateSchema.model_validate({"name": "Camp", "members": ["ada"]})
    )
    container.project_service().transition(ADA, made.id, TransitionKind.FINISHED)
    question = session.scalars(
        select(Item).where(
            Item.project_id == made.id, Item.kind_code == "archive_question"
        )
    ).one()
    return made, question


def _transitions(session: DbSession, project: Project) -> list[tuple[str, object]]:
    return [
        (transition.kind_code, transition.by_user_id)
        for transition in session.scalars(
            select(ProjectTransition)
            .where(ProjectTransition.project_id == project.id)
            .order_by(ProjectTransition.at, ProjectTransition.id)
        )
    ]


@pytest.mark.usefixtures("person")
class TestItemServiceArchiveQuestion:
    """The archive question's Archive archives the project by the person who
    answered, in the same act; its Keep keeps it finished (DB 265)."""

    def test_archive_answers_it_and_archives_the_project_by_the_caller(
        self, session: DbSession, container: ServiceContainer, person: User
    ) -> None:
        made, question = _finished(session, container)

        container.item_service().answer(ADA, question.id, "D1", "Archive", None)

        assert (question.done_cause_code, question.done_by_user_id) == (
            "answered",
            person.id,
        )
        assert _block(session, question, "D1").answer == "Archive"
        assert (made.state_code, made.archived) == (ProjectState.FINISHED, True)
        assert _transitions(session, made)[-1] == (
            TransitionKind.ARCHIVED,
            person.id,
        )

    def test_keep_answers_it_and_the_project_stays_finished(
        self, session: DbSession, container: ServiceContainer, person: User
    ) -> None:
        made, question = _finished(session, container)
        before = _transitions(session, made)

        container.item_service().answer(ADA, question.id, "D1", "Keep", None)

        assert (question.done_cause_code, question.done_by_user_id) == (
            "answered",
            person.id,
        )
        assert (made.state_code, made.archived) == (ProjectState.FINISHED, False)
        assert _transitions(session, made) == before

    def test_archive_on_an_answered_question_is_refused_and_archives_nothing(
        self, session: DbSession, container: ServiceContainer
    ) -> None:
        made, question = _finished(session, container)
        container.item_service().answer(ADA, question.id, "D1", "Keep", None)
        before = _transitions(session, made)

        with pytest.raises(InvalidOperationException) as refused:
            container.item_service().answer(ADA, question.id, "D1", "Archive", None)

        assert refused.value.cause == "the item is done"
        assert made.archived is False
        assert _transitions(session, made) == before

    def test_archive_on_a_block_the_question_lacks_is_not_found(
        self, session: DbSession, container: ServiceContainer
    ) -> None:
        made, question = _finished(session, container)

        with pytest.raises(RecordNotFoundException) as missing:
            container.item_service().answer(ADA, question.id, "D9", "Archive", None)

        assert missing.value.message == f"Block {question.id}/D9 was not found"
        assert (question.done_at, made.archived) == (None, False)

    def test_archive_keeps_its_note(
        self, session: DbSession, container: ServiceContainer
    ) -> None:
        _made, question = _finished(session, container)

        container.item_service().answer(
            ADA, question.id, "D1", "Archive", "Done with it."
        )

        block = _block(session, question, "D1")
        assert (block.answer, block.by, block.note, block.via) == (
            "Archive",
            "ada",
            "Done with it.",
            "app",
        )


def _card_wait(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
    project_session: models.Session,
) -> Item:
    """An open card wait of `project`'s, opened."""
    project.state_code = ProjectState.OPEN
    project.slug = "camp"
    project.name = "Camp"
    session.flush()
    return container.wait_service().add_card_wait(
        project, project_session, "SR-4 is done", ["SR-4"], ["Done"], None
    )


@pytest.mark.usefixtures("person")
class TestItemServiceRequest:
    """A person's request of a wait, its head's button (F27.3)."""

    def test_the_request_fires_the_wait_by_the_caller(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        wait = _card_wait(session, container, project, project_session)

        container.item_service().request(ADA, wait.id)

        assert [
            (firing.cause_code, firing.requested_by_user_id)
            for firing in session.scalars(
                select(WaitFiring).where(WaitFiring.wait_id == wait.id)
            )
        ] == [(FiringCause.REQUESTED, person.id)]

    def test_an_unknown_item_is_not_found(self, container: ServiceContainer) -> None:
        unknown = uuid.uuid4()

        with pytest.raises(RecordNotFoundException) as missing:
            container.item_service().request(ADA, unknown)

        assert missing.value.message == f"Item {unknown} was not found"

    def test_a_caller_without_a_handle_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        wait = _card_wait(session, container, project, project_session)

        with pytest.raises(InvalidOperationException) as refused:
            container.item_service().request(NEWCOMER, wait.id)

        assert refused.value.cause == NO_HANDLE
        assert session.scalars(select(WaitFiring)).all() == []

    def test_the_wait_s_refusal_reaches_the_caller(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        wait = _card_wait(session, container, project, project_session)
        container.item_service().request(ADA, wait.id)

        with pytest.raises(InvalidOperationException) as refused:
            container.item_service().request(ADA, wait.id)

        assert refused.value.cause == "Pilot is checking"


CLAIMED = """# The cut-over

```action id=A1
answer: Pilot does it
by: agent
at: 2026-11-02T09:00:00Z
```

```action id=A2
```
"""
"""An action the pass claimed beside one that waits on the person."""

CLAIMED_ALONE = """# The cut-over

```action id=A1
answer: Pilot does it
by: agent
at: 2026-11-02T09:00:00Z
```
"""

PITCH = """# Where do we pitch?

```question id=Q1
```

```decision id=D1
options:
  - Lake
  - Hill
```
"""
"""A question a research checks a fact for, beside a decision."""

QUESTION = "# Which lake?\n\n```question id=Q1\n```\n"


@pytest.fixture
def camp(container: ServiceContainer, session: DbSession, person: User) -> Camp:
    return Camp(container, session)


def _passed(camp: Camp, text: str) -> Item:
    """A document a worker registered and its pass went over."""
    writer = camp.worker()
    document = camp.registered(writer, text)
    camp.ended(writer)
    camp.ended(camp.job_after(writer))
    return document


def _claimed(camp: Camp, text: str = CLAIMED) -> tuple[Item, models.Session]:
    """`text` registered, its pass over, and its action A1 claimed by a work
    item running on a conversation of its own."""
    document = _passed(camp, text)
    doing = camp.worker(conversation="conversation-2")
    camp.claim(document, "A1", doing)
    return document, doing


def _waits(camp: Camp, item: Item) -> bool:
    return (
        camp.session.scalar(select(Item.id).where(Item.id == item.id, waiting()))
        is not None
    )


class TestItemServiceTakeOver:
    """Stop and take over (F28.9, F26.3): what of Pilot's work holds the
    document, in flight, stopped by the person, the document theirs at
    once."""

    def test_the_pass_is_stopped_and_every_document_it_covers_is_the_persons(
        self, container: ServiceContainer, camp: Camp, person: User
    ) -> None:
        run = camp.worker()
        pitch, lake = camp.registered(run, PITCH), camp.registered(run, QUESTION)
        camp.ended(run)
        job = camp.job_after(run)

        container.item_service().take_over(ADA, pitch.id)

        assert (job.state_code, job.stopped_by_user_id) == (
            SessionState.STOPPED,
            person.id,
        )
        assert camp.reading(pitch, lake) == {}
        # A stopped job shows with Retry, and counts until retried.
        assert _waits(camp, camp.session.get_one(Item, job.id))
        assert _waits(camp, pitch) and _waits(camp, lake)

    def test_the_clarification_run_asking_its_writer_is_stopped(
        self, container: ServiceContainer, camp: Camp, person: User
    ) -> None:
        run = camp.worker(conversation="conversation-1")
        pitch = camp.registered(run, PITCH)
        camp.ended(run)
        pass_ = camp.job_after(run)
        camp.ask_writer(pass_, pitch, "Q1")
        camp.ended(pass_)
        clarifying = camp.clarification(pass_, run)

        container.item_service().take_over(ADA, pitch.id)

        assert (clarifying.state_code, clarifying.stopped_by_user_id) == (
            SessionState.STOPPED,
            person.id,
        )
        assert camp.of(pitch) is None

    def test_the_holding_runs_work_item_is_stopped_and_its_claim_handed_back(
        self, container: ServiceContainer, camp: Camp, person: User
    ) -> None:
        cut_over, doing = _claimed(camp, CLAIMED_ALONE)
        items = container.item_service()

        items.take_over(ADA, cut_over.id)

        assert (doing.state_code, doing.stopped_by_user_id) == (
            SessionState.STOPPED,
            person.id,
        )
        assert camp.of(cut_over) is None
        assert holds(camp.session, [cut_over.id]).undone == {
            camp.block(cut_over, "A1").id
        }
        items.done_action(ADA, cut_over.id, "A1", "Done by hand.")
        assert _block(camp.session, cut_over, "A1").done is not None

    def test_the_job_after_the_holding_runs_turn_is_stopped(
        self, container: ServiceContainer, camp: Camp, person: User
    ) -> None:
        cut_over, doing = _claimed(camp, CLAIMED_ALONE)
        camp.ended(doing)
        job = camp.job_after(doing)

        container.item_service().take_over(ADA, cut_over.id)

        assert (job.state_code, job.stopped_by_user_id) == (
            SessionState.STOPPED,
            person.id,
        )
        assert camp.of(cut_over) is None

    def test_a_document_pilot_is_not_working_on_is_refused(
        self, container: ServiceContainer, camp: Camp
    ) -> None:
        pitch = _passed(camp, PITCH)

        with pytest.raises(InvalidOperationException) as refused:
            container.item_service().take_over(ADA, pitch.id)

        assert refused.value.cause == NOT_PILOTS

    def test_a_document_of_a_run_awaiting_its_read_is_refused(
        self, container: ServiceContainer, camp: Camp
    ) -> None:
        run = camp.worker()
        pitch = camp.registered(run, PITCH)
        camp.registered(run, read=False)
        camp.ended(run)

        with pytest.raises(InvalidOperationException) as refused:
            container.item_service().take_over(ADA, pitch.id)

        assert refused.value.cause == UNREAD

    def test_one_whose_holding_run_waits_on_the_person_is_refused_naming_its_document(
        self, container: ServiceContainer, camp: Camp
    ) -> None:
        cut_over, doing = _claimed(camp, CLAIMED_ALONE)
        asked = camp.registered(doing, QUESTION)
        camp.ended(doing)
        camp.ended(camp.job_after(doing))

        with pytest.raises(InvalidOperationException) as refused:
            container.item_service().take_over(ADA, cut_over.id)

        path = tree_path(camp.project, camp.session.get_one(Document, asked.id).path)
        assert refused.value.cause == WAITS_ON.format(document=path)
        assert camp.of(cut_over) is not None

    def test_one_whose_holding_run_registered_a_document_not_read_yet_is_refused(
        self, container: ServiceContainer, camp: Camp
    ) -> None:
        cut_over, doing = _claimed(camp, CLAIMED_ALONE)
        camp.registered(doing, read=False)
        camp.ended(doing)

        with pytest.raises(InvalidOperationException) as refused:
            container.item_service().take_over(ADA, cut_over.id)

        assert refused.value.cause == HOLDING_UNREAD

    def test_an_item_with_no_document_is_not_found(
        self, container: ServiceContainer, camp: Camp
    ) -> None:
        run = camp.worker()

        with pytest.raises(RecordNotFoundException):
            container.item_service().take_over(ADA, run.id)

    def test_an_unknown_item_is_not_found(self, container: ServiceContainer) -> None:
        with pytest.raises(RecordNotFoundException):
            container.item_service().take_over(ADA, uuid.uuid4())

    def test_a_caller_with_no_handle_is_refused(
        self, container: ServiceContainer, camp: Camp
    ) -> None:
        run = camp.worker()
        pitch = camp.registered(run, PITCH)
        camp.ended(run)
        camp.job_after(run)

        with pytest.raises(InvalidOperationException) as refused:
            container.item_service().take_over(NEWCOMER, pitch.id)

        assert refused.value.cause == NO_HANDLE


REPORT = "# What tagging needs\n\nA signed tag.\n"
"""A document with no block, a report a run registers beside its question."""


def _asked(camp: Camp, *, research: bool = False) -> tuple[Item, Item, Item]:
    """A document whose one block a work item's run holds, a claimed action
    or a researched question, and the question and the report that run
    registered, its turn and the job after it ended: the run waits on the
    person."""
    held = _passed(camp, QUESTION if research else CLAIMED_ALONE)
    doing = camp.worker(conversation="conversation-2")
    if research:
        camp.research(held, "Q1", doing)
    else:
        camp.claim(held, "A1", doing)
    asked, report = camp.registered(doing, QUESTION), camp.registered(doing, REPORT)
    camp.ended(doing)
    camp.ended(camp.job_after(doing))
    return held, asked, report


class TestItemServiceCancel:
    """A Cancel on a document of a run that holds a block of another
    document, while the run waits on the person (F28.9; DB 297 to 299): the
    run ended, every open document of it done `cancelled` by them, the block
    theirs again."""

    def test_it_closes_every_open_document_of_the_run_and_hands_the_claim_back(
        self, container: ServiceContainer, camp: Camp, person: User
    ) -> None:
        cut_over, asked, report = _asked(camp)
        items = container.item_service()
        assert not _waits(camp, cut_over)

        items.cancel(ADA, report.id)

        for each in (asked, report):
            assert (each.done_cause_code, each.done_by_user_id) == (
                "cancelled",
                person.id,
            )
        assert camp.of(cut_over) is None
        assert holds(camp.session, [cut_over.id]).undone == {
            camp.block(cut_over, "A1").id
        }
        assert _waits(camp, cut_over)
        # No work item continues the run.
        assert camp.session.scalars(
            select(models.Session.id).where(
                models.Session.conversation_id == "conversation-2"
            )
        ).all() == [camp.session.get_one(Item, asked.id).created_by_session_id]
        items.done_action(ADA, cut_over.id, "A1", "Pushed by hand.")
        assert _block(camp.session, cut_over, "A1").done is not None
        with pytest.raises(InvalidOperationException) as refused:
            items.undo(asked.id)
        assert refused.value.cause == "an item done as cancelled offers no undo"

    def test_a_researched_block_whose_work_asked_first_is_the_persons_again(
        self, container: ServiceContainer, camp: Camp
    ) -> None:
        lake, asked, _ = _asked(camp, research=True)
        items = container.item_service()

        items.cancel(ADA, asked.id)

        assert camp.of(lake) is None
        items.answer(ADA, lake.id, "Q1", "The north shore", None)
        assert _block(camp.session, lake, "Q1").answer == "The north shore"

    def test_one_whose_run_holds_nothing_is_refused(
        self, container: ServiceContainer, camp: Camp
    ) -> None:
        pitch = _passed(camp, PITCH)

        with pytest.raises(InvalidOperationException) as refused:
            container.item_service().cancel(ADA, pitch.id)

        assert str(refused.value) == (
            f"Cannot cancel item {pitch.id} because {HOLDS_NOTHING}"
        )
        assert pitch.done_at is None

    def test_one_whose_run_has_something_in_flight_is_refused(
        self, container: ServiceContainer, camp: Camp
    ) -> None:
        cut_over, doing = _claimed(camp, CLAIMED_ALONE)
        asked, other = camp.registered(doing, QUESTION), camp.registered(doing, PITCH)
        camp.ended(doing)
        pass_ = camp.job_after(doing)
        camp.ask_writer(pass_, other, "Q1")
        camp.ended(pass_)
        camp.clarification(pass_, doing)

        with pytest.raises(InvalidOperationException) as refused:
            container.item_service().cancel(ADA, asked.id)

        assert refused.value.cause == RUN_IN_FLIGHT
        assert asked.done_at is None
        assert camp.of(cut_over) is not None

    def test_a_document_that_is_pilots_is_refused(
        self, container: ServiceContainer, camp: Camp
    ) -> None:
        cut_over, doing = _claimed(camp, CLAIMED_ALONE)
        asked = camp.registered(doing, QUESTION)
        camp.ended(doing)
        camp.job_after(doing)

        for each in (asked, cut_over):
            with pytest.raises(InvalidOperationException) as refused:
                container.item_service().cancel(ADA, each.id)
            assert refused.value.cause == PILOTS_ITEM

    def test_a_document_done_is_refused(
        self, container: ServiceContainer, camp: Camp
    ) -> None:
        _, asked, report = _asked(camp)
        items = container.item_service()
        items.reviewed(ADA, report.id)

        with pytest.raises(InvalidOperationException) as refused:
            items.cancel(ADA, report.id)

        assert refused.value.cause == "the item is done"
        assert asked.done_at is None

    def test_a_document_no_work_items_run_registered_is_refused(
        self, container: ServiceContainer, camp: Camp
    ) -> None:
        notice = container.test_data_service().item(
            camp.project.id, "notice", "Pitched", "By the lake.\n", by_pilot=True
        )

        with pytest.raises(InvalidOperationException) as refused:
            container.item_service().cancel(ADA, notice.id)

        assert refused.value.cause == NOT_A_RUNS

    def test_an_archived_projects_document_is_refused(
        self, container: ServiceContainer, camp: Camp
    ) -> None:
        _, asked, _ = _asked(camp)
        camp.project.archived = True
        camp.session.flush()

        with pytest.raises(InvalidOperationException) as refused:
            container.item_service().cancel(ADA, asked.id)

        assert refused.value.cause == "its project is archived"
        assert asked.done_at is None

    def test_an_item_with_no_document_is_not_found(
        self, container: ServiceContainer, camp: Camp
    ) -> None:
        with pytest.raises(RecordNotFoundException):
            container.item_service().cancel(ADA, camp.worker().id)

    def test_an_unknown_item_is_not_found(self, container: ServiceContainer) -> None:
        with pytest.raises(RecordNotFoundException):
            container.item_service().cancel(ADA, uuid.uuid4())

    def test_a_caller_with_no_handle_is_refused(
        self, container: ServiceContainer, camp: Camp
    ) -> None:
        _, asked, _ = _asked(camp)

        with pytest.raises(InvalidOperationException) as refused:
            container.item_service().cancel(NEWCOMER, asked.id)

        assert refused.value.cause == NO_HANDLE
        assert asked.done_at is None


class TestItemServiceWhilePilotWorks:
    """A document that is Pilot's and a held block take no answer, Done or
    paste-back from the app's controls (DB 295)."""

    def test_a_document_under_its_pass_takes_no_answer_done_or_paste_back(
        self, container: ServiceContainer, camp: Camp
    ) -> None:
        run = camp.worker()
        pitch = camp.registered(run, PITCH)
        camp.ended(run)
        camp.job_after(run)
        items = container.item_service()

        for act in (
            lambda: items.answer(ADA, pitch.id, "D1", "Lake", None),
            lambda: items.done(ADA, pitch.id),
        ):
            with pytest.raises(InvalidOperationException) as refused:
                act()
            assert refused.value.cause == PILOTS_ITEM

    def test_a_held_block_takes_no_answer_its_neighbour_does(
        self, container: ServiceContainer, camp: Camp
    ) -> None:
        pitch = _passed(camp, PITCH)
        camp.research(pitch, "Q1", camp.worker(conversation="conversation-2"))
        items = container.item_service()

        with pytest.raises(InvalidOperationException) as refused:
            items.answer(ADA, pitch.id, "Q1", "The lake", None)

        assert str(refused.value) == (
            f"Cannot answer block Q1 of item {pitch.id} because Pilot is working"
            " on block Q1"
        )
        items.answer(ADA, pitch.id, "D1", "Lake", None)
        assert _block(camp.session, pitch, "D1").answer == "Lake"

    def test_a_held_action_takes_no_done_until_its_work_fails(
        self, container: ServiceContainer, camp: Camp
    ) -> None:
        cut_over, doing = _claimed(camp)
        items = container.item_service()

        with pytest.raises(InvalidOperationException) as refused:
            items.done_action(ADA, cut_over.id, "A1", "Rotated by hand.")
        assert refused.value.cause == "Pilot is working on block A1"

        doing.state_code = SessionState.FAILED
        camp.session.flush()
        items.done_action(ADA, cut_over.id, "A1", "Rotated by hand.")

        assert _block(camp.session, cut_over, "A1").note == "Rotated by hand."

    def test_a_document_with_a_held_block_takes_no_done(
        self, container: ServiceContainer, camp: Camp
    ) -> None:
        cut_over, _ = _claimed(camp)

        with pytest.raises(InvalidOperationException) as refused:
            container.item_service().done(ADA, cut_over.id)

        assert refused.value.cause == "Pilot is working on block A1"
