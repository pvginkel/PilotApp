"""Pilot's own background jobs, the setup, the job after a worker's turn and
the job after an item of Pilot's own is closed, one at a time per project,
each briefed as it starts (design 3 §5.1 to §5.3, D2; F14.1, F49, F59, F59.1,
F59.2, F141.4; TD §4.2; DB Work, assertion 167, 243, decision 45; V01, V11,
V12, V23, V29)."""

import threading
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from dependency_injector import providers
from flask import Flask
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session as DbSession
from werkzeug.wrappers import Request, Response

from app import models
from app.database import scoped_session
from app.engine.views import ViewService, utc_time
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import Item, Project, ProjectTransition, Turn, User, Work
from app.models.reference import (
    AnswerChannel,
    ProjectState,
    RecordKind,
    SessionState,
    Surface,
    TransitionKind,
    UserKind,
    WorkTrigger,
)
from app.schemas.timeline import HeldReason
from app.services.container import ServiceContainer
from app.services.controller_outage import ControllerOutage
from app.services.job_service import NEXT_TITLE, SETUP_TITLE, JobService
from app.services.session_record_service import SessionRecordService
from app.services.session_scope import STORE_REPO, scoped_create
from app.services.session_start_service import SessionStartService
from app.services.start_gate import Held
from app.services.supervisor import LoopHandle
from app.services.timeline_service import work_status
from tests.support.fake_controller import ServedFakeController, client_of
from tests.support.fake_sidecar import STORE_ENVIRONMENT_ID
from tests.support.starts import configured_starts
from tests.support.supervisor import WAIT_SECONDS, Supervise, wait_until

AT = datetime(2026, 10, 27, 9, 30, 15, tzinfo=UTC)
FOLDER = "/work/Projects/soup-club"
OPERATION = "create Soup club"


class _Sent(ServedFakeController):
    """The fake, keeping each send's message; `during_create`, when set, run
    once, as a headless create is answered."""

    def __init__(self, keepalive_seconds: float) -> None:
        super().__init__(keepalive_seconds)
        self.sent: list[str] = []
        self.during_create: Callable[[], None] | None = None

    def _send(self, request: Request, env_id: str, name: str) -> Response:
        self.sent.append((request.get_json(silent=True) or {}).get("message"))
        return super()._send(request, env_id, name)

    def _create_session(self, request: Request, env_id: str) -> Response:
        hook, self.during_create = self.during_create, None
        if hook is not None:
            hook()
        return super()._create_session(request, env_id)


@pytest.fixture
def opened(session: DbSession, project: Project) -> Project:
    """`project` open, named and with its slug, as Create leaves it."""
    project.state_code = ProjectState.OPEN
    project.slug, project.name = "soup-club", "Soup club"
    session.flush()
    return project


@pytest.fixture
def opening(container: ServiceContainer, opened: Project, person: User) -> Item:
    return container.document_service().bear_opening(
        opened, "Ada Example started this project", person, "Soup for the club?"
    )


@pytest.fixture
def starts(container: ServiceContainer, supervise: Supervise) -> SessionStartService:
    """The start with a controller and the store configured, its loops never
    run, on a slot of one work item per project."""
    return configured_starts(container, supervise, project_max=1)


def _jobs(container: ServiceContainer, starts: SessionStartService) -> JobService:
    service: JobService = container.job_service(session_start_service=starts)
    return service


def _setup(
    container: ServiceContainer,
    starts: SessionStartService,
    project: Project,
    at: datetime = AT,
) -> models.Session:
    """The setup placed, triggered at `at`; its Session."""
    work = _jobs(container, starts).setup(project, at, OPERATION)
    return container.db_session().get_one(models.Session, work.id)


def _brief(container: ServiceContainer, job: models.Session) -> Turn:
    """The job's one Turn, its brief."""
    (turn,) = container.db_session().scalars(
        select(Turn).where(Turn.session_id == job.id)
    )
    return turn


