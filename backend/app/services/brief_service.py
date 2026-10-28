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

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine.documents import OPENING
from app.engine.paths import draft_folder
from app.engine.plan import PlanService
from app.engine.views import utc_time
from app.models import (
    Attachment,
    Chat,
    Document,
    Item,
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
from app.models.reference import (
    DocumentRole,
    ErrorKind,
    ProjectState,
    TransitionKind,
    WorkTrigger,
)
from app.services.session_scope import project_folder

CHAT_SKILL = "/chat"
CREATE_SKILL = "/create"
PLAN_SKILL = "/plan"

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
            self._notes(project),
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
        (F141.4, `_trigger_paused`), then its trigger's payload.

        The setup's (F49), triggered at Create project's instant, which opened
        the project and took its slug: `/plan`, then the draft's folder and
        the project's, the draft, the opening that holds the words that
        started it, and the plan, empty. No notes: its plan holds none."""
        # `JobService` places the setup alone.
        assert work.trigger_code is WorkTrigger.SETUP
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
            [_switch(project), self._trigger_paused(project, triggered)],
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

    def _notes(self, project: Project) -> list[str]:
        """The open plan notes, by summary (F57.4), the tasks' in the plan's
        order and then the plan's own; then the deferrals without a home, as
        the hook's check prints them (F79.3; DB 214)."""
        lines: list[str] = []
        for note, task_title in self.db.execute(
            select(PlanNote, PlanTask.title)
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
