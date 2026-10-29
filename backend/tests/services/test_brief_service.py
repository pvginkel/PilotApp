"""The brief a brain session's first Turn carries, per kind, the server's
trailer on a worker's, and the follow-up turn, against invented records
(design 3 §5.1 to §5.4; D058; F46.1, F79, F129.5, F5.5; DB assertion 251;
V03, V08, V12, V13, V21)."""

import hashlib
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.engine.views import ViewService
from app.models import (
    Attachment,
    Block,
    Chat,
    ClaimAssignment,
    ClarificationRun,
    Document,
    Environment,
    Item,
    ItemAttachment,
    PlanTask,
    Project,
    ProjectMember,
    ProjectTransition,
    SaveError,
    Turn,
    User,
    Work,
    WriterQuestion,
)
from app.models.reference import (
    AnswerChannel,
    AttachmentSource,
    ChatKind,
    CloseCause,
    ErrorKind,
    ProjectState,
    RecordKind,
    SessionState,
    TaskStatus,
    TransitionKind,
    UserKind,
    WorkTrigger,
)
from app.services.brief_service import FOLLOW_UP_END, BriefService, is_follow_up
from app.services.container import ServiceContainer
from app.services.session_record_service import SessionRecordService
from app.services.turn_end_read_service import READ_FAILED
from tests.support.fake_sidecar import STORE_ENVIRONMENT_ID

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


class TestMessageFrom:
    def test_it_names_the_person_and_whether_they_are_a_member(
        self, session: DbSession, briefs: BriefService, opened: Project, person: User
    ) -> None:
        stranger = briefs.message_from(opened, person)
        session.add(
            ProjectMember(project_id=opened.id, user_id=person.id, joined_at=AT)
        )
        session.flush()

        assert (stranger, briefs.message_from(opened, person)) == (
            "The message, from ada (not a member):",
            "The message, from ada (member):",
        )

    def test_a_member_who_left_is_not_one(
        self, session: DbSession, briefs: BriefService, opened: Project, person: User
    ) -> None:
        session.add(
            ProjectMember(
                project_id=opened.id, user_id=person.id, joined_at=AT, left_at=AT
            )
        )
        session.flush()

        assert briefs.message_from(opened, person) == (
            "The message, from ada (not a member):"
        )


@pytest.fixture
def draft(
    session: DbSession, container: ServiceContainer, project: Project, person: User
) -> Project:
    """`project`, a draft from the plus: `person` its member, its draft born
    empty."""
    session.add(ProjectMember(project_id=project.id, user_id=person.id, joined_at=AT))
    session.flush()
    container.document_service().bear_draft(project)
    return project


def _attached(
    db: DbSession, project: Project, run: models.Session, filename: str
) -> None:
    content = f"# {filename}\n".encode()
    db.add(
        Attachment(
            project_id=project.id,
            batch=1,
            title=filename,
            filename=filename,
            content_type="text/markdown",
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            content=content,
            source_code=AttachmentSource.FILE,
            source_environment_id=run.environment_id,
            source_path=f"/work/Notes/{filename}",
            copied_at=AT,
            created_by_session_id=run.id,
        )
    )
    db.flush()


class TestDefinitionChat:
    """The definition chat's first Turn, from the plus (design 3 §5.3)."""

    def test_an_empty_drafts_brief_is_the_draft_its_starter_and_the_message(
        self, briefs: BriefService, draft: Project, person: User
    ) -> None:
        assert briefs.definition_chat(draft, person, "Garden sensors?", AT) == (
            "/create\n\n"
            "Pilot's brief · the definition chat ·"
            f" /work/Projects/draft-{draft.number} · 2026-10-26T09:30:15Z\n\n"
            "The draft: project.md, empty. The person who started it: ada"
            " (member).\n"
            "Attachments so far: none.\n\n"
            "The message:\n"
            "Garden sensors?"
        )

    def test_a_written_draft_names_the_project_and_counts_what_is_attached(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        draft: Project,
        person: User,
        project_session: models.Session,
    ) -> None:
        document = session.scalars(
            select(Document).where(Document.project_id == draft.id)
        ).one()
        container.document_service().publish(document, "# Garden sensors\n\nSoil.\n")
        _attached(session, draft, project_session, "soil.md")

        brief = briefs.definition_chat(draft, person, "Hi", AT)

        assert brief.startswith(
            "/create\n\n"
            'Pilot\'s brief · the definition chat · project "Garden sensors" ·'
            f" /work/Projects/draft-{draft.number} · 2026-10-26T09:30:15Z\n\n"
            "The draft: project.md. The person who started it: ada (member).\n"
            "Attachments so far: 1 file (timeline.json lists it).\n\n"
        )
        _attached(session, draft, project_session, "rain.md")
        assert "\nAttachments so far: 2 files (timeline.json lists them).\n" in (
            briefs.definition_chat(draft, person, "Hi", AT)
        )

    def test_another_persons_first_message_is_named(
        self, container: ServiceContainer, briefs: BriefService, draft: Project
    ) -> None:
        bea = container.test_data_service().person("bea", "Bea Example")

        brief = briefs.definition_chat(draft, bea, "Hi", AT)

        assert brief.endswith(
            "The person who started it: ada (member).\n"
            "Attachments so far: none.\n\n"
            "The message, from bea (not a member):\n"
            "Hi"
        )

    def test_it_ends_with_the_words_verbatim(
        self, briefs: BriefService, draft: Project, person: User
    ) -> None:
        words = '  <quoted_path path="project.md">Soil</quoted_path path="project.md">\n\nWhy?\n'

        assert briefs.definition_chat(draft, person, words, AT).endswith(
            f"The message:\n{words}"
        )


SETUP = Work(trigger_code=WorkTrigger.SETUP)
"""The setup's Work, as the brief reads it."""

LATER = datetime(2026, 10, 26, 11, 5, 40, tzinfo=UTC)
"""When a job held since `AT` leaves the queue or the pause."""


