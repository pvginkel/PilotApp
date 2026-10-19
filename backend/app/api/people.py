"""The signed-in person: who they are on the record, and the handle they
choose at their first sign-in (F137)."""

from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from spectree import Response as SpectreeResponse

from app.api.caller import caller
from app.models import User
from app.schemas.common import ApiErrorResponseSchema
from app.schemas.people import HandleChoiceSchema, SelfResponseSchema
from app.services.container import ServiceContainer
from app.services.people_service import (
    PeopleService,
    handle_prefill,
    initials,
    token_name,
)
from app.utils.spectree_config import api

people_bp = Blueprint("people", __name__, url_prefix="/people")


def _person(person: User) -> SelfResponseSchema:
    return SelfResponseSchema(
        handle=person.handle,
        handle_prefill=None,
        name=person.name,
        initials=initials(person.name),
        avatar_slot=person.avatar_slot,
    )


@people_bp.route("/self", methods=["GET"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=SelfResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
    )
)
@inject
def get_self(
    people_service: PeopleService = Provide[ServiceContainer.people_service],
) -> Any:
    """Read the signed-in person, recording the sign-in on their row.

    A person with a row has its name (unless the token carries none), email
    and last seen refreshed. One without is at their first sign-in: the
    answer has no handle and no slot, and the prefill for the handle step.

    Returns:
        200: The signed-in person
        401: No one is signed in
        403: The caller lacks the editor role
    """
    auth = caller()
    person = people_service.record_sign_in(auth)
    if person is not None:
        return _person(person).model_dump()
    name = token_name(auth)
    return SelfResponseSchema(
        handle=None,
        handle_prefill=handle_prefill(name),
        name=name,
        initials=None if name is None else initials(name),
        avatar_slot=None,
    ).model_dump()


@people_bp.route("/self/handle", methods=["POST"])
@api.validate(
    json=HandleChoiceSchema,
    resp=SpectreeResponse(
        HTTP_201=SelfResponseSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def choose_handle(
    people_service: PeopleService = Provide[ServiceContainer.people_service],
) -> Any:
    """Choose the signed-in person's handle, which puts them on the record.

    Returns:
        201: The person, with their handle and avatar slot
        400: The handle is not lower-case letters, digits and hyphens
        401: No one is signed in
        403: The caller lacks the editor role
        409: The handle is Pilot's or another person's, or the caller has one
    """
    choice = HandleChoiceSchema.model_validate(request.get_json())
    person = people_service.choose_handle(caller(), choice.handle)
    return _person(person).model_dump(), 201
