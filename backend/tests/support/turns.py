"""A Session's Turn in flight and its end, as the send and the relay leave
them, for the tests of a store save: a save is its session's turn's while
that turn is in flight, and late once it ended (design 1 §7)."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import Turn


def turn_in_flight(db: DbSession, run: models.Session) -> Turn:
    """`run`'s Turn in flight: its latest open one, else a server's Turn
    sent now."""
    turn = db.scalars(
        select(Turn)
        .where(Turn.session_id == run.id, Turn.ended_at.is_(None))
        .order_by(Turn.seq.desc())
    ).first()
    if turn is not None:
        return turn
    last = db.scalar(select(func.max(Turn.seq)).where(Turn.session_id == run.id))
    turn = Turn(
        session_id=run.id,
        seq=(last or 0) + 1,
        message="Write the palette.",
        started_at=datetime.now(UTC),
    )
    db.add(turn)
    db.flush()
    return turn


def end_turns(db: DbSession, run: models.Session) -> None:
    """Every Turn of `run` in flight ended now, as its turn's end ends it."""
    for turn in db.scalars(
        select(Turn).where(Turn.session_id == run.id, Turn.ended_at.is_(None))
    ):
        turn.ended_at = datetime.now(UTC)
    db.flush()
