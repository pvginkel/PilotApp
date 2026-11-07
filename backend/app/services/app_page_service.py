"""A person's pages of Pilot, and whether they are online (F147; DB 312; DB
decision 74).

A page its person is active in beats. Its first beat writes its App Page,
whose id the server mints, and each beat after, naming it, sets when it beat
and the project it shows. Its away deletes it. A page whose beat is
`EXPIRY_SECONDS` old counts for nothing and is deleted: by the timer
`app-page-expiry`, or by the next beat or away of its person, whichever comes
first. A person is online while a page of theirs counts: derived, never
stored (`online`).

The listeners hear two things, each once, after the commit of the request or
the sweep that made it so: a project coming to be shown by a page of the
person, none of theirs having shown it, or ceasing to be, the last that showed
it gone or moved (`ShowingTurned`); and the person going offline, their last
page deleted (`WentOffline`). A listener reads what stands when it runs, which
a later commit may have moved since: a beat after the away that took the
person offline.

What was told is what the person's rows are. Every write of their pages holds
their User row, reads their pages under it, and compares them with what it
leaves, so that two processes during a roll, a beat racing another page's
away, or two sweeps, take turns there: a person goes offline once, and only
when no page of theirs is left. The sweep skips a person another transaction
holds; its next round, or that transaction, expires their pages.
"""

import logging
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.exceptions import RecordNotFoundException
from app.models import AppPage, Project, User
from app.services.supervisor import Supervisor
from app.utils.after_commit import after_commit

logger = logging.getLogger(__name__)

EXPIRY_TIMER = "app-page-expiry"

EXPIRY_SECONDS = 90.0
"""How old a page's beat is when the page counts for nothing (DB 312)."""


@dataclass(frozen=True)
class ShowingTurned:
    """A page of the person came to show the project, none of theirs having
    shown it (`shown`), or the last of theirs that showed it was deleted or
    moved off it."""

    user_id: uuid.UUID
    project_id: uuid.UUID
    shown: bool


@dataclass(frozen=True)
class WentOffline:
    """The person's last page was deleted, by its away or its expiry."""

    user_id: uuid.UUID


type PresenceEvent = ShowingTurned | WentOffline
type PresenceListener = Callable[[PresenceEvent], None]


