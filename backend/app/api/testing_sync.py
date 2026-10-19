"""Testing endpoints for the store's sync (TEST-6): what the live proof of
the sync sets off inside the running server, where the engine's bus is.

Refused unless the server runs with FLASK_ENV=testing on a STAGE other than
prd (`reject_if_not_testing()`).
"""

from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, jsonify, request
from spectree import Response as SpectreeResponse

from app.api.testing_guard import reject_if_not_testing
from app.schemas.common import ApiErrorResponseSchema
from app.schemas.testing_sync import (
    TestingSyncAnswerRequestSchema,
    TestingSyncAnswerResponseSchema,
)
from app.services.container import ServiceContainer
from app.services.testing_sync_service import TestingSyncService
from app.utils.auth import public
from app.utils.spectree_config import api

testing_sync_bp = Blueprint("testing_sync", __name__, url_prefix="/api/testing/sync")


@testing_sync_bp.before_request
def check_testing_mode() -> Any:
    return reject_if_not_testing()


@testing_sync_bp.route("/answer", methods=["POST"])
@public
@api.validate(
    json=TestingSyncAnswerRequestSchema,
    resp=SpectreeResponse(
        HTTP_200=TestingSyncAnswerResponseSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def answer(
    testing_sync_service: TestingSyncService = Provide[
        ServiceContainer.testing_sync_service
    ],
) -> Any:
    """A person's answer to a block of a document, as the UI gives it: the
    record writes the file, and the store's change stream says so once
    committed.

    Returns:
        200: The document's path and its tree hash once answered
        404: No document at the path, or no user with the handle
        409: The record refuses the answer
    """
    body = TestingSyncAnswerRequestSchema.model_validate(request.get_json())
    file = testing_sync_service.answer(body.path, body.block, body.answer, body.user)
    response = TestingSyncAnswerResponseSchema(path=body.path, hash=file.hash)
    return jsonify(response.model_dump()), 200


@testing_sync_bp.route("/manifest", methods=["POST"])
@public
@api.validate(resp=SpectreeResponse(HTTP_204=None, HTTP_400=ApiErrorResponseSchema))
@inject
def announce_manifest(
    testing_sync_service: TestingSyncService = Provide[
        ServiceContainer.testing_sync_service
    ],
) -> Any:
    """Raise the `manifest` event, as a change to the set of syncing projects
    does: every change stream carries a `manifest` once committed."""
    testing_sync_service.announce_manifest()
    return "", 204
