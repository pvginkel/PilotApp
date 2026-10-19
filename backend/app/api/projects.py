"""The projects as the signed-in person reads them: the project list, the
archived projects and a project's head (F1, F2, F3, D2)."""

import uuid
from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from spectree import Response as SpectreeResponse

from app.api.caller import caller
from app.models import PlanNote, User
from app.schemas.common import ApiErrorResponseSchema
from app.schemas.projects import (
    MemberSchema,
    PlanNoteSchema,
    PlanProgressSchema,
    PlanTaskSchema,
    ProjectHeadSchema,
    ProjectListQuerySchema,
    ProjectListResponseSchema,
    ProjectTabSchema,
)
from app.services.container import ServiceContainer
from app.services.people_service import initials
from app.services.project_service import PlanProgress, ProjectService
from app.utils.spectree_config import api

projects_bp = Blueprint("projects", __name__, url_prefix="/projects")


def _progress(progress: PlanProgress) -> PlanProgressSchema:
    return PlanProgressSchema(
        done=progress.done,
        total=progress.total,
        in_progress=list(progress.in_progress),
    )


def _note(note: PlanNote) -> PlanNoteSchema:
    return PlanNoteSchema(id=note.note_id, summary=note.summary, content=note.content)


def _member(person: User) -> MemberSchema:
    # Members are people, Pilot never one (F127), and a person's row has a
    # slot (`ck_users_person`).
    assert person.avatar_slot is not None
    return MemberSchema(
        handle=person.handle,
        name=person.name,
        initials=initials(person.name),
        avatar_slot=person.avatar_slot,
    )


@projects_bp.route("", methods=["GET"])
@api.validate(
    query=ProjectListQuerySchema,
    resp=SpectreeResponse(
        HTTP_200=ProjectListResponseSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
    ),
)
@inject
def list_projects(
    project_service: ProjectService = Provide[ServiceContainer.project_service],
) -> Any:
    """Read the project list's tabs, or with `archived` the archived projects'.

    Returns:
        200: The projects, in the order they were created
        400: `archived` is not a boolean
        401: No one is signed in
        403: The caller lacks the editor role
    """
    query = ProjectListQuerySchema.model_validate(request.args.to_dict())
    return ProjectListResponseSchema(
        projects=[
            ProjectTabSchema(
                id=tab.project.id,
                name=tab.project.name,
                ticket=tab.project.ticket,
                state=tab.project.state_code,
                finished_at=tab.finished_at,
                member=tab.member,
                progress=_progress(tab.progress),
            )
            for tab in project_service.tabs(caller(), query.archived)
        ]
    ).model_dump(mode="json")


@projects_bp.route("/<uuid:project_id>", methods=["GET"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=ProjectHeadSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
    )
)
@inject
def get_project(
    project_id: uuid.UUID,
    project_service: ProjectService = Provide[ServiceContainer.project_service],
) -> Any:
    """Read a project's head: its standing, its members and its plan.

    Returns:
        200: The project's head
        401: No one is signed in
        403: The caller lacks the editor role
        404: No project has the id
    """
    head = project_service.head(caller(), project_id)
    project = head.project
    return ProjectHeadSchema(
        id=project.id,
        name=project.name,
        ticket=project.ticket,
        repo=project.repo,
        state=project.state_code,
        archived=project.archived,
        autopilot=project.autopilot,
        member=head.member,
        members=[_member(person) for person in head.members],
        progress=_progress(head.progress),
        tasks=[
            PlanTaskSchema(
                id=step.task.task_id,
                title=step.task.title,
                status=step.task.status_code,
                notes=[_note(note) for note in step.notes],
            )
            for step in head.steps
        ],
        notes=[_note(note) for note in head.notes],
        open_items=head.open_items,
    ).model_dump(mode="json")
