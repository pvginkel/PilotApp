"""Work (DB §2.2), the subtype of Item and of Session.

`work` is the extension table keyed by the id a Work's Item and Session share
(DB §7.3).
"""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.reference import WORK_TRIGGER, WorkTrigger


class Work(db.Model):  # type: ignore[name-defined]
    """One run of a session Pilot started or resumed, shown on the timeline.

    `project_id` and `session_kind_code` are its Item's and its Session's,
    carried so that the keys reach one Project by both paths (DB assertion
    166) and the checks read the Session Kind (DB 149, 167).

    `retried_by_id` is the job a person's Retry of this failed or stopped
    job placed, set once and never changed: a recursive list, a job retried
    at most once and a retry retrying one job.
    """

    __tablename__ = "work"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "id"], ["items.project_id", "items.id"]),
        ForeignKeyConstraint(
            ["project_id", "id", "session_kind_code"],
            ["sessions.project_id", "sessions.id", "sessions.kind_code"],
        ),
        # The trigger Item is of the Work's Project (DB assertion 166).
        ForeignKeyConstraint(
            ["project_id", "trigger_item_id"], ["items.project_id", "items.id"]
        ),
        # A Work is a `work` or `job` Session; a Chat's never is (DB 149).
        CheckConstraint(
            "session_kind_code IN ('work', 'job')", name="ck_work_session_kind"
        ),
        # A job has a Work Trigger, a worker's run none (DB assertion 167).
        CheckConstraint(
            "(session_kind_code = 'job') = (trigger_code IS NOT NULL)",
            name="ck_work_trigger",
        ),
        CheckConstraint("trigger_item_id <> id", name="ck_work_trigger_item"),
        # A job runs in the store, placed in no repository (DB §2.2).
        CheckConstraint(
            "session_kind_code = 'work' OR repo IS NULL", name="ck_work_repo"
        ),
        # What a retry's key references, so the job it retries is of its
        # Project and its Session Kind.
        UniqueConstraint("project_id", "id", "session_kind_code"),
        ForeignKeyConstraint(
            ["project_id", "retried_by_id", "session_kind_code"],
            ["work.project_id", "work.id", "work.session_kind_code"],
        ),
        # Only a job is retried, by another job.
        CheckConstraint(
            "retried_by_id IS NULL"
            " OR (session_kind_code = 'job' AND retried_by_id <> id)",
            name="ck_work_retried_by",
        ),
        # A retry retries one job.
        Index("uq_work_retried_by_id", "retried_by_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    project_id: Mapped[uuid.UUID]
    session_kind_code: Mapped[str] = mapped_column(Text)
    trigger_code: Mapped[WorkTrigger | None] = mapped_column(WORK_TRIGGER)
    trigger_item_id: Mapped[uuid.UUID | None]
    repo: Mapped[str | None] = mapped_column(Text)
    autopilot: Mapped[bool] = mapped_column(Boolean)
    retried_by_id: Mapped[uuid.UUID | None]
