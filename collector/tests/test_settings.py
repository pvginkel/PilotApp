"""The collector's settings."""

import pytest
from pydantic import ValidationError

from pilot_collector.settings import Settings


class TestTheSettings:
    def test_the_defaults_read_a_kubecoder_environment(self) -> None:
        settings = Settings()

        named = settings.COLLECTOR_ENVIRONMENT_PATTERN.match(
            "# Environment: cleo-loom-7a41d9\n\nYou are running inside a workspace."
        )
        assert named is not None and named.group(1) == "cleo-loom-7a41d9"
        assert settings.COLLECTOR_CHECKOUT_ROOTS == ["/work"]

    def test_each_is_read_from_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("COLLECTOR_ENVIRONMENT_PATTERN", r"# Host: (\w+)")
        monkeypatch.setenv("COLLECTOR_CHECKOUT_ROOTS", '["/srv/checkouts", "/work"]')

        settings = Settings()

        assert settings.COLLECTOR_ENVIRONMENT_PATTERN.pattern == r"# Host: (\w+)"
        assert settings.COLLECTOR_CHECKOUT_ROOTS == ["/srv/checkouts", "/work"]

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
            Settings(COLLECTOR_ENVIRONMENT_PATTERN=pattern)  # type: ignore[arg-type]

    def test_a_checkout_root_that_is_no_absolute_path_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="`work` is no absolute path"):
            Settings(COLLECTOR_CHECKOUT_ROOTS=["work"])
