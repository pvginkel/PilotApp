"""`pilot-store`'s routes (TD §4.5, F86): the REST calls Pilot's MCP server
makes for the brain's tools, under the session's bearer.

Registered on the app beside `pilot-work`'s, outside `/api/` and the OIDC gate,
so that only the pod's loopback reaches them (D048). Every call passes the
gate below first, and carries the tool call's id in the `Tool-Use-Id` header
where Claude Code gave one, which its effect's record names.
"""

from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, g, request
from spectree import Response as SpectreeResponse

from app.schemas.common import ApiErrorResponseSchema
from app.schemas.pilot_store import (
    AnswerRequestSchema,
    MarkRequestSchema,
    RecordedSchema,
    StopRequestSchema,
    WriterQuestionRequestSchema,
    WriterQuestionsSchema,
)
from app.services.container import ServiceContainer
from app.services.effect_service import TOOL_USE_ID_HEADER, EffectLine
from app.services.pilot_store_service import PilotStoreService
from app.utils.auth import public
from app.utils.spectree_config import api

pilot_store_bp = Blueprint("pilot_store", __name__, url_prefix="/tools/pilot-store")


@pilot_store_bp.before_request
@inject
def admit_the_session(
    pilot_store_service: PilotStoreService = Provide[
        ServiceContainer.pilot_store_service
    ],
) -> None:
    """The gate every call passes: 401 or 403 before anything is read or
    written."""
    g.brain = pilot_store_service.admit(request.headers.get("Authorization"))


@pilot_store_bp.route("/answers", methods=["POST"])
@public
@api.validate(
    json=AnswerRequestSchema,
    resp=SpectreeResponse(
        HTTP_200=RecordedSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def answer(
    pilot_store_service: PilotStoreService = Provide[
        ServiceContainer.pilot_store_service
    ],
) -> Any:
    """`answer(block, value, for, note?, to?)` (F86.2, F42.1): a person's
    answer to a block, given in the chat, recorded on their behalf through
    the chat.

    Returns:
        200: The call's effect line
        400: The body is not a block's id, an answer, a handle, and an
            optional note and task
        401: No bearer, or one no session has
        403: The bearer's session is not a chat's or a job's, or has no turn
            running
        404: The block is not of the session's project, or no person has the
            handle
        409: The record refuses the answer: the reason
    """
    body = AnswerRequestSchema.model_validate(request.get_json())
    line = pilot_store_service.answer(
        g.brain,
        body.block,
        body.value,
        body.for_,
        note=body.note,
        to=body.to,
        tool_use_id=request.headers.get(TOOL_USE_ID_HEADER),
    )
    return _recorded(line), 200


@pilot_store_bp.route("/marks", methods=["POST"])
@public
@api.validate(
    json=MarkRequestSchema,
    resp=SpectreeResponse(
        HTTP_200=RecordedSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def mark(
    pilot_store_service: PilotStoreService = Provide[
        ServiceContainer.pilot_store_service
    ],
) -> Any:
    """`mark(item, done | read | reviewed, for?)` (F86.3): Done, Read or
    Reviewed on an item for the person `for` names, else Pilot's own Done.

    Returns:
        200: The call's effect line
        400: The body is not an item's id, a mark and an optional handle
        401: No bearer, or one no session has
        403: The bearer's session is not a chat's or a job's, or has no turn
            running
        404: The item is not of the session's project, or no person has the
            handle
        409: Read or Reviewed without a person, or the record refuses the
            mark: the reason
    """
    body = MarkRequestSchema.model_validate(request.get_json())
    line = pilot_store_service.mark(
        g.brain,
        body.item,
        body.mark,
        body.for_,
        request.headers.get(TOOL_USE_ID_HEADER),
    )
    return _recorded(line), 200


@pilot_store_bp.route("/stops", methods=["POST"])
@public
@api.validate(
    json=StopRequestSchema,
    resp=SpectreeResponse(
        HTTP_200=RecordedSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def stop_work(
    pilot_store_service: PilotStoreService = Provide[
        ServiceContainer.pilot_store_service
    ],
) -> Any:
    """`stop_work(item)` (F86.4): a work item's session stopped by Pilot.

    Returns:
        200: The call's effect line
        400: The body is not an item's id
        401: No bearer, or one no session has
        403: The bearer's session is not a chat's or a job's, or has no turn
            running
        404: The item is not of the session's project
        409: It is no work item, or its session is neither running, starting
            nor held: the reason
    """
    body = StopRequestSchema.model_validate(request.get_json())
    line = pilot_store_service.stop_work(
        g.brain, body.item, request.headers.get(TOOL_USE_ID_HEADER)
    )
    return _recorded(line), 200


@pilot_store_bp.route("/finish", methods=["POST"])
@public
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=RecordedSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def finish(
    pilot_store_service: PilotStoreService = Provide[
        ServiceContainer.pilot_store_service
    ],
) -> Any:
    """`finish()` (F86.5, F5.4): the session's project finished by Pilot as
    Finish finishes it, its own turn stopped with every other once this
    commits.

    Returns:
        200: The call's effect line
        401: No bearer, or one no session has
        403: The bearer's session is not a chat's or a job's, or has no turn
            running
        409: The project is a draft, finished or archived: the reason
    """
    line = pilot_store_service.finish(g.brain, request.headers.get(TOOL_USE_ID_HEADER))
    return _recorded(line), 200


@pilot_store_bp.route("/writer-questions", methods=["POST"])
@public
@api.validate(
    json=WriterQuestionRequestSchema,
    resp=SpectreeResponse(
        HTTP_201=WriterQuestionsSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def ask_writer(
    pilot_store_service: PilotStoreService = Provide[
        ServiceContainer.pilot_store_service
    ],
) -> Any:
    """`ask_writer(document, block, question)` (F86.8, D059): the pre-ruling
    pass's question to a registered document's writer about one of its
    blocks, recorded with the pass's turn.

    Returns:
        201: The document's blocks its writer is asked about
        400: The body is not a document's id, a block's id and a question
        401: No bearer, or one no session has
        403: The bearer's session is not a job's, or has no turn running
        404: The document is not of the session's project, or has no such
            block
        409: The question is blank, the item is no registered document or is
            done, or the block is not of it, is answered or was asked about
            already: the reason
    """
    body = WriterQuestionRequestSchema.model_validate(request.get_json())
    blocks = pilot_store_service.ask_writer(
        g.brain, body.document, body.block, body.question
    )
    return WriterQuestionsSchema(blocks=blocks).model_dump(mode="json"), 201


def _recorded(line: EffectLine) -> dict[str, Any]:
    return RecordedSchema(effect=f"{line.verb} · {line.label}").model_dump(mode="json")
