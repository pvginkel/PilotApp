"""A member's notification of a project (F94, F147; DB 157, 224 to 226, 307
to 315; DB decision 74): a push to every browser of theirs, under the
project's id, while they are offline, alerting for an item that waits on them
they have not been shown, and silent once one they were shown stopped waiting
with another still waiting. What they were shown is their membership's Item
Sightings.

The reconcile of one member reads what waits on them
(`StandingNotificationService`) and what they were shown, in their turn:

- with the project archived, their membership closed or nothing waiting on
  them, their sightings are deleted and nothing is pushed, since nothing is
  dismissed by push: so Archive and Leave forget what they were shown;
- while a page of theirs shows the project (`AppPageService`), every item that
  waits on them is shown, nothing pushed;
- online with no page on it, nothing is pushed and their sightings stand;
- offline with a browser subscribed, an item that waits with no sighting
  alerts; else a sighting of an item that no longer waits updates silently;
  else nothing is pushed.

A push some browser of theirs took (`WebPushService.push`) shows them every
item it named or counted, and the sightings of the others are deleted; one
that none took shows them nothing, and their next reconcile pushes anew.
Nothing is retried: a push service's failure is logged and counted where the
push is sent.

The loop `notification:<project id>` reconciles each member of the project.
The engine bus's `ProjectChanged` asks for it once its commit is in: a commit
that touches the project's items, a work item's state, its membership or its
transitions. `WorkMoved` alone is not heard: it moves a work item's line,
which no notification shows, and a move of its state carries `ProjectChanged`
(`work_status.work_moved`). STARTUP's reconcile asks for it for every project
with an open membership of the project unarchived, or with a sighting, so
that a change no after-commit reconcile reached is found then. The loop
`notification-person:<person id>` reconciles one person in each of their
projects, asked for by their pages: one coming to show a project or ceasing
to, and their going offline, which sends what was held while they were
online.

A member's pushes in one project go out at most once in `spacing_seconds`,
two by default (F94.4; DB 226), from their last push, taken or not, as their
memberships' `notification_sent_at` record it, so that it holds across the two
processes of a roll. A push due inside it is compared again at its end, the
run waiting with no turn and no database connection held: a burst of commits
comes to one push per window, of the latest state. A run told to stop pushes
nothing more; what it held stays unshown in the record, for the member's next
reconcile.

A member's turn is an advisory lock held on a connection of its own, from
before the record is read until what the push came to is written, so that two
processes push them once. The read, the push's own read and delete, and the
write are transactions of their own on that connection (`Turn.transaction`),
so that a turn holds one connection and never waits on the pool for another:
across the push services' calls no row or table is locked and no transaction
is open, and no request or commit waits on them.
"""

import logging
import uuid
from collections.abc import Collection, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING

from sqlalchemy import and_, delete, exists, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.database import scoped_session
from app.engine.bus import EngineBus, EngineEvent, ProjectChanged
from app.models import ItemSighting, Project, ProjectMember, PushSubscription
from app.services.advisory_turn import Turn, advisory_turn, turn_key
from app.services.app_page_service import AppPageService, PresenceEvent
from app.services.standing_notification_service import StandingNotification
from app.services.supervisor import LoopHandle, Supervisor
from app.services.web_push import WebPushService

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)

NOTIFICATION_JOB = "notification"
NOTIFICATION_PERSON_JOB = "notification-person"

NOTIFICATION_SPACING_SECONDS = 2.0
"""The least time between two of a member's pushes in one project (F94.4)."""

NOTIFICATION_LOCK = 224
"""The first key of a member's turn (`advisory_turn`); the second is drawn
from the person's and the project's ids."""

type _Member = tuple[uuid.UUID, uuid.UUID]
"""A project's id and a person's, a member to reconcile."""


@dataclass(frozen=True)
class _Due:
    """A member's push the compare found wanting, and what it read."""

    membership_ids: tuple[int, ...]
    """Every membership of the person's in the project."""
    holder_id: int
    """The open membership, whose push it is."""
    notification: StandingNotification
    alert: bool
    last_push: datetime | None
    """When the person's last push in the project went out; none before
    their first."""


