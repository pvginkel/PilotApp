"""A member's notification of a project (F94, F147; DB 157, 224 to 226, 307
to 315; DB decision 74; V09 to V12, V14): a push to every browser of theirs,
under the project's id, while they are offline, alerting for an item that
waits on them they have not been shown and silent once one they were shown
stopped waiting, on the fake push service.

Every test is on a database of its own: a member's turn is an advisory lock on
a connection of its own, which reads committed rows alone. A loop's run is
called as its loop calls it; the loops themselves run where a test fires
STARTUP."""

import threading
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import Integer, cast, func, literal, select
from sqlalchemy.pool import QueuePool

from app import models
from app.database import scoped_session
from app.engine.bus import EngineBus, ProjectChanged, WorkMoved
from app.models import AppPage, ItemSighting, Project, ProjectMember, User
from app.models.reference import (
    ProgressState,
    SessionState,
    TaskStatus,
    TransitionKind,
)
from app.schemas.pilot_work import ProgressStepRequestSchema
from app.schemas.testing_record import InventedProjectCreateSchema
from app.services.advisory_turn import turn_key
from app.services.app_page_service import EXPIRY_SECONDS, AppPageService
from app.services.auth_service import AuthContext
from app.services.container import ServiceContainer
from app.services.fake_push_service import FakePush, FakeSubscription
from app.services.notification_reconcile_service import (
    NOTIFICATION_JOB,
    NOTIFICATION_LOCK,
    NOTIFICATION_PERSON_JOB,
    NotificationReconcileService,
)
from app.services.pilot_work_service import Worker
from app.services.push_subscription_service import PushSubscriptionService
from app.services.supervisor import LoopHandle, Supervisor
from app.services.web_push import WEB_PUSH_SENDS_TOTAL, WebPushService
from app.utils.after_commit import clear_after_commit_callbacks
from app.utils.lifecycle_coordinator import LifecycleCoordinator
from tests.support.fake_push_service import ServedFakePushService
from tests.support.locks import in_thread, lock_waits, pool_capacity
from tests.support.supervisor import (
    WAIT_SECONDS,
    LogWaiter,
    RoundsHandle,
    Supervise,
    listening,
    metric_value,
    wait_until,
)

ENV = "env-a"
LOGGER = "app.services.notification_reconcile_service"
SUPERVISOR_LOGGER = "app.services.supervisor"

DECISION = "```decision id=D1\noptions:\n  - Dome\n  - Tunnel\n```\n"
QUESTION = "```question id=Q1\n```\n"

SPACING = 1.0
"""A member's window between two pushes in one project, in the tests of it."""


@dataclass(frozen=True)
class _Built:
    service: NotificationReconcileService
    supervisor: Supervisor
    coordinator: LifecycleCoordinator
    pages: AppPageService


@pytest.fixture(autouse=True)
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


@pytest.fixture
def container(committed_app: Flask) -> ServiceContainer:
    """The committed app's container, with Ada, Ben, Cal and an environment."""
    container: ServiceContainer = committed_app.container
    with scoped_session(container):
        data = container.test_data_service()
        data.person("ada", "Ada Example")
        data.person("ben", "Ben Example")
        data.person("cal", "Cal Example")
        data.environment(ENV, "Env-A")
    return container


@pytest.fixture
def browsers(
    container: ServiceContainer,
    fake_push_service: ServedFakePushService,
    web_push_service: WebPushService,
) -> dict[str, FakeSubscription]:
    """A browser of Ada's and one of Ben's, each subscribed; Cal has none."""
    return {
        handle: _subscribe(container, fake_push_service, web_push_service, handle)
        for handle in ("ada", "ben")
    }


@pytest.fixture
def log() -> Iterator[LogWaiter]:
    with listening(LOGGER, SUPERVISOR_LOGGER) as waiter:
        yield waiter


def _service(
    container: ServiceContainer,
    supervise: Supervise,
    web_push_service: WebPushService,
    *,
    engine_bus: EngineBus | None = None,
    spacing_seconds: float | None = 0.0,
) -> _Built:
    """The reconcile on a supervisor of its own, hearing `engine_bus`, a bus
    of its own unless one is given, and the pages on the same supervisor. No
    window between a member's pushes unless `spacing_seconds` gives one; none
    for the service's own."""
    supervisor, coordinator = supervise(container)
    pages = AppPageService(supervisor)
    spacing = {} if spacing_seconds is None else {"spacing_seconds": spacing_seconds}
    service = NotificationReconcileService(
        container=container,
        supervisor=supervisor,
        engine_bus=EngineBus() if engine_bus is None else engine_bus,
        app_page_service=pages,
        web_push_service=web_push_service,
        **spacing,
    )
    return _Built(service, supervisor, coordinator, pages)


def _reconcile(built: _Built, project_id: uuid.UUID) -> None:
    built.service.reconcile(project_id, LoopHandle("test"))


