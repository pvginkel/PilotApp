"""A person's message to a project's brain: the project's chat started in the
store, briefed, or a turn of the chat open; a draft's definition chat; a
finished project's chat reading only, the chat the project's state closed,
the handbook's notice, and the line naming a later message's author (design 3
§5.1, §5.3; F38.3, F46.1, F130, F130.2, F5.5, F128.1, F128.5; D052; DB
decisions 60, 61, 62, assertions 159, 229, 243, 244, 245, 251; V02, V05, V06,
V12, V13, V16, V25, V27, V28)."""

import json
import threading
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flask import Flask
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from werkzeug.wrappers import Request, Response

from app import models
from app.database import scoped_session
from app.engine.bus import EngineEvent, ProjectChanged, TreeHashMoved, _Delivery
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import (
    Block,
    Chat,
    Environment,
    Item,
    Project,
    ProjectMember,
    ProjectTransition,
    Turn,
    User,
)
from app.models.reference import (
    ChatKind,
    CloseCause,
    ProjectState,
    RecordKind,
    SessionState,
    TransitionKind,
    UserKind,
    VersionCause,
)
from app.services.auth_service import AuthContext
from app.services.chat_close_service import CLOSED, ChatCloseService
from app.services.chat_service import (
    HANDBOOK_CHANGED_TOTAL,
    STORE_NOTIFICATION,
    ChatService,
)
from app.services.container import ServiceContainer
from app.services.controller_client import HeadlessCreateRequest
from app.services.controller_outage import ControllerOutage
from app.services.environment_service import EnvironmentService
from app.services.pilot_server import PilotServer
from app.services.relay_service import RelayService
from app.services.session_record_service import StoredRecord, read_records
from app.services.session_start_service import SessionStartService
from app.services.start_gate import WorkSlots
from app.services.supervisor import LoopHandle
from app.services.turn_end_read_service import TurnEndReadService
from app.utils import after_commit as after_commit_module
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.chats import close_chat, open_chat
from tests.support.fake_controller import ServedFakeController, client_of
from tests.support.fake_sidecar import STORE_ENVIRONMENT_ID
from tests.support.locks import in_thread, lock_waits
from tests.support.supervisor import WAIT_SECONDS, Supervise, metric_value, wait_until

MCP_URL = "https://pilot-mcp.example.com/mcp"
STORE_REPO = "/work/PilotProjects"
FOLDER = "/work/Projects/soup-club"
WORDS = "What next?"

DRAFT_ASKS = """---
title: Soup club
---

```question id=Q1
default: The lake
```
"""
NO_ITEM = "0b7c51d2-9e3f-4a61-8d0e-5f2c7a9b1e44"
"""An item id no item has."""

DECISION = """# Which stock?

```decision id=D1
options:
  - Leek
  - Onion
```
"""


class _Sent(ServedFakeController):
    """The fake, keeping each send's message; `during_create`, when set, run
    once, as a headless create is answered."""

    def __init__(self, keepalive_seconds: float) -> None:
        super().__init__(keepalive_seconds)
        self.sent: list[str] = []
        self.during_create: Callable[[], None] | None = None

    def _send(self, request: Request, env_id: str, name: str) -> Response:
        self.sent.append((request.get_json(silent=True) or {}).get("message"))
        return super()._send(request, env_id, name)

    def _create_session(self, request: Request, env_id: str) -> Response:
        hook, self.during_create = self.during_create, None
        if hook is not None:
            hook()
        return super()._create_session(request, env_id)


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
    """The fake controller, `container`'s client on it, the store running in
    it with the store repo's root and the project's folder on its tree."""
    served = _Sent(keepalive_seconds=0.2)
    client_of(container, served)
    served.add_environment(
        STORE_ENVIRONMENT_ID, name="PilotProjects", status="running", exempt=True
    )
    served.put_file(STORE_ENVIRONMENT_ID, f"{STORE_REPO}/CLAUDE.md", b"# Pilot\n")
    served.put_file(STORE_ENVIRONMENT_ID, f"{FOLDER}/plan.json", b"{}")
    try:
        yield served
    finally:
        served.close()


def _starts(
    container: ServiceContainer,
    supervise: Supervise,
    *,
    controller_configured: bool = True,
) -> tuple[SessionStartService, RelayService]:
    """The start and the relay on a supervisor of their own, whose loops never
    run, handing Pilot's server at `MCP_URL`."""
    supervisor, _ = supervise(container)
    environments = EnvironmentService(
        container=container,
        supervisor=supervisor,
        stop_after_seconds=1800,
        delete_after_seconds=604800,
    )
    slots = WorkSlots(work_max=3, project_max=3)
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
        pilot_server=pilot_server,
        controller_configured=controller_configured,
        store_environment_id=STORE_ENVIRONMENT_ID,
    )
    return starts, relays


def _chats(
    container: ServiceContainer, starts: SessionStartService, relays: RelayService
) -> ChatService:
    """The chat service on the container's session of the calling thread."""
    return ChatService(
        db=container.db_session(),
        relay_service=relays,
        session_start_service=starts,
        brief_service=container.brief_service(),
        session_record_service=container.session_record_service(),
        view_service=container.view_service(),
        brain_model="opus",
        brain_reasoning_effort="xhigh",
    )


@pytest.fixture
def services(
    container: ServiceContainer, fake: _Sent, supervise: Supervise
) -> tuple[SessionStartService, RelayService]:
    return _starts(container, supervise)


@pytest.fixture
def chats(
    container: ServiceContainer, services: tuple[SessionStartService, RelayService]
) -> ChatService:
    return _chats(container, *services)


def _send(
    chats: ChatService, project: Project, person: User, words: str = WORDS
) -> Turn:
    turn = chats.send(project.id, person, words)
    return turn


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


def _chat_rows(db: DbSession, project: Project) -> list[Chat]:
    return list(
        db.scalars(
            select(Chat)
            .where(Chat.project_id == project.id)
            .execution_options(populate_existing=True)
        )
    )


def _up(
    services: tuple[SessionStartService, RelayService],
    db: DbSession,
    run_id: uuid.UUID,
) -> models.Session:
    """The chat's start loop run, as its loop calls it: its session up and its
    first Turn sent."""
    services[0].run(run_id, LoopHandle(f"start:{run_id}"))
    clear_after_commit_callbacks()
    return _read(db, run_id)


