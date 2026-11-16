"""A calling session's conversation with a project's brain: opened in the
store, briefed, from the environment and the session that called, as the
service user; its caller's Environment row; its later messages, one in
flight at a time; several open at once, beside the project's chat; its
caller's interrupt and end; the store's update, the pause and its project's
Finish, Reopen and Archive (F150.10, F150.12; design 3 §5.3; DB decision 77,
assertions 330 to 337)."""

import json
import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from flask import Flask
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from werkzeug.wrappers import Request, Response

from app import models
from app.database import scoped_session
from app.engine.bus import EngineEvent, ProjectChanged, TreeHashMoved, _Delivery
from app.engine.views import utc_time
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import (
    Chat,
    Conversation,
    Environment,
    Project,
    ProjectTransition,
    Turn,
    User,
)
from app.models.reference import (
    CloseCause,
    ProjectState,
    RecordKind,
    SessionState,
    TransitionKind,
    UserKind,
)
from app.schemas.timeline import HeldReason
from app.services.caller_environment_service import CallerEnvironmentService
from app.services.chat_close_service import ChatCloseService
from app.services.chat_service import HANDBOOK_CHANGED_TOTAL, STORE_NOTIFICATION
from app.services.container import ServiceContainer
from app.services.controller_client import HeadlessCreateRequest
from app.services.controller_outage import ControllerOutage
from app.services.conversation_service import ConversationService
from app.services.environment_service import EnvironmentService
from app.services.pilot_server import PilotServer
from app.services.relay_service import RelayService
from app.services.session_record_service import StoredRecord, read_records
from app.services.session_start_service import SessionStartService
from app.services.start_gate import Held, WorkSlots
from app.services.supervisor import LoopHandle
from app.services.turn_end_read_service import TurnEndReadService
from app.utils import after_commit as after_commit_module
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.chats import open_chat
from tests.support.fake_controller import ServedFakeController, client_of
from tests.support.fake_sidecar import STORE_ENVIRONMENT_ID
from tests.support.locks import in_thread, lock_waits
from tests.support.store_updates import hold, lift
from tests.support.supervisor import WAIT_SECONDS, Supervise, metric_value, wait_until

MCP_URL = "https://pilot-mcp.example.com/mcp"
STORE_REPO = "/work/PilotProjects"
FOLDER = "/work/Projects/soup-club"
CALLER = "example-recipebox-1a2b3c"
CALLER_NAME = "RecipeBox-2"
CALLER_SESSION = "ui-sweep-triage"
WORDS = "How is the stock going?"
THREAD = "thread-1"
"""Claude Code's thread an idle conversation's first turn named."""

KIND = (
    "/chat\n\nPilot's brief · a conversation with a session in RecipeBox-2"
    " (example-recipebox-1a2b3c, session ui-sweep-triage) ·"
)


class _Sent(ServedFakeController):
    """The fake, keeping each send's message."""

    def __init__(self, keepalive_seconds: float) -> None:
        super().__init__(keepalive_seconds)
        self.sent: list[str] = []

    def _send(self, request: Request, env_id: str, name: str) -> Response:
        self.sent.append((request.get_json(silent=True) or {}).get("message"))
        return super()._send(request, env_id, name)


@pytest.fixture(autouse=True)
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


@pytest.fixture
def opened(session: DbSession, project: Project) -> Project:
    """`project` open, named and with its slug."""
    project.state_code = ProjectState.OPEN
    project.slug, project.name = "soup-club", "Soup club"
    session.flush()
    return project


@pytest.fixture
def fake(container: ServiceContainer) -> Iterator[_Sent]:
    """The fake controller, `container`'s client on it: the store running in
    it with the store repo's root and the project's folder on its tree, and
    the caller's environment, which it reports by its name."""
    served = _Sent(keepalive_seconds=0.2)
    client_of(container, served)
    served.add_environment(
        STORE_ENVIRONMENT_ID, name="PilotProjects", status="running", exempt=True
    )
    served.put_file(STORE_ENVIRONMENT_ID, f"{STORE_REPO}/CLAUDE.md", b"# Pilot\n")
    served.put_file(STORE_ENVIRONMENT_ID, f"{FOLDER}/plan.json", b"{}")
    served.add_environment(CALLER, name=CALLER_NAME, status="running")
    try:
        yield served
    finally:
        served.close()


def _starts(
    container: ServiceContainer,
    supervise: Supervise,
    *,
    controller_configured: bool = True,
    work_max: int = 3,
) -> tuple[SessionStartService, RelayService]:
    """The start and the relay on a supervisor of their own, whose loops never
    run, handing Pilot's server at `MCP_URL`, `work_max` running work items
    leaving a work item no slot."""
    supervisor, _ = supervise(container)
    environments = EnvironmentService(
        container=container,
        supervisor=supervisor,
        stop_after_seconds=1800,
        delete_after_seconds=604800,
    )
    slots = WorkSlots(work_max=work_max, project_max=work_max)
    pilot_server = PilotServer(MCP_URL)
    relays = RelayService(
        container=container,
        supervisor=supervisor,
        session_streams=container.session_stream_service(),
        environment_service=environments,
        work_slots=slots,
        pilot_server=pilot_server,
        turn_end_reads=TurnEndReadService(
            container=container,
            supervisor=supervisor,
            session_streams=container.session_stream_service(),
        ),
        chat_closes=ChatCloseService(
            container=container,
            supervisor=supervisor,
            session_streams=container.session_stream_service(),
            close_after_seconds=3300,
        ),
    )
    starts = SessionStartService(
        container=container,
        supervisor=supervisor,
        session_streams=container.session_stream_service(),
        environment_service=environments,
        relay_service=relays,
        controller_outage=container.controller_outage(),
        work_slots=slots,
        usage_halts=container.usage_halts(),
        pilot_server=pilot_server,
        controller_configured=controller_configured,
        store_environment_id=STORE_ENVIRONMENT_ID,
    )
    return starts, relays


def _conversations(
    container: ServiceContainer, starts: SessionStartService, relays: RelayService
) -> ConversationService:
    """The service on the container's session of the calling thread."""
    return ConversationService(
        db=container.db_session(),
        relay_service=relays,
        session_start_service=starts,
        brief_service=container.brief_service(),
        session_record_service=container.session_record_service(),
        caller_environment_service=CallerEnvironmentService(
            db=container.db_session(),
            controller_client=container.controller_client,
            controller_configured=True,
        ),
        chat_close_service=container.chat_close_service(),
        brain_model="opus",
        brain_reasoning_effort="xhigh",
    )


@pytest.fixture
def services(
    container: ServiceContainer, fake: _Sent, supervise: Supervise
) -> tuple[SessionStartService, RelayService]:
    return _starts(container, supervise)


@pytest.fixture
def conversations(
    container: ServiceContainer, services: tuple[SessionStartService, RelayService]
) -> ConversationService:
    return _conversations(container, *services)


def _open(
    conversations: ConversationService,
    project: Project,
    caller: User,
    words: str = WORDS,
    *,
    environment: str = CALLER,
    caller_session: str | None = CALLER_SESSION,
) -> Turn:
    return conversations.open(project.id, caller, environment, caller_session, words)


def _read(db: DbSession, run_id: uuid.UUID) -> models.Session:
    return db.get_one(models.Session, run_id, populate_existing=True)


def _records(db: DbSession, run_id: uuid.UUID) -> list[StoredRecord]:
    return read_records(db, run_id, limit=1000)


def _sends(db: DbSession, run_id: uuid.UUID) -> list[tuple[int | None, str | None]]:
    """The Session's `send` records: each one's Turn's number and its words."""
    return [
        (stored.turn, stored.words)
        for stored in _records(db, run_id)
        if stored.record.kind_code == RecordKind.SEND
    ]


def _callbacks() -> set[str]:
    return {
        type(callback).__name__ for callback in after_commit_module._callbacks.get()
    }


