"""`pilot-work`: a bearer resolved to its work item's Session,
`register_document` (TD §4.5, F84, F85.1, ruling D1) and `attach_file`
(F85.2, F36.1), each call's Effects (R18, F41), against the fake controller,
`set_progress` and `set_progress_step`, the work item's steps (F85.3,
F85.4, F145.1; DB 285 to 289, a step's why 327), each change moving its
status alone (F145.4), a step's kind, mark and conversations, whether it was
listed ahead and the Step Timing of one that goes done (F156.1, F156.2; DB
353 to 358, 562 to 565, 572, 573), and `register_debrief`, its debrief,
stored once with its subject and whether it completes it, and moving nothing
(F85.5; DB 322 to 329, 608)."""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import pytest
from dependency_injector import providers
from flask import Flask
from sqlalchemy import func, select
from sqlalchemy import text as sql
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.engine.attachments import MAX_CALL_FILES, MAX_CALL_SIZE
from app.engine.bus import EngineEvent, WorkMoved
from app.exceptions import (
    AuthenticationException,
    AuthorizationException,
    InvalidOperationException,
    RecordNotFoundException,
)
from app.extensions import db
from app.models import (
    Attachment,
    DebriefEntry,
    Document,
    Effect,
    Environment,
    Item,
    ItemAttachment,
    ProgressStep,
    Project,
    StepKind,
    StepTiming,
    StepTranscript,
    Turn,
    User,
    Work,
)
from app.models.reference import (
    EffectKind,
    ProgressState,
    RecordKind,
    SessionState,
    TurnCause,
    UserKind,
)
from app.schemas.pilot_work import (
    DebriefEntryRequestSchema,
    ProgressStepRequestSchema,
)
from app.services.container import ServiceContainer
from app.services.controller_client import (
    FILE_SIZE_CAP,
    ControllerClient,
    ControllerProblem,
    ControllerProblemType,
    ControllerUnreachable,
    FileContent,
)
from app.services.pilot_server import token_hash
from app.services.pilot_work_service import Worker
from app.services.session_record_service import read_records
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.debriefs import FIGURES
from tests.support.fake_controller import ServedFakeController
from tests.support.locks import in_thread, lock_waits
from tests.support.supervisor import wait_until

TOKEN = "worker-token"

PATH = "/work/Example/docs/refinement.md"

TEXT = "Two options for the camp.\n\n```question id=Q1\n```\n"

ENVIRONMENT_ID = "example-env-1"
"""The environment of a committed run (`_committed_run`)."""


def _session(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
    environment: Environment,
    kind: str = "work",
    token: str = TOKEN,
    state: SessionState = SessionState.RUNNING,
) -> models.Session:
    """A Session of `kind` whose bearer is `token`, running unless `state`
    says otherwise; a work one with its Work."""
    run = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code=kind,
        cwd="/work/Example",
        token_hash=token_hash(token),
        state_code=state,
    )
    session.add(run)
    session.flush()
    if kind == "work":
        container.record_service().place_work(
            project, run, "Refining the camp", repo="example/Example"
        )
    return run


def _worker(run: models.Session) -> Worker:
    assert run.environment_id is not None
    return Worker(run.id, run.project_id, run.environment_id, run.id)


def _items(session: DbSession) -> int:
    return session.scalar(select(func.count()).select_from(Item)) or 0


def _committed_run(app: Flask) -> tuple[uuid.UUID, uuid.UUID]:
    """A draft project and a running work Session of it in `ENVIRONMENT_ID`,
    committed: their ids."""
    with scoped_session(app.container) as db_session:
        person = User(
            kind_code=UserKind.PERSON,
            subject="subject-ada",
            handle="ada",
            name="Ada Example",
            avatar_slot=1,
        )
        db_session.add(person)
        db_session.flush()
        project = Project(created_by_user_id=person.id)
        db_session.add(project)
        db_session.add(Environment(id=ENVIRONMENT_ID, name="Example-1", exempt=False))
        db_session.flush()
        run = models.Session(
            project_id=project.id,
            environment_id=ENVIRONMENT_ID,
            kind_code="work",
            cwd="/work/Example",
            token_hash=token_hash(TOKEN),
            state_code=SessionState.RUNNING,
        )
        db_session.add(run)
        db_session.flush()
        return project.id, run.id


class TestPilotWorkServiceAdmit:
    def test_a_work_items_bearer_names_its_session(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        _session(session, container, project, environment, token="another-token")

        worker = container.pilot_work_service().admit(f"Bearer {TOKEN}")

        assert worker == Worker(
            session_id=run.id,
            project_id=project.id,
            environment_id=environment.id,
            work_item_id=run.id,
        )

    @pytest.mark.parametrize(
        ("authorization", "message"),
        [
            (None, "Cannot call pilot-work because the request carries no bearer"),
            (
                f"Basic {TOKEN}",
                "Cannot call pilot-work because the request carries no bearer",
            ),
            (
                f"bearer {TOKEN}",
                "Cannot call pilot-work because the request carries no bearer",
            ),
            (
                "Bearer an-unknown-token",
                "Cannot call pilot-work because no session has the request's bearer",
            ),
            (
                f"Bearer {token_hash(TOKEN)}",
                "Cannot call pilot-work because no session has the request's bearer",
            ),
        ],
    )
    def test_no_bearer_or_an_unknown_one_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        authorization: str | None,
        message: str,
    ) -> None:
        _session(session, container, project, environment)

        with pytest.raises(AuthenticationException) as refused:
            container.pilot_work_service().admit(authorization)

        assert refused.value.message == message

    @pytest.mark.parametrize("kind", ["chat", "job"])
    def test_a_session_that_is_not_a_work_items_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        kind: str,
    ) -> None:
        run = _session(session, container, project, environment, kind=kind)

        with pytest.raises(AuthorizationException) as refused:
            container.pilot_work_service().admit(f"Bearer {TOKEN}")

        assert refused.value.message == (
            f"Cannot call pilot-work because session {run.id} is a {kind} session,"
            " not a work item's"
        )

    @pytest.mark.parametrize(
        "state",
        [
            SessionState.HELD,
            SessionState.STARTING,
            SessionState.IDLE,
            SessionState.STOPPED,
            SessionState.ENDED,
            SessionState.FAILED,
        ],
    )
    def test_a_session_whose_turn_does_not_run_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        state: SessionState,
    ) -> None:
        """A run Finish or Archive stopped, or one that has ended, admits
        nothing more through its bearer (P-60)."""
        run = _session(session, container, project, environment, state=state)

        with pytest.raises(AuthorizationException) as refused:
            container.pilot_work_service().admit(f"Bearer {TOKEN}")

        assert refused.value.message == (
            f"Cannot call pilot-work because session {run.id} has no turn running"
        )


