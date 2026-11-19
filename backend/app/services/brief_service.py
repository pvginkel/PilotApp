"""The brief a brain session's first Turn carries (design 3 §5): one frame,
the server's, Markdown, in one order (§5.2), and a renderer per kind (§5.3);
the server's trailer on the brief the brain writes a worker (§5.4); the
follow-up turn of a brain session whose turn ended with a save of its own
still held (§5.1; F79); and the turn that carries a work item on after its
environment's restart cut its turn (§9.6; F71).

A line that does not hold is left out, never written as "none", so that a
brief reads as the facts of its session. Every brain brief but the definition
chat's carries the project's state as the record holds it when the brief is
composed, every open plan note whole among it, and the handbook whole
(`BriefService._state`). A project chat's message that quotes an item or a
block carries the item as it then stands (`BriefService.quoted`), and its
opening brief what changed in the record since the project's previous chat
closed (`BriefService._changed`). A worker's carries the grants text its
project's switch selects, as the store's grants file holds it at the add
(`switch_grants`), and the handbook verbatim, the worker having no tree
(F129.5).
"""

import re
import uuid
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

import pilot_dsl as dsl
from sqlalchemy import ColumnElement, Select, func, literal, select
from sqlalchemy.orm import Session, aliased

from app.engine import claims, researches
from app.engine.documents import OPENING, REVIEW
from app.engine.paths import draft_folder, folder
from app.engine.plan import PlanService
from app.engine.record import ANSWERED
from app.engine.views import caller_named, utc_time
from app.models import (
    Attachment,
    Block,
    CardTransition,
    Chat,
    ClaimAssignment,
    ClarificationRun,
    Document,
    Environment,
    Item,
    ItemAttachment,
    PilotNote,
    PlanNote,
    PlanNoteReference,
    PlanTask,
    Project,
    ProjectMember,
    ProjectTransition,
    ResearchAssignment,
    SaveError,
    Turn,
    User,
    Wait,
    WaitFiring,
    Work,
)
from app.models import Session as AgentSession
from app.models.reference import (
    DocumentRole,
    ErrorKind,
    FiringCause,
    ProjectState,
    RecordKind,
    TaskStatus,
    TransitionKind,
    UserKind,
    WorkTrigger,
)
from app.services.clarification_service import Clarification, of_pass
from app.services.session_record_service import read_records
from app.services.session_scope import project_folder
from app.services.turn_end_read_service import READ_FAILED
from app.services.wait_service import CARD_WAIT, REQUESTS
from app.services.working_on import Reading, holds, run_of

CHAT_SKILL = "/chat"
CREATE_SKILL = "/create"
PLAN_SKILL = "/plan"
PRE_RULE_SKILL = "/pre-rule"

TASKS_HEADING = (
    "The plan's tasks not done, in its order, as `pilot.py plan task list` prints them:"
)
ITEMS_HEADING = "The open items, as `pilot.py items list --open` prints them:"
NOTES_HEADING = "The open plan notes, whole, as `pilot.py plan note list` prints them:"
HANDBOOK_HEADING = "The project's handbook, handbook.md, whole:"
CHANGED_HEADING = "What changed in the record since it closed, oldest first:"
QUOTED_HEADING = "The item the message quotes, as it stands now:"
QUOTED_BLOCK_HEADING = (
    "The item whose block {block} the message quotes, as it stands now:"
)

TRAILER_HEADING = "From Pilot:"

GRANTS_SECTION = "## In a worker's brief"
"""The section of the store's grants file that holds a worker's grants text:
one fenced block per position of the switch, each under its label of
`SWITCH_LABELS`."""
SWITCH_LABELS = {True: "Auto pilot on:", False: "Auto pilot off:"}
TOPIC_BRANCH = "pilot/<project>/<task>"
"""The work's topic branch as the grants text names it, in whose place the
trailer writes the work's own."""

_GRANTS_SECTION = re.compile(
    rf"^{re.escape(GRANTS_SECTION)}[ \t]*$(.*?)(?=^##? |\Z)", re.MULTILINE | re.DOTALL
)
_GRANTS_BLOCK = re.compile(
    rf"^({'|'.join(re.escape(label) for label in SWITCH_LABELS.values())})[ \t]*\n"
    r"(?:[ \t]*\n)*```[^\n]*\n((?:(?!```)[^\n]*\n)*)```[ \t]*$",
    re.MULTILINE,
)

FOLLOW_UP_END = "Fix it and end your turn."
"""The last line of the server's follow-up turn, which marks it as one."""

RESTARTED = (
    "Your environment restarted under your last turn, and this conversation"
    " goes on in a new session."
)
"""How the server's turn after a work item's restart begins, which marks it
as one (`BriefService.restarted`)."""

HOMELESS_HEADING = (
    "Deferrals without a home (a note names none of these blocks — write one,"
    " or answer the block anew in a new item):"
)

OFFER_TAKEN_KIND = "an offer of yours was taken"
"""The kind line of the job an offer's taking places (§5.2), which the store's
map reads its skill's passage from."""

HANDED_BACK = "handed back to the operator: leave it to them"
"""How a claimed or researched block's line in a job's brief ends once the
reading handed it back to the person (`working_on`)."""

ASKS_NOTHING = (
    "This pass asks nothing: what is still unclear is the operator's, the"
    " clarification beside the ask."
)
"""The last line of the writer-answered brief (design 3 §5.3; DB 256)."""

type Group = Sequence[str | None]
"""Lines of a brief kept together; one that does not hold is None."""


@dataclass(frozen=True)
class Call:
    """What a call of `start_project` says of itself (F150.9), which its
    draft's brief alone holds (DB decision 77), the first and one that
    carries the call's brief again (`BriefService.definition_chat`): the name
    of the environment it came from and the handle of the person it starts
    the project for, each none where the call gave none."""

    environment: str | None
    for_handle: str | None


