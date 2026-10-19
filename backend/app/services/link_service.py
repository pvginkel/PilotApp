"""What links in text (F91, F93) that the record holds."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Environment


class LinkService:
    """The record's half of the links: the environments text names."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def environments(self) -> list[Environment]:
        """Every environment of the record, by name, then id."""
        return list(
            self.db.scalars(
                select(Environment).order_by(Environment.name, Environment.id)
            )
        )
