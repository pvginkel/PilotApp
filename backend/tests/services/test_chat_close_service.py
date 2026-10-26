"""A project chat's close: at Finish and Reopen, the close's record kept last
when a turn of the chat still runs, and on the close timer's tick (F130,
F130.1, F130.2, F5.5; DB decision 57; design 2 §13; V05, V28)."""

import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flask import Flask
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.engine.bus import EngineEvent, ProjectChanged, TreeHashMoved
from app.engine.views import ViewService, utc_time
from app.models import Chat, Environment, Project, Turn, User
from app.models.reference import (
    ChatKind,
    CloseCause,
    ProjectState,
    RecordKind,
    SessionState,
    UserKind,
)
from app.services.chat_close_service import CLOSED, ChatCloseService
from app.services.container import ServiceContainer
from app.services.controller_client import (
    ControllerClient,
    ControllerUnreachable,
    HeadlessCreateRequest,
)
from app.services.session_record_service import SessionRecordService, read_records
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.fake_controller import ServedFakeController
from tests.support.fake_sidecar import STORE_ENVIRONMENT_ID
from tests.support.locks import in_thread
from tests.support.supervisor import WAIT_SECONDS, Supervise

CLOSE_AFTER = timedelta(minutes=55)


@pytest.fixture(autouse=True)
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


def _service(container: ServiceContainer, supervise: Supervise) -> ChatCloseService:
    supervisor, _ = supervise(container)
    return ChatCloseService(
        container=container,
        supervisor=supervisor,
        session_streams=container.session_stream_service(),
        close_after_seconds=CLOSE_AFTER.total_seconds(),
    )


@pytest.fixture
def closes(container: ServiceContainer, supervise: Supervise) -> ChatCloseService:
    return _service(container, supervise)


@pytest.fixture
def opened(session: DbSession, project: Project, environment: Environment) -> Project:
    """`project` open, the store's row Pilot's."""
    project.state_code = ProjectState.OPEN
    project.slug, project.name = "soup-club", "Soup club"
    session.flush()
    return project


@pytest.fixture
def store(
    fake_controller: ServedFakeController,
    controller_client: ControllerClient,
    environment: Environment,
) -> ServedFakeController:
    """The store running in the fake, its row Pilot's."""
    fake_controller.add_environment(
        STORE_ENVIRONMENT_ID, name="PilotProjects", status="running", exempt=True
    )
    return fake_controller


def _headless(client: ControllerClient) -> str:
    """An idle headless session in the store; its name."""
    return client.create_headless_session(
        STORE_ENVIRONMENT_ID, HeadlessCreateRequest()
    ).name


def _chat(
    db: DbSession,
    project: Project,
    ended: datetime,
    *,
    state: SessionState = SessionState.IDLE,
    controller_session: str | None = None,
    kind: ChatKind = ChatKind.PROJECT,
    in_flight: bool = False,
) -> models.Session:
    """A chat of the project in the store whose latest Turn ended at `ended`;
    with `in_flight`, an earlier one still in flight, as a send that failed
    after a turn the controller has leaves it."""
    run = models.Session(
        project_id=project.id,
        environment_id=STORE_ENVIRONMENT_ID,
        kind_code="chat",
        cwd="/work/PilotProjects",
        conversation_id=None if controller_session is None else "conversation-1",
        controller_session=controller_session,
        token_hash=uuid.uuid4().hex * 2,
        state_code=state,
    )
    db.add(run)
    db.flush()
    db.add(
        Chat(id=run.id, project_id=project.id, session_kind_code="chat", kind_code=kind)
    )
    started = ended - timedelta(minutes=1)
    db.add(
        Turn(
            session_id=run.id,
            seq=1,
            message="/chat",
            started_at=started,
            ended_at=None if in_flight else ended,
        )
    )
    if in_flight:
        db.add(
            Turn(
                session_id=run.id,
                seq=2,
                message="Again",
                started_at=ended,
                ended_at=ended,
                error="the send failed",
            )
        )
    run.turns = 2 if in_flight else 1
    run.turn_started_at = ended if in_flight else started
    run.turn_ended_at = ended
    db.flush()
    return run


def _chat_row(db: DbSession, run: models.Session) -> Chat:
    return db.get_one(Chat, run.id, populate_existing=True)