class BriefService:
    """Composes the briefs of the brain's sessions from the record."""

    def __init__(self, db: Session, plan_service: PlanService) -> None:
        self.db = db
        self.plan_service = plan_service

    def project_chat(
        self,
        project: Project,
        person: User,
        words: str,
        at: datetime,
        *,
        quote_item_id: uuid.UUID | None = None,
        quote_block_id: int | None = None,
    ) -> str:
        """The first Turn of a project's chat (§5.3), sent at `at`: `/chat`,
        the switch, the pause while the project is paused, the project's
        state and the handbook (`_state`), the latest closed chat and what
        changed in the record since it closed (`_changed`), the item the
        words quote by `quote_item_id` or `quote_block_id` as it stands
        (`quoted`), then `person`'s `words` verbatim, which it ends with (DB
        assertion 251). A finished project's has the finish line in place of
        the switch (F5.5)."""
        closed = self.db.scalar(
            select(func.max(Chat.closed_at)).where(Chat.project_id == project.id)
        )
        standing: Group
        if project.state_code is ProjectState.FINISHED:
            kind, standing = "a finished project's chat", [self._finish(project)]
        else:
            kind, standing = (
                "the project's chat",
                [_switch(project), self._pause(project)],
            )
        return _frame(
            CHAT_SKILL,
            kind,
            project,
            at,
            standing,
            *self._state(project),
            [_earlier_chats(closed)],
            self._changed(project, closed),
            self.quoted(quote_item_id, quote_block_id),
            [self.message_from(project, person), words],
        )

    def conversation(
        self,
        project: Project,
        environment: Environment,
        caller_session: str | None,
        words: str,
        at: datetime,
    ) -> str:
        """The first Turn of a Conversation (§5.3; F150.12; DB 336), sent at
        `at`: `/chat`, under a kind line of its own naming the Environment
        its caller called from, by its name and its id, and that caller's
        session where the call named one; the switch, the pause while the
        project is paused, the project's state and the handbook (`_state`);
        then the caller's `words` verbatim, headed as the session's, which it
        ends with (DB assertion 251). A finished project's has the finish line
        in place of the switch, as its chat's (DB 334). It names no earlier
        chat: a caller reads its own conversations alone."""
        kind = conversation_kind(environment, caller_session)
        message = [f"The message, from the session in {environment.name}:", words]
        if project.state_code is ProjectState.FINISHED:
            return _frame(
                CHAT_SKILL,
                kind,
                project,
                at,
                [self._finish(project)],
                *self._state(project),
                message,
            )
        return _frame(
            CHAT_SKILL,
            kind,
            project,
            at,
            [_switch(project), self._pause(project)],
            *self._state(project),
            message,
        )

    def definition_chat(
        self,
        project: Project,
        person: User,
        words: str,
        at: datetime,
        call: Call | None = None,
    ) -> str:
        """The first Turn of a draft's definition chat (§5.3), sent at `at`:
        `/create`; no switch, no state and no handbook, a draft having none
        (F141.2, F129.2); the draft, who started it and the attachments so
        far; then `person`'s `words` verbatim, which it ends with, after the
        line naming them when another started the draft (DB decision 61).

        From the plus, who started it is the person who did. By a call
        (F150.9), `person` its service user and `words` its brief, it is
        `call`: the environment it came from and the person it is for.

        A later definition chat of a call's draft has a person's message and
        no `call`. While no Turn of the draft has reached Pilot
        (`_unheard`), it names the call as the first brief did, and the
        call's brief goes before the person's message as the call's own.
        Once one has, it says that a call started the draft, and carries the
        person's message alone."""
        creator = self.db.get_one(User, project.created_by_user_id)
        messages: list[Group] = []
        if creator.kind_code is UserKind.SERVICE:
            unheard = None if call is not None else self._unheard(project, creator)
            if unheard is None:
                started = _by_a_call(call)
            else:
                started = _started_by_a_call(unheard.message)
                messages.append(["The message:", unheard.words])
        else:
            started = (
                f"The person who started it: {creator.handle}"
                f" ({self._standing(project, creator)})."
            )
        messages.append(
            [
                "The message:"
                if person.id == creator.id
                else self.message_from(project, person),
                words,
            ]
        )
        draft = self.db.scalar(
            select(Document.published_text).where(
                Document.project_id == project.id,
                Document.role_code == DocumentRole.DRAFT,
            )
        )
        attached = self.db.scalar(
            select(func.count())
            .select_from(Attachment)
            .where(Attachment.project_id == project.id)
        )
        return _frame(
            CREATE_SKILL,
            "the definition chat",
            project,
            at,
            [
                f"The draft: project.md{'' if (draft or '').strip() else ', empty'}."
                f" {started}",
                f"Attachments so far: {_files(attached or 0)}.",
            ],
            *messages,
        )

    def _unheard(self, project: Project, creator: User) -> Turn | None:
        """The Turn that carried the brief of the call that started the draft
        `project`, the service user `creator`'s, while no Turn of the draft
        has reached Pilot: no Session of its chats has a conversation, which
        the first line a turn prints gives it (`RelayService`), so a start
        that failed and one stopped before its brief went out left none.
        None once one has."""
        chats = select(Chat.id).where(Chat.project_id == project.id)
        heard = self.db.scalar(
            select(func.count())
            .select_from(AgentSession)
            .where(
                AgentSession.id.in_(chats),
                AgentSession.conversation_id.is_not(None),
            )
        )
        if heard:
            return None
        # A call's draft is made with the Turn of its brief, the one Turn its
        # service user writes in it (F150.9; DB 339).
        return self.db.scalars(
            select(Turn).where(
                Turn.session_id.in_(chats), Turn.author_user_id == creator.id
            )
        ).one()

    def job(
        self, project: Project, work: Work, triggered: datetime, at: datetime
    ) -> str:
        """A job's first Turn (§5.3), composed at `at` as it leaves the queue
        or the pause, from the record as it then stands (F59), its trigger at
        `triggered`: the switch, the pause its trigger came in if it did
        (F141.4, `_trigger_paused`), then its trigger's payload, the
        project's state with the job's seqs and the notes it returns to, and
        the handbook (`_state`)."""
        if work.trigger_code is WorkTrigger.WORKER_TURN_ENDED:
            # The job after a worker's turn names its run.
            assert work.trigger_item_id is not None
            clarification = self.db.get(ClarificationRun, work.trigger_item_id)
            if clarification is not None:
                return self._writer_answered(
                    project, work, clarification, triggered, at
                )
            return self._worker_turn_ended(
                project, work, work.trigger_item_id, triggered, at
            )
        if work.trigger_code is WorkTrigger.ITEM_DONE:
            # The job after an item's close names the item.
            assert work.trigger_item_id is not None
            return self._item_done(project, work, work.trigger_item_id, triggered, at)
        if work.trigger_code is WorkTrigger.WAIT_FIRED:
            return self._wait_fired(project, work, triggered, at)
        if work.trigger_code is WorkTrigger.OFFER_TAKEN:
            # An offer's job names its Pilot Note (DB 630).
            assert work.trigger_note_id is not None
            return self._offer_taken(project, work, work.trigger_note_id, triggered, at)
        assert work.trigger_code is WorkTrigger.SETUP
        return self._setup(project, work, triggered, at)

    def wait_follow_up(self, work: Work) -> str:
        """The first Turn of the wait's run `work` that resumes its previous
        run's conversation (§5.3; F136.5): no frame, the follow-up alone,
        naming the wait and the firings the run took, oldest first."""
        item, wait = self._wait(work)
        return "\n".join(
            [
                f'Another firing of "{item.title}" since your last run:',
                *self._firings(wait, [work.id]),
            ]
        )

    def _wait_fired(
        self, project: Project, work: Work, triggered: datetime, at: datetime
    ) -> str:
        """A wait's run, fresh (§5.3, *A wait's firings*): `/plan`, then the
        wait's line and the firings the run took at its brief, oldest first,
        a Retry's with those the runs it retries took, which stay theirs (DB
        191); then the project's state, its return list the notes of the
        wait's task and the plan's own, and the handbook."""
        item, wait = self._wait(work)
        lines = [_wait_line(item, wait)]
        firings = self._firings(wait, _retried(self.db, work))
        if firings:
            lines.extend(["Firings pending, oldest first:", *firings])
        return _frame(
            PLAN_SKILL,
            "a wait fired",
            project,
            at,
            [_switch(project), self._trigger_paused(project, triggered)],
            lines,
            *self._state(project, work, _task_of(item)),
        )

    def _wait(self, work: Work) -> tuple[Item, Wait]:
        # A wait's run names its wait (DB 195).
        assert work.trigger_item_id is not None
        return (
            self.db.get_one(Item, work.trigger_item_id),
            self.db.get_one(Wait, work.trigger_item_id),
        )

    def _firings(self, wait: Wait, jobs: Sequence[uuid.UUID]) -> list[str]:
        """The wait's firings the runs `jobs` took, oldest first, each its
        time and its cause: the transition, the due time, or a person's
        request by its button's name."""
        return [
            f"- {utc_time(firing.fired_at)} · {_fired(wait, firing, transition, by)}"
            for firing, transition, by in self.db.execute(
                select(WaitFiring, CardTransition, User.handle)
                .outerjoin(
                    CardTransition, CardTransition.id == WaitFiring.transition_id
                )
                .outerjoin(User, User.id == WaitFiring.requested_by_user_id)
                .where(WaitFiring.wait_id == wait.id, WaitFiring.job_id.in_(jobs))
                .order_by(WaitFiring.seq)
            )
        ]

    def _setup(
        self, project: Project, work: Work, triggered: datetime, at: datetime
    ) -> str:
        """The setup's (F49), triggered at Create project's instant, which
        opened the project and took its slug: `/plan`, then the draft's folder
        and the project's, the draft, the opening that holds the words that
        started it, and the plan, empty; then the project's state and the
        handbook, its plan holding no task and no note. The pause holds no
        setup (`setups`), so no pause line; but while Create's pause stands
        (D083) the setup is told of it, since every work item it adds is held
        (`_create_paused`)."""
        opening = self.db.scalars(
            select(Item.id).where(
                Item.project_id == project.id, Item.kind_code == OPENING
            )
        ).one()
        return _frame(
            PLAN_SKILL,
            "the setup",
            project,
            at,
            [_switch(project), self._create_paused(project)],
            [
                f"The project was created {utc_time(triggered)} from"
                f" {draft_folder(project)}; its folder is now"
                f" {project_folder(project)}.",
                f"The draft: project.md (the opening item {opening} holds the"
                " words that started it; the draft's copy and what the chat"
                " attached hang on it).",
                "The plan: plan.json, empty.",
            ],
            *self._state(project, work),
        )

    def _worker_turn_ended(
        self,
        project: Project,
        work: Work,
        run_id: uuid.UUID,
        triggered: datetime,
        at: datetime,
    ) -> str:
        """The job after the turn of the worker's run `run_id` (design 3 D2):
        `/pre-rule` where the run left the pass something, a document it
        registered, a debrief or a block it researched, else `/plan`, under
        the same kind line; then the work item's line, the documents the run
        registered in the order registered, each published or its read failed
        with the reason the read recorded, else that it registered nothing and
        the whole text its turn ended with, which the line then leaves out
        (P-291), the files attached on the work item, the stage session's debrief
        (`_debriefed`), and the claimed actions it was given (`_given`) and
        the blocks it researched (`_researched`); then the project's state,
        whose every open note the pass takes (F57.4), or `/plan` where the job
        opens on it, and the handbook."""
        registered = self._registered(run_id)
        debriefed = self._debriefed(run_id)
        researched = self._researched(run_id)
        lines: list[str | None] = [self._run_line(run_id, last_line=bool(registered))]
        if registered:
            lines.extend(registered)
        else:
            lines.extend(self._registered_nothing(run_id))
        lines.append(self._attached(run_id))
        lines.extend(debriefed)
        lines.extend(self._given(run_id))
        lines.extend(researched)
        return _frame(
            PRE_RULE_SKILL if registered or debriefed or researched else PLAN_SKILL,
            "a worker's turn ended",
            project,
            at,
            [_switch(project), self._trigger_paused(project, triggered)],
            lines,
            *self._state(project, work),
        )

    def _writer_answered(
        self,
        project: Project,
        work: Work,
        run: ClarificationRun,
        triggered: datetime,
        at: datetime,
    ) -> str:
        """The job after the turn of the clarification run `run` (design 3
        §5.3, *The writer answered*; DB 256): `/pre-rule`, then the run's
        line, naming the work item whose conversation it resumed, and per
        document its pass asked about, in timeline order, the questions as
        asked and the writer's answer as the document records it
        (`_clarified`); then the files attached on the run and what it
        registered, as any run's, and that this pass asks nothing, and the
        debrief its session gave (`_debriefed`); then the project's state and
        the handbook."""
        item = self.db.get_one(Item, run.id)
        worker_id = self.db.get_one(Work, run.pass_id).trigger_item_id
        # A clarification run's pass is the job after a worker's turn (DB 254),
        # and the run is done at its turn's end when its job is placed.
        assert worker_id is not None and item.done_at is not None
        worker = self.db.get_one(Item, worker_id)
        head = (
            f'The clarification run: "{item.title}" ({item.id}), of the work item'
            f' "{worker.title}" ({worker.id})'
        )
        if worker.plan_task_id is not None:
            head += f", task {worker.plan_task_id}"
        lines: list[str | None] = [f"{head}; its turn ended {utc_time(item.done_at)}."]
        for clarification in of_pass(self.db, run.pass_id):
            lines.extend(self._clarified(clarification))
        lines.append(self._attached(run.id))
        registered = self._registered(run.id)
        if registered:
            lines.extend([*registered, ASKS_NOTHING])
        else:
            lines.append(f"Registered this run: nothing. {ASKS_NOTHING}")
        lines.extend(self._debriefed(run.id))
        return _frame(
            PRE_RULE_SKILL,
            "the writer answered",
            project,
            at,
            [_switch(project), self._trigger_paused(project, triggered)],
            lines,
            *self._state(project, work),
        )

    def _clarified(self, clarification: Clarification) -> list[str]:
        """A document's clarification as the writer-answered brief gives it:
        when it was first asked and the document, each question with its
        block's local id and its section's heading, then the writer's answer
        as recorded on the document (DB 257): per block where the reply kept
        the asked headings, else whole, quoted; none where the run's turn
        ended with no text."""
        document = self.db.get_one(Document, clarification.item_id)
        # A Writer Question is asked about a Block of a published text.
        assert document.published_text is not None
        sections = {
            block.local_id: block.section.heading
            for block in dsl.parse(document.published_text).blocks
            if block.section is not None
        }
        lines = [
            f"Asked {utc_time(clarification.asked_at)} on {document.path}"
            f" ({document.id}):"
        ]
        for each in clarification.questions:
            section = sections.get(each.local_id)
            named = each.local_id if section is None else f'{each.local_id} "{section}"'
            lines.append(f"- {named}: {each.question}")
        if clarification.reply is None:
            lines.append(
                "The writer's answer: none — the run's turn ended with no text."
            )
        elif clarification.split:
            lines.append("The writer's answer, as recorded on the document:")
            lines.extend(
                f"- {each.local_id}: "
                + clarification.parts[each.block_id].replace("\n", "\n  ")
                for each in clarification.questions
            )
        else:
            lines.append(
                "The writer's answer, as recorded on the document, whole — the reply"
                " did not keep the asked headings:"
            )
            lines.extend(
                f"> {line}" if line else ">"
                for line in clarification.reply.splitlines()
            )
        return lines

    def _registered(self, run_id: uuid.UUID) -> list[str]:
        """The documents the run registered, in the order registered, each
        published or its read failed with the reason the read recorded;
        none where it registered none."""
        registered = self.db.execute(
            select(Item.id, Document.path, Document.read_failed_at)
            .join(Document, Document.id == Item.id)
            .where(
                Item.created_by_session_id == run_id,
                Document.source_path.is_not(None),
            )
            .order_by(Item.seq)
        ).all()
        if not registered:
            return []
        failures = self._read_failures(run_id, len(registered))
        return [
            "Registered this run, in the order registered:",
            *(
                f"- {path} ({item_id}) — "
                + (
                    "published"
                    if failed is None
                    else f"read failed: {failures[str(item_id)]}"
                )
                for item_id, path, failed in registered
            ),
        ]

    def _debriefed(self, run_id: uuid.UUID) -> list[str]:
        """The debrief the run's session gave, whole and as given, under its
        heading (F52.4; design 3 §5.3; DB 328), the space it ends in left off
        so that the next line follows it; none where it gave none. Its
        entries, the roles' accounts, stay out."""
        debrief = self.db.scalar(select(Work.debrief).where(Work.id == run_id))
        if debrief is None:
            return []
        return ["The stage session's debrief, as given:", debrief.rstrip()]

    def _attached(self, run_id: uuid.UUID) -> str | None:
        """The files attached on the work item, counted; None for none."""
        attached = self.db.scalar(
            select(func.count())
            .select_from(ItemAttachment)
            .where(ItemAttachment.item_id == run_id)
        )
        if not attached:
            return None
        return f"Attached on the work item: {_files(attached)}."

    def _item_done(
        self,
        project: Project,
        work: Work,
        item_id: uuid.UUID,
        triggered: datetime,
        at: datetime,
    ) -> str:
        """The job after a person's close of the item of Pilot's own
        `item_id` (DB decision 45): `/plan`, then the item and what was done
        to it, as the record holds it (`_closed`); then the project's state,
        its return list the open notes of the task the item names and the
        plan's own, the plan's alone where it names none (F57.4), and the
        handbook."""
        item = self.db.get_one(Item, item_id)
        return _frame(
            PLAN_SKILL,
            "an item of yours is done",
            project,
            at,
            [_switch(project), self._trigger_paused(project, triggered)],
            [self._closed(item)],
            *self._state(project, work, _task_of(item)),
        )

    def _offer_taken(
        self,
        project: Project,
        work: Work,
        note_id: int,
        triggered: datetime,
        at: datetime,
    ) -> str:
        """The job a member's press of the offer of the Pilot Note `note_id`
        placed (F168.7; DB 629, 630): `/plan`, then the note and its taking
        (`_taken`); then, as the job after an item's close, the project's
        state, its return list the open notes of the task the note's item
        names and the plan's own, the plan's alone where it names none
        (F57.4), and the handbook."""
        note = self.db.get_one(PilotNote, note_id)
        item = self.db.get_one(Item, note.item_id)
        return _frame(
            PLAN_SKILL,
            OFFER_TAKEN_KIND,
            project,
            at,
            [_switch(project), self._trigger_paused(project, triggered)],
            self._taken(note, item),
            *self._state(project, work, _task_of(item)),
        )

    def _taken(self, note: PilotNote, item: Item) -> list[str | None]:
        """The taken offer's lines: the action's place, its path, item and
        task, and its own section's words, quoted; then each of the note's
        fields that it holds, and who took the offer and when."""
        document = self.db.get_one(Document, item.id)
        # An offer stands on an action of a published text (DB 626, 627),
        # and its taking sets both of its facts (DB 629).
        assert note.block_id is not None and document.published_text is not None
        assert note.offer is not None and note.offer_taken_at is not None
        assert note.offer_taken_by_user_id is not None
        local_id = self.db.get_one(Block, note.block_id).local_id
        head = (
            f"The offer, on action {local_id} of {document.path} ({item.id}),"
            f' {item.kind_code} "{item.title}"'
        )
        if item.plan_task_id is not None:
            head += f", task {item.plan_task_id}"
        words = "\n\n".join(
            part.markdown
            for part in dsl.body(document.published_text)
            if isinstance(part, dsl.Prose) and part.section == local_id
        )
        taker = self.db.get_one(User, note.offer_taken_by_user_id).handle
        return [
            f"{head}:",
            *(f"> {line}" if line else ">" for line in words.splitlines()),
            None if note.text is None else f'Your note: "{note.text}"',
            (
                None
                if note.suggested_answer is None
                else f'Your suggested answer: "{note.suggested_answer}"'
            ),
            (
                None
                if note.suggested_note is None
                else f'Your suggested note: "{note.suggested_note}"'
            ),
            f'Your offer: "{note.offer}"',
            f"Taken by {taker} at {utc_time(note.offer_taken_at)}.",
        ]

    def _closed(self, item: Item) -> str:
        """The closed item's line: its path, id, kind, title and task, then
        its close, by the person whose close placed the job and when — a
        one-ask item's block as answered or done; a document's Done, one line
        per block as the closed block reads; a review's Reviewed."""
        document = self.db.get_one(Document, item.id)
        # A person's close starts the job; Pilot's own text is born published.
        assert item.done_at is not None and item.done_by_user_id is not None
        assert document.published_text is not None
        closer = self.db.get_one(User, item.done_by_user_id).handle
        when = utc_time(item.done_at)
        head = f'The item: {document.path} ({item.id}), {item.kind_code} "{item.title}"'
        if item.plan_task_id is not None:
            head += f", task {item.plan_task_id}"
        blocks = dsl.parse(document.published_text).blocks
        if item.done_cause_code == ANSWERED:
            # The one block a person answered closed the one-ask item.
            block = next(
                block
                for block in blocks
                if block.by is not None and block.by != dsl.AGENT
            )
            return f"{head} — {_answered(block, when)}."
        if item.kind_code == REVIEW:
            return f"{head} — Reviewed by {closer} at {when}."
        if not blocks:
            return f"{head} — Done by {closer} at {when}."
        return "\n".join(
            [
                f"{head} — Done by {closer} at {when}; its blocks:",
                *(f"- {_block_line(block, closer)}" for block in blocks),
            ]
        )

    def _given(self, run_id: uuid.UUID) -> list[str]:
        """The claimed actions whose standing Claim Assignment names the run
        `run_id` or a work item on its conversation (DB 260), so that a
        continuation's names those of the run it continues (D100), for their
        `done` (design 3 §6.5), in timeline order, each as its block reads
        now: open while still claimed, and handed back to the person once the
        reading no longer holds it (`working_on`), else as its close reads, a
        person's Done meanwhile among them; none where the run was given
        none."""
        named = self._named(run_id, ClaimAssignment, claims.standing())
        if not named:
            return []
        held = self._held(named)
        lines = ["The claimed actions given to this work item, as they stand:"]
        for document_id, path, block_id, block in named:
            if block.claimed and block_id not in held:
                said = f"{block.local_id} open, claimed, {HANDED_BACK}"
            elif block.claimed:
                said = f"{block.local_id} open, claimed"
            elif not block.answered:
                said = f"{block.local_id} open, its claim gone"
            else:
                said = _block_line(block, dsl.AGENT)
            lines.append(f"- {path} ({document_id}) {said}")
        return lines

    def _researched(self, run_id: uuid.UUID) -> list[str]:
        """The blocks whose standing Research Assignment names the run
        `run_id` or a work item on its conversation (DB 292), as a claim's
        are given (`_given`), for the pass to route on what the run found
        (F52.3), in timeline order, each as its block reads now: open while
        unanswered, and handed back to the person once the reading no longer
        holds it (`working_on`), a claim since among them, else as its close
        reads; none where the run researched none."""
        named = self._named(run_id, ResearchAssignment, researches.standing())
        if not named:
            return []
        held = self._held(named)
        lines = ["The blocks this work item researched, as they stand:"]
        for document_id, path, block_id, block in named:
            if block.claimed:
                said = f"{block.local_id} open, claimed"
            elif not block.answered and block_id not in held:
                said = f"{block.local_id} open, {HANDED_BACK}"
            elif not block.answered:
                said = f"{block.local_id} open"
            else:
                said = _block_line(block, dsl.AGENT)
            lines.append(f"- {path} ({document_id}) {said}")
        return lines

    def _named(
        self,
        run_id: uuid.UUID,
        assignment: type[ClaimAssignment | ResearchAssignment],
        standing: Select[int, uuid.UUID],
    ) -> list[tuple[uuid.UUID, str, int, dsl.Block]]:
        """The Blocks of `assignment` whose standing naming, of `standing`,
        names the run `run_id` or a work item on its conversation, in
        timeline order, each with its document's id and path and its own
        id, as its published text reads it now."""
        conversation = self.db.get_one(AgentSession, run_id).conversation_id
        runs = (
            [run_id]
            if conversation is None
            else select(AgentSession.id).where(
                AgentSession.conversation_id == conversation
            )
        )
        latest = standing.where(
            assignment.block_id.in_(
                select(assignment.block_id).where(assignment.work_id.in_(runs))
            )
        ).subquery()
        document_item = aliased(Item)
        rows = self.db.execute(
            select(
                Document.id,
                Document.path,
                Document.published_text,
                Block.id,
                Block.local_id,
            )
            .join(Block, Block.document_id == Document.id)
            .join(latest, latest.c.block_id == Block.id)
            .join(document_item, document_item.id == Document.id)
            .where(latest.c.work_id.in_(runs))
            .order_by(document_item.seq, Block.position)
        ).all()
        named = []
        for document_id, path, text, block_id, local_id in rows:
            # A named block is of a registered document read, or of an item of
            # Pilot's own, born published.
            assert text is not None
            block = next(
                block for block in dsl.parse(text).blocks if block.local_id == local_id
            )
            named.append((document_id, path, block_id, block))
        return named

    def _held(self, named: Sequence[tuple[uuid.UUID, str, int, dsl.Block]]) -> set[int]:
        """The ids of the `named` Blocks the reading holds: the others it
        handed back to the person (`working_on.holds`)."""
        return set(
            holds(Reading(self.db), {document_id for document_id, *_ in named}).held
        )

    def _run_line(self, run_id: uuid.UUID, *, last_line: bool) -> str:
        """The work item's line: its title and id, the plan's task it serves,
        its repository, environment and controller session, each that it
        has, its turn's end and, where `last_line`, its last line, the text
        its turn ended with."""
        item = self.db.get_one(Item, run_id)
        session = self.db.get_one(AgentSession, run_id)
        repo = self.db.get_one(Work, run_id).repo
        # A worker's run whose job is placed is done at its turn's end.
        assert item.done_at is not None
        task = (
            None
            if item.plan_task_id is None
            else self.db.scalar(
                select(PlanTask.title).where(
                    PlanTask.project_id == item.project_id,
                    PlanTask.task_id == item.plan_task_id,
                )
            )
        )
        facts = [
            f'The work item: "{item.title}" ({item.id})',
            None if item.plan_task_id is None else f'task {item.plan_task_id} "{task}"',
            None if repo is None else f"repository {repo}",
            None
            if session.environment_id is None
            else f"environment {session.environment_id}",
            None
            if session.controller_session is None
            else f"session {session.controller_session}",
        ]
        line = ", ".join(fact for fact in facts if fact is not None)
        line += f"; its turn ended {utc_time(item.done_at)}"
        last = self._last_line(run_id) if last_line else None
        if last is not None:
            line += f' — the item\'s last line: "{last}"'
        return f"{line}."

    def _registered_nothing(self, run_id: uuid.UUID) -> list[str]:
        """That the run registered nothing, and where its turn ended with
        text, the whole of it, quoted: a finding the worker stated only there
        is all the pass, or `/plan` where the job opens on it, has to go on
        (P-291)."""
        lines = [line.rstrip() for line in self._final_text(run_id).splitlines()]
        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()
        if not lines:
            return ["Registered nothing this run."]
        return [
            "Registered nothing this run. Its final message, whole:",
            *(f"> {line}" if line else ">" for line in lines),
        ]

    def _final_text(self, run_id: uuid.UUID) -> str:
        """The text the run's turn ended with, its `result` record's; empty
        when it ended with none."""
        # A run done at its turn's end has its `result` record.
        (result,) = read_records(
            self.db, run_id, kind=RecordKind.RESULT, limit=1, newest_first=True
        )
        text = result.record.payload.get("result")
        return text if isinstance(text, str) else ""

    def _last_line(self, run_id: uuid.UUID) -> str | None:
        """The last line of the text the run's turn ended with; None when it
        ended with none."""
        lines = [
            line.strip()
            for line in self._final_text(run_id).splitlines()
            if line.strip()
        ]
        return lines[-1] if lines else None

    def _read_failures(self, run_id: uuid.UUID, registered: int) -> dict[str, str]:
        """Why each turn-end read of the run's `registered` documents that
        failed did, by the document's id, as its `server` record gives it: one
        per document at most."""
        return {
            stored.record.payload["item"]: stored.record.payload["reason"]
            for stored in read_records(
                self.db,
                run_id,
                kind=RecordKind.SERVER,
                payload_type=READ_FAILED,
                limit=registered,
            )
        }

    def message_from(self, project: Project, person: User) -> str:
        """The line before `person`'s words naming them and whether they are
        a member of the project: the brief's, and a later Turn's whose
        chat's previous Turn with an author has another author (§5.3; DB
        decision 61, assertion 251)."""
        return f"The message, from {person.handle} ({self._standing(project, person)}):"

    def follow_up(self, held: Sequence[str]) -> str:
        """The server's turn after a brain session's turn that ended with its
        saves of `held` still held, paths from the tree's root as the engine's
        turn end returns them (§5.1; F79): each path with its faults as the
        hook's check prints them, then what to do."""
        lines = []
        for path in held:
            faults = ", ".join(
                f"`{_printed(path, line, message)}`"
                for line, message in self.db.execute(
                    select(SaveError.line, SaveError.message)
                    .where(
                        SaveError.path == path, SaveError.kind_code == ErrorKind.PARSE
                    )
                    .order_by(SaveError.id)
                )
            )
            lines.append(f"Your save of `{path}` is held: {faults}.")
        lines.append(FOLLOW_UP_END)
        return "\n".join(lines)

    def restarted(self, session: AgentSession) -> str:
        """The server's turn that carries on the work item `session`, its turn
        cut by its environment's restart (§9.6; F71): one line saying so and
        naming each document its run registered (`working_on.run_of`), in the
        order registered, with where it stands, then its brief again, whole: a
        clarification run's own first Turn, the questions it was placed with
        (DB 254), else its run's first work item's first Turn as sent, a
        continuation's own first Turn being no brief."""
        run = run_of(literal(session.id))
        documents = [
            f"{path} ({item_id}) — "
            + _where_it_stands(done=done, failed=failed, read=read, written_back=back)
            for item_id, path, done, failed, read, back in self.db.execute(
                select(
                    Item.id,
                    Document.path,
                    Item.done_at.is_not(None),
                    Document.read_failed_at.is_not(None),
                    Document.published_hash.is_not(None),
                    Document.written_back_at.is_not(None),
                )
                .join(Document, Document.id == Item.id)
                .where(
                    Item.created_by_session_id.in_(run),
                    Document.source_path.is_not(None),
                )
                .order_by(Item.seq)
            )
        ]
        registered = (
            f"The documents you registered: {'; '.join(documents)}."
            if documents
            else "You registered no documents."
        )
        first = (
            select(Turn.message)
            .join(Item, Item.id == Turn.session_id)
            .where(Turn.seq == 1)
        )
        brief = self.db.scalars(
            first.where(Item.id == session.id)
            if self.db.get(ClarificationRun, session.id) is not None
            else first.where(Item.id.in_(run)).order_by(Item.seq).limit(1)
        ).one()
        return f"{RESTARTED} {registered} Your brief again, whole:\n\n{brief}"

    def work_item(
        self,
        project: Project,
        brief: str,
        task: PlanTask | None,
        grants: str,
        branch: str,
    ) -> str:
        """A work item's first Turn (§5.4): `brief`, the brain's own text, then
        the server's trailer under one heading — the plan's task `task` it
        serves, the switch it is briefed under (F54.7) with `grants`, the
        text the store's grants file holds for that position, the work's
        topic branch `branch` written into it, and the project's handbook
        verbatim (F129.5), each line that holds."""
        lines = [TRAILER_HEADING]
        if task is not None:
            lines.append(
                f'- This work item serves plan task {task.task_id} "{task.title}":'
                f" write `step: {task.task_id}` into the front matter of every"
                " document you register."
            )
        lines.extend(
            [
                f"- Auto pilot is {'on' if project.autopilot else 'off'}, and these"
                " grants hold for this session:",
                grants.replace(TOPIC_BRANCH, branch),
            ]
        )
        handbook = self._handbook(project)
        if handbook is not None:
            lines.extend(["- The project's handbook:", handbook])
        return f"{brief.rstrip()}\n\n" + "\n".join(lines)

    def _handbook(self, project: Project) -> str | None:
        """The project's handbook as published; None where it is blank."""
        handbook = self.db.scalar(
            select(Document.published_text).where(
                Document.project_id == project.id,
                Document.role_code == DocumentRole.HANDBOOK,
            )
        )
        return handbook if handbook is not None and handbook.strip() else None

    def _pause(self, project: Project) -> str | None:
        if not project.paused:
            return None
        since = self.db.scalar(
            select(func.max(ProjectTransition.at)).where(
                ProjectTransition.project_id == project.id,
                ProjectTransition.kind_code == TransitionKind.PAUSED,
            )
        )
        # A project is paused by its `paused` transition alone.
        assert since is not None
        return (
            f"The project is paused since {utc_time(since)}: anything you start"
            " is held until it resumes — say so."
        )

    def _create_paused(self, project: Project) -> str | None:
        """The setup's line while Create's pause stands: the project paused,
        its latest pause Pilot's, since Pilot pauses a project at its Create
        alone and a resume ends that pause for good (D083); None otherwise,
        a person's pause included."""
        if not project.paused:
            return None
        by = self.db.scalars(
            select(User.kind_code)
            .join(ProjectTransition, ProjectTransition.by_user_id == User.id)
            .where(
                ProjectTransition.project_id == project.id,
                ProjectTransition.kind_code == TransitionKind.PAUSED,
            )
            .order_by(ProjectTransition.id.desc())
            .limit(1)
        ).one_or_none()
        if by is not UserKind.AGENT:
            return None
        return (
            "Create project paused the project: every work item you add is held"
            " until a person resumes it."
        )

    def _trigger_paused(self, project: Project, triggered: datetime) -> str | None:
        """§5.2's pause line of a job whose trigger at `triggered` came while
        the project was paused: that pause, from its start to the resume that
        let the job go on, and that the record moved on meanwhile (F141.4);
        None for one that came while it was not."""
        paused = self.db.scalars(
            select(ProjectTransition)
            .where(
                ProjectTransition.project_id == project.id,
                ProjectTransition.kind_code == TransitionKind.PAUSED,
                ProjectTransition.at <= triggered,
            )
            .order_by(ProjectTransition.id.desc())
            .limit(1)
        ).one_or_none()
        if paused is None:
            return None
        resumed = self.db.scalars(
            select(ProjectTransition)
            .where(
                ProjectTransition.project_id == project.id,
                ProjectTransition.kind_code == TransitionKind.RESUMED,
                ProjectTransition.id > paused.id,
            )
            .order_by(ProjectTransition.id)
            .limit(1)
        ).one_or_none()
        # The gate briefs no job while its project is paused.
        assert resumed is not None
        if resumed.at <= triggered:
            return None
        return (
            f"Paused {utc_time(paused.at)} to {utc_time(resumed.at)}: this job's"
            " trigger happened while the project was paused; the record moved on"
            " meanwhile."
        )

    def _finish(self, project: Project) -> str:
        finished = self.db.scalar(
            select(func.max(ProjectTransition.at)).where(
                ProjectTransition.project_id == project.id,
                ProjectTransition.kind_code == TransitionKind.FINISHED,
            )
        )
        # A project is finished by its `finished` transition alone.
        assert finished is not None
        return (
            f"This project is finished ({utc_time(finished)}): you read only — no"
            " `pilot-store`, nothing under `/work` you can write. Answer from the"
            " tree, the records and the fleet tools; what you would change, say so"
            " and name who can."
        )

    def _state(
        self,
        project: Project,
        job: Work | None = None,
        returns: Collection[str] | None = None,
    ) -> list[Group]:
        """The project's state as the record holds it when the brief is
        composed, each part as `pilot.py` prints its listing, so that the
        brain meets one shape whichever it reads: a job's seqs (`_seqs`);
        the plan's tasks not done, with their status; the open items; every
        open note whole, then, for a job on the tasks `returns`, the notes it
        returns to, those tasks' and the plan's own (F57.4), and the
        deferrals without a home (F79.3; DB 214), which a finished project's
        leaves out, its sessions reading only (F5.5); then the handbook
        whole."""
        notes = self._open_notes(project)
        noted: list[str | None] = [*self._noted(notes)]
        if returns is not None:
            noted.append(_return_list(notes, returns))
        if project.state_code is not ProjectState.FINISHED:
            noted.extend(self._homeless(project))
        handbook = self._handbook(project)
        return [
            [] if job is None else [self._seqs(job)],
            self._tasks(project, notes),
            self._open_items(project),
            noted,
            [] if handbook is None else [HANDBOOK_HEADING, handbook.rstrip()],
        ]

    def _seqs(self, job: Work) -> str:
        """The job's own seq and that of the item its trigger names: its
        trigger Item, an offer's the item its Pilot Note is on; the setup's
        names none."""
        own = self.db.get_one(Item, job.id).seq
        named = job.trigger_item_id
        if job.trigger_note_id is not None:
            named = self.db.get_one(PilotNote, job.trigger_note_id).item_id
        if named is None:
            return f"This job is seq {own} on the timeline."
        return (
            f"This job is seq {own} on the timeline; the item its trigger names,"
            f" seq {self.db.get_one(Item, named).seq}."
        )

    def _tasks(self, project: Project, notes: Sequence[PlanNote]) -> list[str]:
        """The plan's tasks not done, in its order, each with its status and
        its open notes' ids, as `pilot.py plan task list` prints them."""
        lines = []
        for task in self.db.scalars(
            select(PlanTask)
            .where(
                PlanTask.project_id == project.id,
                PlanTask.removed_at.is_(None),
                PlanTask.status_code != TaskStatus.DONE,
            )
            .order_by(PlanTask.position)
        ):
            line = f"{task.task_id} · {task.status_code.value} · {task.title}"
            ids = [note.note_id for note in notes if note.plan_task_id == task.task_id]
            if ids:
                line += " · notes " + ", ".join(ids)
            lines.append(line)
        return [TASKS_HEADING, *lines] if lines else []

    def _open_items(self, project: Project) -> list[str]:
        """The project's open items, as `pilot.py items list --open` prints
        them (`_item_lines`)."""
        lines = self._item_lines(Item.project_id == project.id, Item.done_at.is_(None))
        return [ITEMS_HEADING, *lines] if lines else []

    def _item_lines(self, *where: ColumnElement[bool]) -> list[str]:
        """The items `where` holds for, in timeline order, each as `pilot.py
        items list` prints it from `timeline.json` (`ViewService.timeline`):
        seq, kind, title, open or its close, its addressee and its step,
        urgent, a wait's watch and firings, a closed wait's or work item's
        note, its document's path, none before its text is read, and its
        id."""
        closer = aliased(User)
        rows = self.db.execute(
            select(
                Item,
                Document.path,
                Document.published_hash,
                User.handle,
                closer.handle,
                Wait,
                Work.done_note,
            )
            .outerjoin(Document, Document.id == Item.id)
            .outerjoin(User, User.id == Item.for_user_id)
            .outerjoin(closer, closer.id == Item.done_by_user_id)
            .outerjoin(Wait, Wait.id == Item.id)
            .outerjoin(Work, Work.id == Item.id)
            .where(*where)
            .order_by(Item.seq)
        ).all()
        fired = {
            wait_id: (count, pending)
            for wait_id, count, pending in self.db.execute(
                select(
                    WaitFiring.wait_id,
                    func.count(),
                    func.count().filter(WaitFiring.job_id.is_(None)),
                )
                .where(
                    WaitFiring.wait_id.in_(
                        [row.Wait.id for row in rows if row.Wait is not None]
                    )
                )
                .group_by(WaitFiring.wait_id)
            )
        }
        lines = []
        for item, path, published, handle, done_by, wait, work_note in rows:
            parts = [str(item.seq), item.kind_code, item.title or "(no title)"]
            if item.done_at is None:
                parts.append("open")
            else:
                by = "" if done_by is None else f" by {done_by}"
                parts.append(
                    f"done {utc_time(item.done_at)} ({item.done_cause_code}{by})"
                )
            if handle is not None:
                parts.append(f"for {handle}")
            if item.plan_task_id is not None:
                parts.append(f"step {item.plan_task_id}")
            if item.urgent:
                parts.append("urgent")
            if wait is not None:
                count, pending = fired.get(wait.id, (0, 0))
                parts.extend(
                    _watched(wait, count, pending if item.done_at is None else 0)
                )
            note = work_note if wait is None else wait.done_note
            if item.done_at is not None and note is not None:
                parts.append(f"note: {' '.join(note.split())}")
            parts.append("no document" if published is None else path)
            parts.append(str(item.id))
            lines.append(" · ".join(parts))
        return lines

    def _open_notes(self, project: Project) -> list[PlanNote]:
        """The project's open plan notes: the tasks' in the plan's order,
        then the plan's own, each in the order made."""
        return list(
            self.db.scalars(
                select(PlanNote)
                .outerjoin(
                    PlanTask,
                    (PlanTask.project_id == PlanNote.project_id)
                    & (PlanTask.task_id == PlanNote.plan_task_id),
                )
                .where(PlanNote.project_id == project.id, PlanNote.deleted_at.is_(None))
                .order_by(
                    PlanNote.plan_task_id.is_(None),
                    PlanTask.position.nulls_last(),
                    PlanNote.id,
                )
            )
        )

    def _noted(self, notes: Sequence[PlanNote]) -> list[str]:
        """The open notes whole, as `pilot.py plan note list` prints them:
        each its id, its task or the plan, and its summary, then its content
        and each block it names, with its item's title and its answer as it
        stands, indented under it."""
        refs: dict[int, list[str]] = {}
        parsed: dict[uuid.UUID, dsl.ParsedDocument] = {}
        for note_id, local_id, item_id, title, text in self.db.execute(
            select(
                PlanNoteReference.plan_note_id,
                Block.local_id,
                Item.id,
                Item.title,
                Document.published_text,
            )
            .join(Block, Block.id == PlanNoteReference.block_id)
            .join(Document, Document.id == Block.document_id)
            .join(Item, Item.id == Document.id)
            .where(PlanNoteReference.plan_note_id.in_([note.id for note in notes]))
            .order_by(Block.id)
        ):
            # A Block is of its Document's published text (DB §7.4).
            assert text is not None
            if item_id not in parsed:
                parsed[item_id] = dsl.parse(text)
            document = parsed[item_id]
            block = next(
                block for block in document.blocks if block.local_id == local_id
            )
            refs.setdefault(note_id, []).append(
                f"    {item_id}/{local_id} · {title or document.title or '(no title)'}"
                f" · {_answer_line(block)}"
            )
        lines = []
        for note in notes:
            on = "plan" if note.plan_task_id is None else note.plan_task_id
            lines.append(f"{note.note_id} · {on} · {note.summary}")
            lines.extend(f"    {line}" for line in note.content.splitlines())
            lines.extend(refs.get(note.id, []))
        return [NOTES_HEADING, *lines] if lines else []

    def _homeless(self, project: Project) -> list[str]:
        """The deferrals without a home, as the hook's check prints them
        (F79.3; DB 214)."""
        homeless = self.plan_service.homeless_deferrals(project)
        if not homeless:
            return []
        return [
            HOMELESS_HEADING,
            *(
                f"- {deferral.block} in {deferral.document}"
                f" ({deferral.title or ''}), to: {deferral.to}"
                for deferral in homeless
            ),
        ]

    def quoted(self, item_id: uuid.UUID | None, block_id: int | None) -> list[str]:
        """The item a project chat's message quotes, a Turn's quote by
        `item_id` or by its block `block_id`, as it stands when the message
        is sent: its line as `pilot.py items list` prints it, open or closed
        (`_item_lines`), then each of its blocks with its section's heading
        and its answer as it stands, who gave it among it (`_answer_line`).
        Nothing where the message quotes nothing, or a block of no item, a
        draft's."""
        heading = QUOTED_HEADING
        if block_id is not None:
            block = self.db.get_one(Block, block_id)
            item_id = self.db.scalar(
                select(Item.id).where(Item.id == block.document_id)
            )
            heading = QUOTED_BLOCK_HEADING.format(block=block.local_id)
        if item_id is None:
            return []
        (line,) = self._item_lines(Item.id == item_id)
        text = self.db.scalar(
            select(Document.published_text).where(Document.id == item_id)
        )
        blocks = [] if text is None else dsl.parse(text).blocks
        return [
            heading,
            line,
            *(
                " · ".join(
                    [
                        block.local_id,
                        block.kind,
                        *([] if block.section is None else [block.section.heading]),
                        _answer_line(block),
                    ]
                )
                for block in blocks
            ),
        ]

    def _changed(self, project: Project, closed: datetime | None) -> list[str]:
        """What changed in the record since the project's chat that closed at
        `closed`, oldest first, each by the time the record keeps for it, as
        no log of it is kept: an item added and one closed, a block of an
        item answered or done, a plan note added and one struck, and the
        project paused or resumed. A task's status move is none of them: no
        time dates one. Nothing with no chat closed before, or nothing
        changed since."""
        if closed is None:
            return []
        changes: list[tuple[datetime, int, str]] = []
        closer = aliased(User)
        for item, done_by in self.db.execute(
            select(Item, closer.handle)
            .outerjoin(closer, closer.id == Item.done_by_user_id)
            .where(
                Item.project_id == project.id,
                (Item.created_at > closed) | (Item.done_at > closed),
            )
            .order_by(Item.seq)
        ):
            named = f"{item.kind_code} · {item.title or '(no title)'}"
            if item.created_at > closed:
                changes.append((item.created_at, 0, f"item {item.seq} added · {named}"))
            if item.done_at is not None and item.done_at > closed:
                by = "" if done_by is None else f" by {done_by}"
                changes.append(
                    (
                        item.done_at,
                        2,
                        f"item {item.seq} closed ({item.done_cause_code}{by})"
                        f" · {named}",
                    )
                )
        for block, seq, kind, title, by in self.db.execute(
            select(Block, Item.seq, Item.kind_code, Item.title, User.handle)
            .join(Item, Item.id == Block.document_id)
            .outerjoin(User, User.id == Block.answered_by_user_id)
            .where(
                Item.project_id == project.id,
                (Block.answered_at > closed) | (Block.done_at > closed),
            )
            .order_by(Item.seq, Block.position)
        ):
            named = f"{kind} · {title or '(no title)'}"
            given = "" if by is None else f" by {by}"
            if block.answered_at is not None and block.answered_at > closed:
                changes.append(
                    (
                        block.answered_at,
                        1,
                        f"item {seq}'s {block.local_id} answered{given} · {named}",
                    )
                )
            if block.done_at is not None and block.done_at > closed:
                changes.append(
                    (
                        block.done_at,
                        1,
                        f"item {seq}'s {block.local_id} done{given} · {named}",
                    )
                )
        for note in self.db.scalars(
            select(PlanNote)
            .where(
                PlanNote.project_id == project.id,
                (PlanNote.created_at > closed) | (PlanNote.deleted_at > closed),
            )
            .order_by(PlanNote.id)
        ):
            on = (
                "the plan" if note.plan_task_id is None else f"task {note.plan_task_id}"
            )
            if note.created_at > closed:
                changes.append(
                    (
                        note.created_at,
                        3,
                        f"note {note.note_id} added on {on} · {note.summary}",
                    )
                )
            if note.deleted_at is not None and note.deleted_at > closed:
                changes.append(
                    (
                        note.deleted_at,
                        4,
                        f"note {note.note_id} struck on {on} · {note.summary}",
                    )
                )
        for transition, at, by in self.db.execute(
            select(ProjectTransition.kind_code, ProjectTransition.at, User.handle)
            .join(User, User.id == ProjectTransition.by_user_id)
            .where(
                ProjectTransition.project_id == project.id,
                ProjectTransition.kind_code.in_(
                    [TransitionKind.PAUSED, TransitionKind.RESUMED]
                ),
                ProjectTransition.at > closed,
            )
            .order_by(ProjectTransition.id)
        ):
            changes.append((at, 5, f"the project {transition} by {by}"))
        if not changes:
            return []
        changes.sort(key=lambda change: change[:2])
        return [
            CHANGED_HEADING,
            *(f"{utc_time(at)} · {what}" for at, _, what in changes),
        ]

    def _standing(self, project: Project, person: User) -> str:
        member = self.db.scalar(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == person.id,
                ProjectMember.left_at.is_(None),
            )
        )
        return "not a member" if member is None else "member"


