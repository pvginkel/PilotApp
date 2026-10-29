"""Pilot's own background jobs (design 3 §5.1; F59, F59.1, F59.2, F49; DB
Work, assertion 167, decision 45): a fresh brain session per trigger, ending
with its turn, each a quiet work item of Pilot's with its session log behind
it.

A job is placed in its caller's transaction, which holds its project's row,
at its trigger's instant: its Session, a `job` one in the store repo's root on
the brain's model and effort, boxed to the project's folder and handed
`pilot-store` (`scoped_create`), created at that instant, and its Work, of its
Work Trigger, in no repository, its Item next on the timeline. It starts
through the gate (`SessionStartService.start_brain`): held while its project
is paused, the setup's never (`setups`), and while another job of its project
is before it, one at a time in the order their triggers came (F59.2), taking
no slot (DB 243); its create made again for a bounded time while its
project's folder is not on disk (F50). Its brief is composed as it leaves the
queue or the pause, from the record as it then stands (F59, F141.4). Its work item is done once its last
turn ends, a follow-up turn included (`RelayService`), and its project's next
job goes on then; a person's Stop and Resume do not take it (F26.3).

Three triggers are placed here: the setup, Create project's; a worker's turn
ended, once the turn-end read settled every document the run registered (D2);
and a person's close of an item of Pilot's own (DB decision 45), whose Undo
withdraws the job while it is held before its brief. A job that failed or
stopped takes a person's Retry, a fresh job for the same trigger; the server
retries none on its own.
"""

import uuid
from datetime import UTC, datetime
from pathlib import PurePosixPath

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.engine.bus import EngineBus
from app.engine.record import WITHDRAWN, RecordService
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import Document, Item, Project, Work
from app.models import Session as AgentSession
from app.models.reference import ProjectState, SessionState, WorkTrigger
from app.services.pilot_server import unheld_token_hash
from app.services.session_scope import STORE_REPO
from app.services.session_start_service import SessionStartService
from app.services.start_gate import JOB_KIND
from app.services.work_status import work_moved

SETUP_TITLE = "Setting up the project"
"""The setup's work item's title (DB Item sample)."""

PASS_TITLE = "Pre-ruling {places}"
"""The title of the job after a worker's turn whose run registered documents,
each named by its place, `<folder>/<seq>` (DB Item sample)."""

NEXT_TITLE = "Deciding what is next"
"""The title of the job after a worker's turn whose run registered nothing,
and of the job after an item of Pilot's own is closed (DB Item sample)."""

_RETRIABLE = (SessionState.FAILED, SessionState.STOPPED)

_RETRY_REFUSALS = {
    SessionState.HELD: "its start waits at the gate",
    SessionState.STARTING: "it is starting",
    SessionState.RUNNING: "it is running",
    SessionState.IDLE: "its turn has ended",
    SessionState.ENDED: "its session has ended",
}


