"""The fake collector, mounted for Playwright (F122.5).

A backend whose COLLECTOR_URL is its own `/api/testing/collector` reads a
conversation's reading from the fake with no process added: the collector's
readings route, and the fake's verbs as `/fake/<verb>`, are served under that
prefix. Guarded by reject_if_not_testing(): FLASK_ENV=testing on a stage
other than prd.
"""

from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from werkzeug.wrappers import Response

from app.services.container import ServiceContainer
from app.services.fake_collector import FakeCollector

PREFIX = "/api/testing/collector"

testing_collector_bp = Blueprint("testing_collector", __name__, url_prefix=PREFIX)


@testing_collector_bp.before_request
def check_testing_mode() -> Any:
    """Reject requests when the server is not running in testing mode."""
    from app.api.testing_guard import reject_if_not_testing

    return reject_if_not_testing()


@testing_collector_bp.route("/<path:path>", methods=["GET", "POST"])
@inject
def serve_fake_collector(
    path: str,
    fake_collector: FakeCollector = Provide[ServiceContainer.fake_collector],
) -> Response:
    """The fake collector's answer to its route at `path`."""
    environ = dict(request.environ)
    environ["SCRIPT_NAME"] = request.script_root + PREFIX
    environ["PATH_INFO"] = f"/{path}"
    return Response.from_app(fake_collector, environ)