class TestSetup:
    """The setup's first Turn, triggered at Create project (design 3 §5.3;
    F49)."""

    def test_it_names_the_drafts_folder_the_opening_and_the_empty_plan(
        self,
        container: ServiceContainer,
        briefs: BriefService,
        opened: Project,
        person: User,
    ) -> None:
        opening = container.document_service().bear_opening(
            opened, "Ada Example started this project", person, "Soup?"
        )

        assert briefs.job(opened, SETUP, AT, AT) == (
            "/plan\n\n"
            'Pilot\'s brief · the setup · project "Soup club" ·'
            " /work/Projects/soup-club · 2026-10-26T09:30:15Z\n\n"
            "Auto pilot: off — the granted column asks for this session"
            " (rules/grants.md).\n\n"
            f"The project was created 2026-10-26T09:30:15Z from"
            f" draft-{opened.number}; its folder is now /work/Projects/soup-club.\n"
            f"The draft: project.md (the opening item {opening.id} holds the words"
            " that started it; the draft's copy and what the chat attached hang on"
            " it).\n"
            "The plan: plan.json, empty."
        )

    @pytest.mark.parametrize("resumed", [False, True])
    def test_under_a_pause_it_composes_with_no_pause_line(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        opened: Project,
        person: User,
        resumed: bool,
    ) -> None:
        """Paused at Create's instant by Pilot, its trigger's, and still
        paused, or resumed and paused again by a person before a Retry: the
        pause holds no setup, whose brief is the one with no pause (D083)."""
        container.document_service().bear_opening(
            opened, "Ada Example started this project", person, "Soup?"
        )
        unpaused = briefs.job(opened, SETUP, AT, LATER)
        pilot = session.scalars(
            select(User).where(User.kind_code == UserKind.AGENT)
        ).one()
        _transition(session, opened, pilot, TransitionKind.PAUSED, AT)
        if resumed:
            _transition(session, opened, person, TransitionKind.RESUMED, RESUMED_AT)
            _transition(session, opened, person, TransitionKind.PAUSED, LATER)

        assert briefs.job(opened, SETUP, AT, LATER) == unpaused
        assert "paused" not in unpaused

    def test_composed_later_its_stamp_and_switch_are_then_its_creation_creates(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        opened: Project,
        person: User,
    ) -> None:
        """Held, it is composed as it leaves the queue: the stamp and the
        switch are the record's then, Create's instant stays Create's (F59,
        F54.7)."""
        container.document_service().bear_opening(
            opened, "Ada Example started this project", person, "Soup?"
        )
        opened.autopilot = True
        session.flush()

        brief = briefs.job(opened, SETUP, AT, LATER)

        assert brief.startswith(
            "/plan\n\n"
            'Pilot\'s brief · the setup · project "Soup club" ·'
            " /work/Projects/soup-club · 2026-10-26T11:05:40Z\n\n"
            "Auto pilot: on — the granted column holds for this session"
            " (rules/grants.md).\n\n"
            "The project was created 2026-10-26T09:30:15Z from"
        )

    def test_a_project_with_no_title_is_named_by_its_folder_alone(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        opened: Project,
        person: User,
    ) -> None:
        """A draft with a body and no title names no project (`_frame`)."""
        opened.name = None
        session.flush()
        container.document_service().bear_opening(
            opened, "Ada Example started this project", person, "Soup?"
        )

        assert briefs.job(opened, SETUP, AT, AT).startswith(
            "/plan\n\n"
            "Pilot's brief · the setup · /work/Projects/soup-club ·"
            " 2026-10-26T09:30:15Z\n\n"
        )


WORKER_ENV = "example-soup-3f2a1c"
ENDED = datetime(2026, 10, 26, 9, 29, 50, tzinfo=UTC)
LAST_WORDS = "Fixed the stock.\n\n  Registered the notes; ending the turn.\n"
STOCK = "# The stock\n\nLeek, not onion.\n"
CUT_OVER = """# The cut-over

```action id=A1
answer: Pilot does it
by: agent
at: 2026-10-26T09:00:00Z
```

```action id=A2
done: 2026-10-26T09:10:00Z
by: ada
note: Salted it myself
```

```action id=A3
answer: Pilot does it
by: agent
at: 2026-10-26T09:00:00Z
```

```action id=A4
```
"""


def _worker_run(
    db: DbSession, container: ServiceContainer, project: Project, task: str | None
) -> models.Session:
    """A worker's run in an environment of Pilot's, placed on `task`."""
    db.add(Environment(id=WORKER_ENV, name="Soup-1", exempt=False))
    run = models.Session(
        project_id=project.id,
        environment_id=WORKER_ENV,
        kind_code="work",
        cwd="/work/Soup",
        controller_session="claude-7",
        token_hash="7" * 64,
        state_code=SessionState.RUNNING,
    )
    db.add(run)
    db.flush()
    container.record_service().place_work(
        project, run, "Fixing the stock", task, repo="example/Soup"
    )
    return run


def _turn_ended(
    db: DbSession, container: ServiceContainer, run: models.Session, words: str
) -> None:
    """The run's turn ended well at `ENDED` with `words`, as the relay ends
    it: its `result` record, the Session idle, its work item done."""
    turn = Turn(session_id=run.id, seq=1, message="Fix the stock.", started_at=ENDED)
    turn.ended_at = ENDED
    db.add(turn)
    db.flush()
    _records(db, container).append(
        run.id,
        RecordKind.RESULT,
        payload={"type": "result", "subtype": "success", "result": words},
        turn_id=turn.id,
        raw_offset=1,
        controller_session="claude-7",
    )
    run.state_code = SessionState.IDLE
    container.record_service().work_done(run.id, ENDED)


def _records(db: DbSession, container: ServiceContainer) -> SessionRecordService:
    return SessionRecordService(
        db, container.session_stream_service(), ViewService(db, container.engine_bus())
    )


def _after(run: models.Session) -> Work:
    """The job after the run's turn, as the brief reads it."""
    return Work(trigger_code=WorkTrigger.WORKER_TURN_ENDED, trigger_item_id=run.id)


