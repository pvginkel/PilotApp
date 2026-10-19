"""The store sidecar's change streams (design 1 §5.4): each open stream a
subscriber of the engine's bus, holding the events the sync carries until
the stream's request thread writes them.

The bus delivers in the committing thread, so a stream takes an event
without blocking: one that falls `queue_max_events` behind ends instead, as
a reconnect reconciles (design 1 §5.4). On `PREPARE_SHUTDOWN` every stream
ends, and no new one is let in.
"""

import logging
import threading
from queue import Full, Queue

from prometheus_client import Counter, Gauge

from app.engine.bus import EngineBus, EngineEvent, ManifestChanged, TreeHashMoved
from app.utils.lifecycle_coordinator import LifecycleCoordinatorProtocol, LifecycleEvent

STREAM_CONNECTS_TOTAL = Counter(
    "pilot_sync_stream_connects_total",
    "Change streams the store's sidecar opened",
)
STREAM_CONNECTED = Gauge(
    "pilot_sync_stream_connected",
    "Change streams open to the store's sidecar",
)

DEFAULT_QUEUE_MAX_EVENTS = 1000
"""The events a stream holds unwritten before it counts as not keeping up."""

logger = logging.getLogger(__name__)

SyncEvent = TreeHashMoved | ManifestChanged
"""An event the change stream carries: `change` and `manifest`."""


class SyncStream:
    """One change stream: a subscriber of the engine's bus that keeps the
    events the sync carries for the stream to write. Made by
    `SyncStreamService.open()`."""

    def __init__(self, queue_max_events: int) -> None:
        self.queue_max_events = queue_max_events
        # None wakes a reader blocked on an empty queue when the stream ends.
        self._events: Queue[SyncEvent | None] = Queue(maxsize=queue_max_events)
        self._ended = threading.Event()

    @property
    def ended(self) -> bool:
        """Whether the stream has ended: it writes nothing more."""
        return self._ended.is_set()

    def __call__(self, event: EngineEvent) -> None:
        """Take `event` from the bus, never blocking; one the sync does not
        carry is dropped. A stream whose queue is full ends."""
        if not isinstance(event, TreeHashMoved | ManifestChanged) or self.ended:
            return
        try:
            self._events.put_nowait(event)
        except Full:
            logger.warning(
                "Sync stream ended: it fell %d events behind", self.queue_max_events
            )
            self.end()

    def end(self) -> None:
        """End the stream: `next_event()` answers None from now on."""
        self._ended.set()
        try:
            self._events.put_nowait(None)
        except Full:
            # The reader is not blocked: it takes an event, then sees the end.
            pass

    def next_event(self, timeout: float) -> SyncEvent | None:
        """The next event to write, waiting up to `timeout` seconds for one;
        None once the stream has ended, the events still queued dropped.

        Raises:
            queue.Empty: Nothing arrived within `timeout`
        """
        if self.ended:
            return None
        event = self._events.get(timeout=timeout)
        if event is None or self.ended:
            return None
        return event


class SyncStreamService:
    """The change streams open to the store's sidecar, in this process."""

    def __init__(
        self,
        engine_bus: EngineBus,
        lifecycle_coordinator: LifecycleCoordinatorProtocol,
        queue_max_events: int = DEFAULT_QUEUE_MAX_EVENTS,
    ) -> None:
        self.engine_bus = engine_bus
        self.queue_max_events = queue_max_events
        self._streams: set[SyncStream] = set()
        self._shutting_down = False
        self._lock = threading.Lock()
        lifecycle_coordinator.register_lifecycle_notification(self._on_lifecycle_event)

    def open(self) -> SyncStream:
        """A new stream, taking the bus's events from now on; after
        `PREPARE_SHUTDOWN` it comes back ended, and takes none."""
        stream = SyncStream(self.queue_max_events)
        with self._lock:
            if self._shutting_down:
                stream.end()
                logger.info("Sync stream refused: shutting down")
                return stream
            self._streams.add(stream)
            self.engine_bus.subscribe(stream)
        STREAM_CONNECTS_TOTAL.inc()
        STREAM_CONNECTED.inc()
        logger.info("Sync stream opened")
        return stream

    def close(self, stream: SyncStream) -> None:
        """End `stream` and take it off the bus. Idempotent."""
        with self._lock:
            opened = stream in self._streams
            if opened:
                self._streams.remove(stream)
                self.engine_bus.unsubscribe(stream)
        stream.end()
        if opened:
            STREAM_CONNECTED.dec()
            logger.info("Sync stream closed")

    def _on_lifecycle_event(self, event: LifecycleEvent) -> None:
        if event != LifecycleEvent.PREPARE_SHUTDOWN:
            return
        with self._lock:
            self._shutting_down = True
            streams = list(self._streams)
        for stream in streams:
            stream.end()
        logger.info("Ended %d sync streams for shutdown", len(streams))
