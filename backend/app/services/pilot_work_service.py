"""`pilot-work`, a worker session's tools (TD §4.5, F85): the bearer its
Session was created with resolved to the Session, `register_document`
(ruling D1) and `attach_file`, each call that changed the record writing its
Effects (F41)."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.attachments import (
    MAX_CALL_FILES,
    MAX_CALL_SIZE,
    AttachService,
    Copy,
    copied,
)
from app.engine.documents import DocumentService, Registration, listed
from app.engine.ingest import IngestService
from app.exceptions import (
    AuthenticationException,
    AuthorizationException,
    InvalidOperationException,
    RecordNotFoundException,
)
from app.models import Attachment, Document, Item, Project, SessionKind, Work
from app.models import Session as AgentSession
from app.models.reference import EffectKind
from app.services.controller_client import (
    ControllerClient,
    ControllerProblem,
    ControllerProblemType,
)
from app.services.effect_service import Change, EffectLine, EffectService
from app.services.pilot_server import token_hash

PILOT_WORK = "pilot-work"
"""The surface of a work item's Session (`session_kinds.surface`)."""

_BEARER = "Bearer "

REGISTERED = "Registered"
ATTACHED = "Attached"
"""The verbs of the two tools' effect lines (F41)."""

_UNREADABLE_FILE = (
    ControllerProblemType.NOT_FOUND,
    ControllerProblemType.PATH_OUTSIDE_WORK,
    ControllerProblemType.NOT_A_FILE,
    ControllerProblemType.FILE_TOO_LARGE,
)
"""The controller's refusals of a read that name what the worker can fix."""

_UNCOPYABLE_FILE = (*_UNREADABLE_FILE, ControllerProblemType.CONFLICT)
"""The controller's refusals of a copy's read or listing that name what the
worker can fix: `CONFLICT` a link loop, in a folder or at the path."""


@dataclass(frozen=True)
class Worker:
    """The Session a bearer names, and what it names (F84): its project, its
    environment and its work item, the Work that is the Session."""

    session_id: uuid.UUID
    project_id: uuid.UUID
    environment_id: str
    work_item_id: uuid.UUID


