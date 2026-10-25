"""The turn-end read (TD §4.4; F65.1, F89; ruling D1; design 2 §8; V07, V08,
V24): the documents a work item's run registered, read through the fake
controller once the run ends, and published as written or their read failed.

The read's run is called on the test's session as its loop calls it; the
loop's tests run it on a database of its own, as the supervisor does."""

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from urllib.parse import quote

import pytest
from flask import Flask
from sqlalchemy import select
from sqlalchemy import text as sql
from sqlalchemy.orm import Session as DbSession
from werkzeug.wrappers import Request, Response

from app import extensions, models
from app.core_exceptions import ExternalServiceException
from app.database import scoped_session
from app.engine.documents import awaits_read
from app.models import Document, DocumentVersion, Environment, Item, Project, User
from app.models.reference import RecordKind, SessionState, UserKind, VersionCause
from app.services.container import ServiceContainer
from app.services.controller_client import (
    FILE_SIZE_CAP,
    ControllerClient,
    ControllerProblem,
    ControllerProblemType,
    ControllerUnreachable,
)
from app.services.controller_outage import ControllerOutage
from app.services.fake_controller import FakeControllerProblem
from app.services.session_record_service import read_records
from app.services.supervisor import LoopHandle
from app.services.turn_end_read_service import (
    READ_FAILED,
    READ_JOB,
    TurnEndReadService,
)
from app.utils import after_commit as after_commit_module
from app.utils.after_commit import clear_after_commit_callbacks
from app.utils.lifecycle_coordinator import LifecycleCoordinator
from tests.support.fake_controller import ServedFakeController, client_of
from tests.support.locks import in_thread, lock_waits
from tests.support.supervisor import (
    LogWaiter,
    Supervise,
    listening,
    wait_until,
)

ENV = "env-a"
PATH = "/work/Example/docs/refinement.md"
OTHER = "/work/Example/docs/survey.md"
TEXT = "# Two sites for the camp\n\nThe lake or the hill.\n\n```question id=Q1\n```\n"
SURVEY = "# The survey\n\nNine of ten want the lake.\n"
SUPERVISOR_LOGGER = "app.services.supervisor"
READ_LOGGER = "app.services.turn_end_read_service"


@pytest.fixture(autouse=True)
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


def _service(
    container: ServiceContainer, supervise: Supervise
) -> tuple[TurnEndReadService, LifecycleCoordinator]:
    supervisor, coordinator = supervise(container)
    reads = TurnEndReadService(
        container=container,
        supervisor=supervisor,
        session_streams=container.session_stream_service(),
    )
    return reads, coordinator


@pytest.fixture
def reads(
    container: ServiceContainer,
    controller_client: ControllerClient,
    supervise: Supervise,
) -> TurnEndReadService:
    """The reads on the test's session; no loop of theirs ever runs."""
    return _service(container, supervise)[0]


def _run(
    db: DbSession, container: ServiceContainer, project: Project
) -> models.Session:
    """A work item's Session running in the environment, as its start leaves
    it, its environment's row with it."""
    if db.get(Environment, ENV) is None:
        db.add(Environment(id=ENV, name="Env-A", exempt=False, last_state="running"))
    run = models.Session(
        project_id=project.id,
        environment_id=ENV,
        kind_code="work",
        cwd="/work/Example",
        token_hash=uuid.uuid4().hex,
        state_code=SessionState.RUNNING,
    )
    db.add(run)
    db.flush()
    container.record_service().place_work(
        project, run, "Refining the camp", repo="example/Example"
    )
    return run


def _register(
    container: ServiceContainer,
    project: Project,
    run: models.Session,
    path: str = PATH,
) -> Item:
    return container.document_service().register(project, run, path).item


def _end(db: DbSession, container: ServiceContainer, run: models.Session) -> None:
    """The run's turn ended well, as the relay ends it: the Session idle, its
    work item done (decision 44)."""
    run.state_code = SessionState.IDLE
    container.record_service().work_done(run.id, datetime.now(UTC))
    db.flush()


