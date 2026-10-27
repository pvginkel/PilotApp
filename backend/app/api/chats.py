"""A person's message to a project's brain (F38.3, F130; design 3 §5.3): a
turn of the project's open chat, or the chat started with it in the store;
Pilot's answer in it stopped (F44); and the project's chats as a person reads
them, with their place in them (F40.3, F43).

Access is the API's `editor` gate.
"""

import uuid
from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from spectree import Response as SpectreeResponse
from sqlalchemy.orm import Session

from app.api.caller import caller
from app.engine.views import ListedChat
from app.models import Session as AgentSession
from app.schemas.chats import (
    ChatListSchema,
    ChatMessageRequestSchema,
    ChatReadSchema,
    ChatSchema,
    ChatTurnSchema,
)
from app.schemas.common import ApiErrorResponseSchema
from app.services.chat_read_service import ChatReadService, answering
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
    with none open, or with its start failed, the chat started with it, a
    draft's its definition chat, its first turn the chat's brief and the
    words, which goes out once its session is up in the store, held while the
    controller is unreachable.

    A send the controller fails is the turn's `error` (F125).

    Returns:
        201: The message's turn in the chat
        400: The message has no words
        401: No one is signed in
        403: The caller lacks the editor role
        404: No project has the id
        409: The caller has not chosen a handle; the project is archived;
            the chat is starting or a turn of it is in flight; or no
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


@chats_bp.route("/<uuid:project_id>/chat/stop", methods=["POST"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=ChatSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def stop_chat(
    project_id: uuid.UUID,
    chat_service: ChatService = Provide[ServiceContainer.chat_service],
    people_service: PeopleService = Provide[ServiceContainer.people_service],
) -> Any:
    """Stop Pilot's answer in the project's open chat where it is, as the
    signed-in person, whoever sent the message (F44): a turn in flight is
    interrupted, the conversation kept for the next message, and a start held
    or under way ends, nothing of it sent afterwards, so the next message
    starts the chat afresh. The interrupt runs once the request commits; a
    controller that does not answer lets the turn run out.

    Returns:
        200: The chat, Pilot no longer answering in it
        401: No one is signed in
        403: The caller lacks the editor role
        404: No project has the id
        409: The caller has not chosen a handle; no chat of the project is
            open, or Pilot is not answering in it
    """
    person = people_service.require_person(
        caller(), f"stop Pilot in project {project_id}"
    )
    return _chat(chat_service.stop(project_id, person)).model_dump(mode="json")


@chats_bp.route("/<uuid:project_id>/chats", methods=["GET"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=ChatListSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
    ),
)
@inject
def list_chats(
    project_id: uuid.UUID,
    chat_read_service: ChatReadService = Provide[ServiceContainer.chat_read_service],
    people_service: PeopleService = Provide[ServiceContainer.people_service],
) -> Any:
    """Read the project's chats, the definition chat first where one exists,
    then the project's chats in the order they opened, each open or closed
    with its cause; and the caller's place in them, whether a reply of
    Pilot's came after they last saw the chat to its end. A chat's records
    are its session's.

    Returns:
        200: The project's chats and the caller's place in them
        401: No one is signed in
        403: The caller lacks the editor role
        404: No project has the id
    """
    listed = chat_read_service.chats(project_id, people_service.find(caller()))
    return ChatListSchema(
        chats=[_chat(entry) for entry in listed.chats],
        read_at=listed.place.read_at,
        unread=listed.place.unread,
    ).model_dump(mode="json")


@chats_bp.route("/<uuid:project_id>/chat/read", methods=["PUT"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=ChatReadSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def read_chat(
    project_id: uuid.UUID,
    chat_read_service: ChatReadService = Provide[ServiceContainer.chat_read_service],
    people_service: PeopleService = Provide[ServiceContainer.people_service],
) -> Any:
    """Say the signed-in person has seen the project's chat to its end now,
    on whichever device: their place in it, one per person and project.

    Returns:
        200: The caller's place in the project's chat
        401: No one is signed in
        403: The caller lacks the editor role
        404: No project has the id
        409: The caller has not chosen a handle
    """
    person = people_service.require_person(
        caller(), f"mark the chat of project {project_id} read"
    )
    place = chat_read_service.read(project_id, person)
    return ChatReadSchema(read_at=place.read_at, unread=place.unread).model_dump(
        mode="json"
    )


def _chat(entry: ListedChat) -> ChatSchema:
    return ChatSchema(
        id=entry.chat.id,
        kind=entry.chat.kind_code,
        opened_at=entry.opened_at,
        closed_at=entry.chat.closed_at,
        close_cause=entry.chat.close_cause_code,
        answering=answering(entry),
    )
