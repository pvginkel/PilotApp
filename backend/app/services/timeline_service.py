"""A project's timeline as a screen draws it (F8, F12, F13, F18, F31, F78); a
document read on its own, an item's, as it was done (F13.3), the project's
draft or its handbook (F37.4, F129.4); and the items waiting on a person,
which a tab's badge counts (F1.4, F94.5)."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import cast

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.engine import dsl
from app.engine.documents import OPENING, PROSE
from app.engine.paths import tree_path
from app.engine.record import MARKED, NOTICE, SETTLED, RecordService
from app.exceptions import RecordNotFoundException
from app.models import (
    Attachment,
    ConfirmationReason,
    Document,
    DocumentVersion,
    Item,
    ItemAttachment,
    ItemKind,
    PlanTask,
    Project,
    ProjectTransition,
    SaveError,
    User,
)
from app.models import Session as AgentSession
from app.models.reference import (
    AnswerChannel,
    BlockKind,
    DocumentRole,
    ErrorKind,
    ProjectState,
    SessionState,
    TransitionKind,
    VersionCause,
)
from app.schemas.timeline import (
    AttachmentSchema,
    BlockPartSchema,
    BlockSchema,
    BodyPartSchema,
    ConfirmationReasonSchema,
    DeferralSchema,
    DoneCauseCode,
    DoneSchema,
    ItemDocumentSchema,
    ItemForm,
    ItemKindCode,
    OptionSchema,
    ProjectDocumentSchema,
    ProsePartSchema,
    SectionSchema,
    StepSchema,
    TimelineItemSchema,
    TimelineSchema,
    UserSchema,
)
from app.services.people_service import initials

WORK = "work"

_STOPPED = (SessionState.STOPPED, SessionState.FAILED)
"""The states in which a work item waits on a person: stopped, or failed to
start (F1.4, F125)."""

_WORDS_A_MINUTE = 230
"""The reading speed of a review's "N min read" (F25.1)."""


@dataclass(frozen=True)
class Badge:
    """The items waiting on a person in one project, and whether one is urgent."""

    count: int
    urgent: bool


def waiting_on(person: User | None) -> ColumnElement[bool]:
    """The items waiting on `person` (F94.5, DB 225): open, `for` nobody or
    for them; a prose item but the opening, a notice only when it is urgent
    (F23.2, F10.3); a work item stopped or failed to start; never a wait
    (F27.5). Before a person has chosen their handle, every `for` item is
    another's."""
    form = (
        select(ItemKind.form).where(ItemKind.code == Item.kind_code).scalar_subquery()
    )
    state = (
        select(AgentSession.state_code)
        .where(AgentSession.id == Item.id)
        .scalar_subquery()
    )
    addressed: ColumnElement[bool] = Item.for_user_id.is_(None)
    if person is not None:
        addressed = or_(addressed, Item.for_user_id == person.id)
    return and_(
        Item.done_at.is_(None),
        addressed,
        or_(
            and_(
                form == PROSE,
                Item.kind_code != OPENING,
                or_(Item.kind_code != NOTICE, Item.urgent),
            ),
            and_(form == WORK, state.in_(_STOPPED)),
        ),
    )


