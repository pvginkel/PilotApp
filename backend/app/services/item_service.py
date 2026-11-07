"""What a person does to an item on the timeline, by the item's id and a
block's local id (F30.7): each the record's own write (F32.4), the item and
the block found by their ids and the writer by the caller; the archive
question's Archive archives the project with it (DB 265); and a person's
request of a wait, which fires it (F27.3). A document that is Pilot's, and a
held block, take no answer, Done or paste-back from here (DB 295); Stop and
take over hands such a document to the person (F28.9), and a Cancel on a
document of the run holding a block, while that run waits on the person, ends
the run and hands the block back (DB 297 to 299)."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.documents import ARCHIVE, ARCHIVE_QUESTION
from app.engine.paths import tree_path
from app.engine.record import RecordService
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import Block, Document, Item, Project
from app.schemas.timeline import Doing
from app.services.auth_service import AuthContext
from app.services.people_service import PeopleService
from app.services.project_service import ProjectService
from app.services.session_start_service import SessionStartService
from app.services.wait_service import WaitService
from app.services.working_on import (
    Reading,
    cancels,
    holding_work,
    pilots_work,
    run_documents,
)

PILOTS_ITEM = "Pilot is working on the item"
"""Why a document that is Pilot's takes no answer, Done or paste-back from
the app's controls (DB 295, 296)."""

NOT_PILOTS = "Pilot is not working on it"

UNREAD = "it, or another document its run registered, has not been read yet"
"""Why Stop and take over is refused before the pass over a run's documents
is placed: nothing of it is in flight to stop."""

WAITS_ON = "Pilot waits on an answer to {document}, whose Cancel hands the blocks back"
"""Why Stop and take over is refused while the run holding the blocks waits
on the person: nothing of it is in flight to stop, and a Cancel on that
document ends the run (R20)."""

HOLDING_UNREAD = "a document of the run holding its blocks has not been read yet"

NOT_A_RUNS = "it is no document a work item's run registered"
"""Why a Cancel is refused on an item that is not a registered document of a
worker's run (DB 297)."""

HOLDS_NOTHING = "its run holds no block of another document"

RUN_IN_FLIGHT = "something of its run is in flight"
"""Why a Cancel is refused while the server goes on with the run by itself
(DB 294, 297)."""

RUN_PILOTS = "Pilot is working on another document of its run, or a block of one"
"""Why a Cancel is refused while one of the run's open documents is Pilot's
or has a held block, which its close would take from Pilot's work (DB 295,
297)."""


