"""Wait (DB §2.2), the subtype of Item, with its two kinds, Card Wait and
Timed Wait; Wait Firing, a characteristic of Wait; and Card Transition, a
kernel (DB decision 46).

`waits` is the extension table keyed by its Item's id, both kinds in one
table: a Timed Wait's `due_at`, and a Card Wait's Watched Cards and Watched
States folded into `cards` and `states` (DB §7.3).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.reference import FIRING_CAUSE, FiringCause


class Wait(db.Model):  # type: ignore[name-defined]
    """An Item that waits for something outside Pilot, fixed at add (F27.6).

    `kind_code` is its Item's, carried so that the key reaches an Item of the
    same kind (DB assertion 185) and the check reads it. `cards` and `states`
    hold no name twice, `states` case-insensitively (DB 194): the server's
    check at add, which no constraint holds.

    `done_note` is the brain's words at a `marked` close, none while the wait
    is open and after a close by Finish (DB 300): a rule across `items` and
    `waits` the server keeps.
    """

    __tablename__ = "waits"
    __table_args__ = (
        ForeignKeyConstraint(["id", "kind_code"], ["items.id", "items.kind_code"]),
        # What a firing's key references, so the check reads its Wait's kind.
        UniqueConstraint("id", "kind_code"),
        CheckConstraint(
            "kind_code IN ('card_wait', 'timed_wait')", name="ck_waits_kind"
        ),
        # A timed wait has its due time, a card wait its two lists, each of
        # one name or more (DB 186, 187).
        CheckConstraint(
            "(kind_code = 'timed_wait') = (due_at IS NOT NULL)"
            " AND (kind_code = 'card_wait') = (cards IS NOT NULL)"
            " AND (cards IS NULL) = (states IS NULL)"
            " AND (cards IS NULL"
            " OR (cardinality(cards) >= 1 AND cardinality(states) >= 1))",
            name="ck_waits_halves",
        ),
        # The waits' timer reads the timed waits; a partial index reads no
        # other table, so the item's openness and its `due` firing are the
        # query's (DB §7.6).
        Index("ix_waits_due_at", "due_at", postgresql_where=text("due_at IS NOT NULL")),
        # The match reads the card waits by card (DB §7.6).
        Index(
            "ix_waits_cards",
            "cards",
            postgresql_using="gin",
            postgresql_where=text("cards IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    kind_code: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cards: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    states: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    done_note: Mapped[str | None] = mapped_column(Text)


class CardTransition(db.Model):  # type: ignore[name-defined]
    """One change of a card's state the tracker reported and a Card Wait
    matched, recorded only then (DB 197). `at` is the tracker's time of the
    change, `received_at` the record's (TIME-4)."""

    __tablename__ = "card_transitions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    card: Mapped[str] = mapped_column(Text)
    from_state: Mapped[str | None] = mapped_column(Text)
    to_state: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    by: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WaitFiring(db.Model):  # type: ignore[name-defined]
    """One occasion a Wait fired, pending until a job takes it (DB 191).

    `wait_kind_code` is its Wait's, carried so that the check reads it: a
    transition fires a card wait, the due time a timed wait (DB 193).
    """

    __tablename__ = "wait_firings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["wait_id", "wait_kind_code"], ["waits.id", "waits.kind_code"]
        ),
        UniqueConstraint("wait_id", "seq"),
        CheckConstraint("seq >= 1", name="ck_wait_firings_seq"),
        CheckConstraint(
            "(cause_code = 'transition') = (transition_id IS NOT NULL)"
            " AND (cause_code = 'requested') = (requested_by_user_id IS NOT NULL)",
            name="ck_wait_firings_cause",
        ),
        CheckConstraint(
            "(cause_code <> 'transition' OR wait_kind_code = 'card_wait')"
            " AND (cause_code <> 'due' OR wait_kind_code = 'timed_wait')",
            name="ck_wait_firings_kind",
        ),
        # A timed wait fires `due` at most once (DB 198).
        Index(
            "uq_wait_firings_due",
            "wait_id",
            unique=True,
            postgresql_where=text("cause_code = 'due'"),
        ),
        # A transition fires each card wait it matched once (DB 197).
        Index(
            "uq_wait_firings_transition_id_wait_id",
            "transition_id",
            "wait_id",
            unique=True,
            postgresql_where=text("transition_id IS NOT NULL"),
        ),
        # The batcher reads the pending firings (DB §7.6).
        Index(
            "ix_wait_firings_pending",
            "wait_id",
            postgresql_where=text("job_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    wait_id: Mapped[uuid.UUID]
    wait_kind_code: Mapped[str] = mapped_column(Text)
    seq: Mapped[int] = mapped_column(Integer)
    cause_code: Mapped[FiringCause] = mapped_column(FIRING_CAUSE)
    transition_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("card_transitions.id")
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id")
    )
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("work.id"))
