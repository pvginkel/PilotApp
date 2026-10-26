"""The turn-end read (TD §4.4; F65.1, F89; ruling D1; design 2 §8): once the
turn that ends a work item's run commits, its `result` making the work item
done (decision 44), each document its Session registered is read through the
controller, a stopped environment's too, and published as written; else its
read failed.

The reads run on a loop of their own per Session, `read:<session id>`, after
that commit. Each file is read outside any transaction, and what it gave is
written in a transaction of its own, under the Project's row, the Session's and
the Document's, in the start's lock order, unless the document no longer
awaits its read: Finish closed it, or another process read it first. A file the
controller refuses — nothing at the path, outside `/work`, not a file, over
16 MiB, a link loop or a manifest it cannot read the layout from — or a text
with faults is a failed read: the document keeps no text and takes its closes,
and a `server` record in no Turn of the Session's log names its path and why.
A read the controller does not answer, or answers `503 environment-unreadable`,
raises, and the loop runs again after its backoff, waiting the outage out.

A run that stops or fails reads nothing: its documents await their reads until
its Resume's run ends. At STARTUP the job's reconcile runs the reads of every
Session that owes one, from the rows.
"""

import logging
import uuid
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from sqlalchemy import ColumnElement, and_, exists, select
from sqlalchemy.orm import Session, aliased

from app.database import scoped_session
from app.engine.documents import awaiting_read, awaits_read, listed
from app.engine.record import TURN_ENDED
from app.engine.views import ViewService
from app.models import Document, Item, Project
from app.models.reference import RecordKind
from app.services.controller_client import (
    ControllerClient,
    ControllerProblem,
    ControllerProblemType,
)
from app.services.session_record_service import SessionRecordService
from app.services.session_stream_service import SessionStreamService
from app.services.supervisor import LoopHandle, Supervisor
from app.utils.after_commit import after_commit

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)

READ_JOB = "read"

READ_FAILED = "read-failed"
"""The `type` of the `server` record of a turn-end read that failed, with the
document's `item`, its `path` and the `reason`."""

_FILE_REFUSALS = (
    ControllerProblemType.NOT_FOUND,
    ControllerProblemType.PATH_OUTSIDE_WORK,
    ControllerProblemType.NOT_A_FILE,
    ControllerProblemType.FILE_TOO_LARGE,
    ControllerProblemType.CONFLICT,
)
"""The controller's refusals of a read that name what is wrong with the file,
its path or its environment's layout: a failed read. A `CONFLICT` is a link
loop, or a manifest the controller cannot read the layout from; reads take no
`409` from a bring-up."""


@dataclass(frozen=True)
class _Owed:
    """A registered document owed its turn-end read, and where its file is."""

    document_id: uuid.UUID
    environment_id: str
    path: str


@dataclass(frozen=True)
class _Refused:
    """The controller's refusal of a file, in its words."""

    reason: str


@dataclass(frozen=True)
class _ReadStart:
    # `after_commit()` runs a callback equal to one it holds once.
    reads: "TurnEndReadService"
    session_id: uuid.UUID

    def __call__(self) -> None:
        self.reads._start(self.session_id)


