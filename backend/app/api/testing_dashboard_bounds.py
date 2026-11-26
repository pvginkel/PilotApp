"""A testing endpoint that sets the dashboard engine's timeout (F154.5) on
the running app, so that a spec meets the engine's refusal of a read: outside
the tests only its environment sets it, at boot (TEST-6)."""

from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from spectree import Response as SpectreeResponse

from app.app_config import AppSettings
from app.dashboard.bounds import Bounds
from app.schemas.common import ApiErrorResponseSchema
from app.schemas.testing_dashboard_bounds import DashboardBoundsSchema
from app.services.container import ServiceContainer
from app.utils.spectree_config import api

testing_dashboard_bounds_bp = Blueprint(
    "testing_dashboard_bounds", __name__, url_prefix="/api/testing/dashboard-bounds"
)


@testing_dashboard_bounds_bp.before_request
def check_testing_mode() -> Any:
    """Reject requests when the server is not running in testing mode."""
    from app.api.testing_guard import reject_if_not_testing

    return reject_if_not_testing()


@testing_dashboard_bounds_bp.route("", methods=["PUT"])
@api.validate(
    json=DashboardBoundsSchema,
    resp=SpectreeResponse(
        HTTP_200=DashboardBoundsSchema,
        HTTP_400=ApiErrorResponseSchema,
    ),
)
@inject
def put_dashboard_bounds(
    app_config: AppSettings = Provide[ServiceContainer.app_config],
    bounds: Bounds = Provide[ServiceContainer.dashboard_bounds],
) -> Any:
    """Set the engine's timeout; left out, the one the app booted with. The
    reads that start from here on take it.

    Returns:
        200: The engine's timeout as the app now holds it
        400: A timeout that is not above zero
    """
    data = DashboardBoundsSchema.model_validate(request.get_json())
    bounds.timeout_seconds = (
        data.timeout_seconds or app_config.dashboard_statement_timeout_seconds
    )
    return DashboardBoundsSchema(timeout_seconds=bounds.timeout_seconds).model_dump()
