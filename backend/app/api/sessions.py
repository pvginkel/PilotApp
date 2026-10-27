"""A Session's records by REST, and its live frames on the browser's SSE
connection (design 2 §11.1; F40.3's stream); a work item's Stop and Resume
(F67).

Access is the API's `editor` gate. The stream routes subscribe only the
caller's own connection (SSE-6).
"""

import uuid
from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from spectree import Response as SpectreeResponse
from sqlalchemy.orm import Session

from app.api.caller import caller
from app.schemas.common import ApiErrorResponseSchema
from app.schemas.session_schema import (
    SessionRecordPageSchema,
    SessionRecordsQuerySchema,
    SessionStreamViewSchema,
)
from app.schemas.timeline import WorkSchema
from app.services.container import ServiceContainer
from app.services.people_service import PeopleService
from app.services.session_record_service import SessionRecordService, to_record_schema
from app.services.session_start_service import SessionStartService
from app.services.session_stream_service import SessionStreamService
from app.services.timeline_service import TimelineService
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


@sessions_bp.route("/<uuid:session_id>/stop", methods=["POST"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=WorkSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    )
)
@inject
def stop_session(
    session_id: uuid.UUID,
    record_service: SessionRecordService = Provide[
        ServiceContainer.session_record_service
    ],
    people_service: PeopleService = Provide[ServiceContainer.people_service],
    session_starts: SessionStartService = Provide[
        ServiceContainer.session_start_service
    ],
    timeline_service: TimelineService = Provide[ServiceContainer.timeline_service],
    db: Session = Provide[ServiceContainer.db_session],
) -> Any:
    """Stop the work item's session where it is, as the signed-in person: a
    turn in flight is interrupted, the conversation kept, and a start held or
    under way ends, nothing of it sent afterwards. The interrupt runs once the
    request commits; a controller that does not answer lets the turn run out.

    Returns:
        200: The work item's status, stopped
        401: No one is signed in
        403: The caller lacks the editor role
        404: No session has the id
        409: The caller has not chosen a handle; the session is no work
            item's, is Pilot's own, or is neither running, starting nor held
    """
    record_service.require_session(session_id)
    person = people_service.require_person(caller(), f"stop work item {session_id}")
    session_starts.stop(db, session_id, person)
    return timeline_service.work(session_id).model_dump(mode="json")


@sessions_bp.route("/<uuid:session_id>/resume", methods=["POST"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=WorkSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    )
)
@inject
def resume_session(
    session_id: uuid.UUID,
    session_starts: SessionStartService = Provide[
        ServiceContainer.session_start_service
    ],
    timeline_service: TimelineService = Provide[ServiceContainer.timeline_service],
    db: Session = Provide[ServiceContainer.db_session],
) -> Any:
    """Resume the stopped or failed work item: a turn of the server's own
    carries it on, "continue", or its last turn's message while it has no
    conversation, through the gate. It is held while the gate is closed;
    else its send runs once the request commits, its environment started
    again when it is not running. It stays one item.

    Returns:
        200: The work item's status, starting, or held at the gate
        401: No one is signed in
        403: The caller lacks the editor role
        404: No session has the id
        409: No controller is configured; the session is no work item's, is
            Pilot's own, is neither stopped nor failed, or has its stopped
            turn still ending; or its project is finished or archived
    """
    session_starts.resume(db, session_id)
    return timeline_service.work(session_id).model_dump(mode="json")
