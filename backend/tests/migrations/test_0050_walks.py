"""Revision 0050's downgrade: the walks kept go with their table."""

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session as DbSession

from app.models import Walk
from tests.support.revisions import run_revision


class TestTheDowngrade:
    def test_the_table_is_gone_with_the_walks_it_kept(self, session: DbSession) -> None:
        session.add(Walk(ended_at=datetime(2026, 11, 12, 17, 35, 4, tzinfo=UTC)))
        session.flush()

        run_revision(session, "0050", "downgrade")

        assert session.scalar(text("SELECT to_regclass('walks')")) is None