class AppPageService:
    """Writes the pages' beats and aways, expires them on its timer, and
    tells the listeners what they turn."""

    def __init__(self, supervisor: Supervisor) -> None:
        """Register the expiry's timer, which needs no controller.

        Args:
            supervisor: Runs the timer on its tick
        """
        self._expiry = timedelta(seconds=EXPIRY_SECONDS)
        self._listeners: tuple[PresenceListener, ...] = ()
        supervisor.register_timer(EXPIRY_TIMER, self.expire, needs_controller=False)

    def subscribe(self, listener: PresenceListener) -> None:
        """Call `listener` with each event once the transaction that made it
        so has committed, in the thread that committed it."""
        self._listeners = (*self._listeners, listener)

    def begin(
        self, db: Session, person: User, project_id: uuid.UUID | None
    ) -> uuid.UUID:
        """A page's first beat, in `db`'s transaction: its App Page written,
        showing `project_id`, or none.

        Returns:
            The page's id, which it names in its beats after and its away

        Raises:
            RecordNotFoundException: No project has the id `project_id`
        """
        _require_project(db, project_id)
        _hold(db, person.id)
        pages = _pages(db, person.id)
        now = datetime.now(UTC)
        before = _shows(pages)
        live = self._expire_pages(db, pages, now)
        page = AppPage(user_id=person.id, project_id=project_id, beat_at=now)
        db.add(page)
        db.flush()
        self._tell(person.id, before, _shows([*live, page]))
        return page.id

    def beat(
        self,
        db: Session,
        person: User,
        page_id: uuid.UUID,
        project_id: uuid.UUID | None,
    ) -> None:
        """A beat of the page `page_id`, in `db`'s transaction: when it beat,
        now, and the project it shows, `project_id` or none.

        Raises:
            RecordNotFoundException: The page is no page of `person`'s that
                counts: its away or its expiry ended it, or it is another
                person's, and the page beats afresh with `begin`. Or no project
                has the id `project_id`
        """
        _require_project(db, project_id)
        _hold(db, person.id)
        pages = _pages(db, person.id)
        now = datetime.now(UTC)
        before = _shows(pages)
        live = self._expire_pages(db, pages, now)
        page = next((page for page in live if page.id == page_id), None)
        if page is None:
            raise RecordNotFoundException("App Page", str(page_id))
        page.beat_at = now
        page.project_id = project_id
        db.flush()
        self._tell(person.id, before, _shows(live))

    def away(self, db: Session, person: User, page_id: uuid.UUID) -> None:
        """The away of the page `page_id`, in `db`'s transaction: its App Page
        deleted. A page that has ended already, or is another person's, is
        nothing to delete."""
        _hold(db, person.id)
        pages = _pages(db, person.id)
        now = datetime.now(UTC)
        before = _shows(pages)
        live = self._expire_pages(db, pages, now)
        for page in live:
            if page.id == page_id:
                db.delete(page)
        db.flush()
        self._tell(person.id, before, _shows(p for p in live if p.id != page_id))

    def expire(self, db: Session) -> None:
        """The timer's run, in `db`'s transaction, the scheduler's: every page
        that counts for nothing deleted, but those of a person another
        transaction holds."""
        now = datetime.now(UTC)
        people = db.scalars(
            select(AppPage.user_id)
            .where(AppPage.beat_at <= now - self._expiry)
            .distinct()
            .order_by(AppPage.user_id)
        ).all()
        expired = 0
        for user_id in people:
            if not _hold(db, user_id, skip_locked=True):
                continue
            pages = _pages(db, user_id)
            before = _shows(pages)
            live = self._expire_pages(db, pages, now)
            expired += len(pages) - len(live)
            db.flush()
            self._tell(user_id, before, _shows(live))
        if expired:
            logger.info("%d pages of Pilot expired", expired)

    def online(self, db: Session, user_id: uuid.UUID) -> bool:
        """Whether the person is online: a page of theirs counts."""
        return bool(
            db.scalar(
                select(
                    exists().where(
                        AppPage.user_id == user_id,
                        AppPage.beat_at > datetime.now(UTC) - self._expiry,
                    )
                )
            )
        )

    def shows(self, db: Session, user_id: uuid.UUID, project_id: uuid.UUID) -> bool:
        """Whether a page of the person's that counts shows the project."""
        return bool(
            db.scalar(
                select(
                    exists().where(
                        AppPage.user_id == user_id,
                        AppPage.project_id == project_id,
                        AppPage.beat_at > datetime.now(UTC) - self._expiry,
                    )
                )
            )
        )

    def _expire_pages(
        self, db: Session, pages: Sequence[AppPage], now: datetime
    ) -> list[AppPage]:
        """Delete those of `pages` that count for nothing at `now`; the rest."""
        live = []
        for page in pages:
            if page.beat_at <= now - self._expiry:
                db.delete(page)
            else:
                live.append(page)
        return live

    def _tell(
        self,
        user_id: uuid.UUID,
        before: list[uuid.UUID | None],
        after: list[uuid.UUID | None],
    ) -> None:
        """Tell the listeners, once the transaction commits, what turned
        between the person's pages as they were, `before`, and as they are
        left, `after`: the project each shows, or none."""
        was = {project for project in before if project is not None}
        now = {project for project in after if project is not None}
        events: list[PresenceEvent] = [
            ShowingTurned(user_id, project, shown=True) for project in sorted(now - was)
        ]
        events += [
            ShowingTurned(user_id, project, shown=False)
            for project in sorted(was - now)
        ]
        if before and not after:
            events.append(WentOffline(user_id))
        if events:
            after_commit(partial(self._deliver, tuple(events)))

    def _deliver(self, events: tuple[PresenceEvent, ...]) -> None:
        listeners = self._listeners
        for event in events:
            for listener in listeners:
                # A listener that fails keeps the event from no other.
                try:
                    listener(event)
                except Exception:
                    logger.exception("Listener %r failed on %r", listener, event)


def _hold(db: Session, user_id: uuid.UUID, *, skip_locked: bool = False) -> bool:
    """Hold the person's User row for the transaction, the turn every write
    of their pages takes; False when `skip_locked` and another transaction
    holds it."""
    held = db.scalar(
        select(User.id)
        .where(User.id == user_id)
        .with_for_update(key_share=True, skip_locked=skip_locked)
    )
    return held is not None


def _pages(db: Session, user_id: uuid.UUID) -> Sequence[AppPage]:
    """The person's pages as committed, read under their User row."""
    return db.scalars(
        select(AppPage)
        .where(AppPage.user_id == user_id)
        .order_by(AppPage.id)
        .execution_options(populate_existing=True)
    ).all()


def _require_project(db: Session, project_id: uuid.UUID | None) -> None:
    if project_id is not None and db.get(Project, project_id) is None:
        raise RecordNotFoundException("Project", str(project_id))


def _shows(pages: Iterable[AppPage]) -> list[uuid.UUID | None]:
    """The project each page shows, or none: read before its row changes."""
    return [page.project_id for page in pages]