def _earlier_chats(closed: datetime | None) -> str | None:
    """The line naming `chat.md` and the project's latest chat to close, at
    `closed`; None while none has."""
    if closed is None:
        return None
    return (
        "Earlier chats of this project are in chat.md; the latest closed"
        f" {utc_time(closed)}."
    )


def _frame(
    skill: str, kind: str, project: Project, at: datetime, *groups: Group
) -> str:
    """§5.2's frame: the skill line alone, so that Claude Code loads the skill
    and hands it the rest; the kind, the project and the stamp in one line;
    then each group that holds a line, a blank line between two."""
    head = " · ".join(
        part
        for part in (
            "Pilot's brief",
            kind,
            None if project.name is None else f'project "{project.name}"',
            project_folder(project),
            utc_time(at),
        )
        if part is not None
    )
    blocks = [skill, head]
    for group in groups:
        lines = [line for line in group if line is not None]
        if lines:
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


CONVERSATION_KIND_LINE = "a conversation with a session in"
"""How the kind of a Conversation's brief opens, which the store's map reads
its skill and its frame from (§5.3)."""


def conversation_kind(environment: Environment, caller_session: str | None) -> str:
    """The kind of a Conversation's brief (§5.3): its caller, as `chat.md`
    names it too."""
    return f"{CONVERSATION_KIND_LINE} {caller_named(environment, caller_session)}"


