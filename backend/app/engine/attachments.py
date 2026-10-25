"""Where attachments keep their bytes (TD §8): in the record, `bytea` on the
attachment's own row. Every read and write of the bytes goes through
`AttachmentStore`, so another backend is a change to this module alone.

A file copied in is hung on its item by `AttachService` (F36, DB decision 39).
"""

import hashlib
import mimetypes
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine.bus import EngineBus, TreeHashMoved
from app.engine.dsl.reader import parse
from app.engine.paths import attachment_path, tree_path
from app.engine.views import ViewService
from app.exceptions import ValidationException
from app.models import Attachment, Item, ItemAttachment, Project
from app.models import Session as AgentSession
from app.models.reference import AttachmentSource

MAX_SIZE = 16 * 1024 * 1024
"""The largest attachment, in bytes: the controller's cap, where every
attachment comes from (TD §8), held where a file enters the record."""

MAX_CALL_SIZE = 64 * 1024 * 1024
"""The most bytes one attach call copies, its files' sizes summed: the call
holds every copy in memory until it commits."""

MAX_CALL_FILES = 1000
"""The most files one attach call copies: each is one read through the
controller, made while the call waits."""

_TYPES = mimetypes.MimeTypes()
"""Media types by extension from Python's own table alone, so a file is typed
alike in every image, whatever `/etc/mime.types` it holds."""

_MARKDOWN = "text/markdown"
_PLAIN_TEXT = "text/plain; charset=utf-8"
_BYTES = "application/octet-stream"


@dataclass(frozen=True)
class Copy:
    """A file a session copied from its environment, as its attachment keeps
    it."""

    title: str
    filename: str
    content_type: str
    content: bytes
    source_path: str


def copied(filename: str, source_path: str, content: bytes) -> Copy:
    """`content`, the file at `source_path`, as the attachment `filename`
    keeps it: typed by its extension, else plain text where it is UTF-8, else
    bytes; titled by a Markdown file's front matter `title`, else its first
    heading, else the file's name (F37.1, DB decision 32)."""
    name = filename.rsplit("/", 1)[-1]
    content_type, encoding = _TYPES.guess_file_type(name)
    try:
        text: str | None = content.decode()
    except UnicodeDecodeError:
        text = None
    if content_type is None or encoding is not None:
        content_type = _BYTES if text is None else _PLAIN_TEXT
    title = parse(text).title if content_type == _MARKDOWN and text else None
    return Copy(title or name, filename, content_type, content, source_path)


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


class AttachService:
    """Files copied into the record, hung on an item (F36, DB §7.4)."""

    def __init__(
        self,
        db: Session,
        attachment_store: AttachmentStore,
        engine_bus: EngineBus,
        view_service: ViewService,
    ) -> None:
        self.db = db
        self.attachment_store = attachment_store
        self.engine_bus = engine_bus
        self.view_service = view_service

    def attach(
        self, item: Item, session: AgentSession, copies: Sequence[Copy]
    ) -> list[Attachment]:
        """`copies`, files `session` copied from its environment now, kept as
        one batch, the project's next, and hung on `item` after its own
        attachments, in their order; their tree paths and the timeline moved
        once the transaction commits.

        Raises:
            ValidationException: a copy is over 16 MiB, nothing kept.
        """
        for copy in copies:
            if len(copy.content) > MAX_SIZE:
                raise ValidationException(
                    f"{copy.filename} is {len(copy.content)} bytes, over the "
                    f"{MAX_SIZE}-byte cap"
                )
        project = self.db.scalars(
            # Two attach calls of one project never take one batch.
            select(Project).where(Project.id == item.project_id).with_for_update()
        ).one()
        now = self.db.scalar(select(func.now()))
        assert now is not None
        batch = 1 + (
            self.db.scalar(
                select(func.max(Attachment.batch)).where(
                    Attachment.project_id == project.id
                )
            )
            or 0
        )
        position = (
            self.db.scalar(
                select(func.max(ItemAttachment.position)).where(
                    ItemAttachment.item_id == item.id
                )
            )
            or 0
        )
        attachments: list[Attachment] = []
        for copy in copies:
            attachment = Attachment(
                project_id=project.id,
                batch=batch,
                title=copy.title,
                filename=copy.filename,
                content_type=copy.content_type,
                source_code=AttachmentSource.FILE,
                source_environment_id=session.environment_id,
                source_path=copy.source_path,
                copied_at=now,
                created_by_session_id=session.id,
            )
            self.attachment_store.put(attachment, copy.content)
            position += 1
            self.db.add(
                ItemAttachment(
                    item_id=item.id,
                    attachment_id=attachment.id,
                    position=position,
                    attached_at=now,
                )
            )
            self.engine_bus.emit(
                TreeHashMoved(
                    tree_path(project, attachment_path(attachment)), attachment.sha256
                )
            )
            attachments.append(attachment)
        self.db.flush()
        self.view_service.timeline_moved(project)
        return attachments
