"""What the signed-in person does to a timeline's items (F14, F17, F32.4):
answer a block, mark an action Done, mark a document Done, a notice Read, a
review Reviewed, and undo. Each is the record's own write; its refusals
answer as the API's errors. A block is addressed under its item, by its
local id (F30.7)."""

import uuid

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from spectree import Response as SpectreeResponse

from app.api.caller import caller
from app.schemas.common import ApiErrorResponseSchema
from app.schemas.items import ActionDoneRequestSchema, AnswerRequestSchema
from app.services.container import ServiceContainer
from app.services.item_service import ItemService
from app.utils.spectree_config import api

items_bp = Blueprint("items", __name__, url_prefix="/items")


@items_bp.route("/<uuid:item_id>/blocks/<block_id>/answer", methods=["POST"])
@api.validate(
    json=AnswerRequestSchema,
    resp=SpectreeResponse(
        HTTP_204=None,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def answer_block(
    item_id: uuid.UUID,
    block_id: str,
    item_service: ItemService = Provide[ServiceContainer.item_service],
) -> tuple[str, int]:
    """Answer a block as the signed-in person, now, through the app.

    A one-ask item is done by its answer.

    Returns:
        204: The answer is recorded
        400: The body is not an answer
        401: No one is signed in
        403: The caller lacks the editor role
        404: No item has the id, or it has no block of the id
        409: The caller has not chosen a handle, the item is done, or the
            block takes no such answer
    """
    body = AnswerRequestSchema.model_validate(request.get_json())
    item_service.answer(caller(), item_id, block_id, body.answer, body.note)
    return "", 204


@items_bp.route("/<uuid:item_id>/blocks/<block_id>/done", methods=["POST"])
@api.validate(
    json=ActionDoneRequestSchema,
    resp=SpectreeResponse(
        HTTP_204=None,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def mark_action_done(
    item_id: uuid.UUID,
    block_id: str,
    item_service: ItemService = Provide[ServiceContainer.item_service],
) -> tuple[str, int]:
    """Mark an action without options Done as the signed-in person, now,
    with the paste-back as its note.

    A one-ask item is done by its action's Done.

    Returns:
        204: The Done is recorded
        400: The body is not a Done
        401: No one is signed in
        403: The caller lacks the editor role
        404: No item has the id, or it has no block of the id
        409: The caller has not chosen a handle, the item is done, or the
            block is no action without options
    """
    body = ActionDoneRequestSchema.model_validate(request.get_json())
    item_service.done_action(caller(), item_id, block_id, body.note)
    return "", 204


_MARK_RESPONSES = SpectreeResponse(
    HTTP_204=None,
    HTTP_401=ApiErrorResponseSchema,
    HTTP_403=ApiErrorResponseSchema,
    HTTP_404=ApiErrorResponseSchema,
    HTTP_409=ApiErrorResponseSchema,
)


@items_bp.route("/<uuid:item_id>/done", methods=["POST"])
@api.validate(resp=_MARK_RESPONSES)
@inject
def mark_document_done(
    item_id: uuid.UUID,
    item_service: ItemService = Provide[ServiceContainer.item_service],
) -> tuple[str, int]:
    """Mark a document Done as the signed-in person, now: every unanswered
    block that has a recommendation answered with it first, `via:
    recommended`.

    Returns:
        204: The document is done
        401: No one is signed in
        403: The caller lacks the editor role
        404: No item has the id
        409: The caller has not chosen a handle, the item is done or no
            document, or a block has neither an answer nor a recommendation
    """
    item_service.done(caller(), item_id)
    return "", 204


@items_bp.route("/<uuid:item_id>/read", methods=["POST"])
@api.validate(resp=_MARK_RESPONSES)
@inject
def mark_read(
    item_id: uuid.UUID,
    item_service: ItemService = Provide[ServiceContainer.item_service],
) -> tuple[str, int]:
    """Mark a notice Read as the signed-in person, now.

    Returns:
        204: The notice is done
        401: No one is signed in
        403: The caller lacks the editor role
        404: No item has the id
        409: The caller has not chosen a handle, or the item is done or no
            notice
    """
    item_service.read(caller(), item_id)
    return "", 204


@items_bp.route("/<uuid:item_id>/reviewed", methods=["POST"])
@api.validate(resp=_MARK_RESPONSES)
@inject
def mark_reviewed(
    item_id: uuid.UUID,
    item_service: ItemService = Provide[ServiceContainer.item_service],
) -> tuple[str, int]:
    """Mark a review Reviewed as the signed-in person, now.

    Returns:
        204: The review is done
        401: No one is signed in
        403: The caller lacks the editor role
        404: No item has the id
        409: The caller has not chosen a handle, or the item is done or no
            review
    """
    item_service.reviewed(caller(), item_id)
    return "", 204


@items_bp.route("/<uuid:item_id>/undo", methods=["POST"])
@api.validate(resp=_MARK_RESPONSES)
@inject
def undo(
    item_id: uuid.UUID,
    item_service: ItemService = Provide[ServiceContainer.item_service],
) -> tuple[str, int]:
    """Undo a done item's answer or mark, whoever gave it, while no session
    has taken it: the item open again, and a one-ask item's block unanswered.

    Returns:
        204: The item is open
        401: No one is signed in
        403: The caller lacks the editor role
        404: No item has the id
        409: The item is not done, a session has taken its answers, it was
            done in a way that offers no undo, or it is no prose item
    """
    item_service.undo(item_id)
    return "", 204
