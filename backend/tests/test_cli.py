"""The CLI: its database announcement keeps the password out of the log, and
`update-store` makes the store's update and reports it to the lift (F144.1)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from click.testing import CliRunner
from flask import Flask
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import cli
from app.app import App
from app.models import StoreUpdate
from app.services.container import ServiceContainer
from app.services.store_update_service import unlifted, utc_time
from app.store_update_cli import POLL_SECONDS, handle_update_store, update_store

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


AT = datetime(2026, 10, 13, 6, 2, 11, tzinfo=UTC)
"""Where the stand-in server's phases start."""

Step = Callable[[StoreUpdate], None]


def _set(**columns: object) -> Step:
    """A step of the stand-in server: these columns written on the row."""

    def write(update: StoreUpdate) -> None:
        for column, value in columns.items():
            setattr(update, column, value)

    return write


class _Server:
    """Stands in for the server's sequence, which nothing runs yet: each of
    the command's sleeps writes the next step on the row it polls."""

    def __init__(self, session: Session, *steps: Step) -> None:
        self._session = session
        self._steps = list(steps)
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        step = self._steps.pop(0)
        update = self._session.scalars(
            select(StoreUpdate).order_by(StoreUpdate.id.desc()).limit(1)
        ).one()
        step(update)
        self._session.flush()


def _no_sleep(seconds: float) -> None:
    raise AssertionError("the command waited")


@pytest.fixture
def cli_app(app: Flask, container: ServiceContainer) -> App:
    """The session app, its commands' sessions the test's."""
    assert isinstance(app, App)
    return app


def _made(update: StoreUpdate) -> str:
    return (
        f"Update made at {utc_time(update.made_at)}: Pilot's chats and jobs are held.\n"
    )


