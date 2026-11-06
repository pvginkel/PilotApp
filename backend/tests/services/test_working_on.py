"""What Pilot is working on (F13.7, F21.6, F52.3, F94.5; DB 294 to 296, held
through the run): a registered document Pilot's while its read is awaited,
while its pass or its clarification is in flight, or while every open block
is held, and the person's otherwise; a block held through its run until the
run is done with it, and handed back at once while something of the run
stands failed or stopped."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.engine.bus import EngineEvent, ProjectChanged
from app.models import (
    Document,
    Item,
    ProjectMember,
    StoreUpdate,
    Turn,
    User,
)
from app.models.reference import SessionState
from app.schemas.projects import ProjectStatus
from app.services.auth_service import AuthContext
from app.services.container import ServiceContainer
from app.services.timeline_service import Badge
from app.services.working_on import (
    Cancel,
    Doing,
    PilotsWork,
    TakenBack,
    cancels,
    flying,
    handed_back_in,
    holding_work,
    holds,
    run_documents,
)
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.working_on import AT, Camp

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

_RUNNING_STATES = (SessionState.HELD, SessionState.STARTING, SessionState.RUNNING)


@pytest.fixture
def camp(container: ServiceContainer, session: DbSession, person: User) -> Camp:
    return Camp(container, session)


class TestAwaitingItsRead:
    def test_a_registered_document_awaiting_its_read_is_pilots_linking_its_run(
        self, camp: Camp
    ) -> None:
        run = camp.worker()
        awaiting = camp.registered(run, read=False)

        assert camp.of(awaiting) == PilotsWork(Doing.AWAITING_RUN, run.id, False, None)

    def test_once_read_with_nothing_of_pilots_in_flight_it_is_the_persons(
        self, camp: Camp
    ) -> None:
        run = camp.worker()
        read = camp.registered(run, QUESTION)
        failed = camp.registered(run, read=False)
        camp.container.document_service().fail_read(
            camp.session.get_one(Document, failed.id)
        )

        assert camp.reading(read, failed) == {}

    def test_a_read_document_is_pilots_while_another_of_its_run_awaits_its_read(
        self, camp: Camp
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
        self, camp: Camp
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
        self, camp: Camp, state: SessionState, pulse: bool
    ) -> None:
        run = camp.worker()
        survey, pitch = camp.registered(run, REPORT), camp.registered(run, QUESTION)
        camp.ended(run)
        job = camp.job_after(run, state)

        assert camp.reading(survey, pitch) == {
            survey.id: PilotsWork(Doing.PRE_RULING, job.id, pulse, None),
            pitch.id: PilotsWork(Doing.PRE_RULING, job.id, pulse, None),
        }

    def test_a_pass_in_flight_leaves_the_work_item_whose_turn_it_follows_alone(
        self, camp: Camp
    ) -> None:
        # Its own Session created the work item's Item, as it registered the
        # documents: the pass is over the documents alone.
        run = camp.worker(SessionState.IDLE)
        survey = camp.registered(run, REPORT)
        job = camp.job_after(run)

        assert camp.reading(camp.session.get_one(Item, run.id), survey) == {
            survey.id: PilotsWork(Doing.PRE_RULING, job.id, True, None),
        }

    def test_a_pass_owed_its_nudge_is_in_flight_without_a_pulse(
        self, camp: Camp
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
        self, camp: Camp
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
        self, camp: Camp, person: User, ending: str
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
        self, camp: Camp
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
        self, camp: Camp
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
        self, camp: Camp
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

    def _claimed(self, camp: Camp) -> tuple[Item, models.Session]:
        writer = camp.worker()
        cut_over = camp.registered(writer, CLAIMED)
        camp.ended(writer)
        camp.ended(camp.job_after(writer))
        doing = camp.worker(SessionState.HELD, conversation="conversation-2")
        camp.claim(cut_over, "A1", doing)
        return cut_over, doing

    def test_its_work_item_queued_running_and_its_job_hold_it(self, camp: Camp) -> None:
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
        self, camp: Camp
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
        self, camp: Camp
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
        self, camp: Camp, person: User, down: str
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

    def test_a_hard_stop_owed_its_nudge_keeps_it_held(self, camp: Camp) -> None:
        cut_over, doing = self._claimed(camp)
        camp.stopped(doing, by=camp.pilot())
        doing.nudge_owed_at = AT
        camp.session.flush()

        assert camp.of(cut_over) == PilotsWork(Doing.DOING, doing.id, False, None)

    def test_the_job_after_its_turn_failed_hands_it_back_for_the_rest_of_the_run_until_retried(
        self, camp: Camp
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

    def test_a_later_naming_stands(self, camp: Camp) -> None:
        cut_over, doing = self._claimed(camp)
        doing.state_code = SessionState.FAILED
        again = camp.worker(conversation="conversation-3")
        camp.claim(cut_over, "A1", again)

        assert camp.of(cut_over) == PilotsWork(Doing.DOING, again.id, True, None)

    def test_a_document_with_an_open_block_besides_is_the_persons_its_claim_held(
        self, camp: Camp
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

    def test_a_claim_no_work_item_is_named_for_is_the_persons(self, camp: Camp) -> None:
        writer = camp.worker()
        cut_over = camp.registered(writer, CLAIMED)
        camp.ended(writer)
        camp.ended(camp.job_after(writer))

        assert camp.of(cut_over) is None
        assert holds(camp.session, [cut_over.id]) == holds(camp.session, [])


class TestAResearch:
    def _researched(self, camp: Camp) -> tuple[Item, models.Session]:
        writer = camp.worker()
        pitch = camp.registered(writer, QUESTION)
        camp.ended(writer)
        camp.ended(camp.job_after(writer))
        checking = camp.worker(conversation="conversation-2")
        camp.research(pitch, "Q1", checking)
        return pitch, checking

    def test_its_run_holds_the_block_until_the_pass_after_its_answer_ends(
        self, camp: Camp
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
        self, camp: Camp
    ) -> None:
        pitch, checking = self._researched(camp)
        asked = camp.registered(checking, QUESTION)
        camp.ended(checking)
        camp.ended(camp.job_after(checking))

        assert camp.of(pitch) == PilotsWork(
            Doing.WAITING_ON_ANSWER, checking.id, False, asked.id
        )

    def test_a_researched_block_answered_is_no_longer_held(self, camp: Camp) -> None:
        pitch, _ = self._researched(camp)
        camp.container.record_service().answer(
            camp.session.get_one(Document, pitch.id),
            "Q1",
            camp.session.scalars(select(User).where(User.handle == "ada")).one(),
            "The lake",
        )

        assert holds(camp.session, [pitch.id]) == holds(camp.session, [])


class TestACancel:
    """A Cancel on an open registered document of a run that is the
    person's (DB 297 to 299): offered while nothing of the run is in flight
    and it holds a Block of another document; once one of its documents is
    closed `cancelled`, the run holds nothing."""

    def _asking(
        self, camp: Camp, *, research: bool = False
    ) -> tuple[Item, models.Session, Item]:
        """A document whose one block a work item's run holds, a claimed
        action or a researched question, and the open question that run put
        to the person, its pass over."""
        writer = camp.worker()
        held = camp.registered(writer, QUESTION if research else CLAIMED)
        camp.ended(writer)
        camp.ended(camp.job_after(writer))
        doing = camp.worker(conversation="conversation-2")
        if research:
            camp.research(held, "Q1", doing)
        else:
            camp.claim(held, "A1", doing)
        asked = camp.registered(doing, QUESTION)
        return held, doing, asked

    def _waits(self, camp: Camp, doing: models.Session) -> None:
        camp.ended(doing)
        camp.ended(camp.job_after(doing))

    def _cancel(self, camp: Camp, document: Item, person: User) -> None:
        reading = cancels(camp.session, [document.id])[document.id]
        camp.container.record_service().cancel(
            camp.project,
            run_documents(camp.session, reading.run_id),
            person,
            "cancel the run",
        )

    def test_it_is_offered_on_each_document_of_a_run_that_waits_on_the_person(
        self, camp: Camp
    ) -> None:
        cut_over, doing, asked = self._asking(camp)
        report = camp.registered(doing, REPORT)
        self._waits(camp, doing)
        taken = (TakenBack(camp.block(cut_over, "A1").id, cut_over.id, False),)

        found = cancels(camp.session, [cut_over.id, asked.id, report.id, doing.id])

        # The held document is Pilot's, and a work item no document.
        assert found == {
            asked.id: Cancel(doing.id, taken, False, False),
            report.id: Cancel(doing.id, taken, False, False),
        }
        assert found[asked.id].offered

    def test_a_cancel_ends_the_run_and_hands_the_claim_back(
        self, camp: Camp, person: User
    ) -> None:
        cut_over, doing, asked = self._asking(camp)
        report = camp.registered(doing, REPORT)
        self._waits(camp, doing)

        self._cancel(camp, asked, person)

        assert (asked.done_cause_code, report.done_cause_code) == (
            "cancelled",
            "cancelled",
        )
        assert camp.of(cut_over) is None
        assert holds(camp.session, [cut_over.id]).undone == {
            camp.block(cut_over, "A1").id
        }
        assert cancels(camp.session, [asked.id, report.id]) == {}
        assert handed_back_in(camp.session, doing.id) == [
            (
                cut_over.id,
                camp.session.get_one(Document, cut_over.id).path,
                "A1",
            )
        ]

    def test_a_researched_block_whose_work_asked_first_is_open_again(
        self, camp: Camp, person: User
    ) -> None:
        pitch, doing, asked = self._asking(camp, research=True)
        self._waits(camp, doing)
        assert cancels(camp.session, [asked.id])[asked.id].takes_back == (
            TakenBack(camp.block(pitch, "Q1").id, pitch.id, True),
        )

        self._cancel(camp, asked, person)

        assert camp.of(pitch) is None
        assert holds(camp.session, [pitch.id]) == holds(camp.session, [])

    def test_it_is_not_offered_while_something_of_the_run_is_in_flight(
        self, camp: Camp
    ) -> None:
        _, doing, asked = self._asking(camp)
        other = camp.registered(doing, QUESTION)
        camp.ended(doing)
        pass_ = camp.job_after(doing)
        camp.ask_writer(pass_, other, "Q1")
        camp.ended(pass_)
        camp.clarification(pass_, doing)

        reading = cancels(camp.session, [asked.id, other.id])

        # The other is Pilot's while its writer is asked.
        assert reading.keys() == {asked.id}
        assert reading[asked.id].going_on
        assert not reading[asked.id].offered

    def test_it_is_not_offered_while_another_run_holds_a_block_of_the_runs(
        self, camp: Camp
    ) -> None:
        _, doing, asked = self._asking(camp)
        actions = camp.registered(doing, CLAIMED)
        self._waits(camp, doing)
        third = camp.worker(conversation="conversation-3")
        camp.claim(actions, "A1", third)

        reading = cancels(camp.session, [asked.id])[asked.id]

        assert (reading.going_on, reading.pilots_in_run) == (False, True)
        assert not reading.offered
        self._waits(camp, third)
        assert cancels(camp.session, [asked.id])[asked.id].offered

    def test_it_is_not_offered_on_a_document_of_a_run_that_holds_nothing(
        self, camp: Camp
    ) -> None:
        writer = camp.worker()
        pitch = camp.registered(writer, QUESTION)
        camp.ended(writer)
        camp.ended(camp.job_after(writer))

        reading = cancels(camp.session, [pitch.id])

        assert reading == {pitch.id: Cancel(writer.id, (), False, False)}
        assert not reading[pitch.id].offered

    def test_the_runs_documents_follow_its_conversation(
        self, camp: Camp, person: User
    ) -> None:
        _, doing, first = self._asking(camp)
        self._waits(camp, doing)
        camp.answered(first, "Q1", "The lake")
        continuation = camp.continuation(doing)
        second = camp.registered(continuation, QUESTION)
        third = camp.registered(continuation, REPORT)
        self._waits(camp, continuation)

        assert run_documents(camp.session, doing.id) == [second.id, third.id]
        assert run_documents(camp.session, continuation.id) == [second.id, third.id]
        assert cancels(camp.session, [second.id])[second.id].run_id == continuation.id


class TestWhatWaits:
    """`waiting()` leaves out every item that is Pilot's, so that the badge,
    the project's status and the standing notification follow it, live
    (F94.5, F1.4; DB 225)."""

    ADA = AuthContext(
        subject="subject-ada", email=None, name="Ada Example", roles={"editor"}
    )

    def _waits(
        self, camp: Camp, person: User
    ) -> tuple[Badge | None, ProjectStatus | None, bool]:
        """The badge, the project's status and whether the standing
        notification stands, as Ada reads them."""
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
        return badge.get(camp.project.id), status, seen is not None

    def test_a_document_under_its_pass_waits_once_the_pass_ends(
        self, camp: Camp, person: User, engine_events: list[EngineEvent]
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
            False,
        )

        clear_after_commit_callbacks()
        with scoped_session(camp.container):
            camp.ended(job)

        assert ProjectChanged(camp.project.id) in engine_events
        assert self._waits(camp, person) == (
            Badge(1, False),
            ProjectStatus.WAITING_ON_YOU,
            True,
        )

    def test_a_document_read_waits_on_no_one_until_its_runs_last_read_and_pass(
        self, camp: Camp, person: User
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
        idle = (None, ProjectStatus.IDLE, False)

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
            True,
        )

    def test_a_document_held_by_a_queued_work_item_waits_once_it_fails(
        self, camp: Camp, person: User
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
            False,
        )

        doing.state_code = SessionState.FAILED
        camp.session.flush()

        # The failed work item waits too (F125).
        assert self._waits(camp, person) == (
            Badge(2, False),
            ProjectStatus.WAITING_ON_YOU,
            True,
        )


class TestFlying:
    def test_it_finds_the_works_in_flight_among_those_named(
        self, camp: Camp, person: User
    ) -> None:
        running = camp.worker()
        owed = camp.worker()
        camp.stopped(owed, by=camp.pilot())
        owed.nudge_owed_at = AT
        stopped = camp.worker()
        camp.stopped(stopped, by=person)
        done = camp.worker()
        camp.ended(done)

        assert flying(camp.session, [running.id, owed.id, stopped.id, done.id]) == {
            running.id,
            owed.id,
        }


class TestHoldingWork:
    """What Stop and take over stops on a document that is Pilot's (F28.9)."""

    def test_the_pass_over_it_a_retry_included(self, camp: Camp) -> None:
        run = camp.worker()
        pitch = camp.registered(run, QUESTION)
        camp.ended(run)
        job = camp.job_after(run)
        job.state_code = SessionState.FAILED
        retry = camp.retried(job, SessionState.HELD)

        assert holding_work(camp.session, pitch.id) == [retry.id]

    def test_the_clarification_run_asking_its_writer_then_the_job_after_its_reply(
        self, camp: Camp
    ) -> None:
        run = camp.worker(conversation="conversation-1")
        pitch = camp.registered(run, QUESTION)
        camp.ended(run)
        pass_ = camp.job_after(run)
        camp.ask_writer(pass_, pitch, "Q1")
        camp.ended(pass_)
        clarifying = camp.clarification(pass_, run)

        assert holding_work(camp.session, pitch.id) == [clarifying.id]

        camp.ended(clarifying)
        after = camp.job_after(clarifying)

        assert holding_work(camp.session, pitch.id) == [after.id]

    def test_what_of_the_run_holding_every_open_block_is_in_flight(
        self, camp: Camp
    ) -> None:
        writer = camp.worker()
        cut_over = camp.registered(writer, CLAIMED)
        camp.ended(writer)
        camp.ended(camp.job_after(writer))
        doing = camp.worker(conversation="conversation-2")
        camp.claim(cut_over, "A1", doing)

        assert holding_work(camp.session, cut_over.id) == [doing.id]

        camp.ended(doing)
        job = camp.job_after(doing)

        assert holding_work(camp.session, cut_over.id) == [job.id]

    def test_none_while_the_holding_run_waits_on_the_person(self, camp: Camp) -> None:
        writer = camp.worker()
        cut_over = camp.registered(writer, CLAIMED)
        camp.ended(writer)
        camp.ended(camp.job_after(writer))
        doing = camp.worker(conversation="conversation-2")
        camp.claim(cut_over, "A1", doing)
        camp.registered(doing, QUESTION)
        camp.ended(doing)
        camp.ended(camp.job_after(doing))

        assert camp.of(cut_over) is not None
        assert holding_work(camp.session, cut_over.id) == []

    def test_none_for_a_held_block_beside_an_open_one(self, camp: Camp) -> None:
        writer = camp.worker()
        cut_over = camp.registered(writer, CLAIMED_AND_OPEN)
        camp.ended(writer)
        camp.ended(camp.job_after(writer))
        camp.claim(cut_over, "A1", camp.worker(conversation="conversation-2"))

        assert holding_work(camp.session, cut_over.id) == []

    def test_none_while_it_awaits_its_read(self, camp: Camp) -> None:
        run = camp.worker()
        pitch = camp.registered(run, read=False)
        camp.ended(run)

        assert holding_work(camp.session, pitch.id) == []
