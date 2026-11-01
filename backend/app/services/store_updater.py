"""The store's update, which the server runs from its row (F144.3; design 5
D2, D4, D6, D7; DB Store Update, assertions 279 to 281).

The job `store-update` runs the unlifted Store Update's sequence on one loop,
from the row's columns. Each phase is a transaction of its own that locks the
row and writes its column once, in order, while it is unwritten and no lift
is asked (`lift_requested_at`):

1. `stopped_at`: every job's and Chat's Session `running` or `starting`
   stopped by Pilot (`SessionStartService.stop_for_update`), one by one, a
   held one left held and a Chat left open; then a wait, bounded by
   `turn_wait_seconds`, for the turns those stops interrupted to end. Past
   it, the store's stop ends what is left as a stop made elsewhere. One gone
   `running` or `starting` since is stopped before the column is written.
2. `reset_at`: the store stopped, reset and started by
   `EnvironmentService.reset` with STORE_ENVIRONMENT_ID, its Environment row
   made first when it has none; written once the reset returns with the store
   running. The step takes a turn across processes (`advisory_turn`): a
   second process's waits for the first's and then finds `reset_at` written,
   rather than stopping the store the first is bringing up. A refusal, a
   settle other than running or any other failure the controller answers is
   the row's `error`, cleared at the next attempt, which the supervisor's
   backoff makes; a call the controller did not answer writes none.
3. `reconciled_at`, the sync's (`reconciled`): the loop ends here, and runs
   again at that commit or when the timer finds it written.
4. `lifted_at`, after each job the update stopped whose item is open and
   which no Work retries is retried once, through a person's Retry, in the
   order the jobs were made, each in a transaction of its own under the row's
   lock (DB 281): its retry placed held behind its project's held jobs, a
   refusal logged and the job's Retry left to a person. A stopped turn still
   ending, which that Retry refuses too, holds the lift to a later run. Once
   `lifted_at` commits, the held starts are released, the nudges sent and the
   conditions told. The server retries no other job (D078).

A lift asked goes to 4 from wherever the sequence stands. The job's reconcile
at STARTUP and the timer `store-update`, on every tick, run the loop while an
update is unlifted and not waiting for the sync, so a roll, a crash or an
outage costs a restart of the sequence and never a phase: a second process
meets the columns the first wrote, and a reset cut before `reset_at` is made
again. The command that makes an update and asks its lift tells no one: the
timer tells the conditions when the unlifted update is not the one this
process last told of, made or lifted elsewhere, and the lift tells them at its
commit.
"""

import logging
import threading
import time
import uuid
from datetime import UTC, datetime
from enum import Enum, auto
from typing import TYPE_CHECKING

from sqlalchemy import Exists, Select, exists, select
from sqlalchemy.orm import Session

from app.core_exceptions import ExternalServiceException
from app.database import scoped_session
from app.exceptions import InvalidOperationException
from app.models import Item, StoreUpdate, Work
from app.models import Session as AgentSession
from app.models.reference import SessionState
from app.services.advisory_turn import advisory_turn
from app.services.controller_client import ControllerUnreachable
from app.services.environment_service import EnvironmentService
from app.services.job_service import TURN_ENDING
from app.services.session_start_service import SessionStartService
from app.services.start_gate import CHAT_KIND, JOB_KIND
from app.services.store_update_service import stopped_by, unlifted
from app.services.supervisor import LoopHandle, Supervisor
from app.utils.after_commit import after_commit

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)

STORE_UPDATE_JOB = "store-update"

STORE_UPDATE_TIMER = "store-update"

TURN_WAIT_SECONDS = 60.0
"""How long the update waits, past its stops, for the turns they interrupted
to end before the store's stop (design 5 D4)."""

TURN_POLL_SECONDS = 0.5
"""The wait between two reads of those turns."""

RESET_LOCK = 279
"""The first key of the reset's turn (`advisory_turn`), its second 0."""


class _Phase(Enum):
    STOP = auto()
    RESET = auto()
    RECONCILE = auto()
    LIFT = auto()


