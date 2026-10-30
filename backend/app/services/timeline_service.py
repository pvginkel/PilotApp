"""A project's timeline as a screen draws it (F8, F12, F13, F18, F31, F78); a
document read on its own, an item's, as it was done (F13.3), the project's
draft or its handbook (F37.4, F129.4); and the items waiting on a person,
which a tab's badge counts (F1.4, F94.5)."""

import uuid
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, cast

import pilot_dsl as dsl
from sqlalchemy import ColumnElement, and_, exists, func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session, aliased

from app.engine.claims import claimed, standing
from app.engine.documents import OPENING, PROSE, awaiting_read, awaits_read
from app.engine.paths import tree_path
from app.engine.record import MARKED, NOTICE, SETTLED, TURN_ENDED, RecordService
from app.exceptions import RecordNotFoundException
from app.models import (
    Attachment,
    Block,
    Chat,
    ClaimAssignment,
    ConfirmationReason,
    Document,
    DocumentVersion,
    Effect,
    Environment,
    Item,
    ItemAttachment,
    ItemKind,
    PlanTask,
    Project,
    ProjectMember,
    ProjectTransition,
    SaveError,
    Turn,
    User,
    Work,
    WriterQuestion,
)
from app.models import Session as AgentSession
from app.models.reference import (
    AnswerChannel,
    BlockKind,
    DocumentRole,
    EffectKind,
    ErrorKind,
    ProjectState,
    RecordKind,
    SessionState,
    TransitionKind,
    UserKind,
    VersionCause,
    WorkTrigger,
)
from app.schemas.links import EnvironmentNameSchema
from app.schemas.timeline import (
    AttachmentSchema,
    BlockPartSchema,
    BlockSchema,
    BodyPartSchema,
    ChatPlaceSchema,
    ClaimedWorkSchema,
    ClaimSchema,
    ClarificationSchema,
    ConfirmationReasonSchema,
    CurrentLineSchema,
    DeferralSchema,
    DoneCauseCode,
    DoneSchema,
    ItemDocumentSchema,
    ItemForm,
    ItemKindCode,
    OptionSchema,
    ProjectDocumentSchema,
    ProsePartSchema,
    RetriedSchema,
    SectionSchema,
    StepSchema,
    StopCause,
    TimelineItemSchema,
    TimelineSchema,
    UserSchema,
    WorkSchema,
    WriterQuestionSchema,
)
from app.services.clarification_service import Clarification, on_documents
from app.services.controller_outage import ControllerOutage
from app.services.people_service import initials
from app.services.relay_service import ENVIRONMENT_STOPPED
from app.services.session_record_service import last_record, read_records
from app.services.start_gate import (
    JOB_KIND,
    WORK_KIND,
    Held,
    WorkSlots,
    conversing,
    held_reason,
    queued,
)

WORK = "work"
WAIT = "wait"

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
    """The items waiting on `person` (F94.5, DB 225): F94.5's set, `for`
    nobody or for them. Before a person has chosen their handle, every `for`
    item is another's."""
    addressed: ColumnElement[bool] = Item.for_user_id.is_(None)
    if person is not None:
        addressed = or_(addressed, Item.for_user_id == person.id)
    return and_(waiting(), addressed)


def waiting_on_a_member() -> ColumnElement[bool]:
    """The items waiting on a member of their project (DB 225, 228): F94.5's
    set, `for` nobody while the project has a member, or for one of its
    members."""
    member = (
        select(ProjectMember.id)
        .where(
            ProjectMember.project_id == Item.project_id,
            ProjectMember.left_at.is_(None),
            or_(Item.for_user_id.is_(None), ProjectMember.user_id == Item.for_user_id),
        )
        .correlate(Item)
    )
    return and_(waiting(), member.exists())


