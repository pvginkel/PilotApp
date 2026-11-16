"""A project's conversations as its people read them through the API, and
Pilot's answer in one stopped by a person (F150.12, F44; V09)."""

import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest
from dependency_injector import providers
from flask.testing import FlaskClient
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import Environment, Project, User
from app.models.reference import CloseCause, ProjectState, SessionState
from app.services.container import ServiceContainer
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.chats import close_conversation, open_chat, open_conversation
from tests.support.starts import configured_starts
from tests.support.supervisor import Supervise

SUBJECT = "subject-ada"
OPENED = datetime.fromisoformat("2026-10-12T09:00:00+00:00")


def _sign_in(
    client: FlaskClient, subject: str = SUBJECT, roles: tuple[str, ...] = ("editor",)
) -> None:
    response = client.post(
        "/api/testing/auth/session", json={"subject": subject, "roles": list(roles)}
    )
    assert response.status_code == 201, response.get_json()


def _conversations(project_id: uuid.UUID) -> str:
    return f"/api/projects/{project_id}/conversations"


def _stop(project_id: uuid.UUID, conversation_id: uuid.UUID) -> str:
    return f"/api/projects/{project_id}/conversations/{conversation_id}/stop"


@pytest.fixture(autouse=True)
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


@pytest.fixture
def starts(container: ServiceContainer, supervise: Supervise) -> Iterator[None]:
    """The routes' session starts with a controller and the store configured,
    on a supervisor of their own whose loops never run."""
    container.session_start_service.override(
        providers.Object(configured_starts(container, supervise))
    )
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
def recipebox(session: DbSession) -> Environment:
    """The environment a session called from."""
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


class TestListProjectConversations:
    def test_it_answers_the_projects_conversations_in_the_order_they_opened(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        recipebox: Environment,
        automation: Environment,
        service_user: User,
        person: User,
    ) -> None:
        running = open_conversation(
            session,
            opened,
            automation,
            opened_at=OPENED + timedelta(hours=1),
            state=SessionState.RUNNING,
            opener=service_user,
        )
        closed = open_conversation(
            session,
            opened,
            recipebox,
            caller_session="ui-sweep-triage",
            opened_at=OPENED,
            opener=service_user,
        )
        close_conversation(
            session, closed, OPENED + timedelta(minutes=30), CloseCause.ENDED
        )
        _sign_in(client)

        response = client.get(_conversations(opened.id))

        assert response.status_code == 200, response.get_json()
        assert response.get_json() == {
            "conversations": [
                {
                    "id": str(closed.id),
                    "environment": {
                        "id": "example-recipebox-1a2b3c",
                        "name": "RecipeBox-2",
                    },
                    "session": "ui-sweep-triage",
                    "opened_at": "2026-10-12T09:00:00Z",
                    "closed_at": "2026-10-12T09:30:00Z",
                    "close_cause": "ended",
                    "answering": False,
                },
                {
                    "id": str(running.id),
                    "environment": {
                        "id": "example-automation-9f8e7d",
                        "name": "Automation",
                    },
                    "session": None,
                    "opened_at": "2026-10-12T10:00:00Z",
                    "closed_at": None,
                    "close_cause": None,
                    "answering": True,
                },
            ]
        }

    def test_a_project_that_has_had_none_answers_none_whatever_chat_it_has(
        self, client: FlaskClient, session: DbSession, opened: Project, person: User
    ) -> None:
        open_chat(session, opened)
        _sign_in(client)

        response = client.get(_conversations(opened.id))

        assert response.status_code == 200
        assert response.get_json() == {"conversations": []}

    def test_another_projects_are_not_listed(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        recipebox: Environment,
        service_user: User,
        person: User,
    ) -> None:
        other = Project(
            created_by_user_id=person.id,
            state_code=ProjectState.OPEN,
            slug="bike-log",
            name="Bike log",
        )
        session.add(other)
        session.flush()
        open_conversation(session, other, recipebox, opener=service_user)
        _sign_in(client)

        response = client.get(_conversations(opened.id))

        assert response.get_json() == {"conversations": []}

    def test_a_caller_who_has_chosen_no_handle_reads_them(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        run = open_conversation(session, opened, recipebox, opener=service_user)
        _sign_in(client, subject="subject-ben")

        response = client.get(_conversations(opened.id))

        assert response.status_code == 200
        assert [each["id"] for each in response.get_json()["conversations"]] == [
            str(run.id)
        ]

    def test_no_project_has_the_id_404(self, client: FlaskClient, person: User) -> None:
        _sign_in(client)
        unknown = uuid.uuid4()

        response = client.get(_conversations(unknown))

        assert response.status_code == 404
        assert response.get_json()["error"] == f"Project {unknown} was not found"

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, opened: Project
    ) -> None:
        _sign_in(client, roles=())

        assert client.get(_conversations(opened.id)).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.get(_conversations(uuid.uuid4())).status_code == 401


