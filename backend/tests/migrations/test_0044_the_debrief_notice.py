"""Revision 0044: a Work's debrief subject, its completion and its Debrief
Notice, and Item Kind `debrief_notice` (DB 606 to 613), over a record as
revision 0043 leaves it: the revision's downgrade builds 0043's schema in the
test's transaction."""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session as DbSession

from app import models
from app.extensions import db as app_db
from app.models import Environment, Item, Project, User, Work
from app.models.reference import SessionState
from app.services.container import ServiceContainer
from tests.support.revisions import run_revision

_SUBJECT = "Slice 058 · The search page"


def _debriefed_work(
    db: DbSession,
    container: ServiceContainer,
    project: Project,
    environment: Environment,
) -> Work:
    """A work item whose session gave its debrief."""
    run = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code="work",
        cwd="/work/Camp",
        token_hash="4" * 64,
        state_code=SessionState.RUNNING,
    )
    db.add(run)
    db.flush()
    work = container.record_service().place_work(
        project, run, "Building the camp", repo="example/Camp"
    )
    work.debrief = "It went well, if slowly."
    db.flush()
    return work


def _work_columns(db: DbSession) -> set[str]:
    return {column["name"] for column in inspect(db.connection()).get_columns("work")}


def _kinds(db: DbSession) -> list[str]:
    return list(db.scalars(text("SELECT code FROM item_kinds ORDER BY code")))


class TestRevision0044:
    def test_its_downgrade_takes_the_fields_and_the_kind_and_its_upgrade_builds_them(
        self, session: DbSession
    ) -> None:
        run_revision(session, "0044", "downgrade")

        assert not _work_columns(session) & {
            "debrief_subject",
            "debrief_completes",
            "debrief_notice_id",
            "debrief_notice_kind_code",
        }
        assert "debrief_notice" not in _kinds(session)

        run_revision(session, "0044", "upgrade")

        assert "debrief_notice" in _kinds(session)
        context = MigrationContext.configure(session.connection())
        assert compare_metadata(context, app_db.metadata) == []

    def test_the_downgrade_leaves_three_forms(self, session: DbSession) -> None:
        run_revision(session, "0044", "downgrade")

        with pytest.raises(DBAPIError) as raised, session.begin_nested():
            session.execute(
                text(
                    "INSERT INTO item_kinds (code, name, form, icon)"
                    " VALUES ('other', 'Other', 'debrief_notice', 'notebook')"
                )
            )
        assert raised.value.orig.diag.constraint_name == "ck_item_kinds_form"

    def test_a_debrief_keeps_its_words_and_is_not_backfilled(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """DB 609: a debrief given before the revision names no subject and
        no completion, so no notice ever carries it."""
        work = _debriefed_work(session, container, project, environment)
        work.debrief_subject = _SUBJECT
        work.debrief_completes = False
        session.flush()
        session.expunge(work)

        run_revision(session, "0044", "downgrade")
        run_revision(session, "0044", "upgrade")

        kept = session.get_one(Work, work.id)
        assert (
            kept.debrief,
            kept.debrief_subject,
            kept.debrief_completes,
            kept.debrief_notice_id,
        ) == ("It went well, if slowly.", None, None, None)

    def test_a_placed_notice_fails_the_downgrade(
        self,
        session: DbSession,
        project: Project,
    ) -> None:
        pilot = session.scalars(select(User).where(User.handle == "agent")).one()
        session.add(
            Item(
                project_id=project.id,
                seq=1,
                kind_code="debrief_notice",
                title=f"Debrief · {_SUBJECT}",
                created_by_user_id=pilot.id,
            )
        )
        session.flush()

        with pytest.raises(DBAPIError) as raised:
            run_revision(session, "0044", "downgrade")

        assert raised.value.orig.diag.constraint_name == "ck_items_created_by"
