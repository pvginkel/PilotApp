"""A calling session's conversation with Pilot about a project (F150.10,
F150.11; DB Conversation, assertions 334 to 337): opened with its first
message, sent its next, read, listed, interrupted and ended.

The routes are a service user's alone, its second write beside starting a
project (F150.2): a call to Pilot's projects surface comes as it, and names
where it came from in two headers, the environment's id and the session's
name there. A person is refused each of them.

A conversation answers to the service user and the environment that opened
it. A call about one another opened, one that names no environment among
them, is answered as for an id that never was.
"""

import uuid
from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from spectree import Response as SpectreeResponse

from app.api.caller import caller
from app.exceptions import ValidationException
from app.schemas.common import ApiErrorResponseSchema
from app.schemas.conversations import (
    ConversationListQuerySchema,
    ConversationListSchema,
    ConversationMessageRequestSchema,
    ConversationOpenRequestSchema,
    ConversationSchema,
    ConversationTurnSchema,
)
from app.services.caller_environment_service import (
    CALLER_ENVIRONMENT_HEADER,
    CALLER_SESSION_HEADER,
)
from app.services.container import ServiceContainer
from app.services.conversation_read_service import (
    ConversationReadService,
    ListedConversation,
)
from app.services.conversation_service import ConversationService
from app.services.people_service import PeopleService
from app.services.project_service import ProjectService
from app.utils.spectree_config import api

conversations_bp = Blueprint("conversations", __name__, url_prefix="/conversations")


def _calling_environment() -> str | None:
    """The id of the environment the call came from; none where its header is
    absent or empty."""
    return request.headers.get(CALLER_ENVIRONMENT_HEADER) or None


def _conversation(listed: ListedConversation) -> ConversationSchema:
    conversation = listed.conversation
    return ConversationSchema(
        id=conversation.id,
        project_id=conversation.project_id,
        environment=conversation.caller_environment_id,
        session=conversation.caller_session,
        opened_at=listed.opened_at,
        closed_at=conversation.closed_at,
        close_cause=conversation.close_cause_code,
        turns=listed.turns,
        in_flight=listed.in_flight,
    )


