"""A person's message to a project's brain through the API (F38.3, F130,
F5.5, F128.5; design 3 §5.3; V05, V06, V25); Pilot's answer in it stopped
(F44); and the project's chats as a person reads them, with their place in
them and whether Pilot is answering (F40.3, F43; V09)."""

import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest
from dependency_injector import providers
from flask.testing import FlaskClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import Chat, ChatRead, Project, Turn, User
from app.models.reference import (
    ChatKind,
    CloseCause,
    ProjectState,
    SessionState,
    TransitionKind,
    UserKind,
)
from app.services.chat_close_service import ChatCloseService
from app.services.container import ServiceContainer
from app.services.environment_service import EnvironmentService
from app.services.relay_service import RelayService
from app.services.session_start_service import SessionStartService
from app.services.start_gate import WorkSlots
from app.services.turn_end_read_service import TurnEndReadService
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.chats import ChatWriter, close_chat, open_chat
from tests.support.fake_sidecar import STORE_ENVIRONMENT_ID
from tests.support.supervisor import Supervise

SUBJECT = "subject-ada"


def _sign_in(client: FlaskClient, roles: tuple[str, ...] = ("editor",)) -> None:
    response = client.post(
        "/api/testing/auth/session", json={"subject": SUBJECT, "roles": list(roles)}
    )
    assert response.status_code == 201, response.get_json()


def _messages(project_id: uuid.UUID) -> str:
    return f"/api/projects/{project_id}/chat/messages"


def _chats(project_id: uuid.UUID) -> str:
    return f"/api/projects/{project_id}/chats"


def _stop(project_id: uuid.UUID) -> str:
    return f"/api/projects/{project_id}/chat/stop"


def _read(project_id: uuid.UUID) -> str:
    return f"/api/projects/{project_id}/chat/read"


def _stamp(at: datetime) -> str:
    """A time as the API writes it."""
    return at.isoformat().replace("+00:00", "Z")


@pytest.fixture(autouse=True)
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


@pytest.fixture
def starts(container: ServiceContainer, supervise: Supervise) -> Iterator[None]:
    """The routes' session starts with a controller and the store configured,
    on a supervisor of their own whose loops never run."""
    supervisor, _ = supervise(container)
    environments = EnvironmentService(
        container=container,
        supervisor=supervisor,
        stop_after_seconds=1800,
        delete_after_seconds=604800,
    )
    slots = WorkSlots(work_max=3, project_max=3)
    starting = SessionStartService(
        container=container,
        supervisor=supervisor,
        session_streams=container.session_stream_service(),
        environment_service=environments,
        relay_service=RelayService(
            container=container,
            supervisor=supervisor,
            session_streams=container.session_stream_service(),
            environment_service=environments,
            work_slots=slots,
            pilot_server=container.pilot_server(),
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
        ),
        controller_outage=container.controller_outage(),
        work_slots=slots,
        pilot_server=container.pilot_server(),
        controller_configured=True,
        store_environment_id=STORE_ENVIRONMENT_ID,
    )
    container.session_start_service.override(providers.Object(starting))
    try:
        yield
    finally:
        container.session_start_service.reset_last_overriding()


@pytest.fixture
def opened(session: DbSession, project: Project) -> Project:
    project.state_code = ProjectState.OPEN
    project.slug, project.name = "soup-club", "Soup club"
    session.flush()
    return project


@pytest.fixture
def bea(session: DbSession) -> User:
    """Another person, who sent the message."""
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


