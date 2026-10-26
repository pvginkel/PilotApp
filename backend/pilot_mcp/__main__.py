"""`python -m pilot_mcp`: Pilot's MCP server on the settings in the
environment, the backend image's second entry point."""

import logging

import uvicorn

from pilot_mcp.api import PilotStoreApi, PilotWorkApi
from pilot_mcp.config import McpSettings
from pilot_mcp.server import build_app


def main() -> None:
    settings = McpSettings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    api_url = str(settings.api_url)
    uvicorn.run(
        build_app(PilotWorkApi(api_url), PilotStoreApi(api_url)),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