class TestSetup:
    """The setup, placed at Create project (F49)."""

    def test_it_places_a_job_of_the_setup_its_work_item_next_on_the_timeline(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
    ) -> None:
        job = _setup(container, starts, opened)

        item = session.get_one(Item, job.id)
        assert (
            item.seq,
            item.kind_code,
            item.title,
            item.created_by_session_id,
            item.plan_task_id,
        ) == (opening.seq + 1, "work", SETUP_TITLE, job.id, None)
        work = session.get_one(Work, job.id)
        assert (
            work.session_kind_code,
            work.trigger_code,
            work.trigger_item_id,
            work.repo,
            work.autopilot,
        ) == ("job", WorkTrigger.SETUP, None, None, False)
        assert (
            job.kind_code,
            job.cwd,
            job.model,
            job.reasoning_effort,
            job.environment_id,
            job.controller_session,
            job.state_code,
            job.turns,
            job.turn_started_at,
            job.created_at,
        ) == (
            "job",
            STORE_REPO,
            "opus",
            "xhigh",
            None,
            None,
            SessionState.STARTING,
            1,
            AT,
            AT,
        )

    def test_going_at_once_its_first_turn_is_the_setups_brief_at_creates_instant(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
    ) -> None:
        job = _setup(container, starts, opened)

        turn = _brief(container, job)
        assert (turn.seq, turn.author_user_id, turn.words, turn.started_at) == (
            1,
            None,
            None,
            AT,
        )
        assert turn.message == container.brief_service().job(
            opened, session.get_one(Work, job.id), AT, AT
        )
        assert f"the opening item {opening.id} holds" in turn.message

    def test_its_create_is_boxed_to_the_projects_folder_with_pilot_store(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
    ) -> None:
        job = _setup(container, starts, opened)

        create = scoped_create(session, job)
        assert create.surface is Surface.STORE
        assert (
            create.request.cwd,
            create.request.sandbox_read_only_cwd,
            create.request.sandbox_writable_dirs,
            create.request.env,
        ) == (
            STORE_REPO,
            True,
            [FOLDER],
            [f"PILOT_PROJECT={FOLDER}", f"PILOT_SESSION={job.id}"],
        )

    @pytest.mark.parametrize("by_pilot", [True, False])
    def test_the_pause_holds_it_not_its_brief_composed_at_once(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
        person: User,
        by_pilot: bool,
    ) -> None:
        """Create's pause, Pilot's at its instant, and a person's alike: the
        setup goes on as a Chat does (D083)."""
        pilot = session.scalars(
            select(User).where(User.kind_code == UserKind.AGENT)
        ).one()
        _transition(
            session, opened, pilot if by_pilot else person, TransitionKind.PAUSED, AT
        )

        job = _setup(container, starts, opened)

        assert job.state_code is SessionState.STARTING
        assert starts.held(session, opened, job) is None
        turn = _brief(container, job)
        assert (job.turns, turn.started_at) == (1, AT)
        assert "paused" not in turn.message
        status = work_status(session, [job.id], unreachable=False, slots=starts._slots)
        assert status[job.id].held_reason is None

    def test_under_the_pause_the_outage_and_the_queue_still_hold_it(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
        person: User,
        controller_outage: ControllerOutage,
    ) -> None:
        first = _setup(container, starts, opened)
        _transition(session, opened, person, TransitionKind.PAUSED, PAUSED_AT)
        controller_outage.call_unanswered()

        second = _setup(container, starts, opened, LATER)

        assert second.state_code is SessionState.HELD
        assert starts.held(session, opened, second) == Held(
            HeldReason.CONTROLLER_UNREACHABLE
        )
        controller_outage.probe_answered()
        assert starts.held(session, opened, second) == Held(HeldReason.QUEUE)
        status = work_status(
            session, [second.id], unreachable=False, slots=starts._slots
        )[second.id]
        assert status.held_reason is HeldReason.QUEUE
        _in(session, first, SessionState.IDLE)
        assert starts.held(session, opened, second) is None

    def test_it_takes_no_slot(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
    ) -> None:
        session.add(
            models.Session(
                project_id=opened.id,
                kind_code="work",
                cwd="/work/Example",
                token_hash=uuid.uuid4().hex,
                state_code=SessionState.RUNNING,
            )
        )
        session.flush()

        job = _setup(container, starts, opened)

        assert job.state_code is SessionState.STARTING
        assert starts._slots.filled(session, [opened.id]) == {opened.id: 1}

    def test_with_no_controller_configured_it_is_refused(
        self,
        container: ServiceContainer,
        opened: Project,
        opening: Item,
    ) -> None:
        with pytest.raises(InvalidOperationException) as raised:
            container.job_service().setup(opened, AT, OPERATION)

        assert raised.value.message == (
            "Cannot create Soup club because no controller is configured"
        )


@pytest.fixture
def fake(container: ServiceContainer) -> Iterator[_Sent]:
    """The fake controller, `container`'s client on it, the store running in
    it with the store repo's root on its tree and no project folder."""
    served = _Sent(keepalive_seconds=0.2)
    client_of(container, served)
    served.add_environment(
        STORE_ENVIRONMENT_ID, name="PilotProjects", status="running", exempt=True
    )
    served.put_file(STORE_ENVIRONMENT_ID, f"{STORE_REPO}/CLAUDE.md", b"# Pilot\n")
    try:
        yield served
    finally:
        served.close()


class TestSetupStart:
    """The setup's start in the store (TD §4.2; F50, F59)."""

    def test_its_session_is_created_once_the_projects_folder_is_on_disk(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        fake: _Sent,
        opened: Project,
        opening: Item,
    ) -> None:
        """`pilot-sync` writes `<slug>/` a moment after Create commits: the
        create refused `422` meanwhile is made again."""
        starts._folder_wait, starts._folder_retry = 2.0, 0.05
        job = _setup(container, starts, opened)
        brief = _brief(container, job).message

        def folder_written() -> None:
            fake.put_file(STORE_ENVIRONMENT_ID, f"{FOLDER}/plan.json", b"{}")

        def refused_once() -> None:
            fake.during_create = folder_written

        fake.during_create = refused_once

        starts.run(job.id, LoopHandle(f"start:{job.id}"))

        job = session.get_one(models.Session, job.id, populate_existing=True)
        assert (job.environment_id, job.state_code) == (
            STORE_ENVIRONMENT_ID,
            SessionState.RUNNING,
        )
        assert job.controller_session is not None
        assert (
            fake.calls.count(
                f"POST /environments/{STORE_ENVIRONMENT_ID}/sessions/headless"
            )
            == 2
        )
        assert fake.sent == [brief]


LATER = datetime(2026, 10, 27, 9, 35, 40, tzinfo=UTC)
"""A second trigger of the project's, after `AT`."""

PAUSED_AT = datetime(2026, 10, 27, 9, 0, 0, tzinfo=UTC)
RESUMED_AT = datetime(2026, 10, 27, 10, 15, 0, tzinfo=UTC)


def _transition(
    db: DbSession, project: Project, person: User, kind: TransitionKind, at: datetime
) -> None:
    """The project paused or resumed at `at`, as its transition writes it."""
    db.add(
        ProjectTransition(
            project_id=project.id, kind_code=kind, at=at, by_user_id=person.id
        )
    )
    project.paused = kind is TransitionKind.PAUSED
    db.flush()


def _read(db: DbSession, job: models.Session) -> models.Session:
    return db.get_one(models.Session, job.id, populate_existing=True)


def _release(starts: SessionStartService) -> None:
    """The release loop's run, as its loop calls it."""
    starts.release(LoopHandle("start:held"))


def _in(db: DbSession, job: models.Session, state: SessionState) -> None:
    job.state_code = state
    db.flush()


