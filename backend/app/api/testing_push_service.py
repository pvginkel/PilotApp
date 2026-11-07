"""The fake push service, mounted for Playwright (TEST-1).

A subscription the mount issues has an endpoint under its own
`/api/testing/push-service`, so a backend pushes to it with no process added:
the push resources, and the fake's verbs as `/fake/<verb>`, are served under
that prefix. Guarded by reject_if_not_testing(): FLASK_ENV=testing on a stage
other than prd.
"""

from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from werkzeug.wrappers import Response

from app.services.container import ServiceContainer
from app.services.fake_push_service import FakePushService

PREFIX = "/api/testing/push-service"

testing_push_service_bp = Blueprint("testing_push_service", __name__, url_prefix=PREFIX)


@testing_push_service_bp.before_request
def check_testing_mode() -> Any:
    """Reject requests when the server is not running in testing mode."""
    from app.api.testing_guard import reject_if_not_testing

    return reject_if_not_testing()


@testing_push_service_bp.route("/<path:path>", methods=["POST"])
@inject
def serve_fake_push_service(
    path: str,
    fake_push_service: FakePushService = Provide[ServiceContainer.fake_push_service],
) -> Response:
    """The fake push service's answer to its route at `path`."""
    environ = dict(request.environ)
    environ["SCRIPT_NAME"] = request.script_root + PREFIX
    environ["PATH_INFO"] = f"/{path}"
    return Response.from_app(fake_push_service, environ)
