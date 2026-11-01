"""The store's update in a test: its hold made and lifted on the record
(F144; DB Store Update, assertions 276 and 282)."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import StoreUpdate


def hold(db: Session) -> StoreUpdate:
    """A Store Update made now, unlifted: the hold on the store's work."""
    made = StoreUpdate(made_at=datetime.now(UTC))
    db.add(made)
    db.flush()
    return made


def lift(db: Session, update: StoreUpdate) -> None:
    """The update lifted now, its hold gone."""
    update.lifted_at = datetime.now(UTC)
    db.flush()
