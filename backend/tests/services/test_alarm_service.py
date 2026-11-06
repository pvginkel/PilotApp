"""The alarms (F142, F135.7, F144.4; DB decision 70; V06, V12): one
notification per person, under one sequence id, standing while the outage or
the week's halt is due, submitted, updated and dismissed through the fake
bridge.

The halts are proven one step in from the conditions service, the reconcile
driven with them holding by their codes; the wiring from the conditions
service with the outage and the store's update. Every test is on a database of
its own: a person's turn is an advisory lock on a connection of its own, which
reads committed rows alone."""

from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import or_, select

from app.database import scoped_session
from app.models import StoreUpdate, User
from app.schemas.conditions import ConditionCode
from app.services.alarm_service import (
    ALARM_CLEAR_DISMISSES_TOTAL,
    ALARM_CLEAR_JOB,
    ALARM_JOB,
    ALARM_RECONCILES_TOTAL,
    ALARM_SEQUENCE_ID,
    AlarmService,
)
from app.services.condition_service import ConditionService
from app.services.container import ServiceContainer
from app.services.controller_outage import ControllerOutage
from app.services.fake_notification_bridge import FakeCall, FakeNotification
from app.services.supervisor import LoopHandle, Supervisor
from app.utils.after_commit import clear_after_commit_callbacks
from app.utils.lifecycle_coordinator import LifecycleCoordinator
from tests.support.fake_notification_bridge import (
    WatchedFakeNotificationBridge,
    bridge_client_of,
)
from tests.support.locks import in_thread, lock_waits
from tests.support.store_updates import hold, lift
from tests.support.supervisor import (
    LogWaiter,
    Supervise,
    listening,
    metric_value,
    wait_until,
)

ADA_TOKEN = "token-of-ada"
BEN_TOKEN = "token-of-ben"
LOGGER = "app.services.alarm_service"
SUPERVISOR_LOGGER = "app.services.supervisor"
LONG_AGO = timedelta(hours=1)
OUTAGE = "The controller has been unreachable"
WEEK = "The week's usage halt"

type _Built = tuple[AlarmService, ControllerOutage, Supervisor, LifecycleCoordinator]
type _LastSent = tuple[str | None, datetime | None, datetime | None]


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
    outage_after_seconds: float = 300.0,
    retry_seconds: float = 60.0,
    configured: bool = True,
) -> _Built:
    """The alarms on a supervisor of their own, hearing a conditions service
    on an outage of its own."""
    supervisor, coordinator = supervise(container)
    outage = ControllerOutage()
    service = AlarmService(
        container=container,
        supervisor=supervisor,
        condition_service=ConditionService(
            container,
            outage,
            container.usage_halts(),
            container.sse_connection_manager(),
        ),
        notification_token_cipher=container.notification_token_cipher(),
        bridge_configured=configured,
        base_url=container.config().baseurl,
        outage_after_seconds=outage_after_seconds,
        retry_seconds=retry_seconds,
    )
    return service, outage, supervisor, coordinator


def _reconcile(
    service: AlarmService, holding: Mapping[ConditionCode, datetime]
) -> None:
    service.reconcile_holding(holding, LoopHandle("test"))


def _now() -> datetime:
    return datetime.now(UTC)


def _person(container: ServiceContainer, handle: str) -> User:
    return (
        container.db_session().scalars(select(User).where(User.handle == handle)).one()
    )


def _give_token(container: ServiceContainer, handle: str, token: str) -> None:
    """The token on the record, as it was before this reconcile's time."""
    with scoped_session(container):
        _person(
            container, handle
        ).notification_token = container.notification_token_cipher().seal(token)


def _switch(
    container: ServiceContainer, service: AlarmService, handle: str, *, on: bool
) -> None:
    """The person's alarms switch turned, as their profile turns it."""
    with scoped_session(container):
        _person(container, handle).alarms = on
        service.switched()


