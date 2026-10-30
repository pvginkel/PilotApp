"""The session start: a work item's Session brought up end to end, from its
rows to its brief's send (design 2 §13.2, §13.4, §13.5, §7.1; F88.1, F125,
F141.5, F143.1; decision 38), and a brain session's, a chat's, in the store
(design 3 §12; F50, F81).

`start_work` places a work item by repository, `owner/Name`, in the caller's
transaction: its Item, its Work, which keeps the repository, its Session, with
no Environment until its start provides one (DB 107), and its first Turn, the
brief. The gate (§13.4) decides the Session's state: `held` while it is
closed, with nothing run for it, else `starting`. A `starting` Session's start
loop, `start:<id>`, runs once that commits: it takes a free environment of
Pilot's own made from the repository, the take committed before any controller
call and the environment then renamed after the Project and reset, or creates
one, whose row commits before its bring-up is waited on; then it creates the
headless session, Pilot's MCP server handed to it with a token minted for it
(`PilotServer`), and sends the brief, whose `202` starts the relay. The token's
hash is the Session's from the commit that makes the create's controller
session its own, before any Turn goes to that session. Each phase the
start enters is a `server` record in no Turn (DB assertion 220), and each such
record rebuilds the current line in its transaction.

A brain session's start, its rows written by its caller (`start_brain`), passes
the gate as a work item's does, taking no slot; a chat's is never held for the
pause, and a job's waits while another job of its project is before it
(F59.2). A job is placed with no Turn: its brief is composed from the record
as it stands when it leaves the queue or the pause (F59), as its first Turn,
its Work's switch the one that brief states (F54.7).
Its environment is the store (`STORE_ENVIRONMENT_ID`): its row made on Pilot's
first touch, then started (`EnvironmentService.start`); the store is exempt, so
no timer of Pilot's stops it. Its create is boxed (`scoped_create`), and a
`422` while its project's folder is not yet on disk is made again for a bounded
time (`FOLDER_WAIT_SECONDS`), then fails the start with the controller's title
(TD §4.2; F125).

A start that meets a call the controller does not answer goes back to `held`
with its rows as they stand, the outage on (DB 230). Every other failure of the
controller during the start leaves the Session `failed` with its `error` and a
`server` record saying so, its brief no longer in flight, and nothing is
retried (F125).

When the gate may have moved — a usage halt on or off, at a reading or a
stale window's minute (`UsageWatcher`); the outage on or off, off at the
probe's success or the fleet stream's reconnect; a work item's start, which takes its
slot (`WorkSlots.took`); a work item's end, its turn's `result`, its Stop, its
failure or a stop made elsewhere, which frees its slot (`WorkSlots.left`) —
the held Sessions it opens for move to `starting` in `created_at` order, each
under its lock while it is still `held`, a work item whose Project has no
slot passed over, and a job behind another of its project; each loop resumes
its start where the rows left it. A job's end, its last turn's, its failure or
its stop, opens the gate for its project's next job (`WorkSlots.left`). A
work item it still holds has its line told again, its reason read anew. The
probe, the controller's readiness call, runs on the scheduler's tick while the
outage holds.

The lock order (P-45). A start, a Resume and the release take their locks in
one order: the Project's row, then the Session's, then the slot's
(`WorkSlots.lock`), then an Environment's, the release taking a job's
Project's row shared. A start that places a work item
locks its Project's row as `next_seq` does, so its Item's birth takes no lock
stronger than one it holds. The start loop's transactions lock no Project
row: no controller call is made while one is locked.

At STARTUP the job's reconcile runs the start loop of every Session still
`starting`, which resumes where its rows left it, and opens the gate for the
held ones (§8.2). Each write the run makes is conditional on the rows it read,
under the Session's lock, so a second process running the same start during a
roll's overlap (§8.1) changes nothing the first has written.

A work item's Stop ends its Session where it is (F67.1): a turn in flight is
interrupted after the commit, and a start held or under way ends, nothing of it
sent afterwards. Finish and Archive stop every Session of the project so (F5.1,
F128.1), and Reopen a finished project's chat (F5.5); a usage halt's hard stop
every running work item, by Pilot, its nudge owed (F135.6; DB 269). Its Resume
writes a server-own Turn, "continue", or the ended Turn's
message while the Session has no conversation (R15's rule), and passes the gate
as a start does (F67.2): `held`, or `starting`, its loop sending the Turn to
its controller session, or to one created anew, its environment started again,
when that one is gone or its environment is not running (§9.6), never reset. A
Resume with no conversation to continue is a fresh start (review B1): in a
headless session of its own, in its environment reset, or in one taken or
created when it has none or that one is gone or deleting. A work item placed
before slice 020, in an environment Pilot did not create, is never started
there (F143.1; review A2).

A nudge (F135.3, F141.3; DB 232) carries a work item on as a Resume does,
its Turn the nudge's words: owed to one the hard stop stopped, and to one
whose turn ended under a cooperative usage halt or its project's pause
(`RelayService`), it goes once nothing holds it — every usage halt lifted,
the project neither paused, finished nor archived, the item open — on a loop
of its own, `start:nudges`. A halt's turn (`UsageWatcher`) and a project's
resume ask for that loop; so do the job's reconcile, and the nudges' timer on
every tick while one owed is held by nothing. A person's Resume clears the
nudge owed: one continuation, never two.

The close that leaves no document of a work item's ended run open continues its
conversation (`continue_run`; decision 44, F26.7): a new work item placed in the
close's transaction, its Session in the run's environment from then on, never
reset, through the gate as any start. Before its environment is brought up,
its start writes back what the documents it carries still owe (F65.1), and a
write-back the controller refused fails it with the controller's reason
(F125); its Resume owes those again, and sends the continuation's message, not
"continue", while no Turn of its Session has gone out.
"""

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core_exceptions import ExternalServiceException
from app.database import scoped_session
from app.engine.views import ViewService
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import (
    Chat,
    ClarificationRun,
    Document,
    Environment,
    Item,
    Project,
    ProjectTransition,
    Turn,
    User,
    Work,
)
from app.models import Session as AgentSession
from app.models.reference import (
    ProjectState,
    RecordKind,
    SessionState,
    TransitionKind,
    UserKind,
    WorkTrigger,
)
from app.services.controller_client import (
    ControllerClient,
    ControllerEnvironment,
    ControllerProblem,
    ControllerProblemType,
    ControllerUnreachable,
    HeadlessCreateRequest,
    SessionSnapshot,
)
from app.services.controller_outage import ControllerOutage
from app.services.current_line import while_starting
from app.services.environment_service import EnvironmentService
from app.services.pilot_server import PilotServer, unheld_token_hash
from app.services.relay_service import CONTINUE, SESSION_GONE, RelayService
from app.services.session_record_service import (
    SessionRecordService,
    read_records,
    stream_position,
)
from app.services.session_scope import ScopedCreate, scoped_create
from app.services.session_stream_service import SessionStreamService
from app.services.start_gate import (
    JOB_KIND,
    WORK_KIND,
    Held,
    WorkSlots,
    carried,
    held_reason,
    queued,
    setups,
)
from app.services.supervisor import LoopHandle, Supervisor
from app.services.usage_halts import UsageHalts
from app.services.work_status import work_moved
from app.services.write_back_service import WRITE_BACK_REFUSED
from app.utils.after_commit import after_commit

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)

START_JOB = "start"

RELEASE_KEY = "held"
"""The key of the start job's loop that moves the held Sessions on."""

HARD_STOP_KEY = "hard-stop"
"""The key of the start job's loop that stops the running work items under a
usage halt's hard stop."""

NUDGE_KEY = "nudges"
"""The key of the start job's loop that sends the nudges owed."""

PROBE_TIMER = "controller-probe"

NUDGE_TIMER = "nudges"

STARTING = "starting"
"""The `type` of the `server` record that names a phase of the start."""

START_FAILED = "start-failed"
"""The `type` of the `server` record a start that failed writes."""

CREATING = "Creating the session…"

NOT_PILOTS = "its environment is not Pilot's"

PILOTS_OWN = "it is Pilot's own work"
"""Why a person's Stop and Resume do not take a job (F26.3)."""

FOLDER_WAIT_SECONDS = 60.0
"""How long a boxed create refused `422` is made again from its first refusal:
`pilot-sync` writes a project's folder a moment after the record changes (TD
§4.2)."""

FOLDER_RETRY_SECONDS = 2.0
"""The wait between two of those creates."""

STOPPABLE = (SessionState.RUNNING, SessionState.STARTING, SessionState.HELD)
"""The states a Stop ends a Session in: a turn in flight, a start under way or
held at the gate."""

_STOP_REFUSALS = {
    SessionState.IDLE: "its turn has ended",
    SessionState.STOPPED: "it is stopped already",
    SessionState.ENDED: "its session has ended",
    SessionState.FAILED: "it has failed",
}