def _servers(db: DbSession, run_id: uuid.UUID) -> list[tuple[int | None, Any]]:
    """The Session's `server` records: each one's Turn and its payload."""
    return [
        (stored.turn, stored.record.payload)
        for stored in read_records(db, run_id, limit=1000)
        if stored.record.kind_code == RecordKind.SERVER
    ]


def _last(db: DbSession, run_id: uuid.UUID) -> Any:
    (last,) = read_records(db, run_id, limit=1, newest_first=True)
    return last.record.payload


def _end_turn(container: ServiceContainer, db: DbSession, run: models.Session) -> None:
    """The Turn in flight ended with a `result`, as the relay ends it."""
    turn = db.scalars(
        select(Turn).where(Turn.session_id == run.id, Turn.ended_at.is_(None))
    ).one()
    SessionRecordService(
        db, container.session_stream_service(), ViewService(db, container.engine_bus())
    ).append(
        run.id,
        RecordKind.RESULT,
        payload={"type": "result", "interrupted": True},
        turn_id=turn.id,
        raw_offset=10,
        controller_session="session-1",
    )
    turn.ended_at = datetime.now(UTC)
    db.flush()


def _ago(delta: timedelta) -> datetime:
    return datetime.now(UTC) - delta


class TestCloseOpen:
    def test_an_idle_chat_closes_with_its_cause_its_record_last(
        self, session: DbSession, closes: ChatCloseService, opened: Project
    ) -> None:
        run = _chat(session, opened, _ago(timedelta(minutes=2)))
        at = datetime.now(UTC)

        closes.close_open(session, opened, CloseCause.FINISHED, at)

        chat = _chat_row(session, run)
        assert (chat.closed_at, chat.close_cause_code) == (at, CloseCause.FINISHED)
        assert _servers(session, run.id) == [
            (None, {"type": CLOSED, "cause": "finished"})
        ]
        assert _last(session, run.id) == {"type": CLOSED, "cause": "finished"}
        assert run.state_code is SessionState.IDLE

    def test_the_close_is_told_to_the_browsers_and_to_chat_md(
        self,
        session: DbSession,
        container: ServiceContainer,
        closes: ChatCloseService,
        engine_events: list[EngineEvent],
        opened: Project,
    ) -> None:
        _chat(session, opened, _ago(timedelta(minutes=2)))
        clear_after_commit_callbacks()
        at = datetime.now(UTC)

        with scoped_session(container) as db:
            closes.close_open(db, opened, CloseCause.FINISHED, at)

        chat = container.view_service().chat(opened)
        assert chat.text.endswith(f"\n\nClosed {utc_time(at)}\n")
        assert engine_events == [
            TreeHashMoved("soup-club/chat.md", chat.hash),
            ProjectChanged(opened.id),
        ]

    def test_one_with_a_turn_in_flight_leaves_its_record_to_the_turns_end(
        self, session: DbSession, closes: ChatCloseService, opened: Project
    ) -> None:
        run = _chat(
            session,
            opened,
            _ago(timedelta(minutes=2)),
            state=SessionState.STOPPED,
            in_flight=True,
        )
        at = datetime.now(UTC)

        closes.close_open(session, opened, CloseCause.REOPENED, at)

        chat = _chat_row(session, run)
        assert (chat.closed_at, chat.close_cause_code) == (at, CloseCause.REOPENED)
        assert _servers(session, run.id) == []

    def test_with_no_chat_open_nothing_closes(
        self, session: DbSession, closes: ChatCloseService, opened: Project
    ) -> None:
        run = _chat(session, opened, _ago(timedelta(days=1)))
        earlier = _ago(timedelta(hours=20))
        chat = _chat_row(session, run)
        chat.closed_at, chat.close_cause_code = earlier, CloseCause.TIMEOUT
        session.flush()

        closes.close_open(session, opened, CloseCause.FINISHED, datetime.now(UTC))

        chat = _chat_row(session, run)
        assert (chat.closed_at, chat.close_cause_code) == (earlier, CloseCause.TIMEOUT)
        assert _servers(session, run.id) == []


