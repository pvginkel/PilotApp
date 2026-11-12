"""Revision 0031: a person's `join_calls` (DB decision 77), over rows as
revision 0030 leaves them: the revision's downgrade builds 0030's schema in
the test's transaction."""

from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.models import User

_BACKEND_DIR = Path(__file__).resolve().parents[2]


def _run(db: Session, step: str) -> None:
    """Revision 0031's `step`, `upgrade` or `downgrade`, on the test's
    transaction; what the session holds is read again after an upgrade."""
    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    revision = ScriptDirectory.from_config(config).get_revision("0031")
    assert revision is not None
    with Operations.context(MigrationContext.configure(db.connection())):
        getattr(revision.module, step)()
    if step == "upgrade":
        db.expire_all()


def _columns(db: Session) -> set[str]:
    return {column["name"] for column in inspect(db.connection()).get_columns("users")}


class TestJoinCalls:
    def test_the_upgrade_turns_it_on_for_every_row_there_is(
        self, session: Session, person: User, service_user: User
    ) -> None:
        _run(session, "downgrade")
        assert "join_calls" not in _columns(session)

        _run(session, "upgrade")

        assert session.execute(
            text("SELECT handle, join_calls FROM users ORDER BY handle")
        ).all() == [("ada", True), ("agent", True), ("fleet", True)]

    def test_a_row_written_without_it_has_it_on(self, session: Session) -> None:
        _run(session, "downgrade")
        _run(session, "upgrade")
        session.execute(
            text(
                "INSERT INTO users (id, kind_code, subject, handle, name, avatar_slot)"
                " VALUES (gen_random_uuid(), 'person', 'subject-hal', 'hal',"
                " 'Hal Example', 3)"
            )
        )

        assert (
            session.execute(
                text("SELECT join_calls FROM users WHERE handle = 'hal'")
            ).scalar_one()
            is True
        )

    def test_the_downgrade_drops_where_it_stood(
        self, session: Session, person: User
    ) -> None:
        person.join_calls = False
        session.flush()

        _run(session, "downgrade")
        assert "join_calls" not in _columns(session)
        _run(session, "upgrade")

        assert person.join_calls is True
