"""An attachment as the stream serves it: inline only what a browser cannot
run, everything else a download (F28.5, F36)."""

import uuid
from datetime import UTC, datetime

import pytest

from app.exceptions import RecordNotFoundException
from app.models import Attachment, Project
from app.models.reference import AttachmentSource
from app.services.attachment_service import ServedAttachment, served_inline
from app.services.container import ServiceContainer


def _kept(
    container: ServiceContainer, project: Project, content_type: str, content: bytes
) -> Attachment:
    copy = Attachment(
        project_id=project.id,
        batch=1,
        title="Palette",
        filename="palette.bin",
        content_type=content_type,
        source_code=AttachmentSource.DRAFT,
        copied_at=datetime.now(UTC),
    )
    container.attachment_store().put(copy, content)
    return copy


class TestServedInline:
    @pytest.mark.parametrize(
        ("stored", "served"),
        [
            ("image/png", "image/png"),
            ("image/jpeg", "image/jpeg"),
            ("image/gif", "image/gif"),
            ("image/webp", "image/webp"),
            ("image/avif", "image/avif"),
            ("image/bmp", "image/bmp"),
            ("text/plain", "text/plain"),
            ("text/markdown", "text/plain"),
            ("text/csv", "text/plain"),
            ("text/javascript", "text/plain"),
            ("text/plain; charset=latin-1", "text/plain"),
            ("Image/PNG", "image/png"),
            (" image/png ; name=x", "image/png"),
        ],
    )
    def test_a_raster_image_as_itself_and_text_as_plain_text(
        self, stored: str, served: str
    ) -> None:
        assert served_inline(stored) == served

    @pytest.mark.parametrize(
        "stored",
        [
            "image/svg+xml",
            "text/html",
            "TEXT/HTML; charset=utf-8",
            "application/xhtml+xml",
            "application/pdf",
            "application/javascript",
            "application/json",
            "application/octet-stream",
            "image/tiff",
            "not a type",
            "",
        ],
    )
    def test_anything_else_is_no_inline_type(self, stored: str) -> None:
        assert served_inline(stored) is None


class TestAttachmentService:
    def test_a_raster_image_is_served_inline_as_itself(
        self, container: ServiceContainer, project: Project
    ) -> None:
        copy = _kept(container, project, "image/png", b"\x89PNG")

        assert container.attachment_service().served(copy.id) == ServedAttachment(
            content=b"\x89PNG",
            content_type="image/png",
            inline=True,
            filename="palette.bin",
        )

    def test_text_is_served_inline_as_plain_text(
        self, container: ServiceContainer, project: Project
    ) -> None:
        copy = _kept(container, project, "text/markdown", b"# Palette\n")

        served = container.attachment_service().served(copy.id)

        assert (served.content_type, served.inline) == ("text/plain", True)

    @pytest.mark.parametrize(
        "stored", ["image/svg+xml", "text/html", "application/pdf"]
    )
    def test_anything_else_is_a_download_of_bytes(
        self, container: ServiceContainer, project: Project, stored: str
    ) -> None:
        copy = _kept(container, project, stored, b"<svg onload='x()'/>")

        served = container.attachment_service().served(copy.id)

        assert (served.content, served.content_type, served.inline) == (
            b"<svg onload='x()'/>",
            "application/octet-stream",
            False,
        )

    def test_an_unknown_id_is_not_found(self, container: ServiceContainer) -> None:
        attachment_id = uuid.uuid4()

        with pytest.raises(RecordNotFoundException) as raised:
            container.attachment_service().served(attachment_id)

        assert raised.value.message == f"Attachment {attachment_id} was not found"
