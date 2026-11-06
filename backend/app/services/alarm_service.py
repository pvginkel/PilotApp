"""The alarms (F142; DB decision 70; design 2 §7.2 *The alarms*, §13.4): one
notification per person, under one sequence id, standing while a condition
that alarms is due, the person holds a token and their switch is on, and
dismissed when any of the three ceases (DB 238).

Two conditions alarm: the controller unreachable, once it has held
`outage_after_seconds` from its `since`, so that a shorter blip buzzes nobody
(F142.2), and the week's usage halt, at once. Which hold is the conditions
service's, by their codes; the five-hour halt and the store's update alarm
nobody. The text is the titles of those due, the latest begun first, the
first alone or followed by ", +<n>" counting the others. The outage is each
process's own and off at a start.

The reconcile is the one loop of the job `alarm`: every person's text compared
with what their alarm notification last sent (`User.alarm_text`), and
submitted, updated or dismissed when it differs or is owed. The conditions
service asks for it at each turn of a condition (`tell()`), STARTUP once, so
that an outage alarm a stopped process left standing is dismissed; the timer
`alarm-retry` when the text due differs from the one the last reconcile read,
as the outage's does once it has held its time, and while a send is owed whose
retry is due. A token's set (`submit_all`), its clear (`dismiss_all`) and the
switch's turn (`switched`), each in its own transaction, have it act once that
commits (F142.1).

A person's sends take turns under an advisory lock, as a member's do
(`notification_reconcile_service`): the read, the bridge's call outside any
transaction, and the write, dropped when the person's token changed during
the call. A send the bridge refuses or does not answer is owed,
`alarm_owed_at` the time of the try. A token's clear is best effort: what
stood reads as dismissed at once, nothing owed, and the dismiss is tried once,
off the request, by a loop of the job `alarm-clear`.
"""

import itertools
import logging
import threading
import uuid
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING

from prometheus_client import Counter
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from app.database import scoped_session
from app.models import User
from app.schemas.conditions import ConditionCode
from app.services.advisory_turn import advisory_turn, turn_key
from app.services.condition_service import ConditionService
from app.services.notification_bridge_client import (
    BridgeOutcome,
    BridgePriority,
    NotificationBridgeClient,
    NotificationBridgeFailure,
)
from app.services.notification_reconcile_service import NOTIFICATION_RETRY_SECONDS
from app.services.notification_token_cipher import NotificationTokenCipher
from app.services.supervisor import LoopHandle, Supervisor
from app.utils.after_commit import after_commit

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)

ALARM_JOB = "alarm"
ALARM_CLEAR_JOB = "alarm-clear"
ALARM_RETRY_TIMER = "alarm-retry"

ALARM_LOCK = 238
"""The first key of a person's alarm turn (`advisory_turn`); the second is
drawn from the person's id."""

ALARM_SEQUENCE_ID = "alarms"
"""The sequence id of every person's alarm notification."""

ALARM_TITLE = "Pilot"

ALARM_TITLES: dict[ConditionCode, str] = {
    ConditionCode.OUTAGE: "The controller has been unreachable",
    ConditionCode.WEEK_HALT: "The week's usage halt",
}
"""The conditions that alarm, each by its part of the text."""

_PRIORITY: BridgePriority = "high"

ALARM_RECONCILES_TOTAL = Counter(
    "pilot_alarm_reconciles_total",
    "Compares of what a person's alarm notification should read with what it "
    "last sent, by outcome: unchanged, sent, owed (the send failed) or "
    "superseded (the person's token changed during the send)",
    ["outcome"],
)
ALARM_CLEAR_DISMISSES_TOTAL = Counter(
    "pilot_alarm_clear_dismisses_total",
    "Dismisses of a person's alarm notification tried once through a token "
    "just cleared, by outcome: sent, refused or unanswered; one not sent stays "
    "on the phone",
    ["outcome"],
)


def _text(due: Sequence[ConditionCode]) -> str | None:
    """The alarm notification's text for the conditions `due`, the latest
    begun first; none for none."""
    if not due:
        return None
    first = ALARM_TITLES[due[0]]
    return first if len(due) == 1 else f"{first}, +{len(due) - 1}"