class TestWorkerTurnEnded:
    """The job after a worker's turn, once the turn-end read settled every
    document the run registered (design 3 §5.3, D2; F57.4; V03, V12)."""

    def test_every_line_that_holds_is_in_the_frames_order(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        opened: Project,
        person: User,
        project_session: models.Session,
    ) -> None:
        opened.autopilot = True
        assert container.plan_service().save(opened, json.dumps(PLAN).encode()) == []
        deferring = container.document_service().bear_item(
            opened, "decision", "Soup chores", project_session, DEFERRED
        )
        container.record_service().done(deferring, person)
        run = _worker_run(session, container, opened, "fix")
        documents = container.document_service()
        stock = documents.register(opened, run, "/work/Soup/stock.md").item
        notes = documents.register(opened, run, "/work/Soup/notes.md").item
        _attached(session, opened, run, "stock.txt")
        _attached(session, opened, run, "salt.txt")
        for position, attachment in enumerate(
            session.scalars(select(Attachment).order_by(Attachment.filename)), 1
        ):
            session.add(
                ItemAttachment(
                    item_id=run.id,
                    attachment_id=attachment.id,
                    position=position,
                    attached_at=AT,
                )
            )
        _turn_ended(session, container, run, LAST_WORDS)
        documents.publish_read(session.get_one(Document, stock.id), STOCK, run.id)
        documents.fail_read(session.get_one(Document, notes.id))
        _records(session, container).append(
            run.id,
            RecordKind.SERVER,
            payload={
                "type": READ_FAILED,
                "item": str(notes.id),
                "path": "/work/Soup/notes.md",
                "reason": "the controller answered 404 not-found: no such file",
            },
        )

        brief = briefs.job(opened, _after(run), AT, LATER)

        stock_path = session.get_one(Document, stock.id).path
        notes_path = session.get_one(Document, notes.id).path
        path = f"soup-club/{session.get_one(Document, deferring.id).path}"
        assert brief == (
            "/pre-rule\n\n"
            "Pilot's brief · a worker's turn ended · project \"Soup club\" ·"
            " /work/Projects/soup-club · 2026-10-26T11:05:40Z\n\n"
            "Auto pilot: on — the granted column holds for this session"
            " (rules/grants.md).\n\n"
            f'The work item: "Fixing the stock" ({run.id}), task fix "Fix the'
            ' stock", repository example/Soup, environment example-soup-3f2a1c,'
            " session claude-7; its turn ended 2026-10-26T09:29:50Z — the item's"
            ' last line: "Registered the notes; ending the turn.".\n'
            "Registered this run, in the order registered:\n"
            f"- {stock_path} ({stock.id}) — published\n"
            f"- {notes_path} ({notes.id}) — read failed: the controller answered"
            " 404 not-found: no such file\n"
            "Attached on the work item: 2 files (timeline.json lists them).\n\n"
            f"{NOTES}\n"
            '- fix "Fix the stock" · n1: Ask about salt\n'
            '- taste "Taste it" · n3: Two spoons\n'
            "- the plan · n2: Add a sweep task\n"
            f"{HOMELESS}\n"
            f"- {deferring.id}/D1 in {path} (Soup chores), to: fix\n"
            f"- {deferring.id}/Q1 in {path} (Soup chores), to: plan"
        )

    def test_a_run_that_registered_nothing_says_so_and_no_line_holds_unheld(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        opened: Project,
    ) -> None:
        """No task, no text its turn ended with, nothing attached and no note:
        each line left out."""
        run = _worker_run(session, container, opened, None)
        _turn_ended(session, container, run, "")

        assert briefs.job(opened, _after(run), AT, AT).split("\n\n")[3:] == [
            f'The work item: "Fixing the stock" ({run.id}), repository'
            " example/Soup, environment example-soup-3f2a1c, session claude-7;"
            " its turn ended 2026-10-26T09:29:50Z.\n"
            "Registered nothing this run."
        ]

    def test_the_claimed_actions_it_was_given_are_named_as_they_stand(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        opened: Project,
        project_session: models.Session,
    ) -> None:
        """Each action whose latest naming is this run, open while it is
        still claimed, else as its close reads; one a retry named since is
        the retry's (DB 260; design 3 §6.5)."""
        documents = container.document_service()
        cut_over = documents.register(
            opened, project_session, "/work/Soup/cut-over.md"
        ).item
        documents.publish_read(
            session.get_one(Document, cut_over.id), CUT_OVER, project_session.id
        )
        run = _worker_run(session, container, opened, None)
        retry = models.Session(
            project_id=opened.id,
            kind_code="work",
            cwd="/work/Soup",
            token_hash="8" * 64,
            state_code=SessionState.STARTING,
        )
        session.add(retry)
        session.flush()
        container.record_service().place_work(opened, retry, "Salting it again")
        blocks = dict(
            session.execute(
                select(Block.local_id, Block.id).where(Block.document_id == cut_over.id)
            ).all()
        )
        session.add_all(
            [
                *(
                    ClaimAssignment(work_id=run.id, block_id=blocks[local_id])
                    for local_id in ("A1", "A2", "A3", "A4")
                ),
                ClaimAssignment(work_id=retry.id, block_id=blocks["A3"]),
            ]
        )
        session.flush()
        _turn_ended(session, container, run, "")

        path = session.get_one(Document, cut_over.id).path
        assert briefs.job(opened, _after(run), AT, AT).split("\n\n")[3] == (
            f'The work item: "Fixing the stock" ({run.id}), repository'
            " example/Soup, environment example-soup-3f2a1c, session claude-7;"
            " its turn ended 2026-10-26T09:29:50Z.\n"
            "Registered nothing this run.\n"
            "The claimed actions given to this work item, as they stand:\n"
            f"- {path} ({cut_over.id}) A1 open, claimed\n"
            f'- {path} ({cut_over.id}) A2 done (by ada), pasted back: "Salted it'
            ' myself"\n'
            f"- {path} ({cut_over.id}) A4 open, its claim gone"
        )

    def test_a_trigger_in_a_pause_carries_it_after_the_switch(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        opened: Project,
        person: User,
    ) -> None:
        run = _worker_run(session, container, opened, None)
        _turn_ended(session, container, run, LAST_WORDS)
        _transition(session, opened, person, TransitionKind.PAUSED, PAUSED_AT)
        _transition(session, opened, person, TransitionKind.RESUMED, RESUMED_AT)

        assert briefs.job(opened, _after(run), AT, LATER).split("\n\n")[2] == (
            "Auto pilot: off — the granted column asks for this session"
            f" (rules/grants.md).\n{PAUSE_LINE}"
        )