def _read(reads: TurnEndReadService, run_id: uuid.UUID) -> None:
    """The read's run, as its loop calls it."""
    reads.read(run_id, LoopHandle(f"{READ_JOB}:{run_id}"))


def _document(db: DbSession, item: Item) -> Document:
    return db.get_one(Document, item.id, populate_existing=True)


def _versions(db: DbSession, item: Item) -> list[tuple[int, VersionCause, str]]:
    return [
        (version.number, version.cause_code, version.text)
        for version in db.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == item.id)
            .order_by(DocumentVersion.number)
        )
    ]


def _servers(db: DbSession, run_id: uuid.UUID) -> list[tuple[int | None, object]]:
    """The Session's `server` records: each one's Turn and payload."""
    return [
        (stored.turn, stored.record.payload)
        for stored in read_records(db, run_id, kind=RecordKind.SERVER, limit=100)
    ]


def _file_reads(fake: ServedFakeController) -> list[str]:
    return [
        call for call in fake.calls if call.startswith(f"GET /environments/{ENV}/file")
    ]


def _failed(item: Item, path: str, reason: str) -> dict[str, str]:
    return {"type": READ_FAILED, "item": str(item.id), "path": path, "reason": reason}


@pytest.fixture
def run(
    session: DbSession,
    container: ServiceContainer,
    fake_controller: ServedFakeController,
    project: Project,
) -> models.Session:
    """A work item's Session in an environment the fake runs, which holds the
    document's file as its worker wrote it."""
    fake_controller.add_environment(ENV, status="running")
    fake_controller.put_file(ENV, PATH, TEXT.encode())
    return _run(session, container, project)


