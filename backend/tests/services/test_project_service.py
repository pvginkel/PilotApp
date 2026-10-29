"""The projects as the signed-in person reads them, the project list's tabs
and a project's head, its status among them (F1, F2, F3, F141.1; DB 227,
228); a draft made from the plus (F46.1, F47.1); and what they change of a
project's standing, its transitions and their membership (F4.1, F5, F6, F127,
F128, F141.2; DB 170, 171)."""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from dependency_injector import providers
from flask import Flask
from psycopg.errors import LockNotAvailable
from sqlalchemy import func, select
from sqlalchemy import text as sql
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.engine.attachments import Copy
from app.engine.bus import (
    EngineEvent,
    ManifestChanged,
    ProjectChanged,
    TreeHashMoved,
    WorkMoved,
)
from app.engine.paths import TIMELINE, sha256_hex, tree_path
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.extensions import db
from app.models import (
    Attachment,
    Block,
    Chat,
    Document,
    Environment,
    Item,
    ItemAttachment,
    PlanNote,
    PlanTask,
    Project,
    ProjectMember,
    ProjectTransition,
    Turn,
    User,
    Work,
)
from app.models.reference import (
    AnswerChannel,
    AttachmentSource,
    ChatKind,
    CloseCause,
    DocumentRole,
    ProjectState,
    RecordKind,
    SessionState,
    TaskStatus,
    TransitionKind,
    UserKind,
    WorkTrigger,
)
from app.schemas.projects import ProjectStatus
from app.schemas.testing_record import InventedProjectCreateSchema
from app.services.auth_service import AuthContext
from app.services.chat_close_service import CLOSED
from app.services.container import ServiceContainer
from app.services.controller_outage import ControllerOutage
from app.services.job_service import SETUP_TITLE
from app.services.project_service import (
    ARCHIVED_REFUSAL,
    NO_SLUG_REFUSAL,
    NOTHING_DRAFTED_REFUSAL,
    WRITING_REFUSAL,
    Activity,
    PlanProgress,
    RunningWork,
    plan_progress,
    project_status,
)
from app.services.session_record_service import read_records
from app.services.session_scope import STORE_REPO
from app.services.session_start_service import SessionStartService
from app.services.supervisor import LoopHandle
from app.services.timeline_service import Badge
from app.utils import after_commit as after_commit_module
from tests.support.starts import configured_starts
from tests.support.supervisor import Supervise

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


def _questions(session: DbSession, project: Project) -> list[Item]:
    """The project's archive questions, in their order."""
    return list(
        session.scalars(
            select(Item)
            .where(Item.project_id == project.id, Item.kind_code == "archive_question")
            .order_by(Item.seq)
        )
    )


def _question(session: DbSession, project: Project) -> Document:
    """The project's one archive question's document."""
    (question,) = _questions(session, project)
    return session.get_one(Document, question.id)


def _published(document: Document) -> str:
    assert document.published_text is not None
    return document.published_text


