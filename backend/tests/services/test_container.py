"""The container's start of the controller's client (design 2 §14; V12), its
supervisor (design 2 §7), and the jobs registered on it (design 2 §9, §13)."""

import logging
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy.orm import Session

from app import create_app
from app.app_config import AppSettings
from app.config import Settings
from app.database import scoped_session
from app.exceptions import ConfigurationError
from app.models import Environment, Project, User
from app.models import Session as AgentSession
from app.models.reference import SessionState, UserKind
from app.services.container import ServiceContainer, start_controller_client
from app.services.controller_client import HeadlessCreateRequest
from app.services.environment_service import EnvironmentService
from app.services.fleet_consumer import FleetConsumer
from app.services.relay_service import RelayService
from app.services.supervisor import Supervisor
from tests.conftest_infrastructure import (
    _clear_prometheus_registry,
    _create_test_app,
    _dispose_app,
)
from tests.support.fake_controller import ServedFakeController, client_of, raw_turn
from tests.support.supervisor import wait_until
from tests.support.tls import invent_ca


def _container(settings: Settings, app_settings: AppSettings) -> ServiceContainer:
    container = ServiceContainer()
    container.config.override(settings)
    container.app_config.override(app_settings)
    return container


def _checks(app: Flask, container: ServiceContainer) -> dict[str, object]:
    with app.app_context():
        body, _ = container.health_service().check_readyz()
    checks: dict[str, object] = body["checks"]
    return checks


class TestStartControllerClient:
    @pytest.mark.parametrize(
        "app_settings",
        [
            AppSettings(),
            AppSettings(controller_url="http://controller.example"),
            AppSettings(controller_token="a-token"),
        ],
        ids=["neither", "no-token", "no-url"],
    )
    def test_production_refuses_to_start_without_a_controller(
        self, test_settings: Settings, app_settings: AppSettings
    ) -> None:
        container = _container(
            test_settings.model_copy(update={"flask_env": "production"}), app_settings
        )

        with pytest.raises(
            ConfigurationError, match="CONTROLLER_URL and CONTROLLER_TOKEN"
        ):
            start_controller_client(container)

    def test_production_with_a_controller_builds_its_client_and_check(
        self, app: Flask, test_settings: Settings, fake_controller: ServedFakeController
    ) -> None:
        container = _container(
            test_settings.model_copy(update={"flask_env": "production"}),
            AppSettings(controller_url=fake_controller.url, controller_token="a-token"),
        )

        start_controller_client(container)

        assert _checks(app, container)["controller"] == {
            "status": "ok",
            "critical": False,
        }

    def test_with_no_controller_the_app_runs_without_one(
        self, app: Flask, test_settings: Settings
    ) -> None:
        container = _container(test_settings, AppSettings())

        start_controller_client(container)

        assert "controller" not in _checks(app, container)

    def test_outside_production_a_url_is_enough(
        self, app: Flask, test_settings: Settings, fake_controller: ServedFakeController
    ) -> None:
        container = _container(
            test_settings, AppSettings(controller_url=fake_controller.url)
        )

        start_controller_client(container)

        assert "controller" in _checks(app, container)

    def test_the_client_verifies_the_controller_against_its_ca_file(
        self, app: Flask, test_settings: Settings, tmp_path: Path
    ) -> None:
        authority = invent_ca(tmp_path)
        tls_controller = ServedFakeController(keepalive_seconds=0.2, tls=authority)
        try:
            container = _container(
                test_settings,
                AppSettings(
                    controller_url=tls_controller.url,
                    controller_ca_file=authority.ca_file,
                ),
            )

            start_controller_client(container)

            assert _checks(app, container)["controller"] == {
                "status": "ok",
                "critical": False,
            }
        finally:
            tls_controller.close()

    def test_a_production_server_without_a_controller_does_not_start(
        self, test_settings: Settings
    ) -> None:
        _clear_prometheus_registry()

        with pytest.raises(ConfigurationError):
            create_app(
                test_settings.model_copy(update={"flask_env": "production"}),
                app_settings=AppSettings(),
            )

    def test_the_cli_builds_a_production_app_without_a_controller(
        self, test_settings: Settings
    ) -> None:
        # The chart's migrate init container: the CLI's app, with none of the
        # controller's settings.
        production = _create_test_app(
            test_settings.model_copy(update={"flask_env": "production"}), AppSettings()
        )

        _dispose_app(production)


