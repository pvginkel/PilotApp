"""The collector's settings."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from pilot_collector.settings import Settings
from tests.support import settings as given

WALKS = {
    "COLLECTOR_PILOT_URL": "http://pilot.loom.invalid",
    "COLLECTOR_TOKEN": "an-invented-bearer",
    "COLLECTOR_HOME": "/srv/home/.claude",
}
"""The settings with no default, as a process's environment names them."""


class TestTheSettings:
    def test_the_defaults_read_a_kubecoder_environment(self) -> None:
        settings = given()

        named = settings.COLLECTOR_ENVIRONMENT_PATTERN.match(
            "# Environment: cleo-loom-7a41d9\n\nYou are running inside a workspace."
        )
        assert named is not None and named.group(1) == "cleo-loom-7a41d9"
        assert settings.COLLECTOR_CHECKOUT_ROOTS == ["/work"]

    def test_each_is_read_from_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name, value in WALKS.items():
            monkeypatch.setenv(name, value)
        monkeypatch.setenv("COLLECTOR_ENVIRONMENT_PATTERN", r"# Host: (\w+)")
        monkeypatch.setenv("COLLECTOR_CHECKOUT_ROOTS", '["/srv/checkouts", "/work"]')

        settings = Settings()

        assert settings.COLLECTOR_PILOT_URL == "http://pilot.loom.invalid"
        assert settings.COLLECTOR_TOKEN.get_secret_value() == "an-invented-bearer"
        assert settings.COLLECTOR_HOME == Path("/srv/home/.claude")
        assert settings.COLLECTOR_ENVIRONMENT_PATTERN.pattern == r"# Host: (\w+)"
        assert settings.COLLECTOR_CHECKOUT_ROOTS == ["/srv/checkouts", "/work"]

    @pytest.mark.parametrize("missing", sorted(WALKS))
    def test_pilots_address_the_bearer_and_the_home_have_no_default(
        self, monkeypatch: pytest.MonkeyPatch, missing: str
    ) -> None:
        for name, value in WALKS.items():
            monkeypatch.setenv(name, value)
        monkeypatch.delenv(missing)

        with pytest.raises(ValidationError, match=f"{missing}\n  Field required"):
            Settings()

    def test_the_bearer_is_kept_out_of_what_the_settings_print(self) -> None:
        settings = given(COLLECTOR_TOKEN="an-invented-bearer")

        assert "an-invented-bearer" not in repr(settings)

    @pytest.mark.parametrize(
        ("pattern", "fault"),
        [
            ("# Environment: ", "no group for the environment's id"),
            ("# Environment: (", "Input should be a valid regular expression"),
        ],
    )
    def test_a_pattern_that_names_no_id_is_refused(
        self, pattern: str, fault: str
    ) -> None:
        with pytest.raises(ValidationError, match=fault):
            given(COLLECTOR_ENVIRONMENT_PATTERN=pattern)

    def test_a_checkout_root_that_is_no_absolute_path_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="`work` is no absolute path"):
            given(COLLECTOR_CHECKOUT_ROOTS=["work"])
