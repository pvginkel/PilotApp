"""A person's message to a project's brain (F38.3, F130; design 3 §5.3): a
turn of the project's open chat, or the chat started with it in the store.

Access is the API's `editor` gate.
"""

import uuid
from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from spectree import Response as SpectreeResponse
from sqlalchemy.orm import Session

from app.api.caller import caller
from app.models import Session as AgentSession
from app.schemas.chats import ChatMessageRequestSchema, ChatTurnSchema
from app.schemas.common import ApiErrorResponseSchema
from app.services.chat_service import ChatService
from app.services.container import ServiceContainer
from app.services.people_service import PeopleService
from app.utils.spectree_config import api

chats_bp = Blueprint("chats", __name__, url_prefix="/projects")


@chats_bp.route("/<uuid:project_id>/chat/messages", methods=["POST"])
@api.validate(
    json=ChatMessageRequestSchema,
    resp=SpectreeResponse(
        HTTP_201=ChatTurnSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def send_chat_message(
    project_id: uuid.UUID,
    chat_service: ChatService = Provide[ServiceContainer.chat_service],
    people_service: PeopleService = Provide[ServiceContainer.people_service],
    db: Session = Provide[ServiceContainer.db_session],
) -> Any:
    """Send Pilot a message in the project, as the signed-in person, the
    words verbatim: a turn of the project's open chat, its send made now; or,
    with none open, or with its start failed, the chat started with it, its
    first turn the chat's brief and the words, which goes out once its
    session is up in the store, held while the controller is unreachable.

    A send the controller fails is the turn's `error` (F125).

    Returns:
        201: The message's turn in the chat
        400: The message has no words
        401: No one is signed in
        403: The caller lacks the editor role
        404: No project has the id
        409: The caller has not chosen a handle; the project is a draft or
            archived; the chat is starting or a turn of it is in flight; or no
            controller or store environment is configured
    """
    words = ChatMessageRequestSchema.model_validate(request.get_json()).words
    person = people_service.require_person(
        caller(), f"send a message to Pilot in project {project_id}"
    )
    turn = chat_service.send(project_id, person, words)
    session = db.get_one(AgentSession, turn.session_id)
    return ChatTurnSchema(
        chat=turn.session_id, seq=turn.seq, state=session.state_code, error=turn.error
    ).model_dump(mode="json"), 201
