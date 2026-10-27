"""Pilot's own background jobs (design 3 §5.1; F59, F59.1, F49; DB Work,
assertion 167, decision 45): a fresh brain session per trigger, ending with
its turn, each a quiet work item of Pilot's with its session log behind it.

A job is placed in its caller's transaction, which holds its project's row:
its Session, a `job` one in the store repo's root on the brain's model and
effort, boxed to the project's folder and handed `pilot-store`
(`scoped_create`), its first Turn its trigger's brief, and its Work, of its
Work Trigger, in no repository, its Item next on the timeline. It starts
through the gate (`SessionStartService.start_brain`): held while its project
is paused, taking no slot (DB 243), its create made again for a bounded time
while its project's folder is not on disk (F50). Its work item is done once
its last turn ends, a follow-up turn included (`RelayService`); a person's
Stop and Resume do not take it (F26.3).

The setup, Create project's, is the one trigger placed here.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.engine.record import RecordService
from app.models import Item, Project, Turn, Work
from app.models import Session as AgentSession
from app.models.reference import SessionState, WorkTrigger
from app.services.brief_service import BriefService
from app.services.pilot_server import unheld_token_hash
from app.services.session_scope import STORE_REPO
from app.services.session_start_service import SessionStartService
from app.services.start_gate import JOB_KIND

SETUP_TITLE = "Setting up the project"
"""The setup's work item's title (DB Item sample)."""


class JobService:
    """Places Pilot's own background jobs and starts them through the gate."""

    def __init__(
        self,
        db: Session,
        record_service: RecordService,
        brief_service: BriefService,
        session_start_service: SessionStartService,
        brain_model: str | None,
        brain_reasoning_effort: str | None,
    ) -> None:
        self.db = db
        self.record_service = record_service
        self.brief_service = brief_service
        self.session_start_service = session_start_service
        self.brain_model = brain_model
        self.brain_reasoning_effort = brain_reasoning_effort

    def setup(
        self, project: Project, opening: Item, at: datetime, operation: str
    ) -> Work:
        """The setup (F49), placed at Create project's instant `at` in its
        transaction, which opened the project and holds its row: briefed from
        the draft (`BriefService.setup`), its work item after the opening.

        Raises:
            InvalidOperationException: No controller or no store environment
                is configured, refused as `operation`
        """
        return self._place(
            project,
            WorkTrigger.SETUP,
            SETUP_TITLE,
            self.brief_service.setup(project, opening, at),
            at,
            operation,
        )

    def _place(
        self,
        project: Project,
        trigger: WorkTrigger,
        title: str,
        brief: str,
        at: datetime,
        operation: str,
    ) -> Work:
        session = AgentSession(
            project_id=project.id,
            kind_code=JOB_KIND,
            cwd=STORE_REPO,
            model=self.brain_model,
            reasoning_effort=self.brain_reasoning_effort,
            token_hash=unheld_token_hash(),
            state_code=SessionState.STARTING,
            turns=1,
            turn_started_at=at,
        )
        self.db.add(session)
        self.db.flush()
        self.db.add(Turn(session_id=session.id, seq=1, message=brief, started_at=at))
        self.db.flush()
        work = self.record_service.place_work(project, session, title, trigger=trigger)
        self.session_start_service.start_brain(self.db, project, session, operation)
        return work