def waiting() -> ColumnElement[bool]:
    """F94.5's set, whoever an item is for: open; a prose item but the
    opening, a notice only when it is urgent (F23.2, F10.3), a registered
    document only once its turn-end read is made, since none takes a close
    before it (review 7), and none whose open blocks are all actions Pilot
    claimed, which are Pilot's until their `done` (DB 262); a work item
    stopped or failed, a job only until it is retried; never a wait
    (F27.5)."""
    form = (
        select(ItemKind.form)
        .where(ItemKind.code == Item.kind_code)
        .correlate(Item)
        .scalar_subquery()
    )
    state = (
        select(AgentSession.state_code)
        .where(AgentSession.id == Item.id)
        .correlate(Item)
        .scalar_subquery()
    )
    unread = (
        select(Document.id)
        .where(Document.id == Item.id, awaiting_read())
        .correlate(Item)
        .exists()
    )
    retried = (
        select(Work.id)
        .where(Work.id == Item.id, Work.retried_by_id.is_not(None))
        .correlate(Item)
        .exists()
    )
    claims = (
        select(Block.id)
        .where(Block.document_id == Item.id, claimed())
        .correlate(Item)
        .exists()
    )
    unanswered = (
        select(Block.id)
        .where(
            Block.document_id == Item.id,
            Block.answer.is_(None),
            Block.done_at.is_(None),
        )
        .correlate(Item)
        .exists()
    )
    return and_(
        Item.done_at.is_(None),
        or_(
            and_(
                form == PROSE,
                Item.kind_code != OPENING,
                or_(Item.kind_code != NOTICE, Item.urgent),
                ~unread,
                or_(~claims, unanswered),
            ),
            and_(form == WORK, state.in_(_STOPPED), ~retried),
        ),
    )


def work_status(
    db: Session,
    item_ids: Collection[uuid.UUID],
    *,
    unreachable: bool,
    slots: WorkSlots,
) -> dict[uuid.UUID, WorkSchema]:
    """The work status of each work item among `item_ids`, as its line and
    head show it, the controller `unreachable` or not; an item of another kind
    is left out. A failed one's error is its latest Turn's, else its
    Session's: a turn's failure is its Turn's, a start's the Session's (DB
    Session `error?`). A held one's reason is the gate's as it reads now, the
    slot's with the count that closed it (`slots`), a job's queue read for
    it (`queued`), a work item's conversation for it (`conversing`). A
    stopped one's stop is
    when and by whom, a Resume keeping both on the Session (DB Session
    `stopped_at?`, `stopped_by?`); one no one stopped has the cause its
    environment's stop under it left as its last record. One whose start has
    no environment yet has none (DB 107). A job's is Pilot's own (F59.1); a
    retried one's names the job its Retry placed, created at the press."""
    stopper = aliased(User)
    retry = aliased(AgentSession)
    rows = db.execute(
        select(
            AgentSession,
            Environment.id,
            Environment.name,
            Work.autopilot,
            Project.paused,
            Work.trigger_code,
            stopper,
            retry.id,
            retry.created_at,
        )
        .join(Work, Work.id == AgentSession.id)
        .outerjoin(Environment, Environment.id == AgentSession.environment_id)
        .join(Project, Project.id == AgentSession.project_id)
        .outerjoin(stopper, stopper.id == AgentSession.stopped_by_user_id)
        .outerjoin(retry, retry.id == Work.retried_by_id)
        .where(AgentSession.id.in_(list(item_ids)))
    ).all()
    failed = [
        session.id for session, *_ in rows if session.state_code is SessionState.FAILED
    ]
    turn_errors: dict[uuid.UUID, str | None] = (
        dict(
            db.execute(
                select(Turn.session_id, Turn.error)
                .where(Turn.session_id.in_(failed))
                .ext(distinct_on(Turn.session_id))
                .order_by(Turn.session_id, Turn.seq.desc())
            ).all()
        )
        if failed
        else {}
    )
    causes = {
        session.id: _stop_cause(db, session.id)
        for session, *_ in rows
        if session.state_code is SessionState.STOPPED
        and session.stopped_by_user_id is None
    }
    waiting = {
        session.project_id
        for session, *_ in rows
        if session.state_code is SessionState.HELD and session.kind_code == WORK_KIND
    }
    filled = slots.filled(db, waiting) if waiting else {}
    behind = queued(
        db,
        [
            session.id
            for session, *_ in rows
            if session.state_code is SessionState.HELD and session.kind_code == JOB_KIND
        ],
    )
    resuming = conversing(
        db,
        [
            session.id
            for session, *_ in rows
            if session.state_code is SessionState.HELD
            and session.kind_code == WORK_KIND
        ],
    )
    held: dict[uuid.UUID, Held] = {}
    for session, _, _, _, paused, trigger, *_ in rows:
        if session.state_code is not SessionState.HELD:
            continue
        reason = held_reason(
            paused=paused,
            kind_code=session.kind_code,
            setup=trigger is WorkTrigger.SETUP,
            unreachable=unreachable,
            filled=filled.get(session.project_id),
            queued=session.id in behind,
            conversing=session.id in resuming,
        )
        if reason is not None:
            held[session.id] = reason
    return {
        session.id: WorkSchema(
            state=session.state_code,
            current_line=_current_line(session.current_line),
            environment=(
                None if env_id is None else EnvironmentNameSchema(id=env_id, name=name)
            ),
            started_at=session.started_at,
            error=(
                turn_errors.get(session.id) or session.error
                if session.state_code is SessionState.FAILED
                else None
            ),
            autopilot=autopilot,
            pilots_own=session.kind_code == JOB_KIND,
            held_reason=held[session.id].reason if session.id in held else None,
            held_running=held[session.id].running if session.id in held else None,
            stopped_at=(
                session.stopped_at
                if session.state_code is SessionState.STOPPED
                else None
            ),
            stopped_by=(
                _user_schema(stopped_by)
                if session.state_code is SessionState.STOPPED and stopped_by is not None
                else None
            ),
            stopped_cause=causes.get(session.id),
            retried=(
                None if retry_id is None else RetriedSchema(id=retry_id, at=retried_at)
            ),
        )
        for (
            session,
            env_id,
            name,
            autopilot,
            _,
            _,
            stopped_by,
            retry_id,
            retried_at,
        ) in rows
    }


