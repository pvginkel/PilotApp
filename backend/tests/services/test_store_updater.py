"""The store's update, run by the server from its row (F144.3; design 5 D2,
D4, D6, D9; DB Store Update, assertions 279 and 280): the stops by Pilot, the
store's reset, the wait for its sidecar's reconcile and the lift, each phase
written once and in order, through a roll, a cut and an outage.

`TestRun`, `TestTimer` and `TestReconciled` call the loop's run, the tick and
the sync's note on the test's session, as their callers do. `TestSequence`
runs the job from the row's commit on a database of its own, as the
supervisor does, on the fake controller and the fake sidecar."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from dependency_injector import providers
from flask import Flask
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.models import Chat, Environment, Project, StoreUpdate, Turn, User
from app.models.reference import (
    ChatKind,
    ProjectState,
    SessionState,
    UserKind,
    WorkTrigger,
)
from app.services.chat_close_service import ChatCloseService
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerUnreachable, HeadlessCreateRequest
from app.services.environment_service import EnvironmentService, EnvironmentStartFailed
from app.services.pilot_server import PilotServer
from app.services.relay_service import RelayService
from app.services.session_start_service import (
    NUDGE_KEY,
    RELEASE_KEY,
    START_JOB,
    SessionStartService,
)
from app.services.start_gate import WorkSlots
from app.services.store_updater import STORE_UPDATE_JOB, StoreUpdater
from app.services.supervisor import JOB_RESTARTS_TOTAL, TIMER_RUNS_TOTAL, LoopHandle
from app.services.turn_end_read_service import TurnEndReadService
from app.utils.after_commit import clear_after_commit_callbacks
from app.utils.lifecycle_coordinator import LifecycleCoordinator
from tests.support.fake_controller import ServedFakeController, client_of
from tests.support.fake_sidecar import STORE_ENVIRONMENT_ID, FakeSidecar
from tests.support.locks import lock_waits
from tests.support.store_updates import hold, lift
from tests.support.supervisor import (
    LogWaiter,
    RoundsHandle,
    Supervise,
    listening,
    metric_value,
    wait_until,
)

STORE_REPO = "/work/PilotProjects"
OTHER_ENV = "example-env-2"
"""An environment of the fleet that is not the store."""
UPDATER_LOGGER = "app.services.store_updater"
START_LOGGER = "app.services.session_start_service"


def _built(
    container: ServiceContainer,
    supervise: Supervise,
    *,
    tick: float = 0.05,
    turn_wait: float = 5.0,
) -> tuple[StoreUpdater, SessionStartService, LifecycleCoordinator]:
    """The update and the services it drives on a supervisor of their own,
    as a process of its own has them, the container's from now on."""
    supervisor, coordinator = supervise(container, tick=tick)
    environments = EnvironmentService(
        container=container,
        supervisor=supervisor,
        stop_after_seconds=1800,
        delete_after_seconds=604800,
    )
    slots = WorkSlots(work_max=3, project_max=3)
    pilot_server = PilotServer(None)
    relays = RelayService(
        container=container,
        supervisor=supervisor,
        session_streams=container.session_stream_service(),
        environment_service=environments,
        work_slots=slots,
        pilot_server=pilot_server,
        turn_end_reads=TurnEndReadService(
            container=container,
            supervisor=supervisor,
            session_streams=container.session_stream_service(),
        ),
        chat_closes=ChatCloseService(
            container=container,
            supervisor=supervisor,
            session_streams=container.session_stream_service(),
            close_after_seconds=3300,
        ),
    )
    starts = SessionStartService(
        container=container,
        supervisor=supervisor,
        session_streams=container.session_stream_service(),
        environment_service=environments,
        relay_service=relays,
        controller_outage=container.controller_outage(),
        work_slots=slots,
        usage_halts=container.usage_halts(),
        pilot_server=pilot_server,
        controller_configured=True,
        store_environment_id=STORE_ENVIRONMENT_ID,
        folder_wait_seconds=1.0,
        folder_retry_seconds=0.05,
    )
    updater = StoreUpdater(
        container=container,
        supervisor=supervisor,
        environment_service=environments,
        session_start_service=starts,
        store_environment_id=STORE_ENVIRONMENT_ID,
        turn_wait_seconds=turn_wait,
        turn_poll_seconds=0.02,
    )
    container.session_start_service.override(providers.Object(starts))
    container.store_updater.override(providers.Object(updater))
    return updater, starts, coordinator


