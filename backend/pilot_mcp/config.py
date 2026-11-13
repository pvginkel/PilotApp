"""The MCP process's settings, read from the environment at startup.

| Variable | Default | What |
| --- | --- | --- |
| `PILOT_MCP_API_URL` | `http://localhost:3501` | the API, as the pod's loopback reaches it |
| `PILOT_MCP_HOST`, `PILOT_MCP_PORT` | `0.0.0.0`, 3502 | where the server listens |
| `PILOT_MCP_LOG_LEVEL` | `INFO` | |
| `PILOT_MCP_PROJECTS_TOKEN` | none | the projects surface's shared token, its callers' bearer |
| `PILOT_MCP_TOKEN_URL` | none | the token endpoint of the service user's Keycloak client |
| `PILOT_MCP_SERVICE_CLIENT_ID`, `PILOT_MCP_SERVICE_CLIENT_SECRET` | none | that client |

The last four are the projects surface's (F150.1, F150.13). While one of them
is unset or empty the surface refuses every call, and the rest of the process
serves.
"""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECTS = (
    "projects_token",
    "token_url",
    "service_client_id",
    "service_client_secret",
)

_PREFIX = "PILOT_MCP_"


@dataclass(frozen=True)
class ProjectsSettings:
    """The projects surface's settings, each one set; the two secrets out of
    its repr."""

    token: str = field(repr=False)
    token_url: str
    client_id: str
    client_secret: str = field(repr=False)


class McpSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix=_PREFIX)

    api_url: HttpUrl = HttpUrl("http://localhost:3501")
    host: str = "0.0.0.0"
    port: int = 3502
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    projects_token: SecretStr | None = None
    token_url: HttpUrl | None = None
    service_client_id: str | None = None
    service_client_secret: SecretStr | None = None

    @field_validator(*_PROJECTS, mode="before")
    @classmethod
    def _empty_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    def projects_unset(self) -> list[str]:
        """The variables of the projects surface that are unset."""
        return [
            f"{_PREFIX}{name.upper()}"
            for name in _PROJECTS
            if getattr(self, name) is None
        ]

    def projects(self) -> ProjectsSettings | None:
        """The projects surface's settings; None while one is unset."""
        if (
            self.projects_token is None
            or self.token_url is None
            or self.service_client_id is None
            or self.service_client_secret is None
        ):
            return None
        return ProjectsSettings(
            token=self.projects_token.get_secret_value(),
            token_url=str(self.token_url),
            client_id=self.service_client_id,
            client_secret=self.service_client_secret.get_secret_value(),
        )
