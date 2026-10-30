"""The standing notifications' reconcile (F94.3, F94.4; DB decision 51; design
2 §7.2): what each member should see of a project, derived from the record
(`StandingNotificationService`), compared with what their membership last
sent, and submitted or dismissed through the bridge when it differs.

A project's reconcile is a loop of the job `notification`, keyed by the
project's id. The engine bus's `ProjectChanged` asks for it once its commit is
in: a commit that touches the project's items, a work item's state, its
membership or its transitions. `WorkMoved` alone is not heard: it moves a work
item's line, which no notification shows, and a move of its state carries
`ProjectChanged` (`work_status.work_moved`). The retry timer asks for it while
a membership of the project is owed and its retry is due, and STARTUP's
reconcile for every project with a membership whose notification stands, is
owed or should stand, so that a change no after-commit reconcile reached is
found then.

Of one person in one project the phone shows one notification, under the
project's id, whichever of their memberships sent it; the latest of them takes
what goes out. Their sends take turns under an advisory lock held on a
connection of its own, from before the record is read until what went out is
written, so that the phone ends on the latest state with two processes running.
The read and the write are transactions of their own: across the bridge's
call no row or table is locked, and no request or commit waits on it. The
write is dropped when the person's token changed during the call: the set or
clear that changed it says what the record holds since.

A send the bridge refuses or does not answer is owed, `notification_owed_at`
the time of the try: the project's next reconcile sends the current state
again, the timer's once `retry_seconds` have passed. The log says so when a
membership turns owed and when its owed send goes out, not at each retry.

A token's set (`submit_all`) has the person's current state submitted through
it whatever went before (F94.3, DB 224). A token's clear (`dismiss_all`) is
best effort (F134): what stood reads as dismissed at once, nothing owed, and
each dismiss is tried once, off the request, through the token in hand, by a
loop of the job `notification-clear`; what the bridge does not take stays on
the phone. A submit through the token in flight when the clear commits is
followed by a dismiss of its own.
"""

import itertools
import logging
import uuid
from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING

from prometheus_client import Counter
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.database import scoped_session
from app.engine.bus import EngineBus, EngineEvent, ProjectChanged
from app.models import Project, ProjectMember, User
from app.models.reference import NotificationPriority
from app.services.advisory_turn import advisory_turn, turn_key
from app.services.notification_bridge_client import (
    BridgeOutcome,
    BridgePriority,
    NotificationBridgeClient,
    NotificationBridgeFailure,
)
from app.services.notification_token_cipher import NotificationTokenCipher
from app.services.standing_notification_service import StandingNotification
from app.services.supervisor import LoopHandle, Supervisor
from app.utils.after_commit import after_commit

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)

NOTIFICATION_JOB = "notification"
NOTIFICATION_CLEAR_JOB = "notification-clear"
NOTIFICATION_RETRY_TIMER = "notification-retry"

NOTIFICATION_RETRY_SECONDS = 60.0
"""The least time between two of the retry timer's tries of an owed send."""

NOTIFICATION_LOCK = 224
"""The first key of a member's turn (`advisory_turn`); the second is drawn
from the person's and the project's ids."""

_BRIDGE_PRIORITY: dict[NotificationPriority, BridgePriority] = {
    NotificationPriority.MIN: "min",
    NotificationPriority.DEFAULT: "default",
    NotificationPriority.HIGH: "high",
}

NOTIFICATION_RECONCILES_TOTAL = Counter(
    "pilot_notification_reconciles_total",
    "Compares of what a member should see of a project with what their "
    "membership last sent, by outcome: unchanged, sent, owed (the send failed) "
    "or superseded (the person's token changed during the send)",
    ["outcome"],
)
NOTIFICATION_CLEAR_DISMISSES_TOTAL = Counter(
    "pilot_notification_clear_dismisses_total",
    "Dismisses tried once through a token just cleared, by outcome: sent, "
    "refused or unanswered; one not sent stays on the phone",
    ["outcome"],
)


@dataclass(frozen=True)
class _Due:
    """A member's send the compare found wanting, and what it read."""

    project_id: uuid.UUID
    person_id: uuid.UUID
    handle: str
    membership_ids: tuple[int, ...]
    holder_id: int
    """The latest membership, which takes a submit."""
    notification: StandingNotification | None
    """What to submit; none to dismiss."""
    owed: bool
    sealed: str
    """The person's token as the record held it, sealed."""
    token: str

    @property
    def call(self) -> str:
        return "dismiss" if self.notification is None else "submit"


