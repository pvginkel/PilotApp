"""The gate every start passes (design 2 §13.4, §13.5; F141.4, F141.5, F143.4,
F59.2, F135; DB 183, 229, 243, 266): its conditions in their order, the usage
halts a work item's alone, the slot's count, its
lock and its open event, a project's queue of jobs, and the runs of one
conversation."""

import uuid
from collections.abc import Iterator

import pytest
from flask import Flask
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.database import scoped_session
from app.models import Environment, Project, User, Work
from app.models import Session as AgentSession
from app.models.reference import SessionState, UsageWindow, WorkTrigger
from app.schemas.timeline import HeldReason
from app.services.container import ServiceContainer
from app.services.start_gate import (
    SLOT_LOCK,
    Held,
    WorkSlots,
    carried,
    conversing,
    held_reason,
    queued,
    setups,
)
from app.utils import after_commit as after_commit_module
from app.utils.after_commit import clear_after_commit_callbacks

UNREACHABLE = HeldReason.CONTROLLER_UNREACHABLE
CONVERSATION = HeldReason.CONVERSATION
WEEK_HALT = HeldReason.WEEK_HALT
FIVE_HOUR_HALT = HeldReason.FIVE_HOUR_HALT
WEEK = UsageWindow.SEVEN_DAY
FIVE_HOUR = UsageWindow.FIVE_HOUR


class TestHeldReason:
    @pytest.mark.parametrize(
        (
            "paused",
            "kind_code",
            "unreachable",
            "filled",
            "queued",
            "conversing",
            "held",
        ),
        [
            (False, "work", False, None, False, False, None),
            (True, "work", False, None, False, False, Held(HeldReason.PAUSED)),
            (False, "work", True, None, False, False, Held(UNREACHABLE)),
            (False, "work", False, 3, False, False, Held(HeldReason.SLOT, 3)),
            (False, "job", False, None, True, False, Held(HeldReason.QUEUE)),
            (False, "work", False, None, False, True, Held(CONVERSATION)),
            # The pause comes first, then the outage, the gold bar's, then the
            # slot, then the queue, then the conversation.
            (True, "work", True, 3, False, True, Held(HeldReason.PAUSED)),
            (False, "work", True, 3, False, True, Held(UNREACHABLE)),
            (False, "work", False, 3, False, True, Held(HeldReason.SLOT, 3)),
            (True, "job", False, None, False, False, Held(HeldReason.PAUSED)),
            (True, "job", True, None, True, False, Held(HeldReason.PAUSED)),
            (False, "job", True, None, True, False, Held(UNREACHABLE)),
            # A Chat is never held for the pause, and is for the outage.
            (True, "chat", False, None, False, False, None),
            (True, "chat", True, None, False, False, Held(UNREACHABLE)),
            (False, "chat", True, None, False, False, Held(UNREACHABLE)),
            # The slot and the conversation are a work item's alone, the
            # queue a job's.
            (False, "chat", False, 3, False, False, None),
            (False, "job", False, 3, False, False, None),
            (False, "work", False, None, True, False, None),
            (False, "chat", False, None, True, False, None),
            (False, "job", False, None, False, True, None),
            (False, "chat", False, None, False, True, None),
        ],
    )
    def test_the_gate_holds_for_the_pause_the_outage_the_slot_the_queue_and_the_conversation(
        self,
        paused: bool,
        kind_code: str,
        unreachable: bool,
        filled: int | None,
        queued: bool,
        conversing: bool,
        held: Held | None,
    ) -> None:
        assert (
            held_reason(
                halted=None,
                paused=paused,
                kind_code=kind_code,
                setup=False,
                unreachable=unreachable,
                filled=filled,
                queued=queued,
                conversing=conversing,
            )
            == held
        )

    @pytest.mark.parametrize(
        ("halted", "kind_code", "paused", "unreachable", "filled", "held"),
        [
            (WEEK, "work", False, False, None, Held(WEEK_HALT)),
            (FIVE_HOUR, "work", False, False, None, Held(FIVE_HOUR_HALT)),
            # The halt comes first.
            (WEEK, "work", True, True, 3, Held(WEEK_HALT)),
            (FIVE_HOUR, "work", True, True, 3, Held(FIVE_HOUR_HALT)),
            # A job's and a Chat's are never held for a halt (F135).
            (WEEK, "job", False, False, None, None),
            (FIVE_HOUR, "job", False, False, None, None),
            (WEEK, "chat", False, False, None, None),
            (FIVE_HOUR, "chat", False, False, None, None),
            (WEEK, "job", True, False, None, Held(HeldReason.PAUSED)),
            (WEEK, "chat", True, True, None, Held(UNREACHABLE)),
        ],
    )
    def test_a_usage_halt_holds_a_work_items_start_first_and_never_a_jobs_or_a_chats(
        self,
        halted: UsageWindow,
        kind_code: str,
        paused: bool,
        unreachable: bool,
        filled: int | None,
        held: Held | None,
    ) -> None:
        assert (
            held_reason(
                halted=halted,
                paused=paused,
                kind_code=kind_code,
                setup=False,
                unreachable=unreachable,
                filled=filled,
                queued=False,
                conversing=False,
            )
            == held
        )

    @pytest.mark.parametrize(
        ("paused", "unreachable", "queued", "held"),
        [
            (True, False, False, None),
            (False, False, False, None),
            (True, True, True, Held(UNREACHABLE)),
            (True, False, True, Held(HeldReason.QUEUE)),
        ],
    )
    def test_the_setup_is_never_held_for_the_pause_its_other_holds_standing(
        self, paused: bool, unreachable: bool, queued: bool, held: Held | None
    ) -> None:
        """Create project's pause holds every start but the setup's, a
        Retry's included (D083)."""
        assert (
            held_reason(
                halted=None,
                paused=paused,
                kind_code="job",
                setup=True,
                unreachable=unreachable,
                filled=None,
                queued=queued,
                conversing=False,
            )
            == held
        )


