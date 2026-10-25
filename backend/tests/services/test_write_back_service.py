"""The write-back (TD §4.4, FM §5; F65.1, F89; V10): a closed registered
document's text, the answers in it, written to its file through the fake
controller once the close commits, or the write refused and said why.

The write's run is called on the test's session as its loop calls it; the
loop's tests run it on a database of its own, as the supervisor does."""

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from urllib.parse import quote

import pytest
from flask import Flask
from sqlalchemy import text as sql
from sqlalchemy.orm import Session as DbSession
from werkzeug.wrappers import Request, Response

from app import extensions, models
from app.core_exceptions import ExternalServiceException
from app.database import scoped_session
from app.engine.bus import EngineBus
from app.models import Document, Environment, Item, Project, User
from app.models.reference import RecordKind, SessionState, UserKind
from app.services.container import ServiceContainer
from app.services.controller_client import (
    ControllerClient,
    ControllerProblem,
    ControllerProblemType,
    ControllerUnreachable,
    EnvironmentStatus,
)
from app.services.controller_outage import ControllerOutage
from app.services.fake_controller import FakeControllerProblem
from app.services.session_record_service import read_records
from app.services.supervisor import LoopHandle
from app.services.write_back_service import (
    WRITE_BACK_JOB,
    WRITE_BACK_REFUSED,
    WriteBackService,
)
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
DECISION = """# Two sites for the camp

The lake or the hill.

```decision id=D1
options:
  - The lake
  - The hill
recommend: The lake
```
"""
PLAN = """# The camp plan

```decision id=D1
options:
  - The lake
  - The hill
recommend: The lake
```

```question id=Q1
default: Friday
```
"""
REVIEW = "# The survey\n\nNine of ten want the lake.\n"
SUPERVISOR_LOGGER = "app.services.supervisor"
WRITE_BACK_LOGGER = "app.services.write_back_service"


@pytest.fixture(autouse=True)
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


def _service(
    container: ServiceContainer,
    supervise: Supervise,
    engine_bus: EngineBus | None = None,
) -> tuple[WriteBackService, LifecycleCoordinator]:
    """The write-backs, hearing `engine_bus`: a bus of their own unless one
    is given, so that the session app's bus keeps no subscriber of a test's."""
    supervisor, coordinator = supervise(container)
    write_backs = WriteBackService(
        container=container,
        supervisor=supervisor,
        session_streams=container.session_stream_service(),
        engine_bus=EngineBus() if engine_bus is None else engine_bus,
    )
    return write_backs, coordinator


@pytest.fixture
def write_backs(
    container: ServiceContainer,
    controller_client: ControllerClient,
    supervise: Supervise,
) -> WriteBackService:
    """The write-backs on the test's session; no loop of theirs ever runs."""
    return _service(container, supervise)[0]


def _run(
    db: DbSession, container: ServiceContainer, project: Project
) -> models.Session:
    """A work item's Session in the environment, its run ended, its
    environment's row with it."""
    if db.get(Environment, ENV) is None:
        db.add(Environment(id=ENV, name="Env-A", exempt=False, last_state="running"))
    run = models.Session(
        project_id=project.id,
        environment_id=ENV,
        kind_code="work",
        cwd="/work/Example",
        token_hash=uuid.uuid4().hex,
        state_code=SessionState.IDLE,
    )
    db.add(run)
    db.flush()
    container.record_service().place_work(
        project, run, "Refining the camp", repo="example/Example"
    )
    container.record_service().work_done(run.id, datetime.now(UTC))
    return run


def _registered(
    db: DbSession,
    container: ServiceContainer,
    project: Project,
    run: models.Session,
    text: str = DECISION,
    path: str = PATH,
) -> Item:
    """A document the run registered, read at its end as written."""
    documents = container.document_service()
    item = documents.register(project, run, path).item
    documents.publish_read(db.get_one(Document, item.id), text, run.id)
    return item


def _kept_open(
    db: DbSession, container: ServiceContainer, project: Project, run: models.Session
) -> Item:
    """Another document the run registered, left open: no continuation takes
    the answers of the run's documents, and their Undo stays (review 1)."""
    return _registered(db, container, project, run, REVIEW, OTHER)


def _answer(
    db: DbSession, container: ServiceContainer, item: Item, person: User, answer: str
) -> None:
    """The person's answer to the decision, which closes it."""
    container.record_service().answer(
        db.get_one(Document, item.id), "D1", person, answer
    )


