"""Environments on demand, Pilot's own created, taken, named and deleted, and
the shutdown and delete timers (design 2 §13.2, §13.3, §13.5; F88.1, F73.1,
F143.1, F143.3; DB 239, 240, 242; slice 020's refinement D1).

The rules that protect the most: an environment Pilot did not start is never
stopped, nor one running a pod other than the one Pilot's start brought up, nor
an exempt one, nor one where a Session runs or starts (`TestShutdownTimer`,
`test_..._is_never_stopped`); an environment Pilot did not create is never
taken, renamed or deleted, nor one a Session holds, a stopped or failed work
item's among them (`TestTake`, `TestDeleteTimer`)."""

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flask import Flask
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session
from werkzeug.wrappers import Request, Response

from app.core_exceptions import ExternalServiceException
from app.database import scoped_session
from app.models import Document, Environment, Item, Project, User
from app.models import Session as AgentSession
from app.models.reference import SessionState, UserKind
from app.services import environment_service
from app.services.container import ServiceContainer
from app.services.controller_client import (
    ControllerClient,
    ControllerProblem,
    ControllerProblemType,
    ControllerUnreachable,
    EnvironmentStatus,
)
from app.services.environment_service import (
    DELETE_TIMER,
    GONE,
    SHUTDOWN_TIMER,
    EnvironmentService,
    EnvironmentStartFailed,
)
from app.services.fake_controller import CLIENT_NAME, FakeController
from tests.support.fake_controller import ServedFakeController, client_of
from tests.support.locks import Outcome, in_thread, lock_waits
from tests.support.supervisor import Supervise, listening, wait_until

STOP_AFTER = timedelta(minutes=30)
DELETE_AFTER = timedelta(days=7)
ENV = "env-a"
WAIT = "?wait=settled&waitMs=3600000"


@pytest.fixture
def environments(
    container: ServiceContainer,
    controller_client: ControllerClient,
    supervise: Supervise,
) -> EnvironmentService:
    supervisor, _ = supervise(container)
    return EnvironmentService(
        container=container,
        supervisor=supervisor,
        stop_after_seconds=STOP_AFTER.total_seconds(),
        delete_after_seconds=DELETE_AFTER.total_seconds(),
    )


def _row(db: Session, env_id: str = ENV) -> Environment | None:
    return db.scalars(
        select(Environment)
        .where(Environment.id == env_id)
        .execution_options(populate_existing=True)
    ).one_or_none()


def _environment(
    db: Session,
    env_id: str = ENV,
    *,
    started: bool = True,
    pod: datetime | None = None,
    due: datetime | None = None,
    exempt: bool = False,
) -> Environment:
    """An environment's row; `started` as Pilot's own start leaves it, its
    claim on the pod that started at `pod`."""
    row = Environment(
        id=env_id,
        name=env_id.title(),
        exempt=exempt,
        last_state="running",
        server_started_at=datetime.now(UTC) - timedelta(hours=1) if started else None,
        started_pod_at=pod,
        stop_due_at=due,
    )
    db.add(row)
    db.flush()
    return row


def _agent_session(
    db: Session, project: Project, state: SessionState, env_id: str = ENV
) -> AgentSession:
    run = AgentSession(
        project_id=project.id,
        environment_id=env_id,
        kind_code="work",
        cwd="/work/Example",
        token_hash=uuid.uuid4().hex,
        state_code=state,
    )
    db.add(run)
    db.flush()
    return run


def _overdue() -> datetime:
    return datetime.now(UTC) - timedelta(minutes=1)


def _armed_around(row: Environment | None, before: datetime) -> bool:
    assert row is not None and row.stop_due_at is not None
    return before + STOP_AFTER <= row.stop_due_at <= datetime.now(UTC) + STOP_AFTER


def _stops(fake: FakeController, env_id: str = ENV) -> list[str]:
    return [call for call in fake.calls if call == f"POST /environments/{env_id}/stop"]


def _pod(fake: FakeController, env_id: str = ENV) -> datetime:
    """The `startedAt` of the environment's pod at the fake."""
    started_at = fake.environment(env_id).pod_started_at
    assert started_at is not None
    return started_at


def _claim(row: Environment | None) -> tuple[Any, Any, Any]:
    assert row is not None
    return (row.server_started_at, row.started_pod_at, row.stop_due_at)


_NO_CLAIM = (None, None, None)


