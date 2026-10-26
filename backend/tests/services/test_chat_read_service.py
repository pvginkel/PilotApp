"""A project's chats as a person reads them, whether Pilot is answering in
one, and their place in them (F40.3, F43, F44; DB Chat, Chat Read, decision
13, assertion 158; V07, V09)."""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.exceptions import RecordNotFoundException
from app.models import ChatRead, Project, User
from app.models.reference import ChatKind, CloseCause, SessionState, UserKind
from app.services.chat_read_service import ChatReadService, ReadPlace, answering
from app.services.container import ServiceContainer
from tests.support.chats import ChatWriter, close_chat, open_chat


@pytest.fixture
def reads(container: ServiceContainer) -> ChatReadService:
    return container.chat_read_service()


@pytest.fixture
def other(session: DbSession) -> User:
    """A second person."""
    user = User(
        kind_code=UserKind.PERSON,
        subject="subject-bea",
        handle="bea",
        name="Bea Example",
        avatar_slot=2,
    )
    session.add(user)
    session.flush()
    return user


def _now(db: DbSession) -> datetime:
    """The database's now: the test's transaction's start, every record's
    `at`."""
    now: datetime = db.scalar(select(func.now()))
    return now


def _writer(
    session: DbSession, container: ServiceContainer, project: Project
) -> ChatWriter:
    return ChatWriter(
        session, container.session_record_service(), open_chat(session, project)
    )


def _read_at(db: DbSession, person: User, project: Project, at: datetime) -> None:
    db.add(ChatRead(user_id=person.id, project_id=project.id, read_at=at))
    db.flush()


def _replied(
    session: DbSession, container: ServiceContainer, project: Project, person: User
) -> ChatWriter:
    """A chat of the project in which Pilot replied to `person`."""
    chat = _writer(session, container, project)
    chat.message(person, "What next?")
    chat.text("Two things.")
    return chat


class TestChats:
    def test_a_project_with_no_chat_lists_none_with_nothing_unread(
        self, reads: ChatReadService, project: Project, person: User
    ) -> None:
        listed = reads.chats(project.id, person)

        assert (listed.chats, listed.place) == ([], ReadPlace(None, False))

    def test_the_definition_chat_comes_first_then_the_chats_as_they_opened(
        self, session: DbSession, reads: ChatReadService, project: Project
    ) -> None:
        opened = datetime.fromisoformat("2026-10-12T09:00:00+00:00")
        first = open_chat(session, project, opened_at=opened)
        closed = opened + timedelta(hours=1)
        close_chat(session, first, closed, CloseCause.TIMEOUT)
        definition = open_chat(
            session,
            project,
            kind=ChatKind.DEFINITION,
            opened_at=opened + timedelta(hours=2),
        )
        close_chat(session, definition, closed, CloseCause.CREATED)
        latest = open_chat(session, project, opened_at=opened + timedelta(hours=3))

        listed = reads.chats(project.id, None).chats

        assert [
            (
                entry.chat.id,
                entry.chat.kind_code,
                entry.opened_at,
                entry.chat.closed_at,
                entry.chat.close_cause_code,
            )
            for entry in listed
        ] == [
            (
                definition.id,
                ChatKind.DEFINITION,
                opened + timedelta(hours=2),
                closed,
                CloseCause.CREATED,
            ),
            (first.id, ChatKind.PROJECT, opened, closed, CloseCause.TIMEOUT),
            (latest.id, ChatKind.PROJECT, opened + timedelta(hours=3), None, None),
        ]

    def test_another_projects_chats_are_not_listed(
        self,
        session: DbSession,
        reads: ChatReadService,
        project: Project,
        person: User,
    ) -> None:
        another = Project(created_by_user_id=person.id)
        session.add(another)
        session.flush()
        open_chat(session, another)

        assert reads.chats(project.id, person).chats == []

    def test_a_reply_never_read_is_unread(
        self,
        session: DbSession,
        container: ServiceContainer,
        reads: ChatReadService,
        project: Project,
        person: User,
    ) -> None:
        _replied(session, container, project, person)

        assert reads.chats(project.id, person).place == ReadPlace(None, True)

    def test_a_read_after_the_latest_reply_has_nothing_unread(
        self,
        session: DbSession,
        container: ServiceContainer,
        reads: ChatReadService,
        project: Project,
        person: User,
    ) -> None:
        _replied(session, container, project, person)
        read = _now(session) + timedelta(seconds=1)
        _read_at(session, person, project, read)

        assert reads.chats(project.id, person).place == ReadPlace(read, False)

    def test_a_reply_after_the_read_is_unread(
        self,
        session: DbSession,
        container: ServiceContainer,
        reads: ChatReadService,
        project: Project,
        person: User,
    ) -> None:
        _replied(session, container, project, person)
        read = _now(session) - timedelta(seconds=1)
        _read_at(session, person, project, read)

        assert reads.chats(project.id, person).place == ReadPlace(read, True)

    def test_only_pilots_main_thread_text_is_a_reply(
        self,
        session: DbSession,
        container: ServiceContainer,
        reads: ChatReadService,
        project: Project,
        person: User,
    ) -> None:
        chat = _writer(session, container, project)
        chat.message(person, "What next?")
        chat.assistant([{"type": "thinking", "thinking": "Hm."}])
        chat.call("toolu_1")
        chat.text("A sub-agent's words.", parent="toolu_1")
        chat.effect("toolu_1", "Answered", "D1 · Which stock?")

        assert reads.chats(project.id, person).place == ReadPlace(None, False)

    def test_with_no_reply_in_the_newest_chat_the_one_before_answers(
        self,
        session: DbSession,
        container: ServiceContainer,
        reads: ChatReadService,
        project: Project,
        person: User,
    ) -> None:
        earlier = _replied(session, container, project, person)
        close_chat(session, earlier.run, _now(session), CloseCause.TIMEOUT)
        _writer(session, container, project).message(person, "And now?")

        assert reads.chats(project.id, person).place == ReadPlace(None, True)

    def test_a_reply_further_back_than_a_page_is_found(
        self,
        session: DbSession,
        container: ServiceContainer,
        reads: ChatReadService,
        project: Project,
        person: User,
    ) -> None:
        chat = _replied(session, container, project, person)
        for n in range(40):
            chat.call(f"toolu_{n}", "Read")

        assert reads.chats(project.id, person).place == ReadPlace(None, True)

    def test_another_persons_read_is_not_the_readers(
        self,
        session: DbSession,
        container: ServiceContainer,
        reads: ChatReadService,
        project: Project,
        person: User,
        other: User,
    ) -> None:
        _replied(session, container, project, person)
        _read_at(session, other, project, _now(session) + timedelta(seconds=1))

        assert reads.chats(project.id, person).place == ReadPlace(None, True)

    def test_a_caller_who_is_no_person_yet_has_no_place(
        self,
        session: DbSession,
        container: ServiceContainer,
        reads: ChatReadService,
        project: Project,
        person: User,
    ) -> None:
        _replied(session, container, project, person)

        assert reads.chats(project.id, None).place == ReadPlace(None, True)

    def test_an_unknown_project_is_refused(self, reads: ChatReadService) -> None:
        with pytest.raises(RecordNotFoundException):
            reads.chats(uuid.uuid4(), None)