class TestSendChatMessage:
    def test_a_message_with_no_chat_open_starts_the_chat_and_answers_its_turn(
        self,
        client: FlaskClient,
        session: DbSession,
        starts: None,
        opened: Project,
        person: User,
    ) -> None:
        _sign_in(client)

        response = client.post(_messages(opened.id), json={"words": "What next?"})

        assert response.status_code == 201, response.get_json()
        body = response.get_json()
        (chat,) = session.scalars(select(Chat)).all()
        assert body == {
            "chat": str(chat.id),
            "seq": 1,
            "state": "starting",
            "error": None,
        }
        turn = session.scalars(select(Turn)).one()
        assert (turn.author_user_id, turn.words) == (person.id, "What next?")
        assert turn.message.endswith("\nWhat next?")

    def test_a_message_quoting_a_file_by_its_path_keeps_it_in_its_words_201(
        self,
        client: FlaskClient,
        session: DbSession,
        starts: None,
        opened: Project,
    ) -> None:
        words = (
            '<quoted_path path="handbook.md">The handbook</quoted_path path='
            '"handbook.md"> Salt last?'
        )
        _sign_in(client)

        response = client.post(_messages(opened.id), json={"words": words})

        assert response.status_code == 201, response.get_json()
        turn = session.scalars(select(Turn)).one()
        assert (turn.words, turn.quote_item_id, turn.quote_block_id) == (
            words,
            None,
            None,
        )
        assert turn.message.endswith(f"\n{words}")

    @pytest.mark.parametrize("payload", [{"words": "  \n"}, {"words": ""}, {}])
    def test_a_message_without_words_is_400(
        self,
        client: FlaskClient,
        session: DbSession,
        starts: None,
        opened: Project,
        person: User,
        payload: dict[str, str],
    ) -> None:
        _sign_in(client)

        response = client.post(_messages(opened.id), json=payload)

        assert response.status_code == 400
        assert session.scalars(select(Chat)).all() == []

    def test_no_project_has_the_id_404(
        self, client: FlaskClient, starts: None, person: User
    ) -> None:
        _sign_in(client)
        unknown = uuid.uuid4()

        response = client.post(_messages(unknown), json={"words": "Hi"})

        assert response.status_code == 404
        assert response.get_json()["error"] == f"Project {unknown} was not found"

    def test_an_archived_project_takes_no_message_409(
        self,
        client: FlaskClient,
        session: DbSession,
        starts: None,
        opened: Project,
        person: User,
    ) -> None:
        opened.archived = True
        session.flush()
        _sign_in(client)

        response = client.post(_messages(opened.id), json={"words": "Hi"})

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot send a message to Pilot in Soup club because its project is"
            " archived"
        )
        assert session.scalars(select(Chat)).all() == []

    def test_a_finished_projects_message_starts_its_chat_reading_only_201(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        starts: None,
        opened: Project,
        person: User,
    ) -> None:
        container.project_service().transition_as(
            person, opened.id, TransitionKind.FINISHED
        )
        _sign_in(client)

        response = client.post(_messages(opened.id), json={"words": "Hi"})

        assert response.status_code == 201, response.get_json()
        assert response.get_json()["state"] == "starting"
        turn = session.scalars(select(Turn)).one()
        assert "a finished project's chat" in turn.message
        assert "This project is finished" in turn.message

    def test_a_message_while_the_chat_starts_is_409(
        self,
        client: FlaskClient,
        session: DbSession,
        starts: None,
        opened: Project,
        person: User,
    ) -> None:
        _sign_in(client)
        assert (
            client.post(_messages(opened.id), json={"words": "One"}).status_code == 201
        )

        response = client.post(_messages(opened.id), json={"words": "Two"})

        assert response.status_code == 409
        assert "its chat is starting" in response.get_json()["error"]

    def test_with_no_controller_configured_it_is_409(
        self, client: FlaskClient, opened: Project, person: User
    ) -> None:
        _sign_in(client)

        response = client.post(_messages(opened.id), json={"words": "Hi"})

        assert response.status_code == 409
        assert "no controller is configured" in response.get_json()["error"]

    def test_a_caller_with_no_handle_is_409(
        self, client: FlaskClient, session: DbSession, starts: None, opened: Project
    ) -> None:
        response = client.post(
            "/api/testing/auth/session",
            json={"subject": "subject-ben", "roles": ["editor"]},
        )
        assert response.status_code == 201

        response = client.post(_messages(opened.id), json={"words": "Hi"})

        assert response.status_code == 409
        assert session.scalars(select(Chat)).all() == []

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, opened: Project
    ) -> None:
        _sign_in(client, roles=())

        assert (
            client.post(_messages(opened.id), json={"words": "Hi"}).status_code == 403
        )

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.post(_messages(uuid.uuid4()), json={"words": "Hi"})

        assert response.status_code == 401


