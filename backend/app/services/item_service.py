"""What a person does to an item on the timeline, by the item's id and a
block's local id (F30.7): each the record's own write (F32.4), the item and
the block found by their ids and the writer by the caller."""

import uuid

from sqlalchemy.orm import Session

from app.engine.record import RecordService
from app.exceptions import RecordNotFoundException
from app.models import Document, Item
from app.services.auth_service import AuthContext
from app.services.people_service import PeopleService


class ItemService:
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
        item_id: uuid.UUID,
        block_id: str,
        answer: str,
        note: str | None,
    ) -> None:
        """The caller's answer to the block, through the app, with `note`
        (F17.4); whoever the item is for (F107.1).

        Raises:
            RecordNotFoundException: no item has the id, or it has no such
                block.
            InvalidOperationException: the caller has not chosen a handle, or
                the record refuses the answer.
        """
        item = self._item(item_id)
        person = self.people_service.require_person(
            auth, f"answer block {block_id} of item {item_id}"
        )
        self.record_service.answer(
            self._document(item, block_id), block_id, person, answer, note=note
        )

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
            InvalidOperationException: the caller has not chosen a handle, or
                the record refuses the Done.
        """
        item = self._item(item_id)
        person = self.people_service.require_person(
            auth, f"mark action {block_id} of item {item_id} done"
        )
        self.record_service.done_action(
            self._document(item, block_id), block_id, person, note=note
        )

    def done(self, auth: AuthContext, item_id: uuid.UUID) -> None:
        """Done on a document, by the caller, with its recommendations
        (F32.5).

        Raises:
            RecordNotFoundException: no item has the id.
            InvalidOperationException: the caller has not chosen a handle, or
                the record refuses the Done.
        """
        item = self._item(item_id)
        person = self.people_service.require_person(auth, f"mark item {item_id} done")
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