class TestEnsureEnvironment:
    def test_the_first_touch_makes_the_row_from_the_controllers_report(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        fake_controller.add_environment(
            ENV, name="Alpha", status="running", exempt=True
        )
        before = datetime.now(UTC)

        environments.ensure_environment(session, ENV)

        row = _row(session)
        assert row is not None
        assert (row.name, row.last_state, row.exempt) == ("Alpha", "running", True)
        assert row.last_seen_at is not None and row.last_seen_at >= before
        assert row.server_started_at is None
        assert row.stop_due_at is None

    def test_an_unnamed_environment_is_named_by_its_id(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        fake_controller.add_environment(ENV)

        environments.ensure_environment(session, ENV)

        row = _row(session)
        assert row is not None and row.name == ENV

    def test_a_row_pilot_has_is_left_as_it_is(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        _environment(session, started=False)
        fake_controller.add_environment(ENV, name="Renamed", status="stopped")

        environments.ensure_environment(session, ENV)

        row = _row(session)
        assert row is not None and (row.name, row.last_state) == ("Env-A", "running")
        assert fake_controller.calls == []

    def test_the_row_is_the_callers_to_commit(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        fake_controller.add_environment(ENV)

        environments.ensure_environment(session, ENV)
        session.rollback()

        assert _row(session) is None

    def test_an_environment_the_controller_lacks_is_not_found(
        self, environments: EnvironmentService, session: Session
    ) -> None:
        with pytest.raises(ControllerProblem) as raised:
            environments.ensure_environment(session, ENV)

        assert raised.value.problem_type is ControllerProblemType.NOT_FOUND
        assert _row(session) is None


REPO = "example/Example"


class TestCreate:
    """An environment of Pilot's own (§13.5; F143.1)."""

    def test_it_is_managed_by_pilots_client_named_the_slug(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
    ) -> None:
        created = environments.create(REPO, "camp")

        assert (created.status, created.name, created.repo, created.managed_by) == (
            "provisioning",
            "camp",
            REPO,
            CLIENT_NAME,
        )
        assert fake_controller.environment(created.env_id).managed_by == CLIENT_NAME
        assert fake_controller.calls == ["POST /environments"]

    def test_a_name_the_fleet_holds_takes_the_first_free_suffix(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
    ) -> None:
        fake_controller.add_environment("operators-env", name="camp")
        fake_controller.add_environment("second-env", name="Camp-2")

        created = environments.create(REPO, "camp")

        assert created.name == "camp-3"
        assert fake_controller.calls == ["POST /environments"] * 3

    def test_with_no_slug_it_is_unnamed(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
    ) -> None:
        fake_controller.add_environment("operators-env", name="camp")

        created = environments.create(REPO, None)

        assert created.name is None

    @pytest.mark.parametrize(
        ("refusal", "repo", "problem_type"),
        [
            ("capped", REPO, ControllerProblemType.ADMISSION_BLOCKED),
            (
                "not-whitelisted",
                REPO,
                ControllerProblemType.NAMESPACE_NOT_WHITELISTED,
            ),
            ("invalid", "no-owner", ControllerProblemType.VALIDATION_ERROR),
        ],
    )
    def test_a_refusal_is_the_controllers_problem_unretried(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        refusal: str,
        repo: str,
        problem_type: ControllerProblemType,
    ) -> None:
        if refusal == "capped":
            fake_controller.capped()
        elif refusal == "not-whitelisted":
            fake_controller.not_whitelisted("example")

        with pytest.raises(ControllerProblem) as raised:
            environments.create(repo, "camp")

        assert raised.value.problem_type is problem_type
        assert fake_controller.calls == ["POST /environments"]


class TestRecordCreated:
    def test_the_row_is_pilots_own_its_claim_the_creates(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        created = environments.create(REPO, "camp")
        before = datetime.now(UTC)

        environments.record_created(session, created, REPO)

        row = _row(session, created.env_id)
        assert row is not None
        assert (row.name, row.repo, row.exempt, row.last_state) == (
            "camp",
            REPO,
            False,
            "provisioning",
        )
        assert row.server_created_at is not None and row.server_created_at >= before
        assert row.server_started_at == row.server_created_at
        assert (row.started_pod_at, row.stop_due_at, row.delete_due_at) == (
            None,
            None,
            None,
        )

    def test_the_row_is_the_callers_to_commit(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        created = environments.create(REPO, "camp")

        environments.record_created(session, created, REPO)
        session.rollback()

        assert _row(session, created.env_id) is None


class TestSettle:
    def test_a_created_environment_settled_running_takes_its_pod_as_the_claims(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        created = environments.create(REPO, "camp")
        environments.record_created(session, created, REPO)

        settled = environments.settle(created.env_id)

        assert settled.status == "running"
        row = _row(session, created.env_id)
        assert row is not None
        assert row.started_pod_at == _pod(fake_controller, created.env_id)
        # Nothing runs or starts there: the timer covers it.
        assert _armed_around(row, row.server_created_at or datetime.now(UTC))
        (wait,) = fake_controller.calls[1:]
        assert wait.startswith(f"GET /environments/{created.env_id}?wait=settled")

    @pytest.mark.parametrize("elsewhere", ["stopped-and-started", "recreated"])
    def test_one_of_pilots_own_settled_on_another_pod_keeps_its_claim_on_it(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
        elsewhere: str,
    ) -> None:
        # Close-out B1: every pod of Pilot's own is Pilot's (§13.5), one
        # KubeCoder replaced among them.
        created = environments.create(REPO, "camp")
        environments.record_created(session, created, REPO)
        environments.settle(created.env_id)
        started, old, _ = _claim(_row(session, created.env_id))
        if elsewhere == "recreated":
            fake_controller.recreate_pod(created.env_id)
        else:
            fake_controller.set_status(created.env_id, "stopped")
        fake_controller.set_status(created.env_id, "running")

        environments.settle(created.env_id)

        pod = _pod(fake_controller, created.env_id)
        assert pod != old
        assert _claim(_row(session, created.env_id))[:2] == (started, pod)

    @pytest.mark.parametrize("status", ["error", "stopped"])
    def test_a_bring_up_that_settles_other_than_running_is_the_starts_failure(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
        status: str,
    ) -> None:
        fake_controller.settle_creates(status)
        created = environments.create(REPO, "camp")
        environments.record_created(session, created, REPO)

        with pytest.raises(EnvironmentStartFailed, match=f"it settled {status}"):
            environments.settle(created.env_id)


class TestStopUntaken:
    def test_it_is_stopped_at_once_its_claim_ended(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        created = environments.create(REPO, "camp")
        environments.record_created(session, created, REPO)

        environments.stop_untaken(created.env_id)

        assert fake_controller.environment(created.env_id).status == "stopped"
        row = _row(session, created.env_id)
        assert _claim(row) == _NO_CLAIM
        assert row is not None and row.server_created_at is not None

    def test_one_whose_stop_went_unanswered_the_timer_stops(
        self,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        session: Session,
    ) -> None:
        # Review r1, F1: its claim has no pod, and no start waits there.
        service = _service(container, supervise, stop_after=timedelta(0))
        created = service.create(REPO, "camp")
        service.record_created(session, created, REPO)
        session.commit()
        fake_controller.outage()
        with pytest.raises(ControllerUnreachable):
            service.stop_untaken(created.env_id)
        fake_controller.outage(on=False)

        service.run_shutdown_timer(session)  # armed
        service.run_shutdown_timer(session)

        assert fake_controller.environment(created.env_id).status == "stopped"
        assert _claim(_row(session, created.env_id)) == _NO_CLAIM

    def test_one_another_start_took_first_is_left_to_it(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
        project: Project,
    ) -> None:
        created = environments.create(REPO, "camp")
        environments.record_created(session, created, REPO)
        _agent_session(session, project, SessionState.STARTING, created.env_id)

        environments.stop_untaken(created.env_id)

        assert fake_controller.environment(created.env_id).status == "running"
        assert fake_controller.calls == ["POST /environments"]
        row = _row(session, created.env_id)
        assert row is not None and row.server_started_at is not None


def _own(
    db: Session,
    env_id: str = ENV,
    *,
    state: str = "stopped",
    repo: str = REPO,
    claimed: bool = False,
    delete_due: datetime | None = None,
) -> Environment:
    """The row of an environment of Pilot's own made from `repo`, as the fleet
    reports it `state`; `claimed` as Pilot's own bring-up left it."""
    now = datetime.now(UTC)
    row = Environment(
        id=env_id,
        name=env_id,
        exempt=False,
        last_state=state,
        server_created_at=now - timedelta(days=1),
        repo=repo,
        server_started_at=now - timedelta(hours=1) if claimed else None,
        delete_due_at=delete_due,
    )
    db.add(row)
    db.flush()
    return row


def _registered(
    db: Session,
    container: ServiceContainer,
    project: Project,
    run: AgentSession,
    read: str,
) -> Item:
    """A document `run` registered in its environment: `awaiting` its read,
    its read `published`, or its read `failed` (ruling D1)."""
    documents = container.document_service()
    item = documents.register(project, run, "/work/Example/notes.md").item
    document = db.get_one(Document, item.id)
    if read == "published":
        documents.publish_read(document, "# Notes\n\nThe lake.\n", run.id)
    elif read == "failed":
        documents.fail_read(document)
    return item


_READS = ["awaiting", "published", "failed"]


def _taken(service: EnvironmentService, db: Session) -> str | None:
    taken = service.take(db, REPO)
    return None if taken is None else taken.id


class TestTake:
    """A free environment of Pilot's own taken for a start (§13.5; DB 240;
    refinement D1; V18)."""

    def test_a_free_one_of_the_repository_is_taken_its_claim_and_deadline_cleared(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        now = datetime.now(UTC)
        row = _own(session, state="running", claimed=True, delete_due=now)
        row.started_pod_at = now - timedelta(hours=1)
        row.stop_due_at = now + STOP_AFTER
        session.flush()

        assert _taken(environments, session) == ENV

        row = _row(session)
        assert _claim(row) == _NO_CLAIM
        assert row is not None and row.delete_due_at is None
        assert fake_controller.calls == []

    def test_the_take_is_the_callers_to_commit(
        self, environments: EnvironmentService, session: Session
    ) -> None:
        due = datetime.now(UTC) + DELETE_AFTER
        _own(session, delete_due=due)
        session.commit()

        environments.take(session, REPO)
        session.rollback()

        row = _row(session)
        assert row is not None and row.delete_due_at == due

    def test_the_most_recently_freed_is_taken(
        self, environments: EnvironmentService, session: Session
    ) -> None:
        now = datetime.now(UTC)
        _own(session, "env-older", delete_due=now + timedelta(days=1))
        _own(session, "env-recent", delete_due=now + timedelta(days=6))
        _own(session, "env-oldest", delete_due=now)

        assert _taken(environments, session) == "env-recent"

    def test_one_freed_since_the_last_tick_is_the_most_recently_freed(
        self, environments: EnvironmentService, session: Session
    ) -> None:
        _own(session, "env-armed", delete_due=datetime.now(UTC) + DELETE_AFTER)
        _own(session, "env-just-freed")

        assert _taken(environments, session) == "env-just-freed"

    @pytest.mark.parametrize(
        ("state", "claimed"),
        [("stopped", False), ("stopping", False), ("running", True)],
    )
    def test_one_stopped_stopping_or_running_under_pilots_claim_is_taken(
        self,
        environments: EnvironmentService,
        session: Session,
        state: str,
        claimed: bool,
    ) -> None:
        _own(session, state=state, claimed=claimed)

        assert _taken(environments, session) == ENV

    @pytest.mark.parametrize(
        ("state", "claimed"),
        [
            ("error", False),
            ("provisioning", True),
            ("starting", True),
            ("running", False),
            ("deleting", False),
            (GONE, False),
        ],
        ids=[
            "error",
            "provisioning",
            "starting",
            "running-outside-the-claim",
            "deleting",
            "gone",
        ],
    )
    def test_one_in_error_coming_up_running_outside_the_claim_or_leaving_is_passed_over(
        self,
        environments: EnvironmentService,
        session: Session,
        state: str,
        claimed: bool,
    ) -> None:
        _own(session, state=state, claimed=claimed)

        assert _taken(environments, session) is None

    @pytest.mark.parametrize(
        "state",
        [
            SessionState.RUNNING,
            SessionState.STARTING,
            SessionState.HELD,
            SessionState.STOPPED,
            SessionState.FAILED,
        ],
    )
    def test_one_a_session_holds_is_never_taken(
        self,
        environments: EnvironmentService,
        session: Session,
        project: Project,
        state: SessionState,
    ) -> None:
        # A stopped or failed work item may resume there (refinement D1).
        _own(session)
        _agent_session(session, project, state)

        assert _taken(environments, session) is None

    @pytest.mark.parametrize("state", [SessionState.IDLE, SessionState.ENDED])
    def test_one_whose_sessions_are_done_is_free(
        self,
        environments: EnvironmentService,
        session: Session,
        project: Project,
        state: SessionState,
    ) -> None:
        _own(session)
        _agent_session(session, project, state)

        assert _taken(environments, session) == ENV

    @pytest.mark.parametrize("read", _READS)
    def test_one_where_a_document_a_run_registered_is_open_is_never_taken(
        self,
        environments: EnvironmentService,
        session: Session,
        container: ServiceContainer,
        project: Project,
        read: str,
    ) -> None:
        # Its conversation goes on there once each is closed (DB 240, §13.5).
        _own(session)
        run = _agent_session(session, project, SessionState.IDLE)
        _registered(session, container, project, run, read)

        assert _taken(environments, session) is None

    def test_one_whose_registered_documents_are_closed_is_free(
        self,
        environments: EnvironmentService,
        session: Session,
        container: ServiceContainer,
        project: Project,
        person: User,
    ) -> None:
        _own(session)
        run = _agent_session(session, project, SessionState.IDLE)
        item = _registered(session, container, project, run, "failed")
        container.record_service().reviewed(item, person)

        assert _taken(environments, session) == ENV

    def test_finishs_close_of_the_open_documents_frees_it(
        self,
        environments: EnvironmentService,
        session: Session,
        container: ServiceContainer,
        project: Project,
        person: User,
    ) -> None:
        # Review 4: no document of the run open and no resume to come.
        _own(session)
        run = _agent_session(session, project, SessionState.IDLE)
        _registered(session, container, project, run, "awaiting")
        _registered(session, container, project, run, "published")
        container.record_service().close_unanswered(project, person, datetime.now(UTC))

        assert _taken(environments, session) == ENV

    def test_a_document_registered_elsewhere_binds_it_not(
        self,
        environments: EnvironmentService,
        session: Session,
        container: ServiceContainer,
        project: Project,
    ) -> None:
        _own(session)
        _own(session, "env-b", repo="example/Other")
        run = _agent_session(session, project, SessionState.IDLE, "env-b")
        _registered(session, container, project, run, "awaiting")

        assert _taken(environments, session) == ENV

    def test_another_repositorys_is_never_taken(
        self, environments: EnvironmentService, session: Session
    ) -> None:
        _own(session, repo="example/Other")

        assert _taken(environments, session) is None

    def test_an_environment_pilot_did_not_create_is_never_taken(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
        project: Project,
    ) -> None:
        # An operator's of the repository, the store, and one a work item placed
        # by id before slice 020 ran in, its turn ended.
        for env_id, exempt in (
            ("env-operators", False),
            ("env-store", True),
            ("env-placed-by-id", False),
        ):
            row = _environment(session, env_id, started=False, exempt=exempt)
            row.last_state = "stopped"
        _agent_session(session, project, SessionState.IDLE, "env-placed-by-id")
        session.flush()

        assert _taken(environments, session) is None
        assert fake_controller.calls == []

    def test_a_row_another_transaction_holds_is_skipped(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        container = committed_app.container
        service = _service(container, supervise)
        with scoped_session(container) as db:
            _own(db, "env-held", delete_due=datetime.now(UTC) + DELETE_AFTER)
            _own(db, "env-next", delete_due=datetime.now(UTC))
        holder = container.session_maker()()
        try:
            holder.execute(
                text("SELECT 1 FROM environments WHERE id = 'env-held' FOR UPDATE")
            )
            with scoped_session(container) as db:
                assert _taken(service, db) == "env-next"
        finally:
            holder.close()

    def test_two_starts_never_take_one(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        container = committed_app.container
        service = _service(container, supervise)
        with scoped_session(container) as db:
            _own(db)
            project_id = _project(db).id
        first = container.session_maker()()
        try:
            # The first start's take, its Session there, not yet committed.
            assert _taken(service, first) == ENV
            run = _agent_session(
                first, first.get_one(Project, project_id), SessionState.STARTING
            )
            with scoped_session(container) as db:
                assert _taken(service, db) is None
            first.commit()
            with scoped_session(container) as db:
                assert _taken(service, db) is None
                assert db.get_one(AgentSession, run.id).environment_id == ENV
        finally:
            first.close()

    def test_a_take_committed_between_the_read_and_the_lock_is_seen(
        self,
        committed_app: Flask,
        supervise: Supervise,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The later start read its candidates before the earlier's take
        # committed, and locks the row once it has: unlocked by then.
        container = committed_app.container
        service = _service(container, supervise)
        with scoped_session(container) as db:
            _own(db)
            project_id = _project(db).id
        earlier: list[uuid.UUID] = []
        _before_the_next_lock(
            monkeypatch,
            lambda: earlier.append(_take_and_start(container, service, project_id)),
        )

        with scoped_session(container) as db:
            assert _taken(service, db) is None

        assert len(earlier) == 1
        with scoped_session(container) as db:
            assert db.get_one(AgentSession, earlier[0]).environment_id == ENV


class TestName:
    """The name, the taking Project's slug at every take (§13.5; V17)."""

    def test_it_is_renamed_the_slug_and_its_row_named_so(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        fake_controller.add_environment(ENV)
        _own(session)
        session.commit()

        assert environments.name(ENV, "camp") == "camp"

        assert fake_controller.environment(ENV).name == "camp"
        row = _row(session)
        assert row is not None and row.name == "camp"
        assert fake_controller.calls == [f"POST /environments/{ENV}/rename"]

    def test_a_name_the_fleet_holds_takes_the_first_free_suffix(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        fake_controller.add_environment(ENV, name="dune")
        fake_controller.add_environment("operators-env", name="camp")
        _own(session)
        session.commit()

        assert environments.name(ENV, "camp") == "camp-2"

        assert fake_controller.environment(ENV).name == "camp-2"

    def test_the_name_it_has_is_its_own(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        fake_controller.add_environment(ENV, name="camp")
        _own(session)
        session.commit()

        assert environments.name(ENV, "camp") == "camp"

    def test_with_no_slug_its_name_is_cleared(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        # A draft's take: it has no slug.
        fake_controller.add_environment(ENV, name="camp")
        _own(session)
        session.commit()

        assert environments.name(ENV, None) == ENV

        assert fake_controller.environment(ENV).name is None

    @pytest.mark.parametrize(
        ("gone", "problem_type"),
        [
            (False, ControllerProblemType.CONFLICT),
            (True, ControllerProblemType.NOT_FOUND),
        ],
        ids=["deleting", "gone"],
    )
    def test_a_refusal_is_the_controllers_problem(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
        gone: bool,
        problem_type: ControllerProblemType,
    ) -> None:
        if not gone:
            fake_controller.add_environment(ENV, status="deleting")
        _own(session)
        session.commit()

        with pytest.raises(ControllerProblem) as raised:
            environments.name(ENV, "camp")

        assert raised.value.problem_type is problem_type


class TestStart:
    def test_a_start_answered_202_marks_the_environment_pilots(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        fake_controller.add_environment(ENV, status="stopped")
        before = datetime.now(UTC)

        settled = environments.start(ENV)

        assert settled.status == "running"
        row = _row(session)
        assert row is not None and row.server_started_at is not None
        assert row.server_started_at >= before
        assert row.started_pod_at == _pod(fake_controller)
        assert settled.pod is not None
        assert settled.pod.started_at == row.started_pod_at
        assert fake_controller.calls == [
            f"GET /environments/{ENV}",
            f"POST /environments/{ENV}/start",
            f"GET /environments/{ENV}?wait=settled&waitMs=3600000",
        ]

    def test_a_start_answered_200_marks_nothing(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        fake_controller.add_environment(ENV, status="running")

        settled = environments.start(ENV)

        assert settled.status == "running"
        assert _claim(_row(session)) == _NO_CLAIM

    def test_a_200_over_a_claim_on_its_pod_keeps_it(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        fake_controller.add_environment(ENV, status="stopped")
        environments.start(ENV)
        claim = _claim(_row(session))[:2]

        environments.start(ENV)  # answered 200: Pilot's bring-up runs

        assert _claim(_row(session))[:2] == claim
        assert _claim(_row(session))[1] is not None

    def test_a_200_over_a_claim_on_another_pod_ends_it(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        # 007's close-out D2: Pilot's 202, someone's stop and start, Pilot's 200.
        fake_controller.add_environment(ENV, status="stopped")
        environments.start(ENV)
        fake_controller.set_status(ENV, "stopped")
        fake_controller.set_status(ENV, "running")

        environments.start(ENV)

        assert _claim(_row(session)) == _NO_CLAIM

    def test_a_200_over_a_claim_with_no_pod_yet_takes_the_pod(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        # Review O1: the rows a start cut between its 202 and its settle leaves;
        # its bring-up went on meanwhile.
        fake_controller.add_environment(ENV, status="running")
        started = _environment(session).server_started_at
        before = datetime.now(UTC)

        environments.start(ENV)

        row = _row(session)
        assert _claim(row)[:2] == (started, _pod(fake_controller))
        assert _armed_around(row, before)

    def test_a_202_over_an_ended_bring_up_claims_the_new_pod(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        fake_controller.add_environment(ENV, status="stopped")
        environments.start(ENV)
        old = _claim(_row(session))
        fake_controller.set_status(ENV, "stopped")

        environments.start(ENV)

        row = _row(session)
        assert row is not None and row.server_started_at is not None
        assert row.server_started_at > old[0]
        assert row.started_pod_at == _pod(fake_controller) != old[1]

    def test_a_start_that_settles_with_nothing_there_arms_the_timer(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        fake_controller.add_environment(ENV, status="stopped")
        before = datetime.now(UTC)

        environments.start(ENV)

        assert _armed_around(_row(session), before)

    def test_a_start_for_a_session_starting_there_arms_nothing(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
        project: Project,
    ) -> None:
        fake_controller.add_environment(ENV, status="stopped")
        environments.ensure_environment(session, ENV)
        _agent_session(session, project, SessionState.STARTING)

        environments.start(ENV)

        row = _row(session)
        assert row is not None and row.server_started_at is not None
        assert row.stop_due_at is None

    def test_admission_blocked_is_the_starts_failure(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        fake_controller.add_environment(ENV, status="stopped")
        fake_controller.capped(ENV)

        with pytest.raises(EnvironmentStartFailed, match="refused it") as raised:
            environments.start(ENV)

        assert raised.value.env_id == ENV
        assert isinstance(raised.value.__cause__, ControllerProblem)
        row = _row(session)
        assert row is not None and row.server_started_at is None
        assert fake_controller.calls[-1] == f"POST /environments/{ENV}/start"

    @pytest.mark.parametrize("settles", ["error", "stopped"])
    def test_a_wait_that_ends_on_error_or_stopped_is_the_starts_failure(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
        settles: Any,
    ) -> None:
        fake_controller.add_environment(ENV, status="stopped")
        fake_controller.settle_starts(ENV, settles)

        with pytest.raises(EnvironmentStartFailed, match=f"it settled {settles}"):
            environments.start(ENV)

    def test_a_start_settled_error_keeps_its_claim_on_its_pod(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        fake_controller.add_environment(ENV, status="stopped")
        fake_controller.settle_starts(ENV, "error")
        before = datetime.now(UTC)

        with pytest.raises(EnvironmentStartFailed):
            environments.start(ENV)

        # Pilot's bring-up is there: the timer is armed so that it is stopped.
        row = _row(session)
        assert _claim(row)[1] == _pod(fake_controller)
        assert _armed_around(row, before)

    def test_a_start_settled_stopped_ends_its_claim(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        fake_controller.add_environment(ENV, status="stopped")
        fake_controller.settle_starts(ENV, "stopped")

        with pytest.raises(EnvironmentStartFailed):
            environments.start(ENV)

        assert _claim(_row(session)) == _NO_CLAIM

    def test_another_conflict_is_the_controllers_problem(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
    ) -> None:
        fake_controller.add_environment(ENV, status="deleting")

        with pytest.raises(ControllerProblem) as raised:
            environments.start(ENV)

        assert not isinstance(raised.value, EnvironmentStartFailed)
        assert raised.value.problem_type is ControllerProblemType.CONFLICT

    def test_the_mark_commits_before_the_wait(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
    ) -> None:
        container = committed_app.container
        service = _service(container, supervise)
        fake_controller.add_environment(ENV, status="stopped")
        fake_controller.settle_starts(ENV, None)

        outcome = in_thread(lambda: service.start(ENV))
        wait_until(
            lambda: _committed(container, "server_started_at") is not None,
            "marked Pilot's",
        )
        assert outcome.thread.is_alive()
        fake_controller.set_status(ENV, "running")

        assert outcome.result().status == "running"

    def test_a_wait_that_runs_out_is_a_failure_of_the_controller(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
    ) -> None:
        container = committed_app.container
        service = _service(container, supervise)
        fake_controller.add_environment(ENV, status="stopped")
        fake_controller.settle_starts(ENV, None)

        outcome = in_thread(lambda: service.start(ENV))
        wait_until(
            lambda: any("wait=settled" in call for call in fake_controller.calls),
            "waiting",
        )
        # Ends the held wait with the environment still starting, as its time
        # running out does; the server keeps serving.
        FakeController.close(fake_controller)

        with pytest.raises(ExternalServiceException) as raised:
            outcome.result()
        assert not isinstance(raised.value, EnvironmentStartFailed)
        assert "still starting when the wait ran out" in str(raised.value)


class TestReset:
    """An environment brought up in a tree made anew, for a start on a new
    conversation in one Pilot took (§13.5; review B1, B3; V02, V05, V19)."""

    def test_a_stopped_one_is_reset_its_202_taking_the_claim(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        _own(session)
        fake_controller.add_environment(ENV, status="stopped")
        before = datetime.now(UTC)

        settled = environments.reset(ENV)

        assert settled.status == "running"
        assert fake_controller.environment(ENV).resets == 1
        # Its stop answers that it is stopped, so no wait follows; and a reset
        # ends in a running pod, so no start does.
        assert fake_controller.calls == [
            f"POST /environments/{ENV}/stop",
            f"POST /environments/{ENV}/reset",
            f"GET /environments/{ENV}{WAIT}",
        ]
        row = _row(session)
        assert row is not None and row.server_started_at is not None
        assert row.server_started_at >= before
        assert row.started_pod_at == _pod(fake_controller)
        # Nothing runs or starts there: the timer covers it.
        assert _armed_around(row, before)

    @pytest.mark.parametrize("state", ["running", "error", "provisioning"])
    def test_one_not_stopped_is_stopped_and_its_settled_stop_awaited_first(
        self,
        container: ServiceContainer,
        controller_client: ControllerClient,
        supervise: Supervise,
        session: Session,
        state: EnvironmentStatus,
    ) -> None:
        # The fake's stop leaves it `stopping` until the wait, and its reset
        # refuses one not `stopped`, as KubeCoder's does.
        fake = _SlowStop()
        try:
            client_of(container, fake)
            service = _service(container, supervise)
            _own(session, state=state)
            fake.add_environment(ENV, status=state)

            settled = service.reset(ENV)
        finally:
            fake.close()

        assert settled.status == "running"
        assert fake.environment(ENV).resets == 1
        assert fake.calls == [
            f"POST /environments/{ENV}/stop",
            f"GET /environments/{ENV}{WAIT}",
            f"POST /environments/{ENV}/reset",
            f"GET /environments/{ENV}{WAIT}",
        ]

    @pytest.mark.parametrize("settles", ["running", "error"])
    def test_a_stop_that_settles_other_than_stopped_is_the_starts_failure(
        self,
        container: ServiceContainer,
        controller_client: ControllerClient,
        supervise: Supervise,
        session: Session,
        settles: EnvironmentStatus,
    ) -> None:
        fake = _SlowStop(stop_settles_to=settles)
        try:
            client_of(container, fake)
            service = _service(container, supervise)
            _own(session, state="running")
            fake.add_environment(ENV, status="running")

            with pytest.raises(
                EnvironmentStartFailed, match=f"it settled {settles} after its stop"
            ):
                service.reset(ENV)
        finally:
            fake.close()

        assert fake.environment(ENV).resets == 0
        assert f"POST /environments/{ENV}/reset" not in fake.calls
        assert _claim(_row(session)) == _NO_CLAIM

    def test_a_wait_for_its_stop_that_runs_out_is_a_failure_of_the_controller(
        self,
        container: ServiceContainer,
        controller_client: ControllerClient,
        supervise: Supervise,
        session: Session,
    ) -> None:
        fake = _SlowStop(stop_settles_to="stopping")
        try:
            client_of(container, fake)
            service = _service(container, supervise)
            _own(session, state="running")
            fake.add_environment(ENV, status="running")

            with pytest.raises(ExternalServiceException) as raised:
                service.reset(ENV)
        finally:
            fake.close()

        assert not isinstance(raised.value, EnvironmentStartFailed)
        assert "still stopping when the wait for its stop ran out" in str(raised.value)
        assert f"POST /environments/{ENV}/reset" not in fake.calls

    def test_admission_blocked_is_the_starts_failure(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        _own(session)
        fake_controller.add_environment(ENV, status="stopped")
        fake_controller.capped(ENV)

        with pytest.raises(EnvironmentStartFailed, match="refused its reset") as raised:
            environments.reset(ENV)

        assert raised.value.env_id == ENV
        assert isinstance(raised.value.__cause__, ControllerProblem)
        assert fake_controller.environment(ENV).resets == 0
        assert _claim(_row(session)) == _NO_CLAIM
        assert fake_controller.calls[-1] == f"POST /environments/{ENV}/reset"

    def test_a_stop_refused_otherwise_is_the_controllers_problem(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        _own(session, state="deleting")
        fake_controller.add_environment(ENV, status="deleting")

        with pytest.raises(ControllerProblem) as raised:
            environments.reset(ENV)

        assert not isinstance(raised.value, EnvironmentStartFailed)
        assert raised.value.problem_type is ControllerProblemType.CONFLICT
        assert fake_controller.calls == [f"POST /environments/{ENV}/stop"]

    @pytest.mark.parametrize("settles", ["error", "stopped"])
    def test_a_reset_that_settles_other_than_running_is_the_starts_failure(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
        settles: EnvironmentStatus,
    ) -> None:
        _own(session)
        fake_controller.add_environment(ENV, status="stopped")
        fake_controller.settle_starts(ENV, settles)

        with pytest.raises(EnvironmentStartFailed, match=f"it settled {settles}"):
            environments.reset(ENV)

        assert fake_controller.environment(ENV).resets == 1

    def test_its_claim_commits_before_the_wait(
        self,
        committed_app: Flask,
        committed_controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
    ) -> None:
        # Review B3: a start cut in the wait reads the reset as made.
        container = committed_app.container
        service = _service(container, supervise)
        with scoped_session(container) as db:
            _own(db)
        fake_controller.add_environment(ENV, status="stopped")
        fake_controller.settle_starts(ENV, None)

        outcome = in_thread(lambda: service.reset(ENV))
        wait_until(
            lambda: _committed(container, "server_started_at") is not None,
            "claimed",
        )
        assert outcome.thread.is_alive()
        assert _committed(container, "started_pod_at") is None
        fake_controller.set_status(ENV, "running")

        assert outcome.result().status == "running"
        assert _committed(container, "started_pod_at") == _pod(fake_controller)


class TestRetake:
    """The environment a work item's fresh-start Resume runs in again (review
    B1, B3; V23)."""

    def test_its_claim_is_cleared_its_reset_still_to_make(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        now = datetime.now(UTC)
        row = _own(session, state="running", claimed=True)
        row.started_pod_at = now - timedelta(hours=1)
        row.stop_due_at = now + STOP_AFTER
        session.flush()

        assert environments.retake(session, ENV) is True

        assert _claim(_row(session)) == _NO_CLAIM
        assert fake_controller.calls == []

    @pytest.mark.parametrize("leaving", ["deleting", GONE])
    def test_one_leaving_is_let_go_as_it_is(
        self, environments: EnvironmentService, session: Session, leaving: str
    ) -> None:
        _own(session, state=leaving, claimed=True)

        assert environments.retake(session, ENV) is False

        row = _row(session)
        assert row is not None and row.server_started_at is not None


class TestReclaim:
    """An environment of Pilot's own whose start ended before its reset,
    handed to the shutdown timer (V19; refinement D1)."""

    def test_one_with_no_claim_is_claimed_with_no_pod(
        self, environments: EnvironmentService, session: Session
    ) -> None:
        before = datetime.now(UTC)
        _own(session, state="running")

        environments.reclaim(session, ENV)

        row = _row(session)
        assert row is not None and row.server_started_at is not None
        assert row.server_started_at >= before
        assert (row.started_pod_at, row.stop_due_at) == (None, None)

    def test_a_claim_it_has_stands(
        self, environments: EnvironmentService, session: Session
    ) -> None:
        row = _own(session, state="running", claimed=True)
        row.started_pod_at = datetime.now(UTC) - timedelta(hours=1)
        session.flush()
        claim = _claim(row)

        environments.reclaim(session, ENV)

        assert _claim(_row(session)) == claim

    def test_one_pilot_did_not_create_is_left_unclaimed(
        self, environments: EnvironmentService, session: Session
    ) -> None:
        _environment(session, started=False)

        environments.reclaim(session, ENV)

        assert _claim(_row(session)) == _NO_CLAIM

    def test_the_timer_then_stops_it_once_nothing_waits_to_start_there(
        self,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        session: Session,
        project: Project,
    ) -> None:
        service = _service(container, supervise, stop_after=timedelta(0))
        _own(session, state="running")
        fake_controller.add_environment(ENV, status="running")
        _agent_session(session, project, SessionState.STOPPED)

        service.reclaim(session, ENV)
        service.arm_shutdown_timer(session, ENV)
        service.run_shutdown_timer(session)

        assert fake_controller.environment(ENV).status == "stopped"
        assert _claim(_row(session)) == _NO_CLAIM


class TestArmShutdownTimer:
    def test_it_arms_an_environment_pilot_started_with_nothing_running_there(
        self, environments: EnvironmentService, session: Session, project: Project
    ) -> None:
        _environment(session)
        _agent_session(session, project, SessionState.IDLE)
        _agent_session(session, project, SessionState.ENDED)
        before = datetime.now(UTC)

        environments.arm_shutdown_timer(session, ENV)

        assert _armed_around(_row(session), before)

    def test_a_turns_end_renews_the_deadline(
        self, environments: EnvironmentService, session: Session
    ) -> None:
        _environment(session, due=datetime.now(UTC) + timedelta(minutes=1))
        before = datetime.now(UTC)

        environments.arm_shutdown_timer(session, ENV)

        assert _armed_around(_row(session), before)

    @pytest.mark.parametrize(
        ("started", "exempt", "state"),
        [
            (False, False, None),
            (True, True, None),
            (True, False, SessionState.RUNNING),
            (True, False, SessionState.STARTING),
        ],
        ids=["not-pilots", "exempt", "a-session-running", "a-session-starting"],
    )
    def test_it_never_arms_what_is_not_the_servers_to_stop(
        self,
        environments: EnvironmentService,
        session: Session,
        project: Project,
        started: bool,
        exempt: bool,
        state: SessionState | None,
    ) -> None:
        _environment(session, started=started, exempt=exempt)
        if state is not None:
            _agent_session(session, project, state)

        environments.arm_shutdown_timer(session, ENV)

        row = _row(session)
        assert row is not None and row.stop_due_at is None

    def test_two_sessions_ending_at_once_leave_it_armed(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        container = committed_app.container
        service = _service(container, supervise)
        with scoped_session(container) as db:
            _environment(db)
            project = _project(db)
            first_id = _agent_session(db, project, SessionState.RUNNING).id
            second_id = _agent_session(db, project, SessionState.RUNNING).id
        maker = container.session_maker()
        first, second = maker(), maker()
        try:
            # Each Session's turn ends in a transaction of its own, which arms
            # the timer before it commits.
            _end_turn(first, first_id)
            service.arm_shutdown_timer(first, ENV)
            _end_turn(second, second_id)
            arming = in_thread(lambda: _arm_and_commit(service, second))
            wait_until(lambda: lock_waits(container) == 1, "waiting on the row")

            # The first saw the second Session still running.
            assert _committed(container, "stop_due_at") is None
            first.commit()
            arming.result()
        finally:
            first.close()
            second.close()

        assert _committed(container, "stop_due_at") is not None


class TestClearShutdownTimer:
    def test_a_session_starting_there_clears_the_deadline(
        self, environments: EnvironmentService, session: Session
    ) -> None:
        _environment(session, due=datetime.now(UTC) + timedelta(minutes=1))

        environments.clear_shutdown_timer(session, ENV)

        row = _row(session)
        assert row is not None
        assert row.stop_due_at is None
        assert row.server_started_at is not None


class TestShutdownTimer:
    def test_it_is_a_timer_that_needs_the_controller(
        self, app: Flask, supervise: Supervise
    ) -> None:
        supervisor, coordinator = supervise(app.container, controller_configured=False)
        EnvironmentService(
            container=app.container,
            supervisor=supervisor,
            stop_after_seconds=60,
            delete_after_seconds=60,
        )

        with listening("app.services.supervisor") as log:
            coordinator.fire_startup()

        assert log.matching(r"No controller configured.*") == [
            "No controller configured (CONTROLLER_URL unset): the jobs and timers "
            f"that need one do not start ({SHUTDOWN_TIMER}, {DELETE_TIMER})"
        ]

    def test_it_stops_an_overdue_environment_pilot_started(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        fake_controller.add_environment(ENV, status="running")
        _environment(session, pod=_pod(fake_controller), due=_overdue())

        environments.run_shutdown_timer(session)

        assert fake_controller.environment(ENV).status == "stopped"
        assert fake_controller.calls == [
            f"GET /environments/{ENV}",
            f"POST /environments/{ENV}/stop",
        ]
        assert _claim(_row(session)) == _NO_CLAIM

    def test_one_bound_by_an_open_registered_document_is_stopped(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
        container: ServiceContainer,
        project: Project,
    ) -> None:
        # F65.1: it waits stopped for its documents' answers.
        fake_controller.add_environment(ENV, status="running")
        _environment(session, pod=_pod(fake_controller), due=_overdue())
        run = _agent_session(session, project, SessionState.IDLE)
        _registered(session, container, project, run, "published")

        environments.run_shutdown_timer(session)

        assert fake_controller.environment(ENV).status == "stopped"

    @pytest.mark.parametrize("pilots_200", [False, True])
    def test_a_bring_up_someone_stopped_and_started_again_is_never_stopped(
        self,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        session: Session,
        pilots_200: bool,
    ) -> None:
        # 007's close-out D2, as the reviewer witnessed it: Pilot's 202,
        # someone's stop and start, then Pilot's 200 or none, the tick. No time
        # to stand idle, so the tick is due at once.
        service = _service(container, supervise, stop_after=timedelta(0))
        fake_controller.add_environment(ENV, status="stopped")
        service.start(ENV)
        fake_controller.set_status(ENV, "stopped")
        fake_controller.set_status(ENV, "running")
        if pilots_200:
            service.start(ENV)

        service.run_shutdown_timer(session)
        service.run_shutdown_timer(session)

        assert _stops(fake_controller) == []
        assert fake_controller.environment(ENV).status == "running"
        assert _claim(_row(session)) == _NO_CLAIM

    def test_pilots_own_bring_up_left_idle_is_stopped(
        self,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        session: Session,
    ) -> None:
        service = _service(container, supervise, stop_after=timedelta(0))
        fake_controller.add_environment(ENV, status="stopped")
        service.start(ENV)
        service.start(ENV)  # answered 200: Pilot's own pod runs

        service.run_shutdown_timer(session)

        assert fake_controller.environment(ENV).status == "stopped"
        assert _claim(_row(session)) == _NO_CLAIM

    @pytest.mark.parametrize("settle", ["cut", "run-out"])
    def test_a_start_cut_before_its_settle_keeps_its_claim(
        self,
        container: ServiceContainer,
        controller_client: ControllerClient,
        supervise: Supervise,
        session: Session,
        settle: str,
    ) -> None:
        # Review O1: Pilot's 202, the settle cut or run out before a pod, the
        # resumed start's 200, and the environment stopped once idle past the
        # timer.
        fake = _SettleCut() if settle == "cut" else _SettleRunOut()
        try:
            client_of(container, fake)
            service = _service(container, supervise, stop_after=timedelta(0))
            fake.add_environment(ENV, status="stopped")
            with pytest.raises(ExternalServiceException):
                service.start(ENV)
            row = _row(session)
            assert row is not None and row.server_started_at is not None
            assert row.started_pod_at is None

            service.start(ENV)  # answered 200: the cut start's bring-up runs
            assert _claim(_row(session))[1] == _pod(fake)
            service.run_shutdown_timer(session)
        finally:
            fake.close()

        assert fake.environment(ENV).status == "stopped"
        assert _claim(_row(session)) == _NO_CLAIM

    def test_a_bring_up_that_settled_stopped_claims_no_later_pod(
        self,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        session: Session,
    ) -> None:
        # Review r1, F1: Pilot's 202 settled stopped, someone's start, Pilot's
        # 200, the tick.
        service = _service(container, supervise, stop_after=timedelta(0))
        fake_controller.add_environment(ENV, status="stopped")
        fake_controller.settle_starts(ENV, "stopped")
        with pytest.raises(EnvironmentStartFailed):
            service.start(ENV)
        fake_controller.settle_starts(ENV, None)
        fake_controller.set_status(ENV, "running")

        service.start(ENV)
        service.run_shutdown_timer(session)

        assert _stops(fake_controller) == []
        assert fake_controller.environment(ENV).status == "running"
        assert _claim(_row(session)) == _NO_CLAIM

    @pytest.mark.parametrize(
        "elsewhere", ["stopped", "stopped-and-started", "recreated"]
    )
    def test_a_pod_not_the_claims_is_not_stopped(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
        elsewhere: str,
    ) -> None:
        fake_controller.add_environment(ENV, status="running")
        _environment(session, pod=_pod(fake_controller), due=_overdue())
        if elsewhere == "stopped":
            fake_controller.set_status(ENV, "stopped")
        elif elsewhere == "stopped-and-started":
            fake_controller.set_status(ENV, "stopped")
            fake_controller.set_status(ENV, "running")
        else:
            fake_controller.recreate_pod(ENV)
            fake_controller.set_status(ENV, "running")

        environments.run_shutdown_timer(session)

        assert fake_controller.calls == [f"GET /environments/{ENV}"]
        assert _claim(_row(session)) == _NO_CLAIM

    @pytest.mark.parametrize(
        "elsewhere", ["stopped", "stopped-and-started", "recreated"]
    )
    def test_pilots_own_is_stopped_whatever_pod_runs_there(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
        project: Project,
        elsewhere: str,
    ) -> None:
        # Close-out B1: the pod replaced under a work item that has since
        # ended, every pod of Pilot's own being Pilot's (§13.5).
        fake_controller.add_environment(ENV, status="running")
        row = _own(session, state="running", claimed=True)
        row.started_pod_at = _pod(fake_controller)
        row.stop_due_at = _overdue()
        _agent_session(session, project, SessionState.STOPPED)
        if elsewhere == "recreated":
            fake_controller.recreate_pod(ENV)
            fake_controller.set_status(ENV, "running")
        else:
            fake_controller.set_status(ENV, "stopped")
            if elsewhere == "stopped-and-started":
                fake_controller.set_status(ENV, "running")

        environments.run_shutdown_timer(session)

        assert fake_controller.calls == [f"POST /environments/{ENV}/stop"]
        assert fake_controller.environment(ENV).status == "stopped"
        assert _claim(_row(session)) == _NO_CLAIM

    def test_a_container_restart_leaves_the_pod_the_claims(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        fake_controller.add_environment(ENV, status="running")
        _environment(session, pod=_pod(fake_controller), due=_overdue())
        fake_controller.restart(ENV)
        fake_controller.set_status(ENV, "running")

        environments.run_shutdown_timer(session)

        assert fake_controller.environment(ENV).status == "stopped"
        assert _claim(_row(session)) == _NO_CLAIM

    def test_a_pod_whose_start_is_unknown_is_not_stopped(
        self, container: ServiceContainer, supervise: Supervise, session: Session
    ) -> None:
        fake = _UnknownPodStart()
        try:
            client_of(container, fake)
            fake.add_environment(ENV, status="running")
            _environment(session, pod=_pod(fake), due=_overdue())

            _service(container, supervise).run_shutdown_timer(session)
        finally:
            fake.close()

        assert _stops(fake) == []
        assert _claim(_row(session)) == _NO_CLAIM

    def test_a_claim_with_no_pod_ends_with_no_stop(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
        project: Project,
    ) -> None:
        # As rows written before the claim had its pod hold it.
        fake_controller.add_environment(ENV, status="running")
        _environment(session, due=_overdue())
        _agent_session(session, project, SessionState.FAILED)

        environments.run_shutdown_timer(session)

        assert fake_controller.calls == []
        assert _claim(_row(session)) == _NO_CLAIM

    def test_a_claim_with_no_pod_lasts_while_a_start_waits_there(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
        project: Project,
    ) -> None:
        fake_controller.add_environment(ENV, status="running")
        claim = _claim(_environment(session, due=_overdue()))
        _agent_session(session, project, SessionState.HELD)

        environments.run_shutdown_timer(session)

        assert fake_controller.calls == []
        assert _claim(_row(session)) == claim

    def test_it_leaves_one_not_yet_due(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        fake_controller.add_environment(ENV, status="running")
        due = datetime.now(UTC) + timedelta(minutes=1)
        _environment(session, due=due)

        environments.run_shutdown_timer(session)

        assert fake_controller.calls == []
        row = _row(session)
        assert row is not None and row.stop_due_at == due

    def test_an_environment_pilot_did_not_start_is_never_stopped(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        fake_controller.add_environment(ENV, status="running")
        environments.start(ENV)  # answered 200: running already
        row = _row(session)
        assert row is not None and row.stop_due_at is None
        # Even a deadline the timer never sets does not stop it.
        row.stop_due_at = _overdue()
        session.flush()

        environments.run_shutdown_timer(session)

        assert _stops(fake_controller) == []
        assert fake_controller.environment(ENV).status == "running"

    def test_an_exempt_environment_is_never_stopped(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        fake_controller.add_environment(ENV, status="stopped", exempt=True)
        environments.start(ENV)  # answered 202: Pilot started it
        row = _row(session)
        assert row is not None and row.server_started_at is not None
        assert row.stop_due_at is None
        row.stop_due_at = _overdue()
        session.flush()

        environments.run_shutdown_timer(session)

        assert _stops(fake_controller) == []
        assert fake_controller.environment(ENV).status == "running"

    @pytest.mark.parametrize("state", [SessionState.RUNNING, SessionState.STARTING])
    def test_an_environment_where_a_session_runs_is_never_stopped(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
        project: Project,
        state: SessionState,
    ) -> None:
        fake_controller.add_environment(ENV, status="running")
        _environment(session, due=_overdue())
        _agent_session(session, project, state)

        environments.run_shutdown_timer(session)

        assert _stops(fake_controller) == []
        assert fake_controller.environment(ENV).status == "running"

    def test_it_arms_what_a_restart_left_unarmed(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
        project: Project,
    ) -> None:
        # A restart between the last Session's end and its arm.
        _environment(session)
        _agent_session(session, project, SessionState.IDLE)
        _environment(session, "env-busy")
        _agent_session(session, project, SessionState.RUNNING, "env-busy")
        _environment(session, "env-exempt", exempt=True)
        _environment(session, "env-not-pilots", started=False)
        before = datetime.now(UTC)

        environments.run_shutdown_timer(session)

        assert _armed_around(_row(session), before)
        for env_id in ("env-busy", "env-exempt", "env-not-pilots"):
            row = _row(session, env_id)
            assert row is not None and row.stop_due_at is None, env_id
        assert fake_controller.calls == []

    def test_a_session_start_that_failed_leaves_its_environment_stopped(
        self,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
        supervise: Supervise,
        session: Session,
        project: Project,
    ) -> None:
        # Review r1, B2: the start Pilot made for a Session whose start then
        # fails (F125). No time to stand idle, so the next tick is overdue.
        service = EnvironmentService(
            container=container,
            supervisor=supervise(container)[0],
            stop_after_seconds=0,
            delete_after_seconds=DELETE_AFTER.total_seconds(),
        )
        fake_controller.add_environment(ENV, status="stopped")
        service.ensure_environment(session, ENV)
        starting = _agent_session(session, project, SessionState.STARTING)
        service.start(ENV)
        row = _row(session)
        assert row is not None and row.stop_due_at is None

        starting.state_code = SessionState.FAILED
        session.flush()
        service.arm_shutdown_timer(session, ENV)
        row = _row(session)
        assert row is not None and row.stop_due_at is not None
        service.run_shutdown_timer(session)

        assert fake_controller.environment(ENV).status == "stopped"
        row = _row(session)
        assert row is not None
        assert (row.stop_due_at, row.server_started_at) == (None, None)

    def test_an_environment_the_controller_no_longer_has_is_cleared(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        _environment(session, pod=datetime.now(UTC), due=_overdue())

        environments.run_shutdown_timer(session)

        assert fake_controller.calls == [f"GET /environments/{ENV}"]
        assert _claim(_row(session)) == _NO_CLAIM

    def test_an_environment_gone_before_its_stop_is_cleared(
        self, container: ServiceContainer, supervise: Supervise, session: Session
    ) -> None:
        fake = _StopHook()
        try:
            client_of(container, fake)
            fake.add_environment(ENV, status="running")
            _environment(session, pod=_pod(fake), due=_overdue())
            fake.during_stop = lambda: fake.remove_environment(ENV)

            with listening("app.services.environment_service") as log:
                _service(container, supervise).run_shutdown_timer(session)
        finally:
            fake.close()

        assert _stops(fake) == [f"POST /environments/{ENV}/stop"]
        assert log.matching(rf"Environment {ENV} is gone: .*")
        assert _claim(_row(session)) == _NO_CLAIM

    def test_a_stop_the_controller_refuses_keeps_the_deadline(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        fake_controller.add_environment(ENV, status="deleting")
        due = _overdue()
        _environment(session, pod=_pod(fake_controller), due=due)

        with pytest.raises(ControllerProblem) as raised:
            environments.run_shutdown_timer(session)

        assert raised.value.problem_type is ControllerProblemType.CONFLICT
        row = _row(session)
        assert row is not None and row.stop_due_at == due

    def test_two_ticks_at_once_stop_an_environment_once(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        container = committed_app.container
        fake = _StopHook()
        try:
            client_of(container, fake)
            service = _service(container, supervise)
            fake.add_environment(ENV, status="running")
            with scoped_session(container) as db:
                _environment(db, pod=_pod(fake), due=_overdue())
            other: list[Outcome] = []

            def other_tick() -> None:
                # Another process's tick, while this one holds the row.
                other.append(in_thread(lambda: _tick(container, service)))
                other[0].result()

            fake.during_stop = other_tick
            _tick(container, service)
        finally:
            fake.close()

        assert _stops(fake) == [f"POST /environments/{ENV}/stop"]
        assert _committed(container, "server_started_at") is None
        assert _committed(container, "started_pod_at") is None


def _released_around(row: Environment | None, before: datetime) -> bool:
    assert row is not None and row.delete_due_at is not None
    return (
        before + DELETE_AFTER <= row.delete_due_at <= datetime.now(UTC) + DELETE_AFTER
    )


def _deletes(fake: FakeController, env_id: str = ENV) -> list[str]:
    return [call for call in fake.calls if call == f"DELETE /environments/{env_id}"]


class TestDeleteTimer:
    """The delete timer (§13.5; DB 242; F143.3; V03, V10)."""

    def test_a_free_environment_loses_its_name_and_gets_its_deadline(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
        project: Project,
    ) -> None:
        # Its work item's turn ended: done.
        fake_controller.add_environment(ENV, name="camp", status="running")
        row = _own(session, state="running", claimed=True)
        row.name = "camp"
        _agent_session(session, project, SessionState.IDLE)
        before = datetime.now(UTC)

        environments.run_delete_timer(session)

        assert fake_controller.environment(ENV).name is None
        assert fake_controller.calls == [f"POST /environments/{ENV}/rename"]
        row = _row(session)
        assert _released_around(row, before)
        assert row is not None and row.name == ENV
        # The shutdown timer's claim stands: the delete timer is beside it.
        assert row.server_started_at is not None

    def test_one_with_its_deadline_is_left_as_it_is(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        due = datetime.now(UTC) + timedelta(days=1)
        _own(session, delete_due=due)

        environments.run_delete_timer(session)

        row = _row(session)
        assert row is not None and row.delete_due_at == due
        assert fake_controller.calls == []

    @pytest.mark.parametrize(
        "state",
        [
            SessionState.RUNNING,
            SessionState.STARTING,
            SessionState.HELD,
            SessionState.STOPPED,
            SessionState.FAILED,
        ],
    )
    def test_one_a_session_holds_keeps_its_name_and_gets_no_deadline(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
        project: Project,
        state: SessionState,
    ) -> None:
        # A stopped or failed work item may resume there, with no expiry
        # (refinement D1).
        _own(session)
        _agent_session(session, project, SessionState.IDLE)
        _agent_session(session, project, state)

        environments.run_delete_timer(session)

        row = _row(session)
        assert row is not None and row.delete_due_at is None
        assert fake_controller.calls == []

    @pytest.mark.parametrize("read", _READS)
    def test_one_where_a_registered_document_is_open_keeps_its_name_and_no_deadline(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
        container: ServiceContainer,
        project: Project,
        read: str,
    ) -> None:
        _own(session)
        run = _agent_session(session, project, SessionState.IDLE)
        _registered(session, container, project, run, read)

        environments.run_delete_timer(session)

        row = _row(session)
        assert row is not None and row.delete_due_at is None
        assert fake_controller.calls == []

    def test_an_overdue_one_where_a_registered_document_is_open_is_never_deleted(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
        container: ServiceContainer,
        project: Project,
    ) -> None:
        fake_controller.add_environment(ENV, status="stopped")
        _own(session, delete_due=_overdue())
        run = _agent_session(session, project, SessionState.IDLE)
        _registered(session, container, project, run, "published")

        environments.run_delete_timer(session)

        assert _deletes(fake_controller) == []
        row = _row(session)
        assert row is not None and row.last_state == "stopped"

    def test_one_the_controller_no_longer_has_is_gone(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        _own(session)

        environments.run_delete_timer(session)

        row = _row(session)
        assert row is not None
        assert (row.last_state, row.delete_due_at) == (GONE, None)

    @pytest.mark.parametrize("state", ["stopped", "running", "error"])
    def test_an_overdue_free_environment_is_deleted_whatever_its_state_its_row_kept_gone(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
        project: Project,
        state: str,
    ) -> None:
        fake_controller.add_environment(ENV, status="running")
        if state != "running":
            fake_controller.set_status(ENV, state)
        row = _own(session, state=state, claimed=True, delete_due=_overdue())
        row.stop_due_at = datetime.now(UTC) + STOP_AFTER
        run = _agent_session(session, project, SessionState.IDLE)

        environments.run_delete_timer(session)

        assert _deletes(fake_controller) == [f"DELETE /environments/{ENV}"]
        assert fake_controller.calls == [f"DELETE /environments/{ENV}"]
        row = _row(session)
        assert row is not None
        assert (row.last_state, row.delete_due_at) == (GONE, None)
        assert _claim(row) == _NO_CLAIM
        # Its work item's env chip and links keep reading it (DB 242).
        assert session.get_one(AgentSession, run.id).environment_id == ENV

    def test_one_already_gone_at_the_controller_is_deleted(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        _own(session, delete_due=_overdue())

        environments.run_delete_timer(session)

        assert _deletes(fake_controller) == [f"DELETE /environments/{ENV}"]
        row = _row(session)
        assert row is not None and row.last_state == GONE

    def test_it_leaves_one_not_yet_due(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        fake_controller.add_environment(ENV)
        due = datetime.now(UTC) + timedelta(minutes=1)
        _own(session, delete_due=due)

        environments.run_delete_timer(session)

        assert fake_controller.calls == []
        row = _row(session)
        assert row is not None and row.delete_due_at == due

    @pytest.mark.parametrize("state", ["deleting", GONE])
    def test_one_no_longer_free_loses_its_deadline_undeleted(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
        state: str,
    ) -> None:
        # Someone deleted it before its deadline.
        _own(session, state=state, delete_due=_overdue())

        environments.run_delete_timer(session)

        assert fake_controller.calls == []
        row = _row(session)
        assert row is not None
        assert (row.last_state, row.delete_due_at) == (state, None)

    def test_an_environment_pilot_did_not_create_is_never_renamed_or_deleted(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
        project: Project,
    ) -> None:
        # An operator's of the repository, the store, and one a work item placed
        # by id before slice 020 ran in, each with nothing holding it.
        for env_id, exempt in (
            ("env-operators", False),
            ("env-store", True),
            ("env-placed-by-id", False),
        ):
            fake_controller.add_environment(env_id, name=env_id.upper())
            _environment(session, env_id, started=False, exempt=exempt)
        _agent_session(session, project, SessionState.IDLE, "env-placed-by-id")

        environments.run_delete_timer(session)

        assert fake_controller.calls == []
        for env_id in ("env-operators", "env-store", "env-placed-by-id"):
            assert fake_controller.environment(env_id).name == env_id.upper()
            row = _row(session, env_id)
            assert row is not None and row.delete_due_at is None

    def test_a_delete_the_controller_does_not_answer_keeps_the_deadline(
        self,
        environments: EnvironmentService,
        fake_controller: ServedFakeController,
        session: Session,
    ) -> None:
        fake_controller.add_environment(ENV)
        due = _overdue()
        _own(session, delete_due=due)
        fake_controller.outage()

        with pytest.raises(ControllerUnreachable):
            environments.run_delete_timer(session)

        row = _row(session)
        assert row is not None and row.delete_due_at == due
        assert fake_controller.environment(ENV).status == "stopped"

    def test_two_ticks_at_once_delete_an_environment_once(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        container = committed_app.container
        fake = _Hooked()
        try:
            client_of(container, fake)
            service = _service(container, supervise)
            fake.add_environment(ENV)
            with scoped_session(container) as db:
                _own(db, delete_due=_overdue())

            def other_tick() -> None:
                # Another process's tick, while this one holds the row.
                in_thread(lambda: _delete_tick(container, service)).result()

            fake.during["DELETE"] = other_tick
            _delete_tick(container, service)
        finally:
            fake.close()

        assert _deletes(fake) == [f"DELETE /environments/{ENV}"]
        assert _committed(container, "last_state") == GONE

    def test_a_take_while_the_tick_unnames_it_passes_it_over(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        container = committed_app.container
        fake = _Hooked()
        try:
            client_of(container, fake)
            service = _service(container, supervise)
            fake.add_environment(ENV, name="camp")
            with scoped_session(container) as db:
                _own(db)
            taken: list[str | None] = []

            def take() -> None:
                def run() -> None:
                    with scoped_session(container) as db:
                        taken.append(_taken(service, db))

                in_thread(run).result()

            fake.during["rename"] = take
            _delete_tick(container, service)
        finally:
            fake.close()

        assert taken == [None]
        assert _committed(container, "delete_due_at") is not None

    def test_a_take_committed_between_the_ticks_read_and_its_lock_keeps_its_name(
        self,
        committed_app: Flask,
        supervise: Supervise,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The tick read the environment free with no deadline; a start took it
        # before the tick locked its row.
        container = committed_app.container
        fake = ServedFakeController(keepalive_seconds=0.2)
        try:
            client_of(container, fake)
            service = _service(container, supervise)
            fake.add_environment(ENV, name="camp")
            with scoped_session(container) as db:
                _own(db).name = "camp"
                project_id = _project(db).id
            earlier: list[uuid.UUID] = []
            _before_the_next_lock(
                monkeypatch,
                lambda: earlier.append(_take_and_start(container, service, project_id)),
            )
            _delete_tick(container, service)
        finally:
            fake.close()

        assert len(earlier) == 1
        assert fake.calls == []
        assert fake.environment(ENV).name == "camp"
        assert _committed(container, "name") == "camp"
        assert _committed(container, "delete_due_at") is None


def _before_the_next_lock(
    monkeypatch: pytest.MonkeyPatch, run: Callable[[], None]
) -> None:
    """Run `run` once just before the next Environment row lock that skips a
    locked row, after the caller read the row it is about to lock. `run` shares
    the caller's Session, `container.db_session` being context-local, and a
    `scoped_session` in it commits that Session on its exit: the lock and its
    re-read then run in a new transaction, which sees what `run` wrote."""
    try_lock = environment_service._try_lock
    pending = [run]

    def hooked(db: Session, env_id: str) -> Environment | None:
        if pending:
            pending.pop()()
        return try_lock(db, env_id)

    monkeypatch.setattr(environment_service, "_try_lock", hooked)


def _take_and_start(
    container: ServiceContainer, service: EnvironmentService, project_id: uuid.UUID
) -> uuid.UUID:
    """A start's take of ENV, its Session `starting` there, committed."""
    with scoped_session(container) as db:
        assert _taken(service, db) == ENV
        return _agent_session(
            db, db.get_one(Project, project_id), SessionState.STARTING
        ).id


class _StopHook(ServedFakeController):
    """The fake, running `during_stop` once while it answers a stop."""

    def __init__(self) -> None:
        super().__init__(keepalive_seconds=0.2)
        self.during_stop: Callable[[], None] | None = None

    def _stop(self, request: Request, env_id: str) -> Response:
        hook, self.during_stop = self.during_stop, None
        if hook is not None:
            hook()
        return super()._stop(request, env_id)


class _SlowStop(ServedFakeController):
    """The fake, whose stop leaves the environment `stopping` until a settled
    `GET` finds it `stop_settles_to`; `stopping` there answers as a wait run
    out does."""

    def __init__(self, stop_settles_to: EnvironmentStatus = "stopped") -> None:
        super().__init__(keepalive_seconds=0.2)
        self.stop_settles_to = stop_settles_to

    def _stop(self, request: Request, env_id: str) -> Response:
        response = super()._stop(request, env_id)
        if response.status_code == 202:
            self.set_status(env_id, "stopping")
        return response

    def _get_environment(self, request: Request, env_id: str) -> Response:
        stopping = self.environment(env_id).status == "stopping"
        if stopping and request.args.get("wait") == "settled":
            if self.stop_settles_to == "stopping":
                return Response(
                    json.dumps(self.environment(env_id).to_json()),
                    status=200,
                    content_type="application/json",
                )
            self.set_status(env_id, self.stop_settles_to)
        return super()._get_environment(request, env_id)


class _Hooked(ServedFakeController):
    """The fake, running `during[verb]` once while it answers a delete
    (`DELETE`) or a rename (`rename`)."""

    def __init__(self) -> None:
        super().__init__(keepalive_seconds=0.2)
        self.during: dict[str, Callable[[], None]] = {}

    def _delete_environment(self, request: Request, env_id: str) -> Response:
        self._run("DELETE")
        return super()._delete_environment(request, env_id)

    def _rename(self, request: Request, env_id: str) -> Response:
        self._run("rename")
        return super()._rename(request, env_id)

    def _run(self, verb: str) -> None:
        hook = self.during.pop(verb, None)
        if hook is not None:
            hook()


class _SettleCut(ServedFakeController):
    """The fake, answering the first settle's `GET` with an ingress's 503, as a
    start cut between its `202` and its settle leaves it."""

    def __init__(self) -> None:
        super().__init__(keepalive_seconds=0.2)
        self._cut = True

    def _get_environment(self, request: Request, env_id: str) -> Response:
        if self._cut and request.args.get("wait") == "settled":
            self._cut = False
            return Response("upstream unavailable", status=503)
        return super()._get_environment(request, env_id)


class _SettleRunOut(ServedFakeController):
    """The fake, answering the first settle's `GET` as a wait run out before
    the bring-up had a pod: `starting`, no pod."""

    def __init__(self) -> None:
        super().__init__(keepalive_seconds=0.2)
        self._run_out = True

    def _get_environment(self, request: Request, env_id: str) -> Response:
        response = super()._get_environment(request, env_id)
        if not (self._run_out and request.args.get("wait") == "settled"):
            return response
        self._run_out = False
        body = response.get_json()
        body["status"] = "starting"
        body["pod"] = None
        return Response(json.dumps(body), status=200, content_type="application/json")


class _UnknownPodStart(ServedFakeController):
    """The fake, reporting a pod with no `startedAt`."""

    def __init__(self) -> None:
        super().__init__(keepalive_seconds=0.2)

    def _get_environment(self, request: Request, env_id: str) -> Response:
        response = super()._get_environment(request, env_id)
        body = response.get_json()
        body["pod"]["startedAt"] = None
        return Response(
            json.dumps(body),
            status=response.status_code,
            content_type="application/json",
        )


def _service(
    container: ServiceContainer,
    supervise: Supervise,
    stop_after: timedelta = STOP_AFTER,
    delete_after: timedelta = DELETE_AFTER,
) -> EnvironmentService:
    return EnvironmentService(
        container=container,
        supervisor=supervise(container)[0],
        stop_after_seconds=stop_after.total_seconds(),
        delete_after_seconds=delete_after.total_seconds(),
    )


def _tick(container: ServiceContainer, service: EnvironmentService) -> None:
    with scoped_session(container) as db:
        service.run_shutdown_timer(db)


def _delete_tick(container: ServiceContainer, service: EnvironmentService) -> None:
    with scoped_session(container) as db:
        service.run_delete_timer(db)


def _project(db: Session) -> Project:
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
    return project


def _end_turn(db: Session, session_id: uuid.UUID) -> None:
    db.execute(
        update(AgentSession)
        .where(AgentSession.id == session_id)
        .values(state_code=SessionState.IDLE)
    )


def _arm_and_commit(service: EnvironmentService, db: Session) -> None:
    service.arm_shutdown_timer(db, ENV)
    db.commit()


def _committed(container: ServiceContainer, column: str) -> Any:
    """The committed value of the environment's column; None with no row."""
    with scoped_session(container) as db:
        row = _row(db)
        return None if row is None else getattr(row, column)
