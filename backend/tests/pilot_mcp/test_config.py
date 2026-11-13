"""The MCP process's settings, from `PILOT_MCP_*`."""

import pytest
from pydantic import ValidationError

from pilot_mcp.config import McpSettings, ProjectsSettings

_PROJECTS = {
    "PILOT_MCP_PROJECTS_TOKEN": "a-shared-token",
    "PILOT_MCP_TOKEN_URL": "https://auth.example.com/realms/test/token",
    "PILOT_MCP_SERVICE_CLIENT_ID": "pilot-test-service",
    "PILOT_MCP_SERVICE_CLIENT_SECRET": "a-client-secret",
}
"""The projects surface's four settings, each set."""

_NAMES = (
    "PILOT_MCP_API_URL",
    "PILOT_MCP_HOST",
    "PILOT_MCP_PORT",
    "PILOT_MCP_LOG_LEVEL",
    *_PROJECTS,
)


@pytest.fixture(autouse=True)
def _unset(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _NAMES:
        monkeypatch.delenv(name, raising=False)


class TestMcpSettings:
    def test_the_defaults_are_the_pods(self) -> None:
        settings = McpSettings()

        assert str(settings.api_url) == "http://localhost:3501/"
        assert (settings.host, settings.port) == ("0.0.0.0", 3502)
        assert settings.log_level == "INFO"

    def test_the_environment_sets_each(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PILOT_MCP_API_URL", "http://127.0.0.1:9000")
        monkeypatch.setenv("PILOT_MCP_HOST", "127.0.0.1")
        monkeypatch.setenv("PILOT_MCP_PORT", "9001")
        monkeypatch.setenv("PILOT_MCP_LOG_LEVEL", "DEBUG")

        settings = McpSettings()

        assert str(settings.api_url) == "http://127.0.0.1:9000/"
        assert (settings.host, settings.port) == ("127.0.0.1", 9001)
        assert settings.log_level == "DEBUG"

    @pytest.mark.parametrize(
        ("name", "value", "field"),
        [
            ("PILOT_MCP_API_URL", "localhost:3501", "api_url"),
            ("PILOT_MCP_API_URL", "ftp://localhost", "api_url"),
            ("PILOT_MCP_PORT", "eighty", "port"),
            ("PILOT_MCP_LOG_LEVEL", "CHATTY", "log_level"),
            ("PILOT_MCP_TOKEN_URL", "auth.example.com/token", "token_url"),
        ],
    )
    def test_a_malformed_value_is_refused_naming_it(
        self, monkeypatch: pytest.MonkeyPatch, name: str, value: str, field: str
    ) -> None:
        monkeypatch.setenv(name, value)

        with pytest.raises(ValidationError, match=field):
            McpSettings()


class TestTheProjectsSurfacesSettings:
    def test_unset_the_surface_has_none_and_each_is_named(self) -> None:
        settings = McpSettings()

        assert settings.projects() is None
        assert settings.projects_unset() == list(_PROJECTS)

    def test_all_four_set_are_the_surfaces(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name, value in _PROJECTS.items():
            monkeypatch.setenv(name, value)

        settings = McpSettings()

        assert settings.projects() == ProjectsSettings(
            token="a-shared-token",
            token_url="https://auth.example.com/realms/test/token",
            client_id="pilot-test-service",
            client_secret="a-client-secret",
        )
        assert settings.projects_unset() == []

    @pytest.mark.parametrize("missing", sorted(_PROJECTS))
    @pytest.mark.parametrize("left", ["unset", "empty"])
    def test_one_unset_or_empty_leaves_the_surface_none_and_is_named(
        self, monkeypatch: pytest.MonkeyPatch, missing: str, left: str
    ) -> None:
        for name, value in _PROJECTS.items():
            monkeypatch.setenv(name, value)
        if left == "unset":
            monkeypatch.delenv(missing)
        else:
            monkeypatch.setenv(missing, "")

        settings = McpSettings()

        assert settings.projects() is None
        assert settings.projects_unset() == [missing]

    def test_the_secrets_are_not_in_the_settings_repr(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name, value in _PROJECTS.items():
            monkeypatch.setenv(name, value)

        shown = repr(McpSettings())

        assert "a-shared-token" not in shown
        assert "a-client-secret" not in shown

    def test_the_secrets_are_not_in_the_surfaces_settings_repr(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name, value in _PROJECTS.items():
            monkeypatch.setenv(name, value)

        shown = repr(McpSettings().projects())

        assert "a-shared-token" not in shown
        assert "a-client-secret" not in shown
        assert "pilot-test-service" in shown
