"""Testing endpoints that make the record's states the UI cannot make
(TEST-6): people who never signed in, environments, projects in every
standing, with members, a plan, their opening and open items, the items a
project's session adds, an agent's saves of them and of the project's draft
and handbook, the files it attaches, Pilot's Done, and the end of its turn;
and a work item placed by repository, started in an environment of Pilot's
own the stage's own controller creates, and the documents and the material its
session registers and attaches there, each with its effect; a pre-ruling
pass's questions to a registered document's writer; and a person's answer the
brain records through the project's open chat, with its effect.
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
from sqlalchemy.orm import Session

from app.config import Settings
from app.engine.ingest import Ingested
from app.exceptions import RouteNotAvailableException
from app.models.reference import DocumentRole
from app.schemas.common import ApiErrorResponseSchema
from app.schemas.pilot_store import RecordedSchema
from app.schemas.testing_record import (
    InventedAttachmentsCreateSchema,
    InventedAttachmentsSchema,
    InventedChatAnswerCreateSchema,
    InventedEnvironmentSchema,
    InventedFaultSchema,
    InventedItemCreateSchema,
    InventedItemSchema,
    InventedPersonCreateSchema,
    InventedPersonSchema,
    InventedProjectCreateSchema,
    InventedProjectSchema,
    InventedRegistrationCreateSchema,
    InventedSaveCreateSchema,
    InventedSaveSchema,
    InventedWorkCreateSchema,
    InventedWorkerAttachmentCreateSchema,
    InventedWorkerAttachmentsSchema,
    InventedWriterQuestionsCreateSchema,
    InventedWriterQuestionsSchema,
)
from app.services.container import ServiceContainer
from app.services.session_start_service import SessionStartService
from app.services.test_data_service import TestDataService
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
        201: The project's id
        400: A finished project with auto pilot on, a member named twice,
            open items without an environment, or a plan with a fault
        404: A member is no person, or no environment has the id
        409: The name makes a draft text with a fault
    """
    data = InventedProjectCreateSchema.model_validate(request.get_json())
    project = test_data_service.project(data)
    return InventedProjectSchema(id=project.id).model_dump(mode="json"), 201


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
    as Pilot adds one: its kind, urgency, person, step and blocks, Pilot's
    answers and deferrals among them, are what its text says.

    Returns:
        201: The item's id
        400: The kind is no prose kind Pilot adds, or the title is empty
        404: No project has the id
        409: The project has no session, or the text holds a fault
    """
    data = InventedItemCreateSchema.model_validate(request.get_json())
    item = test_data_service.item(project_id, data.kind, data.title, data.text)
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
    session_starts: SessionStartService = Provide[
        ServiceContainer.session_start_service
    ],
    db: Session = Provide[ServiceContainer.db_session],
) -> Any:
    """Place a work item on the project's timeline by repository, and start
    its session as every work item's starts: once the request commits, its
    start creates an environment of Pilot's own from the repository on the
    stage's own controller.

    Returns:
        201: The work item's id, its Work's and its Session's
        400: The body is invalid, or the stage is prd
        404: No project has the id, or its plan has no task of the step
        409: No controller is configured, or the project is finished or
            archived
    """
    data = InventedWorkCreateSchema.model_validate(request.get_json())
    work = session_starts.start_work(
        db,
        project_id,
        data.repo,
        title=data.title,
        brief=data.brief,
        cwd=data.cwd,
        plan_task_id=data.step,
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


def _saved(ingested: Ingested) -> dict[str, Any]:
    return InventedSaveSchema(
        held=ingested.held,
        faults=[
            InventedFaultSchema(line=fault.line, message=fault.message)
            for fault in ingested.faults
        ],
    ).model_dump()
