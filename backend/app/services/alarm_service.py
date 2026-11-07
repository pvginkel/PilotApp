"""The alarms (F142; DB 238; DB decisions 70 and 74): a push to every browser
of a person's, alerting, when a condition that alarms has begun since they
were last shown the conditions (`User.alarm_seen_at`), while they are offline
and their switch is on.

Two conditions alarm: the controller unreachable, once it has held
`outage_after_seconds` from its `since`, so that a shorter blip buzzes nobody
(F142.2), and the week's usage halt, at once. Which hold is the conditions
service's, by their codes; the five-hour halt and the store's update alarm
nobody. The text is the titles of those due, the latest begun first, the
first alone or followed by ", +<n>" counting the others, under the one `tag`
`alarms`, which the app closes wherever a page of Pilot opens. The outage is
each process's own and off at a start.

A person's `alarm_seen_at` only moves forward. An alarm push moves it to when
the latest begun of the conditions it named began, whether a browser took the
push or not, so none of them is pushed again (DB 314); a condition begun after
that, while the push was in flight too, alerts in a push of its own. Their
going offline moves it to that moment, every condition holding having shown on
the gold bar while they were online, so an outage begun before it does not
alarm when it comes due after. A condition's end pushes nothing, and nothing
is ever dismissed by push. The switch writes nothing else: it is turned on a
page of Pilot, whose going offline counts what holds then as shown, so on
alarms on the next condition that comes to hold (F142.1).

The reconcile is the one loop of the job `alarm`: each person with the switch
on and a browser subscribed, in their turn, pushed when a condition due began
after their `alarm_seen_at` and no page of theirs counts (`AppPageService`).
The conditions service asks for it at each turn of a condition, STARTUP once,
and the timer `alarm-due` when the conditions due differ from those the last
reconcile read, as they do once the outage has held its time. A person's
going offline is written by a loop of the job `alarm-seen`, off the thread
that committed it.

A person's pushes take turns under an advisory lock, so that two processes
during a roll alert them once: the read, the push and the write in the turn's
one transaction (`advisory_turn`), so that it never waits on the pool for
another connection, the read let go before the push (`let_go`), so that
across it no row or table is locked.
"""

import itertools
import threading
import uuid
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING

from sqlalchemy import exists, or_, select, update
from sqlalchemy.orm import Session

from app.database import scoped_session
from app.models import PushSubscription, User
from app.models.reference import UserKind
from app.schemas.conditions import ConditionCode
from app.services.advisory_turn import advisory_turn, let_go, turn_key
from app.services.app_page_service import AppPageService, PresenceEvent, WentOffline
from app.services.condition_service import ConditionService
from app.services.supervisor import LoopHandle, Supervisor
from app.services.web_push import Push, WebPushService

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

ALARM_JOB = "alarm"
ALARM_SEEN_JOB = "alarm-seen"
ALARM_DUE_TIMER = "alarm-due"

ALARM_LOCK = 238
"""The first key of a person's alarm turn (`advisory_turn`); the second is
drawn from the person's id."""

ALARM_TAG = "alarms"
"""The `tag` of every person's alarm push, the one the app closes wherever a
page of Pilot opens (`frontend/src/hooks/use-app-page.ts`)."""

ALARM_TITLE = "Pilot"

ALARM_TITLES: dict[ConditionCode, str] = {
    ConditionCode.OUTAGE: "The controller has been unreachable",
    ConditionCode.WEEK_HALT: "The week's usage halt",
}
"""The conditions that alarm, each by its part of the text."""

type _Due = tuple[tuple[ConditionCode, datetime], ...]
"""The conditions that alarm now, each with when it began, the latest begun
first."""


def _text(due: _Due) -> str:
    """The alarm's text for the conditions `due`, one at least."""
    first = ALARM_TITLES[due[0][0]]
    return first if len(due) == 1 else f"{first}, +{len(due) - 1}"