class TurnEndReadService:
    """Reads the documents a work item's run registered, once its run ends."""

    def __init__(
        self,
        container: "ServiceContainer",
        supervisor: Supervisor,
        session_streams: SessionStreamService,
    ) -> None:
        """Register the `read` job, whose loops are one per Session, and whose
        reconcile runs the reads every Session owes.

        Args:
            container: Gives each read's transaction its database session, and
                the client
            supervisor: Runs the reads, and runs one again whose call raised
            session_streams: Woken by a failed read's `server` record
        """
        self._container = container
        self._supervisor = supervisor
        self._streams = session_streams
        supervisor.register_job(
            READ_JOB, needs_controller=True, reconcile=self._reconcile
        )

    def run_ended(self, db: Session, session_id: uuid.UUID) -> None:
        """The Session's work item done at its turn's end, in the caller's
        transaction: the documents it registered are read once that commits."""
        if _owed(db, session_id):
            after_commit(_ReadStart(self, session_id))

    def read(self, session_id: uuid.UUID, handle: LoopHandle) -> None:
        """The read loop's run: each document the Session registered that is
        owed its read, in the order registered, read and published, or its
        read failed. Returns once none is owed, and when the loop is told to
        stop.

        Raises:
            ExternalServiceException: The controller did not answer, or
                refused a read for a reason of its own
        """
        with scoped_session(self._container) as db:
            owed = _owed(db, session_id)
        for document in owed:
            if handle.stopping:
                return
            content = self._read_file(document)
            with scoped_session(self._container) as db:
                self._take(db, session_id, document, content)

    def _reconcile(self, db: Session) -> None:
        """At STARTUP: run the reads of every Session that owes one (§8)."""
        owing = db.scalars(
            select(Item.created_by_session_id)
            .join(Document, Document.id == Item.id)
            .where(_owed_read())
            .distinct()
            .order_by(Item.created_by_session_id)
        )
        for session_id in owing:
            # A registered document is its Session's.
            assert session_id is not None
            logger.info("Resuming the turn-end reads of session %s", session_id)
            self._start(session_id)

    def _start(self, session_id: uuid.UUID) -> None:
        self._supervisor.start_loop(
            READ_JOB, partial(self.read, session_id), key=str(session_id)
        )

    def _read_file(self, owed: _Owed) -> bytes | _Refused:
        """The file's bytes, or the controller's refusal of it."""
        try:
            return self._client().read_file(owed.environment_id, owed.path).data
        except ControllerProblem as problem:
            if problem.problem_type not in _FILE_REFUSALS:
                raise
            return _Refused(problem.cause)

    def _take(
        self,
        db: Session,
        session_id: uuid.UUID,
        owed: _Owed,
        content: bytes | _Refused,
    ) -> None:
        """What the read gave, written under the Project's row, the Session's
        and the Document's, unless the document no longer awaits its read."""
        documents = self._container.document_service()
        document = db.get_one(Document, owed.document_id)
        project, item = documents.owner(document)
        # A registered document is a Prose Item's.
        assert item is not None
        db.execute(select(Project.id).where(Project.id == project.id).with_for_update())
        records = SessionRecordService(
            db, self._streams, ViewService(db, self._container.engine_bus())
        )
        records.lock_session(session_id)
        documents.lock(document)
        if not awaits_read(item, document):
            logger.info(
                "Document %s of session %s no longer awaits its read",
                owed.path,
                session_id,
            )
            return
        if isinstance(content, _Refused):
            reason = content.reason
        else:
            version = self._container.ingest_service().worker_version(project, content)
            if not version.faults:
                documents.publish_read(document, version.text, session_id)
                logger.info(
                    "Read document %s of session %s: published",
                    owed.path,
                    session_id,
                )
                return
            reason = f"its text holds faults: {listed(version.faults)}"
        documents.fail_read(document)
        records.append(
            session_id,
            RecordKind.SERVER,
            payload={
                "type": READ_FAILED,
                "item": str(document.id),
                "path": owed.path,
                "reason": reason,
            },
        )
        logger.info(
            "Read document %s of session %s: failed, %s", owed.path, session_id, reason
        )

    def _client(self) -> ControllerClient:
        client: ControllerClient = self._container.controller_client()
        return client


def _owed_read() -> ColumnElement[bool]:
    """A registered document owed its turn-end read, on a query of Documents
    joined to their Items: awaiting it, the run that registered it ended, its
    work item done at its turn's end (decision 44)."""
    work = aliased(Item)
    return and_(
        awaiting_read(),
        exists().where(
            work.id == Item.created_by_session_id, work.done_cause_code == TURN_ENDED
        ),
    )


def _owed(db: Session, session_id: uuid.UUID) -> list[_Owed]:
    """The documents the Session registered that are owed their read, with
    where their files are, in the order registered."""
    rows = db.execute(
        select(Document.id, Document.source_environment_id, Document.source_path)
        .join(Item, Item.id == Document.id)
        .where(Item.created_by_session_id == session_id, _owed_read())
        .order_by(Item.seq)
    ).all()
    owed: list[_Owed] = []
    for document_id, environment_id, path in rows:
        # A registered document's source is its environment and its path.
        assert environment_id is not None and path is not None
        owed.append(_Owed(document_id, environment_id, path))
    return owed
