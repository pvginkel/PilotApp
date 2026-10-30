"""The halt file (F135.6, F141.3; design 2 §13.4; DB 231; V02, V07, V19):
written into an environment where a work item's Session runs under a usage
halt whose setting is the cooperative stop or under its project's pause, and
deleted once none runs there under either; never for a job or a chat, so
never into the store; shared by two projects and by a halt and a pause; owed
from the rows through an outage and a restart.

An environment's run is called on the test's session as its loop calls it;
the loops' tests run them on a database of their own, as the supervisor
does."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from flask import Flask
from sqlalchemy.orm import Session as DbSession

from app import models
from app.app_config import HaltSetting
from app.core_exceptions import ExternalServiceException
from app.database import scoped_session
from app.models import Environment, Project, UsageReading, User, WindowShare
from app.models.reference import (
    ProjectState,
    SessionState,
    UsageWindow,
    UserKind,
)
from app.services.container import ServiceContainer
from app.services.controller_client import (
    ControllerClient,
    ControllerProblem,
    ControllerProblemType,
)
from app.services.halt_file_service import HALT_FILE, HALT_FILE_JOB, HaltFileService
from app.services.start_gate import WorkSlots
from app.services.supervisor import LoopHandle
from app.utils import after_commit as after_commit_module
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.fake_controller import ServedFakeController
from tests.support.fake_sidecar import STORE_ENVIRONMENT_ID
from tests.support.supervisor import LogWaiter, Supervise, listening, wait_until

ENV = "env-a"
OTHER = "env-b"
COOPERATIVE = HaltSetting.COOPERATIVE_STOP
HALT_LOGGER = "app.services.halt_file_service"
SUPERVISOR_LOGGER = "app.services.supervisor"


@pytest.fixture(autouse=True)
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


def _service(
    container: ServiceContainer,
    supervise: Supervise,
    *,
    week: HaltSetting = COOPERATIVE,
    five_hour: HaltSetting = COOPERATIVE,
    slots: WorkSlots | None = None,
    tick: float = 0.05,
) -> tuple[HaltFileService, Supervise]:
    """The halt files on a supervisor of their own and a slot of their own,
    so that the session app's slot keeps no listener of a test's."""
    supervisor, coordinator = supervise(container, tick=tick)
    service = HaltFileService(
        container=container,
        supervisor=supervisor,
        usage_halts=container.usage_halts(),
        work_slots=WorkSlots(work_max=3, project_max=3) if slots is None else slots,
        week_halt=week,
        five_hour_halt=five_hour,
    )
    return service, coordinator


@pytest.fixture
def halt_files(
    container: ServiceContainer,
    controller_client: ControllerClient,
    supervise: Supervise,
) -> HaltFileService:
    """The halt files on the test's session, both halts the cooperative stop;
    no loop of theirs ever runs."""
    return _service(container, supervise)[0]


@pytest.fixture
def halt_log() -> Iterator[LogWaiter]:
    with listening(HALT_LOGGER) as waiter:
        yield waiter


def _environment(
    db: DbSession,
    fake: ServedFakeController,
    env_id: str = ENV,
    *,
    requested: bool = False,
) -> Environment:
    """An environment the fake runs, its row with it; with `requested`, the
    halt file written there."""
    fake.add_environment(env_id, status="running")
    row = Environment(id=env_id, name=env_id, exempt=False, last_state="running")
    if requested:
        fake.put_file(env_id, HALT_FILE, b"")
        row.halt_requested_at = datetime.now(UTC)
    db.add(row)
    db.flush()
    return row


def _project(db: DbSession, person: User, *, paused: bool = False) -> Project:
    project = Project(
        created_by_user_id=person.id,
        state_code=ProjectState.OPEN,
        slug=f"camp-{uuid.uuid4().hex[:8]}",
        paused=paused,
    )
    db.add(project)
    db.flush()
    return project


def _run(
    db: DbSession,
    project: Project,
    env_id: str = ENV,
    *,
    kind: str = "work",
    state: SessionState = SessionState.RUNNING,
) -> models.Session:
    """A Session of `kind` of the project in the environment, `state`."""
    run = models.Session(
        project_id=project.id,
        environment_id=env_id,
        kind_code=kind,
        cwd="/work/Example",
        token_hash=uuid.uuid4().hex,
        state_code=state,
    )
    db.add(run)
    db.flush()
    return run


def _usage(db: DbSession, *, week: float, five_hour: float = 0.1) -> None:
    """A fresh Usage Reading recorded now with these shares."""
    now = datetime.now(UTC)
    reading = UsageReading(taken_at=now, received_at=now, stale=False)
    db.add(reading)
    db.flush()
    db.add_all(
        WindowShare(
            reading_id=reading.id,
            window_code=window,
            share=share,
            resets_at=now + timedelta(hours=4),
        )
        for window, share in (
            (UsageWindow.SEVEN_DAY, week),
            (UsageWindow.FIVE_HOUR, five_hour),
        )
    )
    db.flush()


def _settle(halt_files: HaltFileService, env_id: str = ENV) -> None:
    """The environment's run, as its loop calls it."""
    halt_files.settle(env_id, LoopHandle(f"{HALT_FILE_JOB}:{env_id}"))


