"""The store's update in a test: its hold made and lifted on the record, and
the jobs it stops (F144; DB Store Update, assertions 276, 280 and 282)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Project, StoreUpdate, User
from app.models import Session as AgentSession
from app.models.reference import SessionState, UserKind, WorkTrigger
from app.services.container import ServiceContainer


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


def pilot(db: Session) -> User:
    """Pilot, the record's agent, who the store's update stops by."""
    return db.scalars(select(User).where(User.kind_code == UserKind.AGENT)).one()


def stopped_job(
    container: ServiceContainer,
    db: Session,
    project: Project,
    at: datetime,
    *,
    by: User | None = None,
    title: str = "Setting up the project",
) -> AgentSession:
    """A job of the project's in the store, made now, its one turn ended at
    its stop at `at`: by Pilot, as the store's update stops it, unless `by`."""
    job = AgentSession(
        project_id=project.id,
        kind_code="job",
        cwd="/work/PilotProjects",
        token_hash=uuid.uuid4().hex,
        state_code=SessionState.STOPPED,
        created_at=datetime.now(UTC),
        stopped_at=at,
        stopped_by_user_id=(by or pilot(db)).id,
        turns=1,
        turn_started_at=at,
        turn_ended_at=at,
    )
    db.add(job)
    db.flush()
    container.record_service().place_work(
        project, job, title, trigger=WorkTrigger.SETUP
    )
    return job