def _fleet(fake: ServedFakeController) -> None:
    """The store in the fleet, running and exempt, with its repo's root on
    its tree; and an environment that is not the store, running too."""
    fake.add_environment(
        STORE_ENVIRONMENT_ID, name="PilotProjects", status="running", exempt=True
    )
    fake.put_file(STORE_ENVIRONMENT_ID, f"{STORE_REPO}/CLAUDE.md", b"# Pilot\n")
    fake.add_environment(OTHER_ENV, name="Example-2", status="running")


def _store_row(db: DbSession) -> Environment:
    """The store's Environment row, made once a brain session started there."""
    row = Environment(id=STORE_ENVIRONMENT_ID, name="PilotProjects", exempt=True)
    db.add(row)
    db.flush()
    return row


def _person(db: DbSession) -> User:
    person = User(
        kind_code=UserKind.PERSON,
        subject="subject-ada",
        handle="ada",
        name="Ada Example",
        avatar_slot=1,
    )
    db.add(person)
    db.flush()
    return person


def _project(db: DbSession, person: User, slug: str) -> Project:
    opened = Project(
        created_by_user_id=person.id, state_code=ProjectState.OPEN, slug=slug
    )
    db.add(opened)
    db.flush()
    return opened


def _brain(
    container: ServiceContainer,
    db: DbSession,
    project: Project,
    kind: str,
    state: SessionState,
    *,
    controller_session: str | None = None,
    briefed: bool = True,
) -> models.Session:
    """A Chat's Session or a job's, in the store, in `state`: a Chat open,
    a job placed as the project's setup, its brief written as its first Turn
    when `briefed`."""
    run = models.Session(
        project_id=project.id,
        environment_id=None if controller_session is None else STORE_ENVIRONMENT_ID,
        kind_code=kind,
        cwd=STORE_REPO,
        controller_session=controller_session,
        token_hash=uuid.uuid4().hex,
        state_code=state,
    )
    db.add(run)
    db.flush()
    if kind == "chat":
        db.add(
            Chat(
                id=run.id,
                project_id=project.id,
                session_kind_code="chat",
                kind_code=ChatKind.PROJECT,
            )
        )
    else:
        container.record_service().place_work(
            project, run, "Setting up the project", trigger=WorkTrigger.SETUP
        )
    if briefed:
        now = datetime.now(UTC)
        db.add(Turn(session_id=run.id, seq=1, message="Hi", started_at=now))
        run.turns, run.turn_started_at = 1, now
    db.flush()
    return run


def _work_item(db: DbSession, project: Project) -> models.Session:
    """A work item running in an environment that is not the store."""
    db.add(Environment(id=OTHER_ENV, name="Example-2", exempt=False))
    db.flush()
    run = models.Session(
        project_id=project.id,
        environment_id=OTHER_ENV,
        kind_code="work",
        cwd="/work/Example",
        token_hash=uuid.uuid4().hex,
        state_code=SessionState.RUNNING,
    )
    db.add(run)
    db.flush()
    return run


def _pilot_id(db: DbSession) -> uuid.UUID:
    return db.scalars(select(User.id).where(User.kind_code == UserKind.AGENT)).one()


def _update(db: DbSession, update_id: int) -> StoreUpdate:
    return db.get_one(StoreUpdate, update_id, populate_existing=True)


def _session(db: DbSession, run_id: uuid.UUID) -> models.Session:
    return db.get_one(models.Session, run_id, populate_existing=True)


def _run(updater: StoreUpdater, handle: LoopHandle | None = None) -> None:
    """The loop's run, as its loop calls it."""
    updater.run(handle or LoopHandle(STORE_UPDATE_JOB))
    clear_after_commit_callbacks()


