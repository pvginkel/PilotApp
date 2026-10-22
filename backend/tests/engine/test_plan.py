"""`plan.json`: rendered canonical from the plan's rows, and a save parsed back
into them with its notes, every fault holding the whole save (design 1 §6.2,
DB 173, 205-213); and the deferrals no note gives a home (DB 214)."""

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.engine import dsl
from app.engine.plan import HomelessDeferral, PlanService
from app.models import (
    Document,
    Environment,
    Item,
    PlanNote,
    PlanNoteReference,
    PlanTask,
    Project,
    User,
)
from app.models.reference import ProjectState, TaskStatus
from app.services.container import ServiceContainer

TENT = """# Which tent?

```decision id=D1
options:
  - Dome
  - Tunnel
```

```decision id=D2
options:
  - North
  - South
```
"""

DEFERRED = """# Camp chores

```decision id=D1
options:
  - Dome
  - Tunnel
answer: deferred
by: agent
at: 2026-10-12T09:30:00Z
to: fix
```

```question id=Q1
answer: deferred
by: agent
at: 2026-10-12T09:30:00Z
to: plan
```
"""

CREATED = datetime(2026, 10, 12, 12, 34, tzinfo=UTC)

NOT_TEXT = "the plan is not text: a string holds `\\u0000` or an unpaired surrogate"


def _save(container: ServiceContainer, project: Project, data: Any) -> list[str]:
    """The messages of a save's faults; `data` is JSON's, or the bytes."""
    content = data if isinstance(data, bytes) else json.dumps(data).encode()
    faults = container.plan_service().save(project, content)
    assert all(
        fault.line is None for fault in faults if "not JSON" not in fault.message
    )
    return [fault.message for fault in faults]


def _tent(
    container: ServiceContainer, project: Project, project_session: models.Session
) -> Item:
    """An item of `project` with the blocks D1 and D2."""
    return container.document_service().bear_item(
        project, "decision", "Which tent?", project_session, TENT
    )


def _rows(session: DbSession, project: Project) -> dict[str, Any]:
    """The plan's rows as a value, to compare before and after."""
    session.flush()
    session.expire_all()
    return {
        "project": (project.ticket, project.repo),
        "tasks": [
            (task.task_id, task.position, task.title, task.status_code, task.removed_at)
            for task in session.scalars(
                select(PlanTask)
                .where(PlanTask.project_id == project.id)
                .order_by(PlanTask.task_id)
            )
        ],
        "notes": [
            (
                note.id,
                note.note_id,
                note.plan_task_id,
                note.summary,
                note.content,
                note.deleted_at,
            )
            for note in session.scalars(
                select(PlanNote)
                .where(PlanNote.project_id == project.id)
                .order_by(PlanNote.id)
            )
        ],
        "references": _references(session),
    }


def _references(session: DbSession) -> list[tuple[int, int]]:
    return [
        (reference.plan_note_id, reference.block_id)
        for reference in session.scalars(
            select(PlanNoteReference).order_by(
                PlanNoteReference.plan_note_id, PlanNoteReference.block_id
            )
        )
    ]


def _note(session: DbSession, project: Project, note_id: str) -> PlanNote:
    """The open note of `note_id`."""
    return session.scalars(
        select(PlanNote).where(
            PlanNote.project_id == project.id,
            PlanNote.note_id == note_id,
            PlanNote.deleted_at.is_(None),
        )
    ).one()


def _task(session: DbSession, project: Project, task_id: str) -> PlanTask:
    return session.get_one(PlanTask, (project.id, task_id))


def _block_id(session: DbSession, item: Item, local_id: str) -> int:
    return session.scalars(
        select(models.Block.id).where(
            models.Block.document_id == item.id, models.Block.local_id == local_id
        )
    ).one()


def _deferrals(
    container: ServiceContainer,
    project: Project,
    project_session: models.Session,
    person: User,
    *,
    done: bool = True,
) -> Item:
    """An item of `project` whose D1 is deferred to the task `fix` and Q1 to
    the plan, done by `person` unless `done` is false."""
    item = container.document_service().bear_item(
        project, "decision", "Camp chores", project_session, DEFERRED
    )
    if done:
        container.record_service().done(item, person)
    return item