_CHAT_STOP_REFUSALS = {
    SessionState.IDLE: "it is not answering",
    SessionState.STOPPED: "it was stopped already",
    SessionState.ENDED: "its chat's session has ended",
    SessionState.FAILED: "its chat failed to start",
}

_RESUMABLE = (SessionState.STOPPED, SessionState.FAILED)

_RESUME_REFUSALS = {
    SessionState.HELD: "its start waits at the gate",
    SessionState.STARTING: "it is starting",
    SessionState.RUNNING: "it is running",
    SessionState.IDLE: "its turn has ended",
    SessionState.ENDED: "its session has ended",
}

_NUDGED = "This is a nudge to allow you to complete any outstanding work, if any."

NUDGE = f"The subscription quota ran out. {_NUDGED}"
"""The nudge to a work item found ended under a usage halt (F135.3)."""

NUDGE_AFTER_A_STOP = (
    "Pilot stopped this session at the subscription quota's usage limit, and "
    f"there is quota again. {_NUDGED}"
)
"""The nudge to a work item a usage halt's hard stop stopped (F135.6)."""

NUDGE_AFTER_A_PAUSE = f"The project was paused, and it has been resumed. {_NUDGED}"
"""The nudge to a work item found ended while its project was paused
(F141.3)."""

_DONE_STATUSES = ("ended", "error")
"""A headless session's terminal statuses: it takes no turn."""

_RECORD_PAGE = 32
"""The `server` records one read of a Session's takes, newest first."""

_WAITED_OUT = (
    ControllerProblemType.CONFLICT,
    ControllerProblemType.ENVIRONMENT_UNREADABLE,
)
"""The controller's refusals of a write-back for its own work on the tree or
its share unreadable: a continuation's start waits them out, its loop running
again after its backoff."""


@dataclass(frozen=True)
class _LoopStart:
    # `after_commit()` runs a callback equal to one it holds once.
    starts: "SessionStartService"
    session_id: uuid.UUID

    def __call__(self) -> None:
        self.starts._start_loop(self.session_id)


@dataclass(frozen=True)
class _HeldWritten:
    # `after_commit()` runs a callback equal to one it holds once.
    starts: "SessionStartService"

    def __call__(self) -> None:
        # The gate may have opened between the write's read of it and this
        # commit, its release missing the Session; the release reads the
        # project's pause itself.
        if not self.starts._outage.holds:
            self.starts.release_held()


@dataclass(frozen=True)
class _Pending:
    """A `starting` Session, as its start loop's run reads it."""

    env_id: str | None
    """None until its start provides its environment."""
    bringing_up: bool
    """A bring-up of Pilot's there awaits its settle: its claim has no pod
    yet."""
    unreset: bool
    """The environment is Pilot's own with no claim, for a start on a new
    conversation: a take's or a fresh Resume's, its rename, its stop and its
    reset still to make (review B3)."""
    foreign: bool
    """The Session is a work item's in an environment Pilot did not create:
    placed before slice 020, it is never started there."""
    brain: bool
    """The Session is a chat's or a job's: it runs in the store."""
    controller_session: str | None
    create: ScopedCreate
    turn_id: int
    """The Turn the start sends: the brief, or a Resume's."""
    resuming: bool
    """The Turn is a Resume's: the Session's controller session may be gone,
    or its environment stopped, since it last ran."""

    @property
    def environment(self) -> str:
        # A start past its environment's bring-up has its Environment.
        assert self.env_id is not None
        return self.env_id


