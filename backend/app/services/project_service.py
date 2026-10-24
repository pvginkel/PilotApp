"""The projects as the signed-in person reads them, the project list's tabs
and a project's head, its status among them (F1, F2, F3, F141.1); and what
they change of a project's standing, its transitions and their membership
(F4.1, F5, F6, F127, F128, F141.2)."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine.bus import EngineBus, ManifestChanged, ProjectChanged
from app.engine.documents import OPENING
from app.engine.record import RecordService
from app.engine.views import ViewService
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import (
    Item,
    ItemKind,
    PlanNote,
    PlanTask,
    Project,
    ProjectMember,
    ProjectTransition,
    User,
    Work,
)
from app.models import Session as AgentSession
from app.models.reference import (
    ProjectState,
    SessionState,
    TaskStatus,
    TransitionKind,
)
from app.schemas.projects import ProjectStatus
from app.services.auth_service import AuthContext
from app.services.people_service import PeopleService
from app.services.session_start_service import SessionStartService
from app.services.timeline_service import (
    WAIT,
    Badge,
    TimelineService,
    waiting_on_a_member,
)
from app.services.work_status import work_moved
from app.utils.after_commit import after_commit


@dataclass(frozen=True)
class PlanProgress:
    """The steps done and in progress, of the steps in the plan."""

    done: int
    total: int
    in_progress: tuple[str, ...]


@dataclass(frozen=True)
class ProjectTab:
    project: Project
    finished_at: datetime | None
    status: ProjectStatus | None
    member: bool
    progress: PlanProgress
    badge: Badge


@dataclass(frozen=True)
class PlanStep:
    task: PlanTask
    notes: tuple[PlanNote, ...]


@dataclass(frozen=True)
class ProjectHead:
    project: Project
    status: ProjectStatus | None
    member: bool
    members: tuple[User, ...]
    progress: PlanProgress
    steps: tuple[PlanStep, ...]
    notes: tuple[PlanNote, ...]
    open_items: int


@dataclass(frozen=True)
class Activity:
    """What of a project runs and waits, as its status reads it (DB 228)."""

    running: bool
    """A Session of the project is `running`, a Chat's included."""
    work_running: bool
    """A Work of the project is `running`: a work item or a job."""
    waiting: bool
    """An open Item waits on a member, F94.5's set (225)."""
    wait_open: bool
    """A Wait of the project is open."""


_QUIET = Activity(running=False, work_running=False, waiting=False, wait_open=False)


def project_status(
    project: Project, activity: Activity, progress: PlanProgress
) -> ProjectStatus | None:
    """The project's status (DB 228): paused, or pausing while a Session of
    it is `running`; then running, waiting on you, waiting on an event, done
    while every step of a plan is done, idle; none for a draft and a finished
    project (227). A plan with no step is not done."""
    if project.state_code is not ProjectState.OPEN:
        return None
    if project.paused:
        return ProjectStatus.PAUSING if activity.running else ProjectStatus.PAUSED
    if activity.work_running:
        return ProjectStatus.RUNNING
    if activity.waiting:
        return ProjectStatus.WAITING_ON_YOU
    if activity.wait_open:
        return ProjectStatus.WAITING_ON_EVENT
    if progress.total and progress.done == progress.total:
        return ProjectStatus.DONE
    return ProjectStatus.IDLE


def plan_progress(tasks: Iterable[PlanTask]) -> PlanProgress:
    """The progress of `tasks`, the plan's steps in their order."""
    steps = list(tasks)
    return PlanProgress(
        done=sum(task.status_code is TaskStatus.DONE for task in steps),
        total=len(steps),
        in_progress=tuple(
            task.title for task in steps if task.status_code is TaskStatus.IN_PROGRESS
        ),
    )


_VERBS = {
    TransitionKind.FINISHED: "finish",
    TransitionKind.REOPENED: "reopen",
    TransitionKind.ARCHIVED: "archive",
    TransitionKind.BROUGHT_BACK: "bring back",
    TransitionKind.AUTOPILOT_ON: "turn auto pilot on for",
    TransitionKind.AUTOPILOT_OFF: "turn auto pilot off for",
    TransitionKind.PAUSED: "pause",
    TransitionKind.RESUMED: "resume",
}
"""What a person does with each kind, as a refusal names it."""

ARCHIVED_REFUSAL = "it is archived, and an archived project takes Bring back alone"


