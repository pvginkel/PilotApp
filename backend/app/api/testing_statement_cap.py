"""The statement cap's statements, for Playwright (app/utils/statement_cap.py):
a backend under STATEMENT_CAP keeps each statement it sends over its bound,
and each spec's teardown takes them (frontend/tests/support/fixtures.ts) and
fails on any. Guarded by reject_if_not_testing(): FLASK_ENV=testing on a
stage other than prd.
"""

from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from sqlalchemy import BindParameter, bindparam, text
from sqlalchemy.orm import Session

from app.exceptions import InvalidOperationException
from app.schemas.testing_statement_cap import StatementSendSchema
from app.services.container import ServiceContainer
from app.utils.statement_cap import StatementCap

PREFIX = "/api/testing/statement-cap"

testing_statement_cap_bp = Blueprint(
    "testing_statement_cap", __name__, url_prefix=PREFIX
)

# The statement `/send` pads to its length with the comment's dashes.
_HEAD = "SELECT 1 WHERE 1 IN :ids -- "


@testing_statement_cap_bp.before_request
def check_testing_mode() -> Any:
    """Reject requests when the server is not running in testing mode."""
    from app.api.testing_guard import reject_if_not_testing

    return reject_if_not_testing()


@testing_statement_cap_bp.route("/take", methods=["POST"])
@inject
def take_statements(
    statement_cap: StatementCap = Provide[ServiceContainer.statement_cap],
) -> Any:
    """The statements over their bound since the last take, each told with
    its length, where it was sent and its text, the cap keeping none.

    Refused where the cap is not installed, so that a backend without
    STATEMENT_CAP fails the spec rather than passing it unwatched.
    """
    if not statement_cap.installed:
        raise InvalidOperationException(
            "take the statement cap's statements", "STATEMENT_CAP is not set"
        )
    return {"statements": [long.describe() for long in statement_cap.drain()]}


@testing_statement_cap_bp.route("/send", methods=["POST"])
@inject
def send_statement(
    db_session: Session = Provide[ServiceContainer.db_session],
) -> Any:
    """Send one statement of `length` characters before SQLAlchemy expands
    it, its IN list of `ids` ids filled in as it is sent, for a spec of the
    cap: no route of the app's sends one over the cap.

    Returns:
        204: Sent
        400: A body with no length, or with no id
        409: A length below the shortest such statement's
    """
    data = StatementSendSchema.model_validate(request.get_json())
    ids: BindParameter[list[int]] = bindparam(
        "ids", value=list(range(data.ids)), expanding=True
    )
    head = text(_HEAD).bindparams(ids)
    shortest = len(head.compile(dialect=db_session.get_bind().dialect).string)
    if data.length < shortest:
        raise InvalidOperationException(
            f"send a statement of {data.length} characters",
            f"the shortest is {shortest}",
        )
    db_session.execute(
        text(_HEAD + "-" * (data.length - shortest)).bindparams(ids)
    ).all()
    return "", 204
