"""GET /api/attachments/<id>: an attachment's bytes, streamed, served so that
nothing in them runs in the app's origin (F28.5, F36; TD §8)."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app.models import Attachment, Project
from app.models.reference import AttachmentSource
from app.services.container import ServiceContainer

_PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256))


def _path(attachment_id: uuid.UUID | str) -> str:
    return f"/api/attachments/{attachment_id}"


def _kept(
    container: ServiceContainer,
    project: Project,
    filename: str,
    content_type: str,
    content: bytes,
) -> Attachment:
    copy = Attachment(
        project_id=project.id,
        batch=1,
        title="Sketch",
        filename=filename,
        content_type=content_type,
        source_code=AttachmentSource.DRAFT,
        copied_at=datetime.now(UTC),
    )
    container.attachment_store().put(copy, content)
    return copy


class TestGetAttachment:
    def test_a_raster_image_streams_inline_as_its_type(
        self, client: FlaskClient, container: ServiceContainer, project: Project
    ) -> None:
        copy = _kept(container, project, "sketch.png", "image/png", _PNG)

        response = client.get(_path(copy.id))

        assert response.status_code == 200
        assert response.data == _PNG
        assert {
            name: response.headers[name]
            for name in (
                "Content-Type",
                "Content-Length",
                "Content-Disposition",
                "X-Content-Type-Options",
            )
        } == {
            "Content-Type": "image/png",
            "Content-Length": str(len(_PNG)),
            "Content-Disposition": "inline; filename=sketch.png",
            "X-Content-Type-Options": "nosniff",
        }

    def test_text_streams_inline_as_plain_text(
        self, client: FlaskClient, container: ServiceContainer, project: Project
    ) -> None:
        content = b"# Sketch\n\nTwo columns, then one.\n"
        copy = _kept(container, project, "sketch.md", "text/markdown", content)

        response = client.get(_path(copy.id))

        assert response.data == content
        assert (
            response.headers["Content-Type"],
            response.headers["Content-Disposition"],
            response.headers["X-Content-Type-Options"],
        ) == ("text/plain; charset=utf-8", "inline; filename=sketch.md", "nosniff")

    @pytest.mark.parametrize(
        ("filename", "stored"),
        [
            ("sketch.svg", "image/svg+xml"),
            ("sketch.html", "text/html"),
            ("sketch.pdf", "application/pdf"),
        ],
    )
    def test_anything_else_downloads_as_bytes(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        project: Project,
        filename: str,
        stored: str,
    ) -> None:
        content = b"<svg xmlns='http://www.w3.org/2000/svg' onload='alert(1)'/>"
        copy = _kept(container, project, filename, stored, content)

        response = client.get(_path(copy.id))

        assert response.status_code == 200
        assert response.data == content
        assert (
            response.headers["Content-Type"],
            response.headers["Content-Disposition"],
            response.headers["X-Content-Type-Options"],
        ) == ("application/octet-stream", f"attachment; filename={filename}", "nosniff")

    def test_a_name_beyond_ascii_travels_encoded(
        self, client: FlaskClient, container: ServiceContainer, project: Project
    ) -> None:
        copy = _kept(container, project, "schéma.png", "image/png", _PNG)

        response = client.get(_path(copy.id))

        assert response.headers["Content-Disposition"] == (
            "inline; filename=schema.png; filename*=UTF-8''sch%C3%A9ma.png"
        )

    def test_an_unknown_id_is_not_found(self, client: FlaskClient) -> None:
        attachment_id = uuid.uuid4()

        response = client.get(_path(attachment_id))

        assert response.status_code == 404
        assert response.get_json()["error"] == (
            f"Attachment {attachment_id} was not found"
        )


class TestTheSignIn:
    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.get(_path(uuid.uuid4())).status_code == 401

    def test_without_editor_it_is_refused(
        self, oidc_client: FlaskClient, generate_test_jwt: Any
    ) -> None:
        token = generate_test_jwt(roles=["reader"])

        response = oidc_client.get(
            _path(uuid.uuid4()), headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 403

    def test_an_editor_is_answered(
        self, oidc_app: Flask, oidc_client: FlaskClient, generate_test_jwt: Any
    ) -> None:
        token = generate_test_jwt(roles=["editor"])

        response = oidc_client.get(
            _path(uuid.uuid4()), headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 404
