"""A person's overrule of the week's usage halt (F135.2; DB Quota Overrule,
decision 66, assertions 179 and 267).

An overrule is made only while the week's halt holds, which no holding
overrule allows, and only as the halt offers it: the allowance under the
second limit, its target written when made; run-out at or over it, short of
the wall, where none is offered (D101). The
server ends it (`UsageHalts.end_spent`); once made, the watcher lifts the
halt and tells of it.
"""

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.exceptions import InvalidOperationException
from app.models import QuotaOverrule
from app.models.reference import OverruleKind, UsageWindow
from app.services.auth_service import AuthContext
from app.services.people_service import PeopleService
from app.services.usage_halts import UsageHalts, UsageWatcher, overrule
from app.utils.after_commit import after_commit

_OPERATIONS = {
    OverruleKind.ALLOWANCE: "add the week's allowance",
    OverruleKind.RUN_OUT: "run out the week's quota",
}

_NOT_OFFERED = {
    OverruleKind.ALLOWANCE: (
        "the week's share is at the second limit, where only run-out is offered"
    ),
    OverruleKind.RUN_OUT: (
        "the week's share is under the second limit, where the allowance is offered"
    ),
}


class QuotaOverruleService:
    """The overrules people make."""

    def __init__(
        self,
        db: Session,
        people_service: PeopleService,
        usage_halts: UsageHalts,
        usage_watcher: UsageWatcher,
    ) -> None:
        self.db = db
        self.people_service = people_service
        self.usage_halts = usage_halts
        self.usage_watcher = usage_watcher

    def make(self, auth: AuthContext, kind: OverruleKind) -> QuotaOverrule:
        """The caller's overrule of the week's halt, of the kind it offers
        now; once committed, the halt lifts and the conditions are told.

        Raises:
            InvalidOperationException: the caller has not chosen a handle, an
                overrule holds already, the week's halt does not hold, the
                week's share is at the wall, where it offers none (D101), or it
                offers the other kind.
        """
        operation = _OPERATIONS[kind]
        person = self.people_service.require_person(auth, operation)
        # One make at a time, and no reading recorded from the read of the
        # offer to the commit (DB 267; `UsageHalts._spent`).
        self.db.execute(text("LOCK TABLE quota_overrules IN SHARE ROW EXCLUSIVE MODE"))
        self.db.execute(text("LOCK TABLE usage_readings IN SHARE MODE"))
        if overrule(self.db) is not None:
            raise InvalidOperationException(operation, "an overrule holds already")
        offer = self.usage_halts.offer(self.db)
        if offer is None:
            raise InvalidOperationException(
                operation,
                "the week's share is at the wall, where no overrule is offered"
                if UsageWindow.SEVEN_DAY in self.usage_halts.holding(self.db)
                else "the week's halt does not hold",
            )
        if offer.kind is not kind:
            raise InvalidOperationException(operation, _NOT_OFFERED[kind])
        made = QuotaOverrule(
            kind_code=kind,
            made_by_user_id=person.id,
            made_at=datetime.now(UTC),
            target=offer.target,
        )
        self.db.add(made)
        self.db.flush()
        after_commit(self.usage_watcher.overruled)
        return made