class TestSupervisorWiring:
    def test_the_supervisor_ticks_as_the_settings_say(
        self, committed_app: Flask
    ) -> None:
        container = committed_app.container
        container.app_config.override(AppSettings(scheduler_tick_seconds=0.05))
        supervisor = container.supervisor()
        ticks: list[int] = []
        ticked = threading.Event()

        def timer(db: Session) -> None:
            ticks.append(len(ticks) + 1)
            if len(ticks) == 3:
                ticked.set()

        supervisor.register_timer("probe", timer, needs_controller=False)
        container.lifecycle_coordinator().fire_startup()

        assert isinstance(supervisor, Supervisor)
        assert supervisor is container.supervisor()
        assert ticked.wait(5)

    @pytest.mark.parametrize(
        ("app_settings", "said"),
        [
            (AppSettings(), True),
            (AppSettings(controller_url="http://controller.example"), False),
        ],
        ids=["no-controller", "controller"],
    )
    def test_the_supervisor_knows_whether_a_controller_is_configured(
        self,
        test_settings: Settings,
        app_settings: AppSettings,
        said: bool,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        container = _container(test_settings, app_settings)
        container.supervisor().register_job("fleet", needs_controller=True)
        coordinator = container.lifecycle_coordinator()

        with caplog.at_level(logging.INFO, logger="app.services.supervisor"):
            coordinator.fire_startup()
        coordinator.shutdown()

        assert (
            "No controller configured (CONTROLLER_URL unset): the jobs and timers "
            "that need one do not start (fleet)" in caplog.messages
        ) is said


class TestEnvironmentWiring:
    def test_the_fleet_consumer_and_the_shutdown_timer_run_from_startup(
        self, committed_app: Flask, fake_controller: ServedFakeController
    ) -> None:
        container = committed_app.container
        container.app_config.override(
            AppSettings(
                controller_url=fake_controller.url,
                scheduler_tick_seconds=0.05,
                environment_stop_after_seconds=0.01,
            )
        )
        client_of(container, fake_controller)
        fake_controller.add_environment("env-pilots", status="running")
        fake_controller.add_environment("env-other", status="running")
        with scoped_session(container) as db:
            db.add_all(
                [
                    # Pilot started it, and nothing runs there: a restart lost
                    # its arm.
                    Environment(
                        id="env-pilots",
                        name="Pilot's",
                        exempt=False,
                        server_started_at=datetime.now(UTC),
                    ),
                    Environment(id="env-other", name="Other", exempt=False),
                ]
            )
        assert isinstance(container.fleet_consumer(), FleetConsumer)
        assert isinstance(container.environment_service(), EnvironmentService)
        coordinator = container.lifecycle_coordinator()

        coordinator.fire_startup()
        try:
            wait_until(
                lambda: fake_controller.environment("env-pilots").status == "stopped",
                "stopped by the timer",
            )
            wait_until(
                lambda: _last_state(container, "env-pilots") == "stopped",
                "its state frame applied",
            )
        finally:
            coordinator.shutdown()

        assert fake_controller.environment("env-other").status == "running"
        assert _last_state(container, "env-other") == "running"


class TestRelayWiring:
    def test_a_send_after_startup_is_relayed_to_its_turns_end(
        self, committed_app: Flask, fake_controller: ServedFakeController
    ) -> None:
        container = committed_app.container
        container.app_config.override(
            AppSettings(controller_url=fake_controller.url, scheduler_tick_seconds=0.05)
        )
        client = client_of(container, fake_controller)
        fake_controller.add_environment("env-a", status="running")
        name = client.create_headless_session("env-a", HeadlessCreateRequest()).name
        with scoped_session(container) as db:
            person = User(
                kind_code=UserKind.PERSON,
                subject="subject-ada",
                handle="ada",
                name="Ada Example",
                avatar_slot=1,
            )
            db.add_all([person, Environment(id="env-a", name="A", exempt=False)])
            db.flush()
            project = Project(created_by_user_id=person.id)
            db.add(project)
            db.flush()
            run = AgentSession(
                project_id=project.id,
                environment_id="env-a",
                kind_code="work",
                cwd="/work/Example",
                controller_session=name,
                token_hash="1" * 64,
                state_code=SessionState.IDLE,
            )
            db.add(run)
            db.flush()
            run_id = run.id
        relays = container.relay_service()
        assert isinstance(relays, RelayService)
        coordinator = container.lifecycle_coordinator()

        coordinator.fire_startup()
        try:
            with scoped_session(container) as db:
                relays.send(db, run_id, "Rename the badge")
            fake_controller.play("env-a", name, raw_turn("turn_text"))
            fake_controller.finish("env-a", name)
            wait_until(lambda: _turns_ended(container, run_id) == 1, "the turn ended")
        finally:
            coordinator.shutdown()


def _turns_ended(container: ServiceContainer, run_id: uuid.UUID) -> int | None:
    with scoped_session(container) as db:
        run = db.get_one(AgentSession, run_id)
        return run.turns if run.state_code == SessionState.IDLE else None


def _last_state(container: ServiceContainer, env_id: str) -> str | None:
    with scoped_session(container) as db:
        environment = db.get(Environment, env_id)
        assert environment is not None
        return environment.last_state