class SessionStartService:
    """Brings Sessions up through the gate: writes each `held` or `starting`,
    runs the start loop of each `starting` one, and moves the held ones on
    when the gate opens."""

    def __init__(
        self,
        container: "ServiceContainer",
        supervisor: Supervisor,
        session_streams: SessionStreamService,
        environment_service: EnvironmentService,
        relay_service: RelayService,
        controller_outage: ControllerOutage,
        work_slots: WorkSlots,
        usage_halts: UsageHalts,
        pilot_server: PilotServer,
        controller_configured: bool,
        store_environment_id: str,
        folder_wait_seconds: float = FOLDER_WAIT_SECONDS,
        folder_retry_seconds: float = FOLDER_RETRY_SECONDS,
    ) -> None:
        """Register the `start` job, whose loops are one per Session, one
        that moves the held Sessions on, one that stops the running work
        items under a hard stop and one that sends the nudges owed, and whose
        reconcile runs the start of every Session still `starting`, opens the
        gate and sends the nudges; the probe's timer and the nudges'; and the
        release, on every turn of the outage and every move of the slot's
        count.

        Args:
            container: Gives each start transaction its database session, and
                the client
            supervisor: Runs the start loops and the probe
            session_streams: Woken by the records the start writes
            environment_service: Takes or creates the environment and makes
                its row, renames, resets or starts it, and clears and arms its
                shutdown timer
            relay_service: Sends the brief, and relays its turn
            controller_outage: The gate's outage, which the probe turns off
            work_slots: The gate's slot, whose count a work item's start and
                its end move
            usage_halts: The gate's usage halts, which hold work items alone
            pilot_server: Hands each headless create Pilot's MCP server, with
                a token minted for it
            controller_configured: False refuses every start
            store_environment_id: The store's environment, where every brain
                session runs; empty refuses a brain session's start
            folder_wait_seconds: How long a boxed create refused `422` is made
                again from its first refusal
            folder_retry_seconds: The wait between two of those creates
        """
        self._container = container
        self._supervisor = supervisor
        self._streams = session_streams
        self._environments = environment_service
        self._relays = relay_service
        self._outage = controller_outage
        self._slots = work_slots
        self._halts = usage_halts
        self._pilot_server = pilot_server
        self._controller_configured = controller_configured
        self._store = store_environment_id
        self._folder_wait = folder_wait_seconds
        self._folder_retry = folder_retry_seconds
        supervisor.register_job(
            START_JOB, needs_controller=True, reconcile=self._reconcile
        )
        supervisor.register_timer(PROBE_TIMER, self.run_probe, needs_controller=True)
        supervisor.register_timer(
            NUDGE_TIMER, self.run_nudge_timer, needs_controller=False
        )
        controller_outage.subscribe(self.release_held)
        work_slots.subscribe(self.release_held)

    def start_work(
        self,
        db: Session,
        project_id: uuid.UUID,
        repo: str,
        *,
        title: str,
        brief: str,
        cwd: str,
        plan_task_id: str | None = None,
        agent: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> Work:
        """Place a work item titled `title` on the project's timeline, by the
        repository `repo`, on the plan's task `plan_task_id` when given, and
        write its `work` Session's start, in the caller's transaction: its
        Item, its Work, which keeps `repo`, and its Session one id (DB Work,
        decision 3), its first Turn the brief. The repository, `cwd`, and the
        agent, model and effort where given are taken as the placement gives
        them (F61.1). The Session has no
        Environment until its start provides one (DB 107), and the hash of a
        token no one holds until its create mints the one its controller
        session carries (`run`). It passes the gate (§13.4): `held` while
        the gate is closed for it, with nothing run, its slot counted under
        the slot's lock; else `starting`, its start run once this commits. No
        controller call is made.

        Nothing of a finished or an archived project starts (F5.1, F128.1):
        the project's row is read under the lock its Item's birth takes
        (`next_seq`), so a start and a Finish or an Archive never interleave,
        and two starts of the project take it one after the other.

        Returns:
            The Work

        Raises:
            InvalidOperationException: No controller is configured, or the
                project is finished or archived
            RecordNotFoundException: No Project has the id, or its plan has
                no task `plan_task_id`
        """
        operation = f"place a work item of {repo}"
        if not self._controller_configured:
            raise InvalidOperationException(operation, "no controller is configured")
        project = _standing(db, project_id, births=True)
        refusal = _closed(project)
        if refusal is not None:
            raise InvalidOperationException(operation, refusal)
        held = self._held(db, project, WORK_KIND, queued=False)
        now = datetime.now(UTC)
        session = AgentSession(
            project_id=project_id,
            kind_code=WORK_KIND,
            cwd=cwd,
            agent=agent,
            model=model,
            reasoning_effort=reasoning_effort,
            token_hash=unheld_token_hash(),
            state_code=SessionState.STARTING if held is None else SessionState.HELD,
            turns=1,
            turn_started_at=now,
        )
        db.add(session)
        db.flush()
        db.add(Turn(session_id=session.id, seq=1, message=brief, started_at=now))
        db.flush()
        work = self._container.record_service().place_work(
            project, session, title, plan_task_id, repo=repo
        )
        if held is None:
            self._begin(db, session)
        else:
            after_commit(_HeldWritten(self))
            logger.info("Session %s is held at its start: %s", session.id, held.reason)
        return work

    def held(self, db: Session, project: Project, session: AgentSession) -> Held | None:
        """Why the gate holds the Session of `project` now, read as a screen
        reads it (decision 53); None for a Session that is not `held`, or one
        the gate holds no longer."""
        if session.state_code is not SessionState.HELD:
            return None
        return self._held(
            db,
            project,
            session.kind_code,
            queued=_queued(db, session),
            session=session,
        )

    def start_brain(
        self, db: Session, project: Project, session: AgentSession, operation: str
    ) -> None:
        """A brain Session's start through the gate (§13.4), in the caller's
        transaction, which holds the project's row: `held` while the gate is
        closed for it, else `starting`, its start run once this commits. A
        Chat's, its Turn to send written by the caller, is never held for the
        pause and takes no slot. A job's, placed with no Turn, waits its turn
        behind its project's jobs before it, held for the pause but the
        setup's (`setups`); going at once, it is briefed at its trigger's
        instant, its Session's `created_at` (`_brief`). No controller call is
        made.

        Raises:
            InvalidOperationException: No controller or no store environment
                is configured
        """
        if not self._controller_configured:
            raise InvalidOperationException(operation, "no controller is configured")
        if not self._store:
            raise InvalidOperationException(
                operation, "no store environment is configured"
            )
        held = self._held(
            db, project, session.kind_code, queued=_queued(db, session), session=session
        )
        if held is None:
            session.state_code = SessionState.STARTING
            if _unbriefed(session):
                self._brief(db, project, session, session.created_at)
            self._begin(db, session)
        else:
            session.state_code = SessionState.HELD
            after_commit(_HeldWritten(self))
        self._moved(session, state=True)
        logger.info(
            "Session %s starts%s",
            session.id,
            "" if held is None else f", held: {held.reason}",
        )

    def continue_run(
        self,
        db: Session,
        project: Project,
        run_id: uuid.UUID,
        released: Item,
        message: str,
    ) -> AgentSession:
        """The conversation of the work item `run_id`, its run ended and every
        document it registered closed, continued as a new work item (decision
        44, F26.7), in the caller's transaction, which holds the project's row
        exclusively: titled as the run, its trigger the Item `released` whose
        close released it, as `_resume_conversation` places it.

        Returns:
            The continuation's Session

        Raises:
            InvalidOperationException: The project is archived
        """
        title = db.get_one(Item, run_id).title
        # A work item is titled at its placement.
        assert title is not None
        session = self._resume_conversation(
            db,
            project,
            run_id,
            title,
            message,
            released.id,
            f"continue {_work_named(db, run_id)}",
        )
        logger.info("Session %s continues session %s", session.id, run_id)
        return session

    def clarify(
        self,
        db: Session,
        project: Project,
        pass_id: uuid.UUID,
        run_id: uuid.UUID,
        title: str,
        message: str,
    ) -> AgentSession:
        """The conversation of the work item `run_id` resumed by its
        clarification run (DB decision 63, 254), which puts the questions the
        job `pass_id` asked about its documents to their writer, in the
        caller's transaction, which holds the project's row exclusively:
        titled `title`, with no trigger Item, the pass its role's, as
        `_resume_conversation` places it.

        Returns:
            The clarification run's Session

        Raises:
            InvalidOperationException: The project is finished or archived
        """
        session = self._resume_conversation(
            db, project, run_id, title, message, None, f"place {title}"
        )
        db.add(ClarificationRun(id=session.id, pass_id=pass_id))
        db.flush()
        logger.info(
            "Session %s clarifies session %s on session %s's conversation",
            session.id,
            pass_id,
            run_id,
        )
        return session

    def _resume_conversation(
        self,
        db: Session,
        project: Project,
        run_id: uuid.UUID,
        title: str,
        message: str,
        trigger_item_id: uuid.UUID | None,
        operation: str,
    ) -> AgentSession:
        """A new work item `title` on the conversation of the work item
        `run_id`, its trigger Item `trigger_item_id`, and no Work Trigger, in
        the caller's transaction, which holds the project's row exclusively:
        at the project's next place, on the run's plan task while the plan
        still has it, none once it was removed. Its Session is in the run's
        environment from its placement on, held or not, so the environment is
        never free between the two (DB 240, §13.5), and continues the run's
        conversation, never reset (DB 241), on the run's cwd, agent, model and
        effort, its first Turn `message`; its Work keeps the run's repository.
        It passes the gate as `start_work`'s does, and waits while another
        Session runs or starts on the conversation (DB 183): `held` while the
        gate is closed for it, else `starting`, its start run once this
        commits. No controller call is made.

        Raises:
            InvalidOperationException: The project is finished or archived,
                refused as `operation`
        """
        refusal = _closed(project)
        if refusal is not None:
            raise InvalidOperationException(operation, refusal)
        run = db.get_one(AgentSession, run_id)
        record = self._container.record_service()
        task = db.get_one(Item, run_id).plan_task_id
        if task is not None and not record.in_the_plan(project, task):
            task = None
        now = datetime.now(UTC)
        session = AgentSession(
            project_id=project.id,
            environment_id=run.environment_id,
            kind_code=WORK_KIND,
            conversation_id=run.conversation_id,
            cwd=run.cwd,
            agent=run.agent,
            model=run.model,
            reasoning_effort=run.reasoning_effort,
            token_hash=unheld_token_hash(),
            state_code=SessionState.HELD,
            turns=1,
            turn_started_at=now,
        )
        db.add(session)
        db.flush()
        db.add(Turn(session_id=session.id, seq=1, message=message, started_at=now))
        db.flush()
        held = self._held(db, project, WORK_KIND, queued=False, session=session)
        if held is None:
            session.state_code = SessionState.STARTING
        record.place_work(
            project,
            session,
            title,
            task,
            repo=db.get_one(Work, run_id).repo,
            trigger_item_id=trigger_item_id,
        )
        if held is None:
            self._begin(db, session)
        else:
            after_commit(_HeldWritten(self))
            logger.info("Session %s is held at its start: %s", session.id, held.reason)
        return session

    def run(self, session_id: uuid.UUID, handle: LoopHandle) -> None:
        """The start loop's run, from where the Session's rows left its start:
        the environment brought up and the headless session created while the
        Session has no controller session, then its Turn sent, the brief or a
        Resume's, unless the controller has it already. The create hands the
        session Pilot's MCP server with a token minted for it, whose hash the
        Session takes as it takes the controller session, in the commit before
        the Turn is sent; a Turn to a controller session that stands keeps the
        token its create carried. A Resume's controller
        session that is gone, or whose environment is not running, is given up
        first, a `server` record saying so, and the start goes on from the
        environment. Returns at once for a Session no longer `starting`, and
        between the phases when the loop is told to stop. A continuation's
        start writes back what the documents it carries owe before it brings
        its environment up (`_written_back`). A run a Stop and then
        a Resume overtook, its Session `starting` the Resume's Turn, goes no
        further than its bring-up: it creates and records no controller
        session, sends nothing and fails nothing, and the run the Resume asks
        for starts from the rows (review B1). A controller session another
        process recorded first stands, and the one this run created is left
        to the controller's reaper, as it is for a Session stopped while it
        was created. A call the controller does not answer
        returns the Session to `held`; any other failure fails it (F125), a
        refused create among them, a boxed one refused `422` once its
        folder's wait has passed (`_create_session`).

        The bring-up: a brain Session with no Environment takes the store
        and starts it (`_in_store`); a work item's takes a free one of
        Pilot's own (`_take`), or has one created (`_create`) and its bring-up
        awaited; one whose environment's reset is still to make has it
        renamed after its Project (`_named`) and reset; one whose environment
        has a bring-up of Pilot's still to settle, a create's, a reset's or a
        start's, has it awaited, never a second scheduled; any other has its
        environment started. A Session in an environment Pilot did not create
        fails with nothing called.
        """
        with scoped_session(self._container) as db:
            pending = _pending(db, session_id)
        if pending is None:
            return
        turn_id = pending.turn_id
        if pending.foreign:
            with scoped_session(self._container) as db:
                self._fail(db, session_id, turn_id, NOT_PILOTS, recorded=False)
            return
        if pending.resuming and pending.controller_session is not None:
            try:
                lost = self._lost_reason(
                    pending.environment, pending.controller_session
                )
            except ControllerUnreachable as error:
                with scoped_session(self._container) as db:
                    self._hold(db, session_id, error)
                return
            except ExternalServiceException as error:
                with scoped_session(self._container) as db:
                    self._fail(db, session_id, turn_id, str(error), recorded=False)
                return
            if lost is not None:
                with scoped_session(self._container) as db:
                    pending = self._lost(
                        db, session_id, pending.controller_session, lost
                    )
                if pending is None:
                    return
        if pending.controller_session is None:
            if not self._written_back(session_id, turn_id, handle):
                return
            try:
                if not self._bring_up(session_id, pending) or handle.stopping:
                    return
                with scoped_session(self._container) as db:
                    pending = self._creating(db, session_id, turn_id)
                if pending is None:
                    return
                injected = self._pilot_server.inject(pending.create)
                created = None
                if pending.controller_session is None:
                    created = self._create_session(
                        session_id, pending.environment, injected.request, handle
                    )
                    if created is None:
                        return
            except ControllerUnreachable as error:
                with scoped_session(self._container) as db:
                    self._hold(db, session_id, error)
                return
            except ExternalServiceException as error:
                with scoped_session(self._container) as db:
                    self._fail(db, session_id, turn_id, str(error), recorded=False)
                return
            if created is not None:
                with scoped_session(self._container) as db:
                    session = self._records(db).lock_session(session_id)
                    if not _sends(db, session, turn_id):
                        return
                    if session.controller_session is None:
                        session.controller_session = created.name
                        session.token_hash = injected.token_hash
                        session.started_at = datetime.now(UTC)
                        self._moved(session)
            if handle.stopping:
                return
        with scoped_session(self._container) as db:
            try:
                turn = self._relays.send_turn(db, pending.turn_id)
            except ControllerUnreachable as error:
                self._hold(db, session_id, error)
                return
            if turn.error is not None:
                self._fail(db, session_id, turn_id, turn.error, recorded=True)
            elif pending.resuming:
                self._resumed(db, session_id, turn)

    def release_held(self) -> None:
        """Move on the held Sessions the gate is open for, and tell the line of
        each it still holds, on a loop of their own: called once the gate may
        have moved. A call while that loop runs has it run once more."""
        self._supervisor.start_loop(
            START_JOB, self.release, key=RELEASE_KEY, again=True
        )

    def release(self, handle: LoopHandle) -> None:
        """The release loop's run: each held Session in `created_at` order,
        moved to `starting` under its lock while it is still `held` and the
        gate is open for it, a work item's slot counted under the slot's
        lock, a job's queue read (`queued`) and its brief composed if it has
        none yet (`_brief`), its loop run once that commits. One the gate
        still holds has its work item's line told again: a halt's turn, the
        outage's, the slot's count or a job's end, which asked for the run,
        may have moved its reason. So has each work item whose nudge is owed,
        the hard stop's or a turn's end's under a halt: a halt's turn may have
        moved the halt its line names (decision 66)."""
        with scoped_session(self._container) as db:
            held = db.scalars(
                select(AgentSession.id)
                .where(AgentSession.state_code == SessionState.HELD)
                .order_by(AgentSession.created_at, AgentSession.id)
            ).all()
            for owed in db.scalars(
                select(AgentSession).where(
                    AgentSession.kind_code == WORK_KIND,
                    AgentSession.nudge_owed_at.is_not(None),
                )
            ):
                self._moved(owed)
        for session_id in held:
            if handle.stopping:
                return
            with scoped_session(self._container) as db:
                self._release_one(db, session_id)

    def hard_stop(self) -> None:
        """A usage halt whose setting is the hard stop holds: every running
        work item stopped on a loop of its own (F135.6). A call while that
        loop runs has it run once more."""
        self._supervisor.start_loop(
            START_JOB, self.stop_halted, key=HARD_STOP_KEY, again=True
        )

    def stop_halted(self, handle: LoopHandle) -> None:
        """The hard stop's loop's run: each work item's Session `running`, in
        `created_at` order, stopped by Pilot as a Stop stops one, its nudge
        owed (DB 269, 232), each in a transaction of its own, under its lock
        while it still runs and a hard-stop halt still holds."""
        with scoped_session(self._container) as db:
            running = db.scalars(
                select(AgentSession.id)
                .where(
                    AgentSession.kind_code == WORK_KIND,
                    AgentSession.state_code == SessionState.RUNNING,
                )
                .order_by(AgentSession.created_at, AgentSession.id)
            ).all()
        for session_id in running:
            if handle.stopping:
                return
            with scoped_session(self._container) as db:
                self._stop_halted(db, session_id)

    def send_nudges(self) -> None:
        """What holds an owed nudge may have lifted — a usage halt, at a
        reading or an overrule, or a project's pause: the nudges owed sent on
        a loop of their own (F135.3, F141.3). A call while that loop runs has
        it run once more."""
        self._supervisor.start_loop(START_JOB, self.nudge, key=NUDGE_KEY, again=True)

    def nudge(self, handle: LoopHandle) -> None:
        """The nudges' loop's run: each Session whose nudge is owed and that
        nothing holds now, in the order they were owed, carried on by its
        nudge as a Resume carries one on, through the gate, its nudge then no
        longer owed (DB 232); each in a transaction of its own, read again
        under its locks."""
        with scoped_session(self._container) as db:
            owed = db.scalars(
                self._nudgeable(db).order_by(
                    AgentSession.nudge_owed_at, AgentSession.id
                )
            ).all()
        for session_id in owed:
            if handle.stopping:
                return
            with scoped_session(self._container) as db:
                self._nudge_one(db, session_id)

    def run_nudge_timer(self, db: Session) -> None:
        """The nudges' tick (design 2 §8.2): their loop run while a nudge owed
        is held by nothing, one a reading's or a resume's ask missed, a
        project brought back or a stopped turn's end among them."""
        if db.scalar(select(self._nudgeable(db).exists())):
            self.send_nudges()

    def stop(self, db: Session, session_id: uuid.UUID, person: User) -> AgentSession:
        """`person`'s Stop of a work item, in the caller's transaction (F67.1):
        its Session `stopped` where it is, as `_stop` writes it.

        Returns:
            The Session, `stopped`

        Raises:
            RecordNotFoundException: No Session has the id
            InvalidOperationException: The Session is no work item's, is a
                job's, Pilot's own (F26.3), or it is neither running, starting
                nor held at the gate
        """
        session = self._records(db).lock_session(session_id)
        operation = f"stop {_work_named(db, session_id)}"
        if db.get(Work, session_id) is None:
            raise InvalidOperationException(operation, "it is no work item")
        if session.kind_code == JOB_KIND:
            raise InvalidOperationException(operation, PILOTS_OWN)
        if session.state_code not in STOPPABLE:
            raise InvalidOperationException(
                operation, _STOP_REFUSALS[session.state_code]
            )
        self._stop(db, session, person, datetime.now(UTC))
        return session

    def stop_chat(
        self, db: Session, session_id: uuid.UUID, person: User, operation: str
    ) -> AgentSession:
        """`person`'s Stop of Pilot's answer in a chat, whoever sent its
        message, in the caller's transaction (F44): its Session `stopped`
        where it is, as `_stop` writes a work item's Stop.

        Returns:
            The Session, `stopped`

        Raises:
            InvalidOperationException: The Session is neither running,
                starting nor held at the gate, refused as `operation`
        """
        session = self._records(db).lock_session(session_id)
        if session.state_code not in STOPPABLE:
            raise InvalidOperationException(
                operation, _CHAT_STOP_REFUSALS[session.state_code]
            )
        self._stop(db, session, person, datetime.now(UTC))
        return session

    def stop_project(
        self, db: Session, project: Project, person: User, at: datetime
    ) -> None:
        """Every Session of the project running, starting or held, a Chat's
        among them, stopped by `person` at `at` as a Stop stops a work item:
        Finish's and Archive's (F5.1, F128.1), and Reopen's of a finished
        project's chat (F5.5). It calls no controller in the
        transaction. The caller holds the project's row; the Sessions are
        locked before any Item, which a turn's end locks after its Session.
        The open chat's Session is locked first, whatever its state: a
        message's send moves it to `running` under that lock alone, not the
        project's row (`ChatService.send`)."""
        chat_id = db.scalar(
            select(Chat.id).where(
                Chat.project_id == project.id, Chat.closed_at.is_(None)
            )
        )
        if chat_id is not None:
            self._records(db).lock_session(chat_id)
        for session in db.scalars(
            select(AgentSession)
            .where(
                AgentSession.project_id == project.id,
                AgentSession.state_code.in_(STOPPABLE),
            )
            .order_by(AgentSession.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ):
            self._stop(db, session, person, at)

    def resume(self, db: Session, session_id: uuid.UUID) -> AgentSession:
        """A work item's Resume, stopped or failed, in the caller's
        transaction (F67.2): carried on by "continue" (`_carry_on`). The item
        stays one item (F26.7). A nudge owed to it, the hard stop's, is owed
        no more: the Resume stands in for it (DB 232).

        The project's row is read under a share lock, so a Resume and a
        Finish or an Archive never interleave, and the slot is counted under
        its lock before the environment's row is locked (the lock order).

        Returns:
            The Session, `starting`, or `held` while the gate is closed

        Raises:
            RecordNotFoundException: No Session has the id
            InvalidOperationException: No controller is configured; the
                Session is no work item's, is a job's, Pilot's own (F26.3), is
                neither stopped nor failed, runs in an environment Pilot did
                not create, or has its stopped turn still in flight; or the
                project is finished or archived
        """
        operation = f"resume {_work_named(db, session_id)}"
        if not self._controller_configured:
            raise InvalidOperationException(operation, "no controller is configured")
        records = self._records(db)
        project = _standing(
            db, records.require_session(session_id).project_id, births=False
        )
        session = records.lock_session(session_id)
        if db.get(Work, session_id) is None:
            raise InvalidOperationException(operation, "it is no work item")
        if session.kind_code == JOB_KIND:
            raise InvalidOperationException(operation, PILOTS_OWN)
        if session.state_code not in _RESUMABLE:
            raise InvalidOperationException(
                operation, _RESUME_REFUSALS[session.state_code]
            )
        if _foreign(session, _environment(db, session)):
            raise InvalidOperationException(operation, NOT_PILOTS)
        refusal = _closed(project)
        if refusal is not None:
            raise InvalidOperationException(operation, refusal)
        if _latest_turn(db, session_id).ended_at is None:
            raise InvalidOperationException(
                operation, "its stopped turn is still ending"
            )
        held = self._carry_on(db, project, session, CONTINUE)
        logger.info(
            "Session %s resumed%s",
            session_id,
            "" if held is None else f", held: {held.reason}",
        )
        return session

    def run_probe(self, db: Session) -> None:
        """The gate's probe, on the scheduler's tick (§8.2, §13.4): while the
        outage holds, the controller's readiness call, whose answer turns it
        off; one with no answer keeps it on."""
        if not self._outage.holds:
            return
        try:
            self._client().probe()
        except ExternalServiceException as error:
            logger.debug("The probe found the controller unreachable: %s", error)
            return
        self._outage.probe_answered()

    def _reconcile(self, db: Session) -> None:
        """At STARTUP: run the start of every Session still `starting`, open
        the gate for the held ones, the outage off in a fresh process, and
        send the nudges owed (§8.2)."""
        for session_id in db.scalars(
            select(AgentSession.id)
            .where(AgentSession.state_code == SessionState.STARTING)
            .order_by(AgentSession.id)
        ):
            logger.info("Resuming the start of session %s", session_id)
            self._start_loop(session_id)
        self.release_held()
        self.send_nudges()

    def _release_one(self, db: Session, session_id: uuid.UUID) -> None:
        unlocked = db.get_one(AgentSession, session_id)
        if unlocked.kind_code == JOB_KIND:
            # Before the Session's lock (the lock order): a job's brief writes
            # its Session's row a second time, whose foreign key's check then
            # takes the project's row, which an Item's birth holds exclusively.
            _standing(db, unlocked.project_id, births=False)
        session = self._records(db).lock_session(session_id)
        if session.state_code != SessionState.HELD:
            return
        project = db.get_one(Project, session.project_id, populate_existing=True)
        if (
            self._held(
                db,
                project,
                session.kind_code,
                queued=_queued(db, session),
                session=session,
            )
            is not None
        ):
            self._moved(session)
            return
        session.state_code = SessionState.STARTING
        if _unbriefed(session):
            self._brief(db, project, session, datetime.now(UTC))
        self._begin(db, session)
        self._moved(session, state=True)
        logger.info("Session %s goes on from held", session_id)

    def _begin(self, db: Session, session: AgentSession) -> None:
        """The start of a `starting` Session begun through the gate, its slot
        taken (`WorkSlots.took`), and its loop run once the transaction
        commits. In its Environment, the phase that brings it up, unless the
        Session has its controller session already, and its shutdown timer
        cleared. One with no Environment yet, or with one whose reset is
        still to make, enters its phase at the create, at the rename or as it
        takes the store; one in an environment Pilot did not create none, its
        loop failing it."""
        environment = _environment(db, session)
        if environment is not None and not _foreign(session, environment):
            if session.controller_session is None and not _unreset(
                session, environment
            ):
                self._phase(db, session.id, _bringing_up(session, environment))
            self._environments.clear_shutdown_timer(db, environment.id)
        self._slots.took(session)
        after_commit(_LoopStart(self, session.id))

    def _stop(
        self, db: Session, session: AgentSession, person: User, at: datetime
    ) -> None:
        """Under the Session's lock: `stopped` by `person` at `at`, with no
        current line (F67.1, F69.2). A turn in flight stays so, for its relay to
        record to the end the controller's interrupt gives it once this
        commits; a start held or under way has its Turn ended unsent, and its
        loop sends nothing more, and a job held before its brief has none. Its
        environment is handed to the shutdown timer (`_hand_to_timer`); a start
        held before it had one arms none. A work item's slot opens once this
        commits."""
        before = session.state_code
        session.state_code = SessionState.STOPPED
        session.stopped_at = at
        session.stopped_by_user_id = person.id
        session.current_line = None
        if before == SessionState.RUNNING:
            self._relays.request_interrupt(session.id)
        elif not _unbriefed(session):
            turn = _latest_turn(db, session.id)
            turn.ended_at = at
            session.turn_ended_at = at
        self._hand_to_timer(db, session)
        self._moved(session, state=True)
        self._slots.left(session, before)
        logger.info("Session %s stopped by %s, %s", session.id, person.handle, before)

    def _stop_halted(self, db: Session, session_id: uuid.UUID) -> None:
        session = self._records(db).lock_session(session_id)
        if session.state_code != SessionState.RUNNING or not self._halts.stopping(db):
            return
        pilot = db.scalars(select(User).where(User.kind_code == UserKind.AGENT)).one()
        now = datetime.now(UTC)
        self._stop(db, session, pilot, now)
        session.nudge_owed_at = now
        logger.info("Session %s stopped at the usage limit, its nudge owed", session_id)

    def _nudgeable(self, db: Session) -> Select[uuid.UUID]:
        """The Sessions whose nudge is owed and that nothing holds now: their
        work item open, their project neither finished, archived nor paused,
        and, a work item's, no usage halt holding (DB 232, 266)."""
        query = (
            select(AgentSession.id)
            .join(Project, Project.id == AgentSession.project_id)
            .join(Item, Item.id == AgentSession.id)
            .where(
                AgentSession.nudge_owed_at.is_not(None),
                Item.done_at.is_(None),
                Project.state_code != ProjectState.FINISHED,
                Project.archived.is_(False),
                Project.paused.is_(False),
            )
        )
        if self._halts.halted(db) is not None:
            query = query.where(AgentSession.kind_code != WORK_KIND)
        return query

    def _nudge_one(self, db: Session, session_id: uuid.UUID) -> None:
        """The Session's nudge sent, under its project's row and then its
        own, while it is still owed and nothing holds it; one whose stopped
        turn is still ending waits for the next run."""
        unlocked = db.get_one(AgentSession, session_id)
        project = _standing(db, unlocked.project_id, births=False)
        session = self._records(db).lock_session(session_id)
        if (
            session.nudge_owed_at is None
            or _closed(project) is not None
            or project.paused
            or db.get_one(Item, session_id, populate_existing=True).done_at is not None
            or (session.kind_code == WORK_KIND and self._halts.halted(db) is not None)
            or _latest_turn(db, session_id).ended_at is None
        ):
            return
        held = self._carry_on(db, project, session, _nudge_words(db, session))
        logger.info(
            "Session %s nudged%s",
            session_id,
            "" if held is None else f", held: {held.reason}",
        )

    def _carry_on(
        self, db: Session, project: Project, session: AgentSession, message: str
    ) -> Held | None:
        """Under the project's row and the Session's lock, its last Turn
        ended: a server-own Turn, `message`, or the ended Turn's message
        while the Session has no conversation (R15's rule, so a failed
        start's carries its brief, or while no Turn of the Session has gone
        out, so a continuation's carries its message), and the Session
        through the gate (§13.4): `held` while it is closed, else
        `starting`, its loop sending the Turn once this commits. Its `error`
        is cleared, its nudge is owed no more, and a write-back the
        controller refused of a document it carries is owed again
        (`RecordService.retry_write_backs`). With no conversation it is a
        fresh start (`_fresh`). Returns why the gate holds it; None while it
        is open."""
        ended = _latest_turn(db, session.id)
        now = datetime.now(UTC)
        turn = Turn(
            session_id=session.id,
            seq=ended.seq + 1,
            message=(
                ended.message
                if session.conversation_id is None or not _went_out(db, session.id)
                else message
            ),
            started_at=now,
        )
        db.add(turn)
        db.flush()
        session.turns = turn.seq
        session.turn_started_at = now
        session.turn_ended_at = None
        session.error = None
        session.current_line = None
        session.nudge_owed_at = None
        self._container.record_service().retry_write_backs(session.id)
        held = self._held(
            db,
            project,
            session.kind_code,
            queued=False,
            session=session,
        )
        if session.conversation_id is None:
            self._fresh(db, session)
        if held is None:
            session.state_code = SessionState.STARTING
            self._begin(db, session)
        else:
            session.state_code = SessionState.HELD
            after_commit(_HeldWritten(self))
        self._moved(session, state=True)
        return held

    def _fresh(self, db: Session, session: AgentSession) -> None:
        """A Resume with no conversation to continue, a fresh start (review
        B1): in a headless session of its own, never one an earlier start
        left there, in its environment taken back, its reset still to make
        (`EnvironmentService.retake`); one gone or deleting it lets go, and
        its start takes a free one or creates one."""
        session.controller_session = None
        if session.environment_id is not None and not self._environments.retake(
            db, session.environment_id
        ):
            logger.info(
                "Session %s lets environment %s go: it is leaving",
                session.id,
                session.environment_id,
            )
            session.environment_id = None

    def _hand_to_timer(self, db: Session, session: AgentSession) -> None:
        """The shutdown timer of the environment the Session stops or fails
        in armed, if it has one, when nothing else runs or starts there. One
        whose reset was still to make, its claim cleared for it, is claimed
        first (`EnvironmentService.reclaim`), so that a start cut before its
        reset leaves no environment of Pilot's running outside the timer
        (refinement D1)."""
        if session.environment_id is None:
            return
        if session.conversation_id is None:
            self._environments.reclaim(db, session.environment_id)
        self._environments.arm_shutdown_timer(db, session.environment_id)

    def _lost_reason(self, env_id: str, name: str) -> str | None:
        """Why the controller session takes no turn: gone, ended, or its
        environment not running; None when it takes one.

        Raises:
            ExternalServiceException: The controller failed otherwise
        """
        try:
            snapshot = self._client().get_session(env_id, name)
        except ControllerProblem as problem:
            if problem.problem_type not in (
                ControllerProblemType.NOT_FOUND,
                ControllerProblemType.CONFLICT,
            ):
                raise
            return str(problem)
        if snapshot.status in _DONE_STATUSES:
            return f"controller session {name} is {snapshot.status}"
        return None

    def _lost(
        self, db: Session, session_id: uuid.UUID, gone: str, reason: str
    ) -> _Pending | None:
        """Under the Session's lock, while it is `starting` on the controller
        session `gone`: a `server` record saying it is gone, the Session left
        with none, and the phase that starts its environment; the start as its
        rows then have it. None when it has moved on."""
        records = self._records(db)
        session = records.lock_session(session_id)
        if (
            session.state_code != SessionState.STARTING
            or session.controller_session != gone
        ):
            return None
        records.append(
            session_id,
            RecordKind.SERVER,
            payload={"type": SESSION_GONE, "reason": reason},
        )
        session.controller_session = None
        environment = db.get_one(Environment, session.environment_id)
        self._phase(db, session_id, f"Starting {environment.name}…")
        logger.info(
            "Session %s resumes in a new controller session: %s", session_id, reason
        )
        return _pending(db, session_id)

    def _resumed(self, db: Session, session_id: uuid.UUID, turn: Turn) -> None:
        """A Resume's Turn sent: the Session's run counts from it, as "running
        N min" reads it."""
        session = self._records(db).lock_session(session_id)
        if session.state_code == SessionState.RUNNING:
            session.started_at = turn.started_at
            self._moved(session)

    def _hold(
        self, db: Session, session_id: uuid.UUID, error: ControllerUnreachable
    ) -> None:
        """The Session back to `held` where its rows stand, the outage on,
        while it is still `starting` (DB 230)."""
        session = self._records(db).lock_session(session_id)
        if session.state_code != SessionState.STARTING:
            return
        session.state_code = SessionState.HELD
        self._moved(session, state=True)
        after_commit(_HeldWritten(self))
        logger.warning("Session %s is held: %s", session_id, error)

    def _start_loop(self, session_id: uuid.UUID) -> None:
        # A run that held the Session still counts as live until its thread
        # ends: `again` has it run once more, which resumes the start.
        self._supervisor.start_loop(
            START_JOB, partial(self.run, session_id), key=str(session_id), again=True
        )

    def _written_back(
        self, session_id: uuid.UUID, turn_id: int, handle: LoopHandle
    ) -> bool:
        """Every write-back owed for the documents the Session carries, a
        continuation's, made before its environment is brought up, which the
        controller refuses a write during (F65.1): each landed, or refused for
        the file, its path or its environment (`WriteBackService`). One
        refused so, before this run or by it, fails the start with the
        controller's reason (F125); a call the controller does not answer
        returns the Session to `held`, and any other failure fails it.
        Returns whether the start goes on: False once it is held or failed, or
        the loop is told to stop.

        Raises:
            ControllerProblem: The controller refused a write for its own work
                on the tree (`409 conflict`) or its share unreadable (`503`):
                the loop runs again after its backoff, the Session `starting`
        """
        with scoped_session(self._container) as db:
            runs = _carried(db, session_id)
        if not runs:
            return True
        try:
            for run_id in runs:
                self._container.write_back_service().write_back(run_id, handle)
        except ControllerUnreachable as error:
            with scoped_session(self._container) as db:
                self._hold(db, session_id, error)
            return False
        except ExternalServiceException as error:
            if (
                isinstance(error, ControllerProblem)
                and error.problem_type in _WAITED_OUT
            ):
                raise
            with scoped_session(self._container) as db:
                self._fail(db, session_id, turn_id, str(error), recorded=False)
            return False
        if handle.stopping:
            return False
        with scoped_session(self._container) as db:
            refused = _refused_write_backs(db, session_id)
            if refused is not None:
                self._fail(db, session_id, turn_id, refused, recorded=False)
                return False
        return True

    def _bring_up(self, session_id: uuid.UUID, pending: _Pending) -> bool:
        """The Session's environment brought up as its rows have it, and its
        settle awaited (`run`); a brain session's with none is the store
        (`_in_store`). Returns False when the Session moved on before it took
        an environment, one this run's create made for it stopped at once and
        left free, or before its reset.

        Raises:
            ControllerProblem: The controller refused the create, the rename
                or the stop
            EnvironmentStartFailed: It refused the start or the reset, or the
                environment settled other than `stopped` after its stop or
                other than `running` after its bring-up
            ControllerUnreachable: The controller did not answer a call
            ExternalServiceException: The controller failed otherwise
        """
        if pending.env_id is None:
            if pending.brain:
                return self._in_store(session_id)
            taking = self._take(session_id)
            if taking is None:
                return False
            pending = taking
        if pending.env_id is None:
            env_id, taken = self._create(session_id)
            if not taken:
                self._environments.stop_untaken(env_id)
                return False
            self._environments.settle(env_id)
            return True
        if pending.unreset:
            if not self._named(session_id, pending.env_id):
                return False
            self._environments.reset(pending.env_id)
        elif pending.bringing_up:
            self._environments.settle(pending.env_id)
        else:
            self._environments.start(pending.env_id)
        return True

    def _in_store(self, session_id: uuid.UUID) -> bool:
        """A brain Session's environment, the store (design 3 §12; F81): its
        row made on Pilot's first touch (`ensure_environment`), the Session's
        under its lock while it is still `starting` with none, with the phase
        that starts it; then started, and its settle awaited
        (`EnvironmentService.start`). The store is exempt, so no timer of
        Pilot's stops it. Returns False when the Session moved on first.

        Raises:
            ControllerProblem: The controller has no such environment
            EnvironmentStartFailed: It refused the start, or the store settled
                other than `running`
            ControllerUnreachable: The controller did not answer a call
            ExternalServiceException: The controller failed otherwise
        """
        with scoped_session(self._container) as db:
            self._environments.ensure_environment(db, self._store)
        with scoped_session(self._container) as db:
            session = self._records(db).lock_session(session_id)
            if (
                session.state_code != SessionState.STARTING
                or session.environment_id is not None
            ):
                return False
            session.environment_id = self._store
            self._phase(
                db,
                session_id,
                _bringing_up(session, db.get_one(Environment, self._store)),
            )
        self._environments.start(self._store)
        return True

    def _create_session(
        self,
        session_id: uuid.UUID,
        env_id: str,
        request: HeadlessCreateRequest,
        handle: LoopHandle,
    ) -> SessionSnapshot | None:
        """The headless create. A boxed one with a folder to write, refused
        `422` — its folder not yet on disk, as `pilot-sync` writes it a
        moment after the record changes (TD §4.2) — is made again every
        `folder_retry_seconds` until `folder_wait_seconds` have passed since
        its first refusal (F50, F125). None when the loop is told to stop
        meanwhile.

        Raises:
            ControllerProblem: The controller refused it otherwise, or still
                `422` past the wait
            ControllerUnreachable: The controller did not answer
            ExternalServiceException: The controller failed otherwise
        """
        client = self._client()
        refused_at: float | None = None
        while True:
            try:
                return client.create_headless_session(env_id, request)
            except ControllerProblem as problem:
                if (
                    problem.problem_type is not ControllerProblemType.VALIDATION_ERROR
                    or not request.sandbox_writable_dirs
                ):
                    raise
                now = time.perf_counter()
                if refused_at is None:
                    refused_at = now
                    logger.info(
                        "Session %s waits for its folder: %s", session_id, problem
                    )
                elif now - refused_at >= self._folder_wait:
                    raise
            if handle.wait(self._folder_retry):
                return None

    def _take(self, session_id: uuid.UUID) -> _Pending | None:
        """Under the Session's lock, while it is `starting` with no
        Environment: a free environment of Pilot's own made from its Work's
        repository taken for it, and committed before any controller call
        (`EnvironmentService.take`). Returns the Session's start as its rows
        then have it, with no Environment when none was free to take; None
        when it has moved on, stopped or given its Environment by another
        process."""
        with scoped_session(self._container) as db:
            session = self._records(db).lock_session(session_id)
            if (
                session.state_code != SessionState.STARTING
                or session.environment_id is not None
            ):
                return None
            repo = db.get_one(Work, session_id).repo
            # `start_work` places every Session with no Environment by repository.
            assert repo is not None
            environment = self._environments.take(db, repo)
            if environment is not None:
                session.environment_id = environment.id
                logger.info(
                    "Session %s took environment %s", session_id, environment.id
                )
            return _pending(db, session_id)

    def _named(self, session_id: uuid.UUID, env_id: str) -> bool:
        """The environment its start took renamed after the Session's
        Project (§13.5), unnamed for a draft's, and the phase that prepares
        it, while the Session is still `starting` there. Returns whether it
        is.

        Raises:
            ControllerProblem: The controller refused the rename
            ControllerUnreachable: The controller did not answer
            ExternalServiceException: The controller failed otherwise
        """
        with scoped_session(self._container) as db:
            slug = db.get_one(Project, db.get_one(Work, session_id).project_id).slug
        name = self._environments.name(env_id, slug)
        with scoped_session(self._container) as db:
            session = self._records(db).lock_session(session_id)
            if (
                session.state_code != SessionState.STARTING
                or session.environment_id != env_id
            ):
                return False
            self._phase(db, session_id, f"Preparing {name}…")
            return True

    def _create(self, session_id: uuid.UUID) -> tuple[str, bool]:
        """An environment of Pilot's own created from the Work's repository,
        named after its Project's slug (§13.5), and its row committed before
        its bring-up is waited on, with the Session's Environment while it is
        still `starting` with none (`_created`). Returns its id and whether
        the Session took it.

        Raises:
            ControllerProblem: The controller refused the create
            ControllerUnreachable: The controller did not answer
            ExternalServiceException: The controller failed otherwise
        """
        with scoped_session(self._container) as db:
            work = db.get_one(Work, session_id)
            repo = work.repo
            slug = db.get_one(Project, work.project_id).slug
        # `start_work` places every Session with no Environment by repository.
        assert repo is not None
        created = self._environments.create(repo, slug)
        with scoped_session(self._container) as db:
            return created.env_id, self._created(db, session_id, created, repo)

    def _created(
        self,
        db: Session,
        session_id: uuid.UUID,
        created: ControllerEnvironment,
        repo: str,
    ) -> bool:
        """Under the Session's lock, the row of the environment its start
        created; while the Session is `starting` with no Environment, it is
        the Session's, with the phase that prepares it, and True. One that
        moved on, stopped or given its Environment by another process,
        leaves the environment free, and False."""
        session = self._records(db).lock_session(session_id)
        environment = self._environments.record_created(db, created, repo)
        if (
            session.state_code != SessionState.STARTING
            or session.environment_id is not None
        ):
            logger.info(
                "Session %s moved on while environment %s was created for it",
                session_id,
                environment.id,
            )
            return False
        session.environment_id = environment.id
        self._phase(db, session_id, f"Preparing {environment.name}…")
        return True

    def _creating(
        self, db: Session, session_id: uuid.UUID, turn_id: int
    ) -> _Pending | None:
        """The Session's start as its rows have it under its lock, with the
        phase that creates the headless session written while it has no
        controller session; None when it is no longer `starting` to send the
        Turn `turn_id`."""
        self._records(db).lock_session(session_id)
        pending = _pending(db, session_id)
        if pending is None or pending.turn_id != turn_id:
            return None
        if pending.controller_session is None:
            self._phase(db, session_id, CREATING)
        return pending

    def _phase(self, db: Session, session_id: uuid.UUID, text: str) -> None:
        """The `server` record naming the phase the start enters, and the
        current line in its words."""
        records = self._records(db)
        record = records.append(
            session_id, RecordKind.SERVER, payload={"type": STARTING, "text": text}
        )
        session = records.lock_session(session_id)
        session.current_line = while_starting(text, record.at)
        self._moved(session)

    def _fail(
        self,
        db: Session,
        session_id: uuid.UUID,
        turn_id: int,
        reason: str,
        *,
        recorded: bool,
    ) -> None:
        """The Session `failed` with `reason`, the Turn `turn_id` its start
        sends ended, and a `server` record saying so unless that Turn's failed
        send `recorded` one. Then its environment is handed to the shutdown
        timer (`_hand_to_timer`), and a work item's slot opens once this
        commits. A Session no longer `starting` to send that Turn is left as it
        is."""
        records = self._records(db)
        if not _sends(db, records.lock_session(session_id), turn_id):
            return
        if not recorded:
            records.append(
                session_id,
                RecordKind.SERVER,
                payload={"type": START_FAILED, "reason": reason},
            )
        session = records.lock_session(session_id)
        turn = _latest_turn(db, session_id)
        if turn.ended_at is None:
            turn.ended_at = datetime.now(UTC)
        session.turn_ended_at = turn.ended_at
        session.state_code = SessionState.FAILED
        session.error = reason
        session.current_line = None
        self._moved(session, state=True)
        self._hand_to_timer(db, session)
        self._slots.left(session, SessionState.STARTING)
        logger.warning("Session %s failed to start: %s", session_id, reason)

    def _held(
        self,
        db: Session,
        project: Project,
        kind_code: str,
        *,
        queued: bool,
        session: AgentSession | None = None,
    ) -> Held | None:
        """Why the gate holds a start of a Session of `kind_code` in
        `project` now, a job's `queued` behind another of its project or not,
        a work item's or a job's `session` when it is written already, a
        setup's let through the pause (`setups`); None while it is open. A
        work item's reads the usage halts (`UsageHalts.halted`), and counts
        the slot under the slot's lock (`WorkSlots.lock`), held to the
        transaction's end, so the next start's count sees the Session this
        one moves to `starting`, and reads under it whether another Session
        carries the conversation `session` resumes (`carried`)."""
        halted = None
        filled = None
        conversing = False
        if kind_code == WORK_KIND:
            halted = self._halts.halted(db)
            self._slots.lock(db)
            filled = self._slots.filled(db, [project.id]).get(project.id)
            conversing = session is not None and carried(db, session)
        return held_reason(
            halted=halted,
            paused=project.paused,
            kind_code=kind_code,
            setup=session is not None
            and kind_code == JOB_KIND
            and session.id in setups(db, [session.id]),
            unreachable=self._outage.holds,
            filled=filled,
            queued=queued,
            conversing=conversing,
        )

    def _brief(
        self, db: Session, project: Project, session: AgentSession, at: datetime
    ) -> None:
        """A job leaving the queue or the pause with no Turn yet, in the
        transaction that moves it to `starting`: its brief composed from the
        record as it stands at `at` (F59; `BriefService.job`), its trigger's
        instant its Session's creation, a Retry's that of the job its trigger
        placed first (`_triggered`), sent as its first Turn, and its Work's
        switch the one that brief states, which the session keeps (F54.7).
        The job after an item's close consumes the item it is briefed with,
        which takes Undo from it (F14.1): under the Session's lock, which the
        item's Undo takes before it reads the item. A Retry's finds it
        consumed by the job it retries, and consumed is final (DB 56)."""
        work = db.get_one(Work, session.id)
        work.autopilot = project.autopilot
        db.add(
            Turn(
                session_id=session.id,
                seq=1,
                message=self._container.brief_service().job(
                    project, work, _triggered(db, session), at
                ),
                started_at=at,
            )
        )
        if work.trigger_code is WorkTrigger.ITEM_DONE:
            # The job after an item's close names the item.
            assert work.trigger_item_id is not None
            closed = db.get_one(Item, work.trigger_item_id)
            if closed.consumed_at is None:
                closed.consumed_at = at
                closed.consumed_session_id = session.id
        db.flush()
        session.turns = 1
        session.turn_started_at = at

    def withdraw(self, db: Session, session: AgentSession, at: datetime) -> None:
        """A job held before its brief, its Session locked by the caller,
        withdrawn at `at` by its trigger item's Undo: `stopped` by no one,
        with no Turn, as a Stop leaves a job held before its brief, so the
        gate never starts it. It held no slot and no environment; the
        project's next job goes on once what held this one moves."""
        session.state_code = SessionState.STOPPED
        session.stopped_at = at
        session.current_line = None
        self._moved(session, state=True)
        logger.info("Session %s withdrawn before its brief", session.id)

    def _moved(self, session: AgentSession, *, state: bool = False) -> None:
        work_moved(self._container.engine_bus(), session, state=state)

    def _records(self, db: Session) -> SessionRecordService:
        return SessionRecordService(
            db, self._streams, ViewService(db, self._container.engine_bus())
        )

    def _client(self) -> ControllerClient:
        client: ControllerClient = self._container.controller_client()
        return client


def _unbriefed(session: AgentSession) -> bool:
    """Whether the Session is a job held before its brief: placed with no
    Turn, which `_brief` writes."""
    return session.kind_code == JOB_KIND and session.turns == 0


def _triggered(db: Session, session: AgentSession) -> datetime:
    """The instant of the job's trigger: its Session's creation, or, for a
    Retry's job, that of the first job of the chain its Retries make."""
    first = session
    while (
        earlier := db.scalar(select(Work.id).where(Work.retried_by_id == first.id))
    ) is not None:
        first = db.get_one(AgentSession, earlier)
    return first.created_at


def _queued(db: Session, session: AgentSession) -> bool:
    """Whether the Session is a job behind another of its project
    (`queued`)."""
    return session.kind_code == JOB_KIND and session.id in queued(db, [session.id])


def _pending(db: Session, session_id: uuid.UUID) -> _Pending | None:
    """The Session's start as its rows have it; None when it is not
    `starting`."""
    session = db.get_one(AgentSession, session_id)
    if session.state_code != SessionState.STARTING:
        return None
    turn = _latest_turn(db, session_id)
    environment = _environment(db, session)
    return _Pending(
        env_id=session.environment_id,
        bringing_up=environment is not None
        and environment.server_started_at is not None
        and environment.started_pod_at is None,
        unreset=environment is not None and _unreset(session, environment),
        foreign=_foreign(session, environment),
        brain=session.kind_code != WORK_KIND,
        controller_session=session.controller_session,
        create=scoped_create(db, session),
        turn_id=turn.id,
        resuming=turn.seq > 1,
    )


def _sends(db: Session, session: AgentSession, turn_id: int) -> bool:
    """Whether the Session, its row locked, is `starting` to send the Turn:
    after a Stop and a Resume it starts the Resume's Turn instead."""
    return (
        session.state_code == SessionState.STARTING
        and _latest_turn(db, session.id).id == turn_id
    )


def _environment(db: Session, session: AgentSession) -> Environment | None:
    """The Session's Environment, read afresh; None while it has none."""
    if session.environment_id is None:
        return None
    return db.get_one(Environment, session.environment_id, populate_existing=True)


def _unreset(session: AgentSession, environment: Environment) -> bool:
    """Whether the Session's environment is still to be named, stopped and
    reset: Pilot's own with no claim, the take's or the fresh Resume's
    cleared, for a start on a new conversation (review B3)."""
    return (
        environment.server_created_at is not None
        and environment.server_started_at is None
        and session.conversation_id is None
    )


def _foreign(session: AgentSession, environment: Environment | None) -> bool:
    """Whether the Session is a work item's in an environment Pilot did not
    create: placed by id before slice 020, it is never started there
    (F143.1; review A2)."""
    return (
        environment is not None
        and environment.server_created_at is None
        and session.kind_code == WORK_KIND
    )


def _bringing_up(session: AgentSession, environment: Environment) -> str:
    """The phase that brings the Session's environment up (decision 38):
    "Preparing" one of Pilot's own for a start on a new conversation, which
    created or reset it, else "Starting" it."""
    if environment.server_created_at is not None and session.conversation_id is None:
        return f"Preparing {environment.name}…"
    return f"Starting {environment.name}…"


def _latest_turn(db: Session, session_id: uuid.UUID) -> Turn:
    """The Session's latest Turn: the one its start or its Resume sends while
    it is `held` or `starting`, and the one a Resume follows."""
    return db.scalars(
        select(Turn)
        .where(Turn.session_id == session_id)
        .order_by(Turn.seq.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    ).one()


def _went_out(db: Session, session_id: uuid.UUID) -> bool:
    """Whether a Turn of the Session has gone out: its controller session ran
    it, the relay recording its stream."""
    return stream_position(db, session_id) is not None


def _carried(db: Session, session_id: uuid.UUID) -> list[uuid.UUID]:
    """The Sessions whose registered documents the Session carries, a
    continuation: the run it continues."""
    runs = []
    for run_id in db.scalars(
        select(Item.created_by_session_id)
        .join(Document, Document.id == Item.id)
        .where(
            Item.consumed_session_id == session_id,
            Document.source_path.is_not(None),
        )
        .distinct()
        .order_by(Item.created_by_session_id)
    ):
        # A registered document is its Session's.
        assert run_id is not None
        runs.append(run_id)
    return runs


def _refused_write_backs(db: Session, session_id: uuid.UUID) -> str | None:
    """Why the controller refused the write-back of each document the Session
    carries that it refused, in the order registered, as the `server` record
    of the registering Session says; None when it refused none."""
    refused = db.execute(
        select(Item.id, Item.created_by_session_id, Document.source_path)
        .join(Document, Document.id == Item.id)
        .where(
            Item.consumed_session_id == session_id,
            Document.write_back_refused_at.is_not(None),
        )
        .order_by(Item.seq)
    ).all()
    reasons = []
    for item_id, run_id, path in refused:
        # A registered document is its Session's.
        assert run_id is not None
        reason = _refusal_recorded(db, run_id, item_id)
        reasons.append(f"Cannot write {path} back because {reason}")
    return "; ".join(reasons) if reasons else None


def _refusal_recorded(db: Session, run_id: uuid.UUID, item_id: uuid.UUID) -> str:
    """The reason of the Session's latest `write-back-refused` record of the
    Item, read newest first a page at a time."""
    before = None
    while True:
        page = read_records(
            db,
            run_id,
            before=before,
            kind=RecordKind.SERVER,
            limit=_RECORD_PAGE,
            newest_first=True,
        )
        for stored in page:
            payload = stored.record.payload
            if payload.get("type") == WRITE_BACK_REFUSED and payload.get("item") == str(
                item_id
            ):
                reason: str = payload["reason"]
                return reason
        # A refused write-back writes its record in the refusal's transaction
        # (`WriteBackService`).
        assert len(page) == _RECORD_PAGE
        before = page[-1].record.seq


def _standing(db: Session, project_id: uuid.UUID, *, births: bool) -> Project:
    """The project, its row locked until the transaction ends, so no change
    of its standing interleaves, read as the lock found it. A transaction
    that `births` an Item locks it as `next_seq` does, which then takes no
    stronger lock than the one it holds (the lock order); any other shares
    it.

    Raises:
        RecordNotFoundException: No Project has the id
    """
    project = db.scalars(
        select(Project)
        .where(Project.id == project_id)
        .with_for_update(read=not births)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if project is None:
        raise RecordNotFoundException("Project", str(project_id))
    return project


def _nudge_words(db: Session, session: AgentSession) -> str:
    """The nudge the Session is owed (DB 232; decision 53): worded for the
    stop when a usage halt's hard stop stopped it, for the pause when its
    project was paused when it was found ended, as its Project Transitions
    read at `nudge_owed_at`, else for the quota."""
    if session.state_code == SessionState.STOPPED:
        return NUDGE_AFTER_A_STOP
    last = db.scalar(
        select(ProjectTransition.kind_code)
        .where(
            ProjectTransition.project_id == session.project_id,
            ProjectTransition.kind_code.in_(
                (TransitionKind.PAUSED, TransitionKind.RESUMED)
            ),
            ProjectTransition.at <= session.nudge_owed_at,
        )
        .order_by(ProjectTransition.at.desc(), ProjectTransition.id.desc())
        .limit(1)
    )
    return NUDGE_AFTER_A_PAUSE if last is TransitionKind.PAUSED else NUDGE


def _work_named(db: Session, session_id: uuid.UUID) -> str:
    """A work item as a refusal names it: its Item's title, as Finish's
    names the project, else its id."""
    item = db.get(Item, session_id)
    if item is not None and item.title:
        return item.title
    return f"work item {session_id}"


def _closed(project: Project) -> str | None:
    """Why nothing of the project starts: finished or archived (F5.1,
    F128.1); None while it may."""
    if project.archived:
        return "its project is archived"
    if project.state_code is ProjectState.FINISHED:
        return "its project is finished"
    return None
