"""The engine's bus: typed, in-process, delivered once the transaction that
caused an event has committed."""

import pytest
from flask import Flask

from app.database import scoped_session
from app.engine.bus import EngineEvent, TreeHashMoved
from app.services.container import ServiceContainer

MOVED = TreeHashMoved("draft-1/project.md", "a" * 64)
MOVED_AGAIN = TreeHashMoved("draft-1/project.md", "b" * 64)


class TestEngineBus:
    def test_an_event_waits_for_the_commit_off_the_request_path(
        self, container: ServiceContainer, engine_events: list[EngineEvent]
    ) -> None:
        with scoped_session(container):
            container.engine_bus().emit(MOVED)
            assert engine_events == []

        assert engine_events == [MOVED]

    def test_an_event_waits_for_the_requests_commit(
        self,
        app: Flask,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
    ) -> None:
        with app.test_request_context():
            container.engine_bus().emit(MOVED)
            assert engine_events == []

        assert engine_events == [MOVED]

    def test_a_rolled_back_transaction_delivers_nothing(
        self, container: ServiceContainer, engine_events: list[EngineEvent]
    ) -> None:
        with pytest.raises(RuntimeError), scoped_session(container):
            container.engine_bus().emit(MOVED)
            raise RuntimeError("the transaction fails")

        with scoped_session(container):
            pass

        assert engine_events == []

    def test_events_arrive_in_order_and_an_equal_one_once(
        self, container: ServiceContainer, engine_events: list[EngineEvent]
    ) -> None:
        bus = container.engine_bus()
        with scoped_session(container):
            bus.emit(MOVED)
            bus.emit(MOVED_AGAIN)
            bus.emit(MOVED)

        assert engine_events == [MOVED, MOVED_AGAIN]

    def test_every_subscriber_receives_every_event(
        self, container: ServiceContainer, engine_events: list[EngineEvent]
    ) -> None:
        bus = container.engine_bus()
        other: list[EngineEvent] = []
        bus.subscribe(other.append)
        try:
            with scoped_session(container):
                bus.emit(MOVED)
        finally:
            bus.unsubscribe(other.append)

        assert engine_events == [MOVED]
        assert other == [MOVED]

    def test_a_failing_subscriber_keeps_the_event_from_no_other(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        bus = container.engine_bus()
        other: list[EngineEvent] = []

        def fail(event: EngineEvent) -> None:
            raise RuntimeError("the subscriber fails")

        bus.subscribe(fail)
        bus.subscribe(other.append)
        try:
            with scoped_session(container):
                bus.emit(MOVED)
        finally:
            bus.unsubscribe(other.append)
            bus.unsubscribe(fail)

        assert engine_events == [MOVED]
        assert other == [MOVED]
        [failure] = [
            record for record in caplog.records if record.name == "app.engine.bus"
        ]
        assert failure.exc_info is not None
        assert str(failure.exc_info[1]) == "the subscriber fails"

    def test_an_unsubscribed_subscriber_receives_nothing(
        self, container: ServiceContainer, engine_events: list[EngineEvent]
    ) -> None:
        bus = container.engine_bus()
        other: list[EngineEvent] = []
        bus.subscribe(other.append)
        bus.unsubscribe(other.append)

        with scoped_session(container):
            bus.emit(MOVED)

        assert other == []
        assert engine_events == [MOVED]

    def test_unsubscribing_a_stranger_is_refused(
        self, container: ServiceContainer
    ) -> None:
        with pytest.raises(ValueError):
            container.engine_bus().unsubscribe([].append)
