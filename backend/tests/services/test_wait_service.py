"""The waits (F27, DB decision 46): a card wait or a timed wait born with what
it waits on and fixed from then on, refused as F86.1 has it, fired by a card's
transition or its due time (F136.2, F27.2), and closed by Pilot's own `done`
with a note (DB 199, 300) or by Finish, with none."""

import json
import re
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from flask import Flask
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.engine.bus import EngineEvent, ProjectChanged, TreeHashMoved
from app.engine.paths import TIMELINE, tree_path
from app.exceptions import InvalidOperationException
from app.models import (
    CardTransition,
    Environment,
    Item,
    PlanTask,
    Project,
    User,
    Wait,
    WaitFiring,
)
from app.models.reference import (
    FiringCause,
    ProjectState,
    SessionState,
    TaskStatus,
    TransitionKind,
    UserKind,
    WorkTrigger,
)
from app.services import wait_service
from app.services.container import ServiceContainer
from app.services.wait_service import ReportedTransition, WaitService
from app.utils.after_commit import clear_after_commit_callbacks

NOTE = "ANS-312 read Done at 09:40; the rollout goes on"


def _service(container: ServiceContainer) -> WaitService:
    service: WaitService = container.wait_service()
    return service


def _pilot(db: DbSession) -> User:
    return db.scalars(select(User).where(User.kind_code == UserKind.AGENT)).one()


def _ahead(hours: int = 1) -> datetime:
    return datetime.now(UTC).replace(microsecond=0) + timedelta(hours=hours)


def _card_wait(
    container: ServiceContainer, project: Project, creator: models.Session
) -> Item:
    return _service(container).add_card_wait(
        project, creator, "Slice 058 completes", ["ANS-312"], ["Done"], None
    )


def _opened(db: DbSession, project: Project) -> Project:
    project.state_code = ProjectState.OPEN
    project.slug = "camp"
    project.name = "Camp"
    db.flush()
    return project


