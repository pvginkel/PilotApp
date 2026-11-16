"""Pilot's notes and alerts put on the record as `note` and `alert` write
their rows, for a test of what reads them (DB 616 to 631)."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import Block, Item, PilotNote, SendAlert, Turn
from app.models.reference import TurnCause


def a_turn(session: DbSession, run: models.Session) -> Turn:
    """A Turn of `run`, after any it has, the one whose calls write the
    notes."""
    last = session.scalar(select(func.max(Turn.seq)).where(Turn.session_id == run.id))
    turn = Turn(
        session_id=run.id,
        seq=1 if last is None else last + 1,
        message="Pre-rule.",
        started_at=datetime.now(UTC),
        cause_code=TurnCause.BRIEF,
    )
    session.add(turn)
    session.flush()
    return turn


def block_of(session: DbSession, item: Item, local_id: str) -> Block:
    return session.scalars(
        select(Block).where(Block.document_id == item.id, Block.local_id == local_id)
    ).one()


def noted(
    session: DbSession,
    item: Item,
    local_id: str | None,
    turn: Turn,
    *,
    withdrawn: bool = False,
    **fields: Any,
) -> PilotNote:
    """A Pilot Note on `item`'s block `local_id`, or with none on the item
    as a whole, holding `fields`; withdrawn where asked."""
    note = PilotNote(
        item_id=item.id,
        block_id=None if local_id is None else block_of(session, item, local_id).id,
        turn_id=turn.id,
        withdrawn_at=datetime.now(UTC) if withdrawn else None,
        **fields,
    )
    session.add(note)
    session.flush()
    return note


def alerted(
    session: DbSession,
    item: Item,
    awaits: Item,
    local_id: str,
    turn: Turn,
    text: str,
    *,
    withdrawn: bool = False,
) -> SendAlert:
    """A Send Alert on `item` awaiting `awaits`'s block `local_id`; withdrawn
    where asked."""
    alert = SendAlert(
        item_id=item.id,
        awaits_block_id=block_of(session, awaits, local_id).id,
        turn_id=turn.id,
        text=text,
        withdrawn_at=datetime.now(UTC) if withdrawn else None,
    )
    session.add(alert)
    session.flush()
    return alert
