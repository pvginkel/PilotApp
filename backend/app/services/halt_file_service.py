"""The halt file (F135.6, F141.3; design 2 §13.4, *The pause's file and
nudge*; DB 231): `/work/.quota-limit-halt-requested`, written into an
environment where a work item's Session runs under a usage halt whose setting
is the cooperative stop or under its project's pause, and deleted once none
runs there under either. Never for a job's Session or a chat's, so never into
the store. Two projects sharing an environment share its file, and so do a
halt and a pause.

An Environment's `halt_requested_at` says the file may be there: it is set,
and committed, before the write goes out, and cleared once the delete is
answered, so that a write the controller made but whose answer never came is
deleted once nothing holds the file. What is owed is read from the rows: an
environment whose column is unset where the file is wanted, or set where it
is not. Each such environment's file is brought in line by a loop of its own,
`halt-file:<env id>`, under the Environment's row; a file the controller no
longer finds counts as deleted. A call the controller does not answer, or
refuses — its own work on the tree, a `409 conflict`, among the refusals —
raises, and the loop runs again after its backoff. Each run writes the file
where it is wanted, whatever the column says, so an environment owed a write
or a delete gets it once the controller answers.

A change of what holds the file asks for a sweep once it commits: a pause or
a resume (`ProjectService`), a halt's turn (`UsageWatcher`), a work item's
run's end (`WorkSlots`). The sweep, the loop `halt-file`, starts the loop of
every environment owed. The timer does the same on every tick, and finds a
work item whose start the gate let through before a halt or a pause it now
runs under. The job's reconcile at STARTUP starts the loop of every
environment owed or whose column is set: a process that ended during a call
left the file's presence unknown there.
"""

import logging
from datetime import UTC, datetime
from enum import Enum
from functools import partial
from typing import TYPE_CHECKING

from sqlalchemy import Exists, and_, or_, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.app_config import HaltSetting
from app.database import scoped_session
from app.models import Environment, Project
from app.models import Session as AgentSession
from app.models.reference import SessionState, UsageWindow
from app.services.controller_client import ControllerClient
from app.services.start_gate import WORK_KIND, WorkSlots
from app.services.supervisor import LoopHandle, Supervisor
from app.services.usage_halts import UsageHalts

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)

HALT_FILE = "/work/.quota-limit-halt-requested"

HALT_FILE_JOB = "halt-file"

TIMER = "halt-file"


class _Step(Enum):
    """What one pass of an environment's run did."""

    MARKED = "marked"
    WRITTEN = "written"
    DELETED = "deleted"