class NotificationReconcileService:
    """Pushes each member a project's notification as what waits on them and
    what they were shown say."""

    def __init__(
        self,
        container: "ServiceContainer",
        supervisor: Supervisor,
        engine_bus: EngineBus,
        app_page_service: AppPageService,
        web_push_service: WebPushService,
        spacing_seconds: float = NOTIFICATION_SPACING_SECONDS,
    ) -> None:
        """Register the `notification` job, whose reconcile runs at STARTUP,
        and the `notification-person` job, and hear the engine's bus and the
        pages; where the deployment pushes nothing, none of them.

        Args:
            container: Gives each transaction its database session, and the
                notification each member should see
            supervisor: Runs the reconciles
            engine_bus: Tells of each commit that moves what a project's
                screens show
            app_page_service: Says whether a person is online and what their
                pages show, and tells of each turn of it
            web_push_service: Pushes to a person's browsers; with no key,
                nothing is pushed
            spacing_seconds: The least time between two of a member's pushes
                in one project
        """
        self._container = container
        self._supervisor = supervisor
        self._pages = app_page_service
        self._web_push = web_push_service
        self._spacing = timedelta(seconds=spacing_seconds)
        if web_push_service.public_key is None:
            return
        supervisor.register_job(
            NOTIFICATION_JOB, needs_controller=False, reconcile=self._reconcile_all
        )
        supervisor.register_job(NOTIFICATION_PERSON_JOB, needs_controller=False)
        engine_bus.subscribe(self._heard)
        app_page_service.subscribe(self._heard_pages)

    def reconcile(self, project_id: uuid.UUID, handle: LoopHandle) -> None:
        """The loop `notification:<project id>`'s run: each person with a
        membership of the project open or with a sighting, reconciled in
        their turn (`_reconcile_members`)."""
        with scoped_session(self._container) as db:
            people = db.scalars(
                select(ProjectMember.user_id)
                .where(ProjectMember.project_id == project_id, _looked_at())
                .distinct()
                .order_by(ProjectMember.user_id)
            ).all()
        self._reconcile_members([(project_id, person) for person in people], handle)

    def reconcile_person(self, person_id: uuid.UUID, handle: LoopHandle) -> None:
        """The loop `notification-person:<person id>`'s run: the person in
        each project with a membership of theirs open or with a sighting,
        reconciled in their turn (`_reconcile_members`)."""
        with scoped_session(self._container) as db:
            projects = db.scalars(
                select(ProjectMember.project_id)
                .where(ProjectMember.user_id == person_id, _looked_at())
                .distinct()
                .order_by(ProjectMember.project_id)
            ).all()
        self._reconcile_members([(project, person_id) for project in projects], handle)

    def _reconcile_members(
        self, members: Sequence[_Member], handle: LoopHandle
    ) -> None:
        """Each of `members` compared, and pushed when due. One whose last
        push in the project is not yet `spacing_seconds` old is compared
        again once it is, the run waiting with no turn and no database
        connection held. Returns once each is, or when the loop is told to
        stop, pushing nothing more."""
        while members:
            spaced: list[tuple[_Member, datetime]] = []
            for member in members:
                if handle.stopping:
                    return
                after = self._reconcile_member(*member)
                if after is not None:
                    spaced.append((member, after))
            if not spaced:
                return
            members = [member for member, _ in spaced]
            wake = min(at for _, at in spaced)
            if handle.wait(max((wake - datetime.now(UTC)).total_seconds(), 0.0)):
                for project_id, person_id in members:
                    logger.info(
                        "The push of project %s's notification to %s is left to "
                        "their next reconcile: the run stopped inside its window",
                        project_id,
                        person_id,
                    )
                return

    def _heard(self, event: EngineEvent) -> None:
        if isinstance(event, ProjectChanged):
            self._start(event.project_id)

    def _heard_pages(self, event: PresenceEvent) -> None:
        # Again: a turn after the run's read is reconciled by a run after it.
        self._supervisor.start_loop(
            NOTIFICATION_PERSON_JOB,
            partial(self.reconcile_person, event.user_id),
            key=str(event.user_id),
            again=True,
        )

    def _reconcile_all(self, db: Session) -> None:
        """At STARTUP: the reconcile of every project with an open membership
        of the project unarchived, or with a sighting, archived projects' and
        closed memberships' among them."""
        projects = db.scalars(
            select(ProjectMember.project_id)
            .join(Project, Project.id == ProjectMember.project_id)
            .where(
                or_(
                    and_(ProjectMember.left_at.is_(None), Project.archived.is_(False)),
                    _sighted(),
                )
            )
            .distinct()
            .order_by(ProjectMember.project_id)
        ).all()
        for project_id in projects:
            self._start(project_id)

    def _start(self, project_id: uuid.UUID) -> None:
        # Again: a commit after the run's last read is reconciled by a run
        # after it.
        self._supervisor.start_loop(
            NOTIFICATION_JOB,
            partial(self.reconcile, project_id),
            key=str(project_id),
            again=True,
        )

    def _reconcile_member(
        self, project_id: uuid.UUID, person_id: uuid.UUID
    ) -> datetime | None:
        """The member's compare and push, in their turn; with their last push
        not yet `spacing_seconds` old, nothing pushed, and the time it is."""
        with self._turn(person_id, project_id) as turn:
            with turn.transaction() as db:
                due = self._compare(db, project_id, person_id)
            if due is None:
                return None
            if due.last_push is not None:
                after = due.last_push + self._spacing
                if after > datetime.now(UTC):
                    return after
            took = self._web_push.push(
                person_id, due.notification.push(alert=due.alert), turn.transaction
            )
            with turn.transaction() as db:
                db.execute(
                    update(ProjectMember)
                    .where(ProjectMember.id == due.holder_id)
                    .values(notification_sent_at=datetime.now(UTC))
                )
                if took:
                    _show(db, due.membership_ids, due.holder_id, due.notification.items)
        return None

    def _compare(
        self, db: Session, project_id: uuid.UUID, person_id: uuid.UUID
    ) -> _Due | None:
        """In `db`'s transaction, what the member was shown brought in line
        where nothing is to be pushed; the push due, if one is."""
        memberships = db.scalars(
            select(ProjectMember)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == person_id,
            )
            .order_by(ProjectMember.joined_at, ProjectMember.id)
        ).all()
        membership_ids = tuple(membership.id for membership in memberships)
        holder = next((m for m in memberships if m.left_at is None), None)
        notification = (
            None
            if holder is None
            else self._container.standing_notification_service(db=db).should_see(
                db.get_one(Project, project_id), [holder]
            )[holder.id]
        )
        if holder is None or notification is None:
            _show(db, membership_ids, None, frozenset())
            return None
        if self._pages.shows(db, person_id, project_id):
            _show(db, membership_ids, holder.id, notification.items)
            return None
        # A closed membership's sightings go whatever is pushed: Leave forgets.
        _show(db, membership_ids, holder.id, None)
        if self._pages.online(db, person_id):
            return None
        seen = set(
            db.scalars(
                select(ItemSighting.item_id).where(ItemSighting.member_id == holder.id)
            )
        )
        alert = not notification.items <= seen
        if not alert and seen <= notification.items:
            return None
        if not db.scalar(select(exists().where(PushSubscription.user_id == person_id))):
            return None
        return _Due(
            membership_ids=membership_ids,
            holder_id=holder.id,
            notification=notification,
            alert=alert,
            last_push=max(
                (m.notification_sent_at for m in memberships if m.notification_sent_at),
                default=None,
            ),
        )

    def _turn(
        self, person_id: uuid.UUID, project_id: uuid.UUID
    ) -> AbstractContextManager[Turn]:
        """The member's turn to be pushed, until the block ends."""
        return advisory_turn(
            self._container.session_maker(),
            NOTIFICATION_LOCK,
            turn_key(person_id.bytes, project_id.bytes),
        )


