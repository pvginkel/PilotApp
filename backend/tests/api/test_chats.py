"""A person's message to a project's brain through the API (F38.3, F130;
design 3 §5.3; V06, V25)."""

import uuid
from collections.abc import Iterator

import pytest
from dependency_injector import providers
from flask.testing import FlaskClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.models import Chat, Project, Turn, User
from app.models.reference import ProjectState
from app.services.container import ServiceContainer
from app.services.environment_service import EnvironmentService
from app.services.relay_service import RelayService
from app.services.session_start_service import SessionStartService
from app.services.start_gate import WorkSlots
from app.services.turn_end_read_service import TurnEndReadService
from app.utils.after_commit import clear_after_commit_callbacks
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

    def test_a_finished_project_takes_no_message_409(
        self,
        client: FlaskClient,
        session: DbSession,
        starts: None,
        opened: Project,
        person: User,
    ) -> None:
        opened.state_code = ProjectState.FINISHED
        session.flush()
        _sign_in(client)

        response = client.post(_messages(opened.id), json={"words": "Hi"})

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot send a message to Pilot in Soup club because its project is"
            " finished"
        )

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
