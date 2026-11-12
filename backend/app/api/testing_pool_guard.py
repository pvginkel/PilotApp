"""The pool guard's nestings, for Playwright (app/utils/pool_guard.py): a
backend under POOL_GUARD keeps each nesting its threads make, and each spec's
teardown takes them (frontend/tests/support/fixtures.ts) and fails on any;
and a nesting made for a spec of the guard. Guarded by
reject_if_not_testing(): FLASK_ENV=testing on a stage other than prd.
"""

from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.exceptions import InvalidOperationException
from app.extensions import db
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


@testing_pool_guard_bp.route("/nest", methods=["POST"])
@inject
def nest_checkouts(
    db_session: Session = Provide[ServiceContainer.db_session],
) -> Any:
    """Check out a second connection of the pool while the request's session
    holds one, for a spec of the guard: no route of the app's nests.

    Returns:
        204: Nested
    """
    db_session.execute(select(1)).all()
    with db.engine.connect() as second:
        second.execute(select(1)).all()
    return "", 204
