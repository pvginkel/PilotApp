"""One revision's step run on a test's transaction, for the tests of what a
revision does to the rows and the schema it meets."""

from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
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