class TestSendStartsTheChat:
    def test_its_opening_is_told_to_the_browsers_and_to_chat_md(
        self,
        container: ServiceContainer,
        chats: ChatService,
        opened: Project,
        person: User,
    ) -> None:
        _send(chats, opened, person)

        chat = container.view_service().chat(opened)
        assert ProjectChanged(opened.id) in _emitted()
        assert [
            event.hash
            for event in _emitted()
            if isinstance(event, TreeHashMoved) and event.path == "soup-club/chat.md"
        ][-1] == chat.hash
        assert "\n\n**ada** · " in chat.text
        assert chat.text.endswith(f"\n\n{WORDS}\n\nOpen\n")

    def test_with_no_chat_open_it_starts_the_projects_chat_briefed(
        self,
        session: DbSession,
        container: ServiceContainer,
        chats: ChatService,
        fake: _Sent,
        opened: Project,
        person: User,
    ) -> None:
        turn = _send(chats, opened, person)

        (chat,) = _chat_rows(session, opened)
        assert (chat.id, chat.kind_code, chat.closed_at) == (
            turn.session_id,
            ChatKind.PROJECT,
            None,
        )
        run = _read(session, chat.id)
        assert (run.kind_code, run.cwd, run.model, run.reasoning_effort) == (
            "chat",
            STORE_REPO,
            "opus",
            "xhigh",
        )
        assert (run.state_code, run.environment_id, run.controller_session) == (
            SessionState.STARTING,
            None,
            None,
        )
        assert (turn.seq, turn.author_user_id, turn.words) == (1, person.id, WORDS)
        assert turn.message == container.brief_service().project_chat(
            opened, person, WORDS, turn.started_at
        )
        assert turn.message.startswith("/chat\n\n")
        assert turn.message.endswith(f"\n{WORDS}")
        assert (run.turns, run.turn_started_at, run.turn_ended_at) == (
            1,
            turn.started_at,
            None,
        )
        assert _sends(session, run.id) == [(1, WORDS)]
        assert "_LoopStart" in _callbacks()
        assert fake.calls == []

    def test_its_start_reaches_the_brain_in_the_store_with_the_brief(
        self,
        session: DbSession,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
    ) -> None:
        turn = _send(chats, opened, person)
        clear_after_commit_callbacks()

        run = _up(services, session, turn.session_id)

        assert (run.state_code, run.environment_id) == (
            SessionState.RUNNING,
            STORE_ENVIRONMENT_ID,
        )
        assert fake.sent == [turn.message]
        (created,) = fake.sessions(STORE_ENVIRONMENT_ID)
        body = created.create_body
        assert (
            body["cwd"],
            body["sandboxReadOnlyCwd"],
            body["sandboxWritableDirs"],
        ) == (
            STORE_REPO,
            True,
            [FOLDER],
        )
        assert body["env"][:2] == [f"PILOT_PROJECT={FOLDER}", f"PILOT_SESSION={run.id}"]
        assert _sends(session, run.id) == [(1, WORDS)]

    def test_while_the_controller_is_unreachable_its_start_is_held(
        self,
        session: DbSession,
        chats: ChatService,
        opened: Project,
        person: User,
        controller_outage: ControllerOutage,
    ) -> None:
        controller_outage.call_unanswered()

        turn = _send(chats, opened, person)

        assert _read(session, turn.session_id).state_code == SessionState.HELD
        assert "_HeldWritten" in _callbacks()

    def test_in_a_paused_project_its_start_is_not_held(
        self, session: DbSession, chats: ChatService, opened: Project, person: User
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

        turn = _send(chats, opened, person)

        assert _read(session, turn.session_id).state_code == SessionState.STARTING

    def test_a_chat_whose_start_failed_starts_afresh_in_the_same_chat(
        self,
        session: DbSession,
        container: ServiceContainer,
        chats: ChatService,
        fake: _Sent,
        opened: Project,
        person: User,
    ) -> None:
        first = _send(chats, opened, person, "One")
        clear_after_commit_callbacks()
        container.environment_service().ensure_environment(
            session, STORE_ENVIRONMENT_ID
        )
        run = _read(session, first.session_id)
        run.environment_id = STORE_ENVIRONMENT_ID
        run.controller_session, run.token_hash = "claude-1", "a" * 64
        run.state_code, run.error = SessionState.FAILED, "the create was refused"
        first.ended_at = datetime.now(UTC)
        session.flush()

        second = _send(chats, opened, person, "Two")

        assert second.session_id == first.session_id
        (chat,) = _chat_rows(session, opened)
        assert chat.closed_at is None
        run = _read(session, first.session_id)
        assert (run.state_code, run.error, run.controller_session) == (
            SessionState.STARTING,
            None,
            None,
        )
        assert (second.seq, second.words) == (2, "Two")
        assert second.message == container.brief_service().project_chat(
            opened, person, "Two", second.started_at
        )
        assert run.turns == 2
        assert _sends(session, run.id) == [(1, "One"), (2, "Two")]
        assert "_LoopStart" in _callbacks()

    @pytest.mark.parametrize("cut", ["held", "in the store", "created"])
    def test_a_chat_whose_start_was_stopped_starts_afresh_in_the_same_chat(
        self,
        session: DbSession,
        container: ServiceContainer,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
        cut: str,
    ) -> None:
        """The chat's Stop of its start before the brief went out, wherever
        it was, leaves the chat open: the next message reaches the brain,
        briefed."""
        first = _send(chats, opened, person, "One")
        clear_after_commit_callbacks()
        run = _read(session, first.session_id)
        if cut != "held":
            container.environment_service().ensure_environment(
                session, STORE_ENVIRONMENT_ID
            )
            run.environment_id = STORE_ENVIRONMENT_ID
        if cut == "created":
            run.controller_session, run.token_hash = "claude-0", "a" * 64
        session.flush()
        chats.stop(opened.id, person)
        clear_after_commit_callbacks()
        assert _read(session, first.session_id).state_code == SessionState.STOPPED

        second = _send(chats, opened, person, "Two")

        assert (second.session_id, second.seq, second.error) == (
            first.session_id,
            2,
            None,
        )
        assert second.message == container.brief_service().project_chat(
            opened, person, "Two", second.started_at
        )
        assert len(_chat_rows(session, opened)) == 1
        clear_after_commit_callbacks()
        run = _up(services, session, first.session_id)
        assert (run.state_code, run.environment_id) == (
            SessionState.RUNNING,
            STORE_ENVIRONMENT_ID,
        )
        assert run.controller_session != "claude-0"
        assert fake.sent == [second.message]
        assert _sends(session, run.id) == [(1, "One"), (2, "Two")]

    def test_a_stopped_chat_with_its_conversation_is_sent_its_words_alone(
        self,
        session: DbSession,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
    ) -> None:
        run = _idle_chat(services, chats, session, fake, opened, person)
        run.state_code, run.conversation_id = SessionState.STOPPED, "conversation-1"
        session.flush()

        turn = _send(chats, opened, person, "Two")

        assert (turn.session_id, turn.seq, turn.message) == (run.id, 2, "Two")
        assert fake.sent == ["Two"]

    def test_a_stopped_turn_still_ending_with_no_conversation_is_refused(
        self,
        session: DbSession,
        chats: ChatService,
        opened: Project,
        person: User,
    ) -> None:
        first = _send(chats, opened, person, "One")
        _read(session, first.session_id).state_code = SessionState.STOPPED
        session.flush()

        with pytest.raises(
            InvalidOperationException, match="a turn of its chat is in flight"
        ):
            _send(chats, opened, person, "Two")

        assert len(session.scalars(select(Turn)).all()) == 1

    @pytest.mark.parametrize("state", [SessionState.HELD, SessionState.STARTING])
    def test_a_message_while_its_start_is_under_way_is_refused(
        self,
        session: DbSession,
        chats: ChatService,
        opened: Project,
        person: User,
        state: SessionState,
    ) -> None:
        first = _send(chats, opened, person)
        _read(session, first.session_id).state_code = state
        session.flush()

        with pytest.raises(
            InvalidOperationException,
            match="Cannot send a message to Pilot in Soup club because its chat is starting",
        ):
            _send(chats, opened, person, "Again")

        assert len(session.scalars(select(Turn)).all()) == 1


def _idle_chat(
    services: tuple[SessionStartService, RelayService],
    chats: ChatService,
    db: DbSession,
    fake: _Sent,
    project: Project,
    person: User,
) -> models.Session:
    """The project's chat started with "One", its first turn ended: idle on
    its headless session in the store."""
    first = _send(chats, project, person, "One")
    clear_after_commit_callbacks()
    run = _up(services, db, first.session_id)
    assert run.controller_session is not None
    fake.finish(STORE_ENVIRONMENT_ID, run.controller_session, "success", "Done.")
    services[1].relay(run.id, LoopHandle(f"relay:{run.id}"))
    clear_after_commit_callbacks()
    run = _read(db, run.id)
    assert run.state_code == SessionState.IDLE
    fake.sent.clear()
    return run


class TestSendToTheOpenChat:
    def test_a_message_to_its_idle_chat_is_a_turn_of_it_its_words_alone(
        self,
        session: DbSession,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
    ) -> None:
        run = _idle_chat(services, chats, session, fake, opened, person)

        turn = _send(chats, opened, person, "Two")

        assert (turn.session_id, turn.seq, turn.message, turn.words) == (
            run.id,
            2,
            "Two",
            "Two",
        )
        assert turn.error is None
        assert fake.sent == ["Two"]
        assert _read(session, run.id).state_code == SessionState.RUNNING
        assert _sends(session, run.id) == [(1, "One"), (2, "Two")]
        assert len(_chat_rows(session, opened)) == 1

    def test_a_message_while_a_turn_of_it_runs_is_refused(
        self,
        session: DbSession,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
    ) -> None:
        first = _send(chats, opened, person, "One")
        clear_after_commit_callbacks()
        _up(services, session, first.session_id)

        with pytest.raises(InvalidOperationException, match="a turn is in flight"):
            _send(chats, opened, person, "Two")

        assert _sends(session, first.session_id) == [(1, "One")]
        assert len(session.scalars(select(Turn)).all()) == 1

    def test_a_quote_travels_into_its_turn(
        self,
        session: DbSession,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
        item: Item,
    ) -> None:
        _idle_chat(services, chats, session, fake, opened, person)
        words = f'<quoted_item id="{item.id}">Badge</quoted_item id="{item.id}"> Blue.'

        turn = _send(chats, opened, person, words)

        assert (turn.quote_item_id, turn.quote_block_id, turn.words) == (
            item.id,
            None,
            words,
        )
        assert fake.sent == [words]


def _stopped_turn_ends(
    services: tuple[SessionStartService, RelayService],
    db: DbSession,
    fake: _Sent,
    run_id: uuid.UUID,
) -> models.Session:
    """The stopped chat's turn in flight ended by the controller's interrupt,
    relayed to its `result` as its loop relays it."""
    run = _read(db, run_id)
    assert run.controller_session is not None
    fake.finish(STORE_ENVIRONMENT_ID, run.controller_session, "interrupted")
    services[1].relay(run.id, LoopHandle(f"relay:{run.id}"))
    clear_after_commit_callbacks()
    return _read(db, run_id)


class TestStop:
    """The chat's Stop (F44): Pilot's answer stopped where it is, as a work
    item's Stop stops one, by any person, whoever sent the message."""

    def test_a_running_turn_is_stopped_by_another_person_interrupted_once_it_commits(
        self,
        session: DbSession,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
        bea: User,
    ) -> None:
        run = _idle_chat(services, chats, session, fake, opened, person)
        _send(chats, opened, person, "Two")
        clear_after_commit_callbacks()
        before = datetime.now(UTC)

        stopped = chats.stop(opened.id, bea)

        assert (stopped.chat.id, stopped.state) == (run.id, SessionState.STOPPED)
        assert stopped.chat.closed_at is None
        run = _read(session, run.id)
        assert (run.state_code, run.stopped_by_user_id, run.current_line) == (
            SessionState.STOPPED,
            bea.id,
            None,
        )
        assert run.stopped_at is not None and run.stopped_at >= before
        # The turn stays in flight for its relay; the interrupt follows the commit.
        assert run.turn_ended_at is None
        assert "_InterruptStart" in _callbacks()
        assert ProjectChanged(opened.id) in _emitted()

    def test_after_its_interrupted_turn_the_next_message_continues_the_conversation(
        self,
        session: DbSession,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
    ) -> None:
        run = _idle_chat(services, chats, session, fake, opened, person)
        # The conversation `claude`'s lines name; the fake's turns print none.
        run.conversation_id = "conversation-1"
        _send(chats, opened, person, "Two")
        chats.stop(opened.id, person)
        clear_after_commit_callbacks()
        run = _stopped_turn_ends(services, session, fake, run.id)
        assert (run.state_code, run.turn_ended_at is not None) == (
            SessionState.STOPPED,
            True,
        )
        fake.sent.clear()

        turn = _send(chats, opened, person, "Three")

        assert (turn.session_id, turn.seq, turn.message) == (run.id, 3, "Three")
        assert fake.sent == ["Three"]
        assert _read(session, run.id).state_code == SessionState.RUNNING

    @pytest.mark.parametrize("state", [SessionState.HELD, SessionState.STARTING])
    def test_a_start_held_or_under_way_ends_its_turn_unsent(
        self,
        session: DbSession,
        chats: ChatService,
        opened: Project,
        person: User,
        state: SessionState,
    ) -> None:
        first = _send(chats, opened, person, "One")
        _read(session, first.session_id).state_code = state
        session.flush()
        clear_after_commit_callbacks()

        chats.stop(opened.id, person)

        run = _read(session, first.session_id)
        assert run.state_code == SessionState.STOPPED
        turn = session.get_one(Turn, first.id, populate_existing=True)
        assert turn.ended_at == run.stopped_at == run.turn_ended_at
        assert "_InterruptStart" not in _callbacks()

    @pytest.mark.parametrize("cut", ["running", "starting"])
    def test_a_stopped_chat_closes_on_its_timeout(
        self,
        session: DbSession,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
        cut: str,
    ) -> None:
        if cut == "running":
            run = _idle_chat(services, chats, session, fake, opened, person)
            _send(chats, opened, person, "Two")
            chats.stop(opened.id, person)
            clear_after_commit_callbacks()
            run = _stopped_turn_ends(services, session, fake, run.id)
        else:
            run = _read(session, _send(chats, opened, person, "One").session_id)
            chats.stop(opened.id, person)
            clear_after_commit_callbacks()
        assert run.turn_ended_at is not None
        run.turn_ended_at -= timedelta(seconds=3301)
        session.flush()

        services[1]._closes.run_close_timer(session)

        assert _closed(session, run.id) is CloseCause.TIMEOUT

    def test_with_no_chat_open_nothing_is_stopped(
        self,
        session: DbSession,
        chats: ChatService,
        opened: Project,
        person: User,
    ) -> None:
        close_chat(
            session, open_chat(session, opened), datetime.now(UTC), CloseCause.TIMEOUT
        )

        with pytest.raises(
            InvalidOperationException,
            match="Cannot stop Pilot in Soup club because no chat is open",
        ):
            chats.stop(opened.id, person)

    @pytest.mark.parametrize(
        ("state", "refusal"),
        [
            (SessionState.IDLE, "it is not answering"),
            (SessionState.STOPPED, "it was stopped already"),
            (SessionState.FAILED, "its chat failed to start"),
        ],
    )
    def test_a_chat_pilot_is_not_answering_in_is_refused(
        self,
        session: DbSession,
        chats: ChatService,
        opened: Project,
        person: User,
        state: SessionState,
        refusal: str,
    ) -> None:
        run = open_chat(session, opened)
        run.state_code = state
        session.flush()

        with pytest.raises(InvalidOperationException) as raised:
            chats.stop(opened.id, person)

        assert (
            raised.value.message == f"Cannot stop Pilot in Soup club because {refusal}"
        )
        assert _read(session, run.id).stopped_at is None

    def test_no_project_has_the_id(self, chats: ChatService, person: User) -> None:
        unknown = uuid.uuid4()

        with pytest.raises(RecordNotFoundException, match=str(unknown)):
            chats.stop(unknown, person)


def _elsewhere(db: DbSession, person: User) -> Item:
    """An item of another project."""
    other = Project(
        created_by_user_id=person.id, state_code=ProjectState.OPEN, slug="other"
    )
    db.add(other)
    db.flush()
    run = models.Session(
        project_id=other.id,
        kind_code="work",
        cwd="/work/Other",
        token_hash=uuid.uuid4().hex,
        state_code=SessionState.IDLE,
    )
    db.add(run)
    db.flush()
    entry = Item(
        project_id=other.id,
        seq=1,
        kind_code="decision",
        title="Elsewhere",
        created_by_session_id=run.id,
    )
    db.add(entry)
    db.flush()
    return entry


def _quoting(kind: str, ref: str, text: str = "Which stock?") -> str:
    return f'<quoted_{kind} id="{ref}">{text}</quoted_{kind} id="{ref}">'


class TestQuote:
    """A Turn's quote, read from the first quote tag in its words (F38.3; DB
    decision 29, assertion 159)."""

    @pytest.fixture
    def decision(
        self,
        container: ServiceContainer,
        opened: Project,
        project_session: models.Session,
    ) -> Item:
        return container.document_service().bear_item(
            opened, "decision", "Which stock?", project_session, DECISION
        )

    def test_a_tag_naming_an_item_of_the_project_quotes_it(
        self, chats: ChatService, opened: Project, person: User, decision: Item
    ) -> None:
        turn = _send(
            chats, opened, person, f"{_quoting('item', str(decision.id))} Leek."
        )

        assert (turn.quote_item_id, turn.quote_block_id) == (decision.id, None)

    def test_a_tag_naming_a_block_of_the_project_quotes_it(
        self,
        session: DbSession,
        chats: ChatService,
        opened: Project,
        person: User,
        decision: Item,
    ) -> None:
        block = session.scalars(
            select(Block).where(
                Block.document_id == decision.id, Block.local_id == "D1"
            )
        ).one()

        turn = _send(
            chats, opened, person, f"{_quoting('block', f'{decision.id}/D1')} Leek."
        )

        assert (turn.quote_item_id, turn.quote_block_id) == (None, block.id)

    def test_the_first_tag_is_the_quote(
        self, chats: ChatService, opened: Project, person: User, decision: Item
    ) -> None:
        words = (
            f"{_quoting('block', f'{decision.id}/D1')} or"
            f" {_quoting('item', str(decision.id))}"
        )

        turn = _send(chats, opened, person, words)

        assert turn.quote_item_id is None and turn.quote_block_id is not None

    @pytest.mark.parametrize(
        "words",
        [
            "No quote at all.",
            _quoting("item", "not-an-id"),
            _quoting("block", "not-an-id/D1"),
            _quoting("item", NO_ITEM),
            f'<quoted_item id="{NO_ITEM}">Unclosed',
        ],
    )
    def test_words_whose_tag_names_nothing_of_the_project_quote_nothing(
        self, chats: ChatService, opened: Project, person: User, words: str
    ) -> None:
        turn = _send(chats, opened, person, words)

        assert (turn.quote_item_id, turn.quote_block_id, turn.words) == (
            None,
            None,
            words,
        )

    def test_another_projects_item_or_an_unknown_block_quotes_nothing(
        self,
        session: DbSession,
        chats: ChatService,
        opened: Project,
        person: User,
        decision: Item,
    ) -> None:
        other = _elsewhere(session, person)
        words = (
            f"{_quoting('item', str(other.id))}"
            f" {_quoting('block', f'{decision.id}/D9')}"
        )

        turn = _send(chats, opened, person, words)

        assert (turn.quote_item_id, turn.quote_block_id) == (None, None)

    @pytest.mark.parametrize(
        "path",
        [
            "handbook.md",
            "project.md",
            "attachments/2/menu.pdf",
            "attachments/2/menus/menu.pdf",
        ],
    )
    def test_a_tag_naming_a_file_of_the_projects_folder_quotes_no_item_or_block(
        self,
        chats: ChatService,
        opened: Project,
        person: User,
        decision: Item,
        path: str,
    ) -> None:
        """The file's tag stays in the words alone, and is the first quote
        tag (DB decision 62)."""
        words = (
            f'<quoted_path path="{path}">Menu</quoted_path path="{path}"> or'
            f" {_quoting('item', str(decision.id))}"
        )

        turn = _send(chats, opened, person, words)

        assert (turn.quote_item_id, turn.quote_block_id, turn.words) == (
            None,
            None,
            words,
        )

    @pytest.mark.parametrize(
        "path",
        [
            "notes.md",
            "items/1-which-stock.md",
            "../handbook.md",
            "attachments/0/menu.pdf",
            "attachments/2/menus/../menu.pdf",
            "attachments/2/./menu.pdf",
            "attachments/2//menu.pdf",
            "attachments/2/menus/",
            "attachments/2/..",
        ],
    )
    def test_a_tag_naming_any_other_path_is_no_quote(
        self,
        chats: ChatService,
        opened: Project,
        person: User,
        decision: Item,
        path: str,
    ) -> None:
        words = (
            f'<quoted_path path="{path}">Notes</quoted_path path="{path}"> or'
            f" {_quoting('item', str(decision.id))}"
        )

        turn = _send(chats, opened, person, words)

        assert (turn.quote_item_id, turn.quote_block_id) == (decision.id, None)

    def test_a_tag_naming_a_block_of_the_draft_quotes_it_as_answer_names_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        chats: ChatService,
        project: Project,
        person: User,
    ) -> None:
        draft = container.document_service().bear_draft(project, DRAFT_ASKS)
        block = session.scalars(
            select(Block).where(Block.document_id == draft.id, Block.local_id == "Q1")
        ).one()

        turn = _send(
            chats, project, person, f"{_quoting('block', 'project.md/Q1')} The lake."
        )

        assert (turn.quote_item_id, turn.quote_block_id) == (None, block.id)

    @pytest.mark.parametrize(
        "local_id",
        [
            pytest.param("Q2", id="another draft's"),
            pytest.param("Q9", id="no draft's"),
        ],
    )
    def test_a_block_its_draft_does_not_hold_quotes_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        chats: ChatService,
        project: Project,
        person: User,
        local_id: str,
    ) -> None:
        container.document_service().bear_draft(project, DRAFT_ASKS)
        other = Project(created_by_user_id=person.id)
        session.add(other)
        session.flush()
        container.document_service().bear_draft(other, "```question id=Q2\n```\n")

        turn = _send(
            chats, project, person, _quoting("block", f"project.md/{local_id}")
        )

        assert (turn.quote_item_id, turn.quote_block_id) == (None, None)