class TestPilotWorkServiceRegisterDocument:
    def test_a_clean_file_is_registered_as_a_document_with_no_text(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        fake_controller.add_environment(environment.id)
        fake_controller.put_file(environment.id, PATH, TEXT.encode())

        registration = container.pilot_work_service().register_document(
            _worker(run), PATH, None
        )

        item = registration.item
        assert registration.minted
        assert (item.project_id, item.seq, item.kind_code, item.title) == (
            project.id,
            2,
            "review",
            None,
        )
        assert item.created_by_session_id == run.id
        document = session.get_one(Document, item.id)
        assert (
            document.path,
            document.source_environment_id,
            document.source_path,
            document.published_text,
        ) == ("inbox/2-refinement.md", environment.id, PATH, None)
        # The read changed nothing in the environment.
        assert fake_controller.environment(environment.id).files == {
            PATH: TEXT.encode()
        }

    def test_the_path_registered_again_in_the_run_is_the_same_item(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        fake_controller.add_environment(environment.id)
        fake_controller.put_file(environment.id, PATH, TEXT.encode())
        pilot_work = container.pilot_work_service()
        first = pilot_work.register_document(_worker(run), PATH, None)
        fake_controller.put_file(environment.id, PATH, b"# Refinement\n")

        again = pilot_work.register_document(_worker(run), PATH, None)

        assert (again.item.id, again.minted) == (first.item.id, False)
        assert _items(session) == 2

    def test_the_file_is_read_in_the_tokens_environment(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        fake_controller.add_environment(environment.id)
        fake_controller.add_environment("example-env-2")
        fake_controller.put_file("example-env-2", PATH, TEXT.encode())

        with pytest.raises(InvalidOperationException) as refused:
            container.pilot_work_service().register_document(_worker(run), PATH, None)

        assert refused.value.cause == (
            f"the controller answered 404 not-found: no such file or directory: {PATH!r}"
        )
        assert _items(session) == 1

    @pytest.mark.parametrize(
        ("path", "content", "cause"),
        [
            (
                "/etc/passwd",
                None,
                "the controller answered 403 path-outside-work: the path is outside"
                " the environment's /work; '/etc/passwd' leaves /work; only absolute"
                " paths under /work are reachable",
            ),
            (
                "docs/refinement.md",
                None,
                "the controller answered 403 path-outside-work: the path is outside"
                " the environment's /work; 'docs/refinement.md' leaves /work; only"
                " absolute paths under /work are reachable",
            ),
            (
                "/work/Example/docs/missing.md",
                None,
                "the controller answered 404 not-found: no such file or directory:"
                " '/work/Example/docs/missing.md'",
            ),
            (
                "/work/Example/docs",
                None,
                "the controller answered 409 not-a-file: '/work/Example/docs' is not"
                " a regular file; it is a directory",
            ),
            (
                PATH,
                b"x" * (FILE_SIZE_CAP + 1),
                f"the controller answered 413 file-too-large: {PATH!r} is too large;"
                f" the file surface reads and writes files of at most {FILE_SIZE_CAP}"
                " bytes",
            ),
        ],
        # The last case's content is 16 MB: named, so that its id is not.
        ids=["outside-work", "relative", "missing", "directory", "too-large"],
    )
    def test_a_file_the_controller_will_not_read_is_refused_with_its_reason(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
        path: str,
        content: bytes | None,
        cause: str,
    ) -> None:
        run = _session(session, container, project, environment)
        fake_controller.add_environment(environment.id)
        fake_controller.put_file(
            environment.id, PATH, TEXT.encode() if content is None else content
        )

        with pytest.raises(InvalidOperationException) as refused:
            container.pilot_work_service().register_document(_worker(run), path, None)

        assert refused.value.operation == f"register document {path}"
        assert refused.value.cause == cause
        assert _items(session) == 1

    def test_a_text_with_faults_is_refused_with_each_and_its_line(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        fake_controller.add_environment(environment.id)
        broken = "---\nfor: nobody\n---\n\nCamp \xff notes.\n"
        fake_controller.put_file(environment.id, PATH, broken.encode("latin-1"))

        with pytest.raises(InvalidOperationException) as refused:
            container.pilot_work_service().register_document(_worker(run), PATH, None)

        assert refused.value.cause == (
            "its text holds faults: line 2: front matter: `for: nobody` names no"
            " handle; line 5: the file is not UTF-8 text: each sequence that is"
            " not, and each NUL, is replaced by U+FFFD"
        )
        assert _items(session) == 1

    def test_an_unreadable_environment_is_the_controllers_failure(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        fake_controller.add_environment(environment.id)
        fake_controller.put_file(environment.id, PATH, TEXT.encode())
        fake_controller.unreadable(environment.id)

        with pytest.raises(ControllerProblem) as failed:
            container.pilot_work_service().register_document(_worker(run), PATH, None)

        assert failed.value.problem_type is ControllerProblemType.ENVIRONMENT_UNREADABLE
        assert _items(session) == 1

    def test_an_unanswered_read_mints_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        fake_controller.add_environment(environment.id)
        fake_controller.put_file(environment.id, PATH, TEXT.encode())
        fake_controller.outage()

        with pytest.raises(ControllerUnreachable):
            container.pilot_work_service().register_document(_worker(run), PATH, None)

        assert _items(session) == 1

    def test_a_registration_that_waited_out_a_finish_mints_nothing(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
    ) -> None:
        """Finish and Archive stop the project's Sessions under its row: a
        registration admitted while its Session ran, then waiting on the row,
        reads it again there, stopped, and mints nothing (P-60)."""
        container = committed_app.container
        project_id, run_id = _committed_run(committed_app)
        fake_controller.add_environment(ENVIRONMENT_ID)
        fake_controller.put_file(ENVIRONMENT_ID, PATH, TEXT.encode())
        with committed_app.app_context():
            engine = db.engine

        def register() -> object:
            with scoped_session(container):
                return container.pilot_work_service().register_document(
                    Worker(run_id, project_id, ENVIRONMENT_ID, run_id), PATH, None
                )

        with engine.connect() as finish:
            finish.execute(
                sql("SELECT id FROM projects WHERE id = :id FOR UPDATE"),
                {"id": project_id},
            )
            finish.execute(
                sql("UPDATE sessions SET state_code = 'stopped' WHERE id = :id"),
                {"id": run_id},
            )
            registration = in_thread(register)
            wait_until(lambda: lock_waits(container) == 1, "the registration waiting")
            finish.commit()

        with pytest.raises(AuthorizationException) as refused:
            registration.result()
        assert refused.value.message == (
            f"Cannot call pilot-work because session {run_id} has no turn running"
        )
        with scoped_session(container) as db_session:
            assert _items(db_session) == 0


FOLDER = "/work/Example/docs/survey"


class _Refusing:
    """A controller client whose read refuses with `read`, and its listing
    with `listing`: what the fake, which holds no links and no FIFOs, never
    answers."""

    def __init__(
        self, read: ControllerProblem, listing: ControllerProblem | None
    ) -> None:
        self._read = read
        self._listing = listing

    def read_file(self, env_id: str, path: str) -> FileContent:
        raise self._read

    def list_folder_files(self, env_id: str, path: str) -> list[str]:
        assert self._listing is not None
        raise self._listing


def _attached(session: DbSession, item: Item) -> list[tuple[int, int, str, str]]:
    """The item's attachments in order: position, batch, filename and source."""
    return [
        (position, batch, filename, f"{environment_id}:{source_path}")
        for position, batch, filename, environment_id, source_path in session.execute(
            select(
                ItemAttachment.position,
                Attachment.batch,
                Attachment.filename,
                Attachment.source_environment_id,
                Attachment.source_path,
            )
            .join(Attachment, Attachment.id == ItemAttachment.attachment_id)
            .where(ItemAttachment.item_id == item.id)
            .order_by(ItemAttachment.position)
        )
    ]


def _attachments(session: DbSession) -> int:
    return session.scalar(select(func.count()).select_from(Attachment)) or 0


class TestPilotWorkServiceAttachFile:
    def test_a_file_is_copied_onto_the_work_item_with_its_source(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        fake_controller.add_environment(environment.id)
        fake_controller.put_file(environment.id, PATH, TEXT.encode())

        [attachment] = container.pilot_work_service().attach_file(
            _worker(run), PATH, None, None
        )

        assert (
            attachment.title,
            attachment.filename,
            attachment.content_type,
            attachment.created_by_session_id,
            container.attachment_store().get(attachment),
        ) == ("refinement.md", "refinement.md", "text/markdown", run.id, TEXT.encode())
        assert _attached(session, session.get_one(Item, run.id)) == [
            (1, 1, "refinement.md", f"{environment.id}:{PATH}")
        ]

    def test_a_folder_is_every_file_under_it_in_one_batch_by_relative_name(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        fake_controller.add_environment(environment.id)
        for name in ("summary.md", "data/answers.json", "data/raw/b.csv"):
            fake_controller.put_file(environment.id, f"{FOLDER}/{name}", b"x")
        fake_controller.put_file(environment.id, PATH, TEXT.encode())

        attachments = container.pilot_work_service().attach_file(
            _worker(run), f"{FOLDER}/", None, None
        )

        source = environment.id
        assert _attached(session, session.get_one(Item, run.id)) == [
            (1, 1, "data/answers.json", f"{source}:{FOLDER}/data/answers.json"),
            (2, 1, "data/raw/b.csv", f"{source}:{FOLDER}/data/raw/b.csv"),
            (3, 1, "summary.md", f"{source}:{FOLDER}/summary.md"),
        ]
        assert [attachment.filename for attachment in attachments] == [
            "data/answers.json",
            "data/raw/b.csv",
            "summary.md",
        ]

    def test_to_hangs_them_on_an_item_of_the_project(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        fake_controller.add_environment(environment.id)
        fake_controller.put_file(environment.id, PATH, TEXT.encode())
        fake_controller.put_file(environment.id, f"{FOLDER}/a.md", b"# A\n")
        pilot_work = container.pilot_work_service()
        document = pilot_work.register_document(_worker(run), PATH, None).item

        [attachment] = pilot_work.attach_file(_worker(run), FOLDER, document.id, None)

        assert attachment.title == "A"
        assert _attached(session, document) == [
            (1, 1, "a.md", f"{environment.id}:{FOLDER}/a.md")
        ]
        assert _attached(session, session.get_one(Item, run.id)) == []

    def test_an_item_of_another_project_or_none_is_not_found(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
        person: models.User,
    ) -> None:
        run = _session(session, container, project, environment)
        other = Project(created_by_user_id=person.id)
        session.add(other)
        session.flush()
        elsewhere = _session(
            session, container, other, environment, token="another-token"
        )
        fake_controller.add_environment(environment.id)
        fake_controller.put_file(environment.id, PATH, TEXT.encode())
        pilot_work = container.pilot_work_service()

        for to in (elsewhere.id, uuid.uuid4()):
            with pytest.raises(RecordNotFoundException) as refused:
                pilot_work.attach_file(_worker(run), PATH, to, None)

            assert refused.value.message == f"Item {to} was not found"
        assert _attachments(session) == 0

    @pytest.mark.parametrize(
        ("path", "cause"),
        [
            (
                "/work/Example/docs/missing.md",
                "the controller answered 404 not-found: no such file or directory:"
                " '/work/Example/docs/missing.md'",
            ),
            (
                "/etc/passwd",
                "the controller answered 403 path-outside-work: the path is outside"
                " the environment's /work; '/etc/passwd' leaves /work; only absolute"
                " paths under /work are reachable",
            ),
            (
                f"{FOLDER}/big.bin",
                "the controller answered 413 file-too-large:"
                f" '{FOLDER}/big.bin' is too large; the file surface reads and"
                f" writes files of at most {FILE_SIZE_CAP} bytes",
            ),
            (
                FOLDER,
                "the controller answered 413 file-too-large:"
                f" '{FOLDER}/big.bin' is too large; the file surface reads and"
                f" writes files of at most {FILE_SIZE_CAP} bytes",
            ),
        ],
    )
    def test_a_file_that_cannot_be_copied_attaches_nothing_with_its_reason(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
        path: str,
        cause: str,
    ) -> None:
        run = _session(session, container, project, environment)
        fake_controller.add_environment(environment.id)
        fake_controller.put_file(environment.id, f"{FOLDER}/a.md", b"# A\n")
        fake_controller.put_file(
            environment.id, f"{FOLDER}/big.bin", bytes(FILE_SIZE_CAP + 1)
        )

        with pytest.raises(InvalidOperationException) as refused:
            container.pilot_work_service().attach_file(_worker(run), path, None, None)

        assert refused.value.operation == f"attach {path}"
        assert refused.value.cause == cause
        assert _attachments(session) == 0

    @pytest.mark.parametrize(
        ("read", "listing"),
        [
            # A link loop at the path.
            (ControllerProblemType.CONFLICT, None),
            # A FIFO at the path: neither a file nor a folder.
            (ControllerProblemType.NOT_A_FILE, ControllerProblemType.NOT_A_DIRECTORY),
        ],
        ids=["link-loop", "fifo"],
    )
    def test_a_link_loop_or_a_fifo_at_the_path_attaches_nothing_with_the_reads_reason(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        read: ControllerProblemType,
        listing: ControllerProblemType | None,
    ) -> None:
        run = _session(session, container, project, environment)
        problem = ControllerProblem(
            f"read {PATH} in environment {environment.id}", read, "a scripted refusal"
        )
        container.controller_client.override(
            providers.Object(
                _Refusing(
                    problem,
                    None
                    if listing is None
                    else ControllerProblem(
                        f"list {PATH} in environment {environment.id}",
                        listing,
                        "a scripted listing refusal",
                    ),
                )
            )
        )

        with pytest.raises(InvalidOperationException) as refused:
            container.pilot_work_service().attach_file(_worker(run), PATH, None, None)

        assert refused.value.operation == f"attach {PATH}"
        assert refused.value.cause == problem.cause
        assert _attachments(session) == 0

    def test_a_folder_over_the_calls_cap_of_files_reads_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        fake_controller.add_environment(environment.id)
        # The first file in path order a read would refuse.
        fake_controller.put_file(
            environment.id, f"{FOLDER}/0.md", bytes(FILE_SIZE_CAP + 1)
        )
        for number in range(1, MAX_CALL_FILES + 1):
            fake_controller.put_file(environment.id, f"{FOLDER}/{number}.md", b"x")

        with pytest.raises(InvalidOperationException) as refused:
            container.pilot_work_service().attach_file(_worker(run), FOLDER, None, None)

        assert refused.value.cause == (
            f"the folder holds {MAX_CALL_FILES + 1} files, over the"
            f" {MAX_CALL_FILES}-file cap of one call"
        )
        assert _attachments(session) == 0

    def test_a_folder_over_the_calls_cap_of_bytes_attaches_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        fake_controller.add_environment(environment.id)
        for number in range(MAX_CALL_SIZE // FILE_SIZE_CAP):
            fake_controller.put_file(
                environment.id, f"{FOLDER}/{number}.bin", bytes(FILE_SIZE_CAP)
            )
        fake_controller.put_file(environment.id, f"{FOLDER}/last.bin", b"x")

        with pytest.raises(InvalidOperationException) as refused:
            container.pilot_work_service().attach_file(_worker(run), FOLDER, None, None)

        assert refused.value.cause == (
            f"the folder's files are over the {MAX_CALL_SIZE}-byte cap of one call"
        )
        assert _attachments(session) == 0

    def test_an_unreadable_environment_is_the_controllers_failure(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        fake_controller.add_environment(environment.id)
        fake_controller.put_file(environment.id, PATH, TEXT.encode())
        fake_controller.unreadable(environment.id)

        with pytest.raises(ControllerProblem) as failed:
            container.pilot_work_service().attach_file(_worker(run), PATH, None, None)

        assert failed.value.problem_type is ControllerProblemType.ENVIRONMENT_UNREADABLE
        assert _attachments(session) == 0

    def test_an_unanswered_read_attaches_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        fake_controller.add_environment(environment.id)
        fake_controller.put_file(environment.id, PATH, TEXT.encode())
        fake_controller.outage()

        with pytest.raises(ControllerUnreachable):
            container.pilot_work_service().attach_file(_worker(run), PATH, None, None)

        assert _attachments(session) == 0


TOOL_USE_ID = "toolu_01ABC"


def _turn_in_flight(session: DbSession, run: models.Session) -> Turn:
    """The worker's turn, its brief sent and not ended."""
    turn = Turn(
        session_id=run.id,
        seq=1,
        message="Refine the camp.",
        started_at=datetime.now(UTC),
        cause_code=TurnCause.BRIEF,
    )
    session.add(turn)
    session.flush()
    return turn


def _effect_records(session: DbSession, run: models.Session) -> list[Any]:
    """The payloads of the Session's records, every one an effect's here."""
    return [
        stored.record.payload for stored in read_records(session, run.id, limit=100)
    ]


def _effects(session: DbSession) -> list[tuple[int, int, EffectKind, uuid.UUID | None]]:
    return [
        (effect.turn_id, effect.record_id, effect.kind_code, effect.item_id)
        for effect in session.scalars(select(Effect).order_by(Effect.id))
    ]


class TestPilotWorkServiceEffects:
    """Each call that changed the record writes its Effects, placed by one
    `server` record of the worker's turn (R18, F41)."""

    def test_a_registration_is_registered_naming_its_place(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        turn = _turn_in_flight(session, run)
        fake_controller.add_environment(environment.id)
        fake_controller.put_file(environment.id, PATH, TEXT.encode())

        item = (
            container.pilot_work_service()
            .register_document(_worker(run), PATH, TOOL_USE_ID)
            .item
        )

        [record] = read_records(session, run.id, limit=10)
        assert (record.record.kind_code, record.turn) == (RecordKind.SERVER, 1)
        assert record.record.payload == {
            "type": "effect",
            "toolUseId": TOOL_USE_ID,
            "effect": {
                "verb": "Registered",
                "label": "inbox/2",
                "itemId": str(item.id),
            },
        }
        assert _effects(session) == [
            (turn.id, record.record.id, EffectKind.REGISTERED, item.id)
        ]

    def test_the_path_registered_again_changes_nothing_and_records_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        _turn_in_flight(session, run)
        fake_controller.add_environment(environment.id)
        fake_controller.put_file(environment.id, PATH, TEXT.encode())
        pilot_work = container.pilot_work_service()
        pilot_work.register_document(_worker(run), PATH, TOOL_USE_ID)

        pilot_work.register_document(_worker(run), PATH, "toolu_02")

        assert [payload["toolUseId"] for payload in _effect_records(session, run)] == [
            TOOL_USE_ID
        ]
        assert len(_effects(session)) == 1

    def test_a_refused_registration_records_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        _turn_in_flight(session, run)
        fake_controller.add_environment(environment.id)
        fake_controller.put_file(environment.id, PATH, b"```question id=Q1\n")

        with pytest.raises(InvalidOperationException):
            container.pilot_work_service().register_document(
                _worker(run), PATH, TOOL_USE_ID
            )

        assert _effect_records(session, run) == []
        assert _effects(session) == []

    def test_a_file_attached_is_attached_by_its_title_on_its_item(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        turn = _turn_in_flight(session, run)
        fake_controller.add_environment(environment.id)
        fake_controller.put_file(
            environment.id, PATH, b"---\ntitle: Diagnosis of the 401s\n---\n"
        )

        [attachment] = container.pilot_work_service().attach_file(
            _worker(run), PATH, None, TOOL_USE_ID
        )

        [record] = read_records(session, run.id, limit=10)
        assert record.record.payload == {
            "type": "effect",
            "toolUseId": TOOL_USE_ID,
            "effect": {
                "verb": "Attached",
                "label": "Diagnosis of the 401s",
                "itemId": str(run.id),
            },
        }
        [effect] = session.scalars(select(Effect)).all()
        assert (
            effect.turn_id,
            effect.record_id,
            effect.kind_code,
            effect.attachment_id,
        ) == (turn.id, record.record.id, EffectKind.ATTACHED, attachment.id)

    def test_a_folder_attached_is_one_line_for_an_effect_per_file(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        _turn_in_flight(session, run)
        fake_controller.add_environment(environment.id)
        for name in ("summary.md", "data/answers.json", "data/raw/b.csv"):
            fake_controller.put_file(environment.id, f"{FOLDER}/{name}", b"x")
        fake_controller.put_file(environment.id, PATH, TEXT.encode())
        pilot_work = container.pilot_work_service()
        document = pilot_work.register_document(_worker(run), PATH, "toolu_01").item

        attachments = pilot_work.attach_file(
            _worker(run), f"{FOLDER}/", document.id, "toolu_02"
        )

        registered, attached = read_records(session, run.id, limit=10)
        assert attached.record.payload == {
            "type": "effect",
            "toolUseId": "toolu_02",
            "effect": {
                "verb": "Attached",
                "label": "survey, 3 files",
                "itemId": str(document.id),
            },
        }
        assert [
            (effect.record_id, effect.kind_code, effect.attachment_id)
            for effect in session.scalars(
                select(Effect)
                .where(Effect.record_id == attached.record.id)
                .order_by(Effect.id)
            )
        ] == [
            (attached.record.id, EffectKind.ATTACHED, attachment.id)
            for attachment in attachments
        ]
        assert registered.record.payload["effect"]["verb"] == "Registered"

    def test_a_refused_attachment_records_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        _turn_in_flight(session, run)
        fake_controller.add_environment(environment.id)

        with pytest.raises(InvalidOperationException):
            container.pilot_work_service().attach_file(
                _worker(run), "/work/Example/missing.md", None, TOOL_USE_ID
            )

        assert _effect_records(session, run) == []
        assert _effects(session) == []

    def test_a_call_outside_a_turn_changes_the_record_and_records_no_effect(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        project: Project,
        environment: Environment,
    ) -> None:
        """A running Session's call that finds no Turn in flight stands, with
        no Turn to record its Effects under."""
        run = _session(session, container, project, environment)
        fake_controller.add_environment(environment.id)
        fake_controller.put_file(environment.id, PATH, TEXT.encode())
        pilot_work = container.pilot_work_service()

        registration = pilot_work.register_document(_worker(run), PATH, TOOL_USE_ID)
        [attachment] = pilot_work.attach_file(_worker(run), PATH, None, TOOL_USE_ID)

        assert registration.minted
        assert attachment.id is not None
        assert _effect_records(session, run) == []
        assert _effects(session) == []


PENDING, ACTIVE, DONE = ProgressState.PENDING, ProgressState.ACTIVE, ProgressState.DONE

EARLIER = datetime(2026, 11, 1, 9, 30, tzinfo=UTC)
"""A stamp a test writes before its call, which the call keeps or replaces."""

WHY = "The reviewer found the migration's downgrade left the column"


def _step(
    code: str,
    label: str | None = None,
    state: ProgressState | None = None,
    why: str | None = None,
    *,
    kind: str | None = None,
    duration: int | None = None,
    marked: bool | None = None,
    conversations: list[str] | None = None,
) -> ProgressStepRequestSchema:
    return ProgressStepRequestSchema(
        code=code,
        label=label or code,
        state=state,
        why=why,
        kind=kind,
        duration=duration,
        marked=marked,
        conversations=conversations,
    )


def _listed(steps: list[ProgressStep]) -> list[tuple[str, str, int, ProgressState]]:
    return [(step.code, step.label, step.position, step.state_code) for step in steps]


def _stored(session: DbSession, run: models.Session) -> list[ProgressStep]:
    return list(
        session.scalars(
            select(ProgressStep)
            .where(ProgressStep.work_id == run.id)
            .order_by(ProgressStep.position)
        )
    )


class _Clock:
    """The server's clock around a call: a stamp it wrote lies between."""

    def __enter__(self) -> "_Clock":
        self.before = datetime.now(UTC)
        return self

    def __exit__(self, *_: object) -> None:
        self.after = datetime.now(UTC)

    def stamped(self, at: datetime | None) -> bool:
        return at is not None and self.before <= at <= self.after


class TestPilotWorkServiceSetProgress:
    def test_a_list_published_to_a_new_work_is_stamped_at_the_call(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """Steps already done when a list is published whole, as a resume
        after Done publishes it, are stamped at that call (DB 287)."""
        run = _session(session, container, project, environment)

        with _Clock() as clock:
            answered = container.pilot_work_service().set_progress(
                _worker(run),
                [
                    _step("P1.code", "P1 · the client", DONE),
                    _step("test", "Test", ACTIVE),
                    _step("docs", "Docs"),
                ],
            )

        assert _listed(answered) == [
            ("P1.code", "P1 · the client", 1, DONE),
            ("test", "Test", 2, ACTIVE),
            ("docs", "Docs", 3, PENDING),
        ]
        assert _listed(_stored(session, run)) == _listed(answered)
        code, test, docs = answered
        assert clock.stamped(code.started_at)
        assert code.ended_at == code.started_at
        assert clock.stamped(test.started_at)
        assert test.ended_at is None
        assert (docs.started_at, docs.ended_at) == (None, None)

    def test_a_kept_code_keeps_its_row_its_stamps_and_where_none_is_given_its_state(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(
            _worker(run), [_step("P1.code", state=DONE), _step("test", state=ACTIVE)]
        )
        [code, test] = _stored(session, run)
        code.started_at = code.ended_at = test.started_at = EARLIER
        session.flush()

        answered = pilot_work.set_progress(
            _worker(run),
            [
                _step("P1.review", "P1 · review"),
                _step("test", "Test, again"),
                _step("P1.code", "P1 · the client"),
            ],
        )

        assert _listed(answered) == [
            ("P1.review", "P1 · review", 1, PENDING),
            ("test", "Test, again", 2, ACTIVE),
            ("P1.code", "P1 · the client", 3, DONE),
        ]
        _, test, code = _stored(session, run)
        assert (test.started_at, test.ended_at) == (EARLIER, None)
        assert (code.started_at, code.ended_at) == (EARLIER, EARLIER)

    def test_a_kept_steps_given_state_moves_it_and_back_keeps_its_start(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(_worker(run), [_step("test", state=DONE)])
        [test] = _stored(session, run)
        test.started_at = test.ended_at = EARLIER
        session.flush()

        [moved] = pilot_work.set_progress(_worker(run), [_step("test", state=ACTIVE)])

        assert (moved.state_code, moved.started_at, moved.ended_at) == (
            ACTIVE,
            EARLIER,
            None,
        )

    def test_a_code_left_out_goes_and_no_steps_remove_the_list(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(
            _worker(run), [_step("P1.code"), _step("test"), _step("docs")]
        )

        kept = pilot_work.set_progress(_worker(run), [_step("docs"), _step("P1.code")])

        assert _listed(kept) == [
            ("docs", "docs", 1, PENDING),
            ("P1.code", "P1.code", 2, PENDING),
        ]
        assert pilot_work.set_progress(_worker(run), []) == []
        assert _stored(session, run) == []

    def test_a_repeated_code_is_refused_and_changes_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(_worker(run), [_step("test", state=ACTIVE)])

        with pytest.raises(InvalidOperationException) as refused:
            pilot_work.set_progress(
                _worker(run), [_step("test"), _step("docs"), _step("test", "Test")]
            )

        assert refused.value.message == (
            f"Cannot set the progress of work item {run.id} because code test is"
            " repeated"
        )
        assert _listed(_stored(session, run)) == [("test", "test", 1, ACTIVE)]

    def test_a_turn_ended_after_the_gate_changes_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        worker = _worker(run)
        run.state_code = SessionState.STOPPED
        session.flush()

        with pytest.raises(AuthorizationException) as refused:
            container.pilot_work_service().set_progress(worker, [_step("test")])

        assert refused.value.message == (
            f"Cannot call pilot-work because session {run.id} has no turn running"
        )
        assert _stored(session, run) == []

    def test_only_the_workers_own_work_item_is_listed(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """Each work item a list of its own (F145.1); no Session writes
        another Work's steps (DB 286)."""
        run = _session(session, container, project, environment)
        other = _session(session, container, project, environment, token="other")
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(_worker(other), [_step("reproduce", state=ACTIVE)])

        pilot_work.set_progress(_worker(run), [_step("test")])

        assert _listed(_stored(session, other)) == [
            ("reproduce", "reproduce", 1, ACTIVE)
        ]
        assert _listed(_stored(session, run)) == [("test", "test", 1, PENDING)]

    def test_a_steps_why_stands_as_the_last_call_gave_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """DB 327: taken on any step, as its label is; a step the call gives
        without one has none, and a step moved keeps its own."""
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(
            _worker(run),
            [_step("P1.code", state=DONE, why="First"), _step("P1.code-2", why=WHY)],
        )

        moved = [
            step.why
            for step in pilot_work.set_progress_step(_worker(run), "P1.code-2", ACTIVE)
        ]
        published = [
            step.why
            for step in pilot_work.set_progress(
                _worker(run),
                [_step("P1.code", state=DONE), _step("P1.code-2", why="Again")],
            )
        ]

        assert moved == ["First", WHY]
        assert published == [None, "Again"]
        assert [step.why for step in _stored(session, run)] == [None, "Again"]


CODE_WRITER, REVIEW = "code-writer", "review"
"""Two kinds a run gives its steps, invented."""

THREAD, OTHER_THREAD, THIRD_THREAD = (
    "6f1d2c9e-0b7a-4e58-9a31-5c8e2f4d7b06",
    "b2a47c10-93de-4f6b-8c05-1e7d9a3f6c42",
    "0d5e8b73-41fa-4c29-b6e8-7a2c9f105d3b",
)
"""Claude Code session ids of three conversations, invented."""


def _kinds(session: DbSession) -> list[tuple[str, str]]:
    return [
        (kind.code, kind.name)
        for kind in session.scalars(select(StepKind).order_by(StepKind.code))
    ]


def _named(session: DbSession, run: models.Session) -> list[tuple[str, str]]:
    """The conversations the run's steps name, by step and id."""
    return [
        (naming.code, naming.session_id)
        for naming in session.scalars(
            select(StepTranscript)
            .where(StepTranscript.work_id == run.id)
            .order_by(StepTranscript.code, StepTranscript.session_id)
        )
    ]


def _timings(session: DbSession, run: models.Session) -> list[StepTiming]:
    return list(
        session.scalars(
            select(StepTiming)
            .where(StepTiming.work_id == run.id)
            .order_by(StepTiming.id)
            .execution_options(populate_existing=True)
        )
    )


def _timed(
    session: DbSession, run: models.Session
) -> list[tuple[str | None, str, int, bool | None, bool | None]]:
    """The run's timings: each one's code, kind, duration, listing and mark."""
    return [
        (
            timing.code,
            timing.kind_code,
            timing.duration,
            timing.listed_ahead,
            timing.marked,
        )
        for timing in _timings(session, run)
    ]


class TestPilotWorkServiceSetProgressKindMarkAndConversations:
    def test_a_steps_kind_and_mark_stand_as_the_last_call_gave_them(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """As its why does: a step the call gives without one has none, and a
        step moved keeps its own."""
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(
            _worker(run),
            [
                _step("P1.code", state=ACTIVE, kind=CODE_WRITER, marked=False),
                _step("P1.review", kind=REVIEW),
            ],
        )

        moved = [
            (step.kind_code, step.marked)
            for step in pilot_work.set_progress_step(_worker(run), "P1.code", DONE)
        ]
        published = [
            (step.kind_code, step.marked)
            for step in pilot_work.set_progress(
                _worker(run),
                [_step("P1.code"), _step("P1.review", kind=CODE_WRITER, marked=True)],
            )
        ]

        assert moved == [(CODE_WRITER, False), (REVIEW, None)]
        assert published == [(None, None), (CODE_WRITER, True)]
        assert [(step.kind_code, step.marked) for step in _stored(session, run)] == [
            (None, None),
            (CODE_WRITER, True),
        ]

    def test_a_kind_is_met_once_as_given_and_read_out_of_no_code(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """F156.1: opaque, stored as given, its name the kind itself (DB
        §7.2); a step with none has none, whatever its code says."""
        run = _session(session, container, project, environment)
        other = _session(session, container, project, environment, token="other")
        pilot_work = container.pilot_work_service()

        pilot_work.set_progress(
            _worker(run),
            [
                _step("P1.code-writer-1", kind=" Code Writer "),
                _step("P1.review-1"),
                _step("P2.code-writer-1", kind=" Code Writer "),
            ],
        )
        pilot_work.set_progress(_worker(other), [_step("x", kind=" Code Writer ")])

        assert _kinds(session) == [(" Code Writer ", " Code Writer ")]
        assert [step.kind_code for step in _stored(session, run)] == [
            " Code Writer ",
            None,
            " Code Writer ",
        ]

    def test_a_mark_is_taken_on_a_step_in_any_state(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)

        listed = container.pilot_work_service().set_progress(
            _worker(run),
            [
                _step("a", state=PENDING, marked=True),
                _step("b", state=ACTIVE, marked=True),
                _step("c", state=DONE, marked=True),
                _step("d", state=ACTIVE, marked=False),
            ],
        )

        assert [step.marked for step in listed] == [True, True, True, False]

    def test_a_step_names_the_conversations_its_last_call_gave_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """DB 355: replaced with the step's list; a step given without any
        names none, and one moved keeps its own."""
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(
            _worker(run),
            [
                _step("P1.code", state=ACTIVE, conversations=[THREAD, OTHER_THREAD]),
                _step("test", conversations=[THREAD]),
            ],
        )
        first = _named(session, run)

        pilot_work.set_progress_step(_worker(run), "P1.code", DONE)
        moved = _named(session, run)
        pilot_work.set_progress(
            _worker(run),
            [
                _step("P1.code", conversations=[OTHER_THREAD, THIRD_THREAD]),
                _step("test"),
                _step("docs", conversations=[]),
            ],
        )

        assert first == [
            ("P1.code", THREAD),
            ("P1.code", OTHER_THREAD),
            ("test", THREAD),
        ]
        assert moved == first
        assert _named(session, run) == [
            ("P1.code", THIRD_THREAD),
            ("P1.code", OTHER_THREAD),
        ]

    def test_a_step_left_out_takes_its_conversations_with_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """DB 356; and no Session names another Work's conversations."""
        run = _session(session, container, project, environment)
        other = _session(session, container, project, environment, token="other")
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(
            _worker(other), [_step("P1.code", conversations=[THREAD])]
        )
        pilot_work.set_progress(
            _worker(run),
            [
                _step("P1.code", conversations=[THREAD]),
                _step("test", conversations=[OTHER_THREAD]),
            ],
        )

        pilot_work.set_progress(_worker(run), [_step("test")])
        kept = _named(session, run)
        pilot_work.set_progress(_worker(run), [_step("P1.code")])

        assert kept == []
        assert _named(session, run) == []
        assert _named(session, other) == [("P1.code", THREAD)]


class TestPilotWorkServiceListedAhead:
    """F156.1, DB decision 79: the server's own observation, written with a
    step's first start."""

    def test_a_works_first_list_leaves_a_begun_steps_listing_unknown(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """A continuation's running step, and its done ones; a step still
        pending has not begun."""
        run = _session(session, container, project, environment)

        listed = container.pilot_work_service().set_progress(
            _worker(run),
            [_step("a", state=DONE), _step("b", state=ACTIVE), _step("c")],
        )

        assert [step.listed_ahead for step in listed] == [None, None, None]

    def test_a_step_that_stood_pending_was_listed_ahead_whichever_call_begins_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(
            _worker(run), [_step("a", state=ACTIVE), _step("b"), _step("c"), _step("d")]
        )

        pilot_work.set_progress_step(_worker(run), "b", ACTIVE)
        listed = pilot_work.set_progress(
            _worker(run),
            [_step("a"), _step("b"), _step("c", state=DONE), _step("d")],
        )

        assert [step.listed_ahead for step in listed] == [None, True, True, None]

    def test_a_step_a_later_list_brings_begun_was_not_listed_ahead(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """A repeat round first seen running, or first seen done."""
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(_worker(run), [_step("P1.review-1", state=ACTIVE)])

        listed = pilot_work.set_progress(
            _worker(run),
            [
                _step("P1.review-1", state=DONE),
                _step("P1.code-2", state=DONE),
                _step("P1.review-2", state=ACTIVE),
                _step("test"),
            ],
        )

        assert [step.listed_ahead for step in listed] == [None, False, False, None]

    def test_a_listing_is_written_once_with_the_steps_first_start(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """A step moved back to pending and begun again keeps it, as it keeps
        its start (DB 287)."""
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(_worker(run), [_step("a", state=ACTIVE), _step("b")])
        pilot_work.set_progress(
            _worker(run), [_step("a"), _step("b"), _step("c", state=ACTIVE)]
        )

        for state in (PENDING, ACTIVE, PENDING):
            pilot_work.set_progress_step(_worker(run), "a", state)
            pilot_work.set_progress_step(_worker(run), "c", state)
        listed = pilot_work.set_progress(
            _worker(run),
            [_step("a", state=DONE), _step("b"), _step("c", state=DONE)],
        )

        assert [step.listed_ahead for step in listed] == [None, None, False]

    def test_a_list_published_after_the_list_was_removed_is_a_first_list(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """Pilot holds no list the step could have stood pending on."""
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(_worker(run), [_step("a")])
        pilot_work.set_progress(_worker(run), [])

        [begun] = pilot_work.set_progress(_worker(run), [_step("a", state=ACTIVE)])

        assert begun.listed_ahead is None


class TestPilotWorkServiceStepTiming:
    """F156.2: a step Pilot holds as not done that goes done with a kind and
    a duration is kept as a Step Timing, once."""

    def test_a_held_step_gone_done_with_a_kind_and_a_duration_is_timed(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """Its end the server's clock at the move, its mark the step's as it
        went done, its listing the step's, and its repo its Work's."""
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(
            _worker(run),
            [
                _step("P1.code", state=ACTIVE, kind=CODE_WRITER, marked=True),
                _step("P1.review", kind=REVIEW, marked=True),
                _step("test", kind="test"),
            ],
        )

        with _Clock() as clock:
            pilot_work.set_progress(
                _worker(run),
                [
                    _step("P1.code", state=DONE, kind=CODE_WRITER, duration=1440),
                    _step(
                        "P1.review",
                        state=DONE,
                        kind=REVIEW,
                        duration=0,
                        marked=True,
                    ),
                    _step("test", state=ACTIVE, kind="test"),
                ],
            )

        assert _timed(session, run) == [
            ("P1.code", CODE_WRITER, 1440, None, None),
            ("P1.review", REVIEW, 0, True, True),
        ]
        code, review = _timings(session, run)
        [stored, *_] = _stored(session, run)
        assert clock.stamped(code.ended_at)
        assert code.ended_at == review.ended_at == stored.ended_at
        assert (code.key, code.repo) == (None, "example/Example")

    def test_a_step_with_no_kind_or_no_duration_leaves_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(
            _worker(run), [_step("a"), _step("b", kind=REVIEW), _step("c")]
        )

        pilot_work.set_progress(
            _worker(run),
            [
                _step("a", state=DONE, duration=60),
                _step("b", state=DONE, kind=REVIEW),
                _step("c", state=DONE),
            ],
        )

        assert _timed(session, run) == []

    def test_a_step_first_seen_done_leaves_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """A continuation's done steps arrive done at its Work's first list
        and are not timed again; nor is one a later list brings done."""
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()

        pilot_work.set_progress(
            _worker(run),
            [
                _step("P1.code", state=DONE, kind=CODE_WRITER, duration=1440),
                _step("P1.review", state=ACTIVE, kind=REVIEW),
            ],
        )
        pilot_work.set_progress(
            _worker(run),
            [
                _step("P1.code", state=DONE, kind=CODE_WRITER, duration=1440),
                _step("P1.review", state=ACTIVE, kind=REVIEW),
                _step("P1.code-2", state=DONE, kind=CODE_WRITER, duration=300),
            ],
        )

        assert _timed(session, run) == []

    def test_a_step_is_timed_once_though_moved_back_and_done_again(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """DB 572: no two timings of one Work have one code."""
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(_worker(run), [_step("a"), _step("b")])
        done = [
            _step("a", state=DONE, kind=CODE_WRITER, duration=600),
            _step("b", state=ACTIVE, kind=REVIEW),
        ]
        pilot_work.set_progress(_worker(run), done)
        [first] = _timings(session, run)
        ended_at = first.ended_at

        pilot_work.set_progress(_worker(run), done)
        pilot_work.set_progress_step(_worker(run), "a", ACTIVE)
        pilot_work.set_progress(
            _worker(run),
            [
                _step("a", state=DONE, kind=REVIEW, duration=900, marked=True),
                _step("b", state=DONE, kind=REVIEW, duration=120),
            ],
        )

        assert _timed(session, run) == [
            ("a", CODE_WRITER, 600, True, None),
            ("b", REVIEW, 120, True, None),
        ]
        assert _timings(session, run)[0].ended_at == ended_at

    def test_a_timing_stays_when_its_step_leaves_the_list(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """DB 573; and its code, published anew, is not timed again."""
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(_worker(run), [_step("a"), _step("b")])
        pilot_work.set_progress(
            _worker(run),
            [_step("a", state=DONE, kind=CODE_WRITER, duration=600), _step("b")],
        )

        pilot_work.set_progress(_worker(run), [_step("b")])
        left = _timed(session, run)
        pilot_work.set_progress(_worker(run), [])
        pilot_work.set_progress(_worker(run), [_step("a")])
        pilot_work.set_progress(
            _worker(run), [_step("a", state=DONE, kind=CODE_WRITER, duration=5)]
        )

        assert left == [("a", CODE_WRITER, 600, True, None)]
        assert _timed(session, run) == left

    def test_a_step_set_progress_step_turns_done_leaves_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """F85.4 takes no duration."""
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(
            _worker(run), [_step("a", state=ACTIVE, kind=CODE_WRITER)]
        )

        pilot_work.set_progress_step(_worker(run), "a", DONE)

        assert _timed(session, run) == []

    def test_a_timings_repo_is_its_works_as_it_is_written(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """DB 572: the Work's label, else its environment's, none with
        neither; stored, so that a later label leaves it."""
        run = _session(session, container, project, environment)
        work = session.get_one(Work, run.id)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(_worker(run), [_step("a"), _step("b"), _step("c")])

        def done(code: str) -> None:
            pilot_work.set_progress(
                _worker(run),
                [
                    _step(code, state=DONE, kind=CODE_WRITER, duration=60),
                    *(_step(other) for other in "abc" if other != code),
                ],
            )

        done("a")
        work.repo = None
        session.flush()
        done("b")
        environment.server_created_at = EARLIER
        environment.repo = "example/Other"
        session.flush()
        done("c")

        assert {timing.code: timing.repo for timing in _timings(session, run)} == {
            "a": "example/Example",
            "b": None,
            "c": "example/Other",
        }

    def test_a_duration_on_a_step_the_call_leaves_not_done_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """Whether the call gives the state, the list holds it or the code is
        new; nothing changed, no kind met."""
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(_worker(run), [_step("a", state=ACTIVE), _step("b")])
        refusals = []

        for refused_step in (
            _step("a", state=ACTIVE, kind=REVIEW, duration=60),
            _step("b", state=PENDING, kind=REVIEW, duration=60),
            _step("a", kind=REVIEW, duration=60),
            _step("new", kind=REVIEW, duration=60),
        ):
            with pytest.raises(InvalidOperationException) as refused:
                pilot_work.set_progress(
                    _worker(run), [_step("first", kind=REVIEW), refused_step]
                )
            refusals.append(refused.value.message)

        assert refusals == [
            f"Cannot set the progress of work item {run.id} because step {code} has"
            " a duration and is not done"
            for code in ("a", "b", "a", "new")
        ]
        assert _listed(_stored(session, run)) == [
            ("a", "a", 1, ACTIVE),
            ("b", "b", 2, PENDING),
        ]
        assert _kinds(session) == []
        assert _timed(session, run) == []

    def test_a_duration_on_a_step_the_list_holds_done_is_taken_and_times_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """A step given no state keeps its own, so the call leaves it done;
        Pilot did not hold it as not done."""
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(_worker(run), [_step("a", state=ACTIVE)])
        pilot_work.set_progress_step(_worker(run), "a", DONE)

        [kept] = pilot_work.set_progress(
            _worker(run), [_step("a", kind=CODE_WRITER, duration=60)]
        )

        assert (kept.state_code, kept.kind_code) == (DONE, CODE_WRITER)
        assert _timed(session, run) == []


_Stamp = Literal["earlier", "now"] | None


class TestPilotWorkServiceSetProgressStep:
    @pytest.mark.parametrize(
        ("before", "after", "started", "ended"),
        [
            (PENDING, ACTIVE, "now", None),
            (PENDING, DONE, "now", "now"),
            (ACTIVE, DONE, "earlier", "now"),
            (DONE, ACTIVE, "earlier", None),
            (DONE, PENDING, "earlier", None),
            (ACTIVE, PENDING, "earlier", None),
            (DONE, DONE, "earlier", "earlier"),
            (ACTIVE, ACTIVE, "earlier", None),
            (PENDING, PENDING, None, None),
        ],
    )
    def test_the_step_moves_its_start_written_once_its_end_while_done(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        before: ProgressState,
        after: ProgressState,
        started: _Stamp,
        ended: _Stamp,
    ) -> None:
        """DB 287: the start written when the step first goes `active` or
        `done`, never changed after; the end written when it goes `done`,
        cleared when it leaves it."""
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(_worker(run), [_step("test", state=before)])
        [test] = _stored(session, run)
        test.started_at = None if before is PENDING else EARLIER
        test.ended_at = EARLIER if before is DONE else None
        session.flush()

        with _Clock() as clock:
            [moved] = pilot_work.set_progress_step(_worker(run), "test", after)

        assert moved.state_code == after
        for stamp, expected in ((moved.started_at, started), (moved.ended_at, ended)):
            if expected == "now":
                assert clock.stamped(stamp)
            else:
                assert stamp == (EARLIER if expected == "earlier" else None)

    def test_every_step_keeps_its_place(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(
            _worker(run), [_step("P1.code", state=DONE), _step("test"), _step("docs")]
        )

        answered = pilot_work.set_progress_step(_worker(run), "docs", ACTIVE)

        assert _listed(answered) == [
            ("P1.code", "P1.code", 1, DONE),
            ("test", "test", 2, PENDING),
            ("docs", "docs", 3, ACTIVE),
        ]
        assert _listed(_stored(session, run)) == _listed(answered)

    def test_a_code_not_on_the_list_is_refused_and_changes_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(_worker(run), [_step("test")])

        with pytest.raises(RecordNotFoundException) as refused:
            pilot_work.set_progress_step(_worker(run), "docs", DONE)

        assert refused.value.message == "Progress step docs was not found"
        assert _listed(_stored(session, run)) == [("test", "test", 1, PENDING)]

    def test_a_turn_ended_after_the_gate_changes_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(_worker(run), [_step("test")])
        run.state_code = SessionState.IDLE
        session.flush()

        with pytest.raises(AuthorizationException):
            pilot_work.set_progress_step(_worker(run), "test", ACTIVE)

        assert _listed(_stored(session, run)) == [("test", "test", 1, PENDING)]


class TestPilotWorkServiceProgressRecordsNoEffect:
    def test_neither_call_records_an_effect_or_a_line_of_the_servers(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """F145.4; DB 289: a change of the list is no Effect, and writes no
        `server` record into the turn the call ran in."""
        run = _session(session, container, project, environment)
        _turn_in_flight(session, run)
        pilot_work = container.pilot_work_service()

        pilot_work.set_progress(_worker(run), [_step("test"), _step("docs")])
        pilot_work.set_progress_step(_worker(run), "test", ACTIVE)
        pilot_work.set_progress(_worker(run), [])

        assert _effect_records(session, run) == []
        assert _effects(session) == []


class TestPilotWorkServiceProgressMovesTheWork:
    """A call that changes the list tells the browsers once it commits, the
    work item's status alone, not the project's tab or head (F145.4)."""

    def test_each_change_moves_the_work_items_status_alone(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        engine_events: list[EngineEvent],
    ) -> None:
        run = _session(session, container, project, environment)
        clear_after_commit_callbacks()
        pilot_work = container.pilot_work_service()
        changes = [
            lambda: pilot_work.set_progress(
                _worker(run), [_step("test", "Test"), _step("docs", "Docs")]
            ),
            lambda: pilot_work.set_progress(
                _worker(run), [_step("test", "Test, again"), _step("docs", "Docs")]
            ),
            lambda: pilot_work.set_progress(
                _worker(run), [_step("docs", "Docs"), _step("test", "Test, again")]
            ),
            lambda: pilot_work.set_progress(
                _worker(run),
                [_step("docs", "Docs", ACTIVE), _step("test", "Test, again")],
            ),
            lambda: pilot_work.set_progress_step(_worker(run), "docs", DONE),
            lambda: pilot_work.set_progress(_worker(run), [_step("docs", "Docs")]),
            lambda: pilot_work.set_progress(
                _worker(run), [_step("docs", "Docs", why=WHY)]
            ),
            lambda: pilot_work.set_progress(_worker(run), [_step("docs", "Docs")]),
            lambda: pilot_work.set_progress(_worker(run), []),
        ]
        moved = []

        for change in changes:
            engine_events.clear()
            with scoped_session(container):
                change()
            moved.append(list(engine_events))

        assert moved == [[WorkMoved(project.id, run.id)]] * len(changes)

    def test_a_call_that_changes_nothing_moves_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        engine_events: list[EngineEvent],
    ) -> None:
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        with scoped_session(container):
            pilot_work.set_progress(_worker(run), [])
        listed = [_step("test", "Test", ACTIVE), _step("docs", "Docs", why=WHY)]
        with scoped_session(container):
            pilot_work.set_progress(_worker(run), listed)
        engine_events.clear()

        with scoped_session(container):
            pilot_work.set_progress(_worker(run), listed)
            pilot_work.set_progress(
                _worker(run), [_step("test", "Test"), _step("docs", "Docs", why=WHY)]
            )
            pilot_work.set_progress_step(_worker(run), "test", ACTIVE)

        assert engine_events == []

    def test_a_refused_call_moves_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        engine_events: list[EngineEvent],
    ) -> None:
        run = _session(session, container, project, environment)
        clear_after_commit_callbacks()
        pilot_work = container.pilot_work_service()

        with pytest.raises(InvalidOperationException):
            pilot_work.set_progress(_worker(run), [_step("test"), _step("test")])
        with pytest.raises(RecordNotFoundException):
            pilot_work.set_progress_step(_worker(run), "docs", DONE)
        with scoped_session(container):
            pass

        assert engine_events == []


def _committed_work(app: Flask) -> Worker:
    """A running work Session of a draft project and its Work, committed: its
    worker."""
    project_id, run_id = _committed_run(app)
    with scoped_session(app.container) as db_session:
        app.container.record_service().place_work(
            db_session.get_one(Project, project_id),
            db_session.get_one(models.Session, run_id),
            "Refining the camp",
            repo="example/Example",
        )
    return Worker(run_id, project_id, ENVIRONMENT_ID, run_id)


_Listed = list[tuple[str, ProgressState]]


class TestPilotWorkServiceProgressAtOnce:
    """A script's call from its loop's `wait` and the agent's own, on one
    work item's list at once, are served one after the other under the
    Session's row (V07)."""

    def test_a_code_added_by_both_lands_once_the_second_reading_the_first(
        self, committed_app: Flask
    ) -> None:
        container = committed_app.container
        worker = _committed_work(committed_app)

        def script() -> _Listed:
            with scoped_session(container):
                steps = container.pilot_work_service().set_progress(
                    worker, [_step("P1.code"), _step("test"), _step("docs")]
                )
                return [(step.code, step.state_code) for step in steps]

        with scoped_session(container):
            agents = container.pilot_work_service().set_progress(
                worker, [_step("P1.code"), _step("test", state=ACTIVE)]
            )
            first = [(step.code, step.state_code) for step in agents]
            second = in_thread(script)
            wait_until(lambda: lock_waits(container) == 1, "the script's call waiting")

        assert first == [("P1.code", PENDING), ("test", ACTIVE)]
        assert second.result() == [
            ("P1.code", PENDING),
            ("test", ACTIVE),
            ("docs", PENDING),
        ]

    def test_a_step_moved_while_the_list_is_published_is_kept(
        self, committed_app: Flask
    ) -> None:
        container = committed_app.container
        worker = _committed_work(committed_app)
        with scoped_session(container):
            container.pilot_work_service().set_progress(
                worker, [_step("P1.code", state=ACTIVE), _step("test")]
            )

        def script() -> _Listed:
            with scoped_session(container):
                steps = container.pilot_work_service().set_progress(
                    worker, [_step("P1.code"), _step("test"), _step("docs")]
                )
                return [(step.code, step.state_code) for step in steps]

        with scoped_session(container):
            container.pilot_work_service().set_progress_step(worker, "P1.code", DONE)
            second = in_thread(script)
            wait_until(lambda: lock_waits(container) == 1, "the script's call waiting")

        assert second.result() == [
            ("P1.code", DONE),
            ("test", PENDING),
            ("docs", PENDING),
        ]

    def test_a_kind_two_works_meet_at_once_stands_once(
        self, committed_app: Flask
    ) -> None:
        """A kind is every Work's, so no Session's row serves the two calls
        one after the other: the second waits on the first's Step Kind."""
        container = committed_app.container
        worker = _committed_work(committed_app)
        with scoped_session(container) as db_session:
            run = models.Session(
                project_id=worker.project_id,
                environment_id=ENVIRONMENT_ID,
                kind_code="work",
                cwd="/work/Example",
                token_hash=token_hash("other"),
                state_code=SessionState.RUNNING,
            )
            db_session.add(run)
            db_session.flush()
            container.record_service().place_work(
                db_session.get_one(Project, worker.project_id),
                run,
                "Reviewing the camp",
                repo="example/Example",
            )
            other = Worker(run.id, worker.project_id, ENVIRONMENT_ID, run.id)

        def others() -> list[str | None]:
            with scoped_session(container):
                steps = container.pilot_work_service().set_progress(
                    other, [_step("P1.code", state=ACTIVE, kind=CODE_WRITER)]
                )
                return [step.kind_code for step in steps]

        with scoped_session(container):
            container.pilot_work_service().set_progress(
                worker, [_step("P1.code", state=ACTIVE, kind=CODE_WRITER)]
            )
            second = in_thread(others)
            wait_until(lambda: lock_waits(container) == 1, "the other's call waiting")

        assert second.result() == [CODE_WRITER]
        with scoped_session(container) as db_session:
            assert _kinds(db_session) == [(CODE_WRITER, CODE_WRITER)]

    def test_a_call_that_waited_out_a_stop_changes_nothing(
        self, committed_app: Flask
    ) -> None:
        """Every change of the Session's state takes its row: a call admitted
        while its turn ran, then waiting on the row, reads the stop there and
        lists nothing (DB 286)."""
        container = committed_app.container
        worker = _committed_work(committed_app)
        with committed_app.app_context():
            engine = db.engine

        def publish() -> object:
            with scoped_session(container):
                return container.pilot_work_service().set_progress(
                    worker, [_step("test", state=ACTIVE)]
                )

        with engine.connect() as stop:
            stop.execute(
                sql("UPDATE sessions SET state_code = 'stopped' WHERE id = :id"),
                {"id": worker.session_id},
            )
            call = in_thread(publish)
            wait_until(lambda: lock_waits(container) == 1, "the call waiting")
            stop.commit()

        with pytest.raises(AuthorizationException):
            call.result()
        with scoped_session(container) as db_session:
            assert db_session.scalars(select(ProgressStep)).all() == []


DEBRIEF = "It went well, if slowly: the second review was worth it."
SUBJECT = "Slice 058 · The search page"

_ACCOUNTS = [
    DebriefEntryRequestSchema(
        section="The preparer",
        round=1,
        role="plan-preparer",
        duration=1020,
        words="A well-specified slice.",
    ),
    DebriefEntryRequestSchema(
        section="P1 · The client", round=1, role="code-writer", duration=2400
    ),
    DebriefEntryRequestSchema(
        section="Completion check",
        round=2,
        role="sweep",
        duration=0,
        passed=False,
        why=WHY,
    ),
    DebriefEntryRequestSchema(
        section="P1 · The client",
        round=1,
        role="code-writer",
        duration=60,
        words="The same name further on.",
    ),
]

_Account = tuple[int, str, int, str, int, str | None, bool | None, str | None]


def _accounts(entries: list[DebriefEntry]) -> list[_Account]:
    return [
        (
            entry.position,
            entry.section,
            entry.round,
            entry.role,
            entry.duration,
            entry.words,
            entry.passed,
            entry.why,
        )
        for entry in entries
    ]


_GIVEN: list[_Account] = [
    (
        1,
        "The preparer",
        1,
        "plan-preparer",
        1020,
        "A well-specified slice.",
        None,
        None,
    ),
    (2, "P1 · The client", 1, "code-writer", 2400, None, None, None),
    (3, "Completion check", 2, "sweep", 0, None, False, WHY),
    (
        4,
        "P1 · The client",
        1,
        "code-writer",
        60,
        "The same name further on.",
        None,
        None,
    ),
]


def _debrief_of(
    session: DbSession, work_id: uuid.UUID
) -> tuple[str | None, list[_Account]]:
    """The Work's debrief and its entries, in order, as the database holds
    them."""
    session.expire_all()
    entries = session.scalars(
        select(DebriefEntry)
        .where(DebriefEntry.work_id == work_id)
        .order_by(DebriefEntry.position)
    ).all()
    return session.get_one(Work, work_id).debrief, _accounts(list(entries))


def _subject_of(
    session: DbSession, work_id: uuid.UUID
) -> tuple[str | None, bool | None]:
    """The Work's debrief subject and whether its debrief completes it."""
    session.expire_all()
    work = session.get_one(Work, work_id)
    return work.debrief_subject, work.debrief_completes


class TestPilotWorkServiceRegisterDebrief:
    def test_the_debrief_and_its_entries_are_stored_as_given_in_order(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """DB 325, 326: every value as given, each entry's position its
        place; the same section's name further on is an entry like any."""
        run = _session(session, container, project, environment)

        stored = container.pilot_work_service().register_debrief(
            _worker(run), DEBRIEF, _ACCOUNTS
        )

        assert _accounts(stored) == _GIVEN
        assert _debrief_of(session, run.id) == (DEBRIEF, _GIVEN)
        assert _subject_of(session, run.id) == (None, True)

    def test_its_subject_and_whether_it_completes_it_are_stored_with_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """DB 608: given with the debrief, as given."""
        run = _session(session, container, project, environment)

        container.pilot_work_service().register_debrief(
            _worker(run), DEBRIEF, _ACCOUNTS, subject=SUBJECT, completes=False
        )

        assert _subject_of(session, run.id) == (SUBJECT, False)

    def test_the_loops_figures_are_stored_with_it_and_none_where_not_given(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """DB 635: given with the debrief, as given; Pilot's lines, the
        pass's to write, stay none."""
        given = _session(session, container, project, environment)
        bare = _session(session, container, project, environment, token="bare-token")
        service = container.pilot_work_service()

        service.register_debrief(_worker(given), DEBRIEF, _ACCOUNTS, figures=FIGURES)
        service.register_debrief(_worker(bare), DEBRIEF, _ACCOUNTS)

        works = {run.id: session.get_one(Work, run.id) for run in (given, bare)}
        assert (works[given.id].debrief_figures, works[bare.id].debrief_figures) == (
            FIGURES,
            None,
        )
        assert works[given.id].debrief_notable is None

    def test_a_second_call_is_refused_and_changes_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """DB 324: a work item is debriefed once."""
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.register_debrief(_worker(run), DEBRIEF, _ACCOUNTS)

        with pytest.raises(InvalidOperationException) as refused:
            pilot_work.register_debrief(
                _worker(run), "Again.", _ACCOUNTS[:1], subject=SUBJECT, completes=False
            )

        assert refused.value.message == (
            f"Cannot register the debrief of work item {run.id} because it has"
            " its debrief already"
        )
        assert _debrief_of(session, run.id) == (DEBRIEF, _GIVEN)
        assert _subject_of(session, run.id) == (None, True)

    def test_the_steps_are_untouched_and_take_a_call_after_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """DB 324: the call touches nothing else of the Work."""
        run = _session(session, container, project, environment)
        pilot_work = container.pilot_work_service()
        pilot_work.set_progress(_worker(run), [_step("test", state=ACTIVE, why=WHY)])

        pilot_work.register_debrief(_worker(run), DEBRIEF, _ACCOUNTS)
        moved = [
            (step.code, step.state_code, step.why)
            for step in pilot_work.set_progress_step(_worker(run), "test", DONE)
        ]
        listed = pilot_work.set_progress(_worker(run), [_step("test"), _step("docs")])

        assert moved == [("test", DONE, WHY)]
        assert _listed(listed) == [
            ("test", "test", 1, DONE),
            ("docs", "docs", 2, PENDING),
        ]

    def test_a_turn_ended_after_the_gate_stores_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _session(session, container, project, environment)
        worker = _worker(run)
        run.state_code = SessionState.IDLE
        session.flush()

        with pytest.raises(AuthorizationException) as refused:
            container.pilot_work_service().register_debrief(worker, DEBRIEF, _ACCOUNTS)

        assert refused.value.message == (
            f"Cannot call pilot-work because session {run.id} has no turn running"
        )
        assert _debrief_of(session, run.id) == (None, [])

    def test_only_the_workers_own_work_item_is_debriefed(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """DB 323: no Session gives another Work's."""
        run = _session(session, container, project, environment)
        other = _session(session, container, project, environment, token="other")

        container.pilot_work_service().register_debrief(
            _worker(run), DEBRIEF, _ACCOUNTS
        )

        assert _debrief_of(session, other.id) == (None, [])
        assert _debrief_of(session, run.id) == (DEBRIEF, _GIVEN)

    def test_it_records_no_effect_or_line_and_moves_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        engine_events: list[EngineEvent],
    ) -> None:
        """DB 328: no Effect and no line in the session log; DB 329: no live
        event of its own."""
        run = _session(session, container, project, environment)
        _turn_in_flight(session, run)
        clear_after_commit_callbacks()
        engine_events.clear()

        with scoped_session(container):
            container.pilot_work_service().register_debrief(
                _worker(run), DEBRIEF, _ACCOUNTS
            )

        assert engine_events == []
        assert _effect_records(session, run) == []
        assert _effects(session) == []


class TestPilotWorkServiceRegisterDebriefAtOnce:
    def test_a_second_call_waits_on_the_first_and_is_refused(
        self, committed_app: Flask
    ) -> None:
        """Two calls at once are served one after the other under the
        Session's row, the second reading the debrief the first stored (DB
        324)."""
        container = committed_app.container
        worker = _committed_work(committed_app)

        def again() -> object:
            with scoped_session(container):
                return container.pilot_work_service().register_debrief(
                    worker, "Again.", _ACCOUNTS[:1]
                )

        with scoped_session(container):
            container.pilot_work_service().register_debrief(worker, DEBRIEF, _ACCOUNTS)
            second = in_thread(again)
            wait_until(lambda: lock_waits(container) == 1, "the second call waiting")

        with pytest.raises(InvalidOperationException):
            second.result()
        with scoped_session(container) as db_session:
            assert _debrief_of(db_session, worker.work_item_id) == (DEBRIEF, _GIVEN)
