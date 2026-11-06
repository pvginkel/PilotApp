"""The standing notifications' reconcile (F94.3, F94.4; DB decision 51; V02,
V05, V06, V08, V16, V18, V19): what each member should see of a project
compared with what their membership last sent, and submitted or dismissed
through the fake bridge when it differs.

Every test is on a database of its own: a member's turn is an advisory lock on
a connection of its own, which reads committed rows alone. A loop's run is
called as its loop calls it; the loops themselves run where a test fires
STARTUP."""

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import Integer, cast, func, literal, select
from sqlalchemy.pool import QueuePool

from app import models
from app.database import scoped_session
from app.engine.bus import EngineBus, ProjectChanged, WorkMoved
from app.models import Project, ProjectMember, User
from app.models.reference import (
    ProgressState,
    SessionState,
    TaskStatus,
    TransitionKind,
)
from app.schemas.pilot_work import ProgressStepRequestSchema
from app.schemas.testing_record import InventedProjectCreateSchema
from app.services.advisory_turn import turn_key
from app.services.auth_service import AuthContext
from app.services.container import ServiceContainer
from app.services.fake_notification_bridge import FakeCall, FakeNotification
from app.services.notification_bridge_client import BridgePriority
from app.services.notification_reconcile_service import (
    NOTIFICATION_CLEAR_DISMISSES_TOTAL,
    NOTIFICATION_CLEAR_JOB,
    NOTIFICATION_JOB,
    NOTIFICATION_LOCK,
    NOTIFICATION_RECONCILES_TOTAL,
    NotificationReconcileService,
)
from app.services.pilot_work_service import Worker
from app.services.supervisor import LoopHandle, Supervisor
from app.utils.after_commit import clear_after_commit_callbacks
from app.utils.lifecycle_coordinator import LifecycleCoordinator
from tests.support.fake_notification_bridge import (
    WatchedFakeNotificationBridge,
    bridge_client_of,
)
from tests.support.locks import in_thread, lock_waits
from tests.support.supervisor import (
    LogWaiter,
    RoundsHandle,
    Supervise,
    listening,
    metric_value,
    wait_until,
)

ADA_TOKEN = "token-of-ada"
BEN_TOKEN = "token-of-ben"
ENV = "env-a"
LOGGER = "app.services.notification_reconcile_service"
SUPERVISOR_LOGGER = "app.services.supervisor"

DECISION = "```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n"
QUESTION = "```question id=Q1\n```\n"

SPACING = 0.3
"""A person's window between two sends in one project, in the tests of it."""


@pytest.fixture(autouse=True)
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


@pytest.fixture
def container(committed_app: Flask) -> ServiceContainer:
    """The committed app's container, with Ada, Ben and an environment."""
    container: ServiceContainer = committed_app.container
    with scoped_session(container):
        data = container.test_data_service()
        data.person("ada", "Ada Example")
        data.person("ben", "Ben Example")
        data.environment(ENV, "Env-A")
    return container


@pytest.fixture
def bridge(container: ServiceContainer) -> Iterator[WatchedFakeNotificationBridge]:
    """The fake bridge, the container's client on it, with a registration for
    Ada and one for Ben."""
    fake = WatchedFakeNotificationBridge()
    try:
        bridge_client_of(container, fake)
        fake.add_registration("ada", ADA_TOKEN)
        fake.add_registration("ben", BEN_TOKEN)
        yield fake
        assert fake.failures == []
    finally:
        fake.close()


@pytest.fixture
def log() -> Iterator[LogWaiter]:
    with listening(LOGGER, SUPERVISOR_LOGGER) as waiter:
        yield waiter


def _service(
    container: ServiceContainer,
    supervise: Supervise,
    *,
    engine_bus: EngineBus | None = None,
    retry_seconds: float = 60.0,
    spacing_seconds: float | None = 0.0,
    configured: bool = True,
) -> tuple[NotificationReconcileService, Supervisor, LifecycleCoordinator]:
    """The reconcile on a supervisor of its own, hearing `engine_bus`: a bus
    of its own unless one is given. No window between a person's sends unless
    `spacing_seconds` gives one; none for the service's own."""
    supervisor, coordinator = supervise(container)
    spacing = {} if spacing_seconds is None else {"spacing_seconds": spacing_seconds}
    service = NotificationReconcileService(
        container=container,
        supervisor=supervisor,
        engine_bus=EngineBus() if engine_bus is None else engine_bus,
        notification_token_cipher=container.notification_token_cipher(),
        bridge_configured=configured,
        retry_seconds=retry_seconds,
        **spacing,
    )
    return service, supervisor, coordinator


def _reconcile(service: NotificationReconcileService, project_id: uuid.UUID) -> None:
    service.reconcile(project_id, LoopHandle("test"))


def _person(container: ServiceContainer, handle: str) -> User:
    return (
        container.db_session().scalars(select(User).where(User.handle == handle)).one()
    )


def _auth(person: User) -> AuthContext:
    assert person.subject is not None
    return AuthContext(subject=person.subject, email=None, name=None, roles=set())


def _project(
    container: ServiceContainer, members: tuple[str, ...] = ("ada",), **spec: Any
) -> uuid.UUID:
    """A project, not started, its session in the environment unless
    `environment_id` is given as none."""
    spec.setdefault("environment_id", ENV)
    with scoped_session(container):
        return (
            container.test_data_service()
            .project(
                InventedProjectCreateSchema.model_validate(
                    {"members": list(members), "name": "Camp", **spec}
                )
            )
            .id
        )


def _give_token(container: ServiceContainer, handle: str, token: str) -> None:
    """The token on the record, as it was before this reconcile's time."""
    with scoped_session(container):
        _person(
            container, handle
        ).notification_token = container.notification_token_cipher().seal(token)