@dataclass(frozen=True)
class _Send:
    """A person's send the compare found wanting, and what it read."""

    person_id: uuid.UUID
    handle: str
    text: str | None
    """What to submit; none to dismiss."""
    owed: bool
    sealed: str
    """The person's token as the record held it, sealed."""
    token: str

    @property
    def call(self) -> str:
        return "dismiss" if self.text is None else "submit"


class AlarmService:
    """Keeps each person's alarm notification standing while a condition that
    alarms is due."""

    def __init__(
        self,
        container: "ServiceContainer",
        supervisor: Supervisor,
        condition_service: ConditionService,
        notification_token_cipher: NotificationTokenCipher,
        bridge_configured: bool,
        base_url: str,
        outage_after_seconds: float,
        retry_seconds: float = NOTIFICATION_RETRY_SECONDS,
    ) -> None:
        """Register the `alarm` job, whose reconcile runs at STARTUP, the
        `alarm-clear` job and the retry timer, and hear the conditions
        service; with no bridge configured, none of them, and nothing is
        sent.

        Args:
            container: Gives each transaction its database session, and the
                bridge's client
            supervisor: Runs the reconciles and the clears' dismisses
            condition_service: Says which conditions hold, and tells of each
                turn
            notification_token_cipher: Opens the token a send goes through
            bridge_configured: False sends nothing
            base_url: The app's public address, the notification's `url`
            outage_after_seconds: How long the outage holds before it is due
            retry_seconds: The least time between two of the retry timer's
                tries of an owed send
        """
        self._container = container
        self._supervisor = supervisor
        self._conditions = condition_service
        self._cipher = notification_token_cipher
        self._configured = bridge_configured
        self._url = f"{base_url}/"
        self._outage_after = timedelta(seconds=outage_after_seconds)
        self._retry_after = timedelta(seconds=retry_seconds)
        self._clears = itertools.count(1)
        self._lock = threading.Lock()
        self._reconciled: str | None = None
        if not bridge_configured:
            return
        supervisor.register_job(
            ALARM_JOB, needs_controller=False, reconcile=self._reconcile_at_startup
        )
        supervisor.register_job(ALARM_CLEAR_JOB, needs_controller=False)
        supervisor.register_timer(ALARM_RETRY_TIMER, self.retry, needs_controller=False)
        condition_service.subscribe(self._start)

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
        """With `holding` the conditions that hold, each since when: for each
        person whose alarm notification should stand, stands or is owed, in
        their turn, the text due compared with what it last sent, and
        submitted or dismissed when it differs or is owed. Returns once each
        is, or when the loop is told to stop."""
        text = _text(self._due(holding))
        with self._lock:
            self._reconciled = text
        with scoped_session(self._container) as db:
            people = _looked_at(db, due=text is not None)
        for person_id in people:
            if handle.stopping:
                return
            self._reconcile_person(person_id, text)

    def dismiss_cleared(
        self, person_id: uuid.UUID, token: str, handle: LoopHandle
    ) -> None:
        """A loop `alarm-clear:<n>`'s run, once the clear of the person's
        `token` committed: their alarm notification dismissed through it, in
        their turn, tried once, unless the person holds `token` again, whose
        set submits afresh, or the loop is told to stop first."""
        if handle.stopping:
            return
        with self._turn(person_id):
            with scoped_session(self._container) as db:
                person = db.get_one(User, person_id)
                again = self._cipher.open(person) == token
                name = person.handle
            if again:
                logger.info(
                    "%s holds the token they cleared again: their alarm "
                    "notification is not dismissed",
                    name,
                )
                return
            self._dismiss_once(token, name)

    def retry(self, db: Session) -> None:
        """The retry timer's run: the reconcile asked for when the text due
        now differs from the one the last reconcile read, or while a send is
        owed whose last try is `retry_seconds` old or more; one running
        already is left to finish."""
        text = _text(self._due(self.holding()))
        with self._lock:
            turned = text != self._reconciled
        owed = db.scalar(
            select(
                exists().where(
                    User.alarm_owed_at <= datetime.now(UTC) - self._retry_after
                )
            )
        )
        if turned or owed:
            self._start(again=False)

    def submit_all(self, db: Session, person: User) -> None:
        """In the transaction that set `person`'s token, a first one or
        another in its place: their alarm notification, when it should stand,
        reads as not standing, so that once the transaction commits the
        reconcile submits it through the token (F142.1, the A3 ruling).
        Nothing goes through a token it replaced."""
        # The person's row locked first: a send's write-back holding it has
        # committed before what stands is read (`_take`).
        db.refresh(person, ["alarm_text"], with_for_update={"key_share": True})
        if person.alarms and self._due(self.holding()):
            person.alarm_text = None
        if self._configured:
            after_commit(self._start)

    def dismiss_all(self, db: Session, person: User, token: str) -> None:
        """In the transaction that cleared `person`'s token, `token` the one
        cleared: their alarm notification, when it stands or is owed, reads
        as dismissed from the commit on, with nothing owed; once the
        transaction commits it is dismissed through `token`, tried once, off
        the request (F134). What the bridge does not take is logged, counted,
        and stays on the phone."""
        # The person's row locked first, as `submit_all` locks it.
        db.refresh(
            person,
            ["alarm_text", "alarm_owed_at"],
            with_for_update={"key_share": True},
        )
        stood = person.alarm_text is not None or person.alarm_owed_at is not None
        person.alarm_text = None
        person.alarm_owed_at = None
        if self._configured and stood:
            after_commit(partial(self._start_clear, person.id, token))

    def switched(self) -> None:
        """In the transaction that turned a person's switch (`User.alarms`):
        once it commits, the reconcile, off dismissing their alarm
        notification, owed while the bridge does not take it, and on
        submitting it while a condition is due (F142.1)."""
        if self._configured:
            after_commit(self._start)

    def _reconcile_at_startup(self, db: Session) -> None:
        """At STARTUP: every alarm notification reconciled, the outage off
        (design 2 §7.2)."""
        self._start()

    def _start(self, *, again: bool = True) -> None:
        # Again: a turn after the run's read is reconciled by a run after it.
        self._supervisor.start_loop(ALARM_JOB, self.reconcile, again=again)

    def _start_clear(self, person_id: uuid.UUID, token: str) -> None:
        self._supervisor.start_loop(
            ALARM_CLEAR_JOB,
            partial(self.dismiss_cleared, person_id, token),
            key=next(self._clears),
        )

    def _due(
        self, holding: Mapping[ConditionCode, datetime]
    ) -> tuple[ConditionCode, ...]:
        """The conditions of `holding` that alarm now, the latest begun
        first."""
        now = datetime.now(UTC)
        alarming = [
            (holding[condition], condition)
            for condition in ALARM_TITLES
            if condition in holding
            and (
                condition is not ConditionCode.OUTAGE
                or now - holding[condition] >= self._outage_after
            )
        ]
        alarming.sort(key=lambda pair: pair[0], reverse=True)
        return tuple(condition for _, condition in alarming)

    def _reconcile_person(self, person_id: uuid.UUID, text: str | None) -> None:
        with self._turn(person_id):
            with scoped_session(self._container) as db:
                send = self._compare(db, person_id, text)
            if send is None:
                ALARM_RECONCILES_TOTAL.labels(outcome="unchanged").inc()
                return
            failure = self._send(send)
            with scoped_session(self._container) as db:
                cleared = self._take(db, send, failure)
            if cleared:
                self._dismiss_once(send.token, send.handle)

    def _turn(self, person_id: uuid.UUID) -> AbstractContextManager[None]:
        """The person's turn to send their alarm, until the block ends."""
        return advisory_turn(
            self._container.session_maker(), ALARM_LOCK, turn_key(person_id.bytes)
        )

    def _compare(
        self, db: Session, person_id: uuid.UUID, text: str | None
    ) -> _Send | None:
        """The person's send, unless what they should see is what was last
        sent and nothing is owed."""
        person = db.get_one(User, person_id)
        should = (
            text if person.alarms and person.notification_token is not None else None
        )
        owed = person.alarm_owed_at is not None
        if not owed and should == person.alarm_text:
            return None
        token = self._cipher.open(person)
        # Nothing of a person's with no token stands or is owed: the clear
        # that dropped it read it all dismissed (`dismiss_all`).
        assert token is not None and person.notification_token is not None
        return _Send(
            person_id=person_id,
            handle=person.handle,
            text=should,
            owed=owed,
            sealed=person.notification_token,
            token=token,
        )

    def _send(self, send: _Send) -> NotificationBridgeFailure | None:
        """The submit or dismiss sent, or the bridge's failure to take it."""
        try:
            if send.text is None:
                self._client().dismiss(send.token, ALARM_SEQUENCE_ID)
            else:
                self._client().submit(
                    send.token,
                    ALARM_SEQUENCE_ID,
                    message=send.text,
                    title=ALARM_TITLE,
                    priority=_PRIORITY,
                    url=self._url,
                )
        except NotificationBridgeFailure as failure:
            return failure
        return None

    def _take(
        self, db: Session, send: _Send, failure: NotificationBridgeFailure | None
    ) -> bool:
        """What the send came to, written on the person's row unless their
        token changed meanwhile. Whether their token was cleared during a
        submit that may have reached the phone, which its own dismiss then
        follows."""
        # Locked as the token's set and clear lock it: a clear committed
        # first is read here, and one after waits for this write, which its
        # read of what stands then sees.
        person = db.scalars(
            select(User)
            .where(User.id == send.person_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        ).one()
        if person.notification_token != send.sealed:
            ALARM_RECONCILES_TOTAL.labels(outcome="superseded").inc()
            logger.info(
                "The token of %s changed during the %s of their alarm "
                "notification; what came of it is not recorded",
                send.handle,
                send.call,
            )
            return (
                person.notification_token is None
                and send.text is not None
                and (failure is None or failure.outcome is BridgeOutcome.UNANSWERED)
            )
        now = datetime.now(UTC)
        if failure is not None:
            person.alarm_owed_at = now
            ALARM_RECONCILES_TOTAL.labels(outcome="owed").inc()
            logger.log(
                logging.DEBUG if send.owed else logging.WARNING,
                "The %s of the alarm notification to %s is owed: %s",
                send.call,
                send.handle,
                failure,
            )
            return False
        person.alarm_text = send.text
        person.alarm_sent_at = now
        person.alarm_owed_at = None
        ALARM_RECONCILES_TOTAL.labels(outcome="sent").inc()
        if send.owed:
            logger.info(
                "The owed %s of the alarm notification to %s went out",
                send.call,
                send.handle,
            )
        return False

    def _dismiss_once(self, token: str, name: str) -> None:
        """A cleared token's dismiss of the alarm notification, tried once:
        what the bridge does not take stays on the phone."""
        try:
            self._client().dismiss(token, ALARM_SEQUENCE_ID)
        except NotificationBridgeFailure as failure:
            ALARM_CLEAR_DISMISSES_TOTAL.labels(outcome=failure.outcome).inc()
            logger.warning(
                "The dismiss of the alarm notification to %s after their "
                "token's clear failed, and it stays on the phone: %s",
                name,
                failure,
            )
            return
        ALARM_CLEAR_DISMISSES_TOTAL.labels(outcome=BridgeOutcome.SENT).inc()

    def _client(self) -> NotificationBridgeClient:
        return self._container.notification_bridge_client()


def _looked_at(db: Session, *, due: bool) -> Sequence[uuid.UUID]:
    """Each person whose alarm notification should stand — while a condition
    is `due`, one holding a token with the switch on —, stands or is owed, in
    order. Pilot holds no token (`ck_users_agent`)."""
    shown = or_(User.alarm_text.is_not(None), User.alarm_owed_at.is_not(None))
    holders = and_(User.notification_token.is_not(None), User.alarms.is_(True))
    return db.scalars(
        select(User.id).where(or_(shown, holders) if due else shown).order_by(User.id)
    ).all()
