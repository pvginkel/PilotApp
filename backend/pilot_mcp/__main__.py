"""`python -m pilot_mcp`: Pilot's MCP server on the settings in the
environment, the backend image's second entry point."""

import logging

import uvicorn

from pilot_mcp.api import PilotProjectsApi, PilotStoreApi, PilotWorkApi
from pilot_mcp.config import McpSettings
from pilot_mcp.credential import ServiceCredential
from pilot_mcp.server import ProjectsSurface, build_app

logger = logging.getLogger(__name__)


def projects_surface(settings: McpSettings) -> ProjectsSurface | None:
    """The projects surface on `settings`; None, the surface closed, while
    one of its settings is unset."""
    projects = settings.projects()
    if projects is None:
        logger.warning(
            "The projects surface refuses every call: %s unset",
            ", ".join(settings.projects_unset()),
        )
        return None
    credential = ServiceCredential(
        projects.token_url, projects.client_id, projects.client_secret
    )
    return ProjectsSurface(
        token=projects.token,
        api=PilotProjectsApi(str(settings.api_url), credential),
    )


def main() -> None:
    settings = McpSettings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    api_url = str(settings.api_url)
    uvicorn.run(
        build_app(
            PilotWorkApi(api_url), PilotStoreApi(api_url), projects_surface(settings)
        ),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
