"""Database connection and session management."""

import logging
import re
from pathlib import Path

from sqlalchemy import MetaData, text
from sqlalchemy.engine import Engine

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.config import Settings
from app.extensions import db

logger = logging.getLogger(__name__)


def get_engine() -> Engine:
    """Get SQLAlchemy engine from current Flask app."""
    return db.engine


def init_db() -> None:
    """Initialize database tables.

    Only creates tables if they don't exist. Safe to call multiple times.
    """
    # Import all models to ensure they're registered with SQLAlchemy
    import app.models  # noqa: F401

    # Create all tables (only if they don't exist)
    db.create_all()


def check_db_connection() -> bool:
    """Check if database connection is working."""
    try:
        with db.engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            return result.scalar() == 1
    except Exception as e:
        logger.warning(f"Checking database connection failed: {e}")
        return False


def _get_alembic_config() -> Config:
    """Get Alembic configuration with database URL from Flask settings."""
    # Assume alembic.ini is in the project root (parent of app/)
    alembic_cfg_path = Path(__file__).parent.parent / "alembic.ini"

    config = Config(str(alembic_cfg_path))

    # Override database URL with current Flask configuration
    settings = Settings.load()
    # Convert Flask-SQLAlchemy URL to raw SQLAlchemy URL (remove +psycopg suffix)
    db_url = settings.database_url.replace("+psycopg", "")
    config.set_main_option("sqlalchemy.url", db_url)

    return config


def get_current_revision() -> str | None:
    """Get current database revision from Alembic version table.

    Optimized version that catches missing table exception instead of checking existence first.
    """
    try:
        with db.engine.connect() as conn:
            result = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
            row = result.fetchone()
            return row[0] if row else None
    except Exception:
        # Table doesn't exist or query failed - treat as no migrations applied
        return None


def get_pending_migrations() -> list[str]:
    """Get list of pending migration revisions.

    Optimized version that reduces queries by reusing connection and catching exceptions.
    """
    try:
        config = _get_alembic_config()

        with db.engine.connect() as connection:
            config.attributes["connection"] = connection
            script = ScriptDirectory.from_config(config)

            # Get current revision (optimized to use single query)
            current_rev = get_current_revision()

            # Get head revision from script directory (no DB query, just reads migration files)
            head_rev = script.get_current_head()

            if not head_rev:
                return []

            if not current_rev:
                # No migrations applied yet, return all from base to head
                revisions = []
                for rev in script.walk_revisions(base="base", head=head_rev):
                    if rev.revision != head_rev:  # Don't include head twice
                        revisions.append(rev.revision)
                revisions.reverse()  # Want chronological order
                revisions.append(head_rev)
                return revisions

            if current_rev == head_rev:
                return []  # Up to date

            # Get pending revisions between current and head
            revisions = []
            for rev in script.walk_revisions(base=current_rev, head=head_rev):
                if rev.revision != current_rev:  # Don't include current
                    revisions.append(rev.revision)

            revisions.reverse()  # Want chronological order
            return revisions

    except Exception:
        # On any error, treat as no pending migrations (fail safe)
        return []


def drop_all_tables() -> None:
    """Drop all tables including Alembic version table."""
    # Use reflection to get all table names
    metadata = MetaData()
    metadata.reflect(bind=db.engine)

    # Drop all tables
    metadata.drop_all(bind=db.engine)

    # Clear SQLAlchemy metadata cache
    db.metadata.clear()


def _get_migration_info(script_dir: ScriptDirectory, revision: str) -> tuple[str, str]:
    """Extract migration info from revision file."""
    try:
        rev_obj = script_dir.get_revision(revision)
        if not rev_obj or not rev_obj.path:
            return revision, "Unknown migration"

        # Read the migration file to get description from docstring
        migration_file = Path(rev_obj.path)
        if not migration_file.exists():
            return revision, "Migration file not found"

        content = migration_file.read_text()

        # Extract description from docstring (first line after triple quotes)
        docstring_match = re.search(r'"""([^"]+)"""', content)
        if docstring_match:
            description = docstring_match.group(1).strip()
            return revision[:7], description  # Short revision + description

        # Fallback: extract from filename slug
        filename = migration_file.name
        slug_match = re.search(r"_([^.]+)\.py$", filename)
        if slug_match:
            slug = slug_match.group(1).replace("_", " ").title()
            return revision[:7], slug

        return revision[:7], "Migration"

    except Exception:
        return revision[:7], "Migration"


def upgrade_database(recreate: bool = False) -> list[tuple[str, str]]:
    """Upgrade database with progress reporting.

    Args:
        recreate: If True, drop all tables first

    Returns:
        List of (revision, description) tuples for applied migrations
    """
    engine = db.engine
    is_sqlite = engine.dialect.name == "sqlite"

    if recreate and is_sqlite:
        # SQLite does not support many ALTER operations required by Alembic migrations.
        # Instead, drop and recreate the schema using SQLAlchemy metadata directly.
        print("SQLite detected - rebuilding schema using SQLAlchemy metadata")
        metadata = MetaData()
        metadata.reflect(bind=engine)

        if metadata.tables:
            print("Dropping all existing tables...")
            metadata.drop_all(bind=engine)
            print("All tables dropped")
        else:
            print("No existing tables found to drop")

        # Ensure models are registered before create_all (create_app imports them already).
        db.create_all()
        config = _get_alembic_config()
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.stamp(config, "head")
        print("Alembic version stamped to head")
        print("Database schema created with SQLAlchemy metadata")
        return []

    config = _get_alembic_config()
    applied_migrations: list[tuple[str, str]] = []

    with db.engine.connect() as connection:
        config.attributes["connection"] = connection
        script = ScriptDirectory.from_config(config)

        if recreate:
            print("Dropping all tables...")
            drop_all_tables()
            print("All tables dropped")

        # Get list of migrations to apply
        pending = get_pending_migrations()

        if not pending:
            return applied_migrations

        # Apply migrations one by one with progress reporting
        for revision in pending:
            rev_short, description = _get_migration_info(script, revision)
            print(f"Applying schema {rev_short} - {description}")

            try:
                # Apply single migration
                command.upgrade(config, revision)
                applied_migrations.append((rev_short, description))

            except Exception as e:
                print(f"Failed to apply migration {rev_short}: {e}")
                raise

        return applied_migrations
