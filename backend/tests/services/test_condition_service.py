"""The conditions that hold all work, which the gold bar shows (UC *The gold
bar*; F125; design 2 §13.4): read, and told to every person's connections at
once when one turns. Read off test connections' queues."""

import json
from collections.abc import Iterator
from queue import Empty
from typing import Any

import pytest

from app.models import User
from app.services.condition_service import ConditionService
from app.services.container import ServiceContainer
from app.services.controller_outage import ControllerOutage
from app.services.sse_connection_manager import SSEConnection, SSEConnectionManager


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
    return ConditionService(container, controller_outage, manager)


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
            "conditions": [{"code": "outage", "since": controller_outage.since}]
        }

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