class TestRefusals:
    @pytest.mark.parametrize(
        "standing",
        [
            {"archived": True},
            {"state_code": ProjectState.FINISHED, "archived": True},
            {"state_code": ProjectState.DRAFT, "slug": None, "archived": True},
        ],
    )
    def test_an_archived_project_takes_no_message(
        self,
        session: DbSession,
        chats: ChatService,
        fake: _Sent,
        opened: Project,
        person: User,
        standing: dict[str, Any],
    ) -> None:
        for column, value in standing.items():
            setattr(opened, column, value)
        session.flush()

        with pytest.raises(
            InvalidOperationException,
            match="Cannot send a message to Pilot in Soup club because its project"
            " is archived",
        ):
            _send(chats, opened, person)

        assert _chat_rows(session, opened) == []
        assert fake.calls == []

    def test_an_archived_projects_open_chat_takes_no_message(
        self,
        session: DbSession,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
    ) -> None:
        run = _idle_chat(services, chats, session, fake, opened, person)
        opened.archived = True
        session.flush()

        with pytest.raises(InvalidOperationException, match="its project is archived"):
            _send(chats, opened, person, "Two")

        assert fake.sent == []
        assert _sends(session, run.id) == [(1, "One")]

    def test_no_project_has_the_id(self, chats: ChatService, person: User) -> None:
        with pytest.raises(RecordNotFoundException):
            chats.send(uuid.uuid4(), person, WORDS)

    def test_without_a_controller_configured_no_chat_starts(
        self,
        container: ServiceContainer,
        supervise: Supervise,
        fake: _Sent,
        opened: Project,
        person: User,
    ) -> None:
        chats = _chats(
            container, *_starts(container, supervise, controller_configured=False)
        )

        with pytest.raises(
            InvalidOperationException, match="no controller is configured"
        ):
            _send(chats, opened, person)


