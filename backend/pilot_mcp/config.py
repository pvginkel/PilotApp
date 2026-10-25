"""The MCP process's settings, read from the environment at startup.

| Variable | Default | What |
| --- | --- | --- |
| `PILOT_MCP_API_URL` | `http://localhost:3501` | the API, as the pod's loopback reaches it |
| `PILOT_MCP_HOST`, `PILOT_MCP_PORT` | `0.0.0.0`, 3502 | where the server listens |
| `PILOT_MCP_LOG_LEVEL` | `INFO` | |
"""

from typing import Literal

from pydantic import HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class McpSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PILOT_MCP_")

    api_url: HttpUrl = HttpUrl("http://localhost:3501")
    host: str = "0.0.0.0"
    port: int = 3502
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
