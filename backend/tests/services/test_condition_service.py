"""The conditions that hold all work, which the gold bar shows (UC *The gold
bar*; F125, F135.7, F144.4; design 2 §13.4; design 5 D8): the outage, the
store's update and the usage halts, read, and
told to every person's connections at once when one turns, the outage's turn
on a loop of its own. Read off test connections' queues; the outage's turns
on a database of their own, as the supervisor runs the loop."""

import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from queue import Empty
from typing import Any

import pytest
from flask import Flask
from sqlalchemy.orm import Session as DbSession

from app.app_config import HaltSetting
from app.database import scoped_session
from app.models import UsageReading, User, WindowShare
from app.models.reference import UsageWindow
from app.services.condition_service import CONDITIONS_JOB, ConditionService
from app.services.container import ServiceContainer
from app.services.controller_outage import ControllerOutage
from app.services.sse_connection_manager import SSEConnection, SSEConnectionManager
from app.services.usage_halts import UsageHalts
from tests.support.store_updates import hold, lift
from tests.support.supervisor import WAIT_SECONDS, Supervise


@pytest.fixture
def manager(container: ServiceContainer) -> SSEConnectionManager:
    return container.sse_connection_manager()


@pytest.fixture
def conditions(
    container: ServiceContainer,
    controller_outage: ControllerOutage,
    manager: SSEConnectionManager,
    supervise: Supervise,
) -> ConditionService:
    """A service of its own, on the test's outage and a supervisor of its
    own, which never starts: the outage's turns are told by no loop."""
    supervisor, _ = supervise(container, controller_configured=False)
    return ConditionService(
        container, supervisor, controller_outage, container.usage_halts(), manager
    )


@pytest.fixture
def connections(manager: SSEConnectionManager) -> Iterator[list[SSEConnection]]:
    opened: list[SSEConnection] = []
    yield opened
    for connection in opened:
        manager.on_disconnect(connection)


def _frames(connection: SSEConnection) -> list[dict[str, Any]]:
    queued = []
    while True:
        try:
            frame = connection.next_frame(timeout=0)
        except Empty:
            return queued
        assert frame is not None
        queued.append(json.loads(frame.removeprefix("data: ")))


def _next(connection: SSEConnection) -> dict[str, Any]:
    """The connection's next frame, which another thread sends."""
    frame = connection.next_frame(timeout=WAIT_SECONDS)
    assert frame is not None
    parsed: dict[str, Any] = json.loads(frame.removeprefix("data: "))
    return parsed


def _usage(db: DbSession, *, week: float, five_hour: float) -> UsageReading:
    """A fresh Usage Reading recorded now with these shares."""
    now = datetime.now(UTC)
    reading = UsageReading(
        taken_at=now - timedelta(minutes=3), received_at=now, stale=False
    )
    db.add(reading)
    db.flush()
    db.add_all(
        WindowShare(
            reading_id=reading.id,
            window_code=window,
            share=share,
            resets_at=now + timedelta(days=1),
        )
        for window, share in (
            (UsageWindow.SEVEN_DAY, week),
            (UsageWindow.FIVE_HOUR, five_hour),
        )
    )
    db.flush()
    return reading


