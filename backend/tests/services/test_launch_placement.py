"""A Launch placed under the Session and the Turn of Pilot's that started it
(DB decision 79 point 7; assertions 537 and 538; F152.4, F152.9).

The rule that protects the most: a Launch a Turn started is placed once,
under the Session whose Turn was sent last before its start, and what it was
placed under stands whatever Turn follows (`TestPlacedOnce`). A round a
driver started is on the work item that was running when its process
started, however many work items' steps name it and whichever Pilot held
first, the round or a step's naming (`TestDriverStarted`)."""

import logging
import uuid
from datetime import datetime, timedelta

import pytest
from flask import Flask
from pilot_collection.publication import PublicationSchema
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.models import (
    ComponentVersion,
    Environment,
    Launch,
    ProgressStep,
    Project,
    Transcript,
    User,
)
from app.models.reference import SessionState, UserKind
from app.schemas.pilot_work import ProgressStepRequestSchema
from app.services.container import ServiceContainer
from app.services.launch_placement import conversation_named, place_launches
from app.services.pilot_work_service import Worker
from tests.support import publications, transcripts
from tests.support.adoption import adopted_project
from tests.support.database import writes
from tests.support.locks import in_thread, lock_waits
from tests.support.supervisor import wait_until
from tests.support.transcripts import CAMP, OTHER, STARTED, SUB_AGENT
from tests.support.turns import turn_at

LOGGER = "app.services.launch_placement"


def _at(minutes: int) -> datetime:
    return STARTED + timedelta(minutes=minutes)


@pytest.fixture
def collector(session: DbSession) -> ComponentVersion:
    return transcripts.component_version(session)


@pytest.fixture
def thread(session: DbSession, collector: ComponentVersion) -> Transcript:
    """The conversation's main thread."""
    return transcripts.transcript(session, collector)


@pytest.fixture
def run(session: DbSession, project_session: models.Session) -> models.Session:
    """A Session of Pilot's that names the conversation."""
    project_session.conversation_id = CAMP
    session.flush()
    return project_session


def _camp() -> PublicationSchema:
    """The main thread's publication: one Launch, begun a minute into the
    Session's Turn."""
    return publications.whole(
        launches=[publications.launch(started_at=_at(1).isoformat())]
    )


def _carrying_on(db: DbSession, run: models.Session) -> models.Session:
    """A later Session of `run`'s project on `run`'s conversation."""
    later = models.Session(
        project_id=run.project_id,
        environment_id=run.environment_id,
        kind_code="work",
        cwd="/work/Example",
        conversation_id=run.conversation_id,
        token_hash=uuid.uuid4().hex,
        state_code=SessionState.RUNNING,
    )
    db.add(later)
    db.flush()
    return later


@pytest.fixture
def waited(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
    project_session: models.Session,
) -> models.Session:
    """A Session of Pilot's that is a Work, created ten minutes before the
    conversation began, whose step names the conversation: the one that
    waited on the loop a driver ran it in."""
    project_session.created_at = _at(-10)
    container.record_service().place_work(project, project_session, "Scaling")
    transcripts.named_by_step(session, project_session)
    return project_session


def _continuing(
    db: DbSession,
    container: ServiceContainer,
    project: Project,
    run: models.Session,
    created_at: datetime,
) -> models.Session:
    """A later Work of `run`'s project, created at `created_at`, whose step
    names the conversation again: the continuation of `run`'s."""
    later = models.Session(
        project_id=run.project_id,
        environment_id=run.environment_id,
        kind_code="work",
        cwd="/work/Example",
        token_hash=uuid.uuid4().hex,
        state_code=SessionState.RUNNING,
        created_at=created_at,
    )
    db.add(later)
    db.flush()
    container.record_service().place_work(project, later, "Scaling, continued")
    transcripts.named_by_step(db, later)
    return later


def _placed(db: DbSession, launch: Launch) -> tuple[uuid.UUID | None, int | None]:
    """The Session and the Turn the Launch stands under, as the record holds
    them."""
    row = db.execute(
        select(Launch.session_id, Launch.turn_seq).where(Launch.id == launch.id)
    ).one()
    return row.session_id, row.turn_seq


