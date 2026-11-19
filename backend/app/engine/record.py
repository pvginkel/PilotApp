"""The record's own writes (design 1 §6.4, F32.4): a person's answer, Done on
an action, undo, Done on a document, Read and Reviewed; Finish's close of the
open items (F5.1); Archive's and Reopen's close of the archive question (DB
265); the switch's Yes to the confirmations it answers (F4.2);
a work item's place and its done at its turn's end (DB Work, decision 44);
the debrief's notice a work item's done places (DB decision 82); the claimed
actions a work item is named for at its `add_item`, of a registered document
or an item of Pilot's own (DB decision 64, widened by D224); an item of
Pilot's own done at the save that writes its last open block's `done` (DB
163); a person's fold of an open item and their unfold (DB decision 75);
the chat's cancel of an ask Pilot added, on a person's word (DB 297); a
stopped work item's close for good, a person's or Pilot's (DB decision 78);
and a member's taking of the offer of Pilot's note, which places Pilot's job
(DB 629).

Each is a write of the caller's transaction, under the document's row lock
(TD §8.5), a close and an Undo under its project's row first, and refused
while the project is archived (D012); a work item's, which has no document,
under its project's row or its item's. A
write that touches the text splices it into the published text and publishes
it, whether or not the path's latest save is held: the tree keeps the agent's
ingest then, and the next clean save's merge carries the write to the file
(design 1 §5.2, §7). No write raises *modified*. A close of a registered
document owes its text to the file it was registered from, written back once
the transaction commits (F65.1). The close that leaves no document of a work
item's ended run open continues its conversation in the same transaction
(decision 44, review 1): the session start places the continuation, and every
document of the run is consumed by it, its Undo gone. A person's close of an
item of Pilot's own places the job after it in the same transaction (F59; DB
decision 45), whose brief consumes the item, and an Undo before that brief
withdraws the job (`Jobs`). One the chat records on their behalf, whose own
turn carries the ruling out, places none and is consumed on the spot by the
chat's Session; an item of Pilot's own that a save closes, writing its last
open block's `done`, by the Session the save is credited to. Neither offers
an Undo after it (D225, D226), as after a brief; a notice's Read keeps its Undo.
"""

import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol

import pilot_dsl as dsl
from sqlalchemy import ColumnElement, Select, and_, exists, select
from sqlalchemy.orm import Session

from app.engine.bus import EngineBus, ProjectChanged, WriteBackOwed
from app.engine.documents import (
    ARCHIVE,
    ARCHIVE_BLOCK,
    ARCHIVE_QUESTION,
    CONFIRMATION,
    DOCUMENT,
    KEEP,
    OPENING,
    PROSE,
    REVIEW,
    DocumentService,
    awaits_read,
)
from app.engine.paths import tree_path
from app.engine.pilot_notes import differs, standing_notes
from app.engine.references import References
from app.engine.views import ViewService
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import (
    Block,
    ClaimAssignment,
    ConfirmationReason,
    Document,
    Item,
    PilotNote,
    PlanTask,
    Project,
    ResearchAssignment,
    SessionKind,
    User,
    Work,
)
from app.models import Session as AgentSession
from app.models.reference import (
    AnswerChannel,
    ProjectState,
    Surface,
    UserKind,
    VersionCause,
    WorkTrigger,
)

NOTICE = "notice"
WORK = "work"

DEBRIEF_NOTICE = "debrief_notice"
"""A Debrief Notice's kind, and its form (DB decision 82)."""

DEBRIEF_TITLE = "Debrief · {subject}"
"""A Debrief Notice's title, by its completing Work's subject, else by that
Work's title (DB 611)."""

WORKERS_RUN = "work"
"""The Session Kind of a worker's run, as its Work carries it."""

ANSWERED = "answered"
MARKED = "marked"
SETTLED = "settled"
TURN_ENDED = "turn_ended"
FINISHED = "finished"
CANCELLED = "cancelled"
WITHDRAWN = "withdrawn"

ENDS_RUN = (FINISHED, CANCELLED)
"""The Done Causes of a registered document's close that ends its run: no
continuation follows it and it owes no write-back (D049; DB 299)."""

ASKS = ("decision", CONFIRMATION, "question", "action", DOCUMENT)
"""The kinds of an ask Pilot added that the chat calls off (DB 297)."""

REGISTERED_CANCEL = (
    "a document a work item's run registered is called off by the Cancel on its"
    " page, which ends that run"
)
"""Why the chat's cancel takes no registered document (DB 297)."""

CLOSED_FOR_GOOD = "it is closed for good"
"""Why a work item closed for good takes no Resume and no second close (DB
347)."""

YES = "Yes"

WRITTEN_BACK = (
    "Your documents were answered and written back in place: {paths}."
    " Read the answers and continue."
)
"""The continuation's message naming the run's documents written back, verbatim
(the rulings)."""

UNREAD = "Could not be read: {paths}."
"""Its line naming the run's documents whose turn-end read failed (ruling D1)."""

ARCHIVED = "its project is archived"
"""Why an archived project's item takes no close and no Undo (D012), as the
start of its work is refused."""


class Continuations(Protocol):
    """Places a work item's continuation through the gate: the session start."""

    def continue_run(
        self,
        db: Session,
        project: Project,
        run_id: uuid.UUID,
        released: Item,
        message: str,
    ) -> AgentSession:
        """The conversation of the work item `run_id` continued as a new work
        item, its trigger the Item `released`, its first Turn `message`, in
        the caller's transaction, which holds the project's row."""
        ...


class Jobs(Protocol):
    """Places the job after a person's close of an item of Pilot's own, and
    withdraws it on the item's Undo before its brief, and the job a member's
    press of a Pilot Note's offer places: the job service."""

    def item_done(self, project: Project, item: Item) -> Work:
        """The job after the close of `item`, placed in the caller's
        transaction, which holds the project's row exclusively."""
        ...

    def offer_taken(self, project: Project, note: PilotNote) -> Work:
        """The job the taking of `note`'s offer places, in the caller's
        transaction, which holds the project's row exclusively."""
        ...

    def unbriefed(self, item: Item) -> AgentSession | None:
        """The job a close of `item` placed that is held before its brief,
        its Session locked until the transaction ends; None when there is
        none."""
        ...

    def withdraw(self, job: AgentSession, at: datetime) -> None:
        """The job `job`, locked and held before its brief, withdrawn at
        `at`: it never starts."""
        ...