class ItemService:
    def __init__(
        self,
        db: Session,
        people_service: PeopleService,
        record_service: RecordService,
        project_service: ProjectService,
        wait_service: WaitService,
        session_start_service: SessionStartService,
    ) -> None:
        self.db = db
        self.people_service = people_service
        self.record_service = record_service
        self.project_service = project_service
        self.wait_service = wait_service
        self.session_start_service = session_start_service

    def answer(
        self,
        auth: AuthContext,
        item_id: uuid.UUID,
        block_id: str,
        answer: str,
        note: str | None,
    ) -> None:
        """The caller's answer to the block, through the app, with `note`
        (F17.4); whoever the item is for (F107.1). Archive on the archive
        question then archives the project, by the caller, in the same act,
        with every effect of the menu's Archive (F128.1; DB 265).

        Raises:
            RecordNotFoundException: no item has the id, or it has no such
                block.
            InvalidOperationException: the caller has not chosen a handle,
                the item is Pilot's or the block held, or the record refuses
                the answer.
        """
        item = self._item(item_id)
        operation = f"answer block {block_id} of item {item_id}"
        person = self.people_service.require_person(auth, operation)
        if item.kind_code == ARCHIVE_QUESTION and answer.strip() == ARCHIVE:
            self.project_service.archive_by_its_question(person, item, block_id, note)
            return
        document = self._document(item, block_id)
        self._not_pilots(item, operation, block_id)
        self.record_service.answer(document, block_id, person, answer, note=note)

    def done_action(
        self,
        auth: AuthContext,
        item_id: uuid.UUID,
        block_id: str,
        note: str | None,
    ) -> None:
        """Done on the action, by the caller, with what they pasted back
        (F21.1).

        Raises:
            RecordNotFoundException: no item has the id, or it has no such
                block.
            InvalidOperationException: the caller has not chosen a handle,
                the item is Pilot's or the action held, or the record refuses
                the Done.
        """
        item = self._item(item_id)
        operation = f"mark action {block_id} of item {item_id} done"
        person = self.people_service.require_person(auth, operation)
        document = self._document(item, block_id)
        self._not_pilots(item, operation, block_id)
        self.record_service.done_action(document, block_id, person, note=note)

    def done(self, auth: AuthContext, item_id: uuid.UUID) -> None:
        """Done on a document, by the caller, with its recommendations
        (F32.5).

        Raises:
            RecordNotFoundException: no item has the id.
            InvalidOperationException: the caller has not chosen a handle,
                the item is Pilot's or a block of it held, or the record
                refuses the Done.
        """
        item = self._item(item_id)
        operation = f"mark item {item_id} done"
        person = self.people_service.require_person(auth, operation)
        self._not_pilots(item, operation, None)
        self.record_service.done(item, person)

    def read(self, auth: AuthContext, item_id: uuid.UUID) -> None:
        """Read on a notice, by the caller.

        Raises:
            RecordNotFoundException: no item has the id.
            InvalidOperationException: the caller has not chosen a handle, or
                the record refuses the mark.
        """
        item = self._item(item_id)
        person = self.people_service.require_person(auth, f"mark item {item_id} Read")
        self.record_service.read(item, person)

    def reviewed(self, auth: AuthContext, item_id: uuid.UUID) -> None:
        """Reviewed on a review, by the caller.

        Raises:
            RecordNotFoundException: no item has the id.
            InvalidOperationException: the caller has not chosen a handle, or
                the record refuses the mark.
        """
        item = self._item(item_id)
        person = self.people_service.require_person(
            auth, f"mark item {item_id} Reviewed"
        )
        self.record_service.reviewed(item, person)

    def undo(self, item_id: uuid.UUID) -> None:
        """Undo of the item's answer or mark, whoever gave it (F14.1).

        Raises:
            RecordNotFoundException: no item has the id.
            InvalidOperationException: the record refuses the undo.
        """
        self.record_service.undo(self._item(item_id))

    def request(self, auth: AuthContext, item_id: uuid.UUID) -> None:
        """The caller's request of the wait (F27.3): *Check now* on a card
        wait, *Skip wait* on a timed wait, a firing by them.

        Raises:
            RecordNotFoundException: no item has the id.
            InvalidOperationException: the caller has not chosen a handle,
                the item is no wait, or the wait takes no request now.
        """
        item = self._item(item_id)
        person = self.people_service.require_person(
            auth, f"request a firing of item {item_id}"
        )
        self.wait_service.request(item, person)

    def take_over(self, auth: AuthContext, item_id: uuid.UUID) -> None:
        """The caller's Stop and take over of a document that is Pilot's
        (F28.9, F26.3), under its project's row: what of Pilot's work holds
        it, in flight, stopped by them (`SessionStartService.take_over`), so
        that it is theirs at once, as is every other document the same pass
        covers. That is the pass's job, its clarification run, the job after
        the writer's reply, or what of the run holding its blocks is in
        flight. What it stops shows as any stopped work does, and the
        hand-back holds until a Resume or a Retry gives the work back.

        Raises:
            RecordNotFoundException: no item has the id, or it has no
                document.
            InvalidOperationException: the caller has not chosen a handle;
                Pilot is not working on the item; it, or another document
                its run registered, awaits its read; or nothing of the run
                holding its blocks is in flight: it waits on an answer to
                one of its documents, or one of them awaits its read.
        """
        item = self._item(item_id)
        operation = f"stop and take over item {item_id}"
        person = self.people_service.require_person(auth, operation)
        if self.db.get(Document, item.id) is None:
            raise RecordNotFoundException("Document", str(item_id))
        project = self._lock_project(item)
        reading = Reading(self.db)
        working = pilots_work(reading, [item.id]).get(item.id)
        if working is None:
            raise InvalidOperationException(operation, NOT_PILOTS)
        if working.doing is Doing.AWAITING_RUN:
            raise InvalidOperationException(operation, UNREAD)
        if working.doing is Doing.WAITING_ON_ANSWER:
            # The reading names the run's open document while it waits.
            assert working.asked_in is not None
            asked = self.db.get_one(Document, working.asked_in)
            raise InvalidOperationException(
                operation, WAITS_ON.format(document=tree_path(project, asked.path))
            )
        work = holding_work(reading, item.id)
        if not work:
            raise InvalidOperationException(operation, HOLDING_UNREAD)
        self.session_start_service.take_over(self.db, work, person)

    def cancel(self, auth: AuthContext, item_id: uuid.UUID) -> None:
        """The caller's Cancel on an open registered document of a worker's
        run that is theirs, while nothing of the run is in flight and it
        holds a block of another document (F28.9; DB 297 to 299), under its
        project's row: every open document of the run closed at once by
        them, done `cancelled`, which offers no undo, owes no write-back and
        continues nothing, so that the run is ended and the blocks it held
        are theirs again.

        Raises:
            RecordNotFoundException: no item has the id, or it has no
                document.
            InvalidOperationException: the caller has not chosen a handle;
                the item is done, or no document a work item's run
                registered; it is Pilot's; its run holds no block of another
                document, something of it is in flight, or another of its
                documents is Pilot's or has a held block; or the project is
                archived.
        """
        item = self._item(item_id)
        operation = f"cancel item {item_id}"
        person = self.people_service.require_person(auth, operation)
        if self.db.get(Document, item.id) is None:
            raise RecordNotFoundException("Document", str(item_id))
        project = self._lock_project(item)
        if item.done_at is not None:
            raise InvalidOperationException(operation, "the item is done")
        reading = Reading(self.db)
        if item.id in reading.found:
            raise InvalidOperationException(operation, PILOTS_ITEM)
        offer = cancels(reading, [item.id]).get(item.id)
        if offer is None:
            raise InvalidOperationException(operation, NOT_A_RUNS)
        if not offer.takes_back:
            raise InvalidOperationException(operation, HOLDS_NOTHING)
        if offer.going_on:
            raise InvalidOperationException(operation, RUN_IN_FLIGHT)
        if offer.pilots_in_run:
            raise InvalidOperationException(operation, RUN_PILOTS)
        self.record_service.cancel(
            project, run_documents(self.db, offer.run_id), person, operation
        )

    def _lock_project(self, item: Item) -> Project:
        """The item's project, its row locked as an item's close locks it,
        before any of its Sessions: every placement of work and every Resume
        takes it too, so that no hold begins while this transaction reads
        the item as the person's (DB 295)."""
        return self.db.scalars(
            select(Project)
            .where(Project.id == item.project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()

    def _not_pilots(self, item: Item, operation: str, local_id: str | None) -> None:
        """Refuses the app's write on the item while it is Pilot's, or while
        Pilot holds its block `local_id`, or, with none named, any block of
        it (DB 295), under the project's row (`_lock_project`). Pilot's own
        tools are not the app's controls, and the record takes their writes
        as ever."""
        self._lock_project(item)
        reading = Reading(self.db)
        if item.id in reading.found:
            raise InvalidOperationException(operation, PILOTS_ITEM)
        query = select(Block.local_id).where(
            Block.document_id == item.id, reading.held()
        )
        if local_id is not None:
            query = query.where(Block.local_id == local_id)
        held_ids = list(self.db.scalars(query.order_by(Block.position)))
        if held_ids:
            named = "block" if len(held_ids) == 1 else "blocks"
            raise InvalidOperationException(
                operation, f"Pilot is working on {named} {', '.join(held_ids)}"
            )

    def _item(self, item_id: uuid.UUID) -> Item:
        item = self.db.get(Item, item_id)
        if item is None:
            raise RecordNotFoundException("Item", str(item_id))
        return item

    def _document(self, item: Item, block_id: str) -> Document:
        """The item's text; a work or wait item has none, so no block."""
        document = self.db.get(Document, item.id)
        if document is None:
            raise RecordNotFoundException("Block", f"{item.id}/{block_id}")
        return document
