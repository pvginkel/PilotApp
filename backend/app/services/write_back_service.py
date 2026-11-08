"""The write-back (TD §4.4, FM §5; F65.1, F89; design 2 §8): once a close of a
registered document commits — Done, the answer that closes a one-ask item,
Reviewed — its text as the record holds it, the answers in it, overwrites the
file it was registered from through the controller, a stopped environment's
too, and `written_back_at` says when. A document whose read failed has no text
to write, and Finish's close owes none (review 4).

The writes run on a loop of their own per registering Session,
`write-back:<session id>`, which the close's `WriteBackOwed` asks for once it
commits. Each file is written outside any transaction, and what came of it is
taken in a transaction of its own, under the Project's row, the Session's and
the Document's, in the start's lock order, unless the document no longer owes
the text written: an Undo reopened it, or another process wrote it first. A
write the controller refuses for what is wrong with the file, its path or its
environment — the environment gone, outside `/work`, a folder or under a file
now, over 16 MiB — is not made again until the document's next close, or the
Resume of the continuation that carries it: `write_back_refused_at` says so,
and a `server` record in no Turn of the Session's log names its path and the
controller's answer. A write it refuses for a reason of its own — its own work
on the tree (`409 conflict`), its share unreadable (`503`), or any other
answer, a `401`, a `422` or a `500` among them — is made again while Pilot's
record has its environment coming up or being deleted, then for
`REFUSAL_WAIT_SECONDS` more (`RefusalWaits`), and is then refused so, with the
controller's last answer. A run makes its writes again side by side, so that
the documents a continuation carries wait those minutes together, and a close
owes its write afresh, with a wait of its own. A write the controller does not
answer raises, and the loop runs again after its backoff, with no wait
started.

At STARTUP the job's reconcile runs the writes every Session owes, from the
rows.
"""

import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core_exceptions import ExternalServiceException
from app.database import scoped_session
from app.engine.bus import EngineBus, EngineEvent, WriteBackOwed
from app.engine.record import owes_write_back, write_back_owed
from app.engine.views import ViewService
from app.models import Document, Environment, Item, Project
from app.models.reference import RecordKind
from app.services.controller_client import (
    ControllerClient,
    ControllerProblem,
    ControllerProblemType,
    ControllerUnreachable,
)
from app.services.refusal_waits import (
    REFUSAL_RETRY_SECONDS,
    REFUSAL_WAIT_SECONDS,
    RefusalWaits,
)
from app.services.session_record_service import SessionRecordService
from app.services.session_stream_service import SessionStreamService
from app.services.supervisor import LoopHandle, Supervisor

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)

WRITE_BACK_JOB = "write-back"

WRITE_BACK_REFUSED = "write-back-refused"
"""The `type` of the `server` record of a write-back the controller refused,
with the document's `item`, its `path` and the `reason`."""

_FILE_REFUSALS = (
    ControllerProblemType.NOT_FOUND,
    ControllerProblemType.PATH_OUTSIDE_WORK,
    ControllerProblemType.NOT_A_FILE,
    ControllerProblemType.NOT_A_DIRECTORY,
    ControllerProblemType.FILE_TOO_LARGE,
)
"""The controller's refusals of a write that name what is wrong with the file,
its path or its environment. A write makes the file and the folders it needs,
so its `NOT_FOUND` is an environment gone."""

_SETTLING = ("provisioning", "starting", "deleting")
"""The statuses of an environment the controller is bringing up or deleting:
a refusal of a write there counts toward no wait."""


@dataclass(frozen=True)
class _Owed:
    """A closed registered document's text owed to its file, and where that
    is."""

    document_id: uuid.UUID
    session_id: uuid.UUID
    """The Session that registered it."""
    closed_at: datetime
    environment_id: str
    path: str
    text: str
    hash: str
    settling: bool
    """Pilot's record has its environment coming up or being deleted."""

    @property
    def key(self) -> tuple[uuid.UUID, datetime, str]:
        """The write as its close owes it: each close owes it afresh, and a
        close's time is to the second."""
        return (self.document_id, self.closed_at, self.hash)