CACHE = """# The cut-over

```question id=Q1
```

## Which cache?

```decision id=D2
options:
  - OpenAPI
  - Vite
```

## Keep the shim?

```decision id=D4
options:
  - Keep
  - Drop
```
"""
ASKED = datetime(2026, 10, 26, 9, 31, 0, tzinfo=UTC)
REPLIED = datetime(2026, 10, 26, 9, 40, 0, tzinfo=UTC)
ASKS_NOTHING = (
    "This pass asks nothing: what is still unclear is the operator's, the"
    " clarification beside the ask."
)


class TestWriterAnswered:
    """The job after a clarification run's turn: the run, the questions as
    asked and the writer's answer as each document records it, and that the
    pass asks nothing (design 3 §5.1, §5.3; DB 256, 257; V08)."""

    def _asked(
        self,
        db: DbSession,
        container: ServiceContainer,
        project: Project,
        documents: dict[str, str],
        questions: list[tuple[str, str, str]],
    ) -> tuple[models.Session, dict[str, Item]]:
        """A worker's run on task fix that registered `documents`, by path,
        its turn ended, and the pass after it, which asked `questions`, each
        a path, a local id and the question, in that order."""
        assert container.plan_service().save(project, json.dumps(PLAN).encode()) == []
        run = _worker_run(db, container, project, "fix")
        run.conversation_id = "conv-soup"
        registered = {
            path: container.document_service().register(project, run, path).item
            for path in documents
        }
        _turn_ended(db, container, run, LAST_WORDS)
        for path, text in documents.items():
            container.document_service().publish_read(
                db.get_one(Document, registered[path].id), text, run.id
            )
        asking = models.Session(
            project_id=project.id,
            kind_code="job",
            cwd="/work/PilotProjects",
            token_hash="9" * 64,
            state_code=SessionState.IDLE,
        )
        db.add(asking)
        db.flush()
        turn = Turn(session_id=asking.id, seq=1, message="/pre-rule", started_at=ASKED)
        db.add(turn)
        container.record_service().place_work(
            project,
            asking,
            "Pre-ruling soup-club/2",
            trigger=WorkTrigger.WORKER_TURN_ENDED,
            trigger_item_id=run.id,
        )
        for path, local_id, question in questions:
            db.add(
                WriterQuestion(
                    turn_id=turn.id,
                    block_id=db.scalars(
                        select(Block.id).where(
                            Block.document_id == registered[path].id,
                            Block.local_id == local_id,
                        )
                    ).one(),
                    question=question,
                    asked_at=ASKED,
                )
            )
        db.flush()
        return asking, registered

    def _clarifying(
        self,
        db: DbSession,
        container: ServiceContainer,
        project: Project,
        asking: models.Session,
        reply: str | None,
        title: str,
    ) -> models.Session:
        """The pass's clarification run, its turn ended at `REPLIED` with
        `reply`."""
        clarifying = models.Session(
            project_id=project.id,
            environment_id=WORKER_ENV,
            kind_code="work",
            conversation_id="conv-soup",
            cwd="/work/Soup",
            token_hash="8" * 64,
            state_code=SessionState.IDLE,
        )
        db.add(clarifying)
        db.flush()
        container.record_service().place_work(
            project, clarifying, title, "fix", repo="example/Soup"
        )
        db.add(
            ClarificationRun(
                id=clarifying.id,
                pass_id=asking.id,
                reply=reply,
                replied_at=None if reply is None else REPLIED,
            )
        )
        container.record_service().work_done(clarifying.id, REPLIED)
        return clarifying

    def test_a_split_reply_per_block_and_every_line_in_the_frames_order(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        opened: Project,
    ) -> None:
        asking, registered = self._asked(
            session,
            container,
            opened,
            {"/work/Soup/cut-over.md": CACHE},
            [
                (
                    "/work/Soup/cut-over.md",
                    "D2",
                    'Does "the cache" mean the OpenAPI one?',
                ),
                ("/work/Soup/cut-over.md", "D4", "Which file is the shim?"),
                ("/work/Soup/cut-over.md", "Q1", "How long is the cut-over?"),
            ],
        )
        clarifying = self._clarifying(
            session,
            container,
            opened,
            asking,
            "Answers below.\n\n## D2\nThe OpenAPI cache.\n\n## D4\nThe old loader,"
            "\nkept until the client is regenerated.\n\n## Q1\nAn hour.",
            "Clarify cut-over.md",
        )
        run = session.get_one(Item, session.get_one(Work, asking.id).trigger_item_id)
        cut_over = registered["/work/Soup/cut-over.md"]

        brief = briefs.job(opened, _after(clarifying), AT, LATER)

        path = session.get_one(Document, cut_over.id).path
        assert brief == (
            "/pre-rule\n\n"
            'Pilot\'s brief · the writer answered · project "Soup club" ·'
            " /work/Projects/soup-club · 2026-10-26T11:05:40Z\n\n"
            "Auto pilot: off — the granted column asks for this session"
            " (rules/grants.md).\n\n"
            'The clarification run: "Clarify cut-over.md"'
            f' ({clarifying.id}), of the work item "Fixing the stock" ({run.id}),'
            " task fix; its turn ended 2026-10-26T09:40:00Z.\n"
            f"Asked 2026-10-26T09:31:00Z on {path} ({cut_over.id}):\n"
            "- Q1: How long is the cut-over?\n"
            '- D2 "Which cache?": Does "the cache" mean the OpenAPI one?\n'
            '- D4 "Keep the shim?": Which file is the shim?\n'
            "The writer's answer, as recorded on the document:\n"
            "- Q1: An hour.\n"
            "- D2: The OpenAPI cache.\n"
            "- D4: The old loader,\n"
            "  kept until the client is regenerated.\n"
            f"Registered this run: nothing. {ASKS_NOTHING}\n\n"
            f"{NOTES}\n"
            '- fix "Fix the stock" · n1: Ask about salt\n'
            '- taste "Taste it" · n3: Two spoons\n'
            "- the plan · n2: Add a sweep task"
        )

    def test_a_reply_that_did_not_keep_the_headings_is_quoted_whole(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        opened: Project,
    ) -> None:
        asking, registered = self._asked(
            session,
            container,
            opened,
            {"/work/Soup/cut-over.md": CACHE},
            [
                ("/work/Soup/cut-over.md", "D2", "Which cache?"),
                ("/work/Soup/cut-over.md", "D4", "Which shim?"),
            ],
        )
        clarifying = self._clarifying(
            session,
            container,
            opened,
            asking,
            "## D2\nThe OpenAPI cache.\n\nThe shim is the old loader.",
            "Clarify cut-over.md",
        )

        group = briefs.job(opened, _after(clarifying), AT, LATER).split("\n\n")[3]

        cut_over = registered["/work/Soup/cut-over.md"]
        path = session.get_one(Document, cut_over.id).path
        assert group.split("\n")[1:] == [
            f"Asked 2026-10-26T09:31:00Z on {path} ({cut_over.id}):",
            '- D2 "Which cache?": Which cache?',
            '- D4 "Keep the shim?": Which shim?',
            "The writer's answer, as recorded on the document, whole — the reply"
            " did not keep the asked headings:",
            "> ## D2",
            "> The OpenAPI cache.",
            ">",
            "> The shim is the old loader.",
            f"Registered this run: nothing. {ASKS_NOTHING}",
        ]

    def test_a_turn_that_ended_with_no_text_has_no_answer(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        opened: Project,
    ) -> None:
        asking, _ = self._asked(
            session,
            container,
            opened,
            {"/work/Soup/cut-over.md": CACHE},
            [("/work/Soup/cut-over.md", "Q1", "How long?")],
        )
        clarifying = self._clarifying(
            session, container, opened, asking, None, "Clarify cut-over.md"
        )

        group = briefs.job(opened, _after(clarifying), AT, LATER).split("\n\n")[3]

        assert group.split("\n")[2:] == [
            "- Q1: How long?",
            "The writer's answer: none — the run's turn ended with no text.",
            f"Registered this run: nothing. {ASKS_NOTHING}",
        ]

    def test_each_document_in_timeline_order_and_what_the_run_registered_anyway(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        opened: Project,
    ) -> None:
        """Two documents of one pass, a local id they share named by its
        document's path; the files attached on the run and a document it
        registered anyway listed as any run's."""
        asking, registered = self._asked(
            session,
            container,
            opened,
            {"/work/Soup/cut-over.md": CACHE, "/work/Soup/drain.md": STOCK + CACHE},
            [
                ("/work/Soup/drain.md", "Q1", "Which queue?"),
                ("/work/Soup/cut-over.md", "Q1", "How long?"),
            ],
        )
        clarifying = self._clarifying(
            session,
            container,
            opened,
            asking,
            "## /work/Soup/cut-over.md Q1\nAn hour.\n## /work/Soup/drain.md Q1\n"
            "The v1 broker's.",
            "Clarify cut-over.md and drain.md",
        )
        notes = (
            container.document_service()
            .register(opened, clarifying, "/work/Soup/notes.md")
            .item
        )
        container.document_service().publish_read(
            session.get_one(Document, notes.id), STOCK, clarifying.id
        )
        _attached(session, opened, clarifying, "salt.txt")
        session.add(
            ItemAttachment(
                item_id=clarifying.id,
                attachment_id=session.scalars(select(Attachment.id)).one(),
                position=1,
                attached_at=AT,
            )
        )
        session.flush()

        group = briefs.job(opened, _after(clarifying), AT, LATER).split("\n\n")[3]

        cut_over = session.get_one(Document, registered["/work/Soup/cut-over.md"].id)
        drain = session.get_one(Document, registered["/work/Soup/drain.md"].id)
        assert group.split("\n")[1:] == [
            f"Asked 2026-10-26T09:31:00Z on {cut_over.path} ({cut_over.id}):",
            "- Q1: How long?",
            "The writer's answer, as recorded on the document:",
            "- Q1: An hour.",
            f"Asked 2026-10-26T09:31:00Z on {drain.path} ({drain.id}):",
            "- Q1: Which queue?",
            "The writer's answer, as recorded on the document:",
            "- Q1: The v1 broker's.",
            "Attached on the work item: 1 file (timeline.json lists it).",
            "Registered this run, in the order registered:",
            f"- {session.get_one(Document, notes.id).path} ({notes.id}) — published",
            ASKS_NOTHING,
        ]


