"""Revision 0043's downgrade: no `conversations`, no Session Kind
`conversation`, and Close Cause without `ended`, the chats' closes standing
on the type it leaves."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app import models
from app.models import Conversation, Environment, Project
from app.models.reference import CloseCause, SessionState
from tests.support.chats import close_chat, open_chat

_BACKEND_DIR = Path(__file__).resolve().parents[2]

CLOSED_AT = datetime(2026, 11, 14, 11, 20, tzinfo=UTC)


def _downgrade(db: Session) -> None:
    """Revision 0043's downgrade, on the test's transaction. Its upgrade
    adds the enum's value in a transaction of its own, which no test's
    transaction holds."""
    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    revision = ScriptDirectory.from_config(config).get_revision("0043")
    assert revision is not None
    with Operations.context(MigrationContext.configure(db.connection())):
        revision.module.downgrade()


class TestTheDowngrade:
    def test_the_causes_and_the_kinds_are_the_chats(self, session: Session) -> None:
        _downgrade(session)

        assert session.scalars(
            text(
                "SELECT e.enumlabel FROM pg_type t JOIN pg_enum e"
                " ON e.enumtypid = t.oid WHERE t.typname = 'close_cause'"
                " ORDER BY e.enumsortorder"
            )
        ).all() == ["timeout", "created", "finished", "reopened", "archived"]
        assert session.scalars(
            text("SELECT code FROM session_kinds ORDER BY code")
        ).all() == ["chat", "job", "work"]
        assert session.scalar(text("SELECT to_regclass('conversations')")) is None

    def test_a_closed_chat_keeps_its_cause(
        self, session: Session, project: Project
    ) -> None:
        run = open_chat(session, project)
        close_chat(session, run, CLOSED_AT, CloseCause.ARCHIVED)
        session.expunge_all()

        _downgrade(session)

        assert (
            session.execute(
                text("SELECT close_cause_code::text FROM chats WHERE id = :id"),
                {"id": run.id},
            ).scalar_one()
            == "archived"
        )
        with pytest.raises(DBAPIError) as raised, session.begin_nested():
            session.execute(
                text("UPDATE chats SET close_cause_code = 'ended' WHERE id = :id"),
                {"id": run.id},
            )
        assert "invalid input value for enum close_cause" in str(raised.value.orig)

    def test_a_conversations_session_fails_it(
        self, session: Session, project: Project, environment: Environment
    ) -> None:
        """Its row goes with its table, and its Session, of a kind the
        downgrade removes, stays."""
        run = models.Session(
            project_id=project.id,
            kind_code="conversation",
            cwd="/work/PilotProjects",
            token_hash=uuid.uuid4().hex * 2,
            state_code=SessionState.IDLE,
        )
        session.add(run)
        session.flush()
        session.add(
            Conversation(
                id=run.id,
                project_id=project.id,
                session_kind_code="conversation",
                caller_environment_id=environment.id,
            )
        )
        session.flush()

        with pytest.raises(DBAPIError) as raised:
            _downgrade(session)

        assert raised.value.orig.diag.constraint_name == "sessions_kind_code_fkey"
