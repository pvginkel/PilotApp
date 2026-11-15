"""Revision 0037: a Block's `handed_at` and the ended Sessions' `ended_at`
(DB decision 79), over a record as revision 0036 leaves it: the revision's
downgrade builds 0036's schema in the test's transaction."""

import uuid
from datetime import UTC, datetime

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session as DbSession

from app import models
from app.extensions import db as app_db
from app.models import Chat, Project
from app.models.reference import ChatKind, CloseCause, SessionState
from tests.support.revisions import run_revision

CLOSED = datetime(2026, 11, 14, 8, 30, tzinfo=UTC)


def _has_handed_at(db: DbSession) -> bool:
    return "handed_at" in {
        column["name"] for column in inspect(db.connection()).get_columns("blocks")
    }


def _chat(
    db: DbSession,
    project: Project,
    state: SessionState,
    closed: tuple[datetime, CloseCause] | None,
) -> models.Session:
    """A project chat's Session in `state`, its chat closed as `closed`."""
    run = models.Session(
        project_id=project.id,
        kind_code="chat",
        cwd="/work/PilotProjects",
        token_hash=uuid.uuid4().hex * 2,
        state_code=state,
    )
    db.add(run)
    db.flush()
    db.add(
        Chat(
            id=run.id,
            project_id=project.id,
            session_kind_code="chat",
            kind_code=ChatKind.PROJECT,
            closed_at=None if closed is None else closed[0],
            close_cause_code=None if closed is None else closed[1],
        )
    )
    db.flush()
    return run


def _ended_at(db: DbSession, run: models.Session) -> datetime | None:
    return db.scalars(
        select(models.Session.ended_at).where(models.Session.id == run.id)
    ).one()


class TestRevision0037:
    def test_its_downgrade_takes_handed_at_and_its_upgrade_adds_it_with_none(
        self, session: DbSession
    ) -> None:
        run_revision(session, "0037", "downgrade")

        assert not _has_handed_at(session)

        run_revision(session, "0037", "upgrade")

        assert _has_handed_at(session)
        assert (
            session.scalars(
                text("SELECT count(*) FROM blocks WHERE handed_at IS NOT NULL")
            ).one()
            == 0
        )
        context = MigrationContext.configure(session.connection())
        assert compare_metadata(context, app_db.metadata) == []

    def test_a_session_that_ended_carries_its_chats_close(
        self, session: DbSession, project: Project
    ) -> None:
        ended = _chat(
            session, project, SessionState.ENDED, (CLOSED, CloseCause.TIMEOUT)
        )
        run_revision(session, "0037", "downgrade")
        assert _ended_at(session, ended) is None

        run_revision(session, "0037", "upgrade")

        assert _ended_at(session, ended) == CLOSED

    def test_a_session_that_did_not_end_gets_no_end(
        self, session: DbSession, project: Project
    ) -> None:
        """A chat a transition closed keeps its controller session, and an
        open chat's Session goes on: neither ended."""
        finished = _chat(
            session, project, SessionState.IDLE, (CLOSED, CloseCause.FINISHED)
        )
        run_revision(session, "0037", "downgrade")

        run_revision(session, "0037", "upgrade")

        assert _ended_at(session, finished) is None
