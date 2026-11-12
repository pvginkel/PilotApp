"""The app's startup hooks: the engine's listener that turns PostgreSQL's JIT
off, the seed `cli load-test-data` loads (slice 002 P9), and the app's CLI
commands."""

import click
import pytest
from flask import Flask
from sqlalchemy import select, text
from sqlalchemy.orm import Session as DbSession

from app.app import App
from app.engine.bus import EngineEvent, TreeHashMoved
from app.extensions import db
from app.models import Project
from app.service_user_cli import create_service_user
from app.services.container import ServiceContainer
from app.startup import load_test_data_hook, register_cli_commands
from app.store_update_cli import update_store


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


class TestLoadTestDataHook:
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
        assert "   - 12 items\n" in out


class TestRegisterCliCommands:
    def test_it_registers_update_store_and_create_service_user(self) -> None:
        group = click.Group()

        register_cli_commands(group)

        assert group.commands == {
            "update-store": update_store,
            "create-service-user": create_service_user,
        }