class AlarmService:
    """Pushes each person the conditions that alarm, begun since they were
    last shown them, while they are offline."""

    def __init__(
        self,
        container: "ServiceContainer",
        supervisor: Supervisor,
        condition_service: ConditionService,
        app_page_service: AppPageService,
        web_push_service: WebPushService,
        base_url: str,
        outage_after_seconds: float,
    ) -> None:
        """Register the `alarm` job, whose reconcile runs at STARTUP, the
        `alarm-seen` job and the timer, and hear the conditions and the
        pages; where the deployment pushes nothing, none of them.

        Args:
            container: Gives each transaction its database session
            supervisor: Runs the reconciles and the goings offline
            condition_service: Says which conditions hold, and tells of each
                turn
            app_page_service: Says whether a person is online, and tells of
                their going offline
            web_push_service: Pushes to a person's browsers; with no key,
                nothing alarms
            base_url: The app's public address, the push's `url`
            outage_after_seconds: How long the outage holds before it is due
        """
        self._container = container
        self._supervisor = supervisor
        self._conditions = condition_service
        self._pages = app_page_service
        self._web_push = web_push_service
        self._url = f"{base_url}/"
        self._outage_after = timedelta(seconds=outage_after_seconds)
        self._offline = itertools.count(1)
        self._lock = threading.Lock()
        self._reconciled: _Due = ()
        if web_push_service.public_key is None:
            return
        supervisor.register_job(
            ALARM_JOB, needs_controller=False, reconcile=self._reconcile_at_startup
        )
        supervisor.register_job(ALARM_SEEN_JOB, needs_controller=False)
        supervisor.register_timer(ALARM_DUE_TIMER, self.tick, needs_controller=False)
        condition_service.subscribe(self._start)
        app_page_service.subscribe(self._heard)

    def holding(self) -> dict[ConditionCode, datetime]:
        """The conditions that hold now, each with when it began to hold."""
        return {
            condition.code: condition.since
            for condition in self._conditions.conditions().conditions
        }

    def reconcile(self, handle: LoopHandle) -> None:
        """The loop `alarm`'s run: the alarms reconciled with the conditions
        that hold now (`reconcile_holding`)."""
        self.reconcile_holding(self.holding(), handle)

    def reconcile_holding(
        self, holding: Mapping[ConditionCode, datetime], handle: LoopHandle
    ) -> None:
        """With `holding` the conditions that hold, each since when: each
        person with the switch on and a browser subscribed, in their turn,
        pushed the conditions due when one began after their `alarm_seen_at`
        and they are offline. Returns once each is, or when the loop is told
        to stop."""
        due = self._due(holding)
        with self._lock:
            self._reconciled = due
        if not due:
            return
        with scoped_session(self._container) as db:
            people = _alarmed(db)
        for person_id in people:
            if handle.stopping:
                return
            self._alarm(person_id, due)

    def tick(self, db: Session) -> None:
        """The timer `alarm-due`'s run: the reconcile asked for when the
        conditions due now differ from those the last reconcile read; one
        running already is left to finish."""
        due = self._due(self.holding())
        with self._lock:
            turned = due != self._reconciled
        if turned:
            self._start(again=False)

    def _reconcile_at_startup(self, db: Session) -> None:
        self._start()

    def _start(self, *, again: bool = True) -> None:
        # Again: a turn after the run's read is reconciled by a run after it.
        self._supervisor.start_loop(ALARM_JOB, self.reconcile, again=again)

    def _heard(self, event: PresenceEvent) -> None:
        if not isinstance(event, WentOffline):
            return
        # The moment the commit that took them offline is heard, not the
        # loop's later one: a condition begun between the two alarms them.
        at = datetime.now(UTC)
        self._supervisor.start_loop(
            ALARM_SEEN_JOB,
            partial(self._went_offline, event.user_id, at),
            key=next(self._offline),
        )

    def _went_offline(
        self, person_id: uuid.UUID, at: datetime, handle: LoopHandle
    ) -> None:
        """A loop `alarm-seen:<n>`'s run: the person, gone offline `at`, shown
        every condition that held then."""
        with scoped_session(self._container) as db:
            _seen(db, person_id, at)

    def _due(self, holding: Mapping[ConditionCode, datetime]) -> _Due:
        """The conditions of `holding` that alarm now, the latest begun
        first."""
        now = datetime.now(UTC)
        alarming = [
            (condition, holding[condition])
            for condition in ALARM_TITLES
            if condition in holding
            and (
                condition is not ConditionCode.OUTAGE
                or now - holding[condition] >= self._outage_after
            )
        ]
        alarming.sort(key=lambda pair: pair[1], reverse=True)
        return tuple(alarming)

    def _alarm(self, person_id: uuid.UUID, due: _Due) -> None:
        latest = due[0][1]
        with self._turn(person_id) as db:
            with let_go(db):
                person = db.get_one(User, person_id)
                seen = person.alarm_seen_at
                if (
                    not person.alarms
                    or (seen is not None and latest <= seen)
                    or self._pages.online(db, person_id)
                ):
                    return
            self._web_push.push(
                person_id,
                Push(
                    title=ALARM_TITLE,
                    body=_text(due),
                    tag=ALARM_TAG,
                    url=self._url,
                    renotify=True,
                ),
                db,
            )
            _seen(db, person_id, latest)

    def _turn(self, person_id: uuid.UUID) -> AbstractContextManager[Session]:
        """The person's turn to be alarmed, until the block ends."""
        return advisory_turn(
            self._container.session_maker(), ALARM_LOCK, turn_key(person_id.bytes)
        )


def _alarmed(db: Session) -> Sequence[uuid.UUID]:
    """Each person with the switch on and a browser subscribed, in order;
    Pilot has no alarm (DB 238)."""
    return db.scalars(
        select(User.id)
        .where(
            User.kind_code == UserKind.PERSON,
            User.alarms.is_(True),
            exists().where(PushSubscription.user_id == User.id),
        )
        .order_by(User.id)
    ).all()


def _seen(db: Session, person_id: uuid.UUID, at: datetime) -> None:
    """The person shown every condition begun by `at`: their `alarm_seen_at`
    moved to it, unless it stands there or later."""
    db.execute(
        update(User)
        .where(
            User.id == person_id,
            or_(User.alarm_seen_at.is_(None), User.alarm_seen_at < at),
        )
        .values(alarm_seen_at=at)
    )