class ProjectService:
    def __init__(
        self,
        db: Session,
        engine_bus: EngineBus,
        people_service: PeopleService,
        record_service: RecordService,
        view_service: ViewService,
        timeline_service: TimelineService,
        session_start_service: SessionStartService,
    ) -> None:
        self.db = db
        self.engine_bus = engine_bus
        self.people_service = people_service
        self.record_service = record_service
        self.view_service = view_service
        self.timeline_service = timeline_service
        self.session_start_service = session_start_service

    def tabs(self, auth: AuthContext, archived: bool) -> list[ProjectTab]:
        """The archived projects, or every other, in the order they were
        created, with what their tabs show to the caller: the project's
        status (F141.1), and the badge counting what waits on them (F1.4)."""
        projects = list(
            self.db.scalars(
                select(Project)
                .where(Project.archived.is_(archived))
                .order_by(Project.number)
            )
        )
        ids = [project.id for project in projects]
        memberships = self._memberships(auth, ids)
        finished = dict(
            self.db.execute(
                select(ProjectTransition.project_id, func.max(ProjectTransition.at))
                .where(
                    ProjectTransition.project_id.in_(ids),
                    ProjectTransition.kind_code == TransitionKind.FINISHED,
                )
                .group_by(ProjectTransition.project_id)
            ).all()
        )
        steps: dict[uuid.UUID, list[PlanTask]] = {}
        for task in self._steps(ids):
            steps.setdefault(task.project_id, []).append(task)
        progress = {
            project.id: plan_progress(steps.get(project.id, [])) for project in projects
        }
        activities = self._activities(projects)
        badges = self.timeline_service.badges(self.people_service.find(auth), ids)
        return [
            ProjectTab(
                project=project,
                finished_at=(
                    finished[project.id]
                    if project.state_code is ProjectState.FINISHED
                    else None
                ),
                status=project_status(
                    project,
                    activities.get(project.id, _QUIET),
                    progress[project.id],
                ),
                member=project.id in memberships,
                progress=progress[project.id],
                badge=badges.get(project.id, Badge(0, False)),
            )
            for project in projects
        ]

    def head(self, auth: AuthContext, project_id: uuid.UUID) -> ProjectHead:
        """The project's head as the caller reads it.

        Raises:
            RecordNotFoundException: no project has the id.
        """
        project = self.db.get(Project, project_id)
        if project is None:
            raise RecordNotFoundException("Project", str(project_id))
        members = tuple(
            self.db.scalars(
                select(User)
                .join(ProjectMember, ProjectMember.user_id == User.id)
                .where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.left_at.is_(None),
                )
                .order_by(ProjectMember.joined_at, ProjectMember.id)
            )
        )
        tasks = self._steps([project.id])
        notes: dict[str | None, list[PlanNote]] = {}
        for note in self.db.scalars(
            select(PlanNote)
            .where(PlanNote.project_id == project.id, PlanNote.deleted_at.is_(None))
            .order_by(PlanNote.id)
        ):
            notes.setdefault(note.plan_task_id, []).append(note)
        open_items = self.db.scalar(
            select(func.count())
            .select_from(Item)
            .where(
                Item.project_id == project.id,
                Item.done_at.is_(None),
                Item.kind_code != OPENING,
            )
        )
        progress = plan_progress(tasks)
        return ProjectHead(
            project=project,
            status=project_status(
                project, self._activities([project]).get(project.id, _QUIET), progress
            ),
            member=project.id in self._memberships(auth, [project.id]),
            members=members,
            progress=progress,
            steps=tuple(
                PlanStep(task, tuple(notes.get(task.task_id, []))) for task in tasks
            ),
            notes=tuple(notes.get(None, [])),
            open_items=open_items or 0,
        )

    def transition(
        self, auth: AuthContext, project_id: uuid.UUID, kind: TransitionKind
    ) -> None:
        """The caller's transition of `kind`, now, the project's caches
        refreshed with it (DB §7.4). Finish is followed at its instant by
        `autopilot_off` while auto pilot is on and by `resumed` while the
        project is paused (DB 171), and closes the open items unanswered
        (F5.1). A finished project's auto pilot is off and it is not paused,
        so Reopen leaves both so (F6). Archive keeps the pause, and Bring back
        returns it (F141.2). A pause and a resume move the reason on the
        project's held work items' lines, and once a resume commits the gate
        opens for its held starts (F141.5). Archive and Bring back raise the
        `manifest` event once committed: the project's folder leaves the
        store's tree or comes back to it (F128.4).

        Raises:
            RecordNotFoundException: no project has the id.
            InvalidOperationException: the caller has not chosen a handle, or
                the project's standing does not allow `kind` (DB 170).
        """
        project = self._locked(project_id)
        operation = f"{_VERBS[kind]} {_named(project)}"
        person = self.people_service.require_person(auth, operation)
        refusal = _refusal(project, kind)
        if refusal is not None:
            raise InvalidOperationException(operation, refusal)
        at = datetime.now(UTC)
        paused = project.paused
        self._write(project, person, at, kind)
        if kind is TransitionKind.FINISHED:
            if project.autopilot:
                self._write(project, person, at, TransitionKind.AUTOPILOT_OFF)
            if project.paused:
                self._write(project, person, at, TransitionKind.RESUMED)
            self.record_service.close_unanswered(project, person, at)
        if project.paused != paused:
            self._pause_moved(project)
        if kind in (TransitionKind.PAUSED, TransitionKind.RESUMED):
            # The pause is not in the store's tree: its timeline is unmoved.
            self.engine_bus.emit(ProjectChanged(project.id))
        else:
            self.view_service.timeline_moved(project)
        if kind in (TransitionKind.ARCHIVED, TransitionKind.BROUGHT_BACK):
            self.engine_bus.emit(ManifestChanged())

    def join(self, auth: AuthContext, project_id: uuid.UUID) -> None:
        """The caller's new membership of the project, a rejoin a new row
        (F127).

        Raises:
            RecordNotFoundException: no project has the id.
            InvalidOperationException: the caller has not chosen a handle, is
                a member, or the project is archived.
        """
        project = self._locked(project_id)
        operation = f"join {_named(project)}"
        person = self.people_service.require_person(auth, operation)
        if project.archived:
            raise InvalidOperationException(operation, ARCHIVED_REFUSAL)
        if self._membership(project, person) is not None:
            raise InvalidOperationException(operation, "you are a member already")
        self.db.add(
            ProjectMember(
                project_id=project.id, user_id=person.id, joined_at=datetime.now(UTC)
            )
        )
        self.db.flush()
        self.engine_bus.emit(ProjectChanged(project.id))

    def leave(self, auth: AuthContext, project_id: uuid.UUID) -> None:
        """The caller's membership of the project closed (F127).

        Raises:
            RecordNotFoundException: no project has the id.
            InvalidOperationException: the caller has not chosen a handle, is
                no member, or the project is archived.
        """
        project = self._locked(project_id)
        operation = f"leave {_named(project)}"
        person = self.people_service.require_person(auth, operation)
        if project.archived:
            raise InvalidOperationException(operation, ARCHIVED_REFUSAL)
        membership = self._membership(project, person)
        if membership is None:
            raise InvalidOperationException(operation, "you are no member")
        membership.left_at = datetime.now(UTC)
        self.db.flush()
        self.engine_bus.emit(ProjectChanged(project.id))

    def _locked(self, project_id: uuid.UUID) -> Project:
        """The project, its row held until the transaction ends, so that two
        changes of its standing never interleave, read as the lock found it.

        Raises:
            RecordNotFoundException: no project has the id.
        """
        project = self.db.scalars(
            select(Project)
            .where(Project.id == project_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        ).one_or_none()
        if project is None:
            raise RecordNotFoundException("Project", str(project_id))
        return project

    def _write(
        self, project: Project, person: User, at: datetime, kind: TransitionKind
    ) -> None:
        """The transition, and the cache it changes (DB 170)."""
        self.db.add(
            ProjectTransition(
                project_id=project.id, kind_code=kind, at=at, by_user_id=person.id
            )
        )
        # One flush each: at one instant, the ids keep the transitions' order.
        self.db.flush()
        match kind:
            case TransitionKind.FINISHED:
                project.state_code = ProjectState.FINISHED
            case TransitionKind.ARCHIVED:
                project.archived = True
            case TransitionKind.BROUGHT_BACK:
                project.archived = False
            case TransitionKind.AUTOPILOT_ON:
                project.autopilot = True
            case TransitionKind.AUTOPILOT_OFF:
                project.autopilot = False
            case TransitionKind.REOPENED:
                project.state_code = ProjectState.OPEN
            case TransitionKind.PAUSED:
                project.paused = True
            case TransitionKind.RESUMED:
                project.paused = False

    def _pause_moved(self, project: Project) -> None:
        """The project paused or resumed: its held work items' reasons moved
        (`held_reason`, the pause read first), and on a resume the gate asked
        again once the transaction commits (F141.5)."""
        for session in self.db.scalars(
            select(AgentSession).where(
                AgentSession.project_id == project.id,
                AgentSession.state_code == SessionState.HELD,
            )
        ):
            work_moved(self.engine_bus, session)
        if not project.paused:
            after_commit(self.session_start_service.release_held)

    def _activities(self, projects: list[Project]) -> dict[uuid.UUID, Activity]:
        """What runs and waits in each open project among `projects`, as its
        status reads it (DB 228); one where nothing does is left out."""
        ids = [
            project.id
            for project in projects
            if project.state_code is ProjectState.OPEN
        ]
        if not ids:
            return {}
        running: dict[uuid.UUID, bool] = dict(
            self.db.execute(
                select(AgentSession.project_id, func.bool_or(Work.id.is_not(None)))
                .outerjoin(Work, Work.id == AgentSession.id)
                .where(
                    AgentSession.project_id.in_(ids),
                    AgentSession.state_code == SessionState.RUNNING,
                )
                .group_by(AgentSession.project_id)
            ).all()
        )
        waits = {
            row.project_id: row
            for row in self.db.execute(
                select(
                    Item.project_id,
                    func.bool_or(waiting_on_a_member()).label("waiting"),
                    func.bool_or(ItemKind.form == WAIT).label("wait_open"),
                )
                .join(ItemKind, ItemKind.code == Item.kind_code)
                .where(Item.project_id.in_(ids), Item.done_at.is_(None))
                .group_by(Item.project_id)
            )
        }
        return {
            project_id: Activity(
                running=project_id in running,
                work_running=running.get(project_id, False),
                waiting=project_id in waits and waits[project_id].waiting,
                wait_open=project_id in waits and waits[project_id].wait_open,
            )
            for project_id in running.keys() | waits.keys()
        }

    def _membership(self, project: Project, person: User) -> ProjectMember | None:
        return self.db.scalars(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == person.id,
                ProjectMember.left_at.is_(None),
            )
        ).one_or_none()

    def _memberships(
        self, auth: AuthContext, project_ids: list[uuid.UUID]
    ) -> set[uuid.UUID]:
        """Which of the projects the caller is a member of; none before they
        chose their handle."""
        person = self.people_service.find(auth)
        if person is None:
            return set()
        return set(
            self.db.scalars(
                select(ProjectMember.project_id).where(
                    ProjectMember.user_id == person.id,
                    ProjectMember.left_at.is_(None),
                    ProjectMember.project_id.in_(project_ids),
                )
            )
        )

    def _steps(self, project_ids: list[uuid.UUID]) -> list[PlanTask]:
        """The plans' steps, project by project, each plan's in its order."""
        return list(
            self.db.scalars(
                select(PlanTask)
                .where(
                    PlanTask.project_id.in_(project_ids),
                    PlanTask.removed_at.is_(None),
                )
                .order_by(PlanTask.project_id, PlanTask.position)
            )
        )