BY_A_CALL = "Started by a call"

_DRAFT_BY_A_CALL = re.compile(
    rf"^The draft: project\.md(?:, empty)?\. ({BY_A_CALL}.*)$", re.MULTILINE
)
"""The draft's line of a definition chat's brief by a call, the sentence
naming the call its group."""


def _by_a_call(call: Call | None) -> str:
    """Who started a call's draft, in place of the person who started one
    from the plus (§5.3): the call, from its environment and for its person,
    each as far as `call` names it."""
    said = BY_A_CALL
    if call is not None and call.environment is not None:
        said += f" from {call.environment}"
    if call is not None and call.for_handle is not None:
        said += f", for {call.for_handle}"
    return f"{said}."


def _started_by_a_call(brief: str) -> str:
    """The sentence naming the call in `brief`, the first brief of a call's
    draft (`_by_a_call`), its environment and its person as that brief named
    them, which its words alone hold (DB decision 77). The frame's line
    comes before the call's words, so the first match is the frame's."""
    named = _DRAFT_BY_A_CALL.search(brief)
    # The call's Turn is the definition chat's brief by a call.
    assert named is not None
    return named[1]


def is_follow_up(turn: Turn) -> bool:
    """Whether the Turn is the server's follow-up (`BriefService.follow_up`)."""
    return turn.author_user_id is None and turn.message.endswith(FOLLOW_UP_END)