def _write_back(write_backs: WriteBackService, run_id: uuid.UUID) -> None:
    """The write-back's run, as its loop calls it."""
    write_backs.write_back(run_id, LoopHandle(f"{WRITE_BACK_JOB}:{run_id}"))


def _document(db: DbSession, item: Item) -> Document:
    return db.get_one(Document, item.id, populate_existing=True)


def _servers(db: DbSession, run_id: uuid.UUID) -> list[tuple[int | None, object]]:
    """The Session's `server` records: each one's Turn and payload."""
    return [
        (stored.turn, stored.record.payload)
        for stored in read_records(db, run_id, kind=RecordKind.SERVER, limit=100)
    ]


def _writes(fake: ServedFakeController) -> list[str]:
    return [
        call for call in fake.calls if call.startswith(f"PUT /environments/{ENV}/file")
    ]


def _write_of(path: str) -> str:
    return f"PUT /environments/{ENV}/file?path={quote(path, safe='')}"


def _refused(item: Item, path: str, reason: str) -> dict[str, str]:
    return {
        "type": WRITE_BACK_REFUSED,
        "item": str(item.id),
        "path": path,
        "reason": reason,
    }


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
    fake_controller.put_file(ENV, PATH, DECISION.encode())
    return _run(session, container, project)


class TestWriteBackServiceWriteBack:
    def test_done_writes_the_text_with_its_answers_back_to_its_file(
        self,
        session: DbSession,
        container: ServiceContainer,
        write_backs: WriteBackService,
        fake_controller: ServedFakeController,
        project: Project,
        person: User,
        run: models.Session,
    ) -> None:
        item = _registered(session, container, project, run, PLAN)
        container.record_service().done(item, person)
        before = datetime.now(UTC)

        _write_back(write_backs, run.id)

        document = _document(session, item)
        assert document.published_text is not None
        assert "answer: The lake" in document.published_text
        assert "answer: Friday" in document.published_text
        assert "via: recommended" in document.published_text
        assert fake_controller.file_text(ENV, PATH) == document.published_text
        assert _writes(fake_controller) == [_write_of(PATH)]
        assert document.written_back_at is not None
        assert before <= document.written_back_at <= datetime.now(UTC)
        assert _servers(session, run.id) == []

    def test_the_answer_that_closes_a_one_ask_item_writes_it_back(
        self,
        session: DbSession,
        container: ServiceContainer,
        write_backs: WriteBackService,
        fake_controller: ServedFakeController,
        project: Project,
        person: User,
        run: models.Session,
    ) -> None:
        item = _registered(session, container, project, run)
        _answer(session, container, item, person, "The hill")

        _write_back(write_backs, run.id)

        text = fake_controller.file_text(ENV, PATH)
        assert text == _document(session, item).published_text
        assert text is not None and "answer: The hill\nby: ada" in text
        assert _document(session, item).written_back_at is not None

    def test_reviewed_writes_a_review_back_as_it_reads(
        self,
        session: DbSession,
        container: ServiceContainer,
        write_backs: WriteBackService,
        fake_controller: ServedFakeController,
        project: Project,
        person: User,
        run: models.Session,
    ) -> None:
        item = _registered(session, container, project, run, REVIEW)
        container.record_service().reviewed(item, person)

        _write_back(write_backs, run.id)

        assert fake_controller.file_text(ENV, PATH) == REVIEW
        assert _document(session, item).written_back_at is not None

    def test_a_stopped_environments_file_is_written(
        self,
        session: DbSession,
        container: ServiceContainer,
        write_backs: WriteBackService,
        fake_controller: ServedFakeController,
        project: Project,
        person: User,
        run: models.Session,
    ) -> None:
        # F89: the controller writes the environment's share, never its pod.
        item = _registered(session, container, project, run)
        _answer(session, container, item, person, "The hill")
        fake_controller.set_status(ENV, "stopped")

        _write_back(write_backs, run.id)

        assert fake_controller.file_text(ENV, PATH) == (
            _document(session, item).published_text
        )

    def test_the_documents_are_written_in_the_order_registered(
        self,
        session: DbSession,
        container: ServiceContainer,
        write_backs: WriteBackService,
        fake_controller: ServedFakeController,
        project: Project,
        person: User,
        run: models.Session,
    ) -> None:
        first = _registered(session, container, project, run)
        second = _registered(session, container, project, run, REVIEW, OTHER)
        container.record_service().reviewed(second, person)
        _answer(session, container, first, person, "The hill")

        _write_back(write_backs, run.id)

        assert _writes(fake_controller) == [_write_of(PATH), _write_of(OTHER)]
        assert fake_controller.file_text(ENV, OTHER) == REVIEW

    @pytest.mark.parametrize(
        "state", ["open", "finished", "its-read-failed"], ids=lambda state: state
    )
    def test_a_document_that_owes_no_write_back_is_not_written(
        self,
        session: DbSession,
        container: ServiceContainer,
        write_backs: WriteBackService,
        fake_controller: ServedFakeController,
        project: Project,
        person: User,
        run: models.Session,
        state: str,
    ) -> None:
        records = container.record_service()
        if state == "its-read-failed":
            # Its file was moved before the read: it has no text to write.
            documents = container.document_service()
            item = documents.register(project, run, PATH).item
            documents.fail_read(session.get_one(Document, item.id))
            records.reviewed(item, person)
        else:
            item = _registered(session, container, project, run)
        if state == "finished":
            records.close_unanswered(project, person, datetime.now(UTC))

        _write_back(write_backs, run.id)

        assert _writes(fake_controller) == []
        assert fake_controller.file_text(ENV, PATH) == DECISION
        assert _document(session, item).written_back_at is None

    def test_a_document_written_back_is_not_written_again(
        self,
        session: DbSession,
        container: ServiceContainer,
        write_backs: WriteBackService,
        fake_controller: ServedFakeController,
        project: Project,
        person: User,
        run: models.Session,
    ) -> None:
        item = _registered(session, container, project, run)
        _answer(session, container, item, person, "The hill")
        _write_back(write_backs, run.id)
        written_at = _document(session, item).written_back_at
        fake_controller.calls.clear()

        _write_back(write_backs, run.id)

        assert _writes(fake_controller) == []
        assert _document(session, item).written_back_at == written_at

    def test_after_an_undo_its_next_close_writes_it_again(
        self,
        session: DbSession,
        container: ServiceContainer,
        write_backs: WriteBackService,
        fake_controller: ServedFakeController,
        project: Project,
        person: User,
        run: models.Session,
    ) -> None:
        item = _registered(session, container, project, run)
        _kept_open(session, container, project, run)
        _answer(session, container, item, person, "The hill")
        _write_back(write_backs, run.id)
        container.record_service().undo(item)
        _answer(session, container, item, person, "The lake")

        _write_back(write_backs, run.id)

        text = fake_controller.file_text(ENV, PATH)
        assert text is not None and "answer: The lake" in text
        assert _writes(fake_controller) == [_write_of(PATH), _write_of(PATH)]
        assert _document(session, item).written_back_at is not None


