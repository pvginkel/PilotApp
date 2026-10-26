"""`pilot-store`, the brain's tools (TD §4.5, F86): the bearer its Session was
created with resolved to the Session, a chat's or a job's, admitted only while
its turn runs (the planning ruling) and acting on its project alone. Each tool
writes as the record's own writes do, Pilot the actor where it acts for itself
and the person `for` names where it acts on their behalf. Each call that
changed the record writes its Effect (F41); `ask_writer` writes its Writer
Question in place of one (DB decision 59).

Every write locks the Project's row first and the Session's for its effect
after, the order Finish takes, which locks the project's Sessions before their
Documents. `finish` writes its effect before the transition that stops its own
Session. Outside material is read through the controller before the Project's
row is locked, so no controller call is made while it is held.
"""

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

import pilot_dsl as dsl
from prometheus_client import Counter
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.engine.attachments import AttachService, Copy
from app.engine.documents import DocumentService, listed
from app.engine.ingest import IngestService
from app.engine.record import RecordService
from app.engine.views import ViewService
from app.exceptions import (
    AuthorizationException,
    InvalidOperationException,
    RecordNotFoundException,
)
from app.models import (
    Attachment,
    Block,
    Document,
    Item,
    ItemKind,
    PlanTask,
    Project,
    Turn,
    User,
    Work,
    WriterQuestion,
)
from app.models import Session as AgentSession
from app.models.reference import (
    AnswerChannel,
    EffectKind,
    SessionState,
    Surface,
    TransitionKind,
    UserKind,
)
from app.schemas.pilot_store import AddItemRequestSchema, Mark, source_parts
from app.services.brief_service import BriefService
from app.services.controller_client import (
    ControllerClient,
    ControllerProblem,
    ControllerProblemType,
)
from app.services.effect_service import Change, EffectLine, EffectService
from app.services.environment_service import EnvironmentService
from app.services.pilot_server import bearer_session
from app.services.pilot_work_service import ATTACHED, attached_label, material
from app.services.project_service import ProjectService, project_name
from app.services.session_scope import project_folder
from app.services.session_start_service import SessionStartService
from app.services.start_gate import Held
from app.services.timeline_service import writer_asked

JOB = "job"
"""The Session Kind of the server's jobs, the pre-ruling pass among them."""

WORK = "work"
WAITS = ("card_wait", "timed_wait")
"""The kinds of item `add_item` is given that are not prose (TD §4.5)."""

PROSE_FIELDS = ("markdown", "urgent", "for", "summary")
WORK_FIELDS = ("repo", "cwd", "brief", "agent", "model", "reasoning_effort")
NEEDED_FOR_WORK = ("title", "repo", "cwd", "brief")
"""The fields of `add_item`'s item that one form takes alone, by their names
on the wire, and those a work item needs."""

ADDED = "Added"
ANSWERED = "Answered"
MARKED: dict[Mark, str] = {
    "done": "Marked done",
    "read": "Marked read",
    "reviewed": "Marked reviewed",
}
STOPPED = "Stopped"
FINISHED = "Finished"
"""The verbs of the tools' effect lines (F41)."""

PASS_QUESTIONS_TOTAL = Counter(
    "pilot_pass_questions_total",
    "Questions the pre-ruling pass put to a registered document's writer, by project",
    ["project"],
)


@dataclass(frozen=True)
class Added:
    """The item `add_item` added, and its effect line."""

    item: Item
    path: str | None
    """A prose item's file, absolute; none for a work item."""
    state: Literal["starting", "held"] | None
    """A work item's Session as the gate left it."""
    held: Held | None
    """Why the gate holds a held work item's start."""
    line: EffectLine


@dataclass(frozen=True)
class Attached:
    """The attachments `attach_file` copied in, and its effect line."""

    attachments: list[Attachment]
    line: EffectLine


@dataclass(frozen=True)
class _Outside:
    """Outside material read for a call: the environment it was copied from,
    its path there, and its files."""

    environment_id: str
    path: str
    copies: list[Copy]