PAUSED_AT = datetime(2026, 10, 26, 9, 0, 0, tzinfo=UTC)
RESUMED_AT = datetime(2026, 10, 26, 11, 5, 0, tzinfo=UTC)
PAUSE_LINE = (
    "Paused 2026-10-26T09:00:00Z to 2026-10-26T11:05:00Z: this job's trigger"
    " happened while the project was paused; the record moved on meanwhile."
)


class TestJobPause:
    """A job whose trigger came while its project was paused carries the
    pause it came in, its interval and that the record moved on (design 3
    §5.2; F141.4; V11). The setup carries none: the pause holds it not
    (D083)."""

    @pytest.fixture
    def job(
        self, session: DbSession, container: ServiceContainer, opened: Project
    ) -> Work:
        """The job after a worker's turn, as the brief reads it."""
        run = _worker_run(session, container, opened, None)
        _turn_ended(session, container, run, LAST_WORDS)
        return _after(run)

    def test_a_trigger_in_a_pause_carries_it_after_the_switch(
        self,
        session: DbSession,
        briefs: BriefService,
        opened: Project,
        person: User,
        job: Work,
    ) -> None:
        _transition(session, opened, person, TransitionKind.PAUSED, PAUSED_AT)
        _transition(session, opened, person, TransitionKind.RESUMED, RESUMED_AT)

        assert briefs.job(opened, job, AT, LATER).split("\n\n")[2] == (
            "Auto pilot: off — the granted column asks for this session"
            f" (rules/grants.md).\n{PAUSE_LINE}"
        )

    def test_of_two_pauses_it_names_the_one_its_trigger_came_in(
        self,
        session: DbSession,
        briefs: BriefService,
        opened: Project,
        person: User,
        job: Work,
    ) -> None:
        early = datetime(2026, 10, 26, 8, 0, 0, tzinfo=UTC)
        _transition(session, opened, person, TransitionKind.PAUSED, early)
        _transition(
            session, opened, person, TransitionKind.RESUMED, early.replace(minute=30)
        )
        _transition(session, opened, person, TransitionKind.PAUSED, PAUSED_AT)
        _transition(session, opened, person, TransitionKind.RESUMED, RESUMED_AT)
        _transition(
            session, opened, person, TransitionKind.PAUSED, RESUMED_AT.replace(minute=6)
        )
        _transition(
            session,
            opened,
            person,
            TransitionKind.RESUMED,
            RESUMED_AT.replace(minute=7),
        )

        assert PAUSE_LINE in briefs.job(opened, job, AT, LATER)

    @pytest.mark.parametrize(
        ("paused", "resumed"),
        [
            # Over before the trigger came.
            (PAUSED_AT, PAUSED_AT.replace(minute=30)),
            # Begun after it, while the job waited its turn.
            (AT.replace(minute=45), RESUMED_AT),
        ],
    )
    def test_a_trigger_outside_a_pause_carries_none(
        self,
        session: DbSession,
        briefs: BriefService,
        opened: Project,
        person: User,
        paused: datetime,
        resumed: datetime,
        job: Work,
    ) -> None:
        _transition(session, opened, person, TransitionKind.PAUSED, paused)
        _transition(session, opened, person, TransitionKind.RESUMED, resumed)

        assert "Paused" not in briefs.job(opened, job, AT, LATER)


