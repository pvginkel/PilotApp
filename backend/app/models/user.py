"""User and Alarm (DB §2.1)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.reference import CONDITION, USER_KIND, Condition, UserKind


class User(db.Model):  # type: ignore[name-defined]
    """A person who signs in, or Pilot itself: the one row of kind `agent`.

    Pilot's row is the first revision's. `notification_token` holds the
    ciphertext, encrypted with the app's `SECRET_KEY` (DB decision 17), which
    `NotificationTokenCipher` seals and opens.
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
            " AND notification_token IS NULL AND avatar_slot IS NULL)",
            name="ck_users_agent",
        ),
        CheckConstraint(
            "kind_code <> 'person' OR (subject IS NOT NULL AND avatar_slot IS NOT NULL)",
            name="ck_users_person",
        ),
        # What an Alarm's key references, so that it reaches a person alone.
        UniqueConstraint("id", "kind_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind_code: Mapped[UserKind] = mapped_column(USER_KIND)
    subject: Mapped[str | None] = mapped_column(Text, unique=True)
    handle: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    notification_token: Mapped[str | None] = mapped_column(Text)
    alarms: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    avatar_slot: Mapped[int | None] = mapped_column(Integer, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Alarm(db.Model):  # type: ignore[name-defined]
    """What Pilot last sent one person for one Condition (DB decision 55).

    Born at the first submit, never deleted. `user_kind_code` is its User's,
    carried so that the key reaches a person's row alone: Pilot holds no
    Alarm (DB assertion 238).
    """

    __tablename__ = "alarms"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "user_kind_code"], ["users.id", "users.kind_code"]
        ),
        CheckConstraint("user_kind_code = 'person'", name="ck_alarms_person"),
        # One Alarm per User and Condition (DB assertion 237).
        UniqueConstraint("user_id", "condition_code"),
        # Standing is what a submit that went out left on the phone.
        CheckConstraint(
            "NOT standing OR sent_at IS NOT NULL", name="ck_alarms_standing_sent"
        ),
        # The alarms' retry reads the owed ones (DB §7.6).
        Index(
            "ix_alarms_owed_at", "owed_at", postgresql_where=text("owed_at IS NOT NULL")
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID]
    user_kind_code: Mapped[UserKind] = mapped_column(
        USER_KIND, default=UserKind.PERSON, server_default=UserKind.PERSON
    )
    condition_code: Mapped[Condition] = mapped_column(CONDITION)
    standing: Mapped[bool] = mapped_column(Boolean)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