def _transition(
    container: ServiceContainer, project: Project, person: User, kind: TransitionKind
) -> None:
    container.project_service().transition_as(person, project.id, kind)
    clear_after_commit_callbacks()


def _last(db: DbSession, run_id: uuid.UUID) -> tuple[RecordKind, Any]:
    (last,) = read_records(db, run_id, limit=1, newest_first=True)
    return last.record.kind_code, last.record.payload


def _closed(db: DbSession, run_id: uuid.UUID) -> CloseCause | None:
    return db.get_one(Chat, run_id, populate_existing=True).close_cause_code


class TestFinishedProjectChat:
    def test_a_message_starts_it_reading_only_with_no_surface(
        self,
        session: DbSession,
        container: ServiceContainer,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
    ) -> None:
        _transition(container, opened, person, TransitionKind.FINISHED)

        turn = _send(chats, opened, person, "What was settled?")

        assert turn.message == container.brief_service().project_chat(
            opened, person, "What was settled?", turn.started_at
        )
        assert turn.message.startswith(
            "/chat\n\nPilot's brief · a finished project's chat ·"
        )
        clear_after_commit_callbacks()
        run = _up(services, session, turn.session_id)
        assert run.state_code == SessionState.RUNNING
        assert fake.sent == [turn.message]
        (created,) = fake.sessions(STORE_ENVIRONMENT_ID)
        body = created.create_body
        assert (body["cwd"], body["sandboxReadOnlyCwd"]) == (STORE_REPO, True)
        assert "sandboxWritableDirs" not in body
        assert "mcpConfig" not in body
        assert body["env"] == [f"PILOT_PROJECT={FOLDER}", f"PILOT_SESSION={run.id}"]
        assert _sends(session, run.id) == [(1, "What was settled?")]

    def test_its_create_refused_422_fails_its_start_at_once(
        self,
        session: DbSession,
        container: ServiceContainer,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
    ) -> None:
        """No folder to wait for: the store repo's root missing is no wait
        `pilot-sync` ends (V25)."""
        _transition(container, opened, person, TransitionKind.FINISHED)
        fake.remove_file(STORE_ENVIRONMENT_ID, f"{STORE_REPO}/CLAUDE.md")
        turn = _send(chats, opened, person)
        clear_after_commit_callbacks()

        run = _up(services, session, turn.session_id)

        assert run.state_code == SessionState.FAILED
        assert run.error is not None
        assert f'the cwd "{STORE_REPO}" does not exist' in run.error
        creates = f"POST /environments/{STORE_ENVIRONMENT_ID}/sessions/headless"
        assert fake.calls.count(creates) == 1