def _emitted() -> list[EngineEvent]:
    """The engine's events the transaction holds for its commit."""
    return [
        callback.event
        for callback in after_commit_module._callbacks.get()
        if isinstance(callback, _Delivery)
    ]


def _rows(db: DbSession, project: Project) -> list[Conversation]:
    return list(
        db.scalars(
            select(Conversation)
            .where(Conversation.project_id == project.id)
            .execution_options(populate_existing=True)
        )
    )


def _turns(db: DbSession) -> int:
    return len(db.scalars(select(Turn)).all())


def _up(
    services: tuple[SessionStartService, RelayService],
    db: DbSession,
    run_id: uuid.UUID,
) -> models.Session:
    """The conversation's start loop run, as its loop calls it: its session
    up and its first Turn sent."""
    services[0].run(run_id, LoopHandle(f"start:{run_id}"))
    clear_after_commit_callbacks()
    return _read(db, run_id)


def _idle(
    services: tuple[SessionStartService, RelayService],
    conversations: ConversationService,
    db: DbSession,
    fake: _Sent,
    project: Project,
    caller: User,
) -> models.Session:
    """A conversation opened with "One", its first turn ended: idle on its
    headless session in the store, which holds the thread that turn named,
    `THREAD`."""
    first = _open(conversations, project, caller, "One")
    clear_after_commit_callbacks()
    run = _up(services, db, first.session_id)
    assert run.controller_session is not None
    fake.play(
        STORE_ENVIRONMENT_ID,
        run.controller_session,
        [
            json.dumps({"type": "system", "subtype": "init", "session_id": THREAD}),
            json.dumps(
                {
                    "type": "assistant",
                    "parent_tool_use_id": None,
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Simmering."}],
                    },
                }
            ),
        ],
    )
    fake.finish(STORE_ENVIRONMENT_ID, run.controller_session, "success", "Done.")
    services[1].relay(run.id, LoopHandle(f"relay:{run.id}"))
    clear_after_commit_callbacks()
    run = _read(db, run.id)
    assert (run.state_code, run.conversation_id) == (SessionState.IDLE, THREAD)
    fake.sent.clear()
    return run


def _transition(
    container: ServiceContainer, project: Project, person: User, kind: TransitionKind
) -> None:
    container.project_service().transition_as(person, project.id, kind)
    clear_after_commit_callbacks()


def _row(db: DbSession, run_id: uuid.UUID) -> Conversation:
    return db.get_one(Conversation, run_id, populate_existing=True)


def _last(db: DbSession, run_id: uuid.UUID) -> Any:
    """The payload of the Session's last record."""
    (last,) = read_records(db, run_id, limit=1, newest_first=True)
    return last.record.payload


def _stopped_turn_ends(
    services: tuple[SessionStartService, RelayService],
    db: DbSession,
    fake: _Sent,
    run_id: uuid.UUID,
) -> models.Session:
    """The stopped conversation's turn in flight ended by the controller's
    interrupt, relayed to its `result` as its loop relays it."""
    run = _read(db, run_id)
    assert run.controller_session is not None
    fake.finish(STORE_ENVIRONMENT_ID, run.controller_session, "interrupted")
    services[1].relay(run.id, LoopHandle(f"relay:{run.id}"))
    clear_after_commit_callbacks()
    return _read(db, run_id)


class TestOpen:
    def test_it_opens_a_conversation_in_the_store_briefed_as_the_service_users_turn(
        self,
        session: DbSession,
        container: ServiceContainer,
        conversations: ConversationService,
        fake: _Sent,
        opened: Project,
        service_user: User,
    ) -> None:
        turn = _open(conversations, opened, service_user)

        (conversation,) = _rows(session, opened)
        assert (
            conversation.id,
            conversation.caller_environment_id,
            conversation.caller_session,
            conversation.closed_at,
            conversation.close_cause_code,
        ) == (turn.session_id, CALLER, CALLER_SESSION, None, None)
        run = _read(session, conversation.id)
        assert (run.kind_code, run.cwd, run.model, run.reasoning_effort) == (
            "conversation",
            STORE_REPO,
            "opus",
            "xhigh",
        )
        assert (run.state_code, run.environment_id, run.controller_session) == (
            SessionState.STARTING,
            None,
            None,
        )
        assert (turn.seq, turn.author_user_id, turn.words) == (
            1,
            service_user.id,
            WORDS,
        )
        assert turn.message == container.brief_service().conversation(
            opened,
            session.get_one(Environment, CALLER),
            CALLER_SESSION,
            WORDS,
            turn.started_at,
        )
        assert turn.message.startswith(KIND)
        assert turn.message.endswith(
            f"\n\nThe message, from the session in RecipeBox-2:\n{WORDS}"
        )
        assert (run.turns, run.turn_started_at, run.turn_ended_at) == (
            1,
            turn.started_at,
            None,
        )
        assert _sends(session, run.id) == [(1, WORDS)]
        assert "_LoopStart" in _callbacks()
        assert ProjectChanged(opened.id) in _emitted()
        assert [call for call in fake.calls if "/sessions" in call[1]] == []

    def test_it_is_no_chat_and_stands_beside_the_projects_open_chat(
        self,
        session: DbSession,
        conversations: ConversationService,
        opened: Project,
        service_user: User,
    ) -> None:
        chat = open_chat(session, opened)

        turn = _open(conversations, opened, service_user)

        assert session.scalars(select(Chat.id)).all() == [chat.id]
        assert session.get_one(Chat, chat.id).closed_at is None
        assert turn.session_id != chat.id
        assert _turns(session) == 1

    def test_its_start_reaches_the_brain_in_the_store_boxed_to_the_projects_folder(
        self,
        session: DbSession,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        service_user: User,
    ) -> None:
        """DB 333: it runs in the store, handed `pilot-store`, whatever
        environment it was opened from."""
        turn = _open(conversations, opened, service_user)
        clear_after_commit_callbacks()

        run = _up(services, session, turn.session_id)

        assert (run.state_code, run.environment_id) == (
            SessionState.RUNNING,
            STORE_ENVIRONMENT_ID,
        )
        assert fake.sent == [turn.message]
        assert fake.sessions(CALLER) == []
        (created,) = fake.sessions(STORE_ENVIRONMENT_ID)
        body = created.create_body
        assert (
            body["cwd"],
            body["sandboxReadOnlyCwd"],
            body["sandboxWritableDirs"],
        ) == (STORE_REPO, True, [FOLDER])
        assert body["env"][:2] == [f"PILOT_PROJECT={FOLDER}", f"PILOT_SESSION={run.id}"]
        (registration,) = body["mcpConfig"]
        assert f'"url": "{MCP_URL}/store"' in registration
        assert _sends(session, run.id) == [(1, WORDS)]

    def test_its_turn_is_relayed_to_its_end_as_a_chats(
        self,
        session: DbSession,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        service_user: User,
    ) -> None:
        run = _idle(services, conversations, session, fake, opened, service_user)

        (turn,) = session.scalars(select(Turn).where(Turn.session_id == run.id))
        assert turn.ended_at is not None and turn.error is None
        kinds = [stored.record.kind_code for stored in _records(session, run.id)]
        assert kinds[0] is RecordKind.SEND
        assert kinds[-1] is RecordKind.RESULT
        assert [
            stored.record.payload["message"]["content"][0]["text"]
            for stored in _records(session, run.id)
            if stored.record.kind_code is RecordKind.CLAUDE
            and stored.record.payload.get("type") == "assistant"
        ] == ["Simmering."]
        assert session.get_one(Conversation, run.id).closed_at is None

    def test_a_call_that_named_no_session_opens_one_with_none(
        self,
        session: DbSession,
        conversations: ConversationService,
        opened: Project,
        service_user: User,
    ) -> None:
        turn = _open(conversations, opened, service_user, caller_session=None)

        (conversation,) = _rows(session, opened)
        assert conversation.caller_session is None
        assert turn.message.startswith(
            "/chat\n\nPilot's brief · a conversation with a session in RecipeBox-2"
            " (example-recipebox-1a2b3c) ·"
        )

    def test_while_the_controller_is_unreachable_its_start_is_held(
        self,
        session: DbSession,
        conversations: ConversationService,
        opened: Project,
        service_user: User,
        controller_outage: ControllerOutage,
    ) -> None:
        controller_outage.call_unanswered()

        turn = _open(conversations, opened, service_user)

        assert _read(session, turn.session_id).state_code == SessionState.HELD
        assert "_HeldWritten" in _callbacks()

    def test_a_finished_projects_reads_only_with_no_surface(
        self,
        session: DbSession,
        container: ServiceContainer,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
        service_user: User,
    ) -> None:
        """DB 334: as a finished project's chat (F5.5)."""
        _transition(container, opened, person, TransitionKind.FINISHED)

        turn = _open(conversations, opened, service_user, "What was settled?")

        assert turn.message.startswith(KIND)
        assert "\n\nThis project is finished (" in turn.message
        assert "Auto pilot:" not in turn.message
        clear_after_commit_callbacks()
        run = _up(services, session, turn.session_id)
        assert run.state_code == SessionState.RUNNING
        (created,) = fake.sessions(STORE_ENVIRONMENT_ID)
        body = created.create_body
        assert (body["cwd"], body["sandboxReadOnlyCwd"]) == (STORE_REPO, True)
        assert "sandboxWritableDirs" not in body
        assert "mcpConfig" not in body
        assert body["env"] == [f"PILOT_PROJECT={FOLDER}", f"PILOT_SESSION={run.id}"]