class NotificationReconcileService:
    """Keeps each member's standing notifications as the record says they
    stand."""

    def __init__(
        self,
        container: "ServiceContainer",
        supervisor: Supervisor,
        engine_bus: EngineBus,
        notification_token_cipher: NotificationTokenCipher,
        bridge_configured: bool,
        retry_seconds: float = NOTIFICATION_RETRY_SECONDS,
    ) -> None:
        """Register the `notification` job, whose reconcile runs at STARTUP,
        the `notification-clear` job and the retry timer, and hear the
        engine's bus; with no bridge configured, none of them, and nothing is
        sent.

        Args:
            container: Gives each transaction its database session, and the
                bridge's client
            supervisor: Runs the reconciles and the clears' dismisses
            engine_bus: Tells of each commit that moves what a project's
                screens show
            notification_token_cipher: Opens the token a send goes through
            bridge_configured: False sends nothing
            retry_seconds: The least time between two of the retry timer's
                tries of an owed send
        """
        self._container = container
        self._supervisor = supervisor
        self._cipher = notification_token_cipher
        self._configured = bridge_configured
        self._retry_after = timedelta(seconds=retry_seconds)
        self._clears = itertools.count(1)
        if not bridge_configured:
            return
        supervisor.register_job(
            NOTIFICATION_JOB, needs_controller=False, reconcile=self._reconcile_all
        )
        supervisor.register_job(NOTIFICATION_CLEAR_JOB, needs_controller=False)
        supervisor.register_timer(
            NOTIFICATION_RETRY_TIMER, self.retry, needs_controller=False
        )
        engine_bus.subscribe(self._heard)

    def reconcile(self, project_id: uuid.UUID, handle: LoopHandle) -> None:
        """The loop `notification:<project id>`'s run: for each person with a
        membership of the project that is open, stands or is owed, in their
        turn, what they should see compared with what was last sent, and
        submitted or dismissed when it differs or is owed. Returns once each
        is, or when the loop is told to stop."""
        with scoped_session(self._container) as db:
            people = db.scalars(
                select(ProjectMember.user_id)
                .where(ProjectMember.project_id == project_id, _looked_at())
                .distinct()
                .order_by(ProjectMember.user_id)
            ).all()
        for person_id in people:
            if handle.stopping:
                return
            self._reconcile_member(project_id, person_id)

    def dismiss_cleared(
        self,
        person_id: uuid.UUID,
        token: str,
        project_ids: Sequence[uuid.UUID],
        handle: LoopHandle,
    ) -> None:
        """A loop `notification-clear:<n>`'s run, once the clear of the
        person's `token` committed: each project's notification dismissed
        through it, in the member's turn, tried once, unless the person holds
        `token` again, whose set submits afresh. Returns once each is, or when
        the loop is told to stop."""
        for project_id in project_ids:
            if handle.stopping:
                return
            with self._turn(person_id, project_id):
                with scoped_session(self._container) as db:
                    person = db.get_one(User, person_id)
                    again = self._cipher.open(person) == token
                    name = person.handle
                if again:
                    logger.info(
                        "%s holds the token they cleared again: project %s's "
                        "notification is not dismissed",
                        name,
                        project_id,
                    )
                    continue
                self._dismiss_once(token, project_id, name)

    def retry(self, db: Session) -> None:
        """The retry timer's run (F94.4): the reconcile of each project with a
        membership owed whose last try is `retry_seconds` old or more; one
        running already is left to finish."""
        due = db.scalars(
            select(ProjectMember.project_id)
            .where(
                ProjectMember.notification_owed_at
                <= datetime.now(UTC) - self._retry_after
            )
            .distinct()
            .order_by(ProjectMember.project_id)
        ).all()
        for project_id in due:
            self._start(project_id, again=False)

    def submit_all(self, db: Session, person: User) -> None:
        """In the transaction that set `person`'s token, a first one or
        another in its place: what each of their open memberships of an
        unarchived project last sent reads as nothing, so that once the
        transaction commits each submits its current state through the token
        (F94.3, DB 224). Nothing goes through a token it replaced."""
        for membership in db.scalars(
            select(ProjectMember)
            .join(Project, Project.id == ProjectMember.project_id)
            .where(
                ProjectMember.user_id == person.id,
                ProjectMember.left_at.is_(None),
                Project.archived.is_(False),
            )
            .order_by(ProjectMember.id)
            .with_for_update(of=ProjectMember, key_share=True)
            .execution_options(populate_existing=True)
        ):
            _unsent(membership)
        if not self._configured:
            return
        for project_id in db.scalars(
            select(ProjectMember.project_id)
            .where(ProjectMember.user_id == person.id, _looked_at())
            .distinct()
            .order_by(ProjectMember.project_id)
        ):
            after_commit(partial(self._start, project_id))

    def dismiss_all(self, db: Session, person: User, token: str) -> None:
        """In the transaction that cleared `person`'s token, `token` the one
        cleared: each notification of theirs that stands, an owed one
        included, reads as dismissed from the commit on, with nothing owed;
        once the transaction commits each is dismissed through `token`, tried
        once, off the request (F94.3, F134). What the bridge does not take is
        logged, counted, and stays on the phone."""
        # The person's row first: a send's write-back holding it has committed
        # before what stands is read (`_take`).
        db.execute(
            select(User.id).where(User.id == person.id).with_for_update(key_share=True)
        )
        memberships = db.scalars(
            select(ProjectMember)
            .where(
                ProjectMember.user_id == person.id,
                or_(_standing(), ProjectMember.notification_owed_at.is_not(None)),
            )
            .order_by(ProjectMember.id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        ).all()
        for membership in memberships:
            _unsent(membership)
            membership.notification_owed_at = None
        project_ids = tuple(
            sorted({membership.project_id for membership in memberships})
        )
        if self._configured and project_ids:
            after_commit(partial(self._start_clear, person.id, token, project_ids))

    def _heard(self, event: EngineEvent) -> None:
        if isinstance(event, ProjectChanged):
            self._start(event.project_id)

    def _reconcile_all(self, db: Session) -> None:
        """At STARTUP: the reconcile of every project with a membership whose
        notification stands, is owed, or should stand, archived projects' and
        closed memberships' among them (design 2 §7.2; DB decision 51)."""
        projects = db.scalars(
            select(ProjectMember.project_id)
            .join(Project, Project.id == ProjectMember.project_id)
            .join(User, User.id == ProjectMember.user_id)
            .where(
                or_(
                    _standing(),
                    ProjectMember.notification_owed_at.is_not(None),
                    and_(
                        ProjectMember.left_at.is_(None),
                        Project.archived.is_(False),
                        User.notification_token.is_not(None),
                    ),
                )
            )
            .distinct()
            .order_by(ProjectMember.project_id)
        ).all()
        for project_id in projects:
            self._start(project_id)

    def _start(self, project_id: uuid.UUID, *, again: bool = True) -> None:
        # Again: a commit after the run's last read is reconciled by a run
        # after it.
        self._supervisor.start_loop(
            NOTIFICATION_JOB,
            partial(self.reconcile, project_id),
            key=str(project_id),
            again=again,
        )

    def _start_clear(
        self, person_id: uuid.UUID, token: str, project_ids: tuple[uuid.UUID, ...]
    ) -> None:
        self._supervisor.start_loop(
            NOTIFICATION_CLEAR_JOB,
            partial(self.dismiss_cleared, person_id, token, project_ids),
            key=next(self._clears),
        )

    def _reconcile_member(self, project_id: uuid.UUID, person_id: uuid.UUID) -> None:
        with self._turn(person_id, project_id):
            with scoped_session(self._container) as db:
                due = self._due(db, project_id, person_id)
            if due is None:
                NOTIFICATION_RECONCILES_TOTAL.labels(outcome="unchanged").inc()
                return
            failure = self._send(due)
            with scoped_session(self._container) as db:
                cleared = self._take(db, due, failure)
            if cleared:
                self._dismiss_once(due.token, project_id, due.handle)

    def _turn(
        self, person_id: uuid.UUID, project_id: uuid.UUID
    ) -> AbstractContextManager[None]:
        """The member's turn to send, until the block ends."""
        return advisory_turn(
            self._container.session_maker(),
            NOTIFICATION_LOCK,
            turn_key(person_id.bytes, project_id.bytes),
        )

    def _due(
        self, db: Session, project_id: uuid.UUID, person_id: uuid.UUID
    ) -> _Due | None:
        """The member's send, unless what they should see is what was last
        sent and nothing is owed."""
        # The person first: a clear committed after this read has read what
        # stood as dismissed by the memberships' read.
        person = db.get_one(User, person_id)
        memberships = db.scalars(
            select(ProjectMember)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == person_id,
                _looked_at(),
            )
            .order_by(ProjectMember.joined_at, ProjectMember.id)
        ).all()
        if not memberships:
            return None
        holder = memberships[-1]
        notification = self._container.standing_notification_service().should_see(
            db.get_one(Project, project_id), [holder]
        )[holder.id]
        shown = next(
            (
                m
                for m in reversed(memberships)
                if m.notification_priority_code is not None
            ),
            None,
        )
        owed = any(m.notification_owed_at is not None for m in memberships)
        if not owed and _shows(shown, notification):
            return None
        token = self._cipher.open(person)
        # Nothing of a person's with no token stands or is owed: the clear
        # that dropped it read it all dismissed (`dismiss_all`).
        assert token is not None and person.notification_token is not None
        return _Due(
            project_id=project_id,
            person_id=person_id,
            handle=person.handle,
            membership_ids=tuple(m.id for m in memberships),
            holder_id=holder.id,
            notification=notification,
            owed=owed,
            sealed=person.notification_token,
            token=token,
        )

    def _send(self, due: _Due) -> NotificationBridgeFailure | None:
        """The submit or dismiss sent, or the bridge's failure to take it."""
        try:
            if due.notification is None:
                self._client().dismiss(due.token, str(due.project_id))
            else:
                self._client().submit(
                    due.token,
                    due.notification.sequence_id,
                    message=due.notification.message,
                    title=due.notification.title,
                    priority=_BRIDGE_PRIORITY[due.notification.priority],
                    url=due.notification.url,
                )
        except NotificationBridgeFailure as failure:
            return failure
        return None

    def _take(
        self, db: Session, due: _Due, failure: NotificationBridgeFailure | None
    ) -> bool:
        """What the send came to, written under the memberships' rows unless
        the person's token changed meanwhile. Whether their token was cleared
        during a submit that may have reached the phone, which its own
        dismiss then follows."""
        # The person's row locked before the memberships', as the token's set
        # and clear take it: a clear committed first is read here, and one
        # after waits for this write, which its read of what stands then sees.
        sealed = db.scalar(
            select(User.notification_token)
            .where(User.id == due.person_id)
            .with_for_update(read=True)
        )
        if sealed != due.sealed:
            NOTIFICATION_RECONCILES_TOTAL.labels(outcome="superseded").inc()
            logger.info(
                "The token of %s changed during the %s of project %s's "
                "notification; what came of it is not recorded",
                due.handle,
                due.call,
                due.project_id,
            )
            return (
                sealed is None
                and due.notification is not None
                and (failure is None or failure.outcome is BridgeOutcome.UNANSWERED)
            )
        memberships = db.scalars(
            select(ProjectMember)
            .where(ProjectMember.id.in_(due.membership_ids))
            .order_by(ProjectMember.id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        ).all()
        now = datetime.now(UTC)
        if failure is not None:
            for membership in memberships:
                membership.notification_owed_at = now
            NOTIFICATION_RECONCILES_TOTAL.labels(outcome="owed").inc()
            logger.log(
                logging.DEBUG if due.owed else logging.WARNING,
                "The %s of project %s's notification to %s is owed: %s",
                due.call,
                due.project_id,
                due.handle,
                failure,
            )
            return False
        for membership in memberships:
            _unsent(membership)
            membership.notification_owed_at = None
            if due.notification is None:
                membership.notification_sent_at = now
        if due.notification is not None:
            holder = next(m for m in memberships if m.id == due.holder_id)
            holder.notification_priority_code = due.notification.priority
            holder.notification_text = due.notification.message
            holder.notification_url = due.notification.url
            holder.notification_sent_at = now
        NOTIFICATION_RECONCILES_TOTAL.labels(outcome="sent").inc()
        if due.owed:
            logger.info(
                "The owed %s of project %s's notification to %s went out",
                due.call,
                due.project_id,
                due.handle,
            )
        return False

    def _dismiss_once(self, token: str, project_id: uuid.UUID, name: str) -> None:
        """A cleared token's dismiss of the project's notification, tried
        once: what the bridge does not take stays on the phone."""
        try:
            self._client().dismiss(token, str(project_id))
        except NotificationBridgeFailure as failure:
            NOTIFICATION_CLEAR_DISMISSES_TOTAL.labels(outcome=failure.outcome).inc()
            logger.warning(
                "The dismiss of project %s's notification to %s after their "
                "token's clear failed, and it stays on the phone: %s",
                project_id,
                name,
                failure,
            )
            return
        NOTIFICATION_CLEAR_DISMISSES_TOTAL.labels(outcome=BridgeOutcome.SENT).inc()

    def _client(self) -> NotificationBridgeClient:
        return self._container.notification_bridge_client()


def _looked_at() -> ColumnElement[bool]:
    """A membership whose notification stands, is owed, or may be due: an
    open one."""
    return or_(
        ProjectMember.left_at.is_(None),
        _standing(),
        ProjectMember.notification_owed_at.is_not(None),
    )


def _standing() -> ColumnElement[bool]:
    return ProjectMember.notification_priority_code.is_not(None)


def _shows(
    membership: ProjectMember | None, notification: StandingNotification | None
) -> bool:
    """Whether what `membership` last sent is `notification`: none for no
    membership standing and none to see. The title is in no column."""
    if membership is None or notification is None:
        return membership is None and notification is None
    return (
        membership.notification_priority_code,
        membership.notification_text,
        membership.notification_url,
    ) == (notification.priority, notification.message, notification.url)


def _unsent(membership: ProjectMember) -> None:
    """Nothing standing from `membership`."""
    membership.notification_priority_code = None
    membership.notification_text = None
    membership.notification_url = None
