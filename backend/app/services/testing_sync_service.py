"""What the live proof of the sync sets off inside the running server, where
the engine's bus is (TEST-6): a person's answer, the record writing a file
the store holds, and the `manifest` event."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.bus import EngineBus, ManifestChanged
from app.engine.record import RecordService
from app.engine.tree import TreeDocument, TreeFile, TreeService
from app.exceptions import RecordNotFoundException
from app.models import User


class TestingSyncService:
    def __init__(
        self,
        db: Session,
        engine_bus: EngineBus,
        record_service: RecordService,
        tree_service: TreeService,
    ) -> None:
        self.db = db
        self.engine_bus = engine_bus
        self.record_service = record_service
        self.tree_service = tree_service

    def answer(self, path: str, block: str, answer: str, handle: str) -> TreeFile:
        """The answer of the person with `handle` to block `block` of the
        document at `path`, from the tree's root, as the UI gives it
        (`RecordService.answer`); returns what the path holds once
        answered."""
        resolved = self.tree_service.resolve(path)
        if not isinstance(resolved, TreeDocument):
            raise RecordNotFoundException("Document", path)
        user = self.db.scalars(select(User).where(User.handle == handle)).one_or_none()
        if user is None:
            raise RecordNotFoundException("User", handle)
        self.record_service.answer(resolved.document, block, user, answer)
        return self.tree_service.read(path)

    def announce_manifest(self) -> None:
        """Raise the `manifest` event, delivered once the caller's
        transaction has committed."""
        self.engine_bus.emit(ManifestChanged())
