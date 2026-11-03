"""The batcher (design 2 §8.2; F136.4, F136.5; DB 191, 195, 196, 200; V06):
its tick places one run per batch of a wait's firings, through the gate and its
project's queue, the run taking every firing pending at its brief and resuming
its wait's previous run's conversation within `cache_expiration_ttl`; driven on
the fake controller."""

import logging
import threading
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from dependency_injector import providers
from flask import Flask
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session as DbSession
from werkzeug.wrappers import Request, Response

from app import models
from app.database import scoped_session
from app.models import Item, Project, Turn, User, WaitFiring, Work
from app.models.reference import ProjectState, SessionState, UserKind, WorkTrigger
from app.services import job_service
from app.services.container import ServiceContainer
from app.services.fake_controller import FakeControllerProblem
from app.services.job_service import JobService
from app.services.session_scope import STORE_REPO
from app.services.session_start_service import SessionStartService
from app.services.supervisor import LoopHandle
from app.services.wait_batcher import WaitBatcher
from app.services.wait_service import ReportedTransition
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.fake_controller import ServedFakeController, client_of
from tests.support.fake_sidecar import STORE_ENVIRONMENT_ID
from tests.support.starts import configured_starts
from tests.support.supervisor import WAIT_SECONDS, Supervise, wait_until

AT = datetime(2026, 10, 27, 9, 30, 15, tzinfo=UTC)
FOLDER = "/work/Projects/soup-club"
TITLE = "Slice 058 completes"
QUIET = timedelta(seconds=5)
TRANSITION = ReportedTransition(
    card="ANS-312", from_state="In Progress", to_state="Done", at=AT, by="pieter"
)


class _Recording(ServedFakeController):
    """The fake, keeping each headless create's body and each send's message;
    with `refuse_resume`, refusing a create that resumes a conversation."""

    def __init__(self, keepalive_seconds: float) -> None:
        super().__init__(keepalive_seconds)
        self.creates: list[dict[str, Any]] = []
        self.sent: list[str] = []
        self.refuse_resume = False

    def _create_session(self, request: Request, env_id: str) -> Response:
        body = request.get_json(silent=True) or {}
        self.creates.append(body)
        if self.refuse_resume and body.get("resume"):
            raise FakeControllerProblem(
                409, "conflict", f"no conversation {body['resume']} to resume"
            )
        return super()._create_session(request, env_id)

    def _send(self, request: Request, env_id: str, name: str) -> Response:
        self.sent.append((request.get_json(silent=True) or {}).get("message"))
        return super()._send(request, env_id, name)


@pytest.fixture
def opened(session: DbSession, project: Project) -> Project:
    """`project` open, named and with its slug, as Create leaves it."""
    project.state_code = ProjectState.OPEN
    project.slug, project.name = "soup-club", "Soup club"
    session.flush()
    return project


@pytest.fixture
def starts(container: ServiceContainer, supervise: Supervise) -> SessionStartService:
    """The container's start, with a controller and the store configured, its
    loops never run."""
    configured = configured_starts(container, supervise)
    container.session_start_service.override(providers.Object(configured))
    return configured


@pytest.fixture
def batcher(
    container: ServiceContainer, supervise: Supervise, starts: SessionStartService
) -> WaitBatcher:
    supervisor, _ = supervise(container)
    return WaitBatcher(container, supervisor, QUIET.total_seconds())


@pytest.fixture
def fake(container: ServiceContainer) -> Iterator[_Recording]:
    """The fake controller, `container`'s client on it, the store running in
    it with the store repo's root and the project's folder on its tree."""
    served = _Recording(keepalive_seconds=0.2)
    client_of(container, served)
    served.add_environment(
        STORE_ENVIRONMENT_ID, name="PilotProjects", status="running", exempt=True
    )
    served.put_file(STORE_ENVIRONMENT_ID, f"{STORE_REPO}/CLAUDE.md", b"# Pilot\n")
    served.put_file(STORE_ENVIRONMENT_ID, f"{FOLDER}/plan.json", b"{}")
    try:
        yield served
    finally:
        served.close()


