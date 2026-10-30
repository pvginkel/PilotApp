"""The standing notification each member of a project should see (F94.1,
F94.2, F94.5; DB 224 to 226), derived from the record: what the reconcile
compares with what the membership last sent.

Every field stays within the bridge's limits (its README § Submit), so the
bridge refuses no derivation.
"""

import re
import uuid
from collections import Counter
from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Item, ItemKind, PlanTask, Project, ProjectMember, User, Work
from app.models import Session as AgentSession
from app.models.reference import NotificationPriority, ProjectState, SessionState
from app.services.project_service import PlanProgress, plan_progress
from app.services.timeline_service import WAIT, waiting

_UNTITLED = "New project"
"""A draft's title before its draft names it, as its tab reads it."""

_MAX_TITLE = 250
_MAX_MESSAGE = 4096
_CUT = "…"
_SEPARATOR = " · "

_MARKDOWN = re.compile(r"([\\`*_\[\]<>#+\-.!|~&)])")
"""The characters by which a text could open or close a Markdown construct in
the message, each escaped by a backslash (CommonMark §2.4)."""


@dataclass(frozen=True)
class StandingNotification:
    """A project's standing notification as one member should see it."""

    sequence_id: str
    """The project's id."""
    priority: NotificationPriority
    title: str
    """The project's name, plain text."""
    message: str
    """The status line, Markdown that reads as its words."""
    url: str


@dataclass(frozen=True)
class _Waiting:
    id: uuid.UUID
    kind: str
    title: str | None
    urgent: bool
    for_user_id: uuid.UUID | None


@dataclass(frozen=True)
class _Standing:
    """What of a project's standing reads the same for every member."""

    status_line: str
    running: list[str | None]
    waiting: list[_Waiting]
    waits: list[tuple[str, str | None]]
    """Each open wait's kind and title."""
    handles: dict[uuid.UUID, str]
    """The handle of each person a waiting item is `for`."""


