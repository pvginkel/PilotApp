"""A debrief's notice placed as the server places one: a worker's run whose
debrief completes, done at its turn's end (DB 609)."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import Item, Project, Work
from app.services.container import ServiceContainer

DEBRIEF = "It went well, if slowly: the second review was worth it."
"""A stage session's debrief, invented."""


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


def placed_notice(
    db: DbSession, container: ServiceContainer, project: Project, run: models.Session
) -> Item:
    """The debrief's notice of `run`, a worker's run placed as a work item,
    its debrief completing and naming no subject: placed at its turn's end."""
    give_debrief(db, run)
    container.record_service().work_done(run.id, datetime.now(UTC))
    return db.scalars(
        select(Item).where(
            Item.project_id == project.id, Item.kind_code == "debrief_notice"
        )
    ).one()
