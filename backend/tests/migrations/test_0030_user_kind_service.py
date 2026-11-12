"""Revision 0030's downgrade: User Kind without `service`, the checks of
`users` that name a kind standing on the type it leaves."""

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models import User

_BACKEND_DIR = Path(__file__).resolve().parents[2]

_INSERT = (
    "INSERT INTO users (id, kind_code, subject, handle, name, avatar_slot)"
    " VALUES (gen_random_uuid(), :kind, :subject, :handle, 'An Example', :slot)"
)


def _downgrade(db: Session) -> None:
    """Revision 0030's downgrade, on the test's transaction. Its upgrade
    adds the enum's value in a transaction of its own, which no test's
    transaction holds."""
    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    revision = ScriptDirectory.from_config(config).get_revision("0030")
    assert revision is not None
    with Operations.context(MigrationContext.configure(db.connection())):
        revision.module.downgrade()


def _refused(db: Session, **row: object) -> str:
    """The constraint that refuses `row` of `users`, or the error's words
    where no constraint does."""
    with pytest.raises(DBAPIError) as raised, db.begin_nested():
        db.execute(text(_INSERT), row)
    return raised.value.orig.diag.constraint_name or str(raised.value.orig)


class TestTheDowngrade:
    def test_the_kinds_are_a_person_and_pilot(self, session: Session) -> None:
        _downgrade(session)

        kinds = session.scalars(
            text(
                "SELECT e.enumlabel FROM pg_type t JOIN pg_enum e"
                " ON e.enumtypid = t.oid WHERE t.typname = 'user_kind'"
                " ORDER BY e.enumsortorder"
            )
        ).all()
        assert kinds == ["person", "agent"]
        assert "invalid input value for enum user_kind" in _refused(
            session, kind="service", subject="subject-fleet", handle="fleet", slot=None
        )

    def test_the_rows_keep_their_kinds_and_their_checks(
        self, session: Session, person: User
    ) -> None:
        _downgrade(session)

        assert session.execute(
            text("SELECT handle, kind_code::text FROM users ORDER BY handle")
        ).all() == [("ada", "person"), ("agent", "agent")]
        assert _refused(session, kind="person", subject=None, handle="ben", slot=2) == (
            "ck_users_person"
        )
        assert _refused(
            session, kind="agent", subject=None, handle="pilot-two", slot=None
        ) == ("ck_users_agent_handle")
        assert _refused(
            session, kind="agent", subject="subject-pilot", handle="agent", slot=None
        ) in ("ck_users_agent", "users_handle_key")

    def test_a_service_users_row_fails_it(
        self, session: Session, service_user: User
    ) -> None:
        with pytest.raises(DBAPIError) as raised:
            _downgrade(session)

        assert "invalid input value for enum user_kind" in str(raised.value.orig)
