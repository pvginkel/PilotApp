"""`pilot-work`'s routes (TD §4.5, F85): the REST calls Pilot's MCP server
makes for a worker session's tools, under the session's bearer.

Registered on the app, not on `api_bp`, so the OIDC gate never sees them, and
outside `/api/`, the one prefix the site's nginx forwards, so that only the
pod's loopback reaches them, as it reaches `/metrics` (review 2). Every call
passes the gate below first, and carries the tool call's id in the
`Tool-Use-Id` header where Claude Code gave one, which its effect's record
names.
"""

from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, g, request
from spectree import Response as SpectreeResponse

from app.schemas.common import ApiErrorResponseSchema
from app.schemas.pilot_work import (
    AttachedFilesSchema,
    AttachFileRequestSchema,
    RegisterDocumentRequestSchema,
    RegisteredDocumentSchema,
)
from app.services.container import ServiceContainer
from app.services.effect_service import TOOL_USE_ID_HEADER
from app.services.pilot_work_service import PilotWorkService
from app.utils.auth import public
from app.utils.spectree_config import api

pilot_work_bp = Blueprint("pilot_work", __name__, url_prefix="/tools/pilot-work")


@pilot_work_bp.before_request
@inject
def admit_the_session(
    pilot_work_service: PilotWorkService = Provide[ServiceContainer.pilot_work_service],
) -> None:
    """The gate every call passes: 401 or 403 before anything is read or
    written."""
    g.worker = pilot_work_service.admit(request.headers.get("Authorization"))


@pilot_work_bp.route("/documents", methods=["POST"])
@public
@api.validate(
    json=RegisterDocumentRequestSchema,
    resp=SpectreeResponse(
        HTTP_200=RegisteredDocumentSchema,
        HTTP_201=RegisteredDocumentSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
        HTTP_502=ApiErrorResponseSchema,
    ),
)
@inject
def register_document(
    pilot_work_service: PilotWorkService = Provide[ServiceContainer.pilot_work_service],
) -> Any:
    """`register_document(path)` (F85.1, ruling D1): the file the worker wrote
    at `path` in its environment, read and parsed now, registered as a
    document on its project's timeline, its text read at the end of the turn.

    Returns:
        200: The document the session registered from the path already
        201: The document, minted
        400: The body is not a path
        401: No bearer, or one no session has
        403: The bearer's session is not a work item's
        409: The file cannot be registered, nothing minted: the reason, the
            text's faults each with its line
        502: The controller did not answer, or refused for a reason of its own
    """
    body = RegisterDocumentRequestSchema.model_validate(request.get_json())
    registration = pilot_work_service.register_document(
        g.worker, body.path, request.headers.get(TOOL_USE_ID_HEADER)
    )
    answer = RegisteredDocumentSchema(id=registration.item.id)
    return answer.model_dump(mode="json"), 201 if registration.minted else 200


@pilot_work_bp.route("/attachments", methods=["POST"])
@public
@api.validate(
    json=AttachFileRequestSchema,
    resp=SpectreeResponse(
        HTTP_201=AttachedFilesSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
        HTTP_502=ApiErrorResponseSchema,
    ),
)
@inject
def attach_file(
    pilot_work_service: PilotWorkService = Provide[ServiceContainer.pilot_work_service],
) -> Any:
    """`attach_file(path, to?)` (F85.2, F36.1): the file or the folder the
    worker wrote at `path` in its environment, copied into the record now
    with its source and hung on the item `to` names, else on the session's
    own work item.

    Returns:
        201: The attachments, one per file
        400: The body is not a path and an optional item id
        401: No bearer, or one no session has
        403: The bearer's session is not a work item's
        404: `to` names no item of the session's project
        409: A file cannot be copied, nothing attached: the reason
        502: The controller did not answer, or refused for a reason of its own
    """
    body = AttachFileRequestSchema.model_validate(request.get_json())
    attachments = pilot_work_service.attach_file(
        g.worker, body.path, body.to, request.headers.get(TOOL_USE_ID_HEADER)
    )
    answer = AttachedFilesSchema(ids=[attachment.id for attachment in attachments])
    return answer.model_dump(mode="json"), 201
