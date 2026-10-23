"""The conditions that hold all work, a line each on the gold bar over the
project list (UC *The gold bar*; F125): read once, then followed by the
`conditions_changed` event."""

from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint
from spectree import Response as SpectreeResponse

from app.schemas.common import ApiErrorResponseSchema
from app.schemas.conditions import ConditionsSchema
from app.services.condition_service import ConditionService
from app.services.container import ServiceContainer
from app.utils.spectree_config import api

conditions_bp = Blueprint("conditions", __name__, url_prefix="/conditions")


@conditions_bp.route("", methods=["GET"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=ConditionsSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
    )
)
@inject
def get_conditions(
    condition_service: ConditionService = Provide[ServiceContainer.condition_service],
) -> Any:
    """Read the conditions that hold now: the controller unreachable, as this
    server last met it.

    Returns:
        200: The conditions that hold; none while all work can go on
        401: No one is signed in
        403: The caller lacks the editor role
    """
    return condition_service.conditions().model_dump(mode="json")
