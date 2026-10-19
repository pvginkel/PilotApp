"""A testing endpoint that sets the deployment's link settings (F91, F93) on
the running app: outside the tests only its environment sets them, at boot
(TEST-6)."""

from typing import Any

from dependency_injector import providers
from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from spectree import Response as SpectreeResponse

from app.app_config import AppSettings
from app.schemas.common import ApiErrorResponseSchema
from app.schemas.testing_links import LinkSettingsSchema
from app.services.container import ServiceContainer
from app.utils.spectree_config import api

testing_links_bp = Blueprint("testing_links", __name__, url_prefix="/api/testing/links")


@testing_links_bp.before_request
def check_testing_mode() -> Any:
    """Reject requests when the server is not running in testing mode."""
    from app.api.testing_guard import reject_if_not_testing

    return reject_if_not_testing()


@testing_links_bp.route("", methods=["PUT"])
@api.validate(
    json=LinkSettingsSchema,
    resp=SpectreeResponse(
        HTTP_200=LinkSettingsSchema,
        HTTP_400=ApiErrorResponseSchema,
    ),
)
@inject
def put_link_settings(
    app_config: providers.Dependency[AppSettings] = Provide[
        ServiceContainer.app_config.provider
    ],
) -> Any:
    """Set the ticket URL template and KubeCoder's address, checked as at
    boot; a setting left out is unset. The ticket id pattern stays.

    Returns:
        200: The link settings as the app now holds them
        400: A template without `{id}`, or a base that is not an http(s)
            address
    """
    data = LinkSettingsSchema.model_validate(request.get_json())
    settings = AppSettings.model_validate(app_config().model_dump() | data.model_dump())
    app_config.override(settings)
    return LinkSettingsSchema(
        ticket_url_template=settings.ticket_url_template,
        environment_link_base_url=settings.environment_link_base_url,
    ).model_dump()
