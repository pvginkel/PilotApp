"""The projects as the signed-in person reads them: the project list's tabs
and a project's head (F1, F2, F3)."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine.documents import OPENING
from app.exceptions import RecordNotFoundException
from app.models import (
    Item,
    PlanNote,
    PlanTask,
    Project,
    ProjectMember,
    ProjectTransition,
    User,
)
from app.models.reference import ProjectState, TaskStatus, TransitionKind
from app.services.auth_service import AuthContext
from app.services.people_service import PeopleService


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
    member: bool
    progress: PlanProgress


@dataclass(frozen=True)
class PlanStep:
    task: PlanTask
    notes: tuple[PlanNote, ...]


@dataclass(frozen=True)
class ProjectHead:
    project: Project
    member: bool
    members: tuple[User, ...]
    progress: PlanProgress
    steps: tuple[PlanStep, ...]
    notes: tuple[PlanNote, ...]
    open_items: int


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


class ProjectService:
    def __init__(self, db: Session, people_service: PeopleService) -> None:
        self.db = db
        self.people_service = people_service

    def tabs(self, auth: AuthContext, archived: bool) -> list[ProjectTab]:
        """The archived projects, or every other, in the order they were
        created, with what their tabs show to the caller."""
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
        return [
            ProjectTab(
                project=project,
                finished_at=(
                    finished[project.id]
                    if project.state_code is ProjectState.FINISHED
                    else None
                ),
                member=project.id in memberships,
                progress=plan_progress(steps.get(project.id, [])),
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
        return ProjectHead(
            project=project,
            member=project.id in self._memberships(auth, [project.id]),
            members=members,
            progress=plan_progress(tasks),
            steps=tuple(
                PlanStep(task, tuple(notes.get(task.task_id, []))) for task in tasks
            ),
            notes=tuple(notes.get(None, [])),
            open_items=open_items or 0,
        )

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