class TestItsTranscript:
    """The conversation in `chat.md`, beside the chats' (F150.12)."""

    def test_its_opening_puts_it_in_chat_md_and_tells_the_store(
        self,
        container: ServiceContainer,
        conversations: ConversationService,
        opened: Project,
        service_user: User,
    ) -> None:
        turn = _open(conversations, opened, service_user)

        chat = container.view_service().chat(opened)
        assert chat.text.split("\n\n")[1:] == [
            "## Conversation with a session in RecipeBox-2"
            " (example-recipebox-1a2b3c, session ui-sweep-triage)"
            f" · opened {utc_time(_read(conversations.db, turn.session_id).created_at)}",
            f"**fleet** · {utc_time(turn.started_at)}",
            WORDS,
            "Open\n",
        ]
        assert TreeHashMoved("soup-club/chat.md", chat.hash) in _emitted()

    def test_its_turns_stand_in_it_as_the_caller_and_pilot_said_them(
        self,
        session: DbSession,
        container: ServiceContainer,
        services: tuple[SessionStartService, RelayService],
        conversations: ConversationService,
        fake: _Sent,
        opened: Project,
        service_user: User,
    ) -> None:
        chat = open_chat(session, opened)
        run = _idle(services, conversations, session, fake, opened, service_user)
        conversations.send(run.id, service_user, "Two")
        before = container.view_service().chat(opened).text

        conversations.end(run.id, service_user)

        said = [
            paragraph
            for paragraph in before.split("\n\n")
            if not paragraph.startswith("**")
        ]
        assert said == [
            said[0],
            f"## Chat · opened {utc_time(chat.created_at)}",
            "Open",
            "## Conversation with a session in RecipeBox-2"
            " (example-recipebox-1a2b3c, session ui-sweep-triage)"
            f" · opened {utc_time(run.created_at)}",
            "One",
            "Simmering.",
            "Two",
            "Open\n",
        ]
        assert [
            paragraph.split(" · ")[0]
            for paragraph in before.split("\n\n")
            if paragraph.startswith("**")
        ] == ["**fleet**", "**agent**", "**fleet**"]
        closed = _row(session, run.id).closed_at
        assert closed is not None
        after = container.view_service().chat(opened)
        assert after.text.endswith(f"\n\nTwo\n\nClosed {utc_time(closed)}\n")
        assert TreeHashMoved("soup-club/chat.md", after.hash) in _emitted()


class TestTheCallersEnvironment:
    def test_its_row_is_written_at_the_opening_named_as_the_controller_reports_it(
        self,
        session: DbSession,
        conversations: ConversationService,
        opened: Project,
        service_user: User,
    ) -> None:
        assert session.get(Environment, CALLER) is None

        _open(conversations, opened, service_user)

        row = session.get_one(Environment, CALLER)
        assert (row.name, row.last_state, row.server_created_at, row.repo) == (
            CALLER_NAME,
            "running",
            None,
            None,
        )

    def test_an_environment_the_controller_does_not_know_opens_it_named_by_its_id(
        self,
        session: DbSession,
        conversations: ConversationService,
        opened: Project,
        service_user: User,
    ) -> None:
        """No call is refused for where it came from (F150.1)."""
        turn = _open(
            conversations, opened, service_user, environment="other-fleet-7c1d"
        )

        row = session.get_one(Environment, "other-fleet-7c1d")
        assert (row.name, row.last_state, row.server_created_at) == (
            "other-fleet-7c1d",
            None,
            None,
        )
        (conversation,) = _rows(session, opened)
        assert conversation.caller_environment_id == "other-fleet-7c1d"
        assert turn.message.startswith(
            "/chat\n\nPilot's brief · a conversation with a session in"
            " other-fleet-7c1d (other-fleet-7c1d, session ui-sweep-triage) ·"
        )
        assert _read(session, turn.session_id).state_code == SessionState.STARTING

    def test_a_controller_that_does_not_answer_opens_it_named_by_its_id(
        self,
        session: DbSession,
        conversations: ConversationService,
        fake: _Sent,
        opened: Project,
        service_user: User,
        controller_outage: ControllerOutage,
    ) -> None:
        """Its start waits at the gate for the controller, as any start
        does."""
        fake.outage()

        turn = _open(conversations, opened, service_user)

        assert session.get_one(Environment, CALLER).name == CALLER
        (conversation,) = _rows(session, opened)
        assert conversation.id == turn.session_id
        assert _read(session, turn.session_id).state_code == SessionState.HELD

    def test_a_later_conversation_from_it_finds_its_row_and_asks_nothing(
        self,
        session: DbSession,
        conversations: ConversationService,
        fake: _Sent,
        opened: Project,
        service_user: User,
    ) -> None:
        _open(conversations, opened, service_user)
        fake.environment(CALLER).name = "Renamed since"
        fake.calls.clear()

        second = _open(conversations, opened, service_user, caller_session="ga-prep")

        assert fake.calls == []
        assert session.get_one(Environment, CALLER).name == CALLER_NAME
        assert (
            "a session in RecipeBox-2 (example-recipebox-1a2b3c, session ga-prep)"
            in (second.message)
        )

    def test_the_store_itself_may_be_where_it_is_opened_from(
        self,
        session: DbSession,
        conversations: ConversationService,
        opened: Project,
        service_user: User,
    ) -> None:
        """DB 333: a brain session's own call."""
        turn = _open(
            conversations, opened, service_user, environment=STORE_ENVIRONMENT_ID
        )

        (conversation,) = _rows(session, opened)
        assert conversation.caller_environment_id == STORE_ENVIRONMENT_ID
        assert "a session in PilotProjects (" in turn.message