CONFIRM = """---
title: Push the stock
step: fix
---

```decision id=C1
type: confirmation
because: rider
proposal: Push the three commits.
```
"""

CHOICE = """---
title: Leek or onion
---

```decision id=D1
options:
  - Leek
  - Onion
```
"""

AGREE = """---
title: Salt it
---

```decision id=D1
proposal: Salt it.
```
"""

ASK = """---
title: When to taste
---

```question id=Q1
```
"""

CHORE = """---
title: Stir the pot
---

```action id=A1
```
"""

PLAN_DONE = """---
title: Soup plan
step: fix
---

```decision id=D1
options:
  - Leek
  - Onion
answer: Leek
by: agent
at: 2026-10-12T09:30:00Z
```

```question id=Q1
default: Tomorrow
```

```decision id=D2
proposal: Salt it.
answer: deferred
by: agent
at: 2026-10-12T09:30:00Z
to: fix
note: At the stove.
```

```action id=A1
done: 2026-10-12T11:00:00Z
by: ada
note: Stirred twice.
```
"""


def _closing(item: Item) -> Work:
    """The job after the item's close, as the brief reads it."""
    return Work(trigger_code=WorkTrigger.ITEM_DONE, trigger_item_id=item.id)


def _item_line(db: DbSession, item: Item, closed: str) -> str:
    """The item's line before its close, read from the record."""
    head = f"The item: {db.get_one(Document, item.id).path} ({item.id})"
    return f'{head}, {item.kind_code} "{item.title}"{closed}'


