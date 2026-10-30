"""A person's overrule of the week's usage halt (F135.2; DB Quota Overrule):
the gold bar's button."""

from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from spectree import Response as SpectreeResponse

from app.api.caller import caller
from app.schemas.common import ApiErrorResponseSchema
from app.schemas.quota_overrules import QuotaOverruleRequestSchema, QuotaOverruleSchema
from app.services.container import ServiceContainer
from app.services.quota_overrule_service import QuotaOverruleService
from app.utils.spectree_config import api

quota_overrules_bp = Blueprint(
    "quota_overrules", __name__, url_prefix="/quota-overrules"
)


@quota_overrules_bp.route("", methods=["POST"])
@api.validate(
    json=QuotaOverruleRequestSchema,
    resp=SpectreeResponse(
        HTTP_201=QuotaOverruleSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def make_quota_overrule(
    quota_overrule_service: QuotaOverruleService = Provide[
        ServiceContainer.quota_overrule_service
    ],
) -> Any:
    """Overrule the week's usage halt, as the signed-in person, now.

    The allowance's target is the latest reading's week share plus the
    allowance, at most the second limit; run-out's is the wall. The overrule
    holds until a reading reaches its target or shows the share lower than
    the one before, or a stale reading's week is a minute past its reset;
    meanwhile the week's halt holds no work item, and every person's
    connections hear the conditions once it is made.

    Returns:
        201: The overrule, as made
        400: The kind is not an overrule's
        401: No one is signed in
        403: The caller lacks the editor role
        409: The caller has not chosen a handle, an overrule holds already,
            the week's halt does not hold, or it offers the other kind
    """
    body = QuotaOverruleRequestSchema.model_validate(request.get_json())
    made = quota_overrule_service.make(caller(), body.kind)
    return QuotaOverruleSchema(
        id=made.id, kind=made.kind_code, target=made.target, made_at=made.made_at
    ).model_dump(mode="json"), 201
