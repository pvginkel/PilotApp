"""`pilot-work`, a worker session's tools (TD §4.5, F85): the bearer its
Session was created with resolved to the Session, `register_document`
(ruling D1) and `attach_file`, each call that changed the record writing its
Effects (F41), and `set_progress` and `set_progress_step`, its work item's
steps (F145), which write none."""

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
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
    AuthorizationException,
    InvalidOperationException,
    RecordNotFoundException,
)
from app.models import Attachment, Document, Item, ProgressStep, Project, Work
from app.models import Session as AgentSession
from app.models.reference import EffectKind, ProgressState, SessionState, Surface
from app.schemas.pilot_work import ProgressStepRequestSchema
from app.services.controller_client import (
    ControllerClient,
    ControllerProblem,
    ControllerProblemType,
)
from app.services.effect_service import Change, EffectLine, EffectService
from app.services.pilot_server import bearer_session, no_turn

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
session copying can fix: `CONFLICT` a link loop, in a folder or at the path."""


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
        """The work item's Session whose bearer `authorization` carries,
        while its turn runs.

        Raises:
            AuthenticationException: no bearer, or one no Session has.
            AuthorizationException: the bearer's Session is not a work
                item's, whose surface is `pilot-work`, or has no turn
                running.
        """
        session, surface = bearer_session(self.db, authorization, Surface.WORK)
        if surface is not Surface.WORK or self.db.get(Work, session.id) is None:
            raise AuthorizationException(
                f"Cannot call pilot-work because session {session.id} is a"
                f" {session.kind_code} session, not a work item's"
            )
        if session.state_code != SessionState.RUNNING:
            raise AuthorizationException(no_turn(Surface.WORK, session.id))
        # A bearer is minted at its Session's create, which names its
        # environment.
        assert session.environment_id is not None
        return Worker(
            session_id=session.id,
            project_id=session.project_id,
            environment_id=session.environment_id,
            work_item_id=session.id,
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
            AuthorizationException: the worker's Session has no turn running
                once the project's row is held, as Finish and Archive leave
                it, nothing minted.
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
            project, self._still_running(project, worker), path
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

    def _still_running(self, project: Project, worker: Worker) -> AgentSession:
        """The worker's Session, read again under the project's row lock,
        which its registration's `seq` takes and holds until the transaction
        ends; refused unless its turn still runs. Finish and Archive stop the
        project's Sessions under that row (F5.1, F128.1), so a call that
        waited on it for either registers nothing in the project they closed.

        Raises:
            AuthorizationException: the Session has no turn running.
        """
        self.document_service.lock_project(project)
        session = self.db.get_one(
            AgentSession, worker.session_id, populate_existing=True
        )
        if session.state_code != SessionState.RUNNING:
            raise AuthorizationException(no_turn(Surface.WORK, session.id))
        return session

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
        copies = material(
            self.controller_client(), worker.environment_id, path, f"attach {path}"
        )
        attachments = self.attach_service.attach(
            item,
            self.db.get_one(AgentSession, worker.session_id),
            copies,
            environment_id=worker.environment_id,
        )
        self.effect_service.record(
            worker.session_id,
            tool_use_id,
            EffectLine(ATTACHED, attached_label(path, attachments), item_id=item.id),
            [
                Change(EffectKind.ATTACHED, attachment_id=attachment.id)
                for attachment in attachments
            ],
        )
        return attachments

    def set_progress(
        self, worker: Worker, steps: Sequence[ProgressStepRequestSchema]
    ) -> list[ProgressStep]:
        """The worker's own work item's list of steps replaced by `steps`, in
        their order (F85.3, DB 288): a code on the list keeps its row, its
        stamps and, where its step gives no state, its state; a new code
        starts `pending`, or in the state its step gives; a code left out
        goes, and no steps remove the list. Each change of a state is stamped
        by the server's clock (DB 287). No Effect is recorded (DB 289).

        Returns:
            The list as it stands, in order.

        Raises:
            InvalidOperationException: a code is repeated, nothing changed.
            AuthorizationException: the worker's Session has no turn running
                once its row is held, nothing changed.
        """
        operation = f"set the progress of work item {worker.work_item_id}"
        codes: set[str] = set()
        for given in steps:
            if given.code in codes:
                raise InvalidOperationException(
                    operation, f"code {given.code} is repeated"
                )
            codes.add(given.code)
        self._holding_its_turn(worker)
        at = datetime.now(UTC)
        standing = {step.code: step for step in self._steps(worker)}
        for position, given in enumerate(steps, start=1):
            step = standing.pop(given.code, None)
            if step is None:
                step = ProgressStep(
                    work_id=worker.work_item_id,
                    code=given.code,
                    state_code=ProgressState.PENDING,
                )
                self.db.add(step)
            step.label = given.label
            step.position = position
            if given.state is not None:
                _move(step, given.state, at)
        for left_out in standing.values():
            self.db.delete(left_out)
        self.db.flush()
        return self._steps(worker)

    def set_progress_step(
        self, worker: Worker, code: str, state: ProgressState
    ) -> list[ProgressStep]:
        """The step `code` of the worker's own work item's list moved to
        `state`, stamped by the server's clock (F85.4, DB 287); every step
        keeps its place (DB 285). No Effect is recorded (DB 289).

        Returns:
            The list as it stands, in order.

        Raises:
            RecordNotFoundException: the list has no step `code`.
            AuthorizationException: the worker's Session has no turn running
                once its row is held, nothing changed.
        """
        self._holding_its_turn(worker)
        step = self.db.get(
            ProgressStep, (worker.work_item_id, code), populate_existing=True
        )
        if step is None:
            raise RecordNotFoundException("Progress step", code)
        _move(step, state, datetime.now(UTC))
        self.db.flush()
        return self._steps(worker)

    def _holding_its_turn(self, worker: Worker) -> None:
        """Hold the worker's Session's row until the transaction ends, read
        as the lock found it, and refuse the call unless its turn still runs.
        Every change of the Session's state takes the row, so a call that
        waited on one reads its outcome; and two calls on the Work's list are
        served one after the other, the second reading the list the first
        left (DB 286).

        Raises:
            AuthorizationException: the Session has no turn running.
        """
        session = self.db.get_one(
            AgentSession,
            worker.session_id,
            with_for_update={"key_share": True},
            populate_existing=True,
        )
        if session.state_code != SessionState.RUNNING:
            raise AuthorizationException(no_turn(Surface.WORK, session.id))

    def _steps(self, worker: Worker) -> list[ProgressStep]:
        """The worker's own work item's list of steps, in order."""
        return list(
            self.db.scalars(
                select(ProgressStep)
                .where(ProgressStep.work_id == worker.work_item_id)
                .order_by(ProgressStep.position)
                .execution_options(populate_existing=True)
            )
        )


def _move(step: ProgressStep, state: ProgressState, at: datetime) -> None:
    """`step` moved to `state` at `at` (DB 287): its start written when it
    first goes `active` or `done`, never changed after; its end written when
    it goes `done`, cleared when it leaves it. A step already in `state` is
    left as it is."""
    if step.state_code == state:
        return
    if state is not ProgressState.PENDING and step.started_at is None:
        step.started_at = at
    step.ended_at = at if state is ProgressState.DONE else None
    step.state_code = state


def material(
    client: ControllerClient, environment_id: str, path: str, operation: str
) -> list[Copy]:
    """The file at `path` in the environment, else every file under the folder
    at `path`, read through the controller as one attach call copies them
    (F36.1, F36.6): a file one copy, a folder one per file under it, named by
    its path relative to the folder, in path order.

    Raises:
        InvalidOperationException: a file cannot be copied: the controller
            refused its read or the folder's listing — a path outside
            `/work`, nothing there, neither a file nor a folder, more than 16
            MiB, a link loop — or the call is over its cap of files or bytes.
        ExternalServiceException: the controller did not answer, or refused
            for a reason of its own.
    """
    try:
        content = client.read_file(environment_id, path)
    except ControllerProblem as problem:
        if problem.problem_type is not ControllerProblemType.NOT_A_FILE:
            _refuse(operation, problem)
            raise
        return _folder(client, environment_id, path, operation, problem)
    return [copied(_name(path), path, content.data)]


def attached_label(path: str, attachments: Sequence[Attachment]) -> str:
    """The label of an attach call's effect line: its one file's title, else
    the folder's name and its count of files."""
    if len(attachments) == 1:
        return attachments[0].title
    return f"{_name(path)}, {len(attachments)} files"


def _folder(
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
            raise InvalidOperationException(operation, not_a_file.cause) from not_a_file
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
                f"the folder's files are over the {MAX_CALL_SIZE}-byte cap of one call",
            )
        copies.append(copied(file.removeprefix(folder), file, content.data))
    return copies


def _name(path: str) -> str:
    """The file's or the folder's name at `path`."""
    return path.rstrip("/").rsplit("/", 1)[-1]


def _refuse(operation: str, problem: ControllerProblem) -> None:
    """Refuse the call when the controller's `problem` names what the session
    copying can fix."""
    if problem.problem_type in _UNCOPYABLE_FILE:
        raise InvalidOperationException(operation, problem.cause) from problem