class StandingNotificationService:
    def __init__(self, db: Session, base_url: str) -> None:
        self.db = db
        self.base_url = base_url

    def should_see(
        self, project: Project, memberships: Collection[ProjectMember]
    ) -> dict[int, StandingNotification | None]:
        """What each of `memberships`, every one of `project`, should see, by
        the membership's id: none, to be dismissed, unless the project is
        unarchived, the membership open and its person holds a token (DB
        224); a draft and a finished project are unarchived (F94)."""
        users = {
            user.id: user
            for user in self.db.scalars(
                select(User).where(
                    User.id.in_([membership.user_id for membership in memberships])
                )
            )
        }
        receiving = {
            membership.id
            for membership in memberships
            if not project.archived
            and membership.left_at is None
            and users[membership.user_id].notification_token is not None
        }
        standing = self._standing(project) if receiving else None
        return {
            membership.id: (
                None
                if standing is None or membership.id not in receiving
                else self._notification(project, standing, users[membership.user_id])
            )
            for membership in memberships
        }

    def _notification(
        self, project: Project, standing: _Standing, person: User
    ) -> StandingNotification:
        """F94.1's priority and text and F94.2's `url`, as `person` reads
        them: an item `for` nobody or for them waits on them, one `for`
        another counts in the text alone (DB 225)."""
        mine = [
            item
            for item in standing.waiting
            if item.for_user_id is None or item.for_user_id == person.id
        ]
        others = Counter(
            standing.handles[item.for_user_id]
            for item in standing.waiting
            if item.for_user_id is not None and item.for_user_id != person.id
        )
        if any(item.urgent for item in mine):
            priority = NotificationPriority.HIGH
        elif mine:
            priority = NotificationPriority.DEFAULT
        else:
            priority = NotificationPriority.MIN
        parts = [standing.status_line]
        if project.paused:
            parts.append("Paused")
        elif len(standing.running) == 1:
            parts.append(_named("Running", standing.running[0]))
        elif standing.running:
            parts.append(f"{len(standing.running)} running")
        if len(mine) == 1:
            parts.append(_named(f"{mine[0].kind} waiting", mine[0].title))
        elif mine:
            parts.append(f"{len(mine)} waiting")
        parts.extend(
            f"{count} waiting on {_plain(handle)}" for handle, count in others.items()
        )
        if len(standing.waits) == 1:
            kind, title = standing.waits[0]
            parts.append(
                f"{kind} open" if title is None else _named("Waiting for", title)
            )
        elif standing.waits:
            parts.append(f"{len(standing.waits)} waits open")
        timeline = f"{self.base_url}/projects/{project.id}"
        return StandingNotification(
            sequence_id=str(project.id),
            priority=priority,
            title=_cut(project.name or _UNTITLED, _MAX_TITLE),
            message=_cut_markdown(_SEPARATOR.join(parts), _MAX_MESSAGE),
            url=f"{timeline}/items/{mine[0].id}" if len(mine) == 1 else timeline,
        )

    def _standing(self, project: Project) -> _Standing:
        """The tab's status line (F1.2), what runs (F141.1) and what waits,
        F94.5's set and the open waits (F27.5), each in the timeline's
        order."""
        progress = plan_progress(
            self.db.scalars(
                select(PlanTask)
                .where(PlanTask.project_id == project.id, PlanTask.removed_at.is_(None))
                .order_by(PlanTask.position)
            )
        )
        running = list(
            self.db.scalars(
                select(Item.title)
                .join(Work, Work.id == Item.id)
                .join(AgentSession, AgentSession.id == Item.id)
                .where(
                    Item.project_id == project.id,
                    AgentSession.state_code == SessionState.RUNNING,
                )
                .order_by(Item.seq)
            )
        )
        items = [
            _Waiting(row.id, row.name, row.title, row.urgent, row.for_user_id)
            for row in self.db.execute(
                select(
                    Item.id, ItemKind.name, Item.title, Item.urgent, Item.for_user_id
                )
                .join(ItemKind, ItemKind.code == Item.kind_code)
                .where(Item.project_id == project.id, waiting())
                .order_by(Item.seq)
            )
        ]
        waits = [
            (row.name, row.title)
            for row in self.db.execute(
                select(ItemKind.name, Item.title)
                .join(ItemKind, ItemKind.code == Item.kind_code)
                .where(
                    Item.project_id == project.id,
                    Item.done_at.is_(None),
                    ItemKind.form == WAIT,
                )
                .order_by(Item.seq)
            )
        ]
        addressed = {item.for_user_id for item in items} - {None}
        handles = {
            row.id: row.handle
            for row in self.db.execute(
                select(User.id, User.handle).where(User.id.in_(addressed))
            )
        }
        return _Standing(
            status_line=_status_line(project, progress),
            running=running,
            waiting=items,
            waits=waits,
            handles=handles,
        )


def _status_line(project: Project, progress: PlanProgress) -> str:
    """The tab's status line (F1.2), its finished date aside: "Draft",
    "Finished", else the head's step reading (F2.2)."""
    match project.state_code:
        case ProjectState.DRAFT:
            return "Draft"
        case ProjectState.FINISHED:
            return "Finished"
        case ProjectState.OPEN:
            return _step_reading(progress)


def _step_reading(progress: PlanProgress) -> str:
    """The first step in progress by name, ", …" after it when more are;
    else "Not started", "N of M done" or "All steps done"."""
    if progress.in_progress:
        first = _plain(progress.in_progress[0])
        return f"{first}, …" if len(progress.in_progress) > 1 else first
    if progress.done == 0:
        return "Not started"
    if progress.done == progress.total:
        return "All steps done"
    return f"{progress.done} of {progress.total} done"


def _named(label: str, title: str | None) -> str:
    return label if title is None else f"{label}: {_plain(title)}"


def _plain(text: str) -> str:
    """`text` as Markdown that reads as its words."""
    return _MARKDOWN.sub(r"\\\1", text)


def _cut(text: str, limit: int) -> str:
    """`text`, cut to `limit` characters and ending in "…" when longer."""
    return text if len(text) <= limit else text[: limit - len(_CUT)] + _CUT


def _cut_markdown(text: str, limit: int) -> str:
    """Markdown `text` cut as `_cut` cuts it, never inside a backslash's
    escape."""
    if len(text) <= limit:
        return text
    kept = text[: limit - len(_CUT)]
    if (len(kept) - len(kept.rstrip("\\"))) % 2:
        kept = kept[:-1]
    return kept + _CUT
