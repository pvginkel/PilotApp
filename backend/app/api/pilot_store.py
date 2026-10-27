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
    AddedSchema,
    AddItemRequestSchema,
    AnswerRequestSchema,
    AttachedSchema,
    AttachRequestSchema,
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


@pilot_store_bp.route("/items", methods=["POST"])
@public
@api.validate(
    json=AddItemRequestSchema,
    resp=SpectreeResponse(
        HTTP_201=AddedSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
        HTTP_502=ApiErrorResponseSchema,
    ),
)
@inject
def add_item(
    pilot_store_service: PilotStoreService = Provide[
        ServiceContainer.pilot_store_service
    ],
) -> Any:
    """`add_item(item)` (F86.1, F86.6, F36.5): a prose item minted with its
    file, or a work item started on add, with the attachments it carries.

    Returns:
        201: The item, a prose item's file, a work item's state as the gate
            left it, and the call's effect line
        400: The body is not an item in `timeline.json`'s shape
        401: No bearer, or one no session has
        403: The bearer's session is not a chat's or a job's, or has no turn
            running
        404: An attachment, the plan's task or a source's environment is not
            the session's project's or the controller's
        409: A wait, a field the kind does not take or one it needs missing,
            a text with faults, material that cannot be copied, or a start
            the project refuses: the reason
        502: The controller did not answer, or refused for a reason of its own
    """
    body = AddItemRequestSchema.model_validate(request.get_json())
    added = pilot_store_service.add_item(
        g.brain, body, request.headers.get(TOOL_USE_ID_HEADER)
    )
    answer = AddedSchema(
        id=added.item.id,
        path=added.path,
        state=added.state,
        held=None if added.held is None else added.held.reason,
        effect=_effect(added.line),
    )
    return answer.model_dump(mode="json"), 201


@pilot_store_bp.route("/attachments", methods=["POST"])
@public
@api.validate(
    json=AttachRequestSchema,
    resp=SpectreeResponse(
        HTTP_201=AttachedSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
        HTTP_502=ApiErrorResponseSchema,
    ),
)
@inject
def attach_file(
    pilot_store_service: PilotStoreService = Provide[
        ServiceContainer.pilot_store_service
    ],
) -> Any:
    """`attach_file(source, to?)` (F86.7, F36.6): outside material, a file or
    a folder in any environment, copied into the record now with its source
    and hung on the item `to` names, or, with no `to` in a draft's definition
    chat, on nothing.

    Returns:
        201: The attachments, one per file, and the call's effect line
        400: The body is not a source and an optional item id
        401: No bearer, or one no session has
        403: The bearer's session is not a chat's or a job's, or has no turn
            running
        404: `to` names no item of the session's project, or the source's
            environment is not the controller's
        409: No `to` outside a draft's definition chat, or a file cannot be
            copied, nothing attached: the reason
        502: The controller did not answer, or refused for a reason of its own
    """
    body = AttachRequestSchema.model_validate(request.get_json())
    attached = pilot_store_service.attach_file(
        g.brain, body.source, body.to, request.headers.get(TOOL_USE_ID_HEADER)
    )
    answer = AttachedSchema(
        ids=[attachment.id for attachment in attached.attachments],
        effect=_effect(attached.line),
    )
    return answer.model_dump(mode="json"), 201


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
    the chat: a block of the draft, `project.md/<local id>`, in its
    definition chat alone (F47.4).

    Returns:
        200: The call's effect line
        400: The body is not a block's id, an answer, a handle, and an
            optional note and task
        401: No bearer, or one no session has
        403: The bearer's session is not a chat's or a job's, or has no turn
            running
        404: The block is not of the session's project, or no person has the
            handle
        409: A block of the draft outside its definition chat, or the record
            refuses the answer: the reason
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
    return RecordedSchema(effect=_effect(line)).model_dump(mode="json")


def _effect(line: EffectLine) -> str:
    return f"{line.verb} · {line.label}"