class TestQueue:
    """A project's jobs one at a time, the chat beside them, in the order
    their triggers came (F59.2; design 3 §5.1; V23)."""

    @pytest.mark.parametrize("state", [SessionState.STARTING, SessionState.RUNNING])
    def test_a_job_waits_its_turn_while_another_of_its_project_starts_or_runs(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
        state: SessionState,
    ) -> None:
        first = _setup(container, starts, opened)
        _in(session, first, state)

        second = _setup(container, starts, opened, LATER)

        assert second.state_code is SessionState.HELD
        assert (second.turns, second.turn_started_at) == (0, None)
        assert starts.held(session, opened, second) == Held(HeldReason.QUEUE)
        status = work_status(
            session, [second.id], unreachable=False, slots=starts._slots
        )[second.id]
        assert (status.held_reason, status.held_running) == (HeldReason.QUEUE, None)

    @pytest.mark.usefixtures("placing")
    def test_a_job_held_before_it_holds_it_up_and_one_after_it_none(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
        person: User,
    ) -> None:
        _transition(session, opened, person, TransitionKind.PAUSED, PAUSED_AT)
        first = _item_done(session, container, opened, person)
        second = _item_done(session, container, opened, person)

        _transition(session, opened, person, TransitionKind.RESUMED, RESUMED_AT)

        assert starts.held(session, opened, first) is None
        assert starts.held(session, opened, second) == Held(HeldReason.QUEUE)

    @pytest.mark.parametrize(
        "state", [SessionState.IDLE, SessionState.STOPPED, SessionState.FAILED]
    )
    def test_a_job_done_stopped_or_failed_holds_up_none(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
        state: SessionState,
    ) -> None:
        first = _setup(container, starts, opened)
        _in(session, first, state)

        second = _setup(container, starts, opened, LATER)

        assert second.state_code is SessionState.STARTING
        assert _brief(container, second).started_at == LATER

    def test_its_chat_and_another_projects_job_hold_up_none(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
        person: User,
    ) -> None:
        session.add(
            models.Session(
                project_id=opened.id,
                kind_code="chat",
                cwd=STORE_REPO,
                token_hash=uuid.uuid4().hex,
                state_code=SessionState.RUNNING,
            )
        )
        site = Project(
            created_by_user_id=person.id,
            state_code=ProjectState.OPEN,
            slug="site",
            name="Site",
        )
        session.add(site)
        session.flush()
        container.document_service().bear_opening(
            site, "Ada Example started this project", person, "A site?"
        )
        _in(session, _setup(container, starts, site), SessionState.RUNNING)

        job = _setup(container, starts, opened, LATER)

        assert job.state_code is SessionState.STARTING

    @pytest.mark.usefixtures("placing")
    def test_the_pause_and_the_outage_come_before_the_queue(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
        person: User,
        controller_outage: ControllerOutage,
    ) -> None:
        _setup(container, starts, opened)
        _transition(session, opened, person, TransitionKind.PAUSED, PAUSED_AT)
        controller_outage.call_unanswered()
        second = _item_done(session, container, opened, person)

        assert starts.held(session, opened, second) == Held(HeldReason.PAUSED)
        _transition(session, opened, person, TransitionKind.RESUMED, RESUMED_AT)
        assert starts.held(session, opened, second) == Held(
            HeldReason.CONTROLLER_UNREACHABLE
        )
        controller_outage.probe_answered()
        assert starts.held(session, opened, second) == Held(HeldReason.QUEUE)


class TestQueueRelease:
    """The release lets a project's earliest held job go on, its brief
    composed then from the record as it stands (F59, F59.2, F141.4; V11,
    V23)."""

    @pytest.mark.usefixtures("placing")
    def test_released_only_the_earliest_job_goes_on_whatever_the_loops_order(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
        person: User,
    ) -> None:
        """The release visits held Sessions in `created_at` order; the queue's
        is the timeline's, the order the jobs were placed in."""
        _transition(session, opened, person, TransitionKind.PAUSED, PAUSED_AT)
        first = _item_done(session, container, opened, person)
        second = _item_done(session, container, opened, person)
        second.created_at = first.created_at - timedelta(minutes=1)
        _transition(session, opened, person, TransitionKind.RESUMED, RESUMED_AT)

        _release(starts)

        first, second = _read(session, first), _read(session, second)
        assert (first.state_code, second.state_code) == (
            SessionState.STARTING,
            SessionState.HELD,
        )
        assert starts.held(session, opened, second) == Held(HeldReason.QUEUE)
        assert second.turns == 0
        assert first.turns == 1

    @pytest.mark.usefixtures("placing")
    def test_a_job_triggered_while_paused_is_briefed_at_the_resume_with_the_pause(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
        person: User,
    ) -> None:
        paused_at = datetime.now(UTC)
        _transition(session, opened, person, TransitionKind.PAUSED, paused_at)
        job = _item_done(session, container, opened, person)
        resumed_at = datetime.now(UTC)
        _transition(session, opened, person, TransitionKind.RESUMED, resumed_at)

        _release(starts)

        job = _read(session, job)
        assert job.state_code is SessionState.STARTING
        turn = _brief(container, job)
        assert (job.turns, job.turn_started_at) == (1, turn.started_at)
        assert turn.message == container.brief_service().job(
            opened, session.get_one(Work, job.id), job.created_at, turn.started_at
        )
        assert turn.message.split("\n\n")[2] == (
            "Auto pilot: off — the granted column asks for this session"
            f" (rules/grants.md).\nPaused {utc_time(paused_at)} to"
            f" {utc_time(resumed_at)}: this job's trigger happened while the"
            " project was paused; the record moved on meanwhile."
        )

    def test_when_a_job_ends_the_next_goes_on_briefed_and_switched_as_it_then_is(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
    ) -> None:
        first = _setup(container, starts, opened)
        second = _setup(container, starts, opened, LATER)
        assert session.get_one(Work, second.id).autopilot is False
        opened.autopilot = True
        _in(session, first, SessionState.IDLE)

        _release(starts)

        second = _read(session, second)
        assert second.state_code is SessionState.STARTING
        work = session.get_one(Work, second.id)
        turn = _brief(container, second)
        assert work.autopilot is True
        assert turn.started_at > LATER
        assert turn.message == container.brief_service().job(
            opened, work, LATER, turn.started_at
        )
        assert "Auto pilot: on — the granted column holds" in turn.message

    def test_across_a_restart_the_queue_holds(
        self,
        container: ServiceContainer,
        session: DbSession,
        supervise: Supervise,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
    ) -> None:
        """A fresh process reconciles the cut start and asks the release:
        the job behind it still waits, and goes on once that one ends."""
        first = _setup(container, starts, opened)
        second = _setup(container, starts, opened, LATER)
        restarted = configured_starts(container, supervise, project_max=1)

        restarted._reconcile(session)
        _release(restarted)

        assert (
            _read(session, first).state_code,
            _read(session, second).state_code,
        ) == (
            SessionState.STARTING,
            SessionState.HELD,
        )
        _in(session, first, SessionState.FAILED)
        _release(restarted)
        assert _read(session, second).state_code is SessionState.STARTING

    def test_a_held_jobs_stop_ends_no_turn_it_never_had(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
        person: User,
    ) -> None:
        """Finish and Archive stop a project's jobs, a held one with no brief
        among them (`stop_project`)."""
        _setup(container, starts, opened)
        second = _setup(container, starts, opened, LATER)

        starts.stop_project(session, opened, person, LATER)

        second = _read(session, second)
        assert (second.state_code, second.turns, second.turn_ended_at) == (
            SessionState.STOPPED,
            0,
            None,
        )