def _project(db: DbSession, person: User) -> Project:
    draft = Project(created_by_user_id=person.id)
    db.add(draft)
    db.flush()
    return draft


def _sessions(
    db: DbSession,
    project: Project,
    state: SessionState,
    count: int = 1,
    *,
    kind_code: str = "work",
) -> list[AgentSession]:
    runs = [
        AgentSession(
            project_id=project.id,
            kind_code=kind_code,
            cwd="/work/Example",
            token_hash=uuid.uuid4().hex,
            state_code=state,
        )
        for _ in range(count)
    ]
    db.add_all(runs)
    db.flush()
    return runs


class TestFilled:
    def test_a_project_with_room_is_left_out(
        self, session: DbSession, person: User
    ) -> None:
        camp = _project(session, person)
        _sessions(session, camp, SessionState.RUNNING, 2)

        assert WorkSlots(work_max=3, project_max=3).filled(session, [camp.id]) == {}

    def test_the_cross_project_maximum_leaves_every_project_no_slot(
        self, session: DbSession, person: User
    ) -> None:
        camp, site, quiet = (_project(session, person) for _ in range(3))
        _sessions(session, camp, SessionState.RUNNING, 2)
        _sessions(session, site, SessionState.STARTING)

        filled = WorkSlots(work_max=3, project_max=3).filled(
            session, [camp.id, site.id, quiet.id]
        )

        assert filled == {camp.id: 3, site.id: 3, quiet.id: 3}

    def test_the_per_project_maximum_leaves_its_project_alone_no_slot(
        self, session: DbSession, person: User
    ) -> None:
        camp, site = _project(session, person), _project(session, person)
        _sessions(session, camp, SessionState.RUNNING)
        _sessions(session, camp, SessionState.STARTING)
        _sessions(session, site, SessionState.RUNNING)

        filled = WorkSlots(work_max=5, project_max=2).filled(
            session, [camp.id, site.id]
        )

        assert filled == {camp.id: 2}

    def test_only_work_items_running_or_starting_count(
        self, session: DbSession, person: User
    ) -> None:
        camp = _project(session, person)
        for state in (
            SessionState.HELD,
            SessionState.IDLE,
            SessionState.STOPPED,
            SessionState.FAILED,
            SessionState.ENDED,
        ):
            _sessions(session, camp, state)
        # A Chat and a job count for neither maximum (DB 243).
        _sessions(session, camp, SessionState.RUNNING, kind_code="chat")
        _sessions(session, camp, SessionState.STARTING, kind_code="job")

        assert WorkSlots(work_max=1, project_max=1).filled(session, [camp.id]) == {}