class TestTurnEnded:
    def test_the_end_of_a_closed_chats_last_turn_writes_the_close_after_it_once(
        self,
        session: DbSession,
        container: ServiceContainer,
        closes: ChatCloseService,
        opened: Project,
    ) -> None:
        run = _chat(
            session,
            opened,
            _ago(timedelta(minutes=2)),
            state=SessionState.STOPPED,
            in_flight=True,
        )
        closes.close_open(session, opened, CloseCause.FINISHED, datetime.now(UTC))
        _end_turn(container, session, run)

        closes.turn_ended(session, run)
        closes.turn_ended(session, run)

        assert _servers(session, run.id) == [
            (None, {"type": CLOSED, "cause": "finished"})
        ]
        assert _last(session, run.id) == {"type": CLOSED, "cause": "finished"}

    def test_while_a_turn_of_it_is_in_flight_it_writes_nothing(
        self, session: DbSession, closes: ChatCloseService, opened: Project
    ) -> None:
        run = _chat(
            session,
            opened,
            _ago(timedelta(minutes=2)),
            state=SessionState.STOPPED,
            in_flight=True,
        )
        closes.close_open(session, opened, CloseCause.FINISHED, datetime.now(UTC))

        closes.turn_ended(session, run)

        assert _servers(session, run.id) == []

    def test_an_open_chat_and_a_work_item_get_no_close(
        self,
        session: DbSession,
        closes: ChatCloseService,
        opened: Project,
        project_session: models.Session,
    ) -> None:
        run = _chat(session, opened, _ago(timedelta(minutes=2)))

        closes.turn_ended(session, run)
        closes.turn_ended(session, project_session)

        assert _servers(session, run.id) == []
        assert _servers(session, project_session.id) == []


class TestCloseTimer:
    def test_an_idle_chat_past_the_timeout_closes_its_controller_session_ended(
        self,
        session: DbSession,
        closes: ChatCloseService,
        store: ServedFakeController,
        controller_client: ControllerClient,
        opened: Project,
    ) -> None:
        name = _headless(controller_client)
        run = _chat(
            session,
            opened,
            _ago(CLOSE_AFTER + timedelta(seconds=5)),
            controller_session=name,
        )
        before = datetime.now(UTC)

        closes.run_close_timer(session)

        chat = _chat_row(session, run)
        assert chat.close_cause_code is CloseCause.TIMEOUT
        assert chat.closed_at is not None
        assert before <= chat.closed_at <= datetime.now(UTC)
        assert _last(session, run.id) == {"type": CLOSED, "cause": "timeout"}
        assert (run.state_code, run.current_line, run.controller_session) == (
            SessionState.ENDED,
            None,
            name,
        )
        assert store.sessions(STORE_ENVIRONMENT_ID) == []

    def test_a_chat_short_of_the_timeout_stays_open(
        self,
        session: DbSession,
        closes: ChatCloseService,
        store: ServedFakeController,
        controller_client: ControllerClient,
        opened: Project,
    ) -> None:
        name = _headless(controller_client)
        run = _chat(
            session,
            opened,
            _ago(CLOSE_AFTER - timedelta(minutes=1)),
            controller_session=name,
        )

        closes.run_close_timer(session)

        assert _chat_row(session, run).closed_at is None
        assert run.state_code is SessionState.IDLE
        assert [s.name for s in store.sessions(STORE_ENVIRONMENT_ID)] == [name]

    def test_a_chat_with_a_turn_in_flight_stays_open(
        self,
        session: DbSession,
        closes: ChatCloseService,
        store: ServedFakeController,
        controller_client: ControllerClient,
        opened: Project,
    ) -> None:
        run = _chat(
            session,
            opened,
            _ago(CLOSE_AFTER * 2),
            state=SessionState.RUNNING,
            controller_session=_headless(controller_client),
            in_flight=True,
        )

        closes.run_close_timer(session)

        assert _chat_row(session, run).closed_at is None
        assert _servers(session, run.id) == []

    def test_the_definition_chat_never_closes_by_timeout(
        self,
        session: DbSession,
        closes: ChatCloseService,
        store: ServedFakeController,
        controller_client: ControllerClient,
        project: Project,
    ) -> None:
        run = _chat(
            session,
            project,
            _ago(CLOSE_AFTER * 10),
            controller_session=_headless(controller_client),
            kind=ChatKind.DEFINITION,
        )

        closes.run_close_timer(session)

        assert _chat_row(session, run).closed_at is None

    @pytest.mark.parametrize("gone", ["stopped", "removed"])
    def test_a_chat_whose_store_runs_no_session_closes_with_nothing_to_end(
        self,
        session: DbSession,
        closes: ChatCloseService,
        store: ServedFakeController,
        controller_client: ControllerClient,
        opened: Project,
        gone: str,
    ) -> None:
        run = _chat(
            session,
            opened,
            _ago(CLOSE_AFTER * 2),
            controller_session=_headless(controller_client),
        )
        if gone == "stopped":
            store.set_status(STORE_ENVIRONMENT_ID, "stopped")
        else:
            store.remove_environment(STORE_ENVIRONMENT_ID)

        closes.run_close_timer(session)

        assert _chat_row(session, run).close_cause_code is CloseCause.TIMEOUT
        assert run.state_code is SessionState.ENDED

    def test_a_controller_that_does_not_answer_leaves_the_chat_open(
        self,
        session: DbSession,
        closes: ChatCloseService,
        store: ServedFakeController,
        controller_client: ControllerClient,
        opened: Project,
    ) -> None:
        run = _chat(
            session,
            opened,
            _ago(CLOSE_AFTER * 2),
            controller_session=_headless(controller_client),
        )
        store.outage()

        with pytest.raises(ControllerUnreachable):
            closes.run_close_timer(session)

        assert _chat_row(session, run).closed_at is None

    def test_a_chat_with_no_controller_session_closes_keeping_its_state(
        self,
        session: DbSession,
        closes: ChatCloseService,
        store: ServedFakeController,
        opened: Project,
    ) -> None:
        run = _chat(session, opened, _ago(CLOSE_AFTER * 2), state=SessionState.FAILED)

        closes.run_close_timer(session)

        assert _chat_row(session, run).close_cause_code is CloseCause.TIMEOUT
        assert run.state_code is SessionState.FAILED
        assert _last(session, run.id) == {"type": CLOSED, "cause": "timeout"}
        assert store.calls == []

    def test_a_closed_chat_is_left_as_it_closed(
        self,
        session: DbSession,
        closes: ChatCloseService,
        store: ServedFakeController,
        opened: Project,
    ) -> None:
        run = _chat(session, opened, _ago(CLOSE_AFTER * 2))
        closes.close_open(session, opened, CloseCause.FINISHED, _ago(CLOSE_AFTER))

        closes.run_close_timer(session)

        assert _chat_row(session, run).close_cause_code is CloseCause.FINISHED
        assert len(_servers(session, run.id)) == 1
        assert run.state_code is SessionState.IDLE


