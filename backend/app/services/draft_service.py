"""What a person does to a draft's asks in the Draft tab, in place (F47.4): an
answer, and Done on an action, each the record's own write (F32.4) into
`project.md`, the block found by its local id and the writer by the caller.
The draft has no item, so neither takes an Undo; answering again replaces the
answer. Past Create project the project document takes no answer."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.paths import DRAFT
from app.engine.record import RecordService
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import Document, Project
from app.models.reference import DocumentRole, ProjectState
from app.services.auth_service import AuthContext
from app.services.people_service import PeopleService


class DraftService:
    def __init__(
        self,
        db: Session,
        people_service: PeopleService,
        record_service: RecordService,
    ) -> None:
        self.db = db
        self.people_service = people_service
        self.record_service = record_service

    def answer(
        self,
        auth: AuthContext,
        project_id: uuid.UUID,
        block_id: str,
        answer: str,
        note: str | None,
    ) -> None:
        """The caller's answer to the draft's block, through the app, with
        `note` (F47.4, F17.4).

        Raises:
            RecordNotFoundException: no project has the id, or its draft has
                no such block.
            InvalidOperationException: the caller has not chosen a handle, the
                project is no draft, or the record refuses the answer.
        """
        operation = f"answer block {block_id} of the draft of project {project_id}"
        draft = self._draft(project_id, operation)
        person = self.people_service.require_person(auth, operation)
        self.record_service.answer(draft, block_id, person, answer, note=note)

    def done_action(
        self,
        auth: AuthContext,
        project_id: uuid.UUID,
        block_id: str,
        note: str | None,
    ) -> None:
        """Done on the draft's action, by the caller, with what they pasted
        back (F47.4, F21.1).

        Raises:
            RecordNotFoundException: no project has the id, or its draft has
                no such block.
            InvalidOperationException: the caller has not chosen a handle, the
                project is no draft, or the record refuses the Done.
        """
        operation = f"mark action {block_id} of the draft of project {project_id} done"
        draft = self._draft(project_id, operation)
        person = self.people_service.require_person(auth, operation)
        self.record_service.done_action(draft, block_id, person, note=note)

    def _draft(self, project_id: uuid.UUID, operation: str) -> Document:
        """The project's `project.md` while it is a draft: an ask Create
        project leaves open stays open (the planning's ruling). The project's
        row is held shared, as the record's write holds it, so that no change
        of its standing passes between the check and the write."""
        project = self.db.scalars(
            select(Project)
            .where(Project.id == project_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        ).one_or_none()
        if project is None:
            raise RecordNotFoundException("Project", str(project_id))
        if project.state_code is not ProjectState.DRAFT:
            raise InvalidOperationException(
                operation, f"the project is no draft: its `{DRAFT}` takes no answer"
            )
        return self.db.scalars(
            select(Document).where(
                Document.project_id == project.id,
                Document.role_code == DocumentRole.DRAFT,
            )
        ).one()