class TestTurnEndReadServiceRead:
    def test_each_document_the_run_registered_is_published_as_its_file_reads(
        self,
        session: DbSession,
        container: ServiceContainer,
        reads: TurnEndReadService,
        fake_controller: ServedFakeController,
        project: Project,
        run: models.Session,
    ) -> None:
        fake_controller.put_file(ENV, OTHER, SURVEY.encode())
        first = _register(container, project, run)
        second = _register(container, project, run, OTHER)
        _end(session, container, run)

        _read(reads, run.id)

        assert _file_reads(fake_controller) == [
            f"GET /environments/{ENV}/file?path={quote(PATH, safe='')}",
            f"GET /environments/{ENV}/file?path={quote(OTHER, safe='')}",
        ]
        document = _document(session, first)
        assert document.published_text == TEXT
        assert (first.kind_code, first.title) == ("question", "Two sites for the camp")
        assert _versions(session, first) == [(1, VersionCause.REGISTERED, TEXT)]
        assert session.scalars(
            select(DocumentVersion.session_id).where(
                DocumentVersion.document_id == first.id
            )
        ).all() == [run.id]
        assert not awaits_read(first, document)
        assert _document(session, second).published_text == SURVEY
        assert (second.kind_code, second.title) == ("review", "The survey")
        assert _servers(session, run.id) == []

    def test_a_stopped_environments_file_is_read(
        self,
        session: DbSession,
        container: ServiceContainer,
        reads: TurnEndReadService,
        fake_controller: ServedFakeController,
        project: Project,
        run: models.Session,
    ) -> None:
        # F89: the controller reads the environment's share, never its pod.
        item = _register(container, project, run)
        _end(session, container, run)
        fake_controller.set_status(ENV, "stopped")

        _read(reads, run.id)

        assert _document(session, item).published_text == TEXT

    @pytest.mark.parametrize(
        ("change", "reason"),
        [
            pytest.param(
                lambda fake: fake.remove_file(ENV, PATH),
                "the controller answered 404 not-found",
                id="moved",
            ),
            pytest.param(
                lambda fake: (
                    fake.remove_file(ENV, PATH),
                    fake.put_file(ENV, f"{PATH}/notes.md", b"Notes.\n"),
                ),
                "the controller answered 409 not-a-file",
                id="a-folder-now",
            ),
            pytest.param(
                lambda fake: fake.put_file(ENV, PATH, b"x" * (FILE_SIZE_CAP + 1)),
                "the controller answered 413 file-too-large",
                id="over-the-cap",
            ),
            pytest.param(
                lambda fake: fake.remove_environment(ENV),
                "the controller answered 404 not-found",
                id="its-environment-gone",
            ),
        ],
    )
    def test_a_file_the_controller_refuses_fails_the_read_saying_why(
        self,
        session: DbSession,
        container: ServiceContainer,
        reads: TurnEndReadService,
        fake_controller: ServedFakeController,
        project: Project,
        run: models.Session,
        change: Callable[[ServedFakeController], object],
        reason: str,
    ) -> None:
        item = _register(container, project, run)
        _end(session, container, run)
        change(fake_controller)

        _read(reads, run.id)

        document = _document(session, item)
        assert document.published_text is None
        assert document.read_failed_at is not None
        assert _versions(session, item) == []
        assert not awaits_read(item, document)
        [(turn, payload)] = _servers(session, run.id)
        assert turn is None
        assert isinstance(payload, dict)
        assert payload["reason"].startswith(reason)
        assert payload == _failed(item, PATH, payload["reason"])

    def test_a_path_outside_work_fails_the_read(
        self,
        session: DbSession,
        container: ServiceContainer,
        reads: TurnEndReadService,
        project: Project,
        run: models.Session,
    ) -> None:
        # Registered through the engine: the tool refuses such a path.
        item = _register(container, project, run, "/etc/notes.md")
        _end(session, container, run)

        _read(reads, run.id)

        [(_, payload)] = _servers(session, run.id)
        assert payload == _failed(
            item,
            "/etc/notes.md",
            "the controller answered 403 path-outside-work: the path is outside"
            " the environment's /work; '/etc/notes.md' leaves /work; only absolute"
            " paths under /work are reachable",
        )

    def test_a_text_with_faults_fails_the_read_with_each_and_its_line(
        self,
        session: DbSession,
        container: ServiceContainer,
        reads: TurnEndReadService,
        fake_controller: ServedFakeController,
        project: Project,
        run: models.Session,
    ) -> None:
        item = _register(container, project, run)
        _end(session, container, run)
        broken = "---\nfor: nobody\n---\n\nCamp \xff notes.\n"
        fake_controller.put_file(ENV, PATH, broken.encode("latin-1"))

        _read(reads, run.id)

        assert _document(session, item).published_text is None
        assert _servers(session, run.id) == [
            (
                None,
                _failed(
                    item,
                    PATH,
                    "its text holds faults: line 2: front matter: `for: nobody`"
                    " names no handle; line 5: the file is not UTF-8 text: each"
                    " sequence that is not, and each NUL, is replaced by U+FFFD",
                ),
            )
        ]

    def test_a_failed_read_leaves_the_others_of_the_run_read(
        self,
        session: DbSession,
        container: ServiceContainer,
        reads: TurnEndReadService,
        fake_controller: ServedFakeController,
        project: Project,
        run: models.Session,
    ) -> None:
        fake_controller.put_file(ENV, OTHER, SURVEY.encode())
        gone = _register(container, project, run)
        read = _register(container, project, run, OTHER)
        _end(session, container, run)
        fake_controller.remove_file(ENV, PATH)

        _read(reads, run.id)

        assert _document(session, gone).read_failed_at is not None
        assert _document(session, read).published_text == SURVEY

    def test_a_read_the_controller_does_not_answer_raises_and_reads_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        reads: TurnEndReadService,
        fake_controller: ServedFakeController,
        controller_outage: ControllerOutage,
        project: Project,
        run: models.Session,
    ) -> None:
        item = _register(container, project, run)
        _end(session, container, run)
        fake_controller.outage()

        with pytest.raises(ControllerUnreachable):
            _read(reads, run.id)

        assert controller_outage.holds
        assert awaits_read(item, _document(session, item))
        assert _servers(session, run.id) == []

    def test_an_environment_the_controller_cannot_read_raises_and_reads_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        reads: TurnEndReadService,
        fake_controller: ServedFakeController,
        project: Project,
        run: models.Session,
    ) -> None:
        item = _register(container, project, run)
        _end(session, container, run)
        fake_controller.unreadable(ENV)

        with pytest.raises(ControllerProblem) as raised:
            _read(reads, run.id)

        assert raised.value.problem_type is ControllerProblemType.ENVIRONMENT_UNREADABLE
        assert awaits_read(item, _document(session, item))

    @pytest.mark.parametrize(
        "state", [SessionState.RUNNING, SessionState.STOPPED, SessionState.FAILED]
    )
    def test_a_run_that_has_not_ended_well_reads_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        reads: TurnEndReadService,
        fake_controller: ServedFakeController,
        project: Project,
        run: models.Session,
        state: SessionState,
    ) -> None:
        # A stopped or failed run's documents await the end of its Resume's.
        item = _register(container, project, run)
        run.state_code = state
        session.flush()

        _read(reads, run.id)

        assert _file_reads(fake_controller) == []
        assert awaits_read(item, _document(session, item))

    def test_a_document_finish_closed_is_not_read(
        self,
        session: DbSession,
        container: ServiceContainer,
        reads: TurnEndReadService,
        fake_controller: ServedFakeController,
        project: Project,
        person: User,
        run: models.Session,
    ) -> None:
        item = _register(container, project, run)
        _end(session, container, run)
        container.record_service().close_unanswered(project, person, datetime.now(UTC))

        _read(reads, run.id)

        assert _file_reads(fake_controller) == []
        document = _document(session, item)
        assert (document.published_text, document.read_failed_at) == (None, None)
        assert item.done_cause_code == "finished"

    def test_a_document_already_read_is_not_read_again(
        self,
        session: DbSession,
        container: ServiceContainer,
        reads: TurnEndReadService,
        fake_controller: ServedFakeController,
        project: Project,
        run: models.Session,
    ) -> None:
        item = _register(container, project, run)
        _end(session, container, run)
        _read(reads, run.id)
        fake_controller.calls.clear()

        _read(reads, run.id)

        assert _file_reads(fake_controller) == []
        assert _versions(session, item) == [(1, VersionCause.REGISTERED, TEXT)]


