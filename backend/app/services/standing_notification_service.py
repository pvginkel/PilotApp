"""The standing notification each member of a project should see (F94.1,
F94.2, F94.5; DB 224 to 226), derived from the record: what the reconcile
compares with what the membership last sent.

Every field stays within the bridge's limits (its README § Submit), so the
bridge refuses no derivation.
"""

import re
import uuid
from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Item, ItemKind, Project, ProjectMember, User
from app.services.timeline_service import waiting

_UNTITLED = "New project"
"""A draft's title before its draft names it, as its tab reads it."""

_MAX_TITLE = 250
_MAX_MESSAGE = 4096
_CUT = "…"

_MARKDOWN = re.compile(r"([\\`*_\[\]<>#+\-.!|~&)])")
"""The characters by which a text could open or close a Markdown construct in
the message, each escaped by a backslash (CommonMark §2.4)."""


@dataclass(frozen=True)
class StandingNotification:
    """A project's standing notification as one member should see it."""

    sequence_id: str
    """The project's id."""
    title: str
    """The project's name, plain text."""
    message: str
    """What waits on the member, Markdown that reads as its words."""
    url: str


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
        the membership's id: none, to be dismissed, unless the project is
        unarchived, the membership open, its person holds a token (DB 224)
        and an item waits on them (F94.1); a draft and a finished project are
        unarchived (F94)."""
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
        items = self._waiting(project) if receiving else []
        return {
            membership.id: (
                self._notification(project, items, users[membership.user_id])
                if membership.id in receiving
                else None
            )
            for membership in memberships
        }

    def _notification(
        self, project: Project, items: list[_Waiting], person: User
    ) -> StandingNotification | None:
        """F94.1's text and F94.2's `url`, as `person` reads them, or none
        while nothing waits on them: an item `for` nobody or for them waits on
        them, one `for` another is not theirs (DB 225). The text is the
        latest of theirs, ", +<n>" after it counting the others."""
        mine = [
            item
            for item in items
            if item.for_user_id is None or item.for_user_id == person.id
        ]
        if not mine:
            return None
        latest = mine[0]
        ask = latest.kind if latest.title is None else _plain(latest.title)
        timeline = f"{self.base_url}/projects/{project.id}"
        return StandingNotification(
            sequence_id=str(project.id),
            title=_cut(project.name or _UNTITLED, _MAX_TITLE),
            message=_cut_markdown(
                ask if len(mine) == 1 else f"{ask}, +{len(mine) - 1}", _MAX_MESSAGE
            ),
            url=f"{timeline}/items/{latest.id}" if len(mine) == 1 else timeline,
        )

    def _waiting(self, project: Project) -> list[_Waiting]:
        """F94.5's set, the latest placed first."""
        return [
            _Waiting(row.id, row.name, row.title, row.for_user_id)
            for row in self.db.execute(
                select(Item.id, ItemKind.name, Item.title, Item.for_user_id)
                .join(ItemKind, ItemKind.code == Item.kind_code)
                .where(Item.project_id == project.id, waiting())
                .order_by(Item.seq.desc())
            )
        ]


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
