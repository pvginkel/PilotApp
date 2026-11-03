"""Testing endpoints that make the record's states the UI cannot make
(TEST-6): people who never signed in, environments, projects in every
standing, with members, a plan, their opening and open items, the items a
project's session adds, an agent's saves of them and of the project's draft
and handbook, the files it attaches, a draft's on no item, Pilot's Done, and
the end of its turn; and a work item placed by repository, started in an
environment of Pilot's own the stage's own controller creates, named for the
claimed actions it does, and the
documents and the material its session registers and attaches there, each with
its effect, and the list of steps it publishes; a pre-ruling pass's questions to a registered document's writer,
and its clarification run, with the writer's reply or to run; a person's
answer the brain records through the project's open chat, with
its effect; the store's update, made or its lift asked, as `update-store`
does (F144.5); and the brain's waits, a card's transition delivered as the
tracker-events endpoint takes it, past its token, which the dev stage has
none of (R8), the waits' timer's tick, a wait's run placed as the batcher
places it, and its close by Pilot's `mark`.
Nothing in the UI places a work item, which the brain adds (F66).

They answer on every STAGE but prd, whatever FLASK_ENV says, so that the dev
stage's deployed check makes its record through them (D027). They sit on
the API blueprint, behind its sign-in and the `editor` role.
"""

import uuid
from typing import Any

from dependency_injector.wiring import Provide, inject
from flask import Blueprint, request
from spectree import Response as SpectreeResponse

from app.config import Settings
from app.engine.ingest import Ingested
from app.engine.paths import folder
from app.exceptions import RouteNotAvailableException
from app.models.reference import DocumentRole
from app.schemas.common import ApiErrorResponseSchema
from app.schemas.pilot_store import RecordedSchema
from app.schemas.pilot_work import (
    ProgressSchema,
    ProgressStepSchema,
    SetProgressRequestSchema,
)
from app.schemas.testing_record import (
    InventedAttachmentsCreateSchema,
    InventedAttachmentsSchema,
    InventedChatAnswerCreateSchema,
    InventedClarificationCreateSchema,
    InventedClarificationSchema,
    InventedEnvironmentSchema,
    InventedFaultSchema,
    InventedFiredSchema,
    InventedItemCreateSchema,
    InventedItemSchema,
    InventedPersonCreateSchema,
    InventedPersonSchema,
    InventedProjectCreateSchema,
    InventedProjectSchema,
    InventedRegistrationCreateSchema,
    InventedSaveCreateSchema,
    InventedSaveSchema,
    InventedStoreUpdateCreateSchema,
    InventedStoreUpdateSchema,
    InventedWaitCloseSchema,
    InventedWaitCreateSchema,
    InventedWorkCreateSchema,
    InventedWorkerAttachmentCreateSchema,
    InventedWorkerAttachmentsSchema,
    InventedWriterQuestionsCreateSchema,
    InventedWriterQuestionsSchema,
)
from app.schemas.tracker_events import TrackerEventReplySchema
from app.services.container import ServiceContainer
from app.services.store_update_service import StoreUpdateService
from app.services.test_data_service import TestDataService
from app.services.tracker_event_service import TrackerEventService
from app.services.wait_service import WaitService
from app.utils.flask_error_handlers import build_error_response
from app.utils.spectree_config import api

testing_record_bp = Blueprint("testing_record", __name__, url_prefix="/testing")


@testing_record_bp.before_request
@inject
def refuse_on_prd(config: Settings = Provide[ServiceContainer.config]) -> Any:
    """Refuse every request on prd; an unset STAGE outside testing and
    development resolves to prd (`default_stage`)."""
    if config.stage != "prd":
        return None
    exception = RouteNotAvailableException(
        "The record's testing endpoints are not available on prd"
    )
    return build_error_response(
        exception.message,
        {"message": "The record's testing endpoints require a STAGE other than prd"},
        code=exception.error_code,
        status_code=400,
    )


