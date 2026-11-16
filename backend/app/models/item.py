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
from sqlalchemy.orm import Mapped, mapped_column, validates
from sqlalchemy.orm.attributes import flag_modified

from app.extensions import db


class Item(db.Model):  # type: ignore[name-defined]
    """An entry on a Project's timeline: a Prose Item, a Work, a Wait or a
    Debrief Notice, which has no row of its own beyond this one.

    A Prose Item's Document has the Item's id. For a Prose Item, `kind_code`,
    `title`, `plan_task_id`, `urgent` and `for_user_id` are caches of its
    Document's published text, rebuilt on every publish (DB §7.4); the
    opening's are set at its birth, and an archive question's `kind_code` (DB
    264). A Prose Item's `title` is none while its text gives none (DB 223).

    `folded` is an open Item's alone (DB 318): every write of `done_at` that
    closes the Item clears it in the same UPDATE, whatever the row held when
    the Item was loaded.
    """

    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("project_id", "seq"),
        # What a Work's keys reference, so its Item is of its Project.
        UniqueConstraint("project_id", "id"),
        # What a Wait's key and a Work's key to its Debrief Notice reference,
        # so that the Item is of the kind each holds.
        UniqueConstraint("id", "kind_code"),
        # The task is of the Item's Project, the key carrying `project_id`
        # once (DB assertion 176).
        ForeignKeyConstraint(
            ["project_id", "plan_task_id"],
            ["plan_tasks.project_id", "plan_tasks.task_id"],
        ),
        CheckConstraint("seq >= 1", name="ck_items_seq"),
        # The opening is a person's words, and an archive question and a
        # Debrief Notice Pilot's; every other Item a Session's (DB assertion
        # 161).
        CheckConstraint(
            "(created_by_user_id IS NULL) <> (created_by_session_id IS NULL)"
            " AND (created_by_user_id IS NULL"
            " OR kind_code IN ('opening', 'archive_question', 'debrief_notice'))",
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
        # No done Item is folded (DB assertion 318).
        CheckConstraint("NOT folded OR done_at IS NULL", name="ck_items_folded"),
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
    folded: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    @validates("done_at")
    def _close_clears_fold(
        self, _key: str, done_at: datetime | None
    ) -> datetime | None:
        """The Item's close clears its fold (DB 318). The fold is written with
        the close even where the Item was loaded unfolded, so that a fold
        committed since that load does not outlive the close."""
        if done_at is not None:
            self.folded = False
            flag_modified(self, "folded")
        return done_at
