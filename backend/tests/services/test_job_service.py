"""Pilot's own background jobs, the setup the one placed (design 3 §5.1,
§5.3; F49, F59, F59.1; TD §4.2; DB Work, assertion 167, 243)."""

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from werkzeug.wrappers import Request, Response

from app import models
from app.exceptions import InvalidOperationException
from app.models import Item, Project, Turn, User, Work
from app.models.reference import ProjectState, SessionState, Surface, WorkTrigger
from app.schemas.timeline import HeldReason
from app.services.container import ServiceContainer
from app.services.job_service import SETUP_TITLE, JobService
from app.services.session_scope import STORE_REPO, scoped_create
from app.services.session_start_service import SessionStartService
from app.services.supervisor import LoopHandle
from tests.support.fake_controller import ServedFakeController, client_of
from tests.support.fake_sidecar import STORE_ENVIRONMENT_ID
from tests.support.starts import configured_starts
from tests.support.supervisor import Supervise

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
    opening: Item,
) -> models.Session:
    """The setup placed; its Session."""
    work = _jobs(container, starts).setup(project, opening, AT, OPERATION)
    return container.db_session().get_one(models.Session, work.id)


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
        job = _setup(container, starts, opened, opening)

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
        )

    def test_its_first_turn_is_the_setups_brief(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
    ) -> None:
        job = _setup(container, starts, opened, opening)

        (turn,) = session.scalars(select(Turn).where(Turn.session_id == job.id))
        assert (turn.seq, turn.author_user_id, turn.words, turn.started_at) == (
            1,
            None,
            None,
            AT,
        )
        assert turn.message == container.brief_service().setup(opened, opening, AT)

    def test_its_create_is_boxed_to_the_projects_folder_with_pilot_store(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
    ) -> None:
        job = _setup(container, starts, opened, opening)

        create = scoped_create(session, job)
        assert create.surface is Surface.STORE
        assert (
            create.request.cwd,
            create.request.sandbox_read_only_cwd,
            create.request.sandbox_writable_dirs,
            create.request.env,
        ) == (STORE_REPO, True, [FOLDER], [f"PILOT_PROJECT={FOLDER}"])

    def test_it_is_held_while_the_project_is_paused(
        self,
        container: ServiceContainer,
        session: DbSession,
        starts: SessionStartService,
        opened: Project,
        opening: Item,
    ) -> None:
        opened.paused = True
        session.flush()

        job = _setup(container, starts, opened, opening)

        assert job.state_code is SessionState.HELD
        held = starts.held(session, opened, job)
        assert held is not None and held.reason is HeldReason.PAUSED

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

        job = _setup(container, starts, opened, opening)

        assert job.state_code is SessionState.STARTING
        assert starts._slots.filled(session, [opened.id]) == {opened.id: 1}

    def test_with_no_controller_configured_it_is_refused(
        self,
        container: ServiceContainer,
        opened: Project,
        opening: Item,
    ) -> None:
        with pytest.raises(InvalidOperationException) as raised:
            container.job_service().setup(opened, opening, AT, OPERATION)

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
        job = _setup(container, starts, opened, opening)
        brief = container.brief_service().setup(opened, opening, AT)

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