class TestLock:
    def test_the_slot_is_held_until_the_transaction_ends(
        self, committed_app: Flask
    ) -> None:
        container = committed_app.container
        slots = WorkSlots(work_max=3, project_max=3)

        def free() -> bool:
            other = container.session_maker()()
            try:
                taken: bool = other.scalar(
                    select(func.pg_try_advisory_xact_lock(SLOT_LOCK))
                )
                return taken
            finally:
                other.rollback()
                other.close()

        with scoped_session(container) as db:
            slots.lock(db)
            assert not free()
        assert free()


@pytest.fixture
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


def _opened() -> None:
    """A listener of the slot's open event."""


@pytest.mark.usefixtures("_no_callbacks")
class TestTook:
    @pytest.mark.parametrize(("kind_code", "told"), [("work", True), ("chat", False)])
    def test_a_work_items_start_tells_the_listeners_once_it_commits(
        self, session: DbSession, person: User, kind_code: str, told: bool
    ) -> None:
        slots = WorkSlots(work_max=3, project_max=3)
        slots.subscribe(_opened)
        (run,) = _sessions(
            session,
            _project(session, person),
            SessionState.STARTING,
            kind_code=kind_code,
        )

        slots.took(run)

        assert after_commit_module._callbacks.get() == ((_opened,) if told else ())


@pytest.mark.usefixtures("_no_callbacks")
class TestLeft:
    @pytest.mark.parametrize(
        ("kind_code", "before", "after"),
        [
            # Its turn's `result`, its Stop, a stop made elsewhere.
            ("work", SessionState.RUNNING, SessionState.IDLE),
            ("work", SessionState.RUNNING, SessionState.STOPPED),
            ("work", SessionState.RUNNING, SessionState.FAILED),
            # A start's Stop and its failure.
            ("work", SessionState.STARTING, SessionState.STOPPED),
            ("work", SessionState.STARTING, SessionState.FAILED),
            # A job's last turn's end, a stop made elsewhere, a turn in error
            # and a start's failure: its project's next job may go on (F59.2).
            ("job", SessionState.RUNNING, SessionState.IDLE),
            ("job", SessionState.RUNNING, SessionState.STOPPED),
            ("job", SessionState.RUNNING, SessionState.FAILED),
            ("job", SessionState.STARTING, SessionState.FAILED),
        ],
    )
    def test_a_work_items_or_a_jobs_end_tells_the_listeners_once_it_commits(
        self,
        session: DbSession,
        person: User,
        kind_code: str,
        before: SessionState,
        after: SessionState,
    ) -> None:
        slots = WorkSlots(work_max=3, project_max=3)
        slots.subscribe(_opened)
        (run,) = _sessions(
            session, _project(session, person), after, kind_code=kind_code
        )

        slots.left(run, before)

        assert after_commit_module._callbacks.get() == (_opened,)

    @pytest.mark.parametrize(
        ("kind_code", "before", "after"),
        [
            # A held start stopped held no slot.
            ("work", SessionState.HELD, SessionState.STOPPED),
            # A start that goes on to its turn keeps its slot.
            ("work", SessionState.STARTING, SessionState.RUNNING),
            ("chat", SessionState.RUNNING, SessionState.IDLE),
            # A job's turn that ends with the follow-up keeps its place.
            ("job", SessionState.RUNNING, SessionState.RUNNING),
            ("job", SessionState.STARTING, SessionState.RUNNING),
        ],
    )
    def test_any_other_move_leaves_it_as_it_is(
        self,
        session: DbSession,
        person: User,
        kind_code: str,
        before: SessionState,
        after: SessionState,
    ) -> None:
        slots = WorkSlots(work_max=3, project_max=3)
        slots.subscribe(_opened)
        (run,) = _sessions(
            session, _project(session, person), after, kind_code=kind_code
        )

        slots.left(run, before)

        assert after_commit_module._callbacks.get() == ()