def _committed_opened(container: ServiceContainer) -> uuid.UUID:
    """An open project with its opening, committed; its id."""
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
        project = Project(
            created_by_user_id=person.id,
            state_code=ProjectState.OPEN,
            slug="soup-club",
            name="Soup club",
        )
        db.add(project)
        db.flush()
        container.document_service().bear_opening(
            project, "Ada Example started this project", person, "Soup?"
        )
        return project.id


def _waiting_on_a_lock(container: ServiceContainer) -> bool:
    """Whether a connection to the test's database waits on a lock."""
    other = container.session_maker()()
    try:
        return bool(
            other.scalar(
                select(func.count())
                .select_from(text("pg_stat_activity"))
                .where(
                    text("datname = current_database()"),
                    text("wait_event_type = 'Lock'"),
                )
            )
        )
    finally:
        other.rollback()
        other.close()


class TestQueueAcrossTransactions:
    """A placement and a release reading one project's queue at once start
    one job (F59.2; the lock order; V23)."""

    def test_a_release_waits_for_a_placement_in_flight_and_one_job_starts(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        container = committed_app.container
        starts = configured_starts(container, supervise, project_max=1)
        project_id = _committed_opened(container)
        # A job held by the pause, the pause lifted with no release run: the
        # gate is open for it.
        with scoped_session(container) as db:
            project = db.get_one(Project, project_id)
            project.paused = True
            db.flush()
            first = _jobs(container, starts).setup(project, AT, OPERATION).id
        with scoped_session(container) as db:
            db.get_one(Project, project_id).paused = False
        placed, waited = threading.Event(), threading.Event()

        def place() -> uuid.UUID:
            """A second job's placement, its commit held until the release
            waits for it."""
            with scoped_session(container) as db:
                work = _jobs(container, starts).setup(
                    db.get_one(Project, project_id), LATER, OPERATION
                )
                placed.set()
                assert waited.wait(WAIT_SECONDS)
                return work.id

        def release() -> None:
            with scoped_session(container) as db:
                starts._release_one(db, first)

        with ThreadPoolExecutor(max_workers=2) as pool:
            placing = pool.submit(place)
            assert placed.wait(WAIT_SECONDS)
            releasing = pool.submit(release)
            wait_until(
                lambda: _waiting_on_a_lock(container),
                "the release waits for the placement's project row",
            )
            waited.set()
            second = placing.result(WAIT_SECONDS)
            releasing.result(WAIT_SECONDS)

        with scoped_session(container) as db:
            states = {
                job: db.get_one(models.Session, job).state_code
                for job in (first, second)
            }
        assert states == {first: SessionState.STARTING, second: SessionState.HELD}


WORKER_ENV = "example-soup-3f2a1c"


def _worker_run(
    db: DbSession, container: ServiceContainer, project: Project, files: int
) -> tuple[models.Session, list[Item]]:
    """A worker's run whose turn ended well, as the relay ends it, having
    registered `files` documents, each read and published: the Session and
    the documents' items in the order registered."""
    if db.get(models.Environment, WORKER_ENV) is None:
        db.add(models.Environment(id=WORKER_ENV, name="Soup-1", exempt=False))
    run = models.Session(
        project_id=project.id,
        environment_id=WORKER_ENV,
        kind_code="work",
        cwd="/work/Soup",
        controller_session="claude-7",
        token_hash=uuid.uuid4().hex,
        state_code=SessionState.RUNNING,
    )
    db.add(run)
    db.flush()
    container.record_service().place_work(
        project, run, "Fixing the stock", repo="example/Soup"
    )
    documents = container.document_service()
    items = [
        documents.register(project, run, f"/work/Soup/notes-{n}.md").item
        for n in range(files)
    ]
    now = datetime.now(UTC)
    turn = Turn(session_id=run.id, seq=1, message="Fix the stock.", started_at=now)
    turn.ended_at = now
    db.add(turn)
    db.flush()
    SessionRecordService(
        db,
        container.session_stream_service(),
        ViewService(db, container.engine_bus()),
    ).append(
        run.id,
        RecordKind.RESULT,
        payload={"type": "result", "subtype": "success", "result": "Done."},
        turn_id=turn.id,
        raw_offset=1,
        controller_session="claude-7",
    )
    run.state_code = SessionState.IDLE
    container.record_service().work_done(run.id, now)
    for item in items:
        documents.publish_read(
            db.get_one(models.Document, item.id), "# Notes\n\nLeek.\n", run.id
        )
    return run, items


def _after(
    container: ServiceContainer,
    starts: SessionStartService,
    project: Project,
    run: models.Session,
) -> models.Session | None:
    """The job after the run's turn placed; its Session, None when none is."""
    work = _jobs(container, starts).worker_turn_ended(project, run.id)
    return (
        None
        if work is None
        else container.db_session().get_one(models.Session, work.id)
    )


def _place(db: DbSession, item: Item) -> str:
    """A registered document's place, as a title names it."""
    path = db.get_one(models.Document, item.id).path
    return f"{path.rsplit('/', 1)[0]}/{item.seq}"


class TestWorkerTurnEnded:
    """The job after a worker's turn, placed once the turn-end read settled
    every document the run registered (design 3 §5.3, D2; F59; DB Item
    sample; V01, V12)."""

    @pytest.mark.parametrize("files", [0, 1, 2, 3])
    def test_it_places_a_job_its_trigger_item_the_run_titled_by_what_it_registered(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        files: int,
    ) -> None:
        run, items = _worker_run(session, container, opened, files)
        before = datetime.now(UTC)

        job = _after(container, starts, opened, run)

        assert job is not None
        title = {
            0: NEXT_TITLE,
            1: "Pre-ruling {}",
            2: "Pre-ruling {} and {}",
            3: "Pre-ruling {}, {} and {}",
        }[files].format(*(_place(session, item) for item in items))
        item = session.get_one(Item, job.id)
        last = items[-1] if items else session.get_one(Item, run.id)
        assert (item.seq, item.kind_code, item.title, item.created_by_session_id) == (
            last.seq + 1,
            "work",
            title,
            job.id,
        )
        work = session.get_one(Work, job.id)
        assert (
            work.session_kind_code,
            work.trigger_code,
            work.trigger_item_id,
            work.repo,
        ) == ("job", WorkTrigger.WORKER_TURN_ENDED, run.id, None)
        assert (job.kind_code, job.cwd, job.state_code) == (
            "job",
            STORE_REPO,
            SessionState.STARTING,
        )
        assert before <= job.created_at <= datetime.now(UTC)
        assert _brief(container, job).message.startswith(
            "/pre-rule\n\nPilot's brief · a worker's turn ended · "
        )

    def test_a_run_gets_one_job(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
    ) -> None:
        run, _ = _worker_run(session, container, opened, 1)
        _after(container, starts, opened, run)

        assert _after(container, starts, opened, run) is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(Work)
                .where(Work.trigger_item_id == run.id)
            )
            == 1
        )

    @pytest.mark.parametrize("closed", ["finished", "archived"])
    def test_a_project_finished_or_archived_gets_none(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        closed: str,
    ) -> None:
        run, _ = _worker_run(session, container, opened, 1)
        if closed == "finished":
            opened.state_code = ProjectState.FINISHED
        else:
            opened.archived = True
        session.flush()

        assert _after(container, starts, opened, run) is None
        assert (
            session.scalars(select(Work).where(Work.session_kind_code == "job")).all()
            == []
        )

    def test_placed_while_the_setup_runs_it_waits_its_turn_behind_it(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
    ) -> None:
        setup = _setup(container, starts, opened)
        _in(session, setup, SessionState.RUNNING)
        run, _ = _worker_run(session, container, opened, 1)

        job = _after(container, starts, opened, run)

        assert job is not None
        assert (job.state_code, job.turns) == (SessionState.HELD, 0)
        assert starts.held(session, opened, job) == Held(HeldReason.QUEUE)