class TestSeveralAtOnce:
    def test_one_calling_session_and_several_open_conversations_on_one_project(
        self,
        session: DbSession,
        conversations: ConversationService,
        opened: Project,
        service_user: User,
    ) -> None:
        """DB 335, the ruling of 2026-11-08."""
        open_chat(session, opened)
        turns = [
            _open(conversations, opened, service_user, "One"),
            _open(conversations, opened, service_user, "Two"),
            _open(
                conversations, opened, service_user, "Three", caller_session="ga-prep"
            ),
            _open(
                conversations,
                opened,
                service_user,
                "Four",
                environment="other-fleet-7c1d",
                caller_session=None,
            ),
        ]

        rows = _rows(session, opened)
        assert {row.id for row in rows} == {turn.session_id for turn in turns}
        assert len(rows) == 4
        assert all(row.closed_at is None for row in rows)
        assert [_read(session, turn.session_id).state_code for turn in turns] == [
            SessionState.STARTING
        ] * 4
        assert [turn.seq for turn in turns] == [1, 1, 1, 1]

    def test_it_waits_behind_no_job_and_takes_no_work_items_slot(
        self,
        session: DbSession,
        container: ServiceContainer,
        supervise: Supervise,
        fake: _Sent,
        opened: Project,
        environment: Environment,
        service_user: User,
    ) -> None:
        """DB 335: beside the project's jobs, never in their queue, and for
        neither maximum at the gate."""
        for kind_code in ("job", "work"):
            session.add(
                models.Session(
                    project_id=opened.id,
                    environment_id=environment.id,
                    kind_code=kind_code,
                    cwd=STORE_REPO,
                    token_hash=uuid.uuid4().hex * 2,
                    state_code=SessionState.RUNNING,
                )
            )
        session.flush()
        conversations = _conversations(
            container, *_starts(container, supervise, work_max=1)
        )

        turn = _open(conversations, opened, service_user)

        assert _read(session, turn.session_id).state_code == SessionState.STARTING


class TestOpeningRefused:
    def test_a_draft_takes_none(
        self,
        session: DbSession,
        conversations: ConversationService,
        fake: _Sent,
        project: Project,
        service_user: User,
    ) -> None:
        """DB 334: its definition chat is the one session that writes its
        `project.md`."""
        with pytest.raises(
            InvalidOperationException,
            match="Cannot open a conversation with Pilot in .* because its project"
            " is a draft",
        ):
            _open(conversations, project, service_user)

        assert _rows(session, project) == []
        assert session.get(Environment, CALLER) is None
        assert fake.calls == []

    def test_an_archived_project_takes_none(
        self,
        session: DbSession,
        conversations: ConversationService,
        opened: Project,
        service_user: User,
    ) -> None:
        opened.archived = True
        session.flush()

        with pytest.raises(
            InvalidOperationException,
            match="Cannot open a conversation with Pilot in Soup club because its"
            " project is archived",
        ):
            _open(conversations, opened, service_user)

        assert _rows(session, opened) == []

    def test_no_project_has_the_id(
        self, conversations: ConversationService, service_user: User
    ) -> None:
        with pytest.raises(RecordNotFoundException):
            conversations.open(uuid.uuid4(), service_user, CALLER, None, WORDS)

    def test_without_a_controller_configured_none_starts(
        self,
        container: ServiceContainer,
        supervise: Supervise,
        fake: _Sent,
        opened: Project,
        service_user: User,
    ) -> None:
        conversations = _conversations(
            container, *_starts(container, supervise, controller_configured=False)
        )

        with pytest.raises(
            InvalidOperationException, match="no controller is configured"
        ):
            _open(conversations, opened, service_user)


class TestSend:
    def test_a_message_to_its_idle_conversation_is_a_turn_of_it_its_words_alone(
        self,
        session: DbSession,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        service_user: User,
    ) -> None:
        run = _idle(services, conversations, session, fake, opened, service_user)

        turn = conversations.send(run.id, service_user, "Two")

        assert (turn.session_id, turn.seq, turn.message, turn.words) == (
            run.id,
            2,
            "Two",
            "Two",
        )
        assert (turn.author_user_id, turn.error) == (service_user.id, None)
        assert fake.sent == ["Two"]
        assert _read(session, run.id).state_code == SessionState.RUNNING
        assert _sends(session, run.id) == [(1, "One"), (2, "Two")]
        assert len(_rows(session, opened)) == 1

    def test_a_message_while_a_turn_of_it_runs_is_refused_and_nothing_queued(
        self,
        session: DbSession,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        service_user: User,
    ) -> None:
        """DB 336: read from the record, with no call to the controller."""
        first = _open(conversations, opened, service_user, "One")
        clear_after_commit_callbacks()
        _up(services, session, first.session_id)
        fake.calls.clear()

        with pytest.raises(
            InvalidOperationException,
            match="Cannot send a message to Pilot in Soup club because a turn of"
            " its conversation is in flight",
        ):
            conversations.send(first.session_id, service_user, "Two")

        assert fake.calls == []
        assert fake.sent == [first.message]
        assert _sends(session, first.session_id) == [(1, "One")]
        assert _turns(session) == 1

    @pytest.mark.parametrize("state", [SessionState.HELD, SessionState.STARTING])
    def test_a_message_while_its_start_is_held_or_under_way_is_refused(
        self,
        session: DbSession,
        conversations: ConversationService,
        opened: Project,
        service_user: User,
        state: SessionState,
    ) -> None:
        first = _open(conversations, opened, service_user)
        _read(session, first.session_id).state_code = state
        session.flush()

        with pytest.raises(
            InvalidOperationException, match="a turn of its conversation is in flight"
        ):
            conversations.send(first.session_id, service_user, "Again")

        assert _turns(session) == 1

    def test_a_stopped_turn_still_ending_is_refused(
        self,
        session: DbSession,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
        service_user: User,
    ) -> None:
        """A turn stopped and still relayed to its end is in flight."""
        first = _open(conversations, opened, service_user, "One")
        clear_after_commit_callbacks()
        _up(services, session, first.session_id)
        services[0].stop_chat(session, first.session_id, person, "stop Pilot")
        clear_after_commit_callbacks()
        run = _read(session, first.session_id)
        assert (run.state_code, run.turn_ended_at) == (SessionState.STOPPED, None)

        with pytest.raises(
            InvalidOperationException, match="a turn of its conversation is in flight"
        ):
            conversations.send(first.session_id, service_user, "Two")

        assert _turns(session) == 1

    def test_an_interrupted_conversation_is_kept_for_the_next_message(
        self,
        session: DbSession,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        service_user: User,
    ) -> None:
        run = _idle(services, conversations, session, fake, opened, service_user)
        run.state_code = SessionState.STOPPED
        session.flush()

        turn = conversations.send(run.id, service_user, "Two")

        assert (turn.session_id, turn.seq, turn.message) == (run.id, 2, "Two")
        assert fake.sent == ["Two"]

    def test_one_whose_start_failed_starts_afresh_briefed_in_the_same_conversation(
        self,
        session: DbSession,
        container: ServiceContainer,
        conversations: ConversationService,
        opened: Project,
        service_user: User,
    ) -> None:
        first = _open(conversations, opened, service_user, "One")
        clear_after_commit_callbacks()
        container.environment_service().ensure_environment(
            session, STORE_ENVIRONMENT_ID
        )
        run = _read(session, first.session_id)
        run.environment_id = STORE_ENVIRONMENT_ID
        run.controller_session, run.token_hash = "claude-1", "a" * 64
        run.state_code, run.error = SessionState.FAILED, "the create was refused"
        first.ended_at = run.turn_ended_at = datetime.now(UTC)
        session.flush()

        second = conversations.send(first.session_id, service_user, "Two")

        assert second.session_id == first.session_id
        run = _read(session, first.session_id)
        assert (run.state_code, run.error, run.controller_session) == (
            SessionState.STARTING,
            None,
            None,
        )
        assert (second.seq, second.words, second.author_user_id) == (
            2,
            "Two",
            service_user.id,
        )
        assert second.message == container.brief_service().conversation(
            opened,
            session.get_one(Environment, CALLER),
            CALLER_SESSION,
            "Two",
            second.started_at,
        )
        assert run.turns == 2
        assert _sends(session, run.id) == [(1, "One"), (2, "Two")]
        assert "_LoopStart" in _callbacks()
        assert len(_rows(session, opened)) == 1

    def test_one_stopped_before_its_brief_went_out_starts_afresh_and_reaches_the_brain(
        self,
        session: DbSession,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
        service_user: User,
    ) -> None:
        first = _open(conversations, opened, service_user, "One")
        clear_after_commit_callbacks()
        services[0].stop_chat(session, first.session_id, person, "stop Pilot")
        clear_after_commit_callbacks()
        assert _read(session, first.session_id).state_code == SessionState.STOPPED

        second = conversations.send(first.session_id, service_user, "Two")

        assert (second.session_id, second.seq, second.error) == (
            first.session_id,
            2,
            None,
        )
        assert second.message.startswith(KIND)
        clear_after_commit_callbacks()
        run = _up(services, session, first.session_id)
        assert (run.state_code, run.environment_id) == (
            SessionState.RUNNING,
            STORE_ENVIRONMENT_ID,
        )
        assert fake.sent == [second.message]
        assert _sends(session, run.id) == [(1, "One"), (2, "Two")]

    def test_each_conversation_takes_its_own_turns(
        self,
        session: DbSession,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        service_user: User,
    ) -> None:
        """A turn in flight in one refuses no message to another."""
        idle = _idle(services, conversations, session, fake, opened, service_user)
        busy = _open(conversations, opened, service_user, "Another")
        clear_after_commit_callbacks()
        _up(services, session, busy.session_id)

        turn = conversations.send(idle.id, service_user, "Two")

        assert (turn.session_id, turn.seq, turn.error) == (idle.id, 2, None)
        assert _sends(session, busy.session_id) == [(1, "Another")]