def _asked(updater: StoreUpdater, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Each loop its supervisor is asked for from now on."""
    asked: list[str] = []
    supervisor = updater._supervisor
    start_loop = supervisor.start_loop

    def recording(
        job: str, run: Any, key: str | int | None = None, *, again: bool = False
    ) -> bool:
        asked.append(job if key is None else f"{job}:{key}")
        return start_loop(job, run, key, again=again)

    monkeypatch.setattr(supervisor, "start_loop", recording)
    return asked


def _tells(container: ServiceContainer) -> list[None]:
    """One entry for each time the conditions are told from now on."""
    told: list[None] = []
    container.condition_service().subscribe(lambda: told.append(None))
    return told


@pytest.fixture
def fake(container: ServiceContainer) -> Iterator[ServedFakeController]:
    served = ServedFakeController(keepalive_seconds=0.2)
    client_of(container, served)
    _fleet(served)
    try:
        yield served
    finally:
        served.close()


@pytest.fixture
def updater(
    container: ServiceContainer, fake: ServedFakeController, supervise: Supervise
) -> StoreUpdater:
    """The update on the test's session, its turn wait 0.1 s; no loop of its
    ever runs."""
    return _built(container, supervise, turn_wait=0.1)[0]


@pytest.fixture
def camp(session: DbSession) -> Project:
    return _project(session, _person(session), "camp")


class TestRun:
    def test_it_stops_the_stores_jobs_and_chats_by_pilot_resets_the_store_alone_and_waits_for_the_sync(
        self,
        container: ServiceContainer,
        updater: StoreUpdater,
        fake: ServedFakeController,
        session: DbSession,
        camp: Project,
    ) -> None:
        _store_row(session)
        chat = _brain(container, session, camp, "chat", SessionState.RUNNING)
        starting = _brain(container, session, camp, "job", SessionState.STARTING)
        held = _brain(container, session, camp, "job", SessionState.HELD, briefed=False)
        work = _work_item(session, camp)
        update = hold(session)

        _run(updater)

        update = _update(session, update.id)
        pilot = _pilot_id(session)
        for stopped in (_session(session, chat.id), _session(session, starting.id)):
            assert (stopped.state_code, stopped.stopped_by_user_id) == (
                SessionState.STOPPED,
                pilot,
            )
            assert stopped.stopped_at is not None
            assert update.made_at <= stopped.stopped_at
            assert update.stopped_at is not None
            assert stopped.stopped_at <= update.stopped_at
        # The chat's turn is its relay's to end; none runs here, so the wait
        # ran to its bound.
        assert _session(session, chat.id).turn_ended_at is None
        assert session.get_one(Chat, chat.id).closed_at is None
        assert _session(session, held.id).state_code == SessionState.HELD
        assert _session(session, work.id).state_code == SessionState.RUNNING
        assert update.reset_at is not None and update.stopped_at < update.reset_at
        assert (update.reconciled_at, update.lifted_at, update.error) == (
            None,
            None,
            None,
        )
        assert fake.environment(STORE_ENVIRONMENT_ID).resets == 1
        assert fake.environment(STORE_ENVIRONMENT_ID).status == "running"
        assert fake.environment(OTHER_ENV).resets == 0

    def test_a_store_never_used_has_its_row_made_from_the_controllers_report(
        self,
        updater: StoreUpdater,
        fake: ServedFakeController,
        session: DbSession,
    ) -> None:
        """No brain session has started there and its sidecar never synced:
        the reset locks the row it has made (DB 279)."""
        update = hold(session)

        _run(updater)

        assert _update(session, update.id).reset_at is not None
        row = session.get_one(Environment, STORE_ENVIRONMENT_ID)
        assert row.exempt
        assert fake.environment(STORE_ENVIRONMENT_ID).resets == 1

    def test_a_session_gone_running_since_the_stops_is_stopped_before_stopped_at(
        self,
        container: ServiceContainer,
        updater: StoreUpdater,
        fake: ServedFakeController,
        session: DbSession,
        camp: Project,
    ) -> None:
        """A start whose gate read came before the update's commit commits
        `starting` after it."""
        _store_row(session)
        _brain(container, session, camp, "chat", SessionState.RUNNING)
        update = hold(session)
        late: list[models.Session] = []

        def started_late(waits: int) -> None:
            if waits == 1:
                late.append(
                    _brain(
                        container,
                        session,
                        _project(
                            session,
                            session.get_one(User, camp.created_by_user_id),
                            "soup",
                        ),
                        "chat",
                        SessionState.STARTING,
                    )
                )

        _run(updater, RoundsHandle(STORE_UPDATE_JOB, started_late))

        (started,) = late
        stopped = _session(session, started.id)
        update = _update(session, update.id)
        assert stopped.state_code == SessionState.STOPPED
        assert stopped.stopped_at is not None and update.stopped_at is not None
        assert stopped.stopped_at <= update.stopped_at

    def test_a_lift_asked_during_the_wait_writes_no_later_phase(
        self,
        container: ServiceContainer,
        updater: StoreUpdater,
        fake: ServedFakeController,
        session: DbSession,
        camp: Project,
    ) -> None:
        _store_row(session)
        _brain(container, session, camp, "chat", SessionState.RUNNING)
        update = hold(session)

        def lift_asked(waits: int) -> None:
            container.store_update_service().request_lift()

        _run(updater, RoundsHandle(STORE_UPDATE_JOB, lift_asked))

        update = _update(session, update.id)
        assert (update.stopped_at, update.reset_at, update.reconciled_at) == (
            None,
            None,
            None,
        )
        assert update.lifted_at is not None
        assert fake.environment(STORE_ENVIRONMENT_ID).resets == 0

    def test_a_lift_asked_before_the_stop_stops_nothing(
        self,
        container: ServiceContainer,
        updater: StoreUpdater,
        fake: ServedFakeController,
        session: DbSession,
        camp: Project,
    ) -> None:
        _store_row(session)
        chat = _brain(container, session, camp, "chat", SessionState.RUNNING)
        update = hold(session)
        container.store_update_service().request_lift()

        _run(updater)

        assert _session(session, chat.id).state_code == SessionState.RUNNING
        update = _update(session, update.id)
        assert (update.stopped_at, update.reset_at) == (None, None)
        assert update.lifted_at is not None

    def test_a_reset_refused_is_the_rows_error_raised_for_the_backoff_and_cleared_at_the_next(
        self,
        updater: StoreUpdater,
        fake: ServedFakeController,
        session: DbSession,
    ) -> None:
        """A store that lost its exemption meets the node's cap (design 5's
        Risks): the controller's reason whole on the row, tried again."""
        _store_row(session)
        fake.set_exempt(STORE_ENVIRONMENT_ID, False)
        fake.capped(STORE_ENVIRONMENT_ID)
        update = hold(session)

        with pytest.raises(EnvironmentStartFailed) as raised:
            _run(updater)

        failed = _update(session, update.id)
        assert failed.error == str(raised.value)
        assert "the controller refused its reset" in failed.error
        assert failed.stopped_at is not None and failed.reset_at is None
        fake.capped(STORE_ENVIRONMENT_ID, on=False)

        _run(updater)

        reset = _update(session, update.id)
        assert reset.reset_at is not None and reset.error is None

    def test_a_reset_settled_other_than_running_is_the_rows_error(
        self,
        updater: StoreUpdater,
        fake: ServedFakeController,
        session: DbSession,
    ) -> None:
        _store_row(session)
        fake.settle_starts(STORE_ENVIRONMENT_ID, "error")
        update = hold(session)

        with pytest.raises(EnvironmentStartFailed):
            _run(updater)

        failed = _update(session, update.id)
        assert failed.error is not None and failed.error.endswith("it settled error")
        assert failed.reset_at is None

    def test_a_controller_that_does_not_answer_writes_no_error(
        self,
        updater: StoreUpdater,
        fake: ServedFakeController,
        session: DbSession,
    ) -> None:
        _store_row(session)
        update = hold(session)
        update.error = "the store's reset settled error"
        session.flush()
        fake.outage()

        with pytest.raises(ControllerUnreachable):
            _run(updater)

        waiting = _update(session, update.id)
        # The last failure was cleared at this attempt, and the outage
        # writes none.
        assert (waiting.reset_at, waiting.error) == (None, None)
        assert waiting.stopped_at is not None

    def test_it_waits_for_the_sync_writing_nothing(
        self,
        updater: StoreUpdater,
        fake: ServedFakeController,
        session: DbSession,
    ) -> None:
        update = hold(session)
        update.stopped_at = update.reset_at = datetime.now(UTC)
        session.flush()

        _run(updater)

        waiting = _update(session, update.id)
        assert (waiting.reconciled_at, waiting.lifted_at) == (None, None)
        assert fake.environment(STORE_ENVIRONMENT_ID).resets == 0

    @pytest.mark.parametrize("asked", [False, True], ids=["reconciled", "lift asked"])
    def test_the_lift_releases_the_held_starts_sends_the_nudges_and_tells_the_conditions(
        self,
        container: ServiceContainer,
        updater: StoreUpdater,
        session: DbSession,
        monkeypatch: pytest.MonkeyPatch,
        asked: bool,
    ) -> None:
        update = hold(session)
        update.stopped_at = update.reset_at = datetime.now(UTC)
        if asked:
            update.lift_requested_at = datetime.now(UTC)
        else:
            update.reconciled_at = datetime.now(UTC)
        session.flush()
        loops = _asked(updater, monkeypatch)
        told = _tells(container)

        updater.run(LoopHandle(STORE_UPDATE_JOB))

        lifted = _update(session, update.id)
        assert lifted.lifted_at is not None
        assert lifted.lifted_at >= (lifted.reconciled_at or lifted.lift_requested_at)
        assert f"{START_JOB}:{RELEASE_KEY}" in loops
        assert f"{START_JOB}:{NUDGE_KEY}" in loops
        assert told == [None]


