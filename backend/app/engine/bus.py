"""The engine's bus: typed, in-process, and delivered only once the
transaction that caused an event has committed (design 1 §5.4)."""

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from app.utils.after_commit import after_commit


@dataclass(frozen=True)
class EngineEvent:
    """What the engine tells its subscribers; each kind is a subclass."""


@dataclass(frozen=True)
class TreeHashMoved(EngineEvent):
    """The tree hash of a path moved (design 1 §5.2); `path` is from the
    tree's root: the project's folder, then the file, or `reference.json`."""

    path: str
    hash: str


@dataclass(frozen=True)
class DocumentModified(EngineEvent):
    """An agent's save of a document was ingested, published or held (design
    1 §7); the record's own writes raise none."""

    project_id: uuid.UUID
    path: str


@dataclass(frozen=True)
class ErrorsRaised(EngineEvent):
    """A save of the path was held: `parse` Save Errors stand on it, that
    save's."""

    project_id: uuid.UUID
    path: str


@dataclass(frozen=True)
class ErrorsResolved(EngineEvent):
    """The path's last `parse` Save Error is gone."""

    project_id: uuid.UUID
    path: str


Subscriber = Callable[[EngineEvent], None]


class EngineBus:
    """One per process: every subscriber receives every event, in the order
    the transaction emitted them."""

    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []
        self._lock = threading.Lock()

    def subscribe(self, subscriber: Subscriber) -> None:
        with self._lock:
            self._subscribers.append(subscriber)

    def unsubscribe(self, subscriber: Subscriber) -> None:
        with self._lock:
            self._subscribers.remove(subscriber)

    def emit(self, event: EngineEvent) -> None:
        """Deliver `event` once the current transaction has committed, and
        never if it rolls back. An event equal to one already emitted in the
        transaction is delivered once."""
        after_commit(_Delivery(self, event))

    def _deliver(self, event: EngineEvent) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers)
        for subscriber in subscribers:
            subscriber(event)


@dataclass(frozen=True)
class _Delivery:
    # `after_commit()` runs a callback equal to one it holds once.
    bus: EngineBus
    event: EngineEvent

    def __call__(self) -> None:
        self.bus._deliver(self.event)