class TimelineService:
    def __init__(self, db: Session, record_service: RecordService) -> None:
        self.db = db
        self.record_service = record_service

    def badges(
        self, person: User | None, project_ids: Iterable[uuid.UUID]
    ) -> dict[uuid.UUID, Badge]:
        """Each project's badge for `person` (F1.4); a project nothing waits
        on is left out."""
        rows = self.db.execute(
            select(
                Item.project_id,
                func.count().label("waiting"),
                func.bool_or(Item.urgent).label("urgent"),
            )
            .where(Item.project_id.in_(list(project_ids)), waiting_on(person))
            .group_by(Item.project_id)
        ).all()
        return {row.project_id: Badge(row.waiting, row.urgent) for row in rows}

    def timeline(self, project_id: uuid.UUID) -> TimelineSchema:
        """The project's every item in order, as its line and its open form
        show it. A prose item's text is the one last published, a held save's
        never (F78).

        Raises:
            RecordNotFoundException: no project has the id.
        """
        project = self._project(project_id)
        rows = self.db.execute(
            select(Item, Document, ItemKind.form)
            .join(ItemKind, ItemKind.code == Item.kind_code)
            .outerjoin(Document, Document.id == Item.id)
            .where(Item.project_id == project.id)
            .order_by(Item.seq)
        ).all()
        return TimelineSchema(
            finished_at=self._finished_at(project),
            items=self._items(
                project,
                [(item, document, form) for item, document, form in rows],
                {
                    item.id: _published(document)
                    for item, document, _ in rows
                    if document is not None and item.kind_code != OPENING
                },
            ),
        )

    def item_document(self, item_id: uuid.UUID) -> ItemDocumentSchema:
        """The item's document read on its own, as its timeline entry shows
        it, but that an item done by Done, Pilot's included, reads as Done
        fixed it (F13.3): the text of its latest `done` Version. Only Done
        cuts one; an open item, and one done any other way, reads as last
        published.

        Raises:
            RecordNotFoundException: no item has the id, or it has no
                document: work and waits.
        """
        row = self.db.execute(
            select(Item, Document, ItemKind.form)
            .join(ItemKind, ItemKind.code == Item.kind_code)
            .join(Document, Document.id == Item.id)
            .where(Item.id == item_id)
        ).one_or_none()
        if row is None:
            raise RecordNotFoundException("Document of item", str(item_id))
        item, document, form = row
        project = self.db.get_one(Project, item.project_id)
        fixed = self._fixed_at_done(item)
        texts = (
            {}
            if item.kind_code == OPENING
            else {item.id: _published(document) if fixed is None else fixed}
        )
        (entry,) = self._items(project, [(item, document, form)], texts)
        if fixed is not None:
            parsed = dsl.parse(fixed)
            entry = entry.model_copy(
                update={"title": parsed.title, "summary": parsed.front_matter.summary}
            )
        return ItemDocumentSchema(project_id=project.id, **dict(entry))

    def project_document(
        self, project_id: uuid.UUID, role: DocumentRole
    ) -> ProjectDocumentSchema:
        """The project's draft or its handbook as last published, read only.

        Raises:
            RecordNotFoundException: no project has the id, or it has no
                document of the role: a draft has no handbook (F129.2).
        """
        project = self._project(project_id)
        document = self.db.scalars(
            select(Document).where(
                Document.project_id == project.id, Document.role_code == role
            )
        ).one_or_none()
        if document is None:
            raise RecordNotFoundException(
                f"{role.value.capitalize()} of project", str(project.id)
            )
        text = _published(document)
        parts = dsl.body(text)
        reader = self._reader(project, self._users(set(), _answerers([parts])))
        return ProjectDocumentSchema(
            title=dsl.parse(text).title,
            body=[reader.part(part) for part in parts],
            writing=document.writing_session_id is not None,
        )

    def _items(
        self,
        project: Project,
        rows: list[tuple[Item, Document | None, str]],
        texts: dict[uuid.UUID, str],
    ) -> list[TimelineItemSchema]:
        """`rows`, items of `project` with their documents and forms, as their
        lines and open forms show them; a prose item's text as drawn is its
        text in `texts`, where the opening, work and waits have none."""
        bodies = {item_id: dsl.body(text) for item_id, text in texts.items()}
        counts = {item_id: dsl.words(text) for item_id, text in texts.items()}
        edited = self._edited(list(texts))
        attachments = self._attachments([item.id for item, _, _ in rows])
        reader = self._reader(
            project,
            self._users(
                {
                    user_id
                    for item, _, _ in rows
                    for user_id in (
                        item.for_user_id,
                        item.done_by_user_id,
                        item.created_by_user_id,
                    )
                    if user_id is not None
                },
                _answerers(bodies.values()),
            ),
        )
        held = set(
            self.db.scalars(
                select(SaveError.path).where(
                    SaveError.kind_code == ErrorKind.PARSE,
                    SaveError.path.in_(
                        [
                            tree_path(project, document.path)
                            for _, document, _ in rows
                            if document is not None
                        ]
                    ),
                )
            )
        )
        return [
            TimelineItemSchema(
                id=item.id,
                seq=item.seq,
                kind=cast(ItemKindCode, item.kind_code),
                form=cast(ItemForm, form),
                title=item.title,
                file_name=(
                    None
                    if document is None or document.source_path is None
                    else PurePosixPath(document.source_path).name
                ),
                created_at=item.created_at,
                step=(
                    None
                    if item.plan_task_id is None
                    else StepSchema(
                        id=item.plan_task_id,
                        title=reader.tasks[item.plan_task_id],
                    )
                ),
                urgent=item.urgent,
                for_user=reader.user(item.for_user_id),
                done=self._done(item, reader),
                concept=(
                    document is not None and tree_path(project, document.path) in held
                ),
                author=reader.user(item.created_by_user_id),
                words=(
                    _published(document)
                    if document is not None and item.kind_code == OPENING
                    else None
                ),
                body=(
                    None
                    if item.id not in bodies
                    else [reader.part(part) for part in bodies[item.id]]
                ),
                summary=None if document is None else document.summary,
                word_count=counts.get(item.id),
                read_minutes=(
                    None if item.id not in counts else _read_minutes(counts[item.id])
                ),
                writing=(
                    document is not None and document.writing_session_id is not None
                ),
                edited_at=edited.get(item.id),
                attachments=attachments.get(item.id, []),
            )
            for item, document, form in rows
        ]

    def _fixed_at_done(self, item: Item) -> str | None:
        """The text Done fixed of an item it marked done (F13.3), from its
        latest `done` Version; none for an open item and one done otherwise.
        Undo cuts no Version, so the cause tells a Done in force from one
        undone before the item was closed another way (`finished`)."""
        if item.done_cause_code not in (MARKED, SETTLED):
            return None
        return self.db.scalars(
            select(DocumentVersion.text)
            .where(
                DocumentVersion.document_id == item.id,
                DocumentVersion.cause_code == VersionCause.DONE,
            )
            .order_by(DocumentVersion.number.desc())
            .limit(1)
        ).first()

    def _project(self, project_id: uuid.UUID) -> Project:
        project = self.db.get(Project, project_id)
        if project is None:
            raise RecordNotFoundException("Project", str(project_id))
        return project

    def _reader(
        self, project: Project, users: dict[uuid.UUID | str, User]
    ) -> "_Reader":
        return _Reader(
            users=users,
            tasks=dict(
                self.db.execute(
                    select(PlanTask.task_id, PlanTask.title).where(
                        PlanTask.project_id == project.id
                    )
                ).all()
            ),
            reasons={
                reason.code: reason
                for reason in self.db.scalars(select(ConfirmationReason))
            },
        )

    def _edited(self, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
        """Each document's *Edited <time>* (F28.7, the planning's ruling): the
        time of its latest `turn` Version where a Version before it holds
        text as drawn, the first text it was shown with. A document with
        none is left out."""
        latest = {
            row.document_id: row
            for row in self.db.execute(
                select(
                    DocumentVersion.document_id,
                    DocumentVersion.number,
                    DocumentVersion.created_at,
                )
                .where(
                    DocumentVersion.document_id.in_(document_ids),
                    DocumentVersion.cause_code == VersionCause.TURN,
                )
                .ext(distinct_on(DocumentVersion.document_id))
                .order_by(DocumentVersion.document_id, DocumentVersion.number.desc())
            )
        }
        edited: dict[uuid.UUID, datetime] = {}
        number = 1
        pending = {key for key, turn in latest.items() if number < turn.number}
        while pending:
            for document_id, text in self.db.execute(
                select(DocumentVersion.document_id, DocumentVersion.text).where(
                    DocumentVersion.document_id.in_(pending),
                    DocumentVersion.number == number,
                )
            ):
                if dsl.body(text):
                    edited[document_id] = latest[document_id].created_at
                    pending.discard(document_id)
            number += 1
            pending = {key for key in pending if number < latest[key].number}
        return edited

    def _attachments(
        self, item_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[AttachmentSchema]]:
        """The attachments hung on each item, in their order; an item with
        none is left out."""
        hung: dict[uuid.UUID, list[AttachmentSchema]] = {}
        for item_id, attachment in self.db.execute(
            select(ItemAttachment.item_id, Attachment)
            .join(Attachment, Attachment.id == ItemAttachment.attachment_id)
            .where(ItemAttachment.item_id.in_(item_ids))
            .order_by(ItemAttachment.item_id, ItemAttachment.position)
        ):
            hung.setdefault(item_id, []).append(
                AttachmentSchema(
                    id=attachment.id,
                    title=attachment.title,
                    filename=attachment.filename,
                    content_type=attachment.content_type,
                    size=attachment.size,
                    batch=attachment.batch,
                    copied_at=attachment.copied_at,
                    source=(
                        None
                        if attachment.source_path is None
                        else f"{attachment.source_environment_id}:"
                        f"{attachment.source_path}"
                    ),
                )
            )
        return hung

    def _done(self, item: Item, reader: "_Reader") -> DoneSchema | None:
        if item.done_at is None:
            return None
        return DoneSchema(
            at=item.done_at,
            cause=cast(DoneCauseCode, item.done_cause_code),
            by=reader.user(item.done_by_user_id),
            undo=self.record_service.offers_undo(item),
        )

    def _finished_at(self, project: Project) -> datetime | None:
        if project.state_code is not ProjectState.FINISHED:
            return None
        return self.db.scalar(
            select(func.max(ProjectTransition.at)).where(
                ProjectTransition.project_id == project.id,
                ProjectTransition.kind_code == TransitionKind.FINISHED,
            )
        )

    def _users(
        self, user_ids: set[uuid.UUID], handles: set[str]
    ) -> dict[uuid.UUID | str, User]:
        """The users by id and by handle."""
        found: dict[uuid.UUID | str, User] = {}
        for user in self.db.scalars(
            select(User).where(or_(User.id.in_(user_ids), User.handle.in_(handles)))
        ):
            found[user.id] = user
            found[user.handle] = user
        return found


@dataclass(frozen=True)
class _Reader:
    """What a timeline's items name, read once for them all."""

    users: dict[uuid.UUID | str, User]
    tasks: dict[str, str]
    reasons: dict[str, ConfirmationReason]

    def user(self, key: uuid.UUID | str | None) -> UserSchema | None:
        if key is None:
            return None
        user = self.users[key]
        return UserSchema(
            kind=user.kind_code,
            handle=user.handle,
            name=user.name,
            initials=initials(user.name),
            avatar_slot=user.avatar_slot,
        )

    def part(self, part: dsl.Prose | dsl.Block) -> BodyPartSchema:
        if isinstance(part, dsl.Prose):
            return ProsePartSchema(
                type="prose", markdown=part.markdown, section=part.section
            )
        return BlockPartSchema(type="block", block=self._block(part))

    def _block(self, block: dsl.Block) -> BlockSchema:
        because = None if block.because is None else self.reasons[block.because]
        return BlockSchema(
            id=block.local_id,
            kind=BlockKind(block.kind.value),
            confirmation=block.confirmation,
            because=(
                None
                if because is None
                else ConfirmationReasonSchema(
                    code=because.code,
                    name=because.name,
                    description=because.description,
                )
            ),
            proposal=block.proposal,
            default=block.default,
            check=block.check,
            options=[
                OptionSchema(
                    label=option.label,
                    text=option.text,
                    recommended=option.recommended,
                )
                for option in block.options
            ],
            answer=block.answer,
            by=self.user(block.by),
            at=block.at,
            note=block.note,
            via=None if block.via is None else AnswerChannel(block.via),
            done=block.done,
            deferral=(
                DeferralSchema(
                    to=block.to,
                    title=None if block.to == dsl.PLAN else self.tasks[block.to],
                )
                if block.answer == dsl.DEFERRED and block.to is not None
                else None
            ),
            section=(
                None
                if block.section is None
                else SectionSchema(heading=block.section.heading)
            ),
        )


def _answerers(bodies: Iterable[Iterable[dsl.Prose | dsl.Block]]) -> set[str]:
    """The handles of those who answered a block of `bodies`."""
    return {
        part.by
        for parts in bodies
        for part in parts
        if isinstance(part, dsl.Block) and part.by is not None
    }


def _read_minutes(words: int) -> int:
    """`words` at the reading speed, rounded half up, at least 1."""
    return max(1, (words + _WORDS_A_MINUTE // 2) // _WORDS_A_MINUTE)


def _published(document: Document) -> str:
    # Every document is born published.
    assert document.published_text is not None
    return document.published_text