class TestPlaced:
    def test_a_launch_started_during_a_turn_is_under_its_session_and_that_turn(
        self, session: DbSession, thread: Transcript, run: models.Session
    ) -> None:
        turn_at(session, run, _at(0))
        launch = transcripts.launch(session, thread, started_at=_at(1))

        place_launches(session, CAMP)

        assert _placed(session, launch) == (run.id, 1)

    def test_a_launch_is_under_the_turn_that_was_in_flight_at_its_start(
        self, session: DbSession, thread: Transcript, run: models.Session
    ) -> None:
        turn_at(session, run, _at(0), _at(9))
        turn_at(session, run, _at(20), _at(29))
        turn_at(session, run, _at(40))
        launch = transcripts.launch(session, thread, started_at=_at(21))

        place_launches(session, CAMP)

        assert _placed(session, launch) == (run.id, 2)

    def test_a_launch_started_as_its_turn_was_sent_is_under_that_turn(
        self, session: DbSession, thread: Transcript, run: models.Session
    ) -> None:
        turn_at(session, run, _at(0), _at(9))
        turn_at(session, run, _at(20))
        launch = transcripts.launch(session, thread, started_at=_at(20))

        place_launches(session, CAMP)

        assert _placed(session, launch) == (run.id, 2)

    def test_a_launch_started_as_a_turn_ended_is_under_that_turn(
        self, session: DbSession, thread: Transcript, run: models.Session
    ) -> None:
        turn_at(session, run, _at(0), _at(9))
        launch = transcripts.launch(session, thread, started_at=_at(9))

        place_launches(session, CAMP)

        assert _placed(session, launch) == (run.id, 1)

    def test_a_launch_started_between_two_turns_has_the_session_and_no_turn(
        self, session: DbSession, thread: Transcript, run: models.Session
    ) -> None:
        turn_at(session, run, _at(0), _at(9))
        turn_at(session, run, _at(20))
        launch = transcripts.launch(session, thread, started_at=_at(12))

        place_launches(session, CAMP)

        assert _placed(session, launch) == (run.id, None)

    def test_a_launch_started_before_every_turn_of_the_conversation_has_neither(
        self, session: DbSession, thread: Transcript, run: models.Session
    ) -> None:
        turn_at(session, run, _at(5))
        launch = transcripts.launch(session, thread, started_at=_at(1))

        place_launches(session, CAMP)

        assert _placed(session, launch) == (None, None)

    def test_each_launch_is_under_the_session_whose_turn_started_it(
        self, session: DbSession, thread: Transcript, run: models.Session
    ) -> None:
        """A conversation a later Session carries on (DB 183): each Session's
        Turns count from 1, so the earlier's Turn 2 comes before the later's
        Turn 1 by time alone."""
        later = _carrying_on(session, run)
        turn_at(session, run, _at(0), _at(9))
        turn_at(session, run, _at(20), _at(29))
        turn_at(session, later, _at(60))
        first = transcripts.launch(session, thread, started_at=_at(1))
        second = transcripts.launch(session, thread, started_at=_at(61))

        place_launches(session, CAMP)

        assert [_placed(session, first), _placed(session, second)] == [
            (run.id, 1),
            (later.id, 1),
        ]

    def test_a_launch_started_between_two_sessions_turns_is_the_earlier_sessions(
        self, session: DbSession, thread: Transcript, run: models.Session
    ) -> None:
        later = _carrying_on(session, run)
        turn_at(session, run, _at(0), _at(9))
        turn_at(session, later, _at(60))
        launch = transcripts.launch(session, thread, started_at=_at(30))

        place_launches(session, CAMP)

        assert _placed(session, launch) == (run.id, None)

    def test_a_transcript_no_session_names_keeps_its_launches_unplaced(
        self, session: DbSession, thread: Transcript, project_session: models.Session
    ) -> None:
        turn_at(session, project_session, _at(0))
        launch = transcripts.launch(session, thread, started_at=_at(1))

        with writes(session) as wrote:
            place_launches(session, CAMP)

        assert _placed(session, launch) == (None, None)
        assert wrote == {}

    def test_a_session_of_another_conversation_runs_none_of_its_launches(
        self, session: DbSession, thread: Transcript, project_session: models.Session
    ) -> None:
        project_session.conversation_id = OTHER
        turn_at(session, project_session, _at(0))
        launch = transcripts.launch(session, thread, started_at=_at(1))

        place_launches(session, CAMP)
        place_launches(session, OTHER)

        assert _placed(session, launch) == (None, None)

    def test_another_conversations_launches_are_left_alone(
        self,
        session: DbSession,
        collector: ComponentVersion,
        thread: Transcript,
        run: models.Session,
    ) -> None:
        turn_at(session, run, _at(0))
        other = transcripts.transcript(session, collector, session_id=OTHER)
        launch = transcripts.launch(session, other, started_at=_at(1))

        place_launches(session, CAMP)

        assert _placed(session, launch) == (None, None)

    def test_a_conversation_with_a_sub_agents_thread_alone_places_nothing(
        self, session: DbSession, collector: ComponentVersion, run: models.Session
    ) -> None:
        turn_at(session, run, _at(0))
        transcripts.transcript(session, collector, agent_id=SUB_AGENT)

        with writes(session) as wrote:
            place_launches(session, CAMP)

        assert wrote == {}


