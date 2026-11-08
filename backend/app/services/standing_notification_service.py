"""The notification each member of a project should see (F94.1, F94.2, F94.5;
DB 224 to 226; D145), derived from the record: the items that wait on them,
and the text, title and `url` a push of it carries, which the reconcile
compares with what they were shown (`NotificationReconcileService`).
"""

import uuid
from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.paths import folder
from app.models import Item, ItemKind, Project, ProjectMember
from app.services.timeline_service import waiting
from app.services.web_push import Push
from app.services.working_on import Reading

_UNTITLED = "New project"
"""A draft's title before its draft names it, as its tab reads it."""

_MAX_TITLE = 250
"""The most of a title: a push's payload is cut in its body alone
(`Push.payload`), which the title leaves room for."""
_CUT = "…"


@dataclass(frozen=True)
class StandingNotification:
    """A project's notification as one member should see it."""

    tag: str
    """The project's id, under which a device shows it."""
    title: str
    """The project's name."""
    body: str
    """The items that wait on the member: the latest placed, by its title or
    its kind's name, then ", +<n>" counting the others; plain text."""
    url: str
    items: frozenset[uuid.UUID]
    """Every item that waits on the member, each named or counted in the
    text."""

    def push(self, *, alert: bool) -> Push:
        """The notification as a push: renotifying when it alerts, else
        replacing what shows under its `tag` silently."""
        return Push(
            title=self.title,
            body=self.body,
            tag=self.tag,
            url=self.url,
            renotify=alert,
        )


@dataclass(frozen=True)
class _Waiting:
    id: uuid.UUID
    kind: str
    title: str | None
    for_user_id: uuid.UUID | None


class StandingNotificationService:
    def __init__(self, db: Session, base_url: str) -> None:
        self.db = db
        self.base_url = base_url

    def should_see(
        self, project: Project, memberships: Collection[ProjectMember]
    ) -> dict[int, StandingNotification | None]:
        """What each of `memberships`, every one of `project`, should see, by
        the membership's id: none unless the project is unarchived, the
        membership open and an item waits on its person (DB 224); a draft and
        a finished project are unarchived (F94)."""
        receiving = {
            membership.id
            for membership in memberships
            if not project.archived and membership.left_at is None
        }
        items = self._waiting(project) if receiving else []
        return {
            membership.id: (
                self._notification(project, items, membership.user_id)
                if membership.id in receiving
                else None
            )
            for membership in memberships
        }

    def _notification(
        self, project: Project, items: list[_Waiting], person_id: uuid.UUID
    ) -> StandingNotification | None:
        """F94.1's text and F94.2's `url`, as the person reads them, or none
        while nothing waits on them: an item `for` nobody or for them waits on
        them, one `for` another is not theirs (DB 225). The `url` names the
        project by its address, the name its pages' URLs take."""
        mine = [
            item
            for item in items
            if item.for_user_id is None or item.for_user_id == person_id
        ]
        if not mine:
            return None
        latest = mine[0]
        ask = latest.kind if latest.title is None else latest.title
        timeline = f"{self.base_url}/projects/{folder(project)}"
        return StandingNotification(
            tag=str(project.id),
            title=_cut(project.name or _UNTITLED, _MAX_TITLE),
            body=ask if len(mine) == 1 else f"{ask}, +{len(mine) - 1}",
            url=f"{timeline}/items/{latest.id}" if len(mine) == 1 else timeline,
            items=frozenset(item.id for item in mine),
        )

    def _waiting(self, project: Project) -> list[_Waiting]:
        """F94.5's set, the latest placed first."""
        return [
            _Waiting(row.id, row.name, row.title, row.for_user_id)
            for row in self.db.execute(
                select(Item.id, ItemKind.name, Item.title, Item.for_user_id)
                .join(ItemKind, ItemKind.code == Item.kind_code)
                .where(Item.project_id == project.id, waiting(Reading(self.db)))
                .order_by(Item.seq.desc())
            )
        ]


def _cut(text: str, limit: int) -> str:
    """`text`, cut to `limit` characters and ending in "…" when longer."""
    return text if len(text) <= limit else text[: limit - len(_CUT)] + _CUT