@dataclass(frozen=True)
class _Refused:
    """The controller's refusal of a write, in its words."""

    reason: str
    own: bool
    """For a reason of the controller's own: made again until its wait
    passes."""


class WriteBackService:
    """Writes each closed registered document's text back to its file."""

    def __init__(
        self,
        container: "ServiceContainer",
        supervisor: Supervisor,
        session_streams: SessionStreamService,
        engine_bus: EngineBus,
        refusal_wait_seconds: float = REFUSAL_WAIT_SECONDS,
        refusal_retry_seconds: float = REFUSAL_RETRY_SECONDS,
    ) -> None:
        """Register the `write-back` job, whose loops are one per registering
        Session, and whose reconcile runs the writes every Session owes; and
        hear the engine's bus, whose `WriteBackOwed` asks for a Session's.

        Args:
            container: Gives each write's transaction its database session,
                and the client
            supervisor: Runs the writes, and runs one again whose call raised
            session_streams: Woken by a refused write's `server` record
            engine_bus: Tells of each close that owes a write-back, once it
                commits
            refusal_wait_seconds: How long a write the controller refuses for
                a reason of its own is made again from its first refusal
                counted
            refusal_retry_seconds: The wait between two rounds of those writes
        """
        self._container = container
        self._supervisor = supervisor
        self._streams = session_streams
        self._refusal_wait = refusal_wait_seconds
        self._refusal_retry = refusal_retry_seconds
        supervisor.register_job(
            WRITE_BACK_JOB, needs_controller=True, reconcile=self._reconcile
        )
        engine_bus.subscribe(self._heard)

    def write_back(
        self,
        session_ids: Sequence[uuid.UUID],
        handle: LoopHandle,
        going_on: Callable[[], bool] | None = None,
    ) -> None:
        """Each document the Sessions registered whose text is owed to its
        file, in the order registered, written and taken, a round at a time,
        until none is owed: the write-back loop's run, its Session's, and a
        continuation's start's, the Sessions it carries. A write the
        controller refuses for a reason of its own is made again in the next
        round until its wait passes (`RefusalWaits`). Returns then, when the
        loop is told to stop, and when `going_on` says no between two rounds.

        Raises:
            ControllerUnreachable: The controller did not answer a write
        """
        waits = RefusalWaits(self._refusal_wait, self._refusal_retry)
        while not handle.stopping:
            with scoped_session(self._container) as db:
                owed = _owed(db, session_ids)
            if not owed:
                return
            waits.round(document.key for document in owed)
            waiting = False
            for document in owed:
                if handle.stopping:
                    return
                refused = self._write(document)
                if (
                    refused is not None
                    and refused.own
                    and not self._waited_out(document, refused, waits)
                ):
                    waiting = True
                    continue
                with scoped_session(self._container) as db:
                    self._take(db, document, refused)
            if waiting and (
                handle.wait(waits.pause()) or (going_on is not None and not going_on())
            ):
                return

    def _heard(self, event: EngineEvent) -> None:
        if isinstance(event, WriteBackOwed):
            self._start(event.session_id)

    def _reconcile(self, db: Session) -> None:
        """At STARTUP: run the writes of every Session that owes one (§8)."""
        owing = db.scalars(
            select(Item.created_by_session_id)
            .join(Document, Document.id == Item.id)
            .where(write_back_owed())
            .distinct()
            .order_by(Item.created_by_session_id)
        )
        for session_id in owing:
            # A registered document is its Session's.
            assert session_id is not None
            logger.info("Resuming the write-backs of session %s", session_id)
            self._start(session_id)

    def _start(self, session_id: uuid.UUID) -> None:
        # Again: a close that commits after the run's last look at the rows
        # has its write made by a run after it.
        self._supervisor.start_loop(
            WRITE_BACK_JOB,
            partial(self.write_back, (session_id,)),
            key=str(session_id),
            again=True,
        )

    def _write(self, owed: _Owed) -> _Refused | None:
        """The text written to the file, or the controller's refusal of it.

        Raises:
            ControllerUnreachable: The controller did not answer
        """
        try:
            self._client().write_file(
                owed.environment_id, owed.path, owed.text.encode()
            )
        except ExternalServiceException as error:
            if isinstance(error, ControllerUnreachable):
                raise
            own = not (
                isinstance(error, ControllerProblem)
                and error.problem_type in _FILE_REFUSALS
            )
            return _Refused(error.cause, own)
        return None

    def _waited_out(self, owed: _Owed, refused: _Refused, waits: RefusalWaits) -> bool:
        """A refusal of the controller's own counted toward the write's wait,
        unless Pilot's record has its environment coming up or being deleted,
        which starts the wait afresh from the next one: whether the wait has
        passed."""
        if owed.settling:
            waits.restart(owed.key)
            logger.debug(
                "Write-back of document %s of session %s refused while its"
                " environment settles: %s",
                owed.path,
                owed.session_id,
                refused.reason,
            )
            return False
        started = owed.key in waits
        if waits.passed(owed.key):
            return True
        if not started:
            logger.info(
                "Write-back of document %s of session %s refused, made again for"
                " %g s: %s",
                owed.path,
                owed.session_id,
                self._refusal_wait,
                refused.reason,
            )
        return False

    def _take(self, db: Session, owed: _Owed, refused: _Refused | None) -> None:
        """What the write came to, taken under the Project's row, the
        Session's and the Document's, unless the document no longer owes the
        text written."""
        documents = self._container.document_service()
        document = db.get_one(Document, owed.document_id)
        project, item = documents.owner(document)
        # A registered document is a Prose Item's.
        assert item is not None
        db.execute(select(Project.id).where(Project.id == project.id).with_for_update())
        records = SessionRecordService(
            db,
            self._streams,
            ViewService(
                db, self._container.engine_bus(), self._container.closed_chats()
            ),
        )
        records.lock_session(owed.session_id)
        documents.lock(document)
        if not owes_write_back(item, document) or document.published_hash != owed.hash:
            logger.info(
                "Document %s of session %s no longer owes the text written",
                owed.path,
                owed.session_id,
            )
            return
        if refused is None:
            documents.wrote_back(document)
            logger.info(
                "Wrote document %s of session %s back", owed.path, owed.session_id
            )
            return
        documents.refuse_write_back(document)
        records.append(
            owed.session_id,
            RecordKind.SERVER,
            payload={
                "type": WRITE_BACK_REFUSED,
                "item": str(document.id),
                "path": owed.path,
                "reason": refused.reason,
            },
        )
        logger.info(
            "Write-back of document %s of session %s refused: %s",
            owed.path,
            owed.session_id,
            refused.reason,
        )

    def _client(self) -> ControllerClient:
        client: ControllerClient = self._container.controller_client()
        return client


