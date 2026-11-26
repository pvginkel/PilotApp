"""The collector's routes (F152.2, F152.3, F152.6, F152.14): Pilot's
inventory, a publication of one transcript, the labeller's vocabularies and a
walk's end, under the collector's bearer.

Registered on the app, not on `api_bp`, so the OIDC gate never sees them:
the caller is a collector, which signs in to nothing, and every call passes
the gate below first.
"""

import logging
from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, Response, g, jsonify, request
from pilot_collection.inventory import InventorySchema
from pilot_collection.publication import CollectorProtocolRangeSchema, PublicationSchema
from pilot_collection.vocabularies import VocabulariesSchema
from spectree import Response as SpectreeResponse

from app.exceptions import CollectorProtocolUnsupportedException
from app.schemas.common import ApiErrorResponseSchema
from app.services.container import ServiceContainer
from app.services.publication_service import PublicationService
from app.services.vocabulary_service import VocabularyService
from app.services.walk_service import WalkService
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


@collector_bp.route("/inventory", methods=["GET"])
@public
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=InventorySchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_426=CollectorProtocolRangeSchema,
    ),
)
@inject
def inventory(
    publication_service: PublicationService = Provide[
        ServiceContainer.publication_service
    ],
) -> Any:
    """Pilot's inventory, which a collector asks for as each walk starts:
    what Pilot holds, whole, for the walk to compare the home against.

    Headers: `Authorization`, `Bearer` and the setting `COLLECTOR_TOKEN`;
    `X-Pilot-Collector-Protocol`, the protocol version the collector speaks.

    - 200: every transcript Pilot holds, a main thread's and a sub-agent's,
      each by its `session_id` and `agent_id` with its last publication's
      `file_size`, `file_modified_at` and collector's version, which are what
      an appended publication of it builds on, and its `replayed_size`; and
      the walk's two settings, `COLLECTOR_WALK_INTERVAL_SECONDS` and
      `COLLECTOR_SETTLING_SECONDS`. A transcript the home has and the answer
      lacks, or holds at another size, time or version, is one to publish;
      one whose `replayed_size` is short of its `file_size`, its file
      unchanged for the settling time, is published whole once.
    - 401: the call does not carry the collector's bearer, and every call
      while `COLLECTOR_TOKEN` is empty.
    - 426, with the range `{min, max}`: the call names a protocol version
      outside it, or none.
    """
    return publication_service.inventory()


@collector_bp.route("/publications", methods=["POST"])
@public
@api.validate(
    json=PublicationSchema,
    resp=SpectreeResponse(
        HTTP_204=None,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
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
    The body is the transcript as its file stands, read whole, or, with
    `appended`, what a file that grew holds from a boundary on.

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
    - 409, with the `code` `PUBLICATION_NOT_APPENDABLE`: an appended call
      does not continue what Pilot holds of the transcript, the reasons in
      `error`: Pilot does not hold it at the size and time and under the
      collector's version the call builds on, holds no row at a place before
      the boundary's, holds from there on, or before, what the call does
      not carry so, or holds at the boundary's `launch`, `prompt` or
      `compaction` another one than the call's first, told by its time; or
      its `labelling` does not continue the labels Pilot holds: they are
      under another stamp or none, or another major of the labeller's
      version, or its first Segment is neither the one the Call before the
      boundary falls in nor the next. The collector publishes the
      transcript whole.
    - 409, with the `code` `TRANSCRIPT_NOT_ADOPTABLE`: the call names a
      `group` for a transcript a session of Pilot's ran, which no adopted
      project adopts. The same call is refused again, and the call without
      its `group` is taken.
    - 409, with the `code` `NO_SERVICE_USER`: the call names a `group` no
      project holds yet, and the stage has no service user to make its
      adopted project. The same call is taken once the stage has one.
    - 413: the body is over `MAX_UPLOAD_SIZE_MB`. The same call is refused
      again.
    """
    publication = PublicationSchema.model_validate(request.get_json())
    publication_service.publish(publication)
    return Response(status=204)


@collector_bp.route("/vocabularies", methods=["PUT"])
@public
@api.validate(
    json=VocabulariesSchema,
    resp=SpectreeResponse(
        HTTP_204=None,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_413=ApiErrorResponseSchema,
        HTTP_426=CollectorProtocolRangeSchema,
    ),
)
@inject
def declare_vocabularies(
    vocabulary_service: VocabularyService = Provide[
        ServiceContainer.vocabulary_service
    ],
) -> Any:
    """The labeller's vocabularies, whole, as the labeller declares them:
    every list a label takes its value from, by the reference entity it
    fills, each value with its code, its name, its line, its place and the
    fact about its category where it has one; the Work Unit Kinds' nestings;
    and the labeller's version that declared them. One call, one
    transaction.

    Headers: `Authorization`, `Bearer` and the setting `COLLECTOR_TOKEN`;
    `X-Pilot-Collector-Protocol`, the protocol version the collector speaks.

    Each answer is the call's outcome, and all but the first leave the record
    as it was:

    - 204: Pilot holds every list and every nesting as the call declares
      them. A value or a nesting the call no longer declares is gone where
      no row names it, and kept where one does, a value with no place. The
      collector's values of Event Kind and Context Part Kind stand as they
      are.
    - 401: the call does not carry the collector's bearer, and every call
      while `COLLECTOR_TOKEN` is empty.
    - 426, with the range `{min, max}`: the call names a protocol version
      outside it, or none.
    - 400: the call does not validate, every fault named at once: the fields
      that are not the call's shape, a list the record has no place for among
      them, or, in `error`, what in the call contradicts itself: a code or a
      place given twice in a list, an Event Kind another entity records, or
      a nesting given twice or naming a Work Unit Kind the call does not
      declare. The same call is refused again.
    - 413: the body is over `MAX_UPLOAD_SIZE_MB`. The same call is refused
      again.
    """
    vocabularies = VocabulariesSchema.model_validate(request.get_json())
    vocabulary_service.declare(vocabularies)
    return Response(status=204)


@collector_bp.route("/walks", methods=["POST"])
@public
@api.validate(
    resp=SpectreeResponse(
        HTTP_204=None,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_426=CollectorProtocolRangeSchema,
    ),
)
@inject
def end_walk(
    walk_service: WalkService = Provide[ServiceContainer.walk_service],
) -> Any:
    """A walk's end, which a collector tells once per walk, after its last
    publication, whether the walk published anything or not. The call has no
    body.

    Headers: `Authorization`, `Bearer` and the setting `COLLECTOR_TOKEN`;
    `X-Pilot-Collector-Protocol`, the protocol version the collector speaks.

    - 204: the server stamped the walk at this moment, which the readiness
      check `collector` reads. Where a transcript was published since the
      walk before ended, every person's connections are sent one
      `collection_changed` event, its `as_of` this walk's end; a walk that
      published nothing raises none. A walk's end that does not arrive
      raises nothing either: what it would have announced, the next walk's
      end announces.
    - 401: the call does not carry the collector's bearer, and every call
      while `COLLECTOR_TOKEN` is empty.
    - 426, with the range `{min, max}`: the call names a protocol version
      outside it, or none.
    """
    walk_service.end()
    return Response(status=204)
