"""The conditions that hold all work, which the gold bar shows (UC *The gold
bar*; DB Condition): the controller unreachable (F125; design 2 §13.4), and the
week's and the five-hour usage halts (F135.7; `UsageHalts`).

When one turns on or off, its listeners hear of it, the alarms among them, and
every person's connections at once, as one event carrying the conditions that
hold then (SSE-2): the outage's turn as its listener, a halt's as the usage
watcher tells it. Only the process that holds a connection delivers to it,
and the outage is each process's own.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.models.reference import UsageWindow, UserKind
from app.schemas.conditions import ConditionCode, ConditionSchema, ConditionsSchema
from app.services.controller_outage import ControllerOutage
from app.services.sse_connection_manager import SSEConnectionManager, Target
from app.services.usage_halts import UsageHalts

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

EVENT_NAME = "conditions_changed"
"""The SSE event the conditions travel as, `ConditionsSchema`'s shape."""

type ConditionListener = Callable[[], None]

HALT_CODES = {
    UsageWindow.SEVEN_DAY: ConditionCode.WEEK_HALT,
    UsageWindow.FIVE_HOUR: ConditionCode.FIVE_HOUR_HALT,
}


class ConditionService:
    """The conditions that hold, read and told; a listener of the outage from
    its construction on."""

    def __init__(
        self,
        container: "ServiceContainer",
        controller_outage: ControllerOutage,
        usage_halts: UsageHalts,
        sse_connection_manager: SSEConnectionManager,
    ) -> None:
        self._container = container
        self._outage = controller_outage
        self._halts = usage_halts
        self._manager = sse_connection_manager
        self._listeners: tuple[ConditionListener, ...] = ()
        controller_outage.subscribe(self.tell)

    def conditions(self) -> ConditionsSchema:
        """The conditions that hold now."""
        with self._open_session() as db:
            return self._conditions(db)

    def subscribe(self, listener: ConditionListener) -> None:
        """Call `listener` at every `tell()`, in the thread that tells, which
        may be inside another transaction."""
        self._listeners = (*self._listeners, listener)

    def tell(self) -> None:
        """Tell every listener that the conditions turned, then send those
        that hold now to every person's connections."""
        for listener in self._listeners:
            listener()
        with self._open_session() as db:
            payload = self._conditions(db).model_dump(mode="json")
            subjects = db.scalars(
                select(User.subject)
                .where(User.kind_code == UserKind.PERSON)
                .order_by(User.subject)
            ).all()
        for subject in subjects:
            # A person's row has a subject (`ck_users_person`).
            assert subject is not None
            self._manager.send_event(
                Target.subject(subject), payload, EVENT_NAME, "conditions"
            )

    def _conditions(self, db: Session) -> ConditionsSchema:
        since = self._outage.since
        held = (
            []
            if since is None
            else [
                ConditionSchema(
                    code=ConditionCode.OUTAGE, since=since, share=None, taken_at=None
                )
            ]
        )
        held += [
            ConditionSchema(
                code=HALT_CODES[halt.window],
                since=halt.since,
                share=halt.share,
                taken_at=halt.taken_at,
            )
            for halt in self._halts.halts(db)
        ]
        return ConditionsSchema(conditions=held)

    def _open_session(self) -> Session:
        # Not `scoped_session`: the outage turns inside other transactions,
        # a request's among them, whose session is the same provider.
        session: Session = self._container.session_maker()()
        return session
