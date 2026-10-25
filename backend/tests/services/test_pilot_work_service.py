"""`pilot-work`: a bearer resolved to its work item's Session,
`register_document` (TD §4.5, F84, F85.1, ruling D1) and `attach_file`
(F85.2, F36.1), against the fake controller."""

import uuid

import pytest
from dependency_injector import providers
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.engine.attachments import MAX_CALL_FILES, MAX_CALL_SIZE
from app.exceptions import (
    AuthenticationException,
    AuthorizationException,
    InvalidOperationException,
    RecordNotFoundException,
)
from app.models import (
    Attachment,
    Document,
    Environment,
    Item,
    ItemAttachment,
    Project,
)
from app.models.reference import SessionState
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
from tests.support.fake_controller import ServedFakeController

TOKEN = "worker-token"

PATH = "/work/Example/docs/refinement.md"

TEXT = "Two options for the camp.\n\n```question id=Q1\n```\n"


def _session(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
    environment: Environment,
    kind: str = "work",
    token: str = TOKEN,
) -> models.Session:
    """A running Session of `kind` whose bearer is `token`; a work one with
    its Work."""
    run = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code=kind,
        cwd="/work/Example",
        token_hash=token_hash(token),
        state_code=SessionState.RUNNING,
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
            _worker(run), PATH
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
        first = pilot_work.register_document(_worker(run), PATH)
        fake_controller.put_file(environment.id, PATH, b"# Refinement\n")

        again = pilot_work.register_document(_worker(run), PATH)

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
            container.pilot_work_service().register_document(_worker(run), PATH)

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
            container.pilot_work_service().register_document(_worker(run), path)

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
            container.pilot_work_service().register_document(_worker(run), PATH)

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
            container.pilot_work_service().register_document(_worker(run), PATH)

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
            container.pilot_work_service().register_document(_worker(run), PATH)

        assert _items(session) == 1


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
            _worker(run), PATH, None
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
            _worker(run), f"{FOLDER}/", None
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
        document = pilot_work.register_document(_worker(run), PATH).item

        [attachment] = pilot_work.attach_file(_worker(run), FOLDER, document.id)

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
                pilot_work.attach_file(_worker(run), PATH, to)

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
            container.pilot_work_service().attach_file(_worker(run), path, None)

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
            container.pilot_work_service().attach_file(_worker(run), PATH, None)

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
            container.pilot_work_service().attach_file(_worker(run), FOLDER, None)

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
            container.pilot_work_service().attach_file(_worker(run), FOLDER, None)

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
            container.pilot_work_service().attach_file(_worker(run), PATH, None)

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
            container.pilot_work_service().attach_file(_worker(run), PATH, None)

        assert _attachments(session) == 0
