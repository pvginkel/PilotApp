"""Revision 0045: Pilot Note and Send Alert (DB 616 to 627, 631), over a
record as revision 0044 leaves it: the revision's downgrade builds 0044's
schema in the test's transaction."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.orm import Session as DbSession

from app.extensions import db as app_db
from app.models import Item
from tests.support.revisions import run_revision


def _table(db: DbSession, name: str) -> object:
    return db.scalar(text("SELECT to_regclass(:name)"), {"name": name})


class TestRevision0045:
    def test_its_downgrade_takes_the_tables_and_its_upgrade_builds_them(
        self, session: DbSession
    ) -> None:
        run_revision(session, "0045", "downgrade")

        assert (_table(session, "pilot_notes"), _table(session, "send_alerts")) == (
            None,
            None,
        )

        run_revision(session, "0045", "upgrade")

        context = MigrationContext.configure(session.connection())
        assert compare_metadata(context, app_db.metadata) == []

    def test_an_item_on_the_record_takes_no_note_from_it(
        self, session: DbSession, item: Item
    ) -> None:
        """The notices already on the timelines stay notices: nothing is
        backfilled (DB decision 84)."""
        run_revision(session, "0045", "downgrade")
        run_revision(session, "0045", "upgrade")

        assert session.scalar(text("SELECT count(*) FROM pilot_notes")) == 0
        assert session.scalar(text("SELECT count(*) FROM send_alerts")) == 0