def _answer(session: DbSession, question: Item) -> Block:
    return session.scalars(select(Block).where(Block.document_id == question.id)).one()


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
    item. One `held` or `starting` has its brief, unsent, as its start writes
    it."""
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
    if state in (SessionState.HELD, SessionState.STARTING):
        session.add(
            Turn(
                session_id=run.id,
                seq=1,
                message="Build the camp",
                started_at=datetime.now(UTC),
            )
        )
        run.turns = 1
        session.flush()
    if kind == "work":
        container.record_service().place_work(project, run, "Build the camp")
    return run


def _chat(
    container: ServiceContainer,
    session: DbSession,
    project: Project,
    environment: Environment,
    state: SessionState,
) -> models.Session:
    """The project's open chat in `state`; a `running` one with its turn in
    flight."""
    run = _run(container, session, project, environment, state, "chat")
    session.add(
        Chat(
            id=run.id,
            project_id=project.id,
            session_kind_code="chat",
            kind_code=ChatKind.PROJECT,
        )
    )
    if state is SessionState.RUNNING:
        session.add(
            Turn(
                session_id=run.id, seq=1, message="/chat", started_at=datetime.now(UTC)
            )
        )
        run.turns = 1
    session.flush()
    return run


def _last_record(session: DbSession, run: models.Session) -> tuple[RecordKind, Any]:
    (last,) = read_records(session, run.id, limit=1, newest_first=True)
    return last.record.kind_code, last.record.payload


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


def _confirmations(
    container: ServiceContainer,
    session: DbSession,
    run: models.Session,
    *becauses: str,
) -> list[Document]:
    """One confirmation item per reason in `becauses`, added by `run`."""
    project = session.get_one(Project, run.project_id)
    documents = container.document_service()
    return [
        session.get_one(
            Document,
            documents.bear_item(
                project,
                "decision",
                "Push the release",
                run,
                "---\ntitle: Push the release\n---\n\n```decision id=C1\n"
                f"type: confirmation\nbecause: {because}\n"
                "proposal: Push the release.\n```\n",
            ).id,
        )
        for because in becauses
    ]


def _answered(
    session: DbSession, document: Document
) -> tuple[str | None, uuid.UUID | None, AnswerChannel | None]:
    block = session.scalars(select(Block).where(Block.document_id == document.id)).one()
    return block.answer, block.answered_by_user_id, block.via_code


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

    def test_the_open_confirmations_the_switch_would_answer_are_counted(
        self, container: ServiceContainer, session: DbSession, environment: Environment
    ) -> None:
        made = _make(container, name="Camp")
        run = _run(container, session, made, environment, SessionState.RUNNING)
        _, rider, _ = _confirmations(
            container, session, run, "auto-pilot-off", "rider", "standing-grant"
        )
        _confirmations(container, session, run, "irreversible")
        service = container.project_service()
        assert service.head(ADA, made.id).autopilot_may_take == 2

        ada = session.scalars(select(User).where(User.handle == "ada")).one()
        container.record_service().answer(rider, "C1", ada, "No")

        assert service.head(ADA, made.id).autopilot_may_take == 1

    def test_the_running_work_is_named_and_the_other_open_items_counted(
        self, container: ServiceContainer, session: DbSession, environment: Environment
    ) -> None:
        """The Finish dialog's lines (F5.1): the sessions that stop, by their
        work items' titles, and the items that close unanswered without them."""
        made = _make(
            container, name="Busy", open_items=2, environment_id=environment.id
        )
        running = [
            _run(container, session, made, environment, state)
            for state in (
                SessionState.RUNNING,
                SessionState.STARTING,
                SessionState.HELD,
            )
        ]
        _run(container, session, made, environment, SessionState.STOPPED)
        _run(container, session, made, environment, SessionState.RUNNING, "chat")

        head = container.project_service().head(ADA, made.id)

        assert head.running_work == tuple(
            RunningWork(id=run.id, title="Build the camp") for run in running
        )
        # The stopped work item waits on you, and closes unanswered.
        assert head.open_items == 3

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
class TestCreate:
    def test_the_plus_makes_a_draft_its_creator_a_member_its_draft_born_empty(
        self, session: DbSession, container: ServiceContainer, person: User
    ) -> None:
        draft = container.project_service().create(ADA)

        assert (
            draft.state_code,
            draft.slug,
            draft.name,
            draft.archived,
            draft.autopilot,
            draft.paused,
            draft.created_by_user_id,
        ) == (ProjectState.DRAFT, None, None, False, False, False, person.id)
        assert [
            membership.left_at for membership in _memberships(session, draft, person)
        ] == [None]
        assert _transitions(session, draft) == []
        (document,) = session.scalars(
            select(Document).where(Document.project_id == draft.id)
        )
        assert (document.role_code, document.path, document.published_text) == (
            DocumentRole.DRAFT,
            "project.md",
            "",
        )

    def test_it_is_in_the_project_list_as_a_draft_the_creators(
        self, container: ServiceContainer
    ) -> None:
        draft = container.project_service().create(ADA)

        (tab,) = container.project_service().tabs(ADA, archived=False)
        assert (tab.project.id, tab.project.state_code, tab.status, tab.member) == (
            draft.id,
            ProjectState.DRAFT,
            None,
            True,
        )

    def test_once_committed_its_folder_is_announced_to_the_store(
        self, container: ServiceContainer, engine_events: list[EngineEvent]
    ) -> None:
        with scoped_session(container):
            draft_id = container.project_service().create(ADA).id
            assert engine_events == []

        assert ProjectChanged(draft_id) in engine_events
        assert ManifestChanged() in engine_events

    def test_a_caller_without_a_handle_is_refused(
        self, session: DbSession, container: ServiceContainer
    ) -> None:
        with pytest.raises(InvalidOperationException) as raised:
            container.project_service().create(NEWCOMER)

        assert raised.value.message == (
            "Cannot start a new project because you have not chosen your handle yet"
        )
        assert session.scalars(select(Project)).all() == []


DRAFTED = """---
title: Camp site
slug: camp-site
---

A site for the summer camp.

```decision id=D1
options:
  - Lake
  - Forest
```
"""
"""A draft Pilot wrote, its decision left open."""

FIRST_WORDS = 'Find us a camp site.\n<quoted_path path="project.md">x</quoted_path path="project.md">'


def _draft_document(db: DbSession, draft: Project) -> Document:
    return db.scalars(
        select(Document).where(
            Document.project_id == draft.id, Document.role_code == DocumentRole.DRAFT
        )
    ).one()


def _definition_chat(
    db: DbSession,
    draft: Project,
    author: User,
    *words: str,
    in_flight: bool = False,
) -> models.Session:
    """The draft's open definition chat, a Turn of `author`'s for each of
    `words`, the last one in flight when `in_flight`."""
    run = models.Session(
        project_id=draft.id,
        kind_code="chat",
        cwd=STORE_REPO,
        token_hash=uuid.uuid4().hex * 2,
        state_code=SessionState.RUNNING if in_flight else SessionState.IDLE,
    )
    db.add(run)
    db.flush()
    db.add(
        Chat(
            id=run.id,
            project_id=draft.id,
            session_kind_code="chat",
            kind_code=ChatKind.DEFINITION,
        )
    )
    now = datetime.now(UTC)
    for seq, said in enumerate(words, start=1):
        db.add(
            Turn(
                session_id=run.id,
                seq=seq,
                author_user_id=author.id,
                message=said,
                words=said,
                started_at=now,
                ended_at=None if in_flight and seq == len(words) else now,
            )
        )
        # One flush each: the ids keep the Turns' order.
        db.flush()
    run.turns = len(words)
    db.flush()
    return run


