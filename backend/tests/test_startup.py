"""The app's startup hooks: the engine's listener that turns PostgreSQL's JIT
off, the price file a deploy loads after the revisions with Pilot's own
system views, the seed `cli load-test-data` loads (slice 002 P9), and the
app's CLI commands."""

import click
import pytest
from flask import Flask
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session as DbSession

from app.app import App
from app.dashboard.views import VIEWS
from app.engine.bus import EngineEvent, TreeHashMoved
from app.extensions import db
from app.models import Price, Project, QuickFilter, SavedView
from app.models.reference import Origin
from app.service_user_cli import create_service_user
from app.services.container import ServiceContainer
from app.services.price_service import read_price_file
from app.startup import (
    load_test_data_hook,
    post_migration_hook,
    register_cli_commands,
)
from app.store_update_cli import update_store
from tests.support import transcripts


class TestConfigureEngine:
    def test_a_connection_reads_with_jit_off_from_its_first_transaction(
        self, app: Flask
    ) -> None:
        with app.app_context():
            engine = db.engine

        with engine.connect() as connection:
            assert connection.scalar(text("SHOW jit")) == "off"

    def test_a_connection_left_with_jit_on_reads_off_in_its_next_transaction(
        self, app: Flask
    ) -> None:
        # A pooler in transaction mode hands a transaction whichever server
        # connection is free, as the client before it left it.
        with app.app_context():
            engine = db.engine

        with engine.connect() as connection:
            try:
                connection.exec_driver_sql("SET jit = on")
                connection.commit()

                assert connection.scalar(text("SHOW jit")) == "off"
            finally:
                connection.invalidate()


def _prices(db: DbSession) -> int:
    return db.scalar(select(func.count()).select_from(Price)) or 0


def _pilots_views(db: DbSession) -> set[str | None]:
    return set(
        db.scalars(select(SavedView.key).where(SavedView.origin_code == Origin.PILOT))
    )


class TestPostMigrationHook:
    def test_it_loads_the_price_file_and_prints_what_it_wrote(
        self,
        app: Flask,
        container: ServiceContainer,
        session: DbSession,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert isinstance(app, App)
        session.execute(delete(Price).where(Price.model_code == "claude-opus-5-5"))

        post_migration_hook(app)

        assert _prices(session) == len(read_price_file())
        assert capsys.readouterr().out == (
            "Prices loaded: 5 added, 0 models priced as another or no longer,"
            " 0 calls priced\n"
            "Call caches derived: 0 calls of 0 transcripts\n"
            "Pilot's system views: 0 added, 0 changed, 0 removed\n"
        )

    def test_it_gives_a_stored_call_with_no_caches_its_caches(
        self,
        app: Flask,
        container: ServiceContainer,
        session: DbSession,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert isinstance(app, App)
        thread = transcripts.transcript(session, transcripts.component_version(session))
        call = transcripts.call(session, thread, 1)

        post_migration_hook(app)

        session.refresh(call)
        assert (call.rewind, call.cache_miss, call.past_ttl) == (False, False, False)
        assert (
            "Call caches derived: 1 calls of 1 transcripts\n" in capsys.readouterr().out
        )

    def test_it_makes_pilots_own_system_views_what_the_release_holds(
        self,
        app: Flask,
        container: ServiceContainer,
        session: DbSession,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert isinstance(app, App)
        session.execute(delete(SavedView).where(SavedView.key == "projects"))

        post_migration_hook(app)

        assert _pilots_views(session) == {view.key for view in VIEWS}
        assert capsys.readouterr().out.endswith(
            "Pilot's system views: 1 added, 0 changed, 0 removed\n"
        )

    def test_a_removed_quick_filter_stays_removed(
        self, app: Flask, container: ServiceContainer, session: DbSession
    ) -> None:
        """The revisions write the shipped ones once; no deploy writes them."""
        assert isinstance(app, App)
        session.execute(delete(QuickFilter).where(QuickFilter.code == "misses"))

        post_migration_hook(app)

        assert "misses" not in set(session.scalars(select(QuickFilter.code)))


class TestLoadTestDataHook:
    def test_it_loads_the_price_file(
        self, app: Flask, container: ServiceContainer, session: DbSession
    ) -> None:
        assert isinstance(app, App)
        session.execute(delete(Price))

        load_test_data_hook(app)

        assert _prices(session) == len(read_price_file())

    def test_it_ships_pilots_own_system_views(
        self, app: Flask, container: ServiceContainer, session: DbSession
    ) -> None:
        assert isinstance(app, App)
        session.execute(delete(SavedView))

        load_test_data_hook(app)

        assert _pilots_views(session) == {view.key for view in VIEWS}

    def test_it_commits_the_seed_and_prints_its_counts(
        self,
        app: Flask,
        container: ServiceContainer,
        session: DbSession,
        engine_events: list[EngineEvent],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert isinstance(app, App)

        load_test_data_hook(app)

        assert session.scalars(select(Project.slug).order_by(Project.slug)).all() == [
            "bike-log",
            "photo-album",
            "recipe-box",
            None,
        ]
        recipes = session.scalars(
            select(Project).where(Project.slug == "recipe-box")
        ).one()
        draft_hash = container.tree_service().hashes(recipes)["recipe-box/project.md"]
        # The bus delivers once the seed's transaction committed.
        assert TreeHashMoved("recipe-box/project.md", draft_hash) in engine_events
        out = capsys.readouterr().out
        assert "   - 4 projects\n" in out
        assert "   - 15 items\n" in out


class TestRegisterCliCommands:
    def test_it_registers_update_store_and_create_service_user(self) -> None:
        group = click.Group()

        register_cli_commands(group)

        assert group.commands == {
            "update-store": update_store,
            "create-service-user": create_service_user,
        }
