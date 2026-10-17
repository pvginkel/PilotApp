"""Schema tests: the Alembic revisions build what the models describe.

Template-owned. Every test database is built by the revisions (see
conftest_infrastructure.py), so a revision that fails already stops the run at
setup. These tests check what the revisions built.
"""

from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.orm import Session

from app.extensions import db

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _script_directory() -> ScriptDirectory:
    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    return ScriptDirectory.from_config(config)


def test_database_is_at_head(session: Session) -> None:
    """The run's database carries the newest revision, or none without revisions."""
    context = MigrationContext.configure(session.connection())

    assert set(context.get_current_heads()) == set(_script_directory().get_heads())


def test_models_match_revisions(session: Session) -> None:
    """Nothing is left for ``alembic revision --autogenerate`` to find.

    A model change without its revision fails here, and so does a revision
    that builds something the models don't describe.
    """
    context = MigrationContext.configure(session.connection())

    assert compare_metadata(context, db.metadata) == []
