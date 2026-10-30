"""The subscription's usage, as KubeCoder's controller reads it (design 4 §6;
F135.8; DB Usage Reading and Window Share, decision 67).

The fleet consumer hands it every `usage` frame of the fleet stream, each
connect's seed included, so the controller's route is never read. A reading
that carries figures is recorded when its `taken_at` is not older than the
latest recorded and its figures or `stale` differ from that one's, as a Usage
Reading with a Window Share per window (DB 274): after a restart, or a
reconnect, the seed is compared with the last recorded. A reading with no
figures, `no-reading-yet` from a controller just started, leaves the latest
as it is. Why a reading is stale is the log's alone. Each reading recorded is
told to the listeners, the halts' watcher, once its commit is done.

Two processes overlapping in a roll each receive every reading: the table's
lock, held from the comparison to the commit, lets one of them record it.
"""

import logging
import math
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from prometheus_client import Gauge
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import scoped_session
from app.models import UsageReading, WindowShare
from app.models.reference import UsageWindow
from app.services.controller_client import ControllerUsageReading

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)

type ReadingListener = Callable[[], None]

READING_AGE = Gauge(
    "pilot_usage_reading_age_seconds",
    "How old the usage figures this process holds are: 0 while fresh, current "
    "to within the controller's poll; the seconds since their takenAt while "
    "stale; NaN before the first reading with figures",
)


@dataclass(frozen=True)
class WindowFigure:
    """A window's used share of its quota, and when the window resets."""

    share: float
    """A fraction, unclamped: it may pass 1."""
    resets_at: datetime


@dataclass(frozen=True)
class Usage:
    """A reading's figures: when the poll got them, whether it has failed
    since, and the figure of each window the reading carries."""

    taken_at: datetime
    stale: bool
    """The poll's latest call got no answer: the figures are its last answer's."""
    windows: Mapping[UsageWindow, WindowFigure]


def latest(db: Session) -> Usage | None:
    """The latest Usage Reading recorded, the one the halts read (DB 274);
    None before the first."""
    reading = db.scalars(
        select(UsageReading).order_by(UsageReading.id.desc()).limit(1)
    ).first()
    return None if reading is None else _usage(db, reading)


def recorded(db: Session, reading_id: int) -> Usage:
    """The figures of the Usage Reading `reading_id`."""
    return _usage(db, db.get_one(UsageReading, reading_id))


def _usage(db: Session, reading: UsageReading) -> Usage:
    shares = db.scalars(
        select(WindowShare).where(WindowShare.reading_id == reading.id)
    ).all()
    return Usage(
        reading.taken_at,
        reading.stale,
        {
            share.window_code: WindowFigure(share.share, share.resets_at)
            for share in shares
        },
    )


class UsageService:
    """The usage readings received, recorded, and the latest held."""

    def __init__(self, container: "ServiceContainer") -> None:
        """Hold no reading yet, with no listener, and read the gauge from
        this instance.

        Args:
            container: Gives each reading's record its database session
        """
        self._container = container
        self._lock = threading.Lock()
        self._held: Usage | None = None
        self._listeners: list[ReadingListener] = []
        READING_AGE.set_function(self._age)

    def subscribe(self, listener: ReadingListener) -> None:
        """Call `listener` once each reading this service records has
        committed."""
        self._listeners.append(listener)

    def receive(self, reading: ControllerUsageReading) -> None:
        """Record the reading the controller served when it is one to record,
        and hold its figures unless they are older than the latest recorded;
        a reading recorded tells the listeners once its commit is done."""
        if reading.taken_at is None or not reading.windows:
            logger.info(
                "Usage reading without figures (%s): the latest recorded stands",
                reading.stale_reason,
            )
            return
        usage = Usage(
            reading.taken_at,
            reading.stale,
            {
                UsageWindow(window.window): WindowFigure(window.share, window.resets_at)
                for window in reading.windows
            },
        )
        recorded: int | None = None
        with scoped_session(self._container) as db:
            db.execute(text("LOCK TABLE usage_readings IN EXCLUSIVE MODE"))
            # Stamped under the lock, which a Quota Overrule's make takes too:
            # a reading's receipt and an overrule's making order as their
            # commits, as the overrule's end reads them (DB 268).
            received_at = datetime.now(UTC)
            last = latest(db)
            if last is not None and usage.taken_at < last.taken_at:
                logger.info(
                    "Usage reading taken at %s is older than the latest recorded, "
                    "taken at %s: ignored",
                    usage.taken_at.isoformat(),
                    last.taken_at.isoformat(),
                )
                return
            if last is not None and (usage.stale, usage.windows) == (
                last.stale,
                last.windows,
            ):
                logger.info(
                    "Usage reading taken at %s: unchanged since the latest recorded",
                    usage.taken_at.isoformat(),
                )
            else:
                recorded = _record(db, usage, received_at)
                logger.info(
                    "Usage reading %d recorded, taken at %s: %s%s",
                    recorded,
                    usage.taken_at.isoformat(),
                    _figures(usage),
                    f"; stale ({reading.stale_reason})" if usage.stale else "",
                )
        with self._lock:
            self._held = usage
        if recorded is not None:
            for listener in self._listeners:
                listener()

    def _age(self) -> float:
        with self._lock:
            held = self._held
        if held is None:
            return math.nan
        if not held.stale:
            return 0.0
        return (datetime.now(UTC) - held.taken_at).total_seconds()


def _record(db: Session, usage: Usage, received_at: datetime) -> int:
    reading = UsageReading(
        taken_at=usage.taken_at, received_at=received_at, stale=usage.stale
    )
    db.add(reading)
    db.flush()
    db.add_all(
        WindowShare(
            reading_id=reading.id,
            window_code=window,
            share=figure.share,
            resets_at=figure.resets_at,
        )
        for window, figure in usage.windows.items()
    )
    return reading.id


def _figures(usage: Usage) -> str:
    return ", ".join(
        f"{window} {figure.share} to {figure.resets_at.isoformat()}"
        for window, figure in usage.windows.items()
    )