def is_restarted(turn: Turn) -> bool:
    """Whether the Turn is the server's after a work item's restart
    (`BriefService.restarted`)."""
    return turn.author_user_id is None and turn.message.startswith(RESTARTED)


def _where_it_stands(
    *, done: bool, failed: bool, read: bool, written_back: bool
) -> str:
    """Where a registered document stands, as the restart's line names it."""
    if done:
        return "closed and written back in place" if written_back else "closed"
    if failed:
        return "open, its read failed"
    return "published, open" if read else "registered, not read yet"


def _answered(block: dsl.Block, when: str) -> str:
    """A one-ask item's block as its close reads: its answer or its Done, by
    whom and when, then its `via` and its note as given, a confirmation's No
    its reason, an action's Done what was pasted back."""
    if block.done is not None:
        line = f"{block.local_id} done by {block.by} at {when}"
    elif block.confirmation:
        line = f"answered {_said(block)} by {block.by} at {when}"
    else:
        line = f"{block.local_id} answered {_said(block)} by {block.by} at {when}"
    if _given(block.via):
        line += f" (via {block.via})"
    return line + _noted(block)


def _block_line(block: dsl.Block, closer: str) -> str:
    """A closed document's block as it reads: its answer or its Done, then
    who gave it where that is not `closer`, the Done's person, and its `via`
    as given, and its note."""
    said = "done" if block.done is not None else _said(block)
    facts = [
        None if block.by in (None, closer) else f"by {block.by}",
        f"via {block.via}" if _given(block.via) else None,
    ]
    given = ", ".join(fact for fact in facts if fact is not None)
    line = f"{block.local_id} {said}" + (f" ({given})" if given else "")
    return line + _noted(block)


