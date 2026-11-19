"""Revision 0048: the indexes the estimate reads a kind's last Step Timings
through, in place of revision 0047's one."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.orm import Session as DbSession

from app.extensions import db as app_db
from tests.support.revisions import run_revision

BY_END = {"ix_step_timings_kind_code_ended_at": ["kind_code", "ended_at"]}
BY_LISTING = {
    "ix_step_timings_kind_code_listed_ahead_ended_at": [
        "kind_code",
        "listed_ahead",
        "ended_at",
        "id",
    ],
    "ix_step_timings_repo_kind_code_listed_ahead_ended_at": [
        "repo",
        "kind_code",
        "listed_ahead",
        "ended_at",
        "id",
    ],
}


def _indexes(db: DbSession) -> dict[str | None, list[str | None]]:
    """A Step Timing's indexes that no key of its own makes, each with its
    columns in order."""
    return {
        index["name"]: index["column_names"]
        for index in inspect(db.connection()).get_indexes("step_timings")
        if not index["unique"]
    }


class TestRevision0048:
    def test_its_downgrade_restores_the_one_index_and_its_upgrade_builds_the_two(
        self, session: DbSession
    ) -> None:
        assert _indexes(session) == BY_LISTING

        run_revision(session, "0048", "downgrade")

        assert _indexes(session) == BY_END

        run_revision(session, "0048", "upgrade")

        assert _indexes(session) == BY_LISTING
        context = MigrationContext.configure(session.connection())
        assert compare_metadata(context, app_db.metadata) == []
