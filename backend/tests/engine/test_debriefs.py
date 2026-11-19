"""A debriefed Work beside the others of its slice: the work items of its
Debrief Notice (`of_notice`; DB 609) and the time its stage took
(`stage_times`; F26.17; DB 637)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session as DbSession

from app import models
from app.engine.debriefs import of_notice, stage_times
from app.models import Environment, Item, Project, Turn, User, Work
from app.models.reference import SessionState, TurnCause
from app.services.container import ServiceContainer

AT = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
SUBJECT = "Slice 4 · The tent list"


def _run(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
    environment: Environment,
    title: str,
    *,
    conversation: str | None = None,
    subject: str | None = None,
    completes: bool = True,
) -> Work:
    """A worker's run of `project` placed as `title`, on `conversation`, its
    debrief given with `subject` and whether it `completes` it."""
    run = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code="work",
        cwd="/work/Example",
        conversation_id=conversation,
        token_hash=uuid.uuid4().hex,
        state_code=SessionState.IDLE,
    )
    session.add(run)
    session.flush()
    work = container.record_service().place_work(project, run, title)
    work.debrief = f"How {title.lower()} went."
    work.debrief_subject = subject
    work.debrief_completes = completes
    session.flush()
    return work


def _turns(session: DbSession, work: Work, *turns: tuple[int, float | None]) -> None:
    """The Work's Turns, each the minutes after `AT` it started at and the
    seconds it took, None for one still running."""
    for seq, (after, seconds) in enumerate(turns, start=1):
        started = AT + timedelta(minutes=after)
        session.add(
            Turn(
                session_id=work.id,
                seq=seq,
                message="Go on.",
                started_at=started,
                ended_at=(
                    None if seconds is None else started + timedelta(seconds=seconds)
                ),
                cause_code=TurnCause.BRIEF,
            )
        )
    session.flush()


def _done(session: DbSession, container: ServiceContainer, work: Work) -> Item:
    container.record_service().work_done(work.id, AT)
    return session.get_one(Item, work.id)


class TestStageTimes:
    def test_a_works_ended_turns_are_summed_the_time_between_them_counting_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """An hour's wait on the operator between two turns is no part of the
        stage's time, and the sum is in whole seconds."""
        work = _run(session, container, project, environment, "Planning")
        _turns(session, work, (0, 600.4), (70, 300.4))

        assert stage_times(session, [work.id]) == {work.id: 901}

    def test_a_turn_still_running_counts_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        work = _run(session, container, project, environment, "Planning")
        _turns(session, work, (0, 600), (70, None))
        started = _run(session, container, project, environment, "Run")
        _turns(session, started, (80, None))

        assert stage_times(session, [work.id, started.id]) == {
            work.id: 600,
            started.id: 0,
        }

    def test_a_work_with_no_ended_turn_took_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        work = _run(session, container, project, environment, "Planning")

        assert stage_times(session, [work.id]) == {work.id: 0}
        assert stage_times(session, []) == {}

    def test_the_earlier_works_of_its_conversation_count_and_the_later_do_not(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """A hand-back's continuation takes the run's time with its own
        (F26.7); a clarification run placed after it adds nothing to it."""
        run = _run(session, container, project, environment, "Run", conversation="c1")
        _turns(session, run, (0, 1000))
        continued = _run(
            session, container, project, environment, "Run on", conversation="c1"
        )
        _turns(session, continued, (60, 200), (90, 30))
        clarifying = _run(
            session, container, project, environment, "Clarify", conversation="c1"
        )
        _turns(session, clarifying, (120, 50))

        assert stage_times(session, [run.id, continued.id, clarifying.id]) == {
            run.id: 1000,
            continued.id: 1230,
            clarifying.id: 1280,
        }

    def test_a_work_of_another_conversation_counts_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """A slice's planning and its run are two conversations, each with a
        time of its own; so are two Works that have no conversation."""
        planning = _run(
            session, container, project, environment, "Planning", conversation="c1"
        )
        _turns(session, planning, (0, 700))
        running = _run(
            session, container, project, environment, "Run", conversation="c2"
        )
        _turns(session, running, (30, 4000))
        first = _run(session, container, project, environment, "First")
        _turns(session, first, (60, 10))
        second = _run(session, container, project, environment, "Second")
        _turns(session, second, (61, 20))

        assert stage_times(session, [planning.id, running.id, first.id, second.id]) == {
            planning.id: 700,
            running.id: 4000,
            first.id: 10,
            second.id: 20,
        }

    def test_a_work_of_another_project_on_its_conversation_counts_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        person: User,
    ) -> None:
        other = Project(created_by_user_id=person.id)
        session.add(other)
        session.flush()
        elsewhere = _run(
            session, container, other, environment, "Run", conversation="c1"
        )
        _turns(session, elsewhere, (0, 500))
        run = _run(session, container, project, environment, "Run", conversation="c1")
        _turns(session, run, (10, 40))
        # Both are their project's first item: the same `seq`.
        assert (
            session.get_one(Item, elsewhere.id).seq == session.get_one(Item, run.id).seq
        )

        assert stage_times(session, [run.id]) == {run.id: 40}