def _bear(
    container: ServiceContainer,
    project_id: uuid.UUID,
    kind: str,
    title: str,
    text: str,
    *,
    by_pilot: bool = False,
    **front_matter: str,
) -> uuid.UUID:
    """A prose item the project's session adds, or with `by_pilot` a job of
    Pilot's own, committed."""
    header = "".join(f"{key}: {value}\n" for key, value in front_matter.items())
    with scoped_session(container):
        return (
            container.test_data_service()
            .item(
                project_id,
                kind,
                title,
                f"---\ntitle: {title}\n{header}---\n\n{text}",
                by_pilot=by_pilot,
            )
            .id
        )


def _ask(
    container: ServiceContainer, project_id: uuid.UUID, title: str = "Which tent?"
) -> uuid.UUID:
    """A decision that waits on the project's members, placed by a job of
    Pilot's own, so that a project with no session holds one too."""
    return _bear(container, project_id, "decision", title, DECISION, by_pilot=True)


def _answer(
    container: ServiceContainer, handle: str, item_id: uuid.UUID, answer: str
) -> None:
    with scoped_session(container):
        container.item_service().answer(
            _auth(_person(container, handle)), item_id, "D1", answer, None
        )


def _running_work(container: ServiceContainer, project_id: uuid.UUID) -> Worker:
    """A work item of the project, its session's turn running in the
    environment, committed: its worker."""
    with scoped_session(container) as db:
        run = models.Session(
            project_id=project_id,
            environment_id=ENV,
            kind_code="work",
            cwd="/work/Camp",
            token_hash=uuid.uuid4().hex * 2,
            state_code=SessionState.RUNNING,
        )
        db.add(run)
        db.flush()
        container.record_service().place_work(
            db.get_one(Project, project_id), run, "Building the camp"
        )
        return Worker(run.id, project_id, ENV, run.id)


def _leave(container: ServiceContainer, handle: str, project_id: uuid.UUID) -> None:
    with scoped_session(container):
        container.project_service().leave(_auth(_person(container, handle)), project_id)


def _join(container: ServiceContainer, handle: str, project_id: uuid.UUID) -> None:
    with scoped_session(container):
        container.project_service().join(_auth(_person(container, handle)), project_id)


def _transition(
    container: ServiceContainer, project_id: uuid.UUID, kind: TransitionKind
) -> None:
    with scoped_session(container):
        container.project_service().transition_as(
            _person(container, "ada"), project_id, kind
        )


def _clear(
    container: ServiceContainer, service: NotificationReconcileService, handle: str
) -> None:
    """The person's token cleared, as their profile's Clear clears it."""
    with scoped_session(container):
        person = _person(container, handle)
        token = container.notification_token_cipher().open(person)
        assert token is not None
        person.notification_token = None
        service.dismiss_all(container.db_session(), person, token)


def _set(
    container: ServiceContainer,
    service: NotificationReconcileService,
    handle: str,
    token: str,
) -> None:
    """The person's token set, as their profile's Save sets it."""
    with scoped_session(container):
        person = _person(container, handle)
        person.notification_token = container.notification_token_cipher().seal(token)
        service.submit_all(container.db_session(), person)


def _memberships(
    container: ServiceContainer, project_id: uuid.UUID, handle: str = "ada"
) -> list[ProjectMember]:
    """The person's memberships of the project, in the order joined, as
    committed."""
    with scoped_session(container) as db:
        memberships = db.scalars(
            select(ProjectMember)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project_id, User.handle == handle)
            .order_by(ProjectMember.joined_at, ProjectMember.id)
        ).all()
        db.expunge_all()
        return list(memberships)


def _last_sent(
    container: ServiceContainer, project_id: uuid.UUID, handle: str = "ada"
) -> tuple[str | None, str | None]:
    """The text and `url` the person's latest membership last sent; none
    while none stands."""
    membership = _memberships(container, project_id, handle)[-1]
    return membership.notification_text, membership.notification_url


def _owed(container: ServiceContainer, project_id: uuid.UUID) -> bool:
    return any(
        membership.notification_owed_at is not None
        for membership in _memberships(container, project_id)
    )


def _timeline(container: ServiceContainer, project_id: uuid.UUID) -> str:
    return f"{container.config().baseurl}/projects/{project_id}"


def _shown(
    bridge: WatchedFakeNotificationBridge, project_id: uuid.UUID, name: str = "ada"
) -> FakeNotification:
    return bridge.shown(name)[str(project_id)]


def _sent_at(
    container: ServiceContainer, project_id: uuid.UUID, handle: str = "ada"
) -> datetime:
    sent_at = _memberships(container, project_id, handle)[-1].notification_sent_at
    assert sent_at is not None
    return sent_at


def _checked_out(container: ServiceContainer) -> int:
    """The app's pooled database connections in use."""
    pool = container.session_maker().kw["bind"].pool
    assert isinstance(pool, QueuePool)
    return pool.checkedout()


def _turn_free(
    container: ServiceContainer, project_id: uuid.UUID, handle: str = "ada"
) -> bool:
    """Whether the person's turn in the project is free: taken and let go at
    once, on a session of its own."""
    person_id = _memberships(container, project_id, handle)[0].user_id
    with container.session_maker()() as db:
        free: bool = db.scalar(
            select(
                func.pg_try_advisory_xact_lock(
                    cast(literal(NOTIFICATION_LOCK), Integer),
                    cast(literal(turn_key(person_id.bytes, project_id.bytes)), Integer),
                )
            )
        )
        db.rollback()
        return free


class _Window(RoundsHandle):
    """A loop's handle that keeps the seconds of each wait asked and calls
    `between` with their count, on the run's thread, before it sleeps."""

    def __init__(self, between: Callable[[int], None]) -> None:
        super().__init__("test", between)
        self.asked: list[float] = []

    def wait(self, seconds: float) -> bool:
        self.asked.append(seconds)
        return super().wait(seconds)


def _reconciles(outcome: str) -> float:
    return metric_value(NOTIFICATION_RECONCILES_TOTAL, outcome=outcome)


def _clear_dismisses(outcome: str) -> float:
    return metric_value(NOTIFICATION_CLEAR_DISMISSES_TOTAL, outcome=outcome)