class TestSendRefused:
    def test_a_closed_conversation_takes_no_turn(
        self,
        session: DbSession,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        service_user: User,
    ) -> None:
        """DB 334."""
        run = _idle(services, conversations, session, fake, opened, service_user)
        conversation = session.get_one(Conversation, run.id)
        conversation.closed_at = datetime.now(UTC)
        conversation.close_cause_code = CloseCause.ENDED
        session.flush()

        with pytest.raises(
            InvalidOperationException,
            match="Cannot send a message to Pilot in Soup club because its"
            " conversation is closed",
        ):
            conversations.send(run.id, service_user, "Two")

        assert fake.sent == []
        assert _turns(session) == 1

    def test_a_closed_conversation_whose_start_failed_starts_no_more(
        self,
        session: DbSession,
        conversations: ConversationService,
        opened: Project,
        service_user: User,
    ) -> None:
        first = _open(conversations, opened, service_user, "One")
        run = _read(session, first.session_id)
        run.state_code = SessionState.FAILED
        first.ended_at = run.turn_ended_at = datetime.now(UTC)
        conversation = session.get_one(Conversation, run.id)
        conversation.closed_at = datetime.now(UTC)
        conversation.close_cause_code = CloseCause.TIMEOUT
        session.flush()

        with pytest.raises(
            InvalidOperationException, match="its conversation is closed"
        ):
            conversations.send(run.id, service_user, "Two")

        assert _turns(session) == 1

    def test_an_archived_projects_conversation_takes_no_turn(
        self,
        session: DbSession,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        service_user: User,
    ) -> None:
        run = _idle(services, conversations, session, fake, opened, service_user)
        opened.archived = True
        session.flush()

        with pytest.raises(InvalidOperationException, match="its project is archived"):
            conversations.send(run.id, service_user, "Two")

        assert fake.sent == []

    def test_no_conversation_has_the_id(
        self,
        session: DbSession,
        conversations: ConversationService,
        opened: Project,
        service_user: User,
    ) -> None:
        """A chat's id among them: a Chat is no Conversation."""
        chat = open_chat(session, opened)

        for unknown in (uuid.uuid4(), chat.id):
            with pytest.raises(RecordNotFoundException):
                conversations.send(unknown, service_user, "Two")


class TestHandbookNotice:
    """A conversation's turn takes the notice as a chat's does (design 3
    §5.3, §6.3; D052)."""

    def test_a_turn_after_the_handbook_changed_opens_with_the_notice_counted(
        self,
        session: DbSession,
        container: ServiceContainer,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        service_user: User,
    ) -> None:
        run = _idle(services, conversations, session, fake, opened, service_user)
        container.document_service().bear_handbook(opened, "# Handbook\n")
        counted = metric_value(HANDBOOK_CHANGED_TOTAL, project=str(opened.id))

        turn = conversations.send(run.id, service_user, "Two")

        assert (turn.message, turn.words) == (f"{STORE_NOTIFICATION}\n\nTwo", "Two")
        assert fake.sent == [turn.message]
        assert metric_value(HANDBOOK_CHANGED_TOTAL, project=str(opened.id)) == (
            counted + 1
        )

    def test_the_notice_comes_once_per_change(
        self,
        session: DbSession,
        container: ServiceContainer,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        service_user: User,
    ) -> None:
        run = _idle(services, conversations, session, fake, opened, service_user)
        container.document_service().bear_handbook(opened, "# Handbook\n")
        conversations.send(run.id, service_user, "Two")
        clear_after_commit_callbacks()
        run = _read(session, run.id)
        assert run.controller_session is not None
        fake.finish(STORE_ENVIRONMENT_ID, run.controller_session, "success", "Done.")
        services[1].relay(run.id, LoopHandle(f"relay:{run.id}"))
        clear_after_commit_callbacks()

        turn = conversations.send(run.id, service_user, "Three")

        assert turn.message == "Three"

    def test_a_handbook_unchanged_since_its_last_turn_brings_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        service_user: User,
    ) -> None:
        container.document_service().bear_handbook(opened, "# Handbook\n")
        run = _idle(services, conversations, session, fake, opened, service_user)

        turn = conversations.send(run.id, service_user, "Two")

        assert turn.message == "Two"


class TestInAPausedProject:
    def test_its_brief_says_the_project_is_paused(
        self,
        session: DbSession,
        conversations: ConversationService,
        opened: Project,
        person: User,
        service_user: User,
    ) -> None:
        opened.paused = True
        session.add(
            ProjectTransition(
                project_id=opened.id,
                kind_code=TransitionKind.PAUSED,
                at=datetime.now(UTC),
                by_user_id=person.id,
            )
        )
        session.flush()

        turn = _open(conversations, opened, service_user)

        assert "\nThe project is paused since " in turn.message

    def test_its_start_and_its_next_message_go_on_under_the_pause(
        self,
        session: DbSession,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
        service_user: User,
    ) -> None:
        """DB 335: never held by the pause."""
        opened.paused = True
        session.add(
            ProjectTransition(
                project_id=opened.id,
                kind_code=TransitionKind.PAUSED,
                at=datetime.now(UTC),
                by_user_id=person.id,
            )
        )
        session.flush()

        run = _idle(services, conversations, session, fake, opened, service_user)
        other = _open(conversations, opened, service_user, "Another")

        assert _read(session, other.session_id).state_code == SessionState.STARTING
        assert "_LoopStart" in _callbacks()
        turn = conversations.send(run.id, service_user, "Two")
        assert turn.error is None
        assert fake.sent == ["Two"]