class TestConditionService:
    def test_none_holds_while_the_controller_answers(
        self, conditions: ConditionService
    ) -> None:
        assert conditions.conditions().model_dump() == {"conditions": []}

    def test_the_outage_holds_from_its_turn_on(
        self, conditions: ConditionService, controller_outage: ControllerOutage
    ) -> None:
        controller_outage.call_unanswered()

        assert conditions.conditions().model_dump() == {
            "conditions": [
                {
                    "code": "outage",
                    "since": controller_outage.since,
                    "share": None,
                    "taken_at": None,
                    "stale": None,
                    "offer": None,
                    "target": None,
                    "setting": None,
                }
            ]
        }

    def test_the_halts_hold_after_the_outage_the_weeks_first_with_share_and_age(
        self,
        conditions: ConditionService,
        controller_outage: ControllerOutage,
        session: DbSession,
    ) -> None:
        controller_outage.call_unanswered()
        reading = _usage(session, week=0.92, five_hour=0.8)

        assert conditions.conditions().model_dump() == {
            "conditions": [
                {
                    "code": "outage",
                    "since": controller_outage.since,
                    "share": None,
                    "taken_at": None,
                    "stale": None,
                    "offer": None,
                    "target": None,
                    "setting": None,
                },
                {
                    "code": "week_halt",
                    "since": reading.received_at,
                    "share": 0.92,
                    "taken_at": reading.taken_at,
                    "stale": False,
                    "offer": "allowance",
                    "target": pytest.approx(0.97),
                    "setting": "cooperative_stop",
                },
                {
                    "code": "five_hour_halt",
                    "since": reading.received_at,
                    "share": 0.8,
                    "taken_at": reading.taken_at,
                    "stale": False,
                    "offer": None,
                    "target": None,
                    "setting": "cooperative_stop",
                },
            ]
        }

    @pytest.mark.parametrize(
        ("week_halt", "five_hour_halt"),
        [
            (HaltSetting.NO_NEW_WORK, HaltSetting.HARD_STOP),
            (HaltSetting.HARD_STOP, HaltSetting.COOPERATIVE_STOP),
            (HaltSetting.COOPERATIVE_STOP, HaltSetting.NO_NEW_WORK),
        ],
    )
    def test_a_halt_carries_its_windows_setting(
        self,
        container: ServiceContainer,
        controller_outage: ControllerOutage,
        manager: SSEConnectionManager,
        session: DbSession,
        supervise: Supervise,
        week_halt: HaltSetting,
        five_hour_halt: HaltSetting,
    ) -> None:
        halts = UsageHalts(
            week_limit=0.9,
            week_allowance=0.05,
            week_second_limit=0.98,
            five_hour_limit=0.75,
            week_halt=week_halt,
            five_hour_halt=five_hour_halt,
        )
        supervisor, _ = supervise(container, controller_configured=False)
        conditions = ConditionService(
            container, supervisor, controller_outage, halts, manager
        )
        _usage(session, week=0.92, five_hour=0.8)

        held = conditions.conditions().model_dump(mode="json")["conditions"]

        assert [(c["code"], c["setting"]) for c in held] == [
            ("week_halt", week_halt.value),
            ("five_hour_halt", five_hour_halt.value),
        ]

    def test_the_stores_update_holds_after_the_outage_before_the_halts_since_made(
        self,
        conditions: ConditionService,
        controller_outage: ControllerOutage,
        session: DbSession,
    ) -> None:
        controller_outage.call_unanswered()
        update = hold(session)
        _usage(session, week=0.5, five_hour=0.8)

        held = conditions.conditions().model_dump()["conditions"]

        assert [condition["code"] for condition in held] == [
            "outage",
            "store_update",
            "five_hour_halt",
        ]
        assert held[1] == {
            "code": "store_update",
            "since": update.made_at,
            "share": None,
            "taken_at": None,
            "stale": None,
            "offer": None,
            "target": None,
            "setting": None,
        }

    def test_the_stores_update_holds_until_its_lift(
        self, conditions: ConditionService, session: DbSession
    ) -> None:
        update = hold(session)
        assert [c.code for c in conditions.conditions().conditions] == ["store_update"]

        lift(session, update)

        assert conditions.conditions().conditions == []

    def test_the_stores_update_is_told_with_the_conditions(
        self,
        conditions: ConditionService,
        manager: SSEConnectionManager,
        connections: list[SSEConnection],
        person: User,
        session: DbSession,
    ) -> None:
        """The server tells them at the hold's change (P3); here the test
        does."""
        connections.append(manager.on_connect("ada-1", person.subject))
        hold(session)

        conditions.tell()

        [frame] = _frames(connections[0])
        assert [c["code"] for c in frame["payload"]["conditions"]] == ["store_update"]

    def test_a_halt_is_told_with_the_conditions(
        self,
        conditions: ConditionService,
        manager: SSEConnectionManager,
        connections: list[SSEConnection],
        person: User,
        session: DbSession,
    ) -> None:
        connections.append(manager.on_connect("ada-1", person.subject))
        _usage(session, week=0.5, five_hour=0.8)

        conditions.tell()

        [frame] = _frames(connections[0])
        assert [c["code"] for c in frame["payload"]["conditions"]] == ["five_hour_halt"]

    def test_each_listener_hears_every_tell(
        self, conditions: ConditionService, controller_outage: ControllerOutage
    ) -> None:
        heard: list[tuple[str, bool]] = []
        for name in ("first", "second"):
            conditions.subscribe(
                lambda name=name: heard.append((name, controller_outage.holds))
            )

        conditions.tell()
        controller_outage.call_unanswered()
        conditions.tell()

        assert heard == [
            ("first", False),
            ("second", False),
            ("first", True),
            ("second", True),
        ]


