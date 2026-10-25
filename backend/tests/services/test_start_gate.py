"""The gate every start passes (design 2 §13.4, §13.5; F141.4, F141.5, F143.4;
DB 229, 243): its conditions in their order, and the slot's count, its lock
and its open event."""

import uuid
from collections.abc import Iterator

import pytest
from flask import Flask
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.database import scoped_session
from app.models import Project, User
from app.models import Session as AgentSession
from app.models.reference import SessionState
from app.schemas.timeline import HeldReason
from app.services.start_gate import SLOT_LOCK, Held, WorkSlots, held_reason
from app.utils import after_commit as after_commit_module
from app.utils.after_commit import clear_after_commit_callbacks


class TestHeldReason:
    @pytest.mark.parametrize(
        ("paused", "kind_code", "unreachable", "filled", "held"),
        [
            (False, "work", False, None, None),
            (True, "work", False, None, Held(HeldReason.PAUSED)),
            (False, "work", True, None, Held(HeldReason.CONTROLLER_UNREACHABLE)),
            (False, "work", False, 3, Held(HeldReason.SLOT, 3)),
            # The pause comes first, then the outage, the gold bar's, then the
            # slot.
            (True, "work", True, 3, Held(HeldReason.PAUSED)),
            (False, "work", True, 3, Held(HeldReason.CONTROLLER_UNREACHABLE)),
            (True, "job", False, None, Held(HeldReason.PAUSED)),
            # A Chat is never held for the pause, and is for the outage.
            (True, "chat", False, None, None),
            (True, "chat", True, None, Held(HeldReason.CONTROLLER_UNREACHABLE)),
            (False, "chat", True, None, Held(HeldReason.CONTROLLER_UNREACHABLE)),
            # The slot is a work item's alone.
            (False, "chat", False, 3, None),
            (False, "job", False, 3, None),
        ],
    )
    def test_the_gate_holds_for_the_pause_the_outage_and_the_slot(
        self,
        paused: bool,
        kind_code: str,
        unreachable: bool,
        filled: int | None,
        held: Held | None,
    ) -> None:
        assert (
            held_reason(
                paused=paused,
                kind_code=kind_code,
                unreachable=unreachable,
                filled=filled,
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
        ],
    )
    def test_a_work_items_end_opens_the_slot_once_it_commits(
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
            ("job", SessionState.RUNNING, SessionState.IDLE),
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
