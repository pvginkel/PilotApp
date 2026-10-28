"""The gate every start passes (design 2 §13.4, §13.5; F141.4, F141.5, F143.4,
F59.2; DB 229, 243): its conditions in their order, the slot's count, its
lock and its open event, and a project's queue of jobs."""

import uuid
from collections.abc import Iterator

import pytest
from flask import Flask
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.database import scoped_session
from app.models import Project, User
from app.models import Session as AgentSession
from app.models.reference import SessionState, WorkTrigger
from app.schemas.timeline import HeldReason
from app.services.container import ServiceContainer
from app.services.start_gate import SLOT_LOCK, Held, WorkSlots, held_reason, queued
from app.utils import after_commit as after_commit_module
from app.utils.after_commit import clear_after_commit_callbacks

UNREACHABLE = HeldReason.CONTROLLER_UNREACHABLE


class TestHeldReason:
    @pytest.mark.parametrize(
        ("paused", "kind_code", "unreachable", "filled", "queued", "held"),
        [
            (False, "work", False, None, False, None),
            (True, "work", False, None, False, Held(HeldReason.PAUSED)),
            (False, "work", True, None, False, Held(UNREACHABLE)),
            (False, "work", False, 3, False, Held(HeldReason.SLOT, 3)),
            (False, "job", False, None, True, Held(HeldReason.QUEUE)),
            # The pause comes first, then the outage, the gold bar's, then the
            # slot, then the queue.
            (True, "work", True, 3, False, Held(HeldReason.PAUSED)),
            (False, "work", True, 3, False, Held(UNREACHABLE)),
            (True, "job", False, None, False, Held(HeldReason.PAUSED)),
            (True, "job", True, None, True, Held(HeldReason.PAUSED)),
            (False, "job", True, None, True, Held(UNREACHABLE)),
            # A Chat is never held for the pause, and is for the outage.
            (True, "chat", False, None, False, None),
            (True, "chat", True, None, False, Held(UNREACHABLE)),
            (False, "chat", True, None, False, Held(UNREACHABLE)),
            # The slot is a work item's alone, the queue a job's.
            (False, "chat", False, 3, False, None),
            (False, "job", False, 3, False, None),
            (False, "work", False, None, True, None),
            (False, "chat", False, None, True, None),
        ],
    )
    def test_the_gate_holds_for_the_pause_the_outage_the_slot_and_the_queue(
        self,
        paused: bool,
        kind_code: str,
        unreachable: bool,
        filled: int | None,
        queued: bool,
        held: Held | None,
    ) -> None:
        assert (
            held_reason(
                paused=paused,
                kind_code=kind_code,
                unreachable=unreachable,
                filled=filled,
                queued=queued,
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
    container: ServiceContainer, db: DbSession, project: Project, *states: SessionState
) -> list[AgentSession]:
    """A job of the project's in each of `states`, placed in that order, as
    their rows have them."""
    runs = _sessions(db, project, SessionState.HELD, len(states), kind_code="job")
    for run, state in zip(runs, states, strict=True):
        container.record_service().place_work(
            project, run, "Setting up the project", trigger=WorkTrigger.SETUP
        )
        run.state_code = state
    db.flush()
    return runs


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
