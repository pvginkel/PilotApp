"""The brief a brain session's first Turn carries, per kind, against invented
records (design 3 §5.2, §5.3; D058; DB assertion 251; V12, V13)."""

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import Chat, Item, Project, ProjectMember, ProjectTransition, User
from app.models.reference import ChatKind, CloseCause, ProjectState, TransitionKind
from app.services.brief_service import BriefService
from app.services.container import ServiceContainer

AT = datetime(2026, 10, 26, 9, 30, 15, tzinfo=UTC)
HEAD = (
    "/chat\n\n"
    "Pilot's brief · the project's chat · project \"Soup club\" ·"
    " /work/Projects/soup-club · 2026-10-26T09:30:15Z"
)
NOTES = (
    "Open plan notes, by summary (the content and the blocks a read away in"
    " plan.json; `pilot.py plan note list`):"
)
HOMELESS = (
    "Deferrals without a home (a note names none of these blocks — write one,"
    " or answer the block anew in a new item):"
)

PLAN = {
    "ticket": None,
    "repo": None,
    "tasks": [
        {
            "id": "fix",
            "title": "Fix the stock",
            "status": "in_progress",
            "notes": [{"id": "n1", "summary": "Ask about salt", "content": "Ask."}],
        },
        {
            "id": "taste",
            "title": "Taste it",
            "status": "pending",
            "notes": [{"id": "n3", "summary": "Two spoons", "content": "Two."}],
        },
    ],
    "notes": [{"id": "n2", "summary": "Add a sweep task", "content": "Later."}],
}

