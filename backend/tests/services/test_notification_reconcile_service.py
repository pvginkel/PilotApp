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
from sqlalchemy import select
from werkzeug.wrappers import Request, Response

from app.database import scoped_session
from app.engine.bus import EngineBus, ProjectChanged, WorkMoved
from app.models import ProjectMember, User
from app.models.reference import NotificationPriority, TransitionKind
from app.schemas.testing_record import InventedProjectCreateSchema
from app.services.auth_service import AuthContext
from app.services.container import ServiceContainer
from app.services.fake_notification_bridge import FakeCall, FakeNotification
from app.services.notification_reconcile_service import (
    NOTIFICATION_CLEAR_DISMISSES_TOTAL,
    NOTIFICATION_CLEAR_JOB,
    NOTIFICATION_JOB,
    NOTIFICATION_RECONCILES_TOTAL,
    NotificationReconcileService,
)
from app.services.supervisor import LoopHandle, Supervisor
from app.utils.after_commit import clear_after_commit_callbacks
from app.utils.lifecycle_coordinator import LifecycleCoordinator
from tests.support.fake_notification_bridge import (
    ServedFakeNotificationBridge,
    bridge_client_of,
)
from tests.support.locks import in_thread, lock_waits
from tests.support.supervisor import (
    LogWaiter,
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


class _Watched(ServedFakeNotificationBridge):
    """The fake, which runs `on_submit` once, after it took the next submit
    and before it answers it: a submit in flight."""

    def __init__(self) -> None:
        super().__init__()
        self.on_submit: Callable[[], None] | None = None
        self.failures: list[BaseException] = []

    def _respond(self, request: Request) -> Response:
        response = super()._respond(request)
        hook = self.on_submit
        if hook is not None and request.path == "/v1/submit":
            self.on_submit = None
            try:
                hook()
            except BaseException as error:
                self.failures.append(error)
        return response


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
def bridge(container: ServiceContainer) -> Iterator[_Watched]:
    """The fake bridge, the container's client on it, with a registration for
    Ada and one for Ben."""
    fake = _Watched()
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
    configured: bool = True,
) -> tuple[NotificationReconcileService, Supervisor, LifecycleCoordinator]:
    """The reconcile on a supervisor of its own, hearing `engine_bus`: a bus
    of its own unless one is given."""
    supervisor, coordinator = supervise(container)
    service = NotificationReconcileService(
        container=container,
        supervisor=supervisor,
        engine_bus=EngineBus() if engine_bus is None else engine_bus,
        notification_token_cipher=container.notification_token_cipher(),
        bridge_configured=configured,
        retry_seconds=retry_seconds,
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
    **front_matter: str,
) -> uuid.UUID:
    """A prose item the project's session adds, committed."""
    header = "".join(f"{key}: {value}\n" for key, value in front_matter.items())
    with scoped_session(container):
        return (
            container.test_data_service()
            .item(
                project_id, kind, title, f"---\ntitle: {title}\n{header}---\n\n{text}"
            )
            .id
        )


def _answer(
    container: ServiceContainer, handle: str, item_id: uuid.UUID, answer: str
) -> None:
    with scoped_session(container):
        container.item_service().answer(
            _auth(_person(container, handle)), item_id, "D1", answer, None
        )


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
) -> tuple[NotificationPriority | None, str | None, str | None]:
    membership = _memberships(container, project_id, handle)[-1]
    return (
        membership.notification_priority_code,
        membership.notification_text,
        membership.notification_url,
    )


def _owed(container: ServiceContainer, project_id: uuid.UUID) -> bool:
    return any(
        membership.notification_owed_at is not None
        for membership in _memberships(container, project_id)
    )


def _timeline(container: ServiceContainer, project_id: uuid.UUID) -> str:
    return f"{container.config().baseurl}/projects/{project_id}"


def _shown(
    bridge: _Watched, project_id: uuid.UUID, name: str = "ada"
) -> FakeNotification:
    return bridge.shown(name)[str(project_id)]


def _reconciles(outcome: str) -> float:
    return metric_value(NOTIFICATION_RECONCILES_TOTAL, outcome=outcome)


def _clear_dismisses(outcome: str) -> float:
    return metric_value(NOTIFICATION_CLEAR_DISMISSES_TOTAL, outcome=outcome)