class TestWriteBackServiceRefused:
    @pytest.mark.parametrize(
        ("change", "reason"),
        [
            pytest.param(
                lambda fake: fake.remove_environment(ENV),
                "the controller answered 404 not-found",
                id="its-environment-gone",
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
                lambda fake: (
                    fake.remove_file(ENV, PATH),
                    fake.put_file(ENV, "/work/Example/docs", b"Notes.\n"),
                ),
                "the controller answered 409 not-a-directory",
                id="under-a-file-now",
            ),
        ],
    )
    def test_a_write_the_controller_refuses_is_not_made_again_and_said_why(
        self,
        session: DbSession,
        container: ServiceContainer,
        write_backs: WriteBackService,
        fake_controller: ServedFakeController,
        project: Project,
        person: User,
        run: models.Session,
        change: Callable[[ServedFakeController], object],
        reason: str,
    ) -> None:
        item = _registered(session, container, project, run)
        _answer(session, container, item, person, "The hill")
        change(fake_controller)

        _write_back(write_backs, run.id)

        document = _document(session, item)
        assert document.written_back_at is None
        assert document.write_back_refused_at is not None
        [(turn, payload)] = _servers(session, run.id)
        assert turn is None
        assert isinstance(payload, dict)
        assert payload["reason"].startswith(reason)
        assert payload == _refused(item, PATH, payload["reason"])
        fake_controller.calls.clear()
        _write_back(write_backs, run.id)
        assert _writes(fake_controller) == []
        assert len(_servers(session, run.id)) == 1

    def test_a_path_outside_work_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        write_backs: WriteBackService,
        project: Project,
        person: User,
        run: models.Session,
    ) -> None:
        # Registered through the engine: the tool refuses such a path.
        item = _registered(session, container, project, run, path="/etc/notes.md")
        _answer(session, container, item, person, "The hill")

        _write_back(write_backs, run.id)

        assert _servers(session, run.id) == [
            (
                None,
                _refused(
                    item,
                    "/etc/notes.md",
                    "the controller answered 403 path-outside-work: the path is"
                    " outside the environment's /work; '/etc/notes.md' leaves"
                    " /work; only absolute paths under /work are reachable",
                ),
            )
        ]

    def test_after_an_undo_its_next_close_writes_it_again(
        self,
        session: DbSession,
        container: ServiceContainer,
        write_backs: WriteBackService,
        fake_controller: ServedFakeController,
        project: Project,
        person: User,
        run: models.Session,
    ) -> None:
        item = _registered(session, container, project, run)
        _kept_open(session, container, project, run)
        _answer(session, container, item, person, "The hill")
        fake_controller.remove_file(ENV, PATH)
        fake_controller.put_file(ENV, f"{PATH}/notes.md", b"Notes.\n")
        _write_back(write_backs, run.id)
        fake_controller.remove_file(ENV, f"{PATH}/notes.md")
        container.record_service().undo(item)
        _answer(session, container, item, person, "The lake")

        _write_back(write_backs, run.id)

        text = fake_controller.file_text(ENV, PATH)
        assert text is not None and "answer: The lake" in text
        document = _document(session, item)
        assert document.written_back_at is not None
        assert document.write_back_refused_at is None