class TestDriverStarted:
    """A Launch a driver started under a loop session continues a Transcript
    no Session's `conversation_id` names, which a step of the Session that
    waited on its loop names (DB 538; F152.9)."""

    def test_it_is_under_the_session_whose_step_names_it_and_its_turn_in_flight(
        self, session: DbSession, thread: Transcript, waited: models.Session
    ) -> None:
        turn_at(session, waited, _at(-9), _at(-5))
        turn_at(session, waited, _at(-1))
        launch = transcripts.launch(session, thread, started_at=_at(1))

        place_launches(session, CAMP)

        assert _placed(session, launch) == (waited.id, 2)

    def test_one_started_between_two_turns_has_the_session_and_no_turn(
        self, session: DbSession, thread: Transcript, waited: models.Session
    ) -> None:
        turn_at(session, waited, _at(-9), _at(-5))
        turn_at(session, waited, _at(20))
        launch = transcripts.launch(session, thread, started_at=_at(1))

        place_launches(session, CAMP)

        assert _placed(session, launch) == (waited.id, None)

    def test_one_started_before_the_sessions_first_turn_has_the_session_and_no_turn(
        self, session: DbSession, thread: Transcript, waited: models.Session
    ) -> None:
        turn_at(session, waited, _at(20))
        launch = transcripts.launch(session, thread, started_at=_at(1))

        place_launches(session, CAMP)

        assert _placed(session, launch) == (waited.id, None)

    def test_one_started_before_the_session_was_created_has_neither(
        self, session: DbSession, thread: Transcript, waited: models.Session
    ) -> None:
        turn_at(session, waited, _at(-9))
        launch = transcripts.launch(session, thread, started_at=_at(-11))

        with writes(session) as wrote:
            place_launches(session, CAMP)

        assert _placed(session, launch) == (None, None)
        assert wrote == {}

    def test_a_round_a_continuation_names_again_stays_on_the_work_that_ran_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        thread: Transcript,
        waited: models.Session,
    ) -> None:
        """F152.9: the step stands on both work items' lists, and the round
        on the one created last before its process started."""
        turn_at(session, waited, _at(-9), _at(30))
        continuation = _continuing(session, container, project, waited, _at(40))
        turn_at(session, continuation, _at(41))
        launch = transcripts.launch(session, thread, started_at=_at(1))

        place_launches(session, CAMP)

        assert _placed(session, launch) == (waited.id, 1)

    def test_a_round_started_under_the_continuation_is_the_continuations(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        thread: Transcript,
        waited: models.Session,
    ) -> None:
        """A loop session the continuation's driver resumed: its two
        Launches are on the two work items."""
        turn_at(session, waited, _at(-9), _at(30))
        continuation = _continuing(session, container, project, waited, _at(40))
        turn_at(session, continuation, _at(41))
        first = transcripts.launch(session, thread, started_at=_at(1), ended_at=_at(9))
        resumed = transcripts.launch(session, thread, started_at=_at(45))

        place_launches(session, CAMP)

        assert [_placed(session, first), _placed(session, resumed)] == [
            (waited.id, 1),
            (continuation.id, 1),
        ]

    def test_a_session_whose_step_names_another_conversation_runs_none_of_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        thread: Transcript,
    ) -> None:
        container.record_service().place_work(project, project_session, "Scaling")
        project_session.created_at = _at(-10)
        transcripts.named_by_step(session, project_session, OTHER)
        turn_at(session, project_session, _at(-9))
        launch = transcripts.launch(session, thread, started_at=_at(1))

        with writes(session) as wrote:
            place_launches(session, CAMP)

        assert _placed(session, launch) == (None, None)
        assert wrote == {}

    def test_a_conversation_a_session_names_is_placed_by_its_turns_alone(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        thread: Transcript,
        waited: models.Session,
    ) -> None:
        """A step that names the thread its own Session's Turn started: the
        Launch from before that Session's first Turn stays unplaced, as a
        Turn-started one does."""
        waited.conversation_id = CAMP
        turn_at(session, waited, _at(5))
        launch = transcripts.launch(session, thread, started_at=_at(1))

        place_launches(session, CAMP)

        assert _placed(session, launch) == (None, None)

    def test_a_placed_launch_stays_when_its_step_goes(
        self, session: DbSession, thread: Transcript, waited: models.Session
    ) -> None:
        turn_at(session, waited, _at(-9))
        launch = transcripts.launch(session, thread, started_at=_at(1))
        place_launches(session, CAMP)

        session.delete(session.get_one(ProgressStep, (waited.id, "P1.code")))
        session.flush()
        with writes(session) as wrote:
            place_launches(session, CAMP)

        assert _placed(session, launch) == (waited.id, 1)
        assert wrote == {}

    def test_a_round_published_before_its_continuation_named_the_thread_moves_to_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        thread: Transcript,
        waited: models.Session,
    ) -> None:
        """DB 538: the round's Session is the same whichever Pilot held
        first, its Launch or the continuation's naming."""
        turn_at(session, waited, _at(-9), _at(30))
        first = transcripts.launch(session, thread, started_at=_at(1), ended_at=_at(9))
        resumed = transcripts.launch(session, thread, started_at=_at(45))
        place_launches(session, CAMP)
        held = _placed(session, resumed)

        continuation = _continuing(session, container, project, waited, _at(40))
        turn_at(session, continuation, _at(41))
        conversation_named(session, CAMP)

        assert held == (waited.id, None)
        assert [_placed(session, first), _placed(session, resumed)] == [
            (waited.id, 1),
            (continuation.id, 1),
        ]

    def test_a_round_moved_to_a_continuation_with_no_turn_in_flight_has_no_turn(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        thread: Transcript,
        waited: models.Session,
    ) -> None:
        turn_at(session, waited, _at(-9))
        launch = transcripts.launch(session, thread, started_at=_at(1))
        place_launches(session, CAMP)
        held = _placed(session, launch)

        continuation = _continuing(session, container, project, waited, _at(0))
        conversation_named(session, CAMP)

        assert held == (waited.id, 1)
        assert _placed(session, launch) == (continuation.id, None)

    def test_a_placed_launch_stays_when_a_work_created_after_its_start_names_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        thread: Transcript,
        waited: models.Session,
    ) -> None:
        turn_at(session, waited, _at(-9), _at(30))
        launch = transcripts.launch(session, thread, started_at=_at(1))
        place_launches(session, CAMP)
        continuation = _continuing(session, container, project, waited, _at(40))
        turn_at(session, continuation, _at(41))

        with writes(session) as wrote:
            conversation_named(session, CAMP)

        assert _placed(session, launch) == (waited.id, 1)
        assert wrote == {}

    def test_a_placed_launch_stays_when_its_step_goes_and_an_earlier_works_names_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        thread: Transcript,
        waited: models.Session,
    ) -> None:
        turn_at(session, waited, _at(-9), _at(30))
        continuation = _continuing(session, container, project, waited, _at(40))
        turn_at(session, continuation, _at(41))
        launch = transcripts.launch(session, thread, started_at=_at(45))
        place_launches(session, CAMP)

        session.delete(session.get_one(ProgressStep, (continuation.id, "P1.code")))
        session.flush()
        with writes(session) as wrote:
            place_launches(session, CAMP)

        assert _placed(session, launch) == (continuation.id, 1)
        assert wrote == {}

    def test_a_launch_held_unplaced_is_placed_once_a_step_names_its_conversation(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        thread: Transcript,
    ) -> None:
        project_session.created_at = _at(-10)
        container.record_service().place_work(project, project_session, "Scaling")
        turn_at(session, project_session, _at(-9))
        launch = transcripts.launch(session, thread, started_at=_at(1))
        place_launches(session, CAMP)

        transcripts.named_by_step(session, project_session)
        conversation_named(session, CAMP)

        assert _placed(session, launch) == (project_session.id, 1)

    def test_an_adopted_transcripts_launches_stay_off_the_session_whose_step_names_it(
        self,
        session: DbSession,
        thread: Transcript,
        waited: models.Session,
        service_user: User,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """DB 539."""
        adopted = adopted_project(session, service_user)
        thread.adopted_project_id = adopted.id
        turn_at(session, waited, _at(-9))
        launch = transcripts.launch(session, thread, started_at=_at(1))

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            place_launches(session, CAMP)

        assert _placed(session, launch) == (None, None)
        assert caplog.messages == [
            f"Transcript {CAMP} is adopted by project {adopted.id}, and a step of a"
            " Session of Pilot's names it: its launches stay off that Session"
        ]


class TestAdopted:
    """A Transcript an adopted Project has adopted has no Launch run by a
    Session (DB 539)."""

    def test_an_adopted_transcripts_launches_stay_off_the_session_that_names_it(
        self,
        session: DbSession,
        thread: Transcript,
        run: models.Session,
        service_user: User,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        adopted = adopted_project(session, service_user)
        thread.adopted_project_id = adopted.id
        turn_at(session, run, _at(0))
        launch = transcripts.launch(session, thread, started_at=_at(1))

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            conversation_named(session, CAMP)

        assert _placed(session, launch) == (None, None)
        assert caplog.messages == [
            f"Transcript {CAMP} is adopted by project {adopted.id}, and a Session of"
            " Pilot's names it: its launches stay off that Session"
        ]

    def test_an_adopted_transcript_no_session_names_is_not_logged(
        self,
        session: DbSession,
        thread: Transcript,
        service_user: User,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        thread.adopted_project_id = adopted_project(session, service_user).id
        transcripts.launch(session, thread, started_at=_at(1))

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            place_launches(session, CAMP)

        assert caplog.messages == []

    def test_a_sub_agents_thread_keeps_no_launch_off_its_session(
        self,
        session: DbSession,
        thread: Transcript,
        collector: ComponentVersion,
        run: models.Session,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The adopted thread is the conversation's main one alone."""
        transcripts.transcript(session, collector, agent_id=SUB_AGENT)
        turn_at(session, run, _at(0))
        launch = transcripts.launch(session, thread, started_at=_at(1))

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            place_launches(session, CAMP)

        assert _placed(session, launch) == (run.id, 1)
        assert caplog.messages == []

    def test_a_transcript_no_longer_adopted_is_placed(
        self,
        session: DbSession,
        thread: Transcript,
        run: models.Session,
        service_user: User,
    ) -> None:
        thread.adopted_project_id = adopted_project(session, service_user).id
        turn_at(session, run, _at(0))
        launch = transcripts.launch(session, thread, started_at=_at(1))
        place_launches(session, CAMP)

        thread.adopted_project_id = None
        session.flush()
        place_launches(session, CAMP)

        assert _placed(session, launch) == (run.id, 1)


class TestPlacedOnce:
    def test_a_placed_launch_is_not_written_again(
        self, session: DbSession, thread: Transcript, run: models.Session
    ) -> None:
        turn_at(session, run, _at(0))
        transcripts.launch(session, thread, started_at=_at(1))
        place_launches(session, CAMP)

        with writes(session) as wrote:
            place_launches(session, CAMP)

        assert wrote == {}

    def test_a_launch_placed_between_two_turns_stays_without_a_turn(
        self, session: DbSession, thread: Transcript, run: models.Session
    ) -> None:
        turn_at(session, run, _at(0), _at(9))
        launch = transcripts.launch(session, thread, started_at=_at(12))
        place_launches(session, CAMP)
        turn_at(session, run, _at(11))

        place_launches(session, CAMP)

        assert _placed(session, launch) == (run.id, None)

    def test_a_launch_keeps_its_session_when_a_later_one_carries_the_conversation_on(
        self, session: DbSession, thread: Transcript, run: models.Session
    ) -> None:
        turn_at(session, run, _at(0), _at(9))
        launch = transcripts.launch(session, thread, started_at=_at(1))
        place_launches(session, CAMP)
        turn_at(session, _carrying_on(session, run), _at(60))

        place_launches(session, CAMP)

        assert _placed(session, launch) == (run.id, 1)

    def test_a_launch_held_unplaced_is_placed_once_a_session_names_the_conversation(
        self, session: DbSession, thread: Transcript, project_session: models.Session
    ) -> None:
        turn_at(session, project_session, _at(0))
        launch = transcripts.launch(session, thread, started_at=_at(1))
        place_launches(session, CAMP)

        project_session.conversation_id = CAMP
        place_launches(session, CAMP)

        assert _placed(session, launch) == (project_session.id, 1)


def _committed_run(db: DbSession) -> uuid.UUID:
    """A Session of Pilot's with a Turn in flight and no conversation yet,
    with what it hangs on; its id."""
    person = models.User(
        kind_code=UserKind.PERSON,
        subject="subject-ada",
        handle="ada",
        name="Ada Example",
        avatar_slot=1,
    )
    db.add(person)
    db.flush()
    project = Project(created_by_user_id=person.id)
    environment = Environment(id="recipe-box-1", name="RecipeBox-1", exempt=False)
    db.add_all([project, environment])
    db.flush()
    run = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code="work",
        cwd="/work/RecipeBox",
        token_hash=uuid.uuid4().hex,
        state_code=SessionState.RUNNING,
    )
    db.add(run)
    db.flush()
    turn_at(db, run, _at(0))
    return run.id


def _committed_work(container: ServiceContainer) -> Worker:
    """As `_committed_run`, the Session a Work, created before the
    conversation began: its worker."""
    with scoped_session(container) as db:
        run = db.get_one(models.Session, _committed_run(db))
        run.created_at = _at(-10)
        container.record_service().place_work(
            db.get_one(Project, run.project_id), run, "Scaling"
        )
        return Worker(run.id, run.project_id, "recipe-box-1", run.id)


def _names_the_camp(container: ServiceContainer, worker: Worker) -> None:
    """The worker's list published, its step naming the conversation, on the
    container's session."""
    container.pilot_work_service().set_progress(
        worker,
        [ProgressStepRequestSchema(code="P1.code", label="P1", conversations=[CAMP])],
    )


class TestConversationNamed:
    """The two writers of what a placement reads take turns, so that the
    later one sees what the earlier committed."""

    def test_a_step_naming_beside_the_transcripts_publication_places_its_launch(
        self, committed_app: Flask
    ) -> None:
        container = committed_app.container
        worker = _committed_work(container)

        def named() -> None:
            with scoped_session(container):
                _names_the_camp(container, worker)

        with scoped_session(container):
            container.publication_service().publish(_camp())
            naming = in_thread(named)
            wait_until(lambda: lock_waits(container) == 1, "the naming's turn waiting")

        naming.result()
        with scoped_session(container) as db:
            assert db.execute(select(Launch.session_id, Launch.turn_seq)).all() == [
                (worker.session_id, 1)
            ]

    def test_a_transcript_published_beside_a_steps_naming_has_its_launch_placed(
        self, committed_app: Flask
    ) -> None:
        container = committed_app.container
        worker = _committed_work(container)

        def published() -> None:
            with scoped_session(container):
                container.publication_service().publish(_camp())

        with scoped_session(container):
            _names_the_camp(container, worker)
            publishing = in_thread(published)
            wait_until(
                lambda: lock_waits(container) == 1, "the publication's turn waiting"
            )

        publishing.result()
        with scoped_session(container) as db:
            assert db.execute(select(Launch.session_id, Launch.turn_seq)).all() == [
                (worker.session_id, 1)
            ]

    def test_a_session_named_beside_its_transcripts_publication_runs_its_launch(
        self, committed_app: Flask
    ) -> None:
        container = committed_app.container
        with scoped_session(container) as db:
            run_id = _committed_run(db)

        def named() -> None:
            with scoped_session(container) as db:
                db.get_one(models.Session, run_id).conversation_id = CAMP
                conversation_named(db, CAMP)

        with scoped_session(container):
            container.publication_service().publish(_camp())
            naming = in_thread(named)
            wait_until(lambda: lock_waits(container) == 1, "the naming's turn waiting")

        naming.result()
        with scoped_session(container) as db:
            assert db.execute(select(Launch.session_id, Launch.turn_seq)).all() == [
                (run_id, 1)
            ]

    def test_a_transcript_published_beside_its_sessions_naming_has_its_launch_run(
        self, committed_app: Flask
    ) -> None:
        container = committed_app.container
        with scoped_session(container) as db:
            run_id = _committed_run(db)

        def published() -> None:
            with scoped_session(container):
                container.publication_service().publish(_camp())

        naming = container.session_maker()()
        try:
            naming.get_one(models.Session, run_id).conversation_id = CAMP
            conversation_named(naming, CAMP)
            publishing = in_thread(published)
            wait_until(
                lambda: lock_waits(container) == 1, "the publication's turn waiting"
            )
            naming.commit()
        finally:
            naming.close()

        publishing.result()
        with scoped_session(container) as db:
            assert db.execute(select(Launch.session_id, Launch.turn_seq)).all() == [
                (run_id, 1)
            ]

    def test_a_session_named_with_no_transcript_held_places_nothing(
        self, session: DbSession, project_session: models.Session
    ) -> None:
        turn_at(session, project_session, _at(0))
        project_session.conversation_id = CAMP

        with writes(session) as wrote:
            conversation_named(session, CAMP)

        assert wrote == {}
