"""The signed-in person: who they are on the record, the handle they choose
at their first sign-in (F137), and on their profile their notification token
and alarms switch (F134, F142.1)."""

from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from spectree import Response as SpectreeResponse

from app.api.caller import caller
from app.schemas.common import ApiErrorResponseSchema
from app.schemas.people import (
    AlarmsSwitchSchema,
    HandleChoiceSchema,
    NotificationTokenSchema,
    SelfResponseSchema,
)
from app.schemas.task_schema import TaskStartResponse
from app.services.container import ServiceContainer
from app.services.notification_settings_service import (
    SAVE_OPERATION,
    NotificationSettingsService,
)
from app.services.people_service import (
    PeopleService,
    handle_prefill,
    initials,
    self_response,
    token_name,
)
from app.utils.spectree_config import api

people_bp = Blueprint("people", __name__, url_prefix="/people")


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
        return self_response(person).model_dump()
    name = token_name(auth)
    return SelfResponseSchema(
        handle=None,
        handle_prefill=handle_prefill(name),
        name=name,
        initials=None if name is None else initials(name),
        avatar_slot=None,
        notification_token_set=None,
        alarms=None,
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
    return self_response(person).model_dump(), 201


@people_bp.route("/self/notification-token", methods=["PUT"])
@api.validate(
    json=NotificationTokenSchema,
    resp=SpectreeResponse(
        HTTP_202=TaskStartResponse,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def save_notification_token(
    people_service: PeopleService = Provide[ServiceContainer.people_service],
    notification_settings_service: NotificationSettingsService = Provide[
        ServiceContainer.notification_settings_service
    ],
) -> Any:
    """Save the signed-in person's notification token, a first one or another
    in its place (F134, F134.1).

    A task sends the one-shot "Pilot will notify you here" through the token,
    and stores it once the bridge took it; its result is the person. A token
    the bridge refuses or does not answer fails the task with the bridge's
    reason, and is not stored.

    Returns:
        202: The save's task
        400: The token is not visible ASCII
        401: No one is signed in
        403: The caller lacks the editor role
        409: The caller has not chosen a handle, or no notification bridge is
            configured
    """
    auth = caller()
    body = NotificationTokenSchema.model_validate(request.get_json())
    person = people_service.require_person(auth, SAVE_OPERATION)
    started = notification_settings_service.start_save(person, body.token, auth.subject)
    return started.model_dump(mode="json"), 202


@people_bp.route("/self/notification-token", methods=["DELETE"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=SelfResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    )
)
@inject
def clear_notification_token(
    people_service: PeopleService = Provide[ServiceContainer.people_service],
    notification_settings_service: NotificationSettingsService = Provide[
        ServiceContainer.notification_settings_service
    ],
) -> Any:
    """Clear the signed-in person's notification token, at once (F134).

    Each of their standing notifications and alarms is dismissed through the
    token cleared, tried once, after the answer; what the bridge does not
    take stays on the phone.

    Returns:
        200: The person, with no token set
        401: No one is signed in
        403: The caller lacks the editor role
        409: The caller has not chosen a handle, or the app's key does not
            open their token
    """
    person = people_service.require_person(caller(), "clear your notification token")
    notification_settings_service.clear(person)
    return self_response(person).model_dump()


@people_bp.route("/self/alarms", methods=["PUT"])
@api.validate(
    json=AlarmsSwitchSchema,
    resp=SpectreeResponse(
        HTTP_200=SelfResponseSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def switch_alarms(
    people_service: PeopleService = Provide[ServiceContainer.people_service],
    notification_settings_service: NotificationSettingsService = Provide[
        ServiceContainer.notification_settings_service
    ],
) -> Any:
    """Turn the signed-in person's alarms switch (F142.1).

    Off dismisses their standing alarms and on submits those of the
    conditions that hold, after the answer.

    Returns:
        200: The person, with the switch as turned
        400: The switch is not true or false
        401: No one is signed in
        403: The caller lacks the editor role
        409: The caller has not chosen a handle
    """
    choice = AlarmsSwitchSchema.model_validate(request.get_json())
    person = people_service.require_person(caller(), "turn your alarms switch")
    notification_settings_service.switch_alarms(person, choice.alarms)
    return self_response(person).model_dump()
