"""The projects as the signed-in person reads them: the project list's tabs
and a project's head (F1, F2, F3)."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.exceptions import RecordNotFoundException
from app.models import (
    Environment,
    Item,
    PlanNote,
    PlanTask,
    Project,
    ProjectMember,
    ProjectTransition,
    User,
)
from app.models.reference import ProjectState, TaskStatus, TransitionKind
from app.schemas.testing_record import InventedProjectCreateSchema
from app.services.auth_service import AuthContext
from app.services.container import ServiceContainer
from app.services.project_service import PlanProgress, plan_progress

ADA = AuthContext(
    subject="subject-ada", email=None, name="Ada Example", roles={"editor"}
)
"""The `person` fixture, signed in."""

NEWCOMER = AuthContext(
    subject="subject-newcomer", email=None, name="Nia Newcomer", roles={"editor"}
)
"""A person at their first sign-in, with no handle yet."""


def _make(container: ServiceContainer, **spec: Any) -> Project:
    spec.setdefault("members", ["ada"])
    return container.test_data_service().project(
        InventedProjectCreateSchema.model_validate(spec)
    )


def _ben(container: ServiceContainer) -> User:
    return container.test_data_service().person("ben", "Ben Example")


def _task(task_id: str, status: TaskStatus) -> PlanTask:
    return PlanTask(task_id=task_id, title=task_id.capitalize(), status_code=status)


def _tasks(*statuses: str) -> list[dict[str, Any]]:
    return [
        {"id": f"t{number}", "title": f"Step {number}", "status": status}
        for number, status in enumerate(statuses, start=1)
    ]


class TestPlanProgress:
    def test_counts_the_steps_done_and_names_those_in_progress_in_order(
        self,
    ) -> None:
        steps = [
            _task("scope", TaskStatus.DONE),
            _task("build", TaskStatus.IN_PROGRESS),
            _task("import", TaskStatus.PENDING),
            _task("test", TaskStatus.IN_PROGRESS),
        ]

        assert plan_progress(steps) == PlanProgress(
            done=1, total=4, in_progress=("Build", "Test")
        )

    def test_no_steps_is_no_progress(self) -> None:
        assert plan_progress([]) == PlanProgress(done=0, total=0, in_progress=())


@pytest.mark.usefixtures("person")
class TestTabs:
    def test_every_unarchived_project_in_the_order_made(
        self, container: ServiceContainer
    ) -> None:
        first = _make(container, name="First", ticket="AB-1")
        draft = _make(container, name="Second", state="draft")
        finished = _make(container, name="Third", state="finished")
        _make(container, name="Gone", archived=True)

        tabs = container.project_service().tabs(ADA, archived=False)

        assert [
            (
                tab.project.id,
                tab.project.name,
                tab.project.ticket,
                tab.project.state_code,
            )
            for tab in tabs
        ] == [
            (first.id, "First", "AB-1", ProjectState.OPEN),
            (draft.id, "Second", None, ProjectState.DRAFT),
            (finished.id, "Third", None, ProjectState.FINISHED),
        ]

    def test_the_archived_projects_are_a_list_of_their_own(
        self, container: ServiceContainer
    ) -> None:
        _make(container, name="Kept")
        draft = _make(container, name="Old draft", state="draft", archived=True)
        done = _make(container, name="Old work", state="finished", archived=True)

        tabs = container.project_service().tabs(ADA, archived=True)

        assert [tab.project.id for tab in tabs] == [draft.id, done.id]
        assert tabs[1].finished_at is not None

    def test_a_tab_says_whether_the_caller_is_a_member(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        _ben(container)
        theirs = _make(container, name="Theirs", members=["ben"])
        shared = _make(container, name="Shared", members=["ben", "ada"])
        left = _make(container, name="Left", members=["ada", "ben"])
        ada = session.scalars(select(User).where(User.handle == "ada")).one()
        session.scalars(
            select(ProjectMember).where(
                ProjectMember.project_id == left.id, ProjectMember.user_id == ada.id
            )
        ).one().left_at = left.created_at + timedelta(hours=1)
        session.flush()

        tabs = container.project_service().tabs(ADA, archived=False)

        assert {tab.project.id: tab.member for tab in tabs} == {
            theirs.id: False,
            shared.id: True,
            left.id: False,
        }

    def test_before_the_handle_no_project_is_the_callers(
        self, container: ServiceContainer
    ) -> None:
        _make(container, name="Mine")

        tabs = container.project_service().tabs(NEWCOMER, archived=False)

        assert [tab.member for tab in tabs] == [False]

    def test_a_finished_project_has_the_date_of_its_latest_finish(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        finished = _make(container, name="Twice", state="finished")
        later = finished.created_at + timedelta(days=2)
        ada = session.scalars(select(User).where(User.handle == "ada")).one()
        session.add_all(
            ProjectTransition(
                project_id=finished.id, kind_code=kind, at=at, by_user_id=ada.id
            )
            for kind, at in (
                (TransitionKind.REOPENED, later - timedelta(days=1)),
                (TransitionKind.FINISHED, later),
            )
        )
        session.flush()

        (tab,) = container.project_service().tabs(ADA, archived=False)

        assert tab.finished_at == later

    def test_a_reopened_project_has_no_finished_date(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        reopened = _make(container, name="Again", state="finished")
        ada = session.scalars(select(User).where(User.handle == "ada")).one()
        session.add(
            ProjectTransition(
                project_id=reopened.id,
                kind_code=TransitionKind.REOPENED,
                at=reopened.created_at + timedelta(days=1),
                by_user_id=ada.id,
            )
        )
        reopened.state_code = ProjectState.OPEN
        session.flush()

        (tab,) = container.project_service().tabs(ADA, archived=False)

        assert tab.finished_at is None

    def test_a_tab_has_its_plans_progress_removed_steps_left_out(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        planned = _make(
            container,
            name="Planned",
            tasks=_tasks("done", "in_progress", "pending", "in_progress", "done"),
        )
        removed = session.get_one(PlanTask, (planned.id, "t5"))
        removed.position, removed.removed_at = None, planned.created_at
        unplanned = _make(container, name="Unplanned")
        session.flush()

        tabs = container.project_service().tabs(ADA, archived=False)

        assert {tab.project.id: tab.progress for tab in tabs} == {
            planned.id: PlanProgress(done=1, total=4, in_progress=("Step 2", "Step 4")),
            unplanned.id: PlanProgress(done=0, total=0, in_progress=()),
        }

    def test_no_project_is_an_empty_list(self, container: ServiceContainer) -> None:
        assert container.project_service().tabs(ADA, archived=False) == []


@pytest.mark.usefixtures("person")
class TestHead:
    def test_the_projects_standing(self, container: ServiceContainer) -> None:
        made = _make(
            container,
            name="Recipe box",
            ticket="RB-12",
            repo="pvginkel/RecipeBox",
            autopilot=True,
        )

        head = container.project_service().head(ADA, made.id)

        assert head.project is made
        assert (
            made.name,
            made.ticket,
            made.repo,
            made.state_code,
            made.archived,
            made.autopilot,
        ) == (
            "Recipe box",
            "RB-12",
            "pvginkel/RecipeBox",
            ProjectState.OPEN,
            False,
            True,
        )

    def test_the_members_in_the_order_they_joined(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        ada = session.scalars(select(User).where(User.handle == "ada")).one()
        ben = _ben(container)
        cleo = container.test_data_service().person("cleo", "Cleo Example")
        made = _make(container, name="Shared", members=["ben", "ada", "cleo"])
        memberships = {
            member.user_id: member
            for member in session.scalars(
                select(ProjectMember).where(ProjectMember.project_id == made.id)
            )
        }
        # Ben leaves and joins again, after the others: a new row.
        memberships[ben.id].left_at = made.created_at + timedelta(hours=1)
        session.add(
            ProjectMember(
                project_id=made.id,
                user_id=ben.id,
                joined_at=made.created_at + timedelta(hours=2),
            )
        )
        session.flush()

        head = container.project_service().head(ADA, made.id)

        assert [person.id for person in head.members] == [ada.id, cleo.id, ben.id]

    def test_a_member_who_left_is_not_shown(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        _ben(container)
        made = _make(container, name="Shared", members=["ada", "ben"])
        for member in session.scalars(
            select(ProjectMember).where(ProjectMember.project_id == made.id)
        ):
            member.left_at = made.created_at + timedelta(hours=1)
        session.flush()

        head = container.project_service().head(ADA, made.id)

        assert (head.members, head.member) == ((), False)

    def test_whether_the_caller_is_a_member(self, container: ServiceContainer) -> None:
        _ben(container)
        mine = _make(container, name="Mine", members=["ben", "ada"])
        theirs = _make(container, name="Theirs", members=["ben"])
        service = container.project_service()

        assert service.head(ADA, mine.id).member is True
        assert service.head(ADA, theirs.id).member is False
        assert service.head(NEWCOMER, mine.id).member is False

    def test_the_steps_in_order_with_their_open_notes(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        made = _make(
            container,
            name="Planned",
            tasks=[
                {"id": "scope", "title": "Agree the scope", "status": "done"},
                {
                    "id": "build",
                    "title": "Build it",
                    "status": "in_progress",
                    "notes": [
                        {"id": "n1", "summary": "First", "content": "One"},
                        {"id": "n2", "summary": "Second", "content": "Two"},
                        {"id": "n3", "summary": "Struck", "content": "Three"},
                    ],
                },
                {"id": "spike", "title": "Try a spike", "status": "pending"},
                {"id": "ship", "title": "Ship it", "status": "pending"},
            ],
        )
        spike = session.get_one(PlanTask, (made.id, "spike"))
        spike.position, spike.removed_at = None, made.created_at
        session.scalars(
            select(PlanNote).where(
                PlanNote.project_id == made.id, PlanNote.note_id == "n3"
            )
        ).one().deleted_at = made.created_at
        session.flush()

        head = container.project_service().head(ADA, made.id)

        assert [
            (
                step.task.task_id,
                step.task.status_code,
                [(note.note_id, note.summary, note.content) for note in step.notes],
            )
            for step in head.steps
        ] == [
            ("scope", TaskStatus.DONE, []),
            (
                "build",
                TaskStatus.IN_PROGRESS,
                [("n1", "First", "One"), ("n2", "Second", "Two")],
            ),
            ("ship", TaskStatus.PENDING, []),
        ]
        assert head.progress == PlanProgress(done=1, total=3, in_progress=("Build it",))

    def test_the_plans_own_open_notes(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        made = _make(
            container,
            name="Planned",
            tasks=_tasks("pending"),
            notes=[
                {"id": "print", "summary": "Print view", "content": "No task yet."},
                {"id": "gone", "summary": "Struck", "content": "Gone."},
            ],
        )
        session.scalars(
            select(PlanNote).where(
                PlanNote.project_id == made.id, PlanNote.note_id == "gone"
            )
        ).one().deleted_at = made.created_at
        session.flush()

        head = container.project_service().head(ADA, made.id)

        assert [(note.note_id, note.summary, note.content) for note in head.notes] == [
            ("print", "Print view", "No task yet.")
        ]
        assert head.steps[0].notes == ()

    def test_the_open_items_leave_out_the_opening_and_the_done(
        self, container: ServiceContainer, session: DbSession, environment: Environment
    ) -> None:
        made = _make(
            container, name="Busy", open_items=3, environment_id=environment.id
        )
        ada = session.scalars(select(User).where(User.handle == "ada")).one()
        container.document_service().bear_opening(made, "Busy", ada, "# Busy\n")
        first = session.scalars(
            select(Item).where(Item.project_id == made.id, Item.title == "Notice 1")
        ).one()
        container.record_service().read(first, ada)

        head = container.project_service().head(ADA, made.id)

        assert head.open_items == 2

    def test_a_draft_has_no_plan_and_no_items(
        self, container: ServiceContainer
    ) -> None:
        draft = _make(container, state="draft")

        head = container.project_service().head(ADA, draft.id)

        assert (draft.name, head.steps, head.notes, head.open_items) == (
            None,
            (),
            (),
            0,
        )
        assert head.progress == PlanProgress(done=0, total=0, in_progress=())

    def test_an_unknown_project_is_not_found(self, container: ServiceContainer) -> None:
        unknown = uuid.uuid4()

        with pytest.raises(RecordNotFoundException) as raised:
            container.project_service().head(ADA, unknown)

        assert raised.value.message == f"Project {unknown} was not found"
