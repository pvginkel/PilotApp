"""Project, Project Member and Project Transition (DB §2.1)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.reference import (
    PROJECT_STATE,
    TRANSITION_KIND,
    ProjectState,
    TransitionKind,
)


class Project(db.Model):  # type: ignore[name-defined]
    """A piece of multi-step work Pilot manages front to end.

    `name` is a cache of the draft's title, rebuilt on every publish of the
    draft. `state_code`, `archived` and `autopilot` are caches of the Project
    Transitions, rebuilt with each (DB §7.4).
    """

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "slug ~ '^[a-z0-9-]+$' AND slug NOT LIKE 'draft-%'", name="ck_projects_slug"
        ),
        # The opened transition sets the slug (DB assertion 177).
        CheckConstraint(
            "(state_code = 'draft') = (slug IS NULL)", name="ck_projects_draft_slug"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    number: Mapped[int] = mapped_column(Integer, Identity(), unique=True)
    slug: Mapped[str | None] = mapped_column(Text, unique=True)
    name: Mapped[str | None] = mapped_column(Text)
    state_code: Mapped[ProjectState] = mapped_column(
        PROJECT_STATE, default=ProjectState.DRAFT, server_default=ProjectState.DRAFT
    )
    archived: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    autopilot: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    ticket: Mapped[str | None] = mapped_column(Text)
    repo: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ProjectMember(db.Model):  # type: ignore[name-defined]
    """One User's membership of one Project, from joining until leaving."""

    __tablename__ = "project_members"
    __table_args__ = (
        # One open membership per User and Project; the members' avatars and
        # the notification fan-out read the open ones per Project.
        Index(
            "uq_project_members_open",
            "project_id",
            "user_id",
            unique=True,
            postgresql_where=text("left_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectTransition(db.Model):  # type: ignore[name-defined]
    """A change of a Project's state, archived flag or auto pilot switch."""

    __tablename__ = "project_transitions"
    __table_args__ = (Index("ix_project_transitions_project_at", "project_id", "at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    kind_code: Mapped[TransitionKind] = mapped_column(TRANSITION_KIND)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
