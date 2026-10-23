"""The store of the attachments' bytes (TD §8): put, get, delete."""

import hashlib
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.models import Attachment, Item, ItemAttachment, Project
from app.models.reference import AttachmentSource
from app.services.container import ServiceContainer

_CONTENT = b"# Palette\n\nThe two colours compared.\n"


def _copy(project: Project) -> Attachment:
    return Attachment(
        project_id=project.id,
        batch=1,
        title="Palette",
        filename="project.md",
        content_type="text/markdown",
        source_code=AttachmentSource.DRAFT,
        copied_at=datetime.now(UTC),
    )


class TestAttachmentStore:
    def test_put_keeps_it_with_its_bytes_their_size_and_sha256(
        self, container: ServiceContainer, session: DbSession, project: Project
    ) -> None:
        copy = _copy(project)

        container.attachment_store().put(copy, _CONTENT)

        session.expire_all()
        kept = session.get_one(Attachment, copy.id)
        assert (kept.size, kept.sha256) == (
            len(_CONTENT),
            hashlib.sha256(_CONTENT).hexdigest(),
        )
        assert container.attachment_store().get(kept) == _CONTENT

    def test_an_empty_file_is_kept(
        self, container: ServiceContainer, project: Project
    ) -> None:
        copy = _copy(project)

        container.attachment_store().put(copy, b"")

        assert (copy.size, copy.sha256) == (0, hashlib.sha256(b"").hexdigest())
        assert container.attachment_store().get(copy) == b""

    def test_get_reads_the_bytes_of_a_row_loaded_without_them(
        self, container: ServiceContainer, session: DbSession, project: Project
    ) -> None:
        container.attachment_store().put(_copy(project), _CONTENT)
        session.expunge_all()

        loaded = session.scalars(select(Attachment)).one()

        assert container.attachment_store().get(loaded) == _CONTENT

    def test_delete_takes_it_off_the_record(
        self, container: ServiceContainer, session: DbSession, project: Project
    ) -> None:
        store = container.attachment_store()
        copy = _copy(project)
        store.put(copy, _CONTENT)

        store.delete(copy)

        assert session.scalar(select(func.count()).select_from(Attachment)) == 0

    def test_delete_refuses_one_that_hangs_on_an_item(
        self,
        container: ServiceContainer,
        session: DbSession,
        project: Project,
        item: Item,
    ) -> None:
        store = container.attachment_store()
        copy = _copy(project)
        store.put(copy, _CONTENT)
        session.add(
            ItemAttachment(
                item_id=item.id,
                attachment_id=copy.id,
                position=1,
                attached_at=datetime.now(UTC),
            )
        )
        session.flush()

        with pytest.raises(IntegrityError) as raised:
            store.delete(copy)

        assert raised.value.orig is not None
        assert raised.value.orig.diag.constraint_name == (  # type: ignore[attr-defined]
            "item_attachments_attachment_id_fkey"
        )
