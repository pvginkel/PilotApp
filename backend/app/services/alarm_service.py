"""The alarms (F142; DB Alarm, decision 55; design 2 §7.2 *The alarms*,
§13.4): a standing notification per person and app-wide condition, submitted
through the bridge once the condition holds, the person holds a token and
their switch is on, and dismissed when any of the three ceases (DB 238).

Which conditions hold is the conditions service's, taken by their Condition
codes, so that each condition it comes to tell of has its alarm. A condition's
alarm is due at once, the outage's once it has held `outage_after_seconds`
from its `since`, so that a shorter blip buzzes nobody (F142.2). The outage is
each process's own and off at a start.

The reconcile is the one loop of the job `alarm`: every person's alarm for
each condition compared with whether it stands, and submitted or dismissed
when it differs or is owed. The conditions service asks for it at each turn of
a condition (`tell()`), STARTUP once, so that an outage alarm a stopped
process left standing is dismissed; the timer `alarm-retry` when the alarms
due differ from those the last reconcile read, as the outage's do once it has
held its time, and while an alarm is owed whose retry is due. A token's set
(`submit_all`), its clear (`dismiss_all`) and the switch's turn (`switched`),
each in its own transaction, have it act once that commits (F142.1).

An alarm's sends take turns under an advisory lock, as a member's do
(`notification_reconcile_service`): the read, the bridge's call outside any
transaction, and the write, dropped when the person's token changed during
the call. A send the bridge refuses or does not answer is owed, `owed_at` the
time of the try. A token's clear is best effort: what stood reads as
dismissed at once, nothing owed, and each dismiss is tried once, off the
request, by a loop of the job `alarm-clear`.
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
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.database import scoped_session
from app.models import Alarm, User
from app.models.reference import Condition, UserKind
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
"""The first key of an alarm's turn (`advisory_turn`); the second is drawn
from the person's id and the condition's code."""


@dataclass(frozen=True)
class AlarmText:
    """What a condition's alarm reads on the phone, fixed per condition."""

    title: str
    message: str
    priority: BridgePriority


ALARM_TEXTS: dict[Condition, AlarmText] = {
    Condition.OUTAGE: AlarmText(
        title="The controller has been unreachable",
        message="Nothing starts until it answers.",
        priority="high",
    ),
    Condition.WEEK_HALT: AlarmText(
        title="The week's usage halt",
        message=(
            "Work items are halted until a reading puts the week's share back "
            "under its limit, or someone overrules the halt."
        ),
        priority="high",
    ),
    Condition.FIVE_HOUR_HALT: AlarmText(
        title="The five-hour usage halt",
        message=(
            "Work items are halted until a reading puts the five-hour window's "
            "share back under its limit."
        ),
        priority="default",
    ),
}

ALARM_RECONCILES_TOTAL = Counter(
    "pilot_alarm_reconciles_total",
    "Compares of whether a person's alarm for a condition should stand with "
    "whether it stands, by outcome: unchanged, sent, owed (the send failed) or "
    "superseded (the person's token changed during the send)",
    ["outcome"],
)
ALARM_CLEAR_DISMISSES_TOTAL = Counter(
    "pilot_alarm_clear_dismisses_total",
    "Dismisses of an alarm tried once through a token just cleared, by "
    "outcome: sent, refused or unanswered; one not sent stays on the phone",
    ["outcome"],
)


@dataclass(frozen=True)
class _Send:
    """An alarm's send the compare found wanting, and what it read."""

    person_id: uuid.UUID
    handle: str
    condition: Condition
    submit: bool
    """Whether the alarm should stand; a dismiss when not."""
    owed: bool
    sealed: str
    """The person's token as the record held it, sealed."""
    token: str

    @property
    def call(self) -> str:
        return "submit" if self.submit else "dismiss"


