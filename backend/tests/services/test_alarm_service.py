"""The alarms (F142, F147; DB 238; DB decisions 70 and 74; V09, V13, V14): a
push to every browser of a person's, under the one tag `alarms`, when a
condition that alarms has begun since they were last shown the conditions,
while they are offline and their switch is on, on the fake push service.

The halts are proven one step in from the conditions service, the reconcile
driven with them holding by their codes; the wiring from the conditions
service with the outage and the store's update, and from the pages with a
page's away. Every test is on a database of its own: a person's turn is an
advisory lock on a connection of its own, which reads committed rows alone."""

import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import scoped_session
from app.models import AppPage, PushSubscription, StoreUpdate, User
from app.models.reference import UserKind
from app.schemas.conditions import ConditionCode
from app.services.alarm_service import (
    ALARM_JOB,
    ALARM_LOCK,
    ALARM_SEEN_JOB,
    ALARM_TAG,
    AlarmService,
)
from app.services.app_page_service import EXPIRY_SECONDS, AppPageService
from app.services.condition_service import ConditionService
from app.services.container import ServiceContainer
from app.services.controller_outage import ControllerOutage
from app.services.fake_push_service import FakePush, FakeSubscription
from app.services.push_subscription_service import PushSubscriptionService
from app.services.supervisor import LoopHandle, Supervisor
from app.services.web_push import WEB_PUSH_SENDS_TOTAL, PushOutcome, WebPushService
from app.utils.after_commit import clear_after_commit_callbacks
from app.utils.lifecycle_coordinator import LifecycleCoordinator
from tests.support.fake_push_service import ServedFakePushService
from tests.support.locks import (
    holding_connections,
    in_thread,
    lock_waits,
    pool_capacity,
    turn_holders,
)
from tests.support.store_updates import hold, lift
from tests.support.supervisor import (
    LogWaiter,
    Supervise,
    listening,
    metric_value,
    wait_until,
)

SUPERVISOR_LOGGER = "app.services.supervisor"
LONG_AGO = timedelta(hours=1)
OUTAGE = "The controller has been unreachable"
WEEK = "The week's usage halt"


@dataclass(frozen=True)
class _Built:
    service: AlarmService
    outage: ControllerOutage
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
    """The committed app's container, with Ada, Ben and Cal."""
    container: ServiceContainer = committed_app.container
    with scoped_session(container):
        data = container.test_data_service()
        data.person("ada", "Ada Example")
        data.person("ben", "Ben Example")
        data.person("cal", "Cal Example")
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
    with listening(SUPERVISOR_LOGGER) as waiter:
        yield waiter


def _service(
    container: ServiceContainer,
    supervise: Supervise,
    web_push_service: WebPushService,
    *,
    outage_after_seconds: float = 300.0,
) -> _Built:
    """The alarms on a supervisor of their own, hearing a conditions service
    on an outage of its own and the pages on the same supervisor."""
    supervisor, coordinator = supervise(container, controller_configured=False)
    outage = ControllerOutage()
    pages = AppPageService(supervisor)
    service = AlarmService(
        container=container,
        supervisor=supervisor,
        condition_service=ConditionService(
            container,
            outage,
            container.usage_halts(),
            container.sse_connection_manager(),
        ),
        app_page_service=pages,
        web_push_service=web_push_service,
        base_url=container.config().baseurl,
        outage_after_seconds=outage_after_seconds,
    )
    return _Built(service, outage, supervisor, coordinator, pages)


def _started(built: _Built, log: LogWaiter) -> None:
    """STARTUP fired, and its reconcile ended, so that the loops asked for
    start."""
    built.coordinator.fire_startup()
    log.wait_for(rf"Loop {ALARM_JOB} ended")


def _reconcile(
    service: AlarmService, holding: Mapping[ConditionCode, datetime]
) -> None:
    service.reconcile_holding(holding, LoopHandle("test"))


def _now() -> datetime:
    return datetime.now(UTC)


def _person(db: Session, handle: str) -> User:
    return db.scalars(select(User).where(User.handle == handle)).one()


