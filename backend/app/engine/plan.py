"""`plan.json`: the plan's rows rendered as the file, and a save of the file
parsed back into them (design 1 §6.2, DB decisions 22, 23, 48). The rows are
the truth: no text of a save is stored (DB 175)."""

import json
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pilot_dsl as dsl
from sqlalchemy import and_, delete, exists, or_, select
from sqlalchemy.orm import Session

from app.engine.paths import tree_path
from app.engine.views import Rendering, render_json, utc_time
from app.models import (
    Block,
    Document,
    Item,
    PlanNote,
    PlanNoteReference,
    PlanTask,
    Project,
)
from app.models.reference import ProjectState, TaskStatus

_PLAN_KEYS = ("ticket", "repo", "tasks", "notes")
_TASK_KEYS = ("id", "title", "status", "notes")
_NOTE_KEYS = ("id", "summary", "content", "refs", "created")
_STATUSES = "pending, in_progress or done"
# What a JSON escape can write and no PostgreSQL `text` holds.
_UNSTORABLE = re.compile(r"[\x00\ud800-\udfff]")
_NOT_TEXT = "the plan is not text: a string holds `\\u0000` or an unpaired surrogate"


@dataclass(frozen=True)
class HomelessDeferral:
    """A deferral without a home (DB decision 214).

    `block` is the Block as a note's `refs` names it, `<item id>/<local id>`;
    `document` its Document's path from the tree's root, and `title` its
    Item's, none while its text gives none; `to` the Plan Task it is deferred
    to, or `plan`.
    """

    block: str
    document: str
    title: str | None
    to: str


@dataclass(frozen=True)
class _Task:
    task_id: str
    title: str | None
    status: TaskStatus | None


@dataclass(frozen=True)
class _Note:
    note_id: str
    task_id: str | None
    summary: str | None
    content: str | None
    refs: tuple[str, ...]


@dataclass(frozen=True)
class _Save:
    """What a save holds, as far as it could be read: an entry without an
    `id` is left out."""

    ticket: str | None
    repo: str | None
    tasks: tuple[_Task, ...]
    notes: tuple[_Note, ...]