def _reconcile_person(
    container: ServiceContainer, built: _Built, handle: str = "ada"
) -> None:
    built.service.reconcile_person(_person_id(container, handle), LoopHandle("test"))


def _person(container: ServiceContainer, handle: str) -> User:
    return (
        container.db_session().scalars(select(User).where(User.handle == handle)).one()
    )


def _person_id(container: ServiceContainer, handle: str) -> uuid.UUID:
    with scoped_session(container):
        return _person(container, handle).id


def _auth(person: User) -> AuthContext:
    assert person.subject is not None
    return AuthContext(subject=person.subject, email=None, name=None, roles=set())


def _subscribe(
    container: ServiceContainer,
    fake: ServedFakePushService,
    web_push_service: WebPushService,
    handle: str,
) -> FakeSubscription:
    """A browser of the person's, subscribed as their switch subscribes it."""
    browser = fake.browser(web_push_service.public_key or "")
    with scoped_session(container):
        PushSubscriptionService(container.db_session()).subscribe(
            _person(container, handle),
            browser.endpoint,
            browser.keys.p256dh,
            browser.keys.auth,
        )
    return browser


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


def _work(
    container: ServiceContainer,
    project_id: uuid.UUID,
    state: SessionState = SessionState.RUNNING,
) -> Worker:
    """A work item of the project, its session in `state` in the environment,
    committed: its worker."""
    with scoped_session(container) as db:
        run = models.Session(
            project_id=project_id,
            environment_id=ENV,
            kind_code="work",
            cwd="/work/Camp",
            token_hash=uuid.uuid4().hex * 2,
            state_code=state,
        )
        db.add(run)
        db.flush()
        container.record_service().place_work(
            db.get_one(Project, project_id), run, "Building the camp"
        )
        return Worker(run.id, project_id, ENV, run.id)


def _set_state(
    container: ServiceContainer, worker: Worker, state: SessionState
) -> None:
    with scoped_session(container) as db:
        db.get_one(models.Session, worker.session_id).state_code = state


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


def _page(
    container: ServiceContainer,
    handle: str = "ada",
    project_id: uuid.UUID | None = None,
    *,
    beat_at: datetime | None = None,
) -> uuid.UUID:
    """A page of the person's on `project_id`, or on none, its beat `beat_at`,
    now by default, committed with nothing told; its id."""
    with scoped_session(container) as db:
        page = AppPage(
            user_id=_person(container, handle).id,
            project_id=project_id,
            beat_at=beat_at or datetime.now(UTC),
        )
        db.add(page)
        db.flush()
        return page.id


def _gone(container: ServiceContainer, page_id: uuid.UUID) -> None:
    """The page deleted, with nothing told."""
    with scoped_session(container) as db:
        db.delete(db.get_one(AppPage, page_id))


def _begin(
    container: ServiceContainer,
    built: _Built,
    handle: str,
    project_id: uuid.UUID | None,
) -> uuid.UUID:
    """A page's first beat, as its person's browser sends it, committed."""
    with scoped_session(container):
        return built.pages.begin(
            container.db_session(), _person(container, handle), project_id
        )


def _away(
    container: ServiceContainer, built: _Built, handle: str, page_id: uuid.UUID
) -> None:
    """The page's away, as its person's browser sends it, committed."""
    with scoped_session(container):
        built.pages.away(container.db_session(), _person(container, handle), page_id)


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


def _seen(
    container: ServiceContainer, project_id: uuid.UUID, handle: str = "ada"
) -> set[uuid.UUID]:
    """The items the person's memberships of the project were shown."""
    with scoped_session(container) as db:
        return set(
            db.scalars(
                select(ItemSighting.item_id)
                .join(ProjectMember, ProjectMember.id == ItemSighting.member_id)
                .join(User, User.id == ProjectMember.user_id)
                .where(ProjectMember.project_id == project_id, User.handle == handle)
            )
        )


def _sent_at(
    container: ServiceContainer, project_id: uuid.UUID, handle: str = "ada"
) -> datetime | None:
    return _memberships(container, project_id, handle)[-1].notification_sent_at


def _timeline(container: ServiceContainer, project_id: uuid.UUID) -> str:
    return f"{container.config().baseurl}/projects/{project_id}"


def _push(
    container: ServiceContainer,
    project_id: uuid.UUID,
    body: str,
    item_id: uuid.UUID | None = None,
    *,
    alert: bool = True,
) -> FakePush:
    """The project's push carrying `body`, as the browser decrypts it: its
    `url` the item's, else the timeline."""
    timeline = _timeline(container, project_id)
    return FakePush(
        title="Camp",
        body=body,
        tag=str(project_id),
        url=timeline if item_id is None else f"{timeline}/items/{item_id}",
        renotify=alert,
        urgency="high" if alert else "normal",
        ttl=86400,
    )


def _pushes(fake: ServedFakePushService, browser: FakeSubscription) -> list[FakePush]:
    return fake.pushes(browser.endpoint)