@pytest.fixture
def wait(
    container: ServiceContainer, opened: Project, project_session: models.Session
) -> Item:
    """An open card wait of the project's, on ANS-312 entering Done."""
    added = container.wait_service().add_card_wait(
        opened, project_session, TITLE, ["ANS-312"], ["Done"], None
    )
    clear_after_commit_callbacks()
    return added


def _fire(
    db: DbSession, container: ServiceContainer, wait: Item, ago: timedelta
) -> WaitFiring:
    """The wait fired by ANS-312's transition, recorded `ago`."""
    assert container.wait_service().fire_transition(TRANSITION) == 1
    firing = db.scalars(
        select(WaitFiring)
        .where(WaitFiring.wait_id == wait.id)
        .order_by(WaitFiring.seq.desc())
        .limit(1)
    ).one()
    firing.fired_at = datetime.now(UTC) - ago
    db.flush()
    clear_after_commit_callbacks()
    return firing


def _tick(db: DbSession, batcher: WaitBatcher) -> None:
    batcher.run(db)
    clear_after_commit_callbacks()


def _runs(db: DbSession, wait: Item) -> list[models.Session]:
    """The wait's runs, in the order placed."""
    return list(
        db.scalars(
            select(models.Session)
            .join(Work, Work.id == models.Session.id)
            .join(Item, Item.id == Work.id)
            .where(
                Work.trigger_code == WorkTrigger.WAIT_FIRED,
                Work.trigger_item_id == wait.id,
            )
            .order_by(Item.seq)
            .execution_options(populate_existing=True)
        )
    )


def _taken(db: DbSession, wait: Item) -> list[uuid.UUID | None]:
    """The run each of the wait's firings went to, in their order."""
    return list(
        db.scalars(
            select(WaitFiring.job_id)
            .where(WaitFiring.wait_id == wait.id)
            .order_by(WaitFiring.seq)
            .execution_options(populate_existing=True)
        )
    )


def _brief(db: DbSession, job: models.Session) -> str:
    (turn,) = db.scalars(select(Turn).where(Turn.session_id == job.id))
    return turn.message


def _run(starts: SessionStartService, job: models.Session) -> None:
    """The job's start loop's run, to its first Turn's send."""
    starts.run(job.id, LoopHandle(f"start:{job.id}"))


def _turn_ended(
    db: DbSession,
    container: ServiceContainer,
    job: models.Session,
    ago: timedelta,
    conversation: str = "conversation-1",
) -> None:
    """The run's turn ended `idle` on its conversation, its work item done,
    as its relay leaves it; the turn's end read as `ago`."""
    job.state_code = SessionState.IDLE
    job.conversation_id = conversation
    job.turn_ended_at = datetime.now(UTC) - ago
    container.record_service().work_done(job.id, datetime.now(UTC))
    db.flush()
    clear_after_commit_callbacks()