class TestWaitServiceAddCardWait:
    def test_a_card_wait_is_born_with_its_lists_at_the_projects_next_place(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        item: Item,
        project_session: models.Session,
    ) -> None:
        session.add(
            PlanTask(
                project_id=project.id,
                task_id="t6",
                position=1,
                title="The rollout",
                status_code=TaskStatus.PENDING,
            )
        )
        project_id, creator_id = project.id, project_session.id

        with scoped_session(container):
            added = _service(container).add_card_wait(
                project,
                project_session,
                "The night shift takes SR-1 and SR-4",
                ["SR-1", "SR-4"],
                ["Done", "Won't fix"],
                "t6",
            )
            added_id = added.id

        wait_item = session.get_one(Item, added_id)
        assert (
            wait_item.seq,
            wait_item.kind_code,
            wait_item.title,
            wait_item.plan_task_id,
            wait_item.created_by_session_id,
            wait_item.done_at,
        ) == (
            2,
            "card_wait",
            "The night shift takes SR-1 and SR-4",
            "t6",
            creator_id,
            None,
        )
        wait = session.get_one(Wait, added_id)
        assert (wait.kind_code, wait.cards, wait.states, wait.due_at) == (
            "card_wait",
            ["SR-1", "SR-4"],
            ["Done", "Won't fix"],
            None,
        )
        assert ProjectChanged(project_id) in engine_events

    @pytest.mark.parametrize(
        ("cards", "states", "cause"),
        [
            ([], ["Done"], "its `cards` list is empty"),
            (["SR-4"], [], "its `states` list is empty"),
            (["SR-4", "SR-1", "SR-4"], ["Done"], "its `cards` list names `SR-4` twice"),
            (
                ["SR-4"],
                ["Done", "Won't fix", "done"],
                "its `states` list names `done` twice",
            ),
            (
                ["sr-4", "SR-1"],
                ["Done"],
                "`sr-4` is no ticket id, `[A-Z][A-Z0-9_]*-[1-9][0-9]*`",
            ),
            (
                ["SR-0", "SR-4", "SR4"],
                ["Done"],
                "`SR-0`, `SR4` are no ticket id, `[A-Z][A-Z0-9_]*-[1-9][0-9]*`",
            ),
        ],
    )
    def test_an_empty_list_a_name_twice_or_a_card_no_ticket_id_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        cards: list[str],
        states: list[str],
        cause: str,
    ) -> None:
        with pytest.raises(InvalidOperationException) as refused:
            _service(container).add_card_wait(
                project, project_session, "SR-4 lands", cards, states, None
            )

        assert refused.value.message == f"Cannot add a card_wait item because {cause}"
        assert session.scalars(select(Item)).all() == []

    def test_the_ticket_id_pattern_is_the_deployments(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        service: WaitService = container.wait_service(
            ticket_id_pattern=re.compile(r"[a-z]+#[0-9]+")
        )

        added = service.add_card_wait(
            project, project_session, "Issue 12 lands", ["repo#12"], ["closed"], None
        )
        clear_after_commit_callbacks()

        assert session.get_one(Wait, added.id).cards == ["repo#12"]


class TestWaitServiceAddTimedWait:
    def test_a_timed_wait_is_born_with_its_due_time(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        due = _ahead(24)

        added = _service(container).add_timed_wait(
            project, project_session, "A 24-hour soak after the rollout", due, None
        )
        clear_after_commit_callbacks()

        assert (added.seq, added.kind_code, added.plan_task_id) == (
            1,
            "timed_wait",
            None,
        )
        wait = session.get_one(Wait, added.id)
        assert (wait.kind_code, wait.due_at, wait.cards, wait.states) == (
            "timed_wait",
            due,
            None,
            None,
        )

    @pytest.mark.parametrize("hours", [0, -1])
    def test_a_due_time_not_ahead_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        hours: int,
    ) -> None:
        due = datetime(2026, 10, 25, 18, 30, tzinfo=UTC) + timedelta(hours=hours)

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).add_timed_wait(
                project, project_session, "ESO refreshes", due, None
            )

        assert refused.value.message == (
            "Cannot add a timed_wait item because its due time,"
            f" {due.isoformat()}, is not ahead"
        )
        assert session.scalars(select(Item)).all() == []