def _answering(
    db: DbSession, container: ServiceContainer, project: Project, person: User
) -> models.Session:
    """The project's open chat, Pilot answering a message of `person`'s."""
    run = open_chat(db, project)
    ChatWriter(db, container.session_record_service(), run).message(person, "Hi")
    run.state_code = SessionState.RUNNING
    db.flush()
    return run


class TestStopChat:
    def test_it_stops_pilots_answer_by_anyone_and_answers_the_chat_200(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        starts: None,
        opened: Project,
        person: User,
        bea: User,
    ) -> None:
        run = _answering(session, container, opened, bea)
        _sign_in(client)

        response = client.post(_stop(opened.id))

        assert response.status_code == 200, response.get_json()
        assert response.get_json() == {
            "id": str(run.id),
            "kind": "project",
            "opened_at": _stamp(run.created_at),
            "closed_at": None,
            "close_cause": None,
            "answering": False,
        }
        run = session.get_one(models.Session, run.id, populate_existing=True)
        assert (run.state_code, run.stopped_by_user_id) == (
            SessionState.STOPPED,
            person.id,
        )

    def test_with_no_chat_open_it_is_409(
        self, client: FlaskClient, starts: None, opened: Project, person: User
    ) -> None:
        _sign_in(client)

        response = client.post(_stop(opened.id))

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot stop Pilot in Soup club because no chat is open"
        )

    def test_a_chat_pilot_is_not_answering_in_is_409(
        self,
        client: FlaskClient,
        session: DbSession,
        starts: None,
        opened: Project,
        person: User,
    ) -> None:
        run = open_chat(session, opened)
        _sign_in(client)

        response = client.post(_stop(opened.id))

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot stop Pilot in Soup club because it is not answering"
        )
        assert session.get_one(models.Session, run.id).stopped_at is None

    def test_a_caller_with_no_handle_is_409(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        starts: None,
        opened: Project,
        person: User,
    ) -> None:
        run = _answering(session, container, opened, person)
        response = client.post(
            "/api/testing/auth/session",
            json={"subject": "subject-ben", "roles": ["editor"]},
        )
        assert response.status_code == 201

        response = client.post(_stop(opened.id))

        assert response.status_code == 409
        assert session.get_one(models.Session, run.id).state_code == (
            SessionState.RUNNING
        )

    def test_no_project_has_the_id_404(
        self, client: FlaskClient, starts: None, person: User
    ) -> None:
        _sign_in(client)
        unknown = uuid.uuid4()

        response = client.post(_stop(unknown))

        assert response.status_code == 404
        assert response.get_json()["error"] == f"Project {unknown} was not found"

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, opened: Project
    ) -> None:
        _sign_in(client, roles=())

        assert client.post(_stop(opened.id)).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.post(_stop(uuid.uuid4())).status_code == 401


