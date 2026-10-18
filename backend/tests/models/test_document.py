"""Document and Document Version: what a row must hold, and how its texts are stored."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session as DbSession

from app.models import Document, DocumentVersion, Environment, Item, Project, Session
from app.models.reference import DocumentRole, VersionCause
from tests.support.database import violated_constraint

_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _prose_document(item: Item, **overrides: object) -> Document:
    values: dict[str, object] = {
        "id": item.id,
        "path": f"items/{item.seq}-which-provider.md",
    }
    values.update(overrides)
    return Document(**values)


class TestDocument:
    def test_a_draft_is_born_empty(self, session: DbSession, project: Project) -> None:
        now = datetime.now(UTC)
        draft = Document(
            path="project.md",
            project_id=project.id,
            role_code=DocumentRole.DRAFT,
            published_text="",
            published_hash=_HASH,
            published_at=now,
        )
        session.add(draft)
        session.flush()
        session.refresh(draft)

        assert draft.published_text == ""
        assert draft.created_at is not None

    def test_an_empty_ingest_is_kept(
        self, session: DbSession, draft_document: Document
    ) -> None:
        draft_document.ingested_text = " \n"
        draft_document.ingested_hash = _HASH
        draft_document.ingested_at = datetime.now(UTC)
        session.flush()
        session.refresh(draft_document)

        assert draft_document.ingested_text == " \n"

    def test_a_prose_items_document_is_its_item(
        self, session: DbSession, item: Item, environment: Environment
    ) -> None:
        document = _prose_document(
            item,
            summary="TheTVDB or TVmaze for the show search.",
            source_environment_id=environment.id,
            source_path="/work/Example/docs/survey.md",
        )
        session.add(document)
        session.flush()

        assert document.id == item.id
        assert document.project_id is None

    def test_a_project_document_has_a_role(
        self, session: DbSession, project: Project
    ) -> None:
        session.add(Document(path="project.md", project_id=project.id))

        assert violated_constraint(session) == "ck_documents_subtype"

    def test_a_role_is_a_project_documents(
        self, session: DbSession, item: Item
    ) -> None:
        session.add(_prose_document(item, role_code=DocumentRole.HANDBOOK))

        assert violated_constraint(session) == "ck_documents_subtype"

    def test_a_project_document_has_no_summary(
        self, session: DbSession, draft_document: Document
    ) -> None:
        draft_document.summary = "What the project is about."

        assert violated_constraint(session) == "ck_documents_subtype"

    def test_a_project_document_has_no_source(
        self, session: DbSession, draft_document: Document, environment: Environment
    ) -> None:
        draft_document.source_environment_id = environment.id
        draft_document.source_path = "/work/Example/project.md"

        assert violated_constraint(session) == "ck_documents_subtype"

    def test_a_project_has_one_draft(
        self, session: DbSession, draft_document: Document, project: Project
    ) -> None:
        session.add(
            Document(
                path="handbook.md",
                project_id=project.id,
                role_code=DocumentRole.DRAFT,
            )
        )

        assert violated_constraint(session) == "uq_documents_project_role"

    def test_a_path_is_unique_in_its_project(
        self, session: DbSession, draft_document: Document, project: Project
    ) -> None:
        session.add(
            Document(
                path="project.md",
                project_id=project.id,
                role_code=DocumentRole.HANDBOOK,
            )
        )

        assert violated_constraint(session) == "uq_documents_project_path"

    def test_a_source_is_an_environment_and_a_path(
        self, session: DbSession, item: Item
    ) -> None:
        session.add(_prose_document(item, source_path="/work/Example/survey.md"))

        assert violated_constraint(session) == "ck_documents_source"

    def test_its_source_is_an_environment(self, session: DbSession, item: Item) -> None:
        session.add(
            _prose_document(
                item,
                source_environment_id="no-such-env",
                source_path="/work/Example/survey.md",
            )
        )

        assert violated_constraint(session) == "documents_source_environment_id_fkey"

    @pytest.mark.parametrize(
        "columns",
        [
            {"ingested_text": "# Title\n"},
            {"ingested_hash": _HASH, "ingested_at": datetime.now(UTC)},
        ],
    )
    def test_an_ingest_is_its_text_hash_and_time(
        self, session: DbSession, draft_document: Document, columns: dict[str, object]
    ) -> None:
        for name, value in columns.items():
            setattr(draft_document, name, value)

        assert violated_constraint(session) == "ck_documents_ingested"

    def test_an_ingests_session_comes_with_it(
        self,
        session: DbSession,
        draft_document: Document,
        project_session: Session,
    ) -> None:
        draft_document.ingested_session_id = project_session.id

        assert violated_constraint(session) == "ck_documents_ingested"

    @pytest.mark.parametrize(
        "columns",
        [
            {"published_text": "# Title\n"},
            {"published_hash": _HASH, "published_at": datetime.now(UTC)},
        ],
    )
    def test_a_publish_is_its_text_hash_and_time(
        self, session: DbSession, draft_document: Document, columns: dict[str, object]
    ) -> None:
        for name, value in columns.items():
            setattr(draft_document, name, value)

        assert violated_constraint(session) == "ck_documents_published"

    def test_a_writing_session_is_written_since(
        self,
        session: DbSession,
        draft_document: Document,
        project_session: Session,
    ) -> None:
        draft_document.writing_session_id = project_session.id

        assert violated_constraint(session) == "ck_documents_writing"

    def test_writing_since_is_a_sessions(
        self, session: DbSession, draft_document: Document
    ) -> None:
        draft_document.writing_since = datetime.now(UTC)

        assert violated_constraint(session) == "ck_documents_writing"


class TestDocumentVersion:
    def _version(self, document: Document, **overrides: object) -> DocumentVersion:
        values: dict[str, object] = {
            "document_id": document.id,
            "number": 1,
            "cause_code": VersionCause.BORN,
            "text": "",
            "hash": _HASH,
        }
        values.update(overrides)
        return DocumentVersion(**values)

    def test_a_born_version_is_kept_empty(
        self, session: DbSession, draft_document: Document
    ) -> None:
        version = self._version(draft_document)
        session.add(version)
        session.flush()
        session.refresh(version)

        assert version.text == ""
        assert version.session_id is None
        assert version.created_at is not None

    def test_a_number_is_one_version(
        self, session: DbSession, draft_document: Document
    ) -> None:
        session.add_all(
            [
                self._version(draft_document),
                self._version(draft_document, cause_code=VersionCause.TURN),
            ]
        )

        assert (
            violated_constraint(session) == "document_versions_document_id_number_key"
        )

    def test_numbers_count_from_1(
        self, session: DbSession, draft_document: Document
    ) -> None:
        session.add(self._version(draft_document, number=0))

        assert violated_constraint(session) == "ck_document_versions_number"


class TestDocumentTextCompression:
    def test_a_documents_texts_are_lz4(self, session: DbSession) -> None:
        """Set by the revision; the models cannot carry it (DB §7.1)."""
        rows = session.execute(
            text(
                "SELECT c.relname, a.attname, a.attcompression"
                " FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid"
                " WHERE (c.relname, a.attname) IN (('documents', 'ingested_text'),"
                " ('documents', 'published_text'), ('document_versions', 'text'))"
            )
        ).all()

        assert set(rows) == {
            ("documents", "ingested_text", "l"),
            ("documents", "published_text", "l"),
            ("document_versions", "text", "l"),
        }
