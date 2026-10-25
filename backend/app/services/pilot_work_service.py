"""`pilot-work`, a worker session's tools (TD §4.5, F85): the bearer its
Session was created with resolved to the Session, and `register_document`
(ruling D1)."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.documents import DocumentService, Registration, listed
from app.engine.ingest import IngestService
from app.exceptions import (
    AuthenticationException,
    AuthorizationException,
    InvalidOperationException,
)
from app.models import Project, SessionKind, Work
from app.models import Session as AgentSession
from app.services.controller_client import (
    ControllerClient,
    ControllerProblem,
    ControllerProblemType,
)
from app.services.pilot_server import token_hash

PILOT_WORK = "pilot-work"
"""The surface of a work item's Session (`session_kinds.surface`)."""

_BEARER = "Bearer "

_UNREADABLE_FILE = (
    ControllerProblemType.NOT_FOUND,
    ControllerProblemType.PATH_OUTSIDE_WORK,
    ControllerProblemType.NOT_A_FILE,
    ControllerProblemType.FILE_TOO_LARGE,
)
"""The controller's refusals of a read that name what the worker can fix."""


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
    ) -> None:
        self.db = db
        self.controller_client = controller_client
        self.document_service = document_service
        self.ingest_service = ingest_service

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

    def register_document(self, worker: Worker, path: str) -> Registration:
        """The document the worker wrote at `path` in its environment,
        registered (F85.1, ruling D1): the file read now and parsed as the
        worker's turn left it, then the item its run registered from the path
        already, else one minted, its text read at the turn's end.

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
        return self.document_service.register(
            project, self.db.get_one(AgentSession, worker.session_id), path
        )
