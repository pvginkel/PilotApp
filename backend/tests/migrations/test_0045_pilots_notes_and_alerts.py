"""Revision 0045: Pilot Note and Send Alert (DB 616 to 627, 631), over a
record as revision 0044 leaves it: the revision's downgrade builds 0044's
schema in the test's transaction, once revision 0046's, whose Work keys into
`pilot_notes`, has undone what it added."""

from typing import Any

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.orm import Session as DbSession

from app.extensions import db as app_db
from app.models import Item
from tests.support.revisions import run_revision


def _table(db: DbSession, name: str) -> object:
    return db.scalar(text("SELECT to_regclass(:name)"), {"name": name})


def _downgrade(db: DbSession) -> None:
    """Revision 0046's downgrade, then 0045's."""
    run_revision(db, "0046", "downgrade")
    run_revision(db, "0045", "downgrade")


def _of_0046(difference: tuple[Any, ...]) -> bool:
    """Whether `difference` is what revision 0046's downgrade left out:
    `work.trigger_note_id` and its key. Its upgrade adds an enum's value in
    an autocommit block, which no test's transaction holds."""
    if difference[0] == "add_column":
        return (difference[2], difference[3].name) == ("work", "trigger_note_id")
    if difference[0] == "add_fk":
        return [column.name for column in difference[1].columns] == ["trigger_note_id"]
    return False


class TestRevision0045:
    def test_its_downgrade_takes_the_tables_and_its_upgrade_builds_them(
        self, session: DbSession
    ) -> None:
        _downgrade(session)

        assert (_table(session, "pilot_notes"), _table(session, "send_alerts")) == (
            None,
            None,
        )

        run_revision(session, "0045", "upgrade")

        context = MigrationContext.configure(session.connection())
        assert [
            difference
            for difference in compare_metadata(context, app_db.metadata)
            if not _of_0046(difference)
        ] == []

    def test_an_item_on_the_record_takes_no_note_from_it(
        self, session: DbSession, item: Item
    ) -> None:
        """The notices already on the timelines stay notices: nothing is
        backfilled (DB decision 84)."""
        _downgrade(session)
        run_revision(session, "0045", "upgrade")

        assert session.scalar(text("SELECT count(*) FROM pilot_notes")) == 0
        assert session.scalar(text("SELECT count(*) FROM send_alerts")) == 0
