"""The record's own writes (design 1 §6.4, F32.4): a person's answer, Done on
an action, undo, Done on a document, Read and Reviewed; Finish's close of the
open items (F5.1); and a work item's place and its done at its turn's end
(DB Work, decision 44).

Each is a write of the caller's transaction, under the document's row lock
(TD §8.5); a work item's, which has no document, under its project's row or
its item's. A write that touches the text splices it into the published text
and publishes it, whether or not the path's latest save is held: the tree
keeps the agent's ingest then, and the next clean save's merge carries the
write to the file (design 1 §5.2, §7). No write raises *modified*.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, and_, exists, select
from sqlalchemy.orm import Session

from app.engine import dsl
from app.engine.documents import DOCUMENT, OPENING, PROSE, DocumentService
from app.engine.paths import tree_path
from app.engine.views import ViewService
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import (
    Document,
    DoneCause,
    Item,
    ItemKind,
    PlanTask,
    Project,
    User,
    Work,
)
from app.models import Session as AgentSession
from app.models.reference import AnswerChannel, ProjectState, UserKind, VersionCause

NOTICE = "notice"
REVIEW = "review"
WORK = "work"

ANSWERED = "answered"
MARKED = "marked"
SETTLED = "settled"
TURN_ENDED = "turn_ended"
FINISHED = "finished"


class RecordService:
    def __init__(
        self,
        db: Session,
        document_service: DocumentService,
        view_service: ViewService,
    ) -> None:
        self.db = db
        self.document_service = document_service
        self.view_service = view_service

    def answer(
        self,
        document: Document,
        local_id: str,
        user: User,
        answer: str,
        *,
        via: AnswerChannel = AnswerChannel.APP,
        note: str | None = None,
        to: str | None = None,
    ) -> None:
        """`user`'s answer to block `local_id`, through `via`, with `note`:
        an option's label, `Agree`, `Yes` or `No`, or free words; `deferred`
        with `to`, a task in the plan or `plan` (decision 47). It replaces the
        block's answer, Pilot's included, while the item is not done (F32.2);
        the answer to a one-ask item is its done (DB 163)."""
        project, item = self._locked(document)
        operation = f"answer block {local_id} of {tree_path(project, document.path)}"
        _a_person(user, operation, "Pilot answers in the file, `by: agent`")
        _not_done(item, operation)
        answer_text, note, to = _value(answer), _value(note), _value(to)
        if answer_text is None:
            raise InvalidOperationException(operation, "the answer is blank")
        if answer_text == dsl.DEFERRED and to is None:
            raise InvalidOperationException(operation, "`deferred` names no `to`")
        if to is not None and answer_text != dsl.DEFERRED:
            raise InvalidOperationException(
                operation, "`to` goes with `deferred` alone"
            )
        if to is not None and to != dsl.PLAN and not self._in_the_plan(project, to):
            raise InvalidOperationException(
                operation, f"`to: {to}` names neither `plan` nor a task in the plan"
            )
        blocks = _blocks(item, document)
        block = _block(document, blocks, local_id)
        if (
            block.kind is dsl.BlockKind.ACTION
            and not block.options
            and answer_text != dsl.DEFERRED
        ):
            raise InvalidOperationException(
                operation, "an action without options is done, not answered"
            )
        at = _now()
        self.document_service.publish(
            document,
            dsl.write_answer(
                _published(document),
                local_id,
                answer=answer_text,
                by=user.handle,
                at=at,
                via=dsl.AnswerChannel(via.value),
                note=note,
                to=to,
            ),
        )
        self._done_by_its_answer(project, item, blocks, user, at)

    def done_action(
        self,
        document: Document,
        local_id: str,
        user: User,
        *,
        note: str | None = None,
    ) -> None:
        """Done on action `local_id`: `done` and `by`, with `note`, what
        `user` pasted back (FM §4). An action with options is answered with
        one of them instead. Done on a one-ask item's action is its done (DB
        163)."""
        project, item = self._locked(document)
        operation = (
            f"mark action {local_id} of {tree_path(project, document.path)} done"
        )
        _a_person(user, operation, "Pilot settles an action in the file")
        _not_done(item, operation)
        blocks = _blocks(item, document)
        block = _block(document, blocks, local_id)
        if block.kind is not dsl.BlockKind.ACTION:
            raise InvalidOperationException(
                operation, f"block {local_id} is a {block.kind}, not an action"
            )
        if block.options:
            raise InvalidOperationException(
                operation, "an action with options is answered with one of them"
            )
        at = _now()
        self.document_service.publish(
            document,
            dsl.write_done(
                _published(document), local_id, by=user.handle, at=at, note=_value(note)
            ),
        )
        self._done_by_its_answer(project, item, blocks, user, at)

    def undo(self, item: Item) -> None:
        """Undo of a done prose item while no session has consumed it, its
        Done Cause offers it (DB 164, F14.1) and its project is not finished
        (D028): its done cleared, and on a one-ask item its block's answer
        with it, an answer of Pilot's it replaced not restored (decision 6).

        The project's row is held shared before the document's, so that
        Finish and Reopen, which change the project's state under its row
        lock, never interleave with an Undo.
        """
        operation = f"undo item {item.id}"
        if self.db.get_one(ItemKind, item.kind_code).form != PROSE:
            raise InvalidOperationException(
                operation, f"a {item.kind_code} item offers no undo"
            )
        self.db.scalars(
            select(Project.id)
            .where(Project.id == item.project_id)
            .with_for_update(read=True)
        ).one()
        document = self.db.get_one(Document, item.id)
        project, _ = self._locked(document)
        refusal = self._undo_refusal(item)
        if refusal is not None:
            raise InvalidOperationException(operation, refusal)
        if item.done_cause_code == ANSWERED:
            # The one answer a person gave the one-ask item: a done item takes
            # no other.
            block = next(
                block
                for block in dsl.parse(_published(document)).blocks
                if block.by is not None and block.by != dsl.AGENT
            )
            self.document_service.publish(
                document, dsl.clear_answer(_published(document), block.local_id)
            )
        item.done_at = None
        item.done_cause_code = None
        item.done_by_user_id = None
        self.view_service.timeline_moved(project)

    def offers_undo(self, item: Item) -> bool:
        """Whether `undo` takes the item now, as it stands."""
        return (
            self.db.get_one(ItemKind, item.kind_code).form == PROSE
            and self._undo_refusal(item) is None
        )

    def done(self, item: Item, user: User) -> None:
        """Done on a document (F32.5): first every unanswered block that has a
        recommendation answered with it, `user`'s, `via: recommended`; then
        a `done` Document Version of the published text and the item's mark.
        Refused while a block has neither. Pilot's Done is on a document it
        settled whole, every block answered (decision 42)."""
        if self.db.get_one(ItemKind, item.kind_code).form != PROSE:
            raise InvalidOperationException(
                f"mark item {item.id} done",
                f"a {item.kind_code} item is not done by Done",
            )
        document = self.db.get_one(Document, item.id)
        project, _ = self._locked(document)
        operation = f"mark {tree_path(project, document.path)} done"
        if item.kind_code != DOCUMENT:
            raise InvalidOperationException(
                operation, f"a {item.kind_code} item is not done by Done"
            )
        _not_done(item, operation)
        blocks = dsl.parse(_published(document)).blocks
        if user.kind_code is UserKind.AGENT:
            cause = SETTLED
            unready = [block for block in blocks if not block.answered]
            problem = (
                "Pilot marks done only a document it settled whole, and these"
                " blocks are unanswered"
            )
        else:
            cause = MARKED
            unready = [
                block
                for block in blocks
                if not block.answered and dsl.recommendation(block) is None
            ]
            problem = "these blocks have neither an answer nor a recommendation"
        if unready:
            ids = ", ".join(block.local_id for block in unready)
            raise InvalidOperationException(operation, f"{problem}: {ids}")
        at = _now()
        if cause == MARKED:
            text = dsl.write_recommended(_published(document), by=user.handle, at=at)
            if text != document.published_text:
                self.document_service.publish(document, text)
        self.document_service.cut_version(document, VersionCause.DONE)
        self._mark(project, item, cause, user, at)

    def read(self, item: Item, user: User) -> None:
        """Read on a notice: the item's mark, the text untouched."""
        self._mark_by_kind(item, user, NOTICE, "Read")

    def reviewed(self, item: Item, user: User) -> None:
        """Reviewed on a review: the item's mark, the text untouched."""
        self._mark_by_kind(item, user, REVIEW, "Reviewed")

    def close_unanswered(self, project: Project, user: User, at: datetime) -> None:
        """Finish's close (F5.1): every open item of the project but the
        opening, which is never done, done unanswered at `at` by `user`, its
        Done Cause `finished`, which offers no undo. The text is untouched.

        Each prose item's document row is held first, so a write of one
        document waits for the close or the close finds its item done.
        """
        self.db.scalars(
            select(Document.id)
            .join(Item, Item.id == Document.id)
            .where(_open_in(project))
            .order_by(Document.id)
            .with_for_update(of=Document)
        ).all()
        items = self.db.scalars(
            select(Item)
            .where(_open_in(project))
            .order_by(Item.seq)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
        for item in items:
            item.done_at = at
            item.done_cause_code = FINISHED
            item.done_by_user_id = user.id
        if items:
            self.view_service.timeline_moved(project)

    def place_work(
        self,
        project: Project,
        session: AgentSession,
        title: str,
        plan_task_id: str | None = None,
        *,
        repo: str | None = None,
    ) -> Work:
        """A work item of `session`, one identity with it (DB Work, decision
        3): its Item of kind `work` at the project's next place on the
        timeline, on the plan's task `plan_task_id` when given, created by its
        own Session, and its Work under the switch's setting as it stands
        (F54.7), placed by the repository `repo` its environment is made from
        (F61.1), none for a job.

        Raises:
            RecordNotFoundException: the project's plan has no task
                `plan_task_id`.
        """
        if plan_task_id is not None and not self._in_the_plan(project, plan_task_id):
            raise RecordNotFoundException("Plan task", f"{project.id}/{plan_task_id}")
        self.db.add(
            Item(
                id=session.id,
                project_id=project.id,
                seq=self.document_service.next_seq(project),
                kind_code=WORK,
                title=title,
                plan_task_id=plan_task_id,
                created_by_session_id=session.id,
            )
        )
        self.db.flush()
        work = Work(
            id=session.id,
            project_id=project.id,
            session_kind_code=session.kind_code,
            repo=repo,
            autopilot=project.autopilot,
        )
        self.db.add(work)
        self.db.flush()
        self.view_service.timeline_moved(project)
        return work

    def work_done(self, work_id: uuid.UUID, at: datetime) -> None:
        """The work item done at `at`, its turn's end, by no one, its Done
        Cause `turn_ended`, which is final (decision 44). An item Finish
        closed first stays as Finish closed it."""
        item = self.db.get_one(
            Item, work_id, with_for_update=True, populate_existing=True
        )
        if item.done_at is not None:
            return
        item.done_at = at
        item.done_cause_code = TURN_ENDED
        self.view_service.timeline_moved(self.db.get_one(Project, item.project_id))

    def _mark_by_kind(self, item: Item, user: User, kind: str, mark: str) -> None:
        if self.db.get_one(ItemKind, item.kind_code).form != PROSE:
            raise InvalidOperationException(
                f"mark item {item.id} {mark}",
                f"a {item.kind_code} item is not marked {mark}",
            )
        document = self.db.get_one(Document, item.id)
        project, _ = self._locked(document)
        operation = f"mark {tree_path(project, document.path)} {mark}"
        _a_person(user, operation, "Pilot marks done only a document it settled whole")
        if item.kind_code != kind:
            raise InvalidOperationException(
                operation, f"a {item.kind_code} item is not marked {mark}"
            )
        _not_done(item, operation)
        self._mark(project, item, MARKED, user, _now())

    def _undo_refusal(self, item: Item) -> str | None:
        """Why a prose item takes no undo now, or none."""
        if item.done_at is None:
            return "the item is not done"
        if item.consumed_at is not None:
            return "a session has taken the item's answers"
        if not self.db.get_one(DoneCause, item.done_cause_code).undo_offered:
            return f"an item done as {item.done_cause_code} offers no undo"
        project = self.db.get_one(Project, item.project_id)
        if project.state_code is ProjectState.FINISHED:
            return "the project is finished"
        return None

    def _locked(self, document: Document) -> tuple[Project, Item | None]:
        self.document_service.lock(document)
        return self.document_service.owner(document)

    def _in_the_plan(self, project: Project, task_id: str) -> bool:
        return bool(
            self.db.scalar(
                select(
                    exists().where(
                        PlanTask.project_id == project.id,
                        PlanTask.task_id == task_id,
                        PlanTask.removed_at.is_(None),
                    )
                )
            )
        )

    def _done_by_its_answer(
        self,
        project: Project,
        item: Item | None,
        blocks: tuple[dsl.Block, ...],
        user: User,
        at: datetime,
    ) -> None:
        """A one-ask item, done when its one block is answered (F32.3)."""
        if item is not None and len(blocks) == 1:
            self._mark(project, item, ANSWERED, user, at)

    def _mark(
        self, project: Project, item: Item, cause: str, user: User, at: datetime
    ) -> None:
        item.done_at = at
        item.done_cause_code = cause
        item.done_by_user_id = user.id
        self.view_service.timeline_moved(project)


def _open_in(project: Project) -> ColumnElement[bool]:
    """The project's open items but the opening."""
    return and_(
        Item.project_id == project.id,
        Item.done_at.is_(None),
        Item.kind_code != OPENING,
    )


def _a_person(user: User, operation: str, cause: str) -> None:
    if user.kind_code is UserKind.AGENT:
        raise InvalidOperationException(operation, cause)


def _not_done(item: Item | None, operation: str) -> None:
    """Done fixes an item's answers (F15, F24.3)."""
    if item is not None and item.done_at is not None:
        raise InvalidOperationException(operation, "the item is done")


def _blocks(item: Item | None, document: Document) -> tuple[dsl.Block, ...]:
    """The published text's blocks; none in the opening, whose text the
    record never reads (DB decision 2)."""
    if item is not None and item.kind_code == OPENING:
        return ()
    return dsl.parse(_published(document)).blocks


def _block(
    document: Document, blocks: tuple[dsl.Block, ...], local_id: str
) -> dsl.Block:
    block = next((block for block in blocks if block.local_id == local_id), None)
    if block is None:
        raise RecordNotFoundException("Block", f"{document.id}/{local_id}")
    return block


def _published(document: Document) -> str:
    # Every document is born published.
    assert document.published_text is not None
    return document.published_text


def _value(text: str | None) -> str | None:
    """A value as the file reads it back: trimmed, an empty one absent."""
    if text is None:
        return None
    return text.strip() or None


def _now() -> datetime:
    """Now, to the second: the text holds its times to the second, and an
    item done by its answer is done at the answer's time (DB 163)."""
    return datetime.now(UTC).replace(microsecond=0)