QUESTION = """---
title: When to taste
---

```question id=Q1
```
"""


@pytest.fixture
def placing(container: ServiceContainer, starts: SessionStartService) -> None:
    """The container's start the configured one, through which a close
    places the job after it."""
    container.session_start_service.override(providers.Object(starts))


def _pilots(
    db: DbSession, container: ServiceContainer, project: Project
) -> models.Document:
    """A question the project's chat added, a session of Pilot's own."""
    chat = models.Session(
        project_id=project.id,
        kind_code="chat",
        cwd=STORE_REPO,
        token_hash=uuid.uuid4().hex,
        state_code=SessionState.RUNNING,
    )
    db.add(chat)
    db.flush()
    item = container.document_service().bear_item(
        project, "question", "When to taste", chat, QUESTION
    )
    return db.get_one(models.Document, item.id)


def _item_done(
    db: DbSession, container: ServiceContainer, project: Project, person: User
) -> models.Session:
    """The job after the person's close of a question of Pilot's own,
    placed now (`placing`): one of no setup, which the pause holds."""
    return _closed(container, _pilots(db, container, project), person)


def _closed(
    container: ServiceContainer, document: models.Document, person: User
) -> models.Session:
    """The person's answer to the question, its close, through the chat; the
    job it placed."""
    container.record_service().answer(
        document, "Q1", person, "Now", via=AnswerChannel.CHAT
    )
    db = container.db_session()
    work = db.scalars(
        select(Work)
        .join(Item, Item.id == Work.id)
        .where(Work.trigger_item_id == document.id)
        .order_by(Item.seq.desc())
        .limit(1)
    ).one()
    return db.get_one(models.Session, work.id)