def _sighted() -> ColumnElement[bool]:
    return exists().where(ItemSighting.member_id == ProjectMember.id)


def _looked_at() -> ColumnElement[bool]:
    """A membership that may be pushed, an open one, or that has sightings to
    forget."""
    return or_(ProjectMember.left_at.is_(None), _sighted())


def _show(
    db: Session,
    membership_ids: Collection[int],
    holder_id: int | None,
    items: frozenset[uuid.UUID] | None,
) -> None:
    """The person's sightings in the project, on any of `membership_ids`,
    made those of `items` on `holder_id`: every other deleted, and each of
    `items` it lacks written. With `items` none, the holder's stand as they
    are, and the other memberships' are deleted."""
    others = [member for member in membership_ids if member != holder_id]
    if others:
        db.execute(delete(ItemSighting).where(ItemSighting.member_id.in_(others)))
    if holder_id is None or items is None:
        return
    db.execute(
        delete(ItemSighting).where(
            ItemSighting.member_id == holder_id, ItemSighting.item_id.not_in(items)
        )
    )
    seen = set(
        db.scalars(
            select(ItemSighting.item_id).where(ItemSighting.member_id == holder_id)
        )
    )
    db.add_all(
        ItemSighting(member_id=holder_id, item_id=item) for item in sorted(items - seen)
    )
