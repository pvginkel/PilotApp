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
    AlertRequestSchema,
    AnswerRequestSchema,
    AttachedSchema,
    AttachRequestSchema,
    CancelAskRequestSchema,
    FinishRequestSchema,
    MarkRequestSchema,
    NotableRequestSchema,
    NotableSchema,
    NoteRequestSchema,
    RecordedSchema,
    StandingSchema,
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
    file, a work item started on add, named for the claimed actions it does
    (F21.6) and for the blocks it researches (F52.3), or a wait, fixed from
    then on (F27.6), with the attachments it carries.

    Returns:
        201: The item, a prose item's file, a work item's state as the gate
            left it, and the call's effect line
        400: The body is not an item in `timeline.json`'s shape
        401: No bearer, or one no session has
        403: The bearer's session is not a chat's or a job's, or has no turn
            running
        404: An attachment, the plan's task, a claimed or researched block's
            item, a source's environment or the one a work item is placed in
            is not the session's project's or the controller's, or that
            block's document has no such block
        409: A field the kind does not take or one it needs missing, a work
            item that names both a repository and an environment, neither, or
            the store's environment, a text
            with faults, a wait's list empty or naming one twice, a card that
            is no ticket id, a due time not ahead, material that cannot be
            copied, a claim that is not an open action of a registered
            document or of an item of Pilot's own, a research of a block that
            is answered or not in an open registered document, or a start the
            project refuses: the reason
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
    """`mark(item, done | read | reviewed, for?, note?)` (F86.3): Done, Read
    or Reviewed on an item for the person `for` names, else Pilot's own Done,
    a wait's with its `note` (F27.4).

    Returns:
        200: The call's effect line
        400: The body is not an item's id, a mark, an optional handle and an
            optional note
        401: No bearer, or one no session has
        403: The bearer's session is not a chat's or a job's, or has no turn
            running
        404: The item is not of the session's project, or no person has the
            handle
        409: Read or Reviewed without a person, a wait's mark with a person or
            without a note, a note on any other item, or the record refuses
            the mark: the reason
    """
    body = MarkRequestSchema.model_validate(request.get_json())
    line = pilot_store_service.mark(
        g.brain,
        body.item,
        body.mark,
        body.for_,
        request.headers.get(TOOL_USE_ID_HEADER),
        note=body.note,
    )
    return _recorded(line), 200


