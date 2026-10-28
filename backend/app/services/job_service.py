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
is paused, and while another job of its project is before it, one at a time
in the order their triggers came (F59.2), taking no slot (DB 243); its create
made again for a bounded time while its project's folder is not on disk
(F50). Its brief is composed as it leaves the queue or the pause, from the
record as it then stands (F59, F141.4). Its work item is done once its last
turn ends, a follow-up turn included (`RelayService`), and its project's next
job goes on then; a person's Stop and Resume do not take it (F26.3).

Two triggers are placed here: the setup, Create project's, and a worker's turn
ended, once the turn-end read settled every document the run registered (D2).
"""

import uuid
from datetime import UTC, datetime
from pathlib import PurePosixPath

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.engine.record import RecordService
from app.models import Document, Item, Project, Work
from app.models import Session as AgentSession
from app.models.reference import ProjectState, SessionState, WorkTrigger
from app.services.pilot_server import unheld_token_hash
from app.services.session_scope import STORE_REPO
from app.services.session_start_service import SessionStartService
from app.services.start_gate import JOB_KIND

SETUP_TITLE = "Setting up the project"
"""The setup's work item's title (DB Item sample)."""

PASS_TITLE = "Pre-ruling {places}"
"""The title of the job after a worker's turn whose run registered documents,
each named by its place, `<folder>/<seq>` (DB Item sample)."""

NEXT_TITLE = "Deciding what is next"
"""The title of the job after a worker's turn whose run registered nothing
(DB Item sample)."""


class JobService:
    """Places Pilot's own background jobs and starts them through the gate."""

    def __init__(
        self,
        db: Session,
        record_service: RecordService,
        session_start_service: SessionStartService,
        brain_model: str | None,
        brain_reasoning_effort: str | None,
    ) -> None:
        self.db = db
        self.record_service = record_service
        self.session_start_service = session_start_service
        self.brain_model = brain_model
        self.brain_reasoning_effort = brain_reasoning_effort

    def setup(self, project: Project, at: datetime, operation: str) -> Work:
        """The setup (F49), placed at Create project's instant `at` in its
        transaction, which opened the project and holds its row, its work
        item after the opening; briefed from the draft and Create's instant
        (`BriefService.job`).

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
    ) -> Work:
        """A job of `trigger` titled `title`, its trigger's instant `at`,
        taken under the project's row, which the pause's transitions are read
        against (`BriefService.job`); its trigger item `trigger_item_id`, the
        Item whose event triggered it."""
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
        self.session_start_service.start_brain(self.db, project, session, operation)
        return work
