"""An attachment's bytes as the screens read them (F28.5, F36), streamed by
its id from the store and served so that nothing in them runs in the app's
origin: inline only what a browser cannot run, everything else a download."""

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.engine.attachments import AttachmentStore
from app.exceptions import RecordNotFoundException
from app.models import Attachment

DOWNLOAD_TYPE = "application/octet-stream"
"""What a download is served as, whatever the attachment was stored as."""

PLAIN_TEXT = "text/plain"

RASTER_IMAGES = frozenset(
    {"image/avif", "image/bmp", "image/gif", "image/jpeg", "image/png", "image/webp"}
)
"""The image types served inline as themselves. An SVG is no raster image:
it can carry script."""


@dataclass(frozen=True)
class ServedAttachment:
    """What the stream answers for an attachment."""

    content: bytes
    content_type: str
    inline: bool
    filename: str


def served_inline(content_type: str) -> str | None:
    """The type an attachment stored as `content_type` is served inline as:
    a raster image as itself, text but HTML as plain text; none where it goes
    out as a download."""
    essence = content_type.partition(";")[0].strip().lower()
    if essence in RASTER_IMAGES:
        return essence
    if essence.startswith("text/") and essence != "text/html":
        return PLAIN_TEXT
    return None


class AttachmentService:
    def __init__(self, db: Session, attachment_store: AttachmentStore) -> None:
        self.db = db
        self.attachment_store = attachment_store

    def served(self, attachment_id: uuid.UUID) -> ServedAttachment:
        """The attachment as the stream serves it.

        Raises:
            RecordNotFoundException: no attachment has the id.
        """
        attachment = self.db.get(Attachment, attachment_id)
        if attachment is None:
            raise RecordNotFoundException("Attachment", str(attachment_id))
        inline = served_inline(attachment.content_type)
        return ServedAttachment(
            content=self.attachment_store.get(attachment),
            content_type=DOWNLOAD_TYPE if inline is None else inline,
            inline=inline is not None,
            filename=attachment.filename,
        )
