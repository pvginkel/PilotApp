"""A project's record for a test of what Pilot is working on (F13.7, F21.6,
F52.3; DB 294 to 296): its work items, jobs, clarification runs and
documents made as the server makes them."""

import itertools
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import (
    Block,
    ClaimAssignment,
    ClarificationRun,
    Document,
    Environment,
    Item,
    Project,
    ResearchAssignment,
    Turn,
    User,
    Wait,
    Work,
    WriterQuestion,
)
from app.models.reference import SessionState, UserKind, WorkTrigger
from app.schemas.testing_record import InventedProjectCreateSchema
from app.services.container import ServiceContainer
from app.services.working_on import JobsOn, PilotsWork, Reading, jobs_on, pilots_work

AT = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


class Camp:
    """A project's record for one test, its rows made as the server makes
    them: work items and jobs placed, documents registered and read."""

    def __init__(self, container: ServiceContainer, session: DbSession) -> None:
        self.container = container
        self.session = session
        self.project: Project = container.test_data_service().project(
            InventedProjectCreateSchema.model_validate(
                {"members": ["ada"], "name": "Camp"}
            )
        )
        self.environment = Environment(id="camp-env-1", name="Camp-1", exempt=False)
        session.add(self.environment)
        session.flush()
        self._names = itertools.count(1)

    def _session(
        self, kind: str, state: SessionState, conversation: str | None
    ) -> models.Session:
        run = models.Session(
            project_id=self.project.id,
            environment_id=self.environment.id,
            kind_code=kind,
            cwd="/work/Camp" if kind == "work" else "/work/PilotProjects",
            conversation_id=conversation,
            token_hash=uuid.uuid4().hex * 2,
            state_code=state,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def worker(
        self,
        state: SessionState = SessionState.RUNNING,
        conversation: str | None = None,
    ) -> models.Session:
        """A worker's run placed on the project's timeline."""
        run = self._session("work", state, conversation)
        self.container.record_service().place_work(
            self.project, run, "Building the camp", repo="example/Camp"
        )
        return run

    def job_after(
        self, run: models.Session, state: SessionState = SessionState.RUNNING
    ) -> models.Session:
        """The job after the run's turn, the pass over what it registered."""
        job = self._session("job", state, None)
        self.container.record_service().place_work(
            self.project,
            job,
            "Pre-ruling",
            trigger=WorkTrigger.WORKER_TURN_ENDED,
            trigger_item_id=run.id,
        )
        return job

    def job_on(
        self,
        item: Item | None,
        trigger: WorkTrigger,
        state: SessionState = SessionState.RUNNING,
    ) -> models.Session:
        """A job of `trigger` that `item` triggered: the job after a close
        of an item of Pilot's, a wait's run; the setup with no item."""
        job = self._session("job", state, None)
        self.container.record_service().place_work(
            self.project,
            job,
            f"Job of {trigger.value}",
            trigger=trigger,
            trigger_item_id=None if item is None else item.id,
        )
        return job

    def retried(
        self, job: models.Session, state: SessionState = SessionState.RUNNING
    ) -> models.Session:
        """A Retry of the job: a fresh one for its trigger, marking it
        retried."""
        work = self.session.get_one(Work, job.id)
        assert work.trigger_code is not None
        retry = self._session("job", state, None)
        self.container.record_service().place_work(
            self.project,
            retry,
            "Pre-ruling",
            trigger=work.trigger_code,
            trigger_item_id=work.trigger_item_id,
        )
        self.session.get_one(Work, job.id).retried_by_id = retry.id
        self.session.flush()
        return retry

    def wait(self, run: models.Session) -> Item:
        """An open timed wait the run placed."""
        wait = Item(
            project_id=self.project.id,
            seq=self.container.document_service().next_seq(self.project),
            kind_code="timed_wait",
            title="The site opens",
            created_by_session_id=run.id,
        )
        self.session.add(wait)
        self.session.flush()
        self.session.add(
            Wait(id=wait.id, kind_code="timed_wait", due_at=AT + timedelta(hours=1))
        )
        self.session.flush()
        return wait

    def line(self, run: models.Session) -> Item:
        """The work item's Item, its line."""
        return self.session.get_one(Item, run.id)

    def ended(self, run: models.Session) -> None:
        """The run's turn ended well: its Session idle, its work item done."""
        run.state_code = SessionState.IDLE
        self.container.record_service().work_done(run.id, AT)
        self.session.flush()

    def pilot(self) -> User:
        return self.session.scalars(
            select(User).where(User.kind_code == UserKind.AGENT)
        ).one()

    def stopped(self, run: models.Session, *, by: User | None = None) -> None:
        run.state_code = SessionState.STOPPED
        run.stopped_at = AT
        run.stopped_by_user_id = None if by is None else by.id
        self.session.flush()

    def clarification(
        self,
        pass_: models.Session,
        worker: models.Session,
        state: SessionState = SessionState.RUNNING,
    ) -> models.Session:
        """The clarification run of the pass, on the worker's conversation."""
        run = self._session("work", state, worker.conversation_id)
        self.container.record_service().place_work(
            self.project, run, "Clarify the survey", repo="example/Camp"
        )
        self.session.add(ClarificationRun(id=run.id, pass_id=pass_.id))
        self.session.flush()
        return run

    def registered(
        self, run: models.Session, text: str | None = None, *, read: bool = True
    ) -> Item:
        """A document the run registered, read with `text`, or awaiting its
        read."""
        documents = self.container.document_service()
        item = documents.register(
            self.project, run, f"/work/Camp/docs/{next(self._names)}.md"
        ).item
        if read:
            assert text is not None
            documents.publish_read(
                self.session.get_one(Document, item.id), text, run.id
            )
        return item

    def block(self, document: Item, local_id: str) -> Block:
        return self.session.scalars(
            select(Block).where(
                Block.document_id == document.id, Block.local_id == local_id
            )
        ).one()

    def claim(self, document: Item, local_id: str, work: models.Session) -> None:
        self.session.add(
            ClaimAssignment(work_id=work.id, block_id=self.block(document, local_id).id)
        )
        self.session.flush()

    def research(self, document: Item, local_id: str, work: models.Session) -> None:
        self.session.add(
            ResearchAssignment(
                work_id=work.id, block_id=self.block(document, local_id).id
            )
        )
        self.session.flush()

    def ask_writer(self, pass_: models.Session, document: Item, local_id: str) -> None:
        """The pass asked the document's writer about one of its blocks."""
        turn = Turn(session_id=pass_.id, seq=1, message="Pre-rule.", started_at=AT)
        self.session.add(turn)
        self.session.flush()
        self.session.add(
            WriterQuestion(
                turn_id=turn.id,
                block_id=self.block(document, local_id).id,
                question="Which lake?",
            )
        )
        self.session.flush()

    def answered(self, document: Item, local_id: str, value: str) -> None:
        """The person's answer to the document's block, as the app writes
        it: a one-ask document's close, which continues its run once every
        document of the run is closed."""
        self.container.record_service().answer(
            self.session.get_one(Document, document.id),
            local_id,
            self.session.scalars(select(User).where(User.handle == "ada")).one(),
            value,
        )
        self.session.flush()

    def continuation(self, run: models.Session) -> models.Session:
        """The work item that continues the run's conversation."""
        return self.session.scalars(
            select(models.Session).where(
                models.Session.conversation_id == run.conversation_id,
                models.Session.id != run.id,
            )
        ).one()

    def reading(self, *documents: Item) -> dict[uuid.UUID, PilotsWork]:
        """What Pilot does on each document that is Pilot's, which are those
        `Reading.pilots` finds."""
        ids = [document.id for document in documents]
        reading = Reading(self.session)
        found = pilots_work(reading, ids)
        assert set(found) == set(
            self.session.scalars(
                select(Item.id).where(Item.id.in_(ids), reading.pilots())
            )
        )
        return found

    def of(self, document: Item) -> PilotsWork | None:
        return self.reading(document).get(document.id)

    def jobs(self, *items: Item) -> JobsOn:
        """Which of Pilot's jobs each item shows, and the job after each
        worker's run's turn among them."""
        return jobs_on(self.session, [item.id for item in items])