def _subscribe(
    container: ServiceContainer,
    fake: ServedFakePushService,
    web_push_service: WebPushService,
    handle: str,
) -> FakeSubscription:
    """A browser of the person's, subscribed as their switch subscribes it."""
    browser = fake.browser(web_push_service.public_key or "")
    with scoped_session(container) as db:
        PushSubscriptionService(db).subscribe(
            _person(db, handle),
            browser.endpoint,
            browser.keys.p256dh,
            browser.keys.auth,
        )
    return browser


def _switch(container: ServiceContainer, handle: str, *, on: bool) -> None:
    with scoped_session(container) as db:
        _person(db, handle).alarms = on


def _online(
    container: ServiceContainer, handle: str, *, beat_at: datetime | None = None
) -> uuid.UUID:
    """A page of the person's, its beat `beat_at`, now by default, committed;
    its id."""
    with scoped_session(container) as db:
        page = AppPage(user_id=_person(db, handle).id, beat_at=beat_at or _now())
        db.add(page)
        db.flush()
        return page.id


def _away(
    container: ServiceContainer, built: _Built, handle: str, page_id: uuid.UUID
) -> None:
    """The page's away, as its person's browser sends it, committed."""
    with scoped_session(container) as db:
        built.pages.away(db, _person(db, handle), page_id)


def _went_offline(
    container: ServiceContainer,
    built: _Built,
    log: LogWaiter,
    handle: str,
    page_id: uuid.UUID,
    count: int = 1,
) -> None:
    """The person's last page away, and the `count`th going offline written."""
    _away(container, built, handle, page_id)
    log.wait_for(rf"Loop {ALARM_SEEN_JOB}:{count} ended")


def _seen_at(container: ServiceContainer, handle: str) -> datetime | None:
    with scoped_session(container) as db:
        return _person(db, handle).alarm_seen_at


def _seen(container: ServiceContainer) -> dict[str, datetime]:
    """Each User's `alarm_seen_at`, by handle, of those that have one."""
    with scoped_session(container) as db:
        return {
            handle: seen
            for handle, seen in db.execute(
                select(User.handle, User.alarm_seen_at).where(
                    User.alarm_seen_at.is_not(None)
                )
            )
            if seen is not None
        }


def _alarm(container: ServiceContainer, text: str) -> FakePush:
    """The alarm push carrying `text`, as the browser decrypts it."""
    return FakePush(
        title="Pilot",
        body=text,
        tag=ALARM_TAG,
        url=f"{container.config().baseurl}/",
        renotify=True,
        urgency="high",
        ttl=86400,
    )


def _pushes(fake: ServedFakePushService, browser: FakeSubscription) -> list[FakePush]:
    return fake.pushes(browser.endpoint)


class TestAlarmServiceHolding:
    def test_none_holds_while_the_controller_answers(
        self,
        container: ServiceContainer,
        supervise: Supervise,
        web_push_service: WebPushService,
    ) -> None:
        built = _service(container, supervise, web_push_service)

        assert built.service.holding() == {}

    def test_the_outage_holds_by_its_code_from_its_turn_on(
        self,
        container: ServiceContainer,
        supervise: Supervise,
        web_push_service: WebPushService,
    ) -> None:
        built = _service(container, supervise, web_push_service)

        built.outage.call_unanswered()

        assert built.service.holding() == {ConditionCode.OUTAGE: built.outage.since}

    def test_the_stores_update_holds_by_its_code_from_its_made_at(
        self,
        container: ServiceContainer,
        supervise: Supervise,
        web_push_service: WebPushService,
    ) -> None:
        built = _service(container, supervise, web_push_service)
        with scoped_session(container) as db:
            made_at = hold(db).made_at

        assert built.service.holding() == {ConditionCode.STORE_UPDATE: made_at}


