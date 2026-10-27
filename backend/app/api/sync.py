"""The store sidecar's sync routes (design 1 §5.1): the store's tree, path by
path and whole, its change stream and the hook's check, under the store's
bearer.

Registered on the app, not on `api_bp`, so the OIDC gate never sees them:
the bearer is the store, and every call passes the gate below first.
"""

import logging
import re
from collections.abc import Generator
from queue import Empty
from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, Response, g, jsonify, request
from spectree import Response as SpectreeResponse

from app.app_config import AppSettings
from app.engine.bus import TreeHashMoved
from app.engine.tree import ManifestEntry
from app.exceptions import SyncProtocolUnsupportedException, ValidationException
from app.schemas.common import ApiErrorResponseSchema
from app.schemas.sync_schema import (
    SyncChangeSchema,
    SyncCheckRequestSchema,
    SyncCheckResponseSchema,
    SyncHelloSchema,
    SyncManifestEntrySchema,
    SyncManifestRequestSchema,
    SyncManifestResponseSchema,
    SyncProtocolRangeSchema,
)
from app.services.container import ServiceContainer
from app.services.sync_service import SYNC_PROTOCOL_MAX, SYNC_PROTOCOL_MIN, SyncService
from app.services.sync_stream_service import SyncEvent, SyncStream, SyncStreamService
from app.utils.auth import public
from app.utils.spectree_config import api
from app.utils.sse_utils import create_sse_response, format_sse_event

logger = logging.getLogger(__name__)

sync_bp = Blueprint("sync", __name__, url_prefix="/api/sync")

_HASH = re.compile(r"[0-9a-f]{64}")

HEARTBEAT_FRAME = ": heartbeat\n\n"


@sync_bp.before_request
@inject
def admit_the_store(
    sync_service: SyncService = Provide[ServiceContainer.sync_service],
) -> None:
    """The gate every sync call passes: 401, 403 or 426 before anything is
    read or written; 502 when the store's Environment row is to be made and
    the controller does not report the store."""
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
        HTTP_502=ApiErrorResponseSchema,
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
    path, or `none`; `X-Pilot-Session`, the Session that held the write lock
    of the path's project folder as the sidecar read the file, left out when
    none held it: the save is that Session's when it is a brain session of
    the path's project, and no Session's otherwise. The body is the file's
    bytes, at most `SYNC_PUT_MAX_BYTES`.

    Answers 204 when the file needs no change, 200 with the bytes it must now
    hold when it does; either with `X-Pilot-Hash`, the hash the file holds
    once answered, and `X-Pilot-Faults`, the count of Save Errors the save
    raised on the path, and `X-Pilot-Stale: true` when the base hash was not
    the path's tree hash. 404 for a path of no syncing project.
    """
    base_hash = _base_hash(request.headers.get("X-Pilot-Base-Hash"))
    request.max_content_length = app_settings.sync_put_max_bytes
    answer = sync_service.put(
        path,
        request.get_data(),
        base_hash,
        request.headers.get("X-Pilot-Session"),
    )
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
        HTTP_502=ApiErrorResponseSchema,
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
        HTTP_502=ApiErrorResponseSchema,
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


@sync_bp.route("/check", methods=["POST"])
@public
@api.validate(
    json=SyncCheckRequestSchema,
    resp=SpectreeResponse(
        HTTP_200=SyncCheckResponseSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_426=SyncProtocolRangeSchema,
        HTTP_502=ApiErrorResponseSchema,
    ),
)
@inject
def check(
    sync_service: SyncService = Provide[ServiceContainer.sync_service],
) -> Any:
    """The hook's check of a project folder of the store's tree after a tool
    call that can write it (design 1 §5.6 step 3): the folder, once its
    sidecar has flushed it, in; the Save Errors under the folder and its
    project's deferrals without a home out, a folder of no syncing project
    answered its Save Errors alone. A `reverted` Save Error is answered once
    and deleted; a `parse` one stands until a clean save of its path."""
    body = SyncCheckRequestSchema.model_validate(request.get_json())
    answer = sync_service.check(body.folder, body.wait_seconds)
    response = SyncCheckResponseSchema.model_validate(answer, from_attributes=True)
    return jsonify(response.model_dump(mode="json")), 200


@sync_bp.route("/events", methods=["GET"])
@public
# No `@api.validate`: its response check reads the whole body, which a stream
# never ends.
@inject
def events(
    sync_service: SyncService = Provide[ServiceContainer.sync_service],
    sync_stream_service: SyncStreamService = Provide[
        ServiceContainer.sync_stream_service
    ],
    app_settings: AppSettings = Provide[ServiceContainer.app_config],
) -> Response:
    """The store's change stream (design 1 §5.4): `text/event-stream`.

    `hello` first, `{protocol: {min, max}, manifest_hash}`; then a `change`,
    `{path, hash}`, for every tree hash that moved once its transaction has
    committed, and a `manifest`, `{}`, whenever the set of syncing projects
    changed; a heartbeat comment after `SYNC_HEARTBEAT_SECONDS` idle. No
    `id:` field: the sidecar's hashes are its cursor. Ends on shutdown, and
    when the stream falls too far behind. Refused with 401, 403 or 426, and
    answered 502, as every sync call is.
    """
    hello = SyncHelloSchema(
        protocol=SyncProtocolRangeSchema(min=SYNC_PROTOCOL_MIN, max=SYNC_PROTOCOL_MAX),
        manifest_hash=sync_service.manifest_hash(),
    )
    stream = sync_stream_service.open()
    response = create_sse_response(
        _frames(
            sync_stream_service,
            stream,
            format_sse_event("hello", hello.model_dump()),
            app_settings.sync_heartbeat_seconds,
        )
    )
    # A body that never starts never runs the generator's `finally`.
    response.call_on_close(lambda: sync_stream_service.close(stream))
    return response


def _frames(
    sync_stream_service: SyncStreamService,
    stream: SyncStream,
    hello: str,
    heartbeat_seconds: float,
) -> Generator[str]:
    """The stream's body. It runs once Flask has popped the request context,
    so it touches the stream alone: no request, session or container."""
    try:
        if stream.ended:
            return
        yield hello
        while True:
            try:
                event = stream.next_event(heartbeat_seconds)
            except Empty:
                yield HEARTBEAT_FRAME
                continue
            if event is None:
                return
            yield _frame(event)
    finally:
        sync_stream_service.close(stream)


def _frame(event: SyncEvent) -> str:
    if isinstance(event, TreeHashMoved):
        change = SyncChangeSchema(path=event.path, hash=event.hash)
        return format_sse_event("change", change.model_dump())
    return format_sse_event("manifest", {})


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
