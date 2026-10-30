"""The usage halts, the week's and the five-hour's, decided from the latest
Usage Reading and never stored (design 4 §6, *The halts*; F135.1, F135.4,
F135.8; DB 266).

The week's halt holds while the latest reading's `seven_day` share is at or
over the first limit; the five-hour halt while its `five_hour` share is at or
over the five-hour limit, a limit of 0 holding none. A window the reading
leaves out holds no halt. A window whose reading is stale counts as reset one
minute past its `resets_at`, its halt lifted until a reading decides again.
The halts hold work items alone, the gate's first condition (design 2 §8.2).

The watcher decides them again at each recorded reading, which the usage
service hands it once its commit is done, and at each tick of the scheduler,
whose timer finds a stale window's minute passed: the one clock in the design.
At a halt's turn the gate is asked again and every person's connections hear
the conditions; at a reading while a halt holds they hear its figures. Each
process decides from the same readings; the halts it last told of are its
own.
"""

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.database import scoped_session
from app.models import UsageReading, WindowShare
from app.models.reference import UsageWindow
from app.services.supervisor import Supervisor
from app.services.usage_service import Usage, UsageService, latest, recorded

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)

TIMER = "usage-halts"

LIFT_AFTER = timedelta(minutes=1)
"""How long past its `resets_at` a stale reading's window counts as reset: the
margin for clock skew (F135.8)."""

WINDOWS = (UsageWindow.SEVEN_DAY, UsageWindow.FIVE_HOUR)
"""The halts' windows in their order, the week's first, as the gate and the
gold bar read them."""

_WORDS = {
    UsageWindow.SEVEN_DAY: "The week's halt",
    UsageWindow.FIVE_HOUR: "The five-hour halt",
}

_PAGE = 64
"""The readings one fetch of `_since`'s walk takes, newest first."""


@dataclass(frozen=True)
class Halt:
    """A halt that holds now."""

    window: UsageWindow
    share: float
    """The window's share in the latest reading."""
    since: datetime
    """When it began, as this server received the readings."""
    taken_at: datetime
    """When the latest reading's figures were taken: the age its line shows."""


class UsageHalts:
    """The halts' limits, and the halts that hold at them (DB 266)."""

    def __init__(self, week_limit: float, five_hour_limit: float) -> None:
        """The halts at these limits.

        Args:
            week_limit: The week's share at or over which the week's halt
                holds (WEEK_FIRST_LIMIT)
            five_hour_limit: The five-hour share at or over which the
                five-hour halt holds; 0 holds none (FIVE_HOUR_LIMIT)
        """
        self._limits = {
            UsageWindow.SEVEN_DAY: week_limit,
            UsageWindow.FIVE_HOUR: five_hour_limit,
        }

    def holding(self, db: Session) -> tuple[UsageWindow, ...]:
        """The windows whose halt holds now, the week's first."""
        return self._holding(latest(db), datetime.now(UTC))

    def halted(self, db: Session) -> UsageWindow | None:
        """The window whose halt holds a work item's start now, the week's
        while both hold; None while neither does."""
        holding = self.holding(db)
        return holding[0] if holding else None

    def halts(self, db: Session) -> list[Halt]:
        """Each halt that holds now, the week's first, with the share it holds
        at, when it began and the age of the reading."""
        # Each read up to the latest as this one reads it: a reading recorded
        # between two statements is the next decision's.
        reading_id = db.scalar(select(func.max(UsageReading.id)))
        if reading_id is None:
            return []
        usage = recorded(db, reading_id)
        return [
            Halt(
                window,
                usage.windows[window].share,
                self._since(db, window, reading_id),
                usage.taken_at,
            )
            for window in self._holding(usage, datetime.now(UTC))
        ]

    def _holding(self, usage: Usage | None, now: datetime) -> tuple[UsageWindow, ...]:
        if usage is None:
            return ()
        held = []
        for window in WINDOWS:
            figure = usage.windows.get(window)
            limit = self._limits[window]
            if figure is None or limit == 0 or figure.share < limit:
                continue
            if usage.stale and now >= figure.resets_at + LIFT_AFTER:
                continue
            held.append(window)
        return tuple(held)

    def _since(self, db: Session, window: UsageWindow, through: int) -> datetime:
        """When the halt of `window`, which the Usage Reading `through` holds,
        began: the receipt of the earliest of the readings that held it over
        their time as the latest, unbroken up to `through` — each at or over
        the limit, and a stale one not past its minute when the next was
        received."""
        limit = self._limits[window]
        result = db.execute(
            select(
                UsageReading.received_at,
                UsageReading.stale,
                WindowShare.share,
                WindowShare.resets_at,
            )
            .outerjoin(
                WindowShare,
                and_(
                    WindowShare.reading_id == UsageReading.id,
                    WindowShare.window_code == window,
                ),
            )
            .where(UsageReading.id <= through)
            .order_by(UsageReading.id.desc())
            .execution_options(yield_per=_PAGE)
        )
        since: datetime | None = None
        try:
            for received_at, stale, share, resets_at in result:
                if share is None or share < limit:
                    break
                if since is not None and stale and since >= resets_at + LIFT_AFTER:
                    break
                since = received_at
        finally:
            result.close()
        # The reading `through` holds the halt.
        assert since is not None
        return since


class UsageWatcher:
    """The halts' turns, told as they turn (design 2 §8.2, *The usage
    watcher*)."""

    def __init__(
        self,
        container: "ServiceContainer",
        supervisor: Supervisor,
        usage_service: UsageService,
        usage_halts: UsageHalts,
    ) -> None:
        """Hear every reading the usage service records, and register the
        stale fallback's timer.

        Args:
            container: Gives each decision its database session, and the gate
                and the conditions a turn moves
            supervisor: Runs the timer on the scheduler's tick
            usage_service: Tells of each reading it records
            usage_halts: Decides the halts
        """
        self._container = container
        self._halts = usage_halts
        self._lock = threading.Lock()
        self._told: tuple[UsageWindow, ...] = ()
        usage_service.subscribe(self.reevaluate)
        supervisor.register_timer(TIMER, self.run_timer, needs_controller=False)

    def reevaluate(self) -> None:
        """At a reading recorded: decide the halts from it, telling of a turn,
        and of the figures a halt that holds shows."""
        with scoped_session(self._container) as db:
            self._decide(db, recorded=True)

    def run_timer(self, db: Session) -> None:
        """The stale fallback, on the scheduler's tick (F135.8): a stale
        window past its minute lifts its halt."""
        self._decide(db, recorded=False)

    def _decide(self, db: Session, *, recorded: bool) -> None:
        # The read and the swap under one lock: of two decisions at once, the
        # later read is the one told.
        with self._lock:
            holding = self._halts.holding(db)
            told, self._told = self._told, holding
        for window in WINDOWS:
            if (window in holding) == (window in told):
                continue
            if window in holding:
                logger.warning("%s holds: work items' starts are held", _WORDS[window])
            else:
                logger.info("%s lifted: held work items go on", _WORDS[window])
        effects = []
        if holding != told:
            effects.append(self._container.session_start_service().release_held)
        if holding != told or (recorded and holding):
            effects.append(self._container.condition_service().tell)
        for effect in effects:
            # An effect that fails keeps the turn from no other.
            try:
                effect()
            except Exception:
                logger.exception("Usage halt effect %r failed", effect)