class TestTheProjectsStateClosesItsChat:
    def test_after_finish_the_next_message_starts_a_chat_reading_only(
        self,
        session: DbSession,
        container: ServiceContainer,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
    ) -> None:
        run = _idle_chat(services, chats, session, fake, opened, person)
        _transition(container, opened, person, TransitionKind.FINISHED)

        turn = _send(chats, opened, person, "Two")

        assert turn.session_id != run.id
        assert _closed(session, run.id) is CloseCause.FINISHED
        assert _last(session, run.id) == (
            RecordKind.SERVER,
            {"type": CLOSED, "cause": "finished"},
        )
        assert fake.sent == []
        new = _up(services, session, turn.session_id)
        assert new.controller_session is not None
        body = fake.session(STORE_ENVIRONMENT_ID, new.controller_session).create_body
        assert "sandboxWritableDirs" not in body
        assert "mcpConfig" not in body

    def test_after_reopen_the_next_message_starts_a_writable_chat(
        self,
        session: DbSession,
        container: ServiceContainer,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
    ) -> None:
        _transition(container, opened, person, TransitionKind.FINISHED)
        run = _idle_chat(services, chats, session, fake, opened, person)
        _transition(container, opened, person, TransitionKind.REOPENED)

        turn = _send(chats, opened, person, "Two")

        assert turn.session_id != run.id
        assert _closed(session, run.id) is CloseCause.REOPENED
        assert turn.message == container.brief_service().project_chat(
            opened, person, "Two", turn.started_at
        )
        new = _up(services, session, turn.session_id)
        assert new.controller_session is not None
        body = fake.session(STORE_ENVIRONMENT_ID, new.controller_session).create_body
        assert body["sandboxWritableDirs"] == [FOLDER]
        assert json.loads(body["mcpConfig"][0])["mcpServers"]["pilot"]["url"] == (
            f"{MCP_URL}/store"
        )

    def test_reopen_stops_a_turn_of_the_read_only_chat_its_close_after_its_end(
        self,
        session: DbSession,
        container: ServiceContainer,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
    ) -> None:
        _transition(container, opened, person, TransitionKind.FINISHED)
        first = _send(chats, opened, person, "One")
        clear_after_commit_callbacks()
        run = _up(services, session, first.session_id)
        assert run.controller_session is not None

        _transition(container, opened, person, TransitionKind.REOPENED)

        assert _closed(session, run.id) is CloseCause.REOPENED
        assert _read(session, run.id).state_code == SessionState.STOPPED
        fake.finish(STORE_ENVIRONMENT_ID, run.controller_session, "interrupted")
        services[1].relay(run.id, LoopHandle(f"relay:{run.id}"))
        clear_after_commit_callbacks()
        records = _records(session, run.id)
        assert records[-2].record.kind_code == RecordKind.RESULT
        assert _last(session, run.id) == (
            RecordKind.SERVER,
            {"type": CLOSED, "cause": "reopened"},
        )

    def test_archive_closes_the_chat_and_after_bring_back_a_message_starts_one(
        self,
        session: DbSession,
        container: ServiceContainer,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
    ) -> None:
        """Archive closes the chat open then, `archived`; the archived project
        takes no message; Bring back starts no chat, and the next message
        starts one, briefed (F128.1, F128.5; DB decision 60)."""
        run = _idle_chat(services, chats, session, fake, opened, person)
        _transition(container, opened, person, TransitionKind.ARCHIVED)

        assert _closed(session, run.id) is CloseCause.ARCHIVED
        assert _last(session, run.id) == (
            RecordKind.SERVER,
            {"type": CLOSED, "cause": "archived"},
        )
        with pytest.raises(InvalidOperationException, match="its project is archived"):
            _send(chats, opened, person, "Two")
        _transition(container, opened, person, TransitionKind.BROUGHT_BACK)
        assert [chat.id for chat in _chat_rows(session, opened)] == [run.id]

        turn = _send(chats, opened, person, "Two")

        assert turn.session_id != run.id
        assert turn.message == container.brief_service().project_chat(
            opened, person, "Two", turn.started_at
        )
        assert fake.sent == []


ADA = AuthContext(
    subject="subject-ada", email=None, name="Ada Example", roles={"editor"}
)
"""The `person` fixture, signed in."""


@pytest.fixture
def draft(container: ServiceContainer, person: User) -> Project:
    """A draft from the plus, `person`'s, its draft born empty."""
    made = container.project_service().create(ADA)
    clear_after_commit_callbacks()
    return made


def _draft_folder(draft: Project) -> str:
    return f"/work/Projects/draft-{draft.number}"


def _on_disk(fake: _Sent, draft: Project) -> None:
    """The draft's folder written into the store's tree, as `pilot-sync`
    writes it once the draft's manifest commits."""
    fake.put_file(STORE_ENVIRONMENT_ID, f"{_draft_folder(draft)}/project.md", b"")


class TestDefinitionChat:
    """A draft's chat, its definition chat, from the plus (design 3 §5.1,
    §5.3; F46.1, F50, F130.2; DB decision 60)."""

    def test_a_message_to_a_draft_starts_its_definition_chat_briefed(
        self,
        session: DbSession,
        container: ServiceContainer,
        chats: ChatService,
        fake: _Sent,
        draft: Project,
        person: User,
    ) -> None:
        turn = _send(chats, draft, person)

        (chat,) = _chat_rows(session, draft)
        assert (chat.id, chat.kind_code, chat.closed_at) == (
            turn.session_id,
            ChatKind.DEFINITION,
            None,
        )
        run = _read(session, chat.id)
        assert (run.kind_code, run.cwd, run.state_code) == (
            "chat",
            STORE_REPO,
            SessionState.STARTING,
        )
        assert (turn.seq, turn.author_user_id, turn.words) == (1, person.id, WORDS)
        assert turn.message == container.brief_service().definition_chat(
            draft, person, WORDS, turn.started_at
        )
        assert turn.message.startswith(
            "/create\n\nPilot's brief · the definition chat ·"
            f" {_draft_folder(draft)} · "
        )
        assert turn.message.endswith(f"\n\nThe message:\n{WORDS}")
        assert _sends(session, run.id) == [(1, WORDS)]
        assert "_LoopStart" in _callbacks()
        assert fake.calls == []

    def test_its_session_is_created_boxed_in_its_folder_once_that_is_on_disk(
        self,
        session: DbSession,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        draft: Project,
        person: User,
    ) -> None:
        """Its first create refused `422`, the folder not yet written, is made
        again once it is (F50, TD §4.2)."""
        services[0]._folder_wait, services[0]._folder_retry = 2.0, 0.05

        def refused_once() -> None:
            fake.during_create = lambda: _on_disk(fake, draft)

        fake.during_create = refused_once
        turn = _send(chats, draft, person)
        clear_after_commit_callbacks()

        run = _up(services, session, turn.session_id)

        assert (run.state_code, run.environment_id) == (
            SessionState.RUNNING,
            STORE_ENVIRONMENT_ID,
        )
        creates = f"POST /environments/{STORE_ENVIRONMENT_ID}/sessions/headless"
        assert fake.calls.count(creates) == 2
        (created,) = fake.sessions(STORE_ENVIRONMENT_ID)
        body = created.create_body
        assert (
            body["cwd"],
            body["sandboxReadOnlyCwd"],
            body["sandboxWritableDirs"],
            body["env"][:2],
        ) == (
            STORE_REPO,
            True,
            [_draft_folder(draft)],
            [f"PILOT_PROJECT={_draft_folder(draft)}", f"PILOT_SESSION={run.id}"],
        )
        assert fake.sent == [turn.message]

    def test_a_later_message_is_a_turn_of_it_its_words_alone(
        self,
        session: DbSession,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        draft: Project,
        person: User,
    ) -> None:
        _on_disk(fake, draft)
        run = _idle_chat(services, chats, session, fake, draft, person)

        turn = _send(chats, draft, person, "Two")

        assert (turn.session_id, turn.seq, turn.message, turn.words) == (
            run.id,
            2,
            "Two",
            "Two",
        )
        assert fake.sent == ["Two"]
        assert [chat.kind_code for chat in _chat_rows(session, draft)] == [
            ChatKind.DEFINITION
        ]

    def test_after_archive_and_bring_back_a_message_starts_a_fresh_one(
        self,
        session: DbSession,
        container: ServiceContainer,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        draft: Project,
        person: User,
    ) -> None:
        """Archive closes the definition chat, `archived`; the archived draft
        takes no message; once brought back, its next message starts a
        definition chat afresh, briefed (F130.2; DB decision 60)."""
        _on_disk(fake, draft)
        run = _idle_chat(services, chats, session, fake, draft, person)
        _transition(container, draft, person, TransitionKind.ARCHIVED)

        assert _closed(session, run.id) is CloseCause.ARCHIVED
        with pytest.raises(InvalidOperationException, match="its project is archived"):
            _send(chats, draft, person, "Two")
        _transition(container, draft, person, TransitionKind.BROUGHT_BACK)

        turn = _send(chats, draft, person, "Two")

        assert turn.session_id != run.id
        assert [
            (chat.id, chat.kind_code, chat.close_cause_code)
            for chat in sorted(
                _chat_rows(session, draft), key=lambda chat: chat.id != run.id
            )
        ] == [
            (run.id, ChatKind.DEFINITION, CloseCause.ARCHIVED),
            (turn.session_id, ChatKind.DEFINITION, None),
        ]
        assert turn.message == container.brief_service().definition_chat(
            draft, person, "Two", turn.started_at
        )