class TestWaitServiceClose:
    def test_the_close_is_pilots_marked_consumed_on_the_spot_with_its_note(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
    ) -> None:
        added = _card_wait(container, project, project_session)
        clear_after_commit_callbacks()
        pilot = _pilot(session)
        project_id, added_id, closer_id = project.id, added.id, project_session.id

        with scoped_session(container):
            _service(container).close(
                project, session.get_one(Wait, added_id), pilot, closer_id, NOTE
            )

        closed = session.get_one(Item, added_id)
        assert closed.done_at is not None
        assert (
            closed.done_cause_code,
            closed.done_by_user_id,
            closed.consumed_at,
            closed.consumed_session_id,
        ) == ("marked", pilot.id, closed.done_at, closer_id)
        assert session.get_one(Wait, added_id).done_note == NOTE
        assert not container.record_service().offers_undo(closed)
        assert ProjectChanged(project_id) in engine_events

    def test_a_done_wait_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        added = _card_wait(container, project, project_session)
        wait = session.get_one(Wait, added.id)
        service = _service(container)
        service.close(project, wait, _pilot(session), project_session.id, NOTE)

        with pytest.raises(InvalidOperationException) as refused:
            service.close(project, wait, _pilot(session), project_session.id, "Again")
        clear_after_commit_callbacks()

        assert refused.value.message == (
            f"Cannot mark item {added.id} done because the item is done"
        )
        assert wait.done_note == NOTE

    def test_an_archived_projects_wait_is_refused(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        added = _card_wait(container, project, project_session)
        clear_after_commit_callbacks()
        project.archived = True
        session.flush()

        with pytest.raises(InvalidOperationException) as refused:
            _service(container).close(
                project,
                session.get_one(Wait, added.id),
                _pilot(session),
                project_session.id,
                NOTE,
            )

        assert refused.value.message.endswith("because its project is archived")
        assert added.done_at is None

    def test_finish_closes_an_open_wait_finished_with_no_note(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
        project_session: models.Session,
    ) -> None:
        _opened(session, project)
        card = _card_wait(container, project, project_session)
        timed = _service(container).add_timed_wait(
            project, project_session, "ESO refreshes", _ahead(), None
        )

        container.project_service().transition_as(
            person, project.id, TransitionKind.FINISHED
        )
        clear_after_commit_callbacks()

        for each in (card, timed):
            session.refresh(each)
            assert (each.done_cause_code, each.done_by_user_id) == (
                "finished",
                person.id,
            )
            assert not container.record_service().offers_undo(each)
            assert session.get_one(Wait, each.id).done_note is None


AT = datetime(2026, 10, 12, 9, 30, tzinfo=UTC)


def _transition(card: str = "ANS-312", to_state: str = "Done") -> ReportedTransition:
    return ReportedTransition(
        card=card, from_state="In Progress", to_state=to_state, at=AT, by="pieter"
    )


def _other_project(session: DbSession, person: User) -> tuple[Project, models.Session]:
    """A second open project, with a work Session of its own."""
    other = Project(
        created_by_user_id=person.id,
        state_code=ProjectState.OPEN,
        slug="soup-club",
        name="Soup club",
    )
    session.add(other)
    session.flush()
    run = models.Session(
        project_id=other.id,
        kind_code="work",
        cwd="/work/Example",
        token_hash="2" * 64,
        state_code=SessionState.RUNNING,
    )
    session.add(run)
    session.flush()
    return other, run


def _overdue(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
    creator: models.Session,
) -> Item:
    """A timed wait whose due time passed five minutes ago, as a restart
    finds one that came due while no process ran."""
    added = _service(container).add_timed_wait(
        project, creator, "ESO refreshes", _ahead(), None
    )
    session.get_one(Wait, added.id).due_at = datetime.now(UTC) - timedelta(minutes=5)
    session.flush()
    return added


def _firings(db: DbSession, wait_id: uuid.UUID) -> list[WaitFiring]:
    return list(
        db.scalars(
            select(WaitFiring)
            .where(WaitFiring.wait_id == wait_id)
            .order_by(WaitFiring.seq)
        )
    )


def _transitions(db: DbSession) -> list[CardTransition]:
    return list(db.scalars(select(CardTransition).order_by(CardTransition.id)))


def _shown_firings(
    container: ServiceContainer, project: Project, wait_id: uuid.UUID
) -> list[dict[str, object]]:
    """The wait's firings as the project's `timeline.json` carries them."""
    text = container.view_service().timeline(project).text
    item = next(
        each for each in json.loads(text)["items"] if each["id"] == str(wait_id)
    )
    firings: list[dict[str, object]] = item["firings"]
    return firings


def _not_firable(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
    wait: Item,
    creator: models.Session,
    how: str,
) -> None:
    """`wait` left where the server fires it not: done, or its project
    finished, archived or a draft."""
    match how:
        case "done":
            _service(container).close(
                project,
                session.get_one(Wait, wait.id),
                _pilot(session),
                creator.id,
                NOTE,
            )
        case "finished":
            project.state_code = ProjectState.FINISHED
        case "archived":
            project.archived = True
        case "draft":
            project.state_code = ProjectState.DRAFT
            project.slug = None
    session.flush()
    clear_after_commit_callbacks()


NOT_FIRABLE = ["done", "finished", "archived", "draft"]


class TestWaitServiceFireTransition:
    def test_it_fires_each_open_card_wait_watching_the_card_and_the_state_once(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        person: User,
        project_session: models.Session,
    ) -> None:
        _opened(session, project)
        other, other_run = _other_project(session, person)
        service = _service(container)
        watching = service.add_card_wait(
            project, project_session, "Slice 058 completes", ["ANS-312"], ["Done"], None
        )
        elsewhere = service.add_card_wait(
            other,
            other_run,
            "The night shift takes ANS-312 and SR-4",
            ["SR-4", "ANS-312"],
            ["won't fix", "DONE"],
            None,
        )
        unwatched = service.add_card_wait(
            project, project_session, "SR-1 is done", ["SR-1"], ["Done"], None
        )
        clear_after_commit_callbacks()
        ids = (watching.id, elsewhere.id, unwatched.id)

        with scoped_session(container):
            assert service.fire_transition(_transition(to_state="done")) == 2

        [recorded] = _transitions(session)
        assert (
            recorded.card,
            recorded.from_state,
            recorded.to_state,
            recorded.at,
            recorded.by,
        ) == ("ANS-312", "In Progress", "done", AT, "pieter")
        for wait_id in ids[:2]:
            [firing] = _firings(session, wait_id)
            assert (
                firing.seq,
                firing.wait_kind_code,
                firing.cause_code,
                firing.transition_id,
                firing.requested_by_user_id,
                firing.fired_at,
                firing.job_id,
            ) == (
                1,
                "card_wait",
                FiringCause.TRANSITION,
                recorded.id,
                None,
                recorded.received_at,
                None,
            )
        assert _firings(session, ids[2]) == []
        for each in (project, other):
            assert ProjectChanged(each.id) in engine_events
            assert (
                TreeHashMoved(
                    tree_path(each, TIMELINE),
                    container.view_service().timeline(each).hash,
                )
                in engine_events
            )
        assert [
            (firing["cause"], firing["transition"])
            for firing in _shown_firings(container, other, ids[1])
        ] == [
            (
                "transition",
                {
                    "card": "ANS-312",
                    "from": "In Progress",
                    "to": "done",
                    "at": "2026-10-12T09:30:00Z",
                    "by": "pieter",
                },
            )
        ]

    @pytest.mark.parametrize(
        ("card", "to_state"),
        [("ANS-313", "Done"), ("ANS-312", "In Review"), ("ans-312", "Done")],
    )
    def test_a_transition_no_card_wait_watches_is_not_recorded(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
        card: str,
        to_state: str,
    ) -> None:
        _opened(session, project)
        added = _card_wait(container, project, project_session)
        clear_after_commit_callbacks()

        with scoped_session(container):
            assert _service(container).fire_transition(_transition(card, to_state)) == 0

        assert _transitions(session) == []
        assert _firings(session, added.id) == []
        assert engine_events == []

    @pytest.mark.parametrize("how", NOT_FIRABLE)
    def test_a_done_wait_or_one_of_a_project_not_open_or_archived_fires_not(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        how: str,
    ) -> None:
        _opened(session, project)
        added = _card_wait(container, project, project_session)
        _not_firable(session, container, project, added, project_session, how)

        assert _service(container).fire_transition(_transition()) == 0

        assert _transitions(session) == []
        assert _firings(session, added.id) == []

    def test_a_transition_posted_again_fires_again(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        # No dedupe of a redelivered transition (F136.3).
        _opened(session, project)
        added = _card_wait(container, project, project_session)
        service = _service(container)

        assert service.fire_transition(_transition()) == 1
        assert service.fire_transition(_transition()) == 1
        clear_after_commit_callbacks()

        first, second = _transitions(session)
        assert [
            (firing.seq, firing.transition_id) for firing in _firings(session, added.id)
        ] == [(1, first.id), (2, second.id)]


class TestWaitServiceFireDue:
    def test_an_overdue_timed_wait_fires_due_once_after_its_earlier_firings(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        person: User,
        project_session: models.Session,
    ) -> None:
        _opened(session, project)
        overdue = _overdue(session, container, project, project_session)
        ahead = _service(container).add_timed_wait(
            project, project_session, "A 24-hour soak", _ahead(24), None
        )
        session.add(
            WaitFiring(
                wait_id=overdue.id,
                wait_kind_code="timed_wait",
                seq=1,
                cause_code=FiringCause.REQUESTED,
                requested_by_user_id=person.id,
                fired_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        session.flush()
        clear_after_commit_callbacks()
        project_id = project.id
        service = _service(container)

        with scoped_session(container):
            assert service.fire_due() == 1

        due = _firings(session, overdue.id)[1]
        assert (
            due.seq,
            due.wait_kind_code,
            due.cause_code,
            due.transition_id,
            due.requested_by_user_id,
            due.job_id,
        ) == (2, "timed_wait", FiringCause.DUE, None, None, None)
        assert _firings(session, ahead.id) == []
        assert ProjectChanged(project_id) in engine_events
        assert [
            firing["cause"] for firing in _shown_firings(container, project, overdue.id)
        ] == [
            "requested",
            "due",
        ]
        engine_events.clear()

        with scoped_session(container):
            assert service.fire_due() == 0

        assert len(_firings(session, overdue.id)) == 2
        assert engine_events == []

    @pytest.mark.parametrize("how", NOT_FIRABLE)
    def test_a_done_wait_or_one_of_a_project_not_open_or_archived_fires_not(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        how: str,
    ) -> None:
        _opened(session, project)
        overdue = _overdue(session, container, project, project_session)
        _not_firable(session, container, project, overdue, project_session, how)

        assert _service(container).fire_due() == 0

        assert _firings(session, overdue.id) == []


class TestWaitServiceFireDueInTwoProcesses:
    """During a roll two processes run the timer at once (design 2 §8.1)."""

    def test_a_wait_another_process_is_firing_is_skipped(
        self, committed_app: Flask
    ) -> None:
        container = committed_app.container
        wait_id = _committed_overdue(container)

        with scoped_session(container):
            assert container.wait_service().fire_due() == 1
            # The other process, while this one's firing is not committed.
            assert _in_thread(lambda: _fire_due(container)) == 0

        assert _fire_due(container) == 0
        assert _due_count(container, wait_id) == 1

    def test_a_firing_committed_after_the_read_is_seen_under_the_lock(
        self, committed_app: Flask, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        container = committed_app.container
        wait_id = _committed_overdue(container)
        hold = WaitService._hold
        pending = [True]
        earlier: list[int] = []

        def hooked(
            service: WaitService,
            project_id: uuid.UUID,
            wait: uuid.UUID,
            *,
            skip_locked: bool,
        ) -> Project | None:
            # The other process fires and commits after this one read the
            # wait as due, before it takes the Wait's row.
            if pending:
                pending.pop()
                earlier.append(_in_thread(lambda: _fire_due(container)))
            return hold(service, project_id, wait, skip_locked=skip_locked)

        monkeypatch.setattr(wait_service.WaitService, "_hold", hooked)

        assert _fire_due(container) == 0
        assert earlier == [1]
        assert _due_count(container, wait_id) == 1


def _committed_overdue(container: ServiceContainer) -> uuid.UUID:
    """An open project's timed wait whose due time has passed, committed."""
    with scoped_session(container) as db:
        person = User(
            kind_code=UserKind.PERSON,
            subject="subject-ada",
            handle="ada",
            name="Ada Example",
            avatar_slot=1,
        )
        db.add_all([person, Environment(id="env-1", name="Example-1", exempt=False)])
        db.flush()
        project = Project(
            created_by_user_id=person.id,
            state_code=ProjectState.OPEN,
            slug="camp",
            name="Camp",
        )
        db.add(project)
        db.flush()
        run = models.Session(
            project_id=project.id,
            environment_id="env-1",
            kind_code="work",
            cwd="/work/Example",
            token_hash="1" * 64,
            state_code=SessionState.RUNNING,
        )
        db.add(run)
        db.flush()
        return _overdue(db, container, project, run).id


def _fire_due(container: ServiceContainer) -> int:
    with scoped_session(container):
        fired: int = container.wait_service().fire_due()
        return fired


def _due_count(container: ServiceContainer, wait_id: uuid.UUID) -> int:
    with scoped_session(container) as db:
        count: int = (
            db.scalar(
                select(func.count())
                .select_from(WaitFiring)
                .where(
                    WaitFiring.wait_id == wait_id,
                    WaitFiring.cause_code == FiringCause.DUE,
                )
            )
            or 0
        )
        return count


def _in_thread[T](run: Callable[[], T]) -> T:
    """`run`'s result, run on a thread of its own: another process's
    transaction, on a database session of its own."""
    results: list[T] = []
    thread = threading.Thread(target=lambda: results.append(run()))
    thread.start()
    thread.join(timeout=30)
    assert results, "the other process did not finish"
    return results[0]


def _fired(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
    creator: models.Session,
    ago: timedelta = timedelta(minutes=1),
) -> Item:
    """An open card wait of `project`'s, fired once by a transition `ago`."""
    _opened(session, project)
    added = _card_wait(container, project, creator)
    assert _service(container).fire_transition(_transition()) == 1
    for firing in _firings(session, added.id):
        firing.fired_at = datetime.now(UTC) - ago
    session.flush()
    clear_after_commit_callbacks()
    return added


def _run(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
    wait: Item,
    state: SessionState,
    *,
    turns: int = 1,
    conversation: str | None = None,
    turn_ended_at: datetime | None = None,
) -> models.Work:
    """A run of `wait`, a `wait_fired` job in `state`, as the batcher places
    it and the gate and the relay leave it."""
    job = models.Session(
        project_id=project.id,
        kind_code="job",
        cwd="/work/PilotProjects",
        token_hash=uuid.uuid4().hex,
        state_code=state,
        turns=turns,
        conversation_id=conversation,
        turn_ended_at=turn_ended_at,
    )
    session.add(job)
    session.flush()
    work = container.record_service().place_work(
        project,
        job,
        "Checking the wait",
        trigger=WorkTrigger.WAIT_FIRED,
        trigger_item_id=wait.id,
    )
    clear_after_commit_callbacks()
    return work


IN_FLIGHT = [SessionState.HELD, SessionState.STARTING, SessionState.RUNNING]
ENDED = [SessionState.IDLE, SessionState.FAILED, SessionState.STOPPED]


class TestWaitServiceBatchesDue:
    """The batcher's read (design 2 §8.2; F136.4)."""

    def test_a_wait_whose_oldest_pending_firing_is_past_the_cutoff_is_due(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
        project_session: models.Session,
    ) -> None:
        added = _fired(session, container, project, project_session)
        other, other_run = _other_project(session, person)
        recent = _card_wait(container, other, other_run)
        assert _service(container).fire_transition(_transition()) == 2
        clear_after_commit_callbacks()
        fired_at = _firings(session, added.id)[0].fired_at

        # The firing of `added` a minute old; the second, of both waits, now.
        assert _service(container).batches_due(fired_at) == [(project.id, added.id)]
        assert _service(container).batches_due(fired_at - timedelta(seconds=1)) == []
        assert _firings(session, recent.id)[0].job_id is None

    def test_a_wait_whose_firings_a_run_took_is_not(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        added = _fired(session, container, project, project_session)
        work = _run(session, container, project, added, SessionState.IDLE)
        _firings(session, added.id)[0].job_id = work.id
        session.flush()

        assert _service(container).batches_due(datetime.now(UTC)) == []

    @pytest.mark.parametrize("state", IN_FLIGHT)
    def test_a_wait_with_a_run_held_starting_or_running_is_not(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        state: SessionState,
    ) -> None:
        """A run held at the gate or queued, not yet briefed, counts too: its
        brief takes the firings still pending."""
        added = _fired(session, container, project, project_session)
        _run(session, container, project, added, state, turns=0)

        assert _service(container).batches_due(datetime.now(UTC)) == []

    def test_a_wait_whose_run_waits_for_its_nudge_at_the_quota_wall_is_not(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        added = _fired(session, container, project, project_session)
        work = _run(session, container, project, added, SessionState.FAILED)
        session.get_one(models.Session, work.id).nudge_owed_at = datetime.now(UTC)
        session.flush()

        assert _service(container).batches_due(datetime.now(UTC)) == []

    @pytest.mark.parametrize("state", ENDED)
    def test_a_wait_whose_runs_ended_is_due_for_its_firing_since(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        state: SessionState,
    ) -> None:
        added = _fired(session, container, project, project_session)
        _run(session, container, project, added, state)

        assert _service(container).batches_due(datetime.now(UTC)) == [
            (project.id, added.id)
        ]

    @pytest.mark.parametrize("how", NOT_FIRABLE)
    def test_a_done_wait_or_one_of_a_project_not_open_or_archived_is_not(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        how: str,
    ) -> None:
        added = _fired(session, container, project, project_session)
        _not_firable(session, container, project, added, project_session, how)

        assert _service(container).batches_due(datetime.now(UTC)) == []


class TestWaitServiceHoldBatch:
    """The batcher's read again under the rows: one run per batch."""

    def test_a_due_batch_is_held_its_project_and_wait_given(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        added = _fired(session, container, project, project_session)

        held = _service(container).hold_batch(project.id, added.id, datetime.now(UTC))

        assert held == (project, added)

    def test_a_batch_whose_run_was_placed_since_the_read_is_not(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        added = _fired(session, container, project, project_session)
        service = _service(container)
        assert service.batches_due(datetime.now(UTC)) == [(project.id, added.id)]
        _run(session, container, project, added, SessionState.HELD, turns=0)

        assert service.hold_batch(project.id, added.id, datetime.now(UTC)) is None

    def test_a_batch_whose_firing_is_younger_than_the_cutoff_is_not(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        added = _fired(session, container, project, project_session)

        held = _service(container).hold_batch(
            project.id, added.id, datetime.now(UTC) - timedelta(minutes=2)
        )

        assert held is None

    @pytest.mark.parametrize("how", ["done", "finished", "archived"])
    def test_a_wait_done_since_the_read_or_its_project_closed_is_not(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        how: str,
    ) -> None:
        added = _fired(session, container, project, project_session)
        _not_firable(session, container, project, added, project_session, how)

        assert (
            _service(container).hold_batch(project.id, added.id, datetime.now(UTC))
            is None
        )


class TestWaitServiceTake:
    """A run takes every firing of its wait pending at its brief (DB 191,
    196)."""

    def test_it_takes_every_pending_firing_and_moves_the_timeline(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
    ) -> None:
        added = _fired(session, container, project, project_session)
        earlier = _run(session, container, project, added, SessionState.IDLE)
        _firings(session, added.id)[0].job_id = earlier.id
        assert _service(container).fire_transition(_transition()) == 1
        assert _service(container).fire_transition(_transition()) == 1
        work = _run(session, container, project, added, SessionState.STARTING)
        project_id = project.id
        clear_after_commit_callbacks()

        with scoped_session(container):
            _service(container).take(project, work)

        assert [
            (firing.seq, firing.job_id) for firing in _firings(session, added.id)
        ] == [(1, earlier.id), (2, work.id), (3, work.id)]
        assert engine_events == [
            TreeHashMoved(
                tree_path(project, TIMELINE),
                container.view_service().timeline(project).hash,
            ),
            ProjectChanged(project_id),
        ]
        assert [
            firing["job"] for firing in _shown_firings(container, project, added.id)
        ] == [
            str(earlier.id),
            str(work.id),
            str(work.id),
        ]

    def test_with_nothing_pending_it_takes_none_and_moves_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        project_session: models.Session,
    ) -> None:
        _opened(session, project)
        added = _card_wait(container, project, project_session)
        work = _run(session, container, project, added, SessionState.STARTING)

        with scoped_session(container):
            _service(container).take(project, work)

        assert engine_events == []


class TestWaitServiceResumed:
    """A wait's run resumes its previous run's conversation while that run's
    turn ended within `cache_expiration_ttl` (F136.5, DB 200)."""

    def _previous(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        wait: Item,
        ended: timedelta,
        state: SessionState = SessionState.IDLE,
        conversation: str | None = "conversation-1",
    ) -> models.Work:
        return _run(
            session,
            container,
            project,
            wait,
            state,
            conversation=conversation,
            turn_ended_at=datetime.now(UTC) - ended,
        )

    def test_within_the_ttl_the_previous_run_is_resumed(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        added = _fired(session, container, project, project_session)
        previous = self._previous(
            session, container, project, added, timedelta(minutes=54)
        )
        work = _run(session, container, project, added, SessionState.STARTING)

        resumed = _service(container).resumed(work, datetime.now(UTC))

        assert resumed is not None and resumed.id == previous.id

    def test_past_the_ttl_none_is(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        added = _fired(session, container, project, project_session)
        self._previous(session, container, project, added, timedelta(minutes=56))
        work = _run(session, container, project, added, SessionState.STARTING)

        assert _service(container).resumed(work, datetime.now(UTC)) is None

    def test_the_ttl_is_the_deployments(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        added = _fired(session, container, project, project_session)
        self._previous(session, container, project, added, timedelta(minutes=11))
        work = _run(session, container, project, added, SessionState.STARTING)
        service = container.wait_service(cache_expiration_ttl_seconds=600)

        assert service.resumed(work, datetime.now(UTC)) is None

    @pytest.mark.parametrize("state", [SessionState.FAILED, SessionState.STOPPED])
    def test_after_a_run_that_failed_or_was_stopped_none_is(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        state: SessionState,
    ) -> None:
        """A resume the controller refused fails its run on the conversation
        it was given: the next run starts fresh."""
        added = _fired(session, container, project, project_session)
        self._previous(session, container, project, added, timedelta(minutes=1), state)
        work = _run(session, container, project, added, SessionState.STARTING)

        assert _service(container).resumed(work, datetime.now(UTC)) is None

    def test_after_a_run_with_no_conversation_none_is(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        added = _fired(session, container, project, project_session)
        self._previous(
            session, container, project, added, timedelta(minutes=1), conversation=None
        )
        work = _run(session, container, project, added, SessionState.STARTING)

        assert _service(container).resumed(work, datetime.now(UTC)) is None

    def test_the_previous_run_is_the_latest_briefed_of_its_wait(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        person: User,
        project_session: models.Session,
    ) -> None:
        """A run never briefed, such as one Finish stopped held, is no run
        that ended; another wait's run is not this wait's."""
        added = _fired(session, container, project, project_session)
        self._previous(session, container, project, added, timedelta(minutes=50))
        latest = self._previous(
            session,
            container,
            project,
            added,
            timedelta(minutes=2),
            conversation="conversation-2",
        )
        _run(session, container, project, added, SessionState.STOPPED, turns=0)
        other = _card_wait(container, project, project_session)
        self._previous(
            session,
            container,
            project,
            other,
            timedelta(minutes=1),
            conversation="conversation-3",
        )
        work = _run(session, container, project, added, SessionState.STARTING)

        resumed = _service(container).resumed(work, datetime.now(UTC))

        assert resumed is not None and resumed.id == latest.id

    def test_a_retry_is_fresh(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        """Also while another run of the wait ended `idle` after the run it
        retries, within the TTL."""
        added = _fired(session, container, project, project_session)
        failed = _run(session, container, project, added, SessionState.FAILED)
        self._previous(session, container, project, added, timedelta(minutes=1))
        retry = _run(session, container, project, added, SessionState.STARTING)
        failed.retried_by_id = retry.id
        session.flush()

        assert _service(container).resumed(retry, datetime.now(UTC)) is None
