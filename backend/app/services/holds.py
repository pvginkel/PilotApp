"""A Session's Holds (DB §2.5, Hold; assertions 360 to 362 and 559): the
record of what Pilot kept one Session from.

A Hold is one period in which Pilot kept a Session from running for one
reason, of the Hold Kind of that reason. A start the gate keeps `held` is held
for the gate's reason (`start_gate.held_reason`), which the gate gives in its
order. A Session at rest that is owed its nudge is held for the first reason,
in that order, that withholds the nudge (`at_rest`): a usage halt, its
project's pause or a Store Update. One Hold of a Session is open at a time: a
reason that changes ends the Hold and starts the next at the same moment, and
so does a held start taking a rest's place. Each is written in the transaction
that moves its Session, reads the gate for it or reads what keeps it at rest,
under the Session's lock, by whichever process does. Nothing reads a Hold to
decide anything: the gate and the nudge decide from what they read themselves,
and a screen reads the gate's reason at display (decision 53).
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Hold, Item, Project
from app.models import Session as AgentSession
from app.models.reference import HoldKind, ProjectState
from app.schemas.timeline import HeldReason
from app.services.start_gate import JOB_KIND, WORK_KIND, Held, held_reason, setups
from app.services.store_update_service import unlifted
from app.services.usage_halts import UsageHalts

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


def at_rest(db: Session, session: AgentSession, halts: UsageHalts) -> Held | None:
    """Why Pilot keeps the Session, at rest, from the nudge it is owed: the
    first, in the gate's order (`held_reason`), of a usage halt, a work
    item's alone, its project's pause, never a setup's, and a Store Update
    unlifted, a job's alone. None where it is owed no nudge; where none of
    the three withholds it, one at the quota wall that waits for quota alone
    among them; and where its nudge goes out no more, its item done or its
    project finished or archived."""
    if session.nudge_owed_at is None:
        return None
    done_at, standing, archived, paused = db.execute(
        select(Item.done_at, Project.state_code, Project.archived, Project.paused)
        .join(Project, Project.id == Item.project_id)
        .where(Item.id == session.id)
    ).one()
    if done_at is not None or archived or standing is ProjectState.FINISHED:
        return None
    work = session.kind_code == WORK_KIND
    return held_reason(
        halted=halts.halted(db) if work else None,
        paused=paused,
        kind_code=session.kind_code,
        setup=session.kind_code == JOB_KIND and session.id in setups(db, [session.id]),
        updating=not work and unlifted(db) is not None,
        unreachable=False,
        filled=None,
        queued=False,
        conversing=False,
    )


def turn_rest(
    db: Session, session: AgentSession, halts: UsageHalts, at: datetime
) -> None:
    """Under the lock of a Session the gate does not hold: its Holds as what
    keeps it at rest reads at `at` (`at_rest`), turned as `turn_hold` turns
    them."""
    turn_hold(db, session, at_rest(db, session, halts), at)