class TestHandbookNotice:
    def test_a_turn_after_the_handbook_changed_opens_with_the_notice(
        self,
        session: DbSession,
        container: ServiceContainer,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
    ) -> None:
        run = _idle_chat(services, chats, session, fake, opened, person)
        container.document_service().bear_handbook(opened, "# Handbook\n")
        counted = metric_value(HANDBOOK_CHANGED_TOTAL, project=str(opened.id))

        turn = _send(chats, opened, person, "Two")

        assert (turn.session_id, turn.message, turn.words) == (
            run.id,
            f"{STORE_NOTIFICATION}\n\nTwo",
            "Two",
        )
        assert STORE_NOTIFICATION == (
            "<store_notification>\n"
            "The handbook (handbook.md) changed since your last turn.\n"
            "</store_notification>"
        )
        assert fake.sent == [turn.message]
        assert _sends(session, run.id) == [(1, "One"), (2, "Two")]
        assert metric_value(HANDBOOK_CHANGED_TOTAL, project=str(opened.id)) == (
            counted + 1
        )

    def test_a_handbook_unchanged_since_the_chats_last_turn_brings_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
    ) -> None:
        container.document_service().bear_handbook(opened, "# Handbook\n")
        _idle_chat(services, chats, session, fake, opened, person)
        counted = metric_value(HANDBOOK_CHANGED_TOTAL, project=str(opened.id))

        turn = _send(chats, opened, person, "Two")

        assert turn.message == "Two"
        assert metric_value(HANDBOOK_CHANGED_TOTAL, project=str(opened.id)) == counted

    def test_the_notice_comes_once_per_change(
        self,
        session: DbSession,
        container: ServiceContainer,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
    ) -> None:
        run = _idle_chat(services, chats, session, fake, opened, person)
        handbook = container.document_service().bear_handbook(opened, "# Handbook\n")
        assert _send(chats, opened, person, "Two").message.startswith(
            STORE_NOTIFICATION
        )
        clear_after_commit_callbacks()
        assert run.controller_session is not None
        fake.finish(STORE_ENVIRONMENT_ID, run.controller_session, "success", "Done.")
        services[1].relay(run.id, LoopHandle(f"relay:{run.id}"))
        clear_after_commit_callbacks()

        assert _send(chats, opened, person, "Three").message == "Three"
        clear_after_commit_callbacks()
        fake.finish(STORE_ENVIRONMENT_ID, run.controller_session, "success", "Done.")
        services[1].relay(run.id, LoopHandle(f"relay:{run.id}"))
        clear_after_commit_callbacks()
        container.document_service().publish(handbook, "# Handbook\n\n- Salt last.\n")
        assert _send(chats, opened, person, "Four").message == (
            f"{STORE_NOTIFICATION}\n\nFour"
        )

    def test_the_chats_own_handbook_edits_bring_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
    ) -> None:
        """Slice 025: the chat's own saves are credited to it, so its turn's
        Versions are its Session's."""
        documents = container.document_service()
        handbook = documents.bear_handbook(opened, "# Handbook\n")
        run = _idle_chat(services, chats, session, fake, opened, person)
        documents.publish(handbook, "# Handbook\n\n- Salt last.\n")
        documents.cut_version(handbook, VersionCause.TURN, run.id)
        counted = metric_value(HANDBOOK_CHANGED_TOTAL, project=str(opened.id))

        turn = _send(chats, opened, person, "Two")

        assert turn.message == "Two"
        assert metric_value(HANDBOOK_CHANGED_TOTAL, project=str(opened.id)) == counted

    @pytest.mark.parametrize("writer", ["a job", "nobody", "unversioned"])
    def test_a_handbook_edit_not_the_chats_own_brings_the_notice(
        self,
        session: DbSession,
        container: ServiceContainer,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
        writer: str,
    ) -> None:
        """A job's Version, one of no Session, or a publication not yet cut
        into a Version, each beside the chat's own since its last turn."""
        documents = container.document_service()
        handbook = documents.bear_handbook(opened, "# Handbook\n")
        run = _idle_chat(services, chats, session, fake, opened, person)
        job = models.Session(
            project_id=opened.id,
            environment_id=STORE_ENVIRONMENT_ID,
            kind_code="job",
            cwd="/work/PilotProjects",
            token_hash="2" * 64,
            state_code=SessionState.RUNNING,
        )
        session.add(job)
        session.flush()
        documents.publish(handbook, "# Handbook\n\n- Salt last.\n")
        documents.cut_version(handbook, VersionCause.TURN, run.id)
        documents.publish(handbook, "# Handbook\n\n- Salt last.\n- Pepper too.\n")
        if writer != "unversioned":
            documents.cut_version(
                handbook, VersionCause.TURN, job.id if writer == "a job" else None
            )

        turn = _send(chats, opened, person, "Two")

        assert turn.message == f"{STORE_NOTIFICATION}\n\nTwo"

    def test_a_send_that_failed_counts_no_notice(
        self,
        session: DbSession,
        container: ServiceContainer,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
    ) -> None:
        _idle_chat(services, chats, session, fake, opened, person)
        container.document_service().bear_handbook(opened, "# Handbook\n")
        counted = metric_value(HANDBOOK_CHANGED_TOTAL, project=str(opened.id))
        fake.unreachable(STORE_ENVIRONMENT_ID)

        turn = _send(chats, opened, person, "Two")

        assert turn.error is not None
        assert turn.message == f"{STORE_NOTIFICATION}\n\nTwo"
        assert metric_value(HANDBOOK_CHANGED_TOTAL, project=str(opened.id)) == counted

    def test_a_retry_after_a_failed_send_carries_the_notice_again(
        self,
        session: DbSession,
        container: ServiceContainer,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
    ) -> None:
        """A Turn whose send failed never reached the brain, nor its notice."""
        _idle_chat(services, chats, session, fake, opened, person)
        container.document_service().bear_handbook(opened, "# Handbook\n")
        fake.unreachable(STORE_ENVIRONMENT_ID)
        assert _send(chats, opened, person, "Two").error is not None
        fake.unreachable(STORE_ENVIRONMENT_ID, on=False)
        counted = metric_value(HANDBOOK_CHANGED_TOTAL, project=str(opened.id))

        retried = _send(chats, opened, person, "Two")

        assert retried.error is None
        assert retried.message == f"{STORE_NOTIFICATION}\n\nTwo"
        assert metric_value(HANDBOOK_CHANGED_TOTAL, project=str(opened.id)) == (
            counted + 1
        )


@pytest.fixture
def bea(session: DbSession, opened: Project) -> User:
    """A second person, a member of `opened`."""
    user = User(
        kind_code=UserKind.PERSON,
        subject="subject-bea",
        handle="bea",
        name="Bea Example",
        avatar_slot=2,
    )
    session.add(user)
    session.flush()
    session.add(
        ProjectMember(
            project_id=opened.id, user_id=user.id, joined_at=datetime.now(UTC)
        )
    )
    session.flush()
    return user