def _checked_out(container: ServiceContainer) -> int:
    """The app's pooled database connections in use."""
    pool = container.session_maker().kw["bind"].pool
    assert isinstance(pool, QueuePool)
    return pool.checkedout()


def _turn_free(container: ServiceContainer, project_id: uuid.UUID) -> bool:
    """Whether Ada's turn in the project is free: taken and let go at once,
    on a session of its own."""
    person_id = _memberships(container, project_id)[0].user_id
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


def _started(built: _Built, log: LogWaiter, *project_ids: uuid.UUID) -> None:
    """STARTUP fired, and the reconciles it asked for of `project_ids`
    ended."""
    built.coordinator.fire_startup()
    for project_id in project_ids:
        log.wait_for(rf"Loop {NOTIFICATION_JOB}:{project_id} ended")


class TestNotificationReconcileServiceReconcile:
    def test_an_item_waiting_unshown_alerts_every_member_with_a_browser(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container, ("ada", "ben", "cal"))
        built = _service(container, supervise, web_push_service)

        _reconcile(built, project_id)

        assert _pushes(fake_push_service, browsers["ada"]) == []

        tent = _bear(container, project_id, "decision", "Which tent?", DECISION)
        _reconcile(built, project_id)

        alert = _push(container, project_id, "Which tent?", tent)
        assert _pushes(fake_push_service, browsers["ada"]) == [alert]
        assert _pushes(fake_push_service, browsers["ben"]) == [alert]
        assert _seen(container, project_id) == {tent}
        assert _sent_at(container, project_id) is not None
        # Cal, a member with no browser: nothing pushed, nothing shown.
        assert _seen(container, project_id, "cal") == set()
        assert _sent_at(container, project_id, "cal") is None

    def test_what_they_were_shown_is_not_pushed_again(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container)
        _ask(container, project_id)
        built = _service(container, supervise, web_push_service)
        _reconcile(built, project_id)
        sent_at = _sent_at(container, project_id)

        _reconcile(built, project_id)

        assert len(_pushes(fake_push_service, browsers["ada"])) == 1
        assert _sent_at(container, project_id) == sent_at

    def test_each_item_come_to_wait_alerts_naming_the_latest(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container)
        built = _service(container, supervise, web_push_service)
        tent = _bear(container, project_id, "decision", "Which tent?", DECISION)
        _reconcile(built, project_id)
        site = _bear(container, project_id, "decision", "Which site?", DECISION)
        _reconcile(built, project_id)
        storm = _bear(
            container, project_id, "decision", "Storm shelter?", DECISION, urgent="true"
        )

        _reconcile(built, project_id)

        assert _pushes(fake_push_service, browsers["ada"]) == [
            _push(container, project_id, "Which tent?", tent),
            _push(container, project_id, "Which site?, +1"),
            _push(container, project_id, "Storm shelter?, +2"),
        ]
        assert _seen(container, project_id) == {tent, site, storm}

    def test_one_they_were_shown_stopping_with_another_waiting_updates_silently(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container)
        built = _service(container, supervise, web_push_service)
        tent = _bear(container, project_id, "decision", "Which tent?", DECISION)
        site = _bear(container, project_id, "decision", "Which site?", DECISION)
        _reconcile(built, project_id)

        # The member's own answer updates it, silently.
        _answer(container, "ada", tent, "Dome")
        _reconcile(built, project_id)

        assert _pushes(fake_push_service, browsers["ada"]) == [
            _push(container, project_id, "Which site?, +1"),
            _push(container, project_id, "Which site?", site, alert=False),
        ]
        assert _seen(container, project_id) == {site}

    def test_the_last_answered_pushes_nothing_and_the_next_alerts_anew(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container)
        built = _service(container, supervise, web_push_service)
        tent = _bear(container, project_id, "decision", "Which tent?", DECISION)
        _reconcile(built, project_id)

        _answer(container, "ada", tent, "Dome")
        _reconcile(built, project_id)

        assert len(_pushes(fake_push_service, browsers["ada"])) == 1
        assert _seen(container, project_id) == set()

        site = _bear(container, project_id, "decision", "Which site?", DECISION)
        _reconcile(built, project_id)

        assert _pushes(fake_push_service, browsers["ada"])[1:] == [
            _push(container, project_id, "Which site?", site)
        ]

    def test_an_item_that_stops_waiting_and_comes_to_wait_again_alerts_again(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        """A work item stopped waits; retried and running, it waits on no
        one; stopped again, it waits again."""
        project_id = _project(container)
        built = _service(container, supervise, web_push_service)
        worker = _work(container, project_id, SessionState.STOPPED)
        _reconcile(built, project_id)

        _set_state(container, worker, SessionState.RUNNING)
        _reconcile(built, project_id)
        _set_state(container, worker, SessionState.STOPPED)
        _reconcile(built, project_id)

        alert = _push(container, project_id, "Building the camp", worker.session_id)
        assert _pushes(fake_push_service, browsers["ada"]) == [alert, alert]

    def test_a_change_of_the_plan_or_of_what_the_text_reads_pushes_nothing(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        """A work item starting to run, a plan step, a retitle of the item
        the text names and an item for another member change nothing of what
        waits on the member (D145)."""
        project_id = _project(
            container,
            ("ada", "ben"),
            tasks=[{"id": "t1", "title": "Pitch the tent", "status": "pending"}],
        )
        built = _service(container, supervise, web_push_service)
        _bear(container, project_id, "decision", "Which site?", DECISION)
        tent = _bear(container, project_id, "decision", "Which tent?", DECISION)
        _reconcile(built, project_id)
        pushed = _pushes(fake_push_service, browsers["ada"])

        _work(container, project_id)
        _reconcile(built, project_id)
        with scoped_session(container) as db:
            db.scalars(
                select(models.PlanTask).where(models.PlanTask.project_id == project_id)
            ).one().status_code = TaskStatus.IN_PROGRESS
        _reconcile(built, project_id)
        with scoped_session(container) as db:
            db.get_one(models.Item, tent).title = "Which tent, now?"
        _bear(
            container,
            project_id,
            "question",
            "Your boots?",
            QUESTION,
            **{"for": "ben"},
        )
        _reconcile(built, project_id)

        assert _pushes(fake_push_service, browsers["ada"]) == pushed
        assert pushed == [_push(container, project_id, "Which tent?, +1")]

    def test_an_item_for_one_member_is_theirs_alone(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container, ("ada", "ben"))
        built = _service(container, supervise, web_push_service)

        boots = _bear(
            container,
            project_id,
            "question",
            "Your boots?",
            QUESTION,
            urgent="true",
            **{"for": "ben"},
        )
        _reconcile(built, project_id)

        assert _pushes(fake_push_service, browsers["ben"]) == [
            _push(container, project_id, "Your boots?", boots)
        ]
        assert _pushes(fake_push_service, browsers["ada"]) == []
        assert _seen(container, project_id) == set()

    def test_leave_pushes_nothing_and_forgets_and_a_rejoin_alerts_anew(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container, ("ada", "ben"))
        tent = _bear(container, project_id, "decision", "Which tent?", DECISION)
        built = _service(container, supervise, web_push_service)
        _reconcile(built, project_id)
        pushed_at = _sent_at(container, project_id)

        _leave(container, "ada", project_id)
        _reconcile(built, project_id)

        assert len(_pushes(fake_push_service, browsers["ada"])) == 1
        assert _seen(container, project_id) == set()
        assert _sent_at(container, project_id) == pushed_at

        _join(container, "ada", project_id)
        _reconcile(built, project_id)

        alert = _push(container, project_id, "Which tent?", tent)
        assert _pushes(fake_push_service, browsers["ada"]) == [alert, alert]
        closed, rejoined = _memberships(container, project_id)
        assert _seen(container, project_id) == {tent}
        assert (closed.notification_sent_at, rejoined.notification_sent_at) == (
            pushed_at,
            _sent_at(container, project_id),
        )

    def test_archive_pushes_nothing_and_forgets_and_bring_back_alerts_anew(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container, environment_id=None)
        tent = _ask(container, project_id)
        built = _service(container, supervise, web_push_service)
        _reconcile(built, project_id)

        _transition(container, project_id, TransitionKind.ARCHIVED)
        _reconcile(built, project_id)

        assert len(_pushes(fake_push_service, browsers["ada"])) == 1
        assert _seen(container, project_id) == set()

        _transition(container, project_id, TransitionKind.BROUGHT_BACK)
        _reconcile(built, project_id)

        alert = _push(container, project_id, "Which tent?", tent)
        assert _pushes(fake_push_service, browsers["ada"]) == [alert, alert]

    def test_a_draft_and_a_finished_project_push_while_something_waits(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        draft = _project(container, environment_id=None, state="draft")
        finished = _project(container, environment_id=None, state="finished")
        built = _service(container, supervise, web_push_service)
        _reconcile(built, draft)
        _reconcile(built, finished)
        assert _pushes(fake_push_service, browsers["ada"]) == []

        _ask(container, draft, "Where?")
        _ask(container, finished)
        _reconcile(built, draft)
        _reconcile(built, finished)

        assert [
            (push.tag, push.body)
            for push in _pushes(fake_push_service, browsers["ada"])
        ] == [(str(draft), "Where?"), (str(finished), "Which tent?")]


class TestNotificationReconcileServicePages:
    def test_a_page_on_the_project_shows_every_item_waiting_and_pushes_nothing(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container)
        built = _service(container, supervise, web_push_service)
        page = _page(container, project_id=project_id)
        tent = _ask(container, project_id)
        site = _ask(container, project_id, "Which site?")

        _reconcile(built, project_id)

        assert _seen(container, project_id) == {tent, site}

        # Once the page is gone, what it showed is not pushed.
        _gone(container, page)
        _reconcile(built, project_id)

        assert _pushes(fake_push_service, browsers["ada"]) == []

    def test_a_page_on_the_project_forgets_what_no_longer_waits(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container)
        built = _service(container, supervise, web_push_service)
        tent = _bear(container, project_id, "decision", "Which tent?", DECISION)
        site = _bear(container, project_id, "decision", "Which site?", DECISION)
        _reconcile(built, project_id)
        _page(container, project_id=project_id)

        _answer(container, "ada", tent, "Dome")
        _reconcile(built, project_id)

        assert _seen(container, project_id) == {site}
        assert len(_pushes(fake_push_service, browsers["ada"])) == 1

    def test_online_with_no_page_on_it_nothing_is_pushed_and_what_was_shown_stands(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        camp = _project(container)
        lake = _project(container, environment_id=None)
        built = _service(container, supervise, web_push_service)
        tent = _bear(container, camp, "decision", "Which tent?", DECISION)
        _reconcile(built, camp)
        _page(container, project_id=lake)

        _bear(container, camp, "decision", "Which site?", DECISION)
        _reconcile(built, camp)
        _answer(container, "ada", tent, "Dome")
        _reconcile(built, camp)

        assert len(_pushes(fake_push_service, browsers["ada"])) == 1
        assert _seen(container, camp) == {tent}

    def test_a_page_whose_beat_is_ninety_seconds_old_counts_for_nothing(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container)
        built = _service(container, supervise, web_push_service)
        _page(
            container,
            project_id=project_id,
            beat_at=datetime.now(UTC) - timedelta(seconds=EXPIRY_SECONDS),
        )
        tent = _ask(container, project_id)

        _reconcile(built, project_id)

        assert _pushes(fake_push_service, browsers["ada"]) == [
            _push(container, project_id, "Which tent?", tent)
        ]


class TestNotificationReconcileServiceOffline:
    def test_going_offline_pushes_what_was_held_and_nothing_for_a_project_open(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        """F147: Camp was open while its ask came; Lake's came while she was
        online on Camp."""
        camp = _project(container)
        lake = _project(container, environment_id=None)
        built = _service(container, supervise, web_push_service)
        page = _page(container, project_id=camp)
        tent = _ask(container, camp)
        shore = _ask(container, lake, "Which shore?")
        _reconcile(built, camp)
        _reconcile(built, lake)
        assert _pushes(fake_push_service, browsers["ada"]) == []

        _gone(container, page)
        _reconcile_person(container, built)

        assert _pushes(fake_push_service, browsers["ada"]) == [
            _push(container, lake, "Which shore?", shore)
        ]
        assert (_seen(container, camp), _seen(container, lake)) == ({tent}, {shore})

    def test_going_offline_pushes_a_held_update_silently(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container)
        built = _service(container, supervise, web_push_service)
        tent = _bear(container, project_id, "decision", "Which tent?", DECISION)
        site = _bear(container, project_id, "decision", "Which site?", DECISION)
        _reconcile(built, project_id)
        page = _page(container)
        _answer(container, "ada", tent, "Dome")
        _reconcile(built, project_id)

        _gone(container, page)
        _reconcile_person(container, built)

        assert _pushes(fake_push_service, browsers["ada"])[1:] == [
            _push(container, project_id, "Which site?", site, alert=False)
        ]

    def test_a_pages_away_that_takes_them_offline_pushes_what_was_held(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        project_id = _project(container)
        built = _service(container, supervise, web_push_service)
        _started(built, log, project_id)
        page = _begin(container, built, "ada", None)
        tent = _ask(container, project_id)
        _reconcile(built, project_id)
        assert _pushes(fake_push_service, browsers["ada"]) == []

        _away(container, built, "ada", page)

        wait_until(
            lambda: (
                _pushes(fake_push_service, browsers["ada"])
                == [_push(container, project_id, "Which tent?", tent)]
            ),
            "the held push pushed",
        )

    def test_a_page_coming_to_show_the_project_shows_what_waits_there(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        project_id = _project(container)
        built = _service(container, supervise, web_push_service)
        tent = _ask(container, project_id)
        _page(container)
        _started(built, log, project_id)

        _begin(container, built, "ada", project_id)

        wait_until(lambda: _seen(container, project_id) == {tent}, "the ask shown")
        assert _pushes(fake_push_service, browsers["ada"]) == []

    def test_each_turn_of_the_persons_pages_asks_for_their_reconcile(
        self,
        container: ServiceContainer,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        """A page coming to show the project, and its away, which ends its
        showing and takes her offline; coming online is told nothing."""
        project_id = _project(container)
        built = _service(container, supervise, web_push_service)
        person_id = _person_id(container, "ada")

        with patch.object(
            built.supervisor, "start_loop", wraps=built.supervisor.start_loop
        ) as start:
            listing = _begin(container, built, "ada", None)
            page = _begin(container, built, "ada", project_id)
            _away(container, built, "ada", page)
            _away(container, built, "ada", listing)

        assert [(call.args[0], call.kwargs) for call in start.call_args_list] == [
            (NOTIFICATION_PERSON_JOB, {"key": str(person_id), "again": True})
        ] * 3


class TestNotificationReconcileServiceFailures:
    def test_a_push_no_browser_took_shows_nothing_and_the_next_change_alerts_anew(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container)
        built = _service(container, supervise, web_push_service)
        fake_push_service.fail(browsers["ada"].endpoint, "error")
        unanswered = metric_value(WEB_PUSH_SENDS_TOTAL, outcome="unanswered")
        _ask(container, project_id)

        _reconcile(built, project_id)

        assert _seen(container, project_id) == set()
        assert _sent_at(container, project_id) is not None
        assert (
            metric_value(WEB_PUSH_SENDS_TOTAL, outcome="unanswered") == unanswered + 1
        )

        fake_push_service.fail(browsers["ada"].endpoint, None)
        _ask(container, project_id, "Which site?")
        _reconcile(built, project_id)

        assert _pushes(fake_push_service, browsers["ada"]) == [
            _push(container, project_id, "Which site?, +1")
        ]
        assert len(_seen(container, project_id)) == 2

    def test_a_push_one_browser_of_theirs_took_shows_them_the_items(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container)
        built = _service(container, supervise, web_push_service)
        phone = _subscribe(container, fake_push_service, web_push_service, "ada")
        fake_push_service.fail(phone.endpoint, "refused")
        tent = _ask(container, project_id)

        _reconcile(built, project_id)

        assert _pushes(fake_push_service, browsers["ada"]) == [
            _push(container, project_id, "Which tent?", tent)
        ]
        assert _seen(container, project_id) == {tent}

    def test_it_registers_no_timer(
        self,
        container: ServiceContainer,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        """Nothing is retried (V14)."""
        supervisor, _ = supervise(container)
        pages = AppPageService(supervisor)

        with patch.object(supervisor, "register_timer") as register_timer:
            NotificationReconcileService(
                container=container,
                supervisor=supervisor,
                engine_bus=EngineBus(),
                app_page_service=pages,
                web_push_service=web_push_service,
            )

        register_timer.assert_not_called()


class TestNotificationReconcileServiceStartup:
    def test_startup_reconciles_every_project_that_may_push_or_forget(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        unpushed = _project(container)
        archived = _project(container, environment_id=None)
        left = _project(container, ("ada", "ben"), environment_id=None)
        untouched = _project(container, environment_id=None)
        tent = _bear(container, unpushed, "decision", "Which tent?", DECISION)
        for project_id in (archived, left, untouched):
            _ask(container, project_id)
        earlier = _service(container, supervise, web_push_service)
        _reconcile(earlier, archived)
        _reconcile(earlier, left)
        # Committed, and the process stopped before their reconciles.
        _transition(container, archived, TransitionKind.ARCHIVED)
        _leave(container, "ada", left)
        _transition(container, untouched, TransitionKind.ARCHIVED)
        later = _service(container, supervise, web_push_service)

        _started(later, log, unpushed, archived, left)

        assert [push.tag for push in _pushes(fake_push_service, browsers["ada"])] == [
            str(archived),
            str(left),
            str(unpushed),
        ]
        assert _seen(container, unpushed) == {tent}
        assert _seen(container, archived) == _seen(container, left) == set()
        assert log.matching(rf"Loop {NOTIFICATION_JOB}:{untouched} .*") == []


class TestNotificationReconcileServiceSpacing:
    def test_a_members_pushes_are_two_seconds_apart(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        """V11: the window the service keeps of its own runs two seconds from
        the member's last push."""
        project_id = _project(container)
        built = _service(container, supervise, web_push_service, spacing_seconds=None)
        _ask(container, project_id)
        _reconcile(built, project_id)
        last = _sent_at(container, project_id)
        assert last is not None
        _ask(container, project_id, "Which site?")
        entered: list[datetime] = []

        def stop(waits: int) -> None:
            entered.append(datetime.now(UTC))
            handle._request_stop()

        handle = _Window(stop)
        before = datetime.now(UTC)
        built.service.reconcile(project_id, handle)

        window_end = last + timedelta(seconds=2)
        [asked] = handle.asked
        assert (
            (window_end - entered[0]).total_seconds()
            <= asked
            <= (window_end - before).total_seconds()
        )
        assert len(_pushes(fake_push_service, browsers["ada"])) == 1

    def test_a_change_inside_the_window_goes_out_at_its_end_the_latest_state(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        """V11: two changes inside the window come to one push at its end,
        the latest; the wait holds no turn and no database connection."""
        project_id = _project(container)
        built = _service(
            container, supervise, web_push_service, spacing_seconds=SPACING
        )
        _ask(container, project_id)
        _reconcile(built, project_id)
        first = _sent_at(container, project_id)
        assert first is not None
        _ask(container, project_id, "Which site?")
        during: list[tuple[int, int, bool]] = []

        def in_the_window(waits: int) -> None:
            during.append(
                (
                    _checked_out(container),
                    len(_pushes(fake_push_service, browsers["ada"])),
                    _turn_free(container, project_id),
                )
            )
            if waits == 1:
                _ask(container, project_id, "Which stove?")

        built.service.reconcile(project_id, _Window(in_the_window))

        assert during[0] == (0, 1, True)
        assert [
            (push.body, push.renotify)
            for push in _pushes(fake_push_service, browsers["ada"])
        ] == [("Which tent?", True), ("Which stove?, +2", True)]
        last = _sent_at(container, project_id)
        assert last is not None and last - first >= timedelta(seconds=SPACING)

    def test_a_change_undone_inside_the_window_pushes_nothing(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container)
        built = _service(
            container, supervise, web_push_service, spacing_seconds=SPACING
        )
        _ask(container, project_id)
        _reconcile(built, project_id)
        site = _bear(container, project_id, "decision", "Which site?", DECISION)

        def answer(waits: int) -> None:
            if waits == 1:
                _answer(container, "ada", site, "Dome")

        built.service.reconcile(project_id, _Window(answer))

        assert [push.body for push in _pushes(fake_push_service, browsers["ada"])] == [
            "Which tent?"
        ]

    def test_a_window_is_one_persons_in_one_project(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        """V11: Ada's window in Camp holds neither Ben's push in it nor hers
        in another project."""
        camp = _project(container, ("ada", "ben"))
        lake = _project(container, environment_id=None)
        ada = _subscribe(container, fake_push_service, web_push_service, "ada")
        built = _service(
            container, supervise, web_push_service, spacing_seconds=SPACING
        )
        _ask(container, camp)
        _reconcile(built, camp)
        ben = _subscribe(container, fake_push_service, web_push_service, "ben")
        _ask(container, camp, "Which site?")
        _ask(container, lake, "Which lake?")
        during: list[tuple[int, int]] = []

        def in_the_window(waits: int) -> None:
            if waits == 1:
                _reconcile(built, lake)
                during.append(
                    (
                        len(_pushes(fake_push_service, ada)),
                        len(_pushes(fake_push_service, ben)),
                    )
                )

        built.service.reconcile(camp, _Window(in_the_window))

        assert during == [(2, 1)]
        assert [(push.tag, push.body) for push in _pushes(fake_push_service, ada)] == [
            (str(camp), "Which tent?"),
            (str(lake), "Which lake?"),
            (str(camp), "Which site?, +1"),
        ]
        assert [push.body for push in _pushes(fake_push_service, ben)] == [
            "Which site?, +1"
        ]

    def test_a_rejoin_waits_for_the_window_of_the_push_before_its_leave(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container, ("ada", "ben"))
        built = _service(
            container, supervise, web_push_service, spacing_seconds=SPACING
        )
        _ask(container, project_id)
        _reconcile(built, project_id)
        _leave(container, "ada", project_id)
        _reconcile(built, project_id)
        _join(container, "ada", project_id)
        pushed: list[int] = []

        def in_the_window(waits: int) -> None:
            pushed.append(len(_pushes(fake_push_service, browsers["ada"])))

        built.service.reconcile(project_id, _Window(in_the_window))

        assert pushed[0] == 1
        assert [push.body for push in _pushes(fake_push_service, browsers["ada"])] == [
            "Which tent?"
        ] * 2

    def test_a_stop_during_the_wait_pushes_nothing_and_leaves_it_to_the_next_run(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        """V11: a roll's old process drained inside the window pushes
        nothing; what it held is unshown in the record, which the new one's
        next reconcile of the member pushes."""
        project_id = _project(container)
        old = _service(container, supervise, web_push_service, spacing_seconds=SPACING)
        new = _service(container, supervise, web_push_service)
        _ask(container, project_id)
        _reconcile(old, project_id)
        _ask(container, project_id, "Which site?")
        handle = _Window(lambda waits: handle._request_stop())

        old.service.reconcile(project_id, handle)

        assert len(handle.asked) == 1
        assert len(_pushes(fake_push_service, browsers["ada"])) == 1
        log.wait_for(
            rf"The push of project {project_id}'s notification to "
            rf"{_person_id(container, 'ada')} is left to their next reconcile: the "
            "run stopped inside its window"
        )

        _reconcile(new, project_id)

        assert [
            (push.body, push.renotify)
            for push in _pushes(fake_push_service, browsers["ada"])
        ][1:] == [("Which site?, +1", True)]

    def test_a_stop_before_a_persons_compare_pushes_nothing(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container)
        built = _service(container, supervise, web_push_service)
        _ask(container, project_id)
        handle = LoopHandle("test")
        handle._request_stop()

        built.service.reconcile(project_id, handle)

        assert _pushes(fake_push_service, browsers["ada"]) == []
        assert _seen(container, project_id) == set()

    def test_two_processes_keep_one_window_and_push_once_at_its_end(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        """V11: the new process, which pushed nothing yet, keeps the window
        of the old one's push, and of the two reconciles inside it one
        pushes."""
        project_id = _project(container)
        old = _service(container, supervise, web_push_service, spacing_seconds=SPACING)
        new = _service(container, supervise, web_push_service, spacing_seconds=SPACING)
        _ask(container, project_id)
        _reconcile(old, project_id)
        first = _sent_at(container, project_id)
        assert first is not None
        _ask(container, project_id, "Which site?")
        during: list[int] = []

        def old_reconciles_too(waits: int) -> None:
            during.append(len(_pushes(fake_push_service, browsers["ada"])))
            if waits == 1:
                _ask(container, project_id, "Which stove?")
                _reconcile(old, project_id)

        new.service.reconcile(project_id, _Window(old_reconciles_too))

        assert during[0] == 1
        assert [push.body for push in _pushes(fake_push_service, browsers["ada"])] == [
            "Which tent?",
            "Which stove?, +2",
        ]
        last = _sent_at(container, project_id)
        assert last is not None and last - first >= timedelta(seconds=SPACING)


class TestNotificationReconcileServiceBus:
    def test_a_project_changed_asks_for_its_reconcile_and_a_work_moved_alone_not(
        self,
        container: ServiceContainer,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        bus = EngineBus()
        built = _service(container, supervise, web_push_service, engine_bus=bus)
        project_id, work_id = uuid.uuid4(), uuid.uuid4()

        with patch.object(
            built.supervisor, "start_loop", wraps=built.supervisor.start_loop
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
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        project_id = _project(container)
        built = _service(
            container, supervise, web_push_service, engine_bus=container.engine_bus()
        )
        _started(built, log, project_id)
        released = threading.Event()
        fake_push_service.on_push = lambda: released.wait(WAIT_SECONDS)

        # The commit returns while the push service holds the reconcile's push.
        item_id = _bear(container, project_id, "decision", "Which tent?", DECISION)

        log.wait_for(rf"Loop {NOTIFICATION_JOB}:{project_id} started", 2)
        released.set()
        log.wait_for(rf"Loop {NOTIFICATION_JOB}:{project_id} ended", 2)
        [push] = _pushes(fake_push_service, browsers["ada"])
        assert push.url.endswith(f"/items/{item_id}")


class TestNotificationReconcileServiceProgress:
    def test_a_change_of_a_work_items_steps_pushes_nothing(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        """F145.4, R7: the notification never names a work item's progress,
        so a change of it, heard on the bus and reconciled after, pushes
        nothing. A question waits on Ada, so that something is pushed."""
        project_id = _project(container)
        _bear(container, project_id, "question", "Your boots?", QUESTION)
        worker = _work(container, project_id)
        built = _service(
            container, supervise, web_push_service, engine_bus=container.engine_bus()
        )
        _reconcile(built, project_id)
        pushed = _pushes(fake_push_service, browsers["ada"])
        assert pushed != []
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
            _reconcile(built, project_id)

        assert _pushes(fake_push_service, browsers["ada"]) == pushed


class TestNotificationReconcileServiceTwoProcesses:
    def test_two_processes_take_turns_and_push_the_member_once_each_change(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        project_id = _project(container)
        old = _service(container, supervise, web_push_service)
        new = _service(container, supervise, web_push_service)
        _ask(container, project_id)
        _reconcile(old, project_id)
        _ask(container, project_id, "Which site?")
        turns = []

        def change_and_reconcile_in_the_other() -> None:
            _ask(container, project_id, "Which stove?")
            turns.append(in_thread(lambda: _reconcile(new, project_id)))
            wait_until(lambda: lock_waits(container) == 1, "the other's turn waiting")

        fake_push_service.on_push = change_and_reconcile_in_the_other

        _reconcile(old, project_id)
        turns[0].result()

        assert [push.body for push in _pushes(fake_push_service, browsers["ada"])] == [
            "Which tent?",
            "Which site?, +1",
            "Which stove?, +2",
        ]
        assert len(_seen(container, project_id)) == 3


class TestNotificationReconcileServiceConnections:
    def test_more_turns_at_once_than_the_pool_holds_each_complete(
        self,
        container: ServiceContainer,
        browsers: dict[str, FakeSubscription],
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        """A member's turn holds one connection at a time: with as many turns
        in their pushes at once as the pool has connections, and one turn
        more waiting on the pool, each completes."""
        capacity = pool_capacity(container)
        projects = [_project(container) for _ in range(capacity + 1)]
        for project_id in projects:
            _ask(container, project_id)
        built = _service(container, supervise, web_push_service)
        held = fake_push_service.hold(capacity)

        turns = [
            in_thread(partial(_reconcile, built, project_id)) for project_id in projects
        ]
        for turn in turns:
            turn.result()

        assert held.is_set()
        assert sorted(
            push.tag for push in _pushes(fake_push_service, browsers["ada"])
        ) == sorted(str(project_id) for project_id in projects)
        assert all(_seen(container, project_id) for project_id in projects)