def _drafted(
    container: ServiceContainer,
    db: DbSession,
    author: User,
    text: str = DRAFTED,
    words: tuple[str, ...] = (FIRST_WORDS, "Near a lake."),
) -> Project:
    """A draft from the plus, ADA's, its definition chat holding `words` by
    `author`, `text` its draft as Pilot wrote it."""
    draft = container.project_service().create(ADA)
    _definition_chat(db, draft, author, *words)
    container.document_service().publish(_draft_document(db, draft), text)
    return draft


def _create(container: ServiceContainer, project_id: uuid.UUID) -> None:
    container.project_service().transition(ADA, project_id, TransitionKind.OPENED)


@pytest.fixture
def starts(
    container: ServiceContainer, supervise: Supervise
) -> Iterator[SessionStartService]:
    """The container's session start with a controller and the store
    configured, its loops never run: Create starts the setup through it."""
    starting = configured_starts(container, supervise)
    container.session_start_service.override(providers.Object(starting))
    try:
        yield starting
    finally:
        container.session_start_service.reset_last_overriding()


def _opening(db: DbSession, project: Project) -> Item:
    return db.scalars(
        select(Item).where(Item.project_id == project.id, Item.kind_code == "opening")
    ).one()


def _hung_on(db: DbSession, item: Item) -> list[tuple[int, int, str, AttachmentSource]]:
    """The item's attachments in order: position, batch, file name, source."""
    return [
        (position, batch, filename, source)
        for position, batch, filename, source in db.execute(
            select(
                ItemAttachment.position,
                Attachment.batch,
                Attachment.filename,
                Attachment.source_code,
            )
            .join(Attachment, Attachment.id == ItemAttachment.attachment_id)
            .where(ItemAttachment.item_id == item.id)
            .order_by(ItemAttachment.position)
        )
    ]


def _material(
    container: ServiceContainer,
    run: models.Session,
    environment: Environment,
    *filenames: str,
) -> None:
    """Files Pilot attached in the definition chat, one batch, on nothing."""
    container.attach_service().attach(
        None,
        run,
        [
            Copy("A file", name, "text/markdown", b"A", f"/work/Notes/{name}")
            for name in filenames
        ],
        environment_id=environment.id,
    )


