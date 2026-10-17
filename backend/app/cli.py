"""CLI commands for application operations."""

import sys

import click
from dotenv import load_dotenv
from sqlalchemy import make_url

from app import create_app
from app.app import App
from app.database import (
    check_db_connection,
    get_current_revision,
    get_pending_migrations,
    upgrade_database,
)
from app.startup import load_test_data_hook, post_migration_hook


@click.group()
@click.pass_context
def cli(ctx: click.Context) -> None:
    """pilot CLI."""
    ctx.ensure_object(dict)
    ctx.obj["app"] = create_app(skip_background_services=True)


@cli.command()
@click.option("--recreate", is_flag=True, help="Drop all tables first, then run all migrations from scratch")
@click.option("--yes-i-am-sure", is_flag=True, help="Required safety flag when using --recreate")
@click.pass_context
def upgrade_db(ctx: click.Context, recreate: bool, yes_i_am_sure: bool) -> None:
    """Apply database migrations."""
    handle_upgrade_db(
        app=ctx.obj["app"],
        recreate=recreate,
        confirmed=yes_i_am_sure,
    )


@cli.command()
@click.option("--yes-i-am-sure", is_flag=True, help="Required safety flag to confirm database recreation")
@click.pass_context
def load_test_data(ctx: click.Context, yes_i_am_sure: bool) -> None:
    """Recreate database and load fixed test data."""
    handle_load_test_data(
        app=ctx.obj["app"],
        confirmed=yes_i_am_sure,
    )


def _database_for_display(app: App) -> str:
    """The database URL without its password, to tell the operator the target."""
    return make_url(app.config["SQLALCHEMY_DATABASE_URI"]).render_as_string(hide_password=True)


def _refuse_on_prd(app: App, action: str) -> None:
    """Stop a command that destroys data when the app runs as STAGE=prd."""
    if app.container.config().stage == "prd":
        print(f"Refusing to {action} on STAGE=prd.", file=sys.stderr)
        sys.exit(1)


def handle_upgrade_db(
    app: App, recreate: bool = False, confirmed: bool = False
) -> None:
    """Handle upgrade-db command."""
    with app.app_context():
        # Check database connectivity
        if not check_db_connection():
            print(
                "Cannot connect to database. Check your DATABASE_URL configuration.",
                file=sys.stderr,
            )
            sys.exit(1)

        # Let operator know which database is targeted
        print(f"Using database: {_database_for_display(app)}")

        if recreate:
            _refuse_on_prd(app, "drop and recreate the database")

        # Safety check for recreate
        if recreate and not confirmed:
            print(
                "--recreate requires --yes-i-am-sure flag for safety",
                file=sys.stderr,
            )
            print(
                "   This will DROP ALL TABLES and recreate from migrations!",
                file=sys.stderr,
            )
            sys.exit(1)

        if recreate:
            print("WARNING: About to drop all tables and recreate from migrations!")
            print("   This will permanently delete all data in the database.")

        # Show current state
        current_rev = get_current_revision()
        pending = get_pending_migrations()

        if current_rev:
            print(f"Current database revision: {current_rev}")
        else:
            print("Database has no migration version (empty or new database)")

        # Phase 1: Apply schema migrations (if needed)
        if recreate or pending:
            if recreate:
                print("Recreating database from scratch...")
            elif pending:
                print(f"Found {len(pending)} pending migration(s)")

            # Apply migrations
            try:
                applied = upgrade_database(recreate=recreate)
                if applied:
                    print(f"Successfully applied {len(applied)} migration(s)")
                    for revision, description in applied:
                        print(f"   {revision}: {description}")
                else:
                    print("Database migration completed")
            except Exception as e:
                print(f"Migration failed: {e}", file=sys.stderr)
                sys.exit(1)
        else:
            print("Database is up to date. No migrations to apply.")

        # Phase 2: Run app-specific post-migration hook (master data sync, etc.)
        post_migration_hook(app)


def handle_load_test_data(app: App, confirmed: bool = False) -> None:
    """Handle load-test-data command."""
    with app.app_context():
        # Check database connectivity
        if not check_db_connection():
            print(
                "Cannot connect to database. Check your DATABASE_URL configuration.",
                file=sys.stderr,
            )
            sys.exit(1)

        # Let operator know which database is targeted
        print(f"Using database: {_database_for_display(app)}")

        _refuse_on_prd(app, "drop the database and load test data")

        # Safety check for confirmation
        if not confirmed:
            print(
                "--yes-i-am-sure flag is required for safety",
                file=sys.stderr,
            )
            print(
                "   This will DROP ALL TABLES and recreate with test data!",
                file=sys.stderr,
            )
            sys.exit(1)

        print("WARNING: About to drop all tables and load test data!")
        print("   This will permanently delete all existing data in the database.")

        try:
            # First recreate the database using existing logic
            print("Recreating database from scratch...")
            applied = upgrade_database(recreate=True)

            if applied:
                print(f"Database recreated with {len(applied)} migration(s)")
            else:
                print("Database recreated successfully")

            # Run app-specific test data hook (master data sync, test data, summary)
            load_test_data_hook(app)

        except Exception as e:
            print(f"Failed to load test data: {e}", file=sys.stderr)
            sys.exit(1)


def main() -> None:
    """Main CLI entry point."""
    # Load environment variables from .env file if present
    load_dotenv()

    # Register app-specific commands via hook
    from app.startup import register_cli_commands

    register_cli_commands(cli)

    cli()


if __name__ == "__main__":
    main()