class TestWriteBackServiceRetried:
    def test_a_write_the_controller_does_not_answer_raises_and_takes_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        write_backs: WriteBackService,
        fake_controller: ServedFakeController,
        controller_outage: ControllerOutage,
        project: Project,
        person: User,
        run: models.Session,
    ) -> None:
        item = _registered(session, container, project, run)
        _answer(session, container, item, person, "The hill")
        fake_controller.outage()

        with pytest.raises(ControllerUnreachable):
            _write_back(write_backs, run.id)

        assert controller_outage.holds
        document = _document(session, item)
        assert (document.written_back_at, document.write_back_refused_at) == (
            None,
            None,
        )
        assert _servers(session, run.id) == []

    @pytest.mark.parametrize("status", ["provisioning", "starting"])
    def test_the_controllers_own_work_on_the_tree_raises_until_it_settles(
        self,
        session: DbSession,
        container: ServiceContainer,
        write_backs: WriteBackService,
        fake_controller: ServedFakeController,
        project: Project,
        person: User,
        run: models.Session,
        status: EnvironmentStatus,
    ) -> None:
        item = _registered(session, container, project, run)
        _answer(session, container, item, person, "The hill")
        fake_controller.set_status(ENV, status)

        with pytest.raises(ControllerProblem) as raised:
            _write_back(write_backs, run.id)

        assert raised.value.problem_type is ControllerProblemType.CONFLICT
        assert _document(session, item).write_back_refused_at is None
        assert _servers(session, run.id) == []
        fake_controller.set_status(ENV, "running")
        _write_back(write_backs, run.id)
        assert _document(session, item).written_back_at is not None

    def test_an_environment_the_controller_cannot_read_raises(
        self,
        session: DbSession,
        container: ServiceContainer,
        write_backs: WriteBackService,
        fake_controller: ServedFakeController,
        project: Project,
        person: User,
        run: models.Session,
    ) -> None:
        item = _registered(session, container, project, run)
        _answer(session, container, item, person, "The hill")
        fake_controller.unreadable(ENV)

        with pytest.raises(ControllerProblem) as raised:
            _write_back(write_backs, run.id)

        assert raised.value.problem_type is ControllerProblemType.ENVIRONMENT_UNREADABLE
        document = _document(session, item)
        assert (document.written_back_at, document.write_back_refused_at) == (
            None,
            None,
        )


class _WriteWatched(ServedFakeController):
    """The fake, calling `on_write` with the path before it answers a write,
    and answering `refusal` instead while it is set."""

    def __init__(self, keepalive_seconds: float) -> None:
        super().__init__(keepalive_seconds)
        self.on_write: Callable[[str], None] | None = None
        self.refusal: FakeControllerProblem | None = None

    def _write_file(self, request: Request, env_id: str) -> Response:
        if self.on_write is not None:
            self.on_write(request.args["path"])
        if self.refusal is not None:
            raise self.refusal
        return super()._write_file(request, env_id)


