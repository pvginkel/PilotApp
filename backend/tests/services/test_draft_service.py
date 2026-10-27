"""What a person does to a draft's asks in the Draft tab, in place (F47.4):
the record's own answer and Done written into `project.md`, refused past
Create project."""

import uuid

import pilot_dsl as dsl
import pytest
from sqlalchemy.orm import Session as DbSession

from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import Document, Project, User
from app.models.reference import AnswerChannel, ProjectState
from app.services.auth_service import AuthContext
from app.services.container import ServiceContainer
from app.services.draft_service import DraftService

ADA = AuthContext(
    subject="subject-ada", email=None, name="Ada Example", roles={"editor"}
)
"""The `person` fixture, signed in."""

NEWCOMER = AuthContext(
    subject="subject-newcomer", email=None, name="Nia Newcomer", roles={"editor"}
)
"""A person at their first sign-in, with no handle yet."""

DRAFT = """---
title: Camp
---

Two tents by the lake.

```question id=Q1
default: The lake
```

```action id=A1
```
"""


@pytest.fixture
def draft(container: ServiceContainer, project: Project) -> Document:
    """The draft's `project.md`, Pilot's asks in it."""
    return container.document_service().bear_draft(project, DRAFT)


def _drafts(container: ServiceContainer) -> DraftService:
    service: DraftService = container.draft_service()
    return service


def _block(draft: Document, local_id: str) -> dsl.Block:
    assert draft.published_text is not None
    return next(
        block
        for block in dsl.parse(draft.published_text).blocks
        if block.local_id == local_id
    )


def _open(session: DbSession, project: Project) -> None:
    """`project` past Create project."""
    project.state_code = ProjectState.OPEN
    project.slug = "camp"
    session.flush()


@pytest.mark.usefixtures("person")
class TestDraftServiceAnswer:
    def test_the_callers_answer_is_written_into_project_md(
        self, container: ServiceContainer, project: Project, draft: Document
    ) -> None:
        _drafts(container).answer(ADA, project.id, "Q1", "The forest", "Shade.")

        block = _block(draft, "Q1")
        assert (block.answer, block.by, block.note, block.via) == (
            "The forest",
            "ada",
            "Shade.",
            AnswerChannel.APP.value,
        )
        assert draft.published_text is not None
        assert "Two tents by the lake." in draft.published_text

    def test_answering_again_replaces_the_answer(
        self, container: ServiceContainer, project: Project, draft: Document
    ) -> None:
        drafts = _drafts(container)

        drafts.answer(ADA, project.id, "Q1", "The forest", None)
        drafts.answer(ADA, project.id, "Q1", "The lake", None)

        assert _block(draft, "Q1").answer == "The lake"

    def test_an_unknown_project_is_not_found(self, container: ServiceContainer) -> None:
        unknown = uuid.uuid4()

        with pytest.raises(RecordNotFoundException) as refused:
            _drafts(container).answer(ADA, unknown, "Q1", "The lake", None)

        assert refused.value.message == f"Project {unknown} was not found"

    def test_an_ask_the_draft_does_not_hold_is_not_found(
        self, container: ServiceContainer, project: Project, draft: Document
    ) -> None:
        with pytest.raises(RecordNotFoundException) as refused:
            _drafts(container).answer(ADA, project.id, "Q9", "The lake", None)

        assert refused.value.message == f"Block {draft.id}/Q9 was not found"

    def test_past_create_project_md_takes_no_answer(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        draft: Document,
    ) -> None:
        _open(session, project)

        with pytest.raises(InvalidOperationException) as refused:
            _drafts(container).answer(ADA, project.id, "Q1", "The lake", None)

        assert refused.value.message == (
            f"Cannot answer block Q1 of the draft of project {project.id} because"
            " the project is no draft: its `project.md` takes no answer"
        )
        assert _block(draft, "Q1").answer is None

    def test_a_caller_with_no_handle_is_refused(
        self, container: ServiceContainer, project: Project, draft: Document
    ) -> None:
        with pytest.raises(InvalidOperationException) as refused:
            _drafts(container).answer(NEWCOMER, project.id, "Q1", "The lake", None)

        assert refused.value.message.endswith(
            "because you have not chosen your handle yet"
        )
        assert _block(draft, "Q1").answer is None

    def test_the_record_refuses_an_answer_the_ask_does_not_take(
        self, container: ServiceContainer, project: Project, draft: Document
    ) -> None:
        with pytest.raises(InvalidOperationException) as refused:
            _drafts(container).answer(ADA, project.id, "A1", "Done", None)

        assert refused.value.message.endswith(
            "because an action without options is done, not answered"
        )

    def test_an_archived_draft_takes_no_answer(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        draft: Document,
    ) -> None:
        project.archived = True
        session.flush()

        with pytest.raises(InvalidOperationException) as refused:
            _drafts(container).answer(ADA, project.id, "Q1", "The lake", None)

        assert refused.value.message.endswith("because its project is archived")


@pytest.mark.usefixtures("person")
class TestDraftServiceDoneAction:
    def test_done_on_the_drafts_action_is_written_with_the_paste_back(
        self,
        container: ServiceContainer,
        project: Project,
        draft: Document,
        person: User,
    ) -> None:
        _drafts(container).done_action(ADA, project.id, "A1", "Both pitched.")

        block = _block(draft, "A1")
        assert block.done is not None
        assert (block.by, block.note) == ("ada", "Both pitched.")

    def test_past_create_it_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        draft: Document,
    ) -> None:
        _open(session, project)

        with pytest.raises(InvalidOperationException) as refused:
            _drafts(container).done_action(ADA, project.id, "A1", None)

        assert refused.value.message == (
            f"Cannot mark action A1 of the draft of project {project.id} done"
            " because the project is no draft: its `project.md` takes no answer"
        )
        assert _block(draft, "A1").done is None

    def test_an_unknown_project_is_not_found(self, container: ServiceContainer) -> None:
        with pytest.raises(RecordNotFoundException):
            _drafts(container).done_action(ADA, uuid.uuid4(), "A1", None)

    def test_a_caller_with_no_handle_is_refused(
        self, container: ServiceContainer, project: Project, draft: Document
    ) -> None:
        with pytest.raises(InvalidOperationException) as refused:
            _drafts(container).done_action(NEWCOMER, project.id, "A1", None)

        assert refused.value.message.endswith(
            "because you have not chosen your handle yet"
        )

    def test_the_record_refuses_done_on_a_question(
        self, container: ServiceContainer, project: Project, draft: Document
    ) -> None:
        with pytest.raises(InvalidOperationException) as refused:
            _drafts(container).done_action(ADA, project.id, "Q1", None)

        assert refused.value.message.endswith(
            "because block Q1 is a question, not an action"
        )