class TestNotificationReconcileServiceReconcile:
    def test_nothing_waiting_sends_nothing_and_an_ask_is_submitted_at_high(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container, ("ada", "ben"))
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise)
        unchanged = _reconciles("unchanged")

        _reconcile(service, project_id)

        assert bridge.calls("ada") == []
        assert _last_sent(container, project_id) == (None, None)
        assert _reconciles("unchanged") == unchanged + 2

        tent = _bear(container, project_id, "decision", "Which tent?", DECISION)
        sent, unchanged = _reconciles("sent"), _reconciles("unchanged")
        _reconcile(service, project_id)

        assert bridge.shown("ada") == {
            str(project_id): FakeNotification(
                sequence_id=str(project_id),
                priority="high",
                title="Camp",
                message="Which tent?",
                url=f"{_timeline(container, project_id)}/items/{tent}",
                alerted=True,
            )
        }
        assert bridge.calls("ben") == []
        [membership] = _memberships(container, project_id)
        assert (
            membership.notification_text,
            membership.notification_url,
            membership.notification_owed_at,
        ) == (
            "Which tent?",
            f"{_timeline(container, project_id)}/items/{tent}",
            None,
        )
        assert membership.notification_sent_at is not None
        assert _reconciles("sent") == sent + 1
        # Ben, a member with no token: nothing to see, nothing sent.
        assert _reconciles("unchanged") == unchanged + 1

    def test_what_was_last_sent_is_not_sent_again(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        _bear(container, project_id, "decision", "Which tent?", DECISION)
        service, _, _ = _service(container, supervise)
        _reconcile(service, project_id)
        sent_at = _memberships(container, project_id)[0].notification_sent_at
        unchanged = _reconciles("unchanged")

        _reconcile(service, project_id)

        assert bridge.calls("ada") == [FakeCall("submit", str(project_id), True)]
        assert _memberships(container, project_id)[0].notification_sent_at == sent_at
        assert _reconciles("unchanged") == unchanged + 1

    def test_the_first_ask_alerts_and_every_later_change_updates_it_silently(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise)

        tent = _bear(container, project_id, "decision", "Which tent?", DECISION)
        _reconcile(service, project_id)
        site = _bear(container, project_id, "decision", "Which site?", DECISION)
        _reconcile(service, project_id)
        shown = _shown(bridge, project_id)
        assert (shown.priority, shown.message, shown.url, shown.alerted) == (
            "high",
            "Which site?, +1",
            _timeline(container, project_id),
            False,
        )

        # An urgent ask arriving while one stands is silent too.
        storm = _bear(
            container, project_id, "decision", "Storm shelter?", DECISION, urgent="true"
        )
        _reconcile(service, project_id)
        shown = _shown(bridge, project_id)
        assert (shown.priority, shown.message, shown.alerted) == (
            "high",
            "Storm shelter?, +2",
            False,
        )

        # The member's own answers update it, silently.
        _answer(container, "ada", tent, "Dome")
        _answer(container, "ada", site, "Dome")
        _reconcile(service, project_id)
        shown = _shown(bridge, project_id)
        assert (shown.priority, shown.message, shown.url, shown.alerted) == (
            "high",
            "Storm shelter?",
            f"{_timeline(container, project_id)}/items/{storm}",
            False,
        )
        assert [call.alerted for call in bridge.calls("ada")] == [
            True,
            False,
            False,
            False,
        ]
        assert _last_sent(container, project_id) == ("Storm shelter?", shown.url)

    def test_answering_the_last_ask_dismisses_and_the_next_alerts_anew(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise)
        tent = _bear(container, project_id, "decision", "Which tent?", DECISION)
        _reconcile(service, project_id)

        _answer(container, "ada", tent, "Dome")
        _reconcile(service, project_id)

        assert bridge.shown("ada") == {}
        assert _last_sent(container, project_id) == (None, None)

        _bear(container, project_id, "decision", "Which site?", DECISION)
        _reconcile(service, project_id)

        assert bridge.calls("ada") == [
            FakeCall("submit", str(project_id), True),
            FakeCall("dismiss", str(project_id), False),
            FakeCall("submit", str(project_id), True),
        ]
        assert _shown(bridge, project_id).message == "Which site?"

    def test_a_change_that_leaves_the_text_and_url_sends_nothing(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        """A work item starting to run, a plan step, a change of an item the
        ", +<n>" counts and an item for another member touch nothing the
        member sees."""
        project_id = _project(
            container,
            ("ada", "ben"),
            tasks=[{"id": "t1", "title": "Pitch the tent", "status": "pending"}],
        )
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise)
        site = _bear(container, project_id, "decision", "Which site?", DECISION)
        _bear(container, project_id, "decision", "Which tent?", DECISION)
        _reconcile(service, project_id)
        calls = bridge.calls("ada")

        _running_work(container, project_id)
        _reconcile(service, project_id)
        with scoped_session(container) as db:
            db.scalars(
                select(models.PlanTask).where(models.PlanTask.project_id == project_id)
            ).one().status_code = TaskStatus.IN_PROGRESS
        _reconcile(service, project_id)
        with scoped_session(container) as db:
            db.get_one(models.Item, site).title = "Which campsite?"
        _bear(
            container,
            project_id,
            "question",
            "Your boots?",
            QUESTION,
            **{"for": "ben"},
        )
        _reconcile(service, project_id)

        assert bridge.calls("ada") == calls
        assert _shown(bridge, project_id).message == "Which tent?, +1"

    def test_an_item_for_one_member_is_theirs_alone(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container, ("ada", "ben"))
        _give_token(container, "ada", ADA_TOKEN)
        _give_token(container, "ben", BEN_TOKEN)
        service, _, _ = _service(container, supervise)

        _bear(
            container,
            project_id,
            "question",
            "Your boots?",
            QUESTION,
            urgent="true",
            **{"for": "ben"},
        )
        _reconcile(service, project_id)

        ben = _shown(bridge, project_id, "ben")
        assert (ben.priority, ben.message, ben.alerted) == ("high", "Your boots?", True)
        assert bridge.calls("ada") == []

    def test_leave_dismisses_and_a_rejoin_submits_afresh(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container, ("ada", "ben"))
        _give_token(container, "ada", ADA_TOKEN)
        _bear(container, project_id, "decision", "Which tent?", DECISION)
        service, _, _ = _service(container, supervise)
        _reconcile(service, project_id)
        submitted_at = _memberships(container, project_id)[0].notification_sent_at
        assert submitted_at is not None

        _leave(container, "ada", project_id)
        _reconcile(service, project_id)

        assert bridge.shown("ada") == {}
        [closed] = _memberships(container, project_id)
        assert _last_sent(container, project_id) == (None, None)
        assert closed.notification_sent_at is not None
        assert closed.notification_sent_at > submitted_at

        _join(container, "ada", project_id)
        _reconcile(service, project_id)

        assert _shown(bridge, project_id).message == "Which tent?"
        assert bridge.calls("ada") == [
            FakeCall("submit", str(project_id), True),
            FakeCall("dismiss", str(project_id), False),
            FakeCall("submit", str(project_id), True),
        ]
        closed, rejoined = _memberships(container, project_id)
        assert closed.notification_text is None
        assert rejoined.notification_text == "Which tent?"

    def test_archive_dismisses_and_bring_back_submits(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container, environment_id=None)
        _give_token(container, "ada", ADA_TOKEN)
        _ask(container, project_id)
        service, _, _ = _service(container, supervise)
        _reconcile(service, project_id)

        _transition(container, project_id, TransitionKind.ARCHIVED)
        _reconcile(service, project_id)
        assert bridge.shown("ada") == {}
        assert _last_sent(container, project_id) == (None, None)

        _transition(container, project_id, TransitionKind.BROUGHT_BACK)
        _reconcile(service, project_id)
        assert _shown(bridge, project_id).message == "Which tent?"
        assert _last_sent(container, project_id)[0] is not None

    def test_a_draft_and_a_finished_project_hold_theirs_while_something_waits(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        draft = _project(container, environment_id=None, state="draft")
        finished = _project(container, environment_id=None, state="finished")
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise)
        _reconcile(service, draft)
        _reconcile(service, finished)
        assert bridge.calls("ada") == []

        _ask(container, draft, "Where?")
        _ask(container, finished)
        _reconcile(service, draft)
        _reconcile(service, finished)

        assert _shown(bridge, draft).message == "Where?"
        assert _shown(bridge, finished).message == "Which tent?"


class TestNotificationReconcileServiceOwed:
    def test_a_send_the_bridge_does_not_answer_is_owed_and_logged_once(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        _bear(container, project_id, "decision", "Which tent?", DECISION)
        service, _, _ = _service(container, supervise)
        owed = _reconciles("owed")
        bridge.unreachable()

        _reconcile(service, project_id)
        _reconcile(service, project_id)

        assert _owed(container, project_id)
        assert _last_sent(container, project_id) == (None, None)
        assert _reconciles("owed") == owed + 2
        failures = [
            record
            for record in log.records
            if record.getMessage().startswith(
                f"The submit of project {project_id}'s notification to ada is owed"
            )
        ]
        assert len(failures) == 1
        assert failures[0].levelname == "WARNING"

        bridge.unreachable(on=False)
        _reconcile(service, project_id)

        assert not _owed(container, project_id)
        assert _last_sent(container, project_id)[0] is not None
        log.wait_for(
            rf"The owed submit of project {project_id}'s notification to ada went out"
        )

    def test_a_refused_token_is_owed(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        _bear(container, project_id, "decision", "Which tent?", DECISION)
        service, _, _ = _service(container, supervise)
        bridge.rotate_token("ada", "a-rotated-token")

        _reconcile(service, project_id)

        assert _owed(container, project_id)
        log.wait_for(rf"The submit of project {project_id}'s .* is owed: .*401.*")

    def test_an_owed_send_is_sent_again_with_nothing_else_changed(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container, ("ada", "ben"))
        _give_token(container, "ada", ADA_TOKEN)
        _bear(container, project_id, "decision", "Which tent?", DECISION)
        service, _, _ = _service(container, supervise)
        _reconcile(service, project_id)
        bridge.unreachable()
        _leave(container, "ada", project_id)
        _reconcile(service, project_id)
        assert _owed(container, project_id)
        assert _last_sent(container, project_id)[0] is not None

        bridge.unreachable(on=False)
        _reconcile(service, project_id)

        assert bridge.shown("ada") == {}
        assert not _owed(container, project_id)
        assert _last_sent(container, project_id) == (None, None)

    def test_a_rejoin_takes_the_place_of_an_owed_dismiss(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container, ("ada", "ben"))
        _give_token(container, "ada", ADA_TOKEN)
        _bear(container, project_id, "decision", "Which tent?", DECISION)
        service, _, _ = _service(container, supervise)
        _reconcile(service, project_id)
        bridge.unreachable()
        _leave(container, "ada", project_id)
        _reconcile(service, project_id)
        bridge.unreachable(on=False)

        _join(container, "ada", project_id)
        _reconcile(service, project_id)

        assert _shown(bridge, project_id).message == "Which tent?"
        assert [call.call for call in bridge.calls("ada")] == ["submit", "submit"]
        closed, rejoined = _memberships(container, project_id)
        assert (closed.notification_text, closed.notification_owed_at) == (None, None)
        assert (rejoined.notification_text, rejoined.notification_owed_at) == (
            "Which tent?",
            None,
        )


class TestNotificationReconcileServiceRetry:
    def test_the_timer_asks_for_the_projects_owed_past_their_retry(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        due, recent, settled = (
            _project(container, environment_id=None) for _ in range(3)
        )
        now = datetime.now(UTC)
        with scoped_session(container) as db:
            for project_id, owed_at in (
                (due, now - timedelta(seconds=61)),
                (recent, now),
                (settled, None),
            ):
                db.scalars(
                    select(ProjectMember).where(ProjectMember.project_id == project_id)
                ).one().notification_owed_at = owed_at
        service, supervisor, _ = _service(container, supervise, retry_seconds=60)

        with patch.object(
            supervisor, "start_loop", wraps=supervisor.start_loop
        ) as start:
            with scoped_session(container) as db:
                service.retry(db)

        assert [(call.args[0], call.kwargs) for call in start.call_args_list] == [
            (NOTIFICATION_JOB, {"key": str(due), "again": False})
        ]

    def test_an_owed_send_goes_out_on_the_timer_once_the_bridge_answers(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        _bear(container, project_id, "decision", "Which tent?", DECISION)
        _, _, coordinator = _service(container, supervise, retry_seconds=0)
        bridge.unreachable()

        coordinator.fire_startup()
        log.wait_for(rf"The submit of project {project_id}'s notification .* owed: .*")
        bridge.unreachable(on=False)

        log.wait_for(
            rf"The owed submit of project {project_id}'s notification to ada went out"
        )
        assert _shown(bridge, project_id).message == "Which tent?"


class TestNotificationReconcileServiceStartup:
    def test_startup_reconciles_what_stands_is_owed_or_should_stand(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        unsent = _project(container)
        archived = _project(container, environment_id=None)
        left = _project(container, ("ada", "ben"), environment_id=None)
        untouched = _project(container, ("ben",), environment_id=None)
        tent = _bear(container, unsent, "decision", "Which tent?", DECISION)
        for project_id in (archived, left, untouched):
            _ask(container, project_id)
        _give_token(container, "ada", ADA_TOKEN)
        earlier, _, _ = _service(container, supervise)
        _reconcile(earlier, archived)
        _reconcile(earlier, left)
        # Committed, and the process stopped before their reconciles.
        _transition(container, archived, TransitionKind.ARCHIVED)
        _leave(container, "ada", left)
        _, _, coordinator = _service(container, supervise)

        coordinator.fire_startup()

        for project_id in (unsent, archived, left):
            log.wait_for(rf"Loop {NOTIFICATION_JOB}:{project_id} ended")
        assert bridge.shown("ada") == {
            str(unsent): FakeNotification(
                sequence_id=str(unsent),
                priority="high",
                title="Camp",
                message="Which tent?",
                url=f"{_timeline(container, unsent)}/items/{tent}",
                alerted=True,
            )
        }
        assert log.matching(rf"Loop {NOTIFICATION_JOB}:{untouched} .*") == []

    def test_at_the_deploy_what_waits_on_no_one_is_dismissed_and_the_rest_rewritten(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        """V12: the notifications the ladder left standing, at `min` with
        nothing waiting and at `default` with an ask, as the release before
        this one sent them and revision 0028 keeps them: their text and `url`,
        their priority dropped."""
        idle = _project(container, environment_id=None)
        asking = _project(container, environment_id=None)
        tent = _ask(container, asking)
        _give_token(container, "ada", ADA_TOKEN)
        client = container.notification_bridge_client()
        stood: list[tuple[uuid.UUID, BridgePriority, str]] = [
            (idle, "min", "Not started"),
            (asking, "default", "Not started · Decision waiting: Which tent?"),
        ]
        for project_id, priority, text in stood:
            url = _timeline(container, project_id)
            client.submit(
                ADA_TOKEN,
                str(project_id),
                message=text,
                title="Camp",
                priority=priority,
                url=url,
            )
            with scoped_session(container) as db:
                membership = db.scalars(
                    select(ProjectMember).where(ProjectMember.project_id == project_id)
                ).one()
                membership.notification_text = text
                membership.notification_url = url
                membership.notification_sent_at = datetime.now(UTC)
        _, _, coordinator = _service(container, supervise)

        coordinator.fire_startup()

        for project_id in (idle, asking):
            log.wait_for(rf"Loop {NOTIFICATION_JOB}:{project_id} ended")
        assert bridge.shown("ada") == {
            str(asking): FakeNotification(
                sequence_id=str(asking),
                priority="high",
                title="Camp",
                message="Which tent?",
                url=f"{_timeline(container, asking)}/items/{tent}",
                alerted=False,
            )
        }
        assert _last_sent(container, idle) == (None, None)
        assert _last_sent(container, asking) == (
            "Which tent?",
            f"{_timeline(container, asking)}/items/{tent}",
        )


class TestNotificationReconcileServiceSpacing:
    def test_a_persons_sends_are_two_seconds_apart(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        """V05: the window the service keeps of its own runs two seconds from
        the person's last send."""
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise, spacing_seconds=None)
        _ask(container, project_id)
        _reconcile(service, project_id)
        last = _sent_at(container, project_id)
        _ask(container, project_id, "Which site?")
        entered: list[datetime] = []

        def stop(waits: int) -> None:
            entered.append(datetime.now(UTC))
            handle._request_stop()

        handle = _Window(stop)
        before = datetime.now(UTC)
        service.reconcile(project_id, handle)

        window_end = last + timedelta(seconds=2)
        [asked] = handle.asked
        assert (
            (window_end - entered[0]).total_seconds()
            <= asked
            <= (window_end - before).total_seconds()
        )
        assert len(bridge.calls("ada")) == 1

    def test_a_change_inside_the_window_goes_out_at_its_end_the_latest_state(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        """V05: two changes inside the window come to one send at its end,
        the latest; the wait holds no turn and no database connection."""
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise, spacing_seconds=SPACING)
        _ask(container, project_id)
        _reconcile(service, project_id)
        first = _sent_at(container, project_id)
        _ask(container, project_id, "Which site?")
        deferred = _reconciles("deferred")
        during: list[tuple[int, int, bool]] = []

        def in_the_window(waits: int) -> None:
            during.append(
                (
                    _checked_out(container),
                    len(bridge.calls("ada")),
                    _turn_free(container, project_id),
                )
            )
            if waits == 1:
                _ask(container, project_id, "Which stove?")

        service.reconcile(project_id, _Window(in_the_window))

        assert during[0] == (0, 1, True)
        assert [call.alerted for call in bridge.calls("ada")] == [True, False]
        assert _shown(bridge, project_id).message == "Which stove?, +2"
        assert _sent_at(container, project_id) - first >= timedelta(seconds=SPACING)
        assert _reconciles("deferred") >= deferred + 1

    def test_a_change_undone_inside_the_window_sends_nothing(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise, spacing_seconds=SPACING)
        _ask(container, project_id)
        _reconcile(service, project_id)
        site = _bear(container, project_id, "decision", "Which site?", DECISION)
        unchanged = _reconciles("unchanged")

        def answer(waits: int) -> None:
            if waits == 1:
                _answer(container, "ada", site, "Dome")

        service.reconcile(project_id, _Window(answer))

        assert bridge.calls("ada") == [FakeCall("submit", str(project_id), True)]
        assert _shown(bridge, project_id).message == "Which tent?"
        assert _reconciles("unchanged") == unchanged + 1

    def test_a_window_is_one_persons_in_one_project(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        """V05: Ada's window in Camp holds neither Ben's send in it nor hers in
        another project."""
        camp = _project(container, ("ada", "ben"))
        lake = _project(container, environment_id=None)
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise, spacing_seconds=SPACING)
        _ask(container, camp)
        _reconcile(service, camp)
        _give_token(container, "ben", BEN_TOKEN)
        _ask(container, camp, "Which site?")
        _ask(container, lake, "Which lake?")
        during: list[tuple[int, int]] = []

        def in_the_window(waits: int) -> None:
            if waits == 1:
                _reconcile(service, lake)
                during.append((len(bridge.calls("ada")), len(bridge.calls("ben"))))

        service.reconcile(camp, _Window(in_the_window))

        assert during == [(2, 1)]
        assert _shown(bridge, lake).message == "Which lake?"
        assert _shown(bridge, camp, "ben").message == "Which site?, +1"
        assert _shown(bridge, camp).message == "Which site?, +1"
        assert len(bridge.calls("ada")) == 3

    def test_a_rejoin_waits_for_the_window_of_the_dismiss_its_leave_sent(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container, ("ada", "ben"))
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise, spacing_seconds=SPACING)
        _ask(container, project_id)
        _reconcile(service, project_id)
        _leave(container, "ada", project_id)
        _reconcile(service, project_id)
        _join(container, "ada", project_id)
        calls: list[int] = []

        def in_the_window(waits: int) -> None:
            calls.append(len(bridge.calls("ada")))

        handle = _Window(in_the_window)
        service.reconcile(project_id, handle)

        assert [call.call for call in bridge.calls("ada")] == [
            "submit",
            "dismiss",
            "submit",
        ]
        assert calls[0] == 2
        assert _shown(bridge, project_id).message == "Which tent?"

    def test_a_stop_during_the_wait_leaves_the_send_owed_for_the_process_that_runs_on(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        """V05: a roll's old process drained inside the window sends nothing
        and leaves the send owed; the new one's retry timer sends the latest
        state."""
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        old, _, _ = _service(container, supervise, spacing_seconds=SPACING)
        new, new_supervisor, _ = _service(
            container, supervise, retry_seconds=0, spacing_seconds=SPACING
        )
        _ask(container, project_id)
        _reconcile(old, project_id)
        _ask(container, project_id, "Which site?")
        handle = _Window(lambda waits: handle._request_stop())

        old.reconcile(project_id, handle)

        assert len(handle.asked) == 1
        assert len(bridge.calls("ada")) == 1
        assert _owed(container, project_id)
        log.wait_for(
            rf"The submit of project {project_id}'s notification to ada is owed: "
            "the run stopped before it went out"
        )
        with patch.object(
            new_supervisor, "start_loop", wraps=new_supervisor.start_loop
        ) as start:
            with scoped_session(container) as db:
                new.retry(db)
        assert [(call.args[0], call.kwargs) for call in start.call_args_list] == [
            (NOTIFICATION_JOB, {"key": str(project_id), "again": False})
        ]
        _reconcile(new, project_id)

        assert [call.alerted for call in bridge.calls("ada")] == [True, False]
        assert _shown(bridge, project_id).message == "Which site?, +1"
        assert not _owed(container, project_id)

    def test_a_stop_before_a_persons_compare_leaves_their_send_owed(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise, spacing_seconds=SPACING)
        _ask(container, project_id)
        handle = LoopHandle("test")
        handle._request_stop()

        service.reconcile(project_id, handle)

        assert bridge.calls("ada") == []
        assert _owed(container, project_id)
        assert _last_sent(container, project_id) == (None, None)

    def test_two_processes_keep_one_window_and_send_once_at_its_end(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        """V05: the new process, which sent nothing yet, keeps the window of
        the old one's send, and of the two reconciles inside it one sends."""
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        old, _, _ = _service(container, supervise, spacing_seconds=SPACING)
        new, _, _ = _service(container, supervise, spacing_seconds=SPACING)
        _ask(container, project_id)
        _reconcile(old, project_id)
        first = _sent_at(container, project_id)
        _ask(container, project_id, "Which site?")
        during: list[int] = []

        def old_reconciles_too(waits: int) -> None:
            during.append(len(bridge.calls("ada")))
            if waits == 1:
                _ask(container, project_id, "Which stove?")
                _reconcile(old, project_id)

        new.reconcile(project_id, _Window(old_reconciles_too))

        assert during[0] == 1
        assert [call.call for call in bridge.calls("ada")] == ["submit"] * 2
        assert _shown(bridge, project_id).message == "Which stove?, +2"
        assert _sent_at(container, project_id) - first >= timedelta(seconds=SPACING)


class TestNotificationReconcileServiceBus:
    def test_a_project_changed_asks_for_its_reconcile_and_a_work_moved_alone_not(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        bus = EngineBus()
        _, supervisor, _ = _service(container, supervise, engine_bus=bus)
        project_id, work_id = uuid.uuid4(), uuid.uuid4()

        with patch.object(
            supervisor, "start_loop", wraps=supervisor.start_loop
        ) as start:
            with scoped_session(container):
                bus.emit(WorkMoved(project_id, work_id))
            with scoped_session(container):
                bus.emit(ProjectChanged(project_id))

        assert [(call.args[0], call.kwargs) for call in start.call_args_list] == [
            (NOTIFICATION_JOB, {"key": str(project_id), "again": True})
        ]

    def test_a_commit_is_reconciled_off_its_thread(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        _, _, coordinator = _service(
            container, supervise, engine_bus=container.engine_bus()
        )
        coordinator.fire_startup()
        log.wait_for(rf"Loop {NOTIFICATION_JOB}:{project_id} ended")
        bridge.unreachable(answer="stall")

        # The commit returns while the bridge holds the reconcile's call.
        item_id = _bear(container, project_id, "decision", "Which tent?", DECISION)

        log.wait_for(rf"Loop {NOTIFICATION_JOB}:{project_id} started", 2)
        bridge.unreachable(on=False)
        log.wait_for(rf"Loop {NOTIFICATION_JOB}:{project_id} ended", 2)
        assert _shown(bridge, project_id).url.endswith(f"/items/{item_id}")


class TestNotificationReconcileServiceProgress:
    def test_a_change_of_a_work_items_steps_sends_nothing(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        """F145.4, R7: the notification never names a work item's progress,
        so a change of it, heard on the bus and reconciled after, sends
        nothing. A question waits on Ada, so that her notification stands."""
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        _bear(container, project_id, "question", "Your boots?", QUESTION)
        worker = _running_work(container, project_id)
        service, _, _ = _service(
            container, supervise, engine_bus=container.engine_bus()
        )
        _reconcile(service, project_id)
        standing = bridge.calls("ada")
        assert standing != []
        lists = [
            [
                ProgressStepRequestSchema(
                    code="test", label="Test", state=ProgressState.ACTIVE
                ),
                ProgressStepRequestSchema(code="docs", label="Docs", state=None),
            ],
            [
                ProgressStepRequestSchema(
                    code="test", label="Test", state=ProgressState.DONE
                ),
                ProgressStepRequestSchema(
                    code="docs", label="Docs", state=ProgressState.ACTIVE
                ),
            ],
            [],
        ]

        for steps in lists:
            with scoped_session(container):
                container.pilot_work_service().set_progress(worker, steps)
            _reconcile(service, project_id)

        assert bridge.calls("ada") == standing


class TestNotificationReconcileServiceSubmitAll:
    def test_a_token_set_submits_the_current_state_whatever_was_last_sent(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container)
        archived = _project(container, environment_id=None)
        _bear(container, project_id, "decision", "Which tent?", DECISION)
        _ask(container, archived)
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise)
        _reconcile(service, project_id)
        _reconcile(service, archived)
        _transition(container, archived, TransitionKind.ARCHIVED)
        bridge.rotate_token("ada", "token-of-ada-rotated")

        _set(container, service, "ada", "token-of-ada-rotated")

        assert _last_sent(container, project_id) == (None, None)
        # An archived project's is left to its reconcile, through the token.
        assert _last_sent(container, archived)[0] is not None
        _reconcile(service, project_id)
        _reconcile(service, archived)
        assert [call.call for call in bridge.calls("ada")] == [
            "submit",
            "submit",
            "submit",
            "dismiss",
        ]
        assert set(bridge.shown("ada")) == {str(project_id)}
        assert _last_sent(container, project_id)[0] is not None

    def test_its_reconciles_are_asked_for_once_it_commits(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        project_id = _project(container)
        _bear(container, project_id, "decision", "Which tent?", DECISION)
        service, _, coordinator = _service(container, supervise)
        coordinator.fire_startup()

        _set(container, service, "ada", ADA_TOKEN)

        log.wait_for(rf"Loop {NOTIFICATION_JOB}:{project_id} ended")
        assert _shown(bridge, project_id).message == "Which tent?"


class TestNotificationReconcileServiceDismissAll:
    def test_a_clear_reads_dismissed_at_once_and_is_dismissed_once_off_the_request(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        standing = _project(container, environment_id=None)
        owed = _project(container, environment_id=None)
        _ask(container, standing)
        _ask(container, owed)
        _give_token(container, "ada", ADA_TOKEN)
        service, _, coordinator = _service(container, supervise)
        _reconcile(service, standing)
        bridge.unreachable()
        _reconcile(service, owed)
        bridge.unreachable(on=False)
        sent = _clear_dismisses("sent")

        _clear(container, service, "ada")

        for project_id in (standing, owed):
            assert _last_sent(container, project_id) == (None, None)
            assert not _owed(container, project_id)
        coordinator.fire_startup()
        log.wait_for(rf"Loop {NOTIFICATION_CLEAR_JOB}:1 ended")
        assert bridge.shown("ada") == {}
        assert sorted(call.sequence_id or "" for call in bridge.calls("ada")[1:]) == (
            sorted([str(standing), str(owed)])
        )
        assert _clear_dismisses("sent") == sent + 2

    def test_a_dismiss_the_bridge_does_not_take_is_logged_counted_and_not_owed(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        project_id = _project(container, environment_id=None)
        _ask(container, project_id)
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise)
        _reconcile(service, project_id)
        unanswered = _clear_dismisses("unanswered")
        bridge.unreachable()
        _clear(container, service, "ada")

        service.dismiss_cleared(
            _memberships(container, project_id)[0].user_id,
            ADA_TOKEN,
            (project_id,),
            LoopHandle("clear"),
        )

        log.wait_for(
            rf"The dismiss of project {project_id}'s notification to ada after their"
            r" token's clear failed, and it stays on the phone: .*"
        )
        assert _clear_dismisses("unanswered") == unanswered + 1
        assert not _owed(container, project_id)
        bridge.unreachable(on=False)
        assert set(bridge.shown("ada")) == {str(project_id)}

    def test_the_same_token_set_again_is_not_dismissed(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        project_id = _project(container, environment_id=None)
        _ask(container, project_id)
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise)
        _reconcile(service, project_id)
        _clear(container, service, "ada")
        _set(container, service, "ada", ADA_TOKEN)
        _reconcile(service, project_id)

        service.dismiss_cleared(
            _memberships(container, project_id)[0].user_id,
            ADA_TOKEN,
            (project_id,),
            LoopHandle("clear"),
        )

        assert [call.call for call in bridge.calls("ada")] == ["submit", "submit"]
        assert set(bridge.shown("ada")) == {str(project_id)}
        log.wait_for(
            "ada holds the token they cleared again: project"
            rf" {project_id}'s notification is not dismissed"
        )

    def test_with_no_bridge_the_record_alone_moves(
        self, container: ServiceContainer, supervise: Supervise
    ) -> None:
        project_id = _project(container, environment_id=None)
        _give_token(container, "ada", ADA_TOKEN)
        with scoped_session(container) as db:
            membership = db.scalars(
                select(ProjectMember).where(ProjectMember.project_id == project_id)
            ).one()
            membership.notification_text = "Which tent?"
            membership.notification_url = _timeline(container, project_id)
            membership.notification_sent_at = datetime.now(UTC)
        service, supervisor, _ = _service(container, supervise, configured=False)

        with patch.object(
            supervisor, "start_loop", wraps=supervisor.start_loop
        ) as start:
            _clear(container, service, "ada")
            _set(container, service, "ada", ADA_TOKEN)

        start.assert_not_called()
        assert _last_sent(container, project_id) == (None, None)


class TestNotificationReconcileServiceInFlight:
    def test_a_clear_during_a_first_submit_is_followed_by_its_dismiss(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        _bear(container, project_id, "decision", "Which tent?", DECISION)
        service, _, _ = _service(container, supervise)
        superseded, sent = _reconciles("superseded"), _clear_dismisses("sent")
        bridge.on_submit = lambda: _clear(container, service, "ada")

        _reconcile(service, project_id)

        assert bridge.calls("ada") == [
            FakeCall("submit", str(project_id), True),
            FakeCall("dismiss", str(project_id), False),
        ]
        assert bridge.shown("ada") == {}
        assert _last_sent(container, project_id) == (None, None)
        assert not _owed(container, project_id)
        assert _reconciles("superseded") == superseded + 1
        assert _clear_dismisses("sent") == sent + 1

    def test_a_clears_dismiss_waits_for_a_submit_in_flight(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        _bear(container, project_id, "decision", "Which tent?", DECISION)
        service, _, _ = _service(container, supervise)
        _reconcile(service, project_id)
        _bear(container, project_id, "decision", "Which site?", DECISION)
        person_id = _memberships(container, project_id)[0].user_id
        clears = []

        def clear() -> None:
            _clear(container, service, "ada")
            clears.append(
                in_thread(
                    lambda: service.dismiss_cleared(
                        person_id, ADA_TOKEN, (project_id,), LoopHandle("clear")
                    )
                )
            )
            wait_until(lambda: lock_waits(container) == 1, "the dismiss waiting")

        bridge.on_submit = clear

        _reconcile(service, project_id)
        clears[0].result()

        assert [call.call for call in bridge.calls("ada")] == [
            "submit",
            "submit",
            "dismiss",
            "dismiss",
        ]
        assert bridge.shown("ada") == {}
        assert _last_sent(container, project_id) == (None, None)

    @pytest.mark.parametrize("answered", [True, False])
    def test_a_clear_committing_during_the_write_back_reads_what_it_wrote(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
        log: LogWaiter,
        answered: bool,
    ) -> None:
        project_id = _project(container, environment_id=None)
        _ask(container, project_id)
        _give_token(container, "ada", ADA_TOKEN)
        service, _, coordinator = _service(container, supervise)
        if not answered:
            bridge.unreachable()
        take = service._take
        clears = []

        def take_then_clear(*args: Any) -> bool:
            cleared: bool = take(*args)
            container.db_session().flush()
            clears.append(in_thread(lambda: _clear(container, service, "ada")))
            wait_until(
                lambda: not clears[0].thread.is_alive() or lock_waits(container) == 1,
                "the clear committed or waiting",
            )
            return cleared

        with patch.object(service, "_take", side_effect=take_then_clear):
            _reconcile(service, project_id)
        clears[0].result()

        assert _last_sent(container, project_id) == (None, None)
        assert not _owed(container, project_id)
        _reconcile(service, project_id)
        bridge.unreachable(on=False)
        coordinator.fire_startup()
        log.wait_for(rf"Loop {NOTIFICATION_CLEAR_JOB}:1 ended")
        assert bridge.shown("ada") == {}
        assert [call.call for call in bridge.calls("ada")][-1] == "dismiss"

    def test_a_replace_during_a_submit_is_resubmitted_through_the_new_token(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        _bear(container, project_id, "decision", "Which tent?", DECISION)
        service, _, _ = _service(container, supervise)

        def replace() -> None:
            bridge.rotate_token("ada", "token-of-ada-rotated")
            _set(container, service, "ada", "token-of-ada-rotated")

        bridge.on_submit = replace

        _reconcile(service, project_id)
        assert _last_sent(container, project_id) == (None, None)
        _reconcile(service, project_id)

        assert [call.call for call in bridge.calls("ada")] == ["submit", "submit"]
        assert _last_sent(container, project_id)[0] is not None

    def test_two_processes_take_turns_and_the_phone_ends_on_the_latest_state(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        old, _, _ = _service(container, supervise)
        new, _, _ = _service(container, supervise)
        _bear(container, project_id, "decision", "Which tent?", DECISION)
        _reconcile(old, project_id)
        _bear(container, project_id, "decision", "Which site?", DECISION)
        turns = []

        def change_and_reconcile_in_the_other() -> None:
            _bear(container, project_id, "decision", "Which stove?", DECISION)
            turns.append(in_thread(lambda: _reconcile(new, project_id)))
            wait_until(lambda: lock_waits(container) == 1, "the other's turn waiting")

        bridge.on_submit = change_and_reconcile_in_the_other

        _reconcile(old, project_id)
        turns[0].result()

        assert [call.call for call in bridge.calls("ada")] == ["submit"] * 3
        assert _shown(bridge, project_id).message == "Which stove?, +2"
        assert _last_sent(container, project_id)[0] == "Which stove?, +2"