def writer_asked(
    db: Session, document_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    """The local ids of the blocks each of the documents' writer is asked
    about (DB Writer Question), in their order in it; a document whose writer
    is asked nothing is left out."""
    asked: dict[uuid.UUID, list[str]] = {}
    for document_id, local_id in db.execute(
        select(Block.document_id, Block.local_id)
        .join(WriterQuestion, WriterQuestion.block_id == Block.id)
        .where(Block.document_id.in_(document_ids))
        .order_by(Block.document_id, Block.position)
    ):
        asked.setdefault(document_id, []).append(local_id)
    return asked


def _stop_cause(db: Session, session_id: uuid.UUID) -> StopCause | None:
    """The cause of the Session's stop when its environment was stopped under
    its turn: its last record is the `server` record that ended the turn
    naming it (design 2 §9.6); None for any other stop."""
    last = last_record(db, session_id)
    if last is None or last.record.kind_code != RecordKind.SERVER:
        return None
    payload = last.record.payload
    if payload.get("type") != ENVIRONMENT_STOPPED:
        return None
    return StopCause(payload["cause"])


def _user_schema(user: User) -> UserSchema:
    return UserSchema(
        kind=user.kind_code,
        handle=user.handle,
        name=user.name,
        initials=initials(user.name),
        avatar_slot=user.avatar_slot,
    )


class TimelineService:
    def __init__(
        self,
        db: Session,
        record_service: RecordService,
        controller_outage: ControllerOutage,
        work_slots: WorkSlots,
    ) -> None:
        self.db = db
        self.record_service = record_service
        self.controller_outage = controller_outage
        self.work_slots = work_slots

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

    def work(self, item_id: uuid.UUID) -> WorkSchema:
        """The work item's status, as its line and head show it.

        Raises:
            RecordNotFoundException: no work item has the id.
        """
        work = work_status(
            self.db,
            [item_id],
            unreachable=self.controller_outage.holds,
            slots=self.work_slots,
        ).get(item_id)
        if work is None:
            raise RecordNotFoundException("Work item", str(item_id))
        return work

    def timeline(self, project_id: uuid.UUID) -> TimelineSchema:
        """The project's every item in order, as its line and its open form
        show it, and the attachments hung on none, a draft's (F36.6). A prose
        item's text is the one last published, a held save's never (F78).

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
            ready_after=self._ready_after(project),
            items=self._items(
                project,
                [(item, document, form) for item, document, form in rows],
                {
                    item.id: document.published_text
                    for item, document, _ in rows
                    if document is not None
                    and item.kind_code != OPENING
                    and document.published_text is not None
                },
            ),
            unhung_attachments=[
                _attachment(attachment)
                for attachment in self.db.scalars(
                    select(Attachment)
                    .where(
                        Attachment.project_id == project.id,
                        ~exists().where(ItemAttachment.attachment_id == Attachment.id),
                    )
                    .order_by(Attachment.batch, Attachment.filename)
                )
            ],
        )

    def item_document(self, item_id: uuid.UUID) -> ItemDocumentSchema:
        """The item's document read on its own, as its timeline entry shows
        it, but that an item done by Done, Pilot's included, reads as Done
        fixed it (F13.3): the text of its latest `done` Version. Only Done
        cuts one; an open item, and one done any other way, reads as last
        published. A registered document with no text reads with no body.

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
        text = document.published_text if fixed is None else fixed
        texts = {} if item.kind_code == OPENING or text is None else {item.id: text}
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
        reader = self._reader(
            project,
            self._users(set(), _answerers([parts])),
            self._chat_places({document.id: parts}),
            {},
            frozenset(),
        )
        return ProjectDocumentSchema(
            title=dsl.parse(text).title,
            body=[reader.part(document.id, part) for part in parts],
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
        text in `texts`, where the opening, work, waits and a registered
        document with no text have none."""
        bodies = {item_id: dsl.body(text) for item_id, text in texts.items()}
        counts = {item_id: dsl.words(text) for item_id, text in texts.items()}
        edited = self._edited(list(texts))
        attachments = self._attachments([item.id for item, _, _ in rows])
        documents = [item.id for item, document, _ in rows if document is not None]
        asked = writer_asked(self.db, documents)
        clarified = on_documents(self.db, documents)
        works = work_status(
            self.db,
            [item.id for item, _, form in rows if form == WORK],
            unreachable=self.controller_outage.holds,
            slots=self.work_slots,
        )
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
            self._chat_places(bodies),
            self._claims(bodies),
            frozenset(
                (document_id, local_id)
                for document_id, local_ids in asked.items()
                for local_id in local_ids
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
                    else [reader.part(item.id, part) for part in bodies[item.id]]
                ),
                summary=None if document is None else document.summary,
                word_count=counts.get(item.id),
                read_minutes=(
                    None if item.id not in counts else _read_minutes(counts[item.id])
                ),
                writing=(
                    document is not None and document.writing_session_id is not None
                ),
                awaiting_read=document is not None and awaits_read(item, document),
                edited_at=edited.get(item.id),
                attachments=attachments.get(item.id, []),
                asked_writer_about=asked.get(item.id, []),
                clarifications=[
                    _clarification(clarification)
                    for clarification in clarified.get(item.id, [])
                ],
                work=works[item.id] if form == WORK else None,
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
        self,
        project: Project,
        users: dict[uuid.UUID | str, User],
        places: dict[tuple[uuid.UUID, str], ChatPlaceSchema],
        claims: dict[tuple[uuid.UUID, str], ClaimedWorkSchema],
        asked: frozenset[tuple[uuid.UUID, str]],
    ) -> "_Reader":
        return _Reader(
            users=users,
            places=places,
            claims=claims,
            asked=asked,
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

    def _chat_places(
        self, bodies: Mapping[uuid.UUID, Iterable[dsl.Prose | dsl.Block]]
    ) -> dict[tuple[uuid.UUID, str], ChatPlaceSchema]:
        """Where in a chat each block of `bodies`, by its document's id, had
        its answer recorded, keyed by the document's id and its local id
        (F42.3): the `server` record placing the latest `answered` Effect on
        it. A block whose answer's channel is not chat is left out, as is one
        whose latest such Effect's call ran in a session no chat is, a job's."""
        answered = {
            (document_id, part.local_id)
            for document_id, parts in bodies.items()
            for part in parts
            if isinstance(part, dsl.Block) and part.via == AnswerChannel.CHAT
        }
        if not answered:
            return {}
        placed = [
            row
            for row in self.db.execute(
                select(
                    Block.document_id,
                    Block.local_id,
                    Effect.record_id,
                    Chat.id.label("chat_id"),
                )
                .join(Effect, Effect.block_id == Block.id)
                .join(Turn, Turn.id == Effect.turn_id)
                .outerjoin(Chat, Chat.id == Turn.session_id)
                .where(
                    Block.document_id.in_({key[0] for key in answered}),
                    Effect.kind_code == EffectKind.ANSWERED,
                )
                .ext(distinct_on(Block.id))
                .order_by(Block.id, Effect.id.desc())
            )
            if row.chat_id is not None and (row.document_id, row.local_id) in answered
        ]
        # An Effect's record is a `server` record of its Turn's Session (DB 216).
        records: dict[uuid.UUID, set[int]] = {}
        for row in placed:
            records.setdefault(row.chat_id, set()).add(row.record_id)
        seqs = {
            stored.record.id: stored.record.seq
            for chat_id, ids in records.items()
            for stored in read_records(self.db, chat_id, ids=ids, limit=len(ids))
        }
        return {
            (row.document_id, row.local_id): ChatPlaceSchema(
                chat=row.chat_id, seq=seqs[row.record_id]
            )
            for row in placed
        }

    def _claims(
        self, bodies: Mapping[uuid.UUID, Iterable[dsl.Prose | dsl.Block]]
    ) -> dict[tuple[uuid.UUID, str], ClaimedWorkSchema]:
        """The work item each action of `bodies` that Pilot claimed and has
        not done is given to, by its standing Claim Assignment (DB 260),
        keyed by its document's id and its local id; a claim no work item is
        named for is left out."""
        claims = {
            (document_id, part.local_id)
            for document_id, parts in bodies.items()
            for part in parts
            if isinstance(part, dsl.Block) and part.claimed
        }
        if not claims:
            return {}
        latest = (
            standing()
            .where(
                ClaimAssignment.block_id.in_(
                    select(Block.id).where(
                        Block.document_id.in_({key[0] for key in claims})
                    )
                )
            )
            .subquery()
        )
        given: dict[tuple[uuid.UUID, str], ClaimedWorkSchema] = {}
        for document_id, local_id, work_id, title in self.db.execute(
            select(
                Block.document_id, Block.local_id, ClaimAssignment.work_id, Item.title
            )
            .join(ClaimAssignment, ClaimAssignment.block_id == Block.id)
            .join(
                latest,
                and_(
                    latest.c.block_id == ClaimAssignment.block_id,
                    latest.c.work_id == ClaimAssignment.work_id,
                ),
            )
            .join(Item, Item.id == ClaimAssignment.work_id)
        ):
            # A work item is born titled (DB decision 50).
            assert title is not None
            if (document_id, local_id) in claims:
                given[(document_id, local_id)] = ClaimedWorkSchema(
                    id=work_id, title=title
                )
        return given

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
            hung.setdefault(item_id, []).append(_attachment(attachment))
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

    def _ready_after(self, project: Project) -> uuid.UUID | None:
        """The setup's work item while the project is paused by Create's pause
        and its setup is done (`TimelineSchema.ready_after`; D083); None
        otherwise. Pilot pauses a project at its Create alone, and a resume
        ends that pause for good."""
        if (
            project.state_code is not ProjectState.OPEN
            or project.archived
            or not project.paused
        ):
            return None
        since_opened = self.db.execute(
            select(ProjectTransition.kind_code, User.kind_code)
            .join(User, User.id == ProjectTransition.by_user_id)
            .where(
                ProjectTransition.project_id == project.id,
                ProjectTransition.id
                >= select(ProjectTransition.id)
                .where(
                    ProjectTransition.project_id == project.id,
                    ProjectTransition.kind_code == TransitionKind.OPENED,
                )
                .scalar_subquery(),
            )
            .order_by(ProjectTransition.id)
        ).all()
        if (
            len(since_opened) < 2
            or tuple(since_opened[1]) != (TransitionKind.PAUSED, UserKind.AGENT)
            or any(kind is TransitionKind.RESUMED for kind, _ in since_opened)
        ):
            return None
        return self.db.scalar(
            select(Item.id)
            .join(Work, Work.id == Item.id)
            .where(
                Item.project_id == project.id,
                Work.trigger_code == WorkTrigger.SETUP,
                Work.retried_by_id.is_(None),
                Item.done_cause_code == TURN_ENDED,
            )
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
    places: dict[tuple[uuid.UUID, str], ChatPlaceSchema]
    claims: dict[tuple[uuid.UUID, str], ClaimedWorkSchema]
    asked: frozenset[tuple[uuid.UUID, str]]
    tasks: dict[str, str]
    reasons: dict[str, ConfirmationReason]

    def user(self, key: uuid.UUID | str | None) -> UserSchema | None:
        if key is None:
            return None
        return _user_schema(self.users[key])

    def part(
        self, document_id: uuid.UUID, part: dsl.Prose | dsl.Block
    ) -> BodyPartSchema:
        """A part of the document `document_id`'s text."""
        if isinstance(part, dsl.Prose):
            return ProsePartSchema(
                type="prose", markdown=part.markdown, section=part.section
            )
        return BlockPartSchema(type="block", block=self._block(document_id, part))

    def _block(self, document_id: uuid.UUID, block: dsl.Block) -> BlockSchema:
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
                    asks_under_autopilot=because.asks_under_autopilot,
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
            in_chat=self.places.get((document_id, block.local_id)),
            done=block.done,
            claim=(
                ClaimSchema(work=self.claims.get((document_id, block.local_id)))
                if block.claimed
                else None
            ),
            deferral=(
                DeferralSchema(
                    to=block.to,
                    title=None if block.to == dsl.PLAN else self.tasks[block.to],
                )
                if block.answer == dsl.DEFERRED and block.to is not None
                else None
            ),
            writer_asked=(document_id, block.local_id) in self.asked,
            section=(
                None
                if block.section is None
                else SectionSchema(heading=block.section.heading)
            ),
        )


def _clarification(clarification: Clarification) -> ClarificationSchema:
    return ClarificationSchema(
        asked_at=clarification.asked_at,
        questions=[
            WriterQuestionSchema(
                block=each.local_id,
                question=each.question,
                asked_at=each.asked_at,
                heading=clarification.headings[each.block_id],
                reply=clarification.parts.get(each.block_id),
            )
            for each in clarification.questions
        ],
        reply=clarification.reply,
        replied_at=clarification.replied_at,
        split=clarification.split,
    )


def _attachment(attachment: Attachment) -> AttachmentSchema:
    return AttachmentSchema(
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
            else f"{attachment.source_environment_id}:{attachment.source_path}"
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


def _current_line(line: dict[str, Any] | None) -> CurrentLineSchema | None:
    """The stored current line, whose keys but `state` and `since` are absent
    where they do not apply (design 2 §9.5)."""
    if line is None:
        return None
    return CurrentLineSchema.model_validate(
        {
            "state": line["state"],
            "since": line["since"],
            "step": line.get("step"),
            "agent": line.get("agent"),
            "text": line.get("text"),
        }
    )


def _read_minutes(words: int) -> int:
    """`words` at the reading speed, rounded half up, at least 1."""
    return max(1, (words + _WORDS_A_MINUTE // 2) // _WORDS_A_MINUTE)


def _published(document: Document) -> str:
    # Every document but a registered one is born published: the opening and
    # a project's draft and handbook are.
    assert document.published_text is not None
    return document.published_text