class TestNotificationReconcileServiceReconcile:
    def test_a_member_holding_a_token_is_submitted_the_projects_standing(
        self, container: ServiceContainer, bridge: _Watched, supervise: Supervise
    ) -> None:
        project_id = _project(container, ("ada", "ben"))
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise)
        sent, unchanged = _reconciles("sent"), _reconciles("unchanged")

        _reconcile(service, project_id)

        assert bridge.shown("ada") == {
            str(project_id): FakeNotification(
                sequence_id=str(project_id),
                priority="min",
                title="Camp",
                message="Not started",
                url=_timeline(container, project_id),
                alerted=False,
            )
        }
        assert bridge.calls("ben") == []
        [membership] = _memberships(container, project_id)
        assert (
            membership.notification_priority_code,
            membership.notification_text,
            membership.notification_url,
            membership.notification_owed_at,
        ) == (
            NotificationPriority.MIN,
            "Not started",
            _timeline(container, project_id),
            None,
        )
        assert membership.notification_sent_at is not None
        assert _reconciles("sent") == sent + 1
        # Ben, a member with no token: nothing to see, nothing sent.
        assert _reconciles("unchanged") == unchanged + 1

    def test_what_was_last_sent_is_not_sent_again(
        self, container: ServiceContainer, bridge: _Watched, supervise: Supervise
    ) -> None:
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise)
        _reconcile(service, project_id)
        sent_at = _memberships(container, project_id)[0].notification_sent_at
        unchanged = _reconciles("unchanged")

        _reconcile(service, project_id)

        assert bridge.calls("ada") == [FakeCall("submit", str(project_id), False)]
        assert _memberships(container, project_id)[0].notification_sent_at == sent_at
        assert _reconciles("unchanged") == unchanged + 1

    def test_a_rise_alerts_and_every_other_change_is_silent(
        self, container: ServiceContainer, bridge: _Watched, supervise: Supervise
    ) -> None:
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise)
        _reconcile(service, project_id)

        tent = _bear(container, project_id, "decision", "Which tent?", DECISION)
        _reconcile(service, project_id)
        assert _shown(bridge, project_id) == FakeNotification(
            sequence_id=str(project_id),
            priority="default",
            title="Camp",
            message="Not started · Decision waiting: Which tent?",
            url=f"{_timeline(container, project_id)}/items/{tent}",
            alerted=True,
        )

        site = _bear(container, project_id, "decision", "Which site?", DECISION)
        _reconcile(service, project_id)
        shown = _shown(bridge, project_id)
        assert (shown.priority, shown.message, shown.url, shown.alerted) == (
            "default",
            "Not started · 2 waiting",
            _timeline(container, project_id),
            False,
        )

        _bear(
            container, project_id, "decision", "Storm shelter?", DECISION, urgent="true"
        )
        _reconcile(service, project_id)
        shown = _shown(bridge, project_id)
        assert (shown.priority, shown.message, shown.alerted) == (
            "high",
            "Not started · 3 waiting",
            True,
        )

        _answer(container, "ada", tent, "Dome")
        _answer(container, "ada", site, "Dome")
        _reconcile(service, project_id)
        shown = _shown(bridge, project_id)
        assert (shown.priority, shown.message, shown.alerted) == (
            "high",
            "Not started · Decision waiting: Storm shelter?",
            False,
        )
        assert [call.alerted for call in bridge.calls("ada")] == [
            False,
            True,
            False,
            True,
            False,
        ]
        assert _last_sent(container, project_id) == (
            NotificationPriority.HIGH,
            "Not started · Decision waiting: Storm shelter?",
            shown.url,
        )

    def test_an_answer_drops_the_priority_back_silently(
        self, container: ServiceContainer, bridge: _Watched, supervise: Supervise
    ) -> None:
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise)
        tent = _bear(container, project_id, "decision", "Which tent?", DECISION)
        _reconcile(service, project_id)

        _answer(container, "ada", tent, "Dome")
        _reconcile(service, project_id)

        shown = _shown(bridge, project_id)
        assert (shown.priority, shown.message, shown.alerted) == (
            "min",
            "Not started",
            False,
        )

    def test_an_item_for_one_member_rises_theirs_alone(
        self, container: ServiceContainer, bridge: _Watched, supervise: Supervise
    ) -> None:
        project_id = _project(container, ("ada", "ben"))
        _give_token(container, "ada", ADA_TOKEN)
        _give_token(container, "ben", BEN_TOKEN)
        service, _, _ = _service(container, supervise)
        _reconcile(service, project_id)

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
        assert (ben.priority, ben.message, ben.alerted) == (
            "high",
            "Not started · Question waiting: Your boots?",
            True,
        )
        ada = _shown(bridge, project_id, "ada")
        assert (ada.priority, ada.message, ada.alerted) == (
            "min",
            "Not started · 1 waiting on ben",
            False,
        )

    def test_leave_dismisses_and_a_rejoin_submits_afresh(
        self, container: ServiceContainer, bridge: _Watched, supervise: Supervise
    ) -> None:
        project_id = _project(container, ("ada", "ben"))
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise)
        _reconcile(service, project_id)
        submitted_at = _memberships(container, project_id)[0].notification_sent_at
        assert submitted_at is not None

        _leave(container, "ada", project_id)
        _reconcile(service, project_id)

        assert bridge.shown("ada") == {}
        [closed] = _memberships(container, project_id)
        assert _last_sent(container, project_id) == (None, None, None)
        assert closed.notification_sent_at is not None
        assert closed.notification_sent_at > submitted_at

        _join(container, "ada", project_id)
        _reconcile(service, project_id)

        assert _shown(bridge, project_id).message == "Not started"
        assert [call.call for call in bridge.calls("ada")] == [
            "submit",
            "dismiss",
            "submit",
        ]
        closed, rejoined = _memberships(container, project_id)
        assert closed.notification_priority_code is None
        assert rejoined.notification_priority_code is NotificationPriority.MIN

    def test_archive_dismisses_and_bring_back_submits(
        self, container: ServiceContainer, bridge: _Watched, supervise: Supervise
    ) -> None:
        project_id = _project(container, environment_id=None)
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise)
        _reconcile(service, project_id)

        _transition(container, project_id, TransitionKind.ARCHIVED)
        _reconcile(service, project_id)
        assert bridge.shown("ada") == {}
        assert _last_sent(container, project_id) == (None, None, None)

        _transition(container, project_id, TransitionKind.BROUGHT_BACK)
        _reconcile(service, project_id)
        assert _shown(bridge, project_id).message == "Not started"
        assert _last_sent(container, project_id)[0] is NotificationPriority.MIN

    def test_a_draft_and_a_finished_project_hold_theirs(
        self, container: ServiceContainer, bridge: _Watched, supervise: Supervise
    ) -> None:
        draft = _project(container, environment_id=None, state="draft")
        finished = _project(container, environment_id=None, state="finished")
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise)

        _reconcile(service, draft)
        _reconcile(service, finished)

        assert _shown(bridge, draft).message == "Draft"
        assert _shown(bridge, finished).message.startswith("Finished")


