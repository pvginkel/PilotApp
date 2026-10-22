"""Item (DB §2.2), the supertype of the timeline's entries.

A Prose Item's own columns are on `documents` (DB §7.3).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class Item(db.Model):  # type: ignore[name-defined]
    """An entry on a Project's timeline: a Prose Item, a Work or a Wait.

    A Prose Item's Document has the Item's id. For a Prose Item, `kind_code`,
    `title`, `plan_task_id`, `urgent` and `for_user_id` are caches of its
    Document's published text, rebuilt on every publish (DB §7.4); the
    opening's are set at its birth. A Prose Item's `title` is none while its
    text gives none (DB 223).
    """

    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("project_id", "seq"),
        # The task is of the Item's Project, the key carrying `project_id`
        # once (DB assertion 176).
        ForeignKeyConstraint(
            ["project_id", "plan_task_id"],
            ["plan_tasks.project_id", "plan_tasks.task_id"],
        ),
        CheckConstraint("seq >= 1", name="ck_items_seq"),
        # The opening is a person's words; every other Item a Session's (DB
        # assertion 161).
        CheckConstraint(
            "(created_by_user_id IS NULL) <> (created_by_session_id IS NULL)"
            " AND (created_by_user_id IS NULL OR kind_code = 'opening')",
            name="ck_items_created_by",
        ),
        CheckConstraint(
            "(done_at IS NULL) = (done_cause_code IS NULL)"
            " AND (done_by_user_id IS NULL OR done_at IS NOT NULL)",
            name="ck_items_done",
        ),
        CheckConstraint(
            "(consumed_at IS NULL) = (consumed_session_id IS NULL)",
            name="ck_items_consumed",
        ),
        # The badge, the banner and "N open above" read a Project's open Items.
        Index(
            "ix_items_open",
            "project_id",
            "seq",
            postgresql_where=text("done_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    seq: Mapped[int] = mapped_column(Integer)
    kind_code: Mapped[str] = mapped_column(ForeignKey("item_kinds.code"))
    title: Mapped[str | None] = mapped_column(Text)
    plan_task_id: Mapped[str | None] = mapped_column(Text)
    urgent: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    for_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_by_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id")
    )
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    done_cause_code: Mapped[str | None] = mapped_column(ForeignKey("done_causes.code"))
    done_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id")
    )
