"""The CLI's database announcement keeps the password out of the log."""

import pytest
from flask import Flask

from app import cli
from app.app import App

URI = "postgresql+psycopg://pilot:s3cret-password@db.test/pilot?sslmode=prefer"


@pytest.fixture
def connected_app(app: Flask, monkeypatch: pytest.MonkeyPatch) -> App:
    assert isinstance(app, App)
    monkeypatch.setattr(cli, "check_db_connection", lambda: True)
    # The session app serves every later test: undo the URI at teardown.
    monkeypatch.setitem(app.config, "SQLALCHEMY_DATABASE_URI", URI)
    return app


def test_upgrade_db_masks_the_password(
    connected_app: App, capsys: pytest.CaptureFixture[str]
) -> None:
    # --recreate without --yes-i-am-sure exits right after the announcement.
    with pytest.raises(SystemExit):
        cli.handle_upgrade_db(connected_app, recreate=True)

    out = capsys.readouterr().out
    assert "s3cret-password" not in out
    assert "Using database: postgresql+psycopg://pilot:***@db.test/pilot" in out


def test_load_test_data_masks_the_password(
    connected_app: App, capsys: pytest.CaptureFixture[str]
) -> None:
    # Without --yes-i-am-sure it exits right after the announcement.
    with pytest.raises(SystemExit):
        cli.handle_load_test_data(connected_app)

    out = capsys.readouterr().out
    assert "s3cret-password" not in out
    assert "Using database: postgresql+psycopg://pilot:***@db.test/pilot" in out