class TestNotificationReconcileServiceOwed:
    def test_a_send_the_bridge_does_not_answer_is_owed_and_logged_once(
        self,
        container: ServiceContainer,
        bridge: _Watched,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise)
        owed = _reconciles("owed")
        bridge.unreachable()

        _reconcile(service, project_id)
        _reconcile(service, project_id)

        assert _owed(container, project_id)
        assert _last_sent(container, project_id) == (None, None, None)
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
        assert _last_sent(container, project_id)[0] is NotificationPriority.MIN
        log.wait_for(
            rf"The owed submit of project {project_id}'s notification to ada went out"
        )

    def test_a_refused_token_is_owed(
        self,
        container: ServiceContainer,
        bridge: _Watched,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise)
        bridge.rotate_token("ada", "a-rotated-token")

        _reconcile(service, project_id)

        assert _owed(container, project_id)
        log.wait_for(rf"The submit of project {project_id}'s .* is owed: .*401.*")

    def test_an_owed_send_is_sent_again_with_nothing_else_changed(
        self, container: ServiceContainer, bridge: _Watched, supervise: Supervise
    ) -> None:
        project_id = _project(container, ("ada", "ben"))
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise)
        _reconcile(service, project_id)
        bridge.unreachable()
        _leave(container, "ada", project_id)
        _reconcile(service, project_id)
        assert _owed(container, project_id)
        assert _last_sent(container, project_id)[0] is NotificationPriority.MIN

        bridge.unreachable(on=False)
        _reconcile(service, project_id)

        assert bridge.shown("ada") == {}
        assert not _owed(container, project_id)
        assert _last_sent(container, project_id) == (None, None, None)

    def test_a_rejoin_takes_the_place_of_an_owed_dismiss(
        self, container: ServiceContainer, bridge: _Watched, supervise: Supervise
    ) -> None:
        project_id = _project(container, ("ada", "ben"))
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise)
        _reconcile(service, project_id)
        bridge.unreachable()
        _leave(container, "ada", project_id)
        _reconcile(service, project_id)
        bridge.unreachable(on=False)

        _join(container, "ada", project_id)
        _reconcile(service, project_id)

        assert _shown(bridge, project_id).message == "Not started"
        assert [call.call for call in bridge.calls("ada")] == ["submit", "submit"]
        closed, rejoined = _memberships(container, project_id)
        assert (closed.notification_priority_code, closed.notification_owed_at) == (
            None,
            None,
        )
        assert (rejoined.notification_priority_code, rejoined.notification_owed_at) == (
            NotificationPriority.MIN,
            None,
        )


