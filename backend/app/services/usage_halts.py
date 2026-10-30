"""The usage halts, the week's and the five-hour's, decided from the latest
Usage Reading and never stored (design 4 §6, *The halts*; F135.1, F135.4,
F135.8; DB 266).

The week's halt holds while the latest reading's `seven_day` share is at or
over the first limit and no Quota Overrule holds; the five-hour halt while its
`five_hour` share is at or over the five-hour limit, a limit of 0 holding
none. A window the reading leaves out holds no halt. A window whose reading is
stale counts as reset one minute past its `resets_at`, its halt lifted until a
reading decides again. The halts hold work items alone, the gate's first
condition (design 2 §8.2).

The week's halt offers one overrule (F135.2; DB 179): under the second limit
the allowance, its target the share plus the allowance, at most the second
limit; at or over it run-out, its target the wall. An overrule ends at the
first reading at or over its target, or lower than the reading before it, or
when a stale reading's week is a minute past its `resets_at` (DB 268).

Each window's halt setting says what its halt does to the work items
(F135.6): every setting holds their starts; the cooperative stop writes the
halt file where one runs (`HaltFileService`); the hard stop stops every one
running, as Stop stops one, by Pilot, its nudge owed (DB 269).

The watcher decides them again at each recorded reading, which the usage
service hands it once its commit is done, at each overrule made, and at each
tick of the scheduler, whose timer finds a stale window's minute passed: the
one clock in the design. Each decision first ends the overrule a reading has
spent. At a halt's turn the gate is asked again, the halt files are swept,
the nudges owed are sent where nothing holds them any more, and every
person's connections hear the conditions; at a reading while a halt
holds, and at an overrule's end, they hear them too. At a reading while a
turn that died at the quota wall owes its nudge, the nudges are sent too: the
reading may decide the wall or bring the quota back (`quota_wall`). At every decision while
a hard-stop halt holds and a work item runs, the hard stop is asked for: one
the gate let through before the halt is stopped at the next. Each process
decides from the same readings; the halts it last told of are its own.
"""

import logging
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session

from app.app_config import HaltSetting
from app.models import QuotaOverrule, UsageReading, WindowShare
from app.models import Session as AgentSession
from app.models.reference import OverruleKind, SessionState, UsageWindow
from app.services.start_gate import WORK_KIND
from app.services.supervisor import Supervisor
from app.services.usage_service import Usage, UsageService, latest, recorded

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)

TIMER = "usage-halts"

WALL = 1.0
"""A run-out's target: the week's whole quota."""

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
class Offer:
    """The overrule the week's halt offers."""

    kind: OverruleKind
    target: float | None
    """The allowance's: the week's share at which it would end; None for
    run-out, whose target is the wall."""


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
    offer: Offer | None
    """The week's: the overrule it offers; None for the five-hour halt."""


def overrule(db: Session) -> QuotaOverrule | None:
    """The Quota Overrule that holds, if one does (DB 267)."""
    return db.scalars(
        select(QuotaOverrule).where(QuotaOverrule.ended_at.is_(None))
    ).one_or_none()