class StoreUpdater:
    """Runs the unlifted Store Update's sequence, and tells the conditions
    when the update turns."""

    def __init__(
        self,
        container: "ServiceContainer",
        supervisor: Supervisor,
        environment_service: EnvironmentService,
        session_start_service: SessionStartService,
        store_environment_id: str,
        turn_wait_seconds: float = TURN_WAIT_SECONDS,
        turn_poll_seconds: float = TURN_POLL_SECONDS,
    ) -> None:
        """Register the job `store-update`, whose one loop runs the sequence
        and whose reconcile runs it at STARTUP, and its timer.

        Args:
            container: Gives each phase its database session, and the
                conditions
            supervisor: Runs the loop and the timer
            environment_service: Makes the store's row and resets the store
            session_start_service: Stops the store's sessions, and releases
                the held starts and sends the nudges at the lift
            store_environment_id: The store, the one environment the update
                resets
            turn_wait_seconds: The bound of the wait for the stopped turns
            turn_poll_seconds: The wait between two reads of them
        """
        self._container = container
        self._supervisor = supervisor
        self._environments = environment_service
        self._starts = session_start_service
        self._store = store_environment_id
        self._turn_wait = turn_wait_seconds
        self._turn_poll = turn_poll_seconds
        self._lock = threading.Lock()
        self._told: int | None = None
        supervisor.register_job(
            STORE_UPDATE_JOB, needs_controller=True, reconcile=self._reconcile
        )
        supervisor.register_timer(
            STORE_UPDATE_TIMER, self.run_timer, needs_controller=False
        )

    def reconciled(self, db: Session) -> None:
        """The store's sidecar posted a manifest with an empty shadow, a fresh
        sidecar's, in the caller's transaction: the unlifted update's
        `reconciled_at` written under its lock when it has `stopped_at` and
        neither `reconciled_at` nor a lift asked (DB 279), and the sequence
        run once that commits."""
        update = db.scalars(
            select(StoreUpdate)
            .where(StoreUpdate.lifted_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one_or_none()
        if (
            update is None
            or update.stopped_at is None
            or update.reconciled_at is not None
            or update.lift_requested_at is not None
        ):
            return
        update.reconciled_at = datetime.now(UTC)
        after_commit(self._wake)
        logger.info("The store's update %s: its tree reconciled", update.id)

    def run_timer(self, db: Session) -> None:
        """The tick: the conditions told when the unlifted update turned, and
        the sequence run while one stands not waiting for the sync."""
        update = unlifted(db)
        self._turned(None if update is None else update.id)
        self._take_up(update)

    def run(self, handle: LoopHandle) -> None:
        """The loop's run: the unlifted update's next phase, as its row has
        it, until it waits for the sync or is lifted."""
        while not handle.stopping:
            with scoped_session(self._container) as db:
                update = unlifted(db)
                if update is None:
                    return
                update_id, phase = update.id, _phase(update)
            match phase:
                case _Phase.STOP:
                    self._stop(handle, update_id)
                case _Phase.RESET:
                    self._reset(update_id)
                case _Phase.RECONCILE:
                    return
                case _Phase.LIFT:
                    self._lift(update_id)
                    return

    def _reconcile(self, db: Session) -> None:
        """At STARTUP: the sequence of an update left unlifted run again."""
        self._take_up(unlifted(db))

    def _take_up(self, update: StoreUpdate | None) -> None:
        if update is not None and _phase(update) is not _Phase.RECONCILE:
            self._supervisor.start_loop(STORE_UPDATE_JOB, self.run)

    def _wake(self) -> None:
        self._supervisor.start_loop(STORE_UPDATE_JOB, self.run, again=True)

    def _stop(self, handle: LoopHandle, update_id: int) -> None:
        """Phase 1: the store's sessions stopped, the wait for their turns,
        then `stopped_at`, unless a lift is asked meanwhile."""
        with scoped_session(self._container) as db:
            stopping = self._starts.stoppable_for_update(db)
        for session_id in stopping:
            if handle.stopping:
                return
            with scoped_session(self._container) as db:
                if not _stopping(_locked(db, update_id)):
                    return
                self._starts.stop_for_update(db, session_id)
        deadline = time.perf_counter() + self._turn_wait
        while True:
            with scoped_session(self._container) as db:
                update = db.get_one(StoreUpdate, update_id, populate_existing=True)
                if not _stopping(update):
                    return
                ending = db.scalar(select(_turns_ending(update.made_at)))
            if not ending or time.perf_counter() >= deadline:
                break
            if handle.wait(self._turn_poll):
                return
        with scoped_session(self._container) as db:
            update = _locked(db, update_id)
            if not _stopping(update) or self._starts.stoppable_for_update(db):
                return
            update.stopped_at = datetime.now(UTC)
            logger.info(
                "The store's update %s: stopped %d sessions", update_id, len(stopping)
            )

    def _reset(self, update_id: int) -> None:
        """Phase 2, in the reset's turn: the store reset, then `reset_at`; a
        failure the controller answers the row's `error`, and raised for the
        backoff."""
        with advisory_turn(self._container.session_maker(), RESET_LOCK, 0):
            with scoped_session(self._container) as db:
                update = _locked(db, update_id)
                if not _resetting(update):
                    return
                update.error = None
            try:
                with scoped_session(self._container) as db:
                    self._environments.ensure_environment(db, self._store)
                self._environments.reset(self._store)
            except ControllerUnreachable:
                raise
            except ExternalServiceException as error:
                with scoped_session(self._container) as db:
                    update = _locked(db, update_id)
                    if _resetting(update):
                        update.error = str(error)
                raise
            with scoped_session(self._container) as db:
                update = _locked(db, update_id)
                if _resetting(update):
                    update.reset_at = datetime.now(UTC)
                    logger.info(
                        "The store's update %s: reset the store %s",
                        update_id,
                        self._store,
                    )

    def _lift(self, update_id: int) -> None:
        """Phase 4: the jobs the update stopped retried, then `lifted_at`, and
        once it commits the gate opened; nothing more while a stopped turn is
        still ending."""
        with scoped_session(self._container) as db:
            update = db.get_one(StoreUpdate, update_id, populate_existing=True)
            if update.lifted_at is not None:
                return
            retrying = db.scalars(_retriable(update)).all()
        for job_id in retrying:
            with scoped_session(self._container) as db:
                update = _locked(db, update_id)
                if update.lifted_at is not None or not self._retry(db, update, job_id):
                    return
        with scoped_session(self._container) as db:
            update = _locked(db, update_id)
            if update.lifted_at is not None:
                return
            update.lifted_at = datetime.now(UTC)
            after_commit(self._lifted)
            logger.info("The store's update %s: lifted", update_id)

    def _retry(self, db: Session, update: StoreUpdate, job_id: uuid.UUID) -> bool:
        """Under the update's lock, while the job is one to retry still: a
        person's Retry of it, or that Retry's refusal logged; False when the
        refusal is its stopped turn still ending."""
        if (
            db.scalars(_retriable(update).where(AgentSession.id == job_id)).first()
            is None
        ):
            return True
        try:
            self._container.job_service().retry(job_id)
        except InvalidOperationException as refused:
            if refused.cause == TURN_ENDING:
                logger.info(
                    "The store's update %s: lifts once %s's stopped turn ends",
                    update.id,
                    job_id,
                )
                return False
            logger.info(
                "The store's update %s: left %s to a person's Retry: %s",
                update.id,
                job_id,
                refused.message,
            )
            return True
        logger.info("The store's update %s: retried %s", update.id, job_id)
        return True

    def _lifted(self) -> None:
        self._starts.release_held()
        self._starts.send_nudges()
        with self._lock:
            self._told = None
        self._container.condition_service().tell()

    def _turned(self, update_id: int | None) -> None:
        """The conditions told when the unlifted update is not the one this
        process last told of."""
        with self._lock:
            if update_id == self._told:
                return
            self._told = update_id
        self._container.condition_service().tell()


def _phase(update: StoreUpdate) -> _Phase:
    """The update's next phase, from its row."""
    if update.lift_requested_at is not None:
        return _Phase.LIFT
    if update.stopped_at is None:
        return _Phase.STOP
    if update.reset_at is None:
        return _Phase.RESET
    if update.reconciled_at is None:
        return _Phase.RECONCILE
    return _Phase.LIFT


def _stopping(update: StoreUpdate) -> bool:
    return (
        update.lifted_at is None
        and update.lift_requested_at is None
        and update.stopped_at is None
    )


def _resetting(update: StoreUpdate) -> bool:
    return (
        update.lifted_at is None
        and update.lift_requested_at is None
        and update.stopped_at is not None
        and update.reset_at is None
    )


def _locked(db: Session, update_id: int) -> StoreUpdate:
    """The update's row, locked and read afresh."""
    return db.scalars(
        select(StoreUpdate)
        .where(StoreUpdate.id == update_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()


def _retriable(update: StoreUpdate) -> Select[uuid.UUID]:
    """The jobs the update stopped whose item is open and which no Work
    retries, in the order they were made (DB 281)."""
    return (
        select(AgentSession.id)
        .join(Item, Item.id == AgentSession.id)
        .join(Work, Work.id == AgentSession.id)
        .where(stopped_by(update), Item.done_at.is_(None), Work.retried_by_id.is_(None))
        .order_by(AgentSession.created_at, AgentSession.id)
    )


def _turns_ending(since: datetime) -> Exists:
    """Whether a job's or a Chat's Session stopped since `since` has its turn
    still in flight, which its relay ends at the interrupt's result."""
    return exists().where(
        AgentSession.kind_code.in_((JOB_KIND, CHAT_KIND)),
        AgentSession.state_code == SessionState.STOPPED,
        AgentSession.stopped_at >= since,
        AgentSession.turns > 0,
        AgentSession.turn_ended_at.is_(None),
    )