DEFERRED = """# Soup chores

```decision id=D1
options:
  - Leek
  - Onion
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


@pytest.fixture
def briefs(container: ServiceContainer) -> BriefService:
    return container.brief_service()


@pytest.fixture
def opened(session: DbSession, project: Project) -> Project:
    """`project` open, named and with its slug."""
    project.state_code = ProjectState.OPEN
    project.slug, project.name = "soup-club", "Soup club"
    session.flush()
    return project


def _transition(
    db: DbSession, project: Project, person: User, kind: TransitionKind, at: datetime
) -> None:
    db.add(
        ProjectTransition(
            project_id=project.id, kind_code=kind, at=at, by_user_id=person.id
        )
    )
    db.flush()


def _closed_chat(db: DbSession, project: Project, closed_at: datetime) -> None:
    run = models.Session(
        project_id=project.id,
        kind_code="chat",
        cwd="/work/PilotProjects",
        token_hash=closed_at.isoformat(),
        state_code="ended",
    )
    db.add(run)
    db.flush()
    db.add(
        Chat(
            id=run.id,
            project_id=project.id,
            session_kind_code="chat",
            kind_code=ChatKind.PROJECT,
            closed_at=closed_at,
            close_cause_code=CloseCause.TIMEOUT,
        )
    )
    db.flush()


class TestProjectChat:
    def test_an_open_projects_brief_with_nothing_more_is_the_switch_and_the_message(
        self, briefs: BriefService, opened: Project, person: User
    ) -> None:
        assert briefs.project_chat(opened, person, "What next?", AT) == (
            f"{HEAD}\n\n"
            "Auto pilot: off — the granted column asks for this session"
            " (rules/grants.md).\n\n"
            "The message, from ada (not a member):\n"
            "What next?"
        )

    def test_every_line_that_holds_is_in_the_frames_order(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        opened: Project,
        person: User,
        project_session: models.Session,
    ) -> None:
        opened.autopilot = opened.paused = True
        session.add(
            ProjectMember(project_id=opened.id, user_id=person.id, joined_at=AT)
        )
        _transition(
            session,
            opened,
            person,
            TransitionKind.PAUSED,
            datetime(2026, 10, 1, tzinfo=UTC),
        )
        _transition(
            session,
            opened,
            person,
            TransitionKind.RESUMED,
            datetime(2026, 10, 2, tzinfo=UTC),
        )
        _transition(
            session,
            opened,
            person,
            TransitionKind.PAUSED,
            datetime(2026, 10, 26, 8, tzinfo=UTC),
        )
        struck = {"id": "n4", "summary": "Struck", "content": "Gone."}
        plans = container.plan_service()
        assert (
            plans.save(
                opened, json.dumps(PLAN | {"notes": [*PLAN["notes"], struck]}).encode()
            )
            == []
        )
        assert plans.save(opened, json.dumps(PLAN).encode()) == []
        item = container.document_service().bear_item(
            opened, "decision", "Soup chores", project_session, DEFERRED
        )
        container.record_service().done(item, person)
        _closed_chat(session, opened, datetime(2026, 10, 24, 12, tzinfo=UTC))
        _closed_chat(session, opened, datetime(2026, 10, 25, 17, 10, tzinfo=UTC))
        words = f'<quoted_item id="{item.id}">Soup chores</quoted_item id="{item.id}"> Leek.'

        brief = briefs.project_chat(opened, person, words, AT)

        path = f"soup-club/{session.get_one(models.Document, item.id).path}"
        assert brief == (
            f"{HEAD}\n\n"
            "Auto pilot: on — the granted column holds for this session"
            " (rules/grants.md).\n"
            "The project is paused since 2026-10-26T08:00:00Z: anything you start"
            " is held until it resumes — say so.\n\n"
            f"{NOTES}\n"
            '- fix "Fix the stock" · n1: Ask about salt\n'
            '- taste "Taste it" · n3: Two spoons\n'
            "- the plan · n2: Add a sweep task\n"
            f"{HOMELESS}\n"
            f"- {item.id}/D1 in {path} (Soup chores), to: fix\n"
            f"- {item.id}/Q1 in {path} (Soup chores), to: plan\n\n"
            "Earlier chats of this project are in chat.md; the latest closed"
            " 2026-10-25T17:10:00Z.\n\n"
            "The message, from ada (member):\n"
            f"{words}"
        )

    def test_the_deferrals_stand_without_notes(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        opened: Project,
        person: User,
        project_session: models.Session,
    ) -> None:
        item = container.document_service().bear_item(
            opened, "decision", "Soup chores", project_session, DEFERRED
        )
        container.record_service().done(item, person)

        brief = briefs.project_chat(opened, person, "Hi", AT)

        path = f"soup-club/{session.get_one(models.Document, item.id).path}"
        # No plan is saved: D1's `fix` is no task of it, and D1 is not listed.
        assert brief == (
            f"{HEAD}\n\n"
            "Auto pilot: off — the granted column asks for this session"
            " (rules/grants.md).\n\n"
            f"{HOMELESS}\n"
            f"- {item.id}/Q1 in {path} (Soup chores), to: plan\n\n"
            "The message, from ada (not a member):\n"
            "Hi"
        )

    def test_a_project_with_no_name_is_named_by_its_folder_alone(
        self, session: DbSession, briefs: BriefService, opened: Project, person: User
    ) -> None:
        opened.name = None
        session.flush()

        brief = briefs.project_chat(opened, person, "Hi", AT)

        assert brief.startswith(
            "/chat\n\nPilot's brief · the project's chat · /work/Projects/soup-club"
            " · 2026-10-26T09:30:15Z\n\n"
        )

    def test_it_carries_nothing_of_the_handbook(
        self,
        container: ServiceContainer,
        briefs: BriefService,
        opened: Project,
        person: User,
    ) -> None:
        container.document_service().bear_handbook(
            opened, "# Handbook\n\n- Salt the stock last.\n"
        )

        brief = briefs.project_chat(opened, person, "Hi", AT)

        assert "handbook" not in brief.lower()
        assert "Salt the stock last" not in brief

    def test_it_ends_with_the_words_verbatim(
        self, briefs: BriefService, opened: Project, person: User, item: Item
    ) -> None:
        words = f'  <quoted_block id="{item.id}/D1">Which?</quoted_block id="{item.id}/D1">\n\nLeek.\n'

        assert briefs.project_chat(opened, person, words, AT).endswith(
            f"(not a member):\n{words}"
        )
