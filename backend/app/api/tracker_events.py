"""The tracker-events endpoint (F136.1): a tracker's post of a card's change of
state, under the tracker's own credential.

Registered on the app, not on `api_bp`, so the OIDC gate never sees it: the
caller is the tracker, which signs in to nothing.
"""

from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from spectree import Response as SpectreeResponse

from app.schemas.common import ApiErrorResponseSchema
from app.schemas.tracker_events import TrackerEventReplySchema
from app.services.container import ServiceContainer
from app.services.tracker_event_service import TrackerEventService
from app.utils.auth import public
from app.utils.spectree_config import api

tracker_events_bp = Blueprint(
    "tracker_events", __name__, url_prefix="/api/tracker-events"
)


@tracker_events_bp.route("/<tracker>", methods=["POST"])
@public
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=TrackerEventReplySchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
    )
)
@inject
def post_tracker_event(
    tracker: str,
    tracker_event_service: TrackerEventService = Provide[
        ServiceContainer.tracker_event_service
    ],
) -> Any:
    """A delivery of `tracker`'s, `youtrack` the one there is: the card waits
    the change of state it reports matches fire inside the request (F136.2).

    `youtrack`'s credential is the header `X-YouTrack-Token`, the instance's
    webhook token; its body the Webhook Triggers app's `issueUpdated`.
    Answers 200 with how many waits fired, none for a delivery that reports
    no change of State or matches no open card wait; 401 for a delivery
    without the token, and every delivery while none is configured; 400 for
    a body the tracker's adapter cannot read; 404 for no such tracker.
    """
    tracker_event_service.admit(tracker, request.headers)
    fired = tracker_event_service.take(tracker, request.get_data())
    return TrackerEventReplySchema(fired=fired).model_dump()
