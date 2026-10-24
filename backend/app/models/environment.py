"""Environment (DB §2.3), with the columns the record gives it."""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class Environment(db.Model):  # type: ignore[name-defined]
    """A KubeCoder environment Pilot has touched, keyed by its environment id."""

    __tablename__ = "environments"
    __table_args__ = (
        Index(
            "ix_environments_stop_due_at",
            "stop_due_at",
            postgresql_where=text("stop_due_at IS NOT NULL"),
        ),
        Index(
            "ix_environments_delete_due_at",
            "delete_due_at",
            postgresql_where=text("delete_due_at IS NOT NULL"),
        ),
        # The take looks among Pilot's own for the Work's repository.
        Index(
            "ix_environments_repo",
            "repo",
            postgresql_where=text("server_created_at IS NOT NULL"),
        ),
        Index(
            "ix_environments_halt_requested_at",
            "halt_requested_at",
            postgresql_where=text("halt_requested_at IS NOT NULL"),
        ),
        # Pilot's own, and only they, were created from a repository (DB 239).
        CheckConstraint(
            "(server_created_at IS NULL) = (repo IS NULL)",
            name="ck_environments_repo",
        ),
        # Only Pilot's own is ever deleted (DB 242).
        CheckConstraint(
            "delete_due_at IS NULL OR server_created_at IS NOT NULL",
            name="ck_environments_delete_due_at",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    server_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    repo: Mapped[str | None] = mapped_column(Text)
    delete_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    server_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_pod_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stop_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exempt: Mapped[bool] = mapped_column(Boolean)
    last_state: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    halt_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
