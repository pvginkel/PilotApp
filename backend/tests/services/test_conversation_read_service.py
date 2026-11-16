"""A caller's conversations as it reads them: the one a call names, answered
to its opener alone, the list its environment opened, and Pilot's reply to
its latest message as it stands (F150.10, F150.11; DB Conversation,
assertion 337; V01, V04)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session as DbSession

from app import models
from app.exceptions import RecordNotFoundException
from app.models import Conversation, Environment, Project, Turn, User
from app.models.reference import (
    CloseCause,
    ProjectState,
    RecordKind,
    SessionState,
    UserKind,
)
from app.services.container import ServiceContainer
from app.services.conversation_read_service import (
    ConversationReadService,
    ListedConversation,
    Reply,
)
from app.services.relay_service import SEND_FAILED, STOPPED_UNSENT
from app.services.session_start_service import START_FAILED
from tests.support.chats import ChatWriter, close_conversation, open_conversation

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


STOCK = "How is the stock going?"


@pytest.fixture
def talk(
    session: DbSession,
    container: ServiceContainer,
    opened: Project,
    recipebox: Environment,
    service_user: User,
) -> ChatWriter:
    """A conversation the service user opened from RecipeBox, its first
    message's Turn in flight."""
    run = open_conversation(session, opened, recipebox, state=SessionState.RUNNING)
    writer = ChatWriter(session, container.session_record_service(), run)
    writer.message(service_user, STOCK)
    return writer


