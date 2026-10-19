"""Environments on demand, and the shutdown timer (design 2 §13.2, §13.3; F88.1,
F73.1).

Pilot starts an environment knowing whether it started it, and stops only what
it started: `server_started_at` is set when Pilot's own `start` scheduled the
bring-up, and the shutdown timer stops an environment only while that is set,
the environment is not exempt, and no Session is `running` or `starting` there.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import Exists, Select, exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.core_exceptions import ExternalServiceException
from app.database import scoped_session
from app.models import Environment
from app.models import Session as AgentSession
from app.models.reference import SessionState
from app.services.controller_client import (
    ControllerClient,
    ControllerEnvironment,
    ControllerProblem,
    ControllerProblemType,
)
from app.services.supervisor import Supervisor

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)

SHUTDOWN_TIMER = "environment-shutdown"

_BUSY_STATES = (SessionState.RUNNING, SessionState.STARTING)
_FAILED_SETTLES = ("error", "stopped", "deleting")


def reported_columns(
    environment: ControllerEnvironment, seen_at: datetime
) -> dict[str, Any]:
    """The columns of an Environment row the controller's report gives (§13.1).

    A null `name` is unset at the controller, whose callers fall back to the
    environment id.
    """
    return {
        "name": environment.name or environment.env_id,
        "last_state": environment.status,
        "last_seen_at": seen_at,
        "exempt": environment.exempt,
    }


class EnvironmentStartFailed(ExternalServiceException):
    """The controller refused the start, or the environment settled other than
    `running`: a session start fails on it (F125)."""

    def __init__(self, env_id: str, cause: str) -> None:
        self.env_id = env_id
        super().__init__(f"start environment {env_id}", cause)


class EnvironmentService:
    """Starts environments, and arms, clears and runs their shutdown timer."""

    def __init__(
        self,
        container: "ServiceContainer",
        supervisor: Supervisor,
        stop_after_seconds: float,
    ) -> None:
        """Register the shutdown timer, whose reconcile is its tick.

        Args:
            container: Gives the start its database sessions and the client
            supervisor: Runs the shutdown timer on its tick
            stop_after_seconds: How long an environment Pilot started stands
                idle before the timer stops it
        """
        self._container = container
        self._stop_after = timedelta(seconds=stop_after_seconds)
        supervisor.register_timer(
            SHUTDOWN_TIMER, self.run_shutdown_timer, needs_controller=True
        )

    def ensure_environment(self, env_id: str) -> None:
        """Make the environment's row from the controller's own report, on
        Pilot's first touch of it; a row that exists is left as it is.

        Raises:
            ControllerProblem: `not-found` if the controller has no such
                environment
        """
        with scoped_session(self._container) as db:
            if db.get(Environment, env_id) is not None:
                return
        report = self._client().get_environment(env_id)
        with scoped_session(self._container) as db:
            db.execute(
                insert(Environment)
                .values(id=env_id, **reported_columns(report, datetime.now(UTC)))
                .on_conflict_do_nothing(index_elements=[Environment.id])
            )

    def start(self, env_id: str) -> ControllerEnvironment:
        """Bring the environment up and wait until it settles (§13.2).

        The start goes without `wait`, since only then does its answer say
        whether this call scheduled the bring-up: on `202` Pilot started it, and
        `server_started_at` is set in a transaction of its own before the wait;
        on `200` it was running already, and nothing is set. Then the single
        `GET` with `wait=settled`, after which the shutdown timer is armed if
        nothing runs or starts there.

        Returns:
            The environment as the wait left it, `running`

        Raises:
            EnvironmentStartFailed: The controller refused the start (`409
                admission-blocked`), or the environment settled `error`,
                `stopped` or `deleting`
            ExternalServiceException: The wait ran out before it settled, or
                the controller failed otherwise
        """
        self.ensure_environment(env_id)
        client = self._client()
        try:
            outcome = client.start_environment(env_id)
        except ControllerProblem as problem:
            if problem.problem_type is not ControllerProblemType.ADMISSION_BLOCKED:
                raise
            raise EnvironmentStartFailed(
                env_id, f"the controller refused it: {problem.title}"
            ) from problem
        if outcome.started:
            with scoped_session(self._container) as db:
                _lock(db, env_id).server_started_at = datetime.now(UTC)
            logger.info("Started environment %s", env_id)
        else:
            logger.info("Environment %s was running already", env_id)

        settled = client.get_environment(env_id, wait="settled")
        with scoped_session(self._container) as db:
            self.arm_shutdown_timer(db, env_id)
        if settled.status in _FAILED_SETTLES:
            raise EnvironmentStartFailed(env_id, f"it settled {settled.status}")
        if settled.status != "running":
            raise ExternalServiceException(
                f"start environment {env_id}",
                f"it was still {settled.status} when the wait ran out",
            )
        return settled

    def arm_shutdown_timer(self, db: Session, env_id: str) -> None:
        """Set `stop_due_at` to now plus ENVIRONMENT_STOP_AFTER_SECONDS when Pilot
        started the environment, it is not exempt, and no Session is `running`
        or `starting` there; otherwise leave it as it is.

        It reads the Sessions under the Environment row's lock, so of two
        Sessions there whose turns end at once, the later's call arms it,
        whether each runs in the transaction that ended its Session's turn or
        after its commit.
        """
        self._arm(db, _lock(db, env_id))

    def clear_shutdown_timer(self, db: Session, env_id: str) -> None:
        """Clear `stop_due_at`, in the transaction that makes a Session there
        `running` or `starting`."""
        _lock(db, env_id).stop_due_at = None

    def run_shutdown_timer(self, db: Session) -> None:
        """The shutdown timer's tick, and its reconcile.

        Stops every overdue environment Pilot started, not exempt, with no
        Session `running` or `starting` there, and clears both its columns. Then
        arms every such environment that has no `stop_due_at`, which a restart
        between a Session's end and its arm leaves. Each environment's action is
        a transaction of its own, under the row's lock: a row another process's
        tick holds is skipped.
        """
        now = datetime.now(UTC)
        overdue = db.scalars(
            select(Environment.id)
            .where(Environment.stop_due_at <= now)
            .order_by(Environment.stop_due_at, Environment.id)
        ).all()
        for env_id in overdue:
            self._stop_if_overdue(db, env_id, now)
            db.commit()

        unarmed = db.scalars(
            select(Environment.id)
            .where(
                Environment.stop_due_at.is_(None),
                Environment.server_started_at.is_not(None),
                Environment.exempt.is_(False),
                ~_busy(Environment.id),
            )
            .order_by(Environment.id)
        ).all()
        for env_id in unarmed:
            row = _try_lock(db, env_id)
            if row is not None and row.stop_due_at is None:
                self._arm(db, row)
            db.commit()

    def _stop_if_overdue(self, db: Session, env_id: str, now: datetime) -> None:
        row = _try_lock(db, env_id)
        if (
            row is None
            or row.stop_due_at is None
            or row.stop_due_at > now
            or not _stoppable(db, row)
        ):
            return
        due = row.stop_due_at
        try:
            self._client().stop_environment(env_id)
        except ControllerProblem as problem:
            if problem.problem_type is not ControllerProblemType.NOT_FOUND:
                raise
            logger.info(
                "Environment %s is gone: its shutdown, due %s, is cleared",
                env_id,
                due.isoformat(),
            )
        else:
            logger.info("Stopped environment %s, due %s", env_id, due.isoformat())
        row.stop_due_at = None
        row.server_started_at = None

    def _arm(self, db: Session, row: Environment) -> None:
        if not _stoppable(db, row):
            return
        row.stop_due_at = datetime.now(UTC) + self._stop_after
        logger.info(
            "Armed the shutdown of environment %s, due %s",
            row.id,
            row.stop_due_at.isoformat(),
        )

    def _client(self) -> ControllerClient:
        client: ControllerClient = self._container.controller_client()
        return client


def _lock(db: Session, env_id: str) -> Environment:
    """The Environment row, locked and read afresh."""
    return db.scalars(_locking(env_id)).one()


def _try_lock(db: Session, env_id: str) -> Environment | None:
    """The Environment row, locked and read afresh; None while another
    transaction holds it."""
    return db.scalars(_locking(env_id, skip_locked=True)).one_or_none()


def _locking(env_id: str, *, skip_locked: bool = False) -> Select[Environment]:
    return (
        select(Environment)
        .where(Environment.id == env_id)
        .with_for_update(skip_locked=skip_locked)
        .execution_options(populate_existing=True)
    )


def _busy(env_id: InstrumentedAttribute[str] | str) -> Exists:
    """Whether a Session is `running` or `starting` in the environment."""
    return exists().where(
        AgentSession.environment_id == env_id,
        AgentSession.state_code.in_(_BUSY_STATES),
    )


def _stoppable(db: Session, row: Environment) -> bool:
    """Whether the server may stop the environment now: it started it, it is
    not exempt, and no Session is `running` or `starting` there."""
    if row.server_started_at is None or row.exempt:
        return False
    return not db.scalar(select(_busy(row.id)))