class TestItemDone:
    """The job after a person's close of an item of Pilot's own: the item and
    what was done to it, as the record holds it, then the notes of the task
    it names and the plan's own (design 3 §5.3; DB decision 45; F57.4; V03,
    V12)."""

    @pytest.fixture
    def planned(self, container: ServiceContainer, opened: Project) -> Project:
        assert container.plan_service().save(opened, json.dumps(PLAN).encode()) == []
        return opened

    def _bear(
        self,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        kind: str,
        text: str,
    ) -> tuple[Item, Document]:
        item = container.document_service().bear_item(
            project, kind, kind.title(), project_session, text
        )
        return item, container.db_session().get_one(Document, item.id)

    def test_a_confirmations_yes_and_every_line_in_the_frames_order(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        planned: Project,
        person: User,
        project_session: models.Session,
    ) -> None:
        deferring = container.document_service().bear_item(
            planned, "decision", "Soup chores", project_session, DEFERRED
        )
        container.record_service().done(deferring, person)
        item, document = self._bear(
            container, planned, project_session, "confirmation", CONFIRM
        )
        container.record_service().answer(document, "C1", person, "Yes")

        brief = briefs.job(planned, _closing(item), AT, LATER)

        assert item.done_at is not None
        head, switch, closed, notes = brief.split("\n\n")[1:]
        assert head == (
            'Pilot\'s brief · an item of yours is done · project "Soup club" ·'
            " /work/Projects/soup-club · 2026-10-26T11:05:40Z"
        )
        assert brief.startswith("/plan\n\n")
        assert switch == (
            "Auto pilot: off — the granted column asks for this session"
            " (rules/grants.md)."
        )
        assert closed == _item_line(
            session,
            item,
            f", task fix — answered Yes by ada at {_z(item.done_at)}.",
        )
        path = f"soup-club/{session.get_one(Document, deferring.id).path}"
        assert notes == (
            f"{NOTES}\n"
            '- fix "Fix the stock" · n1: Ask about salt\n'
            "- the plan · n2: Add a sweep task\n"
            f"{HOMELESS}\n"
            f"- {deferring.id}/D1 in {path} (Soup chores), to: fix\n"
            f"- {deferring.id}/Q1 in {path} (Soup chores), to: plan"
        )

    def test_a_no_carries_its_reason(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        planned: Project,
        person: User,
        project_session: models.Session,
    ) -> None:
        item, document = self._bear(
            container, planned, project_session, "confirmation", CONFIRM
        )
        container.record_service().answer(
            document, "C1", person, "No", via=AnswerChannel.CHAT, note="Not today"
        )

        assert briefs.job(planned, _closing(item), AT, LATER).split("\n\n")[3] == (
            _item_line(
                session,
                item,
                f", task fix — answered No by ada at {_z(item.done_at)}"
                ' (via chat), its reason: "Not today".',
            )
        )

    def test_a_deferral_carries_where_it_was_deferred_to(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        planned: Project,
        person: User,
        project_session: models.Session,
    ) -> None:
        item, document = self._bear(
            container, planned, project_session, "confirmation", CONFIRM
        )
        container.record_service().answer(
            document, "C1", person, "deferred", via=AnswerChannel.CHAT, to="plan"
        )

        assert briefs.job(planned, _closing(item), AT, LATER).split("\n\n")[3] == (
            _item_line(
                session,
                item,
                f", task fix — answered deferred to plan by ada at"
                f" {_z(item.done_at)} (via chat).",
            )
        )

    @pytest.mark.parametrize(
        ("kind", "text", "local_id", "answer", "note", "said"),
        [
            pytest.param(
                "decision",
                CHOICE,
                "D1",
                "Leek",
                "Sweeter",
                'D1 answered Leek by ada at {at}, note: "Sweeter".',
                id="an-option",
            ),
            pytest.param(
                "decision",
                CHOICE,
                "D1",
                "Both, halved",
                None,
                'D1 answered "Both, halved" (Other) by ada at {at}.',
                id="free-words",
            ),
            pytest.param(
                "decision",
                AGREE,
                "D1",
                "Agree",
                None,
                "D1 answered Agree by ada at {at}.",
                id="a-proposals-agree",
            ),
            pytest.param(
                "question",
                ASK,
                "Q1",
                "After lunch",
                None,
                'Q1 answered "After lunch" by ada at {at}.',
                id="a-question",
            ),
            pytest.param(
                "decision",
                CHOICE,
                "D1",
                "deferred",
                None,
                "D1 answered deferred to fix by ada at {at}.",
                id="deferred",
            ),
        ],
    )
    def test_a_one_ask_items_answer_is_its_block_as_answered(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        planned: Project,
        person: User,
        project_session: models.Session,
        kind: str,
        text: str,
        local_id: str,
        answer: str,
        note: str | None,
        said: str,
    ) -> None:
        item, document = self._bear(container, planned, project_session, kind, text)
        container.record_service().answer(
            document,
            local_id,
            person,
            answer,
            note=note,
            to="fix" if answer == "deferred" else None,
        )

        assert briefs.job(planned, _closing(item), AT, LATER).split("\n\n")[3] == (
            _item_line(session, item, f" — {said.format(at=_z(item.done_at))}")
        )

    def test_an_actions_done_carries_what_was_pasted_back(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        planned: Project,
        person: User,
        project_session: models.Session,
    ) -> None:
        item, document = self._bear(
            container, planned, project_session, "action", CHORE
        )
        container.record_service().done_action(document, "A1", person, note="Twice")

        assert briefs.job(planned, _closing(item), AT, LATER).split("\n\n")[3] == (
            _item_line(
                session,
                item,
                f' — A1 done by ada at {_z(item.done_at)}, pasted back: "Twice".',
            )
        )

    def test_a_documents_done_reads_one_line_per_block_as_closed(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        planned: Project,
        person: User,
        project_session: models.Session,
    ) -> None:
        item, _ = self._bear(container, planned, project_session, "document", PLAN_DONE)
        container.record_service().done(item, person)

        assert briefs.job(planned, _closing(item), AT, LATER).split("\n\n")[3] == (
            _item_line(
                session, item, f", task fix — Done by ada at {_z(item.done_at)};"
            )
            + " its blocks:\n"
            "- D1 Leek (by agent)\n"
            '- Q1 "Tomorrow" (via recommended)\n'
            '- D2 deferred to fix (by agent), note: "At the stove."\n'
            '- A1 done, pasted back: "Stirred twice."'
        )

    def test_a_reviews_reviewed_is_who_and_when(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        planned: Project,
        person: User,
        project_session: models.Session,
    ) -> None:
        item, _ = self._bear(
            container, planned, project_session, "review", "# The tasting\n"
        )
        container.record_service().reviewed(item, person)

        assert briefs.job(planned, _closing(item), AT, LATER).split("\n\n")[3] == (
            _item_line(session, item, f" — Reviewed by ada at {_z(item.done_at)}.")
        )

    def test_an_item_naming_no_task_carries_the_plans_own_notes_alone(
        self,
        container: ServiceContainer,
        briefs: BriefService,
        planned: Project,
        person: User,
        project_session: models.Session,
    ) -> None:
        item, document = self._bear(
            container, planned, project_session, "question", ASK
        )
        container.record_service().answer(document, "Q1", person, "Now")

        assert briefs.job(planned, _closing(item), AT, LATER).split("\n\n")[4] == (
            f"{NOTES}\n- the plan · n2: Add a sweep task"
        )

    def test_a_trigger_in_a_pause_carries_it_after_the_switch(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        opened: Project,
        person: User,
        project_session: models.Session,
    ) -> None:
        item, document = self._bear(container, opened, project_session, "question", ASK)
        container.record_service().answer(document, "Q1", person, "Now")
        _transition(session, opened, person, TransitionKind.PAUSED, PAUSED_AT)
        _transition(session, opened, person, TransitionKind.RESUMED, RESUMED_AT)

        assert briefs.job(opened, _closing(item), AT, LATER).split("\n\n")[2] == (
            "Auto pilot: off — the granted column asks for this session"
            f" (rules/grants.md).\n{PAUSE_LINE}"
        )