class TestTurnEndReadServiceRunEnded:
    def test_a_run_that_registered_documents_has_them_read_once_it_commits(
        self,
        session: DbSession,
        container: ServiceContainer,
        reads: TurnEndReadService,
        project: Project,
        run: models.Session,
    ) -> None:
        _register(container, project, run)
        _end(session, container, run)

        reads.run_ended(session, run.id)

        assert "_ReadStart" in _pending()

    def test_a_run_that_registered_none_reads_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        reads: TurnEndReadService,
        project: Project,
        run: models.Session,
    ) -> None:
        _end(session, container, run)

        reads.run_ended(session, run.id)

        assert "_ReadStart" not in _pending()


def _pending() -> set[str]:
    """The kinds of the after-commit callbacks the transaction holds."""
    return {
        type(callback).__name__ for callback in after_commit_module._callbacks.get()
    }


class _ReadWatched(ServedFakeController):
    """The fake, calling `on_read` with the path before it answers a read,
    and answering `refusal` instead while it is set."""

    def __init__(self, keepalive_seconds: float) -> None:
        super().__init__(keepalive_seconds)
        self.on_read: Callable[[str], None] | None = None
        self.refusal: FakeControllerProblem | None = None

    def _read_file(self, request: Request, env_id: str) -> Response:
        if self.on_read is not None:
            self.on_read(request.args["path"])
        if self.refusal is not None:
            raise self.refusal
        return super()._read_file(request, env_id)