class TestAlarmServiceReconcile:
    def test_the_weeks_halt_alerts_every_browser_of_each_person_with_the_switch_on(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        browsers: dict[str, FakeSubscription],
        supervise: Supervise,
    ) -> None:
        desktop = _subscribe(container, fake_push_service, web_push_service, "ada")
        _switch(container, "ben", on=False)
        built = _service(container, supervise, web_push_service)
        since = _now()

        _reconcile(built.service, {ConditionCode.WEEK_HALT: since})

        assert _pushes(fake_push_service, browsers["ada"]) == [_alarm(container, WEEK)]
        assert _pushes(fake_push_service, desktop) == [_alarm(container, WEEK)]
        assert _pushes(fake_push_service, browsers["ben"]) == []
        # Ben with the switch off, Cal with no browser, and Pilot: none.
        assert _seen(container) == {"ada": since}

    @pytest.mark.parametrize(
        "condition", [ConditionCode.FIVE_HOUR_HALT, ConditionCode.STORE_UPDATE]
    )
    def test_the_five_hour_halt_and_the_stores_update_alarm_nobody(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        browsers: dict[str, FakeSubscription],
        supervise: Supervise,
        condition: ConditionCode,
    ) -> None:
        built = _service(container, supervise, web_push_service)

        _reconcile(built.service, {condition: _now() - LONG_AGO})

        assert _pushes(fake_push_service, browsers["ada"]) == []
        assert _seen(container) == {}

    def test_a_condition_they_were_shown_is_not_pushed_again(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        browsers: dict[str, FakeSubscription],
        supervise: Supervise,
    ) -> None:
        built = _service(container, supervise, web_push_service)
        holding = {ConditionCode.WEEK_HALT: _now()}
        _reconcile(built.service, holding)

        _reconcile(built.service, holding)

        assert _pushes(fake_push_service, browsers["ada"]) == [_alarm(container, WEEK)]

    @pytest.mark.parametrize(
        ("outage_age", "week_age", "text", "latest"),
        [
            pytest.param(2, 1, f"{WEEK}, +1", "week", id="the-weeks-halt-latest"),
            pytest.param(1, 2, f"{OUTAGE}, +1", "outage", id="the-outage-latest"),
        ],
    )
    def test_its_text_is_the_conditions_due_the_latest_begun_first(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        browsers: dict[str, FakeSubscription],
        supervise: Supervise,
        outage_age: int,
        week_age: int,
        text: str,
        latest: str,
    ) -> None:
        """The five-hour halt and the store's update, begun last, count for
        nothing."""
        built = _service(container, supervise, web_push_service)
        now = _now()
        began = {
            "outage": now - outage_age * LONG_AGO,
            "week": now - week_age * LONG_AGO,
        }

        _reconcile(
            built.service,
            {
                ConditionCode.OUTAGE: began["outage"],
                ConditionCode.WEEK_HALT: began["week"],
                ConditionCode.FIVE_HOUR_HALT: now,
                ConditionCode.STORE_UPDATE: now,
            },
        )

        assert _pushes(fake_push_service, browsers["ada"]) == [_alarm(container, text)]
        assert _seen_at(container, "ada") == began[latest]

    def test_a_condition_begun_after_alerts_with_every_condition_due(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        browsers: dict[str, FakeSubscription],
        supervise: Supervise,
    ) -> None:
        built = _service(container, supervise, web_push_service)
        week = _now() - 2 * LONG_AGO
        outage = _now() - LONG_AGO
        _reconcile(built.service, {ConditionCode.WEEK_HALT: week})

        _reconcile(
            built.service,
            {ConditionCode.WEEK_HALT: week, ConditionCode.OUTAGE: outage},
        )

        assert _pushes(fake_push_service, browsers["ada"]) == [
            _alarm(container, WEEK),
            _alarm(container, f"{OUTAGE}, +1"),
        ]
        assert _seen_at(container, "ada") == outage

    def test_a_conditions_end_pushes_nothing(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        browsers: dict[str, FakeSubscription],
        supervise: Supervise,
    ) -> None:
        built = _service(container, supervise, web_push_service)
        week = _now() - 2 * LONG_AGO
        outage = _now() - LONG_AGO
        _reconcile(
            built.service,
            {ConditionCode.WEEK_HALT: week, ConditionCode.OUTAGE: outage},
        )

        _reconcile(built.service, {ConditionCode.WEEK_HALT: week})
        _reconcile(built.service, {})

        assert _pushes(fake_push_service, browsers["ada"]) == [
            _alarm(container, f"{OUTAGE}, +1")
        ]

    @pytest.mark.parametrize(("seconds", "due"), [(299, False), (301, True)])
    def test_the_outage_is_due_once_it_has_held_its_time(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        browsers: dict[str, FakeSubscription],
        supervise: Supervise,
        seconds: int,
        due: bool,
    ) -> None:
        built = _service(
            container, supervise, web_push_service, outage_after_seconds=300
        )

        _reconcile(
            built.service,
            {ConditionCode.OUTAGE: _now() - timedelta(seconds=seconds)},
        )

        assert _pushes(fake_push_service, browsers["ada"]) == (
            [_alarm(container, OUTAGE)] if due else []
        )
        assert (_seen_at(container, "ada") is not None) is due

    def test_a_condition_begun_while_a_push_was_in_flight_alerts_after_it(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        browsers: dict[str, FakeSubscription],
        supervise: Supervise,
    ) -> None:
        built = _service(container, supervise, web_push_service, outage_after_seconds=0)
        week = _now() - LONG_AGO
        begun: list[datetime] = []
        fake_push_service.on_push = lambda: begun.append(_now())
        _reconcile(built.service, {ConditionCode.WEEK_HALT: week})

        _reconcile(
            built.service,
            {ConditionCode.WEEK_HALT: week, ConditionCode.OUTAGE: begun[0]},
        )

        assert _pushes(fake_push_service, browsers["ada"])[-1] == _alarm(
            container, f"{OUTAGE}, +1"
        )

    def test_pilot_has_no_alarm(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        supervise: Supervise,
    ) -> None:
        browser = fake_push_service.browser(web_push_service.public_key or "")
        with scoped_session(container) as db:
            pilot = db.scalars(
                select(User).where(User.kind_code == UserKind.AGENT)
            ).one()
            db.add(
                PushSubscription(
                    user_id=pilot.id,
                    endpoint=browser.endpoint,
                    p256dh=browser.keys.p256dh,
                    auth=browser.keys.auth,
                )
            )
        built = _service(container, supervise, web_push_service)

        _reconcile(built.service, {ConditionCode.WEEK_HALT: _now()})

        assert _pushes(fake_push_service, browser) == []
        assert _seen(container) == {}


