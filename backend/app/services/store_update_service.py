"""The operator's update of the store while Pilot runs (F144; DB Store Update,
decision 68, assertions 276, 279 and 280).

`update-store` makes an update, the hold on the store's work while it is
unlifted, and asks its lift. Both write the row and nothing else: no listener
is told, and the server takes the row up from the record. The jobs an update
stopped are derived from their stop, never linked (`stopped_by`).
"""

from datetime import UTC, datetime

from sqlalchemy import ColumnElement, and_, exists, or_, select, text
from sqlalchemy.orm import Session, aliased

from app.engine.record import FINISHED
from app.exceptions import InvalidOperationException
from app.models import Item, StoreUpdate, User
from app.models import Session as AgentSession
from app.models.reference import UserKind
from app.services.start_gate import JOB_KIND


def utc_time(at: datetime) -> str:
    """A Store Update's time as the command prints it and its refusals name it."""
    return at.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def unlifted(db: Session) -> StoreUpdate | None:
    """The Store Update not lifted yet, the hold, if one stands (DB 276)."""
    return db.scalars(
        select(StoreUpdate).where(StoreUpdate.lifted_at.is_(None))
    ).one_or_none()


def stopped_by(update: StoreUpdate) -> ColumnElement[bool]:
    """Whether a Session is a job the update stopped (DB 280): stopped by
    Pilot at or after its `made_at`, and before its `lifted_at` once it has
    one, its Item not closed by a Finish at its stop."""
    stopped = AgentSession.stopped_at >= update.made_at
    if update.lifted_at is not None:
        stopped = and_(stopped, AgentSession.stopped_at < update.lifted_at)
    return and_(_stopped_by_pilot(), stopped)


def stopped_for_update() -> ColumnElement[bool]:
    """Whether a Session is a job a Store Update stopped (DB 280), any update,
    lifted or not: its stop's cause."""
    return and_(
        _stopped_by_pilot(),
        exists().where(
            StoreUpdate.made_at <= AgentSession.stopped_at,
            or_(
                StoreUpdate.lifted_at.is_(None),
                AgentSession.stopped_at < StoreUpdate.lifted_at,
            ),
        ),
    )


def stopped_for_unlifted(session: type[AgentSession]) -> ColumnElement[bool]:
    """Whether the Session `session`, an alias, is a job the Store Update not
    lifted yet stopped (DB 280): one its lift retries unless a Work retries it
    first (DB 281)."""
    update = aliased(StoreUpdate)
    return and_(
        _stopped_by_pilot(session),
        exists().where(
            update.lifted_at.is_(None), update.made_at <= session.stopped_at
        ),
    )


def _stopped_by_pilot(
    session: type[AgentSession] = AgentSession,
) -> ColumnElement[bool]:
    """A job's Session stopped by Pilot, but at a Finish, which closes its
    Item at the instant it stops it (DB 280)."""
    # An alias of its own, so that a caller's select may join Item too.
    line = aliased(Item)
    return and_(
        session.kind_code == JOB_KIND,
        session.stopped_by_user_id.in_(
            select(User.id).where(User.kind_code == UserKind.AGENT)
        ),
        ~exists().where(
            line.id == session.id,
            line.done_cause_code == FINISHED,
            line.done_at == session.stopped_at,
        ),
    )


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
