"""The MCP process's settings, from `PILOT_MCP_*`."""

import pytest
from pydantic import ValidationError

from pilot_mcp.config import McpSettings

_NAMES = (
    "PILOT_MCP_API_URL",
    "PILOT_MCP_HOST",
    "PILOT_MCP_PORT",
    "PILOT_MCP_LOG_LEVEL",
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
        ],
    )
    def test_a_malformed_value_is_refused_naming_it(
        self, monkeypatch: pytest.MonkeyPatch, name: str, value: str, field: str
    ) -> None:
        monkeypatch.setenv(name, value)

        with pytest.raises(ValidationError, match=field):
            McpSettings()
