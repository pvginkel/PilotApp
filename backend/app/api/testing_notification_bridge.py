"""The fake notification bridge, mounted for Playwright (the Q1 ruling).

A backend whose NOTIFICATION_BRIDGE_URL is its own
`/api/testing/notification-bridge` drives the fake with no process added: the
bridge's routes, and the fake's verbs as `/fake/<verb>`, are served under that
prefix. Guarded by reject_if_not_testing(): FLASK_ENV=testing on a stage other
than prd.
"""

from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from werkzeug.wrappers import Response

from app.services.container import ServiceContainer
from app.services.fake_notification_bridge import FakeNotificationBridge

PREFIX = "/api/testing/notification-bridge"

testing_notification_bridge_bp = Blueprint(
    "testing_notification_bridge", __name__, url_prefix=PREFIX
)


@testing_notification_bridge_bp.before_request
def check_testing_mode() -> Any:
    """Reject requests when the server is not running in testing mode."""
    from app.api.testing_guard import reject_if_not_testing

    return reject_if_not_testing()


@testing_notification_bridge_bp.route("/<path:path>", methods=["GET", "POST"])
@inject
def serve_fake_notification_bridge(
    path: str,
    fake_notification_bridge: FakeNotificationBridge = Provide[
        ServiceContainer.fake_notification_bridge
    ],
) -> Response:
    """The fake notification bridge's answer to its route at `path`."""
    environ = dict(request.environ)
    environ["SCRIPT_NAME"] = request.script_root + PREFIX
    environ["PATH_INFO"] = f"/{path}"
    return Response.from_app(fake_notification_bridge, environ)
