"""Revision 0036: the Hold (DB 360 to 362, 559), over a record as revision
0035 leaves it: the revision's downgrade builds 0035's schema in the test's
transaction."""

from datetime import UTC, datetime

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session as DbSession

from app import models
from app.extensions import db as app_db
from app.models import Hold
from app.models.reference import HoldKind, SessionState
from tests.support.revisions import run_revision

AT = datetime(2026, 11, 15, 16, 25, tzinfo=UTC)


def _has_holds(db: DbSession) -> bool:
    return inspect(db.connection()).has_table("holds")


def _hold_kinds(db: DbSession) -> list[str]:
    """The values of the database's `hold_kind`, in its order; none where it
    has no such type."""
    return list(
        db.scalars(
            text(
                "SELECT e.enumlabel FROM pg_type t"
                " JOIN pg_enum e ON e.enumtypid = t.oid"
                " WHERE t.typname = 'hold_kind' ORDER BY e.enumsortorder"
            )
        )
    )


class TestRevision0036:
    def test_its_downgrade_takes_the_holds_and_their_kinds_and_its_upgrade_builds_them(
        self, session: DbSession, project_session: models.Session
    ) -> None:
        held = Hold(
            session_id=project_session.id, kind_code=HoldKind.PAUSE, started_at=AT
        )
        session.add(held)
        session.flush()
        session.expunge(held)

        run_revision(session, "0036", "downgrade")

        assert not _has_holds(session)
        assert _hold_kinds(session) == []

        run_revision(session, "0036", "upgrade")

        assert _hold_kinds(session) == [kind.value for kind in HoldKind]
        assert session.scalars(text("SELECT count(*) FROM holds")).one() == 0
        context = MigrationContext.configure(session.connection())
        assert compare_metadata(context, app_db.metadata) == []

    def test_no_hold_is_back_filled_for_a_session_held_as_it_runs(
        self, session: DbSession, project_session: models.Session
    ) -> None:
        """A Session already held gets its Hold when the gate is next read
        for it (`SessionStartService.release`), starting then."""
        project_session.state_code = SessionState.HELD
        session.flush()
        run_revision(session, "0036", "downgrade")

        run_revision(session, "0036", "upgrade")

        assert project_session.state_code == SessionState.HELD
        assert session.scalars(text("SELECT count(*) FROM holds")).one() == 0
