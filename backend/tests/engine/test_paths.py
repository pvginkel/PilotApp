"""The tree's paths and the protocol's hash."""

import hashlib
import uuid
from datetime import UTC, datetime

from app.engine.paths import attachment_path, folder, sha256_hex, tree_path
from app.models import Attachment, Project
from app.models.reference import AttachmentSource


class TestPaths:
    def test_a_draft_projects_folder_is_its_number(self) -> None:
        project = Project(number=7, slug=None)

        assert folder(project) == "draft-7"
        assert tree_path(project, "project.md") == "draft-7/project.md"

    def test_an_opened_projects_folder_is_its_slug(self) -> None:
        project = Project(number=7, slug="badge-colours")

        assert folder(project) == "badge-colours"
        assert tree_path(project, "items/12-x.md") == "badge-colours/items/12-x.md"

    def test_an_attachment_is_under_its_batch(self) -> None:
        attachment = Attachment(
            id=uuid.uuid4(),
            batch=3,
            filename="notes/survey.md",
            source_code=AttachmentSource.DRAFT,
            copied_at=datetime.now(UTC),
        )

        assert attachment_path(attachment) == "attachments/3/notes/survey.md"

    def test_the_hash_is_of_the_utf8_bytes(self) -> None:
        text = "Groen — of blauw?\r\n"

        assert sha256_hex(text) == hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert sha256_hex("") == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )
