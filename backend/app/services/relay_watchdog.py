"""The relays' watchdog: the fleet stream's corroboration of the turns in flight
(design 2 §9.3, D004).

A Turn ends on its response stream's `result` frame and on nothing else. The
watchdog restarts a relay this process has open when the fleet stream says its
turn is no longer running: its controller session not working on two ticks in a
row, the environment running with no such session on two ticks in a row, the
environment's pod restarted, or the environment stopped elsewhere — `stopping`,
`stopped` or `deleting`, which no restart reads as. The relay's run then reopens
the stream, which delivers the buffered `result` of a turn that ended, carries
on with one that did not, meets the session gone and resumes it, or meets the
environment stopped and stops the Session (§9.6). The fleet consumer writes no
Session.
"""

import logging
import uuid

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from app.models import Environment, Turn
from app.models import Session as AgentSession
from app.models.reference import SessionState
from app.services.fleet_consumer import FleetConsumer
from app.services.relay_service import RELAY_JOB
from app.services.supervisor import Supervisor

logger = logging.getLogger(__name__)

WATCHDOG_TIMER = "relay-watchdog"

_STOPPED_ELSEWHERE = ("stopping", "stopped", "deleting")


class RelayWatchdog:
    """Restarts the relays whose turn the fleet stream no longer shows running."""

    def __init__(self, supervisor: Supervisor, fleet_consumer: FleetConsumer) -> None:
        """Register the watchdog as a timer.

        Args:
            supervisor: Runs the watchdog on its tick, and restarts the relays
            fleet_consumer: The latest state and session set of each environment
        """
        self._supervisor = supervisor
        self._fleet = fleet_consumer
        # The Sessions the previous tick found amiss, and the restart count
        # of each environment a Session ran in then.
        self._suspect: set[uuid.UUID] = set()
        self._restart_counts: dict[str, int] = {}
        supervisor.register_timer(WATCHDOG_TIMER, self.run, needs_controller=True)

    def run(self, db: Session) -> None:
        """The watchdog's tick: the relay of every Session with a turn
        relayed, `running` or stopped under its turn, if this process has it
        open, restarted when the fleet stream says so."""
        stopped_under_turn = and_(
            AgentSession.state_code == SessionState.STOPPED,
            exists().where(Turn.session_id == AgentSession.id, Turn.ended_at.is_(None)),
        )
        sessions = db.execute(
            select(
                AgentSession.id,
                Environment.id,
                AgentSession.controller_session,
            )
            .join(Environment, Environment.id == AgentSession.environment_id)
            .where(
                or_(
                    AgentSession.state_code == SessionState.RUNNING,
                    stopped_under_turn,
                ),
                AgentSession.controller_session.is_not(None),
            )
            .order_by(AgentSession.id)
        ).all()
        restarted = self._restarted({env_id for _, env_id, _ in sessions})
        suspect: set[uuid.UUID] = set()
        for session_id, env_id, name in sessions:
            if env_id in restarted:
                self._restart(session_id, f"environment {env_id} restarted")
                continue
            environment = self._fleet.environment(env_id)
            if environment is not None and environment.status in _STOPPED_ELSEWHERE:
                self._restart(
                    session_id, f"environment {env_id} is {environment.status}"
                )
                continue
            cause = self._amiss(env_id, name)
            if cause is None:
                continue
            if session_id in self._suspect:
                self._restart(session_id, cause)
            else:
                suspect.add(session_id)
        self._suspect = suspect

    def _restarted(self, env_ids: set[str]) -> set[str]:
        """The environments whose pod's restart count moved since the last
        tick."""
        counts: dict[str, int] = {}
        moved: set[str] = set()
        for env_id in env_ids:
            environment = self._fleet.environment(env_id)
            if environment is None or environment.pod is None:
                if env_id in self._restart_counts:
                    counts[env_id] = self._restart_counts[env_id]
                continue
            count = environment.pod.restart_count
            previous = self._restart_counts.get(env_id)
            if previous is not None and count != previous:
                moved.add(env_id)
            counts[env_id] = count
        self._restart_counts = counts
        return moved

    def _amiss(self, env_id: str, name: str | None) -> str | None:
        """What the latest `sessions` frame says is amiss with the Session's
        controller session; None when nothing is, or the stream is down."""
        views = self._fleet.sessions(env_id)
        if views is None:
            return None
        view = next((view for view in views if view.name == name), None)
        if view is None:
            environment = self._fleet.environment(env_id)
            if environment is None or environment.status != "running":
                return None
            return f"environment {env_id} has no session {name}"
        if not view.working:
            return f"its session {name} is not working"
        return None

    def _restart(self, session_id: uuid.UUID, cause: str) -> None:
        if self._supervisor.interrupt_loop(RELAY_JOB, str(session_id)):
            logger.info("Restarted the relay of session %s: %s", session_id, cause)