def _file(fake: ServedFakeController, env_id: str = ENV) -> bytes | None:
    return fake.environment(env_id).files.get(HALT_FILE)


def _requested(db: DbSession, env_id: str = ENV) -> datetime | None:
    return db.get_one(Environment, env_id, populate_existing=True).halt_requested_at


def _calls(fake: ServedFakeController) -> list[str]:
    return [call for call in fake.calls if "/file?" in call]


class TestHaltFileServiceHalting:
    @pytest.mark.parametrize(
        ("week", "five_hour", "week_halt", "five_hour_halt", "halting"),
        [
            (0.95, 0.1, COOPERATIVE, COOPERATIVE, True),
            (0.1, 0.8, COOPERATIVE, COOPERATIVE, True),
            (0.95, 0.8, HaltSetting.NO_NEW_WORK, COOPERATIVE, True),
            (0.95, 0.1, HaltSetting.NO_NEW_WORK, COOPERATIVE, False),
            (0.95, 0.1, HaltSetting.HARD_STOP, COOPERATIVE, False),
            (0.1, 0.8, COOPERATIVE, HaltSetting.HARD_STOP, False),
            (0.1, 0.1, COOPERATIVE, COOPERATIVE, False),
        ],
    )
    def test_a_halt_whose_setting_is_the_cooperative_stop_halts(
        self,
        session: DbSession,
        container: ServiceContainer,
        supervise: Supervise,
        week: float,
        five_hour: float,
        week_halt: HaltSetting,
        five_hour_halt: HaltSetting,
        halting: bool,
    ) -> None:
        halt_files, _ = _service(
            container, supervise, week=week_halt, five_hour=five_hour_halt
        )
        _usage(session, week=week, five_hour=five_hour)

        assert halt_files.halting(session) is halting

    def test_before_the_first_reading_nothing_halts(
        self, session: DbSession, halt_files: HaltFileService
    ) -> None:
        assert halt_files.halting(session) is False


