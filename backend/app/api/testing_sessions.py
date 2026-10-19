"""A session started in testing mode, for the live check against a real
controller (design 2 §13.2). No other route starts a session.

Guarded by reject_if_not_testing(): FLASK_ENV=testing on a stage other than
prd.
"""

from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from spectree import Response as SpectreeResponse
from sqlalchemy.orm import Session

from app.schemas.common import ApiErrorResponseSchema
from app.schemas.testing_sessions import (
    TestingSessionStartedSchema,
    TestingSessionStartSchema,
)
from app.services.container import ServiceContainer
from app.services.session_start_service import SessionOptions, SessionStartService
from app.utils.spectree_config import api

testing_sessions_bp = Blueprint(
    "testing_sessions", __name__, url_prefix="/api/testing/sessions"
)


@testing_sessions_bp.before_request
def check_testing_mode() -> Any:
    """Reject requests when the server is not running in testing mode."""
    from app.api.testing_guard import reject_if_not_testing

    return reject_if_not_testing()


@testing_sessions_bp.route("", methods=["POST"])
@api.validate(
    json=TestingSessionStartSchema,
    resp=SpectreeResponse(
        HTTP_201=TestingSessionStartedSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
        HTTP_502=ApiErrorResponseSchema,
    ),
)
@inject
def start_testing_session(
    session_starts: SessionStartService = Provide[
        ServiceContainer.session_start_service
    ],
    db: Session = Provide[ServiceContainer.db_session],
) -> tuple[dict[str, Any], int]:
    """Start a work Session for an existing project in an environment of the
    configured controller; its start runs once the request commits.

    Returns:
        201: The Session, `starting`
        404: No Project has the id
        409: No controller is configured
        502: The controller has no such environment, or failed
    """
    data = TestingSessionStartSchema.model_validate(request.get_json())
    session = session_starts.start_session(
        db,
        data.project_id,
        data.environment_id,
        kind_code="work",
        cwd=data.cwd,
        brief=data.brief,
        options=SessionOptions(
            agent=data.agent,
            model=data.model,
            reasoning_effort=data.reasoning_effort,
            resume=data.resume,
        ),
    )
    return TestingSessionStartedSchema(id=session.id).model_dump(mode="json"), 201