def _given(via: str | None) -> bool:
    """Whether a block's `via` is in its file: the app's is the line's
    absence (FM §4)."""
    return via is not None and via != dsl.AnswerChannel.APP


def _said(block: dsl.Block) -> str:
    """A block's answer as the file holds it: `deferred` with its `to`; a
    question's words quoted; an option's label, a confirmation's Yes or No
    and a proposal's Agree as they are; any other words quoted, as Other's
    (F17.2)."""
    answer = block.answer
    # A closed block that is not done is answered.
    assert answer is not None
    if answer == dsl.DEFERRED:
        return f"deferred to {block.to}"
    if block.kind is dsl.BlockKind.QUESTION:
        return f'"{answer}"'
    if (
        block.confirmation
        or answer in {option.label for option in block.options}
        or (not block.options and answer == dsl.recommendation(block))
    ):
        return answer
    return f'"{answer}" (Other)'


def _noted(block: dsl.Block) -> str:
    """A block's note as given: a confirmation's No's reason, an action's
    Done's paste-back, else its note."""
    if block.note is None:
        return ""
    if block.done is not None:
        return f', pasted back: "{block.note}"'
    if block.confirmation:
        return f', its reason: "{block.note}"'
    return f', note: "{block.note}"'


def _wait_line(item: Item, wait: Wait) -> str:
    """The wait's line: its title and id, what it waits on, since when, and
    the plan's task it serves."""
    if wait.kind_code == CARD_WAIT:
        # A card wait has its two lists (DB 186, 187).
        assert wait.cards is not None and wait.states is not None
        on = f"a card wait on {', '.join(wait.cards)} for {', '.join(wait.states)}"
    else:
        # A timed wait has its due time (`ck_waits_halves`).
        assert wait.due_at is not None
        on = f"a timed wait due {utc_time(wait.due_at)}"
    line = (
        f'The wait: "{item.title}" ({item.id}), {on};'
        f" waiting since {utc_time(item.created_at)}"
    )
    if item.plan_task_id is not None:
        line += f"; task {item.plan_task_id}"
    return f"{line}."