class TestAnswering:
    """Whether Pilot is answering in a chat: its Session in a state the
    chat's Stop ends (F44)."""

    @pytest.mark.parametrize("state", list(SessionState))
    def test_pilot_answers_while_the_start_is_held_or_under_way_or_a_turn_runs(
        self,
        session: DbSession,
        reads: ChatReadService,
        project: Project,
        state: SessionState,
    ) -> None:
        run = open_chat(session, project)
        run.state_code = state
        session.flush()

        (listed,) = reads.chats(project.id, None).chats

        assert listed.state is state
        assert answering(listed) is (
            state in (SessionState.HELD, SessionState.STARTING, SessionState.RUNNING)
        )


class TestRead:
    def test_it_writes_the_persons_place_now(
        self,
        session: DbSession,
        reads: ChatReadService,
        project: Project,
        person: User,
    ) -> None:
        place = reads.read(project.id, person)

        now = _now(session)
        assert place == ReadPlace(now, False)
        assert session.scalars(select(ChatRead)).all() == [
            session.get_one(ChatRead, (person.id, project.id))
        ]
        assert session.get_one(ChatRead, (person.id, project.id)).read_at == now

    def test_a_reply_written_before_it_is_read(
        self,
        session: DbSession,
        container: ServiceContainer,
        reads: ChatReadService,
        project: Project,
        person: User,
    ) -> None:
        _replied(session, container, project, person)

        assert reads.read(project.id, person) == ReadPlace(_now(session), False)

    def test_a_read_overwrites_the_last_one_per_person_and_project(
        self,
        session: DbSession,
        container: ServiceContainer,
        reads: ChatReadService,
        project: Project,
        person: User,
        other: User,
    ) -> None:
        earlier = _now(session) - timedelta(days=1)
        _read_at(session, person, project, earlier)
        _read_at(session, other, project, earlier)

        reads.read(project.id, person)

        assert {
            (row.user_id, row.read_at)
            for row in session.scalars(
                select(ChatRead).execution_options(populate_existing=True)
            )
        } == {(person.id, _now(session)), (other.id, earlier)}

    def test_an_unknown_project_is_refused(
        self, reads: ChatReadService, person: User
    ) -> None:
        with pytest.raises(RecordNotFoundException):
            reads.read(uuid.uuid4(), person)