class AlarmService:
    """Keeps each person's alarms standing while their conditions hold."""

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
            base_url: The app's public address, each alarm's `url`
            outage_after_seconds: How long the outage holds before its alarm
                is due
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
        self._reconciled: frozenset[Condition] = frozenset()
        if not bridge_configured:
            return
        supervisor.register_job(
            ALARM_JOB, needs_controller=False, reconcile=self._reconcile_at_startup
        )
        supervisor.register_job(ALARM_CLEAR_JOB, needs_controller=False)
        supervisor.register_timer(ALARM_RETRY_TIMER, self.retry, needs_controller=False)
        condition_service.subscribe(self._start)

    def holding(self) -> dict[Condition, datetime]:
        """The conditions that hold now, by their Condition codes, each with
        when it began to hold."""
        return {
            Condition(condition.code.value): condition.since
            for condition in self._conditions.conditions().conditions
        }

    def reconcile(self, handle: LoopHandle) -> None:
        """The loop `alarm`'s run: the alarms reconciled with the conditions
        that hold now (`reconcile_holding`)."""
        self.reconcile_holding(self.holding(), handle)

    def reconcile_holding(
        self, holding: Mapping[Condition, datetime], handle: LoopHandle
    ) -> None:
        """With `holding` the conditions that hold, each since when: for each
        person and condition whose alarm should stand, stands or is owed, in
        its turn, whether it should stand compared with whether it stands,
        and submitted or dismissed when it differs or is owed. Returns once
        each is, or when the loop is told to stop."""
        due = self._due(holding)
        with self._lock:
            self._reconciled = due
        with scoped_session(self._container) as db:
            alarms = _looked_at(db, due)
        for person_id, condition in alarms:
            if handle.stopping:
                return
            self._reconcile_alarm(person_id, condition, due)

    def dismiss_cleared(
        self,
        person_id: uuid.UUID,
        token: str,
        conditions: Sequence[Condition],
        handle: LoopHandle,
    ) -> None:
        """A loop `alarm-clear:<n>`'s run, once the clear of the person's
        `token` committed: each condition's alarm dismissed through it, in its
        turn, tried once, unless the person holds `token` again, whose set
        submits afresh. Returns once each is, or when the loop is told to
        stop."""
        for condition in conditions:
            if handle.stopping:
                return
            with self._turn(person_id, condition):
                with scoped_session(self._container) as db:
                    person = db.get_one(User, person_id)
                    again = self._cipher.open(person) == token
                    name = person.handle
                if again:
                    logger.info(
                        "%s holds the token they cleared again: the %s alarm is "
                        "not dismissed",
                        name,
                        condition,
                    )
                    continue
                self._dismiss_once(token, condition, name)

    def retry(self, db: Session) -> None:
        """The retry timer's run: the reconcile asked for when the alarms due
        now differ from those the last reconcile read, or while an alarm is
        owed whose last try is `retry_seconds` old or more; one running
        already is left to finish."""
        due = self._due(self.holding())
        with self._lock:
            turned = due != self._reconciled
        owed = db.scalar(
            select(
                exists().where(Alarm.owed_at <= datetime.now(UTC) - self._retry_after)
            )
        )
        if turned or owed:
            self._start(again=False)

    def submit_all(self, db: Session, person: User) -> None:
        """In the transaction that set `person`'s token, a first one or
        another in its place: each alarm of theirs that should stand reads as
        not standing, so that once the transaction commits the reconcile
        submits it through the token, and those that should stand and do not
        with it (F142.1, the A3 ruling). Nothing goes through a token it
        replaced."""
        due = self._due(self.holding()) if person.alarms else frozenset()
        for alarm in db.scalars(
            select(Alarm)
            .where(
                Alarm.user_id == person.id,
                Alarm.standing.is_(True),
                Alarm.condition_code.in_(due),
            )
            .order_by(Alarm.id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        ):
            alarm.standing = False
        if self._configured:
            after_commit(self._start)

    def dismiss_all(self, db: Session, person: User, token: str) -> None:
        """In the transaction that cleared `person`'s token, `token` the one
        cleared: each alarm of theirs that stands, an owed one included, reads
        as dismissed from the commit on, with nothing owed; once the
        transaction commits each is dismissed through `token`, tried once,
        off the request (F134). What the bridge does not take is logged,
        counted, and stays on the phone."""
        # The person's row first: a send's write-back holding it has committed
        # before what stands is read (`_take`).
        db.execute(
            select(User.id).where(User.id == person.id).with_for_update(key_share=True)
        )
        alarms = db.scalars(
            select(Alarm)
            .where(
                Alarm.user_id == person.id,
                or_(Alarm.standing.is_(True), Alarm.owed_at.is_not(None)),
            )
            .order_by(Alarm.id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        ).all()
        for alarm in alarms:
            alarm.standing = False
            alarm.owed_at = None
        conditions = tuple(sorted(alarm.condition_code for alarm in alarms))
        if self._configured and conditions:
            after_commit(partial(self._start_clear, person.id, token, conditions))

    def switched(self) -> None:
        """In the transaction that turned a person's switch (`User.alarms`):
        once it commits, the reconcile, off dismissing their standing alarms,
        owed while the bridge does not take them, and on submitting those due
        (F142.1)."""
        if self._configured:
            after_commit(self._start)

    def _reconcile_at_startup(self, db: Session) -> None:
        """At STARTUP: every alarm reconciled, the outage off (design 2
        §7.2)."""
        self._start()

    def _start(self, *, again: bool = True) -> None:
        # Again: a turn after the run's read is reconciled by a run after it.
        self._supervisor.start_loop(ALARM_JOB, self.reconcile, again=again)

    def _start_clear(
        self, person_id: uuid.UUID, token: str, conditions: tuple[Condition, ...]
    ) -> None:
        self._supervisor.start_loop(
            ALARM_CLEAR_JOB,
            partial(self.dismiss_cleared, person_id, token, conditions),
            key=next(self._clears),
        )

    def _due(self, holding: Mapping[Condition, datetime]) -> frozenset[Condition]:
        """The conditions of `holding` whose alarms should stand now."""
        now = datetime.now(UTC)
        return frozenset(
            condition
            for condition, since in holding.items()
            if condition is not Condition.OUTAGE or now - since >= self._outage_after
        )

    def _reconcile_alarm(
        self, person_id: uuid.UUID, condition: Condition, due: frozenset[Condition]
    ) -> None:
        with self._turn(person_id, condition):
            with scoped_session(self._container) as db:
                send = self._compare(db, person_id, condition, due)
            if send is None:
                ALARM_RECONCILES_TOTAL.labels(outcome="unchanged").inc()
                return
            failure = self._send(send)
            with scoped_session(self._container) as db:
                cleared = self._take(db, send, failure)
            if cleared:
                self._dismiss_once(send.token, condition, send.handle)

    def _turn(
        self, person_id: uuid.UUID, condition: Condition
    ) -> AbstractContextManager[None]:
        """The alarm's turn to send, until the block ends."""
        return advisory_turn(
            self._container.session_maker(),
            ALARM_LOCK,
            turn_key(person_id.bytes, condition.value.encode()),
        )

    def _compare(
        self,
        db: Session,
        person_id: uuid.UUID,
        condition: Condition,
        due: frozenset[Condition],
    ) -> _Send | None:
        """The alarm's send, unless whether it should stand is whether it
        stands and nothing is owed."""
        # The person first: a clear committed after this read has read what
        # stood as dismissed by the alarm's read.
        person = db.get_one(User, person_id)
        alarm = db.scalars(
            select(Alarm).where(
                Alarm.user_id == person_id, Alarm.condition_code == condition
            )
        ).one_or_none()
        should = (
            condition in due and person.alarms and person.notification_token is not None
        )
        standing = alarm is not None and alarm.standing
        owed = alarm is not None and alarm.owed_at is not None
        if not owed and should == standing:
            return None
        token = self._cipher.open(person)
        # Nothing of a person's with no token stands or is owed: the clear
        # that dropped it read it all dismissed (`dismiss_all`).
        assert token is not None and person.notification_token is not None
        return _Send(
            person_id=person_id,
            handle=person.handle,
            condition=condition,
            submit=should,
            owed=owed,
            sealed=person.notification_token,
            token=token,
        )

    def _send(self, send: _Send) -> NotificationBridgeFailure | None:
        """The submit or dismiss sent, or the bridge's failure to take it."""
        try:
            if send.submit:
                text = ALARM_TEXTS[send.condition]
                self._client().submit(
                    send.token,
                    send.condition.value,
                    message=text.message,
                    title=text.title,
                    priority=text.priority,
                    url=self._url,
                )
            else:
                self._client().dismiss(send.token, send.condition.value)
        except NotificationBridgeFailure as failure:
            return failure
        return None

    def _take(
        self, db: Session, send: _Send, failure: NotificationBridgeFailure | None
    ) -> bool:
        """What the send came to, written under the alarm's row unless the
        person's token changed meanwhile. Whether their token was cleared
        during a submit that may have reached the phone, which its own dismiss
        then follows."""
        # The person's row locked before the alarm's, as the token's set and
        # clear take it: a clear committed first is read here, and one after
        # waits for this write, which its read of what stands then sees.
        sealed = db.scalar(
            select(User.notification_token)
            .where(User.id == send.person_id)
            .with_for_update(read=True)
        )
        if sealed != send.sealed:
            ALARM_RECONCILES_TOTAL.labels(outcome="superseded").inc()
            logger.info(
                "The token of %s changed during the %s of the %s alarm; what "
                "came of it is not recorded",
                send.handle,
                send.call,
                send.condition,
            )
            return (
                sealed is None
                and send.submit
                and (failure is None or failure.outcome is BridgeOutcome.UNANSWERED)
            )
        alarm = db.scalars(
            select(Alarm)
            .where(
                Alarm.user_id == send.person_id,
                Alarm.condition_code == send.condition,
            )
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        ).one_or_none()
        if alarm is None:
            # Born at the first submit (DB decision 55); the turn keeps a
            # second from being born beside it.
            alarm = Alarm(
                user_id=send.person_id, condition_code=send.condition, standing=False
            )
            db.add(alarm)
        now = datetime.now(UTC)
        if failure is not None:
            alarm.owed_at = now
            ALARM_RECONCILES_TOTAL.labels(outcome="owed").inc()
            logger.log(
                logging.DEBUG if send.owed else logging.WARNING,
                "The %s of the %s alarm to %s is owed: %s",
                send.call,
                send.condition,
                send.handle,
                failure,
            )
            return False
        alarm.standing = send.submit
        alarm.sent_at = now
        alarm.owed_at = None
        ALARM_RECONCILES_TOTAL.labels(outcome="sent").inc()
        if send.owed:
            logger.info(
                "The owed %s of the %s alarm to %s went out",
                send.call,
                send.condition,
                send.handle,
            )
        return False

    def _dismiss_once(self, token: str, condition: Condition, name: str) -> None:
        """A cleared token's dismiss of the condition's alarm, tried once:
        what the bridge does not take stays on the phone."""
        try:
            self._client().dismiss(token, condition.value)
        except NotificationBridgeFailure as failure:
            ALARM_CLEAR_DISMISSES_TOTAL.labels(outcome=failure.outcome).inc()
            logger.warning(
                "The dismiss of the %s alarm to %s after their token's clear "
                "failed, and it stays on the phone: %s",
                condition,
                name,
                failure,
            )
            return
        ALARM_CLEAR_DISMISSES_TOTAL.labels(outcome=BridgeOutcome.SENT).inc()

    def _client(self) -> NotificationBridgeClient:
        return self._container.notification_bridge_client()


def _looked_at(
    db: Session, due: frozenset[Condition]
) -> list[tuple[uuid.UUID, Condition]]:
    """Each person and condition whose alarm should stand — a person holding
    a token with the switch on, never Pilot (DB 238), and a condition due —,
    stands or is owed, in order."""
    holders = db.scalars(
        select(User.id).where(
            User.kind_code == UserKind.PERSON,
            User.notification_token.is_not(None),
            User.alarms.is_(True),
        )
    ).all()
    shown = db.execute(
        select(Alarm.user_id, Alarm.condition_code).where(
            or_(Alarm.standing.is_(True), Alarm.owed_at.is_not(None))
        )
    ).all()
    return sorted(
        {(person_id, condition) for person_id in holders for condition in due}
        | {(person_id, condition) for person_id, condition in shown}
    )
