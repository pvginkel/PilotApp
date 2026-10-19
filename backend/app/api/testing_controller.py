"""The fake KubeCoder controller, mounted for Playwright (design 2 §12).

A backend whose CONTROLLER_URL is its own `/api/testing/controller` drives the
fake with no process added: the controller's routes, and the fake's verbs as
`/fake/<verb>`, are served under that prefix. Guarded by
reject_if_not_testing(): FLASK_ENV=testing on a stage other than prd.
"""

from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from werkzeug.wrappers import Response

from app.services.container import ServiceContainer
from app.services.fake_controller import FakeController

PREFIX = "/api/testing/controller"

testing_controller_bp = Blueprint("testing_controller", __name__, url_prefix=PREFIX)


@testing_controller_bp.before_request
def check_testing_mode() -> Any:
    """Reject requests when the server is not running in testing mode."""
    from app.api.testing_guard import reject_if_not_testing

    return reject_if_not_testing()


@testing_controller_bp.route("/<path:path>", methods=["GET", "POST", "DELETE"])
@inject
def serve_fake_controller(
    path: str,
    fake_controller: FakeController = Provide[ServiceContainer.fake_controller],
) -> Response:
    """The fake controller's answer to its route at `path`, streams included."""
    environ = dict(request.environ)
    environ["SCRIPT_NAME"] = request.script_root + PREFIX
    environ["PATH_INFO"] = f"/{path}"
    return Response.from_app(fake_controller, environ)