class TestNotificationReconcileServiceRetry:
    def test_the_timer_asks_for_the_projects_owed_past_their_retry(
        self, container: ServiceContainer, bridge: _Watched, supervise: Supervise
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
        bridge: _Watched,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        _, _, coordinator = _service(container, supervise, retry_seconds=0)
        bridge.unreachable()

        coordinator.fire_startup()
        log.wait_for(rf"The submit of project {project_id}'s notification .* owed: .*")
        bridge.unreachable(on=False)

        log.wait_for(
            rf"The owed submit of project {project_id}'s notification to ada went out"
        )
        assert _shown(bridge, project_id).message == "Not started"


class TestNotificationReconcileServiceStartup:
    def test_startup_reconciles_what_stands_is_owed_or_should_stand(
        self,
        container: ServiceContainer,
        bridge: _Watched,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        unsent = _project(container)
        archived = _project(container, environment_id=None)
        left = _project(container, ("ada", "ben"), environment_id=None)
        untouched = _project(container, ("ben",), environment_id=None)
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
                priority="min",
                title="Camp",
                message="Not started",
                url=_timeline(container, unsent),
                alerted=False,
            )
        }
        assert log.matching(rf"Loop {NOTIFICATION_JOB}:{untouched} .*") == []


class TestNotificationReconcileServiceBus:
    def test_a_project_changed_asks_for_its_reconcile_and_a_work_moved_alone_not(
        self, container: ServiceContainer, bridge: _Watched, supervise: Supervise
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
        bridge: _Watched,
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


class TestNotificationReconcileServiceSubmitAll:
    def test_a_token_set_submits_the_current_state_whatever_was_last_sent(
        self, container: ServiceContainer, bridge: _Watched, supervise: Supervise
    ) -> None:
        project_id = _project(container)
        archived = _project(container, environment_id=None)
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise)
        _reconcile(service, project_id)
        _reconcile(service, archived)
        _transition(container, archived, TransitionKind.ARCHIVED)
        bridge.rotate_token("ada", "token-of-ada-rotated")

        _set(container, service, "ada", "token-of-ada-rotated")

        assert _last_sent(container, project_id) == (None, None, None)
        # An archived project's is left to its reconcile, through the token.
        assert _last_sent(container, archived)[0] is NotificationPriority.MIN
        _reconcile(service, project_id)
        _reconcile(service, archived)
        assert [call.call for call in bridge.calls("ada")] == [
            "submit",
            "submit",
            "submit",
            "dismiss",
        ]
        assert set(bridge.shown("ada")) == {str(project_id)}
        assert _last_sent(container, project_id)[0] is NotificationPriority.MIN

    def test_its_reconciles_are_asked_for_once_it_commits(
        self,
        container: ServiceContainer,
        bridge: _Watched,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        project_id = _project(container)
        service, _, coordinator = _service(container, supervise)
        coordinator.fire_startup()

        _set(container, service, "ada", ADA_TOKEN)

        log.wait_for(rf"Loop {NOTIFICATION_JOB}:{project_id} ended")
        assert _shown(bridge, project_id).message == "Not started"


class TestNotificationReconcileServiceDismissAll:
    def test_a_clear_reads_dismissed_at_once_and_is_dismissed_once_off_the_request(
        self,
        container: ServiceContainer,
        bridge: _Watched,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        standing = _project(container, environment_id=None)
        owed = _project(container, environment_id=None)
        _give_token(container, "ada", ADA_TOKEN)
        service, _, coordinator = _service(container, supervise)
        _reconcile(service, standing)
        bridge.unreachable()
        _reconcile(service, owed)
        bridge.unreachable(on=False)
        sent = _clear_dismisses("sent")

        _clear(container, service, "ada")

        for project_id in (standing, owed):
            assert _last_sent(container, project_id) == (None, None, None)
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
        bridge: _Watched,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        project_id = _project(container, environment_id=None)
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
        bridge: _Watched,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        project_id = _project(container, environment_id=None)
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
            membership.notification_priority_code = NotificationPriority.MIN
            membership.notification_text = "Not started"
            membership.notification_url = _timeline(container, project_id)
            membership.notification_sent_at = datetime.now(UTC)
        service, supervisor, _ = _service(container, supervise, configured=False)

        with patch.object(
            supervisor, "start_loop", wraps=supervisor.start_loop
        ) as start:
            _clear(container, service, "ada")
            _set(container, service, "ada", ADA_TOKEN)

        start.assert_not_called()
        assert _last_sent(container, project_id) == (None, None, None)


class TestNotificationReconcileServiceInFlight:
    def test_a_clear_during_a_first_submit_is_followed_by_its_dismiss(
        self, container: ServiceContainer, bridge: _Watched, supervise: Supervise
    ) -> None:
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise)
        superseded, sent = _reconciles("superseded"), _clear_dismisses("sent")
        bridge.on_submit = lambda: _clear(container, service, "ada")

        _reconcile(service, project_id)

        assert bridge.calls("ada") == [
            FakeCall("submit", str(project_id), False),
            FakeCall("dismiss", str(project_id), False),
        ]
        assert bridge.shown("ada") == {}
        assert _last_sent(container, project_id) == (None, None, None)
        assert not _owed(container, project_id)
        assert _reconciles("superseded") == superseded + 1
        assert _clear_dismisses("sent") == sent + 1

    def test_a_clears_dismiss_waits_for_a_submit_in_flight(
        self, container: ServiceContainer, bridge: _Watched, supervise: Supervise
    ) -> None:
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise)
        _reconcile(service, project_id)
        _bear(container, project_id, "decision", "Which tent?", DECISION)
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
        assert _last_sent(container, project_id) == (None, None, None)

    def test_a_replace_during_a_submit_is_resubmitted_through_the_new_token(
        self, container: ServiceContainer, bridge: _Watched, supervise: Supervise
    ) -> None:
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _ = _service(container, supervise)

        def replace() -> None:
            bridge.rotate_token("ada", "token-of-ada-rotated")
            _set(container, service, "ada", "token-of-ada-rotated")

        bridge.on_submit = replace

        _reconcile(service, project_id)
        assert _last_sent(container, project_id) == (None, None, None)
        _reconcile(service, project_id)

        assert [call.call for call in bridge.calls("ada")] == ["submit", "submit"]
        assert _last_sent(container, project_id)[0] is NotificationPriority.MIN

    def test_two_processes_take_turns_and_the_phone_ends_on_the_latest_state(
        self, container: ServiceContainer, bridge: _Watched, supervise: Supervise
    ) -> None:
        project_id = _project(container)
        _give_token(container, "ada", ADA_TOKEN)
        old, _, _ = _service(container, supervise)
        new, _, _ = _service(container, supervise)
        _reconcile(old, project_id)
        _bear(container, project_id, "decision", "Which tent?", DECISION)
        turns = []

        def change_and_reconcile_in_the_other() -> None:
            _bear(container, project_id, "decision", "Which site?", DECISION)
            turns.append(in_thread(lambda: _reconcile(new, project_id)))
            wait_until(lambda: lock_waits(container) == 1, "the other's turn waiting")

        bridge.on_submit = change_and_reconcile_in_the_other

        _reconcile(old, project_id)
        turns[0].result()

        assert [call.call for call in bridge.calls("ada")] == ["submit"] * 3
        assert _shown(bridge, project_id).message == "Not started · 2 waiting"
        assert _last_sent(container, project_id)[1] == "Not started · 2 waiting"
