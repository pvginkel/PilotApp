"""Usage Reading and Window Share (DB §2.1; decision 67): the subscription's
usage as KubeCoder's controller served it and Pilot received it."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.reference import USAGE_WINDOW, UsageWindow


class UsageReading(db.Model):  # type: ignore[name-defined]
    """One reading received with figures; a stale one keeps the `taken_at` and
    the figures of the poll's last answer (DB assertion 274). Written once,
    never changed; the latest by `id` is the one the halts read."""

    __tablename__ = "usage_readings"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stale: Mapped[bool] = mapped_column(Boolean)


class WindowShare(db.Model):  # type: ignore[name-defined]
    """One window's figure in one Usage Reading, written with it; `share` is
    a fraction of the window's quota, unclamped, so it may pass 1."""

    __tablename__ = "window_shares"
    __table_args__ = (UniqueConstraint("reading_id", "window_code"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    reading_id: Mapped[int] = mapped_column(ForeignKey("usage_readings.id"))
    window_code: Mapped[UsageWindow] = mapped_column(USAGE_WINDOW)
    share: Mapped[float] = mapped_column(Double)
    resets_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
