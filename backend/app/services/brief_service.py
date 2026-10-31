"""The brief a brain session's first Turn carries (design 3 §5): one frame,
the server's, Markdown, in one order (§5.2), and a renderer per kind (§5.3);
the server's trailer on the brief the brain writes a worker (§5.4); and the
follow-up turn of a brain session whose turn ended with a save of its own
still held (§5.1; F79).

A line that does not hold is left out, never written as "none", so that a
brief reads as the facts of its session. A brain's carries what the tree does
not hold and names what it does: nothing of the handbook, which every skill
but `create` reads itself (D058). A worker's carries the handbook verbatim,
the worker having no tree (F129.5).
"""

import uuid
from collections.abc import Collection, Sequence
from datetime import datetime

import pilot_dsl as dsl
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.engine.claims import standing
from app.engine.documents import OPENING, REVIEW
from app.engine.paths import draft_folder
from app.engine.plan import PlanService
from app.engine.record import ANSWERED
from app.engine.views import utc_time
from app.models import (
    Attachment,
    Block,
    Chat,
    ClaimAssignment,
    ClarificationRun,
    Document,
    Item,
    ItemAttachment,
    PlanNote,
    PlanTask,
    Project,
    ProjectMember,
    ProjectTransition,
    SaveError,
    Turn,
    User,
    Work,
)
from app.models import Session as AgentSession
from app.models.reference import (
    DocumentRole,
    ErrorKind,
    ProjectState,
    RecordKind,
    TransitionKind,
    WorkTrigger,
)
from app.services.clarification_service import Clarification, of_pass
from app.services.session_record_service import read_records
from app.services.session_scope import project_folder
from app.services.turn_end_read_service import READ_FAILED

CHAT_SKILL = "/chat"
CREATE_SKILL = "/create"
PLAN_SKILL = "/plan"
PRE_RULE_SKILL = "/pre-rule"

NOTES_HEADING = (
    "Open plan notes, by summary (the content and the blocks a read away in"
    " plan.json; `pilot.py plan note list`):"
)

TRAILER_HEADING = "From Pilot:"

FOLLOW_UP_END = "Fix it and end your turn."
"""The last line of the server's follow-up turn, which marks it as one."""

HOMELESS_HEADING = (
    "Deferrals without a home (a note names none of these blocks — write one,"
    " or answer the block anew in a new item):"
)

ASKS_NOTHING = (
    "This pass asks nothing: what is still unclear is the operator's, the"
    " clarification beside the ask."
)
"""The last line of the writer-answered brief (design 3 §5.3; DB 256)."""

type Group = Sequence[str | None]
"""Lines of a brief kept together; one that does not hold is None."""


