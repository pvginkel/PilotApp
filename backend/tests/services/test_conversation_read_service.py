"""A caller's conversations as it reads them: the one a call names, answered
to its opener alone, and the list its environment opened (F150.10, F150.11;
DB Conversation, assertion 337; V04)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session as DbSession

from app import models
from app.exceptions import RecordNotFoundException
from app.models import Conversation, Environment, Project, Turn, User
from app.models.reference import CloseCause, ProjectState, SessionState, UserKind
from app.services.container import ServiceContainer
from app.services.conversation_read_service import (
    ConversationReadService,
    ListedConversation,
)
from tests.support.chats import close_conversation, open_conversation

OPENED = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


@pytest.fixture
def reads(container: ServiceContainer) -> ConversationReadService:
    return container.conversation_read_service()


@pytest.fixture
def recipebox(session: DbSession) -> Environment:
    """The environment the caller calls from."""
    caller = Environment(
        id="example-recipebox-1a2b3c", name="RecipeBox-2", exempt=False
    )
    session.add(caller)
    session.flush()
    return caller


@pytest.fixture
def automation(session: DbSession) -> Environment:
    """Another environment sessions call from."""
    other = Environment(id="example-automation-9f8e7d", name="Automation", exempt=False)
    session.add(other)
    session.flush()
    return other


@pytest.fixture
def other_service_user(session: DbSession) -> User:
    """A second service user, another client's."""
    user = User(
        kind_code=UserKind.SERVICE,
        subject="subject-harvest",
        handle="harvest",
        name="Harvest",
    )
    session.add(user)
    session.flush()
    return user


@pytest.fixture
def opened(session: DbSession, project: Project) -> Project:
    project.state_code = ProjectState.OPEN
    project.slug, project.name = "soup-club", "Soup club"
    session.flush()
    return project


@pytest.fixture
def bikes(session: DbSession, person: User) -> Project:
    """A second open project."""
    other = Project(
        created_by_user_id=person.id,
        state_code=ProjectState.OPEN,
        slug="bike-log",
        name="Bike log",
    )
    session.add(other)
    session.flush()
    return other


def _ids(listed: list[ListedConversation]) -> list[uuid.UUID]:
    return [entry.conversation.id for entry in listed]