class TestUnderTheStoresUpdate:
    """While a Store Update is unlifted no message is taken, the opening's
    included, and a start that passed that read is held at the gate, as a
    chat's (F144.2; DB 282, 335)."""

    def test_no_conversation_opens(
        self,
        session: DbSession,
        conversations: ConversationService,
        opened: Project,
        service_user: User,
    ) -> None:
        hold(session)

        with pytest.raises(
            InvalidOperationException,
            match="Cannot open a conversation with Pilot in Soup club because Pilot"
            " is updating",
        ):
            _open(conversations, opened, service_user)

        assert _rows(session, opened) == []
        assert _turns(session) == 0
        assert session.get(Environment, CALLER) is None

    def test_no_message_is_taken(
        self,
        session: DbSession,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        service_user: User,
    ) -> None:
        run = _idle(services, conversations, session, fake, opened, service_user)
        update = hold(session)

        with pytest.raises(
            InvalidOperationException,
            match="Cannot send a message to Pilot in Soup club because Pilot is"
            " updating",
        ):
            conversations.send(run.id, service_user, "Two")

        assert fake.sent == []
        assert _turns(session) == 1
        lift(session, update)
        assert conversations.send(run.id, service_user, "Two").seq == 2

    def test_one_stopped_before_its_brief_went_out_starts_no_more_until_the_lift(
        self,
        session: DbSession,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        opened: Project,
        service_user: User,
    ) -> None:
        first = _open(conversations, opened, service_user, "One")
        clear_after_commit_callbacks()
        update = hold(session)
        services[0].stop_for_update(session, first.session_id)
        clear_after_commit_callbacks()
        assert _read(session, first.session_id).state_code == SessionState.STOPPED

        with pytest.raises(InvalidOperationException, match="Pilot is updating"):
            conversations.send(first.session_id, service_user, "Two")

        assert _turns(session) == 1
        assert _row(session, first.session_id).closed_at is None
        lift(session, update)
        again = conversations.send(first.session_id, service_user, "Two")
        assert (again.session_id, again.seq) == (first.session_id, 2)
        assert again.message.startswith(KIND)

    def test_a_start_the_update_caught_is_held_and_goes_on_at_the_lift(
        self,
        session: DbSession,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        opened: Project,
        service_user: User,
    ) -> None:
        """An opening whose read of the update came before its commit meets
        it at the gate."""
        first = _open(conversations, opened, service_user, "One")
        clear_after_commit_callbacks()
        run = _read(session, first.session_id)
        update = hold(session)

        services[0].start_brain(session, opened, run, "open a conversation")

        assert run.state_code == SessionState.HELD
        assert services[0].held(session, opened, run) == Held(HeldReason.STORE_UPDATE)
        clear_after_commit_callbacks()
        lift(session, update)
        services[0].release(LoopHandle("start:held"))
        assert _read(session, run.id).state_code == SessionState.STARTING


class TestInterrupt:
    """Its caller's interrupt: the turn in flight stopped, the conversation
    kept for the next message (F150.10)."""

    def test_a_running_turn_is_stopped_by_the_caller_interrupted_once_it_commits(
        self,
        session: DbSession,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        service_user: User,
    ) -> None:
        run = _idle(services, conversations, session, fake, opened, service_user)
        conversations.send(run.id, service_user, "Two")
        clear_after_commit_callbacks()
        before = datetime.now(UTC)

        conversation = conversations.interrupt(run.id, service_user)

        assert (conversation.id, conversation.closed_at) == (run.id, None)
        run = _read(session, run.id)
        assert (run.state_code, run.stopped_by_user_id, run.current_line) == (
            SessionState.STOPPED,
            service_user.id,
            None,
        )
        assert run.stopped_at is not None and run.stopped_at >= before
        # The turn stays in flight for its relay; the interrupt follows the commit.
        assert run.turn_ended_at is None
        assert "_InterruptStart" in _callbacks()
        assert ProjectChanged(opened.id) in _emitted()

    def test_after_its_interrupted_turn_the_next_message_goes_to_its_thread(
        self,
        session: DbSession,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        service_user: User,
    ) -> None:
        run = _idle(services, conversations, session, fake, opened, service_user)
        conversations.send(run.id, service_user, "Two")
        conversations.interrupt(run.id, service_user)
        clear_after_commit_callbacks()

        with pytest.raises(
            InvalidOperationException, match="a turn of its conversation is in flight"
        ):
            conversations.send(run.id, service_user, "Too soon")

        run = _stopped_turn_ends(services, session, fake, run.id)
        assert (run.state_code, run.turn_ended_at is not None) == (
            SessionState.STOPPED,
            True,
        )
        fake.sent.clear()

        turn = conversations.send(run.id, service_user, "Three")

        assert (turn.session_id, turn.seq, turn.message) == (run.id, 3, "Three")
        assert fake.sent == ["Three"]
        assert _read(session, run.id).state_code == SessionState.RUNNING

    @pytest.mark.parametrize("state", [SessionState.HELD, SessionState.STARTING])
    def test_a_start_held_or_under_way_ends_its_turn_unsent_and_the_next_message_briefs_it(
        self,
        session: DbSession,
        conversations: ConversationService,
        opened: Project,
        service_user: User,
        state: SessionState,
    ) -> None:
        first = _open(conversations, opened, service_user, "One")
        _read(session, first.session_id).state_code = state
        session.flush()
        clear_after_commit_callbacks()

        conversations.interrupt(first.session_id, service_user)

        run = _read(session, first.session_id)
        assert run.state_code == SessionState.STOPPED
        turn = session.get_one(Turn, first.id, populate_existing=True)
        assert turn.ended_at == run.stopped_at == run.turn_ended_at
        assert "_InterruptStart" not in _callbacks()
        clear_after_commit_callbacks()

        again = conversations.send(first.session_id, service_user, "Two")

        assert (again.session_id, again.seq, again.words) == (run.id, 2, "Two")
        assert again.message.startswith(KIND)
        assert _read(session, run.id).state_code == SessionState.STARTING

    def test_with_no_turn_in_flight_it_changes_nothing(
        self,
        session: DbSession,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        service_user: User,
    ) -> None:
        """As KubeCoder's interrupt of an idle session; a closed
        conversation's included."""
        run = _idle(services, conversations, session, fake, opened, service_user)
        fake.calls.clear()

        conversations.interrupt(run.id, service_user)

        run = _read(session, run.id)
        assert (run.state_code, run.stopped_at) == (SessionState.IDLE, None)
        conversations.end(run.id, service_user)
        clear_after_commit_callbacks()
        records = len(_records(session, run.id))

        conversation = conversations.interrupt(run.id, service_user)

        assert conversation.close_cause_code is CloseCause.ENDED
        assert _read(session, run.id).state_code == SessionState.IDLE
        assert len(_records(session, run.id)) == records
        assert _callbacks() == set()
        assert fake.calls == []

    def test_no_conversation_has_the_id(
        self,
        session: DbSession,
        conversations: ConversationService,
        opened: Project,
        service_user: User,
    ) -> None:
        chat = open_chat(session, opened)

        for unknown in (uuid.uuid4(), chat.id):
            with pytest.raises(RecordNotFoundException):
                conversations.interrupt(unknown, service_user)
            with pytest.raises(RecordNotFoundException):
                conversations.end(unknown, service_user)
        assert session.get_one(Chat, chat.id).closed_at is None


