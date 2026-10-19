"""Testing endpoints that make the record's states the UI cannot make
(TEST-6): people who never signed in, environments, and projects in every
standing, with members, a plan and open items. Nothing in the UI creates a
project before the definition chat (F46)."""

from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from spectree import Response as SpectreeResponse

from app.schemas.common import ApiErrorResponseSchema
from app.schemas.testing_record import (
    InventedEnvironmentSchema,
    InventedPersonCreateSchema,
    InventedPersonSchema,
    InventedProjectCreateSchema,
    InventedProjectSchema,
)
from app.services.container import ServiceContainer
from app.services.test_data_service import TestDataService
from app.utils.spectree_config import api

testing_record_bp = Blueprint("testing_record", __name__, url_prefix="/api/testing")


@testing_record_bp.before_request
def check_testing_mode() -> Any:
    """Reject requests when the server is not running in testing mode."""
    from app.api.testing_guard import reject_if_not_testing

    return reject_if_not_testing()


@testing_record_bp.route("/people", methods=["POST"])
@api.validate(
    json=InventedPersonCreateSchema,
    resp=SpectreeResponse(
        HTTP_201=InventedPersonSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def create_person(
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> Any:
    """Put a person on the record as the handle step does, under a subject
    no one signs in with.

    Returns:
        201: The person, with the avatar slot they took
        400: The handle is not lower-case letters, digits and hyphens
        409: The handle is Pilot's or another person's
    """
    data = InventedPersonCreateSchema.model_validate(request.get_json())
    person = test_data_service.person(data.handle, data.name)
    # A person's row has a slot (`ck_users_person`).
    assert person.avatar_slot is not None
    return InventedPersonSchema(
        handle=person.handle, name=person.name, avatar_slot=person.avatar_slot
    ).model_dump(), 201


@testing_record_bp.route("/environments", methods=["POST"])
@api.validate(
    json=InventedEnvironmentSchema,
    resp=SpectreeResponse(
        HTTP_201=InventedEnvironmentSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def create_environment(
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> Any:
    """Put an environment Pilot has touched on the record.

    Returns:
        201: The environment
        400: The id or the name is missing
        409: An environment has the id
    """
    data = InventedEnvironmentSchema.model_validate(request.get_json())
    environment = test_data_service.environment(data.id, data.name)
    return InventedEnvironmentSchema(
        id=environment.id, name=environment.name
    ).model_dump(), 201


@testing_record_bp.route("/projects", methods=["POST"])
@api.validate(
    json=InventedProjectCreateSchema,
    resp=SpectreeResponse(
        HTTP_201=InventedProjectSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def create_project(
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> Any:
    """Make a project in the standing given, made now by its first member.

    Returns:
        201: The project's id
        400: A finished project with auto pilot on, a member named twice,
            open items without an environment, or a plan with a fault
        404: A member is no person, or no environment has the id
        409: The name makes a draft text with a fault
    """
    data = InventedProjectCreateSchema.model_validate(request.get_json())
    project = test_data_service.project(data)
    return InventedProjectSchema(id=project.id).model_dump(mode="json"), 201