class PilotWorkService:
    def __init__(
        self,
        db: Session,
        controller_client: Callable[[], ControllerClient],
        document_service: DocumentService,
        ingest_service: IngestService,
        attach_service: AttachService,
        effect_service: EffectService,
    ) -> None:
        self.db = db
        self.controller_client = controller_client
        self.document_service = document_service
        self.ingest_service = ingest_service
        self.attach_service = attach_service
        self.effect_service = effect_service

    def admit(self, authorization: str | None) -> Worker:
        """The work item's Session whose bearer `authorization` carries.

        Raises:
            AuthenticationException: no bearer, or one no Session has.
            AuthorizationException: the bearer's Session is not a work
                item's, whose surface is `pilot-work`.
        """
        if authorization is None or not authorization.startswith(_BEARER):
            raise AuthenticationException(
                "Cannot call pilot-work because the request carries no bearer"
            )
        found = self.db.execute(
            select(AgentSession, SessionKind.surface, Work.id)
            .join(SessionKind, SessionKind.code == AgentSession.kind_code)
            .outerjoin(Work, Work.id == AgentSession.id)
            .where(
                AgentSession.token_hash
                == token_hash(authorization.removeprefix(_BEARER))
            )
        ).one_or_none()
        if found is None:
            raise AuthenticationException(
                "Cannot call pilot-work because no session has the request's bearer"
            )
        session, surface, work_id = found
        if surface != PILOT_WORK or work_id is None:
            raise AuthorizationException(
                f"Cannot call pilot-work because session {session.id} is a"
                f" {session.kind_code} session, not a work item's"
            )
        # A bearer is minted at its Session's create, which names its
        # environment.
        assert session.environment_id is not None
        return Worker(
            session_id=session.id,
            project_id=session.project_id,
            environment_id=session.environment_id,
            work_item_id=work_id,
        )

    def register_document(
        self, worker: Worker, path: str, tool_use_id: str | None
    ) -> Registration:
        """The document the worker wrote at `path` in its environment,
        registered (F85.1, ruling D1): the file read now and parsed as the
        worker's turn left it, then the item its run registered from the path
        already, else one minted, its text read at the turn's end. A minted
        one is the call `tool_use_id`'s effect, "Registered · inbox/<n>".

        Raises:
            InvalidOperationException: the file cannot be registered, nothing
                minted: the controller refused its read — a path outside
                `/work`, nothing there, a folder, more than 16 MiB — or its
                text holds faults, each with its line.
            ExternalServiceException: the controller did not answer, or
                refused for a reason of its own.
        """
        operation = f"register document {path}"
        try:
            content = self.controller_client().read_file(worker.environment_id, path)
        except ControllerProblem as problem:
            if problem.problem_type not in _UNREADABLE_FILE:
                raise
            raise InvalidOperationException(operation, problem.cause) from problem
        project = self.db.get_one(Project, worker.project_id)
        version = self.ingest_service.worker_version(project, content.data)
        if version.faults:
            raise InvalidOperationException(
                operation, f"its text holds faults: {listed(version.faults)}"
            )
        registration = self.document_service.register(
            project, self.db.get_one(AgentSession, worker.session_id), path
        )
        if registration.minted:
            item = registration.item
            # A registered document has no title until its text is read: its
            # line names its place, the folder and its number.
            place = PurePosixPath(self.db.get_one(Document, item.id).path).parent
            self.effect_service.record(
                worker.session_id,
                tool_use_id,
                EffectLine(REGISTERED, f"{place}/{item.seq}", item_id=item.id),
                [Change(EffectKind.REGISTERED, item_id=item.id)],
            )
        return registration

    def attach_file(
        self, worker: Worker, path: str, to: uuid.UUID | None, tool_use_id: str | None
    ) -> list[Attachment]:
        """The file or the folder at `path` in the worker's environment,
        copied into the record now and hung on the item `to` names, else on
        the worker's own work item (F85.2, F36.1): a file one attachment, a
        folder one per file under it, named by its path relative to the
        folder, in path order; all of one batch, each with its source. The
        call `tool_use_id`'s effect is one line for its files, "Attached ·
        <title>", or "Attached · <folder>, <n> files".

        Raises:
            RecordNotFoundException: `to` names no item of the worker's
                project.
            InvalidOperationException: a file cannot be copied, nothing
                attached: the controller refused its read or the folder's
                listing — a path outside `/work`, nothing there, neither a
                file nor a folder, more than 16 MiB, a link loop — or the
                call is over its cap of files or bytes.
            ExternalServiceException: the controller did not answer, or
                refused for a reason of its own.
        """
        item = self.db.get(Item, worker.work_item_id if to is None else to)
        if item is None or item.project_id != worker.project_id:
            raise RecordNotFoundException("Item", str(to))
        copies = self._copies(worker.environment_id, path, f"attach {path}")
        attachments = self.attach_service.attach(
            item, self.db.get_one(AgentSession, worker.session_id), copies
        )
        if len(attachments) == 1:
            label = attachments[0].title
        else:
            label = f"{_name(path)}, {len(attachments)} files"
        self.effect_service.record(
            worker.session_id,
            tool_use_id,
            EffectLine(ATTACHED, label, item_id=item.id),
            [
                Change(EffectKind.ATTACHED, attachment_id=attachment.id)
                for attachment in attachments
            ],
        )
        return attachments

    def _copies(self, environment_id: str, path: str, operation: str) -> list[Copy]:
        """The file at `path`, else every file under the folder at `path`,
        read through the controller."""
        client = self.controller_client()
        try:
            content = client.read_file(environment_id, path)
        except ControllerProblem as problem:
            if problem.problem_type is not ControllerProblemType.NOT_A_FILE:
                _refuse(operation, problem)
                raise
            return self._folder(client, environment_id, path, operation, problem)
        return [copied(_name(path), path, content.data)]

    def _folder(
        self,
        client: ControllerClient,
        environment_id: str,
        path: str,
        operation: str,
        not_a_file: ControllerProblem,
    ) -> list[Copy]:
        try:
            files = client.list_folder_files(environment_id, path)
        except ControllerProblem as problem:
            if problem.problem_type is ControllerProblemType.NOT_A_DIRECTORY:
                # Neither a file nor a folder: a FIFO, a socket, a device.
                raise InvalidOperationException(
                    operation, not_a_file.cause
                ) from not_a_file
            _refuse(operation, problem)
            raise
        if len(files) > MAX_CALL_FILES:
            raise InvalidOperationException(
                operation,
                f"the folder holds {len(files)} files, over the {MAX_CALL_FILES}"
                "-file cap of one call",
            )
        folder = f"{path.rstrip('/')}/"
        copies: list[Copy] = []
        size = 0
        for file in files:
            try:
                content = client.read_file(environment_id, file)
            except ControllerProblem as problem:
                _refuse(operation, problem)
                raise
            size += len(content.data)
            if size > MAX_CALL_SIZE:
                raise InvalidOperationException(
                    operation,
                    f"the folder's files are over the {MAX_CALL_SIZE}-byte cap of"
                    " one call",
                )
            copies.append(copied(file.removeprefix(folder), file, content.data))
        return copies


def _name(path: str) -> str:
    """The file's or the folder's name at `path`."""
    return path.rstrip("/").rsplit("/", 1)[-1]


def _refuse(operation: str, problem: ControllerProblem) -> None:
    """Refuse the call when the controller's `problem` names what the worker
    can fix."""
    if problem.problem_type in _UNCOPYABLE_FILE:
        raise InvalidOperationException(operation, problem.cause) from problem