class RecordService:
    def __init__(
        self,
        db: Session,
        engine_bus: EngineBus,
        document_service: DocumentService,
        view_service: ViewService,
        continuations: Callable[[], Continuations],
        jobs: Callable[[], Jobs],
        references: References,
    ) -> None:
        self.db = db
        self.engine_bus = engine_bus
        self.document_service = document_service
        self.view_service = view_service
        self.continuations = continuations
        self.jobs = jobs
        self.references = references

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
        session_id: uuid.UUID | None = None,
    ) -> None:
        """`user`'s answer to block `local_id`, through `via`, with `note`:
        an option's label, `Agree`, `Yes` or `No`, or free words; `deferred`
        with `to`, a task in the plan or `plan` (decision 47). It replaces the
        block's answer, Pilot's included, while the item is not done (F32.2);
        the answer to a one-ask item is its done (DB 163). An archive question
        takes Archive or Keep alone (DB 263). An answer through the app that
        a done item holds from `user` already (`answered_so`) is taken as done
        and changes nothing, ahead of every refusal; the chat's is refused as
        any answer to a done item, since its tool call would show as an
        answer given. The chat's is made in the brain's Session `session_id`,
        which takes an item of Pilot's own the answer closes (`_mark`)."""
        project, item = self._closing(document)
        if via is AnswerChannel.APP and self.answered_so(
            document, local_id, user, answer, note=note, to=to
        ):
            return
        operation = f"answer block {local_id} of {tree_path(project, document.path)}"
        _not_archived(project, operation)
        _not_awaiting_read(item, document, operation)
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
        if to is not None and to != dsl.PLAN and not self.in_the_plan(project, to):
            raise InvalidOperationException(
                operation, f"`to: {to}` names neither `plan` nor a task in the plan"
            )
        if (
            item is not None
            and item.kind_code == ARCHIVE_QUESTION
            and answer_text not in (ARCHIVE, KEEP)
        ):
            raise InvalidOperationException(
                operation, f"an archive question is answered {ARCHIVE} or {KEEP}"
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
        with _refusal_as_invalid():
            text = dsl.write_answer(
                _published(document),
                local_id,
                answer=answer_text,
                by=user.handle,
                at=at,
                via=dsl.AnswerChannel(via.value),
                note=note,
                to=to,
            )
        self.document_service.publish(document, text)
        self._done_by_its_answer(
            project, item, document, blocks, user, at, via=via, session_id=session_id
        )

    def answered_so(
        self,
        document: Document,
        local_id: str,
        user: User,
        answer: str,
        *,
        note: str | None = None,
        to: str | None = None,
    ) -> bool:
        """Whether `answer`, with `note` and `to`, is the answer block
        `local_id` of a done item holds from `user`: a request that reaches
        the record a second time."""
        _, item = self.document_service.owner(document)
        held = _closed_by(item, document, local_id, user)
        return (
            held is not None
            and held.answer is not None
            and (held.answer, held.note, held.to)
            == (_value(answer), _value(note), _value(to))
        )

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
        163). A Done a done item's action holds from `user` already, with the
        same `note`, is taken as done and changes nothing, ahead of every
        refusal."""
        project, item = self._closing(document)
        held = _closed_by(item, document, local_id, user)
        if held is not None and held.done is not None and held.note == _value(note):
            return
        operation = (
            f"mark action {local_id} of {tree_path(project, document.path)} done"
        )
        _not_archived(project, operation)
        _not_awaiting_read(item, document, operation)
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
        with _refusal_as_invalid():
            text = dsl.write_done(
                _published(document), local_id, by=user.handle, at=at, note=_value(note)
            )
        self.document_service.publish(document, text)
        self._done_by_its_answer(
            project,
            item,
            document,
            blocks,
            user,
            at,
            via=AnswerChannel.APP,
            session_id=None,
        )

    def take_offer(
        self, document: Document, local_id: str, note_id: int, user: User
    ) -> Work:
        """`user`'s press of the offer of the Pilot Note `note_id` on action
        `local_id` (F168.7; DB 629): who took it and when, set once, while
        the note stands with an offer, the action has no `done` and its item
        is open; and at that instant the job of Pilot's it places, which names
        the note (`Jobs.offer_taken`; DB 630). The document's text, the
        action's answer and Done, and what is held are untouched: the action
        stays the person's (DB 632). The project's row is held exclusively
        first, as an item's close holds it, since the press places work.

        Raises:
            RecordNotFoundException: the document has no such block, or no
                Pilot Note of the id is on it.
            InvalidOperationException: the project is archived; the item is
                done; the note's offer was taken already, or it was replaced
                or taken off, or offers no work; or the action is done.
        """
        project, item = self._closing(document)
        operation = (
            f"take the offer on {local_id} of {tree_path(project, document.path)}"
        )
        block = self.db.scalars(
            select(Block)
            .where(Block.document_id == document.id, Block.local_id == local_id)
            .execution_options(populate_existing=True)
        ).one_or_none()
        note = self.db.get(PilotNote, note_id, populate_existing=True)
        if block is None or note is None or note.block_id != block.id:
            raise RecordNotFoundException(
                "Pilot Note", f"{document.id}/{local_id}/{note_id}"
            )
        _not_archived(project, operation)
        _not_done(item, operation)
        refusal = self._offer_refusal(note, local_id)
        if refusal is None and block.done_at is not None:
            refusal = f"action {local_id} is done"
        if refusal is not None:
            raise InvalidOperationException(operation, refusal)
        note.offer_taken_at = datetime.now(UTC)
        note.offer_taken_by_user_id = user.id
        self.db.flush()
        self.view_service.timeline_moved(project)
        return self.jobs().offer_taken(project, note)

    def _offer_refusal(self, note: PilotNote, local_id: str) -> str | None:
        """Why the offer of `note`, on block `local_id`, takes no press: taken
        once already, the note no longer standing (DB 625), or no offer in it;
        None while it takes one."""
        if note.offer_taken_at is not None:
            return f"the offer on {local_id} was taken already"
        if self.db.scalar(
            select(
                exists().where(
                    PilotNote.item_id == note.item_id,
                    PilotNote.block_id == note.block_id,
                    PilotNote.id > note.id,
                )
            )
        ):
            return f"Pilot's note on {local_id} was replaced"
        if note.withdrawn_at is not None:
            return f"Pilot's note on {local_id} was taken off"
        if note.offer is None:
            return f"Pilot's note on {local_id} offers no work"
        return None

    def undo(self, item: Item) -> None:
        """Undo of a done prose item but an archive question (DB 265), or of a
        debrief's notice (`_undo_read`; DB 613), while no session has consumed
        it, its Done Cause offers it (DB 164, F14.1) and its project is
        neither finished (D028) nor archived (D012): its done cleared, and on
        a one-ask item its block's answer with it, an answer of Pilot's it
        replaced not restored (decision 6); a registered document's
        write-back of that close with it, so that its next close writes it
        again (F65.1); and the job its close placed, held before its brief,
        withdrawn, its work item done `withdrawn`, so that its next close
        places another.

        The project's row is held shared before the document's, so that
        Finish and Reopen, which change the project's state under its row
        lock, never interleave with an Undo. The job's Session is locked
        before the item is read, so that the brief, which consumes the item
        under that lock, and the Undo never both take effect.
        """
        operation = f"undo item {item.id}"
        form = self.references.form(self.db, item.kind_code)
        if form not in (PROSE, DEBRIEF_NOTICE):
            raise InvalidOperationException(
                operation, f"a {item.kind_code} item offers no undo"
            )
        self.db.scalars(
            select(Project.id)
            .where(Project.id == item.project_id)
            .with_for_update(read=True)
        ).one()
        if form == DEBRIEF_NOTICE:
            self._undo_read(item, operation)
            return
        document = self.db.get_one(Document, item.id)
        project, _ = self._locked(document)
        job = self.jobs().unbriefed(item)
        self.db.refresh(item)
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
            with _refusal_as_invalid():
                text = dsl.clear_answer(_published(document), block.local_id)
            self.document_service.publish(document, text)
        item.done_at = None
        item.done_cause_code = None
        item.done_by_user_id = None
        document.written_back_at = None
        document.write_back_refused_at = None
        if job is not None:
            self.jobs().withdraw(job, _now())
        self.view_service.timeline_moved(project)

    def _undo_read(self, item: Item, operation: str) -> None:
        """Undo of a debrief's notice's Read, under its project's row held
        shared (`undo`): the same notice open again (DB 607). It has no
        Document, so its own row is held where a document's would be, and no
        job followed its Read, so none is withdrawn."""
        item = self.db.get_one(
            Item, item.id, with_for_update=True, populate_existing=True
        )
        refusal = self._undo_refusal(item)
        if refusal is not None:
            raise InvalidOperationException(operation, refusal)
        item.done_at = None
        item.done_cause_code = None
        item.done_by_user_id = None
        self.view_service.timeline_moved(self.db.get_one(Project, item.project_id))

    def fold(self, project: Project, item: Item, folded: bool) -> None:
        """A person's fold of `item`, or, `folded` false, their unfold (F12.3;
        DB 316, 317), in the caller's transaction, which holds the project's
        row: taken on an open item the timeline draws as a box of its own, a
        prose item but the opening, a work item's run or the setup's job
        while not retried, and a wait. Whether the item is Pilot's is the
        caller's to refuse. One that stands so already is taken and changes
        nothing. The item's row is held and read again, so that a close
        committed before it refuses the fold; one committed after it clears
        the fold (`Item.done_at`). The store's tree holds no fold, so the
        project's screens alone are told (DB 321).

        Raises:
            InvalidOperationException: the project is archived, the item is
                done, or the timeline draws no box of its own for it.
        """
        operation = f"{'fold' if folded else 'unfold'} item {item.id}"
        _not_archived(project, operation)
        item = self.db.get_one(
            Item, item.id, with_for_update=True, populate_existing=True
        )
        _not_done(item, operation)
        boxless = self._boxless(item)
        if boxless is not None:
            raise InvalidOperationException(operation, boxless)
        if item.folded == folded:
            return
        item.folded = folded
        self.db.flush()
        self.engine_bus.emit(ProjectChanged(project.id))

    def _boxless(self, item: Item) -> str | None:
        """Why the timeline draws no box of its own for the open `item`, none
        where it draws one (DB 317): the opening is its prompt, a retried job
        its line (D078), and every job but the setup's shows on the item it
        follows from (F59.1)."""
        if item.kind_code == OPENING:
            return "the opening does not fold"
        if item.kind_code != WORK:
            return None
        work = self.db.get_one(Work, item.id)
        if work.retried_by_id is not None:
            return "a retried job is a line"
        if (
            work.session_kind_code != WORK
            and work.trigger_code is not WorkTrigger.SETUP
        ):
            return "a job shows on the item it follows from"
        return None

    def retry_write_backs(self, continuation_id: uuid.UUID) -> None:
        """A Resume of the continuation `continuation_id`, in the caller's
        transaction: each document it carries whose write-back the controller
        refused owes it again, under the document's row lock, so that its
        start writes it before it sends (F125)."""
        refused = self.db.execute(
            select(Document, Item.created_by_session_id)
            .join(Item, Item.id == Document.id)
            .where(
                Item.consumed_session_id == continuation_id,
                Document.write_back_refused_at.is_not(None),
            )
            .order_by(Document.id)
            .with_for_update(of=Document)
            .execution_options(populate_existing=True)
        ).all()
        for document, run_id in refused:
            # A registered document is its Session's.
            assert run_id is not None
            document.write_back_refused_at = None
            self.engine_bus.emit(WriteBackOwed(run_id))
        self.db.flush()

    def offers_undo(self, item: Item) -> bool:
        """Whether `undo` takes the item now, as it stands."""
        return (
            self.references.form(self.db, item.kind_code) in (PROSE, DEBRIEF_NOTICE)
            and self._undo_refusal(item) is None
        )

    def done(
        self,
        item: Item,
        user: User,
        *,
        via: AnswerChannel = AnswerChannel.APP,
        session_id: uuid.UUID | None = None,
    ) -> None:
        """Done on a document (F32.5), given through `via`, the chat's in the
        brain's Session `session_id` (`answer`): first every
        unanswered block that has a recommendation answered with it, `user`'s,
        `via: recommended`; then a `done` Document Version of the published
        text and the item's mark. Refused while a block has neither, a claimed
        action not yet done among them (DB 154); a block Pilot's standing
        note differs on has no recommendation (DB 628). Pilot's Done is on a document
        it settled whole, every block answered (decision 42), and on a
        registered document of one block, which takes its block's kind, once
        that block is answered, deferred, or claimed and done. Done through
        the app on a document `user`'s own Done closed is taken as done and
        changes nothing, ahead of every refusal."""
        if self.references.form(self.db, item.kind_code) != PROSE:
            raise InvalidOperationException(
                f"mark item {item.id} done",
                f"a {item.kind_code} item is not done by Done",
            )
        document = self.db.get_one(Document, item.id)
        project, _ = self._closing(document)
        if via is AnswerChannel.APP and _marked_by(item, user, DOCUMENT):
            return
        operation = f"mark {tree_path(project, document.path)} done"
        _not_archived(project, operation)
        _not_awaiting_read(item, document, operation)
        blocks = _blocks(item, document)
        pilots = user.kind_code is UserKind.AGENT
        one_block = document.source_path is not None and len(blocks) == 1
        if item.kind_code != DOCUMENT and not (pilots and one_block):
            raise InvalidOperationException(
                operation, f"a {item.kind_code} item is not done by Done"
            )
        _not_done(item, operation)
        if pilots:
            cause = SETTLED
            unready = [block for block in blocks if not block.answered]
            refusal = (
                "Pilot marks done only a document it settled whole, and these"
                " blocks are unanswered: " + ", ".join(b.local_id for b in unready)
            )
        else:
            cause = MARKED
            differing = self._differing(item, blocks)
            unready = [
                block
                for block in blocks
                if not block.answered
                and (block.local_id in differing or dsl.recommendation(block) is None)
            ]
            noted = [block.local_id for block in unready if block.local_id in differing]
            refusal = (
                "these blocks have neither an answer nor a recommendation: "
                + ", ".join(block.local_id for block in unready)
                + (
                    f" (Pilot's note on {', '.join(noted)} suggests another answer"
                    " than its recommendation)"
                    if noted
                    else ""
                )
            )
        if unready:
            raise InvalidOperationException(operation, refusal)
        at = _now()
        if cause == MARKED:
            text = dsl.write_recommended(_published(document), by=user.handle, at=at)
            if text != document.published_text:
                self.document_service.publish(document, text)
        self.document_service.cut_version(document, VersionCause.DONE)
        self._mark(
            project, item, document, cause, user, at, via=via, session_id=session_id
        )

    def _differing(self, item: Item, blocks: Sequence[dsl.Block]) -> set[str]:
        """The local ids of `blocks`, the published text's of `item`, that
        Pilot's standing note differs on (DB 628)."""
        notes = {
            standing.block: standing.note
            for standing in standing_notes(self.db, [item.id]).get(item.id, [])
        }
        return {
            block.local_id
            for block in blocks
            if (note := notes.get(block.local_id)) is not None and differs(note, block)
        }

    def read(
        self, item: Item, user: User, *, via: AnswerChannel = AnswerChannel.APP
    ) -> None:
        """Read on a notice, given through `via`: the item's mark, the text
        untouched; on a debrief's notice, which has no text, a person's alone
        (`_read_debrief_notice`). Read through the app on a notice `user`'s
        own Read closed is taken as done and changes nothing, ahead of every
        refusal."""
        if item.kind_code == DEBRIEF_NOTICE:
            self._read_debrief_notice(item, user, via)
        else:
            self._mark_by_kind(item, user, NOTICE, "Read", via, None)

    def _read_debrief_notice(self, item: Item, user: User, via: AnswerChannel) -> None:
        """A member's Read of a debrief's notice (DB 613): done `marked` by
        `user`, its Undo as `marked` offers it. Its project's row is held
        exclusively first, as every close holds it (`_closing`), then its own
        row, where a document's would be. No Session added it, so no job
        follows its Read and no Session consumes it."""
        project = self.db.scalars(
            select(Project)
            .where(Project.id == item.project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()
        item = self.db.get_one(
            Item, item.id, with_for_update=True, populate_existing=True
        )
        if via is AnswerChannel.APP and _marked_by(item, user, DEBRIEF_NOTICE):
            return
        operation = f"mark item {item.id} Read"
        _not_archived(project, operation)
        _a_person(
            user, operation, "Pilot reads a debrief's notice only on a member's word"
        )
        _not_done(item, operation)
        item.done_at = _now()
        item.done_cause_code = MARKED
        item.done_by_user_id = user.id
        self.view_service.timeline_moved(project)

    def reviewed(
        self,
        item: Item,
        user: User,
        *,
        via: AnswerChannel = AnswerChannel.APP,
        session_id: uuid.UUID | None = None,
    ) -> None:
        """Reviewed on a review, given through `via`, the chat's in the
        brain's Session `session_id` (`answer`): the item's mark, the text
        untouched; one sent again is taken as a Read is."""
        self._mark_by_kind(item, user, REVIEW, "Reviewed", via, session_id)

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

    def cancel(
        self,
        project: Project,
        document_ids: Sequence[uuid.UUID],
        user: User,
        operation: str,
    ) -> None:
        """A person's Cancel on a document of a run (F28.9; DB 297 to 299):
        the run's open registered documents `document_ids` done at once by
        `user`, their Done Cause `cancelled`, which offers no undo, in the
        caller's transaction, which holds the project's row exclusively. The
        texts are untouched: no Version is cut, no write-back is owed and no
        continuation is placed, so the run is ended.

        Raises:
            InvalidOperationException: `user` is Pilot, or the project is
                archived.
        """
        _a_person(user, operation, "a Cancel is a person's")
        _not_archived(project, operation)
        self.db.scalars(
            select(Document.id)
            .where(Document.id.in_(document_ids))
            .order_by(Document.id)
            .with_for_update()
        ).all()
        items = self.db.scalars(
            select(Item)
            .where(Item.id.in_(document_ids), Item.done_at.is_(None))
            .order_by(Item.seq)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
        at = _now()
        for item in items:
            item.done_at = at
            item.done_cause_code = CANCELLED
            item.done_by_user_id = user.id
        if items:
            self.view_service.timeline_moved(project)

    def call_off(self, item: Item, user: User) -> None:
        """The chat's cancel of an ask Pilot added, on the word of the person
        `user` (DB 297, 299): an open decision, confirmation, question, action
        or document that a session of Pilot's own added, done at once by
        `user`, its Done Cause `cancelled`, which offers no undo. Its text
        and its blocks stand as they are; no job is placed after it and no
        run is ended.

        Raises:
            InvalidOperationException: the item is a work item, a wait or a
                debrief's notice; the project is archived; `user` is Pilot;
                the item is a registered document, a notice, or no ask Pilot
                added; or it is done.
        """
        if self.references.form(self.db, item.kind_code) != PROSE:
            raise InvalidOperationException(
                f"cancel item {item.id}", f"a {item.kind_code} item is no ask"
            )
        document = self.db.get_one(Document, item.id)
        project, _ = self._closing(document)
        operation = f"cancel {tree_path(project, document.path)}"
        _not_archived(project, operation)
        _a_person(user, operation, "Pilot calls off no ask on its own word")
        if document.source_path is not None:
            raise InvalidOperationException(operation, REGISTERED_CANCEL)
        if item.kind_code == NOTICE:
            raise InvalidOperationException(
                operation, "a notice asks nothing, and takes its Read"
            )
        if item.kind_code not in ASKS or not self.pilots_own(item):
            raise InvalidOperationException(operation, "it is no ask Pilot added")
        _not_done(item, operation)
        item.done_at = _now()
        item.done_cause_code = CANCELLED
        item.done_by_user_id = user.id
        self.view_service.timeline_moved(project)

    def close_work(
        self,
        project: Project,
        work_id: uuid.UUID,
        user: User,
        operation: str,
        *,
        note: str | None = None,
    ) -> None:
        """A work item's close for good (DB 345 to 350), in the caller's
        transaction, which holds the project's row exclusively and the work
        item's Session, `stopped`: the item done at once by `user`, its Done
        Cause `cancelled`, which offers no undo, and `note`, Pilot's reason,
        its Work's `done_note`, none for a person's Close, with the debrief's
        notice, which the close places, no pass following it
        (`_place_debrief_notice`). No document is
        closed, no job is placed and nothing continues its conversation
        (`_release`).

        Raises:
            InvalidOperationException: the project is archived, or the item
                is done.
        """
        _not_archived(project, operation)
        item = self.db.get_one(
            Item, work_id, with_for_update=True, populate_existing=True
        )
        refusal = done_refusal(item)
        if refusal is not None:
            raise InvalidOperationException(operation, refusal)
        item.done_at = _now()
        item.done_cause_code = CANCELLED
        item.done_by_user_id = user.id
        self.db.get_one(Work, work_id).done_note = note
        self._place_debrief_notice(project, item)
        self.view_service.timeline_moved(project)

    def close_archive_question(
        self,
        project: Project,
        user: User,
        answer: str,
        *,
        note: str | None = None,
    ) -> Item | None:
        """The project's open archive question, if it has one, answered
        `answer`, Archive or Keep, by `user`, with `note`, its done
        `answered`: the menu's Archive closes it as its Archive and Reopen as
        its Keep (DB 265). Returns the question it closed.

        In the caller's transaction, which holds the project's row shared, as
        a change of its standing does (`ProjectService._locked`), so that no
        other close runs beside it. The question's document row is held, not
        the project's: a change that stops the project's sessions never
        upgrades its hold on the row, which a send holding its chat's Session
        waits on for its inserts."""
        document = self.db.scalars(
            select(Document)
            .join(Item, Item.id == Document.id)
            .where(
                Item.project_id == project.id,
                Item.kind_code == ARCHIVE_QUESTION,
                Item.done_at.is_(None),
            )
            .with_for_update(of=Document)
            .execution_options(populate_existing=True)
        ).one_or_none()
        if document is None:
            return None
        question = self.db.get_one(Item, document.id)
        at = _now()
        with _refusal_as_invalid():
            text = dsl.write_answer(
                _published(document),
                ARCHIVE_BLOCK,
                answer=answer,
                by=user.handle,
                at=at,
                via=dsl.AnswerChannel(AnswerChannel.APP.value),
                note=_value(note),
            )
        self.document_service.publish(document, text)
        self._mark(project, question, document, ANSWERED, user, at)
        return question

    def autopilot_yes(self, project: Project, user: User) -> None:
        """The switch's Yes (F4.2; DB decisions 7, 58), in the caller's
        transaction, which holds the project's row exclusively: every
        confirmation the switch answers that is open once its document's row
        is held, answered `Yes` by `user` through `autopilot` as `answer`
        answers it, so that an item of Pilot's own places the job after it and
        a registered document owes its write-back and may continue its run."""
        taken = autopilot_may_take(project).subquery()
        documents = self.db.scalars(
            select(Document.id)
            .where(Document.id.in_(select(taken.c.document_id)))
            .order_by(Document.id)
            .with_for_update()
        ).all()
        for document_id, local_id in self.db.execute(
            autopilot_may_take(project).where(Block.document_id.in_(documents))
        ).all():
            self.answer(
                self.db.get_one(Document, document_id),
                local_id,
                user,
                YES,
                via=AnswerChannel.AUTOPILOT,
            )

    def place_work(
        self,
        project: Project,
        session: AgentSession,
        title: str,
        plan_task_id: str | None = None,
        *,
        repo: str | None = None,
        trigger: WorkTrigger | None = None,
        trigger_item_id: uuid.UUID | None = None,
        trigger_note_id: int | None = None,
    ) -> Work:
        """A work item of `session`, one identity with it (DB Work, decision
        3): its Item of kind `work` at the project's next place on the
        timeline, on the plan's task `plan_task_id` when given, created by its
        own Session, and its Work under the switch's setting as it stands
        (F54.7), placed by the repository `repo` its environment is made from
        (F61.1), none for a job; a job has the Work Trigger `trigger` that
        started it, a worker's run none (DB 167); a job's Item
        `trigger_item_id` is the one whose event triggered it (decision 5), a
        run's that continues a conversation after Done the one whose close
        released it (decision 44); an offer's job names the Pilot Note
        `trigger_note_id` whose offer was taken, and no Item (DB 630).

        Raises:
            RecordNotFoundException: the project's plan has no task
                `plan_task_id`.
        """
        if plan_task_id is not None and not self.in_the_plan(project, plan_task_id):
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
            trigger_code=trigger,
            trigger_item_id=trigger_item_id,
            trigger_note_id=trigger_note_id,
            autopilot=project.autopilot,
        )
        self.db.add(work)
        self.db.flush()
        self.view_service.timeline_moved(project)
        return work

    def claimable(
        self, project: Project, block_ids: Sequence[str], operation: str
    ) -> list[Block]:
        """The Blocks `block_ids`, each `<item id>/<local id>`, that a work
        item added to `project` may be named for as the claimed actions it
        does (DB 261, widened by D224): open actions, a claim not yet done among
        them, of open registered documents of the project or of its open
        items of Pilot's own (`pilots_own`), each document's row held until
        the transaction ends, in the caller's, which holds the project's row.

        Raises:
            RecordNotFoundException: an item is not of the project, or its
                document has no such block.
            InvalidOperationException: a block is named twice; an item is
                neither a registered document nor an item of Pilot's own, is
                done, or has not been read yet; a block is no action, or is
                answered.
        """

        def refusal(block: dsl.Block, path: str) -> str | None:
            if block.kind is not dsl.BlockKind.ACTION:
                return (
                    f"block {block.local_id} of {path} is a {block.kind}, not an action"
                )
            if block.answered:
                return f"action {block.local_id} of {path} is answered"
            return None

        return self._nameable(
            project,
            block_ids,
            operation,
            "action",
            refusal,
            pilots_own=True,
            unnamed=(
                "is neither a registered document nor an item of Pilot's own:"
                " Pilot claims an action of a worker's document or of its own item"
            ),
        )

    def researchable(
        self, project: Project, block_ids: Sequence[str], operation: str
    ) -> list[Block]:
        """The Blocks `block_ids`, each `<item id>/<local id>`, that a work
        item added to `project` may be named for as the Blocks it checks a
        fact for (DB 293): Blocks with neither an answer, a claim included,
        nor a `done`, of open registered documents of the project, each
        document's row held until the transaction ends, in the caller's,
        which holds the project's row.

        Raises:
            RecordNotFoundException: an item is not of the project, or its
                document has no such block.
            InvalidOperationException: a block is named twice; an item is no
                registered document, is done, or has not been read yet; a
                block is answered or done.
        """

        def refusal(block: dsl.Block, path: str) -> str | None:
            if block.done is not None:
                return f"block {block.local_id} of {path} is done"
            if block.answer is not None:
                return f"block {block.local_id} of {path} is answered"
            return None

        return self._nameable(
            project,
            block_ids,
            operation,
            "block",
            refusal,
            pilots_own=False,
            unnamed=(
                "is no registered document: Pilot researches a block of a worker's"
                " document"
            ),
        )

    def _nameable(
        self,
        project: Project,
        block_ids: Sequence[str],
        operation: str,
        noun: str,
        refusal: Callable[[dsl.Block, str], str | None],
        *,
        pilots_own: bool,
        unnamed: str,
    ) -> list[Block]:
        """The Blocks `block_ids` of open registered documents of `project`,
        and with `pilots_own` of its open items of Pilot's own, for none of
        which `refusal`, given the block and its document's tree path, gives
        a reason, each document's row held until the transaction ends. A
        refusal of any other item says `unnamed` of it, and one of a block
        named twice names it `noun`."""
        named: list[tuple[Item, Document, str]] = []
        for block_id in block_ids:
            item_id, _, local_id = block_id.partition("/")
            item = self.db.get(Item, uuid.UUID(item_id))
            if item is None or item.project_id != project.id:
                raise RecordNotFoundException("Item", item_id)
            document = self.db.get(Document, item.id)
            if document is None or not (
                document.source_path is not None
                or (pilots_own and self.pilots_own(item))
            ):
                raise InvalidOperationException(operation, f"item {item.id} {unnamed}")
            named.append((item, document, local_id))
        documents = {document.id: document for _, document, _ in named}
        for document_id in sorted(documents):
            self.document_service.lock(documents[document_id])
        blocks: list[Block] = []
        for item, document, local_id in named:
            path = tree_path(project, document.path)
            _not_awaiting_read(item, document, operation)
            if item.done_at is not None:
                raise InvalidOperationException(operation, f"{path} is done")
            refused = refusal(_block(document, _blocks(item, document), local_id), path)
            if refused is not None:
                raise InvalidOperationException(operation, refused)
            row = self.db.scalars(
                select(Block).where(
                    Block.document_id == document.id, Block.local_id == local_id
                )
            ).one()
            if row in blocks:
                raise InvalidOperationException(
                    operation, f"it names {noun} {local_id} of {path} twice"
                )
            blocks.append(row)
        return blocks

    def give(self, project: Project, work: Work, blocks: Sequence[Block]) -> None:
        """The work item `work` named for the claimed actions `blocks`, which
        `claimable` gave, one Claim Assignment each, never changed: of a
        Block's namings the latest stands, the earlier kept (DB 260)."""
        self.db.add_all(
            ClaimAssignment(work_id=work.id, block_id=block.id) for block in blocks
        )
        self.db.flush()
        if blocks:
            self.view_service.timeline_moved(project)

    def research(self, project: Project, work: Work, blocks: Sequence[Block]) -> None:
        """The work item `work` named for the Blocks `blocks` whose facts it
        checks, which `researchable` gave, one Research Assignment each, never
        changed: of a Block's namings the latest stands, the earlier kept (DB
        292)."""
        self.db.add_all(
            ResearchAssignment(work_id=work.id, block_id=block.id) for block in blocks
        )
        self.db.flush()
        if blocks:
            self.view_service.timeline_moved(project)

    def work_done(self, work_id: uuid.UUID, at: datetime) -> None:
        """The work item done at `at`, its turn's end, by no one, its Done
        Cause `turn_ended`, which is final (decision 44). An item Finish
        closed first stays as Finish closed it. A worker's run's debrief's
        notice is placed at the end of the job after its turn
        (`debrief_notice_after_pass`), never here."""
        item = self.db.get_one(
            Item, work_id, with_for_update=True, populate_existing=True
        )
        if item.done_at is not None:
            return
        item.done_at = at
        item.done_cause_code = TURN_ENDED
        self.view_service.timeline_moved(self.db.get_one(Project, item.project_id))

    def debrief_notice_after_pass(self, project: Project, job: Work) -> None:
        """The end of the job `job` of `project`, at its last turn's end, its
        failure, or a stop nothing of the server's retries, in the caller's
        transaction, which holds the project's row exclusively: where it is
        the job after a worker's turn, the pass, the debrief's notice of the
        run whose turn it followed, placed now, so that the lines the pass
        wrote are in it when it is first seen (DB 609;
        `place_debrief_notice`). A job of any other trigger places none."""
        if job.trigger_code is not WorkTrigger.WORKER_TURN_ENDED:
            return
        # The job after a worker's turn names the run.
        assert job.trigger_item_id is not None
        self.place_debrief_notice(project, self.db.get_one(Item, job.trigger_item_id))

    def place_debrief_notice(self, project: Project, work_item: Item) -> None:
        """The debrief's notice of the done work item `work_item`, placed
        where it is owed (`_place_debrief_notice`), the project's timeline
        told. Under the project's row held exclusively."""
        if self._place_debrief_notice(project, work_item):
            self.view_service.timeline_moved(project)

    def _place_debrief_notice(self, project: Project, work_item: Item) -> bool:
        """For the done work item `work_item`, under its project's row held
        exclusively: where its Work's debrief completes, its Debrief Notice
        placed next on the timeline, by Pilot and no session, on the work
        item's task, titled by the debrief's subject, else by the work item's
        title, never urgent and for no one (DB 609, 611). It carries that
        debrief and, where it names a subject, the debrief of every done Work
        of the project with the same subject that does not complete and that
        no notice carries yet, each Work naming it (DB 610). None in a
        project finished or archived, whose Finish left nothing open (DB
        613), for a debrief that does not complete, for one given before its
        completion was taken, which has none (DB 609), and for a Work a
        notice carries already: once per Work (DB 607).

        Returns:
            Whether it placed one.
        """
        if project.archived or project.state_code is ProjectState.FINISHED:
            return False
        work = self.db.get_one(Work, work_item.id)
        if not work.debrief_completes or work.debrief_notice_id is not None:
            return False
        carried = [work]
        if work.debrief_subject is not None:
            carried.extend(
                self.db.scalars(
                    select(Work)
                    .join(Item, Item.id == Work.id)
                    .where(
                        Work.project_id == project.id,
                        Work.debrief_subject == work.debrief_subject,
                        Work.debrief_notice_id.is_(None),
                        Work.debrief_completes.is_(False),
                        Item.done_at.is_not(None),
                    )
                )
            )
        # A work item has the title it was placed with.
        assert work_item.title is not None
        pilot = self.db.scalars(
            select(User).where(User.kind_code == UserKind.AGENT)
        ).one()
        notice = Item(
            project_id=project.id,
            seq=self.document_service.next_seq(project),
            kind_code=DEBRIEF_NOTICE,
            title=DEBRIEF_TITLE.format(
                subject=(
                    work_item.title
                    if work.debrief_subject is None
                    else work.debrief_subject
                )
            ),
            plan_task_id=work_item.plan_task_id,
            created_by_user_id=pilot.id,
        )
        self.db.add(notice)
        self.db.flush()
        for each in carried:
            each.debrief_notice_id = notice.id
            each.debrief_notice_kind_code = DEBRIEF_NOTICE
        self.db.flush()
        return True

    def write_notable(self, work_id: uuid.UUID, text: str) -> bool:
        """Pilot's lines `text` on the debrief of the Work `work_id`, a write
        after the first replacing them (DB 636). Its project's row is held
        exclusively before the Work is read, the row the placement of its
        notice takes for the notice's `seq` (`_place_debrief_notice`), so a
        write that waited on a placement reads the Work as the placement left
        it. Where a Debrief Notice carries the Work, its row in
        `timeline.json` and its box move with the lines (DB 611, 612).

        Returns:
            Whether lines stood there, which `text` replaced.

        Raises:
            RecordNotFoundException: no Work has the id.
            InvalidOperationException: the Work has no debrief, nothing
                changed.
        """
        project_id = self.db.scalar(select(Work.project_id).where(Work.id == work_id))
        if project_id is None:
            raise RecordNotFoundException("Work item", str(work_id))
        project = self.db.scalars(
            select(Project)
            .where(Project.id == project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()
        work = self.db.get_one(Work, work_id, populate_existing=True)
        if work.debrief is None:
            raise InvalidOperationException(
                f"write Pilot's lines on the debrief of work item {work_id}",
                "it gave no debrief",
            )
        replaced = work.debrief_notable is not None
        work.debrief_notable = text
        self.db.flush()
        if work.debrief_notice_id is not None:
            self.view_service.timeline_moved(project)
        return replaced

    def done_by_its_save(
        self,
        project: Project,
        item: Item,
        document: Document,
        before: str,
        session: AgentSession | None,
    ) -> None:
        """An agent's save of `item`, an item of Pilot's own (`pilots_own`),
        merged and published under the project's row and the document's, its
        published text before the save `before`, credited to `session`, none
        for a save no Session's: where the save wrote the `done` of its last
        open block, a `done` Document Version of the published text and the
        item done at the save by Pilot, its Done Cause `settled` (DB 163), and
        no job after it; consumed on the spot by `session`, so that it offers
        no Undo (D226), as a Wait Pilot marks. A save no Session's took nothing,
        and the item keeps its Undo. An item done already, or of an archived
        project (D012), stays as it is."""
        if item.done_at is not None or project.archived:
            return
        if not _wrote_last_done(before, _published(document)):
            return
        pilot = self.db.scalars(
            select(User).where(User.kind_code == UserKind.AGENT)
        ).one()
        self.document_service.cut_version(document, VersionCause.DONE)
        at = _now()
        self._mark(project, item, document, SETTLED, pilot, at)
        if session is not None:
            _consume(item, session.id, at)

    def in_the_plan(self, project: Project, task_id: str) -> bool:
        """Whether the project's plan has the task `task_id`, not removed."""
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

    def _mark_by_kind(
        self,
        item: Item,
        user: User,
        kind: str,
        mark: str,
        via: AnswerChannel,
        session_id: uuid.UUID | None,
    ) -> None:
        if self.references.form(self.db, item.kind_code) != PROSE:
            raise InvalidOperationException(
                f"mark item {item.id} {mark}",
                f"a {item.kind_code} item is not marked {mark}",
            )
        document = self.db.get_one(Document, item.id)
        project, _ = self._closing(document)
        if via is AnswerChannel.APP and _marked_by(item, user, kind):
            return
        operation = f"mark {tree_path(project, document.path)} {mark}"
        _not_archived(project, operation)
        _not_awaiting_read(item, document, operation)
        _a_person(user, operation, "Pilot marks done only a document it settled whole")
        if item.kind_code != kind:
            raise InvalidOperationException(
                operation, f"a {item.kind_code} item is not marked {mark}"
            )
        _not_done(item, operation)
        self._mark(
            project,
            item,
            document,
            MARKED,
            user,
            _now(),
            via=via,
            session_id=session_id,
        )

    def _undo_refusal(self, item: Item) -> str | None:
        """Why a prose item takes no undo now, or none."""
        if item.done_at is None:
            return "the item is not done"
        if item.kind_code == ARCHIVE_QUESTION:
            return "an archive question offers no undo"
        if item.consumed_at is not None:
            return "a session has taken the item's answers"
        # A done item has its cause (`ck_items_done`).
        assert item.done_cause_code is not None
        if not self.references.undo_offered(self.db, item.done_cause_code):
            return f"an item done as {item.done_cause_code} offers no undo"
        project = self.db.get_one(Project, item.project_id)
        if project.archived:
            return ARCHIVED
        if project.state_code is ProjectState.FINISHED:
            return "the project is finished"
        return None

    def _locked(self, document: Document) -> tuple[Project, Item | None]:
        self.document_service.lock(document)
        return self.document_service.owner(document)

    def _closing(self, document: Document) -> tuple[Project, Item | None]:
        """`_locked`, for a write that may close the document, the project's
        row locked first, before the document's, so that the close serialises
        with Archive and reads the project as it stands (D012). An item's
        close may place work: a registered document's continue its run
        (`_release`), an item of Pilot's own's the job after it (`_mark`). Its
        project's row is locked exclusively from the start, as the start that
        places the work locks it (the start's lock order; review 3), so that
        two closes never both upgrade a shared hold. So the close serialises
        with Finish, with an Undo, and with every other item's close. A
        project document's, the draft's, holds the row shared, as an Undo
        does."""
        project, _ = self.document_service.owner(document)
        self.db.execute(
            select(Project.id)
            .where(Project.id == project.id)
            .with_for_update(read=document.project_id is not None)
        )
        return self._locked(document)

    def _done_by_its_answer(
        self,
        project: Project,
        item: Item | None,
        document: Document,
        blocks: tuple[dsl.Block, ...],
        user: User,
        at: datetime,
        *,
        via: AnswerChannel,
        session_id: uuid.UUID | None,
    ) -> None:
        """A one-ask item, done when its one block is answered (F32.3)."""
        if item is not None and len(blocks) == 1:
            self._mark(
                project,
                item,
                document,
                ANSWERED,
                user,
                at,
                via=via,
                session_id=session_id,
            )

    def _mark(
        self,
        project: Project,
        item: Item,
        document: Document,
        cause: str,
        user: User,
        at: datetime,
        *,
        via: AnswerChannel = AnswerChannel.APP,
        session_id: uuid.UUID | None = None,
    ) -> None:
        """The item done at `at` by `user`, its Done Cause `cause`, given
        through `via`: a registered document's close owes its write-back
        (`owes_write_back`) and may continue its run (`_release`); a person's
        close of an item of
        Pilot's own, but a notice's Read, places the job after it, or, the
        chat's, is consumed by the brain's Session `session_id`, whose own
        turn carries it out (D225)."""
        item.done_at = at
        item.done_cause_code = cause
        item.done_by_user_id = user.id
        self.view_service.timeline_moved(project)
        if owes_write_back(item, document):
            # A registered document is its Session's.
            assert item.created_by_session_id is not None
            self.engine_bus.emit(WriteBackOwed(item.created_by_session_id))
        # `close_starts_work` reads these two branches for the page (F59.3).
        if document.source_path is not None:
            self._release(project, item)
        elif (
            user.kind_code is UserKind.PERSON
            and item.kind_code != NOTICE
            and self.pilots_own(item)
        ):
            if via is AnswerChannel.CHAT:
                # A record through the chat names the brain's Session
                # (`PilotStoreService`).
                assert session_id is not None
                _consume(item, session_id, at)
            else:
                self.jobs().item_done(project, item)

    def pilots_own(self, item: Item) -> bool:
        """Whether a session of Pilot's own, one handed `pilot-store`, added
        the item: a person's close of it, but a notice's Read, starts the job
        after it (DB Work Trigger `item_done`); Pilot's own close, made by a
        session acting on the item already, starts none, nor does one the chat
        records on a person's behalf, whose own turn carries it out and which
        that turn's Session consumes (D225)."""
        return (
            self.db.scalar(
                select(SessionKind.surface)
                .join(AgentSession, AgentSession.kind_code == SessionKind.code)
                .where(AgentSession.id == item.created_by_session_id)
            )
            == Surface.STORE
        )

    def _release(self, project: Project, item: Item) -> None:
        """The close of the registered document `item`, under the project's
        row (`_closing`): once its run has ended, its work item done at its
        turn's end, and none of the documents it registered is open, nor any
        closed by Finish or a Cancel, which continue nothing (review 4; DB
        299), the run's conversation continues as a new work item, released
        by `item` (`Continuations`), and every document of the run is
        consumed by it: no Undo from now (review 1). A conversation whose
        latest work item was closed for good continues no more (DB 348)."""
        run_id = item.created_by_session_id
        # A registered document is its Session's.
        assert run_id is not None
        run = self.db.get(Item, run_id, populate_existing=True)
        if run is None or run.done_cause_code != TURN_ENDED:
            return
        if closed_for_good(self.db, run_id):
            return
        registered = self.db.execute(
            select(Item, Document)
            .join(Document, Document.id == Item.id)
            .where(
                Item.created_by_session_id == run_id,
                Document.source_path.is_not(None),
            )
            .order_by(Item.seq)
            .execution_options(populate_existing=True)
        ).all()
        if any(
            each.done_at is None or each.done_cause_code in ENDS_RUN
            for each, _ in registered
        ):
            return
        written: list[str] = []
        unread: list[str] = []
        for _, document in registered:
            # The query takes registered documents alone.
            assert document.source_path is not None
            # A closed registered document was read: one with no text failed
            # its read (review 7).
            if document.published_text is not None:
                written.append(document.source_path)
            else:
                unread.append(document.source_path)
        continuation = self.continuations().continue_run(
            self.db, project, run_id, item, resume_message(written, unread)
        )
        at = datetime.now(UTC)
        for each, _ in registered:
            each.consumed_at = at
            each.consumed_session_id = continuation.id
        self.db.flush()
        self.engine_bus.emit(ProjectChanged(project.id))


def closed_for_good(db: Session, run_id: uuid.UUID) -> bool:
    """Whether a close for good ended the conversation of the work item
    `run_id` (DB 348): the latest worker's run on it, the one whose Item
    has the highest `seq`, is done `cancelled`."""
    conversation = (
        select(AgentSession.conversation_id)
        .where(AgentSession.id == run_id)
        .scalar_subquery()
    )
    latest = db.scalar(
        select(Item.done_cause_code)
        .join(AgentSession, AgentSession.id == Item.id)
        .join(Work, Work.id == Item.id)
        .where(
            Work.session_kind_code == WORKERS_RUN,
            AgentSession.conversation_id == conversation,
        )
        .order_by(Item.seq.desc())
        .limit(1)
    )
    return latest == CANCELLED


def close_starts_work(
    db: Session, project: Project, items: Sequence[tuple[Item, Document | None]]
) -> set[uuid.UUID]:
    """The ids of the open items among `items`, `project`'s, whose close by a
    person on the page starts Pilot's work as the rows stand now (F59.3), as
    `_mark` starts it: a registered document's continues its run
    (`_release`); an item's a session of Pilot's own added, but a notice's,
    places the job after it (`pilots_own`). None while the project is
    archived, whose items take no close (D012). A statement is sent only
    where it can find something."""
    if project.archived:
        return set()
    closable = [
        (item, document)
        for item, document in items
        if document is not None and item.done_at is None
    ]
    added = {
        item.id: item.created_by_session_id
        for item, document in closable
        if document.source_path is None
        and item.kind_code != NOTICE
        and item.created_by_session_id is not None
    }
    pilots = (
        set(
            db.scalars(
                select(AgentSession.id)
                .join(SessionKind, SessionKind.code == AgentSession.kind_code)
                .where(
                    AgentSession.id.in_(set(added.values())),
                    SessionKind.surface == Surface.STORE,
                )
            )
        )
        if added
        else set()
    )
    return {
        item_id for item_id, session_id in added.items() if session_id in pilots
    } | _continuing(
        db,
        [item for item, document in closable if document.source_path is not None],
    )


def _continuing(db: Session, registered: list[Item]) -> set[uuid.UUID]:
    """The ids of the open registered documents `registered` whose close
    continues their run, as `_release` has it: its work item done at its
    turn's end, its conversation not closed for good, and every other
    document it registered closed, by neither Finish nor a Cancel."""
    run_of: dict[uuid.UUID, uuid.UUID] = {}
    for item in registered:
        # A registered document is its Session's.
        assert item.created_by_session_id is not None
        run_of[item.id] = item.created_by_session_id
    if not run_of:
        return set()
    ended = {
        run_id
        for run_id in db.scalars(
            select(Item.id).where(
                Item.id.in_(set(run_of.values())), Item.done_cause_code == TURN_ENDED
            )
        )
        if not closed_for_good(db, run_id)
    }
    if not ended:
        return set()
    holding: dict[uuid.UUID, set[uuid.UUID]] = {run_id: set() for run_id in ended}
    for item_id, run_id, done_at, cause in db.execute(
        select(Item.id, Item.created_by_session_id, Item.done_at, Item.done_cause_code)
        .join(Document, Document.id == Item.id)
        .where(
            Item.created_by_session_id.in_(ended),
            Document.source_path.is_not(None),
        )
    ):
        # The query takes the documents of the runs in `ended` alone.
        assert run_id is not None
        if done_at is None or cause in ENDS_RUN:
            holding[run_id].add(item_id)
    return {
        item_id
        for item_id, run_id in run_of.items()
        if run_id in ended and holding[run_id] <= {item_id}
    }


def done_refusal(item: Item) -> str | None:
    """Why a work item takes no Resume and no close: it is done, closed for
    good or otherwise (DB 347); None while it is open."""
    if item.done_at is None:
        return None
    if item.done_cause_code == CANCELLED:
        return CLOSED_FOR_GOOD
    return "it is done"


def _consume(item: Item, session_id: uuid.UUID, at: datetime) -> None:
    """The done `item` consumed at `at` by the Session `session_id`, which
    took it: it offers no Undo from now (DB 164)."""
    item.consumed_at = at
    item.consumed_session_id = session_id


def resume_message(written: list[str], unread: list[str]) -> str:
    """The continuation's first message (the rulings): the paths of the run's
    documents written back, then those whose turn-end read failed, each line
    only when it names one."""
    lines = []
    if written:
        lines.append(WRITTEN_BACK.format(paths=", ".join(written)))
    if unread:
        lines.append(UNREAD.format(paths=", ".join(unread)))
    return "\n".join(lines)


def _wrote_last_done(before: str, after: str) -> bool:
    """Whether `after`, the text a save of `before` published, has every
    block answered and the `done` of a block open in `before`: the save wrote
    its last open block's `done`."""
    open_before = {
        block.local_id for block in dsl.parse(before).blocks if not block.answered
    }
    blocks = dsl.parse(after).blocks
    return all(block.answered for block in blocks) and any(
        block.done is not None and block.local_id in open_before for block in blocks
    )


def owes_write_back(item: Item, document: Document) -> bool:
    """Whether the document is a registered one whose text, the answers in it,
    is owed to the file it was registered from (F65.1): closed by a person or
    by Pilot, Finish's close and a Cancel owing none (review 4; DB 299); with
    a text, which one whose read failed has not (ruling D1); and neither
    written back nor refused since that close."""
    return (
        document.source_path is not None
        and document.published_text is not None
        and item.done_at is not None
        and item.done_cause_code not in ENDS_RUN
        and document.written_back_at is None
        and document.write_back_refused_at is None
    )


def write_back_owed() -> ColumnElement[bool]:
    """`owes_write_back` as a query's condition on a Document joined to its
    Item."""
    return and_(
        Document.source_path.is_not(None),
        Document.published_text.is_not(None),
        Item.done_at.is_not(None),
        Item.done_cause_code.not_in(ENDS_RUN),
        Document.written_back_at.is_(None),
        Document.write_back_refused_at.is_(None),
    )


def autopilot_may_take(project: Project) -> Select[uuid.UUID, str]:
    """The project's open confirmations the switch answers (F4.2, F4.4; DB
    decision 58), each as its document's id and its local id, in timeline
    order: unanswered, on an open item, `because` a reason that does not ask
    under auto pilot."""
    return (
        select(Block.document_id, Block.local_id)
        .join(Item, Item.id == Block.document_id)
        .join(ConfirmationReason, ConfirmationReason.code == Block.because_code)
        .where(
            Item.project_id == project.id,
            Item.done_at.is_(None),
            Block.confirmation,
            Block.answer.is_(None),
            ConfirmationReason.asks_under_autopilot.is_(False),
        )
        .order_by(Item.seq, Block.position)
    )


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


def _not_archived(project: Project, operation: str) -> None:
    """An archived project takes Bring back alone (D012): no close, as no Undo,
    so the round trip's last close is not the only one it refuses."""
    if project.archived:
        raise InvalidOperationException(operation, ARCHIVED)


def _not_awaiting_read(item: Item | None, document: Document, operation: str) -> None:
    """A registered document takes no close before its read at the end of the
    turn that registered it (review 7)."""
    if item is not None and awaits_read(item, document):
        raise InvalidOperationException(
            operation,
            "its file has not been read yet: it is read at the end of the turn"
            " that registered it",
        )


def _not_done(item: Item | None, operation: str) -> None:
    """Done fixes an item's answers (F15, F24.3)."""
    if item is not None and item.done_at is not None:
        raise InvalidOperationException(operation, "the item is done")


def _closed_by(
    item: Item | None, document: Document, local_id: str, user: User
) -> dsl.Block | None:
    """Block `local_id` of a done item as the person `user` closed it; none
    where the item is open, or has no such block, or another closed it, or
    `user` is Pilot, whose closes are the file's."""
    if item is None or item.done_at is None or user.kind_code is UserKind.AGENT:
        return None
    return next(
        (
            block
            for block in _blocks(item, document)
            if block.local_id == local_id and block.by == user.handle
        ),
        None,
    )


def _marked_by(item: Item, user: User, kind: str) -> bool:
    """Whether the item is of `kind` and done by `user`'s own mark."""
    return (
        item.kind_code == kind
        and item.done_cause_code == MARKED
        and item.done_by_user_id == user.id
    )


def _blocks(item: Item | None, document: Document) -> tuple[dsl.Block, ...]:
    """The published text's blocks; none in the opening, whose text the
    record never reads (DB decision 2), nor in a registered document whose
    read failed, which has no text (ruling D1)."""
    if (item is not None and item.kind_code == OPENING) or (
        document.published_text is None
    ):
        return ()
    return dsl.parse(document.published_text).blocks


def _block(
    document: Document, blocks: tuple[dsl.Block, ...], local_id: str
) -> dsl.Block:
    block = next((block for block in blocks if block.local_id == local_id), None)
    if block is None:
        raise RecordNotFoundException("Block", f"{document.id}/{local_id}")
    return block


@contextmanager
def _refusal_as_invalid() -> Iterator[None]:
    """A refusal of the DSL's writer as the engine's own
    `InvalidOperationException`, with its message."""
    try:
        yield
    except dsl.WriteRefused as refused:
        raise InvalidOperationException(refused.operation, refused.cause) from refused


def _published(document: Document) -> str:
    # Every document but a registered one is born published, and a registered
    # one with no text has no blocks and is a review, which Done does not take.
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