def _turn_ended(
    services: tuple[SessionStartService, RelayService],
    fake: _Sent,
    run: models.Session,
) -> None:
    """The chat's turn in flight ended, as its relay ends it."""
    assert run.controller_session is not None
    fake.finish(STORE_ENVIRONMENT_ID, run.controller_session, "success", "Done.")
    services[1].relay(run.id, LoopHandle(f"relay:{run.id}"))
    clear_after_commit_callbacks()


class TestNamedMessage:
    """A person's message after another person's names its author, as the
    brief names the first (design 3 §5.3; DB decision 61, assertion 251)."""

    def test_a_message_after_another_persons_names_its_author_before_its_words(
        self,
        session: DbSession,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
        bea: User,
    ) -> None:
        run = _idle_chat(services, chats, session, fake, opened, person)

        turn = _send(chats, opened, bea, "Two")

        assert (turn.message, turn.words, turn.author_user_id) == (
            "The message, from bea (member):\nTwo",
            "Two",
            bea.id,
        )
        assert fake.sent == [turn.message]
        assert _sends(session, run.id) == [(1, "One"), (2, "Two")]

    def test_each_change_of_author_is_named_and_a_repeat_is_not(
        self,
        session: DbSession,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
        bea: User,
    ) -> None:
        run = _idle_chat(services, chats, session, fake, opened, person)
        _send(chats, opened, bea, "Two")
        clear_after_commit_callbacks()
        _turn_ended(services, fake, run)

        named = _send(chats, opened, person, "Three")
        clear_after_commit_callbacks()
        _turn_ended(services, fake, run)
        repeated = _send(chats, opened, person, "Four")

        assert (named.message, repeated.message) == (
            "The message, from ada (not a member):\nThree",
            "Four",
        )

    def test_a_server_turn_between_names_no_one(
        self,
        session: DbSession,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
        bea: User,
    ) -> None:
        """The previous Turn with an author is the one compared: the server's
        own, a follow-up or a "continue", has none."""
        run = _idle_chat(services, chats, session, fake, opened, person)
        _send(chats, opened, bea, "Two")
        clear_after_commit_callbacks()
        _turn_ended(services, fake, run)
        now = datetime.now(UTC)
        session.add(
            Turn(
                session_id=run.id,
                seq=3,
                message="continue",
                started_at=now,
                ended_at=now,
            )
        )
        session.flush()

        turn = _send(chats, opened, bea, "Three")

        assert (turn.seq, turn.message) == (4, "Three")

    def test_a_retry_after_a_failed_send_is_named_again(
        self,
        session: DbSession,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
        bea: User,
    ) -> None:
        """A Turn whose send failed never reached the brain, so its naming
        line names no one: the retry names its author again."""
        _idle_chat(services, chats, session, fake, opened, person)
        fake.unreachable(STORE_ENVIRONMENT_ID)
        failed = _send(chats, opened, bea, "Approve the red badge")
        assert failed.error is not None
        fake.unreachable(STORE_ENVIRONMENT_ID, on=False)

        retried = _send(chats, opened, bea, "Approve the red badge")

        assert retried.error is None
        assert retried.message == (
            "The message, from bea (member):\nApprove the red badge"
        )

    def test_a_turn_that_failed_after_its_send_went_out_is_not_named_again(
        self,
        session: DbSession,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
        bea: User,
    ) -> None:
        """A Turn that failed in the brain reached it, naming line and all."""
        run = _idle_chat(services, chats, session, fake, opened, person)
        _send(chats, opened, bea, "Two")
        clear_after_commit_callbacks()
        assert run.controller_session is not None
        fake.finish(STORE_ENVIRONMENT_ID, run.controller_session, "error", "Broke.")
        services[1].relay(run.id, LoopHandle(f"relay:{run.id}"))
        clear_after_commit_callbacks()
        assert session.scalars(
            select(Turn.error).where(Turn.session_id == run.id, Turn.seq == 2)
        ).one()

        assert _send(chats, opened, bea, "Three").message == "Three"

    def test_the_handbooks_notice_goes_before_the_naming_line(
        self,
        session: DbSession,
        container: ServiceContainer,
        chats: ChatService,
        services: tuple[SessionStartService, RelayService],
        fake: _Sent,
        opened: Project,
        person: User,
        bea: User,
    ) -> None:
        _idle_chat(services, chats, session, fake, opened, person)
        container.document_service().bear_handbook(opened, "# Handbook\n")

        turn = _send(chats, opened, bea, "Two")

        assert (turn.message, turn.words) == (
            f"{STORE_NOTIFICATION}\n\nThe message, from bea (member):\nTwo",
            "Two",
        )


def _committed(
    container: ServiceContainer, state: ProjectState = ProjectState.OPEN
) -> tuple[uuid.UUID, uuid.UUID]:
    """A person and a project in `state`, committed; their ids. A draft's
    `project.md` names the project and its slug, so Create project takes it."""
    with scoped_session(container) as db:
        person = User(
            kind_code=UserKind.PERSON,
            subject="subject-ada",
            handle="ada",
            name="Ada Example",
            avatar_slot=1,
        )
        db.add(person)
        db.flush()
        draft = state is ProjectState.DRAFT
        project = Project(
            created_by_user_id=person.id,
            state_code=state,
            slug=None if draft else "soup-club",
            name="Soup club",
        )
        db.add(project)
        db.flush()
        if draft:
            container.document_service().bear_draft(
                project, "---\nslug: soup-club\n---\n# Soup club\n"
            )
        return person.id, project.id