def _refusal(project: Project, kind: TransitionKind) -> str | None:
    """Why the project's standing does not allow a transition of `kind`, or
    none: a kind follows from the standing it leaves (DB 170), an archived
    project takes Bring back alone (D012), and auto pilot is an open project's
    (F2.6, F4.1), as the pause is (F141.2)."""
    if kind is TransitionKind.BROUGHT_BACK:
        return None if project.archived else "it is not archived"
    if project.archived:
        return ARCHIVED_REFUSAL
    state = project.state_code
    if kind is TransitionKind.FINISHED:
        if state is ProjectState.DRAFT:
            return "it is a draft"
        if state is ProjectState.FINISHED:
            return "it is finished already"
    if kind is TransitionKind.REOPENED and state is not ProjectState.FINISHED:
        return "it is not finished"
    if kind in (TransitionKind.AUTOPILOT_ON, TransitionKind.PAUSED):
        if state is ProjectState.DRAFT:
            return "it is a draft"
        if state is ProjectState.FINISHED:
            return "it is finished"
    if kind is TransitionKind.AUTOPILOT_ON and project.autopilot:
        return "auto pilot is on already"
    if kind is TransitionKind.AUTOPILOT_OFF and not project.autopilot:
        return "auto pilot is off already"
    if kind is TransitionKind.PAUSED and project.paused:
        return "it is paused already"
    if kind is TransitionKind.RESUMED and not project.paused:
        return "it is not paused"
    return None


def _named(project: Project) -> str:
    return project.name or "the untitled project"
