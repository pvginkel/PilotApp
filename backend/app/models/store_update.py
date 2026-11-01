"""Store Update (DB §2.3; decision 68): the operator's update of the store
environment while Pilot runs, the hold on the store's work while unlifted."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class StoreUpdate(db.Model):  # type: ignore[name-defined]
    """One update, made by `update-store`; the server writes each phase once,
    in order, from the row, and lifts it (DB 276, 279)."""

    __tablename__ = "store_updates"
    __table_args__ = (
        # At most one is unlifted, the hold, at a time (DB 276).
        Index(
            "uq_store_updates_unlifted",
            text("(lifted_at IS NULL)"),
            unique=True,
            postgresql_where=text("lifted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    made_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """When the store's running and starting jobs and chats were stopped by
    Pilot and their turns had ended or the bounded wait had passed."""
    reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """When the store's reset returned with the environment running."""
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """When the store's sidecar first posted a manifest with an empty shadow
    after `stopped_at`."""
    lift_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """The command's `--lift`: the server writes no phase not yet written but
    `lifted_at`."""
    lifted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    """The sequence's last failure, the controller's reason whole; cleared at
    the next attempt."""
