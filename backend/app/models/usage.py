"""Usage Reading and Window Share (DB §2.1; decision 67): the subscription's
usage as KubeCoder's controller served it and Pilot received it. And Quota
Week (DB §2.5; decision 79.26): the seven-day windows those readings name."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
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


class QuotaWeek(db.Model):  # type: ignore[name-defined]
    """One seven-day window of the subscription's usage, from the reset that
    opened it to the reset that closes it, the end exclusive.

    The weeks leave no gap and none overlap (DB 550): each starts where the
    one before it ends, which `quota_week_service` keeps. The latest is the
    running week, and its `ends_at` alone moves, when a later reading names
    another reset.
    """

    __tablename__ = "quota_weeks"
    __table_args__ = (
        CheckConstraint("starts_at < ends_at", name="ck_quota_weeks_period"),
        ExcludeConstraint(
            (text("tstzrange(starts_at, ends_at)"), "&&"),
            name="ex_quota_weeks_overlap",
            using="gist",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