class BriefService:
    """Composes the briefs of the brain's sessions from the record."""

    def __init__(self, db: Session, plan_service: PlanService) -> None:
        self.db = db
        self.plan_service = plan_service

    def project_chat(
        self, project: Project, person: User, words: str, at: datetime
    ) -> str:
        """The first Turn of a project's chat (§5.3), sent at `at`: `/chat`,
        the switch, the pause while the project is paused, every open plan
        note by summary and the deferrals without a home, the latest closed
        chat, then `person`'s `words` verbatim, which it ends with (DB
        assertion 251). A finished project's has the finish line in place of
        the switch and no notes (F5.5)."""
        message = [self.message_from(project, person), words]
        if project.state_code is ProjectState.FINISHED:
            return _frame(
                CHAT_SKILL,
                "a finished project's chat",
                project,
                at,
                [self._finish(project)],
                [self._earlier_chats(project)],
                message,
            )
        return _frame(
            CHAT_SKILL,
            "the project's chat",
            project,
            at,
            [_switch(project), self._pause(project)],
            self._notes(project, None),
            [self._earlier_chats(project)],
            message,
        )

    def definition_chat(
        self, project: Project, person: User, words: str, at: datetime
    ) -> str:
        """The first Turn of a draft's definition chat, from the plus (§5.3),
        sent at `at`: `/create`; no switch, no notes and no handbook, a
        draft having none (F141.2, F129.2); the draft, the person who started
        it and the attachments so far; then `person`'s `words` verbatim,
        which it ends with, after the line naming them when another person
        started the draft (DB decision 61)."""
        creator = self.db.get_one(User, project.created_by_user_id)
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
                f" The person who started it: {creator.handle}"
                f" ({self._standing(project, creator)}).",
                f"Attachments so far: {_files(attached or 0)}.",
            ],
            [
                "The message:"
                if person.id == creator.id
                else self.message_from(project, person),
                words,
            ],
        )

    def job(
        self, project: Project, work: Work, triggered: datetime, at: datetime
    ) -> str:
        """A job's first Turn (§5.3), composed at `at` as it leaves the queue
        or the pause, from the record as it then stands (F59), its trigger at
        `triggered`: the switch, the pause its trigger came in if it did
        (F141.4, `_trigger_paused`), then its trigger's payload and the notes
        it carries."""
        if work.trigger_code is WorkTrigger.WORKER_TURN_ENDED:
            # The job after a worker's turn names its run.
            assert work.trigger_item_id is not None
            clarification = self.db.get(ClarificationRun, work.trigger_item_id)
            if clarification is not None:
                return self._writer_answered(project, clarification, triggered, at)
            return self._worker_turn_ended(project, work.trigger_item_id, triggered, at)
        if work.trigger_code is WorkTrigger.ITEM_DONE:
            # The job after an item's close names the item.
            assert work.trigger_item_id is not None
            return self._item_done(project, work.trigger_item_id, triggered, at)
        # `JobService` places no job of a wait's firings.
        assert work.trigger_code is WorkTrigger.SETUP
        return self._setup(project, triggered, at)

    def _setup(self, project: Project, triggered: datetime, at: datetime) -> str:
        """The setup's (F49), triggered at Create project's instant, which
        opened the project and took its slug: `/plan`, then the draft's folder
        and the project's, the draft, the opening that holds the words that
        started it, and the plan, empty. No notes: its plan holds none. No
        pause line: the pause holds no setup (`setups`), and Create's pauses
        the project it opens (D083)."""
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
            [_switch(project)],
            [
                f"The project was created {utc_time(triggered)} from"
                f" {draft_folder(project)}; its folder is now"
                f" {project_folder(project)}.",
                f"The draft: project.md (the opening item {opening} holds the"
                " words that started it; the draft's copy and what the chat"
                " attached hang on it).",
                "The plan: plan.json, empty.",
            ],
        )

    def _worker_turn_ended(
        self, project: Project, run_id: uuid.UUID, triggered: datetime, at: datetime
    ) -> str:
        """The job after the turn of the worker's run `run_id` (design 3 D2):
        `/pre-rule`, then the work item's line, the documents the run
        registered in the order registered, each published or its read failed
        with the reason the read recorded, else that it registered nothing,
        the files attached on the work item, and the claimed actions it was
        given (`_given`); then every open note and the deferrals without a
        home, the pass's (F57.4)."""
        lines: list[str | None] = [self._run_line(run_id)]
        lines.extend(self._registered(run_id) or ["Registered nothing this run."])
        lines.append(self._attached(run_id))
        lines.extend(self._given(run_id))
        return _frame(
            PRE_RULE_SKILL,
            "a worker's turn ended",
            project,
            at,
            [_switch(project), self._trigger_paused(project, triggered)],
            lines,
            self._notes(project, None),
        )

    def _writer_answered(
        self,
        project: Project,
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
        registered, as any run's, and that this pass asks nothing; then every
        open note and the deferrals without a home."""
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
        return _frame(
            PRE_RULE_SKILL,
            "the writer answered",
            project,
            at,
            [_switch(project), self._trigger_paused(project, triggered)],
            lines,
            self._notes(project, None),
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
        self, project: Project, item_id: uuid.UUID, triggered: datetime, at: datetime
    ) -> str:
        """The job after a person's close of the item of Pilot's own
        `item_id` (DB decision 45): `/plan`, then the item and what was done
        to it, as the record holds it (`_closed`); then the open notes of the
        task the item names and the plan's own, the plan's alone where it
        names none, and the deferrals without a home (F57.4)."""
        item = self.db.get_one(Item, item_id)
        return _frame(
            PLAN_SKILL,
            "an item of yours is done",
            project,
            at,
            [_switch(project), self._trigger_paused(project, triggered)],
            [self._closed(item)],
            self._notes(
                project, [] if item.plan_task_id is None else [item.plan_task_id]
            ),
        )

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
        now: open while still claimed, else as its close reads, a person's
        Done meanwhile among them; none where the run was given none."""
        conversation = self.db.get_one(AgentSession, run_id).conversation_id
        runs = (
            [run_id]
            if conversation is None
            else select(AgentSession.id).where(
                AgentSession.conversation_id == conversation
            )
        )
        latest = (
            standing()
            .where(
                ClaimAssignment.block_id.in_(
                    select(ClaimAssignment.block_id).where(
                        ClaimAssignment.work_id.in_(runs)
                    )
                )
            )
            .subquery()
        )
        document_item = aliased(Item)
        rows = self.db.execute(
            select(Document.id, Document.path, Document.published_text, Block.local_id)
            .join(Block, Block.document_id == Document.id)
            .join(latest, latest.c.block_id == Block.id)
            .join(document_item, document_item.id == Document.id)
            .where(latest.c.work_id.in_(runs))
            .order_by(document_item.seq, Block.position)
        ).all()
        if not rows:
            return []
        lines = ["The claimed actions given to this work item, as they stand:"]
        for document_id, path, text, local_id in rows:
            # A claimed action is a block of a registered document read.
            assert text is not None
            block = next(
                block for block in dsl.parse(text).blocks if block.local_id == local_id
            )
            if block.claimed:
                said = f"{local_id} open, claimed"
            elif not block.answered:
                said = f"{local_id} open, its claim gone"
            else:
                said = _block_line(block, dsl.AGENT)
            lines.append(f"- {path} ({document_id}) {said}")
        return lines

    def _run_line(self, run_id: uuid.UUID) -> str:
        """The work item's line: its title and id, the plan's task it serves,
        its repository, environment and controller session, each that it
        has, its turn's end and its last line, the text its turn ended
        with."""
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
        last = self._last_line(run_id)
        if last is not None:
            line += f' — the item\'s last line: "{last}"'
        return f"{line}."

    def _last_line(self, run_id: uuid.UUID) -> str | None:
        """The last line of the text the run's turn ended with, its `result`
        record's; None when it ended with none."""
        # A run done at its turn's end has its `result` record.
        (result,) = read_records(
            self.db, run_id, kind=RecordKind.RESULT, limit=1, newest_first=True
        )
        text = result.record.payload.get("result")
        if not isinstance(text, str):
            return None
        lines = [line.strip() for line in text.splitlines() if line.strip()]
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

    def work_item(self, project: Project, brief: str, task: PlanTask | None) -> str:
        """A work item's first Turn (§5.4): `brief`, the brain's own text, then
        the server's trailer under one heading — the plan's task `task` it
        serves, the switch it is briefed under (F54.7) and the project's
        handbook verbatim (F129.5), each line that holds."""
        lines = [TRAILER_HEADING]
        if task is not None:
            lines.append(
                f'- This work item serves plan task {task.task_id} "{task.title}":'
                f" write `step: {task.task_id}` into the front matter of every"
                " document you register."
            )
        lines.append(
            "- Auto pilot is on: the grants above hold for this session."
            if project.autopilot
            else "- Auto pilot is off: the grants above ask the operator first for"
            " this session."
        )
        handbook = self.db.scalar(
            select(Document.published_text).where(
                Document.project_id == project.id,
                Document.role_code == DocumentRole.HANDBOOK,
            )
        )
        if handbook is not None and handbook.strip():
            lines.extend(["- The project's handbook:", handbook])
        return f"{brief.rstrip()}\n\n" + "\n".join(lines)

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

    def _notes(self, project: Project, tasks: Collection[str] | None) -> list[str]:
        """The open plan notes, by summary (F57.4): every one where `tasks` is
        None, else those of `tasks` and the plan's own; the tasks' in the
        plan's order and then the plan's own; then the deferrals without a
        home, as the hook's check prints them (F79.3; DB 214)."""
        lines: list[str] = []
        scope = PlanNote.project_id == project.id
        if tasks is not None:
            scope &= PlanNote.plan_task_id.is_(None) | PlanNote.plan_task_id.in_(tasks)
        for note, task_title in self.db.execute(
            select(PlanNote, PlanTask.title)
            .outerjoin(
                PlanTask,
                (PlanTask.project_id == PlanNote.project_id)
                & (PlanTask.task_id == PlanNote.plan_task_id),
            )
            .where(scope, PlanNote.deleted_at.is_(None))
            .order_by(
                PlanNote.plan_task_id.is_(None),
                PlanTask.position.nulls_last(),
                PlanNote.id,
            )
        ):
            on = (
                "the plan"
                if note.plan_task_id is None
                else f'{note.plan_task_id} "{task_title}"'
            )
            lines.append(f"- {on} · {note.note_id}: {note.summary}")
        if lines:
            lines.insert(0, NOTES_HEADING)
        homeless = self.plan_service.homeless_deferrals(project)
        if homeless:
            lines.append(HOMELESS_HEADING)
            lines.extend(
                f"- {deferral.block} in {deferral.document}"
                f" ({deferral.title or ''}), to: {deferral.to}"
                for deferral in homeless
            )
        return lines

    def _earlier_chats(self, project: Project) -> str | None:
        closed = self.db.scalar(
            select(func.max(Chat.closed_at)).where(Chat.project_id == project.id)
        )
        if closed is None:
            return None
        return (
            "Earlier chats of this project are in chat.md; the latest closed"
            f" {utc_time(closed)}."
        )

    def _standing(self, project: Project, person: User) -> str:
        member = self.db.scalar(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == person.id,
                ProjectMember.left_at.is_(None),
            )
        )
        return "not a member" if member is None else "member"


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


def is_follow_up(turn: Turn) -> bool:
    """Whether the Turn is the server's follow-up (`BriefService.follow_up`)."""
    return turn.author_user_id is None and turn.message.endswith(FOLLOW_UP_END)


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