@pilot_store_bp.route("/cancellations", methods=["POST"])
@public
@api.validate(
    json=CancelAskRequestSchema,
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
def cancel_ask(
    pilot_store_service: PilotStoreService = Provide[
        ServiceContainer.pilot_store_service
    ],
) -> Any:
    """`cancel_ask(item, for)` (DB 297): an ask Pilot added, a decision, a
    confirmation, a question, an action or a document of its own, called off
    on the word of the person `for` names, given in the chat: done
    `cancelled`, by them, with no Undo and no job after it.

    Returns:
        200: The call's effect line
        400: The body is not an item's id and a handle
        401: No bearer, or one no session has
        403: The bearer's session is not a chat's or a job's, or has no turn
            running
        404: The item is not of the session's project, or no person has the
            handle
        409: The item is a document a work item's run registered, a notice,
            a work item, a wait or no ask Pilot added, it is done, or the
            project is archived: the reason
    """
    body = CancelAskRequestSchema.model_validate(request.get_json())
    line = pilot_store_service.cancel_ask(
        g.brain, body.item, body.for_, request.headers.get(TOOL_USE_ID_HEADER)
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
    """`stop_work(item, reason)` (F86.4; DB 345): a work item's session
    stopped by Pilot; with `reason`, the work item closed for good in the
    same act, done `cancelled` by Pilot, the reason on its done line, one
    stopped already included.

    Returns:
        200: The call's effect line
        400: The body is not an item's id, with or without a reason that is
            not empty
        401: No bearer, or one no session has
        403: The bearer's session is not a chat's or a job's, or has no turn
            running
        404: The item is not of the session's project
        409: It is no work item, it is a job of Pilot's own, or its session
            is neither running, starting, held nor idle with its nudge owed;
            with `reason`, it is done, its project is archived, or its
            session is none of those nor stopped: the reason
    """
    body = StopRequestSchema.model_validate(request.get_json())
    line = pilot_store_service.stop_work(
        g.brain,
        body.item,
        request.headers.get(TOOL_USE_ID_HEADER),
        reason=body.reason,
    )
    return _recorded(line), 200


@pilot_store_bp.route("/finish", methods=["POST"])
@public
@api.validate(
    json=FinishRequestSchema,
    resp=SpectreeResponse(
        HTTP_200=RecordedSchema,
        HTTP_400=ApiErrorResponseSchema,
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
    """`finish(archive)` (F86.5, F5.4): the session's project finished by
    Pilot as Finish finishes it, its own turn stopped with every other once
    this commits. With `archive` it is archived in the same act, the archive
    the person's whose word the call carries out, and no archive question is
    placed.

    Returns:
        200: The call's effect line
        400: The body is not the request's
        401: No bearer, or one no session has
        403: The bearer's session is not a chat's or a job's, or has no turn
            running
        409: The project is a draft, finished or archived: the reason
    """
    body = FinishRequestSchema.model_validate(request.get_json())
    line = pilot_store_service.finish(
        g.brain, request.headers.get(TOOL_USE_ID_HEADER), archive=body.archive
    )
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
    """`ask_writer(block, question)` (F86.8, D059): the pre-ruling pass's
    question to a registered document's writer about one of its blocks, the
    block's id naming its document, recorded with the pass's turn.

    Returns:
        201: The document's blocks its writer is asked about
        400: The body is not a block's id and a question
        401: No bearer, or one no session has
        403: The bearer's session is not a job's, or has no turn running
        404: The block's item is not of the session's project, or its
            document has no such block
        409: The question is blank, the item is no registered document or is
            done, the block is answered or was asked about already, or the
            pass asks nothing, one round per worker turn: the reason
    """
    body = WriterQuestionRequestSchema.model_validate(request.get_json())
    blocks = pilot_store_service.ask_writer(g.brain, body.block, body.question)
    return WriterQuestionsSchema(blocks=blocks).model_dump(mode="json"), 201


@pilot_store_bp.route("/notable", methods=["POST"])
@public
@api.validate(
    json=NotableRequestSchema,
    resp=SpectreeResponse(
        HTTP_200=NotableSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def write_notable(
    pilot_store_service: PilotStoreService = Provide[
        ServiceContainer.pilot_store_service
    ],
) -> Any:
    """`write_notable(text)` (F52.4, F26.13; DB 636): Pilot's lines on the
    debrief of the work item whose turn the session's job follows, a later
    call replacing them; no effect.

    Returns:
        200: What the call did to the lines standing on the debrief
        400: The body is not lines of 1 to 16,000 characters: each fault
        401: No bearer, or one no session has
        403: The bearer's session is not a job's, or has no turn running
        409: The job follows no work item's turn, or the work item gave no
            debrief, nothing changed: the reason
    """
    body = NotableRequestSchema.model_validate(request.get_json())
    outcome = pilot_store_service.write_notable(g.brain, body.text)
    return NotableSchema(outcome=outcome).model_dump(mode="json"), 200


@pilot_store_bp.route("/notes", methods=["POST"])
@public
@api.validate(
    json=NoteRequestSchema,
    resp=SpectreeResponse(
        HTTP_200=StandingSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def note(
    pilot_store_service: PilotStoreService = Provide[
        ServiceContainer.pilot_store_service
    ],
) -> Any:
    """`note(item, block?, text?, suggested_answer?, suggested_note?, offer?)`
    (F86.10, F168): Pilot's note on a block of an open prose item, or on the
    item as a whole, recorded with the session's turn; a later one in the
    same place replaces the one standing, and a call that gives none of the
    four takes it off.

    Returns:
        200: What the call did to the note standing in its place
        400: The body is not an item, a block's id and the note's fields
        401: No bearer, or one no session has
        403: The bearer's session is not a chat's or a job's, or has no turn
            running
        404: The item is not of the session's project, or its document has
            no such block
        409: The item has no block or is done, the block is of another item,
            is answered by Pilot or held by another run, a suggested answer
            on an action with no options, an offer on anything but an open
            action, anything but `text` on the item as a whole, or a
            withdrawal where no note stands: the reason
    """
    body = NoteRequestSchema.model_validate(request.get_json())
    outcome = pilot_store_service.note(
        g.brain,
        body.item,
        body.block,
        text=body.text,
        suggested_answer=body.suggested_answer,
        suggested_note=body.suggested_note,
        offer=body.offer,
    )
    return StandingSchema(outcome=outcome).model_dump(mode="json"), 200


@pilot_store_bp.route("/alerts", methods=["POST"])
@public
@api.validate(
    json=AlertRequestSchema,
    resp=SpectreeResponse(
        HTTP_200=StandingSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_401=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def alert(
    pilot_store_service: PilotStoreService = Provide[
        ServiceContainer.pilot_store_service
    ],
) -> Any:
    """`alert(item, text?, awaits?)` (F86.11, F168.6): Pilot's alert on an
    open prose item that another open ask, the block it awaits, comes before
    its Send, recorded with the session's turn; a later one replaces the one
    standing, and a call that gives neither takes it off.

    Returns:
        200: What the call did to the alert standing on the item
        400: The body is not an item, a text and a block's id
        401: No bearer, or one no session has
        403: The bearer's session is not a chat's or a job's, or has no turn
            running
        404: The item or the awaited block's item is not of the session's
            project, or that block's document has no such block
        409: One of `text` and `awaits` without the other, the item is no
            prose item or is done, the awaited block is of the item itself
            or of an item that is done, or a withdrawal where no alert
            stands: the reason
    """
    body = AlertRequestSchema.model_validate(request.get_json())
    outcome = pilot_store_service.alert(
        g.brain, body.item, text=body.text, awaits=body.awaits
    )
    return StandingSchema(outcome=outcome).model_dump(mode="json"), 200


def _recorded(line: EffectLine) -> dict[str, Any]:
    return RecordedSchema(effect=_effect(line)).model_dump(mode="json")


def _effect(line: EffectLine) -> str:
    return f"{line.verb} · {line.label}"