class TestStopProjectConversation:
    def test_it_stops_pilots_answer_by_the_person_and_answers_the_conversation_200(
        self,
        client: FlaskClient,
        session: DbSession,
        starts: None,
        opened: Project,
        recipebox: Environment,
        service_user: User,
        person: User,
    ) -> None:
        run = open_conversation(
            session,
            opened,
            recipebox,
            caller_session="ui-sweep-triage",
            opened_at=OPENED,
            state=SessionState.RUNNING,
            opener=service_user,
        )
        _sign_in(client)

        response = client.post(_stop(opened.id, run.id))

        assert response.status_code == 200, response.get_json()
        assert response.get_json() == {
            "id": str(run.id),
            "environment": {"id": "example-recipebox-1a2b3c", "name": "RecipeBox-2"},
            "session": "ui-sweep-triage",
            "opened_at": "2026-10-12T09:00:00Z",
            "closed_at": None,
            "close_cause": None,
            "answering": False,
        }
        run = session.get_one(models.Session, run.id, populate_existing=True)
        assert (run.state_code, run.stopped_by_user_id) == (
            SessionState.STOPPED,
            person.id,
        )

    def test_a_conversation_pilot_is_not_answering_in_is_409(
        self,
        client: FlaskClient,
        session: DbSession,
        starts: None,
        opened: Project,
        recipebox: Environment,
        service_user: User,
        person: User,
    ) -> None:
        run = open_conversation(session, opened, recipebox, opener=service_user)
        _sign_in(client)

        response = client.post(_stop(opened.id, run.id))

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot stop Pilot in Soup club because it is not answering"
        )
        assert session.get_one(models.Session, run.id).stopped_at is None

    def test_a_caller_with_no_handle_is_409(
        self,
        client: FlaskClient,
        session: DbSession,
        starts: None,
        opened: Project,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        run = open_conversation(
            session, opened, recipebox, state=SessionState.RUNNING, opener=service_user
        )
        _sign_in(client, subject="subject-ben")

        response = client.post(_stop(opened.id, run.id))

        assert response.status_code == 409
        assert session.get_one(models.Session, run.id).state_code == (
            SessionState.RUNNING
        )

    def test_the_service_user_is_409(
        self,
        client: FlaskClient,
        session: DbSession,
        starts: None,
        opened: Project,
        recipebox: Environment,
        service_user: User,
    ) -> None:
        """A caller's own stop is its interrupt, on the projects surface."""
        run = open_conversation(
            session, opened, recipebox, state=SessionState.RUNNING, opener=service_user
        )
        assert service_user.subject is not None
        _sign_in(client, subject=service_user.subject)

        response = client.post(_stop(opened.id, run.id))

        assert response.status_code == 409
        assert "you call as the service user" in response.get_json()["error"]
        assert session.get_one(models.Session, run.id).state_code == (
            SessionState.RUNNING
        )

    def test_another_projects_conversation_and_an_unknown_one_are_404(
        self,
        client: FlaskClient,
        session: DbSession,
        starts: None,
        opened: Project,
        recipebox: Environment,
        service_user: User,
        person: User,
    ) -> None:
        other = Project(
            created_by_user_id=person.id,
            state_code=ProjectState.OPEN,
            slug="bike-log",
            name="Bike log",
        )
        session.add(other)
        session.flush()
        run = open_conversation(
            session, other, recipebox, state=SessionState.RUNNING, opener=service_user
        )
        _sign_in(client)

        for unknown in (run.id, uuid.uuid4()):
            response = client.post(_stop(opened.id, unknown))

            assert response.status_code == 404
            assert response.get_json()["error"] == (
                f"Conversation {unknown} was not found"
            )
        assert session.get_one(models.Session, run.id).state_code == (
            SessionState.RUNNING
        )

    def test_a_chat_is_no_conversation_404(
        self,
        client: FlaskClient,
        session: DbSession,
        starts: None,
        opened: Project,
        person: User,
    ) -> None:
        chat = open_chat(session, opened)
        chat.state_code = SessionState.RUNNING
        session.flush()
        _sign_in(client)

        response = client.post(_stop(opened.id, chat.id))

        assert response.status_code == 404
        assert session.get_one(models.Session, chat.id).state_code == (
            SessionState.RUNNING
        )

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, opened: Project
    ) -> None:
        _sign_in(client, roles=())

        assert client.post(_stop(opened.id, uuid.uuid4())).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.post(_stop(uuid.uuid4(), uuid.uuid4()))

        assert response.status_code == 401