class TestEnd:
    """Its caller's end: closed `ended`, a turn in flight stopped first (DB
    334)."""

    def test_an_idle_conversation_closes_ended_its_record_last_and_no_controller_called(
        self,
        session: DbSession,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        service_user: User,
    ) -> None:
        run = _idle(services, conversations, session, fake, opened, service_user)
        fake.calls.clear()
        before = datetime.now(UTC)

        conversation = conversations.end(run.id, service_user)

        assert conversation.id == run.id
        assert conversation.close_cause_code is CloseCause.ENDED
        assert conversation.closed_at is not None and conversation.closed_at >= before
        assert _last(session, run.id) == {"type": "closed", "cause": "ended"}
        assert ProjectChanged(opened.id) in _emitted()
        run = _read(session, run.id)
        assert (run.state_code, run.stopped_at) == (SessionState.IDLE, None)
        assert run.controller_session is not None
        assert fake.calls == []

    def test_a_turn_in_flight_is_stopped_first_the_close_written_after_its_end(
        self,
        session: DbSession,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        service_user: User,
    ) -> None:
        run = _idle(services, conversations, session, fake, opened, service_user)
        conversations.send(run.id, service_user, "Two")
        clear_after_commit_callbacks()

        conversations.end(run.id, service_user)

        assert _row(session, run.id).close_cause_code is CloseCause.ENDED
        run = _read(session, run.id)
        assert (run.state_code, run.stopped_by_user_id, run.turn_ended_at) == (
            SessionState.STOPPED,
            service_user.id,
            None,
        )
        assert "_InterruptStart" in _callbacks()
        assert _last(session, run.id) != {"type": "closed", "cause": "ended"}
        clear_after_commit_callbacks()

        _stopped_turn_ends(services, session, fake, run.id)

        assert _last(session, run.id) == {"type": "closed", "cause": "ended"}

    def test_a_start_under_way_ends_its_turn_unsent_then_closes(
        self,
        session: DbSession,
        conversations: ConversationService,
        opened: Project,
        service_user: User,
    ) -> None:
        first = _open(conversations, opened, service_user, "One")
        clear_after_commit_callbacks()

        conversations.end(first.session_id, service_user)

        run = _read(session, first.session_id)
        assert run.state_code == SessionState.STOPPED
        assert run.turn_ended_at is not None
        payloads = [
            stored.record.payload
            for stored in _records(session, run.id)
            if stored.record.kind_code == RecordKind.SERVER
        ]
        assert payloads[-2:] == [
            {"type": "stopped-unsent"},
            {"type": "closed", "cause": "ended"},
        ]

    def test_an_ended_conversation_takes_no_turn(
        self,
        session: DbSession,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        service_user: User,
    ) -> None:
        run = _idle(services, conversations, session, fake, opened, service_user)
        conversations.end(run.id, service_user)
        clear_after_commit_callbacks()

        with pytest.raises(
            InvalidOperationException, match="its conversation is closed"
        ):
            conversations.send(run.id, service_user, "Two")

        assert fake.sent == []
        assert _turns(session) == 1

    def test_one_closed_already_stays_as_it_closed(
        self,
        session: DbSession,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        service_user: User,
    ) -> None:
        run = _idle(services, conversations, session, fake, opened, service_user)
        closed_at = datetime(2026, 10, 26, 9, 30, tzinfo=UTC)
        conversation = _row(session, run.id)
        conversation.closed_at = closed_at
        conversation.close_cause_code = CloseCause.TIMEOUT
        session.flush()
        records = len(_records(session, run.id))

        ended = conversations.end(run.id, service_user)

        assert (ended.closed_at, ended.close_cause_code) == (
            closed_at,
            CloseCause.TIMEOUT,
        )
        assert len(_records(session, run.id)) == records
        assert _emitted() == []

    def test_the_other_conversations_and_the_chat_stay_open(
        self,
        session: DbSession,
        conversations: ConversationService,
        opened: Project,
        service_user: User,
    ) -> None:
        chat = open_chat(session, opened)
        first = _open(conversations, opened, service_user, "One")
        second = _open(conversations, opened, service_user, "Another")
        clear_after_commit_callbacks()

        conversations.end(first.session_id, service_user)

        assert _row(session, second.session_id).closed_at is None
        assert _read(session, second.session_id).state_code == SessionState.STARTING
        assert session.get_one(Chat, chat.id).closed_at is None


class TestTransitions:
    """Finish, Reopen and Archive close every open conversation of the
    project, its sessions stopped first (DB 334)."""

    @pytest.mark.parametrize(
        ("kind", "cause"),
        [
            (TransitionKind.FINISHED, CloseCause.FINISHED),
            (TransitionKind.REOPENED, CloseCause.REOPENED),
            (TransitionKind.ARCHIVED, CloseCause.ARCHIVED),
        ],
    )
    def test_each_closes_every_open_conversation_a_running_one_stopped_first(
        self,
        session: DbSession,
        container: ServiceContainer,
        conversations: ConversationService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
        service_user: User,
        kind: TransitionKind,
        cause: CloseCause,
    ) -> None:
        if kind is TransitionKind.REOPENED:
            _transition(container, opened, person, TransitionKind.FINISHED)
        ended = _open(conversations, opened, service_user, "Earlier")
        clear_after_commit_callbacks()
        conversations.end(ended.session_id, service_user)
        idle = _idle(services, conversations, session, fake, opened, service_user)
        running = _idle(services, conversations, session, fake, opened, service_user)
        conversations.send(running.id, service_user, "Two")
        clear_after_commit_callbacks()

        container.project_service().transition_as(person, opened.id, kind)

        closed = {row.id: row for row in _rows(session, opened)}
        assert closed[ended.session_id].close_cause_code is CloseCause.ENDED
        assert closed[idle.id].close_cause_code is cause
        assert closed[running.id].close_cause_code is cause
        assert closed[idle.id].closed_at == closed[running.id].closed_at
        assert _read(session, idle.id).state_code == SessionState.IDLE
        assert _last(session, idle.id) == {"type": "closed", "cause": cause.value}
        stopped = _read(session, running.id)
        assert (stopped.state_code, stopped.stopped_by_user_id) == (
            SessionState.STOPPED,
            person.id,
        )
        assert stopped.stopped_at == closed[running.id].closed_at
        # Its close's record waits for its stopped turn's end.
        assert _last(session, running.id) != {"type": "closed", "cause": cause.value}
        assert "_InterruptStart" in _callbacks()
        clear_after_commit_callbacks()
        _stopped_turn_ends(services, session, fake, running.id)
        assert _last(session, running.id) == {"type": "closed", "cause": cause.value}

    def test_another_projects_conversation_stays_open(
        self,
        session: DbSession,
        container: ServiceContainer,
        conversations: ConversationService,
        opened: Project,
        person: User,
        service_user: User,
    ) -> None:
        other = Project(
            created_by_user_id=person.id,
            state_code=ProjectState.OPEN,
            slug="camp",
            name="Camp",
        )
        session.add(other)
        session.flush()
        mine = _open(conversations, opened, service_user, "One")
        theirs = _open(conversations, other, service_user, "Another")
        clear_after_commit_callbacks()

        _transition(container, opened, person, TransitionKind.FINISHED)

        assert _row(session, mine.session_id).close_cause_code is CloseCause.FINISHED
        assert _row(session, theirs.session_id).closed_at is None
        assert _read(session, theirs.session_id).state_code == SessionState.STARTING

    def test_after_finish_a_conversation_opens_and_after_archive_none_is_left_open(
        self,
        session: DbSession,
        container: ServiceContainer,
        conversations: ConversationService,
        opened: Project,
        person: User,
        service_user: User,
    ) -> None:
        container.project_service().finish_and_archive(person, person, opened.id)
        clear_after_commit_callbacks()

        with pytest.raises(InvalidOperationException, match="its project is archived"):
            _open(conversations, opened, service_user)

        assert _rows(session, opened) == []