def _task_of(item: Item) -> list[str]:
    """The tasks whose notes a job on `item` returns to beside the plan's
    own: the one the item names, none where it names none (F57.4)."""
    return [] if item.plan_task_id is None else [item.plan_task_id]


def _return_list(notes: Sequence[PlanNote], tasks: Collection[str]) -> str | None:
    """The line naming the open notes a job on `tasks` returns to (F57.4):
    those tasks' and the plan's own, in `notes`' order; None for none."""
    returned = [
        note.note_id
        for note in notes
        if note.plan_task_id is None or note.plan_task_id in tasks
    ]
    if not returned:
        return None
    whose = (
        f"the open notes of task {', '.join(tasks)} and the plan's own"
        if tasks
        else "the plan's own open notes"
    )
    return f"Your return list, {whose}: {', '.join(returned)}."


def _answer_line(block: dsl.Block) -> str:
    """A block's answer as it stands, as `pilot.py plan note list` prints
    it: `answer: v4 by ada`, `answer: deferred → t5 by agent`, `done: <at>
    by ada`, its `via` where given, or `no answer`."""
    parts = []
    if block.answer is not None:
        parts.append(
            f"answer: {block.answer}" + ("" if block.to is None else f" → {block.to}")
        )
    if block.done is not None:
        parts.append(f"done: {utc_time(block.done)}")
    if not parts:
        return "no answer"
    line = " · ".join(parts)
    if block.by is not None:
        line += f" by {block.by}"
    if _given(block.via):
        line += f" via {block.via}"
    return line


