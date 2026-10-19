"""The store sidecar's sync routes (design 1 §5.1): the store's tree, path by
path and whole, under the store's bearer.

Registered on the app, not on `api_bp`, so the OIDC gate never sees them:
the bearer is the store, and every call passes the gate below first.
"""

import logging
import re
from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, Response, g, jsonify, request
from spectree import Response as SpectreeResponse

from app.app_config import AppSettings
from app.engine.tree import ManifestEntry
from app.exceptions import SyncProtocolUnsupportedException, ValidationException
from app.schemas.common import ApiErrorResponseSchema
from app.schemas.sync_schema import (
    SyncManifestEntrySchema,
    SyncManifestRequestSchema,
    SyncManifestResponseSchema,
    SyncProtocolRangeSchema,
)
from app.services.container import ServiceContainer
from app.services.sync_service import SyncService
from app.utils.auth import public
from app.utils.spectree_config import api

logger = logging.getLogger(__name__)

sync_bp = Blueprint("sync", __name__, url_prefix="/api/sync")

_HASH = re.compile(r"[0-9a-f]{64}")


@sync_bp.before_request
@inject
def admit_the_store(
    sync_service: SyncService = Provide[ServiceContainer.sync_service],
) -> None:
    """The gate every sync call passes: 401, 403 or 426 before anything is
    read or written."""
    sync_service.admit(
        request.headers.get("Authorization"),
        request.headers.get("X-Pilot-Environment"),
        request.headers.get("X-Pilot-Sync-Protocol"),
    )


@sync_bp.errorhandler(SyncProtocolUnsupportedException)
def answer_the_protocol_range(
    error: SyncProtocolUnsupportedException,
) -> tuple[Response, int]:
    g.needs_rollback = True
    logger.warning("Sync call refused: %s", error.message)
    body = SyncProtocolRangeSchema(min=error.minimum, max=error.maximum)
    return jsonify(body.model_dump()), 426


@sync_bp.route("/files/<path:path>", methods=["PUT"])
@public
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=None,
        HTTP_204=None,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_413=ApiErrorResponseSchema,
        HTTP_426=SyncProtocolRangeSchema,
    )
)
@inject
def put_file(
    path: str,
    sync_service: SyncService = Provide[ServiceContainer.sync_service],
    app_settings: AppSettings = Provide[ServiceContainer.app_config],
) -> Any:
    """The store's save of a file of its tree (design 1 §5.3).

    Headers: `X-Pilot-Base-Hash`, the hash the sidecar last synced for the
    path, or `none`. The body is the file's bytes, at most
    `SYNC_PUT_MAX_BYTES`.

    Answers 204 when the file needs no change, 200 with the bytes it must now
    hold when it does; either with `X-Pilot-Hash`, the hash the file holds
    once answered, and `X-Pilot-Faults`, the count of Save Errors the save
    raised on the path, and `X-Pilot-Stale: true` when the base hash was not
    the path's tree hash. 404 for a path of no syncing project.
    """
    base_hash = _base_hash(request.headers.get("X-Pilot-Base-Hash"))
    request.max_content_length = app_settings.sync_put_max_bytes
    answer = sync_service.put(path, request.get_data(), base_hash)
    headers = {"X-Pilot-Hash": answer.hash, "X-Pilot-Faults": str(len(answer.faults))}
    if answer.stale:
        headers["X-Pilot-Stale"] = "true"
    if answer.content is None:
        return Response(status=204, headers=headers)
    return Response(
        answer.content,
        status=200,
        headers=headers,
        mimetype="application/octet-stream",
    )


@sync_bp.route("/files/<path:path>", methods=["GET"])
@public
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=None,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_426=SyncProtocolRangeSchema,
    )
)
@inject
def get_file(
    path: str,
    sync_service: SyncService = Provide[ServiceContainer.sync_service],
) -> Any:
    """The bytes a file of the store's tree must hold, with their hash as
    `X-Pilot-Hash`. 404 for a path of no syncing project."""
    file = sync_service.get(path)
    return Response(
        file.content,
        status=200,
        headers={"X-Pilot-Hash": file.hash},
        mimetype="application/octet-stream",
    )


@sync_bp.route("/manifest", methods=["POST"])
@public
@api.validate(
    json=SyncManifestRequestSchema,
    resp=SpectreeResponse(
        HTTP_200=SyncManifestResponseSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_426=SyncProtocolRangeSchema,
    ),
)
@inject
def reconcile(
    sync_service: SyncService = Provide[ServiceContainer.sync_service],
) -> Any:
    """The manifest reconcile (design 1 §5.5 step 2): the store's tree as
    its sidecar sees it in, the manifest and the three lists that make the
    tree match it out."""
    body = SyncManifestRequestSchema.model_validate(request.get_json())
    answer = sync_service.reconcile(body.tree, body.shadow)
    response = SyncManifestResponseSchema(
        manifest=[_entry(entry) for entry in answer.manifest],
        send_up=answer.send_up,
        write_down=[_entry(entry) for entry in answer.write_down],
        delete=answer.delete,
    )
    return jsonify(response.model_dump()), 200


def _entry(entry: ManifestEntry) -> SyncManifestEntrySchema:
    return SyncManifestEntrySchema(
        path=entry.path, hash=entry.hash, readonly=entry.readonly
    )


def _base_hash(value: str | None) -> str | None:
    if value == "none":
        return None
    if value is None or not _HASH.fullmatch(value):
        raise ValidationException(
            "X-Pilot-Base-Hash must be a sha256 in lowercase hex, or none"
        )
    return value
