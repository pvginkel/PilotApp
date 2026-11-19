"""Revision 0048: a step's kind, its conversations and its timing (DB
decision 79), over a record as revision 0047 leaves it: the downgrades of
revision 0049 and of this one build 0047's schema in the test's transaction."""

import uuid

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session as DbSession

from app import models
from app.extensions import db as app_db
from app.models import Item, ProgressStep, Project, Work
from app.models.reference import ProgressState
from tests.support.revisions import run_revision

TABLES = ("step_kinds", "step_transcripts", "step_timings")
COLUMNS = {"kind_code", "listed_ahead", "marked"}


def _tables(db: DbSession) -> list[str]:
    """Those of the revision's tables the database has."""
    inspector = inspect(db.connection())
    return [table for table in TABLES if inspector.has_table(table)]


def _step_columns(db: DbSession) -> set[str]:
    """Those of the revision's columns a Progress Step has."""
    columns = inspect(db.connection()).get_columns("progress_steps")
    return {column["name"] for column in columns} & COLUMNS


class TestRevision0048:
    def test_its_downgrade_takes_what_it_built_and_its_upgrade_builds_it_over_a_list(
        self, session: DbSession, project: Project, project_session: models.Session
    ) -> None:
        """A step Pilot held before the revision stays, with no kind, no mark
        and a listing unknown."""
        work_id = uuid.uuid4()
        session.add_all(
            [
                Item(
                    id=work_id,
                    project_id=project.id,
                    seq=2,
                    kind_code="work",
                    title="Fixing the client for v4",
                    created_by_session_id=project_session.id,
                ),
                models.Session(
                    id=work_id,
                    project_id=project.id,
                    environment_id=project_session.environment_id,
                    kind_code="work",
                    cwd="/work/Example",
                    token_hash="2" * 64,
                    state_code=project_session.state_code,
                ),
            ]
        )
        session.flush()
        session.add(
            Work(
                id=work_id,
                project_id=project.id,
                session_kind_code="work",
                autopilot=False,
            )
        )
        session.flush()
        session.add(
            ProgressStep(
                work_id=work_id,
                code="P1.code",
                label="P1 · the v4 client",
                position=1,
                state_code=ProgressState.PENDING,
            )
        )
        session.flush()
        session.expunge_all()

        run_revision(session, "0049", "downgrade")
        run_revision(session, "0048", "downgrade")

        assert _tables(session) == []
        assert _step_columns(session) == set()
        assert session.scalars(text("SELECT code FROM progress_steps")).all() == [
            "P1.code"
        ]

        run_revision(session, "0048", "upgrade")
        run_revision(session, "0049", "upgrade")

        assert _tables(session) == list(TABLES)
        step = session.get_one(ProgressStep, (work_id, "P1.code"))
        assert (step.kind_code, step.listed_ahead, step.marked) == (None, None, None)
        context = MigrationContext.configure(session.connection())
        assert compare_metadata(context, app_db.metadata) == []
