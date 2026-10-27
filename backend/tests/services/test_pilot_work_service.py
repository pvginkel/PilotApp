"""`pilot-work`: a bearer resolved to its work item's Session,
`register_document` (TD §4.5, F84, F85.1, ruling D1) and `attach_file`
(F85.2, F36.1), each call's Effects (R18, F41), against the fake controller."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from dependency_injector import providers
from flask import Flask
from sqlalchemy import func, select
from sqlalchemy import text as sql
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.engine.attachments import MAX_CALL_FILES, MAX_CALL_SIZE
from app.exceptions import (
    AuthenticationException,
    AuthorizationException,
    InvalidOperationException,
    RecordNotFoundException,
)
from app.extensions import db
from app.models import (
    Attachment,
    Document,
    Effect,
    Environment,
    Item,
    ItemAttachment,
    Project,
    Turn,
    User,
)
from app.models.reference import EffectKind, RecordKind, SessionState, UserKind
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
