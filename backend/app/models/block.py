"""Block and Block Option (DB §2.2).

Every attribute but the keys and `updated_at` is a cache of the Document's
published text, rewritten in place on every change to it (DB §7.4).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.reference import (
    ANSWER_CHANNEL,
    BLOCK_KIND,
    AnswerChannel,
    BlockKind,
)


class Block(db.Model):  # type: ignore[name-defined]
    """An ask inside a Document, identified by its Document and `local_id`.

    `deferred_to_task_id` names a Plan Task of the Document's Project, which
    no key can reach from this row: the engine checks it (DB assertion 203).
    """

    __tablename__ = "blocks"
    __table_args__ = (
        UniqueConstraint("document_id", "local_id"),
        # `type: confirmation` is a decision's, and a confirmation without
        # `proposal` or `because` is held (design 1 §6.1).
        CheckConstraint(
            "NOT confirmation OR (kind_code = 'decision'"
            " AND because_code IS NOT NULL AND proposal IS NOT NULL)",
            name="ck_blocks_confirmation",
        ),
        CheckConstraint(
            "deferred_to_task_id IS NULL OR answer = 'deferred'",
            name="ck_blocks_deferred_to",
        ),
        # The popover's count and the deferral-without-a-home check, with the
        # Document's Project through the join.
        Index(
            "ix_blocks_deferred_to_task_id",
            "deferred_to_task_id",
            postgresql_where=text("deferred_to_task_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    local_id: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)
    kind_code: Mapped[BlockKind] = mapped_column(BLOCK_KIND)
    confirmation: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    because_code: Mapped[str | None] = mapped_column(
        ForeignKey("confirmation_reasons.code")
    )
    proposal: Mapped[str | None] = mapped_column(Text)
    default_value: Mapped[str | None] = mapped_column(Text)
    check_text: Mapped[str | None] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    answered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id")
    )
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    via_code: Mapped[AnswerChannel | None] = mapped_column(ANSWER_CHANNEL)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deferred_to_task_id: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BlockOption(db.Model):  # type: ignore[name-defined]
    """A choice a Block offers; deleted with its Block (DB §7.1).

    `text` is NULL for an option written as a bare label (design 1 §6.1).
    """

    __tablename__ = "block_options"
    __table_args__ = (
        Index("ix_block_options_block_id_position", "block_id", "position"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    block_id: Mapped[int] = mapped_column(ForeignKey("blocks.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(Text)
    text: Mapped[str | None] = mapped_column(Text)
    recommended: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