class TestTwoMessages:
    def test_two_messages_with_no_chat_open_start_one_chat(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        """The second waits on the project's row the first start holds, then
        finds its chat starting."""
        container = committed_app.container
        person_id, project_id = _committed(container)
        services = _starts(container, supervise)
        written, proceed = threading.Event(), threading.Event()

        def send(words: str) -> uuid.UUID:
            with scoped_session(container) as db:
                chat_id = (
                    _chats(container, *services)
                    .send(project_id, db.get_one(User, person_id), words)
                    .session_id
                )
                if words == "One":
                    written.set()
                    assert proceed.wait(WAIT_SECONDS)
                return chat_id

        first = in_thread(lambda: send("One"))
        assert written.wait(WAIT_SECONDS)
        second = in_thread(lambda: send("Two"))
        wait_until(lambda: lock_waits(container) == 1, "the second send waiting")
        proceed.set()

        chat_id = first.result()
        with pytest.raises(InvalidOperationException, match="its chat is starting"):
            second.result()
        with scoped_session(container) as db:
            assert db.scalars(select(Chat.id)).all() == [chat_id]
            assert db.scalars(select(Turn.words)).all() == ["One"]


def _committed_idle_chat(
    container: ServiceContainer,
    fake: _Sent,
    state: ProjectState = ProjectState.OPEN,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A person, a project in `state` and its idle chat on a headless session
    in the store, a draft's its definition chat, committed; their ids."""
    person_id, project_id = _committed(container, state)
    name = (
        client_of(container, fake)
        .create_headless_session(STORE_ENVIRONMENT_ID, HeadlessCreateRequest())
        .name
    )
    with scoped_session(container) as db:
        db.add(Environment(id=STORE_ENVIRONMENT_ID, name="PilotProjects", exempt=True))
        db.flush()
        now = datetime.now(UTC)
        run = models.Session(
            project_id=project_id,
            environment_id=STORE_ENVIRONMENT_ID,
            kind_code="chat",
            cwd=STORE_REPO,
            conversation_id="conversation-1",
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
            Chat(
                id=run.id,
                project_id=project_id,
                session_kind_code="chat",
                kind_code=(
                    ChatKind.DEFINITION
                    if state is ProjectState.DRAFT
                    else ChatKind.PROJECT
                ),
            )
        )
        db.add(
            Turn(
                session_id=run.id,
                seq=1,
                author_user_id=person_id,
                message="/chat",
                words="One",
                started_at=now,
                ended_at=now,
            )
        )
        return person_id, project_id, run.id


class TestAMessageMeetingFinish:
    def test_a_message_to_the_chat_finish_closes_meanwhile_starts_the_next(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        """The send waits on the chat's Session, which Finish's close holds;
        once Finish commits it finds the chat closed, lets its lock go and
        starts the finished project's chat, sending nothing to the closed
        one."""
        container = committed_app.container
        fake = _Sent(keepalive_seconds=0.2)
        try:
            fake.add_environment(
                STORE_ENVIRONMENT_ID, name="PilotProjects", status="running"
            )
            person_id, project_id, chat_id = _committed_idle_chat(container, fake)
            services = _starts(container, supervise)
            finished, finish_ends = threading.Event(), threading.Event()
            sent, send_ends = threading.Event(), threading.Event()

            def finish() -> None:
                with scoped_session(container) as db:
                    container.project_service().transition_as(
                        db.get_one(User, person_id), project_id, TransitionKind.FINISHED
                    )
                    finished.set()
                    assert finish_ends.wait(WAIT_SECONDS)

            def send() -> uuid.UUID:
                with scoped_session(container) as db:
                    turn = _chats(container, *services).send(
                        project_id, db.get_one(User, person_id), "Two"
                    )
                    sent.set()
                    assert send_ends.wait(WAIT_SECONDS)
                    return turn.session_id

            finishing = in_thread(finish)
            assert finished.wait(WAIT_SECONDS)
            sending = in_thread(send)
            wait_until(lambda: lock_waits(container) == 1, "the send waiting")
            finish_ends.set()
            finishing.result()
            assert sent.wait(WAIT_SECONDS)
            # The closed chat's Session is free while the send's transaction
            # still runs: the savepoint that locked it let it go.
            with scoped_session(container) as db:
                db.execute(
                    select(models.Session.id)
                    .where(models.Session.id == chat_id)
                    .with_for_update(nowait=True)
                ).one()
            send_ends.set()
            new_chat = sending.result()

            assert new_chat != chat_id
            assert fake.sent == []
            with scoped_session(container) as db:
                assert db.get_one(Chat, chat_id).close_cause_code is CloseCause.FINISHED
                assert _last(db, chat_id) == (
                    RecordKind.SERVER,
                    {"type": CLOSED, "cause": "finished"},
                )
                turn = db.scalars(select(Turn).where(Turn.session_id == new_chat)).one()
                assert turn.message.startswith(
                    "/chat\n\nPilot's brief · a finished project's chat ·"
                )
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
        """The transition's stop waits on the chat's Session, which the send
        holds across the controller's call, and stops the turn it started."""
        container = committed_app.container
        fake = _SendHeld(keepalive_seconds=0.2)
        try:
            fake.add_environment(
                STORE_ENVIRONMENT_ID, name="PilotProjects", status="running"
            )
            person_id, project_id, chat_id = _committed_idle_chat(
                container, fake, state
            )
            services = _starts(container, supervise)

            def send() -> uuid.UUID:
                with scoped_session(container) as db:
                    return (
                        _chats(container, *services)
                        .send(project_id, db.get_one(User, person_id), "Two")
                        .session_id
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

            assert sending.result() == chat_id
            transitioning.result()
            assert fake.sent == ["Two"]
            with scoped_session(container) as db:
                run = _read(db, chat_id)
                assert run.state_code == SessionState.STOPPED
                assert run.stopped_by_user_id == person_id
                assert db.get_one(Chat, chat_id).close_cause_code is cause
        finally:
            fake.close()

    def test_a_message_meeting_archive_is_refused(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        """The send waits on the chat's Session, which Archive's stop holds;
        once Archive commits it finds the chat closed and the project archived
        and sends nothing."""
        container = committed_app.container
        fake = _Sent(keepalive_seconds=0.2)
        try:
            fake.add_environment(
                STORE_ENVIRONMENT_ID, name="PilotProjects", status="running"
            )
            person_id, project_id, chat_id = _committed_idle_chat(container, fake)
            services = _starts(container, supervise)
            archived, archive_ends = threading.Event(), threading.Event()

            def archive() -> None:
                with scoped_session(container) as db:
                    container.project_service().transition_as(
                        db.get_one(User, person_id), project_id, TransitionKind.ARCHIVED
                    )
                    archived.set()
                    assert archive_ends.wait(WAIT_SECONDS)

            def send() -> None:
                with scoped_session(container) as db:
                    _chats(container, *services).send(
                        project_id, db.get_one(User, person_id), "Two"
                    )

            archiving = in_thread(archive)
            assert archived.wait(WAIT_SECONDS)
            sending = in_thread(send)
            wait_until(lambda: lock_waits(container) == 1, "the send waiting")
            archive_ends.set()
            archiving.result()

            with pytest.raises(
                InvalidOperationException, match="its project is archived"
            ):
                sending.result()
            assert fake.sent == []
            with scoped_session(container) as db:
                assert _read(db, chat_id).state_code == SessionState.IDLE
                assert db.get_one(Chat, chat_id).close_cause_code is (
                    CloseCause.ARCHIVED
                )
                assert db.scalars(select(Chat.id)).all() == [chat_id]
        finally:
            fake.close()


class TestCreateMeetingAMessage:
    """Create project and a message to the definition chat never interleave
    (F48.1, F48.2)."""

    def test_create_meeting_a_send_in_flight_is_refused(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        """Create waits on the chat's Session, which the send holds across
        the controller's call, and reads Pilot writing once it commits."""
        container = committed_app.container
        fake = _SendHeld(keepalive_seconds=0.2)
        try:
            fake.add_environment(
                STORE_ENVIRONMENT_ID, name="PilotProjects", status="running"
            )
            person_id, project_id, chat_id = _committed_idle_chat(
                container, fake, ProjectState.DRAFT
            )
            services = _starts(container, supervise)

            def send() -> None:
                with scoped_session(container) as db:
                    _chats(container, *services).send(
                        project_id, db.get_one(User, person_id), "Two"
                    )

            def create() -> None:
                with scoped_session(container) as db:
                    container.project_service().transition_as(
                        db.get_one(User, person_id), project_id, TransitionKind.OPENED
                    )

            sending = in_thread(send)
            assert fake.sending.wait(WAIT_SECONDS)
            creating = in_thread(create)
            wait_until(lambda: lock_waits(container) == 1, "Create waiting")
            fake.release.set()
            sending.result()

            with pytest.raises(
                InvalidOperationException,
                match="Cannot create Soup club because Pilot is writing",
            ):
                creating.result()
            with scoped_session(container) as db:
                assert db.get_one(Project, project_id).state_code is ProjectState.DRAFT
                assert db.get_one(Chat, chat_id).closed_at is None
        finally:
            fake.close()

    def test_a_message_meeting_create_starts_the_projects_chat(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        """The send waits on the definition chat's Session, which Create
        holds; once Create commits it finds the chat closed and starts the
        open project's chat, sending nothing to the closed one."""
        container = committed_app.container
        fake = _Sent(keepalive_seconds=0.2)
        try:
            fake.add_environment(
                STORE_ENVIRONMENT_ID, name="PilotProjects", status="running"
            )
            person_id, project_id, chat_id = _committed_idle_chat(
                container, fake, ProjectState.DRAFT
            )
            services = _starts(container, supervise)
            created, create_ends = threading.Event(), threading.Event()

            def create() -> None:
                with scoped_session(container) as db:
                    container.project_service(
                        job_service=container.job_service(
                            session_start_service=services[0]
                        )
                    ).transition_as(
                        db.get_one(User, person_id), project_id, TransitionKind.OPENED
                    )
                    created.set()
                    assert create_ends.wait(WAIT_SECONDS)

            def send() -> uuid.UUID:
                with scoped_session(container) as db:
                    return (
                        _chats(container, *services)
                        .send(project_id, db.get_one(User, person_id), "Two")
                        .session_id
                    )

            creating = in_thread(create)
            assert created.wait(WAIT_SECONDS)
            sending = in_thread(send)
            wait_until(lambda: lock_waits(container) == 1, "the send waiting")
            create_ends.set()
            creating.result()
            new_chat = sending.result()

            assert new_chat != chat_id
            assert fake.sent == []
            with scoped_session(container) as db:
                assert [
                    (chat.id, chat.kind_code, chat.close_cause_code)
                    for chat in sorted(
                        db.scalars(select(Chat)), key=lambda chat: chat.id != chat_id
                    )
                ] == [
                    (chat_id, ChatKind.DEFINITION, CloseCause.CREATED),
                    (new_chat, ChatKind.PROJECT, None),
                ]
                assert _last(db, chat_id) == (
                    RecordKind.SERVER,
                    {"type": CLOSED, "cause": "created"},
                )
                turn = db.scalars(select(Turn).where(Turn.session_id == new_chat)).one()
                assert turn.message.startswith("/chat\n\nPilot's brief · ")
        finally:
            fake.close()
