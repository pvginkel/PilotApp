"""A Session's records by REST, and its live frames on the browser's SSE
connection (design 2 §11.1; F40.3's stream).

Access is the API's `editor` gate. The stream routes subscribe only the
caller's own connection (SSE-6).
"""

import uuid
from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from spectree import Response as SpectreeResponse

from app.schemas.common import ApiErrorResponseSchema
from app.schemas.session_schema import (
    SessionRecordPageSchema,
    SessionRecordsQuerySchema,
    SessionStreamViewSchema,
)
from app.services.container import ServiceContainer
from app.services.session_record_service import SessionRecordService, to_record_schema
from app.services.session_stream_service import SessionStreamService
from app.utils.auth import get_auth_context
from app.utils.spectree_config import api

sessions_bp = Blueprint("sessions", __name__, url_prefix="/sessions")


def _caller_subject() -> str | None:
    auth_context = get_auth_context()
    return None if auth_context is None else auth_context.subject


@sessions_bp.route("/<uuid:session_id>/records", methods=["GET"])
@api.validate(
    query=SessionRecordsQuerySchema,
    resp=SpectreeResponse(
        HTTP_200=SessionRecordPageSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
    ),
)
@inject
def get_session_records(
    session_id: uuid.UUID,
    record_service: SessionRecordService = Provide[
        ServiceContainer.session_record_service
    ],
) -> Any:
    """A page of the Session's records after a record number, in order."""
    query = SessionRecordsQuerySchema.model_validate(request.args.to_dict())
    page = record_service.read_page(session_id, after=query.after, limit=query.limit)
    return SessionRecordPageSchema(
        records=[to_record_schema(stored) for stored in page.records],
        ended=page.ended,
    )


@sessions_bp.route("/<uuid:session_id>/stream", methods=["POST"])
@api.validate(
    json=SessionStreamViewSchema,
    resp=SpectreeResponse(
        HTTP_204=None,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def subscribe_session_stream(
    session_id: uuid.UUID,
    record_service: SessionRecordService = Provide[
        ServiceContainer.session_record_service
    ],
    stream_service: SessionStreamService = Provide[
        ServiceContainer.session_stream_service
    ],
) -> tuple[str, int]:
    """Open a view of the Session's live frames on the caller's SSE connection.

    Returns:
        204: The connection receives the frames written from now on
        409: This process holds no connection under `request_id`
        403: The connection is another user's
    """
    body = SessionStreamViewSchema.model_validate(request.get_json())
    record_service.require_session(session_id)
    stream_service.subscribe(session_id, body.request_id, body.view, _caller_subject())
    return "", 204


@sessions_bp.route("/<uuid:session_id>/stream", methods=["DELETE"])
@api.validate(
    json=SessionStreamViewSchema,
    resp=SpectreeResponse(
        HTTP_204=None,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
    ),
)
@inject
def unsubscribe_session_stream(
    session_id: uuid.UUID,
    record_service: SessionRecordService = Provide[
        ServiceContainer.session_record_service
    ],
    stream_service: SessionStreamService = Provide[
        ServiceContainer.session_stream_service
    ],
) -> tuple[str, int]:
    """Close a view; the connection's other views of the Session stay.
    Idempotent.

    Returns:
        204: The view is gone
        403: The connection is another user's
    """
    body = SessionStreamViewSchema.model_validate(request.get_json())
    record_service.require_session(session_id)
    stream_service.unsubscribe(
        session_id, body.request_id, body.view, _caller_subject()
    )
    return "", 204
