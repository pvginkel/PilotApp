"""What links in text (F91, F93): the deployment's link settings, with the
record's environments."""

from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint
from spectree import Response as SpectreeResponse

from app.app_config import AppSettings
from app.schemas.common import ApiErrorResponseSchema
from app.schemas.links import EnvironmentNameSchema, LinksResponseSchema
from app.services.container import ServiceContainer
from app.services.link_service import LinkService
from app.utils.spectree_config import api

links_bp = Blueprint("links", __name__, url_prefix="/links")


@links_bp.route("", methods=["GET"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=LinksResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
    )
)
@inject
def get_links(
    app_config: AppSettings = Provide[ServiceContainer.app_config],
    link_service: LinkService = Provide[ServiceContainer.link_service],
) -> Any:
    """Read what text links: ticket ids, by the pattern and the URL template,
    and environments, by KubeCoder's address; unset, they show unlinked.

    Returns:
        200: The link settings and the record's environments
        401: No one is signed in
        403: The caller lacks the editor role
    """
    return LinksResponseSchema(
        ticket_id_pattern=app_config.ticket_id_pattern.pattern,
        ticket_url_template=app_config.ticket_url_template,
        environment_link_base_url=app_config.environment_link_base_url,
        environments=[
            EnvironmentNameSchema(id=environment.id, name=environment.name)
            for environment in link_service.environments()
        ],
    ).model_dump()
