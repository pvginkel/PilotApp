"""The projects as the signed-in person reads them, the project list, the
archived projects, a project's head, its timeline, its draft and its handbook
(F1, F2, F3, F8, F37.4, F129.4, D012); and what they change of a project's
standing: its transitions, its pause among them, and their membership (F4.1,
F5, F6, F127, F128, F141.2)."""

import uuid
from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from spectree import Response as SpectreeResponse

from app.api.caller import caller
from app.models import PlanNote, User
from app.models.reference import DocumentRole, TransitionKind
from app.schemas.common import ApiErrorResponseSchema
from app.schemas.projects import (
    BadgeSchema,
    MemberSchema,
    PlanNoteSchema,
    PlanProgressSchema,
    PlanTaskSchema,
    ProjectHeadSchema,
    ProjectListQuerySchema,
    ProjectListResponseSchema,
    ProjectTabSchema,
    TransitionRequestSchema,
)
from app.schemas.timeline import ProjectDocumentSchema, TimelineSchema
from app.services.container import ServiceContainer
from app.services.people_service import initials
from app.services.project_service import PlanProgress, ProjectHead, ProjectService
from app.services.timeline_service import TimelineService
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


def _head(head: ProjectHead) -> dict[str, Any]:
    project = head.project
    return ProjectHeadSchema(
        id=project.id,
        name=project.name,
        ticket=project.ticket,
        repo=project.repo,
        state=project.state_code,
        archived=project.archived,
        autopilot=project.autopilot,
        status=head.status,
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
    """Read the project list's tabs, or with `archived` the archived projects',
    each with its status and its badge for the caller.

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
                status=tab.status,
                member=tab.member,
                progress=_progress(tab.progress),
                badge=BadgeSchema(count=tab.badge.count, urgent=tab.badge.urgent),
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
    """Read a project's head: its standing and status, its members and its
    plan.

    Returns:
        200: The project's head
        401: No one is signed in
        403: The caller lacks the editor role
        404: No project has the id
    """
    return _head(project_service.head(caller(), project_id))


@projects_bp.route("/<uuid:project_id>/timeline", methods=["GET"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=TimelineSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
    )
)
@inject
def get_timeline(
    project_id: uuid.UUID,
    timeline_service: TimelineService = Provide[ServiceContainer.timeline_service],
) -> Any:
    """Read a project's timeline whole: every item in order, as its line and
    its open form show it.

    Returns:
        200: The timeline
        401: No one is signed in
        403: The caller lacks the editor role
        404: No project has the id
    """
    return timeline_service.timeline(project_id).model_dump(mode="json")


@projects_bp.route("/<uuid:project_id>/draft", methods=["GET"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=ProjectDocumentSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
    )
)
@inject
def get_draft(
    project_id: uuid.UUID,
    timeline_service: TimelineService = Provide[ServiceContainer.timeline_service],
) -> Any:
    """Read the project document, `project.md`, read only: the draft as Pilot
    keeps it after Create project (F37.4).

    Returns:
        200: The draft as last published
        401: No one is signed in
        403: The caller lacks the editor role
        404: No project has the id
    """
    return timeline_service.project_document(project_id, DocumentRole.DRAFT).model_dump(
        mode="json"
    )


@projects_bp.route("/<uuid:project_id>/handbook", methods=["GET"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=ProjectDocumentSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
    )
)
@inject
def get_handbook(
    project_id: uuid.UUID,
    timeline_service: TimelineService = Provide[ServiceContainer.timeline_service],
) -> Any:
    """Read the project's handbook, `handbook.md`, read only (F129.4); born
    empty at Create project (F129.2).

    Returns:
        200: The handbook as last published
        401: No one is signed in
        403: The caller lacks the editor role
        404: No project has the id, or it is a draft, which has no handbook
    """
    return timeline_service.project_document(
        project_id, DocumentRole.HANDBOOK
    ).model_dump(mode="json")


@projects_bp.route("/<uuid:project_id>/transitions", methods=["POST"])
@api.validate(
    json=TransitionRequestSchema,
    resp=SpectreeResponse(
        HTTP_201=ProjectHeadSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def add_transition(
    project_id: uuid.UUID,
    project_service: ProjectService = Provide[ServiceContainer.project_service],
) -> Any:
    """Change the project's standing, as the signed-in person, now.

    Finish also turns auto pilot off, resumes a paused project, and closes
    the project's open items unanswered; Reopen leaves auto pilot off. A
    resume lets the project's held starts go on.

    Returns:
        201: The project's head, with its new standing
        400: The kind is not one a person makes
        401: No one is signed in
        403: The caller lacks the editor role
        404: No project has the id
        409: The caller has not chosen a handle, or the project's standing
            does not allow the change
    """
    change = TransitionRequestSchema.model_validate(request.get_json())
    auth = caller()
    project_service.transition(auth, project_id, TransitionKind(change.kind))
    return _head(project_service.head(auth, project_id)), 201


@projects_bp.route("/<uuid:project_id>/membership", methods=["POST"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_201=ProjectHeadSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    )
)
@inject
def join_project(
    project_id: uuid.UUID,
    project_service: ProjectService = Provide[ServiceContainer.project_service],
) -> Any:
    """Join the project as the signed-in person.

    Returns:
        201: The project's head, the caller a member
        401: No one is signed in
        403: The caller lacks the editor role
        404: No project has the id
        409: The caller has not chosen a handle or is a member, or the
            project is archived
    """
    auth = caller()
    project_service.join(auth, project_id)
    return _head(project_service.head(auth, project_id)), 201


@projects_bp.route("/<uuid:project_id>/membership", methods=["DELETE"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=ProjectHeadSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    )
)
@inject
def leave_project(
    project_id: uuid.UUID,
    project_service: ProjectService = Provide[ServiceContainer.project_service],
) -> Any:
    """Leave the project as the signed-in person.

    Returns:
        200: The project's head, the caller no member
        401: No one is signed in
        403: The caller lacks the editor role
        404: No project has the id
        409: The caller has not chosen a handle or is no member, or the
            project is archived
    """
    auth = caller()
    project_service.leave(auth, project_id)
    return _head(project_service.head(auth, project_id))
