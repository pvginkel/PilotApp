"""The operator's update of the store while Pilot runs (F144; DB Store Update,
decision 68, assertions 276 and 279).

`update-store` makes an update, the hold on the store's work while it is
unlifted, and asks its lift. Both write the row and nothing else: no listener
is told, and the server takes the row up from the record.
"""

from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.exceptions import InvalidOperationException
from app.models import StoreUpdate


def utc_time(at: datetime) -> str:
    """A Store Update's time as the command prints it and its refusals name it."""
    return at.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def unlifted(db: Session) -> StoreUpdate | None:
    """The Store Update not lifted yet, the hold, if one stands (DB 276)."""
    return db.scalars(
        select(StoreUpdate).where(StoreUpdate.lifted_at.is_(None))
    ).one_or_none()


class StoreUpdateService:
    """The updates the operator makes, and the lifts they ask."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def make(self) -> StoreUpdate:
        """A new update, its hold standing from its commit.

        Raises:
            InvalidOperationException: an update is not lifted yet.
        """
        # One make at a time, so that a second one is refused here rather
        # than by the unique index at its commit (DB 276).
        self.db.execute(text("LOCK TABLE store_updates IN SHARE ROW EXCLUSIVE MODE"))
        standing = unlifted(self.db)
        if standing is not None:
            raise InvalidOperationException(
                "update the store",
                f"an update is under way since {utc_time(standing.made_at)}",
            )
        made = StoreUpdate(made_at=datetime.now(UTC))
        self.db.add(made)
        self.db.flush()
        return made

    def request_lift(self) -> StoreUpdate:
        """The update not lifted yet, its lift asked: `lift_requested_at`
        written once, a second ask leaving the first's (DB 279).

        Raises:
            InvalidOperationException: no update is under way.
        """
        standing = self.db.scalars(
            select(StoreUpdate).where(StoreUpdate.lifted_at.is_(None)).with_for_update()
        ).one_or_none()
        if standing is None:
            raise InvalidOperationException(
                "lift the store's update", "no update is under way"
            )
        if standing.lift_requested_at is None:
            standing.lift_requested_at = datetime.now(UTC)
            self.db.flush()
        return standing

    def get(self, update_id: int) -> StoreUpdate:
        """The update, as its row stands now."""
        return self.db.get_one(StoreUpdate, update_id)
