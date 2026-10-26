"""The store of the attachments' bytes (TD §8): put, get, delete; a file
copied in, and the copies hung on an item as one batch (F36, DB decision
39)."""

import functools
import hashlib
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.engine.attachments import MAX_SIZE, Copy, copied
from app.engine.bus import EngineEvent, ProjectChanged, TreeHashMoved
from app.engine.tree import TreeFile
from app.exceptions import ValidationException
from app.models import Attachment, Environment, Item, ItemAttachment, Project
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


def _hung(session: DbSession, item: Item) -> list[tuple[int, int, str]]:
    """The item's attachments in order: position, batch and filename."""
    return [
        (position, batch, filename)
        for position, batch, filename in session.execute(
            select(ItemAttachment.position, Attachment.batch, Attachment.filename)
            .join(Attachment, Attachment.id == ItemAttachment.attachment_id)
            .where(ItemAttachment.item_id == item.id)
            .order_by(ItemAttachment.position)
        )
    ]


def _file(filename: str, content: bytes = b"A") -> Copy:
    return Copy(
        "A file", filename, "text/markdown", content, f"/work/Example/{filename}"
    )


class TestCopied:
    @pytest.mark.parametrize(
        ("filename", "content", "content_type"),
        [
            ("notes.md", b"# Notes\n", "text/markdown"),
            ("survey/data.json", b"{}", "application/json"),
            ("sketch.png", b"\x89PNG\r\n", "image/png"),
            ("session.jsonl", b'{"type": "user"}\n', "text/plain; charset=utf-8"),
            ("README", b"Read me.\n", "text/plain; charset=utf-8"),
            ("blob", b"\xff\xfe\x00", "application/octet-stream"),
            ("logs.tar.gz", b"\x1f\x8b\x08", "application/octet-stream"),
        ],
    )
    def test_it_is_typed_by_its_extension_else_as_text_or_bytes(
        self, filename: str, content: bytes, content_type: str
    ) -> None:
        assert copied(filename, f"/work/Example/{filename}", content).content_type == (
            content_type
        )

    @pytest.mark.parametrize(
        ("filename", "content", "title"),
        [
            ("notes.md", b"---\ntitle: Camp notes\n---\n\n# Notes\n", "Camp notes"),
            ("notes.md", b"Intro.\n\n# Camp notes\n\n## Tents\n", "Camp notes"),
            ("survey/notes.md", b"No heading.\n", "notes.md"),
            ("notes.md", b"", "notes.md"),
            ("notes.md", b"# Caf\xe9\n", "notes.md"),
            ("survey/data.json", b'{"title": "x"}', "data.json"),
            ("README", b"# Read me\n", "README"),
        ],
    )
    def test_a_markdown_files_title_is_its_own_else_the_files_name(
        self, filename: str, content: bytes, title: str
    ) -> None:
        assert copied(filename, f"/work/Example/{filename}", content).title == title

    def test_it_keeps_its_name_its_source_and_its_bytes(self) -> None:
        assert copied(
            "survey/notes.md", "/work/Example/docs/survey/notes.md", b"# Notes\n"
        ) == Copy(
            "Notes",
            "survey/notes.md",
            "text/markdown",
            b"# Notes\n",
            "/work/Example/docs/survey/notes.md",
        )


