"""The collector's routes (F152.3): a publication of one transcript, under the
collector's bearer.

Registered on the app, not on `api_bp`, so the OIDC gate never sees them:
the caller is a collector, which signs in to nothing, and every call passes
the gate below first.
"""

import logging
from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, Response, g, jsonify, request
from spectree import Response as SpectreeResponse

from app.exceptions import CollectorProtocolUnsupportedException
from app.schemas.common import ApiErrorResponseSchema
from app.schemas.publication import CollectorProtocolRangeSchema, PublicationSchema
from app.services.container import ServiceContainer
from app.services.publication_service import PublicationService
from app.utils.auth import public
from app.utils.spectree_config import api

logger = logging.getLogger(__name__)

collector_bp = Blueprint("collector", __name__, url_prefix="/api/collector")


@collector_bp.before_request
@inject
def admit_the_collector(
    publication_service: PublicationService = Provide[
        ServiceContainer.publication_service
    ],
) -> None:
    """The gate every call of a collector's passes: 401 or 426 before
    anything is read or written."""
    publication_service.admit(
        request.headers.get("Authorization"),
        request.headers.get("X-Pilot-Collector-Protocol"),
    )


@collector_bp.errorhandler(CollectorProtocolUnsupportedException)
def answer_the_protocol_range(
    error: CollectorProtocolUnsupportedException,
) -> tuple[Response, int]:
    g.needs_rollback = True
    logger.warning("Collector's call refused: %s", error.message)
    body = CollectorProtocolRangeSchema(min=error.minimum, max=error.maximum)
    return jsonify(body.model_dump()), 426


@collector_bp.route("/publications", methods=["POST"])
@public
@api.validate(
    json=PublicationSchema,
    resp=SpectreeResponse(
        HTTP_204=None,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_413=ApiErrorResponseSchema,
        HTTP_426=CollectorProtocolRangeSchema,
    ),
)
@inject
def publish(
    publication_service: PublicationService = Provide[
        ServiceContainer.publication_service
    ],
) -> Any:
    """A collector's publication of one transcript, a main thread's or one
    sub-agent's: one call, one transaction.

    Headers: `Authorization`, `Bearer` and the setting `COLLECTOR_TOKEN`;
    `X-Pilot-Collector-Protocol`, the protocol version the collector speaks.
    The body is the transcript as its file stands.

    Each answer is the call's outcome, and all but the first leave the record
    as it was:

    - 204: Pilot holds the transcript as the call says.
    - 401: the call does not carry the collector's bearer, and every call
      while `COLLECTOR_TOKEN` is empty. No call of this collector's is taken
      until its bearer is the server's.
    - 426, with the range `{min, max}`: the call names a protocol version
      outside it, or none. No call is taken until the collector speaks a
      version in the range.
    - 400: the call does not validate, every fault named at once: the fields
      that are not the call's shape, or, in `error`, what in the call
      contradicts itself or the record's rules for a transcript. The same
      call is refused again; the collector's other transcripts are not.
    - 413: the body is over `MAX_UPLOAD_SIZE_MB`. The same call is refused
      again.
    """
    publication = PublicationSchema.model_validate(request.get_json())
    publication_service.publish(publication)
    return Response(status=204)
