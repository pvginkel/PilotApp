"""The engine's bus: typed, in-process, and delivered only once the
transaction that caused an event has committed (design 1 §5.4)."""

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from app.utils.after_commit import after_commit

logger = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class ProjectChanged(EngineEvent):
    """What the project's timeline, head or tab shows moved: an item born,
    marked, undone or closed, an item's text published, an item's save held
    or no longer held, its plan or its standing changed."""

    project_id: uuid.UUID


@dataclass(frozen=True)
class WorkMoved(EngineEvent):
    """What a work item's line shows of its Session moved: its state, its one
    current line, its start or its error (F80.2's work status). It moves
    nothing else of the project's screens."""

    project_id: uuid.UUID
    work_id: uuid.UUID


@dataclass(frozen=True)
class ManifestChanged(EngineEvent):
    """The set of syncing projects changed (design 1 §5.4, decision 24): the
    manifest lists other folders."""


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
            # A subscriber that fails keeps the event from no other.
            try:
                subscriber(event)
            except Exception:
                logger.exception("subscriber %r failed on %r", subscriber, event)


@dataclass(frozen=True)
class _Delivery:
    # `after_commit()` runs a callback equal to one it holds once.
    bus: EngineBus
    event: EngineEvent

    def __call__(self) -> None:
        self.bus._deliver(self.event)
