"""Pilot Note and Send Alert (DB §2.2; DB decision 84)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class PilotNote(db.Model):  # type: ignore[name-defined]
    """One note Pilot put on a Prose Item for the person who answers it, on
    one Block of its Document or, with none, on the Prose Item as a whole,
    written at a `note` call of a Turn of Pilot's (DB 616 to 627).

    Of a place's Pilot Notes, its Block's or its Prose Item's with no Block,
    the one with the highest `id` stands unless it is withdrawn; the earlier
    ones are kept (DB 625). That its Prose Item is a Prose Item, and its
    Block a Block of that Prose Item's Document (DB 624), is the server's
    check at the call: no key holds it.
    """

    __tablename__ = "pilot_notes"
    __table_args__ = (
        # A place's standing note (DB 625).
        Index("ix_pilot_notes_item_id_block_id_id", "item_id", "block_id", "id"),
        # DB 626: one or more of the four; on no Block, `text` alone.
        CheckConstraint(
            "text IS NOT NULL OR suggested_answer IS NOT NULL"
            " OR suggested_note IS NOT NULL OR offer IS NOT NULL",
            name="ck_pilot_notes_holds",
        ),
        CheckConstraint(
            "block_id IS NOT NULL OR (suggested_answer IS NULL"
            " AND suggested_note IS NULL AND offer IS NULL)",
            name="ck_pilot_notes_on_the_item",
        ),
        # DB 629: the taking's two facts set together, on a note with an offer.
        CheckConstraint(
            "(offer_taken_at IS NULL) = (offer_taken_by_user_id IS NULL)"
            " AND (offer_taken_at IS NULL OR offer IS NOT NULL)",
            name="ck_pilot_notes_offer_taken",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id"))
    block_id: Mapped[int | None] = mapped_column(ForeignKey("blocks.id"))
    turn_id: Mapped[int] = mapped_column(ForeignKey("turns.id"))
    text: Mapped[str | None] = mapped_column(Text)
    suggested_answer: Mapped[str | None] = mapped_column(Text)
    suggested_note: Mapped[str | None] = mapped_column(Text)
    offer: Mapped[str | None] = mapped_column(Text)
    offer_taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    offer_taken_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SendAlert(db.Model):  # type: ignore[name-defined]
    """One warning Pilot put on a Prose Item that another open ask, the
    Block it awaits, has to be answered before this one is sent, written at
    an `alert` call of a Turn of Pilot's (DB 621 to 623, 631).

    Of a Prose Item's Send Alerts the one with the highest `id` stands unless
    it is withdrawn (DB 631). That the awaited Block is of another Prose Item
    of the same Project is the server's check at the call: no key holds it.
    """

    __tablename__ = "send_alerts"
    __table_args__ = (
        # A Prose Item's standing alert (DB 631).
        Index("ix_send_alerts_item_id_id", "item_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id"))
    awaits_block_id: Mapped[int] = mapped_column(ForeignKey("blocks.id"))
    turn_id: Mapped[int] = mapped_column(ForeignKey("turns.id"))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
