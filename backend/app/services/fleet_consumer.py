"""The fleet consumer: the Environment rows Pilot has, kept current from the
controller's fleet stream (design 2 §8.2, §13.1), and the subscription's usage
readings handed to the usage service (design 4 §6).

On every connect it subscribes to `/stream`, lists the environments, applies the
list, and then the frames. It updates the rows that exist and creates none.

The stream down is the controller unreachable (design 2 §13.4): its failure to
open or its drop turns the outage on, and its reconnect turns it off.
"""

import logging
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from prometheus_client import Gauge
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core_exceptions import ExternalServiceException
from app.database import scoped_session
from app.models import Environment
from app.services.controller_client import (
    ControllerClient,
    ControllerEnvironment,
    EnvironmentList,
    FleetFrame,
    GoneFrame,
    SessionsFrame,
    SessionView,
    StateFrame,
    UsageFrame,
)
from app.services.controller_outage import ControllerOutage
from app.services.environment_service import GONE, reported_columns
from app.services.supervisor import LoopHandle, Supervisor

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)

FLEET_JOB = "fleet"

FLEET_STREAM_CONNECTED = Gauge(
    "pilot_fleet_stream_connected",
    "1 while the fleet consumer holds the controller's /stream open, 0 otherwise",
)


class FleetConsumer:
    """Keeps the Environment rows current, and each environment's latest
    state and session set; hands on each usage reading."""

    def __init__(
        self,
        container: "ServiceContainer",
        supervisor: Supervisor,
        controller_outage: ControllerOutage,
    ) -> None:
        """Register the `fleet` job, whose reconcile starts its loop.

        Args:
            container: Gives each update its database session, and the client
            supervisor: Runs the loop from STARTUP, and restarts it after a drop
            controller_outage: Holds on while the stream is down
        """
        self._container = container
        self._supervisor = supervisor
        self._outage = controller_outage
        self._lock = threading.Lock()
        self._environments: dict[str, ControllerEnvironment] = {}
        self._sessions: dict[str, tuple[SessionView, ...]] = {}
        supervisor.register_job(
            FLEET_JOB, needs_controller=True, reconcile=self._reconcile
        )

    def sessions(self, env_id: str) -> tuple[SessionView, ...] | None:
        """The environment's session set, as the latest `sessions` frame gave it;
        None while the stream is down, and for an environment it has not given."""
        with self._lock:
            return self._sessions.get(env_id)

    def environment(self, env_id: str) -> ControllerEnvironment | None:
        """The environment as the latest list or `state` frame gave it; None
        while the stream is down, and for an environment it has not given."""
        with self._lock:
            return self._environments.get(env_id)

    def _reconcile(self, db: Session) -> None:
        # No rows of its own: each connect's list is its reconcile.
        self._supervisor.start_loop(FLEET_JOB, self._consume)

    def _consume(self, handle: LoopHandle) -> None:
        try:
            self._connect(handle)
        except ExternalServiceException:
            self._outage.fleet_stream_down()
            raise

    def _connect(self, handle: LoopHandle) -> None:
        client: ControllerClient = self._container.controller_client()
        # The list is applied before the frames that came while it was in
        # flight: a `gone` frame carries no state, and a list applied after it
        # would bring the departed environment back (controller-api.md, the
        # state channel).
        with client.open_fleet_stream() as stream, handle.holding(stream):
            try:
                listing = client.list_environments()
                self._apply_listing(listing)
                FLEET_STREAM_CONNECTED.set(1)
                logger.info(
                    "Fleet stream connected; %d environments listed",
                    len(listing.items),
                )
                self._outage.fleet_stream_up()
                for frame in stream:
                    self._apply(frame)
            finally:
                FLEET_STREAM_CONNECTED.set(0)
                with self._lock:
                    self._environments.clear()
                    self._sessions.clear()

    def _apply_listing(self, listing: EnvironmentList) -> None:
        seen_at = datetime.now(UTC)
        reported = sorted(listing.items, key=lambda environment: environment.env_id)
        listed = {environment.env_id for environment in reported}
        listed.update(listing.unprojectable)
        with self._lock:
            self._environments.update(
                (environment.env_id, environment) for environment in reported
            )
        with scoped_session(self._container) as db:
            for environment in reported:
                _report(db, environment, seen_at)
            db.execute(
                update(Environment)
                .where(Environment.id.not_in(listed))
                .values(last_state=GONE)
                .execution_options(synchronize_session=False)
            )

    def _apply(self, frame: FleetFrame) -> None:
        match frame:
            case StateFrame(environment=environment):
                with self._lock:
                    self._environments[environment.env_id] = environment
                with scoped_session(self._container) as db:
                    _report(db, environment, datetime.now(UTC))
            case GoneFrame(env_id=env_id):
                with self._lock:
                    self._environments.pop(env_id, None)
                    self._sessions.pop(env_id, None)
                with scoped_session(self._container) as db:
                    db.execute(
                        update(Environment)
                        .where(Environment.id == env_id)
                        .values(last_state=GONE)
                        .execution_options(synchronize_session=False)
                    )
            case SessionsFrame(env_id=env_id, sessions=sessions):
                with self._lock:
                    self._sessions[env_id] = sessions
            case UsageFrame(reading=reading):
                self._container.usage_service().receive(reading)


def _report(db: Session, environment: ControllerEnvironment, seen_at: datetime) -> None:
    """Update the environment's row, if Pilot has one, from the controller's
    report; an update holds the row's lock. An exempt environment is never
    armed (DB Environment `stop_due_at`)."""
    values = reported_columns(environment, seen_at)
    if environment.exempt:
        values["stop_due_at"] = None
    db.execute(
        update(Environment)
        .where(Environment.id == environment.env_id)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