class PlanService:
    def __init__(self, db: Session, ticket_id_pattern: re.Pattern[str]) -> None:
        self.db = db
        self.ticket_id_pattern = ticket_id_pattern

    def render(self, project: Project) -> Rendering:
        """The project's `plan.json`: its ticket and repo, the tasks in the
        plan in their order, each with its open notes, then the plan's own
        open notes. A note's `created` is the engine's; removed tasks and
        struck notes are absent."""
        tasks = self.db.scalars(
            select(PlanTask)
            .where(PlanTask.project_id == project.id, PlanTask.removed_at.is_(None))
            .order_by(PlanTask.position)
        ).all()
        notes = self.db.scalars(
            select(PlanNote)
            .where(PlanNote.project_id == project.id, PlanNote.deleted_at.is_(None))
            .order_by(PlanNote.id)
        ).all()
        refs: dict[int, list[str]] = {}
        for plan_note_id, document_id, local_id in self.db.execute(
            select(PlanNoteReference.plan_note_id, Block.document_id, Block.local_id)
            .join(Block, Block.id == PlanNoteReference.block_id)
            .where(PlanNoteReference.plan_note_id.in_([note.id for note in notes]))
            .order_by(Block.id)
        ):
            refs.setdefault(plan_note_id, []).append(f"{document_id}/{local_id}")
        placed: dict[str | None, list[dict[str, Any]]] = {}
        for note in notes:
            placed.setdefault(note.plan_task_id, []).append(
                {
                    "id": note.note_id,
                    "summary": note.summary,
                    "content": note.content,
                    "refs": refs.get(note.id, []),
                    "created": utc_time(note.created_at),
                }
            )
        return render_json(
            {
                "ticket": project.ticket,
                "repo": project.repo,
                "tasks": [
                    {
                        "id": task.task_id,
                        "title": task.title,
                        "status": task.status_code.value,
                        "notes": placed.get(task.task_id, []),
                    }
                    for task in tasks
                ],
                "notes": placed.get(None, []),
            }
        )

    def lock(self, project: Project) -> None:
        """Hold the project's row until the transaction ends, so that two
        saves of its plan never interleave, and re-read the project as the
        lock found it."""
        self.db.scalars(
            select(Project)
            .where(Project.id == project.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()

    def save(self, project: Project, content: bytes) -> list[dsl.Fault]:
        """Take a save of the project's `plan.json` and return its faults.

        With none, the save's ticket, repo, tasks and notes become the rows:
        a task absent is removed and one saved again returns; a note is
        matched to the open note of its id, and one absent is struck. With
        any, nothing changes (DB 173, 213).
        """
        reader = _Reader(self.ticket_id_pattern)
        saved = reader.read(content)
        if saved is None:
            return reader.faults
        faults = reader.faults
        tasks = {
            row.task_id: row
            for row in self.db.scalars(
                select(PlanTask).where(PlanTask.project_id == project.id)
            )
        }
        open_notes = {
            row.note_id: row
            for row in self.db.scalars(
                select(PlanNote).where(
                    PlanNote.project_id == project.id, PlanNote.deleted_at.is_(None)
                )
            )
        }
        blocks = self._blocks(
            project, {ref for note in saved.notes for ref in note.refs}
        )
        for note in saved.notes:
            faults.extend(
                dsl.Fault(
                    None,
                    f"note `{note.note_id}`: `refs` names `{ref}`,"
                    " which is no block of this project's items",
                )
                for ref in note.refs
                if ref not in blocks
            )
        kept = {task.task_id for task in saved.tasks}
        for task_id, row in tasks.items():
            if row.removed_at is not None or task_id in kept:
                continue
            carried = [
                f"`{note.note_id}`"
                for note in open_notes.values()
                if note.plan_task_id == task_id
            ]
            if carried:
                faults.append(
                    dsl.Fault(
                        None,
                        f"task `{task_id}` is removed while its notes"
                        f" {', '.join(sorted(carried))} are open: strike or"
                        " move them first, in a save of their own",
                    )
                )
        if faults:
            return faults
        self._write(project, saved, tasks, open_notes, blocks)
        return []

    def _blocks(self, project: Project, refs: set[str]) -> dict[str, int]:
        """The Block each ref names, `<item id>/<local id>` (TD §4.9), of the
        project's items; a ref naming none is left out."""
        named: dict[str, tuple[uuid.UUID, str]] = {}
        for ref in refs:
            item_id, _, local_id = ref.partition("/")
            try:
                named[ref] = (uuid.UUID(item_id), local_id)
            except ValueError:
                continue
        if not named:
            return {}
        found = {
            (document_id, local_id): block_id
            for block_id, document_id, local_id in self.db.execute(
                select(Block.id, Block.document_id, Block.local_id)
                .join(Item, Item.id == Block.document_id)
                .where(
                    Item.project_id == project.id,
                    Block.document_id.in_({key[0] for key in named.values()}),
                )
            )
        }
        return {ref: found[key] for ref, key in named.items() if key in found}

    def _write(
        self,
        project: Project,
        saved: _Save,
        tasks: dict[str, PlanTask],
        open_notes: dict[str, PlanNote],
        blocks: dict[str, int],
    ) -> None:
        now = datetime.now(UTC)
        project.ticket = saved.ticket
        project.repo = saved.repo
        for position, task in enumerate(saved.tasks, start=1):
            # A save with no fault has every value a row requires.
            assert task.title is not None and task.status is not None
            row = tasks.get(task.task_id)
            if row is None:
                row = PlanTask(project_id=project.id, task_id=task.task_id)
                self.db.add(row)
            row.position = position
            row.title = task.title
            row.status_code = task.status
            row.removed_at = None
        kept = {task.task_id for task in saved.tasks}
        for task_id, row in tasks.items():
            if task_id not in kept and row.removed_at is None:
                row.position = None
                row.removed_at = now
        # A note's key names its task's row.
        self.db.flush()

        saved_ids = {note.note_id for note in saved.notes}
        for note_id, row in open_notes.items():
            if note_id not in saved_ids:
                row.deleted_at = now
        rows: dict[str, PlanNote] = {}
        for note in saved.notes:
            assert note.summary is not None and note.content is not None
            row = open_notes.get(note.note_id)
            if row is None:
                row = PlanNote(project_id=project.id, note_id=note.note_id)
                self.db.add(row)
            row.plan_task_id = note.task_id
            row.summary = note.summary
            row.content = note.content
            rows[note.note_id] = row
        self.db.flush()

        named: dict[int, set[int]] = {}
        for plan_note_id, block_id in self.db.execute(
            select(PlanNoteReference.plan_note_id, PlanNoteReference.block_id).where(
                PlanNoteReference.plan_note_id.in_([row.id for row in rows.values()])
            )
        ):
            named.setdefault(plan_note_id, set()).add(block_id)
        for note in saved.notes:
            row = rows[note.note_id]
            held = named.get(row.id, set())
            wanted = {blocks[ref] for ref in note.refs}
            if held - wanted:
                self.db.execute(
                    delete(PlanNoteReference).where(
                        PlanNoteReference.plan_note_id == row.id,
                        PlanNoteReference.block_id.in_(held - wanted),
                    )
                )
            self.db.add_all(
                PlanNoteReference(plan_note_id=row.id, block_id=block_id)
                for block_id in wanted - held
            )
        self.db.flush()

    def homeless_deferrals(self, project: Project) -> list[HomelessDeferral]:
        """The project's deferrals without a home, computed and never stored
        (DB decision 214): a Block answered `deferred` in a Document whose Item
        is the project's and done, deferred to a Plan Task that is not `done`
        or to the plan while the project is not finished, that no Plan Note
        names, a struck note's reference counting. In item and block order."""
        rows = self.db.execute(
            select(
                Document.path,
                Item.title,
                Block.document_id,
                Block.local_id,
                Block.deferred_to_task_id,
            )
            .select_from(Block)
            .join(Document, Document.id == Block.document_id)
            .join(Item, Item.id == Document.id)
            .join(Project, Project.id == Item.project_id)
            .outerjoin(
                PlanTask,
                and_(
                    PlanTask.project_id == Item.project_id,
                    PlanTask.task_id == Block.deferred_to_task_id,
                ),
            )
            .where(
                Item.project_id == project.id,
                Block.answer == dsl.DEFERRED,
                Item.done_at.is_not(None),
                or_(
                    PlanTask.status_code != TaskStatus.DONE,
                    and_(
                        Block.deferred_to_task_id.is_(None),
                        Project.state_code != ProjectState.FINISHED,
                    ),
                ),
                ~exists().where(PlanNoteReference.block_id == Block.id),
            )
            .order_by(Item.seq, Block.position)
        ).all()
        return [
            HomelessDeferral(
                block=f"{document_id}/{local_id}",
                document=tree_path(project, path),
                title=title,
                to=dsl.PLAN if task_id is None else task_id,
            )
            for path, title, document_id, local_id, task_id in rows
        ]


class _Unreadable(Exception):
    def __init__(self, fault: dsl.Fault) -> None:
        super().__init__(fault.message)
        self.fault = fault


class _Reader:
    """Reads a save into a `_Save`, collecting every fault of its shape."""

    def __init__(self, ticket_id_pattern: re.Pattern[str]) -> None:
        self.ticket_id_pattern = ticket_id_pattern
        self.faults: list[dsl.Fault] = []

    def read(self, content: bytes) -> _Save | None:
        """The save, none when it is no JSON object."""
        try:
            data = json.loads(
                content.decode(),
                object_pairs_hook=_object,
                parse_constant=_constant,
                parse_int=_integer,
            )
        except UnicodeDecodeError:
            self._fault("the plan is not UTF-8 text")
            return None
        except json.JSONDecodeError as error:
            self.faults.append(
                dsl.Fault(error.lineno, f"the plan is not JSON: {error.msg}")
            )
            return None
        except RecursionError:
            self._fault("the plan is nested too deep to read")
            return None
        except _Unreadable as error:
            self.faults.append(error.fault)
            return None
        if not _storable(data):
            self._fault(_NOT_TEXT)
            return None
        if not isinstance(data, dict):
            self._fault("the plan is not a JSON object")
            return None

        self._keys(data, _PLAN_KEYS, "", "the plan")
        ticket = self._optional(data, "ticket", "the plan")
        if ticket is not None and not self.ticket_id_pattern.fullmatch(ticket):
            self._fault(f"`ticket: {ticket}` is not a ticket id")
        repo = self._optional(data, "repo", "the plan")
        tasks: list[_Task] = []
        notes: list[_Note] = []
        for index, entry in enumerate(self._list(data, "tasks", "the plan"), start=1):
            task = self._task(entry, index, notes)
            if task is not None:
                tasks.append(task)
        notes.extend(self._notes(data, None, "the plan"))
        for task_id in _repeated(task.task_id for task in tasks):
            self._fault(f"two tasks have the id `{task_id}`")
        for note_id in _repeated(note.note_id for note in notes):
            self._fault(f"two open notes have the id `{note_id}`")
        return _Save(ticket, repo, tuple(tasks), tuple(notes))

    def _task(self, entry: Any, index: int, notes: list[_Note]) -> _Task | None:
        if not isinstance(entry, dict):
            self._fault(f"task {index} is not a JSON object")
            return None
        task_id = self._required(entry, "id", f"task {index}")
        subject = f"task {index}" if task_id is None else f"task `{task_id}`"
        self._keys(entry, _TASK_KEYS, f"{subject}: ", "a task")
        title = self._required(entry, "title", subject)
        status = self._status(entry, subject)
        found = self._notes(entry, task_id, subject)
        if task_id is None:
            return None
        notes.extend(found)
        return _Task(task_id, title, status)

    def _status(self, entry: dict[str, Any], subject: str) -> TaskStatus | None:
        status = entry.get("status")
        if status is None:
            self._fault(f"{subject} has no `status`")
            return None
        written = status.strip() if isinstance(status, str) else _json(status)
        try:
            return TaskStatus(written)
        except ValueError:
            self._fault(f"{subject}: `status: {written}` is not {_STATUSES}")
            return None

    def _notes(
        self, entry: dict[str, Any], task_id: str | None, owner: str
    ) -> list[_Note]:
        notes: list[_Note] = []
        for index, note in enumerate(self._list(entry, "notes", owner), start=1):
            if not isinstance(note, dict):
                self._fault(f"note {index} of {owner} is not a JSON object")
                continue
            note_id = self._required(note, "id", f"note {index} of {owner}")
            subject = (
                f"note {index} of {owner}" if note_id is None else f"note `{note_id}`"
            )
            self._keys(note, _NOTE_KEYS, f"{subject}: ", "a note")
            summary = self._required(note, "summary", subject)
            content = self._required(note, "content", subject)
            refs = self._refs(note, subject)
            if note_id is not None:
                notes.append(_Note(note_id, task_id, summary, content, refs))
        return notes

    def _refs(self, note: dict[str, Any], subject: str) -> tuple[str, ...]:
        refs: list[str] = []
        for ref in self._list(note, "refs", subject):
            if not isinstance(ref, str):
                self._fault(f"{subject}: `refs` holds {_json(ref)}, not a block id")
            elif ref.strip() and ref.strip() not in refs:
                refs.append(ref.strip())
        return tuple(refs)

    def _keys(
        self, entry: dict[str, Any], keys: tuple[str, ...], prefix: str, owner: str
    ) -> None:
        for key in entry:
            if key not in keys:
                self._fault(f"{prefix}`{key}` is not a key of {owner}")

    def _list(self, entry: dict[str, Any], key: str, subject: str) -> list[Any]:
        value = entry.get(key)
        if value is None:
            return []
        if not isinstance(value, list):
            self._fault(f"{subject}: `{key}` is not a list")
            return []
        return value

    def _required(self, entry: dict[str, Any], key: str, subject: str) -> str | None:
        value = entry.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            self._fault(f"{subject} has no `{key}`")
            return None
        return self._optional(entry, key, subject)

    def _optional(self, entry: dict[str, Any], key: str, subject: str) -> str | None:
        """The value trimmed; none when absent, null or blank."""
        value = entry.get(key)
        if value is None or isinstance(value, str):
            return (value or "").strip() or None
        self._fault(f"{subject}: `{key}` is not a string")
        return None

    def _fault(self, message: str) -> None:
        self.faults.append(dsl.Fault(None, message))


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """A JSON object; one that repeats a key is unreadable, since the last
    value would silently win. A repeated key no row holds is not text: the
    fault quotes no such key."""
    data: dict[str, Any] = {}
    for key, value in pairs:
        if key in data:
            if _UNSTORABLE.search(key):
                raise _Unreadable(dsl.Fault(None, _NOT_TEXT))
            raise _Unreadable(
                dsl.Fault(None, f"the plan has `{key}` twice in one object")
            )
        data[key] = value
    return data


def _constant(name: str) -> Any:
    raise _Unreadable(
        dsl.Fault(None, f"the plan is not JSON: `{name}` is no JSON value")
    )


def _integer(digits: str) -> int:
    try:
        return int(digits)
    except ValueError:
        # `int()` takes no more digits than `sys.get_int_max_str_digits()`.
        raise _Unreadable(
            dsl.Fault(
                None,
                f"the plan holds a number of {len(digits.lstrip('-'))} digits,"
                " too long to read",
            )
        ) from None


def _storable(data: Any) -> bool:
    """Whether every key and string of the save is text a row holds."""
    pending = [data]
    while pending:
        value = pending.pop()
        if isinstance(value, str):
            if _UNSTORABLE.search(value):
                return False
        elif isinstance(value, dict):
            pending.extend(value)
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return True


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _repeated(ids: Any) -> list[str]:
    return [key for key, count in Counter(ids).items() if count > 1]