class TestHaltFileServiceSettle:
    def test_a_pause_writes_the_file_where_its_work_item_runs(
        self,
        session: DbSession,
        halt_files: HaltFileService,
        fake_controller: ServedFakeController,
        person: User,
        halt_log: LogWaiter,
    ) -> None:
        _environment(session, fake_controller)
        _run(session, _project(session, person, paused=True))

        _settle(halt_files)

        assert _file(fake_controller) == b""
        assert _requested(session) is not None
        assert halt_log.matching(f"Wrote the halt file into environment {ENV}")

    def test_a_cooperative_halt_writes_the_file_where_a_work_item_runs(
        self,
        session: DbSession,
        halt_files: HaltFileService,
        fake_controller: ServedFakeController,
        person: User,
    ) -> None:
        _environment(session, fake_controller)
        _run(session, _project(session, person))
        _usage(session, week=0.95)

        _settle(halt_files)

        assert _file(fake_controller) == b""
        assert _requested(session) is not None

    @pytest.mark.parametrize(
        "setting", [HaltSetting.NO_NEW_WORK, HaltSetting.HARD_STOP]
    )
    def test_a_halt_of_no_new_work_or_the_hard_stop_writes_no_file(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        supervise: Supervise,
        fake_controller: ServedFakeController,
        person: User,
        setting: HaltSetting,
    ) -> None:
        halt_files, _ = _service(container, supervise, week=setting)
        _environment(session, fake_controller)
        _run(session, _project(session, person))
        _usage(session, week=0.95)

        _settle(halt_files)

        assert (_file(fake_controller), _requested(session)) == (None, None)
        assert _calls(fake_controller) == []

    @pytest.mark.parametrize(
        "state",
        [
            SessionState.HELD,
            SessionState.STARTING,
            SessionState.IDLE,
            SessionState.STOPPED,
            SessionState.FAILED,
        ],
    )
    def test_no_file_where_no_work_item_runs(
        self,
        session: DbSession,
        halt_files: HaltFileService,
        fake_controller: ServedFakeController,
        person: User,
        state: SessionState,
    ) -> None:
        _environment(session, fake_controller)
        _run(session, _project(session, person, paused=True), state=state)
        _usage(session, week=0.95)

        _settle(halt_files)

        assert (_file(fake_controller), _requested(session)) == (None, None)

    def test_no_file_for_a_job_or_a_chat_so_none_into_the_store(
        self,
        session: DbSession,
        halt_files: HaltFileService,
        fake_controller: ServedFakeController,
        person: User,
    ) -> None:
        _environment(session, fake_controller, STORE_ENVIRONMENT_ID)
        paused = _project(session, person, paused=True)
        _run(session, paused, STORE_ENVIRONMENT_ID, kind="job")
        _run(session, paused, STORE_ENVIRONMENT_ID, kind="chat")
        _usage(session, week=0.95, five_hour=0.8)

        owed = halt_files.owed(session)
        _settle(halt_files, STORE_ENVIRONMENT_ID)

        assert owed == []
        assert _file(fake_controller, STORE_ENVIRONMENT_ID) is None
        assert _requested(session, STORE_ENVIRONMENT_ID) is None

    @pytest.mark.parametrize(
        "end", [SessionState.IDLE, SessionState.STOPPED, SessionState.FAILED]
    )
    def test_the_file_goes_once_its_work_items_run_ends(
        self,
        session: DbSession,
        halt_files: HaltFileService,
        fake_controller: ServedFakeController,
        person: User,
        halt_log: LogWaiter,
        end: SessionState,
    ) -> None:
        _environment(session, fake_controller)
        run = _run(session, _project(session, person, paused=True))
        _settle(halt_files)
        assert _file(fake_controller) == b""

        run.state_code = end
        session.flush()
        _settle(halt_files)

        assert (_file(fake_controller), _requested(session)) == (None, None)
        assert halt_log.matching(f"Deleted the halt file from environment {ENV}")

    def test_the_file_goes_at_the_resume(
        self,
        session: DbSession,
        halt_files: HaltFileService,
        fake_controller: ServedFakeController,
        person: User,
    ) -> None:
        _environment(session, fake_controller)
        project = _project(session, person, paused=True)
        _run(session, project)
        _settle(halt_files)
        assert _file(fake_controller) == b""

        project.paused = False
        session.flush()
        _settle(halt_files)

        assert (_file(fake_controller), _requested(session)) == (None, None)

    def test_the_file_goes_when_the_halt_lifts(
        self,
        session: DbSession,
        halt_files: HaltFileService,
        fake_controller: ServedFakeController,
        person: User,
    ) -> None:
        _environment(session, fake_controller)
        _run(session, _project(session, person))
        _usage(session, week=0.95)
        _settle(halt_files)
        assert _file(fake_controller) == b""

        _usage(session, week=0.5)
        _settle(halt_files)

        assert (_file(fake_controller), _requested(session)) == (None, None)

    def test_two_projects_sharing_an_environment_share_its_file(
        self,
        session: DbSession,
        halt_files: HaltFileService,
        fake_controller: ServedFakeController,
        person: User,
    ) -> None:
        _environment(session, fake_controller)
        first = _project(session, person, paused=True)
        second = _project(session, person, paused=True)
        _run(session, first)
        second_run = _run(session, second)
        _settle(halt_files)
        written_at = _requested(session)

        # One project resumed: the other's pause still holds the file.
        first.paused = False
        session.flush()
        owed = halt_files.owed(session)
        kept = (_file(fake_controller), _requested(session))
        # The paused project's work item's turn ends: nothing holds it.
        second_run.state_code = SessionState.IDLE
        session.flush()
        _settle(halt_files)

        assert written_at is not None
        assert (owed, kept) == ([], (b"", written_at))
        assert (_file(fake_controller), _requested(session)) == (None, None)
        assert _calls(fake_controller) == [
            f"PUT /environments/{ENV}/file?path=%2Fwork%2F.quota-limit-halt-requested",
            f"DELETE /environments/{ENV}/file?path=%2Fwork%2F.quota-limit-halt-requested",
        ]

    def test_a_halt_and_a_pause_share_the_file(
        self,
        session: DbSession,
        halt_files: HaltFileService,
        fake_controller: ServedFakeController,
        person: User,
    ) -> None:
        _environment(session, fake_controller)
        project = _project(session, person, paused=True)
        _run(session, project)
        _usage(session, week=0.95)
        _settle(halt_files)

        # Resumed: the halt still holds the file.
        project.paused = False
        session.flush()
        _settle(halt_files)
        kept = _file(fake_controller)
        _usage(session, week=0.5)
        _settle(halt_files)

        assert kept == b""
        assert (_file(fake_controller), _requested(session)) == (None, None)

    def test_a_run_ended_during_the_write_has_the_file_deleted_by_the_same_run(
        self,
        session: DbSession,
        halt_files: HaltFileService,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        person: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _environment(session, fake_controller)
        run = _run(session, _project(session, person, paused=True))
        write = controller_client.write_file

        def ending_during(env_id: str, path: str, data: bytes) -> str:
            # The work item's turn ends while the controller writes.
            written = write(env_id, path, data)
            run.state_code = SessionState.IDLE
            session.flush()
            return written

        monkeypatch.setattr(controller_client, "write_file", ending_during)

        _settle(halt_files)

        assert (_file(fake_controller), _requested(session)) == (None, None)
        assert [call.split("?")[0] for call in _calls(fake_controller)] == [
            f"PUT /environments/{ENV}/file",
            f"DELETE /environments/{ENV}/file",
        ]

    def test_a_file_already_gone_has_its_delete_taken(
        self,
        session: DbSession,
        halt_files: HaltFileService,
        fake_controller: ServedFakeController,
    ) -> None:
        _environment(session, fake_controller, requested=True)
        fake_controller.remove_file(ENV, HALT_FILE)

        _settle(halt_files)

        assert _requested(session) is None

    def test_an_environment_gone_has_its_delete_taken(
        self,
        session: DbSession,
        halt_files: HaltFileService,
        fake_controller: ServedFakeController,
    ) -> None:
        _environment(session, fake_controller, requested=True)
        fake_controller.remove_environment(ENV)

        _settle(halt_files)

        assert _requested(session) is None

    def test_a_run_writes_the_file_wanted_whatever_the_column_says(
        self,
        session: DbSession,
        halt_files: HaltFileService,
        fake_controller: ServedFakeController,
        person: User,
    ) -> None:
        # The column set where the file is wanted, its write unanswered.
        _environment(session, fake_controller, requested=True)
        fake_controller.remove_file(ENV, HALT_FILE)
        _environment(session, fake_controller, OTHER)
        _run(session, _project(session, person, paused=True))
        written_at = _requested(session)

        _settle(halt_files)
        _settle(halt_files, OTHER)

        assert [call.split("?")[0] for call in _calls(fake_controller)] == [
            f"PUT /environments/{ENV}/file"
        ]
        assert _file(fake_controller) == b""
        assert (_requested(session), _requested(session, OTHER)) == (written_at, None)

    def test_a_call_the_controller_does_not_answer_raises_and_leaves_the_column_set(
        self,
        session: DbSession,
        halt_files: HaltFileService,
        fake_controller: ServedFakeController,
        person: User,
    ) -> None:
        _environment(session, fake_controller)
        _environment(session, fake_controller, OTHER, requested=True)
        _run(session, _project(session, person, paused=True))
        written_at = _requested(session, OTHER)
        session.commit()
        fake_controller.outage()

        with pytest.raises(ExternalServiceException):
            _settle(halt_files)
        with pytest.raises(ExternalServiceException):
            _settle(halt_files, OTHER)

        assert _requested(session) is not None
        assert _file(fake_controller) is None
        assert (_requested(session, OTHER), _file(fake_controller, OTHER)) == (
            written_at,
            b"",
        )

    def test_a_write_whose_answer_never_came_is_deleted_once_nothing_holds_it(
        self,
        session: DbSession,
        halt_files: HaltFileService,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        person: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _environment(session, fake_controller)
        run = _run(session, _project(session, person, paused=True))
        session.commit()
        write = controller_client.write_file

        def unanswered(env_id: str, path: str, data: bytes) -> str:
            # The controller writes the file; its answer never arrives.
            write(env_id, path, data)
            raise ExternalServiceException("write the halt file", "timed out")

        monkeypatch.setattr(controller_client, "write_file", unanswered)
        with pytest.raises(ExternalServiceException):
            _settle(halt_files)
        monkeypatch.setattr(controller_client, "write_file", write)
        left = _file(fake_controller)
        run.state_code = SessionState.IDLE
        session.commit()

        owed = halt_files.owed(session)
        _settle(halt_files)

        assert (left, owed) == (b"", [ENV])
        assert (_file(fake_controller), _requested(session)) == (None, None)

    def test_a_delete_whose_answer_never_came_is_written_again_while_wanted(
        self,
        session: DbSession,
        halt_files: HaltFileService,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        person: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _environment(session, fake_controller, requested=True)
        run = _run(
            session, _project(session, person, paused=True), state=SessionState.IDLE
        )
        session.commit()
        delete = controller_client.delete_file

        def unanswered(env_id: str, path: str) -> None:
            # The controller deletes the file; its answer never arrives.
            delete(env_id, path)
            raise ExternalServiceException("delete the halt file", "timed out")

        monkeypatch.setattr(controller_client, "delete_file", unanswered)
        with pytest.raises(ExternalServiceException):
            _settle(halt_files)
        monkeypatch.setattr(controller_client, "delete_file", delete)
        run.state_code = SessionState.RUNNING
        session.commit()

        # The loop's run after the one that raised.
        _settle(halt_files)

        assert _file(fake_controller) == b""
        assert _requested(session) is not None

    def test_a_delete_during_a_bring_up_raises_until_it_settles(
        self,
        session: DbSession,
        halt_files: HaltFileService,
        fake_controller: ServedFakeController,
    ) -> None:
        _environment(session, fake_controller, requested=True)
        session.commit()
        fake_controller.set_status(ENV, "starting")

        with pytest.raises(ControllerProblem) as caught:
            _settle(halt_files)
        refused = _requested(session)
        fake_controller.set_status(ENV, "running")
        _settle(halt_files)

        assert caught.value.problem_type is ControllerProblemType.CONFLICT
        assert refused is not None
        assert (_file(fake_controller), _requested(session)) == (None, None)


class TestHaltFileServiceOwed:
    def test_owed_are_the_environments_whose_column_is_not_what_is_wanted(
        self,
        session: DbSession,
        halt_files: HaltFileService,
        fake_controller: ServedFakeController,
        person: User,
    ) -> None:
        paused = _project(session, person, paused=True)
        # Wanted and unset: a write owed.
        _environment(session, fake_controller, "env-a")
        _run(session, paused, "env-a")
        # Wanted and set: nothing.
        _environment(session, fake_controller, "env-b", requested=True)
        _run(session, paused, "env-b")
        # Set and no longer wanted: a delete owed.
        _environment(session, fake_controller, "env-c", requested=True)
        _run(session, paused, "env-c", state=SessionState.IDLE)
        # Neither: nothing.
        _environment(session, fake_controller, "env-d")
        _run(session, _project(session, person), "env-d")

        assert halt_files.owed(session) == ["env-a", "env-c"]

    def test_a_cooperative_halt_owes_a_write_wherever_a_work_item_runs(
        self,
        session: DbSession,
        halt_files: HaltFileService,
        fake_controller: ServedFakeController,
        person: User,
    ) -> None:
        project = _project(session, person)
        _environment(session, fake_controller, "env-a")
        _run(session, project, "env-a")
        _environment(session, fake_controller, "env-b")
        _run(session, project, "env-b")
        _usage(session, week=0.1, five_hour=0.8)

        assert halt_files.owed(session) == ["env-a", "env-b"]


class TestHaltFileServiceRequest:
    def test_a_work_items_runs_end_sweeps_once_it_commits(
        self,
        session: DbSession,
        container: ServiceContainer,
        controller_client: ControllerClient,
        supervise: Supervise,
        fake_controller: ServedFakeController,
        person: User,
    ) -> None:
        slots = WorkSlots(work_max=3, project_max=3)
        halt_files, _ = _service(container, supervise, slots=slots)
        _environment(session, fake_controller)
        run = _run(session, _project(session, person))
        run.state_code = SessionState.IDLE

        slots.left(run, SessionState.RUNNING)

        assert halt_files.request in after_commit_module._callbacks.get()


# -- The loops, on a database of their own -----------------------------------


def _committed_rows(
    committed_app: Flask, fake: ServedFakeController, *, requested: bool = False
) -> tuple[uuid.UUID, uuid.UUID]:
    """A project and its work item running in the environment: the
    project's id and the run's."""
    with scoped_session(committed_app.container) as db:
        person = User(
            kind_code=UserKind.PERSON,
            subject="subject-ada",
            handle="ada",
            name="Ada Example",
            avatar_slot=1,
        )
        db.add(person)
        db.flush()
        _environment(db, fake, requested=requested)
        project = _project(db, person)
        return project.id, _run(db, project).id


def _committed_requested(container: ServiceContainer) -> datetime | None:
    with scoped_session(container) as db:
        return _requested(db)


class TestHaltFileServiceLoop:
    @pytest.fixture
    def loop_log(self) -> Iterator[LogWaiter]:
        with listening(SUPERVISOR_LOGGER, HALT_LOGGER) as waiter:
            yield waiter

    def test_a_request_writes_the_file_and_the_next_deletes_it(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        project_id, _ = _committed_rows(committed_app, fake_controller)
        # The timer's first tick at startup finds nothing owed, and no other
        # comes: the requests alone write and delete.
        halt_files, coordinator = _service(container, supervise, tick=60)
        coordinator.fire_startup()

        with scoped_session(container) as db:
            db.get_one(Project, project_id).paused = True
        halt_files.request()
        loop_log.wait_for(f"Wrote the halt file into environment {ENV}")
        written = _file(fake_controller)
        with scoped_session(container) as db:
            db.get_one(Project, project_id).paused = False
        halt_files.request()
        loop_log.wait_for(f"Deleted the halt file from environment {ENV}")
        wait_until(lambda: _committed_requested(container) is None, "the delete taken")

        assert written == b""
        assert _file(fake_controller) is None

    def test_a_delete_owed_waits_the_outage_out(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        _, run_id = _committed_rows(committed_app, fake_controller, requested=True)
        with scoped_session(container) as db:
            db.get_one(models.Session, run_id).state_code = SessionState.IDLE
        halt_files, coordinator = _service(container, supervise, tick=60)
        fake_controller.outage()
        coordinator.fire_startup()

        loop_log.wait_for(rf"Loop {HALT_FILE_JOB}:{ENV} raised; restarting in .*", 2)
        assert _committed_requested(container) is not None
        fake_controller.outage(on=False)
        loop_log.wait_for(f"Deleted the halt file from environment {ENV}")
        wait_until(lambda: _committed_requested(container) is None, "the delete taken")

        assert _file(fake_controller) is None

    def test_startup_deletes_a_file_owed_from_the_rows(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        # The file written, and the process gone before the work item's
        # turn ended.
        _, run_id = _committed_rows(committed_app, fake_controller, requested=True)
        with scoped_session(container) as db:
            db.get_one(models.Session, run_id).state_code = SessionState.IDLE
        _, coordinator = _service(container, supervise)

        coordinator.fire_startup()

        loop_log.wait_for(f"Deleted the halt file from environment {ENV}")
        wait_until(lambda: _committed_requested(container) is None, "the delete taken")
        assert _file(fake_controller) is None

    def test_startup_writes_a_file_wanted_where_the_column_is_set(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        loop_log: LogWaiter,
    ) -> None:
        container = committed_app.container
        # The column set, and the process gone before its write went out.
        project_id, _ = _committed_rows(committed_app, fake_controller, requested=True)
        with scoped_session(container) as db:
            db.get_one(Project, project_id).paused = True
        fake_controller.remove_file(ENV, HALT_FILE)
        _, coordinator = _service(container, supervise, tick=60)

        coordinator.fire_startup()

        loop_log.wait_for(f"Wrote the halt file into environment {ENV}")
        assert _file(fake_controller) == b""
        assert _committed_requested(container) is not None
