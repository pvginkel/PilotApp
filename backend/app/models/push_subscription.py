"""Push Subscription (DB §2.1; DB decision 74)."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class PushSubscription(db.Model):  # type: ignore[name-defined]
    """One browser's registration with its push service, through which Pilot
    pushes one person's notifications to it (DB 301, 302, 311).

    Written by the person's turning notifications on in that browser, an
    `endpoint` another person comes to hold replacing the row; deleted by
    their turning them off or signing out there, or by a push its service
    answers gone. Its keys are kept as the browser gives them, base64url: a
    push needs the stage's VAPID key too, so a row alone sends nothing.
    """

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