@pytest.mark.usefixtures("person", "starts")
class TestCreateProject:
    """Create project (F48): the draft opened, the handbook and the opening
    born, the material hung on it, the definition chat closed."""

    def test_it_opens_the_draft_by_its_person_its_slug_the_drafts(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        draft = _drafted(container, session, person)
        started = datetime.now(UTC)

        _create(container, draft.id)

        ((kind, at, by),) = _transitions(session, draft)
        assert (kind, by) == (TransitionKind.OPENED, person.id)
        assert started <= at <= datetime.now(UTC)
        assert (draft.state_code, draft.slug, draft.name) == (
            ProjectState.OPEN,
            "camp-site",
            "Camp site",
        )

    def test_the_handbook_is_born_empty_beside_the_draft(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        draft = _drafted(container, session, person)

        _create(container, draft.id)

        assert [
            (document.role_code, document.path, document.published_text)
            for document in session.scalars(
                select(Document)
                .where(Document.project_id == draft.id)
                .order_by(Document.path)
            )
        ] == [
            (DocumentRole.HANDBOOK, "handbook.md", ""),
            (DocumentRole.DRAFT, "project.md", DRAFTED),
        ]

    def test_the_opening_is_the_first_message_verbatim_by_its_author(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        ben = _ben(container)
        draft = _drafted(container, session, ben)

        _create(container, draft.id)

        opening = _opening(session, draft)
        assert (
            opening.seq,
            opening.title,
            opening.created_by_user_id,
            opening.created_by_session_id,
        ) == (1, "Ben Example started this project", ben.id, None)
        assert session.get_one(Document, opening.id).published_text == FIRST_WORDS

    def test_the_first_message_of_its_first_definition_chat_is_the_opening(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        """A draft archived and brought back has a definition chat of each
        (F130.2); the first message is the first one's."""
        draft = _drafted(container, session, person, words=(FIRST_WORDS,))
        container.project_service().transition(ADA, draft.id, TransitionKind.ARCHIVED)
        container.project_service().transition(
            ADA, draft.id, TransitionKind.BROUGHT_BACK
        )
        _definition_chat(session, draft, _ben(container), "Somewhere else.")

        _create(container, draft.id)

        opening = _opening(session, draft)
        assert opening.created_by_user_id == person.id
        assert session.get_one(Document, opening.id).published_text == FIRST_WORDS

    def test_the_drafts_copy_then_its_material_hang_on_the_opening(
        self,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        environment: Environment,
    ) -> None:
        draft = container.project_service().create(ADA)
        run = _definition_chat(session, draft, person, FIRST_WORDS)
        _material(container, run, environment, "b.md", "a.md")
        _material(container, run, environment, "c.md")
        container.document_service().publish(_draft_document(session, draft), DRAFTED)

        _create(container, draft.id)

        opening = _opening(session, draft)
        assert _hung_on(session, opening) == [
            (1, 3, "project.md", AttachmentSource.DRAFT),
            (2, 1, "a.md", AttachmentSource.FILE),
            (3, 1, "b.md", AttachmentSource.FILE),
            (4, 2, "c.md", AttachmentSource.FILE),
        ]
        copy = session.scalars(
            select(Attachment).where(
                Attachment.project_id == draft.id,
                Attachment.source_code == AttachmentSource.DRAFT,
            )
        ).one()
        assert (copy.title, copy.content_type, copy.size) == (
            "Camp site",
            "text/markdown",
            len(DRAFTED.encode()),
        )
        assert container.attachment_store().get(copy) == DRAFTED.encode()
        assert container.timeline_service().timeline(draft.id).unhung_attachments == []

    def test_the_definition_chat_closes_created_its_close_its_last_record(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        draft = _drafted(container, session, person)
        (chat,) = session.scalars(select(Chat).where(Chat.project_id == draft.id))

        _create(container, draft.id)

        session.refresh(chat)
        ((_, at, _),) = _transitions(session, draft)
        assert (chat.close_cause_code, chat.closed_at) == (CloseCause.CREATED, at)
        assert _last_record(session, session.get_one(models.Session, chat.id)) == (
            RecordKind.SERVER,
            {"type": CLOSED, "cause": "created"},
        )

    def test_an_ask_the_draft_leaves_open_stays_open(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        draft = _drafted(container, session, person)

        _create(container, draft.id)

        (block,) = session.scalars(
            select(Block).where(Block.document_id == _draft_document(session, draft).id)
        )
        assert (block.local_id, block.answer, block.answered_by_user_id) == (
            "D1",
            None,
            None,
        )

    def test_once_committed_its_folder_is_the_slugs(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        person: User,
    ) -> None:
        with scoped_session(container) as db:
            draft = _drafted(container, db, person)
            draft_id, folder = draft.id, f"draft-{draft.number}"
        engine_events.clear()

        with scoped_session(container):
            _create(container, draft_id)
            assert engine_events == []

        assert ManifestChanged() in engine_events
        assert ProjectChanged(draft_id) in engine_events
        with scoped_session(container):
            paths = [entry.path for entry in container.tree_service().manifest()]
        assert "camp-site/project.md" in paths
        assert "camp-site/handbook.md" in paths
        assert not any(path.startswith(f"{folder}/") for path in paths)


def _setup(db: DbSession, project: Project) -> Item:
    return db.scalars(
        select(Item).where(Item.project_id == project.id, Item.kind_code == "work")
    ).one()


@pytest.mark.usefixtures("person")
class TestCreateProjectSetup:
    """Create places the setup, Pilot's first background job (F49, F59)."""

    @pytest.mark.usefixtures("starts")
    def test_it_places_the_setup_after_the_opening_a_job_of_pilots(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        draft = _drafted(container, session, person)

        _create(container, draft.id)

        setup = _setup(session, draft)
        assert (
            setup.seq,
            setup.title,
            setup.created_by_session_id,
            setup.created_by_user_id,
            setup.done_at,
        ) == (2, SETUP_TITLE, setup.id, None, None)
        work = session.get_one(models.Work, setup.id)
        assert (
            work.session_kind_code,
            work.trigger_code,
            work.trigger_item_id,
            work.repo,
            work.autopilot,
        ) == ("job", WorkTrigger.SETUP, None, None, False)
        job = session.get_one(models.Session, setup.id)
        assert (
            job.kind_code,
            job.cwd,
            job.model,
            job.reasoning_effort,
            job.environment_id,
            job.state_code,
            job.turns,
        ) == ("job", STORE_REPO, "opus", "xhigh", None, SessionState.STARTING, 1)

    @pytest.mark.usefixtures("starts")
    def test_its_brief_is_the_setups_at_creates_instant(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        draft = _drafted(container, session, person)

        _create(container, draft.id)

        ((_, at, _),) = _transitions(session, draft)
        (turn,) = session.scalars(
            select(Turn).where(Turn.session_id == _setup(session, draft).id)
        )
        assert (turn.seq, turn.author_user_id, turn.words, turn.started_at) == (
            1,
            None,
            None,
            at,
        )
        setup = _setup(session, draft)
        assert turn.message == container.brief_service().job(
            draft, session.get_one(Work, setup.id), at, at
        )
        assert f"the opening item {_opening(session, draft).id} holds" in turn.message
        assert turn.message.startswith("/plan\n")

    @pytest.mark.usefixtures("starts")
    def test_its_start_runs_once_create_commits(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        draft = _drafted(container, session, person)

        _create(container, draft.id)

        assert "_LoopStart" in {
            type(c).__name__ for c in after_commit_module._callbacks.get()
        }

    @pytest.mark.usefixtures("starts")
    def test_while_the_controller_is_unreachable_it_is_held(
        self,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        controller_outage: ControllerOutage,
    ) -> None:
        draft = _drafted(container, session, person)
        controller_outage.call_unanswered()

        _create(container, draft.id)

        job = session.get_one(models.Session, _setup(session, draft).id)
        assert job.state_code is SessionState.HELD
        assert draft.state_code is ProjectState.OPEN

    def test_with_no_controller_configured_create_is_refused(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        draft = _drafted(container, session, person)

        with pytest.raises(InvalidOperationException) as raised:
            _create(container, draft.id)

        assert raised.value.message == (
            "Cannot create Camp site because no controller is configured"
        )


@pytest.mark.usefixtures("person")
class TestCreateProjectRefused:
    """Refused for F48.1's three reasons and its standing alone; the head says
    why (F48.1)."""

    @staticmethod
    def _refused(
        container: ServiceContainer, session: DbSession, draft: Project, reason: str
    ) -> None:
        with pytest.raises(InvalidOperationException) as raised:
            _create(container, draft.id)

        assert raised.value.message == (
            f"Cannot create {draft.name or 'the untitled project'} because {reason}"
        )
        session.refresh(draft)
        assert container.project_service().head(ADA, draft.id).create_refusal == (
            reason
        )
        assert draft.state_code is ProjectState.DRAFT
        assert TransitionKind.OPENED not in [
            kind for kind, _, _ in _transitions(session, draft)
        ]

    def test_while_pilot_writes(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        draft = container.project_service().create(ADA)
        container.document_service().publish(_draft_document(session, draft), DRAFTED)
        _definition_chat(session, draft, person, FIRST_WORDS, "More.", in_flight=True)

        self._refused(container, session, draft, WRITING_REFUSAL)

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("", id="empty"),
            pytest.param("---\nslug: camp-site\n---\n", id="front-matter-alone"),
        ],
    )
    def test_while_nothing_is_drafted(
        self, container: ServiceContainer, session: DbSession, person: User, text: str
    ) -> None:
        draft = _drafted(container, session, person, text)

        self._refused(container, session, draft, NOTHING_DRAFTED_REFUSAL)

    def test_while_no_message_started_its_definition_chat(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        """Only a save from outside a chat writes such a draft."""
        draft = container.project_service().create(ADA)
        container.document_service().publish(_draft_document(session, draft), DRAFTED)

        self._refused(container, session, draft, NOTHING_DRAFTED_REFUSAL)

    def test_while_the_draft_names_no_slug(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        draft = _drafted(container, session, person, "# Camp site\n")

        self._refused(container, session, draft, NO_SLUG_REFUSAL)

    @pytest.mark.parametrize(
        ("slug", "problem"),
        [
            ("camp-site", "is taken by another project"),
            ("Camp", "is not lower-case letters, digits and hyphens"),
            ("draft-2", "starts with `draft-`"),
        ],
    )
    def test_while_its_slug_is_no_valid_one(
        self,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        slug: str,
        problem: str,
    ) -> None:
        """A slug the record refuses reaches the draft only past its save's
        check (`bear_draft`, a project's Create since that save)."""
        taken = _make(container, name="Other")
        taken.slug = "camp-site"
        session.flush()
        draft = _drafted(
            container, session, person, f"---\nslug: {slug}\n---\n# Camp\n"
        )

        self._refused(container, session, draft, f"the draft's slug `{slug}` {problem}")

    def test_an_archived_draft(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        draft = _drafted(container, session, person)
        container.project_service().transition(ADA, draft.id, TransitionKind.ARCHIVED)

        self._refused(container, session, draft, ARCHIVED_REFUSAL)

    def test_an_open_project(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        made = _make(container, name="Camp")

        with pytest.raises(InvalidOperationException) as raised:
            _create(container, made.id)

        assert raised.value.message == "Cannot create Camp because it is no draft"
        assert container.project_service().head(ADA, made.id).create_refusal == (
            "it is no draft"
        )

    def test_a_draft_it_can_create_has_no_refusal(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        draft = _drafted(container, session, person)

        assert container.project_service().head(ADA, draft.id).create_refusal is None


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

    def test_auto_pilot_on_with_the_yes_answers_what_the_switch_takes_as_its_persons(
        self,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        environment: Environment,
    ) -> None:
        made = _make(container, name="Camp")
        run = _run(container, session, made, environment, SessionState.RUNNING)
        off, rider, kept = _confirmations(
            container, session, run, "auto-pilot-off", "rider", "standing-grant"
        )
        before = _transitions(session, made)
        service = container.project_service()

        service.transition(
            ADA, made.id, TransitionKind.AUTOPILOT_ON, autopilot_yes=True
        )

        ((written, _, by),) = _transitions(session, made)[len(before) :]
        assert (written, by) == (TransitionKind.AUTOPILOT_ON, person.id)
        assert made.autopilot
        yes = ("Yes", person.id, AnswerChannel.AUTOPILOT)
        assert [_answered(session, each) for each in (off, rider, kept)] == [
            yes,
            yes,
            (None, None, None),
        ]
        assert service.head(ADA, made.id).autopilot_may_take == 0

    def test_auto_pilot_on_without_the_yes_answers_nothing_and_asks_again(
        self,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        environment: Environment,
    ) -> None:
        made = _make(container, name="Camp")
        run = _run(container, session, made, environment, SessionState.RUNNING)
        (off,) = _confirmations(container, session, run, "auto-pilot-off")
        service = container.project_service()

        service.transition(ADA, made.id, TransitionKind.AUTOPILOT_ON)

        assert made.autopilot
        assert _answered(session, off) == (None, None, None)
        assert service.head(ADA, made.id).autopilot_may_take == 1

        service.transition(ADA, made.id, TransitionKind.AUTOPILOT_OFF)
        service.transition(
            ADA, made.id, TransitionKind.AUTOPILOT_ON, autopilot_yes=True
        )

        assert _answered(session, off) == ("Yes", person.id, AnswerChannel.AUTOPILOT)

    @pytest.mark.usefixtures("starts")
    def test_the_yes_to_an_item_of_pilots_own_places_the_job_after_it(
        self,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        environment: Environment,
    ) -> None:
        made = _make(container, name="Camp")
        brain = _run(container, session, made, environment, SessionState.IDLE, "chat")
        (off,) = _confirmations(container, session, brain, "auto-pilot-off")

        container.project_service().transition(
            ADA, made.id, TransitionKind.AUTOPILOT_ON, autopilot_yes=True
        )

        (job,) = session.scalars(
            select(Work).where(
                Work.trigger_code == WorkTrigger.ITEM_DONE,
                Work.trigger_item_id == off.id,
            )
        )
        assert job.session_kind_code == "job"
        item = session.get_one(Item, off.id)
        assert (item.done_cause_code, item.done_by_user_id) == ("answered", person.id)

    def test_transition_as_is_the_users_finish_as_the_callers_is(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        made = _make(
            container,
            name="Camp",
            autopilot=True,
            open_items=1,
            environment_id=environment.id,
        )
        pilot = session.scalars(select(User).where(User.handle == "agent")).one()
        before = _transitions(session, made)

        container.project_service().transition_as(
            pilot, made.id, TransitionKind.FINISHED
        )

        finished, autopilot_off = _transitions(session, made)[len(before) :]
        assert (finished[0], finished[2]) == (TransitionKind.FINISHED, pilot.id)
        assert autopilot_off == (TransitionKind.AUTOPILOT_OFF, *finished[1:])
        assert _standing(made) == (ProjectState.FINISHED, False, False)
        [notice] = session.scalars(
            select(Item).where(Item.project_id == made.id, Item.kind_code == "notice")
        )
        assert (notice.done_cause_code, notice.done_by_user_id) == (
            "finished",
            pilot.id,
        )

    def test_transition_as_is_refused_as_the_callers_is(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        made = _make(container, name="Camp", state="finished")
        pilot = session.scalars(select(User).where(User.handle == "agent")).one()

        with pytest.raises(InvalidOperationException) as refused:
            container.project_service().transition_as(
                pilot, made.id, TransitionKind.FINISHED
            )

        assert refused.value.message == (
            "Cannot finish Camp because it is finished already"
        )

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
            select(Item).where(
                Item.project_id == made.id,
                Item.kind_code.not_in(["opening", "archive_question"]),
            )
        )
        assert [
            (item.done_at, item.done_cause_code, item.done_by_user_id) for item in items
        ] == [(at, "finished", person.id)] * 2
        assert service.head(ADA, made.id).open_items == 1

    @pytest.mark.parametrize("kind", [TransitionKind.FINISHED, TransitionKind.ARCHIVED])
    def test_finish_and_archive_stop_every_running_starting_or_held_session(
        self,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        environment: Environment,
        kind: TransitionKind,
    ) -> None:
        made = _make(container, name="Camp")
        stopping = [
            _run(container, session, made, environment, state)
            for state in (
                SessionState.RUNNING,
                SessionState.STARTING,
                SessionState.HELD,
            )
        ]
        stopping.append(
            _run(container, session, made, environment, SessionState.RUNNING, "chat")
        )
        idle = _run(container, session, made, environment, SessionState.IDLE)

        container.project_service().transition(ADA, made.id, kind)

        ((_, at, _),) = [
            transition
            for transition in _transitions(session, made)
            if transition[0] is kind
        ]
        assert [
            (run.state_code, run.stopped_at, run.stopped_by_user_id) for run in stopping
        ] == [(SessionState.STOPPED, at, person.id)] * 4
        assert idle.state_code is SessionState.IDLE

    def test_finish_closes_the_open_chat_finished_its_close_its_last_record(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        made = _make(container, name="Camp")
        chat = _chat(container, session, made, environment, SessionState.IDLE)

        container.project_service().transition(ADA, made.id, TransitionKind.FINISHED)

        ((_, at, _),) = [
            transition
            for transition in _transitions(session, made)
            if transition[0] is TransitionKind.FINISHED
        ]
        row = session.get_one(Chat, chat.id, populate_existing=True)
        assert (row.closed_at, row.close_cause_code) == (at, CloseCause.FINISHED)
        assert chat.state_code is SessionState.IDLE
        assert _last_record(session, chat) == (
            RecordKind.SERVER,
            {"type": CLOSED, "cause": "finished"},
        )

    def test_finish_closes_a_running_chat_it_stops_leaving_its_close_to_the_turns_end(
        self,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        environment: Environment,
    ) -> None:
        made = _make(container, name="Camp")
        chat = _chat(container, session, made, environment, SessionState.RUNNING)

        container.project_service().transition(ADA, made.id, TransitionKind.FINISHED)

        row = session.get_one(Chat, chat.id, populate_existing=True)
        assert row.close_cause_code is CloseCause.FINISHED
        assert (chat.state_code, chat.stopped_by_user_id) == (
            SessionState.STOPPED,
            person.id,
        )
        assert read_records(session, chat.id, limit=10) == []
        assert {type(c).__name__ for c in after_commit_module._callbacks.get()} >= {
            "_InterruptStart"
        }

    @pytest.mark.parametrize("state", [SessionState.RUNNING, SessionState.HELD])
    def test_reopen_stops_the_finished_projects_chat_and_closes_it_reopened(
        self,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        environment: Environment,
        state: SessionState,
    ) -> None:
        made = _make(container, name="Camp", state="finished")
        chat = _chat(container, session, made, environment, state)

        container.project_service().transition(ADA, made.id, TransitionKind.REOPENED)

        ((_, at, _),) = [
            transition
            for transition in _transitions(session, made)
            if transition[0] is TransitionKind.REOPENED
        ]
        row = session.get_one(Chat, chat.id, populate_existing=True)
        assert (row.closed_at, row.close_cause_code) == (at, CloseCause.REOPENED)
        assert (chat.state_code, chat.stopped_at, chat.stopped_by_user_id) == (
            SessionState.STOPPED,
            at,
            person.id,
        )
        # A held start's turn ends at the stop, so the close stands now; a
        # running one's end writes it after the interrupt's records.
        closed = (RecordKind.SERVER, {"type": CLOSED, "cause": "reopened"})
        if state is SessionState.HELD:
            assert _last_record(session, chat) == closed
        else:
            assert read_records(session, chat.id, limit=10) == []

    @pytest.mark.parametrize("state", [SessionState.IDLE, SessionState.RUNNING])
    def test_archive_closes_the_open_chat_archived_after_stopping_it(
        self,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        environment: Environment,
        state: SessionState,
    ) -> None:
        """An idle chat's close is its last record now; a running one's turn
        is stopped, its close's record left to the turn's end (F128.1; DB
        decision 60, assertion 245)."""
        made = _make(container, name="Camp")
        chat = _chat(container, session, made, environment, state)

        container.project_service().transition(ADA, made.id, TransitionKind.ARCHIVED)

        ((_, at, _),) = [
            transition
            for transition in _transitions(session, made)
            if transition[0] is TransitionKind.ARCHIVED
        ]
        row = session.get_one(Chat, chat.id, populate_existing=True)
        assert (row.closed_at, row.close_cause_code) == (at, CloseCause.ARCHIVED)
        if state is SessionState.IDLE:
            assert chat.state_code is SessionState.IDLE
            assert _last_record(session, chat) == (
                RecordKind.SERVER,
                {"type": CLOSED, "cause": "archived"},
            )
        else:
            assert (chat.state_code, chat.stopped_by_user_id) == (
                SessionState.STOPPED,
                person.id,
            )
            assert read_records(session, chat.id, limit=10) == []

    @pytest.mark.parametrize(
        ("spec", "kind"),
        [
            ({"state": "open"}, TransitionKind.PAUSED),
            ({"state": "open"}, TransitionKind.AUTOPILOT_ON),
            ({"state": "open", "archived": True}, TransitionKind.BROUGHT_BACK),
        ],
    )
    def test_no_other_transition_closes_the_chat(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
        spec: dict[str, Any],
        kind: TransitionKind,
    ) -> None:
        made = _make(container, name="Camp", **spec)
        chat = _chat(container, session, made, environment, SessionState.IDLE)

        container.project_service().transition(ADA, made.id, kind)

        assert session.get_one(Chat, chat.id, populate_existing=True).closed_at is None
        assert read_records(session, chat.id, limit=10) == []

    def test_finishs_resume_opens_no_held_start_of_the_finished_project(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        made = _make(container, name="Camp", paused=True)
        held = _run(container, session, made, environment, SessionState.HELD)

        container.project_service().transition(ADA, made.id, TransitionKind.FINISHED)
        container.session_start_service().release(LoopHandle("start:held"))

        assert held.state_code is SessionState.STOPPED
        assert made.paused is False

    def test_finish_closes_the_stopped_work_items_with_the_other_open_items(
        self,
        container: ServiceContainer,
        session: DbSession,
        person: User,
        environment: Environment,
    ) -> None:
        made = _make(
            container, name="Camp", open_items=1, environment_id=environment.id
        )
        run = _run(container, session, made, environment, SessionState.RUNNING)

        container.project_service().transition(ADA, made.id, TransitionKind.FINISHED)

        item = session.get_one(Item, run.id)
        assert (item.done_cause_code, item.done_by_user_id) == ("finished", person.id)
        assert item.done_at == run.stopped_at

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
    def test_a_finish_moves_its_question_and_the_timeline_to_its_last_hash(
        self,
        container: ServiceContainer,
        session: DbSession,
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

        question = _question(session, made)
        timeline = tree_path(made, TIMELINE)
        moves = [event for event in engine_events if isinstance(event, TreeHashMoved)]
        assert moves[-1] == TreeHashMoved(
            timeline, container.view_service().timeline(made).hash
        )
        assert (
            TreeHashMoved(
                tree_path(made, question.path), sha256_hex(_published(question))
            )
            in moves
        )
        assert {move.path for move in moves} == {
            timeline,
            tree_path(made, question.path),
        }
        assert [
            event for event in engine_events if not isinstance(event, TreeHashMoved)
        ] == [ProjectChanged(made.id)]

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
            ({"state": "open", "paused": True}, TransitionKind.AUTOPILOT_ON),
            (
                {"state": "open", "paused": True, "archived": True},
                TransitionKind.BROUGHT_BACK,
            ),
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
class TestArchiveQuestion:
    """After any finish, one question of the server's, "Archive the
    project?", the finished project's one open item: Archive archives the
    project, Keep keeps it finished; the menu's Archive and Reopen close it
    while it is open (F5.6; DB 263 to 265)."""

    def test_finish_puts_it_after_closing_the_open_items(
        self,
        container: ServiceContainer,
        session: DbSession,
        environment: Environment,
    ) -> None:
        made = _make(
            container, name="Camp", open_items=2, environment_id=environment.id
        )
        service = container.project_service()
        pilot = session.scalars(select(User).where(User.handle == "agent")).one()

        service.transition(ADA, made.id, TransitionKind.FINISHED)

        (question,) = _questions(session, made)
        last = session.scalars(
            select(func.max(Item.seq)).where(Item.project_id == made.id)
        ).one()
        assert (question.seq, question.title, question.done_at) == (
            last,
            "Archive the project?",
            None,
        )
        assert (question.created_by_user_id, question.created_by_session_id) == (
            pilot.id,
            None,
        )
        open_items = session.scalars(
            select(Item.id).where(
                Item.project_id == made.id,
                Item.done_at.is_(None),
                Item.kind_code != "opening",
            )
        ).all()
        assert open_items == [question.id]
        assert service.head(ADA, made.id).open_items == 1

    def test_pilots_finish_puts_it_too(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        made = _make(container, name="Camp")
        pilot = session.scalars(select(User).where(User.handle == "agent")).one()

        container.project_service().transition_as(
            pilot, made.id, TransitionKind.FINISHED
        )

        (question,) = _questions(session, made)
        assert (question.done_at, question.created_by_user_id) == (None, pilot.id)

    def test_the_badge_counts_it_for_the_members(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        made = _make(container, name="Camp")
        service = container.project_service()

        service.transition(ADA, made.id, TransitionKind.FINISHED)

        (tab,) = service.tabs(ADA, archived=False)
        assert tab.badge == Badge(1, False)

    def test_reopen_closes_it_as_its_keep_by_the_caller_with_no_undo(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        made = _make(container, name="Camp")
        service = container.project_service()
        service.transition(ADA, made.id, TransitionKind.FINISHED)
        (question,) = _questions(session, made)

        service.transition(ADA, made.id, TransitionKind.REOPENED)

        assert (question.done_cause_code, question.done_by_user_id) == (
            "answered",
            person.id,
        )
        assert _answer(session, question).answer == "Keep"
        assert _standing(made) == (ProjectState.OPEN, False, False)
        assert container.record_service().offers_undo(question) is False

    def test_the_menus_archive_closes_it_as_its_archive_by_the_caller(
        self, container: ServiceContainer, session: DbSession, person: User
    ) -> None:
        made = _make(container, name="Camp")
        service = container.project_service()
        service.transition(ADA, made.id, TransitionKind.FINISHED)
        (question,) = _questions(session, made)

        service.transition(ADA, made.id, TransitionKind.ARCHIVED)

        assert (question.done_cause_code, question.done_by_user_id) == (
            "answered",
            person.id,
        )
        assert _answer(session, question).answer == "Archive"
        assert _standing(made) == (ProjectState.FINISHED, True, False)

    def test_bring_back_puts_none_and_a_second_finish_another(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        made = _make(container, name="Camp")
        service = container.project_service()
        service.transition(ADA, made.id, TransitionKind.FINISHED)
        service.transition(ADA, made.id, TransitionKind.ARCHIVED)

        service.transition(ADA, made.id, TransitionKind.BROUGHT_BACK)

        (archived,) = _questions(session, made)
        assert archived.done_at is not None
        service.transition(ADA, made.id, TransitionKind.REOPENED)
        service.transition(ADA, made.id, TransitionKind.FINISHED)
        first, second = _questions(session, made)
        assert (first.id, first.done_cause_code) == (archived.id, "answered")
        assert second.done_at is None

    @pytest.mark.parametrize("state", ["draft", "open", "finished"])
    def test_an_archive_without_a_finish_puts_none(
        self, container: ServiceContainer, session: DbSession, state: str
    ) -> None:
        made = _make(container, name="Camp", state=state)

        container.project_service().transition(ADA, made.id, TransitionKind.ARCHIVED)

        assert _questions(session, made) == []
        assert made.archived is True


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

    @pytest.mark.parametrize(
        ("before", "kind", "done_cause"),
        [
            ([], TransitionKind.FINISHED, None),
            ([TransitionKind.FINISHED], TransitionKind.ARCHIVED, "answered"),
            ([TransitionKind.FINISHED], TransitionKind.REOPENED, "answered"),
        ],
    )
    def test_the_archive_questions_birth_and_close_keep_the_row_shared(
        self,
        committed_app: Flask,
        before: list[TransitionKind],
        kind: TransitionKind,
        done_cause: str | None,
    ) -> None:
        """Finish bears the question and Archive and Reopen close it while
        they hold the project's sessions, so none upgrades its shared hold on
        the row: a key-share holder, as an insert naming the project is,
        keeps none waiting."""
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
        for earlier in before:
            with scoped_session(container):
                container.project_service().transition(ADA, project_id, earlier)
        with committed_app.app_context():
            engine = db.engine

        with engine.connect() as holder:
            holder.execute(
                sql("SELECT id FROM projects WHERE id = :id FOR KEY SHARE"),
                {"id": project_id},
            )
            with scoped_session(container) as session:
                session.execute(sql("SET LOCAL lock_timeout = '200ms'"))
                container.project_service().transition(ADA, project_id, kind)
            holder.rollback()

        with scoped_session(container) as session:
            (question,) = _questions(session, session.get_one(Project, project_id))
            assert question.done_cause_code == done_cause