@pytest.mark.usefixtures("placing")
class TestItemDone:
    """The job after a person's close of an item of Pilot's own, placed in
    the close's transaction, its brief consuming the item (DB decision 45;
    F14.1, F59; V01, V23, V29)."""

    def test_it_places_a_job_its_trigger_item_the_item(
        self,
        container: ServiceContainer,
        session: DbSession,
        opened: Project,
        person: User,
    ) -> None:
        document = _pilots(session, container, opened)
        item = session.get_one(Item, document.id)
        before = datetime.now(UTC)

        job = _closed(container, document, person)

        work = session.get_one(Work, job.id)
        line = session.get_one(Item, job.id)
        assert (work.trigger_code, work.trigger_item_id, work.repo) == (
            WorkTrigger.ITEM_DONE,
            item.id,
            None,
        )
        assert (line.title, line.seq) == (NEXT_TITLE, item.seq + 1)
        assert (job.kind_code, job.cwd) == ("job", STORE_REPO)
        assert before <= job.created_at <= datetime.now(UTC)

    def test_going_at_once_its_brief_consumes_the_item_in_the_close(
        self,
        container: ServiceContainer,
        session: DbSession,
        opened: Project,
        person: User,
    ) -> None:
        document = _pilots(session, container, opened)

        job = _closed(container, document, person)

        item = session.get_one(Item, document.id)
        turn = _brief(container, job)
        assert job.state_code is SessionState.STARTING
        assert turn.started_at == job.created_at
        assert turn.message.startswith(
            "/plan\n\nPilot's brief · an item of yours is done"
        )
        assert (item.consumed_at, item.consumed_session_id) == (job.created_at, job.id)

    def test_held_by_the_pause_its_brief_and_the_consumption_wait_for_the_release(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        person: User,
    ) -> None:
        document = _pilots(session, container, opened)
        _transition(session, opened, person, TransitionKind.PAUSED, datetime.now(UTC))
        job = _closed(container, document, person)
        item = session.get_one(Item, document.id)
        assert (job.state_code, job.turns, item.consumed_at) == (
            SessionState.HELD,
            0,
            None,
        )
        assert _jobs(container, starts).unbriefed(item) == job
        _transition(session, opened, person, TransitionKind.RESUMED, datetime.now(UTC))

        _release(starts)

        job = _read(session, job)
        item = session.get_one(Item, document.id, populate_existing=True)
        turn = _brief(container, job)
        assert job.state_code is SessionState.STARTING
        assert (item.consumed_at, item.consumed_session_id) == (
            turn.started_at,
            job.id,
        )
        assert "this job's trigger happened while the project was paused" in (
            turn.message
        )
        assert _jobs(container, starts).unbriefed(item) is None

    def test_placed_while_another_job_runs_it_waits_its_turn(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
        person: User,
    ) -> None:
        _in(session, _setup(container, starts, opened), SessionState.RUNNING)
        document = _pilots(session, container, opened)

        job = _closed(container, document, person)

        assert (job.state_code, job.turns) == (SessionState.HELD, 0)
        assert starts.held(session, opened, job) == Held(HeldReason.QUEUE)
        assert session.get_one(Item, document.id).consumed_at is None

    def test_a_withdrawn_job_never_starts_and_the_next_goes_on(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        person: User,
    ) -> None:
        """Withdrawn while the pause holds both, the job before holds up
        none: the release lets the next one go."""
        _transition(session, opened, person, TransitionKind.PAUSED, PAUSED_AT)
        first = _pilots(session, container, opened)
        second = _pilots(session, container, opened)
        withdrawn = _closed(container, first, person)
        following = _closed(container, second, person)

        container.record_service().undo(session.get_one(Item, first.id))
        _transition(session, opened, person, TransitionKind.RESUMED, RESUMED_AT)
        _release(starts)

        withdrawn, following = _read(session, withdrawn), _read(session, following)
        assert (withdrawn.state_code, withdrawn.turns) == (SessionState.STOPPED, 0)
        assert following.state_code is SessionState.STARTING
        status = work_status(
            session, [withdrawn.id], unreachable=False, slots=starts._slots
        )[withdrawn.id]
        assert (status.state, status.stopped_by, status.held_reason) == (
            SessionState.STOPPED,
            None,
            None,
        )


@pytest.mark.usefixtures("placing")
class TestWithdraw:
    """`unbriefed` finds the job a close placed while it is held before its
    brief, and `withdraw` takes it off the gate, its line done `withdrawn`
    (F14.1; V29)."""

    def test_an_item_with_no_job_has_none(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
    ) -> None:
        document = _pilots(session, container, opened)

        assert (
            _jobs(container, starts).unbriefed(session.get_one(Item, document.id))
            is None
        )

    def test_withdrawn_its_session_is_stopped_by_no_one_and_its_line_done(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        person: User,
    ) -> None:
        _transition(session, opened, person, TransitionKind.PAUSED, PAUSED_AT)
        document = _pilots(session, container, opened)
        job = _closed(container, document, person)
        jobs = _jobs(container, starts)
        held = jobs.unbriefed(session.get_one(Item, document.id))
        assert held == job

        jobs.withdraw(job, LATER)

        line = session.get_one(Item, job.id)
        assert (job.state_code, job.stopped_at, job.stopped_by_user_id) == (
            SessionState.STOPPED,
            LATER,
            None,
        )
        assert (line.done_at, line.done_cause_code, line.done_by_user_id) == (
            LATER,
            "withdrawn",
            None,
        )
        assert jobs.unbriefed(session.get_one(Item, document.id)) is None


def _ended(
    db: DbSession,
    container: ServiceContainer,
    job: models.Session,
    state: SessionState = SessionState.FAILED,
    stopped_by: User | None = None,
) -> models.Session:
    """The job's turn ended under it, `failed` or `stopped`, by `stopped_by`
    or no one, its work item left open."""
    ended = datetime.now(UTC)
    _brief(container, job).ended_at = ended
    job.turn_ended_at = ended
    job.state_code = state
    if state is SessionState.STOPPED:
        job.stopped_at = ended
        job.stopped_by_user_id = None if stopped_by is None else stopped_by.id
    else:
        job.error = "API error"
    db.flush()
    return job


def _retry(
    container: ServiceContainer, starts: SessionStartService, job: models.Session
) -> models.Session:
    """A person's Retry of the job; the new job's Session."""
    work = _jobs(container, starts).retry(job.id)
    return container.db_session().get_one(models.Session, work.id)