@testing_record_bp.route("/people", methods=["POST"])
@api.validate(
    json=InventedPersonCreateSchema,
    resp=SpectreeResponse(
        HTTP_201=InventedPersonSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def create_person(
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> Any:
    """Put a person on the record as the handle step does, under a subject
    no one signs in with.

    Returns:
        201: The person, with the avatar slot they took
        400: The handle is not lower-case letters, digits and hyphens
        409: The handle is Pilot's or another person's
    """
    data = InventedPersonCreateSchema.model_validate(request.get_json())
    person = test_data_service.person(data.handle, data.name)
    # A person's row has a slot (`ck_users_person`).
    assert person.avatar_slot is not None
    return InventedPersonSchema(
        handle=person.handle, name=person.name, avatar_slot=person.avatar_slot
    ).model_dump(), 201


@testing_record_bp.route("/environments", methods=["POST"])
@api.validate(
    json=InventedEnvironmentSchema,
    resp=SpectreeResponse(
        HTTP_201=InventedEnvironmentSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def create_environment(
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> Any:
    """Put an environment Pilot has touched on the record.

    Returns:
        201: The environment
        400: The id or the name is missing
        409: An environment has the id
    """
    data = InventedEnvironmentSchema.model_validate(request.get_json())
    environment = test_data_service.environment(data.id, data.name)
    return InventedEnvironmentSchema(
        id=environment.id, name=environment.name
    ).model_dump(), 201


@testing_record_bp.route("/projects", methods=["POST"])
@api.validate(
    json=InventedProjectCreateSchema,
    resp=SpectreeResponse(
        HTTP_201=InventedProjectSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def create_project(
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> Any:
    """Make a project in the standing given, made now by its first member.

    Returns:
        201: The project's id and its folder in the store's tree
        400: A finished project with auto pilot on, a member named twice,
            open items without an environment, or a plan with a fault
        404: A member is no person, or no environment has the id
        409: The name makes a draft text with a fault
    """
    data = InventedProjectCreateSchema.model_validate(request.get_json())
    project = test_data_service.project(data)
    response = InventedProjectSchema(id=project.id, folder=folder(project))
    return response.model_dump(mode="json"), 201


@testing_record_bp.route("/projects/<uuid:project_id>/items", methods=["POST"])
@api.validate(
    json=InventedItemCreateSchema,
    resp=SpectreeResponse(
        HTTP_201=InventedItemSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def create_item(
    project_id: uuid.UUID,
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> Any:
    """Add a prose item to the project's timeline, by the project's session,
    or by a job of Pilot's own, as Pilot adds one: its kind, urgency, person,
    step and blocks, Pilot's answers and deferrals among them, are what its
    text says.

    Returns:
        201: The item's id
        400: The kind is no prose kind Pilot adds, or the title is empty
        404: No project has the id
        409: The project has no session and the item is not Pilot's, or the
            text holds a fault
    """
    data = InventedItemCreateSchema.model_validate(request.get_json())
    item = test_data_service.item(
        project_id, data.kind, data.title, data.text, by_pilot=data.by_pilot
    )
    return InventedItemSchema(id=item.id).model_dump(mode="json"), 201


@testing_record_bp.route("/projects/<uuid:project_id>/work", methods=["POST"])
@api.validate(
    json=InventedWorkCreateSchema,
    resp=SpectreeResponse(
        HTTP_201=InventedItemSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def create_work(
    project_id: uuid.UUID,
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> Any:
    """Place a work item on the project's timeline by repository, and start
    its session as every work item's starts: once the request commits, its
    start creates an environment of Pilot's own from the repository on the
    stage's own controller. It is named for the claimed actions `claims`
    gives, as a pass's `add_item` names them (F21.6).

    Returns:
        201: The work item's id, its Work's and its Session's
        400: The body is invalid, or the stage is prd
        404: No project has the id, its plan has no task of the step, a
            claim's item is not of the project, or its document has no such
            block
        409: A claim that is not an open action of a registered document of
            the project, no controller is configured, or the project is
            finished or archived: the reason
    """
    data = InventedWorkCreateSchema.model_validate(request.get_json())
    work = test_data_service.work(
        project_id,
        data.repo,
        title=data.title,
        brief=data.brief,
        cwd=data.cwd,
        step=data.step,
        claims=data.claims,
    )
    return InventedItemSchema(id=work.id).model_dump(mode="json"), 201


@testing_record_bp.route("/projects/<uuid:project_id>/turn-ends", methods=["POST"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_204=None,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def create_turn_end(
    project_id: uuid.UUID,
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> tuple[str, int]:
    """End the turn of the project's session as the relay does for its
    documents: Pilot's writing flag cleared on each it was saving, told to the
    browsers, and a `turn` Version cut of each whose text moved.

    Returns:
        204: The turn has ended
        400: The stage is prd
        404: No project has the id
        409: The project has no session
    """
    test_data_service.end_turn(project_id)
    return "", 204


@testing_record_bp.route("/items/<uuid:item_id>/saves", methods=["POST"])
@api.validate(
    json=InventedSaveCreateSchema,
    resp=SpectreeResponse(
        HTTP_200=InventedSaveSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def create_save(
    item_id: uuid.UUID,
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> Any:
    """Ingest an agent's save of the item's file, by the project's session, as
    the store's sync does: held on a fault, the item then shown as it was last
    published (F78), else merged and published.

    Returns:
        200: Whether the save is held, and its faults
        400: The text is missing
        404: No item has the id, or its project is archived
        409: The project has no session
    """
    data = InventedSaveCreateSchema.model_validate(request.get_json())
    return _saved(test_data_service.save(item_id, data.text)), 200


@testing_record_bp.route("/projects/<uuid:project_id>/draft/saves", methods=["POST"])
@api.validate(
    json=InventedSaveCreateSchema,
    resp=SpectreeResponse(
        HTTP_200=InventedSaveSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def create_draft_save(
    project_id: uuid.UUID,
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> Any:
    """Ingest an agent's save of the project's draft, `project.md`, by the
    project's session, as the store's sync does: held on a fault, else merged
    and published.

    Returns:
        200: Whether the save is held, and its faults
        400: The text is missing
        404: No project has the id, or it is archived
        409: The project has no session
    """
    data = InventedSaveCreateSchema.model_validate(request.get_json())
    return _saved(
        test_data_service.save_project_document(
            project_id, DocumentRole.DRAFT, data.text
        )
    ), 200


@testing_record_bp.route("/projects/<uuid:project_id>/handbook/saves", methods=["POST"])
@api.validate(
    json=InventedSaveCreateSchema,
    resp=SpectreeResponse(
        HTTP_200=InventedSaveSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def create_handbook_save(
    project_id: uuid.UUID,
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> Any:
    """Ingest an agent's save of the project's handbook, `handbook.md`, by
    the project's session, as the store's sync does: held on a fault, else
    merged and published.

    Returns:
        200: Whether the save is held, and its faults
        400: The text is missing
        404: No project has the id, it is a draft, which has no handbook, or
            it is archived
        409: The project has no session
    """
    data = InventedSaveCreateSchema.model_validate(request.get_json())
    return _saved(
        test_data_service.save_project_document(
            project_id, DocumentRole.HANDBOOK, data.text
        )
    ), 200


@testing_record_bp.route("/items/<uuid:item_id>/done", methods=["POST"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_204=None,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def create_done(
    item_id: uuid.UUID,
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> tuple[str, int]:
    """Mark a document Done as Pilot, by the project's session, as its `mark`
    does a document it settled or deferred whole: the text as it stands
    fixed in a `done` Version, the item done by Pilot.

    Returns:
        204: The document is done
        400: The stage is prd
        404: No item has the id
        409: The project has no session, the item is no document or is done,
            or a block of it is unanswered
    """
    test_data_service.mark_done(item_id)
    return "", 204


@testing_record_bp.route("/items/<uuid:item_id>/attachments", methods=["POST"])
@api.validate(
    json=InventedAttachmentsCreateSchema,
    resp=SpectreeResponse(
        HTTP_201=InventedAttachmentsSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def create_attachments(
    item_id: uuid.UUID,
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> Any:
    """Hang files on the item as the project's session attaches them in one
    call (F36.1, F37.1): copied from its environment, kept through the store,
    one batch, the project's next, after the item's attachments.

    Returns:
        201: The batch and the attachments' ids
        400: No file, a filename that is not one path segment or is named
            twice, or content that is not base64 or is over 16 MiB
        404: No item has the id
        409: The project has no session
    """
    data = InventedAttachmentsCreateSchema.model_validate(request.get_json())
    attachments = test_data_service.attach(item_id, data.files)
    return InventedAttachmentsSchema(
        batch=attachments[0].batch, ids=[attachment.id for attachment in attachments]
    ).model_dump(mode="json"), 201


@testing_record_bp.route("/projects/<uuid:project_id>/attachments", methods=["POST"])
@api.validate(
    json=InventedAttachmentsCreateSchema,
    resp=SpectreeResponse(
        HTTP_201=InventedAttachmentsSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def create_draft_attachments(
    project_id: uuid.UUID,
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> Any:
    """Copy files into a draft as its definition chat's `attach_file` copies
    them with no `to` (F36.6): copied from its session's environment, kept
    through the store, one batch, the project's next, hung on nothing.

    Returns:
        201: The batch and the attachments' ids
        400: No file, a filename that is not one path segment or is named
            twice, or content that is not base64 or is over 16 MiB
        404: No project has the id
        409: The project is no draft, or has no session
    """
    data = InventedAttachmentsCreateSchema.model_validate(request.get_json())
    attachments = test_data_service.attach_to_draft(project_id, data.files)
    return InventedAttachmentsSchema(
        batch=attachments[0].batch, ids=[attachment.id for attachment in attachments]
    ).model_dump(mode="json"), 201


@testing_record_bp.route("/items/<uuid:item_id>/registrations", methods=["POST"])
@api.validate(
    json=InventedRegistrationCreateSchema,
    resp=SpectreeResponse(
        HTTP_200=InventedItemSchema,
        HTTP_201=InventedItemSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
        HTTP_502=ApiErrorResponseSchema,
    ),
)
@inject
def create_registration(
    item_id: uuid.UUID,
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> Any:
    """Register the document the work item's session wrote at `path` in its
    environment, as its worker's `register_document` does (F85.1, ruling D1):
    the file read through the stage's controller and parsed now, its text
    read once the turn that ends its run commits, published or its read
    failed; a minted one the effect of the call `tool_use_id` names, while
    the session's turn is in flight (F41).

    Returns:
        200: The document its run registered from the path already
        201: The document, minted
        400: The body is invalid, or the stage is prd
        404: No work item has the id
        409: Its session has no environment yet, or the file cannot be
            registered, nothing minted: the reason
        502: The controller did not answer, or refused for a reason of its own
    """
    data = InventedRegistrationCreateSchema.model_validate(request.get_json())
    registration = test_data_service.register_document(
        item_id, data.path, data.tool_use_id
    )
    return InventedItemSchema(id=registration.item.id).model_dump(mode="json"), (
        201 if registration.minted else 200
    )


@testing_record_bp.route("/items/<uuid:item_id>/worker-attachments", methods=["POST"])
@api.validate(
    json=InventedWorkerAttachmentCreateSchema,
    resp=SpectreeResponse(
        HTTP_201=InventedWorkerAttachmentsSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
        HTTP_502=ApiErrorResponseSchema,
    ),
)
@inject
def create_worker_attachment(
    item_id: uuid.UUID,
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> Any:
    """Attach the file or the folder the work item's session wrote at `path`
    in its environment, as its worker's `attach_file` does (F85.2): copied
    through the stage's controller now, one batch, hung on the item `to`
    names, else on the work item; the effect of the call `tool_use_id` names,
    while the session's turn is in flight (F41).

    Returns:
        201: The attachments' ids, one per file
        400: The body is invalid, or the stage is prd
        404: No work item has the id, or `to` names no item of its project
        409: Its session has no environment yet, or a file cannot be copied,
            nothing attached: the reason
        502: The controller did not answer, or refused for a reason of its own
    """
    data = InventedWorkerAttachmentCreateSchema.model_validate(request.get_json())
    attachments = test_data_service.attach_as_worker(
        item_id, data.path, data.to, data.tool_use_id
    )
    return InventedWorkerAttachmentsSchema(
        ids=[attachment.id for attachment in attachments]
    ).model_dump(mode="json"), 201


@testing_record_bp.route("/items/<uuid:item_id>/progress", methods=["POST"])
@api.validate(
    json=SetProgressRequestSchema,
    resp=SpectreeResponse(
        HTTP_200=ProgressSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_403=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def create_progress(
    item_id: uuid.UUID,
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> Any:
    """Replace the work item's list of steps, as its worker's `set_progress`
    does (F85.3, F145.1): in the call's order, its status moved on every
    browser through the live event, while the session's turn is in flight.

    Returns:
        200: The list as it stands
        400: The body is not a list of at most 100 steps, each a code of 1 to
            64 characters, a label of 1 to 120 and an optional state, or the
            stage is prd
        403: Its session has no turn running
        404: No work item has the id
        409: Its session has no environment yet, or a code is repeated,
            nothing changed: the reason
    """
    data = SetProgressRequestSchema.model_validate(request.get_json())
    steps = test_data_service.set_progress(item_id, data.steps)
    return ProgressSchema(
        steps=[
            ProgressStepSchema(code=step.code, label=step.label, state=step.state_code)
            for step in steps
        ]
    ).model_dump(mode="json"), 200


@testing_record_bp.route("/items/<uuid:item_id>/writer-questions", methods=["POST"])
@api.validate(
    json=InventedWriterQuestionsCreateSchema,
    resp=SpectreeResponse(
        HTTP_201=InventedWriterQuestionsSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def create_writer_questions(
    item_id: uuid.UUID,
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> Any:
    """Ask the writer of the registered document about its blocks, by their
    local ids, as the pre-ruling pass's `ask_writer` asks (F86.8): in the one
    turn of a job's session of its project placed for the pass and ended
    once they are asked, nothing started; the document's line says so.

    Returns:
        201: The document's blocks its writer is asked about
        400: The body is invalid, or the stage is prd
        404: No item has the id, or its document has no such block
        409: The item is no registered document or is done, or a block is
            answered or was asked about already: the reason
    """
    data = InventedWriterQuestionsCreateSchema.model_validate(request.get_json())
    blocks = test_data_service.ask_writer(item_id, data.questions)
    return InventedWriterQuestionsSchema(blocks=blocks).model_dump(mode="json"), 201


@testing_record_bp.route("/items/<uuid:item_id>/clarification", methods=["POST"])
@api.validate(
    json=InventedClarificationCreateSchema,
    resp=SpectreeResponse(
        HTTP_201=InventedClarificationSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def create_clarification(
    item_id: uuid.UUID,
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> Any:
    """Place the clarification run of the pass that asked about the
    registered document's blocks (`writer-questions`) on the conversation of
    the run that registered the document (F52.2): with a reply, its turn
    ended with it, nothing started, the document's clarification showing it;
    with none, started through the gate as the pass's end starts it, its
    turn's end recording the reply.

    Returns:
        201: The clarification run's work item
        400: The body is invalid, or the stage is prd
        404: No item has the id
        409: Its writer was asked nothing, or the pass that asked has its
            clarification run already, or with no reply the project is
            finished or archived: the reason
    """
    data = InventedClarificationCreateSchema.model_validate(request.get_json())
    run = test_data_service.clarify(item_id, data.reply)
    return InventedClarificationSchema(id=run.id).model_dump(mode="json"), 201


@testing_record_bp.route("/projects/<uuid:project_id>/chat/answers", methods=["POST"])
@api.validate(
    json=InventedChatAnswerCreateSchema,
    resp=SpectreeResponse(
        HTTP_201=RecordedSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def create_chat_answer(
    project_id: uuid.UUID,
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> Any:
    """Record a person's answer to a block through the project's open chat,
    as its brain's `answer` records it (F42.1, F86.2): the effect of the call
    `tool_use_id` names in the chat's turn in flight, the place *In the chat*
    goes to (F42.3).

    Returns:
        201: The call's effect line
        400: The body is not a block's id, an answer, a handle, and an
            optional note, task and call id, or the stage is prd
        404: No project has the id, the block is not of it, or no person has
            the handle
        409: The project has no chat open, its chat has no turn in flight, or
            the record refuses the answer: the reason
    """
    data = InventedChatAnswerCreateSchema.model_validate(request.get_json())
    line = test_data_service.answer_in_chat(
        project_id,
        data.block,
        data.value,
        data.for_,
        note=data.note,
        to=data.to,
        tool_use_id=data.tool_use_id,
    )
    return RecordedSchema(effect=f"{line.verb} · {line.label}").model_dump(
        mode="json"
    ), 201


@testing_record_bp.route("/store-update", methods=["POST"])
@api.validate(
    json=InventedStoreUpdateCreateSchema,
    resp=SpectreeResponse(
        HTTP_200=InventedStoreUpdateSchema,
        HTTP_201=InventedStoreUpdateSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def create_store_update(
    store_update_service: StoreUpdateService = Provide[
        ServiceContainer.store_update_service
    ],
) -> Any:
    """Make a store's update, its hold on the store's work standing from the
    request's commit, or ask the unlifted one's lift, as `update-store` and
    its `--lift` do (F144.5): the row written and nothing else, the server
    taking it up at its timer's next tick (DB 279).

    Returns:
        201: The update made
        200: The unlifted update, its lift asked
        400: The body is invalid, or the stage is prd
        409: An update is under way, to make one, or none is, to lift: the
            reason
    """
    data = InventedStoreUpdateCreateSchema.model_validate(request.get_json())
    if data.lift:
        update = store_update_service.request_lift()
        return InventedStoreUpdateSchema.model_validate(update).model_dump(
            mode="json"
        ), 200
    update = store_update_service.make()
    return InventedStoreUpdateSchema.model_validate(update).model_dump(mode="json"), 201


@testing_record_bp.route("/projects/<uuid:project_id>/waits", methods=["POST"])
@api.validate(
    json=InventedWaitCreateSchema,
    resp=SpectreeResponse(
        HTTP_201=InventedItemSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def create_wait(
    project_id: uuid.UUID,
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> Any:
    """Add a wait to the project's timeline, by the project's session, as the
    brain's `add_item` adds one (F86.1): a card wait on its cards and states,
    a timed wait due at its time; placed at `placed_at`, as a wait added then
    reads, so that a timed wait is due, or past due, at once.

    Returns:
        201: The wait's id
        400: The body is invalid, a field of the other kind given, or the
            stage is prd
        404: No project has the id
        409: The project has no session, `placed_at` is ahead, or the add
            refuses the wait: the reason
    """
    data = InventedWaitCreateSchema.model_validate(request.get_json())
    item = test_data_service.wait(project_id, data)
    return InventedItemSchema(id=item.id).model_dump(mode="json"), 201


@testing_record_bp.route("/tracker-events/<tracker>", methods=["POST"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=TrackerEventReplySchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
    ),
)
@inject
def create_tracker_event(
    tracker: str,
    tracker_event_service: TrackerEventService = Provide[
        ServiceContainer.tracker_event_service
    ],
) -> Any:
    """Deliver a card's change of state as `POST /api/tracker-events/<tracker>`
    takes it, past its token and its count of deliveries received: its body
    the tracker's own, `youtrack`'s the Webhook Triggers app's
    `issueUpdated`; the card waits it matches fire (F136.2).

    Returns:
        200: How many waits fired, none for a delivery the endpoint drops
        400: The tracker's adapter cannot read the body, or the stage is prd
        404: No tracker has the name
    """
    fired = tracker_event_service.take(tracker, request.get_data())
    return TrackerEventReplySchema(fired=fired).model_dump()


@testing_record_bp.route("/waits/due", methods=["POST"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_200=InventedFiredSchema, HTTP_400=ApiErrorResponseSchema
    ),
)
@inject
def create_due_firings(
    wait_service: WaitService = Provide[ServiceContainer.wait_service],
) -> Any:
    """Run the waits' timer's tick now: every open timed wait whose due time
    has passed fires `due`, once (F27.2).

    Returns:
        200: How many waits fired
        400: The stage is prd
    """
    return InventedFiredSchema(fired=wait_service.fire_due()).model_dump()


@testing_record_bp.route("/waits/<uuid:item_id>/run", methods=["POST"])
@api.validate(
    resp=SpectreeResponse(
        HTTP_201=InventedItemSchema,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def create_wait_run(
    item_id: uuid.UUID,
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> Any:
    """Place the wait's run now, as the batcher places it once the quiet
    window from its oldest pending firing has passed (F136.4): it starts
    through the gate once the request commits and takes the firings pending
    at its brief.

    Returns:
        201: The run's work item's id
        400: The stage is prd
        404: No wait has the id
        409: No run of it is due, or no controller or no store environment is
            configured: the reason
    """
    work = test_data_service.wait_run(item_id)
    return InventedItemSchema(id=work.id).model_dump(mode="json"), 201


@testing_record_bp.route("/waits/<uuid:item_id>/close", methods=["POST"])
@api.validate(
    json=InventedWaitCloseSchema,
    resp=SpectreeResponse(
        HTTP_204=None,
        HTTP_400=ApiErrorResponseSchema,
        HTTP_404=ApiErrorResponseSchema,
        HTTP_409=ApiErrorResponseSchema,
    ),
)
@inject
def create_wait_close(
    item_id: uuid.UUID,
    test_data_service: TestDataService = Provide[ServiceContainer.test_data_service],
) -> tuple[str, int]:
    """Close the open wait with its note as Pilot's `mark` does (F27.4), by
    the wait's latest run briefed, else by the project's session: done
    `marked`, consumed on the spot, the note its done line's.

    Returns:
        204: The wait is done
        400: The note is missing, or the stage is prd
        404: No wait has the id
        409: The wait has no run briefed and its project no session, the
            project is archived, or the wait is done
    """
    data = InventedWaitCloseSchema.model_validate(request.get_json())
    test_data_service.close_wait(item_id, data.note)
    return "", 204


def _saved(ingested: Ingested) -> dict[str, Any]:
    return InventedSaveSchema(
        held=ingested.held,
        faults=[
            InventedFaultSchema(line=fault.line, message=fault.message)
            for fault in ingested.faults
        ],
    ).model_dump()
