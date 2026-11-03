"""The batcher (design 2 §8.2; F136.4): on the scheduler's tick, each open wait
of an open, unarchived project whose oldest pending firing is a quiet window
old, and no run of which is in flight, gets one `wait_fired` job, which takes
every firing still pending at its brief (DB 196). Later firings join it until
then, none extending the window, and those after its brief wait for the next
run, placed once this one has ended. The window counts from each firing's
`fired_at`, so a restart reads the same rows; the tick is its granularity, so
a run is placed between the window and one tick later.

During a roll two processes run the batcher at once; each places a run only
under its Project's row, held exclusively, and the Wait's, and reads there
that none is in flight (`WaitService.hold_batch`): one run per batch.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.services.supervisor import Supervisor

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)

TIMER = "wait-batch"


class WaitBatcher:
    def __init__(
        self,
        container: "ServiceContainer",
        supervisor: Supervisor,
        quiet_window_seconds: float,
    ) -> None:
        """Register the timer, which needs the controller: a run starts
        through the gate in the store.

        Args:
            container: Gives each tick the waits' and the jobs' services on
                its session
            supervisor: Runs the timer on its tick
            quiet_window_seconds: How old a wait's oldest pending firing is
                before its run is placed
        """
        self._container = container
        self._quiet_window = timedelta(seconds=quiet_window_seconds)
        supervisor.register_timer(TIMER, self.run, needs_controller=True)

    def run(self, db: Session) -> None:
        """The tick: a run placed for each wait whose batch is due, in `db`'s
        transaction, the scheduler's."""
        cutoff = datetime.now(UTC) - self._quiet_window
        waits = self._container.wait_service(db=db)
        jobs = self._container.job_service(db=db)
        placed = 0
        for project_id, wait_id in waits.batches_due(cutoff):
            held = waits.hold_batch(project_id, wait_id, cutoff)
            if held is None:
                continue
            jobs.wait_fired(*held)
            placed += 1
        if placed:
            logger.info("%d runs placed for waits' firings", placed)
