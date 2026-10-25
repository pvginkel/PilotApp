"""The gate every start passes (design 2 §13.4, §13.5, D11; F141.5, F143.4;
DB 229, 243).

A start is held while its project is paused, a Chat's never (F141.4), while
the controller is unreachable, and, a work item's alone, while no slot is
free: the work items running or starting across every Project number the
cross-project maximum, or those of its Project the per-project one. Where
more than one holds, the pause comes first, then the outage, which is the
gold bar's, then the slot. The halt is slice 016's condition.

The slot is counted under one app-wide lock (`WorkSlots.lock`), so two starts
never both take its last place. A work item's end opens it.
"""

import uuid
from collections.abc import Callable, Collection
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Session as AgentSession
from app.models.reference import SessionState
from app.schemas.timeline import HeldReason
from app.utils.after_commit import after_commit

CHAT_KIND = "chat"

WORK_KIND = "work"
"""The Session Kind the slot counts: a work item's, never a Chat's or a
job's (DB 243)."""

COUNTED = (SessionState.RUNNING, SessionState.STARTING)
"""The states a work item holds a slot in."""

SLOT_LOCK = 243
"""The key of the slot's advisory lock: no other lock of the app's is
advisory."""

type SlotListener = Callable[[], None]


@dataclass(frozen=True)
class Held:
    """Why the gate holds a start."""

    reason: HeldReason
    running: int | None = None
    """The slot's: the running work items of the maximum that closed it;
    None for any other reason."""


def held_reason(
    *, paused: bool, kind_code: str, unreachable: bool, filled: int | None
) -> Held | None:
    """Why the gate holds a start of a Session of `kind_code` in a project
    `paused` or not, the controller `unreachable` or not, where `filled`
    running work items leave a work item no slot (`WorkSlots.filled`), None
    while one is free; None while the gate is open."""
    if paused and kind_code != CHAT_KIND:
        return Held(HeldReason.PAUSED)
    if unreachable:
        return Held(HeldReason.CONTROLLER_UNREACHABLE)
    if kind_code == WORK_KIND and filled is not None:
        return Held(HeldReason.SLOT, filled)
    return None


class WorkSlots:
    """The slot (§13.5): the maxima, the count under its lock, and the open
    event, which a work item's end raises."""

    def __init__(self, work_max: int, project_max: int) -> None:
        """The slot of the maxima, with no listener yet.

        Args:
            work_max: The running work items across every Project that leave
                no slot (WORK_PARALLELISM_MAX)
            project_max: Those of one Project that leave its work items none
                (PROJECT_PARALLELISM_MAX)
        """
        self._work_max = work_max
        self._project_max = project_max
        self._listeners: list[SlotListener] = []

    def subscribe(self, listener: SlotListener) -> None:
        """Call `listener` once a transaction that ended a work item's run
        commits."""
        self._listeners.append(listener)

    def lock(self, db: Session) -> None:
        """Hold the slot until the transaction ends: a start that may move a
        work Session to `starting` takes it before it counts, so the count of
        the next waits for its commit. It comes after the Project's and the
        Session's rows and before any Environment's (the start's lock
        order)."""
        db.execute(select(func.pg_advisory_xact_lock(SLOT_LOCK)))

    def filled(
        self, db: Session, project_ids: Collection[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        """The running work items that leave each Project among `project_ids`
        no slot: those across every Project while they number the
        cross-project maximum, else the Project's own while they number the
        per-project one. A Project with room is left out."""
        running: dict[uuid.UUID, int] = dict(
            db.execute(
                select(AgentSession.project_id, func.count())
                .where(
                    AgentSession.kind_code == WORK_KIND,
                    AgentSession.state_code.in_(COUNTED),
                )
                .group_by(AgentSession.project_id)
            ).all()
        )
        everywhere = sum(running.values())
        if everywhere >= self._work_max:
            return dict.fromkeys(project_ids, everywhere)
        return {
            project_id: running[project_id]
            for project_id in project_ids
            if running.get(project_id, 0) >= self._project_max
        }

    def left(self, session: AgentSession, before: SessionState) -> None:
        """The Session, under its lock, moved from `before` in the
        transaction: a work item's run that ended, `running` or `starting`
        no longer, opens the gate once the transaction commits."""
        if (
            session.kind_code == WORK_KIND
            and before in COUNTED
            and session.state_code not in COUNTED
        ):
            for listener in self._listeners:
                after_commit(listener)
