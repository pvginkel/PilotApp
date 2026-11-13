"""App-specific startup hooks.

Hook points called by create_app():
  - configure_engine()
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
from sqlalchemy import Connection, Engine, event

from app.app import App
from app.database import scoped_session
from app.services.container import ServiceContainer


def configure_engine(engine: Engine) -> None:
    """Configure the app's engine, before anything opens a connection on it:
    PostgreSQL's JIT off in every transaction.

    No read of the app gains from JIT, and once a plan passes
    `jit_above_cost` its compile alone takes seconds where the query runs in
    milliseconds. It is set per transaction, as the transaction's first
    statement: the stages reach PostgreSQL through a pooler in transaction
    mode, which drops a connection's startup `options` and hands each
    transaction whichever server connection is free, so a setting made once
    per connection holds nothing there."""
    event.listen(engine, "begin", _jit_off)


def _jit_off(connection: Connection) -> None:
    connection.exec_driver_sql("SET LOCAL jit = off")


def create_container() -> ServiceContainer:
    """Create and configure the application's service container."""
    return ServiceContainer()


def register_blueprints(api_bp: Blueprint, app: Flask) -> None:
    """Register all app-specific blueprints on api_bp (under /api prefix)."""
    # api_bp is the process's one; a second app (the tests build several)
    # finds it registered already, with these on it.
    if not api_bp._got_registered_once:
        from app.api.app_pages import app_pages_bp
        from app.api.attachments import attachments_bp
        from app.api.chats import chats_bp
        from app.api.conditions import conditions_bp
        from app.api.items import items_bp
        from app.api.links import links_bp
        from app.api.people import people_bp
        from app.api.projects import projects_bp
        from app.api.quota_overrules import quota_overrules_bp
        from app.api.sessions import sessions_bp
        from app.api.testing_record import testing_record_bp
        from app.api.tree import tree_bp
        from app.api.web_push import web_push_bp

        api_bp.register_blueprint(app_pages_bp)
        api_bp.register_blueprint(attachments_bp)
        api_bp.register_blueprint(chats_bp)
        api_bp.register_blueprint(conditions_bp)
        api_bp.register_blueprint(items_bp)
        api_bp.register_blueprint(links_bp)
        api_bp.register_blueprint(people_bp)
        api_bp.register_blueprint(projects_bp)
        api_bp.register_blueprint(quota_overrules_bp)
        api_bp.register_blueprint(sessions_bp)
        api_bp.register_blueprint(testing_record_bp)
        api_bp.register_blueprint(tree_bp)
        api_bp.register_blueprint(web_push_bp)


def register_error_handlers(app: Flask) -> None:
    """Register app-specific error handlers."""
    pass


def register_root_blueprints(app: Flask) -> None:
    """Register app-specific blueprints directly on the app, outside api_bp's
    OIDC gate: the store sidecar's sync routes, under the store's bearer; the
    tracker-events endpoint, under the tracker's token; the tool routes of the
    worker's and the brain's sessions, under each session's bearer, outside
    `/api/`; and the testing endpoints refused outside testing mode, the pool
    guard's nestings and the statement cap's statements among them."""
    from app.api.pilot_store import pilot_store_bp
    from app.api.pilot_work import pilot_work_bp
    from app.api.sync import sync_bp
    from app.api.testing_controller import testing_controller_bp
    from app.api.testing_links import testing_links_bp
    from app.api.testing_pool_guard import testing_pool_guard_bp
    from app.api.testing_push_service import testing_push_service_bp
    from app.api.testing_statement_cap import testing_statement_cap_bp
    from app.api.testing_sync import testing_sync_bp
    from app.api.tracker_events import tracker_events_bp

    app.register_blueprint(sync_bp)
    app.register_blueprint(tracker_events_bp)
    app.register_blueprint(pilot_work_bp)
    app.register_blueprint(pilot_store_bp)
    app.register_blueprint(testing_sync_bp)
    app.register_blueprint(testing_links_bp)
    app.register_blueprint(testing_controller_bp)
    app.register_blueprint(testing_push_service_bp)
    app.register_blueprint(testing_pool_guard_bp)
    app.register_blueprint(testing_statement_cap_bp)


def register_cli_commands(cli: click.Group) -> None:
    """Register app-specific CLI commands: `update-store`, the operator's
    update of the store while Pilot runs (F144.1), and `create-service-user`,
    which makes a service user's row (DB 338)."""
    from app.service_user_cli import create_service_user
    from app.store_update_cli import update_store

    cli.add_command(update_store)
    cli.add_command(create_service_user)


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