@dataclass(frozen=True)
class Brain:
    """The Session a bearer names (F84), a chat's or a job's, and its
    project."""

    session_id: uuid.UUID
    project_id: uuid.UUID
    kind_code: str


class PilotStoreService:
    def __init__(
        self,
        db: Session,
        record_service: RecordService,
        document_service: DocumentService,
        view_service: ViewService,
        project_service: ProjectService,
        session_start_service: SessionStartService,
        effect_service: EffectService,
        ingest_service: IngestService,
        attach_service: AttachService,
        brief_service: BriefService,
        environment_service: EnvironmentService,
        controller_client: Callable[[], ControllerClient],
    ) -> None:
        self.db = db
        self.record_service = record_service
        self.document_service = document_service
        self.view_service = view_service
        self.project_service = project_service
        self.session_start_service = session_start_service
        self.effect_service = effect_service
        self.ingest_service = ingest_service
        self.attach_service = attach_service
        self.brief_service = brief_service
        self.environment_service = environment_service
        self.controller_client = controller_client

    def admit(self, authorization: str | None) -> Brain:
        """The chat's or the job's Session whose bearer `authorization`
        carries, while its turn runs.

        Raises:
            AuthenticationException: no bearer, or one no Session has.
            AuthorizationException: the bearer's Session is a work item's,
                whose surface is `pilot-work`, or has no turn running.
        """
        session, surface = bearer_session(self.db, authorization, Surface.STORE)
        if surface is not Surface.STORE:
            raise AuthorizationException(
                f"Cannot call pilot-store because session {session.id} is a"
                f" {session.kind_code} session, not a chat's or a job's"
            )
        if session.state_code != SessionState.RUNNING:
            raise AuthorizationException(_no_turn(session.id))
        return Brain(session.id, session.project_id, session.kind_code)

    def add_item(
        self, brain: Brain, item: AddItemRequestSchema, tool_use_id: str | None
    ) -> Added:
        """`item` added to the brain's project, with the attachments it
        carries hung on it in their order (F86.1, F36.5): one already made by
        its id, outside material copied in as `attach_file` copies it, a batch
        per source. The call `tool_use_id`'s effect is "Added · <kind> · <title>",
        its Effects the item's and one per attachment hung.

        A prose item is minted with its file, born with its title and its
        facts — `step`, `urgent`, `for`, `summary` — in the front matter
        where its Markdown gives none of its own, empty without Markdown
        (F29.2, F86.6). A work item is started on add by its repository, as
        every work item's start is, its brief followed by the server's trailer
        (F66, §5.4), on the brain's placement (F61.1); its Session `held` or
        `starting`, as the gate leaves it (F141.4).

        Raises:
            RecordNotFoundException: an attachment or the plan's task is not
                of the brain's project, or an outside source's environment
                is not the controller's.
            InvalidOperationException: a wait, which Pilot does not take yet;
                a field the item's kind does not take, or one it needs,
                missing; a prose text that holds faults, each with its line;
                material that cannot be copied, nothing attached; the start a
                work item takes refused.
            ExternalServiceException: the controller did not answer, or
                refused for a reason of its own.
        """
        operation = f"add a {item.kind} item"
        given = set(item.model_dump(by_alias=True, exclude_defaults=True))
        refusal = _shape_refusal(item.kind, given)
        if refusal is not None:
            raise InvalidOperationException(operation, refusal)
        carried = [
            self._attachment(brain, ref)
            if _is_id(ref)
            else self._outside(ref, operation)
            for ref in item.attachments
        ]
        project = self._project(brain)
        session = self.db.get_one(AgentSession, brain.session_id)
        path: str | None = None
        state: Literal["starting", "held"] | None = None
        held: Held | None = None
        if item.kind == WORK:
            added = self._work(project, item)
            started = self.db.get_one(AgentSession, added.id)
            # The gate leaves a work item's start `held` or `starting`.
            state = "held" if started.state_code is SessionState.HELD else "starting"
            held = self.session_start_service.held(self.db, project, started)
        else:
            added = self._prose(project, session, item, operation)
            path = (
                f"{project_folder(project)}/{self.db.get_one(Document, added.id).path}"
            )
        hung: list[Attachment] = []
        for carrying in carried:
            if isinstance(carrying, Attachment):
                self.attach_service.hang(added, [carrying])
                hung.append(carrying)
            else:
                hung.extend(
                    self.attach_service.attach(
                        added,
                        session,
                        carrying.copies,
                        environment_id=carrying.environment_id,
                    )
                )
        kind = self.db.get_one(ItemKind, added.kind_code)
        line = EffectLine(
            ADDED, f"{kind.name} · {self._title(added)}", item_id=added.id
        )
        self.effect_service.record(
            brain.session_id,
            tool_use_id,
            line,
            [
                Change(EffectKind.ADDED, item_id=added.id),
                *(
                    Change(EffectKind.ATTACHED, attachment_id=attachment.id)
                    for attachment in hung
                ),
            ],
        )
        return Added(added, path, state, held, line)

    def attach_file(
        self,
        brain: Brain,
        source: str,
        to: uuid.UUID | None,
        tool_use_id: str | None,
    ) -> Attached:
        """Outside material at `source`, `<environment>:<path>`, a file or a
        folder, copied into the record now as one batch with its source and
        hung on the item `to` names (F86.7, F36.6), as the worker's copy is
        made, its caps included. The call `tool_use_id`'s effect is one line
        for its files, "Attached · <title>", or "Attached · <folder>, <n>
        files".

        Raises:
            RecordNotFoundException: `to` names no item of the brain's
                project, or the source's environment is not the controller's.
            InvalidOperationException: no `to`, which a draft's definition
                chat alone gives; a file cannot be copied, nothing attached.
            ExternalServiceException: the controller did not answer, or
                refused for a reason of its own.
        """
        operation = f"attach {source}"
        if to is None:
            raise InvalidOperationException(
                operation, "it names no item to hang on: give `to`"
            )
        item = self._item(brain, to)
        outside = self._outside(source, operation)
        self._project(brain)
        attachments = self.attach_service.attach(
            item,
            self.db.get_one(AgentSession, brain.session_id),
            outside.copies,
            environment_id=outside.environment_id,
        )
        line = EffectLine(
            ATTACHED, attached_label(outside.path, attachments), item_id=item.id
        )
        self.effect_service.record(
            brain.session_id,
            tool_use_id,
            line,
            [
                Change(EffectKind.ATTACHED, attachment_id=attachment.id)
                for attachment in attachments
            ],
        )
        return Attached(attachments, line)

    def answer(
        self,
        brain: Brain,
        block_id: str,
        value: str,
        person: str,
        *,
        note: str | None,
        to: str | None,
        tool_use_id: str | None,
    ) -> EffectLine:
        """The answer `value` of the person whose handle is `person` to the
        block `block_id`, `<item id>/<local id>`, recorded on their behalf
        through the chat, with `note` and, for `deferred`, `to` (F42.1, F86.2):
        the record's own answer, its undo included. The call `tool_use_id`'s
        effect is "Answered · <local id> · <title>".

        Raises:
            RecordNotFoundException: the block is not of the brain's project,
                or no person has the handle.
            InvalidOperationException: the record refuses the answer.
        """
        self._project(brain)
        item_id, local_id = _parts(block_id)
        item = self._item(brain, item_id)
        document = self.db.get(Document, item.id)
        if document is None:
            raise RecordNotFoundException("Block", block_id)
        self.record_service.answer(
            document,
            local_id,
            self._person(person),
            value,
            via=AnswerChannel.CHAT,
            note=note,
            to=to,
        )
        block = self.db.scalars(
            select(Block).where(
                Block.document_id == document.id, Block.local_id == local_id
            )
        ).one()
        line = EffectLine(
            ANSWERED,
            f"{local_id} · {self._title(item)}",
            item_id=item.id,
            block_id=f"{item.id}/{local_id}",
        )
        self.effect_service.record(
            brain.session_id,
            tool_use_id,
            line,
            [Change(EffectKind.ANSWERED, block_id=block.id)],
        )
        return line

    def mark(
        self,
        brain: Brain,
        item_id: uuid.UUID,
        mark: Mark,
        person: str | None,
        tool_use_id: str | None,
    ) -> EffectLine:
        """`mark` on the item for the person whose handle is `person` (F86.3):
        Done on a document, with its recommendations, Read on a notice,
        Reviewed on a review, as the record marks them. Without `person`,
        Pilot's own Done on a document it settled whole (DB decision 42). The
        call `tool_use_id`'s effect is "Marked <mark> · <title>".

        Raises:
            RecordNotFoundException: the item is not of the brain's project,
                or no person has the handle.
            InvalidOperationException: Read or Reviewed without a person, or
                the record refuses the mark.
        """
        self._project(brain)
        item = self._item(brain, item_id)
        if person is None:
            if mark != "done":
                raise InvalidOperationException(
                    f"mark item {item.id} {mark}",
                    "Pilot's own mark is Done, on a document it settled whole:"
                    " Read and Reviewed are a person's, named by `for`",
                )
            user = self._pilot()
        else:
            user = self._person(person)
        match mark:
            case "done":
                self.record_service.done(item, user)
            case "read":
                self.record_service.read(item, user)
            case "reviewed":
                self.record_service.reviewed(item, user)
        line = EffectLine(MARKED[mark], self._title(item), item_id=item.id)
        self.effect_service.record(
            brain.session_id,
            tool_use_id,
            line,
            [Change(EffectKind.MARKED, item_id=item.id)],
        )
        return line

    def stop_work(
        self, brain: Brain, item_id: uuid.UUID, tool_use_id: str | None
    ) -> EffectLine:
        """The work item's Session stopped by Pilot where it is, as a Stop
        stops it (F86.4, F67.1). The call `tool_use_id`'s effect is "Stopped ·
        <title>".

        Raises:
            RecordNotFoundException: the item is not of the brain's project.
            InvalidOperationException: it is no work item, or its Session is
                neither running, starting nor held.
        """
        self._project(brain)
        item = self._item(brain, item_id)
        if self.db.get(Work, item.id) is None:
            raise InvalidOperationException(
                f"stop {self._title(item)}", "it is no work item"
            )
        self.session_start_service.stop(self.db, item.id, self._pilot())
        line = EffectLine(STOPPED, self._title(item), item_id=item.id)
        self.effect_service.record(
            brain.session_id,
            tool_use_id,
            line,
            [Change(EffectKind.STOPPED, item_id=item.id)],
        )
        return line

    def finish(self, brain: Brain, tool_use_id: str | None) -> EffectLine:
        """The brain's project finished by Pilot as Finish finishes it (F86.5,
        F5.4), the call's effect, "Finished · <name>", written first: every
        Session of the project that runs, starts or is held is then stopped,
        the brain's own among them, whose turn the interrupt ends once this
        commits.

        Raises:
            InvalidOperationException: the project is a draft, finished or
                archived.
        """
        project = self._project(brain)
        line = EffectLine(FINISHED, project_name(project))
        self.effect_service.record(
            brain.session_id, tool_use_id, line, [Change(EffectKind.FINISHED)]
        )
        self.project_service.transition_as(
            self._pilot(), project.id, TransitionKind.FINISHED
        )
        return line

    def ask_writer(
        self, brain: Brain, document_id: uuid.UUID, block_id: str, question: str
    ) -> list[str]:
        """The pre-ruling pass's `question` to the writer of the registered
        document `document_id` about its unanswered block `block_id`,
        recorded as a Writer Question of the job's Turn in flight, once a
        block (F86.8; DB assertion 250), the document's line saying so and the
        question counted. No Effect: the call changes no ask.

        Returns:
            The local ids of the document's blocks its writer is asked about,
            in their order

        Raises:
            AuthorizationException: the brain is a chat's, or its turn has
                ended.
            RecordNotFoundException: the document is not of the brain's
                project, or has no such block.
            InvalidOperationException: the question is blank, the item is no
                registered document or is done, or the block is not of it, is
                answered or was asked about already.
        """
        operation = f"ask the writer about block {block_id}"
        if brain.kind_code != JOB:
            raise AuthorizationException(
                f"Cannot {operation} because session {brain.session_id} is a"
                f" {brain.kind_code} session: the pre-ruling pass, a job's, asks"
            )
        if not question.strip():
            raise InvalidOperationException(operation, "the question is blank")
        project = self._project(brain)
        item = self._item(brain, document_id)
        document = self.db.get(Document, item.id)
        if document is None or document.source_path is None:
            raise InvalidOperationException(
                operation, f"item {item.id} is no registered document"
            )
        item_id, local_id = _parts(block_id)
        if item_id != item.id:
            raise InvalidOperationException(
                operation, f"it is no block of document {item.id}"
            )
        self.document_service.lock(document)
        if item.done_at is not None:
            raise InvalidOperationException(operation, "the document is done")
        block = self.db.scalars(
            select(Block).where(
                Block.document_id == item.id, Block.local_id == local_id
            )
        ).one_or_none()
        if block is None:
            raise RecordNotFoundException("Block", f"{item.id}/{local_id}")
        if block.answer is not None or block.done_at is not None:
            raise InvalidOperationException(operation, f"block {local_id} is answered")
        if self.db.scalar(select(exists().where(WriterQuestion.block_id == block.id))):
            raise InvalidOperationException(
                operation, f"its writer was asked about block {local_id} already"
            )
        self.db.add(
            WriterQuestion(
                turn_id=self._turn_in_flight(brain),
                block_id=block.id,
                question=question,
            )
        )
        self.db.flush()
        PASS_QUESTIONS_TOTAL.labels(project=str(project.id)).inc()
        self.view_service.timeline_moved(project)
        return writer_asked(self.db, [item.id])[item.id]

    def _prose(
        self,
        project: Project,
        session: AgentSession,
        item: AddItemRequestSchema,
        operation: str,
    ) -> Item:
        text = dsl.with_facts(
            item.markdown or "",
            step=item.step,
            urgent=item.urgent,
            addressee=item.for_,
            summary=item.summary,
        )
        if item.title is not None:
            text = dsl.with_title(text, item.title)
        faults = self.ingest_service.born_faults(project, text)
        if faults:
            raise InvalidOperationException(
                operation, f"its text holds faults: {listed(faults)}"
            )
        title = item.title if item.title is not None else dsl.parse(text).title
        # A text the title rule passes has a title (F29.2).
        assert title is not None
        return self.document_service.bear_item(project, item.kind, title, session, text)

    def _work(self, project: Project, item: AddItemRequestSchema) -> Item:
        # The shape check let no work item through without these.
        assert item.title is not None
        assert item.repo is not None
        assert item.cwd is not None
        assert item.brief is not None
        task = None if item.step is None else self._task(project, item.step)
        work = self.session_start_service.start_work(
            self.db,
            project.id,
            item.repo,
            title=item.title,
            brief=self.brief_service.work_item(project, item.brief, task),
            cwd=item.cwd,
            plan_task_id=item.step,
            agent=item.agent,
            model=item.model,
            reasoning_effort=item.reasoning_effort,
        )
        return self.db.get_one(Item, work.id)

    def _task(self, project: Project, task_id: str) -> PlanTask:
        """The project's plan task `task_id`, not removed."""
        task = self.db.scalars(
            select(PlanTask).where(
                PlanTask.project_id == project.id,
                PlanTask.task_id == task_id,
                PlanTask.removed_at.is_(None),
            )
        ).one_or_none()
        if task is None:
            raise RecordNotFoundException("Plan task", f"{project.id}/{task_id}")
        return task

    def _attachment(self, brain: Brain, attachment_id: str) -> Attachment:
        attachment = self.db.get(Attachment, uuid.UUID(attachment_id))
        if attachment is None or attachment.project_id != brain.project_id:
            raise RecordNotFoundException("Attachment", attachment_id)
        return attachment

    def _outside(self, source: str, operation: str) -> _Outside:
        """The material at `source`, read through the controller from its
        environment, whose row is made on Pilot's first touch of it."""
        environment_id, path = source_parts(source)
        try:
            self.environment_service.ensure_environment(self.db, environment_id)
        except ControllerProblem as problem:
            if problem.problem_type is not ControllerProblemType.NOT_FOUND:
                raise
            raise RecordNotFoundException("Environment", environment_id) from problem
        return _Outside(
            environment_id,
            path,
            material(self.controller_client(), environment_id, path, operation),
        )

    def _project(self, brain: Brain) -> Project:
        """The brain's project, its row locked until the transaction ends."""
        return self.db.scalars(
            select(Project)
            .where(Project.id == brain.project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()

    def _item(self, brain: Brain, item_id: uuid.UUID) -> Item:
        item = self.db.get(Item, item_id)
        if item is None or item.project_id != brain.project_id:
            raise RecordNotFoundException("Item", str(item_id))
        return item

    def _person(self, handle: str) -> User:
        person = self.db.scalars(
            select(User).where(User.handle == handle, User.kind_code == UserKind.PERSON)
        ).one_or_none()
        if person is None:
            raise RecordNotFoundException("Person", handle)
        return person

    def _pilot(self) -> User:
        return self.db.scalars(
            select(User).where(User.kind_code == UserKind.AGENT)
        ).one()

    def _title(self, item: Item) -> str:
        """The item as its effect line names it: its title, else a registered
        document's file name, which its line shows (F35)."""
        if item.title is not None:
            return item.title
        document = self.db.get_one(Document, item.id)
        # Every item but a registered document is born titled (DB decision 50).
        assert document.source_path is not None
        return PurePosixPath(document.source_path).name

    def _turn_in_flight(self, brain: Brain) -> int:
        """The brain's Turn in flight; the gate's refusal once it has ended."""
        turn_id = self.db.scalar(
            select(Turn.id)
            .where(Turn.session_id == brain.session_id, Turn.ended_at.is_(None))
            .order_by(Turn.seq.desc())
            .limit(1)
        )
        if turn_id is None:
            raise AuthorizationException(_no_turn(brain.session_id))
        return turn_id


def _shape_refusal(kind: str, given: set[str]) -> str | None:
    """Why `add_item` refuses an item of `kind` given the fields `given`, by
    their names on the wire; None for one it takes."""
    if kind in WAITS:
        return "Pilot takes no waits yet"
    alien: Sequence[str]
    if kind == WORK:
        alien, missing = PROSE_FIELDS, [f for f in NEEDED_FOR_WORK if f not in given]
    else:
        alien, missing = WORK_FIELDS, []
        if "title" not in given and "markdown" not in given:
            return "it has no title: give `title`, or `markdown` that gives one"
    taken = [field for field in alien if field in given]
    if taken:
        return f"a {kind} item takes no {_fields(taken)}"
    if missing:
        return f"a work item needs {_fields(missing)}"
    return None


def _fields(names: Sequence[str]) -> str:
    return ", ".join(f"`{name}`" for name in names)


def _is_id(ref: str) -> bool:
    """Whether an attachment `add_item` names is one already made, by its id,
    rather than a source."""
    try:
        uuid.UUID(ref)
    except ValueError:
        return False
    return True


def _parts(block_id: str) -> tuple[uuid.UUID, str]:
    """A block's id, `<item id>/<local id>` (TD §4.9), as its two parts."""
    item, _, local = block_id.partition("/")
    return uuid.UUID(item), local


def _no_turn(session_id: uuid.UUID) -> str:
    return f"Cannot call pilot-store because session {session_id} has no turn running"