class TestUpdateStore:
    def test_without_waiting_it_sets_the_hold_and_returns(
        self, cli_app: App, session: Session, capsys: pytest.CaptureFixture[str]
    ) -> None:
        handle_update_store(cli_app, lift=False, wait=False, sleep=_no_sleep)

        update = session.scalars(select(StoreUpdate)).one()
        assert unlifted(session) is update
        assert capsys.readouterr().out == _made(update)

    def test_it_prints_each_phase_as_the_server_writes_it_and_returns_at_the_lift(
        self, cli_app: App, session: Session, capsys: pytest.CaptureFixture[str]
    ) -> None:
        server = _Server(
            session,
            _set(),
            _set(stopped_at=AT),
            _set(reset_at=AT + timedelta(seconds=48)),
            _set(),
            _set(
                reconciled_at=AT + timedelta(seconds=79),
                lifted_at=AT + timedelta(seconds=80),
            ),
        )

        handle_update_store(cli_app, lift=False, wait=True, sleep=server.sleep)

        update = session.scalars(select(StoreUpdate)).one()
        assert server.sleeps == [POLL_SECONDS] * 5
        assert capsys.readouterr().out == (
            _made(update)
            + "The store's chats and jobs stopped at 2026-10-13 06:02:11 UTC.\n"
            "The store reset and running again at 2026-10-13 06:02:59 UTC.\n"
            "The store's tree written down again at 2026-10-13 06:03:30 UTC.\n"
            "Lifted at 2026-10-13 06:03:31 UTC: Pilot's chats and jobs go on.\n"
        )

    def test_it_prints_the_rows_error_each_time_it_appears(
        self, cli_app: App, session: Session, capsys: pytest.CaptureFixture[str]
    ) -> None:
        refused = "the reset settled error: setup failed"
        server = _Server(
            session,
            _set(stopped_at=AT, error=refused),
            _set(),
            _set(error=None),
            _set(error=refused),
            _set(error="the controller refused the reset"),
            _set(error=None, reset_at=AT + timedelta(minutes=5)),
            _set(lifted_at=AT + timedelta(minutes=6)),
        )

        handle_update_store(cli_app, lift=False, wait=True, sleep=server.sleep)

        update = session.scalars(select(StoreUpdate)).one()
        failed = "The update's last attempt failed, the server tries again: "
        assert capsys.readouterr().out == (
            _made(update)
            + "The store's chats and jobs stopped at 2026-10-13 06:02:11 UTC.\n"
            f"{failed}{refused}\n"
            f"{failed}{refused}\n"
            f"{failed}the controller refused the reset\n"
            "The store reset and running again at 2026-10-13 06:07:11 UTC.\n"
            "Lifted at 2026-10-13 06:08:11 UTC: Pilot's chats and jobs go on.\n"
        )

    def test_it_is_refused_while_an_update_is_unlifted_naming_when_and_the_lift(
        self, cli_app: App, session: Session, capsys: pytest.CaptureFixture[str]
    ) -> None:
        session.add(StoreUpdate(made_at=AT))
        # Past the refusal's rollback, which returns to the last commit.
        session.commit()

        with pytest.raises(SystemExit) as exited:
            handle_update_store(cli_app, lift=False, wait=True, sleep=_no_sleep)

        assert exited.value.code == 1
        printed = capsys.readouterr()
        assert printed.out == ""
        assert printed.err == (
            "Cannot update the store because an update is under way since "
            "2026-10-13 06:02:11 UTC\n"
            "`update-store --lift` asks the server to lift it.\n"
        )
        assert session.scalar(select(func.count()).select_from(StoreUpdate)) == 1

    def test_the_lift_asks_the_server_and_waits_for_it(
        self, cli_app: App, session: Session, capsys: pytest.CaptureFixture[str]
    ) -> None:
        standing = StoreUpdate(made_at=AT, stopped_at=AT + timedelta(seconds=2))
        session.add(standing)
        session.flush()
        server = _Server(session, _set(), _set(lifted_at=AT + timedelta(hours=1)))

        handle_update_store(cli_app, lift=True, wait=True, sleep=server.sleep)

        assert standing.lift_requested_at is not None
        assert server.sleeps == [POLL_SECONDS] * 2
        assert capsys.readouterr().out == (
            _made(standing)
            + "The store's chats and jobs stopped at 2026-10-13 06:02:13 UTC.\n"
            f"Lift asked at {utc_time(standing.lift_requested_at)}: the server "
            "skips what remains, retries what the update stopped and lifts the "
            "hold.\n"
            "Lifted at 2026-10-13 07:02:11 UTC: Pilot's chats and jobs go on.\n"
        )

    def test_without_waiting_the_lift_returns_once_asked(
        self, cli_app: App, session: Session, capsys: pytest.CaptureFixture[str]
    ) -> None:
        standing = StoreUpdate(made_at=AT)
        session.add(standing)
        session.flush()

        handle_update_store(cli_app, lift=True, wait=False, sleep=_no_sleep)

        assert standing.lift_requested_at is not None
        assert standing.lifted_at is None
        assert capsys.readouterr().out == (
            _made(standing)
            + f"Lift asked at {utc_time(standing.lift_requested_at)}: the server "
            "skips what remains, retries what the update stopped and lifts the "
            "hold.\n"
        )

    def test_the_lift_is_refused_while_no_update_is_under_way(
        self, cli_app: App, session: Session, capsys: pytest.CaptureFixture[str]
    ) -> None:
        session.add(StoreUpdate(made_at=AT, lifted_at=AT + timedelta(minutes=1)))
        session.flush()

        with pytest.raises(SystemExit) as exited:
            handle_update_store(cli_app, lift=True, wait=True, sleep=_no_sleep)

        assert exited.value.code == 1
        assert capsys.readouterr().err == (
            "Cannot lift the store's update because no update is under way\n"
        )

    @pytest.mark.parametrize(
        ("arguments", "asked"),
        [(["--no-wait"], False), (["--lift", "--no-wait"], True)],
    )
    def test_its_flags_reach_the_command(
        self, cli_app: App, session: Session, arguments: list[str], asked: bool
    ) -> None:
        if asked:
            session.add(StoreUpdate(made_at=AT))
            session.flush()

        result = CliRunner().invoke(update_store, arguments, obj={"app": cli_app})

        assert result.exit_code == 0, result.output
        update = session.scalars(select(StoreUpdate)).one()
        assert (update.lift_requested_at is not None) is asked
        assert update.lifted_at is None
