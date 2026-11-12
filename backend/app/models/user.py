"""User (DB §2.1)."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, Text, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.reference import USER_KIND, UserKind


class User(db.Model):  # type: ignore[name-defined]
    """A person who signs in, Pilot itself: the one row of kind `agent`, or
    a service user, whose subject is the service account of the client whose
    credential it calls with (DB 338).

    Pilot's row is the first revision's, a service user's its command's
    (`create-service-user`). A condition that alarms, begun
    after `alarm_seen_at`, is one the person has not been shown (DB 238): the
    alarm push that names it, or their going offline, moves it forward.
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("handle ~ '^[a-z0-9-]+$'", name="ck_users_handle"),
        # Handle `agent` is Pilot's and no person's; with the handle unique,
        # there is one agent row at most.
        CheckConstraint(
            "(kind_code = 'agent') = (handle = 'agent')", name="ck_users_agent_handle"
        ),
        CheckConstraint(
            "kind_code <> 'agent' OR (subject IS NULL AND email IS NULL"
            " AND avatar_slot IS NULL AND alarm_seen_at IS NULL)",
            name="ck_users_agent",
        ),
        CheckConstraint(
            "kind_code <> 'person' OR (subject IS NOT NULL AND avatar_slot IS NOT NULL)",
            name="ck_users_person",
        ),
        CheckConstraint(
            "kind_code <> 'service' OR (subject IS NOT NULL AND email IS NULL"
            " AND avatar_slot IS NULL AND alarm_seen_at IS NULL)",
            name="ck_users_service",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind_code: Mapped[UserKind] = mapped_column(USER_KIND)
    subject: Mapped[str | None] = mapped_column(Text, unique=True)
    handle: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    alarms: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    join_calls: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true()
    )
    alarm_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    avatar_slot: Mapped[int | None] = mapped_column(Integer, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