class TestRetry:
    """A person's Retry of a failed or stopped job: a fresh job for the same
    trigger at the project's next place, through the queue and the gate, the
    job retried marked retried by it; the server retries none on its own
    (D2; the ruling on Q3; F26.3, F94.5; V19)."""

    def test_a_failed_job_is_retried_by_a_fresh_job_for_its_trigger(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
    ) -> None:
        failed = _ended(session, container, _setup(container, starts, opened))
        before = datetime.now(UTC)

        retry = _retry(container, starts, failed)

        line = session.get_one(Item, retry.id)
        assert (line.seq, line.kind_code, line.title, line.created_by_session_id) == (
            session.get_one(Item, failed.id).seq + 1,
            "work",
            SETUP_TITLE,
            retry.id,
        )
        work = session.get_one(Work, retry.id)
        assert (work.trigger_code, work.trigger_item_id, work.retried_by_id) == (
            WorkTrigger.SETUP,
            None,
            None,
        )
        assert (retry.kind_code, retry.cwd, retry.conversation_id) == (
            "job",
            STORE_REPO,
            None,
        )
        assert before <= retry.created_at <= datetime.now(UTC)
        assert retry.state_code is SessionState.STARTING
        assert session.get_one(Work, failed.id).retried_by_id == retry.id
        assert failed.state_code is SessionState.FAILED
        assert session.get_one(Item, failed.id).done_at is None

    def test_its_brief_is_composed_as_it_starts_its_triggers_instant_the_first_jobs(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
    ) -> None:
        """A retried setup's brief says when the project was created, however
        often it was retried (F49, F59)."""
        first = _ended(session, container, _setup(container, starts, opened))
        second = _ended(session, container, _retry(container, starts, first))
        opened.autopilot = True
        session.flush()

        third = _retry(container, starts, second)

        turn = _brief(container, third)
        assert turn.started_at == third.created_at
        assert turn.message == container.brief_service().job(
            opened, session.get_one(Work, third.id), AT, third.created_at
        )
        assert "The project was created 2026-10-27T09:30:15Z from" in turn.message
        assert session.get_one(Work, third.id).autopilot is True

    @pytest.mark.parametrize("by_a_person", [False, True])
    def test_a_stopped_job_is_retried_whoever_stopped_it(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
        person: User,
        by_a_person: bool,
    ) -> None:
        """Stopped under itself, or by an Archive since brought back: a job
        takes no Resume, so Retry is what goes on (F26.3)."""
        stopped = _ended(
            session,
            container,
            _setup(container, starts, opened),
            SessionState.STOPPED,
            person if by_a_person else None,
        )

        retry = _retry(container, starts, stopped)

        assert session.get_one(Work, stopped.id).retried_by_id == retry.id
        assert retry.state_code is SessionState.STARTING

    def test_it_goes_behind_every_job_already_waiting(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
        person: User,
    ) -> None:
        failed = _ended(session, container, _setup(container, starts, opened))
        _transition(session, opened, person, TransitionKind.PAUSED, PAUSED_AT)
        waiting = _setup(container, starts, opened, LATER)

        retry = _retry(container, starts, failed)
        _transition(session, opened, person, TransitionKind.RESUMED, RESUMED_AT)
        _release(starts)

        waiting, retry = _read(session, waiting), _read(session, retry)
        assert (
            session.get_one(Item, retry.id).seq > session.get_one(Item, waiting.id).seq
        )
        assert waiting.state_code is SessionState.STARTING
        assert (retry.state_code, retry.turns) == (SessionState.HELD, 0)
        assert starts.held(session, opened, retry) == Held(HeldReason.QUEUE)

    @pytest.mark.usefixtures("placing")
    def test_a_retried_item_done_jobs_brief_leaves_the_items_consumption(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        person: User,
    ) -> None:
        """Consumed is final (DB 56): the job retried consumed it."""
        document = _pilots(session, container, opened)
        failed = _ended(session, container, _closed(container, document, person))

        retry = _retry(container, starts, failed)

        item = session.get_one(Item, document.id, populate_existing=True)
        assert (item.consumed_at, item.consumed_session_id) == (
            failed.created_at,
            failed.id,
        )
        assert session.get_one(Work, retry.id).trigger_item_id == item.id
        assert _brief(container, retry).message.startswith(
            "/plan\n\nPilot's brief · an item of yours is done"
        )

    def test_the_job_after_a_worker_turn_retried_names_its_run_which_gets_no_other(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
    ) -> None:
        run, _ = _worker_run(session, container, opened, 0)
        job = _after(container, starts, opened, run)
        assert job is not None
        failed = _ended(session, container, job)

        retry = _retry(container, starts, failed)

        work = session.get_one(Work, retry.id)
        assert (work.trigger_code, work.trigger_item_id) == (
            WorkTrigger.WORKER_TURN_ENDED,
            run.id,
        )
        assert session.get_one(Item, retry.id).title == NEXT_TITLE
        assert _after(container, starts, opened, run) is None

    def test_the_server_retries_none_on_its_own(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
    ) -> None:
        failed = _ended(session, container, _setup(container, starts, opened))

        _release(starts)

        assert _read(session, failed).state_code is SessionState.FAILED
        assert session.get_one(Work, failed.id).retried_by_id is None
        assert session.scalar(select(func.count()).select_from(Work)) == 1


