"""The app's startup hooks: the seed `cli load-test-data` loads (slice 002 P9)."""

import pytest
from flask import Flask
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.app import App
from app.engine.bus import EngineEvent, TreeHashMoved
from app.models import Project
from app.services.container import ServiceContainer
from app.startup import load_test_data_hook


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
        assert "   - 11 items\n" in out