@pytest.mark.usefixtures("starts")
class TestBatch:
    """A wait's firings within the quiet window are one run; firings while
    it is in flight go to its brief or to the next run (F136.4; DB 196)."""

    def test_a_burst_is_one_run_its_brief_the_firings_oldest_first(
        self,
        container: ServiceContainer,
        session: DbSession,
        batcher: WaitBatcher,
        starts: SessionStartService,
        fake: _Recording,
        opened: Project,
        wait: Item,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Later firings join the first's window, none extending it."""
        _fire(session, container, wait, QUIET + timedelta(seconds=1))
        _fire(session, container, wait, timedelta(seconds=2))
        _fire(session, container, wait, timedelta())

        with caplog.at_level(logging.INFO, "app.services.wait_batcher"):
            _tick(session, batcher)

        (job,) = _runs(session, wait)
        line = session.get_one(Item, job.id)
        work = session.get_one(Work, job.id)
        assert (line.kind_code, line.title) == ("work", f'Checking "{TITLE}"')
        assert (work.trigger_code, work.trigger_item_id) == (
            WorkTrigger.WAIT_FIRED,
            wait.id,
        )
        assert (job.kind_code, job.state_code, job.conversation_id) == (
            "job",
            SessionState.STARTING,
            None,
        )
        assert _taken(session, wait) == [job.id] * 3
        brief = _brief(session, job)
        assert brief == container.brief_service().job(
            opened, work, job.created_at, job.turn_started_at
        )
        assert brief.count("ANS-312: In Progress → Done, by pieter") == 3
        assert [
            record.getMessage()
            for record in caplog.records
            if record.name == "app.services.wait_batcher"
        ] == ["1 runs placed for waits' firings"]

        _run(starts, job)

        assert fake.creates[0].get("resume") is None
        assert fake.sent == [brief]

    def test_within_the_quiet_window_no_run_is_placed(
        self,
        container: ServiceContainer,
        session: DbSession,
        batcher: WaitBatcher,
        wait: Item,
    ) -> None:
        firing = _fire(session, container, wait, QUIET - timedelta(seconds=1))

        _tick(session, batcher)

        assert _runs(session, wait) == []
        firing.fired_at -= timedelta(seconds=2)
        session.flush()
        _tick(session, batcher)
        assert len(_runs(session, wait)) == 1

    def test_a_firing_while_its_run_is_queued_joins_it_at_its_brief(
        self,
        container: ServiceContainer,
        session: DbSession,
        batcher: WaitBatcher,
        starts: SessionStartService,
        opened: Project,
        person: User,
        wait: Item,
    ) -> None:
        container.document_service().bear_opening(
            opened, "Ada Example started this project", person, "Soup?"
        )
        setup = container.job_service().setup(opened, AT, "create Soup club")
        _fire(session, container, wait, QUIET * 2)

        _tick(session, batcher)

        (job,) = _runs(session, wait)
        assert (job.state_code, job.turns) == (SessionState.HELD, 0)
        assert _taken(session, wait) == [None]
        _fire(session, container, wait, QUIET * 2)
        _tick(session, batcher)
        assert len(_runs(session, wait)) == 1

        session.get_one(models.Session, setup.id).state_code = SessionState.IDLE
        session.flush()
        starts.release(LoopHandle("start:held"))

        (job,) = _runs(session, wait)
        assert job.state_code is SessionState.STARTING
        assert _taken(session, wait) == [job.id, job.id]
        assert _brief(session, job).count("ANS-312: In Progress → Done") == 2

    def test_a_wait_closed_while_its_run_is_queued_withdraws_the_run(
        self,
        container: ServiceContainer,
        session: DbSession,
        batcher: WaitBatcher,
        starts: SessionStartService,
        opened: Project,
        person: User,
        project_session: models.Session,
        wait: Item,
    ) -> None:
        """A wait that is done gets no run: its run never briefed is withdrawn,
        and its firings stay untaken."""
        container.document_service().bear_opening(
            opened, "Ada Example started this project", person, "Soup?"
        )
        setup = container.job_service().setup(opened, AT, "create Soup club")
        _fire(session, container, wait, QUIET * 2)
        _tick(session, batcher)
        (job,) = _runs(session, wait)
        assert (job.state_code, job.turns) == (SessionState.HELD, 0)

        container.wait_service().close(
            opened,
            session.get_one(models.Wait, wait.id),
            session.scalars(select(User).where(User.kind_code == UserKind.AGENT)).one(),
            project_session.id,
            "ANS-312 read Done at 09:40",
        )
        session.get_one(models.Session, setup.id).state_code = SessionState.IDLE
        session.flush()
        starts.release(LoopHandle("start:held"))

        (job,) = _runs(session, wait)
        assert (job.state_code, job.turns, job.stopped_by_user_id) == (
            SessionState.STOPPED,
            0,
            None,
        )
        assert session.get_one(Item, job.id).done_cause_code == "withdrawn"
        assert _taken(session, wait) == [None]

    def test_a_firing_during_its_run_goes_to_the_next_run_once_its_turn_ends(
        self,
        container: ServiceContainer,
        session: DbSession,
        batcher: WaitBatcher,
        wait: Item,
    ) -> None:
        _fire(session, container, wait, QUIET * 2)
        _tick(session, batcher)
        (first,) = _runs(session, wait)
        first.state_code = SessionState.RUNNING
        session.flush()
        _fire(session, container, wait, QUIET * 2)

        _tick(session, batcher)

        assert _runs(session, wait) == [first]
        assert _taken(session, wait) == [first.id, None]
        _turn_ended(session, container, first, timedelta(minutes=1))
        _tick(session, batcher)
        first, second = _runs(session, wait)
        assert _taken(session, wait) == [first.id, second.id]

    @pytest.mark.parametrize("how", ["done", "finished", "archived"])
    def test_a_done_wait_or_a_closed_projects_wait_gets_no_run(
        self,
        container: ServiceContainer,
        session: DbSession,
        batcher: WaitBatcher,
        opened: Project,
        project_session: models.Session,
        wait: Item,
        how: str,
    ) -> None:
        _fire(session, container, wait, QUIET * 2)
        if how == "done":
            pilot = session.scalars(
                select(User).where(User.kind_code == UserKind.AGENT)
            ).one()
            container.wait_service().close(
                opened,
                session.get_one(models.Wait, wait.id),
                pilot,
                project_session.id,
                "ANS-312 read Done at 09:40",
            )
        elif how == "finished":
            opened.state_code = ProjectState.FINISHED
        else:
            opened.archived = True
        session.flush()

        _tick(session, batcher)

        assert _runs(session, wait) == []


@pytest.mark.usefixtures("starts")
class TestResume:
    """A run resumes its wait's previous run's conversation while that run's
    turn ended within `cache_expiration_ttl`, with the follow-up alone; past
    it, fresh; a resume the controller refuses fails the run (F136.5, F125;
    DB 200)."""

    def _previous(
        self,
        container: ServiceContainer,
        session: DbSession,
        batcher: WaitBatcher,
        wait: Item,
        ended: timedelta,
    ) -> models.Session:
        """The wait's first run, its turn ended `ended` ago, briefed under
        auto pilot on; then a firing since, past the window."""
        _fire(session, container, wait, QUIET * 2)
        _tick(session, batcher)
        (previous,) = _runs(session, wait)
        session.get_one(Work, previous.id).autopilot = True
        _turn_ended(session, container, previous, ended)
        _fire(session, container, wait, QUIET * 2)
        return previous

    def test_within_the_ttl_the_next_run_resumes_with_the_follow_up(
        self,
        container: ServiceContainer,
        session: DbSession,
        batcher: WaitBatcher,
        starts: SessionStartService,
        fake: _Recording,
        opened: Project,
        wait: Item,
    ) -> None:
        self._previous(container, session, batcher, wait, timedelta(minutes=54))

        _tick(session, batcher)

        _, job = _runs(session, wait)
        work = session.get_one(Work, job.id)
        assert job.conversation_id == "conversation-1"
        assert _brief(session, job) == container.brief_service().wait_follow_up(work)
        assert _brief(session, job).startswith(f'Another firing of "{TITLE}"')
        # The conversation keeps the switch its brief stated (F54.7).
        assert (opened.autopilot, work.autopilot) == (False, True)

        _run(starts, job)

        assert fake.creates[0]["resume"] == "conversation-1"
        assert fake.sent == [_brief(session, job)]
        assert _read(session, job).state_code is SessionState.RUNNING

    def test_past_the_ttl_the_next_run_is_fresh_with_the_full_brief(
        self,
        container: ServiceContainer,
        session: DbSession,
        batcher: WaitBatcher,
        starts: SessionStartService,
        fake: _Recording,
        opened: Project,
        wait: Item,
    ) -> None:
        self._previous(container, session, batcher, wait, timedelta(minutes=56))

        _tick(session, batcher)

        _, job = _runs(session, wait)
        work = session.get_one(Work, job.id)
        assert job.conversation_id is None
        assert _brief(session, job).startswith("/plan\n\n")
        assert work.autopilot is False

        _run(starts, job)

        assert fake.creates[0].get("resume") is None
        assert fake.sent == [_brief(session, job)]

    def test_a_resume_the_controller_refuses_fails_the_run_with_no_fallback(
        self,
        container: ServiceContainer,
        session: DbSession,
        batcher: WaitBatcher,
        starts: SessionStartService,
        fake: _Recording,
        wait: Item,
    ) -> None:
        """The next run, its previous run failed, starts fresh."""
        self._previous(container, session, batcher, wait, timedelta(minutes=1))
        fake.refuse_resume = True
        _tick(session, batcher)
        _, job = _runs(session, wait)

        _run(starts, job)

        job = _read(session, job)
        assert job.state_code is SessionState.FAILED
        assert job.error is not None and "no conversation conversation-1" in job.error
        assert [body.get("resume") for body in fake.creates] == ["conversation-1"]
        assert fake.sent == []
        assert session.get_one(Item, job.id).done_at is None
        _fire(session, container, wait, QUIET * 2)
        _tick(session, batcher)
        *_, fresh = _runs(session, wait)
        assert fresh.conversation_id is None
        assert _brief(session, fresh).startswith("/plan\n\n")


def _read(db: DbSession, job: models.Session) -> models.Session:
    return db.get_one(models.Session, job.id, populate_existing=True)


def _committed_fired(container: ServiceContainer) -> uuid.UUID:
    """An open project's card wait fired past the quiet window, committed;
    the wait's id."""
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
        run = models.Session(
            project_id=project.id,
            kind_code="work",
            cwd="/work/Example",
            token_hash="1" * 64,
            state_code=SessionState.RUNNING,
        )
        db.add(run)
        db.flush()
        added = container.wait_service().add_card_wait(
            project, run, TITLE, ["ANS-312"], ["Done"], None
        )
        _fire(db, container, added, QUIET * 2)
        return added.id


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


class TestTwoBackends:
    """During a roll two processes run the batcher at once (design 2 §8.1)."""

    def test_two_backends_place_one_run_per_batch(
        self,
        committed_app: Flask,
        supervise: Supervise,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        container = committed_app.container
        container.session_start_service.override(
            providers.Object(configured_starts(container, supervise))
        )
        supervisor, _ = supervise(container)
        batcher = WaitBatcher(container, supervisor, QUIET.total_seconds())
        wait_id = _committed_fired(container)
        placed, waited = threading.Event(), threading.Event()
        place = JobService.wait_fired
        holding = [True]

        def held(service: JobService, project: Project, wait: Item) -> Work:
            """The first process's placement, its commit held until the
            second waits for its rows."""
            work = place(service, project, wait)
            if holding:
                holding.pop()
                placed.set()
                assert waited.wait(WAIT_SECONDS)
            return work

        monkeypatch.setattr(job_service.JobService, "wait_fired", held)

        def tick() -> None:
            with scoped_session(container) as db:
                batcher.run(db)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(tick)
            assert placed.wait(WAIT_SECONDS)
            second = pool.submit(tick)
            wait_until(
                lambda: _waiting_on_a_lock(container),
                "the second backend waits for the first's rows",
            )
            waited.set()
            first.result(WAIT_SECONDS)
            second.result(WAIT_SECONDS)

        with scoped_session(container) as db:
            runs = db.scalar(
                select(func.count())
                .select_from(Work)
                .where(
                    Work.trigger_code == WorkTrigger.WAIT_FIRED,
                    Work.trigger_item_id == wait_id,
                )
            )
            taken = db.scalars(
                select(WaitFiring.job_id).where(WaitFiring.wait_id == wait_id)
            ).all()
        assert runs == 1
        assert len(set(taken)) == 1 and None not in taken
