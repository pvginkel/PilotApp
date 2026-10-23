"""The controller unreachable: the gate's outage (design 2 §13.4, D11; F141.5,
F125; review O2).

The process's own state, never a row: a fresh process starts with it off. It
turns on when a controller call gets no answer — a connection error, a timeout,
or a 5xx without the controller's own problem+json, an ingress's — and holds
while the fleet stream is down. It turns off at the fleet stream's reconnect,
and at the probe's first success while the fleet stream is not down.

A listener runs in the thread that turned it, after every turn, on or off,
and reads the state as it then is: of two turns at once, the listener that
runs last reads the one that stands.
"""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

type OutageListener = Callable[[], None]


class ControllerOutage:
    """Whether the controller answers, as this process last met it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._since: datetime | None = None
        self._fleet_down = False
        self._listeners: list[OutageListener] = []

    @property
    def holds(self) -> bool:
        """Whether the controller is unreachable now."""
        with self._lock:
            return self._since is not None

    @property
    def since(self) -> datetime | None:
        """When it turned on; None while it does not hold."""
        with self._lock:
            return self._since

    def subscribe(self, listener: OutageListener) -> None:
        """Call `listener` after every turn of the outage, on or off."""
        with self._lock:
            self._listeners.append(listener)

    def call_unanswered(self) -> None:
        """A controller call got no answer: the outage is on."""
        self._turn(on=True)

    def fleet_stream_down(self) -> None:
        """The fleet stream failed to open, or dropped: the outage is on until
        it reconnects."""
        with self._lock:
            self._fleet_down = True
        self._turn(on=True)

    def fleet_stream_up(self) -> None:
        """The fleet stream reconnected: the outage is off."""
        with self._lock:
            self._fleet_down = False
        self._turn(on=False)

    def probe_answered(self) -> None:
        """The probe's call was answered: the outage is off, unless the fleet
        stream is still down."""
        self._turn(on=False)

    def _turn(self, *, on: bool) -> None:
        with self._lock:
            if not on and self._fleet_down:
                return
            if (self._since is not None) == on:
                return
            self._since = datetime.now(UTC) if on else None
            listeners = tuple(self._listeners)
        if on:
            logger.warning("The controller is unreachable: starts are held")
        else:
            logger.info("The controller answers again: held starts go on")
        for listener in listeners:
            # A listener that fails keeps the turn from no other.
            try:
                listener()
            except Exception:
                logger.exception("Outage listener %r failed", listener)