class TestListChats:
    def test_it_answers_the_chats_in_order_and_the_callers_place(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        opened: Project,
        person: User,
    ) -> None:
        at = datetime.fromisoformat("2026-10-12T09:00:00+00:00")
        definition = open_chat(session, opened, kind=ChatKind.DEFINITION, opened_at=at)
        close_chat(session, definition, at + timedelta(hours=1), CloseCause.CREATED)
        chat = open_chat(session, opened, opened_at=at + timedelta(hours=2))
        writer = ChatWriter(session, container.session_record_service(), chat)
        writer.message(person, "What next?")
        writer.text("Two things.")
        _sign_in(client)

        response = client.get(_chats(opened.id))

        assert response.status_code == 200
        assert response.get_json() == {
            "chats": [
                {
                    "id": str(definition.id),
                    "kind": "definition",
                    "opened_at": "2026-10-12T09:00:00Z",
                    "closed_at": "2026-10-12T10:00:00Z",
                    "close_cause": "created",
                    "answering": False,
                },
                {
                    "id": str(chat.id),
                    "kind": "project",
                    "opened_at": "2026-10-12T11:00:00Z",
                    "closed_at": None,
                    "close_cause": None,
                    "answering": False,
                },
            ],
            "read_at": None,
            "unread": True,
        }

    def test_a_chat_pilot_answers_in_reads_answering(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        opened: Project,
        person: User,
    ) -> None:
        run = _answering(session, container, opened, person)
        _sign_in(client)

        response = client.get(_chats(opened.id))

        assert response.status_code == 200
        ((chat_id, answering),) = [
            (chat["id"], chat["answering"]) for chat in response.get_json()["chats"]
        ]
        assert (chat_id, answering) == (str(run.id), True)

    def test_the_chat_archive_closed_reads_archived(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        opened: Project,
        person: User,
    ) -> None:
        chat = open_chat(session, opened)
        container.project_service().transition_as(
            person, opened.id, TransitionKind.ARCHIVED
        )
        closed_at = session.get_one(Chat, chat.id).closed_at
        assert closed_at is not None
        _sign_in(client)

        response = client.get(_chats(opened.id))

        assert response.status_code == 200
        assert response.get_json()["chats"] == [
            {
                "id": str(chat.id),
                "kind": "project",
                "opened_at": _stamp(chat.created_at),
                "closed_at": _stamp(closed_at),
                "close_cause": "archived",
                "answering": False,
            }
        ]

    def test_after_the_caller_read_it_nothing_is_unread(
        self,
        client: FlaskClient,
        session: DbSession,
        container: ServiceContainer,
        opened: Project,
        person: User,
    ) -> None:
        writer = ChatWriter(
            session, container.session_record_service(), open_chat(session, opened)
        )
        writer.message(person, "What next?")
        writer.text("Two things.")
        _sign_in(client)
        read = client.put(_read(opened.id)).get_json()

        response = client.get(_chats(opened.id))

        assert response.status_code == 200
        assert (response.get_json()["read_at"], response.get_json()["unread"]) == (
            read["read_at"],
            False,
        )

    def test_a_caller_with_no_handle_reads_it_with_no_place(
        self, client: FlaskClient, session: DbSession, opened: Project
    ) -> None:
        open_chat(session, opened)
        response = client.post(
            "/api/testing/auth/session",
            json={"subject": "subject-ben", "roles": ["editor"]},
        )
        assert response.status_code == 201

        response = client.get(_chats(opened.id))

        assert response.status_code == 200
        assert len(response.get_json()["chats"]) == 1
        assert (response.get_json()["read_at"], response.get_json()["unread"]) == (
            None,
            False,
        )

    def test_no_project_has_the_id_404(self, client: FlaskClient, person: User) -> None:
        _sign_in(client)

        assert client.get(_chats(uuid.uuid4())).status_code == 404

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, opened: Project
    ) -> None:
        _sign_in(client, roles=())

        assert client.get(_chats(opened.id)).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.get(_chats(uuid.uuid4())).status_code == 401


class TestReadChat:
    def test_it_writes_the_callers_place_now(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        person: User,
    ) -> None:
        _sign_in(client)

        response = client.put(_read(opened.id))

        assert response.status_code == 200
        read = session.get_one(ChatRead, (person.id, opened.id))
        assert response.get_json() == {"read_at": _stamp(read.read_at), "unread": False}

    def test_a_caller_with_no_handle_is_409(
        self, client: FlaskClient, session: DbSession, opened: Project
    ) -> None:
        response = client.post(
            "/api/testing/auth/session",
            json={"subject": "subject-ben", "roles": ["editor"]},
        )
        assert response.status_code == 201

        response = client.put(_read(opened.id))

        assert response.status_code == 409
        assert session.scalars(select(ChatRead)).all() == []

    def test_no_project_has_the_id_404(self, client: FlaskClient, person: User) -> None:
        _sign_in(client)

        assert client.put(_read(uuid.uuid4())).status_code == 404

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, opened: Project
    ) -> None:
        _sign_in(client, roles=())

        assert client.put(_read(opened.id)).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.put(_read(uuid.uuid4())).status_code == 401
