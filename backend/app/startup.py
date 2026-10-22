"""App-specific startup hooks.

Hook points called by create_app():
  - create_container()
  - register_blueprints()
  - register_error_handlers()
  - register_root_blueprints()

Hook points called by CLI command handlers:
  - register_cli_commands()
  - post_migration_hook()
  - load_test_data_hook()
"""

from __future__ import annotations

import click
from flask import Blueprint, Flask

from app.app import App
from app.database import scoped_session
from app.services.container import ServiceContainer


def create_container() -> ServiceContainer:
    """Create and configure the application's service container."""
    return ServiceContainer()


def register_blueprints(api_bp: Blueprint, app: Flask) -> None:
    """Register all app-specific blueprints on api_bp (under /api prefix)."""
    # api_bp is the process's one; a second app (the tests build several)
    # finds it registered already, with these on it.
    if not api_bp._got_registered_once:
        from app.api.items import items_bp
        from app.api.links import links_bp
        from app.api.people import people_bp
        from app.api.projects import projects_bp
        from app.api.sessions import sessions_bp

        api_bp.register_blueprint(items_bp)
        api_bp.register_blueprint(links_bp)
        api_bp.register_blueprint(people_bp)
        api_bp.register_blueprint(projects_bp)
        api_bp.register_blueprint(sessions_bp)


def register_error_handlers(app: Flask) -> None:
    """Register app-specific error handlers."""
    pass


def register_root_blueprints(app: Flask) -> None:
    """Register app-specific blueprints directly on the app, outside api_bp's
    OIDC gate: the store sidecar's sync routes, under the store's bearer, and
    the sync's testing endpoints, refused outside testing mode."""
    from app.api.sync import sync_bp
    from app.api.testing_controller import testing_controller_bp
    from app.api.testing_links import testing_links_bp
    from app.api.testing_record import testing_record_bp
    from app.api.testing_sessions import testing_sessions_bp
    from app.api.testing_sync import testing_sync_bp

    app.register_blueprint(sync_bp)
    app.register_blueprint(testing_sync_bp)
    app.register_blueprint(testing_links_bp)
    app.register_blueprint(testing_record_bp)
    app.register_blueprint(testing_controller_bp)
    app.register_blueprint(testing_sessions_bp)


def register_cli_commands(cli: click.Group) -> None:
    """Register app-specific CLI commands."""
    pass


def post_migration_hook(app: Flask) -> None:
    """Run after database migrations (e.g., sync master data)."""
    pass


def load_test_data_hook(app: App) -> None:
    """Load the invented record (`TestDataService`) after database recreation."""
    print("Loading the invented record...")
    with scoped_session(app.container):
        counts = app.container.test_data_service().load_all()
    print("Test data loaded:")
    for entity, count in counts.items():
        print(f"   - {count} {entity}")