def _homeless(
    session: DbSession, project: Project, item: Item, *local_ids_to: str
) -> list[HomelessDeferral]:
    """The deferrals without a home of `item`, each `<local id>:<to>`."""
    document = f"draft-{project.number}/{session.get_one(Document, item.id).path}"
    return [
        HomelessDeferral(f"{item.id}/{local_id}", document, item.title, to)
        for local_id, _, to in (entry.partition(":") for entry in local_ids_to)
    ]


def _plan(**values: Any) -> dict[str, Any]:
    """A save with two tasks, `fix` carrying the note `n1`."""
    return {
        "ticket": "MD-8",
        "repo": "pvginkel/MyDownloads",
        "tasks": [
            {
                "id": "fix",
                "title": "Fix the client for v4",
                "status": "in_progress",
                "notes": [
                    {"id": "n1", "summary": "Ask about the key", "content": "Drop it."}
                ],
            },
            {"id": "verify", "title": "Verify in the app", "status": "pending"},
        ],
        **values,
    }


class TestPlanServiceRender:
    def test_an_empty_plan_renders_every_key(
        self, container: ServiceContainer, project: Project
    ) -> None:
        rendering = container.plan_service().render(project)

        assert rendering.text == (
            '{\n  "ticket": null,\n  "repo": null,\n  "tasks": [],\n  "notes": []\n}\n'
        )
        assert rendering.hash == hashlib.sha256(rendering.text.encode()).hexdigest()

    def test_the_plan_renders_its_open_rows_in_order(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _tent(container, project, project_session)
        project.ticket, project.repo = "MD-8", "pvginkel/MyDownloads"
        session.add_all(
            [
                PlanTask(
                    project_id=project.id,
                    task_id="verify",
                    position=2,
                    title="Verify in the app",
                    status_code=TaskStatus.PENDING,
                ),
                PlanTask(
                    project_id=project.id,
                    task_id="fix",
                    position=1,
                    title="Fix the client for v4",
                    status_code=TaskStatus.IN_PROGRESS,
                ),
                PlanTask(
                    project_id=project.id,
                    task_id="tvmaze",
                    title="Try TVmaze",
                    status_code=TaskStatus.PENDING,
                    removed_at=CREATED,
                ),
            ]
        )
        session.flush()
        sweep = PlanNote(
            project_id=project.id,
            note_id="n3",
            summary="Sweep before the finish",
            content="The v3 fallback.",
            created_at=CREATED,
        )
        ask = PlanNote(
            project_id=project.id,
            plan_task_id="fix",
            note_id="n2",
            summary="Ask at the next turn",
            content="Drop the v3 key.",
            created_at=CREATED,
        )
        struck = PlanNote(
            project_id=project.id,
            plan_task_id="fix",
            note_id="n1",
            summary="Check the second account",
            content="Done.",
            created_at=CREATED,
            deleted_at=CREATED,
        )
        session.add_all([sweep, ask, struck])
        session.flush()
        session.add_all(
            [
                PlanNoteReference(
                    plan_note_id=ask.id, block_id=_block_id(session, item, "D2")
                ),
                PlanNoteReference(
                    plan_note_id=ask.id, block_id=_block_id(session, item, "D1")
                ),
                PlanNoteReference(
                    plan_note_id=struck.id, block_id=_block_id(session, item, "D1")
                ),
            ]
        )
        session.flush()

        rendering = container.plan_service().render(project)

        data = json.loads(rendering.text)
        assert rendering.text == json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        assert rendering.hash == hashlib.sha256(rendering.text.encode()).hexdigest()
        assert data == {
            "ticket": "MD-8",
            "repo": "pvginkel/MyDownloads",
            "tasks": [
                {
                    "id": "fix",
                    "title": "Fix the client for v4",
                    "status": "in_progress",
                    "notes": [
                        {
                            "id": "n2",
                            "summary": "Ask at the next turn",
                            "content": "Drop the v3 key.",
                            "refs": [f"{item.id}/D1", f"{item.id}/D2"],
                            "created": "2026-10-12T12:34:00Z",
                        }
                    ],
                },
                {
                    "id": "verify",
                    "title": "Verify in the app",
                    "status": "pending",
                    "notes": [],
                },
            ],
            "notes": [
                {
                    "id": "n3",
                    "summary": "Sweep before the finish",
                    "content": "The v3 fallback.",
                    "refs": [],
                    "created": "2026-10-12T12:34:00Z",
                }
            ],
        }

    def test_another_projects_plan_is_not_rendered(
        self, session: DbSession, container: ServiceContainer, project: Project
    ) -> None:
        other = Project(created_by_user_id=project.created_by_user_id)
        session.add(other)
        session.flush()
        _save(container, other, _plan())

        assert json.loads(container.plan_service().render(project).text)["tasks"] == []


class TestPlanServiceSave:
    def test_a_save_writes_the_rows(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _tent(container, project, project_session)
        plan = _plan(
            notes=[
                {
                    "id": "n2",
                    "summary": "Sweep before the finish",
                    "content": "The v3 fallback.",
                    "refs": [f"{item.id}/D2"],
                }
            ]
        )

        assert _save(container, project, plan) == []

        assert (project.ticket, project.repo) == ("MD-8", "pvginkel/MyDownloads")
        fix, verify = _task(session, project, "fix"), _task(session, project, "verify")
        assert (fix.position, fix.title, fix.status_code, fix.removed_at) == (
            1,
            "Fix the client for v4",
            TaskStatus.IN_PROGRESS,
            None,
        )
        assert (verify.position, verify.status_code) == (2, TaskStatus.PENDING)
        n1, n2 = _note(session, project, "n1"), _note(session, project, "n2")
        assert (n1.plan_task_id, n1.summary, n1.content) == (
            "fix",
            "Ask about the key",
            "Drop it.",
        )
        assert n2.plan_task_id is None
        assert _references(session) == [(n2.id, _block_id(session, item, "D2"))]
        rendered = json.loads(container.plan_service().render(project).text)
        assert rendered["tasks"][0]["notes"][0]["id"] == "n1"
        assert rendered["notes"][0]["refs"] == [f"{item.id}/D2"]

    def test_a_task_absent_is_removed_and_returns_when_saved_again(
        self, session: DbSession, container: ServiceContainer, project: Project
    ) -> None:
        _save(container, project, _plan())
        tasks = _plan()["tasks"]

        assert _save(container, project, _plan(tasks=[tasks[0]])) == []
        verify = _task(session, project, "verify")
        assert verify.position is None
        assert verify.removed_at is not None
        assert (verify.title, verify.status_code) == (
            "Verify in the app",
            TaskStatus.PENDING,
        )
        assert [
            task["id"]
            for task in json.loads(container.plan_service().render(project).text)[
                "tasks"
            ]
        ] == ["fix"]

        returned = {"id": "verify", "title": "Verify it", "status": "done"}
        assert _save(container, project, _plan(tasks=[returned, tasks[0]])) == []
        verify = _task(session, project, "verify")
        assert (verify.position, verify.removed_at) == (1, None)
        assert (verify.title, verify.status_code) == ("Verify it", TaskStatus.DONE)
        assert _task(session, project, "fix").position == 2

    def test_a_task_already_removed_stays_removed(
        self, session: DbSession, container: ServiceContainer, project: Project
    ) -> None:
        _save(container, project, {"tasks": _plan()["tasks"][1:]})
        _save(container, project, {"tasks": []})
        removed_at = _task(session, project, "verify").removed_at

        assert _save(container, project, {"tasks": []}) == []
        assert _task(session, project, "verify").removed_at == removed_at

    def test_a_note_absent_is_struck_and_its_id_saved_again_is_a_new_note(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _tent(container, project, project_session)
        plan = _plan()
        plan["tasks"][0]["notes"][0]["refs"] = [f"{item.id}/D1"]
        _save(container, project, plan)
        first = _note(session, project, "n1")

        unnoted = _plan()
        unnoted["tasks"][0]["notes"] = []
        assert _save(container, project, unnoted) == []
        session.refresh(first)
        assert first.deleted_at is not None
        # A struck note keeps what it named (DB 214).
        assert _references(session) == [(first.id, _block_id(session, item, "D1"))]
        assert (
            json.loads(container.plan_service().render(project).text)["tasks"][0][
                "notes"
            ]
            == []
        )

        assert _save(container, project, _plan()) == []
        again = _note(session, project, "n1")
        assert again.id != first.id
        assert again.created_at >= first.created_at
        assert _references(session) == [(first.id, _block_id(session, item, "D1"))]

    def test_a_note_moves_to_another_task_or_to_the_plan(
        self, session: DbSession, container: ServiceContainer, project: Project
    ) -> None:
        _save(container, project, _plan())
        note = _note(session, project, "n1")
        moved = _plan()
        moved["tasks"][1]["notes"] = moved["tasks"][0].pop("notes")

        assert _save(container, project, moved) == []
        assert _note(session, project, "n1").id == note.id
        assert note.plan_task_id == "verify"

        lifted = _plan(notes=moved["tasks"][1].pop("notes"))
        lifted["tasks"][0]["notes"] = []
        assert _save(container, project, lifted) == []
        assert _note(session, project, "n1").id == note.id
        assert note.plan_task_id is None

    def test_a_notes_refs_are_the_set_last_saved(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _tent(container, project, project_session)
        plan = _plan()
        plan["tasks"][0]["notes"][0]["refs"] = [f"{item.id}/D1"]
        _save(container, project, plan)
        note = _note(session, project, "n1")

        plan["tasks"][0]["notes"][0]["refs"] = [
            f"{item.id}/D2",
            f"{str(item.id).upper()}/D2",
        ]
        assert _save(container, project, plan) == []
        assert _references(session) == [(note.id, _block_id(session, item, "D2"))]

        plan["tasks"][0]["notes"][0]["refs"] = []
        assert _save(container, project, plan) == []
        assert _references(session) == []

    def test_ticket_and_repo_are_optional(
        self, container: ServiceContainer, project: Project
    ) -> None:
        _save(container, project, _plan())

        assert _save(container, project, {"tasks": _plan()["tasks"]}) == []
        assert (project.ticket, project.repo) == (None, None)
        assert _save(container, project, _plan(ticket=None, repo="  ")) == []
        assert (project.ticket, project.repo) == (None, None)

    def test_any_key_order_and_formatting_is_read_and_created_ignored(
        self, session: DbSession, container: ServiceContainer, project: Project
    ) -> None:
        content = (
            b'{"notes":[],"tasks":[{"status":"  done ","notes":[{"created":'
            b'"2020-01-01T00:00:00Z","content":" Drop it. ","summary":"Ask",'
            b'"id":" n1 "}],"title":" Fix ","id":" fix "}],"repo":null,'
            b'"ticket":" MD-8 "}'
        )

        assert _save(container, project, content) == []
        fix = _task(session, project, "fix")
        assert (fix.title, fix.status_code) == ("Fix", TaskStatus.DONE)
        note = _note(session, project, "n1")
        assert (note.summary, note.content) == ("Ask", "Drop it.")
        assert note.created_at.year != 2020
        assert project.ticket == "MD-8"

    def test_a_surrogate_pair_escape_is_read_as_its_character(
        self, session: DbSession, container: ServiceContainer, project: Project
    ) -> None:
        save = (
            b'{"tasks": [{"id": "fix", "title": "Tent \\ud83c\\udfd5",'
            b' "status": "done"}]}'
        )

        assert _save(container, project, save) == []
        assert _task(session, project, "fix").title == "Tent \N{CAMPING}"

    def test_removing_a_task_whose_notes_are_struck_is_no_fault(
        self, session: DbSession, container: ServiceContainer, project: Project
    ) -> None:
        _save(container, project, _plan())
        unnoted = _plan()
        unnoted["tasks"][0]["notes"] = []
        _save(container, project, unnoted)

        assert _save(container, project, _plan(tasks=[unnoted["tasks"][1]])) == []
        assert _task(session, project, "fix").removed_at is not None

    def test_ticket_is_checked_against_the_configured_pattern(
        self, session: DbSession, project: Project
    ) -> None:
        plans = PlanService(session, re.compile(r"#[1-9][0-9]*"))

        assert plans.save(project, json.dumps({"ticket": "#12"}).encode()) == []
        assert project.ticket == "#12"
        assert plans.save(project, json.dumps({"ticket": "MD-8"}).encode()) == [
            dsl.Fault(None, "`ticket: MD-8` is not a ticket id")
        ]

    def test_the_default_pattern_takes_the_trackers_ids(
        self, container: ServiceContainer, project: Project
    ) -> None:
        for ticket in ("MD-8", "KC-153", "P-1"):
            assert _save(container, project, {"ticket": ticket}) == []
            assert project.ticket == ticket


class TestPlanServiceFaults:
    """Each fault holds the whole save: every row stays as it was (DB 173,
    213)."""

    @pytest.mark.parametrize(
        ("save", "messages"),
        [
            (b"\xff{}", ["the plan is not UTF-8 text"]),
            # Text no row and no Save Error can hold, in a value or a key.
            (
                b'{"tasks": [{"id": "fix", "title": "Fi\\u0000x",'
                b' "status": "pending"}]}',
                [NOT_TEXT],
            ),
            (
                b'{"tasks": [{"id": "fix", "title": "Fi\\ud800x",'
                b' "status": "pending"}]}',
                [NOT_TEXT],
            ),
            (b'{"\\u0000": 1}', [NOT_TEXT]),
            # A repeated key no row holds is not quoted as twice in one object.
            (b'{"\\u0000": 1, "\\u0000": 2}', [NOT_TEXT]),
            (b'{"tasks": [{"\\ud800": 1, "\\ud800": 2}]}', [NOT_TEXT]),
            (
                b'{"notes": [{"id": "n1", "summary": "s", "content": "c",'
                b' "refs": ["\\udfff"]}]}',
                [NOT_TEXT],
            ),
            pytest.param(
                b'{"ticket": ' + b"1" * 5000 + b"}",
                ["the plan holds a number of 5000 digits, too long to read"],
                id="a-number-too-long",
            ),
            pytest.param(
                b"[" * 100000 + b"]" * 100000,
                ["the plan is nested too deep to read"],
                id="nested-too-deep",
            ),
            (b'{"tasks": [', ["the plan is not JSON: Expecting value"]),
            (b'{"tasks": NaN}', ["the plan is not JSON: `NaN` is no JSON value"]),
            (
                b'{"ticket": "MD-8", "ticket": "MD-9"}',
                ["the plan has `ticket` twice in one object"],
            ),
            (b"[]", ["the plan is not a JSON object"]),
            (
                {"tickets": "MD-8", "tasks": []},
                ["`tickets` is not a key of the plan"],
            ),
            ({"ticket": "md-8"}, ["`ticket: md-8` is not a ticket id"]),
            ({"ticket": 8}, ["the plan: `ticket` is not a string"]),
            ({"repo": ["a", "b"]}, ["the plan: `repo` is not a string"]),
            ({"tasks": {"id": "fix"}}, ["the plan: `tasks` is not a list"]),
            ({"tasks": ["fix"]}, ["task 1 is not a JSON object"]),
            (
                {"tasks": [{"title": "Fix", "status": "pending"}]},
                ["task 1 has no `id`"],
            ),
            (
                {"tasks": [{"id": " ", "title": "Fix", "status": "pending"}]},
                ["task 1 has no `id`"],
            ),
            (
                {"tasks": [{"id": "fix", "status": "pending"}]},
                ["task `fix` has no `title`"],
            ),
            (
                {"tasks": [{"id": "fix", "title": 4, "status": "pending"}]},
                ["task `fix`: `title` is not a string"],
            ),
            (
                {"tasks": [{"id": "fix", "title": "Fix"}]},
                ["task `fix` has no `status`"],
            ),
            (
                {"tasks": [{"id": "fix", "title": "Fix", "status": "blocked"}]},
                ["task `fix`: `status: blocked` is not pending, in_progress or done"],
            ),
            (
                {"tasks": [{"id": "fix", "title": "Fix", "status": True}]},
                ["task `fix`: `status: true` is not pending, in_progress or done"],
            ),
            (
                {
                    "tasks": [
                        {"id": "fix", "title": "Fix", "status": "pending", "state": 1}
                    ]
                },
                ["task `fix`: `state` is not a key of a task"],
            ),
            (
                {
                    "tasks": [
                        {"id": "fix", "title": "Fix", "status": "done"},
                        {"id": "fix", "title": "Fix again", "status": "pending"},
                    ]
                },
                ["two tasks have the id `fix`"],
            ),
            (
                {
                    "tasks": [
                        {"id": "fix", "title": "Fix", "status": "pending", "notes": 1}
                    ]
                },
                ["task `fix`: `notes` is not a list"],
            ),
            ({"notes": ["n1"]}, ["note 1 of the plan is not a JSON object"]),
            (
                {"notes": [{"summary": "Ask", "content": "Drop it."}]},
                ["note 1 of the plan has no `id`"],
            ),
            (
                {"notes": [{"id": "n1", "content": "Drop it."}]},
                ["note `n1` has no `summary`"],
            ),
            (
                {"notes": [{"id": "n1", "summary": "Ask"}]},
                ["note `n1` has no `content`"],
            ),
            (
                {"notes": [{"id": "n1", "summary": "Ask", "content": "", "due": 1}]},
                [
                    "note `n1`: `due` is not a key of a note",
                    "note `n1` has no `content`",
                ],
            ),
            (
                {
                    "notes": [
                        {"id": "n1", "summary": "Ask", "content": "x", "refs": "D1"}
                    ]
                },
                ["note `n1`: `refs` is not a list"],
            ),
            (
                {
                    "notes": [
                        {"id": "n1", "summary": "Ask", "content": "x", "refs": [1]}
                    ]
                },
                ["note `n1`: `refs` holds 1, not a block id"],
            ),
            (
                {
                    "tasks": [
                        {
                            "id": "fix",
                            "title": "Fix",
                            "status": "pending",
                            "notes": [{"id": "n1", "summary": "Ask", "content": "x"}],
                        }
                    ],
                    "notes": [{"id": "n1", "summary": "Sweep", "content": "y"}],
                },
                ["two open notes have the id `n1`"],
            ),
            (
                {
                    "tasks": [
                        {"title": "Fix", "status": "later", "notes": [{"id": "n1"}]}
                    ],
                    "ticket": "md8",
                },
                [
                    "`ticket: md8` is not a ticket id",
                    "task 1 has no `id`",
                    "task 1: `status: later` is not pending, in_progress or done",
                    "note `n1` has no `summary`",
                    "note `n1` has no `content`",
                ],
            ),
        ],
    )
    def test_a_fault_holds_the_save(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        save: Any,
        messages: list[str],
    ) -> None:
        # The note is the plan's own: a save without the tasks trips no guard.
        plan = _plan()
        plan["notes"] = plan["tasks"][0].pop("notes")
        _save(container, project, plan)
        rows = _rows(session, project)

        assert _save(container, project, save) == messages
        assert _rows(session, project) == rows

    def test_a_json_fault_names_its_line(
        self, container: ServiceContainer, project: Project
    ) -> None:
        assert container.plan_service().save(
            project, b'{\n  "tasks": [\n    oops\n  ]\n}\n'
        ) == [dsl.Fault(3, "the plan is not JSON: Expecting value")]

    def test_a_ref_naming_no_block_of_the_projects_items_holds_the_save(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = _tent(container, project, project_session)
        draft = container.document_service().bear_draft(project, TENT)
        other = Project(created_by_user_id=project.created_by_user_id)
        session.add(other)
        session.flush()
        elsewhere = _tent(container, other, project_session)
        _save(container, project, _plan())
        rows = _rows(session, project)
        refs = [
            f"{item.id}/D9",
            f"{draft.id}/D1",
            f"{elsewhere.id}/D1",
            "D1",
            f"{item.id}/",
            f"{item.id}/D1",
        ]
        plan = _plan()
        plan["tasks"][0]["notes"][0]["refs"] = refs

        assert _save(container, project, plan) == [
            f"note `n1`: `refs` names `{ref}`, which is no block of this project's"
            " items"
            for ref in refs[:-1]
        ]
        assert _rows(session, project) == rows

    def test_removing_a_task_with_open_notes_holds_the_save(
        self, session: DbSession, container: ServiceContainer, project: Project
    ) -> None:
        plan = _plan()
        plan["tasks"][0]["notes"].append(
            {"id": "n0", "summary": "Check the account", "content": "Both users."}
        )
        _save(container, project, plan)
        rows = _rows(session, project)
        verify = _plan()["tasks"][1]
        moved = dict(verify, notes=plan["tasks"][0]["notes"])

        # The guard reads the notes open before the save: striking them, or
        # moving them, in the save that removes the task is held all the same.
        for save in (_plan(tasks=[verify]), _plan(tasks=[moved])):
            assert _save(container, project, save) == [
                "task `fix` is removed while its notes `n0`, `n1` are open: strike"
                " or move them first, in a save of their own"
            ]
            assert _rows(session, project) == rows


class TestPlanServiceHomelessDeferrals:
    def test_a_done_items_deferrals_no_note_names_are_homeless(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        _save(container, project, _plan())
        item = _deferrals(container, project, project_session, person)

        document = f"draft-{project.number}/items/1-camp-chores.md"
        assert container.plan_service().homeless_deferrals() == [
            HomelessDeferral(f"{item.id}/D1", document, "Camp chores", "fix"),
            HomelessDeferral(f"{item.id}/Q1", document, "Camp chores", "plan"),
        ]

    def test_a_registered_documents_deferrals_with_no_title_have_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
        person: User,
    ) -> None:
        _save(container, project, _plan())
        documents = container.document_service()
        item = documents.bear_item(
            project, "decision", "Camp chores", project_session, DEFERRED
        )
        document = session.get_one(Document, item.id)
        document.source_environment_id = environment.id
        document.source_path = "/work/Example/chores.md"
        documents.publish(document, DEFERRED.replace("# Camp chores\n\n", ""))
        container.record_service().done(item, person)

        path = f"draft-{project.number}/items/1-camp-chores.md"
        assert container.plan_service().homeless_deferrals() == [
            HomelessDeferral(f"{item.id}/D1", path, None, "fix"),
            HomelessDeferral(f"{item.id}/Q1", path, None, "plan"),
        ]

    def test_an_open_items_deferrals_are_not_homeless(
        self,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        _save(container, project, _plan())
        _deferrals(container, project, project_session, person, done=False)

        assert container.plan_service().homeless_deferrals() == []

    def test_a_deferral_in_the_draft_is_no_items_and_not_homeless(
        self, container: ServiceContainer, project: Project
    ) -> None:
        container.document_service().bear_draft(
            project, DEFERRED.replace("to: fix", "to: plan")
        )

        assert container.plan_service().homeless_deferrals() == []

    def test_a_note_naming_the_block_is_its_home_open_or_struck(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        _save(container, project, _plan())
        item = _deferrals(container, project, project_session, person)
        plan = _plan()
        plan["tasks"][0]["notes"][0]["refs"] = [f"{item.id}/D1"]
        assert _save(container, project, plan) == []
        homed = _homeless(session, project, item, "Q1:plan")

        assert container.plan_service().homeless_deferrals() == homed

        # The note is struck: it was dealt with, and the block keeps its home.
        plan["tasks"][0]["notes"] = []
        assert _save(container, project, plan) == []
        assert session.scalars(select(PlanNote.deleted_at)).one() is not None
        assert container.plan_service().homeless_deferrals() == homed

        plan["notes"] = [
            {
                "id": "n2",
                "summary": "Sweep before the finish",
                "content": "Settle what waited.",
                "refs": [f"{item.id}/Q1"],
            }
        ]
        assert _save(container, project, plan) == []
        assert container.plan_service().homeless_deferrals() == []

    def test_a_deferral_to_a_done_task_or_a_finished_project_is_not_homeless(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        _save(container, project, _plan())
        item = _deferrals(container, project, project_session, person)
        plan = _plan()
        plan["tasks"][0]["status"] = "done"
        assert _save(container, project, plan) == []

        assert container.plan_service().homeless_deferrals() == _homeless(
            session, project, item, "Q1:plan"
        )

        project.slug = "camp"
        project.state_code = ProjectState.FINISHED
        session.flush()
        assert container.plan_service().homeless_deferrals() == []

    def test_the_deferrals_are_in_project_item_and_block_order(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        later = Project(created_by_user_id=person.id)
        session.add(later)
        session.flush()
        for owner in (later, project):
            _save(container, owner, _plan())
        last = _deferrals(container, later, project_session, person)
        first = _deferrals(container, project, project_session, person)
        second = _deferrals(container, project, project_session, person)

        assert container.plan_service().homeless_deferrals() == [
            *_homeless(session, project, first, "D1:fix", "Q1:plan"),
            *_homeless(session, project, second, "D1:fix", "Q1:plan"),
            *_homeless(session, later, last, "D1:fix", "Q1:plan"),
        ]
