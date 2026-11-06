"""User (DB §2.1)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Text,
    func,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.reference import USER_KIND, UserKind


class User(db.Model):  # type: ignore[name-defined]
    """A person who signs in, or Pilot itself: the one row of kind `agent`.

    Pilot's row is the first revision's. `notification_token` holds the
    ciphertext, encrypted with the app's `SECRET_KEY` (DB decision 17), which
    `NotificationTokenCipher` seals and opens. The `alarm_` columns are what
    was last sent of the person's alarm notification, overwritten by the next
    submit or dismiss that goes out (DB decision 70): its text while it
    stands, none after a dismiss.
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
            " AND notification_token IS NULL AND avatar_slot IS NULL"
            " AND alarm_text IS NULL AND alarm_sent_at IS NULL"
            " AND alarm_owed_at IS NULL)",
            name="ck_users_agent",
        ),
        CheckConstraint(
            "kind_code <> 'person' OR (subject IS NOT NULL AND avatar_slot IS NOT NULL)",
            name="ck_users_person",
        ),
        # A standing alarm notification is one a submit that went out left.
        CheckConstraint(
            "alarm_text IS NULL OR alarm_sent_at IS NOT NULL",
            name="ck_users_alarm_sent",
        ),
        # The alarms' retry reads the owed ones (DB §7.6).
        Index(
            "ix_users_alarm_owed_at",
            "alarm_owed_at",
            postgresql_where=text("alarm_owed_at IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind_code: Mapped[UserKind] = mapped_column(USER_KIND)
    subject: Mapped[str | None] = mapped_column(Text, unique=True)
    handle: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    notification_token: Mapped[str | None] = mapped_column(Text)
    alarms: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    alarm_text: Mapped[str | None] = mapped_column(Text)
    alarm_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alarm_owed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    avatar_slot: Mapped[int | None] = mapped_column(Integer, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
