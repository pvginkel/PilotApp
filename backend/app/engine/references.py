"""The rows of the reference tables the reads look up (DB §2.4), kept for
the process's life, each read on its code's first lookup.

A revision is the one place a reference row is added or changed
(`app/models/reference.py`), and the backend starts once its revision is
applied (the init container `migrate`). A process keeps each row as it first
read it, and finds a row a later revision added on its first lookup.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.reference import ConfirmationReason, DoneCause, ItemKind


@dataclass(frozen=True)
class Reason:
    """A confirmation reason as a block names it in `because`."""

    code: str
    name: str
    description: str
    asks_under_autopilot: bool


class References:
    """Safe across threads: a code two threads look up at once is read by
    each, and the values either keeps are the same."""

    def __init__(self) -> None:
        self._forms: dict[str, str] = {}
        self._undo_offered: dict[str, bool] = {}
        self._reasons: dict[str, Reason] = {}

    def form(self, db: Session, kind_code: str) -> str:
        """Which subtype an Item of the kind is."""
        if kind_code not in self._forms:
            self._forms[kind_code] = db.get_one(ItemKind, kind_code).form
        return self._forms[kind_code]

    def undo_offered(self, db: Session, done_cause_code: str) -> bool:
        """Whether an item done by the cause offers undo."""
        if done_cause_code not in self._undo_offered:
            cause = db.get_one(DoneCause, done_cause_code)
            self._undo_offered[done_cause_code] = cause.undo_offered
        return self._undo_offered[done_cause_code]

    def reason(self, db: Session, code: str) -> Reason:
        if code not in self._reasons:
            row = db.get_one(ConfirmationReason, code)
            self._reasons[code] = Reason(
                code=row.code,
                name=row.name,
                description=row.description,
                asks_under_autopilot=row.asks_under_autopilot,
            )
        return self._reasons[code]
