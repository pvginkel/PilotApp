"""The store sidecar's change streams (design 1 §5.4): a subscriber of the
engine's bus per stream, which never blocks the commit that delivers to it,
ended when it falls behind and on `PREPARE_SHUTDOWN`."""

import logging
import uuid
from queue import Empty

import pytest
from prometheus_client.metrics import MetricWrapperBase

from app.database import scoped_session
from app.engine.bus import (
    DocumentModified,
    ErrorsRaised,
    ErrorsResolved,
    ManifestChanged,
    TreeHashMoved,
)
from app.services.container import ServiceContainer
from app.services.sync_stream_service import (
    STREAM_CONNECTED,
    STREAM_CONNECTS_TOTAL,
    SyncStream,
    SyncStreamService,
)
from app.utils.lifecycle_coordinator import LifecycleCoordinator

MOVED = TreeHashMoved("draft-1/project.md", "a" * 64)
TIMELINE_MOVED = TreeHashMoved("draft-1/timeline.json", "b" * 64)

WAIT = 0.01


def _sample(metric: MetricWrapperBase, name: str) -> float:
    for family in metric.collect():
        for sample in family.samples:
            if sample.name == name:
                return sample.value
    return 0.0


def _counts() -> tuple[float, float]:
    return (
        _sample(STREAM_CONNECTS_TOTAL, "pilot_sync_stream_connects_total"),
        _sample(STREAM_CONNECTED, "pilot_sync_stream_connected"),
    )


@pytest.fixture
def coordinator() -> LifecycleCoordinator:
    return LifecycleCoordinator(graceful_shutdown_timeout=1)


@pytest.fixture
def streams(
    container: ServiceContainer, coordinator: LifecycleCoordinator
) -> SyncStreamService:
    """A stream service of its own on the app's bus: its shutdown is not the
    app's."""
    return SyncStreamService(container.engine_bus(), coordinator)


class TestSyncStreamService:
    def test_open_takes_the_bus_events_once_committed(
        self, container: ServiceContainer, streams: SyncStreamService
    ) -> None:
        stream = streams.open()
        with scoped_session(container):
            container.engine_bus().emit(MOVED)
            container.engine_bus().emit(ManifestChanged())
            container.engine_bus().emit(TIMELINE_MOVED)
            with pytest.raises(Empty):
                stream.next_event(WAIT)

        assert [stream.next_event(WAIT) for _ in range(3)] == [
            MOVED,
            ManifestChanged(),
            TIMELINE_MOVED,
        ]
        with pytest.raises(Empty):
            stream.next_event(WAIT)
        streams.close(stream)

    def test_a_stream_takes_only_the_events_the_sync_carries(
        self, streams: SyncStreamService
    ) -> None:
        stream = streams.open()
        project_id = uuid.uuid4()

        for event in (
            DocumentModified(project_id, MOVED.path),
            ErrorsRaised(project_id, MOVED.path),
            ErrorsResolved(project_id, MOVED.path),
        ):
            stream(event)

        with pytest.raises(Empty):
            stream.next_event(WAIT)
        streams.close(stream)

    def test_every_open_stream_takes_every_event(
        self, container: ServiceContainer, streams: SyncStreamService
    ) -> None:
        first, second = streams.open(), streams.open()

        with scoped_session(container):
            container.engine_bus().emit(MOVED)

        assert (first.next_event(WAIT), second.next_event(WAIT)) == (MOVED, MOVED)
        streams.close(first)
        streams.close(second)

    def test_close_ends_the_stream_and_takes_it_off_the_bus(
        self, container: ServiceContainer, streams: SyncStreamService
    ) -> None:
        stream = streams.open()
        stream(MOVED)

        streams.close(stream)
        streams.close(stream)
        with scoped_session(container):
            container.engine_bus().emit(TIMELINE_MOVED)

        assert stream.ended
        assert stream.next_event(WAIT) is None

    def test_a_stream_that_falls_behind_ends_without_blocking(
        self,
        container: ServiceContainer,
        coordinator: LifecycleCoordinator,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        streams = SyncStreamService(
            container.engine_bus(), coordinator, queue_max_events=2
        )
        stream = streams.open()

        with caplog.at_level(logging.WARNING):
            for event in (MOVED, TIMELINE_MOVED, ManifestChanged()):
                stream(event)

        assert stream.ended
        assert stream.next_event(WAIT) is None
        assert "fell 2 events behind" in caplog.text
        streams.close(stream)

    def test_prepare_shutdown_ends_every_stream_and_lets_no_new_one_in(
        self,
        container: ServiceContainer,
        coordinator: LifecycleCoordinator,
        streams: SyncStreamService,
    ) -> None:
        first, second = streams.open(), streams.open()
        before = _counts()

        coordinator.shutdown()
        refused = streams.open()
        with scoped_session(container):
            container.engine_bus().emit(MOVED)

        assert (first.ended, second.ended, refused.ended) == (True, True, True)
        assert refused.next_event(WAIT) is None
        assert _counts() == before
        streams.close(refused)
        assert _counts() == before
        streams.close(first)
        streams.close(second)

    def test_connects_and_open_streams_are_observed(
        self, streams: SyncStreamService
    ) -> None:
        connects, connected = _counts()

        first, second = streams.open(), streams.open()
        assert _counts() == (connects + 2, connected + 2)
        streams.close(first)
        streams.close(first)

        assert _counts() == (connects + 2, connected + 1)
        streams.close(second)
        assert _counts() == (connects + 2, connected)


class TestSyncStream:
    def test_next_event_waits_for_an_event(self) -> None:
        stream = SyncStream(queue_max_events=2)

        with pytest.raises(Empty):
            stream.next_event(WAIT)
        stream(MOVED)

        assert stream.next_event(WAIT) == MOVED

    def test_an_ended_stream_drops_what_it_held_and_takes_nothing(self) -> None:
        stream = SyncStream(queue_max_events=2)
        stream(MOVED)

        stream.end()
        stream(TIMELINE_MOVED)

        assert stream.next_event(WAIT) is None
        assert stream.next_event(WAIT) is None
