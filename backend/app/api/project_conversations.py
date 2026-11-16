"""A project's conversations as its people read them (F150.12): the calling
sessions' conversations with Pilot about the project, listed, each by the
environment and the session that opened it, and Pilot's answer in one stopped
(F44). A conversation's records are its session's.

No person writes into a conversation: its messages are its caller's, through
the routes a service user alone calls (`conversations.py`).

Access is the API's `editor` gate.
"""

import uuid
from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint
from spectree import Response as SpectreeResponse

from app.api.caller import caller
from app.schemas.common import ApiErrorResponseSchema
from app.schemas.links import EnvironmentNameSchema
from app.schemas.project_conversations import (
    ProjectConversationListSchema,
    ProjectConversationSchema,
)
from app.services.container import ServiceContainer
from app.services.conversation_read_service import (
    ConversationReadService,
    ProjectConversation,
)
from app.services.conversation_service import ConversationService
from app.services.people_service import PeopleService
from app.utils.spectree_config import api

project_conversations_bp = Blueprint(
    "project_conversations", __name__, url_prefix="/projects"
)


@project_conversations_bp.route("/<uuid:project_id>/conversations", methods=["GET"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=ProjectConversationListSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
    ),
)
@inject
def list_project_conversations(
    project_id: uuid.UUID,
    conversation_read_service: ConversationReadService = Provide[
        ServiceContainer.conversation_read_service
    ],
) -> Any:
    """Read the project's conversations, whoever opened them, in the order
    they opened, each open or closed with its cause, and whether Pilot is
    answering in it.

    Returns:
        200: The project's conversations
        401: No one is signed in
        403: The caller lacks the editor role
        404: No project has the id
    """
    return ProjectConversationListSchema(
        conversations=[
            _conversation(entry)
            for entry in conversation_read_service.of_project(project_id)
        ]
    ).model_dump(mode="json")


@project_conversations_bp.route(
    "/<uuid:project_id>/conversations/<uuid:conversation_id>/stop", methods=["POST"]
)
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=ProjectConversationSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def stop_project_conversation(
    project_id: uuid.UUID,
    conversation_id: uuid.UUID,
    conversation_service: ConversationService = Provide[
        ServiceContainer.conversation_service
    ],
    conversation_read_service: ConversationReadService = Provide[
        ServiceContainer.conversation_read_service
    ],
    people_service: PeopleService = Provide[ServiceContainer.people_service],
) -> Any:
    """Stop Pilot's answer in the project's conversation where it is, as the
    signed-in person, whoever opened it (F44): a turn in flight is
    interrupted, the conversation kept open for its caller's next message,
    and a start held or under way ends, nothing of it sent afterwards. The
    interrupt runs once the request commits; a controller that does not
    answer lets the turn run out.

    Returns:
        200: The conversation, Pilot no longer answering in it
        401: No one is signed in
        403: The caller lacks the editor role
        404: No conversation of the project has the id
        409: The caller has not chosen a handle, or Pilot is not answering
            in the conversation
    """
    person = people_service.require_person(
        caller(), f"stop Pilot in conversation {conversation_id}"
    )
    conversation_service.stop(project_id, conversation_id, person)
    return _conversation(
        conversation_read_service.one_of_project(project_id, conversation_id)
    ).model_dump(mode="json")


def _conversation(entry: ProjectConversation) -> ProjectConversationSchema:
    conversation = entry.conversation
    return ProjectConversationSchema(
        id=conversation.id,
        environment=EnvironmentNameSchema(
            id=entry.environment.id, name=entry.environment.name
        ),
        session=conversation.caller_session,
        opened_at=entry.opened_at,
        closed_at=conversation.closed_at,
        close_cause=conversation.close_cause_code,
        answering=entry.answering,
    )