def _z(moment: datetime | None) -> str:
    assert moment is not None
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


FINISH = (
    "This project is finished (2026-10-25T18:00:00Z): you read only — no"
    " `pilot-store`, nothing under `/work` you can write. Answer from the tree,"
    " the records and the fleet tools; what you would change, say so and name"
    " who can."
)


class TestFinishedProjectChat:
    def test_the_finish_line_stands_in_place_of_the_switch_and_no_notes(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        opened: Project,
        person: User,
        project_session: models.Session,
    ) -> None:
        session.add(
            ProjectMember(project_id=opened.id, user_id=person.id, joined_at=AT)
        )
        assert container.plan_service().save(opened, json.dumps(PLAN).encode()) == []
        item = container.document_service().bear_item(
            opened, "decision", "Soup chores", project_session, DEFERRED
        )
        container.record_service().done(item, person)
        container.document_service().bear_handbook(
            opened, "# Handbook\n\n- Salt the stock last.\n"
        )
        for kind, at in (
            (TransitionKind.FINISHED, datetime(2026, 10, 20, tzinfo=UTC)),
            (TransitionKind.REOPENED, datetime(2026, 10, 21, tzinfo=UTC)),
            (TransitionKind.FINISHED, datetime(2026, 10, 25, 18, tzinfo=UTC)),
        ):
            _transition(session, opened, person, kind, at)
        opened.state_code = ProjectState.FINISHED
        _closed_chat(session, opened, datetime(2026, 10, 25, 18, tzinfo=UTC))

        brief = briefs.project_chat(opened, person, "What was settled?", AT)

        assert brief == (
            "/chat\n\n"
            "Pilot's brief · a finished project's chat · project \"Soup club\" ·"
            " /work/Projects/soup-club · 2026-10-26T09:30:15Z\n\n"
            f"{FINISH}\n\n"
            "Earlier chats of this project are in chat.md; the latest closed"
            " 2026-10-25T18:00:00Z.\n\n"
            "The message, from ada (member):\n"
            "What was settled?"
        )


def _fault(
    db: DbSession,
    path: str,
    line: int | None,
    message: str,
    kind: ErrorKind = ErrorKind.PARSE,
) -> None:
    db.add(
        SaveError(
            environment_id=STORE_ENVIRONMENT_ID,
            path=path,
            kind_code=kind,
            line=line,
            message=message,
        )
    )
    db.flush()


class TestFollowUp:
    def test_each_held_path_is_named_with_its_faults_as_the_check_prints_them(
        self, session: DbSession, briefs: BriefService, environment: Environment
    ) -> None:
        item = "soup-club/items/7-soup.md"
        handbook = "soup-club/handbook.md"
        _fault(session, item, 12, "block D1: recommend: Rack names no option")
        _fault(session, handbook, None, "front matter: not YAML")
        _fault(session, item, None, "the text has no title")
        _fault(session, item, 3, "a reverted save", ErrorKind.REVERTED)
        _fault(session, "soup-club/items/8-other.md", 1, "not held by this turn")

        follow_up = briefs.follow_up([handbook, item])

        assert follow_up == (
            f"Your save of `{handbook}` is held:"
            f" `{handbook}: front matter: not YAML`.\n"
            f"Your save of `{item}` is held:"
            f" `{item}:12: block D1: recommend: Rack names no option`,"
            f" `{item}: the text has no title`.\n"
            "Fix it and end your turn."
        )

    def test_it_is_known_by_its_last_line_on_a_turn_with_no_author(
        self, person: User, project_session: models.Session
    ) -> None:
        def turn(message: str, author: User | None = None) -> Turn:
            return Turn(
                session_id=project_session.id,
                seq=2,
                message=message,
                author_user_id=None if author is None else author.id,
            )

        assert is_follow_up(
            turn(f"Your save of `a.md` is held: `a.md: x`.\n{FOLLOW_UP_END}")
        )
        assert not is_follow_up(turn("continue"))
        assert not is_follow_up(turn(f"Quoting you: {FOLLOW_UP_END}", person))


def _task(db: DbSession, project: Project) -> PlanTask:
    task = PlanTask(
        project_id=project.id,
        task_id="t3",
        position=1,
        title="Plan slice 003",
        status_code=TaskStatus.PENDING,
    )
    db.add(task)
    db.flush()
    return task


class TestWorkItem:
    def test_the_brief_is_followed_by_the_trailer_every_line_that_holds(
        self,
        session: DbSession,
        container: ServiceContainer,
        briefs: BriefService,
        opened: Project,
    ) -> None:
        opened.autopilot = True
        container.document_service().bear_handbook(
            opened, "# Soup club\n\nThe stock is the club's own.\n"
        )

        assert briefs.work_item(
            opened, "Plan the stock.\n\n", _task(session, opened)
        ) == (
            "Plan the stock.\n\n"
            "From Pilot:\n"
            '- This work item serves plan task t3 "Plan slice 003": write `step: t3`'
            " into the front matter of every document you register.\n"
            "- Auto pilot is on: the grants above hold for this session.\n"
            "- The project's handbook:\n"
            "# Soup club\n\nThe stock is the club's own.\n"
        )

    def test_with_no_task_and_auto_pilot_off_the_switch_stands_alone(
        self, briefs: BriefService, opened: Project
    ) -> None:
        assert briefs.work_item(opened, "Rename the badge.", None) == (
            "Rename the badge.\n\n"
            "From Pilot:\n"
            "- Auto pilot is off: the grants above ask the operator first for this"
            " session."
        )

    @pytest.mark.parametrize("handbook", ["", "\n  \n"])
    def test_a_blank_handbook_is_left_out(
        self,
        container: ServiceContainer,
        briefs: BriefService,
        opened: Project,
        handbook: str,
    ) -> None:
        container.document_service().bear_handbook(opened, handbook)

        assert briefs.work_item(opened, "Rename the badge.", None).endswith(
            "- Auto pilot is off: the grants above ask the operator first for this"
            " session."
        )
