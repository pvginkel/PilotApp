"""`pilot-work`: a bearer resolved to its work item's Session, and
`register_document` (TD §4.5, F84, F85.1, ruling D1), against the fake
controller."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.exceptions import (
    AuthenticationException,
    AuthorizationException,
    InvalidOperationException,
)
from app.models import Document, Environment, Item, Project
from app.models.reference import SessionState
from app.services.container import ServiceContainer
from app.services.controller_client import (
    FILE_SIZE_CAP,
    ControllerClient,
    ControllerProblem,
    ControllerProblemType,
    ControllerUnreachable,
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
