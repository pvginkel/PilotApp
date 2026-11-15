"""A Session's Holds (DB §2.5, Hold; assertions 360 to 362 and 559): the
record of what the gate did to one Session.

A Hold is one period in which the gate kept a Session waiting for one reason,
of the Hold Kind of that reason (`start_gate.held_reason`), which the gate
gives in its order. One Hold of a Session is open at a time: a reason that
changes ends the Hold and starts the next at the same moment. Each is written
in the transaction that moves its Session or reads the gate for it, under the
Session's lock, by whichever process does. Nothing reads a Hold to decide
anything: the gate decides from what it reads itself, and a screen reads the
gate's reason at display (decision 53).
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Hold
from app.models import Session as AgentSession
from app.models.reference import HoldKind
from app.schemas.timeline import HeldReason
from app.services.start_gate import Held

KINDS = {
    HeldReason.WEEK_HALT: HoldKind.WEEK_HALT,
    HeldReason.FIVE_HOUR_HALT: HoldKind.FIVE_HOUR_HALT,
    HeldReason.PAUSED: HoldKind.PAUSE,
    HeldReason.STORE_UPDATE: HoldKind.STORE_UPDATE,
    HeldReason.CONTROLLER_UNREACHABLE: HoldKind.OUTAGE,
    HeldReason.SLOT: HoldKind.SLOT,
    HeldReason.QUEUE: HoldKind.QUEUE,
    HeldReason.CONVERSATION: HoldKind.CONVERSATION,
}
"""The Hold Kind of each of the gate's reasons, one to one."""


def turn_hold(
    db: Session, session: AgentSession, held: Held | None, at: datetime
) -> None:
    """Under the Session's lock: its Holds as the gate has it at `at`, kept
    waiting for `held`, None where the gate keeps it no longer. Its open Hold
    of that reason's kind stands; one of another kind ends, and the next
    starts at the same moment (DB 362); with none open, one starts; and with
    no reason the open one ends."""
    kind = None if held is None else KINDS[held.reason]
    standing = db.scalars(
        select(Hold).where(Hold.session_id == session.id, Hold.ended_at.is_(None))
    ).one_or_none()
    if standing is not None:
        if standing.kind_code is kind:
            return
        # `at` may be read before the Session's lock was taken, or by another
        # process's clock than the one the Hold started by.
        at = max(at, standing.started_at)
        standing.ended_at = at
        # Before the next one's insert: `uq_holds_open_session_id`.
        db.flush()
    if kind is not None:
        db.add(Hold(session_id=session.id, kind_code=kind, started_at=at))
        db.flush()
