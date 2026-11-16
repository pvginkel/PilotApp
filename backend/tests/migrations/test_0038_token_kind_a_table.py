"""Revision 0038: Token Kind from an enum type to a table and back, a Turn's
Token Counts keeping their rows (DB decision 79.5, §7.2)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import TokenCount, Turn

_BACKEND_DIR = Path(__file__).resolve().parents[2]

COUNTS = {"input": 6, "cache_write": 31_400, "cache_read": 0, "output": 820}


def _run(db: DbSession, step: str) -> None:
    """Revision 0038's `step`, its upgrade or its downgrade, on the test's
    transaction."""
    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    revision = ScriptDirectory.from_config(config).get_revision("0038")
    assert revision is not None
    with Operations.context(MigrationContext.configure(db.connection())):
        getattr(revision.module, step)()
    db.expire_all()


def _counts(db: DbSession, turn_id: int) -> dict[str, int]:
    """The Turn's Token Counts by kind, read under either type of the kind."""
    rows = db.execute(
        text(
            "SELECT token_kind_code::text, tokens FROM token_counts"
            " WHERE turn_id = :turn"
        ),
        {"turn": turn_id},
    ).all()
    return {row[0]: row[1] for row in rows}


def _kind_type(db: DbSession) -> str:
    """The type of a Token Count's kind."""
    return db.scalars(
        text(
            "SELECT udt_name FROM information_schema.columns"
            " WHERE table_name = 'token_counts' AND column_name = 'token_kind_code'"
        )
    ).one()


def _refused(db: DbSession, turn_id: int, kind: str) -> str:
    """The constraint that refuses the Turn a Token Count of `kind`, or the
    error's words where no constraint does."""
    with pytest.raises(DBAPIError) as raised, db.begin_nested():
        db.execute(
            text(
                "INSERT INTO token_counts (turn_id, token_kind_code, tokens)"
                " VALUES (:turn, :kind, 6)"
            ),
            {"turn": turn_id, "kind": kind},
        )
    return raised.value.orig.diag.constraint_name or str(raised.value.orig)


@pytest.fixture
def turn_id(session: DbSession, project_session: models.Session) -> int:
    """A Turn counted in its four kinds."""
    turn = Turn(
        session_id=project_session.id,
        seq=1,
        message="Fix the client for v4.",
        started_at=datetime(2026, 11, 1, 9, 30, tzinfo=UTC),
    )
    session.add(turn)
    session.flush()
    session.add_all(
        TokenCount(turn_id=turn.id, token_kind_code=kind, tokens=tokens)
        for kind, tokens in COUNTS.items()
    )
    session.flush()
    return turn.id


class TestTokenKindATable:
    def test_a_turns_token_counts_keep_their_rows_both_ways(
        self, session: DbSession, turn_id: int
    ) -> None:
        _run(session, "downgrade")

        assert _kind_type(session) == "token_kind"
        assert _counts(session, turn_id) == COUNTS

        _run(session, "upgrade")

        assert _kind_type(session) == "text"
        assert _counts(session, turn_id) == COUNTS

    def test_the_upgrade_leaves_no_enum_type_and_the_downgrade_no_table(
        self, session: DbSession
    ) -> None:
        has_type = text("SELECT count(*) FROM pg_type WHERE typname = 'token_kind'")
        has_table = text("SELECT to_regclass('token_kinds') IS NOT NULL")

        assert session.scalar(has_type) == 0
        assert session.scalar(has_table) is True

        _run(session, "downgrade")

        assert session.scalar(has_type) == 1
        assert session.scalar(has_table) is False

    def test_the_downgrade_takes_a_cache_writes_lifetimes_away(
        self, session: DbSession, turn_id: int
    ) -> None:
        session.execute(
            text("DELETE FROM token_counts WHERE turn_id = :turn"), {"turn": turn_id}
        )
        assert _refused(session, turn_id, "cache_write_5m") == "ck_token_counts_kind"

        _run(session, "downgrade")

        assert "invalid input value for enum token_kind" in _refused(
            session, turn_id, "cache_write_5m"
        )
        assert _counts(session, turn_id) == {}
