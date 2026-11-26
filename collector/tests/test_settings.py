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

    def test_the_carries_are_bound_at_2500_transcripts_and_64_mb(self) -> None:
        settings = given()

        assert settings.COLLECTOR_CARRY_TRANSCRIPTS == 2_500
        assert settings.COLLECTOR_CARRY_BYTES == 64_000_000

    def test_the_readings_are_served_on_port_3503(self) -> None:
        assert given().COLLECTOR_PORT == 3_503

    def test_the_labeller_is_the_installed_copys_given_a_minute_a_call(
        self,
    ) -> None:
        """The command `labeller.md` § Running it names."""
        settings = given()

        assert settings.COLLECTOR_LABELLER == [
            "python3",
            "-B",
            "{install_path}/tools/labeller.py",
        ]
        assert settings.COLLECTOR_LABELLER_SECONDS == 60.0

    def test_each_is_read_from_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name, value in WALKS.items():
            monkeypatch.setenv(name, value)
        monkeypatch.setenv("COLLECTOR_ENVIRONMENT_PATTERN", r"# Host: (\w+)")
        monkeypatch.setenv("COLLECTOR_CHECKOUT_ROOTS", '["/srv/checkouts", "/work"]')
        monkeypatch.setenv("COLLECTOR_CARRY_TRANSCRIPTS", "40")
        monkeypatch.setenv("COLLECTOR_CARRY_BYTES", "0")
        monkeypatch.setenv("COLLECTOR_PORT", "8088")
        monkeypatch.setenv("COLLECTOR_LABELLER", '["/srv/loom/label", "--quiet"]')
        monkeypatch.setenv("COLLECTOR_LABELLER_SECONDS", "4.5")

        settings = Settings()

        assert settings.COLLECTOR_PILOT_URL == "http://pilot.loom.invalid"
        assert settings.COLLECTOR_TOKEN.get_secret_value() == "an-invented-bearer"
        assert settings.COLLECTOR_HOME == Path("/srv/home/.claude")
        assert settings.COLLECTOR_ENVIRONMENT_PATTERN.pattern == r"# Host: (\w+)"
        assert settings.COLLECTOR_CHECKOUT_ROOTS == ["/srv/checkouts", "/work"]
        assert settings.COLLECTOR_CARRY_TRANSCRIPTS == 40
        assert settings.COLLECTOR_CARRY_BYTES == 0
        assert settings.COLLECTOR_PORT == 8_088
        assert settings.COLLECTOR_LABELLER == ["/srv/loom/label", "--quiet"]
        assert settings.COLLECTOR_LABELLER_SECONDS == 4.5

    @pytest.mark.parametrize("missing", sorted(WALKS))
    def test_pilots_address_the_bearer_and_the_home_have_no_default(
        self, monkeypatch: pytest.MonkeyPatch, missing: str
    ) -> None:
        for name, value in WALKS.items():
            monkeypatch.setenv(name, value)
        monkeypatch.delenv(missing)

        with pytest.raises(ValidationError, match=f"{missing}\n  Field required"):
            Settings()

    def test_a_bearer_of_no_characters_is_refused(self) -> None:
        """A reading is served to a call that carries the bearer, so there
        is one."""
        with pytest.raises(
            ValidationError,
            match="COLLECTOR_TOKEN\n  Value should have at least 1 item",
        ):
            given(COLLECTOR_TOKEN="")

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

    @pytest.mark.parametrize(
        "bound", ["COLLECTOR_CARRY_TRANSCRIPTS", "COLLECTOR_CARRY_BYTES"]
    )
    def test_a_bound_of_the_carries_below_none_is_refused(self, bound: str) -> None:
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            given(**{bound: -1})

    @pytest.mark.parametrize(
        ("port", "fault"),
        [(-1, "greater than or equal to 0"), (65_536, "less than or equal to 65535")],
    )
    def test_a_port_that_is_none_is_refused(self, port: int, fault: str) -> None:
        with pytest.raises(ValidationError, match=fault):
            given(COLLECTOR_PORT=port)

    def test_a_labeller_command_of_no_word_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="at least 1 item"):
            given(COLLECTOR_LABELLER=[])

    def test_a_labellers_time_of_none_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="greater than 0"):
            given(COLLECTOR_LABELLER_SECONDS=0)
