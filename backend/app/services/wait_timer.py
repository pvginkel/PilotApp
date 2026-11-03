"""The waits' timer (design 2 §8.2, TD §4.7): on the scheduler's tick, each open
timed wait whose due time has passed fires `due`, once (F27.2, DB 198), its
first tick after a restart firing what came due while no process ran. The
firing's run is the batcher's.

During a roll two processes run the timer at once; each fires a wait only
under its Wait's row, read there with no `due` firing, and skips a row the
other holds (`WaitService.fire_due`).
"""

import logging
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.services.supervisor import Supervisor

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)

TIMER = "wait-due"


class WaitTimer:
    def __init__(self, container: "ServiceContainer", supervisor: Supervisor) -> None:
        """Register the timer, which needs no controller: a firing is the
        record's alone.

        Args:
            container: Gives each tick the waits' service on its session
            supervisor: Runs the timer on its tick
        """
        self._container = container
        supervisor.register_timer(TIMER, self.run, needs_controller=False)

    def run(self, db: Session) -> None:
        """The tick: fire what is due, in `db`'s transaction, the
        scheduler's."""
        fired = self._container.wait_service(db=db).fire_due()
        if fired:
            logger.info("%d timed waits fired due", fired)