@pytest.fixture
def watched(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
) -> Iterator[tuple[_WriteWatched, models.Session]]:
    """The fake as `_WriteWatched`, holding the document's file, and a work
    item's Session in its environment."""
    fake = _WriteWatched(keepalive_seconds=0.2)
    client_of(container, fake)
    fake.add_environment(ENV, status="running")
    fake.put_file(ENV, PATH, DECISION.encode())
    try:
        yield fake, _run(session, container, project)
    finally:
        fake.close()


class TestWriteBackServiceRefusals:
    def test_a_text_over_the_cap_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        supervise: Supervise,
        project: Project,
        person: User,
        watched: tuple[_WriteWatched, models.Session],
    ) -> None:
        fake, run = watched
        item = _registered(session, container, project, run)
        _answer(session, container, item, person, "The hill")
        fake.refusal = FakeControllerProblem(413, "file-too-large", "too large")

        _write_back(_service(container, supervise)[0], run.id)

        assert _servers(session, run.id) == [
            (
                None,
                _refused(
                    item, PATH, "the controller answered 413 file-too-large: too large"
                ),
            )
        ]
        assert _document(session, item).write_back_refused_at is not None

    @pytest.mark.parametrize(
        "status", [401, 422, 500], ids=["unauthenticated", "invalid", "its-own"]
    )
    def test_a_refusal_of_the_controllers_own_raises_and_takes_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        supervise: Supervise,
        project: Project,
        person: User,
        watched: tuple[_WriteWatched, models.Session],
        status: int,
    ) -> None:
        fake, run = watched
        item = _registered(session, container, project, run)
        _answer(session, container, item, person, "The hill")
        fake.refusal = FakeControllerProblem(status, "something", "its own")

        with pytest.raises(ExternalServiceException):
            _write_back(_service(container, supervise)[0], run.id)

        document = _document(session, item)
        assert (document.written_back_at, document.write_back_refused_at) == (
            None,
            None,
        )
        assert _servers(session, run.id) == []


