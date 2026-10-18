"""Attachment and Item Attachment: what a row must hold."""

import hashlib
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session as DbSession

from app.models import Attachment, Environment, Item, ItemAttachment, Project, Session
from app.models.reference import AttachmentSource
from tests.support.database import violated_constraint

_CONTENT = b"# Palette\n\nThe two colours compared.\n"


def _draft_copy(project: Project, **overrides: object) -> Attachment:
    values: dict[str, object] = {
        "project_id": project.id,
        "batch": 1,
        "title": "Palette",
        "filename": "project.md",
        "content_type": "text/markdown",
        "size": len(_CONTENT),
        "sha256": hashlib.sha256(_CONTENT).hexdigest(),
        "content": _CONTENT,
        "source_code": AttachmentSource.DRAFT,
        "copied_at": datetime.now(UTC),
    }
    values.update(overrides)
    return Attachment(**values)


class TestAttachment:
    def test_the_draft_copy_has_no_source(
        self, session: DbSession, project: Project
    ) -> None:
        copy = _draft_copy(project)
        session.add(copy)
        session.flush()
        session.expire(copy)

        assert copy.content == _CONTENT
        assert copy.source_environment_id is None

    def test_a_file_copy_has_its_source_and_session(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
    ) -> None:
        copy = _draft_copy(
            project,
            filename="docs/palette.md",
            source_code=AttachmentSource.FILE,
            source_environment_id=environment.id,
            source_path="/work/Example/docs/palette.md",
            created_by_session_id=project_session.id,
        )
        session.add(copy)
        session.flush()

        assert copy.source_code == AttachmentSource.FILE

    @pytest.mark.parametrize(
        "missing", ["source_environment_id", "source_path", "created_by_session_id"]
    )
    def test_a_file_copy_misses_none_of_them(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
        missing: str,
    ) -> None:
        source: dict[str, object] = {
            "source_environment_id": environment.id,
            "source_path": "/work/Example/docs/palette.md",
            "created_by_session_id": project_session.id,
        }
        del source[missing]
        session.add(_draft_copy(project, source_code=AttachmentSource.FILE, **source))

        assert violated_constraint(session) == "ck_attachments_source"

    def test_the_draft_copy_has_no_session(
        self, session: DbSession, project: Project, project_session: Session
    ) -> None:
        session.add(_draft_copy(project, created_by_session_id=project_session.id))

        assert violated_constraint(session) == "ck_attachments_source"

    def test_a_filename_is_unique_in_its_batch(
        self, session: DbSession, project: Project
    ) -> None:
        session.add_all([_draft_copy(project), _draft_copy(project)])

        assert (
            violated_constraint(session) == "attachments_project_id_batch_filename_key"
        )

    def test_batches_count_from_1(self, session: DbSession, project: Project) -> None:
        session.add(_draft_copy(project, batch=0))

        assert violated_constraint(session) == "ck_attachments_batch"


class TestItemAttachment:
    def test_an_attachment_hangs_on_an_item(
        self, session: DbSession, project: Project, item: Item
    ) -> None:
        copy = _draft_copy(project)
        session.add(copy)
        session.flush()
        hanging = ItemAttachment(
            item_id=item.id,
            attachment_id=copy.id,
            position=1,
            attached_at=datetime.now(UTC),
        )
        session.add(hanging)
        session.flush()

        assert hanging.position == 1

    def test_an_attachment_hangs_once_on_an_item(
        self, session: DbSession, project: Project, item: Item
    ) -> None:
        copy = _draft_copy(project)
        session.add(copy)
        session.flush()
        session.add(
            ItemAttachment(
                item_id=item.id,
                attachment_id=copy.id,
                position=1,
                attached_at=datetime.now(UTC),
            )
        )
        session.flush()
        session.expunge_all()
        session.add(
            ItemAttachment(
                item_id=item.id,
                attachment_id=copy.id,
                position=2,
                attached_at=datetime.now(UTC),
            )
        )

        assert violated_constraint(session) == "item_attachments_pkey"
