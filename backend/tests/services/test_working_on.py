"""What Pilot is working on (F13.7, F21.6, F52.3, F94.5; DB 294 to 296, held
through the run): a registered document Pilot's while its read is awaited,
while its pass or its clarification is in flight, or while every open block
is held, and the person's otherwise; a block held through its run until the
run is done with it, and handed back at once while something of the run
stands failed or stopped."""

import itertools
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.engine.bus import EngineEvent, ProjectChanged
from app.models import (
    Block,
    ClaimAssignment,
    ClarificationRun,
    Document,
    Environment,
    Item,
    Project,
    ProjectMember,
    ResearchAssignment,
    StoreUpdate,
    Turn,
    User,
    Work,
    WriterQuestion,
)
from app.models.reference import (
    NotificationPriority,
    SessionState,
    UserKind,
    WorkTrigger,
)
from app.schemas.projects import ProjectStatus
from app.schemas.testing_record import InventedProjectCreateSchema
from app.services.auth_service import AuthContext
from app.services.container import ServiceContainer
from app.services.timeline_service import Badge
from app.services.working_on import (
    Doing,
    PilotsWork,
    handed_back_in,
    holds,
    pilots,
    pilots_work,
)
from app.utils.after_commit import clear_after_commit_callbacks

CLAIMED = """# The cut-over

```action id=A1
answer: Pilot does it
by: agent
at: 2026-11-02T09:00:00Z
```
"""
"""An action the pass claimed, the document's one block."""

CLAIMED_AND_OPEN = (
    CLAIMED
    + """
```action id=A2
```

```decision id=D1
options:
  - Friday
  - Monday
```
"""
)
"""The claimed action beside an action and a decision that wait on the
person."""

QUESTION = "# Where do we pitch?\n\n```question id=Q1\n```\n"
"""A question, the document's one block: what a research checks a fact for,
or what a run asks the person."""

REPORT = "# The survey\n\nNine of ten want the lake.\n"
"""A document with no block: a research's answer, or a report."""

AT = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)

_RUNNING_STATES = (SessionState.HELD, SessionState.STARTING, SessionState.RUNNING)


class _Camp:
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

    def retried(
        self, job: models.Session, state: SessionState = SessionState.RUNNING
    ) -> models.Session:
        """A Retry of the job: a fresh one for its trigger, marking it
        retried."""
        trigger = self.session.get_one(Work, job.id).trigger_item_id
        retry = self._session("job", state, None)
        self.container.record_service().place_work(
            self.project,
            retry,
            "Pre-ruling",
            trigger=WorkTrigger.WORKER_TURN_ENDED,
            trigger_item_id=trigger,
        )
        self.session.get_one(Work, job.id).retried_by_id = retry.id
        self.session.flush()
        return retry

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
        `pilots()` finds."""
        ids = [document.id for document in documents]
        found = pilots_work(self.session, ids)
        assert set(found) == set(
            self.session.scalars(select(Item.id).where(Item.id.in_(ids), pilots()))
        )
        return found

    def of(self, document: Item) -> PilotsWork | None:
        return self.reading(document).get(document.id)


@pytest.fixture
def camp(container: ServiceContainer, session: DbSession, person: User) -> _Camp:
    return _Camp(container, session)


class TestAwaitingItsRead:
    def test_a_registered_document_awaiting_its_read_is_pilots_linking_its_run(
        self, camp: _Camp
    ) -> None:
        run = camp.worker()
        awaiting = camp.registered(run, read=False)

        assert camp.of(awaiting) == PilotsWork(Doing.AWAITING_RUN, run.id, False, None)

    def test_once_read_with_nothing_of_pilots_in_flight_it_is_the_persons(
        self, camp: _Camp
    ) -> None:
        run = camp.worker()
        read = camp.registered(run, QUESTION)
        failed = camp.registered(run, read=False)
        camp.container.document_service().fail_read(
            camp.session.get_one(Document, failed.id)
        )

        assert camp.reading(read, failed) == {}

    def test_a_read_document_is_pilots_while_another_of_its_run_awaits_its_read(
        self, camp: _Camp
    ) -> None:
        run = camp.worker()
        first = camp.registered(run, read=False)
        second = camp.registered(run, read=False)
        camp.ended(run)
        camp.container.document_service().publish_read(
            camp.session.get_one(Document, first.id), QUESTION, run.id
        )

        awaiting = PilotsWork(Doing.AWAITING_RUN, run.id, False, None)
        assert camp.reading(first, second) == {first.id: awaiting, second.id: awaiting}

    def test_a_stopped_work_item_whose_document_awaits_its_read_is_the_persons(
        self, camp: _Camp
    ) -> None:
        run = camp.worker()
        awaiting = camp.registered(run, read=False)
        camp.stopped(run, by=camp.pilot())

        assert camp.reading(camp.session.get_one(Item, run.id), awaiting) == {
            awaiting.id: PilotsWork(Doing.AWAITING_RUN, run.id, False, None)
        }


class TestThePass:
    @pytest.mark.parametrize(
        ("state", "pulse"),
        [
            (SessionState.HELD, True),
            (SessionState.STARTING, True),
            (SessionState.RUNNING, True),
            (SessionState.IDLE, False),
        ],
    )
    def test_a_pass_in_flight_makes_every_document_its_run_registered_pilots(
        self, camp: _Camp, state: SessionState, pulse: bool
    ) -> None:
        run = camp.worker()
        survey, pitch = camp.registered(run, REPORT), camp.registered(run, QUESTION)
        camp.ended(run)
        job = camp.job_after(run, state)

        assert camp.reading(survey, pitch) == {
            survey.id: PilotsWork(Doing.PRE_RULING, job.id, pulse, None),
            pitch.id: PilotsWork(Doing.PRE_RULING, job.id, pulse, None),
        }

    def test_a_pass_owed_its_nudge_is_in_flight_without_a_pulse(
        self, camp: _Camp
    ) -> None:
        run = camp.worker()
        pitch = camp.registered(run, QUESTION)
        camp.ended(run)
        job = camp.job_after(run)
        camp.stopped(job, by=camp.pilot())
        job.nudge_owed_at = AT
        camp.session.flush()

        assert camp.of(pitch) == PilotsWork(Doing.PRE_RULING, job.id, False, None)

    def test_a_pass_the_store_update_stopped_is_in_flight_until_its_lift(
        self, camp: _Camp
    ) -> None:
        run = camp.worker()
        pitch = camp.registered(run, QUESTION)
        camp.ended(run)
        job = camp.job_after(run)
        update = StoreUpdate(made_at=AT)
        camp.session.add(update)
        camp.stopped(job, by=camp.pilot())

        assert camp.of(pitch) == PilotsWork(Doing.PRE_RULING, job.id, False, None)

        update.lifted_at = AT
        camp.session.flush()

        assert camp.of(pitch) is None

    @pytest.mark.parametrize("ending", ["failed", "stopped", "ended"])
    def test_a_pass_that_fails_is_stopped_or_ends_hands_its_documents_over(
        self, camp: _Camp, person: User, ending: str
    ) -> None:
        run = camp.worker()
        pitch = camp.registered(run, QUESTION)
        camp.ended(run)
        job = camp.job_after(run)

        if ending == "failed":
            job.state_code = SessionState.FAILED
        elif ending == "stopped":
            camp.stopped(job, by=person)
        else:
            camp.ended(job)
        camp.session.flush()

        assert camp.of(pitch) is None

    def test_a_retry_of_a_failed_pass_makes_its_documents_pilots_again(
        self, camp: _Camp
    ) -> None:
        run = camp.worker()
        pitch = camp.registered(run, QUESTION)
        camp.ended(run)
        job = camp.job_after(run, SessionState.FAILED)
        assert camp.of(pitch) is None

        retry = camp.retried(job, SessionState.HELD)

        assert camp.of(pitch) == PilotsWork(Doing.PRE_RULING, retry.id, True, None)


class TestTheClarification:
    def test_the_clarification_run_asking_its_writer_makes_the_asked_document_pilots(
        self, camp: _Camp
    ) -> None:
        run = camp.worker(conversation="conversation-1")
        pitch, survey = camp.registered(run, QUESTION), camp.registered(run, REPORT)
        camp.ended(run)
        job = camp.job_after(run)
        camp.ask_writer(job, pitch, "Q1")
        camp.ended(job)
        asking = camp.clarification(job, run, SessionState.HELD)

        assert camp.reading(pitch, survey) == {
            pitch.id: PilotsWork(Doing.ASKING_WRITER, None, True, None)
        }

        camp.ended(asking)
        after = camp.job_after(asking)

        assert camp.reading(pitch, survey) == {
            pitch.id: PilotsWork(Doing.PRE_RULING, after.id, True, None)
        }

        camp.ended(after)

        assert camp.reading(pitch, survey) == {}

    def test_a_clarification_run_that_fails_hands_the_document_over(
        self, camp: _Camp
    ) -> None:
        run = camp.worker(conversation="conversation-1")
        pitch = camp.registered(run, QUESTION)
        camp.ended(run)
        job = camp.job_after(run)
        camp.ask_writer(job, pitch, "Q1")
        camp.ended(job)
        camp.clarification(job, run, SessionState.FAILED)

        assert camp.of(pitch) is None


class TestAClaimHeldThroughItsRun:
    """A claimed action held through the run doing it (slice 036's rulings
    on 262 and 295), and the run done with it once a turn that asked the
    person nothing has had its job."""

    def _claimed(self, camp: _Camp) -> tuple[Item, models.Session]:
        writer = camp.worker()
        cut_over = camp.registered(writer, CLAIMED)
        camp.ended(writer)
        camp.ended(camp.job_after(writer))
        doing = camp.worker(SessionState.HELD, conversation="conversation-2")
        camp.claim(cut_over, "A1", doing)
        return cut_over, doing

    def test_its_work_item_queued_running_and_its_job_hold_it(
        self, camp: _Camp
    ) -> None:
        cut_over, doing = self._claimed(camp)
        assert camp.of(cut_over) == PilotsWork(Doing.DOING, doing.id, True, None)

        doing.state_code = SessionState.RUNNING
        camp.registered(doing, REPORT, read=False)
        camp.session.flush()
        assert camp.of(cut_over) == PilotsWork(Doing.DOING, doing.id, True, None)

        camp.ended(doing)
        # Its turn ended, its document awaiting its read: inside the hold.
        assert camp.of(cut_over) == PilotsWork(Doing.DOING, doing.id, False, None)

        report = camp.session.scalars(
            select(Item).where(
                Item.created_by_session_id == doing.id, Item.id != doing.id
            )
        ).one()
        camp.container.document_service().publish_read(
            camp.session.get_one(Document, report.id), REPORT, doing.id
        )
        job = camp.job_after(doing, SessionState.HELD)
        assert camp.of(cut_over) == PilotsWork(Doing.DOING, doing.id, True, None)
        assert holds(camp.session, [cut_over.id]).held.keys() == {
            camp.block(cut_over, "A1").id
        }

        camp.ended(job)

        assert camp.of(cut_over) is None
        assert holds(camp.session, [cut_over.id]).undone == {
            camp.block(cut_over, "A1").id
        }

    def test_a_question_the_run_puts_to_the_person_holds_it_until_the_continuations_job_ends(
        self, camp: _Camp
    ) -> None:
        cut_over, doing = self._claimed(camp)
        doing.state_code = SessionState.RUNNING
        question = camp.registered(doing, QUESTION)
        camp.ended(doing)
        camp.ended(camp.job_after(doing))

        assert camp.reading(cut_over, question) == {
            cut_over.id: PilotsWork(
                Doing.WAITING_ON_ANSWER, doing.id, False, question.id
            )
        }

        camp.answered(question, "Q1", "The lake")
        continuation = camp.continuation(doing)
        continuation.state_code = SessionState.RUNNING
        camp.session.flush()

        assert camp.of(cut_over) == PilotsWork(Doing.DOING, doing.id, True, None)

        camp.ended(continuation)
        job = camp.job_after(continuation)
        assert camp.of(cut_over) == PilotsWork(Doing.DOING, doing.id, True, None)

        camp.ended(job)

        assert camp.of(cut_over) is None
        assert holds(camp.session, [cut_over.id]).undone == {
            camp.block(cut_over, "A1").id
        }

    def test_a_clarification_runs_turn_never_makes_the_run_done(
        self, camp: _Camp
    ) -> None:
        cut_over, doing = self._claimed(camp)
        doing.state_code = SessionState.RUNNING
        question = camp.registered(doing, QUESTION)
        camp.ended(doing)
        job = camp.job_after(doing)
        camp.ask_writer(job, question, "Q1")
        camp.ended(job)
        asking = camp.clarification(job, doing)
        camp.ended(asking)
        camp.ended(camp.job_after(asking))

        assert camp.of(cut_over) == PilotsWork(
            Doing.WAITING_ON_ANSWER, doing.id, False, question.id
        )

    @pytest.mark.parametrize("down", ["failed", "stopped"])
    def test_its_work_item_failed_or_stopped_hands_it_back_until_a_resume(
        self, camp: _Camp, person: User, down: str
    ) -> None:
        cut_over, doing = self._claimed(camp)
        if down == "failed":
            doing.state_code = SessionState.FAILED
        else:
            camp.stopped(doing, by=person)
        camp.session.flush()

        assert camp.of(cut_over) is None
        assert holds(camp.session, [cut_over.id]).undone == {
            camp.block(cut_over, "A1").id
        }

        doing.state_code = SessionState.RUNNING
        camp.session.flush()

        assert camp.of(cut_over) == PilotsWork(Doing.DOING, doing.id, True, None)

    def test_a_hard_stop_owed_its_nudge_keeps_it_held(self, camp: _Camp) -> None:
        cut_over, doing = self._claimed(camp)
        camp.stopped(doing, by=camp.pilot())
        doing.nudge_owed_at = AT
        camp.session.flush()

        assert camp.of(cut_over) == PilotsWork(Doing.DOING, doing.id, False, None)

    def test_the_job_after_its_turn_failed_hands_it_back_for_the_rest_of_the_run_until_retried(
        self, camp: _Camp
    ) -> None:
        cut_over, doing = self._claimed(camp)
        doing.state_code = SessionState.RUNNING
        question = camp.registered(doing, QUESTION)
        camp.ended(doing)
        job = camp.job_after(doing, SessionState.FAILED)
        assert camp.of(cut_over) is None

        camp.answered(question, "Q1", "The lake")
        continuation = camp.continuation(doing)

        assert camp.of(cut_over) is None
        path = camp.session.get_one(Document, cut_over.id).path
        assert handed_back_in(camp.session, continuation.id) == [
            (cut_over.id, path, "A1")
        ]
        first = camp.session.scalars(
            select(Turn.message).where(Turn.session_id == continuation.id)
        ).one()
        assert first.splitlines()[-1] == (
            f"Handed back to the operator, so leave these to them: A1 of {path}"
            f" ({cut_over.id})."
        )

        camp.retried(job)

        assert camp.of(cut_over) == PilotsWork(Doing.DOING, doing.id, True, None)
        assert handed_back_in(camp.session, continuation.id) == []

    def test_a_later_naming_stands(self, camp: _Camp) -> None:
        cut_over, doing = self._claimed(camp)
        doing.state_code = SessionState.FAILED
        again = camp.worker(conversation="conversation-3")
        camp.claim(cut_over, "A1", again)

        assert camp.of(cut_over) == PilotsWork(Doing.DOING, again.id, True, None)

    def test_a_document_with_an_open_block_besides_is_the_persons_its_claim_held(
        self, camp: _Camp
    ) -> None:
        writer = camp.worker()
        cut_over = camp.registered(writer, CLAIMED_AND_OPEN)
        camp.ended(writer)
        camp.ended(camp.job_after(writer))
        doing = camp.worker()
        camp.claim(cut_over, "A1", doing)

        assert camp.of(cut_over) is None
        reading = holds(camp.session, [cut_over.id])
        assert reading.held == {
            camp.block(cut_over, "A1").id: reading.held[camp.block(cut_over, "A1").id]
        }
        assert reading.held[camp.block(cut_over, "A1").id].work_id == doing.id

    def test_a_claim_no_work_item_is_named_for_is_the_persons(
        self, camp: _Camp
    ) -> None:
        writer = camp.worker()
        cut_over = camp.registered(writer, CLAIMED)
        camp.ended(writer)
        camp.ended(camp.job_after(writer))

        assert camp.of(cut_over) is None
        assert holds(camp.session, [cut_over.id]) == holds(camp.session, [])


class TestAResearch:
    def _researched(self, camp: _Camp) -> tuple[Item, models.Session]:
        writer = camp.worker()
        pitch = camp.registered(writer, QUESTION)
        camp.ended(writer)
        camp.ended(camp.job_after(writer))
        checking = camp.worker(conversation="conversation-2")
        camp.research(pitch, "Q1", checking)
        return pitch, checking

    def test_its_run_holds_the_block_until_the_pass_after_its_answer_ends(
        self, camp: _Camp
    ) -> None:
        pitch, checking = self._researched(camp)
        assert camp.of(pitch) == PilotsWork(Doing.RESEARCHING, checking.id, True, None)

        answer = camp.registered(checking, REPORT)
        camp.ended(checking)
        job = camp.job_after(checking)
        assert camp.reading(pitch, answer) == {
            pitch.id: PilotsWork(Doing.RESEARCHING, checking.id, True, None),
            answer.id: PilotsWork(Doing.PRE_RULING, job.id, True, None),
        }

        camp.ended(job)

        assert camp.reading(pitch, answer) == {}
        assert holds(camp.session, [pitch.id]) == holds(camp.session, [])

    def test_one_that_asks_the_person_first_holds_it_until_answered(
        self, camp: _Camp
    ) -> None:
        pitch, checking = self._researched(camp)
        asked = camp.registered(checking, QUESTION)
        camp.ended(checking)
        camp.ended(camp.job_after(checking))

        assert camp.of(pitch) == PilotsWork(
            Doing.WAITING_ON_ANSWER, checking.id, False, asked.id
        )

    def test_a_researched_block_answered_is_no_longer_held(self, camp: _Camp) -> None:
        pitch, _ = self._researched(camp)
        camp.container.record_service().answer(
            camp.session.get_one(Document, pitch.id),
            "Q1",
            camp.session.scalars(select(User).where(User.handle == "ada")).one(),
            "The lake",
        )

        assert holds(camp.session, [pitch.id]) == holds(camp.session, [])


class TestWhatWaits:
    """`waiting()` leaves out every item that is Pilot's, so that the badge,
    the project's status and the standing notification follow it, live
    (F94.5, F1.4; DB 225)."""

    ADA = AuthContext(
        subject="subject-ada", email=None, name="Ada Example", roles={"editor"}
    )

    def _waits(
        self, camp: _Camp, person: User
    ) -> tuple[Badge | None, ProjectStatus | None, NotificationPriority]:
        """The badge, the project's status and the priority of the standing
        notification, as Ada reads them."""
        badge = camp.container.timeline_service().badges(person, [camp.project.id])
        status = next(
            tab.status
            for tab in camp.container.project_service().tabs(self.ADA, archived=False)
            if tab.project.id == camp.project.id
        )
        membership = camp.session.scalars(
            select(ProjectMember).where(
                ProjectMember.project_id == camp.project.id,
                ProjectMember.user_id == person.id,
            )
        ).one()
        seen = camp.container.standing_notification_service().should_see(
            camp.project, [membership]
        )[membership.id]
        assert seen is not None
        return badge.get(camp.project.id), status, seen.priority

    def test_a_document_under_its_pass_waits_once_the_pass_ends(
        self, camp: _Camp, person: User, engine_events: list[EngineEvent]
    ) -> None:
        person.notification_token = camp.container.notification_token_cipher().seal(
            "token-of-ada"
        )
        run = camp.worker()
        camp.registered(run, QUESTION)
        camp.ended(run)
        job = camp.job_after(run, SessionState.HELD)

        assert self._waits(camp, person) == (
            None,
            ProjectStatus.IDLE,
            NotificationPriority.MIN,
        )

        clear_after_commit_callbacks()
        with scoped_session(camp.container):
            camp.ended(job)

        assert ProjectChanged(camp.project.id) in engine_events
        assert self._waits(camp, person) == (
            Badge(1, False),
            ProjectStatus.WAITING_ON_YOU,
            NotificationPriority.DEFAULT,
        )

    def test_a_document_read_waits_on_no_one_until_its_runs_last_read_and_pass(
        self, camp: _Camp, person: User
    ) -> None:
        person.notification_token = camp.container.notification_token_cipher().seal(
            "token-of-ada"
        )
        run = camp.worker()
        first = camp.registered(run, read=False)
        second = camp.registered(run, read=False)
        camp.ended(run)
        documents = camp.container.document_service()
        documents.publish_read(
            camp.session.get_one(Document, first.id), QUESTION, run.id
        )
        idle = (None, ProjectStatus.IDLE, NotificationPriority.MIN)

        assert self._waits(camp, person) == idle

        documents.publish_read(
            camp.session.get_one(Document, second.id), REPORT, run.id
        )
        job = camp.job_after(run, SessionState.HELD)

        assert self._waits(camp, person) == idle

        camp.ended(job)

        assert self._waits(camp, person) == (
            Badge(2, False),
            ProjectStatus.WAITING_ON_YOU,
            NotificationPriority.DEFAULT,
        )

    def test_a_document_held_by_a_queued_work_item_waits_once_it_fails(
        self, camp: _Camp, person: User
    ) -> None:
        person.notification_token = camp.container.notification_token_cipher().seal(
            "token-of-ada"
        )
        writer = camp.worker()
        cut_over = camp.registered(writer, CLAIMED)
        camp.ended(writer)
        camp.ended(camp.job_after(writer))
        doing = camp.worker(SessionState.HELD)
        camp.claim(cut_over, "A1", doing)

        assert self._waits(camp, person) == (
            None,
            ProjectStatus.IDLE,
            NotificationPriority.MIN,
        )

        doing.state_code = SessionState.FAILED
        camp.session.flush()

        # The failed work item waits too (F125).
        assert self._waits(camp, person) == (
            Badge(2, False),
            ProjectStatus.WAITING_ON_YOU,
            NotificationPriority.DEFAULT,
        )
