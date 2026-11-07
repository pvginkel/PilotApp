"""The pool guard's nestings, for Playwright (app/utils/pool_guard.py): a
backend under POOL_GUARD keeps each nesting its threads make, and each spec's
teardown takes them (frontend/tests/support/fixtures.ts) and fails on any.
Guarded by reject_if_not_testing(): FLASK_ENV=testing on a stage other than
prd.
"""

from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint

from app.exceptions import InvalidOperationException
from app.services.container import ServiceContainer
from app.utils.pool_guard import PoolGuard

PREFIX = "/api/testing/pool-guard"

testing_pool_guard_bp = Blueprint("testing_pool_guard", __name__, url_prefix=PREFIX)


@testing_pool_guard_bp.before_request
def check_testing_mode() -> Any:
    """Reject requests when the server is not running in testing mode."""
    from app.api.testing_guard import reject_if_not_testing

    return reject_if_not_testing()


@testing_pool_guard_bp.route("/take", methods=["POST"])
@inject
def take_nestings(
    pool_guard: PoolGuard = Provide[ServiceContainer.pool_guard],
) -> Any:
    """The nestings since the last take, each told with both its stacks, the
    guard keeping none.

    Refused where the guard is not installed, so that a backend without
    POOL_GUARD fails the spec rather than passing it unwatched.
    """
    if not pool_guard.installed:
        raise InvalidOperationException(
            "take the pool guard's nestings", "POOL_GUARD is not set"
        )
    return {"nestings": [nesting.describe() for nesting in pool_guard.drain()]}
