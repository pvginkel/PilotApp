"""The projects as the signed-in person reads them, the project list's tabs
and a project's head, its status among them (F1, F2, F3, F141.1; DB 227,
228); and what they change of a project's standing, its transitions and their
membership (F4.1, F5, F6, F127, F128, F141.2; DB 170, 171)."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flask import Flask
from psycopg.errors import LockNotAvailable
from sqlalchemy import select
from sqlalchemy import text as sql
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.engine.bus import (
    EngineEvent,
    ManifestChanged,
    ProjectChanged,
    TreeHashMoved,
    WorkMoved,
)
from app.engine.paths import TIMELINE, tree_path
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.extensions import db
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
from app.models.reference import (
    ProjectState,
    SessionState,
    TaskStatus,
    TransitionKind,
    UserKind,
)
from app.schemas.projects import ProjectStatus
from app.schemas.testing_record import InventedProjectCreateSchema
from app.services.auth_service import AuthContext
from app.services.container import ServiceContainer
from app.services.project_service import (
    ARCHIVED_REFUSAL,
    Activity,
    PlanProgress,
    plan_progress,
    project_status,
)
from app.services.timeline_service import Badge

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


def _transitions(
    session: DbSession, project: Project
) -> list[tuple[TransitionKind, datetime, uuid.UUID]]:
    return [
        (transition.kind_code, transition.at, transition.by_user_id)
        for transition in session.scalars(
            select(ProjectTransition)
            .where(ProjectTransition.project_id == project.id)
            .order_by(ProjectTransition.at, ProjectTransition.id)
        )
    ]


def _standing(project: Project) -> tuple[ProjectState, bool, bool]:
    return project.state_code, project.archived, project.autopilot


def _memberships(
    session: DbSession, project: Project, person: User
) -> list[ProjectMember]:
    return list(
        session.scalars(
            select(ProjectMember)
            .where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == person.id,
            )
            .order_by(ProjectMember.id)
        )
    )


def _task(task_id: str, status: TaskStatus) -> PlanTask:
    return PlanTask(task_id=task_id, title=task_id.capitalize(), status_code=status)


def _tasks(*statuses: str) -> list[dict[str, Any]]:
    return [
        {"id": f"t{number}", "title": f"Step {number}", "status": status}
        for number, status in enumerate(statuses, start=1)
    ]


def _run(
    container: ServiceContainer,
    session: DbSession,
    project: Project,
    environment: Environment,
    state: SessionState,
    kind: str = "work",
) -> models.Session:
    """A Session of the project in `state`; one of kind `work` with its work
    item."""
    run = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code=kind,
        cwd="/work/Camp",
        token_hash=uuid.uuid4().hex * 2,
        state_code=state,
    )
    session.add(run)
    session.flush()
    if kind == "work":
        container.record_service().place_work(project, run, "Build the camp")
    return run


def _wait(
    container: ServiceContainer,
    session: DbSession,
    project: Project,
    run: models.Session,
) -> Item:
    wait = Item(
        project_id=project.id,
        seq=container.document_service().next_seq(project),
        kind_code="timed_wait",
        title="The site opens",
        created_by_session_id=run.id,
    )
    session.add(wait)
    session.flush()
    return wait


QUIET = Activity(running=False, work_running=False, waiting=False, wait_open=False)


class TestProjectStatus:
    """The order assertion 228 reads the status in (F141.1)."""

    @pytest.mark.parametrize(
        ("standing", "activity", "progress", "status"),
        [
            ({"state_code": ProjectState.DRAFT}, QUIET, (0, 0), None),
            (
                {"state_code": ProjectState.FINISHED},
                Activity(running=True, work_running=True, waiting=True, wait_open=True),
                (2, 2),
                None,
            ),
            ({"paused": True}, QUIET, (2, 2), ProjectStatus.PAUSED),
            (
                {"paused": True},
                Activity(
                    running=True, work_running=False, waiting=True, wait_open=True
                ),
                (0, 1),
                ProjectStatus.PAUSING,
            ),
            (
                {},
                Activity(running=True, work_running=True, waiting=True, wait_open=True),
                (2, 2),
                ProjectStatus.RUNNING,
            ),
            (
                {},
                Activity(
                    running=False, work_running=False, waiting=True, wait_open=True
                ),
                (2, 2),
                ProjectStatus.WAITING_ON_YOU,
            ),
            (
                {},
                Activity(
                    running=False, work_running=False, waiting=False, wait_open=True
                ),
                (2, 2),
                ProjectStatus.WAITING_ON_EVENT,
            ),
            ({}, QUIET, (2, 2), ProjectStatus.DONE),
            ({}, QUIET, (1, 2), ProjectStatus.IDLE),
            ({}, QUIET, (0, 0), ProjectStatus.IDLE),
            (
                {},
                Activity(
                    running=True, work_running=False, waiting=False, wait_open=False
                ),
                (1, 2),
                ProjectStatus.IDLE,
            ),
        ],
        ids=[
            "draft",
            "finished",
            "paused",
            "pausing",
            "running",
            "waiting-on-you",
            "waiting-on-an-event",
            "done",
            "idle",
            "no-plan-is-not-done",
            "a-chat-running-is-not-work-running",
        ],
    )
    def test_the_first_that_holds(
        self,
        standing: dict[str, Any],
        activity: Activity,
        progress: tuple[int, int],
        status: ProjectStatus | None,
    ) -> None:
        project = Project(
            state_code=standing.get("state_code", ProjectState.OPEN),
            paused=standing.get("paused", False),
        )
        done, total = progress

        assert (
            project_status(project, activity, PlanProgress(done, total, ())) is status
        )


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

    def test_a_tab_has_its_badge_for_the_caller(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        waiting = _make(container, name="Waiting")
        quiet = _make(container, name="Quiet")
        run = models.Session(
            project_id=waiting.id,
            environment_id=environment.id,
            kind_code="work",
            cwd="/work/Waiting",
            token_hash="2" * 64,
            state_code=SessionState.IDLE,
        )
        session.add(run)
        session.flush()
        container.document_service().bear_item(
            waiting, "question", "Where?", run, "---\nurgent: true\n---\n"
        )

        tabs = container.project_service().tabs(ADA, archived=False)

        assert {tab.project.id: tab.badge for tab in tabs} == {
            waiting.id: Badge(1, True),
            quiet.id: Badge(0, False),
        }

    def test_a_tab_has_the_projects_status_read_from_the_record(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        running = _make(container, name="Running", tasks=_tasks("done"))
        _run(container, session, running, environment, SessionState.RUNNING)
        stopped = _make(container, name="Stopped")
        _run(container, session, stopped, environment, SessionState.STOPPED)
        waiting = _make(container, name="Waiting")
        idle = _run(container, session, waiting, environment, SessionState.IDLE)
        _wait(container, session, waiting, idle)
        done = _make(container, name="Done", tasks=_tasks("done", "done"))
        quiet = _make(container, name="Quiet", tasks=_tasks("done", "pending"))
        pausing = _make(container, name="Pausing", paused=True)
        _run(container, session, pausing, environment, SessionState.RUNNING, "chat")
        paused = _make(container, name="Paused", paused=True)
        _run(container, session, paused, environment, SessionState.STOPPED)
        draft = _make(container, name="Draft", state="draft")
        finished = _make(container, name="Finished", state="finished")

        tabs = container.project_service().tabs(ADA, archived=False)

        assert {tab.project.id: tab.status for tab in tabs} == {
            running.id: ProjectStatus.RUNNING,
            stopped.id: ProjectStatus.WAITING_ON_YOU,
            waiting.id: ProjectStatus.WAITING_ON_EVENT,
            done.id: ProjectStatus.DONE,
            quiet.id: ProjectStatus.IDLE,
            pausing.id: ProjectStatus.PAUSING,
            paused.id: ProjectStatus.PAUSED,
            draft.id: None,
            finished.id: None,
        }

    def test_the_status_waits_on_a_member_whoever_reads_it(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        """F94.5's set, any member's (DB 225, 228): an item for nobody or for
        a member, where the badge counts the caller's own (F1.4)."""
        _ben(container)
        for_ben = _make(container, name="For Ben", members=["ada", "ben"])
        not_for_a_member = _make(container, name="For no member")
        nobodys = _make(container, name="Nobody's")
        for project in (for_ben, not_for_a_member):
            run = _run(container, session, project, environment, SessionState.IDLE)
            container.document_service().bear_item(
                project, "question", "Where?", run, "---\nfor: ben\n---\n"
            )
        run = _run(container, session, nobodys, environment, SessionState.IDLE)
        container.document_service().bear_item(nobodys, "question", "Where?", run)
        container.project_service().leave(ADA, nobodys.id)

        tabs = container.project_service().tabs(ADA, archived=False)

        assert {tab.project.id: (tab.status, tab.badge.count) for tab in tabs} == {
            for_ben.id: (ProjectStatus.WAITING_ON_YOU, 0),
            not_for_a_member.id: (ProjectStatus.IDLE, 0),
            nobodys.id: (ProjectStatus.IDLE, 1),
        }

    def test_an_archived_projects_tab_has_its_status(
        self, container: ServiceContainer
    ) -> None:
        paused = _make(container, name="Paused", paused=True, archived=True)
        draft = _make(container, name="Draft", state="draft", archived=True)

        tabs = container.project_service().tabs(ADA, archived=True)

        assert {tab.project.id: tab.status for tab in tabs} == {
            paused.id: ProjectStatus.PAUSED,
            draft.id: None,
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

    @pytest.mark.parametrize(
        ("spec", "status"),
        [
            ({"paused": True}, ProjectStatus.PAUSED),
            ({"tasks": _tasks("done")}, ProjectStatus.DONE),
            ({"state": "draft"}, None),
            ({"state": "finished"}, None),
        ],
    )
    def test_the_projects_status(
        self,
        container: ServiceContainer,
        spec: dict[str, Any],
        status: ProjectStatus | None,
    ) -> None:
        made = _make(container, name="Camp", **spec)

        assert container.project_service().head(ADA, made.id).status is status

    def test_a_running_work_item_is_the_heads_status(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        made = _make(container, name="Camp")
        _run(container, session, made, environment, SessionState.RUNNING)

        head = container.project_service().head(ADA, made.id)

        assert head.status is ProjectStatus.RUNNING

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


@pytest.mark.usefixtures("person")
class TestTransition:
    @pytest.mark.parametrize(
        ("spec", "kind", "standing"),
        [
            (
                {"state": "open"},
                TransitionKind.FINISHED,
                (ProjectState.FINISHED, False, False),
            ),
            (
                {"state": "finished"},
                TransitionKind.REOPENED,
                (ProjectState.OPEN, False, False),
            ),
            (
                {"state": "draft"},
                TransitionKind.ARCHIVED,
                (ProjectState.DRAFT, True, False),
            ),
            (
                {"state": "open", "autopilot": True},
                TransitionKind.ARCHIVED,
                (ProjectState.OPEN, True, True),
            ),
            (
                {"state": "finished"},
                TransitionKind.ARCHIVED,
                (ProjectState.FINISHED, True, False),
            ),
            (
                {"state": "draft", "archived": True},
                TransitionKind.BROUGHT_BACK,
                (ProjectState.DRAFT, False, False),
            ),
            (
                {"state": "open", "autopilot": True, "archived": True},
                TransitionKind.BROUGHT_BACK,
                (ProjectState.OPEN, False, True),
            ),
            (
                {"state": "finished", "archived": True},
                TransitionKind.BROUGHT_BACK,
                (ProjectState.FINISHED, False, False),
            ),
            (
                {"state": "open"},
                TransitionKind.AUTOPILOT_ON,
                (ProjectState.OPEN, False, True),
            ),
            (
                {"state": "open", "autopilot": True},
                TransitionKind.AUTOPILOT_OFF,
                (ProjectState.OPEN, False, False),
            ),
        ],
    )
    def test_a_transition_its_standing_allows(
        self,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        spec: dict[str, Any],
        kind: TransitionKind,
        standing: tuple[ProjectState, bool, bool],
    ) -> None:
        made = _make(container, name="Camp", **spec)
        before = _transitions(session, made)
        started = datetime.now(UTC)

        container.project_service().transition(ADA, made.id, kind)

        ((written, at, by),) = _transitions(session, made)[len(before) :]
        assert (written, by) == (kind, person.id)
        assert started <= at <= datetime.now(UTC)
        assert _standing(made) == standing

    def test_finish_turns_auto_pilot_off_at_its_instant_by_its_person(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        made = _make(container, name="Camp", autopilot=True)
        before = _transitions(session, made)

        container.project_service().transition(ADA, made.id, TransitionKind.FINISHED)

        finished, autopilot_off = _transitions(session, made)[len(before) :]
        assert finished[0] is TransitionKind.FINISHED
        assert autopilot_off == (TransitionKind.AUTOPILOT_OFF, *finished[1:])
        assert finished[2] == person.id
        assert _standing(made) == (ProjectState.FINISHED, False, False)

    @pytest.mark.parametrize(
        ("spec", "kind", "paused"),
        [
            ({"state": "open"}, TransitionKind.PAUSED, True),
            ({"state": "open", "autopilot": True}, TransitionKind.PAUSED, True),
            ({"state": "open", "paused": True}, TransitionKind.RESUMED, False),
            (
                {"state": "open", "autopilot": True, "paused": True},
                TransitionKind.RESUMED,
                False,
            ),
        ],
    )
    def test_a_pause_and_a_resume_are_the_callers_transitions(
        self,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        spec: dict[str, Any],
        kind: TransitionKind,
        paused: bool,
    ) -> None:
        made = _make(container, name="Camp", **spec)
        before = (_transitions(session, made), _standing(made))
        started = datetime.now(UTC)

        container.project_service().transition(ADA, made.id, kind)

        ((written, at, by),) = _transitions(session, made)[len(before[0]) :]
        assert (written, by) == (kind, person.id)
        assert started <= at <= datetime.now(UTC)
        assert made.paused is paused
        # The grants are untouched: the switch stays where it is (F141.3).
        assert _standing(made) == before[1]

    def test_finish_resumes_a_paused_project_at_its_instant_by_its_person(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        made = _make(container, name="Camp", autopilot=True, paused=True)
        before = _transitions(session, made)

        container.project_service().transition(ADA, made.id, TransitionKind.FINISHED)

        finished, autopilot_off, resumed = _transitions(session, made)[len(before) :]
        assert finished[0] is TransitionKind.FINISHED
        assert autopilot_off == (TransitionKind.AUTOPILOT_OFF, *finished[1:])
        assert resumed == (TransitionKind.RESUMED, *finished[1:])
        assert finished[2] == person.id
        assert made.paused is False

    def test_a_reopened_project_is_not_paused(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        made = _make(container, name="Camp", paused=True)
        service = container.project_service()
        service.transition(ADA, made.id, TransitionKind.FINISHED)
        before = _transitions(session, made)

        service.transition(ADA, made.id, TransitionKind.REOPENED)

        assert [kind for kind, _, _ in _transitions(session, made)[len(before) :]] == [
            TransitionKind.REOPENED
        ]
        assert made.paused is False

    def test_archive_keeps_the_pause_and_bring_back_returns_it(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        made = _make(container, name="Camp", paused=True)
        service = container.project_service()
        before = _transitions(session, made)

        service.transition(ADA, made.id, TransitionKind.ARCHIVED)
        archived = made.paused
        service.transition(ADA, made.id, TransitionKind.BROUGHT_BACK)

        assert [kind for kind, _, _ in _transitions(session, made)[len(before) :]] == [
            TransitionKind.ARCHIVED,
            TransitionKind.BROUGHT_BACK,
        ]
        assert (archived, made.paused) == (True, True)
        assert service.head(ADA, made.id).status is ProjectStatus.PAUSED

    def test_finish_closes_the_open_items_at_its_instant(
        self,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        environment: Environment,
    ) -> None:
        made = _make(
            container, name="Camp", open_items=2, environment_id=environment.id
        )
        service = container.project_service()

        service.transition(ADA, made.id, TransitionKind.FINISHED)

        ((_, at, _),) = [
            transition
            for transition in _transitions(session, made)
            if transition[0] is TransitionKind.FINISHED
        ]
        items = session.scalars(
            select(Item).where(Item.project_id == made.id, Item.kind_code != "opening")
        )
        assert [
            (item.done_at, item.done_cause_code, item.done_by_user_id) for item in items
        ] == [(at, "finished", person.id)] * 2
        assert service.head(ADA, made.id).open_items == 0

    def test_reopen_leaves_auto_pilot_off(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        made = _make(container, name="Camp", autopilot=True)
        service = container.project_service()
        service.transition(ADA, made.id, TransitionKind.FINISHED)
        before = _transitions(session, made)

        service.transition(ADA, made.id, TransitionKind.REOPENED)

        assert [kind for kind, _, _ in _transitions(session, made)[len(before) :]] == [
            TransitionKind.REOPENED
        ]
        assert _standing(made) == (ProjectState.OPEN, False, False)

    def test_the_timeline_carries_the_new_standing(
        self, container: ServiceContainer
    ) -> None:
        made = _make(container, name="Camp", autopilot=True)
        service = container.project_service()

        service.transition(ADA, made.id, TransitionKind.FINISHED)
        service.transition(ADA, made.id, TransitionKind.ARCHIVED)

        timeline = json.loads(container.view_service().timeline(made).text)
        assert {
            key: timeline["project"][key] for key in ("state", "archived", "autopilot")
        } == {"state": "finished", "archived": True, "autopilot": False}

    @pytest.mark.parametrize(
        ("spec", "kind", "cause"),
        [
            ({"state": "draft"}, TransitionKind.FINISHED, "it is a draft"),
            ({"state": "finished"}, TransitionKind.FINISHED, "it is finished already"),
            ({"state": "draft"}, TransitionKind.REOPENED, "it is not finished"),
            ({"state": "open"}, TransitionKind.REOPENED, "it is not finished"),
            ({"state": "open"}, TransitionKind.BROUGHT_BACK, "it is not archived"),
            ({"state": "draft"}, TransitionKind.AUTOPILOT_ON, "it is a draft"),
            ({"state": "finished"}, TransitionKind.AUTOPILOT_ON, "it is finished"),
            (
                {"state": "open", "autopilot": True},
                TransitionKind.AUTOPILOT_ON,
                "auto pilot is on already",
            ),
            (
                {"state": "open"},
                TransitionKind.AUTOPILOT_OFF,
                "auto pilot is off already",
            ),
            ({"archived": True}, TransitionKind.ARCHIVED, ARCHIVED_REFUSAL),
            ({"archived": True}, TransitionKind.FINISHED, ARCHIVED_REFUSAL),
            (
                {"state": "finished", "archived": True},
                TransitionKind.REOPENED,
                ARCHIVED_REFUSAL,
            ),
            ({"archived": True}, TransitionKind.AUTOPILOT_ON, ARCHIVED_REFUSAL),
            (
                {"autopilot": True, "archived": True},
                TransitionKind.AUTOPILOT_OFF,
                ARCHIVED_REFUSAL,
            ),
            ({"state": "draft"}, TransitionKind.PAUSED, "it is a draft"),
            ({"state": "finished"}, TransitionKind.PAUSED, "it is finished"),
            (
                {"state": "open", "paused": True},
                TransitionKind.PAUSED,
                "it is paused already",
            ),
            ({"state": "open"}, TransitionKind.RESUMED, "it is not paused"),
            ({"state": "finished"}, TransitionKind.RESUMED, "it is not paused"),
            ({"state": "draft"}, TransitionKind.RESUMED, "it is not paused"),
            ({"archived": True}, TransitionKind.PAUSED, ARCHIVED_REFUSAL),
            (
                {"paused": True, "archived": True},
                TransitionKind.RESUMED,
                ARCHIVED_REFUSAL,
            ),
        ],
    )
    def test_a_transition_its_standing_does_not_allow_is_refused(
        self,
        container: ServiceContainer,
        session: DbSession,
        spec: dict[str, Any],
        kind: TransitionKind,
        cause: str,
    ) -> None:
        made = _make(container, name="Camp", **spec)
        before = (_transitions(session, made), _standing(made))

        with pytest.raises(InvalidOperationException) as refused:
            container.project_service().transition(ADA, made.id, kind)

        assert refused.value.cause == cause
        assert (_transitions(session, made), _standing(made)) == before
        assert made.paused is spec.get("paused", False)

    @pytest.mark.parametrize(
        ("name", "kind", "message"),
        [
            (
                "Camp",
                TransitionKind.AUTOPILOT_ON,
                "Cannot turn auto pilot on for Camp because it is a draft",
            ),
            (
                None,
                TransitionKind.FINISHED,
                "Cannot finish the untitled project because it is a draft",
            ),
        ],
    )
    def test_a_refusal_names_the_change_and_the_project(
        self,
        container: ServiceContainer,
        name: str | None,
        kind: TransitionKind,
        message: str,
    ) -> None:
        made = _make(container, name=name, state="draft")

        with pytest.raises(InvalidOperationException) as refused:
            container.project_service().transition(ADA, made.id, kind)

        assert refused.value.message == message

    def test_a_caller_without_a_handle_is_refused(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        made = _make(container, name="Camp")
        before = _transitions(session, made)

        with pytest.raises(InvalidOperationException) as refused:
            container.project_service().transition(
                NEWCOMER, made.id, TransitionKind.FINISHED
            )

        assert refused.value.message == (
            "Cannot finish Camp because you have not chosen your handle yet"
        )
        assert (_transitions(session, made), made.state_code) == (
            before,
            ProjectState.OPEN,
        )

    def test_an_unknown_project_is_not_found(self, container: ServiceContainer) -> None:
        unknown = uuid.uuid4()

        with pytest.raises(RecordNotFoundException) as raised:
            container.project_service().transition(
                ADA, unknown, TransitionKind.FINISHED
            )

        assert raised.value.message == f"Project {unknown} was not found"

    @pytest.mark.parametrize("open_items", [0, 2])
    def test_a_transition_moves_the_timeline_once(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        environment: Environment,
        open_items: int,
    ) -> None:
        made = _make(
            container,
            name="Camp",
            autopilot=True,
            open_items=open_items,
            environment_id=environment.id,
        )
        with scoped_session(container):
            pass
        engine_events.clear()

        with scoped_session(container):
            container.project_service().transition(
                ADA, made.id, TransitionKind.FINISHED
            )

        assert engine_events == [
            TreeHashMoved(
                tree_path(made, TIMELINE),
                container.view_service().timeline(made).hash,
            ),
            ProjectChanged(made.id),
        ]

    @pytest.mark.parametrize(
        ("spec", "kind"),
        [
            ({"state": "open"}, TransitionKind.PAUSED),
            ({"state": "open", "paused": True}, TransitionKind.RESUMED),
        ],
    )
    def test_a_pause_and_a_resume_move_the_project_and_no_timeline(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        spec: dict[str, Any],
        kind: TransitionKind,
    ) -> None:
        """The pause is not in the store's tree (`timeline.json`)."""
        made = _make(container, name="Camp", **spec)
        with scoped_session(container):
            pass
        engine_events.clear()

        with scoped_session(container):
            container.project_service().transition(ADA, made.id, kind)

        assert engine_events == [ProjectChanged(made.id)]

    @pytest.mark.parametrize(
        ("spec", "kind"),
        [
            ({"state": "open"}, TransitionKind.PAUSED),
            ({"state": "open", "paused": True}, TransitionKind.RESUMED),
            ({"state": "open", "paused": True}, TransitionKind.FINISHED),
        ],
    )
    def test_a_pause_and_a_resume_move_the_held_work_items_reasons(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        engine_events: list[EngineEvent],
        spec: dict[str, Any],
        kind: TransitionKind,
    ) -> None:
        """Their lines read `held_reason`, the pause first (F26.1); a Chat's
        Session has no work item."""
        made = _make(container, name="Camp", **spec)
        held = _run(container, session, made, environment, SessionState.HELD)
        _run(container, session, made, environment, SessionState.HELD, "chat")
        _run(container, session, made, environment, SessionState.IDLE)
        with scoped_session(container):
            pass
        engine_events.clear()

        with scoped_session(container):
            container.project_service().transition(ADA, made.id, kind)

        assert [event for event in engine_events if isinstance(event, WorkMoved)] == [
            WorkMoved(made.id, held.id)
        ]

    @pytest.mark.parametrize(
        ("spec", "kind"),
        [
            ({"state": "open", "autopilot": True}, TransitionKind.AUTOPILOT_OFF),
            ({"state": "open"}, TransitionKind.ARCHIVED),
            ({"state": "open", "paused": True}, TransitionKind.ARCHIVED),
        ],
    )
    def test_a_change_that_keeps_the_pause_moves_no_held_work_item(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        engine_events: list[EngineEvent],
        spec: dict[str, Any],
        kind: TransitionKind,
    ) -> None:
        made = _make(container, name="Camp", **spec)
        _run(container, session, made, environment, SessionState.HELD)
        with scoped_session(container):
            pass
        engine_events.clear()

        with scoped_session(container):
            container.project_service().transition(ADA, made.id, kind)

        assert not [event for event in engine_events if isinstance(event, WorkMoved)]

    @pytest.mark.parametrize(
        ("spec", "kind"),
        [
            ({"state": "open"}, TransitionKind.ARCHIVED),
            ({"state": "draft", "archived": True}, TransitionKind.BROUGHT_BACK),
        ],
    )
    def test_archive_and_bring_back_announce_the_manifest_once_committed(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        spec: dict[str, Any],
        kind: TransitionKind,
    ) -> None:
        made = _make(container, name="Camp", **spec)
        with scoped_session(container):
            pass
        engine_events.clear()

        with scoped_session(container):
            container.project_service().transition(ADA, made.id, kind)
            assert engine_events == []

        assert engine_events == [
            TreeHashMoved(
                tree_path(made, TIMELINE),
                container.view_service().timeline(made).hash,
            ),
            ProjectChanged(made.id),
            ManifestChanged(),
        ]

    @pytest.mark.parametrize(
        ("spec", "kind"),
        [
            ({"state": "open"}, TransitionKind.FINISHED),
            ({"state": "finished"}, TransitionKind.REOPENED),
            ({"state": "open"}, TransitionKind.AUTOPILOT_ON),
            ({"state": "open", "autopilot": True}, TransitionKind.AUTOPILOT_OFF),
        ],
    )
    def test_no_other_transition_announces_the_manifest(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        spec: dict[str, Any],
        kind: TransitionKind,
    ) -> None:
        made = _make(container, name="Camp", **spec)
        with scoped_session(container):
            pass
        engine_events.clear()

        with scoped_session(container):
            container.project_service().transition(ADA, made.id, kind)

        assert ProjectChanged(made.id) in engine_events
        assert ManifestChanged() not in engine_events

    @pytest.mark.parametrize(
        ("spec", "kind"),
        [
            ({"archived": True}, TransitionKind.ARCHIVED),
            ({"state": "open"}, TransitionKind.BROUGHT_BACK),
        ],
    )
    def test_a_refused_archive_or_bring_back_announces_nothing(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        spec: dict[str, Any],
        kind: TransitionKind,
    ) -> None:
        made = _make(container, name="Camp", **spec)
        with scoped_session(container):
            pass
        engine_events.clear()

        with pytest.raises(InvalidOperationException), scoped_session(container):
            container.project_service().transition(ADA, made.id, kind)

        assert engine_events == []

    def test_a_rolled_back_archive_announces_nothing(
        self, container: ServiceContainer, engine_events: list[EngineEvent]
    ) -> None:
        made = _make(container, name="Camp")
        with scoped_session(container):
            pass
        engine_events.clear()

        with pytest.raises(RuntimeError), scoped_session(container):
            container.project_service().transition(
                ADA, made.id, TransitionKind.ARCHIVED
            )
            raise RuntimeError("the transaction fails after the archive")

        assert engine_events == []
        assert container.project_service().head(ADA, made.id).project.archived is False


@pytest.mark.usefixtures("person")
class TestJoin:
    @pytest.mark.parametrize("state", ["draft", "open", "finished"])
    def test_joining_opens_a_membership_now(
        self,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        state: str,
    ) -> None:
        _ben(container)
        made = _make(container, name="Camp", state=state, members=["ben"])
        started = datetime.now(UTC)

        container.project_service().join(ADA, made.id)

        (membership,) = _memberships(session, made, person)
        assert membership.left_at is None
        assert started <= membership.joined_at <= datetime.now(UTC)
        assert container.project_service().head(ADA, made.id).member is True

    def test_a_rejoin_is_a_new_row(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        made = _make(container, name="Camp")
        service = container.project_service()
        service.leave(ADA, made.id)

        service.join(ADA, made.id)

        first, again = _memberships(session, made, person)
        assert first.left_at is not None
        assert again.left_at is None
        assert again.joined_at >= first.left_at

    def test_a_member_cannot_join_again(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        made = _make(container, name="Camp")

        with pytest.raises(InvalidOperationException) as refused:
            container.project_service().join(ADA, made.id)

        assert refused.value.message == (
            "Cannot join Camp because you are a member already"
        )
        assert len(_memberships(session, made, person)) == 1

    def test_an_archived_project_is_refused(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        _ben(container)
        made = _make(container, name="Camp", members=["ben"], archived=True)

        with pytest.raises(InvalidOperationException) as refused:
            container.project_service().join(ADA, made.id)

        assert refused.value.cause == ARCHIVED_REFUSAL
        assert _memberships(session, made, person) == []

    def test_a_caller_without_a_handle_is_refused(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        made = _make(container, name="Camp")
        before = session.scalars(
            select(ProjectMember.id).where(ProjectMember.project_id == made.id)
        ).all()

        with pytest.raises(InvalidOperationException) as refused:
            container.project_service().join(NEWCOMER, made.id)

        assert refused.value.message == (
            "Cannot join Camp because you have not chosen your handle yet"
        )
        assert (
            session.scalars(
                select(ProjectMember.id).where(ProjectMember.project_id == made.id)
            ).all()
            == before
        )

    def test_an_unknown_project_is_not_found(self, container: ServiceContainer) -> None:
        unknown = uuid.uuid4()

        with pytest.raises(RecordNotFoundException):
            container.project_service().join(ADA, unknown)

    def test_membership_moves_the_projects_head_and_no_timeline(
        self, container: ServiceContainer, engine_events: list[EngineEvent]
    ) -> None:
        made = _make(container, name="Camp")
        with scoped_session(container):
            pass
        engine_events.clear()

        with scoped_session(container):
            container.project_service().leave(ADA, made.id)
        with scoped_session(container):
            container.project_service().join(ADA, made.id)

        # Other browsers read the head's members again; the timeline's file
        # did not move.
        assert engine_events == [ProjectChanged(made.id)] * 2


@pytest.mark.usefixtures("person")
class TestLeave:
    @pytest.mark.parametrize("state", ["draft", "open", "finished"])
    def test_leaving_closes_the_membership_now(
        self,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        state: str,
    ) -> None:
        made = _make(container, name="Camp", state=state)
        started = datetime.now(UTC)

        container.project_service().leave(ADA, made.id)

        (membership,) = _memberships(session, made, person)
        assert membership.left_at is not None
        assert started <= membership.left_at <= datetime.now(UTC)
        head = container.project_service().head(ADA, made.id)
        assert (head.member, head.members) == (False, ())

    def test_a_person_who_is_no_member_cannot_leave(
        self, container: ServiceContainer
    ) -> None:
        _ben(container)
        made = _make(container, name="Camp", members=["ben"])

        with pytest.raises(InvalidOperationException) as refused:
            container.project_service().leave(ADA, made.id)

        assert refused.value.message == "Cannot leave Camp because you are no member"

    def test_an_archived_project_is_refused(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        made = _make(container, name="Camp", archived=True)

        with pytest.raises(InvalidOperationException) as refused:
            container.project_service().leave(ADA, made.id)

        assert refused.value.cause == ARCHIVED_REFUSAL
        (membership,) = _memberships(session, made, person)
        assert membership.left_at is None

    def test_a_caller_without_a_handle_is_refused(
        self, container: ServiceContainer
    ) -> None:
        made = _make(container, name="Camp")

        with pytest.raises(InvalidOperationException) as refused:
            container.project_service().leave(NEWCOMER, made.id)

        assert refused.value.message == (
            "Cannot leave Camp because you have not chosen your handle yet"
        )

    def test_an_unknown_project_is_not_found(self, container: ServiceContainer) -> None:
        unknown = uuid.uuid4()

        with pytest.raises(RecordNotFoundException):
            container.project_service().leave(ADA, unknown)


class TestStandingRowLock:
    """Two changes of one project's standing never interleave."""

    def test_a_change_waits_for_the_projects_row(self, committed_app: Flask) -> None:
        container = committed_app.container
        with scoped_session(container) as session:
            session.add(
                User(
                    kind_code=UserKind.PERSON,
                    subject=ADA.subject,
                    handle="ada",
                    name="Ada Example",
                    avatar_slot=1,
                )
            )
            session.flush()
            project_id = _make(container, name="Camp").id
        with committed_app.app_context():
            engine = db.engine

        with engine.connect() as holder:
            holder.execute(
                sql("SELECT id FROM projects WHERE id = :id FOR NO KEY UPDATE"),
                {"id": project_id},
            )
            with (
                pytest.raises(OperationalError) as raised,
                scoped_session(container) as session,
            ):
                session.execute(sql("SET LOCAL lock_timeout = '200ms'"))
                container.project_service().transition(
                    ADA, project_id, TransitionKind.FINISHED
                )
            holder.rollback()

        assert isinstance(raised.value.orig, LockNotAvailable)
        with scoped_session(container) as session:
            assert session.get_one(Project, project_id).state_code is ProjectState.OPEN
