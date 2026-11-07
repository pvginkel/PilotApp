"""What a browser needs to turn its notifications on (F146)."""

from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint
from spectree import Response as SpectreeResponse

from app.schemas.common import ApiErrorResponseSchema
from app.schemas.web_push import WebPushSetupSchema
from app.services.container import ServiceContainer
from app.services.web_push import WebPushService
from app.utils.spectree_config import api

web_push_bp = Blueprint("web_push", __name__, url_prefix="/web-push")


@web_push_bp.route("", methods=["GET"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=WebPushSetupSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
    )
)
@inject
def get_web_push(
    web_push_service: WebPushService = Provide[ServiceContainer.web_push_service],
) -> Any:
    """Read the stage's public key, which a browser subscribes with; none where
    the deployment sends no notifications.

    Returns:
        200: The stage's public key, or none
        401: No one is signed in
        403: The caller lacks the editor role
    """
    return WebPushSetupSchema(public_key=web_push_service.public_key).model_dump()