def _committed_idle(
    container: ServiceContainer,
    fake: _Sent,
    state: ProjectState = ProjectState.OPEN,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """A person, a service user and the idle conversation of a project in
    `state` on a headless session in the store, committed; the service
    user's id, the conversation's, the person's and the project's."""
    name = (
        client_of(container, fake)
        .create_headless_session(
            STORE_ENVIRONMENT_ID, HeadlessCreateRequest(resume=THREAD)
        )
        .name
    )
    with scoped_session(container) as db:
        person = User(
            kind_code=UserKind.PERSON,
            subject="subject-ada",
            handle="ada",
            name="Ada Example",
            avatar_slot=1,
        )
        caller = User(
            kind_code=UserKind.SERVICE,
            subject="subject-fleet",
            handle="fleet",
            name="KubeCoder fleet",
        )
        db.add_all([person, caller])
        db.flush()
        project = Project(
            created_by_user_id=person.id,
            state_code=state,
            slug="soup-club",
            name="Soup club",
        )
        db.add_all(
            [
                project,
                Environment(id=STORE_ENVIRONMENT_ID, name="PilotProjects", exempt=True),
                Environment(id=CALLER, name=CALLER_NAME, exempt=False),
            ]
        )
        db.flush()
        now = datetime.now(UTC)
        run = models.Session(
            project_id=project.id,
            environment_id=STORE_ENVIRONMENT_ID,
            kind_code="conversation",
            cwd=STORE_REPO,
            conversation_id=THREAD,
            controller_session=name,
            token_hash="a" * 64,
            state_code=SessionState.IDLE,
            turns=1,
            turn_started_at=now,
            turn_ended_at=now,
        )
        db.add(run)
        db.flush()
        db.add(
            Conversation(
                id=run.id,
                project_id=project.id,
                session_kind_code="conversation",
                caller_environment_id=CALLER,
                caller_session=CALLER_SESSION,
            )
        )
        db.add(
            Turn(
                session_id=run.id,
                seq=1,
                author_user_id=caller.id,
                message="/chat",
                words="One",
                started_at=now,
                ended_at=now,
            )
        )
        return caller.id, run.id, person.id, project.id


class TestTwoMessages:
    def test_of_two_messages_at_once_one_is_its_turn_and_the_other_is_refused(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        """DB 336: the second waits on the conversation's Session, which the
        first holds to its commit, then finds its Turn in flight."""
        container = committed_app.container
        fake = _Sent(keepalive_seconds=0.2)
        try:
            fake.add_environment(
                STORE_ENVIRONMENT_ID, name="PilotProjects", status="running"
            )
            caller_id, conversation_id, _, _ = _committed_idle(container, fake)
            services = _starts(container, supervise)
            written, proceed = threading.Event(), threading.Event()

            def send(words: str) -> int:
                with scoped_session(container) as db:
                    turn = _conversations(container, *services).send(
                        conversation_id, db.get_one(User, caller_id), words
                    )
                    if words == "Two":
                        written.set()
                        assert proceed.wait(WAIT_SECONDS)
                    return turn.seq

            first = in_thread(lambda: send("Two"))
            assert written.wait(WAIT_SECONDS)
            second = in_thread(lambda: send("Three"))
            wait_until(lambda: lock_waits(container) == 1, "the second send waiting")
            proceed.set()

            assert first.result() == 2
            with pytest.raises(
                InvalidOperationException,
                match="a turn of its conversation is in flight",
            ):
                second.result()
            assert fake.sent == ["Two"]
            with scoped_session(container) as db:
                assert db.scalars(select(Turn.words).order_by(Turn.seq)).all() == [
                    "One",
                    "Two",
                ]
        finally:
            fake.close()


class _SendHeld(_Sent):
    """The fake, holding each send until `release` is set."""

    def __init__(self, keepalive_seconds: float) -> None:
        super().__init__(keepalive_seconds)
        self.sending, self.release = threading.Event(), threading.Event()

    def _send(self, request: Request, env_id: str, name: str) -> Response:
        self.sending.set()
        assert self.release.wait(WAIT_SECONDS)
        return super()._send(request, env_id, name)


class TestATransitionMeetingAMessage:
    """A message to an idle conversation and a transition that stops the
    project's sessions never leave a turn running in a closed conversation:
    the transition's stop locks every open conversation's Session, whatever
    its state, before it reads which to stop."""

    @pytest.mark.parametrize(
        ("kind", "state", "cause"),
        [
            (TransitionKind.FINISHED, ProjectState.OPEN, CloseCause.FINISHED),
            (TransitionKind.REOPENED, ProjectState.FINISHED, CloseCause.REOPENED),
            (TransitionKind.ARCHIVED, ProjectState.OPEN, CloseCause.ARCHIVED),
        ],
    )
    def test_it_stops_the_turn_a_send_in_flight_started(
        self,
        committed_app: Flask,
        supervise: Supervise,
        kind: TransitionKind,
        state: ProjectState,
        cause: CloseCause,
    ) -> None:
        """The transition's stop waits on the conversation's Session, which
        the send holds across the controller's call, and stops the turn it
        started."""
        container = committed_app.container
        fake = _SendHeld(keepalive_seconds=0.2)
        try:
            fake.add_environment(
                STORE_ENVIRONMENT_ID, name="PilotProjects", status="running"
            )
            caller_id, conversation_id, person_id, project_id = _committed_idle(
                container, fake, state
            )
            services = _starts(container, supervise)

            def send() -> int:
                with scoped_session(container) as db:
                    return (
                        _conversations(container, *services)
                        .send(conversation_id, db.get_one(User, caller_id), "Two")
                        .seq
                    )

            def transition() -> None:
                with scoped_session(container) as db:
                    container.project_service().transition_as(
                        db.get_one(User, person_id), project_id, kind
                    )

            sending = in_thread(send)
            assert fake.sending.wait(WAIT_SECONDS)
            transitioning = in_thread(transition)
            wait_until(lambda: lock_waits(container) == 1, "the transition waiting")
            fake.release.set()

            assert sending.result() == 2
            transitioning.result()
            assert fake.sent == ["Two"]
            with scoped_session(container) as db:
                run = _read(db, conversation_id)
                assert run.state_code == SessionState.STOPPED
                assert run.stopped_by_user_id == person_id
                assert _row(db, conversation_id).close_cause_code is cause
        finally:
            fake.close()

    def test_a_message_meeting_finish_is_refused(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        """The send waits on the conversation's Session, which Finish's stop
        holds; once Finish commits it finds the conversation closed and
        sends nothing."""
        container = committed_app.container
        fake = _Sent(keepalive_seconds=0.2)
        try:
            fake.add_environment(
                STORE_ENVIRONMENT_ID, name="PilotProjects", status="running"
            )
            caller_id, conversation_id, person_id, project_id = _committed_idle(
                container, fake
            )
            services = _starts(container, supervise)
            finished, finish_ends = threading.Event(), threading.Event()

            def finish() -> None:
                with scoped_session(container) as db:
                    container.project_service().transition_as(
                        db.get_one(User, person_id),
                        project_id,
                        TransitionKind.FINISHED,
                    )
                    finished.set()
                    assert finish_ends.wait(WAIT_SECONDS)

            def send() -> None:
                with scoped_session(container) as db:
                    _conversations(container, *services).send(
                        conversation_id, db.get_one(User, caller_id), "Two"
                    )

            finishing = in_thread(finish)
            assert finished.wait(WAIT_SECONDS)
            sending = in_thread(send)
            wait_until(lambda: lock_waits(container) == 1, "the send waiting")
            finish_ends.set()
            finishing.result()

            with pytest.raises(
                InvalidOperationException, match="its conversation is closed"
            ):
                sending.result()
            assert fake.sent == []
            with scoped_session(container) as db:
                assert _read(db, conversation_id).state_code == SessionState.IDLE
                assert _row(db, conversation_id).close_cause_code is (
                    CloseCause.FINISHED
                )
                assert db.scalars(select(Turn.words)).all() == ["One"]
        finally:
            fake.close()

    def test_an_end_meeting_a_message_waits_for_its_send_and_stops_its_turn(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        """The caller's end waits on the conversation's Session, which the
        send holds across the controller's call, and stops the turn it
        started before it closes."""
        container = committed_app.container
        fake = _SendHeld(keepalive_seconds=0.2)
        try:
            fake.add_environment(
                STORE_ENVIRONMENT_ID, name="PilotProjects", status="running"
            )
            caller_id, conversation_id, _, _ = _committed_idle(container, fake)
            services = _starts(container, supervise)

            def send() -> int:
                with scoped_session(container) as db:
                    return (
                        _conversations(container, *services)
                        .send(conversation_id, db.get_one(User, caller_id), "Two")
                        .seq
                    )

            def end() -> None:
                with scoped_session(container) as db:
                    _conversations(container, *services).end(
                        conversation_id, db.get_one(User, caller_id)
                    )

            sending = in_thread(send)
            assert fake.sending.wait(WAIT_SECONDS)
            ending = in_thread(end)
            wait_until(lambda: lock_waits(container) == 1, "the end waiting")
            fake.release.set()

            assert sending.result() == 2
            ending.result()
            with scoped_session(container) as db:
                run = _read(db, conversation_id)
                assert run.state_code == SessionState.STOPPED
                assert run.stopped_by_user_id == caller_id
                assert _row(db, conversation_id).close_cause_code is CloseCause.ENDED
        finally:
            fake.close()