def _set(
    container: ServiceContainer, service: AlarmService, handle: str, token: str
) -> None:
    """The person's token set, as their profile's Save sets it."""
    with scoped_session(container):
        person = _person(container, handle)
        person.notification_token = container.notification_token_cipher().seal(token)
        service.submit_all(container.db_session(), person)


def _clear(container: ServiceContainer, service: AlarmService, handle: str) -> None:
    """The person's token cleared, as their profile's Clear clears it."""
    with scoped_session(container):
        person = _person(container, handle)
        token = container.notification_token_cipher().open(person)
        assert token is not None
        person.notification_token = None
        service.dismiss_all(container.db_session(), person, token)


def _last_sent(container: ServiceContainer, handle: str) -> _LastSent:
    """The text, sent time and owed time of the person's alarm notification,
    as committed."""
    with scoped_session(container):
        person = _person(container, handle)
        return person.alarm_text, person.alarm_sent_at, person.alarm_owed_at


def _standing(container: ServiceContainer, handle: str) -> bool:
    return _last_sent(container, handle)[0] is not None


def _owed(container: ServiceContainer, handle: str) -> bool:
    return _last_sent(container, handle)[2] is not None


def _holders(container: ServiceContainer) -> set[str]:
    """The handles of every User whose alarm notification was ever sent or is
    owed."""
    with scoped_session(container) as db:
        return set(
            db.scalars(
                select(User.handle).where(
                    or_(
                        User.alarm_sent_at.is_not(None), User.alarm_owed_at.is_not(None)
                    )
                )
            )
        )


def _expected(
    container: ServiceContainer, message: str, *, alerted: bool = True
) -> FakeNotification:
    return FakeNotification(
        sequence_id=ALARM_SEQUENCE_ID,
        priority="high",
        title="Pilot",
        message=message,
        url=f"{container.config().baseurl}/",
        alerted=alerted,
    )


def _reconciles(outcome: str) -> float:
    return metric_value(ALARM_RECONCILES_TOTAL, outcome=outcome)


def _clear_dismisses(outcome: str) -> float:
    return metric_value(ALARM_CLEAR_DISMISSES_TOTAL, outcome=outcome)


class TestAlarmServiceHolding:
    def test_none_holds_while_the_controller_answers(
        self, container: ServiceContainer, supervise: Supervise
    ) -> None:
        service, _, _, _ = _service(container, supervise)

        assert service.holding() == {}

    def test_the_outage_holds_by_its_code_from_its_turn_on(
        self, container: ServiceContainer, supervise: Supervise
    ) -> None:
        service, outage, _, _ = _service(container, supervise)

        outage.call_unanswered()

        assert service.holding() == {ConditionCode.OUTAGE: outage.since}

    def test_the_stores_update_holds_by_its_code_from_its_made_at(
        self, container: ServiceContainer, supervise: Supervise
    ) -> None:
        service, _, _, _ = _service(container, supervise)
        with scoped_session(container) as db:
            made_at = hold(db).made_at

        assert service.holding() == {ConditionCode.STORE_UPDATE: made_at}


