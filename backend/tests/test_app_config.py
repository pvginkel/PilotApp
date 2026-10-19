"""App settings: the ticket id pattern and the link settings (F91, F93), the store's sync,
deployment configuration."""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.app_config import AppEnvironment, AppSettings


class TestAppSettings:
    @pytest.mark.parametrize("ticket", ["MD-8", "KC-153", "P-1", "MY_APP-20"])
    def test_the_default_pattern_takes_the_trackers_ids(self, ticket: str) -> None:
        assert AppSettings().ticket_id_pattern.fullmatch(ticket)

    @pytest.mark.parametrize("ticket", ["md-8", "MD-08", "MD8", "8-MD", "MD-8 x"])
    def test_the_default_pattern_refuses_other_ids(self, ticket: str) -> None:
        assert not AppSettings().ticket_id_pattern.fullmatch(ticket)

    def test_load_reads_the_pattern_from_the_environment(self) -> None:
        settings = AppSettings.load(AppEnvironment(TICKET_ID_PATTERN=r"#[0-9]+"))

        assert settings.ticket_id_pattern.fullmatch("#12")
        assert not settings.ticket_id_pattern.fullmatch("MD-8")

    def test_load_refuses_a_pattern_that_does_not_compile(self) -> None:
        with pytest.raises(re.error):
            AppSettings.load(AppEnvironment(TICKET_ID_PATTERN="(MD"))

    def test_the_sync_refuses_every_call_by_default(self) -> None:
        settings = AppSettings()

        assert (settings.sync_token, settings.store_environment_id) == ("", "")
        assert settings.sync_put_max_bytes == 2 * 1024 * 1024
        assert settings.sync_heartbeat_seconds == 15.0

    def test_load_reads_the_sync_from_the_environment(self) -> None:
        settings = AppSettings.load(
            AppEnvironment(
                SYNC_TOKEN="example-token",
                STORE_ENVIRONMENT_ID="example-env-1",
                SYNC_PUT_MAX_BYTES=1024,
                SYNC_HEARTBEAT_SECONDS=2.5,
            )
        )

        assert (
            settings.sync_token,
            settings.store_environment_id,
            settings.sync_put_max_bytes,
            settings.sync_heartbeat_seconds,
        ) == ("example-token", "example-env-1", 1024, 2.5)

    def test_load_refuses_a_put_limit_below_one_byte(self) -> None:
        with pytest.raises(ValueError):
            AppEnvironment(SYNC_PUT_MAX_BYTES=0)

    def test_load_refuses_a_heartbeat_that_is_not_positive(self) -> None:
        with pytest.raises(ValueError):
            AppEnvironment(SYNC_HEARTBEAT_SECONDS=0)

    def test_load_reads_the_controller_from_the_environment(
        self, tmp_path: Path
    ) -> None:
        ca_file = tmp_path / "ca.pem"
        ca_file.write_text("a CA's certificate")

        settings = AppSettings.load(
            AppEnvironment(
                CONTROLLER_URL="https://controller.example",
                CONTROLLER_TOKEN="a-token",
                CONTROLLER_CA_FILE=str(ca_file),
            )
        )

        assert settings.controller_url == "https://controller.example"
        assert settings.controller_token == "a-token"
        assert settings.controller_ca_file == ca_file

    def test_load_refuses_a_ca_file_that_is_not_there(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="controller_ca_file"):
            AppSettings.load(
                AppEnvironment(
                    _env_file=None, CONTROLLER_CA_FILE=str(tmp_path / "missing.pem")
                )
            )

    def test_an_empty_controller_url_is_no_controller(self) -> None:
        settings = AppSettings.load(
            AppEnvironment(
                CONTROLLER_URL="",
                CONTROLLER_TOKEN="",
                CONTROLLER_CA_FILE="",
            )
        )

        assert settings.controller_url is None
        assert settings.controller_token == ""
        assert settings.controller_ca_file is None

    def test_the_scheduler_ticks_every_ten_seconds_by_default(self) -> None:
        assert (
            AppSettings.load(AppEnvironment(_env_file=None)).scheduler_tick_seconds
            == 10
        )

    def test_load_reads_the_scheduler_tick_from_the_environment(self) -> None:
        settings = AppSettings.load(
            AppEnvironment(_env_file=None, SCHEDULER_TICK_SECONDS=0.5)
        )

        assert settings.scheduler_tick_seconds == 0.5

    def test_load_refuses_a_tick_that_is_not_positive(self) -> None:
        with pytest.raises(ValidationError, match="SCHEDULER_TICK_SECONDS"):
            AppEnvironment(_env_file=None, SCHEDULER_TICK_SECONDS=0)

    def test_an_environment_stands_idle_thirty_minutes_by_default(self) -> None:
        settings = AppSettings.load(AppEnvironment(_env_file=None))

        assert settings.environment_stop_after_seconds == 1800

    def test_load_reads_the_environments_stop_after_from_the_environment(
        self,
    ) -> None:
        settings = AppSettings.load(
            AppEnvironment(_env_file=None, ENVIRONMENT_STOP_AFTER_SECONDS=90)
        )

        assert settings.environment_stop_after_seconds == 90

    def test_load_refuses_a_stop_after_that_is_not_positive(self) -> None:
        with pytest.raises(ValidationError, match="ENVIRONMENT_STOP_AFTER_SECONDS"):
            AppEnvironment(_env_file=None, ENVIRONMENT_STOP_AFTER_SECONDS=0)

    def test_the_controller_token_is_hidden_in_the_log(self) -> None:
        settings = AppSettings(
            controller_url="https://controller.example", controller_token="a-token"
        )

        dumped = settings.dump_for_logging()

        assert dumped["controller_url"] == repr("https://controller.example")
        assert dumped["controller_token"] == "***"

    def test_the_settings_are_logged_with_the_token_masked(self) -> None:
        settings = AppSettings(
            sync_token="example-token", store_environment_id="example-env-1"
        )

        assert settings.dump_for_logging() == {
            "ticket_id_pattern": repr(re.compile(r"[A-Z][A-Z0-9_]*-[1-9][0-9]*")),
            "sync_token": "***",
            "store_environment_id": "'example-env-1'",
            "sync_put_max_bytes": "2097152",
            "sync_heartbeat_seconds": "15.0",
            "ticket_url_template": "None",
            "environment_link_base_url": "None",
            "controller_url": "None",
            "controller_token": "***",
            "controller_ca_file": "None",
            "scheduler_tick_seconds": repr(10.0),
            "environment_stop_after_seconds": repr(1800.0),
        }

    def test_the_link_settings_are_unset_by_default(self) -> None:
        settings = AppSettings.load(AppEnvironment())

        assert settings.ticket_url_template is None
        assert settings.environment_link_base_url is None

    def test_load_reads_the_link_settings_from_the_environment(self) -> None:
        settings = AppSettings.load(
            AppEnvironment(
                TICKET_URL_TEMPLATE="https://tracker.example.com/issue/{id}",
                ENVIRONMENT_LINK_BASE_URL="https://kubecoder.example.com",
            )
        )

        assert settings.ticket_url_template == "https://tracker.example.com/issue/{id}"
        assert settings.environment_link_base_url == "https://kubecoder.example.com"

    def test_an_empty_link_setting_is_unset(self) -> None:
        settings = AppSettings.load(
            AppEnvironment(TICKET_URL_TEMPLATE="", ENVIRONMENT_LINK_BASE_URL="")
        )

        assert settings.ticket_url_template is None
        assert settings.environment_link_base_url is None

    def test_the_base_loses_its_trailing_slash(self) -> None:
        settings = AppSettings(
            environment_link_base_url="http://kubecoder.example.com/"
        )

        assert settings.environment_link_base_url == "http://kubecoder.example.com"

    def test_a_template_without_the_id_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="must hold {id}"):
            AppSettings.load(
                AppEnvironment(TICKET_URL_TEMPLATE="https://tracker.example.com/issue/")
            )

    @pytest.mark.parametrize(
        "base", ["kubecoder.example.com", "ftp://kubecoder.example.com"]
    )
    def test_a_base_that_is_no_http_address_is_refused(self, base: str) -> None:
        with pytest.raises(ValidationError, match="must be an http"):
            AppSettings.load(AppEnvironment(ENVIRONMENT_LINK_BASE_URL=base))

    def test_the_settings_are_logged_as_they_stand(self) -> None:
        settings = AppSettings(ticket_url_template="https://tracker.example.com/{id}")

        assert settings.dump_for_logging() == {
            "ticket_id_pattern": repr(re.compile(r"[A-Z][A-Z0-9_]*-[1-9][0-9]*")),
            "sync_token": "***",
            "store_environment_id": repr(""),
            "sync_put_max_bytes": "2097152",
            "sync_heartbeat_seconds": "15.0",
            "ticket_url_template": repr("https://tracker.example.com/{id}"),
            "environment_link_base_url": "None",
            "controller_url": "None",
            "controller_token": "***",
            "controller_ca_file": repr(None),
            "scheduler_tick_seconds": repr(10.0),
            "environment_stop_after_seconds": repr(1800.0),
        }
