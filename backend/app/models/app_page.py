"""App Page (DB §2.1; DB decision 74)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class AppPage(db.Model):  # type: ignore[name-defined]
    """One page of Pilot open in a browser while its person is active in it
    (DB 303 to 306, 312).

    Written at the page's first beat, which mints its id, and set by each beat
    after; deleted at its away, or once its beat is ninety seconds old, when
    it counts for nothing (`AppPageService`). A person is online while one of
    theirs counts: derived, never stored. Pilot has none.
    """

    __tablename__ = "app_pages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    """The project the page shows, a page of it; none elsewhere."""
    beat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
