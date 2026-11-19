"""Revision 0047: the journals it bears for the Projects past Create (DB 150,
634), and its downgrade, Document Role without `journal` and a Work without
its figures and Pilot's lines. Its upgrade adds the enum's value in a
transaction of its own, which no test's transaction holds: the run's
template database is built by it, and `bear_journals` is run here on the
test's transaction."""

import hashlib

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session as DbSession

from app.models import Document, DocumentVersion, Project, User
from app.models.reference import DocumentRole, ProjectState, VersionCause
from app.services.container import ServiceContainer
from tests.support.adoption import adopted_project
from tests.support.revisions import run_revision


def _bear_journals(db: DbSession) -> None:
    """The revision's `bear_journals`, on the test's transaction."""
    run_revision(db, "0047", "bear_journals")
    db.expire_all()


def _past_create(
    db: DbSession, person: User, slug: str, state: ProjectState, archived: bool = False
) -> Project:
    """A Project past Create as revision 0046 left it: with no journal."""
    project = Project(
        created_by_user_id=person.id, slug=slug, state_code=state, archived=archived
    )
    db.add(project)
    db.flush()
    return project


def _journals(db: DbSession, project: Project) -> list[Document]:
    return list(
        db.scalars(
            select(Document).where(
                Document.project_id == project.id,
                Document.role_code == DocumentRole.JOURNAL,
            )
        )
    )


class TestBearJournals:
    def test_every_project_past_create_takes_an_empty_journal_as_one_is_born(
        self, session: DbSession, person: User
    ) -> None:
        """An archived one included (DB 150); published and with its `born`
        Version, as `bear_journal` writes it."""
        projects = [
            _past_create(session, person, "camp-site", ProjectState.OPEN),
            _past_create(session, person, "bike-log", ProjectState.FINISHED),
            _past_create(session, person, "photo-album", ProjectState.OPEN, True),
        ]

        _bear_journals(session)

        empty = hashlib.sha256(b"").hexdigest()
        for project in projects:
            (journal,) = _journals(session, project)
            assert (
                journal.path,
                journal.published_text,
                journal.published_hash,
                journal.ingested_text,
            ) == ("journal.md", "", empty, None)
            assert journal.published_at is not None
            assert [
                (version.number, version.cause_code, version.text, version.hash)
                for version in session.scalars(
                    select(DocumentVersion).where(
                        DocumentVersion.document_id == journal.id
                    )
                )
            ] == [(1, VersionCause.BORN, "", empty)]

    def test_a_draft_and_an_adopted_project_take_none(
        self, session: DbSession, project: Project, service_user: User
    ) -> None:
        adopted = adopted_project(session, service_user)

        _bear_journals(session)

        assert _journals(session, project) == []
        assert _journals(session, adopted) == []

    def test_a_project_that_has_its_journal_keeps_it(
        self, session: DbSession, container: ServiceContainer, person: User
    ) -> None:
        camp = _past_create(session, person, "camp-site", ProjectState.OPEN)
        born = container.document_service().bear_journal(camp, "# Journal\n")

        _bear_journals(session)

        (journal,) = _journals(session, camp)
        assert (journal.id, journal.published_text) == (born.id, "# Journal\n")

    def test_a_journal_it_bore_is_the_one_the_tree_and_the_read_find(
        self, session: DbSession, container: ServiceContainer, person: User
    ) -> None:
        camp = _past_create(session, person, "camp-site", ProjectState.OPEN)

        _bear_journals(session)

        assert (
            container.tree_service().hashes(camp)["camp-site/journal.md"]
            == hashlib.sha256(b"").hexdigest()
        )
        assert container.timeline_service().project_document(
            camp.id, DocumentRole.JOURNAL
        ).model_dump() == {"title": None, "body": [], "writing": False}


def _labels(db: DbSession) -> list[str]:
    return list(
        db.scalars(
            text(
                "SELECT e.enumlabel FROM pg_type t JOIN pg_enum e"
                " ON e.enumtypid = t.oid WHERE t.typname = 'document_role'"
                " ORDER BY e.enumsortorder"
            )
        )
    )


class TestTheDowngrade:
    def test_the_roles_are_without_journal_and_the_journals_are_gone(
        self, session: DbSession, container: ServiceContainer, person: User
    ) -> None:
        camp = _past_create(session, person, "camp-site", ProjectState.OPEN)
        documents = container.document_service()
        documents.bear_handbook(camp, "Keep it short.\n")
        documents.bear_journal(camp, "# Journal\n")
        session.flush()

        run_revision(session, "0047", "downgrade")

        assert _labels(session) == ["draft", "handbook"]
        assert session.execute(
            text(
                "SELECT d.path, d.role_code::text, count(v.id) FROM documents d"
                " JOIN document_versions v ON v.document_id = d.id"
                " WHERE d.project_id = :project GROUP BY d.path, d.role_code"
            ),
            {"project": camp.id},
        ).all() == [("handbook.md", "handbook", 1)]
        assert session.scalar(text("SELECT count(*) FROM document_versions")) == 1

    def test_the_columns_it_added_are_gone(self, session: DbSession) -> None:
        run_revision(session, "0047", "downgrade")

        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns"
                    " WHERE table_name = 'work'"
                    " AND column_name IN ('debrief_figures', 'debrief_notable')"
                )
            )
            == 0
        )

    def test_the_debrief_columns_check_reads_neither(self, session: DbSession) -> None:
        """`ck_work_debrief_fields` as revision 0044 built it."""
        run_revision(session, "0047", "downgrade")

        definition = session.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
                " WHERE conname = 'ck_work_debrief_fields'"
            )
        )
        assert definition is not None
        assert "debrief_subject IS NULL" in definition
        assert "debrief_figures" not in definition

    def test_a_journal_that_holds_a_block_fails_it(
        self, session: DbSession, container: ServiceContainer, person: User
    ) -> None:
        camp = _past_create(session, person, "camp-site", ProjectState.OPEN)
        container.document_service().bear_journal(camp, "```question id=Q1\n```\n")
        session.flush()

        with pytest.raises(DBAPIError, match="blocks_document_id_fkey"):
            run_revision(session, "0047", "downgrade")
