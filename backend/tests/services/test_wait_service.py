"""The waits (F27, DB decision 46): a card wait or a timed wait born with what
it waits on and fixed from then on, refused as F86.1 has it, and closed by
Pilot's own `done` with a note (DB 199, 300) or by Finish, with none."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.engine.bus import EngineEvent, ProjectChanged
from app.exceptions import InvalidOperationException
from app.models import Item, PlanTask, Project, User, Wait
from app.models.reference import ProjectState, TaskStatus, TransitionKind, UserKind
from app.services.container import ServiceContainer
from app.services.wait_service import WaitService
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