@pytest.fixture
def watched(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
) -> Iterator[tuple[_ReadWatched, models.Session]]:
    """The fake as `_ReadWatched`, holding the document's file, and a work
    item's Session in its environment."""
    fake = _ReadWatched(keepalive_seconds=0.2)
    client_of(container, fake)
    fake.add_environment(ENV, status="running")
    fake.put_file(ENV, PATH, TEXT.encode())
    try:
        yield fake, _run(session, container, project)
    finally:
        fake.close()


class TestTurnEndReadServiceRefusals:
    @pytest.mark.parametrize(
        ("problem", "reason"),
        [
            (
                FakeControllerProblem(409, "conflict", "too many levels of links"),
                "the controller answered 409 conflict: too many levels of links",
            ),
            (
                FakeControllerProblem(409, "not-a-file", "a FIFO"),
                "the controller answered 409 not-a-file: a FIFO",
            ),
        ],
        ids=["a-link-loop", "not-a-regular-file"],
    )
    def test_a_conflict_or_not_a_file_fails_the_read(
        self,
        session: DbSession,
        container: ServiceContainer,
        supervise: Supervise,
        project: Project,
        watched: tuple[_ReadWatched, models.Session],
        problem: FakeControllerProblem,
        reason: str,
    ) -> None:
        fake, run = watched
        item = _register(container, project, run)
        _end(session, container, run)
        fake.refusal = problem

        _read(_service(container, supervise)[0], run.id)

        [(_, payload)] = _servers(session, run.id)
        assert isinstance(payload, dict)
        assert payload["reason"].startswith(reason)
        assert _document(session, item).read_failed_at is not None

    @pytest.mark.parametrize(
        "status", [401, 422, 500], ids=["unauthenticated", "invalid", "its-own"]
    )
    def test_a_refusal_of_the_controllers_own_raises_and_reads_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        supervise: Supervise,
        project: Project,
        watched: tuple[_ReadWatched, models.Session],
        status: int,
    ) -> None:
        fake, run = watched
        item = _register(container, project, run)
        _end(session, container, run)
        fake.refusal = FakeControllerProblem(status, "something", "its own")

        with pytest.raises(ExternalServiceException):
            _read(_service(container, supervise)[0], run.id)

        assert awaits_read(item, _document(session, item))


def _committed_rows(app: Flask, fake: ServedFakeController) -> tuple[uuid.UUID, ...]:
    """A project, a work item's Session in the fake's environment and the
    document it registered there, its file written, committed: their ids."""
    fake.add_environment(ENV, status="running")
    fake.put_file(ENV, PATH, TEXT.encode())
    container = app.container
    with scoped_session(container) as db:
        person = User(
            kind_code=UserKind.PERSON,
            subject="subject-ada",
            handle="ada",
            name="Ada Example",
            avatar_slot=1,
        )
        db.add(person)
        db.flush()
        project = Project(created_by_user_id=person.id)
        db.add(project)
        db.flush()
        run = _run(db, container, project)
        item = _register(container, project, run)
        return project.id, run.id, item.id, person.id


def _end_committed(
    container: ServiceContainer, reads: TurnEndReadService, run_id: uuid.UUID
) -> None:
    """The run's end committed, as the relay's: its reads requested with it."""
    with scoped_session(container) as db:
        _end(db, container, db.get_one(models.Session, run_id))
        reads.run_ended(db, run_id)


def _published(container: ServiceContainer, item_id: uuid.UUID) -> str | None:
    with scoped_session(container) as db:
        return db.get_one(Document, item_id).published_text