class UsageHalts:
    """The halts' limits and settings, the halts that hold at them, and the
    week's overrule (DB 266, 179, 268, 269)."""

    def __init__(
        self,
        *,
        week_limit: float,
        week_allowance: float,
        week_second_limit: float,
        five_hour_limit: float,
        week_halt: HaltSetting,
        five_hour_halt: HaltSetting,
    ) -> None:
        """The halts at these limits.

        Args:
            week_limit: The week's share at or over which the week's halt
                holds (WEEK_FIRST_LIMIT)
            week_allowance: What the allowance adds to the week's share for
                its target (WEEK_ALLOWANCE)
            week_second_limit: The allowance's highest target, and the share
                at or over which run-out is offered in its place
                (WEEK_SECOND_LIMIT)
            five_hour_limit: The five-hour share at or over which the
                five-hour halt holds; 0 holds none (FIVE_HOUR_LIMIT)
            week_halt: What the week's halt does to the work items
                (WEEK_HALT)
            five_hour_halt: What the five-hour halt does to them
                (FIVE_HOUR_HALT)
        """
        self._limits = {
            UsageWindow.SEVEN_DAY: week_limit,
            UsageWindow.FIVE_HOUR: five_hour_limit,
        }
        self._settings = {
            UsageWindow.SEVEN_DAY: week_halt,
            UsageWindow.FIVE_HOUR: five_hour_halt,
        }
        self._allowance = week_allowance
        self._second_limit = week_second_limit

    def holding(self, db: Session) -> tuple[UsageWindow, ...]:
        """The windows whose halt holds now, the week's first."""
        return self._holding(
            latest(db), datetime.now(UTC), overruled=overrule(db) is not None
        )

    def halted(self, db: Session) -> UsageWindow | None:
        """The window whose halt holds a work item's start now, the week's
        while both hold; None while neither does."""
        holding = self.holding(db)
        return holding[0] if holding else None

    def stopping(self, db: Session) -> bool:
        """Whether a halt whose setting is the hard stop holds now: every
        running work item is to be stopped (F135.6; DB 269)."""
        return self.stops(self.holding(db))

    def stops(self, windows: Iterable[UsageWindow]) -> bool:
        """Whether the halt of one of `windows` has the hard stop for its
        setting."""
        return any(
            self._settings[window] is HaltSetting.HARD_STOP for window in windows
        )

    def halts(self, db: Session) -> list[Halt]:
        """Each halt that holds now, the week's first, with the share it holds
        at, when it began, the age of the reading and the week's offer."""
        # Each read up to the latest as this one reads it: a reading recorded
        # between two statements is the next decision's.
        reading_id = db.scalar(select(func.max(UsageReading.id)))
        if reading_id is None:
            return []
        usage = recorded(db, reading_id)
        overruled = overrule(db) is not None
        return [
            Halt(
                window,
                usage.windows[window].share,
                self._since(db, window, reading_id),
                usage.taken_at,
                self._offer(usage.windows[window].share)
                if window is UsageWindow.SEVEN_DAY
                else None,
            )
            for window in self._holding(usage, datetime.now(UTC), overruled=overruled)
        ]

    def offer(self, db: Session) -> Offer | None:
        """The overrule the week's halt offers now; None while it does not
        hold, an overrule holding among the reasons."""
        usage = latest(db)
        overruled = overrule(db) is not None
        if UsageWindow.SEVEN_DAY not in self._holding(
            usage, datetime.now(UTC), overruled=overruled
        ):
            return None
        # The week's halt holds at a reading that carries the week.
        assert usage is not None
        return self._offer(usage.windows[UsageWindow.SEVEN_DAY].share)

    def end_spent(self, db: Session) -> QuotaOverrule | None:
        """Write the end of the Quota Overrule that holds when the latest
        reading has spent it (DB 268), once, whichever process gets there
        first.

        Returns:
            The overrule this call ended; None when none holds, the latest
            reading has not spent it, or another decision ended it first
        """
        holding = overrule(db)
        if holding is None:
            return None
        now = datetime.now(UTC)
        if not self._spent(db, holding, now):
            return None
        ended = db.execute(
            update(QuotaOverrule)
            .where(QuotaOverrule.id == holding.id, QuotaOverrule.ended_at.is_(None))
            .values(ended_at=now)
            .returning(QuotaOverrule.id)
        ).first()
        return None if ended is None else holding

    def _spent(self, db: Session, holding: QuotaOverrule, now: datetime) -> bool:
        """Whether the latest reading spends `holding`: its week share at or
        over the target, its stale week a minute past its reset, or, received
        since the overrule was made, its week share lower than the reading
        before's (DB 274)."""
        reading = db.scalars(
            select(UsageReading).order_by(UsageReading.id.desc()).limit(1)
        ).one()
        figure = recorded(db, reading.id).windows.get(UsageWindow.SEVEN_DAY)
        if figure is None:
            return False
        target = WALL if holding.target is None else holding.target
        if figure.share >= target:
            return True
        if reading.stale and now >= figure.resets_at + LIFT_AFTER:
            return True
        # A reading received before the overrule was made is one it was made
        # at. `UsageService.receive` stamps `received_at` under the table lock
        # `QuotaOverruleService.make` takes too, so the two order as their
        # commits.
        if reading.received_at <= holding.made_at:
            return False
        before = db.scalar(
            select(WindowShare.share)
            .join(UsageReading, UsageReading.id == WindowShare.reading_id)
            .where(
                WindowShare.window_code == UsageWindow.SEVEN_DAY,
                UsageReading.id < reading.id,
            )
            .order_by(UsageReading.id.desc())
            .limit(1)
        )
        return before is not None and figure.share < before

    def _offer(self, share: float) -> Offer:
        if share < self._second_limit:
            # Summed in decimal: a share is a percent ÷ 100, and a binary sum
            # can land a rounding error over the reading that reaches it
            # (0.90 + 0.05 is 0.9500000000000001).
            target = float(Decimal(repr(share)) + Decimal(repr(self._allowance)))
            return Offer(OverruleKind.ALLOWANCE, min(target, self._second_limit))
        return Offer(OverruleKind.RUN_OUT, None)

    def _holding(
        self, usage: Usage | None, now: datetime, *, overruled: bool
    ) -> tuple[UsageWindow, ...]:
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
            if window is UsageWindow.SEVEN_DAY and overruled:
                continue
            held.append(window)
        return tuple(held)

    def _since(self, db: Session, window: UsageWindow, through: int) -> datetime:
        """When the halt of `window`, which the Usage Reading `through` holds,
        began: the receipt of the earliest of the readings that held it over
        their time as the latest, unbroken up to `through` — each at or over
        the limit, and a stale one not past its minute when the next was
        received — or, for the week, the end of an overrule since, at which
        it held again."""
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
        if window is UsageWindow.SEVEN_DAY:
            ended = db.scalar(select(func.max(QuotaOverrule.ended_at)))
            if ended is not None and ended > since:
                return ended
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
        of an overrule's end, and of the figures a halt that holds shows."""
        self._decide_apart(recorded=True, made=False)

    def overruled(self) -> None:
        """At an overrule made, once its commit is done: the week's halt
        lifted, the gate asked again and the conditions told, whatever this
        process last told."""
        self._decide_apart(recorded=False, made=True)

    def run_timer(self, db: Session) -> None:
        """The stale fallback, on the scheduler's tick (F135.8): a stale
        window past its minute lifts its halt and ends the overrule."""
        self._decide(db, recorded=False, made=False)

    def _decide_apart(self, *, recorded: bool, made: bool) -> None:
        # A session of its own, not `scoped_session`: an overrule's request
        # calls this among its after-commit callbacks, which a nested
        # `scoped_session` would run again.
        db: Session = self._container.session_maker()()
        try:
            self._decide(db, recorded=recorded, made=made)
        finally:
            db.close()

    def _decide(self, db: Session, *, recorded: bool, made: bool) -> None:
        # The end, its commit, the read and the swap under one lock: of two
        # decisions at once, the later read is the one told, and the gate and
        # the conditions, each on a session of its own, read the end.
        with self._lock:
            ended = self._halts.end_spent(db)
            spent = None if ended is None else (ended.id, ended.kind_code)
            db.commit()
            holding = self._halts.holding(db)
            told, self._told = self._told, holding
        if spent is not None:
            logger.info(
                "Quota overrule %d (%s) ended: the week's share reached its "
                "target or turned lower, or its stale week reset",
                *spent,
            )
        for window in WINDOWS:
            if (window in holding) == (window in told):
                continue
            if window in holding:
                logger.warning("%s holds: work items' starts are held", _WORDS[window])
            else:
                logger.info("%s lifted: held work items go on", _WORDS[window])
        turned = holding != told or made
        effects = []
        if self._halts.stops(holding) and _work_runs(db):
            effects.append(self._container.session_start_service().hard_stop)
        if turned:
            effects.append(self._container.session_start_service().release_held)
            effects.append(self._container.halt_file_service().request)
            effects.append(self._container.session_start_service().send_nudges)
        elif recorded and _walled(db):
            effects.append(self._container.session_start_service().send_nudges)
        if turned or spent is not None or (recorded and holding):
            effects.append(self._container.condition_service().tell)
        for effect in effects:
            # An effect that fails keeps the turn from no other.
            try:
                effect()
            except Exception:
                logger.exception("Usage halt effect %r failed", effect)


def _walled(db: Session) -> bool:
    """Whether a Session is `failed` with its nudge owed: its turn died at
    the quota wall."""
    return bool(
        db.scalar(
            select(
                select(AgentSession.id)
                .where(
                    AgentSession.nudge_owed_at.is_not(None),
                    AgentSession.state_code == SessionState.FAILED,
                )
                .exists()
            )
        )
    )


def _work_runs(db: Session) -> bool:
    """Whether a work item's Session is `running`."""
    return bool(
        db.scalar(
            select(
                select(AgentSession.id)
                .where(
                    AgentSession.kind_code == WORK_KIND,
                    AgentSession.state_code == SessionState.RUNNING,
                )
                .exists()
            )
        )
    )
