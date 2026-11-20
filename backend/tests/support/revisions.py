"""One revision's step run on a test's transaction, for the tests of what a
revision does to the rows and the schema it meets."""

from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session

_BACKEND_DIR = Path(__file__).resolve().parents[2]


def run_revision(db: Session, revision_id: str, step: str) -> None:
    """The revision's `step`, `upgrade`, `downgrade` or a function of its
    module that one of them calls, on the test's transaction; what the
    session holds is read again after an upgrade."""
    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    revision = ScriptDirectory.from_config(config).get_revision(revision_id)
    assert revision is not None
    with Operations.context(MigrationContext.configure(db.connection())):
        getattr(revision.module, step)()
    if step == "upgrade":
        db.expire_all()


def restore_later_index_on_step_transcripts(db: Session) -> None:
    """Make again, on the test's transaction, the index on `step_transcripts`
    that a revision after 0048 made, which revision 0048's downgrade drops
    with the table."""
    db.execute(
        text(
            "CREATE INDEX ix_step_transcripts_session_id"
            " ON step_transcripts (session_id)"
        )
    )


def drop_later_keys_to_token_kinds(db: Session) -> None:
    """Drop, on the test's transaction, the keys to `token_kinds` that the
    revisions after 0038 made, the Prices' among them, which revision 0038's
    downgrade, dropping the table, cannot run under."""
    db.execute(text("ALTER TABLE prices DROP CONSTRAINT prices_token_kind_code_fkey"))