def _jobs(
    container: ServiceContainer,
    db: DbSession,
    project: Project,
    *states: SessionState,
    trigger: WorkTrigger = WorkTrigger.SETUP,
) -> list[AgentSession]:
    """A job of the project's of `trigger` in each of `states`, placed in that
    order, as their rows have them."""
    runs = _sessions(db, project, SessionState.HELD, len(states), kind_code="job")
    for run, state in zip(runs, states, strict=True):
        container.record_service().place_work(
            project, run, "Setting up the project", trigger=trigger
        )
        run.state_code = state
    db.flush()
    return runs


class TestSetups:
    """The jobs the pause holds not: the setup's, a Retry's among them
    (D083)."""

    def test_the_setups_and_their_retries_and_no_other_job_or_work_item(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        camp = _project(session, person)
        failed, retry = _jobs(
            container, session, camp, SessionState.FAILED, SessionState.HELD
        )
        session.get_one(Work, failed.id).retried_by_id = retry.id
        (other,) = _jobs(
            container,
            session,
            camp,
            SessionState.HELD,
            trigger=WorkTrigger.ITEM_DONE,
        )
        (run,) = _sessions(session, camp, SessionState.HELD)
        container.record_service().place_work(camp, run, "Renaming the badge")
        session.flush()

        assert setups(session, [failed.id, retry.id, other.id, run.id]) == {
            failed.id,
            retry.id,
        }

    def test_of_none_none(self, session: DbSession) -> None:
        assert setups(session, []) == set()


class TestQueued:
    """A project's jobs wait their turn one behind another in the order they
    were placed, a chat beside them (F59.2)."""

    @pytest.mark.parametrize("state", [SessionState.STARTING, SessionState.RUNNING])
    def test_a_held_job_waits_behind_one_starting_or_running_placed_before_or_after_it(
        self,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        state: SessionState,
    ) -> None:
        camp = _project(session, person)
        held, ahead, after = _jobs(
            container, session, camp, SessionState.HELD, state, SessionState.HELD
        )

        assert queued(session, [held.id, ahead.id, after.id]) == {held.id, after.id}

    def test_a_held_job_holds_up_those_placed_after_it_and_none_before(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        camp = _project(session, person)
        first, second, third = _jobs(container, session, camp, *[SessionState.HELD] * 3)

        assert queued(session, [first.id, second.id, third.id]) == {
            second.id,
            third.id,
        }

    @pytest.mark.parametrize(
        "state",
        [
            SessionState.IDLE,
            SessionState.STOPPED,
            SessionState.FAILED,
            SessionState.ENDED,
        ],
    )
    def test_a_job_done_stopped_or_failed_holds_up_none(
        self,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        state: SessionState,
    ) -> None:
        camp = _project(session, person)
        _, held = _jobs(container, session, camp, state, SessionState.HELD)

        assert queued(session, [held.id]) == set()

    def test_a_chat_and_another_projects_job_hold_up_none(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        camp = _project(session, person)
        _sessions(session, camp, SessionState.RUNNING, kind_code="chat")
        _jobs(container, session, _project(session, person), SessionState.RUNNING)
        (held,) = _jobs(container, session, camp, SessionState.HELD)

        assert queued(session, [held.id]) == set()

    def test_a_work_item_waits_on_no_job(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        camp = _project(session, person)
        _jobs(container, session, camp, SessionState.RUNNING)
        (run,) = _sessions(session, camp, SessionState.HELD)
        container.record_service().place_work(camp, run, "Renaming the badge")

        assert queued(session, [run.id]) == set()


def _on(
    db: DbSession,
    project: Project,
    conversation: str | None,
    environment: Environment,
    *states: SessionState,
) -> list[AgentSession]:
    """A work item's Session on the conversation in the environment, in each
    of `states`."""
    runs = _sessions(db, project, SessionState.HELD, len(states))
    for run, state in zip(runs, states, strict=True):
        run.conversation_id = conversation
        run.environment_id = environment.id
        run.state_code = state
    db.flush()
    return runs


def _elsewhere(db: DbSession) -> Environment:
    other = Environment(id="example-elsewhere", name="Elsewhere-1", exempt=False)
    db.add(other)
    db.flush()
    return other


class TestCarried:
    """A work item resuming a conversation waits while another Session runs
    or starts on it in its Environment (DB 183)."""

    @pytest.mark.parametrize(
        ("state", "carrying"),
        [
            (SessionState.RUNNING, True),
            (SessionState.STARTING, True),
            (SessionState.HELD, False),
            (SessionState.IDLE, False),
            (SessionState.STOPPED, False),
            (SessionState.FAILED, False),
        ],
    )
    def test_another_session_carries_it_while_it_runs_or_starts(
        self,
        session: DbSession,
        person: User,
        environment: Environment,
        state: SessionState,
        carrying: bool,
    ) -> None:
        camp = _project(session, person)
        resuming, other = _on(
            session, camp, "conv-camp", environment, SessionState.HELD, state
        )

        assert carried(session, resuming) is carrying
        # A Session never waits for itself.
        assert carried(session, other) is False

    def test_another_conversation_another_environment_or_none_is_never_carried(
        self, session: DbSession, person: User, environment: Environment
    ) -> None:
        camp = _project(session, person)
        _on(session, camp, "conv-camp", _elsewhere(session), SessionState.RUNNING)
        _on(session, camp, "conv-site", environment, SessionState.RUNNING)
        _on(session, camp, None, environment, SessionState.RUNNING)
        resuming, fresh = _on(
            session,
            camp,
            "conv-camp",
            environment,
            SessionState.HELD,
            SessionState.HELD,
        )
        fresh.conversation_id = None
        session.flush()

        assert carried(session, resuming) is False
        assert carried(session, fresh) is False


class TestConversing:
    def test_the_work_items_another_session_of_their_conversation_runs_or_starts_on(
        self, session: DbSession, person: User, environment: Environment
    ) -> None:
        camp = _project(session, person)
        held, running = _on(
            session,
            camp,
            "conv-camp",
            environment,
            SessionState.HELD,
            SessionState.RUNNING,
        )
        (alone,) = _on(session, camp, "conv-site", environment, SessionState.HELD)
        (fresh,) = _on(session, camp, None, environment, SessionState.HELD)
        (apart,) = _on(
            session, camp, "conv-camp", _elsewhere(session), SessionState.HELD
        )

        assert conversing(
            session, [held.id, running.id, alone.id, fresh.id, apart.id]
        ) == {held.id}

    def test_a_job_is_never_conversing(
        self, session: DbSession, person: User, environment: Environment
    ) -> None:
        camp = _project(session, person)
        (job,) = _sessions(session, camp, SessionState.HELD, kind_code="job")
        job.conversation_id = "conv-camp"
        job.environment_id = environment.id
        _on(session, camp, "conv-camp", environment, SessionState.RUNNING)

        assert conversing(session, [job.id]) == set()
        assert conversing(session, []) == set()