class TestReply:
    """Pilot's reply to the caller's latest message, as `get_response`
    answers it (F150.10; V01)."""

    def test_a_turn_in_flight_is_running_with_the_texts_so_far(
        self,
        reads: ConversationReadService,
        talk: ChatWriter,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        talk.text("Reading the plan.")
        talk.call("toolu_1", "Read")
        talk.text("It simmers.")

        reply = reads.reply(talk.run.id, service_user, recipebox.id)

        assert reply == Reply(
            None, "running", "Reading the plan.\n\n---\n\nIt simmers."
        )

    def test_a_turn_in_flight_that_wrote_nothing_yet_has_no_text(
        self,
        reads: ConversationReadService,
        talk: ChatWriter,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        assert reads.reply(talk.run.id, service_user, recipebox.id) == Reply(
            None, "running", None
        )

    @pytest.mark.parametrize(
        "state", [SessionState.HELD, SessionState.STARTING], ids=["held", "starting"]
    )
    def test_a_start_held_or_under_way_is_running(
        self,
        session: DbSession,
        reads: ConversationReadService,
        talk: ChatWriter,
        recipebox: Environment,
        service_user: User,
        state: SessionState,
    ) -> None:
        talk.run.state_code = state
        session.flush()

        assert reads.reply(talk.run.id, service_user, recipebox.id) == Reply(
            None, "running", None
        )

    def test_an_ended_turn_is_done_with_its_number_and_every_text_in_order(
        self,
        reads: ConversationReadService,
        talk: ChatWriter,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        talk.text("Reading the plan.", "Two tasks are done.")
        talk.text("A sub-agent's aside.", parent="toolu_1")
        talk.text("It simmers.")
        talk.result("It simmers.")

        reply = reads.reply(talk.run.id, service_user, recipebox.id)

        assert reply == Reply(
            1,
            "done",
            "Reading the plan.\n\n---\n\nTwo tasks are done.\n\n---\n\nIt simmers.",
        )

    def test_an_ended_turn_that_wrote_nothing_has_no_text(
        self,
        reads: ConversationReadService,
        talk: ChatWriter,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        talk.call("toolu_1", "Read")
        talk.result("")

        assert reads.reply(talk.run.id, service_user, recipebox.id) == Reply(
            1, "done", None
        )

    def test_it_is_the_latest_messages_alone(
        self,
        reads: ConversationReadService,
        talk: ChatWriter,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        talk.text("It simmers.")
        talk.result("It simmers.")
        talk.message(service_user, "And the bread?")
        talk.run.state_code = SessionState.RUNNING

        running = reads.reply(talk.run.id, service_user, recipebox.id)
        talk.text("Proving.")
        talk.result("Proving.")
        done = reads.reply(talk.run.id, service_user, recipebox.id)

        assert running == Reply(None, "running", None)
        assert done == Reply(2, "done", "Proving.")

    def test_the_servers_turn_after_the_message_is_of_its_reply(
        self,
        reads: ConversationReadService,
        talk: ChatWriter,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        """The follow-up of a save still held (F79) runs after the caller's
        turn, and the caller's next message is refused under it."""
        talk.text("Saving the plan.")
        talk.result("Saving the plan.")
        talk.server_turn("Your save of plan.md is still held.")
        talk.run.state_code = SessionState.RUNNING

        running = reads.reply(talk.run.id, service_user, recipebox.id)
        talk.text("Saved.")
        talk.result("Saved.")
        done = reads.reply(talk.run.id, service_user, recipebox.id)

        assert running == Reply(None, "running", "Saving the plan.")
        assert done == Reply(1, "done", "Saving the plan.\n\n---\n\nSaved.")

    def test_a_turn_that_ended_in_error_is_an_error_ending_with_why(
        self,
        reads: ConversationReadService,
        talk: ChatWriter,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        talk.text("Reading the plan.")
        talk.result("The model is overloaded", error=True)

        reply = reads.reply(talk.run.id, service_user, recipebox.id)

        assert reply == Reply(
            1, "error", "Reading the plan.\n\n---\n\nThe model is overloaded"
        )

    def test_an_error_pilots_last_text_says_is_not_said_twice(
        self,
        reads: ConversationReadService,
        talk: ChatWriter,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        talk.text("Reading the plan.")
        talk.text("The model is overloaded")
        talk.result("The model is overloaded", error=True)

        reply = reads.reply(talk.run.id, service_user, recipebox.id)

        assert reply == Reply(
            1, "error", "Reading the plan.\n\n---\n\nThe model is overloaded"
        )

    def test_an_error_before_the_servers_turn_after_it_stays_the_replys(
        self,
        reads: ConversationReadService,
        talk: ChatWriter,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        talk.result("The model is overloaded", error=True)
        talk.server_turn("Your save of plan.md is still held.")
        talk.text("Saved.")
        talk.result("Saved.")

        reply = reads.reply(talk.run.id, service_user, recipebox.id)

        assert reply == Reply(1, "error", "Saved.\n\n---\n\nThe model is overloaded")

    def test_a_message_the_controller_failed_is_an_error_with_its_reason(
        self,
        session: DbSession,
        reads: ConversationReadService,
        talk: ChatWriter,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        talk.text("It simmers.")
        talk.result("It simmers.")
        talk.message(service_user, "And the bread?")
        reason = "Cannot send a message because the controller answered 502"
        assert talk.turn is not None
        talk.records.append(
            talk.run.id,
            RecordKind.SERVER,
            payload={"type": SEND_FAILED, "reason": reason},
            turn_id=talk.turn.id,
        )
        talk.turn.ended_at, talk.turn.error = datetime.now(UTC), reason
        talk.run.turn_ended_at = talk.turn.ended_at
        session.flush()

        assert reads.reply(talk.run.id, service_user, recipebox.id) == Reply(
            2, "error", reason
        )

    def test_a_start_that_failed_is_an_error_with_its_reason_closed_or_not(
        self,
        session: DbSession,
        reads: ConversationReadService,
        talk: ChatWriter,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        """A failed start's reason is its Session's and its `start-failed`
        record's, and no Turn's."""
        reason = "the store environment did not start"
        assert talk.turn is not None
        talk.records.append(
            talk.run.id,
            RecordKind.SERVER,
            payload={"type": START_FAILED, "reason": reason},
        )
        talk.turn.ended_at = datetime.now(UTC)
        talk.run.turn_ended_at = talk.turn.ended_at
        talk.run.state_code, talk.run.error = SessionState.FAILED, reason
        session.flush()

        failed = reads.reply(talk.run.id, service_user, recipebox.id)
        close_conversation(session, talk.run, datetime.now(UTC), CloseCause.ENDED)
        talk.run.state_code = SessionState.ENDED
        talk.records.append(
            talk.run.id, RecordKind.SERVER, payload={"type": "closed", "cause": "ended"}
        )
        closed = reads.reply(talk.run.id, service_user, recipebox.id)

        assert failed == closed == Reply(1, "error", reason)

    def test_a_start_that_failed_before_a_later_message_is_not_that_messages(
        self,
        session: DbSession,
        reads: ConversationReadService,
        talk: ChatWriter,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        talk.records.append(
            talk.run.id,
            RecordKind.SERVER,
            payload={"type": START_FAILED, "reason": "the controller is away"},
        )
        talk.message(service_user, "Are you there?")
        talk.text("Here.")
        talk.result("Here.")

        assert reads.reply(talk.run.id, service_user, recipebox.id) == Reply(
            2, "done", "Here."
        )

    def test_a_stopped_turn_is_running_until_it_has_ended_then_interrupted(
        self,
        session: DbSession,
        reads: ConversationReadService,
        talk: ChatWriter,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        talk.text("Reading the plan.")
        talk.run.state_code = SessionState.STOPPED
        session.flush()

        ending = reads.reply(talk.run.id, service_user, recipebox.id)
        talk.result(stopped=True)
        ended = reads.reply(talk.run.id, service_user, recipebox.id)

        assert ending == Reply(None, "running", "Reading the plan.")
        assert ended == Reply(1, "interrupted", "Reading the plan.")

    def test_a_start_stopped_unsent_is_interrupted_with_no_text(
        self,
        session: DbSession,
        reads: ConversationReadService,
        talk: ChatWriter,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        assert talk.turn is not None
        talk.records.append(
            talk.run.id,
            RecordKind.SERVER,
            payload={"type": STOPPED_UNSENT},
            turn_id=talk.turn.id,
        )
        talk.turn.ended_at = datetime.now(UTC)
        talk.run.turn_ended_at = talk.turn.ended_at
        talk.run.state_code = SessionState.STOPPED
        session.flush()

        assert reads.reply(talk.run.id, service_user, recipebox.id) == Reply(
            1, "interrupted", None
        )

    def test_a_turn_whose_result_an_earlier_one_holds_alone_is_interrupted(
        self,
        session: DbSession,
        reads: ConversationReadService,
        talk: ChatWriter,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        """The server's turn after the message ended with no result, its
        environment stopped under it: the caller's own turn's result does
        not end the reply `done`."""
        talk.text("Saving the plan.")
        talk.result("Saving the plan.")
        talk.server_turn("Your save of plan.md is still held.")
        assert talk.turn is not None
        talk.turn.ended_at = datetime.now(UTC)
        talk.run.turn_ended_at = talk.turn.ended_at
        talk.run.state_code = SessionState.STOPPED
        session.flush()

        assert reads.reply(talk.run.id, service_user, recipebox.id) == Reply(
            1, "interrupted", "Saving the plan."
        )

    def test_a_turn_not_ended_is_running_whatever_its_sessions_row_reads(
        self,
        session: DbSession,
        reads: ConversationReadService,
        talk: ChatWriter,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        """A message sent between the read of the Session and the read of
        its Turns: the Session read idle, the Turn in flight."""
        talk.run.state_code = SessionState.IDLE
        session.flush()

        assert reads.reply(talk.run.id, service_user, recipebox.id) == Reply(
            None, "running", None
        )

    def test_a_closed_conversation_answers_its_last_reply(
        self,
        session: DbSession,
        reads: ConversationReadService,
        talk: ChatWriter,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        talk.text("It simmers.")
        talk.result("It simmers.")
        close_conversation(session, talk.run, datetime.now(UTC), CloseCause.TIMEOUT)
        talk.run.state_code = SessionState.ENDED
        talk.records.append(
            talk.run.id,
            RecordKind.SERVER,
            payload={"type": "closed", "cause": "timeout"},
        )

        assert reads.reply(talk.run.id, service_user, recipebox.id) == Reply(
            1, "done", "It simmers."
        )

    def test_another_callers_is_answered_as_an_id_that_never_was(
        self,
        reads: ConversationReadService,
        talk: ChatWriter,
        recipebox: Environment,
        automation: Environment,
        service_user: User,
        other_service_user: User,
    ) -> None:
        never = uuid.uuid4()
        asks = [
            (talk.run.id, service_user, automation.id),
            (talk.run.id, service_user, None),
            (talk.run.id, other_service_user, recipebox.id),
            (never, service_user, recipebox.id),
        ]

        refusals = []
        for conversation_id, caller, environment_id in asks:
            with pytest.raises(RecordNotFoundException) as refused:
                reads.reply(conversation_id, caller, environment_id)
            refusals.append(str(refused.value))

        assert refusals == [
            f"Conversation {talk.run.id} was not found",
            f"Conversation {talk.run.id} was not found",
            f"Conversation {talk.run.id} was not found",
            f"Conversation {never} was not found",
        ]