class TestConditionServiceOutageTurn:
    """The outage's turns, told on the loop `conditions`, on a database of
    their own."""

    @pytest.fixture
    def outage(self) -> ControllerOutage:
        return ControllerOutage()

    @pytest.fixture
    def told(
        self,
        committed_app: Flask,
        outage: ControllerOutage,
        supervise: Supervise,
    ) -> ConditionService:
        """A service on `outage`, its supervisor started."""
        container: ServiceContainer = committed_app.container
        supervisor, coordinator = supervise(container, controller_configured=False)
        service = ConditionService(
            container,
            supervisor,
            outage,
            container.usage_halts(),
            container.sse_connection_manager(),
        )
        coordinator.fire_startup()
        return service

    @pytest.fixture
    def committed_connections(
        self, committed_app: Flask
    ) -> Iterator[list[SSEConnection]]:
        manager = committed_app.container.sse_connection_manager()
        opened: list[SSEConnection] = []
        yield opened
        for connection in opened:
            manager.on_disconnect(connection)

    def test_every_persons_connections_hear_each_turn_at_once(
        self,
        committed_app: Flask,
        told: ConditionService,
        outage: ControllerOutage,
        committed_connections: list[SSEConnection],
    ) -> None:
        container: ServiceContainer = committed_app.container
        manager = container.sse_connection_manager()
        with scoped_session(container):
            data = container.test_data_service()
            ada_subject = data.person("ada", "Ada Example").subject
            ben_subject = data.person("ben", "Ben Example").subject
        assert ada_subject is not None
        assert ben_subject is not None
        committed_connections.extend(
            [
                manager.on_connect("ada-1", ada_subject),
                manager.on_connect("ben-1", ben_subject),
                manager.on_connect("newcomer-1", "subject-newcomer"),
            ]
        )
        ada, ben, newcomer = committed_connections

        outage.call_unanswered()
        since = outage.since
        assert since is not None
        heard_on = (_next(ada), _next(ben))
        outage.probe_answered()
        heard_off = (_next(ada), _next(ben))

        on = {
            "type": "conditions_changed",
            "payload": {
                "conditions": [
                    {
                        "code": "outage",
                        "since": since.isoformat().replace("+00:00", "Z"),
                        "share": None,
                        "taken_at": None,
                        "stale": None,
                        "offer": None,
                        "target": None,
                        "setting": None,
                    }
                ]
            },
        }
        off = {"type": "conditions_changed", "payload": {"conditions": []}}
        assert (heard_on, heard_off) == ((on, on), (off, off))
        assert _frames(newcomer) == []

    def test_each_listener_hears_each_turn_on_the_loop_not_the_turning_thread(
        self, told: ConditionService, outage: ControllerOutage
    ) -> None:
        heard: list[tuple[str, str, bool]] = []
        turned = threading.Semaphore(0)

        def hear(name: str) -> None:
            heard.append((name, threading.current_thread().name, outage.holds))
            turned.release()

        for name in ("first", "second"):
            told.subscribe(lambda name=name: hear(name))

        outage.call_unanswered()
        assert all(turned.acquire(timeout=WAIT_SECONDS) for _ in range(2))
        outage.probe_answered()
        assert all(turned.acquire(timeout=WAIT_SECONDS) for _ in range(2))

        loop = f"job-{CONDITIONS_JOB}"
        assert heard == [
            ("first", loop, True),
            ("second", loop, True),
            ("first", loop, False),
            ("second", loop, False),
        ]