class TestAlarmServiceOnline:
    def test_a_person_online_on_any_device_is_pushed_nothing(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        browsers: dict[str, FakeSubscription],
        supervise: Supervise,
    ) -> None:
        """Their page on a browser they never subscribed counts as much."""
        _online(container, "ada")
        built = _service(container, supervise, web_push_service)

        _reconcile(built.service, {ConditionCode.WEEK_HALT: _now()})

        assert _pushes(fake_push_service, browsers["ada"]) == []
        assert _pushes(fake_push_service, browsers["ben"]) == [_alarm(container, WEEK)]
        assert set(_seen(container)) == {"ben"}

    def test_a_page_whose_beat_is_ninety_seconds_old_counts_for_nothing(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        browsers: dict[str, FakeSubscription],
        supervise: Supervise,
    ) -> None:
        _online(
            container, "ada", beat_at=_now() - timedelta(seconds=EXPIRY_SECONDS + 1)
        )
        built = _service(container, supervise, web_push_service)

        _reconcile(built.service, {ConditionCode.WEEK_HALT: _now()})

        assert _pushes(fake_push_service, browsers["ada"]) == [_alarm(container, WEEK)]


class TestAlarmServiceOffline:
    def test_going_offline_shows_them_every_condition_that_holds(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        browsers: dict[str, FakeSubscription],
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        built = _service(container, supervise, web_push_service)
        _started(built, log)
        page = _online(container, "ada")
        holding = {ConditionCode.WEEK_HALT: _now()}
        _reconcile(built.service, holding)

        _went_offline(container, built, log, "ada", page)

        seen = _seen_at(container, "ada")
        assert seen is not None and seen > holding[ConditionCode.WEEK_HALT]
        _reconcile(built.service, holding)
        assert _pushes(fake_push_service, browsers["ada"]) == []

    def test_an_outage_begun_while_they_were_online_does_not_alarm_when_due_after(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        browsers: dict[str, FakeSubscription],
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        """The outage comes due on a service whose wait it has held; Ben,
        offline throughout, is alarmed by it."""
        built = _service(container, supervise, web_push_service)
        _started(built, log)
        page = _online(container, "ada")
        holding = {ConditionCode.OUTAGE: _now()}
        _reconcile(built.service, holding)
        _went_offline(container, built, log, "ada", page)
        came_due = _service(
            container, supervise, web_push_service, outage_after_seconds=0
        )

        _reconcile(came_due.service, holding)

        assert _pushes(fake_push_service, browsers["ada"]) == []
        assert _pushes(fake_push_service, browsers["ben"]) == [
            _alarm(container, OUTAGE)
        ]

    def test_a_condition_begun_after_they_went_offline_alarms_them(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        browsers: dict[str, FakeSubscription],
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        built = _service(container, supervise, web_push_service)
        _started(built, log)
        _went_offline(container, built, log, "ada", _online(container, "ada"))
        since = _now()

        _reconcile(built.service, {ConditionCode.WEEK_HALT: since})

        assert _pushes(fake_push_service, browsers["ada"]) == [_alarm(container, WEEK)]
        assert _seen_at(container, "ada") == since

    def test_going_offline_never_moves_it_back(
        self,
        container: ServiceContainer,
        web_push_service: WebPushService,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        later = _now() + LONG_AGO
        with scoped_session(container) as db:
            _person(db, "ada").alarm_seen_at = later
        built = _service(container, supervise, web_push_service)
        _started(built, log)

        _went_offline(container, built, log, "ada", _online(container, "ada"))

        assert _seen_at(container, "ada") == later

    def test_a_page_beside_another_keeps_them_online(
        self,
        container: ServiceContainer,
        web_push_service: WebPushService,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        built = _service(container, supervise, web_push_service)
        _started(built, log)
        phone = _online(container, "ada")
        desktop = _online(container, "ada")

        _away(container, built, "ada", phone)
        _went_offline(container, built, log, "ada", desktop)

        assert log.matching(rf"Loop {ALARM_SEEN_JOB}:\d+ started") == [
            f"Loop {ALARM_SEEN_JOB}:1 started"
        ]


class TestAlarmServiceSwitch:
    def test_off_pushes_no_alarm(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        browsers: dict[str, FakeSubscription],
        supervise: Supervise,
    ) -> None:
        _switch(container, "ada", on=False)
        built = _service(container, supervise, web_push_service)

        _reconcile(built.service, {ConditionCode.WEEK_HALT: _now()})

        assert _pushes(fake_push_service, browsers["ada"]) == []
        assert _seen_at(container, "ada") is None

    def test_on_again_alarms_on_the_next_condition_that_comes_to_hold(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        browsers: dict[str, FakeSubscription],
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        """Turned on a page of Pilot, whose going offline shows what holds;
        with the switch off, the going offline shows it as much."""
        _switch(container, "ada", on=False)
        built = _service(container, supervise, web_push_service, outage_after_seconds=0)
        _started(built, log)
        week = _now() - LONG_AGO
        _reconcile(built.service, {ConditionCode.WEEK_HALT: week})
        page = _online(container, "ada")
        _switch(container, "ada", on=True)
        _went_offline(container, built, log, "ada", page)
        _reconcile(built.service, {ConditionCode.WEEK_HALT: week})
        assert _pushes(fake_push_service, browsers["ada"]) == []

        _reconcile(
            built.service,
            {ConditionCode.WEEK_HALT: week, ConditionCode.OUTAGE: _now()},
        )

        assert _pushes(fake_push_service, browsers["ada"]) == [
            _alarm(container, f"{OUTAGE}, +1")
        ]


class TestAlarmServiceFailures:
    def test_a_push_no_browser_took_is_not_pushed_again(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        browsers: dict[str, FakeSubscription],
        supervise: Supervise,
    ) -> None:
        """The web push service logs and counts the refusal."""
        fake_push_service.fail(browsers["ada"].endpoint, "refused")
        built = _service(container, supervise, web_push_service)
        holding = {ConditionCode.WEEK_HALT: _now()}
        refused = metric_value(WEB_PUSH_SENDS_TOTAL, outcome=PushOutcome.REFUSED)
        _reconcile(built.service, holding)
        fake_push_service.fail(browsers["ada"].endpoint, None)

        _reconcile(built.service, holding)

        assert _pushes(fake_push_service, browsers["ada"]) == []
        assert _seen_at(container, "ada") == holding[ConditionCode.WEEK_HALT]
        assert (
            metric_value(WEB_PUSH_SENDS_TOTAL, outcome=PushOutcome.REFUSED)
            == refused + 1
        )


class TestAlarmServiceConditions:
    def test_each_turn_of_the_outage_asks_for_the_reconcile(
        self,
        container: ServiceContainer,
        supervise: Supervise,
        web_push_service: WebPushService,
    ) -> None:
        built = _service(container, supervise, web_push_service)

        with patch.object(
            built.supervisor, "start_loop", wraps=built.supervisor.start_loop
        ) as start:
            built.outage.call_unanswered()
            built.outage.probe_answered()

        assert [
            (call.args[0], call.args[1], call.kwargs) for call in start.call_args_list
        ] == [(ALARM_JOB, built.service.reconcile, {"again": True})] * 2

    def test_startup_asks_for_the_reconcile(
        self,
        container: ServiceContainer,
        supervise: Supervise,
        web_push_service: WebPushService,
    ) -> None:
        built = _service(container, supervise, web_push_service)

        with patch.object(
            built.supervisor, "start_loop", wraps=built.supervisor.start_loop
        ) as start:
            built.coordinator.fire_startup()

        assert [(call.args[0], call.args[1]) for call in start.call_args_list] == [
            (ALARM_JOB, built.service.reconcile)
        ]

    def test_a_blip_buzzes_nobody(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        browsers: dict[str, FakeSubscription],
        supervise: Supervise,
    ) -> None:
        built = _service(container, supervise, web_push_service)

        built.outage.call_unanswered()
        built.service.reconcile(LoopHandle("test"))
        built.outage.probe_answered()
        built.service.reconcile(LoopHandle("test"))

        assert _pushes(fake_push_service, browsers["ada"]) == []
        assert _seen(container) == {}

    def test_the_outage_alarms_once_it_held_its_time_and_its_end_pushes_nothing(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        browsers: dict[str, FakeSubscription],
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        built = _service(
            container, supervise, web_push_service, outage_after_seconds=0.3
        )
        _started(built, log)

        built.outage.call_unanswered()
        since = built.outage.since
        assert since is not None

        wait_until(
            lambda: _seen_at(container, "ada") == since,
            "the outage's alarm pushed and its showing written",
        )
        assert _pushes(fake_push_service, browsers["ada"]) == [
            _alarm(container, OUTAGE)
        ]
        assert _now() - since >= timedelta(seconds=0.3)

        built.outage.probe_answered()
        built.service.reconcile(LoopHandle("test"))

        assert _pushes(fake_push_service, browsers["ada"]) == [
            _alarm(container, OUTAGE)
        ]

    def test_the_stores_update_reaches_no_browser(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        browsers: dict[str, FakeSubscription],
        supervise: Supervise,
    ) -> None:
        """Read through the conditions service, which holds it until its
        lift."""
        built = _service(container, supervise, web_push_service)
        with scoped_session(container) as db:
            update_id = hold(db).id

        built.service.reconcile(LoopHandle("test"))
        with scoped_session(container) as db:
            lift(db, db.get_one(StoreUpdate, update_id))
        built.service.reconcile(LoopHandle("test"))

        assert _pushes(fake_push_service, browsers["ada"]) == []


class TestAlarmServiceDueTimer:
    def test_it_asks_for_the_reconcile_when_the_conditions_due_turn(
        self,
        container: ServiceContainer,
        supervise: Supervise,
        web_push_service: WebPushService,
    ) -> None:
        built = _service(container, supervise, web_push_service, outage_after_seconds=0)
        _reconcile(built.service, {})
        built.outage.call_unanswered()

        with patch.object(
            built.supervisor, "start_loop", wraps=built.supervisor.start_loop
        ) as start:
            with scoped_session(container) as db:
                built.service.tick(db)

        assert [(call.args[0], call.kwargs) for call in start.call_args_list] == [
            (ALARM_JOB, {"again": False})
        ]

    def test_it_asks_for_nothing_while_the_conditions_due_stand_as_read(
        self,
        container: ServiceContainer,
        supervise: Supervise,
        web_push_service: WebPushService,
    ) -> None:
        built = _service(container, supervise, web_push_service, outage_after_seconds=0)
        built.outage.call_unanswered()
        _reconcile(built.service, built.service.holding())

        with patch.object(
            built.supervisor, "start_loop", wraps=built.supervisor.start_loop
        ) as start:
            with scoped_session(container) as db:
                built.service.tick(db)

        start.assert_not_called()


class TestAlarmServiceTwoProcesses:
    def test_two_processes_alert_each_person_once(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        browsers: dict[str, FakeSubscription],
        supervise: Supervise,
    ) -> None:
        old = _service(container, supervise, web_push_service)
        new = _service(container, supervise, web_push_service)
        holding = {ConditionCode.WEEK_HALT: _now()}
        turns = []

        def reconcile_in_the_other() -> None:
            turns.append(in_thread(lambda: _reconcile(new.service, holding)))
            wait_until(lambda: lock_waits(container) == 1, "the other's turn waiting")

        fake_push_service.on_push = reconcile_in_the_other

        _reconcile(old.service, holding)
        turns[0].result()

        assert _pushes(fake_push_service, browsers["ada"]) == [_alarm(container, WEEK)]
        assert _pushes(fake_push_service, browsers["ben"]) == [_alarm(container, WEEK)]


class TestAlarmServiceConnections:
    def test_across_the_push_its_lock_is_a_transactions_that_holds_no_table(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        browsers: dict[str, FakeSubscription],
        supervise: Supervise,
    ) -> None:
        """Across the push, a transaction holds the person's lock, as a
        pooler in transaction mode keeps it, and no lock on a row or a
        table."""
        built = _service(container, supervise, web_push_service)
        holding = {ConditionCode.WEEK_HALT: _now()}
        holders: list[tuple[str, list[str]]] = []
        fake_push_service.on_push = lambda: holders.extend(
            turn_holders(container, ALARM_LOCK)
        )

        _reconcile(built.service, holding)

        assert holders == [("idle in transaction", [])]
        assert _pushes(fake_push_service, browsers["ada"]) == [_alarm(container, WEEK)]
        assert _pushes(fake_push_service, browsers["ben"]) == [_alarm(container, WEEK)]

    def test_a_turn_alarms_on_the_one_connection_the_pool_has_left(
        self,
        container: ServiceContainer,
        fake_push_service: ServedFakePushService,
        web_push_service: WebPushService,
        browsers: dict[str, FakeSubscription],
        supervise: Supervise,
    ) -> None:
        """A person's turn holds one connection at a time: with every other
        one of the pool held, each person is alarmed."""
        built = _service(container, supervise, web_push_service)
        holding = {ConditionCode.WEEK_HALT: _now()}

        with holding_connections(container, pool_capacity(container) - 1):
            _reconcile(built.service, holding)

        assert _pushes(fake_push_service, browsers["ada"]) == [_alarm(container, WEEK)]
        assert _pushes(fake_push_service, browsers["ben"]) == [_alarm(container, WEEK)]


class TestAlarmServiceNoKey:
    def test_with_no_key_it_registers_and_hears_nothing(
        self, container: ServiceContainer, supervise: Supervise
    ) -> None:
        supervisor, _ = supervise(container, controller_configured=False)
        conditions = ConditionService(
            container,
            ControllerOutage(),
            container.usage_halts(),
            container.sse_connection_manager(),
        )
        pages = AppPageService(supervisor)

        with (
            patch.object(supervisor, "register_job") as register_job,
            patch.object(supervisor, "register_timer") as register_timer,
            patch.object(conditions, "subscribe") as hear_conditions,
            patch.object(pages, "subscribe") as hear_pages,
        ):
            AlarmService(
                container=container,
                supervisor=supervisor,
                condition_service=conditions,
                app_page_service=pages,
                web_push_service=WebPushService(None, container.config().baseurl),
                base_url=container.config().baseurl,
                outage_after_seconds=300,
            )

        register_job.assert_not_called()
        register_timer.assert_not_called()
        hear_conditions.assert_not_called()
        hear_pages.assert_not_called()
