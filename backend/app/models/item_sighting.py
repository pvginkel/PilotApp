"""Item Sighting (DB §2.1; DB decision 74)."""

import uuid

from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class ItemSighting(db.Model):  # type: ignore[name-defined]
    """One Project Member's having been shown one Item that waits on them
    (DB 307 to 310, 313, 315): named or counted in a push to them that went
    out, or waiting while a page of theirs showed the Project.

    Written and deleted by the reconcile alone (`NotificationReconcileService`),
    which writes the Items of the Project it reconciles only, so that the
    Item is of its member's Project (DB 315). Deleted once its Item no longer
    waits on the member, so that an Item coming to wait again alerts again,
    and at Archive and Leave.
    """

    __tablename__ = "item_sightings"

    member_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("project_members.id"), primary_key=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id"), primary_key=True)