def _owed(db: Session, session_ids: Sequence[uuid.UUID]) -> list[_Owed]:
    """The documents the Sessions registered whose text is owed to their
    files, with where those are and their environment's status as Pilot's
    record has it, in the order registered."""
    rows = db.execute(
        select(
            Document.id,
            Item.created_by_session_id,
            Item.done_at,
            Document.source_environment_id,
            Document.source_path,
            Document.published_text,
            Document.published_hash,
            Environment.last_state,
        )
        .join(Item, Item.id == Document.id)
        .join(Environment, Environment.id == Document.source_environment_id)
        .where(Item.created_by_session_id.in_(session_ids), write_back_owed())
        .order_by(Item.seq)
    ).all()
    owed: list[_Owed] = []
    for (
        document_id,
        session_id,
        closed_at,
        environment_id,
        path,
        text,
        text_hash,
        state,
    ) in rows:
        # A registered document is its Session's, its source is its
        # environment and its path, and one owed its write-back is closed and
        # has a text.
        assert session_id is not None and closed_at is not None
        assert environment_id is not None and path is not None
        assert text is not None and text_hash is not None
        owed.append(
            _Owed(
                document_id,
                session_id,
                closed_at,
                environment_id,
                path,
                text,
                text_hash,
                state in _SETTLING,
            )
        )
    return owed