class TestOfNotice:
    def test_before_its_notice_a_run_has_the_plannings_that_wait_on_its_subject(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """DB 609: with it, in timeline order, every done Work of its subject
        whose debrief does not complete and that no notice carries; not one
        still open, of another subject, or that completes."""
        records = container.record_service()
        carried = _run(
            session, container, project, environment, "Old run", subject=SUBJECT
        )
        records.place_debrief_notice(project, _done(session, container, carried))
        first = _run(
            session,
            container,
            project,
            environment,
            "Planning",
            subject=SUBJECT,
            completes=False,
        )
        _done(session, container, first)
        other = _run(
            session,
            container,
            project,
            environment,
            "Planning the stove",
            subject="Slice 5 · The stove",
            completes=False,
        )
        _done(session, container, other)
        second = _run(
            session,
            container,
            project,
            environment,
            "Planning again",
            subject=SUBJECT,
            completes=False,
        )
        _done(session, container, second)
        _run(
            session,
            container,
            project,
            environment,
            "Planning, open",
            subject=SUBJECT,
            completes=False,
        )
        twin = _run(session, container, project, environment, "Twin", subject=SUBJECT)
        _done(session, container, twin)
        run = _run(session, container, project, environment, "Run", subject=SUBJECT)
        _done(session, container, run)

        assert [item.title for item in of_notice(session, run)] == [
            "Planning",
            "Planning again",
            "Run",
        ]

    def test_a_planning_has_itself_and_the_plannings_before_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """Its own pass runs before the run that completes its subject."""
        plannings = [
            _run(
                session,
                container,
                project,
                environment,
                title,
                subject=SUBJECT,
                completes=False,
            )
            for title in ("Planning", "Planning again")
        ]
        for planning in plannings:
            _done(session, container, planning)

        for planning in plannings:
            assert [item.id for item in of_notice(session, planning)] == [
                each.id for each in plannings
            ]

    def test_a_work_that_names_no_subject_has_itself_alone(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        _done(session, container, _run(session, container, project, environment, "A"))
        run = _run(session, container, project, environment, "Run")
        _done(session, container, run)

        assert [item.id for item in of_notice(session, run)] == [run.id]

    def test_once_placed_it_has_the_works_its_notice_carries(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """A Retry's pass after a stop that placed the notice: a planning of
        the subject done since is not the notice's."""
        planning = _run(
            session,
            container,
            project,
            environment,
            "Planning",
            subject=SUBJECT,
            completes=False,
        )
        _done(session, container, planning)
        run = _run(session, container, project, environment, "Run", subject=SUBJECT)
        container.record_service().place_debrief_notice(
            project, _done(session, container, run)
        )
        later = _run(
            session,
            container,
            project,
            environment,
            "Planning it anew",
            subject=SUBJECT,
            completes=False,
        )
        _done(session, container, later)

        for work in (planning, run):
            assert [item.id for item in of_notice(session, work)] == [
                planning.id,
                run.id,
            ]
