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
Session.
"""

import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath

from prometheus_client import Counter
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.engine.documents import DocumentService
from app.engine.record import RecordService
from app.engine.views import ViewService
from app.exceptions import (
    AuthorizationException,
    InvalidOperationException,
    RecordNotFoundException,
)
from app.models import Block, Document, Item, Project, Turn, User, Work, WriterQuestion
from app.models.reference import (
    AnswerChannel,
    EffectKind,
    SessionState,
    Surface,
    TransitionKind,
    UserKind,
)
from app.schemas.pilot_store import Mark
from app.services.effect_service import Change, EffectLine, EffectService
from app.services.pilot_server import bearer_session
from app.services.project_service import ProjectService, project_name
from app.services.session_start_service import SessionStartService
from app.services.timeline_service import writer_asked

JOB = "job"
"""The Session Kind of the server's jobs, the pre-ruling pass among them."""

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
    ) -> None:
        self.db = db
        self.record_service = record_service
        self.document_service = document_service
        self.view_service = view_service
        self.project_service = project_service
        self.session_start_service = session_start_service
        self.effect_service = effect_service

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


def _parts(block_id: str) -> tuple[uuid.UUID, str]:
    """A block's id, `<item id>/<local id>` (TD §4.9), as its two parts."""
    item, _, local = block_id.partition("/")
    return uuid.UUID(item), local


def _no_turn(session_id: uuid.UUID) -> str:
    return f"Cannot call pilot-store because session {session_id} has no turn running"
