"""Where attachments keep their bytes (TD §8): in the record, `bytea` on the
attachment's own row. Every read and write of the bytes goes through
`AttachmentStore`, so another backend is a change to this module alone.

A file copied in is hung on its item, a draft's on nothing, by `AttachService`
(F36, DB decisions 39 and 40); at Create project the draft's copy and the
draft's material are hung on the opening (F18.1, DB decision 14).
"""

import hashlib
import mimetypes
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from pilot_dsl import parse
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.engine.bus import EngineBus, TreeHashMoved
from app.engine.paths import DRAFT, attachment_path, tree_path
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
    title, content_type = _typed(filename, content)
    return Copy(title, filename, content_type, content, source_path)


def _typed(filename: str, content: bytes) -> tuple[str, str]:
    """The title and the media type `copied` gives the file `filename`."""
    name = filename.rsplit("/", 1)[-1]
    content_type, encoding = _TYPES.guess_file_type(name)
    try:
        text: str | None = content.decode()
    except UnicodeDecodeError:
        text = None
    if content_type is None or encoding is not None:
        content_type = _BYTES if text is None else _PLAIN_TEXT
    title = parse(text).title if content_type == _MARKDOWN and text else None
    return title or name, content_type


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
        self,
        item: Item | None,
        session: AgentSession,
        copies: Sequence[Copy],
        *,
        environment_id: str,
    ) -> list[Attachment]:
        """`copies`, files `session` copied now from the environment
        `environment_id`, its own or one it names, kept as one batch, the next
        of `session`'s project, and hung on `item` after its own attachments,
        in their order, or on nothing without `item`: a draft's material,
        until Create project hangs it on the opening (F36.6, DB decision 40);
        their tree paths and the timeline moved once the transaction commits.

        Raises:
            ValidationException: a copy is over 16 MiB, nothing kept.
        """
        for copy in copies:
            if len(copy.content) > MAX_SIZE:
                raise ValidationException(
                    f"{copy.filename} is {len(copy.content)} bytes, over the "
                    f"{MAX_SIZE}-byte cap"
                )
        project = self._locked(session.project_id)
        now = self.db.scalar(select(func.now()))
        assert now is not None
        batch = self._next_batch(project)
        position = 0 if item is None else self._last_position(item)
        attachments: list[Attachment] = []
        for copy in copies:
            attachment = Attachment(
                project_id=project.id,
                batch=batch,
                title=copy.title,
                filename=copy.filename,
                content_type=copy.content_type,
                source_code=AttachmentSource.FILE,
                source_environment_id=environment_id,
                source_path=copy.source_path,
                copied_at=now,
                created_by_session_id=session.id,
            )
            self.attachment_store.put(attachment, copy.content)
            if item is not None:
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

    def hang(self, item: Item, attachments: Sequence[Attachment]) -> None:
        """`attachments`, already in the record, hung on `item` after its own
        attachments, in their order; the timeline moved once the transaction
        commits. None may hang on it already."""
        project = self._locked(item.project_id)
        now = self.db.scalar(select(func.now()))
        assert now is not None
        position = self._last_position(item)
        for attachment in attachments:
            position += 1
            self.db.add(
                ItemAttachment(
                    item_id=item.id,
                    attachment_id=attachment.id,
                    position=position,
                    attached_at=now,
                )
            )
        self.db.flush()
        self.view_service.timeline_moved(project)

    def attach_draft(self, item: Item, text: str) -> Attachment:
        """`text`, the draft as it stands, copied now as `project.md`, the
        next batch of the item's project, with no source and no session
        (Attachment Source `draft`, DB assertion 165), and hung on `item`
        after its own attachments: Create project's copy on the opening
        (F18.1, DB decision 14). Its tree path and the timeline move once the
        transaction commits."""
        project = self._locked(item.project_id)
        now = self.db.scalar(select(func.now()))
        assert now is not None
        content = text.encode()
        title, content_type = _typed(DRAFT, content)
        attachment = Attachment(
            project_id=project.id,
            batch=self._next_batch(project),
            title=title,
            filename=DRAFT,
            content_type=content_type,
            source_code=AttachmentSource.DRAFT,
            copied_at=now,
        )
        self.attachment_store.put(attachment, content)
        self.engine_bus.emit(
            TreeHashMoved(
                tree_path(project, attachment_path(attachment)), attachment.sha256
            )
        )
        self.hang(item, [attachment])
        return attachment

    def hang_unhung(self, item: Item) -> None:
        """Every attachment of the item's project that hangs on no item, the
        draft's material (F36.6), hung on `item` after its own attachments, by
        batch, then file name: Create project's, on the opening (F18.1)."""
        project = self._locked(item.project_id)
        self.hang(
            item,
            self.db.scalars(
                select(Attachment)
                .where(
                    Attachment.project_id == project.id,
                    ~exists().where(ItemAttachment.attachment_id == Attachment.id),
                )
                .order_by(Attachment.batch, Attachment.filename)
            ).all(),
        )

    def _locked(self, project_id: uuid.UUID) -> Project:
        """The project, its row held until the transaction ends: two attach
        calls of one project never take one batch."""
        return self.db.scalars(
            select(Project).where(Project.id == project_id).with_for_update()
        ).one()

    def _next_batch(self, project: Project) -> int:
        return 1 + (
            self.db.scalar(
                select(func.max(Attachment.batch)).where(
                    Attachment.project_id == project.id
                )
            )
            or 0
        )

    def _last_position(self, item: Item) -> int:
        return (
            self.db.scalar(
                select(func.max(ItemAttachment.position)).where(
                    ItemAttachment.item_id == item.id
                )
            )
            or 0
        )
