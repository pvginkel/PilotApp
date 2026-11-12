"""A testing endpoint that sets the usage halts' settings (F135.6) on the
running app: outside the tests only its environment sets them, at boot
(TEST-6)."""

from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from spectree import Response as SpectreeResponse

from app.app_config import AppSettings
from app.schemas.common import ApiErrorResponseSchema
from app.schemas.testing_halt_settings import HaltSettingsSchema
from app.services.container import ServiceContainer
from app.services.halt_file_service import HaltFileService
from app.services.usage_halts import UsageHalts
from app.utils.spectree_config import api

testing_halt_settings_bp = Blueprint(
    "testing_halt_settings", __name__, url_prefix="/api/testing/halt-settings"
)


@testing_halt_settings_bp.before_request
def check_testing_mode() -> Any:
    """Reject requests when the server is not running in testing mode."""
    from app.api.testing_guard import reject_if_not_testing

    return reject_if_not_testing()


@testing_halt_settings_bp.route("", methods=["PUT"])
@api.validate(
    json=HaltSettingsSchema,
    resp=SpectreeResponse(
        HTTP_200=HaltSettingsSchema,
        HTTP_400=ApiErrorResponseSchema,
    ),
)
@inject
def put_halt_settings(
    app_config: AppSettings = Provide[ServiceContainer.app_config],
    usage_halts: UsageHalts = Provide[ServiceContainer.usage_halts],
    halt_file_service: HaltFileService = Provide[ServiceContainer.halt_file_service],
) -> Any:
    """Set what the week's halt and the five-hour halt do to the work items;
    a setting left out is the one the app booted with. The halts decided
    from here on take it: nothing is done for a halt that holds already.

    Returns:
        200: The halt settings as the app now holds them
        400: A setting that is none of the three
    """
    data = HaltSettingsSchema.model_validate(request.get_json())
    week_halt = data.week_halt or app_config.week_halt
    five_hour_halt = data.five_hour_halt or app_config.five_hour_halt
    usage_halts.set_settings(week_halt=week_halt, five_hour_halt=five_hour_halt)
    halt_file_service.set_settings(week_halt=week_halt, five_hour_halt=five_hour_halt)
    return HaltSettingsSchema(
        week_halt=week_halt, five_hour_halt=five_hour_halt
    ).model_dump()
