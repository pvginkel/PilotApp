"""A debrief's notice placed as the server places one: a worker's run whose
debrief completes, done at its turn's end, and the job after its turn, the
pass, ended (DB 609)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import Item, Project, Work
from app.models.reference import SessionState, WorkTrigger
from app.services.container import ServiceContainer

DEBRIEF = "It went well, if slowly: the second review was worth it."
"""A stage session's debrief, invented."""

FIGURES = "Phases: 8. Rounds: 11. Consults: 2. Duration: 4h 12m. Cost: $31.40."
"""The loop's figures as a workflow gives them, invented."""


def give_debrief(
    db: DbSession,
    run: models.Session,
    *,
    subject: str | None = None,
    completes: bool = True,
) -> Work:
    """The debrief of `run`, a worker's run placed as a work item, given as
    its session's call stores it, with `subject` and whether it
    `completes` it."""
    work = db.get_one(Work, run.id)
    work.debrief = DEBRIEF
    work.debrief_subject = subject
    work.debrief_completes = completes
    db.flush()
    return work


def pass_after(
    db: DbSession,
    container: ServiceContainer,
    project: Project,
    run: models.Session,
    state: SessionState = SessionState.IDLE,
) -> models.Session:
    """The job after the turn of `run`, a worker's done run: the pass, placed
    as the run's end places it, its Session in `state`."""
    job = models.Session(
        project_id=project.id,
        environment_id=run.environment_id,
        kind_code="job",
        cwd="/work/PilotProjects",
        token_hash=uuid.uuid4().hex * 2,
        state_code=state,
    )
    db.add(job)
    db.flush()
    container.record_service().place_work(
        project,
        job,
        "Pre-ruling",
        trigger=WorkTrigger.WORKER_TURN_ENDED,
        trigger_item_id=run.id,
    )
    return job


def pass_ended(
    db: DbSession,
    container: ServiceContainer,
    project: Project,
    run: models.Session,
    at: datetime | None = None,
) -> models.Session:
    """The pass after the turn of `run`, a worker's done run, placed and
    ended well at `at`, now where none is given: its work item done and its
    end's hook run, which places the debrief's notice the run's debrief
    owes."""
    job = pass_after(db, container, project, run)
    container.record_service().work_done(job.id, at or datetime.now(UTC))
    container.clarification_service().pass_ended(job)
    return job


def placed_notice(
    db: DbSession, container: ServiceContainer, project: Project, run: models.Session
) -> Item:
    """The debrief's notice of `run`, a worker's run placed as a work item,
    its debrief completing and naming no subject: placed at the end of the
    pass after its turn."""
    give_debrief(db, run)
    container.record_service().work_done(run.id, datetime.now(UTC))
    pass_ended(db, container, project, run)
    return db.scalars(
        select(Item).where(
            Item.project_id == project.id, Item.kind_code == "debrief_notice"
        )
    ).one()