class TestAlarmServiceReconcile:
    def test_the_weeks_halt_is_submitted_at_once_to_each_person_with_a_token_and_the_switch(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        _give_token(container, "ben", BEN_TOKEN)
        with scoped_session(container):
            _person(container, "ben").alarms = False
        service, _, _, _ = _service(container, supervise)
        sent = _reconciles("sent")

        _reconcile(service, {ConditionCode.WEEK_HALT: _now()})

        assert bridge.shown("ada") == {ALARM_SEQUENCE_ID: _expected(container, WEEK)}
        assert bridge.calls("ben") == []
        text, sent_at, owed_at = _last_sent(container, "ada")
        assert (text, owed_at) == (WEEK, None)
        assert sent_at is not None
        # Ben with the switch off, Cal with no token, and Pilot: none.
        assert _holders(container) == {"ada"}
        assert _reconciles("sent") == sent + 1

    @pytest.mark.parametrize(
        "condition", [ConditionCode.FIVE_HOUR_HALT, ConditionCode.STORE_UPDATE]
    )
    def test_the_five_hour_halt_and_the_stores_update_alarm_nobody(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
        condition: ConditionCode,
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _, _ = _service(container, supervise)

        _reconcile(service, {condition: _now() - LONG_AGO})

        assert bridge.calls("ada") == []
        assert _holders(container) == set()

    def test_the_last_condition_that_ceases_dismisses_it(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _, _ = _service(container, supervise)
        _reconcile(service, {ConditionCode.WEEK_HALT: _now()})
        submitted = _last_sent(container, "ada")[1]
        assert submitted is not None

        _reconcile(service, {})

        assert bridge.shown("ada") == {}
        assert bridge.calls("ada") == [
            FakeCall("submit", ALARM_SEQUENCE_ID, True),
            FakeCall("dismiss", ALARM_SEQUENCE_ID, False),
        ]
        text, dismissed, owed_at = _last_sent(container, "ada")
        assert (text, owed_at) == (None, None)
        assert dismissed is not None and dismissed > submitted

    def test_what_stands_is_not_sent_again(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _, _ = _service(container, supervise)
        holding = {ConditionCode.WEEK_HALT: _now()}
        _reconcile(service, holding)
        unchanged = _reconciles("unchanged")

        _reconcile(service, holding)

        assert bridge.calls("ada") == [FakeCall("submit", ALARM_SEQUENCE_ID, True)]
        assert _reconciles("unchanged") == unchanged + 1

    @pytest.mark.parametrize(
        ("outage_age", "week_age", "text"),
        [
            pytest.param(2, 1, f"{WEEK}, +1", id="the-weeks-halt-latest"),
            pytest.param(1, 2, f"{OUTAGE}, +1", id="the-outage-latest"),
        ],
    )
    def test_its_text_is_the_conditions_due_the_latest_begun_first(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
        outage_age: int,
        week_age: int,
        text: str,
    ) -> None:
        """The five-hour halt and the store's update, begun last, count for
        nothing."""
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _, _ = _service(container, supervise)
        now = _now()

        _reconcile(
            service,
            {
                ConditionCode.OUTAGE: now - outage_age * LONG_AGO,
                ConditionCode.WEEK_HALT: now - week_age * LONG_AGO,
                ConditionCode.FIVE_HOUR_HALT: now,
                ConditionCode.STORE_UPDATE: now,
            },
        )

        assert bridge.shown("ada") == {ALARM_SEQUENCE_ID: _expected(container, text)}
        assert _last_sent(container, "ada")[0] == text

    def test_a_turn_of_the_conditions_due_updates_it_in_place_silently(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _, _ = _service(container, supervise)
        week = _now() - 2 * LONG_AGO
        outage = _now() - LONG_AGO
        _reconcile(service, {ConditionCode.WEEK_HALT: week})

        _reconcile(
            service, {ConditionCode.WEEK_HALT: week, ConditionCode.OUTAGE: outage}
        )

        assert bridge.shown("ada") == {
            ALARM_SEQUENCE_ID: _expected(container, f"{OUTAGE}, +1", alerted=False)
        }

        _reconcile(service, {ConditionCode.OUTAGE: outage})

        assert bridge.shown("ada") == {
            ALARM_SEQUENCE_ID: _expected(container, OUTAGE, alerted=False)
        }
        assert bridge.calls("ada") == [
            FakeCall("submit", ALARM_SEQUENCE_ID, True),
            FakeCall("submit", ALARM_SEQUENCE_ID, False),
            FakeCall("submit", ALARM_SEQUENCE_ID, False),
        ]
        assert _last_sent(container, "ada")[0] == OUTAGE

    @pytest.mark.parametrize(("seconds", "due"), [(299, False), (301, True)])
    def test_the_outage_is_due_once_it_has_held_its_time(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
        seconds: int,
        due: bool,
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _, _ = _service(container, supervise, outage_after_seconds=300)

        _reconcile(service, {ConditionCode.OUTAGE: _now() - timedelta(seconds=seconds)})

        assert bridge.shown("ada") == (
            {ALARM_SEQUENCE_ID: _expected(container, OUTAGE)} if due else {}
        )
        assert _standing(container, "ada") is due


class TestAlarmServiceConditions:
    def test_each_turn_of_the_outage_asks_for_the_reconcile(
        self, container: ServiceContainer, supervise: Supervise
    ) -> None:
        service, outage, supervisor, _ = _service(container, supervise)

        with patch.object(
            supervisor, "start_loop", wraps=supervisor.start_loop
        ) as start:
            outage.call_unanswered()
            outage.probe_answered()

        assert [
            (call.args[0], call.args[1], call.kwargs) for call in start.call_args_list
        ] == [(ALARM_JOB, service.reconcile, {"again": True})] * 2

    def test_a_blip_buzzes_nobody(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        service, outage, _, _ = _service(container, supervise)

        outage.call_unanswered()
        service.reconcile(LoopHandle("test"))
        outage.probe_answered()
        service.reconcile(LoopHandle("test"))

        assert bridge.calls("ada") == []
        assert _holders(container) == set()

    def test_the_outage_reaches_the_phone_once_it_held_its_time_and_leaves_at_the_off(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        _, outage, _, coordinator = _service(
            container, supervise, outage_after_seconds=0.3
        )
        coordinator.fire_startup()
        log.wait_for(rf"Loop {ALARM_JOB} ended")

        outage.call_unanswered()
        since = outage.since
        assert since is not None

        wait_until(lambda: _standing(container, "ada"), "the outage's alarm submitted")
        assert bridge.shown("ada") == {ALARM_SEQUENCE_ID: _expected(container, OUTAGE)}
        sent_at = _last_sent(container, "ada")[1]
        assert sent_at is not None
        assert sent_at - since >= timedelta(seconds=0.3)

        outage.probe_answered()

        wait_until(lambda: bridge.shown("ada") == {}, "the outage's alarm dismissed")
        assert [call.call for call in bridge.calls("ada")] == ["submit", "dismiss"]

    def test_the_stores_update_reaches_no_phone(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        """Read through the conditions service, which holds it until its
        lift."""
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _, _ = _service(container, supervise)
        with scoped_session(container) as db:
            update_id = hold(db).id

        service.reconcile(LoopHandle("test"))
        with scoped_session(container) as db:
            lift(db, db.get_one(StoreUpdate, update_id))
        service.reconcile(LoopHandle("test"))

        assert bridge.calls("ada") == []

    def test_startup_dismisses_an_outage_alarm_a_stopped_process_left_standing(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        earlier, _, _, _ = _service(container, supervise)
        _reconcile(earlier, {ConditionCode.OUTAGE: _now() - LONG_AGO})
        assert ALARM_SEQUENCE_ID in bridge.shown("ada")
        _, _, _, coordinator = _service(container, supervise)

        coordinator.fire_startup()

        wait_until(lambda: bridge.shown("ada") == {}, "the outage's alarm dismissed")
        wait_until(lambda: not _standing(container, "ada"), "the dismiss recorded")


class TestAlarmServiceOwed:
    def test_a_send_the_bridge_does_not_answer_is_owed_and_logged_once(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _, _ = _service(container, supervise)
        holding = {ConditionCode.WEEK_HALT: _now()}
        owed = _reconciles("owed")
        bridge.unreachable()

        _reconcile(service, holding)
        _reconcile(service, holding)

        text, sent_at, owed_at = _last_sent(container, "ada")
        assert (text, sent_at) == (None, None)
        assert owed_at is not None
        assert _reconciles("owed") == owed + 2
        failures = [
            record
            for record in log.records
            if record.getMessage().startswith(
                "The submit of the alarm notification to ada is owed"
            )
        ]
        assert len(failures) == 1
        assert failures[0].levelname == "WARNING"

        bridge.unreachable(on=False)
        _reconcile(service, holding)

        assert _standing(container, "ada")
        assert not _owed(container, "ada")
        log.wait_for("The owed submit of the alarm notification to ada went out")

    def test_a_refused_token_is_owed(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _, _ = _service(container, supervise)
        bridge.rotate_token("ada", "a-rotated-token")

        _reconcile(service, {ConditionCode.WEEK_HALT: _now()})

        assert _owed(container, "ada")
        log.wait_for(r"The submit of the alarm notification to ada is owed: .*401.*")

    def test_an_update_the_bridge_does_not_take_keeps_what_was_last_sent(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _, _ = _service(container, supervise)
        week = _now() - 2 * LONG_AGO
        _reconcile(service, {ConditionCode.WEEK_HALT: week})
        both = {ConditionCode.WEEK_HALT: week, ConditionCode.OUTAGE: _now() - LONG_AGO}
        bridge.unreachable()

        _reconcile(service, both)

        assert _last_sent(container, "ada")[0] == WEEK
        assert _owed(container, "ada")
        bridge.unreachable(on=False)
        _reconcile(service, both)
        assert _last_sent(container, "ada")[0] == f"{OUTAGE}, +1"
        assert not _owed(container, "ada")

    def test_an_owed_dismiss_is_sent_again_with_nothing_else_changed(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _, _ = _service(container, supervise)
        _reconcile(service, {ConditionCode.WEEK_HALT: _now()})
        bridge.unreachable()
        _reconcile(service, {})
        assert _owed(container, "ada")
        assert _standing(container, "ada")

        bridge.unreachable(on=False)
        _reconcile(service, {})

        assert bridge.shown("ada") == {}
        assert not _owed(container, "ada")
        assert not _standing(container, "ada")


class TestAlarmServiceRetry:
    def test_the_timer_asks_for_the_reconcile_when_the_alarms_due_turn(
        self, container: ServiceContainer, supervise: Supervise
    ) -> None:
        service, outage, supervisor, _ = _service(
            container, supervise, outage_after_seconds=0
        )
        _reconcile(service, {})
        outage.call_unanswered()

        with patch.object(
            supervisor, "start_loop", wraps=supervisor.start_loop
        ) as start:
            with scoped_session(container) as db:
                service.retry(db)

        assert [(call.args[0], call.kwargs) for call in start.call_args_list] == [
            (ALARM_JOB, {"again": False})
        ]

    def test_the_timer_asks_for_nothing_while_the_alarms_due_stand_as_read(
        self, container: ServiceContainer, supervise: Supervise
    ) -> None:
        service, outage, supervisor, _ = _service(
            container, supervise, outage_after_seconds=0
        )
        outage.call_unanswered()
        _reconcile(service, service.holding())

        with patch.object(
            supervisor, "start_loop", wraps=supervisor.start_loop
        ) as start:
            with scoped_session(container) as db:
                service.retry(db)

        start.assert_not_called()

    @pytest.mark.parametrize(
        ("age", "asked"),
        [(None, False), (timedelta(0), False), (timedelta(seconds=61), True)],
    )
    def test_the_timer_asks_for_it_while_a_send_is_owed_past_its_retry(
        self,
        container: ServiceContainer,
        supervise: Supervise,
        age: timedelta | None,
        asked: bool,
    ) -> None:
        with scoped_session(container):
            _person(container, "ada").alarm_owed_at = (
                None if age is None else _now() - age
            )
        service, _, supervisor, _ = _service(container, supervise, retry_seconds=60)

        with patch.object(
            supervisor, "start_loop", wraps=supervisor.start_loop
        ) as start:
            with scoped_session(container) as db:
                service.retry(db)

        assert [(call.args[0], call.kwargs) for call in start.call_args_list] == (
            [(ALARM_JOB, {"again": False})] if asked else []
        )

    def test_an_owed_send_goes_out_on_the_timer_once_the_bridge_answers(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        _, outage, _, coordinator = _service(
            container, supervise, outage_after_seconds=0, retry_seconds=0
        )
        bridge.unreachable()
        coordinator.fire_startup()

        outage.call_unanswered()
        log.wait_for(r"The submit of the alarm notification to ada is owed: .*")
        bridge.unreachable(on=False)

        log.wait_for("The owed submit of the alarm notification to ada went out")
        assert bridge.shown("ada") == {ALARM_SEQUENCE_ID: _expected(container, OUTAGE)}


class TestAlarmServiceSwitched:
    def test_off_dismisses_the_persons_alarm_and_on_submits_it(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        _give_token(container, "ben", BEN_TOKEN)
        service, _, _, _ = _service(container, supervise)
        holding = {ConditionCode.WEEK_HALT: _now()}
        _reconcile(service, holding)

        _switch(container, service, "ada", on=False)
        _reconcile(service, holding)

        assert bridge.shown("ada") == {}
        assert not _standing(container, "ada")
        assert set(bridge.shown("ben")) == {ALARM_SEQUENCE_ID}

        _switch(container, service, "ada", on=True)
        _reconcile(service, holding)

        assert bridge.shown("ada") == {ALARM_SEQUENCE_ID: _expected(container, WEEK)}
        assert [call.call for call in bridge.calls("ada")] == [
            "submit",
            "dismiss",
            "submit",
        ]

    def test_its_dismiss_is_owed_while_the_bridge_does_not_take_it(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _, _ = _service(container, supervise)
        holding = {ConditionCode.WEEK_HALT: _now()}
        _reconcile(service, holding)
        bridge.unreachable()
        _switch(container, service, "ada", on=False)

        _reconcile(service, holding)

        assert _owed(container, "ada")
        assert _standing(container, "ada")
        bridge.unreachable(on=False)
        _reconcile(service, holding)
        assert bridge.shown("ada") == {}
        assert not _owed(container, "ada")

    def test_its_reconcile_is_asked_for_once_it_commits(
        self, container: ServiceContainer, supervise: Supervise
    ) -> None:
        service, _, supervisor, _ = _service(container, supervise)

        with patch.object(
            supervisor, "start_loop", wraps=supervisor.start_loop
        ) as start:
            with scoped_session(container):
                _person(container, "ada").alarms = False
                service.switched()
                start.assert_not_called()

        assert [(call.args[0], call.kwargs) for call in start.call_args_list] == [
            (ALARM_JOB, {"again": True})
        ]

    def test_with_no_bridge_it_asks_for_nothing(
        self, container: ServiceContainer, supervise: Supervise
    ) -> None:
        service, _, supervisor, _ = _service(container, supervise, configured=False)

        with patch.object(supervisor, "start_loop") as start:
            _switch(container, service, "ada", on=False)

        start.assert_not_called()


class TestAlarmServiceSubmitAll:
    def test_a_first_token_has_the_alarm_submitted_through_it(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        service, outage, _, _ = _service(container, supervise, outage_after_seconds=0)
        outage.call_unanswered()

        _set(container, service, "ada", ADA_TOKEN)
        service.reconcile(LoopHandle("test"))

        assert bridge.shown("ada") == {ALARM_SEQUENCE_ID: _expected(container, OUTAGE)}

    def test_a_replace_resubmits_through_the_new_token_and_sends_nothing_through_the_old(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        service, outage, _, _ = _service(container, supervise, outage_after_seconds=0)
        outage.call_unanswered()
        service.reconcile(LoopHandle("test"))
        bridge.rotate_token("ada", "token-of-ada-rotated")

        _set(container, service, "ada", "token-of-ada-rotated")

        assert not _standing(container, "ada")
        service.reconcile(LoopHandle("test"))
        assert bridge.calls("ada") == [
            FakeCall("submit", ALARM_SEQUENCE_ID, True),
            FakeCall("submit", ALARM_SEQUENCE_ID, False),
        ]
        assert bridge.shown("ada") == {
            ALARM_SEQUENCE_ID: _expected(container, OUTAGE, alerted=False)
        }
        assert _standing(container, "ada")

    def test_a_replace_with_none_due_leaves_it_standing_for_its_dismiss(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        """The week's halt ceased before the replace: its dismiss goes
        through the new token."""
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _, _ = _service(container, supervise)
        _reconcile(service, {ConditionCode.WEEK_HALT: _now()})
        bridge.rotate_token("ada", "token-of-ada-rotated")

        _set(container, service, "ada", "token-of-ada-rotated")

        assert _standing(container, "ada")
        service.reconcile(LoopHandle("test"))
        assert bridge.calls("ada") == [
            FakeCall("submit", ALARM_SEQUENCE_ID, True),
            FakeCall("dismiss", ALARM_SEQUENCE_ID, False),
        ]
        assert not _standing(container, "ada")

    def test_with_the_switch_off_nothing_is_submitted(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        service, outage, _, _ = _service(container, supervise, outage_after_seconds=0)
        outage.call_unanswered()
        with scoped_session(container):
            _person(container, "ada").alarms = False

        _set(container, service, "ada", ADA_TOKEN)
        service.reconcile(LoopHandle("test"))

        assert bridge.calls("ada") == []

    def test_its_reconcile_is_asked_for_once_it_commits(
        self, container: ServiceContainer, supervise: Supervise
    ) -> None:
        service, _, supervisor, _ = _service(container, supervise)

        with patch.object(
            supervisor, "start_loop", wraps=supervisor.start_loop
        ) as start:
            _set(container, service, "ada", ADA_TOKEN)

        assert [(call.args[0], call.kwargs) for call in start.call_args_list] == [
            (ALARM_JOB, {"again": True})
        ]


class TestAlarmServiceDismissAll:
    def test_a_clear_reads_dismissed_at_once_and_is_dismissed_once_off_the_request(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        """An owed update among what stood."""
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _, coordinator = _service(container, supervise)
        week = _now() - LONG_AGO
        _reconcile(service, {ConditionCode.WEEK_HALT: week})
        bridge.unreachable()
        _reconcile(service, {ConditionCode.WEEK_HALT: week, ConditionCode.OUTAGE: week})
        bridge.unreachable(on=False)
        assert _owed(container, "ada")
        sent = _clear_dismisses("sent")

        _clear(container, service, "ada")

        assert not _standing(container, "ada")
        assert not _owed(container, "ada")
        coordinator.fire_startup()
        log.wait_for(rf"Loop {ALARM_CLEAR_JOB}:1 ended")
        assert bridge.shown("ada") == {}
        assert bridge.calls("ada")[1:] == [
            FakeCall("dismiss", ALARM_SEQUENCE_ID, False)
        ]
        assert _clear_dismisses("sent") == sent + 1

    def test_a_clear_with_none_standing_or_owed_dismisses_nothing(
        self, container: ServiceContainer, supervise: Supervise
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        service, _, supervisor, _ = _service(container, supervise)

        with patch.object(supervisor, "start_loop") as start:
            _clear(container, service, "ada")

        start.assert_not_called()

    def test_a_dismiss_the_bridge_does_not_take_is_logged_counted_and_not_owed(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _, _ = _service(container, supervise)
        _reconcile(service, {ConditionCode.WEEK_HALT: _now()})
        unanswered = _clear_dismisses("unanswered")
        bridge.unreachable()
        _clear(container, service, "ada")

        service.dismiss_cleared(
            _person(container, "ada").id, ADA_TOKEN, LoopHandle("clear")
        )

        log.wait_for(
            "The dismiss of the alarm notification to ada after their token's"
            r" clear failed, and it stays on the phone: .*"
        )
        assert _clear_dismisses("unanswered") == unanswered + 1
        assert not _owed(container, "ada")
        bridge.unreachable(on=False)
        assert set(bridge.shown("ada")) == {ALARM_SEQUENCE_ID}

    def test_the_same_token_set_again_is_not_dismissed(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
        log: LogWaiter,
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _, _ = _service(container, supervise)
        holding = {ConditionCode.WEEK_HALT: _now()}
        _reconcile(service, holding)
        _clear(container, service, "ada")
        _set(container, service, "ada", ADA_TOKEN)
        _reconcile(service, holding)

        service.dismiss_cleared(
            _person(container, "ada").id, ADA_TOKEN, LoopHandle("clear")
        )

        assert [call.call for call in bridge.calls("ada")] == ["submit", "submit"]
        assert set(bridge.shown("ada")) == {ALARM_SEQUENCE_ID}
        log.wait_for(
            "ada holds the token they cleared again: their alarm notification is"
            " not dismissed"
        )

    def test_a_stop_before_it_runs_dismisses_nothing(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _, _ = _service(container, supervise)
        _reconcile(service, {ConditionCode.WEEK_HALT: _now()})
        _clear(container, service, "ada")
        handle = LoopHandle("clear")
        handle._request_stop()

        service.dismiss_cleared(_person(container, "ada").id, ADA_TOKEN, handle)

        assert set(bridge.shown("ada")) == {ALARM_SEQUENCE_ID}

    def test_with_no_bridge_the_record_alone_moves(
        self, container: ServiceContainer, supervise: Supervise
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        with scoped_session(container):
            person = _person(container, "ada")
            person.alarm_text = WEEK
            person.alarm_sent_at = _now()
        service, _, supervisor, _ = _service(container, supervise, configured=False)

        with patch.object(supervisor, "start_loop") as start:
            _clear(container, service, "ada")
            _set(container, service, "ada", ADA_TOKEN)

        start.assert_not_called()
        assert not _standing(container, "ada")


class TestAlarmServiceInFlight:
    def test_a_clear_during_a_first_submit_is_followed_by_its_dismiss(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _, _ = _service(container, supervise)
        superseded, sent = _reconciles("superseded"), _clear_dismisses("sent")
        bridge.on_submit = lambda: _clear(container, service, "ada")

        _reconcile(service, {ConditionCode.WEEK_HALT: _now()})

        assert bridge.calls("ada") == [
            FakeCall("submit", ALARM_SEQUENCE_ID, True),
            FakeCall("dismiss", ALARM_SEQUENCE_ID, False),
        ]
        assert bridge.shown("ada") == {}
        assert _last_sent(container, "ada") == (None, None, None)
        assert _reconciles("superseded") == superseded + 1
        assert _clear_dismisses("sent") == sent + 1

    @pytest.mark.parametrize("answered", [True, False])
    def test_a_clear_committing_during_a_first_submits_write_back_reads_what_it_wrote(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
        log: LogWaiter,
        answered: bool,
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        service, _, _, coordinator = _service(container, supervise)
        holding = {ConditionCode.WEEK_HALT: _now()}
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
            _reconcile(service, holding)
        clears[0].result()

        assert not _standing(container, "ada")
        assert not _owed(container, "ada")
        _reconcile(service, holding)
        bridge.unreachable(on=False)
        coordinator.fire_startup()
        log.wait_for(rf"Loop {ALARM_CLEAR_JOB}:1 ended")
        assert bridge.shown("ada") == {}
        assert [call.call for call in bridge.calls("ada")][-1] == "dismiss"

    def test_two_processes_take_turns_and_the_phone_ends_on_the_latest_state(
        self,
        container: ServiceContainer,
        bridge: WatchedFakeNotificationBridge,
        supervise: Supervise,
    ) -> None:
        _give_token(container, "ada", ADA_TOKEN)
        old, _, _, _ = _service(container, supervise)
        new, _, _, _ = _service(container, supervise)
        holding = {ConditionCode.WEEK_HALT: _now()}
        bridge.unreachable()
        _reconcile(old, holding)
        bridge.unreachable(on=False)
        turns = []

        def switch_off_and_reconcile_in_the_other() -> None:
            with scoped_session(container):
                _person(container, "ada").alarms = False
            turns.append(in_thread(lambda: _reconcile(new, holding)))
            wait_until(lambda: lock_waits(container) == 1, "the other's turn waiting")

        bridge.on_submit = switch_off_and_reconcile_in_the_other

        _reconcile(old, holding)
        turns[0].result()

        assert [call.call for call in bridge.calls("ada")] == ["submit", "dismiss"]
        assert bridge.shown("ada") == {}
        assert not _standing(container, "ada")
        assert not _owed(container, "ada")
