"""App settings: the ticket id pattern (F91), the store's sync, deployment
configuration."""

import re

import pytest

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

    def test_load_reads_the_sync_from_the_environment(self) -> None:
        settings = AppSettings.load(
            AppEnvironment(
                SYNC_TOKEN="example-token",
                STORE_ENVIRONMENT_ID="example-env-1",
                SYNC_PUT_MAX_BYTES=1024,
            )
        )

        assert (
            settings.sync_token,
            settings.store_environment_id,
            settings.sync_put_max_bytes,
        ) == ("example-token", "example-env-1", 1024)

    def test_load_refuses_a_put_limit_below_one_byte(self) -> None:
        with pytest.raises(ValueError):
            AppEnvironment(SYNC_PUT_MAX_BYTES=0)

    def test_the_settings_are_logged_with_the_token_masked(self) -> None:
        settings = AppSettings(
            sync_token="example-token", store_environment_id="example-env-1"
        )

        assert settings.dump_for_logging() == {
            "ticket_id_pattern": repr(re.compile(r"[A-Z][A-Z0-9_]*-[1-9][0-9]*")),
            "sync_token": "***",
            "store_environment_id": "'example-env-1'",
            "sync_put_max_bytes": "2097152",
        }