def _committed_chat(container: ServiceContainer, ended: datetime) -> uuid.UUID:
    """An open project's idle chat, its turn ended at `ended`, committed; its
    id."""
    with scoped_session(container) as db:
        person = User(
            kind_code=UserKind.PERSON,
            subject="subject-ada",
            handle="ada",
            name="Ada Example",
            avatar_slot=1,
        )
        db.add(person)
        db.add(Environment(id=STORE_ENVIRONMENT_ID, name="Example-1", exempt=True))
        db.flush()
        project = Project(
            created_by_user_id=person.id,
            state_code=ProjectState.OPEN,
            slug="soup-club",
            name="Soup club",
        )
        db.add(project)
        db.flush()
        return _chat(db, project, ended).id


class TestCloseTimerLocks:
    def test_a_chat_whose_session_another_transaction_holds_is_skipped(
        self, committed_app: Flask, supervise: Supervise
    ) -> None:
        container = committed_app.container
        chat_id = _committed_chat(container, _ago(CLOSE_AFTER * 2))
        closes = _service(container, supervise)
        held, release = threading.Event(), threading.Event()

        def hold() -> None:
            with scoped_session(container) as db:
                db.get_one(models.Session, chat_id, with_for_update=True)
                held.set()
                assert release.wait(WAIT_SECONDS)

        holder = in_thread(hold)
        assert held.wait(WAIT_SECONDS)
        try:
            with scoped_session(container) as db:
                closes.run_close_timer(db)
            with scoped_session(container) as db:
                assert db.get_one(Chat, chat_id).closed_at is None
        finally:
            release.set()
        holder.result()

        with scoped_session(container) as db:
            closes.run_close_timer(db)
        with scoped_session(container) as db:
            assert db.get_one(Chat, chat_id).close_cause_code is CloseCause.TIMEOUT