class TestRetryRefused:
    """Retry refused with the reason, nothing placed (D2; V19)."""

    def _refusal(
        self,
        container: ServiceContainer,
        starts: SessionStartService,
        job_id: uuid.UUID,
    ) -> str:
        db = container.db_session()
        jobs = db.scalar(select(func.count()).select_from(Work))
        with pytest.raises(InvalidOperationException) as raised:
            _jobs(container, starts).retry(job_id)
        assert db.scalar(select(func.count()).select_from(Work)) == jobs
        return raised.value.message

    @pytest.mark.parametrize(
        ("state", "reason"),
        [
            (SessionState.HELD, "its start waits at the gate"),
            (SessionState.STARTING, "it is starting"),
            (SessionState.RUNNING, "it is running"),
            (SessionState.IDLE, "its turn has ended"),
            (SessionState.ENDED, "its session has ended"),
        ],
    )
    def test_a_job_neither_failed_nor_stopped(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
        state: SessionState,
        reason: str,
    ) -> None:
        job = _setup(container, starts, opened)
        _in(session, job, state)

        assert self._refusal(container, starts, job.id) == (
            f"Cannot retry {SETUP_TITLE} because {reason}"
        )

    def test_a_job_retried_already(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
    ) -> None:
        failed = _ended(session, container, _setup(container, starts, opened))
        _retry(container, starts, failed)

        assert self._refusal(container, starts, failed.id) == (
            f"Cannot retry {SETUP_TITLE} because it was retried already"
        )

    def test_a_job_whose_work_item_is_done(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
    ) -> None:
        failed = _ended(session, container, _setup(container, starts, opened))
        container.record_service().work_done(failed.id, datetime.now(UTC))

        assert self._refusal(container, starts, failed.id) == (
            f"Cannot retry {SETUP_TITLE} because it is done"
        )

    @pytest.mark.usefixtures("placing")
    def test_a_job_an_undo_withdrew(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        person: User,
    ) -> None:
        """Stopped by no one with no Turn, but done `withdrawn` (P4)."""
        _transition(session, opened, person, TransitionKind.PAUSED, PAUSED_AT)
        document = _pilots(session, container, opened)
        withdrawn = _closed(container, document, person)
        container.record_service().undo(session.get_one(Item, document.id))

        assert self._refusal(container, starts, withdrawn.id) == (
            f"Cannot retry {NEXT_TITLE} because an Undo withdrew it before its"
            " brief went out"
        )

    def test_a_stopped_job_whose_turn_is_still_ending(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
    ) -> None:
        """Stopped while it ran, by Archive's Stop, the interrupt not yet
        recorded: its session may still write."""
        job = _setup(container, starts, opened)
        job.state_code = SessionState.STOPPED
        session.flush()

        assert self._refusal(container, starts, job.id) == (
            f"Cannot retry {SETUP_TITLE} because its stopped turn is still ending"
        )

    @pytest.mark.parametrize(
        ("archived", "state", "reason"),
        [
            (True, ProjectState.OPEN, "its project is archived"),
            (False, ProjectState.FINISHED, "its project is finished"),
        ],
    )
    def test_in_a_finished_or_archived_project(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
        archived: bool,
        state: ProjectState,
        reason: str,
    ) -> None:
        failed = _ended(session, container, _setup(container, starts, opened))
        opened.archived, opened.state_code = archived, state
        session.flush()

        assert self._refusal(container, starts, failed.id) == (
            f"Cannot retry {SETUP_TITLE} because {reason}"
        )

    @pytest.mark.usefixtures("placing")
    def test_a_job_whose_item_is_open_again(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        person: User,
    ) -> None:
        """Archive stopped it before its brief, and the item's Undo took the
        close back once the project was brought back."""
        _transition(session, opened, person, TransitionKind.PAUSED, PAUSED_AT)
        document = _pilots(session, container, opened)
        job = _closed(container, document, person)
        job.state_code = SessionState.STOPPED
        job.stopped_by_user_id = person.id
        item = session.get_one(Item, document.id)
        item.done_at = item.done_cause_code = item.done_by_user_id = None
        session.flush()

        assert self._refusal(container, starts, job.id) == (
            f"Cannot retry {NEXT_TITLE} because the item it follows is open again"
        )

    def test_a_workers_run(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
    ) -> None:
        run, _ = _worker_run(session, container, opened, 0)
        run.state_code = SessionState.FAILED
        session.flush()

        assert self._refusal(container, starts, run.id) == (
            "Cannot retry Fixing the stock because it is a worker's run, which"
            " Resume carries on"
        )

    def test_a_session_that_is_no_work_item(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
    ) -> None:
        chat = models.Session(
            project_id=opened.id,
            kind_code="chat",
            cwd=STORE_REPO,
            token_hash=uuid.uuid4().hex,
            state_code=SessionState.FAILED,
        )
        session.add(chat)
        session.flush()

        assert self._refusal(container, starts, chat.id) == (
            f"Cannot retry work item {chat.id} because it is no work item"
        )

    def test_an_unknown_session_is_not_found(
        self, container: ServiceContainer, starts: SessionStartService
    ) -> None:
        unknown = uuid.uuid4()

        with pytest.raises(RecordNotFoundException) as raised:
            _jobs(container, starts).retry(unknown)

        assert raised.value.message == f"Session {unknown} was not found"

    def test_with_no_controller_configured(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
    ) -> None:
        failed = _ended(session, container, _setup(container, starts, opened))

        with pytest.raises(InvalidOperationException) as raised:
            container.job_service().retry(failed.id)

        assert raised.value.message == (
            f"Cannot retry {SETUP_TITLE} because no controller is configured"
        )


class TestRetryAcrossTransactions:
    """Two Retries of one job at once place one job (the lock order)."""

    def test_the_second_waits_for_the_first_and_is_refused(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        container = committed_app.container
        starts = configured_starts(container, supervise, project_max=1)
        project_id = _committed_opened(container)
        with scoped_session(container) as db:
            job = _jobs(container, starts).setup(
                db.get_one(Project, project_id), AT, OPERATION
            )
            failed = db.get_one(models.Session, job.id)
            failed.state_code = SessionState.FAILED
            failed.turn_ended_at = datetime.now(UTC)
        retried, waited = threading.Event(), threading.Event()

        def first() -> uuid.UUID:
            """A Retry, its commit held until the second waits for it."""
            with scoped_session(container):
                work = _jobs(container, starts).retry(job.id)
                retried.set()
                assert waited.wait(WAIT_SECONDS)
                return work.id

        def second() -> str:
            with (
                scoped_session(container),
                pytest.raises(InvalidOperationException) as raised,
            ):
                _jobs(container, starts).retry(job.id)
            return raised.value.message

        with ThreadPoolExecutor(max_workers=2) as pool:
            placing = pool.submit(first)
            assert retried.wait(WAIT_SECONDS)
            refusing = pool.submit(second)
            wait_until(
                lambda: _waiting_on_a_lock(container),
                "the second Retry waits for the first's project row",
            )
            waited.set()
            retry = placing.result(WAIT_SECONDS)
            refusal = refusing.result(WAIT_SECONDS)

        assert refusal == f"Cannot retry {SETUP_TITLE} because it was retried already"
        with scoped_session(container) as db:
            assert db.get_one(Work, job.id).retried_by_id == retry
            assert db.scalar(select(func.count()).select_from(Work)) == 2
