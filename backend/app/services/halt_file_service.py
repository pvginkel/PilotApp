"""The halt file (F135.6, F141.3; design 2 §13.4, *The pause's file and
nudge*; DB 231): `/work/.quota-limit-halt-requested`, written into an
environment where a work item's Session runs under a usage halt whose setting
is the cooperative stop or under its project's pause, and deleted once none
runs there under either. Never for a job's Session or a chat's, so never into
the store. Two projects sharing an environment share its file, and so do a
halt and a pause.

An Environment's `halt_requested_at` says the server wrote the file there.
What is owed is read from the rows: an environment whose column is unset
where the file is wanted, or set where it is not. Each such environment's
file is brought in line by a loop of its own, `halt-file:<env id>`, under the
Environment's row: the file written and the column set, or the file deleted
and the column cleared, a file the controller no longer finds deleted. A call
the controller does not answer, or refuses — its own work on the tree, a
`409 conflict`, among the refusals — raises, and the loop runs again after
its backoff, so an environment owed a write or a delete gets it once the
controller answers.

A change of what holds the file asks for a sweep once it commits: a pause or
a resume (`ProjectService`), a halt's turn (`UsageWatcher`), a work item's
run's end (`WorkSlots`). The sweep, the loop `halt-file`, starts the loop of
every environment owed. The timer does the same on every tick, its first a
restart's reconcile, and finds a work item whose start the gate let through
before a halt or a pause it now runs under.
"""

import logging
from datetime import UTC, datetime
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
        """Register the `halt-file` job and its timer, and hear each work
        item's run's end.

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
        supervisor.register_job(HALT_FILE_JOB, needs_controller=True)
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
        """The timer's tick, and its reconcile: the loop of every environment
        owed started."""
        self._start_owed(db)

    def settle(self, env_id: str, handle: LoopHandle) -> None:
        """An environment's loop's run: under its row, the halt file written
        there and `halt_requested_at` set while a work item runs there under
        a cooperative halt or its project's pause, or the file deleted and
        the column cleared once none does; each in a transaction of its own,
        read again after it until the column says what is wanted, so that a
        change committed during the call, which the sweep read before this
        commit, is taken too. Returns then, and when the loop is told to
        stop.

        Raises:
            ExternalServiceException: The controller did not answer, or
                refused the write or the delete
        """
        while not handle.stopping:
            with scoped_session(self._container) as db:
                moved = self._bring_in_line(db, env_id)
            if not moved:
                return

    def _bring_in_line(self, db: Session, env_id: str) -> bool:
        """The file written or deleted as what holds now asks, under the
        Environment's row; whether either was."""
        row = db.scalars(
            select(Environment)
            .where(Environment.id == env_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()
        wanted = bool(db.scalar(select(_wanted(env_id, halting=self.halting(db)))))
        if wanted == (row.halt_requested_at is not None):
            return False
        if wanted:
            self._client().write_file(env_id, HALT_FILE, b"")
            row.halt_requested_at = datetime.now(UTC)
            logger.info("Wrote the halt file into environment %s", env_id)
        else:
            self._client().delete_file(env_id, HALT_FILE)
            row.halt_requested_at = None
            logger.info("Deleted the halt file from environment %s", env_id)
        return True

    def _start_owed(self, db: Session) -> None:
        for env_id in self.owed(db):
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
