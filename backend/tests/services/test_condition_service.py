"""The conditions that hold all work, which the gold bar shows (UC *The gold
bar*; F125, F135.7, F144.4; design 2 §13.4; design 5 D8): the outage, the
store's update and the usage halts, read, and
told to every person's connections at once when one turns. Read off test
connections' queues."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from queue import Empty
from typing import Any

import pytest
from sqlalchemy.orm import Session as DbSession

from app.app_config import HaltSetting
from app.models import UsageReading, User, WindowShare
from app.models.reference import UsageWindow
from app.services.condition_service import ConditionService
from app.services.container import ServiceContainer
from app.services.controller_outage import ControllerOutage
from app.services.sse_connection_manager import SSEConnection, SSEConnectionManager
from app.services.usage_halts import UsageHalts
from tests.support.store_updates import hold, lift


@pytest.fixture
def manager(container: ServiceContainer) -> SSEConnectionManager:
    return container.sse_connection_manager()


@pytest.fixture
def conditions(
    container: ServiceContainer,
    controller_outage: ControllerOutage,
    manager: SSEConnectionManager,
) -> ConditionService:
    """A service of its own, on the test's outage."""
    return ConditionService(
        container, controller_outage, container.usage_halts(), manager
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
        conditions = ConditionService(container, controller_outage, halts, manager)
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

    def test_every_persons_connections_hear_each_turn_at_once(
        self,
        container: ServiceContainer,
        conditions: ConditionService,
        controller_outage: ControllerOutage,
        manager: SSEConnectionManager,
        connections: list[SSEConnection],
        person: User,
    ) -> None:
        ben = container.test_data_service().person("ben", "Ben Example")
        connections.extend(
            [
                manager.on_connect("ada-1", person.subject),
                manager.on_connect("ben-1", ben.subject),
                manager.on_connect("newcomer-1", "subject-newcomer"),
            ]
        )
        ada, ben_tab, newcomer = connections

        controller_outage.call_unanswered()
        since = controller_outage.since
        assert since is not None
        controller_outage.probe_answered()

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
        assert (_frames(ada), _frames(ben_tab)) == ([on, off], [on, off])
        assert _frames(newcomer) == []

    def test_each_listener_hears_every_tell(
        self, conditions: ConditionService, controller_outage: ControllerOutage
    ) -> None:
        heard: list[tuple[str, bool]] = []
        for name in ("first", "second"):
            conditions.subscribe(
                lambda name=name: heard.append((name, controller_outage.holds))
            )

        controller_outage.call_unanswered()
        controller_outage.probe_answered()
        conditions.tell()

        assert heard == [
            ("first", True),
            ("second", True),
            ("first", False),
            ("second", False),
            ("first", False),
            ("second", False),
        ]