class TestAttachService:
    def test_each_copy_is_kept_with_its_source_and_its_session(
        self,
        container: ServiceContainer,
        session: DbSession,
        item: Item,
        project_session: models.Session,
        environment: Environment,
    ) -> None:
        [attachment] = container.attach_service().attach(
            item,
            project_session,
            [Copy("Notes", "notes.md", "text/markdown", _CONTENT, "/work/A/notes.md")],
            environment_id=environment.id,
        )

        now = session.scalar(select(func.now()))
        assert (
            attachment.title,
            attachment.filename,
            attachment.content_type,
            attachment.size,
            attachment.sha256,
            attachment.source_code,
            attachment.source_environment_id,
            attachment.source_path,
            attachment.copied_at,
            attachment.created_by_session_id,
        ) == (
            "Notes",
            "notes.md",
            "text/markdown",
            len(_CONTENT),
            hashlib.sha256(_CONTENT).hexdigest(),
            AttachmentSource.FILE,
            environment.id,
            "/work/A/notes.md",
            now,
            project_session.id,
        )
        assert container.attachment_store().get(attachment) == _CONTENT
        hung = session.get_one(ItemAttachment, (item.id, attachment.id))
        assert hung.attached_at == now

    def test_one_call_is_one_batch_the_projects_next_after_the_items_own(
        self,
        container: ServiceContainer,
        session: DbSession,
        project: Project,
        item: Item,
        project_session: models.Session,
        environment: Environment,
    ) -> None:
        other = Item(
            project_id=project.id,
            seq=2,
            kind_code="notice",
            title="Tents",
            created_by_session_id=project_session.id,
        )
        session.add(other)
        session.flush()
        attach = functools.partial(
            container.attach_service().attach, environment_id=environment.id
        )

        attach(item, project_session, [_file("a.md"), _file("b/c.md")])
        attach(item, project_session, [_file("a.md")])
        attach(other, project_session, [_file("d.md")])

        assert _hung(session, item) == [
            (1, 1, "a.md"),
            (2, 1, "b/c.md"),
            (3, 2, "a.md"),
        ]
        assert _hung(session, other) == [(1, 3, "d.md")]

    def test_the_tree_holds_them_and_the_timeline_lists_them(
        self,
        container: ServiceContainer,
        project: Project,
        item: Item,
        project_session: models.Session,
        environment: Environment,
    ) -> None:
        attachments = container.attach_service().attach(
            item,
            project_session,
            [_file("a.md", b"A"), _file("survey/b.md", b"B")],
            environment_id=environment.id,
        )

        folder = f"draft-{project.number}"
        assert [
            container.tree_service().resolve(f"{folder}/attachments/1/{name}")
            for name in ("a.md", "survey/b.md")
        ] == [
            TreeFile(b"A", hashlib.sha256(b"A").hexdigest()),
            TreeFile(b"B", hashlib.sha256(b"B").hexdigest()),
        ]
        timeline = json.loads(container.view_service().timeline(project).text)
        [entry] = [entry for entry in timeline["items"] if entry["attachments"]]
        assert entry["attachments"] == [
            {"id": str(attachment.id), "path": f"attachments/1/{attachment.filename}"}
            for attachment in attachments
        ]

    def test_their_paths_and_the_timeline_move_after_the_commit(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        item: Item,
        project_session: models.Session,
        environment: Environment,
    ) -> None:
        with scoped_session(container):
            attachments = container.attach_service().attach(
                item,
                project_session,
                [_file("a.md", b"A"), _file("b.md", b"B")],
                environment_id=environment.id,
            )
            assert engine_events == []

        folder = f"draft-{project.number}"
        assert engine_events == [
            TreeHashMoved(f"{folder}/attachments/1/a.md", attachments[0].sha256),
            TreeHashMoved(f"{folder}/attachments/1/b.md", attachments[1].sha256),
            TreeHashMoved(
                f"{folder}/timeline.json",
                container.view_service().timeline(project).hash,
            ),
            ProjectChanged(project.id),
        ]

    def test_a_copy_over_16_mib_is_refused_and_none_kept(
        self,
        container: ServiceContainer,
        session: DbSession,
        item: Item,
        project_session: models.Session,
        environment: Environment,
    ) -> None:
        over = MAX_SIZE + 1

        with pytest.raises(ValidationException) as raised:
            container.attach_service().attach(
                item,
                project_session,
                [_file("a.md"), _file("big.bin", bytes(over))],
                environment_id=environment.id,
            )

        assert raised.value.message == (
            f"big.bin is {over} bytes, over the 16777216-byte cap"
        )
        assert session.scalars(select(Attachment)).all() == []

    def test_a_copy_of_exactly_16_mib_is_kept(
        self,
        container: ServiceContainer,
        item: Item,
        project_session: models.Session,
        environment: Environment,
    ) -> None:
        [attachment] = container.attach_service().attach(
            item,
            project_session,
            [_file("big.bin", bytes(MAX_SIZE))],
            environment_id=environment.id,
        )

        assert attachment.size == MAX_SIZE

    def test_copies_from_an_environment_the_session_names_keep_it_as_their_source(
        self,
        container: ServiceContainer,
        session: DbSession,
        item: Item,
        project_session: models.Session,
    ) -> None:
        elsewhere = Environment(
            id="example-elsewhere", name="Elsewhere-1", exempt=False
        )
        session.add(elsewhere)
        session.flush()

        [attachment] = container.attach_service().attach(
            item, project_session, [_file("a.md")], environment_id=elsewhere.id
        )

        assert (
            attachment.source_environment_id,
            attachment.created_by_session_id,
        ) == (elsewhere.id, project_session.id)


class TestAttachServiceHang:
    def test_attachments_made_are_hung_after_the_items_own_in_their_order(
        self,
        container: ServiceContainer,
        session: DbSession,
        project: Project,
        item: Item,
        project_session: models.Session,
        environment: Environment,
    ) -> None:
        service = container.attach_service()
        other = Item(
            project_id=project.id,
            seq=2,
            kind_code="notice",
            title="Tents",
            created_by_session_id=project_session.id,
        )
        session.add(other)
        session.flush()
        _, first, second = service.attach(
            item,
            project_session,
            [_file("a.md"), _file("b.md"), _file("c.md")],
            environment_id=environment.id,
        )
        service.attach(
            other, project_session, [_file("d.md")], environment_id=environment.id
        )

        service.hang(other, [second, first])

        assert _hung(session, other) == [
            (1, 2, "d.md"),
            (2, 1, "c.md"),
            (3, 1, "b.md"),
        ]
        assert _hung(session, item) == [(1, 1, "a.md"), (2, 1, "b.md"), (3, 1, "c.md")]

    def test_the_timeline_lists_them_once_it_commits(
        self,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        item: Item,
        project_session: models.Session,
        environment: Environment,
    ) -> None:
        with scoped_session(container):
            [attachment] = container.attach_service().attach(
                item, project_session, [_file("a.md")], environment_id=environment.id
            )
        engine_events.clear()
        other = Item(
            project_id=project.id,
            seq=2,
            kind_code="notice",
            title="Tents",
            created_by_session_id=project_session.id,
        )

        with scoped_session(container) as db:
            db.add(other)
            db.flush()
            container.attach_service().hang(other, [attachment])
            assert engine_events == []

        folder = f"draft-{project.number}"
        assert engine_events == [
            TreeHashMoved(
                f"{folder}/timeline.json",
                container.view_service().timeline(project).hash,
            ),
            ProjectChanged(project.id),
        ]
