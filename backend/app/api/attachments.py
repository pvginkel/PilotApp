"""An attachment's bytes, streamed by its id (F28.5, F36; TD §8)."""

import io
import uuid
from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, send_file
from spectree import Response as SpectreeResponse

from app.schemas.common import ApiErrorResponseSchema
from app.services.attachment_service import AttachmentService
from app.services.container import ServiceContainer
from app.utils.spectree_config import api

attachments_bp = Blueprint("attachments", __name__, url_prefix="/attachments")


@attachments_bp.route("/<uuid:attachment_id>", methods=["GET"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=None,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
    )
)
@inject
def get_attachment(
    attachment_id: uuid.UUID,
    attachment_service: AttachmentService = Provide[
        ServiceContainer.attachment_service
    ],
) -> Any:
    """Stream an attachment's bytes, with its file's name and its length.

    A raster image is served inline as its type, text other than HTML inline
    as plain text; anything else, an SVG and HTML among it, as a download of
    `application/octet-stream`, whatever type it was stored with. The type is
    never sniffed.

    Returns:
        200: The bytes
        401: No one is signed in
        403: The caller lacks the editor role
        404: No attachment has the id
    """
    served = attachment_service.served(attachment_id)
    response = send_file(
        io.BytesIO(served.content),
        mimetype=served.content_type,
        as_attachment=not served.inline,
        download_name=served.filename,
        conditional=False,
        etag=False,
    )
    # spectree reads the body to validate the response, which a passthrough
    # body refuses.
    response.direct_passthrough = False
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