@conversations_bp.route("", methods=["POST"])
@api.validate(
    json=ConversationOpenRequestSchema,
    resp=SpectreeResponse(
        HTTP_201=ConversationSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def open_conversation(
    conversation_service: ConversationService = Provide[
        ServiceContainer.conversation_service
    ],
    conversation_read_service: ConversationReadService = Provide[
        ServiceContainer.conversation_read_service
    ],
    people_service: PeopleService = Provide[ServiceContainer.people_service],
    project_service: ProjectService = Provide[ServiceContainer.project_service],
) -> Any:
    """Open a conversation with Pilot about the project an address names,
    with the calling session's first message, as the service user: a session
    of its own beside the project's chat and its other conversations, its
    first turn the conversation's brief and the words, which goes out once
    the session is up, held while the controller is unreachable. It is the
    calling environment's, the request's `X-Pilot-Environment`, and keeps the
    session's name, its `X-Pilot-Session`. An environment Pilot has no row of
    is written one, named as the controller reports it, else by its id.

    Returns:
        201: The conversation, its first turn in flight
        400: The message has no words, no address is given, or the request
            names no environment
        401: No one is signed in
        403: The caller lacks the editor role
        404: No project is at the address
        409: The caller is no service user; the project is a draft or
            archived; Pilot is updating its store; or no controller or store
            environment is configured
    """
    body = ConversationOpenRequestSchema.model_validate(request.get_json())
    operation = "open a conversation with Pilot"
    user = people_service.require_service_user(caller(), operation)
    environment = _calling_environment()
    if environment is None:
        raise ValidationException(
            f"Cannot {operation} because the call names no environment, and a"
            " conversation is its calling environment's"
        )
    project = project_service.at_address(body.address)
    turn = conversation_service.open(
        project.id,
        user,
        environment,
        request.headers.get(CALLER_SESSION_HEADER) or None,
        body.words,
    )
    opened = conversation_read_service.owned(turn.session_id, user, environment)
    return _conversation(opened).model_dump(mode="json"), 201


@conversations_bp.route("", methods=["GET"])
@api.validate(
    query=ConversationListQuerySchema,
    resp=SpectreeResponse(
        HTTP_200=ConversationListSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def list_conversations(
    conversation_read_service: ConversationReadService = Provide[
        ServiceContainer.conversation_read_service
    ],
    people_service: PeopleService = Provide[ServiceContainer.people_service],
    project_service: ProjectService = Provide[ServiceContainer.project_service],
) -> Any:
    """List the conversations the service user opened from the calling
    environment, open and closed, whatever session there opened each; with
    `address`, those about that project alone. No other environment's is
    listed, and a request that names no environment lists none.

    Returns:
        200: The conversations, in the order they opened
        400: The address is empty
        401: No one is signed in
        403: The caller lacks the editor role
        404: No project is at the address
        409: The caller is no service user
    """
    query = ConversationListQuerySchema.model_validate(request.args.to_dict())
    user = people_service.require_service_user(
        caller(), "list the conversations with Pilot"
    )
    project_id = (
        None if query.address is None else project_service.at_address(query.address).id
    )
    return ConversationListSchema(
        conversations=[
            _conversation(listed)
            for listed in conversation_read_service.opened(
                user, _calling_environment(), project_id
            )
        ]
    ).model_dump(mode="json")


@conversations_bp.route("/<uuid:conversation_id>", methods=["GET"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=ConversationSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    )
)
@inject
def get_conversation(
    conversation_id: uuid.UUID,
    conversation_read_service: ConversationReadService = Provide[
        ServiceContainer.conversation_read_service
    ],
    people_service: PeopleService = Provide[ServiceContainer.people_service],
) -> Any:
    """Read where a conversation stands: its project, the environment and the
    session that opened it, open or closed with its cause, its turns and
    whether one is in flight.

    Returns:
        200: The conversation
        401: No one is signed in
        403: The caller lacks the editor role
        404: No conversation has the id, or another caller opened it
        409: The caller is no service user
    """
    user = people_service.require_service_user(
        caller(), f"read the conversation {conversation_id} with Pilot"
    )
    return _conversation(
        conversation_read_service.owned(conversation_id, user, _calling_environment())
    ).model_dump(mode="json")


@conversations_bp.route("/<uuid:conversation_id>/messages", methods=["POST"])
@api.validate(
    json=ConversationMessageRequestSchema,
    resp=SpectreeResponse(
        HTTP_201=ConversationTurnSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def send_conversation_message(
    conversation_id: uuid.UUID,
    conversation_service: ConversationService = Provide[
        ServiceContainer.conversation_service
    ],
    conversation_read_service: ConversationReadService = Provide[
        ServiceContainer.conversation_read_service
    ],
    people_service: PeopleService = Provide[ServiceContainer.people_service],
) -> Any:
    """Send Pilot the calling session's next message in its conversation, as
    the service user, the words verbatim: a turn of it, its send made now, or
    the conversation started afresh with it where its start failed or was
    stopped unsent. One message is in flight at a time, and nothing is
    queued.

    A send the controller fails is the turn's `error` (F125).

    Returns:
        201: The message's turn in the conversation
        400: The message has no words
        401: No one is signed in
        403: The caller lacks the editor role
        404: No conversation has the id, or another caller opened it
        409: The caller is no service user; the conversation is closed, or
            its project archived; Pilot is updating its store; a turn of it
            is in flight, its start held or under way included; or no
            controller or store environment is configured
    """
    words = ConversationMessageRequestSchema.model_validate(request.get_json()).words
    user = people_service.require_service_user(
        caller(), f"send a message to Pilot in the conversation {conversation_id}"
    )
    conversation_read_service.owned(conversation_id, user, _calling_environment())
    turn = conversation_service.send(conversation_id, user, words)
    return ConversationTurnSchema(
        conversation=turn.session_id, seq=turn.seq, error=turn.error
    ).model_dump(mode="json"), 201


@conversations_bp.route("/<uuid:conversation_id>/interrupt", methods=["POST"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=ConversationSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    )
)
@inject
def interrupt_conversation(
    conversation_id: uuid.UUID,
    conversation_service: ConversationService = Provide[
        ServiceContainer.conversation_service
    ],
    conversation_read_service: ConversationReadService = Provide[
        ServiceContainer.conversation_read_service
    ],
    people_service: PeopleService = Provide[ServiceContainer.people_service],
) -> Any:
    """Stop the conversation's turn in flight where it is, as the service
    user, and keep the conversation for the next message: a running turn is
    interrupted once the request commits, and a start held or under way ends
    with nothing of it sent. With no turn in flight it changes nothing.

    Returns:
        200: The conversation, a stopped turn in flight until it has ended
        401: No one is signed in
        403: The caller lacks the editor role
        404: No conversation has the id, or another caller opened it
        409: The caller is no service user
    """
    user = people_service.require_service_user(
        caller(), f"interrupt the conversation {conversation_id} with Pilot"
    )
    environment = _calling_environment()
    conversation_read_service.owned(conversation_id, user, environment)
    conversation_service.interrupt(conversation_id, user)
    return _conversation(
        conversation_read_service.owned(conversation_id, user, environment)
    ).model_dump(mode="json")


@conversations_bp.route("/<uuid:conversation_id>/end", methods=["POST"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=ConversationSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    )
)
@inject
def end_conversation(
    conversation_id: uuid.UUID,
    conversation_service: ConversationService = Provide[
        ServiceContainer.conversation_service
    ],
    conversation_read_service: ConversationReadService = Provide[
        ServiceContainer.conversation_read_service
    ],
    people_service: PeopleService = Provide[ServiceContainer.people_service],
) -> Any:
    """Close the conversation, `ended`, as the service user, a turn of it in
    flight stopped first. One closed already stays as it closed.

    Returns:
        200: The conversation, closed
        401: No one is signed in
        403: The caller lacks the editor role
        404: No conversation has the id, or another caller opened it
        409: The caller is no service user
    """
    user = people_service.require_service_user(
        caller(), f"end the conversation {conversation_id} with Pilot"
    )
    environment = _calling_environment()
    conversation_read_service.owned(conversation_id, user, environment)
    conversation_service.end(conversation_id, user)
    return _conversation(
        conversation_read_service.owned(conversation_id, user, environment)
    ).model_dump(mode="json")