class TestOwned:
    def test_its_opener_reads_it_as_it_stands(
        self,
        session: DbSession,
        reads: ConversationReadService,
        opened: Project,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        run = open_conversation(
            session,
            opened,
            recipebox,
            caller_session="ui-sweep-triage",
            opened_at=OPENED,
            opener=service_user,
        )

        listed = reads.owned(run.id, service_user, recipebox.id)

        assert listed == ListedConversation(
            conversation=session.get_one(Conversation, run.id),
            opened_at=OPENED,
            turns=1,
            in_flight=False,
        )
        assert (
            listed.conversation.project_id,
            listed.conversation.caller_environment_id,
            listed.conversation.caller_session,
            listed.conversation.closed_at,
        ) == (opened.id, recipebox.id, "ui-sweep-triage", None)

    def test_a_later_session_of_its_environment_reads_it_whatever_session_opened_it(
        self,
        session: DbSession,
        reads: ConversationReadService,
        opened: Project,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        """The session's name is kept and never checked: the read takes
        none."""
        run = open_conversation(
            session, opened, recipebox, caller_session="monday", opener=service_user
        )

        assert reads.owned(run.id, service_user, recipebox.id).conversation.id == run.id

    def test_a_closed_one_is_read_with_its_cause(
        self,
        session: DbSession,
        reads: ConversationReadService,
        opened: Project,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        run = open_conversation(session, opened, recipebox, opener=service_user)
        closed_at = OPENED + timedelta(minutes=30)
        close_conversation(session, run, closed_at, CloseCause.ENDED)

        listed = reads.owned(run.id, service_user, recipebox.id)

        assert (
            listed.conversation.closed_at,
            listed.conversation.close_cause_code,
            listed.in_flight,
        ) == (closed_at, CloseCause.ENDED, False)

    def test_one_started_afresh_is_still_its_first_turns_authors(
        self,
        session: DbSession,
        reads: ConversationReadService,
        opened: Project,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        run = open_conversation(session, opened, recipebox, opener=service_user)
        now = datetime.now(UTC)
        session.add(Turn(session_id=run.id, seq=2, message="Go on.", started_at=now))
        run.turns = 2
        session.flush()

        assert reads.owned(run.id, service_user, recipebox.id).turns == 2

    def test_another_environments_call_is_answered_as_an_id_that_never_was(
        self,
        session: DbSession,
        reads: ConversationReadService,
        opened: Project,
        recipebox: Environment,
        automation: Environment,
        service_user: User,
    ) -> None:
        run = open_conversation(session, opened, recipebox, opener=service_user)
        never = uuid.uuid4()

        with pytest.raises(RecordNotFoundException) as anothers:
            reads.owned(run.id, service_user, automation.id)
        with pytest.raises(RecordNotFoundException) as unknown:
            reads.owned(never, service_user, recipebox.id)

        assert anothers.value.message == f"Conversation {run.id} was not found"
        assert unknown.value.message == f"Conversation {never} was not found"
        assert (type(anothers.value), anothers.value.error_code) == (
            type(unknown.value),
            unknown.value.error_code,
        )

    def test_another_users_call_from_its_environment_is_answered_the_same(
        self,
        session: DbSession,
        reads: ConversationReadService,
        opened: Project,
        recipebox: Environment,
        service_user: User,
        other_service_user: User,
    ) -> None:
        run = open_conversation(session, opened, recipebox, opener=service_user)

        with pytest.raises(RecordNotFoundException) as raised:
            reads.owned(run.id, other_service_user, recipebox.id)

        assert raised.value.message == f"Conversation {run.id} was not found"

    def test_a_call_that_names_no_environment_owns_none(
        self,
        session: DbSession,
        reads: ConversationReadService,
        opened: Project,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        run = open_conversation(session, opened, recipebox, opener=service_user)

        with pytest.raises(RecordNotFoundException) as raised:
            reads.owned(run.id, service_user, None)

        assert raised.value.message == f"Conversation {run.id} was not found"

    def test_a_chat_is_no_conversation(
        self,
        session: DbSession,
        reads: ConversationReadService,
        project_session: models.Session,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        with pytest.raises(RecordNotFoundException):
            reads.owned(project_session.id, service_user, recipebox.id)

    @pytest.mark.parametrize(
        ("state", "turn_ended", "in_flight"),
        [
            (SessionState.HELD, False, True),
            (SessionState.STARTING, False, True),
            (SessionState.RUNNING, False, True),
            (SessionState.STOPPED, False, True),
            (SessionState.STOPPED, True, False),
            (SessionState.IDLE, True, False),
            (SessionState.FAILED, False, False),
        ],
    )
    def test_a_turn_is_in_flight_while_it_takes_no_message(
        self,
        session: DbSession,
        reads: ConversationReadService,
        opened: Project,
        recipebox: Environment,
        service_user: User,
        state: SessionState,
        turn_ended: bool,
        in_flight: bool,
    ) -> None:
        run = open_conversation(
            session, opened, recipebox, state=state, opener=service_user
        )
        run.turn_started_at = OPENED
        run.turn_ended_at = OPENED if turn_ended else None
        session.flush()

        assert reads.owned(run.id, service_user, recipebox.id).in_flight is in_flight


class TestOpened:
    def test_it_lists_its_environments_open_and_closed_in_the_order_they_opened(
        self,
        session: DbSession,
        reads: ConversationReadService,
        opened: Project,
        bikes: Project,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        second = open_conversation(
            session,
            bikes,
            recipebox,
            caller_session="tuesday",
            opened_at=OPENED + timedelta(hours=1),
            opener=service_user,
        )
        first = open_conversation(
            session,
            opened,
            recipebox,
            caller_session="monday",
            opened_at=OPENED,
            opener=service_user,
        )
        close_conversation(
            session, first, OPENED + timedelta(minutes=5), CloseCause.TIMEOUT
        )
        third = open_conversation(
            session,
            opened,
            recipebox,
            opened_at=OPENED + timedelta(hours=2),
            state=SessionState.RUNNING,
            opener=service_user,
        )

        listed = reads.opened(service_user, recipebox.id)

        assert _ids(listed) == [first.id, second.id, third.id]
        assert [
            (
                entry.conversation.caller_session,
                entry.opened_at,
                entry.conversation.close_cause_code,
                entry.in_flight,
            )
            for entry in listed
        ] == [
            ("monday", OPENED, CloseCause.TIMEOUT, False),
            ("tuesday", OPENED + timedelta(hours=1), None, False),
            (None, OPENED + timedelta(hours=2), None, True),
        ]

    def test_with_a_project_it_lists_that_projects_alone(
        self,
        session: DbSession,
        reads: ConversationReadService,
        opened: Project,
        bikes: Project,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        soup = open_conversation(session, opened, recipebox, opener=service_user)
        open_conversation(session, bikes, recipebox, opener=service_user)

        assert _ids(reads.opened(service_user, recipebox.id, opened.id)) == [soup.id]

    def test_no_other_environments_and_no_other_users_is_listed(
        self,
        session: DbSession,
        reads: ConversationReadService,
        opened: Project,
        recipebox: Environment,
        automation: Environment,
        service_user: User,
        other_service_user: User,
    ) -> None:
        mine = open_conversation(session, opened, recipebox, opener=service_user)
        theirs = open_conversation(session, opened, automation, opener=service_user)
        open_conversation(session, opened, recipebox, opener=other_service_user)

        assert _ids(reads.opened(service_user, recipebox.id)) == [mine.id]
        assert _ids(reads.opened(service_user, automation.id)) == [theirs.id]

    def test_a_call_that_names_no_environment_lists_none(
        self,
        session: DbSession,
        reads: ConversationReadService,
        opened: Project,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        open_conversation(session, opened, recipebox, opener=service_user)

        assert reads.opened(service_user, None) == []

    def test_an_environment_that_opened_none_lists_none(
        self, reads: ConversationReadService, service_user: User
    ) -> None:
        assert reads.opened(service_user, "example-nowhere-000000") == []
