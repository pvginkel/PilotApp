"""The collector's walks as Pilot keeps them (F152.14, F154.8): the moment
each ended, the event one raises where it wrote a row, and the readiness
check that reads the latest.

The collector tells the server that a walk ended, after its last publication,
whether it published or not. A walk wrote a row where a Transcript was
collected since the walk before it ended, every publication Pilot takes
writing its Transcript's row; such a walk's end is told to every person's
connections once its Walk has committed, and any other to no one.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.app_config import AppSettings
from app.models import Transcript, User, Walk
from app.models.reference import UserKind
from app.schemas.walk import CollectionChangedSchema
from app.services.health_service import CheckResult, CheckStatus
from app.services.sse_connection_manager import SSEConnectionManager, Target
from app.utils.after_commit import after_commit

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

EVENT_NAME = "collection_changed"
"""The SSE event a walk that wrote a row raises, `CollectionChangedSchema`'s
shape."""

COLLECTOR_CHECK = "collector"
"""The readiness check's name in readyz."""

WALKS_KEPT = 20
"""How many Walks the record keeps, the latest: nothing reads one before the
latest (DB decision 79.19)."""

_CHECK_TIMEOUT_MS = 2000
"""The readiness check's cap on its one read (READY-3)."""


@dataclass(frozen=True)
class WalkEnd:
    """A walk's end as the server took it."""

    ended_at: datetime
    announced: bool
    """Whether the walk wrote a row, and its event is sent at the commit."""


def latest_walk_end(db: Session) -> datetime | None:
    """When the collector's latest walk ended: how fresh the record's facts
    of the transcripts are. None before a first walk."""
    return db.scalar(select(func.max(Walk.ended_at)))


class WalkService:
    """Takes a walk's end on the caller's transaction."""

    def __init__(self, db: Session, sse_connection_manager: SSEConnectionManager):
        self.db = db
        self._manager = sse_connection_manager

    def end(self) -> WalkEnd:
        """Stamp a Walk now, keep the latest `WALKS_KEPT`, and, where a
        Transcript was collected since the walk before ended, send one event
        to every person's connections after the commit."""
        before = latest_walk_end(self.db)
        collected = select(Transcript.id)
        if before is not None:
            collected = collected.where(Transcript.collected_at >= before)
        wrote = bool(self.db.scalar(select(collected.exists())))

        ended_at = datetime.now(UTC)
        self.db.add(Walk(ended_at=ended_at))
        self.db.flush()
        kept = (
            select(Walk.id)
            .order_by(Walk.ended_at.desc(), Walk.id.desc())
            .limit(WALKS_KEPT)
        )
        self.db.execute(delete(Walk).where(Walk.id.not_in(kept)))

        if wrote:
            subjects = self.db.scalars(
                select(User.subject)
                .where(User.kind_code == UserKind.PERSON)
                .order_by(User.subject)
            ).all()
            payload = CollectionChangedSchema(as_of=ended_at).model_dump(mode="json")
            after_commit(partial(self._tell, tuple(subjects), payload))
        return WalkEnd(ended_at=ended_at, announced=wrote)

    def _tell(self, subjects: tuple[str | None, ...], payload: dict[str, Any]) -> None:
        for subject in subjects:
            # A person's row has a subject (`ck_users_person`).
            assert subject is not None
            self._manager.send_event(
                Target.subject(subject), payload, EVENT_NAME, "collection"
            )


def collector_readiness(container: "ServiceContainer") -> CheckResult:
    """Readiness check: the collector as its walks' ends show it. `disabled`
    while `COLLECTOR_TOKEN` is empty; an error before a first walk, and once
    the latest ended more than two of the walk's intervals ago."""
    app_settings: AppSettings = container.app_config()
    if not app_settings.collector_token:
        return CheckResult(CheckStatus.DISABLED, "COLLECTOR_TOKEN is empty")
    with container.session_maker()() as db:
        db.execute(text(f"SET LOCAL statement_timeout = {_CHECK_TIMEOUT_MS}"))
        latest = latest_walk_end(db)
    if latest is None:
        return CheckResult(CheckStatus.ERROR, "no walk of the collector's has ended")
    ended = f"the collector's latest walk ended at {latest.astimezone(UTC).isoformat()}"
    allowed = 2 * app_settings.collector_walk_interval_seconds
    if datetime.now(UTC) - latest > timedelta(seconds=allowed):
        return CheckResult(
            CheckStatus.ERROR, f"{ended}, more than {allowed:g} s before this check"
        )
    return CheckResult(CheckStatus.OK, ended)


def register_collector_check(container: "ServiceContainer") -> None:
    """Register the readiness check `collector`, once, at the server's start
    (READY-1). Not critical (READY-2): Pilot serves its record without a
    collector, and a 503 takes the backend out of the Service the collector's
    own calls come through."""
    container.health_service().register_check(
        COLLECTOR_CHECK, partial(collector_readiness, container), critical=False
    )
