"""The signed-in person's pages of Pilot: a page's beat and its away, by which
they are online (F147; DB 312)."""

import uuid
from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from spectree import Response as SpectreeResponse
from sqlalchemy.orm import Session

from app.api.caller import caller
from app.schemas.app_pages import AppPageBeatSchema, AppPageSchema
from app.schemas.common import ApiErrorResponseSchema
from app.services.app_page_service import AppPageService
from app.services.container import ServiceContainer
from app.services.people_service import PeopleService
from app.utils.spectree_config import api

app_pages_bp = Blueprint("app_pages", __name__, url_prefix="/people/self/app-pages")


@app_pages_bp.route("", methods=["POST"])
@api.validate(
    json=AppPageBeatSchema,
    resp=SpectreeResponse(
        HTTP_201=AppPageSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def begin_page(
    db: Session = Provide[ServiceContainer.db_session],
    people_service: PeopleService = Provide[ServiceContainer.people_service],
    app_page_service: AppPageService = Provide[ServiceContainer.app_page_service],
) -> Any:
    """A page's first beat: the page written for the signed-in person,
    showing the project or none, and its id minted.

    Returns:
        201: The page, whose id it names in its beats after and its away
        400: The body has no project id, or one that is no uuid
        401: No one is signed in
        403: The caller lacks the editor role
        404: No project has the id
        409: The caller has not chosen a handle
    """
    body = AppPageBeatSchema.model_validate(request.get_json())
    person = people_service.require_person(caller(), "beat a page of Pilot")
    page_id = app_page_service.begin(db, person, body.project_id)
    return AppPageSchema(id=page_id).model_dump(mode="json"), 201


@app_pages_bp.route("/<uuid:page_id>", methods=["PUT"])
@api.validate(
    json=AppPageBeatSchema,
    resp=SpectreeResponse(
        HTTP_204=None,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def beat_page(
    page_id: uuid.UUID,
    db: Session = Provide[ServiceContainer.db_session],
    people_service: PeopleService = Provide[ServiceContainer.people_service],
    app_page_service: AppPageService = Provide[ServiceContainer.app_page_service],
) -> Any:
    """A page's beat after its first: when it beat, and the project it shows
    or none.

    Returns:
        204: The page beat
        400: The body has no project id, or one that is no uuid
        401: No one is signed in
        403: The caller lacks the editor role
        404: The page has ended, by its away or its beat's ninety seconds,
            or is no page of the caller's: it beats afresh, a first beat. Or
            no project has the id
        409: The caller has not chosen a handle
    """
    body = AppPageBeatSchema.model_validate(request.get_json())
    person = people_service.require_person(caller(), "beat a page of Pilot")
    app_page_service.beat(db, person, page_id, body.project_id)
    return "", 204


@app_pages_bp.route("/<uuid:page_id>/away", methods=["POST"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_204=None,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def leave_page(
    page_id: uuid.UUID,
    db: Session = Provide[ServiceContainer.db_session],
    people_service: PeopleService = Provide[ServiceContainer.people_service],
    app_page_service: AppPageService = Provide[ServiceContainer.app_page_service],
) -> Any:
    """A page's away, as it hides or goes idle: the page deleted. A POST
    whose body is not read, so that a beacon carries it. A page that has
    ended, or is another person's, is nothing to delete.

    Returns:
        204: The caller has no such page
        401: No one is signed in
        403: The caller lacks the editor role
        409: The caller has not chosen a handle
    """
    person = people_service.require_person(caller(), "send a page's away")
    app_page_service.away(db, person, page_id)
    return "", 204