def _watched(wait: Wait, fired: int, pending: int) -> list[str]:
    """A wait's part of its item's line, as `pilot.py items list` prints
    it: when it is due or what it watches, then its firings counted and the
    `pending` no run has taken yet, a closed wait's line given none."""
    if wait.due_at is not None:
        on = f"due {utc_time(wait.due_at)}"
    else:
        # A card wait has its two lists (DB 186, 187).
        assert wait.cards is not None and wait.states is not None
        on = f"on {', '.join(wait.cards)} for {', '.join(wait.states)}"
    count = f"{fired} firing{'' if fired == 1 else 's'}" if fired else "no firings"
    if pending:
        count += f", {pending} pending"
    return [on, count]


def _fired(
    wait: Wait,
    firing: WaitFiring,
    transition: CardTransition | None,
    by: str | None,
) -> str:
    """What fired the wait: the card's transition, by whom where the tracker
    names someone; its due time; or a person's request, by its button's name
    (DB 193)."""
    # A firing's cause has its own (`ck_wait_firings_cause`, DB 193).
    if firing.cause_code is FiringCause.TRANSITION:
        assert transition is not None
        moved = (
            f"{transition.card} → {transition.to_state}"
            if transition.from_state is None
            else f"{transition.card}: {transition.from_state} → {transition.to_state}"
        )
        return moved if transition.by is None else f"{moved}, by {transition.by}"
    if firing.cause_code is FiringCause.DUE:
        assert wait.due_at is not None
        return f"due {utc_time(wait.due_at)} — fired at its due time"
    assert by is not None
    return f"the operator's request ({REQUESTS[wait.kind_code]}), by {by}"


def _retried(db: Session, work: Work) -> list[uuid.UUID]:
    """The job and every job its Retries retry, in their chain."""
    chain = [work.id]
    while (
        earlier := db.scalar(select(Work.id).where(Work.retried_by_id == chain[-1]))
    ) is not None:
        chain.append(earlier)
    return chain


def _files(count: int) -> str:
    """The attachments a draft's brief counts, which `timeline.json` lists."""
    if count == 0:
        return "none"
    if count == 1:
        return "1 file (timeline.json lists it)"
    return f"{count} files (timeline.json lists them)"


def _printed(path: str, line: int | None, message: str) -> str:
    """A fault as the hook's check prints it (`pilot-sync`'s `render`)."""
    return f"{path}: {message}" if line is None else f"{path}:{line}: {message}"


def switch_grants(source: str) -> Mapping[bool, str] | None:
    """A worker's grants text by the position of the switch, auto pilot on or
    off, as `source`, the store's grants file, holds it: under
    `GRANTS_SECTION`, the fenced block right under each label of
    `SWITCH_LABELS`, a position with no block or an empty one left out. None
    where the file has no such section."""
    section = _GRANTS_SECTION.search(source)
    if section is None:
        return None
    grants: dict[bool, str] = {}
    for label, text in _GRANTS_BLOCK.findall(section.group(1)):
        if text.strip():
            grants.setdefault(label == SWITCH_LABELS[True], text.rstrip("\n"))
    return grants


def topic_branch(project: Project, task: PlanTask | None, title: str) -> str | None:
    """The topic branch of a work item titled `title`, `TOPIC_BRANCH`: the
    project's folder, its slug, then the id of the plan's task `task` it
    serves, or its title in kebab case where it serves none. None where such
    a title holds no letter or digit."""
    name = (
        task.task_id
        if task is not None
        else "-".join(re.findall(r"[^\W_]+", title.lower()))
    )
    return f"pilot/{folder(project)}/{name}" if name else None


def _switch(project: Project) -> str:
    """The state the session is briefed under, which it keeps (F54.7)."""
    if project.autopilot:
        return (
            "Auto pilot: on — the granted column holds for this session"
            " (rules/grants.md)."
        )
    return (
        "Auto pilot: off — the granted column asks for this session (rules/grants.md)."
    )
