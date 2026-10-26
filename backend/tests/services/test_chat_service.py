"""A person's message to a project's brain: the project's chat started in the
store, briefed, or a turn of the chat open (design 3 §5.1, §5.3; F38.3, F130;
DB assertions 159, 229, 243, 251; V02, V06, V13, V16, V25)."""

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
from app.exceptions import InvalidOperationException, RecordNotFoundException
from app.models import Block, Chat, Item, Project, ProjectTransition, Turn, User
from app.models.reference import (
    ChatKind,
    ProjectState,
    RecordKind,
    SessionState,
    TransitionKind,
    UserKind,
)
from app.services.chat_service import ChatService
from app.services.container import ServiceContainer
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
from tests.support.fake_controller import ServedFakeController, client_of
from tests.support.fake_sidecar import STORE_ENVIRONMENT_ID
from tests.support.locks import in_thread, lock_waits
from tests.support.supervisor import WAIT_SECONDS, Supervise, wait_until

MCP_URL = "https://pilot-mcp.example.com/mcp"
STORE_REPO = "/work/PilotProjects"
FOLDER = "/work/Projects/soup-club"
WORDS = "What next?"
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
        assert body["env"][0] == f"PILOT_PROJECT={FOLDER}"
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


class TestRefusals:
    @pytest.mark.parametrize(
        ("standing", "refusal"),
        [
            (
                {"state_code": ProjectState.DRAFT, "slug": None},
                "its project is a draft",
            ),
            ({"state_code": ProjectState.FINISHED}, "its project is finished"),
            ({"archived": True}, "its project is archived"),
        ],
    )
    def test_a_draft_or_a_finished_or_archived_project_takes_no_message(
        self,
        session: DbSession,
        chats: ChatService,
        fake: _Sent,
        opened: Project,
        person: User,
        standing: dict[str, Any],
        refusal: str,
    ) -> None:
        for column, value in standing.items():
            setattr(opened, column, value)
        session.flush()

        with pytest.raises(
            InvalidOperationException,
            match=f"Cannot send a message to Pilot in Soup club because {refusal}",
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


def _committed(container: ServiceContainer) -> tuple[uuid.UUID, uuid.UUID]:
    """A person and an open project, committed; their ids."""
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
        project = Project(
            created_by_user_id=person.id,
            state_code=ProjectState.OPEN,
            slug="soup-club",
            name="Soup club",
        )
        db.add(project)
        db.flush()
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
