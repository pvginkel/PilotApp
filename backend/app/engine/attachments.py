"""Where attachments keep their bytes (TD §8): in the record, `bytea` on the
attachment's own row. Every read and write of the bytes goes through
`AttachmentStore`, so another backend is a change to this module alone."""

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Attachment

MAX_SIZE = 16 * 1024 * 1024
"""The largest attachment, in bytes: the controller's cap, where every
attachment comes from (TD §8), held where a file enters the record."""


class AttachmentStore:
    """The attachments of the record, with their bytes."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def put(self, attachment: Attachment, content: bytes) -> None:
        """Keep `attachment`, a row not yet on the record, with `content` as
        its bytes, and their size and sha256 (DB §7.4)."""
        attachment.content = content
        attachment.size = len(content)
        attachment.sha256 = hashlib.sha256(content).hexdigest()
        self.db.add(attachment)
        self.db.flush()

    def get(self, attachment: Attachment) -> bytes:
        """The attachment's bytes."""
        return self.db.scalars(
            select(Attachment.content).where(Attachment.id == attachment.id)
        ).one()

    def delete(self, attachment: Attachment) -> None:
        """Take the attachment off the record with its bytes. It must hang on
        no item: an Item Attachment holds its row."""
        self.db.delete(attachment)
        self.db.flush()
