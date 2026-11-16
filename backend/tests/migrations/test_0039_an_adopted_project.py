"""Revision 0039's downgrade: Project State and Transition Kind without
`adopted`, a draft's check and the state's default standing on the types it
leaves."""

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models import Project, User
from tests.support.adoption import adopted_project

_BACKEND_DIR = Path(__file__).resolve().parents[2]


def _downgrade(db: Session) -> None:
    """Revision 0039's downgrade, on the test's transaction. Its upgrade
    adds the enums' values in a transaction of its own, which no test's
    transaction holds."""
    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    revision = ScriptDirectory.from_config(config).get_revision("0039")
    assert revision is not None
    with Operations.context(MigrationContext.configure(db.connection())):
        revision.module.downgrade()


def _labels(db: Session, enum: str) -> list[str]:
    return list(
        db.scalars(
            text(
                "SELECT e.enumlabel FROM pg_type t JOIN pg_enum e"
                " ON e.enumtypid = t.oid WHERE t.typname = :enum"
                " ORDER BY e.enumsortorder"
            ),
            {"enum": enum},
        )
    )


def _refused(db: Session, statement: str, **values: object) -> str:
    """The constraint that refuses the statement, or the error's words where
    no constraint does."""
    with pytest.raises(DBAPIError) as raised, db.begin_nested():
        db.execute(text(statement), values)
    return raised.value.orig.diag.constraint_name or str(raised.value.orig)


class TestTheDowngrade:
    def test_the_states_and_the_kinds_are_without_adopted(
        self, session: Session
    ) -> None:
        _downgrade(session)

        assert _labels(session, "project_state") == ["draft", "open", "finished"]
        assert _labels(session, "transition_kind") == [
            "opened",
            "finished",
            "reopened",
            "archived",
            "brought_back",
            "autopilot_on",
            "autopilot_off",
            "paused",
            "resumed",
        ]

    def test_the_columns_it_added_are_gone(self, session: Session) -> None:
        _downgrade(session)

        columns = session.scalars(
            text(
                "SELECT table_name || '.' || column_name FROM information_schema.columns"
                " WHERE column_name IN ('adopted_group', 'adopted_project_id')"
            )
        ).all()
        assert columns == []

    def test_a_project_keeps_its_state_its_default_and_a_drafts_check(
        self, session: Session, person: User, project: Project
    ) -> None:
        _downgrade(session)

        session.execute(
            text("INSERT INTO projects (id, created_by_user_id) VALUES (:id, :user)"),
            {"id": "5e7f9a10-1c2d-4e3f-8a4b-6c7d8e9f0a1b", "user": person.id},
        )
        assert session.scalars(
            text("SELECT state_code::text FROM projects ORDER BY number")
        ).all() == ["draft", "draft"]
        assert (
            _refused(
                session,
                "UPDATE projects SET slug = 'fix-the-client' WHERE id = :id",
                id=project.id,
            )
            == "ck_projects_draft_slug"
        )

    def test_an_adopted_projects_row_fails_the_cast(
        self, session: Session, service_user: User
    ) -> None:
        adopted_project(session, service_user)

        with pytest.raises(DBAPIError, match="invalid input value for enum"):
            _downgrade(session)