class JobService:
    """Places Pilot's own background jobs and starts them through the gate."""

    def __init__(
        self,
        db: Session,
        engine_bus: EngineBus,
        record_service: RecordService,
        session_start_service: SessionStartService,
        brain_model: str | None,
        brain_reasoning_effort: str | None,
    ) -> None:
        self.db = db
        self.engine_bus = engine_bus
        self.record_service = record_service
        self.session_start_service = session_start_service
        self.brain_model = brain_model
        self.brain_reasoning_effort = brain_reasoning_effort

    def setup(self, project: Project, at: datetime, operation: str) -> Work:
        """The setup (F49), placed at Create project's instant `at` in its
        transaction, which opened and paused the project and holds its row,
        its work item after the opening, let through the pause; briefed from
        the draft and Create's instant (`BriefService.job`).

        Raises:
            InvalidOperationException: No controller or no store environment
                is configured, refused as `operation`
        """
        return self._place(project, WorkTrigger.SETUP, SETUP_TITLE, at, operation)

    def worker_turn_ended(self, project: Project, run_id: uuid.UUID) -> Work | None:
        """The job after the turn of the worker's run `run_id` (design 3 §5.3,
        D2), in the caller's transaction, which holds the project's row
        exclusively, read as the lock found it, and in which the run is done
        `turn_ended` and no document it registered awaits its read: placed
        now, its trigger item the run, titled by the documents the run
        registered. None in a project finished or archived, or for a run whose
        job was placed already: one per run.

        Raises:
            InvalidOperationException: No controller or no store environment
                is configured
        """
        if project.archived or project.state_code is ProjectState.FINISHED:
            return None
        if self.db.scalar(
            select(
                exists().where(
                    Work.trigger_code == WorkTrigger.WORKER_TURN_ENDED,
                    Work.trigger_item_id == run_id,
                )
            )
        ):
            return None
        return self._place(
            project,
            WorkTrigger.WORKER_TURN_ENDED,
            self._pass_title(run_id),
            datetime.now(UTC),
            f"place the job after work item {run_id}'s turn",
            trigger_item_id=run_id,
        )

    def item_done(self, project: Project, item: Item) -> Work:
        """The job after a person's close of the item of Pilot's own `item`
        (F59; DB decision 45), in the close's transaction, which holds the
        project's row exclusively: placed now, its trigger item the item. Its
        brief, composed as it leaves the queue or the pause, consumes the
        item, which takes Undo from it (F14.1); until then the item's Undo
        withdraws it (`withdraw`).

        Raises:
            InvalidOperationException: No controller or no store environment
                is configured
        """
        return self._place(
            project,
            WorkTrigger.ITEM_DONE,
            NEXT_TITLE,
            datetime.now(UTC),
            f"place the job after item {item.id}'s close",
            trigger_item_id=item.id,
        )

    def unbriefed(self, item: Item) -> AgentSession | None:
        """The job a close of `item` placed that is still held before its
        brief, its Session locked and read afresh until the transaction ends;
        None when there is none. A job that left `held` under the lock is
        none: its brief consumed the item."""
        return self.db.scalars(
            select(AgentSession)
            .join(Work, Work.id == AgentSession.id)
            .where(
                Work.trigger_code == WorkTrigger.ITEM_DONE,
                Work.trigger_item_id == item.id,
                AgentSession.state_code == SessionState.HELD,
                AgentSession.turns == 0,
            )
            .with_for_update(of=AgentSession)
            .execution_options(populate_existing=True)
        ).one_or_none()

    def withdraw(self, job: AgentSession, at: datetime) -> None:
        """The job `job`, its Session locked and held before its brief,
        withdrawn at `at` by its trigger item's Undo: its Session stopped by
        no one, so it never starts, and its work item done `withdrawn`, which
        offers nothing and leaves the badge (F8, F94.5)."""
        self.session_start_service.withdraw(self.db, job, at)
        line = self.db.get_one(Item, job.id)
        line.done_at = at
        line.done_cause_code = WITHDRAWN

    def retry(self, session_id: uuid.UUID) -> Work:
        """A person's Retry of the job `session_id`, failed or stopped, its
        work item open, in the caller's transaction: a fresh job for the
        same trigger and trigger item, titled as it is, placed at the press's
        instant at the project's next place, behind every job of the project
        already waiting, and briefed from the record as it stands when it
        starts (`_place`). The job retried is marked retried by it, which
        takes Retry from its line and its line from the badge (F94.5).

        The project's row is locked before the job's Session, the order a
        placement keeps, so that two Retries of one job, a Finish or an
        Archive never interleave with it.

        Returns:
            The new job's Work

        Raises:
            RecordNotFoundException: No Session has the id
            InvalidOperationException: The Session is no work item's, is a
                worker's run, is done (an Undo's withdrawal among it), was
                retried already, is neither failed nor stopped, has its
                stopped turn still ending, or follows an item open again; its
                project is finished or archived; or no controller or no store
                environment is configured
        """
        found = self.db.get(AgentSession, session_id)
        if found is None:
            raise RecordNotFoundException("Session", str(session_id))
        project = self.db.scalars(
            select(Project)
            .where(Project.id == found.project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()
        job = self.db.get_one(
            AgentSession, session_id, with_for_update=True, populate_existing=True
        )
        line = self.db.get(Item, session_id, populate_existing=True)
        work = self.db.get(Work, session_id, populate_existing=True)
        operation = (
            f"retry {line.title}"
            if line is not None and line.title
            else f"retry work item {session_id}"
        )
        if work is None or line is None:
            raise InvalidOperationException(operation, "it is no work item")
        refusal = self._retry_refusal(project, job, work, line)
        if refusal is not None:
            raise InvalidOperationException(operation, refusal)
        assert work.trigger_code is not None and line.title is not None
        retry = self._place(
            project,
            work.trigger_code,
            line.title,
            datetime.now(UTC),
            operation,
            trigger_item_id=work.trigger_item_id,
            retried=work,
        )
        work_moved(self.engine_bus, job)
        return retry

    def _retry_refusal(
        self, project: Project, job: AgentSession, work: Work, line: Item
    ) -> str | None:
        """Why the job takes no Retry now; None while it does."""
        if job.kind_code != JOB_KIND:
            return "it is a worker's run, which Resume carries on"
        if line.done_at is not None:
            if line.done_cause_code == WITHDRAWN:
                return "an Undo withdrew it before its brief went out"
            return "it is done"
        if work.retried_by_id is not None:
            return "it was retried already"
        if job.state_code not in _RETRIABLE:
            return _RETRY_REFUSALS[job.state_code]
        if job.state_code is SessionState.STOPPED and (
            job.turns > 0 and job.turn_ended_at is None
        ):
            return "its stopped turn is still ending"
        if project.archived:
            return "its project is archived"
        if project.state_code is ProjectState.FINISHED:
            return "its project is finished"
        if work.trigger_code is WorkTrigger.ITEM_DONE:
            assert work.trigger_item_id is not None
            if self.db.get_one(Item, work.trigger_item_id).done_at is None:
                return "the item it follows is open again"
        return None

    def _pass_title(self, run_id: uuid.UUID) -> str:
        """The title of the job after the run's turn: the places of the
        documents it registered, in the order registered, else what is next."""
        places = [
            f"{PurePosixPath(path).parent}/{seq}"
            for path, seq in self.db.execute(
                select(Document.path, Item.seq)
                .join(Item, Item.id == Document.id)
                .where(
                    Item.created_by_session_id == run_id,
                    Document.source_path.is_not(None),
                )
                .order_by(Item.seq)
            )
        ]
        if not places:
            return NEXT_TITLE
        if len(places) == 1:
            return PASS_TITLE.format(places=places[0])
        return PASS_TITLE.format(places=f"{', '.join(places[:-1])} and {places[-1]}")

    def _place(
        self,
        project: Project,
        trigger: WorkTrigger,
        title: str,
        at: datetime,
        operation: str,
        *,
        trigger_item_id: uuid.UUID | None = None,
        retried: Work | None = None,
    ) -> Work:
        """A job of `trigger` titled `title`, placed at `at`, taken under the
        project's row: its trigger's instant, which the pause's transitions
        are read against (`BriefService.job`), or a Retry's; its trigger item
        `trigger_item_id`, the Item whose event triggered it. A Retry's marks
        the job it retries, `retried`, before it starts, so that its brief
        reads the trigger's instant as that job's chain has it."""
        session = AgentSession(
            project_id=project.id,
            kind_code=JOB_KIND,
            cwd=STORE_REPO,
            model=self.brain_model,
            reasoning_effort=self.brain_reasoning_effort,
            token_hash=unheld_token_hash(),
            state_code=SessionState.HELD,
            created_at=at,
        )
        self.db.add(session)
        self.db.flush()
        work = self.record_service.place_work(
            project, session, title, trigger=trigger, trigger_item_id=trigger_item_id
        )
        if retried is not None:
            retried.retried_by_id = work.id
            self.db.flush()
        self.session_start_service.start_brain(self.db, project, session, operation)
        return work