class TestTurnEndReadServiceLoop:
    @pytest.fixture
    def loop_log(self) -> Iterator[LogWaiter]:
        with listening(SUPERVISOR_LOGGER, READ_LOGGER) as waiter:
            yield waiter

    def test_the_end_of_a_run_reads_its_documents_once_it_commits(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        _, run_id, item_id, _ = _committed_rows(committed_app, fake_controller)
        reads, coordinator = _service(container, supervise)
        coordinator.fire_startup()

        _end_committed(container, reads, run_id)

        loop_log.wait_for(rf"Loop read:{run_id} ended")
        assert _published(container, item_id) == TEXT

    def test_a_read_waits_the_outage_out(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        _, run_id, item_id, _ = _committed_rows(committed_app, fake_controller)
        reads, coordinator = _service(container, supervise)
        coordinator.fire_startup()
        fake_controller.outage()

        _end_committed(container, reads, run_id)

        loop_log.wait_for(rf"Loop read:{run_id} raised; restarting in .*", 2)
        assert _published(container, item_id) is None
        fake_controller.outage(on=False)
        loop_log.wait_for(rf"Loop read:{run_id} ended")
        assert _published(container, item_id) == TEXT

    def test_startup_makes_the_reads_owed_from_the_rows(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        project_id, run_id, item_id, _ = _committed_rows(committed_app, fake_controller)
        with scoped_session(container) as db:
            # A second run, stopped under its turn: it owes nothing yet.
            stopped = _run(db, container, db.get_one(Project, project_id))
            stopped.state_code = SessionState.STOPPED
            waiting = _register(container, db.get_one(Project, project_id), stopped)
            # The first's end committed, and the process stopped before its
            # read.
            _end(db, container, db.get_one(models.Session, run_id))
            stopped_id, waiting_id = stopped.id, waiting.id
        _, coordinator = _service(container, supervise)

        coordinator.fire_startup()

        loop_log.wait_for(rf"Loop read:{run_id} ended")
        assert _published(container, item_id) == TEXT
        assert loop_log.matching(rf".*{stopped_id}.*") == []
        with scoped_session(container) as db:
            assert awaits_read(
                db.get_one(Item, waiting_id), db.get_one(Document, waiting_id)
            )

    def test_a_document_finish_closed_during_its_read_is_left_as_finish_closed_it(
        self,
        committed_app: Flask,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        fake = _ReadWatched(keepalive_seconds=0.2)
        try:
            client_of(container, fake)
            project_id, run_id, item_id, person_id = _committed_rows(
                committed_app, fake
            )

            def finish(path: str) -> None:
                with scoped_session(container) as db:
                    container.record_service().close_unanswered(
                        db.get_one(Project, project_id),
                        db.get_one(User, person_id),
                        datetime.now(UTC),
                    )

            fake.on_read = finish
            reads, _ = _service(container, supervise)
            with scoped_session(container) as db:
                _end(db, container, db.get_one(models.Session, run_id))

            _read(reads, run_id)
        finally:
            fake.close()

        loop_log.wait_for(rf"Document {PATH} of session {run_id} no longer awaits.*")
        with scoped_session(container) as db:
            document = db.get_one(Document, item_id)
            assert (document.published_text, document.read_failed_at) == (None, None)
            assert db.get_one(Item, item_id).done_cause_code == "finished"
            assert _servers(db, run_id) == []

    def test_a_read_takes_the_projects_row_before_the_sessions(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
    ) -> None:
        # The start's lock order (P-45): the Project's row, then the
        # Session's, then the Document's.
        container = committed_app.container
        project_id, run_id, item_id, _ = _committed_rows(committed_app, fake_controller)
        reads, _ = _service(container, supervise)
        with scoped_session(container) as db:
            _end(db, container, db.get_one(models.Session, run_id))
        with committed_app.app_context():
            engine = extensions.db.engine

        with engine.connect() as holder:
            holder.execute(
                sql("SELECT id FROM projects WHERE id = :id FOR KEY SHARE"),
                {"id": project_id},
            )
            outcome = in_thread(lambda: _read(reads, run_id))
            wait_until(lambda: lock_waits(container) == 1, "the read waits")
            with engine.connect() as other:
                other.execute(
                    sql("SELECT id FROM sessions WHERE id = :id FOR UPDATE NOWAIT"),
                    {"id": run_id},
                )
                other.rollback()
            assert _published(container, item_id) is None
            holder.rollback()

        outcome.result()
        assert _published(container, item_id) == TEXT