class HaltFileService:
    """Writes the halt file where a work item runs under a cooperative halt
    or its project's pause, and deletes it once none does."""

    def __init__(
        self,
        container: "ServiceContainer",
        supervisor: Supervisor,
        usage_halts: UsageHalts,
        work_slots: WorkSlots,
        week_halt: HaltSetting,
        five_hour_halt: HaltSetting,
    ) -> None:
        """Register the `halt-file` job, its reconcile and its timer, and hear
        each work item's run's end.

        Args:
            container: Gives each run its database session, and the client
            supervisor: Runs the sweep and each environment's loop, again
                after one raised, and the timer on its tick
            usage_halts: Decides which halts hold
            work_slots: Tells of each work item's run's end, once it commits
            week_halt: What the week's halt does to the work items (WEEK_HALT)
            five_hour_halt: What the five-hour halt does to them
                (FIVE_HOUR_HALT)
        """
        self._container = container
        self._supervisor = supervisor
        self._halts = usage_halts
        self._settings = {
            UsageWindow.SEVEN_DAY: week_halt,
            UsageWindow.FIVE_HOUR: five_hour_halt,
        }
        supervisor.register_job(
            HALT_FILE_JOB, needs_controller=True, reconcile=self.reconcile
        )
        supervisor.register_timer(TIMER, self.run_timer, needs_controller=True)
        work_slots.subscribe(self.request)

    def halting(self, db: Session) -> bool:
        """Whether a usage halt whose setting is the cooperative stop holds
        now: the file is wanted wherever a work item runs."""
        return any(
            self._settings[window] is HaltSetting.COOPERATIVE_STOP
            for window in self._halts.holding(db)
        )

    def owed(self, db: Session) -> list[str]:
        """The environments whose `halt_requested_at` is not what is wanted:
        unset where a work item runs under a cooperative halt or its
        project's pause, or set where none does."""
        wanted = _wanted(Environment.id, halting=self.halting(db))
        return list(
            db.scalars(
                select(Environment.id)
                .where(
                    or_(
                        and_(Environment.halt_requested_at.is_(None), wanted),
                        and_(Environment.halt_requested_at.is_not(None), ~wanted),
                    )
                )
                .order_by(Environment.id)
            )
        )

    def request(self) -> None:
        """A change of what holds the file committed: the sweep runs, again
        after the run under way if one is."""
        self._supervisor.start_loop(HALT_FILE_JOB, self.sweep, again=True)

    def sweep(self, handle: LoopHandle) -> None:
        """The sweep's run: the loop of every environment owed started."""
        with scoped_session(self._container) as db:
            self._start_owed(db)

    def run_timer(self, db: Session) -> None:
        """The timer's tick: the loop of every environment owed started."""
        self._start_owed(db)

    def reconcile(self, db: Session) -> None:
        """The job's reconcile at STARTUP: the loop of every environment owed
        or whose `halt_requested_at` is set started."""
        requested = db.scalars(
            select(Environment.id).where(Environment.halt_requested_at.is_not(None))
        )
        for env_id in sorted({*self.owed(db), *requested}):
            self._start(env_id)

    def settle(self, env_id: str, handle: LoopHandle) -> None:
        """An environment's loop's run: under its row, while a work item runs
        there under a cooperative halt or its project's pause,
        `halt_requested_at` set and then the halt file written, or, once none
        does, the file deleted and the column cleared; each in a transaction
        of its own, read again after it until the column says what is wanted
        and the file is written where it is, so that a change committed
        during the call, which the sweep read before this commit, is taken
        too. Returns then, and when the loop is told to stop.

        Raises:
            ExternalServiceException: The controller did not answer, or
                refused the write or the delete
        """
        written = False
        while not handle.stopping:
            with scoped_session(self._container) as db:
                step = self._bring_in_line(db, env_id, written=written)
            if step is None:
                return
            written = step is _Step.WRITTEN

    def _bring_in_line(
        self, db: Session, env_id: str, *, written: bool
    ) -> _Step | None:
        """One step towards what holds now asks, under the Environment's
        row: the column set before the file is written, the file written
        unless this run has written it, or the file deleted and the column
        cleared; None once nothing is left."""
        row = db.scalars(
            select(Environment)
            .where(Environment.id == env_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()
        wanted = bool(db.scalar(select(_wanted(env_id, halting=self.halting(db)))))
        requested = row.halt_requested_at is not None
        if wanted and not requested:
            row.halt_requested_at = datetime.now(UTC)
            return _Step.MARKED
        if wanted and not written:
            self._client().write_file(env_id, HALT_FILE, b"")
            logger.info("Wrote the halt file into environment %s", env_id)
            return _Step.WRITTEN
        if not wanted and requested:
            self._client().delete_file(env_id, HALT_FILE)
            row.halt_requested_at = None
            logger.info("Deleted the halt file from environment %s", env_id)
            return _Step.DELETED
        return None

    def _start_owed(self, db: Session) -> None:
        for env_id in self.owed(db):
            self._start(env_id)

    def _start(self, env_id: str) -> None:
        self._supervisor.start_loop(
            HALT_FILE_JOB, partial(self.settle, env_id), key=env_id, again=True
        )

    def _client(self) -> ControllerClient:
        client: ControllerClient = self._container.controller_client()
        return client


def _wanted(env_id: InstrumentedAttribute[str] | str, *, halting: bool) -> Exists:
    """Whether a work item's Session runs in the environment under a
    cooperative halt, while `halting`, or under its project's pause."""
    held = (
        select(AgentSession.id)
        .join(Project, Project.id == AgentSession.project_id)
        .where(
            AgentSession.environment_id == env_id,
            AgentSession.kind_code == WORK_KIND,
            AgentSession.state_code == SessionState.RUNNING,
        )
    )
    if not halting:
        held = held.where(Project.paused.is_(True))
    return held.exists()
