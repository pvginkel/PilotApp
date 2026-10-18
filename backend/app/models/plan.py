"""Plan Task, Plan Note (DB §2.1) and Plan Note Reference (DB §2.2).

The plan's rows; `plan.json` is their file.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.reference import TASK_STATUS, TaskStatus


class PlanTask(db.Model):  # type: ignore[name-defined]
    """A task of a Project's plan; never deleted, a removed one keeps its row."""

    __tablename__ = "plan_tasks"
    __table_args__ = (
        # A removed task loses its position (DB assertion 173).
        CheckConstraint(
            "(position IS NULL) = (removed_at IS NOT NULL)",
            name="ck_plan_tasks_position",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id"), primary_key=True
    )
    task_id: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    status_code: Mapped[TaskStatus] = mapped_column(TASK_STATUS)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PlanNote(db.Model):  # type: ignore[name-defined]
    """A note the agent keeps on a Plan Task, or on the plan itself.

    Never deleted: a struck note keeps its row with `deleted_at`. Its Plan
    Task is of its own Project, the key carrying `project_id` once (DB
    assertion 211).
    """

    __tablename__ = "plan_notes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "plan_task_id"],
            ["plan_tasks.project_id", "plan_tasks.task_id"],
        ),
        Index(
            "uq_plan_notes_open_note_id",
            "project_id",
            "note_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_plan_notes_open_plan_task",
            "project_id",
            "plan_task_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    plan_task_id: Mapped[str | None] = mapped_column(Text)
    note_id: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlanNoteReference(db.Model):  # type: ignore[name-defined]
    """A Plan Note's naming of one Block, an entry of the note's `refs`.

    The Block is of the note's Project (DB assertion 211), which no key can
    reach from the Block's row: the engine checks it (DB assertion 213).
    """

    __tablename__ = "plan_note_references"
    __table_args__ = (Index("ix_plan_note_references_block_id", "block_id"),)

    plan_note_id: Mapped[int] = mapped_column(
        ForeignKey("plan_notes.id"), primary_key=True
    )
    block_id: Mapped[int] = mapped_column(ForeignKey("blocks.id"), primary_key=True)
