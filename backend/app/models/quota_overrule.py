"""Quota Overrule (DB §2.1; decision 66): a person's lift of the week's usage
halt to a new target."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    Index,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.reference import OVERRULE_KIND, OverruleKind


class QuotaOverrule(db.Model):  # type: ignore[name-defined]
    """One overrule, made by a person while the week's halt held; it holds
    until the server writes its `ended_at`, once (DB 179, 267, 268)."""

    __tablename__ = "quota_overrules"
    __table_args__ = (
        # At most one holds at a time (DB 267).
        Index(
            "uq_quota_overrules_holding",
            text("(ended_at IS NULL)"),
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        # An allowance has its target; a run-out's is the wall, its kind's.
        CheckConstraint(
            "(kind_code = 'allowance') = (target IS NOT NULL)",
            name="ck_quota_overrules_target",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind_code: Mapped[OverruleKind] = mapped_column(OVERRULE_KIND)
    made_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    made_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    target: Mapped[float | None] = mapped_column(Double)
    """An allowance's: the week's share at which it ends, a fraction."""
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