def _committed_rows(
    app: Flask, fake: ServedFakeController, *, kept_open: bool = False
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """A project, a work item's Session in the fake's environment whose run
    ended, and the document it registered there, read, committed, with
    another left open when `kept_open` (`_kept_open`): their ids and the
    person's."""
    fake.add_environment(ENV, status="running")
    fake.put_file(ENV, PATH, DECISION.encode())
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
        item = _registered(db, container, project, run)
        if kept_open:
            _kept_open(db, container, project, run)
        return project.id, run.id, item.id, person.id


def _close_committed(
    container: ServiceContainer, item_id: uuid.UUID, person_id: uuid.UUID, answer: str
) -> None:
    """The person's answer that closes the document, committed."""
    with scoped_session(container) as db:
        _answer(
            db,
            container,
            db.get_one(Item, item_id),
            db.get_one(User, person_id),
            answer,
        )


def _undo_committed(container: ServiceContainer, item_id: uuid.UUID) -> None:
    with scoped_session(container) as db:
        container.record_service().undo(db.get_one(Item, item_id))


def _file_and_stamp(
    container: ServiceContainer, fake: ServedFakeController, item_id: uuid.UUID
) -> tuple[str | None, str | None, bool]:
    """The file's text, the record's, and whether it was written back."""
    with scoped_session(container) as db:
        document = db.get_one(Document, item_id)
        return (
            fake.file_text(ENV, PATH),
            document.published_text,
            document.written_back_at is not None,
        )


class TestWriteBackServiceLoop:
    @pytest.fixture
    def loop_log(self) -> Iterator[LogWaiter]:
        with listening(SUPERVISOR_LOGGER, WRITE_BACK_LOGGER) as waiter:
            yield waiter

    def test_a_close_writes_its_document_back_once_it_commits(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        _, run_id, item_id, person_id = _committed_rows(committed_app, fake_controller)
        _, coordinator = _service(container, supervise, container.engine_bus())
        coordinator.fire_startup()

        _close_committed(container, item_id, person_id, "The hill")

        loop_log.wait_for(rf"Loop {WRITE_BACK_JOB}:{run_id} ended")
        file, record, written = _file_and_stamp(container, fake_controller, item_id)
        assert file == record
        assert written

    def test_a_write_back_waits_the_outage_out(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        _, run_id, item_id, person_id = _committed_rows(committed_app, fake_controller)
        _, coordinator = _service(container, supervise, container.engine_bus())
        coordinator.fire_startup()
        fake_controller.outage()

        _close_committed(container, item_id, person_id, "The hill")

        loop_log.wait_for(
            rf"Loop {WRITE_BACK_JOB}:{run_id} raised; restarting in .*", 2
        )
        assert not _file_and_stamp(container, fake_controller, item_id)[2]
        fake_controller.outage(on=False)
        loop_log.wait_for(rf"Loop {WRITE_BACK_JOB}:{run_id} ended")
        file, record, written = _file_and_stamp(container, fake_controller, item_id)
        assert file == record
        assert written

    def test_startup_makes_the_write_backs_owed_from_the_rows(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        project_id, run_id, item_id, person_id = _committed_rows(
            committed_app, fake_controller
        )
        with scoped_session(container) as db:
            # A second run's document, still open: it owes nothing.
            other = _run(db, container, db.get_one(Project, project_id))
            open_item = _registered(
                db, container, db.get_one(Project, project_id), other, path=OTHER
            )
            other_id, open_id = other.id, open_item.id
        # The close committed, and the process stopped before its write.
        _close_committed(container, item_id, person_id, "The hill")
        _, coordinator = _service(container, supervise)

        coordinator.fire_startup()

        loop_log.wait_for(rf"Loop {WRITE_BACK_JOB}:{run_id} ended")
        file, record, written = _file_and_stamp(container, fake_controller, item_id)
        assert file == record
        assert written
        assert loop_log.matching(rf".*{other_id}.*") == []
        with scoped_session(container) as db:
            assert db.get_one(Document, open_id).written_back_at is None

    def test_an_undo_during_the_write_leaves_the_document_open_and_owing_nothing(
        self,
        committed_app: Flask,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        fake = _WriteWatched(keepalive_seconds=0.2)
        try:
            client_of(container, fake)
            _, run_id, item_id, person_id = _committed_rows(
                committed_app, fake, kept_open=True
            )
            write_backs, _ = _service(container, supervise)
            _close_committed(container, item_id, person_id, "The hill")

            def undo(path: str) -> None:
                fake.on_write = None
                _undo_committed(container, item_id)

            fake.on_write = undo

            _write_back(write_backs, run_id)

            loop_log.wait_for(
                rf"Document {PATH} of session {run_id} no longer owes the text"
                " written"
            )
            with scoped_session(container) as db:
                document = db.get_one(Document, item_id)
                assert db.get_one(Item, item_id).done_at is None
                assert document.written_back_at is None
            assert len(_writes(fake)) == 1
        finally:
            fake.close()

    def test_a_text_closed_again_during_the_write_is_written_again(
        self,
        committed_app: Flask,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        fake = _WriteWatched(keepalive_seconds=0.2)
        try:
            client_of(container, fake)
            _, run_id, item_id, person_id = _committed_rows(
                committed_app, fake, kept_open=True
            )
            write_backs, _ = _service(container, supervise)
            _close_committed(container, item_id, person_id, "The hill")

            def answered_again(path: str) -> None:
                fake.on_write = None
                _undo_committed(container, item_id)
                _close_committed(container, item_id, person_id, "The lake")

            fake.on_write = answered_again

            _write_back(write_backs, run_id)

            file, record, written = _file_and_stamp(container, fake, item_id)
            assert file is not None and "answer: The lake" in file
            assert file == record
            assert written
            assert len(_writes(fake)) == 2
        finally:
            fake.close()

    def test_a_write_back_takes_the_projects_row_before_the_sessions(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
    ) -> None:
        # The start's lock order (P-45): the Project's row, then the
        # Session's, then the Document's.
        container = committed_app.container
        project_id, run_id, item_id, person_id = _committed_rows(
            committed_app, fake_controller
        )
        write_backs, _ = _service(container, supervise)
        _close_committed(container, item_id, person_id, "The hill")
        with committed_app.app_context():
            engine = extensions.db.engine

        with engine.connect() as holder:
            holder.execute(
                sql("SELECT id FROM projects WHERE id = :id FOR KEY SHARE"),
                {"id": project_id},
            )
            outcome = in_thread(lambda: _write_back(write_backs, run_id))
            wait_until(lambda: lock_waits(container) == 1, "the take waits")
            with engine.connect() as other:
                other.execute(
                    sql("SELECT id FROM sessions WHERE id = :id FOR UPDATE NOWAIT"),
                    {"id": run_id},
                )
                other.rollback()
            assert not _file_and_stamp(container, fake_controller, item_id)[2]
            holder.rollback()

        outcome.result()
        assert _file_and_stamp(container, fake_controller, item_id)[2]
