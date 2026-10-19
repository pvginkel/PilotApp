"""The container's start of the controller's client (design 2 §14; V12), and its
supervisor (design 2 §7)."""

import logging
import threading
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy.orm import Session

from app import create_app
from app.app_config import AppSettings
from app.config import Settings
from app.exceptions import ConfigurationError
from app.services.container import ServiceContainer, start_controller_client
from app.services.supervisor import Supervisor
from tests.conftest_infrastructure import (
    _clear_prometheus_registry,
    _create_test_app,
    _dispose_app,
)
from tests.support.fake_controller import ServedFakeController
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
