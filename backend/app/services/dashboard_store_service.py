"""What the dashboard stores (F155; DB §2.10): the saved views, the quick
filters and the custom ratios everyone shares, and a person's favourites.

The system views are the system's: no User changes one but by its star (DB
601). Pilot's own name nothing of a workflow and are what this release's code
holds (`app/dashboard/views.py`): each deploy loads them after the revisions
(`post_migration_hook`), as does the load of the invented record. A load of
an Origin's views leaves them the entries it is given, matched by key: an
entry a row has changes that row in place, its stars kept; one no row has is
added; a row whose key the entries no longer hold is removed, its stars with
it (DB 604).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.dashboard.views import VIEWS, SystemView
from app.models import SavedView
from app.models.reference import Origin


@dataclass(frozen=True)
class Loaded:
    """What a load of system views wrote: the views it added, changed and
    removed."""

    added: int
    changed: int
    removed: int


class DashboardStoreService:
    """The rows of what the dashboard stores."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def ship(self, now: datetime | None = None) -> Loaded:
        """Pilot's own system views made what this release holds."""
        return self.load_views(Origin.PILOT, VIEWS, now or datetime.now(UTC))

    def load_views(
        self, origin: Origin, views: Sequence[SystemView], now: datetime
    ) -> Loaded:
        """The system views of `origin` made `views`, one per key, by key; a
        view added or changed saved at `now`."""
        held = {
            row.key: row
            for row in self.db.scalars(
                select(SavedView).where(SavedView.origin_code == origin)
            )
        }
        keys = {view.key for view in views}
        gone = [row.id for key, row in held.items() if key not in keys]
        if gone:
            # Before the others are written, so that a name a removed view
            # held is free for one of them.
            self.db.execute(delete(SavedView).where(SavedView.id.in_(gone)))
        added = changed = 0
        for view in views:
            row = held.get(view.key)
            if row is None:
                self.db.add(
                    SavedView(
                        origin_code=origin,
                        key=view.key,
                        name=view.name,
                        state=view.state,
                        note=view.note,
                        saved_at=now,
                    )
                )
                added += 1
            elif (row.name, row.state, row.note) != (view.name, view.state, view.note):
                row.name, row.state, row.note = view.name, view.state, view.note
                row.saved_at = now
                changed += 1
        self.db.flush()
        return Loaded(added, changed, len(gone))

    def saved_views(self) -> list[SavedView]:
        """Every Saved View, the system views before those a person saved,
        each list by name."""
        return list(
            self.db.scalars(
                select(SavedView).order_by(
                    SavedView.system.desc(), SavedView.name, SavedView.id
                )
            )
        )