class TestTimer:
    def test_it_tells_the_conditions_once_each_time_the_update_turns(
        self,
        container: ServiceContainer,
        updater: StoreUpdater,
        session: DbSession,
    ) -> None:
        told = _tells(container)

        updater.run_timer(session)
        assert told == []
        update = hold(session)
        updater.run_timer(session)
        updater.run_timer(session)
        assert told == [None]
        lift(session, update)
        updater.run_timer(session)
        updater.run_timer(session)
        assert told == [None, None]

    def test_it_runs_the_sequence_while_an_update_stands_not_waiting_for_the_sync(
        self,
        updater: StoreUpdater,
        session: DbSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        loops = _asked(updater, monkeypatch)

        updater.run_timer(session)
        assert loops == []
        update = hold(session)
        updater.run_timer(session)
        assert loops == [STORE_UPDATE_JOB]
        update.stopped_at = update.reset_at = datetime.now(UTC)
        session.flush()
        updater.run_timer(session)
        assert loops == [STORE_UPDATE_JOB]
        update.reconciled_at = datetime.now(UTC)
        session.flush()
        updater.run_timer(session)
        assert loops == [STORE_UPDATE_JOB, STORE_UPDATE_JOB]


class TestReconciled:
    """The sync's note of a manifest with an empty shadow (design 5 D6)."""

    def test_it_writes_reconciled_at_after_stopped_at_and_runs_the_sequence(
        self,
        updater: StoreUpdater,
        session: DbSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        update = hold(session)
        update.stopped_at = datetime.now(UTC)
        session.flush()
        loops = _asked(updater, monkeypatch)

        with scoped_session(updater._container) as db:
            updater.reconciled(db)

        reconciled = _update(session, update.id)
        assert reconciled.reconciled_at is not None
        assert reconciled.reconciled_at >= update.stopped_at
        assert loops == [STORE_UPDATE_JOB]

    def test_it_is_written_once(
        self, updater: StoreUpdater, session: DbSession
    ) -> None:
        update = hold(session)
        update.stopped_at = update.reconciled_at = datetime.now(UTC)
        session.flush()
        first = update.reconciled_at

        updater.reconciled(session)

        assert _update(session, update.id).reconciled_at == first

    @pytest.mark.parametrize(
        "standing",
        ["none", "not stopped", "lift asked", "lifted"],
    )
    def test_it_writes_nothing_without_a_stopped_update_and_no_lift_asked(
        self,
        updater: StoreUpdater,
        session: DbSession,
        standing: str,
    ) -> None:
        """Before `stopped_at` the manifest is the store's before its stop;
        after a lift asked no phase is written but `lifted_at` (DB 279)."""
        update = None if standing == "none" else hold(session)
        if update is not None:
            if standing != "not stopped":
                update.stopped_at = datetime.now(UTC)
            if standing == "lift asked":
                update.lift_requested_at = datetime.now(UTC)
            if standing == "lifted":
                lift(session, update)
            session.flush()

        updater.reconciled(session)
        clear_after_commit_callbacks()

        assert (
            session.scalar(
                select(StoreUpdate.id).where(StoreUpdate.reconciled_at.is_not(None))
            )
            is None
        )


def _committed_people(container: ServiceContainer) -> tuple[uuid.UUID, uuid.UUID]:
    """Two open projects, `camp` and `soup`, the store's row made."""
    with scoped_session(container) as db:
        person = _person(db)
        _store_row(db)
        return _project(db, person, "camp").id, _project(db, person, "soup").id


def _in_flight(
    container: ServiceContainer,
    starts: SessionStartService,
    project_id: uuid.UUID,
    kind: str,
) -> uuid.UUID:
    """A Chat's or a job's Session in the store with a turn in flight, its
    relay running."""
    name = (
        container.controller_client()
        .create_headless_session(STORE_ENVIRONMENT_ID, HeadlessCreateRequest())
        .name
    )
    with scoped_session(container) as db:
        project = db.get_one(Project, project_id)
        run = _brain(
            container,
            db,
            project,
            kind,
            SessionState.IDLE,
            controller_session=name,
            briefed=False,
        )
        run_id = run.id
        starts._relays.send(db, run_id, "Hi")
    return run_id


def _committed_update(container: ServiceContainer) -> int:
    """The update the command makes."""
    with scoped_session(container):
        return container.store_update_service().make().id


def _committed(container: ServiceContainer, update_id: int) -> StoreUpdate:
    with scoped_session(container) as db:
        update = db.get_one(StoreUpdate, update_id)
        db.expunge(update)
        return update


def _state(container: ServiceContainer, run_id: uuid.UUID) -> models.Session:
    with scoped_session(container) as db:
        run = db.get_one(models.Session, run_id)
        db.expunge(run)
        return run


def _reconciled(app: Flask, *, shadow: dict[str, str] | None = None) -> None:
    """The store's sidecar posts its manifest: a fresh one's, with an empty
    tree and shadow, unless `shadow` gives the one it kept."""
    sidecar = FakeSidecar(app.test_client())
    answer = sidecar.post_manifest(dict(shadow or {}), dict(shadow or {}))
    assert answer.status_code == 200


def _folders(fake: ServedFakeController) -> None:
    """The tree the store's sidecar writes down after its reconcile."""
    fake.put_file(STORE_ENVIRONMENT_ID, f"{STORE_REPO}/CLAUDE.md", b"# Pilot\n")
    fake.put_file(STORE_ENVIRONMENT_ID, "/work/Projects/soup/plan.json", b"{}")


def _phases(update: StoreUpdate) -> list[datetime | None]:
    return [
        update.made_at,
        update.stopped_at,
        update.reset_at,
        update.reconciled_at,
        update.lifted_at,
    ]


@pytest.fixture
def committed_fake(committed_app: Flask) -> Iterator[ServedFakeController]:
    served = ServedFakeController(keepalive_seconds=0.2)
    client_of(committed_app.container, served)
    _fleet(served)
    try:
        yield served
    finally:
        served.close()


@pytest.fixture
def updater_log() -> Iterator[LogWaiter]:
    with listening(UPDATER_LOGGER, START_LOGGER) as waiter:
        yield waiter


class TestSequence:
    def test_an_update_runs_from_its_row_to_its_lift(
        self,
        committed_app: Flask,
        committed_fake: ServedFakeController,
        supervise: Supervise,
    ) -> None:
        container = committed_app.container
        _, starts, coordinator = _built(container, supervise)
        camp_id, soup_id = _committed_people(container)
        with scoped_session(container) as db:
            work_id = _work_item(db, db.get_one(Project, camp_id)).id
        told = _tells(container)
        coordinator.fire_startup()
        chat_id = _in_flight(container, starts, camp_id, "chat")
        job_id = _in_flight(container, starts, camp_id, "job")

        update_id = _committed_update(container)
        with scoped_session(container) as db:
            # A chat started under the hold, held at the gate (DB 282).
            soup = db.get_one(Project, soup_id)
            held = _brain(container, db, soup, "chat", SessionState.STARTING)
            starts.start_brain(db, soup, held, "start the chat")
            held_id = held.id
        assert _state(container, held_id).state_code == SessionState.HELD
        wait_until(lambda: told == [None], "the conditions told of the hold")

        wait_until(
            lambda: _committed(container, update_id).stopped_at is not None,
            "the store's sessions stopped",
        )
        made = _committed(container, update_id)
        for run_id in (chat_id, job_id):
            stopped = _state(container, run_id)
            assert stopped.state_code == SessionState.STOPPED
            assert stopped.stopped_by_user_id == _pilot_of(container)
            assert stopped.stopped_at is not None
            assert made.made_at <= stopped.stopped_at
            # Its relay recorded the interrupt's result before the stop of
            # the store.
            assert stopped.turn_ended_at is not None
            assert made.stopped_at is not None
            assert stopped.turn_ended_at <= made.stopped_at
        assert _state(container, held_id).state_code == SessionState.HELD
        assert _state(container, work_id).state_code == SessionState.RUNNING

        wait_until(
            lambda: _committed(container, update_id).reset_at is not None,
            "the store reset",
        )
        assert committed_fake.environment(STORE_ENVIRONMENT_ID).resets == 1
        assert committed_fake.environment(OTHER_ENV).resets == 0
        _folders(committed_fake)
        # A sidecar that kept its shadow is the store's before its reset.
        _reconciled(committed_app, shadow={"camp/plan.json": "a" * 64})
        assert _committed(container, update_id).reconciled_at is None

        _reconciled(committed_app)

        wait_until(
            lambda: _committed(container, update_id).lifted_at is not None,
            "the hold lifted",
        )
        phases = _phases(_committed(container, update_id))
        assert None not in phases
        assert phases == sorted(phases)
        wait_until(
            lambda: _state(container, held_id).state_code == SessionState.RUNNING,
            "the held chat started",
        )
        wait_until(lambda: told == [None, None], "the conditions told of the lift")
        with scoped_session(container) as db:
            assert db.get_one(Chat, chat_id).closed_at is None
        coordinator.shutdown()

    def test_two_processes_at_once_write_each_phase_once_and_in_order(
        self,
        committed_app: Flask,
        committed_fake: ServedFakeController,
        supervise: Supervise,
        updater_log: LogWaiter,
    ) -> None:
        """A roll: the old and the new backend each run the job."""
        container = committed_app.container
        _, starts, first = _built(container, supervise)
        _, _, second = _built(container, supervise)
        camp_id, _ = _committed_people(container)
        first.fire_startup()
        second.fire_startup()
        chat_id = _in_flight(container, starts, camp_id, "chat")

        update_id = _committed_update(container)
        wait_until(
            lambda: _committed(container, update_id).reset_at is not None,
            "the store reset",
        )
        _reconciled(committed_app)
        wait_until(
            lambda: _committed(container, update_id).lifted_at is not None,
            "the hold lifted",
        )

        phases = _phases(_committed(container, update_id))
        assert phases == sorted(phases)
        assert committed_fake.environment(STORE_ENVIRONMENT_ID).resets == 1
        for written in (
            rf"The store's update {update_id}: stopped \d+ sessions",
            rf"The store's update {update_id}: reset the store {STORE_ENVIRONMENT_ID}",
            rf"The store's update {update_id}: its tree reconciled",
            rf"The store's update {update_id}: lifted",
            rf"Session {chat_id} stopped by .*",
        ):
            assert len(updater_log.matching(written)) == 1, written
        first.shutdown()
        second.shutdown()

    def test_a_second_process_waits_for_the_firsts_reset_and_resets_nothing(
        self,
        committed_app: Flask,
        committed_fake: ServedFakeController,
        supervise: Supervise,
    ) -> None:
        """The reset's turn: a second reset would stop the store the first
        one is bringing up."""
        container = committed_app.container
        _, _, first = _built(container, supervise)
        _, _, second = _built(container, supervise)
        _committed_people(container)
        committed_fake.settle_starts(STORE_ENVIRONMENT_ID, None)
        first.fire_startup()
        second.fire_startup()

        update_id = _committed_update(container)
        wait_until(
            lambda: (
                committed_fake.environment(STORE_ENVIRONMENT_ID).status == "starting"
            ),
            "one process's reset bringing the store up",
        )
        wait_until(lambda: lock_waits(container) == 1, "the other waiting its turn")
        committed_fake.set_status(STORE_ENVIRONMENT_ID, "running")

        wait_until(
            lambda: _committed(container, update_id).reset_at is not None,
            "the store reset",
        )
        wait_until(lambda: lock_waits(container) == 0, "the turn taken and left")
        assert committed_fake.environment(STORE_ENVIRONMENT_ID).resets == 1
        assert committed_fake.environment(STORE_ENVIRONMENT_ID).status == "running"
        assert _committed(container, update_id).error is None
        first.shutdown()
        second.shutdown()

    def test_a_sequence_cut_after_its_stop_resumes_at_startup_and_goes_on_at_the_syncs_commit(
        self,
        committed_app: Flask,
        committed_fake: ServedFakeController,
        supervise: Supervise,
    ) -> None:
        """A crash: the next process takes the row up at STARTUP; its tick is
        30 s, so only the manifest's commit runs the lift within the wait."""
        container = committed_app.container
        _, _, coordinator = _built(container, supervise, tick=30.0)
        _committed_people(container)
        update_id = _committed_update(container)
        stopped_at = datetime.now(UTC)
        with scoped_session(container) as db:
            db.get_one(StoreUpdate, update_id).stopped_at = stopped_at

        coordinator.fire_startup()

        wait_until(
            lambda: _committed(container, update_id).reset_at is not None,
            "the store reset",
        )
        _reconciled(committed_app)
        wait_until(
            lambda: _committed(container, update_id).lifted_at is not None,
            "the hold lifted",
        )
        assert _committed(container, update_id).stopped_at == stopped_at
        coordinator.shutdown()

    def test_an_outage_mid_way_writes_no_error_and_the_sequence_goes_on_once_it_answers(
        self,
        committed_app: Flask,
        committed_fake: ServedFakeController,
        supervise: Supervise,
    ) -> None:
        container = committed_app.container
        _, _, coordinator = _built(container, supervise)
        _committed_people(container)
        restarts = metric_value(JOB_RESTARTS_TOTAL, job=STORE_UPDATE_JOB)
        coordinator.fire_startup()
        committed_fake.outage()

        update_id = _committed_update(container)
        wait_until(
            lambda: (
                metric_value(JOB_RESTARTS_TOTAL, job=STORE_UPDATE_JOB) >= restarts + 2
            ),
            "the reset tried twice",
        )
        waiting = _committed(container, update_id)
        assert waiting.stopped_at is not None
        assert (waiting.reset_at, waiting.error) == (None, None)
        committed_fake.outage(on=False)

        wait_until(
            lambda: _committed(container, update_id).reset_at is not None,
            "the store reset",
        )
        _reconciled(committed_app)
        wait_until(
            lambda: _committed(container, update_id).lifted_at is not None,
            "the hold lifted",
        )
        coordinator.shutdown()

    def test_a_reset_settled_error_stands_as_the_rows_error_until_one_settles_running(
        self,
        committed_app: Flask,
        committed_fake: ServedFakeController,
        supervise: Supervise,
    ) -> None:
        container = committed_app.container
        _, _, coordinator = _built(container, supervise)
        _committed_people(container)
        committed_fake.settle_starts(STORE_ENVIRONMENT_ID, "error")
        coordinator.fire_startup()

        update_id = _committed_update(container)
        wait_until(
            lambda: _committed(container, update_id).error is not None,
            "the reset's failure on the row",
        )
        failed = _committed(container, update_id)
        assert failed.error is not None and failed.error.endswith("it settled error")
        assert failed.reset_at is None
        committed_fake.settle_starts(STORE_ENVIRONMENT_ID, "running")

        wait_until(
            lambda: _committed(container, update_id).reset_at is not None,
            "the store reset",
        )
        assert _committed(container, update_id).error is None
        assert committed_fake.environment(STORE_ENVIRONMENT_ID).resets >= 2
        coordinator.shutdown()

    def test_a_lift_asked_at_the_reconcile_lifts_with_no_reconcile(
        self,
        committed_app: Flask,
        committed_fake: ServedFakeController,
        supervise: Supervise,
    ) -> None:
        """No sidecar posts its manifest: the command's `--lift`."""
        container = committed_app.container
        _, _, coordinator = _built(container, supervise)
        _committed_people(container)
        ticks = metric_value(TIMER_RUNS_TOTAL, timer=STORE_UPDATE_JOB, outcome="ok")
        coordinator.fire_startup()
        update_id = _committed_update(container)
        wait_until(
            lambda: _committed(container, update_id).reset_at is not None,
            "the store reset",
        )
        wait_until(
            lambda: (
                metric_value(TIMER_RUNS_TOTAL, timer=STORE_UPDATE_JOB, outcome="ok")
                >= ticks + 5
            ),
            "five ticks",
        )
        assert _committed(container, update_id).lifted_at is None

        with scoped_session(container):
            container.store_update_service().request_lift()

        wait_until(
            lambda: _committed(container, update_id).lifted_at is not None,
            "the hold lifted",
        )
        assert _committed(container, update_id).reconciled_at is None
        coordinator.shutdown()


def _pilot_of(container: ServiceContainer) -> uuid.UUID:
    with scoped_session(container) as db:
        return _pilot_id(db)
