"""A calling session's conversation with Pilot through the API (F150.10,
F150.11, F150.2; DB Conversation, assertions 334 to 337; V01, V04, V18): its
opening, its next message, its read, its caller's list, its interrupt and its
end, each the service user's alone and each answering to the environment
that opened it."""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from dependency_injector import providers
from flask.testing import FlaskClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import Chat, Conversation, Environment, Project, Turn, User
from app.models.reference import CloseCause, ProjectState, SessionState
from app.services.caller_environment_service import (
    CALLER_ENVIRONMENT_HEADER,
    CALLER_SESSION_HEADER,
)
from app.services.container import ServiceContainer
from app.services.relay_service import RelayService
from app.services.session_start_service import SessionStartService
from app.services.supervisor import LoopHandle
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.chats import close_conversation, open_conversation
from tests.support.fake_controller import ServedFakeController, client_of
from tests.support.fake_sidecar import STORE_ENVIRONMENT_ID
from tests.support.starts import configured_starts_and_relays
from tests.support.store_updates import hold
from tests.support.supervisor import Supervise

CALLER = "example-recipebox-1a2b3c"
CALLER_SESSION = "ui-sweep-triage"
OTHER = "example-automation-9f8e7d"
HEADERS = {CALLER_ENVIRONMENT_HEADER: CALLER, CALLER_SESSION_HEADER: CALLER_SESSION}
OTHERS_HEADERS = {CALLER_ENVIRONMENT_HEADER: OTHER, CALLER_SESSION_HEADER: "nightly"}
WORDS = "How is the stock going?"
STORE_REPO = "/work/PilotProjects"
FOLDER = "/work/Projects/soup-club"
ROOT = "/api/conversations"

Services = tuple[SessionStartService, RelayService]


def _sign_in(
    client: FlaskClient, subject: str, roles: tuple[str, ...] = ("editor",)
) -> None:
    response = client.post(
        "/api/testing/auth/session",
        json={"subject": subject, "name": None, "email": None, "roles": list(roles)},
    )
    assert response.status_code == 201, response.get_json()


def _one(conversation_id: uuid.UUID) -> str:
    return f"{ROOT}/{conversation_id}"


def _messages(conversation_id: uuid.UUID) -> str:
    return f"{ROOT}/{conversation_id}/messages"


def _interrupt(conversation_id: uuid.UUID) -> str:
    return f"{ROOT}/{conversation_id}/interrupt"


def _end(conversation_id: uuid.UUID) -> str:
    return f"{ROOT}/{conversation_id}/end"


def _stamp(at: datetime) -> str:
    """A time as the API writes it."""
    return at.isoformat().replace("+00:00", "Z")


def _made(
    db: DbSession, project: Project, caller: Environment, **spec: Any
) -> models.Session:
    """A conversation on the record, committed, so that a refused call's
    rollback keeps it."""
    run = open_conversation(db, project, caller, **spec)
    db.commit()
    return run


def _closed(
    db: DbSession, run: models.Session, at: datetime, cause: CloseCause
) -> None:
    close_conversation(db, run, at, cause)
    db.commit()


def _refusal(response: Any, conversation_id: uuid.UUID) -> dict[str, Any]:
    """A refusal as its caller reads it, but for the request's own id and
    the conversation's: what tells one refusal from another."""
    body = response.get_json()
    del body["correlationId"]
    return json.loads(json.dumps(body).replace(str(conversation_id), "<id>"))


def _read(db: DbSession, run_id: uuid.UUID) -> models.Session:
    return db.get_one(models.Session, run_id, populate_existing=True)


def _row(db: DbSession, run_id: uuid.UUID) -> Conversation:
    return db.get_one(Conversation, run_id, populate_existing=True)


def _turns(db: DbSession) -> int:
    return len(db.scalars(select(Turn)).all())


@pytest.fixture(autouse=True)
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


@pytest.fixture
def fake(container: ServiceContainer) -> Iterator[ServedFakeController]:
    """The fake controller, `container`'s client on it: the store running in
    it with the store repo's root and the project's folder on its tree."""
    served = ServedFakeController(keepalive_seconds=0.2)
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


@pytest.fixture
def services(
    container: ServiceContainer, supervise: Supervise, fake: ServedFakeController
) -> Iterator[Services]:
    """The routes' session start and relay with a controller and the store
    configured, on a supervisor of their own whose loops never run."""
    starts, relays = configured_starts_and_relays(container, supervise)
    container.session_start_service.override(providers.Object(starts))
    container.relay_service.override(providers.Object(relays))
    try:
        yield starts, relays
    finally:
        container.relay_service.reset_last_overriding()
        container.session_start_service.reset_last_overriding()


@pytest.fixture
def opened(session: DbSession, project: Project) -> Project:
    project.state_code = ProjectState.OPEN
    project.slug, project.name = "soup-club", "Soup club"
    session.flush()
    return project


@pytest.fixture
def recipebox(session: DbSession) -> Environment:
    """The caller's environment, on the record."""
    caller = Environment(id=CALLER, name="RecipeBox-2", exempt=False)
    session.add(caller)
    session.flush()
    return caller


@pytest.fixture
def fleet(client: FlaskClient, service_user: User) -> User:
    """The service user, signed in."""
    _sign_in(client, service_user.subject)
    return service_user


def _open(client: FlaskClient, **changes: Any) -> Any:
    body = {"address": "soup-club", "words": WORDS} | changes
    return client.post(ROOT, json=body, headers=HEADERS)


def _idle(
    client: FlaskClient,
    db: DbSession,
    fake: ServedFakeController,
    services: Services,
) -> uuid.UUID:
    """A conversation opened through its route, its first turn ended: idle
    on its headless session in the store."""
    response = _open(client)
    assert response.status_code == 201, response.get_json()
    clear_after_commit_callbacks()
    run_id = uuid.UUID(response.get_json()["id"])
    starts, relays = services
    starts.run(run_id, LoopHandle(f"start:{run_id}"))
    clear_after_commit_callbacks()
    run = _read(db, run_id)
    assert run.controller_session is not None
    fake.play(
        STORE_ENVIRONMENT_ID,
        run.controller_session,
        [json.dumps({"type": "system", "subtype": "init", "session_id": "thread-1"})],
    )
    fake.finish(STORE_ENVIRONMENT_ID, run.controller_session, "success", "Done.")
    relays.relay(run_id, LoopHandle(f"relay:{run_id}"))
    clear_after_commit_callbacks()
    assert _read(db, run_id).state_code == SessionState.IDLE
    return run_id


@pytest.mark.usefixtures("services")
class TestOpenConversation:
    def test_it_opens_the_callers_conversation_and_answers_it_201(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        fleet: User,
    ) -> None:
        response = _open(client)

        assert response.status_code == 201, response.get_json()
        body = response.get_json()
        (conversation,) = session.scalars(select(Conversation)).all()
        run = _read(session, conversation.id)
        assert body == {
            "id": str(conversation.id),
            "project_id": str(opened.id),
            "environment": CALLER,
            "session": CALLER_SESSION,
            "opened_at": _stamp(run.created_at),
            "closed_at": None,
            "close_cause": None,
            "turns": 1,
            "in_flight": True,
        }
        assert (
            conversation.project_id,
            conversation.caller_environment_id,
            conversation.caller_session,
        ) == (opened.id, CALLER, CALLER_SESSION)
        assert (run.kind_code, run.state_code) == (
            "conversation",
            SessionState.STARTING,
        )
        turn = session.scalars(select(Turn)).one()
        assert (turn.session_id, turn.seq, turn.author_user_id, turn.words) == (
            conversation.id,
            1,
            fleet.id,
            WORDS,
        )
        assert turn.message.endswith(f"\n{WORDS}")
        assert session.scalars(select(Chat)).all() == []

    def test_an_environment_pilot_has_no_row_of_is_written_one_named_by_its_id(
        self, client: FlaskClient, session: DbSession, opened: Project, fleet: User
    ) -> None:
        """The suite's app has no controller configured, so none reports it
        (V23)."""
        assert session.get(Environment, CALLER) is None

        assert _open(client).status_code == 201

        row = session.get_one(Environment, CALLER)
        assert (row.name, row.server_created_at) == (CALLER, None)

    def test_the_project_is_named_by_its_id_too(
        self, client: FlaskClient, session: DbSession, opened: Project, fleet: User
    ) -> None:
        response = _open(client, address=str(opened.id))

        assert response.status_code == 201
        assert response.get_json()["project_id"] == str(opened.id)

    @pytest.mark.parametrize(
        "session_header", [{}, {CALLER_SESSION_HEADER: ""}], ids=["absent", "empty"]
    )
    def test_a_call_that_names_no_session_opens_one_with_none(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        fleet: User,
        session_header: dict[str, str],
    ) -> None:
        response = client.post(
            ROOT,
            json={"address": "soup-club", "words": WORDS},
            headers={CALLER_ENVIRONMENT_HEADER: CALLER, **session_header},
        )

        assert response.status_code == 201
        assert response.get_json()["session"] is None
        assert session.scalars(select(Conversation)).one().caller_session is None

    def test_one_calling_session_opens_several_on_one_project(
        self, client: FlaskClient, session: DbSession, opened: Project, fleet: User
    ) -> None:
        first, second = _open(client), _open(client, words="And the bread?")

        assert (first.status_code, second.status_code) == (201, 201)
        assert first.get_json()["id"] != second.get_json()["id"]
        assert len(session.scalars(select(Conversation)).all()) == 2

    @pytest.mark.parametrize(
        "environment_header",
        [{}, {CALLER_ENVIRONMENT_HEADER: ""}],
        ids=["absent", "empty"],
    )
    def test_a_call_that_names_no_environment_is_400_and_nothing_opens(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        fleet: User,
        environment_header: dict[str, str],
    ) -> None:
        response = client.post(
            ROOT,
            json={"address": "soup-club", "words": WORDS},
            headers={CALLER_SESSION_HEADER: CALLER_SESSION, **environment_header},
        )

        assert response.status_code == 400
        assert response.get_json()["error"] == (
            "Cannot open a conversation with Pilot because the call names no"
            " environment, and a conversation is its calling environment's"
        )
        assert session.scalars(select(Conversation)).all() == []
        assert session.scalars(select(Environment)).all() == []

    @pytest.mark.parametrize(
        "body",
        [
            {"address": "soup-club"},
            {"address": "soup-club", "words": " \n"},
            {"words": WORDS},
            {"address": "", "words": WORDS},
        ],
        ids=["no-words", "blank-words", "no-address", "empty-address"],
    )
    def test_a_body_that_is_no_opening_is_400(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        fleet: User,
        body: dict[str, str],
    ) -> None:
        response = client.post(ROOT, json=body, headers=HEADERS)

        assert response.status_code == 400
        assert session.scalars(select(Conversation)).all() == []

    def test_no_project_is_at_the_address_404(
        self, client: FlaskClient, session: DbSession, fleet: User
    ) -> None:
        response = _open(client, address="no-such-project")

        assert response.status_code == 404
        assert session.scalars(select(Conversation)).all() == []

    def test_a_draft_takes_none_409(
        self, client: FlaskClient, session: DbSession, project: Project, fleet: User
    ) -> None:
        response = _open(client, address=f"draft-{project.number}")

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot open a conversation with Pilot in the untitled project because"
            " its project is a draft"
        )
        assert session.scalars(select(Conversation)).all() == []

    def test_an_archived_project_takes_none_409(
        self, client: FlaskClient, session: DbSession, opened: Project, fleet: User
    ) -> None:
        opened.archived = True
        session.flush()

        response = _open(client)

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot open a conversation with Pilot in Soup club because its project"
            " is archived"
        )
        assert session.scalars(select(Conversation)).all() == []

    def test_under_the_stores_update_none_opens_409(
        self, client: FlaskClient, session: DbSession, opened: Project, fleet: User
    ) -> None:
        hold(session)
        session.commit()

        response = _open(client)

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot open a conversation with Pilot in Soup club because Pilot is"
            " updating"
        )
        assert session.scalars(select(Conversation)).all() == []

    def test_a_person_opens_none_409(
        self, client: FlaskClient, session: DbSession, opened: Project, person: User
    ) -> None:
        _sign_in(client, person.subject)

        response = _open(client)

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot open a conversation with Pilot because you do not call as a"
            " service user"
        )
        assert session.scalars(select(Conversation)).all() == []
        assert _turns(session) == 0

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, opened: Project, service_user: User
    ) -> None:
        _sign_in(client, service_user.subject, roles=())

        assert _open(client).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.post(
            ROOT, json={"address": "soup-club", "words": WORDS}, headers=HEADERS
        )

        assert response.status_code == 401


class TestGetConversation:
    def test_its_caller_reads_where_it_stands_200(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        recipebox: Environment,
        fleet: User,
    ) -> None:
        opened_at = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
        closed_at = datetime(2026, 10, 12, 9, 30, tzinfo=UTC)
        run = _made(
            session,
            opened,
            recipebox,
            caller_session=CALLER_SESSION,
            opened_at=opened_at,
            opener=fleet,
        )
        _closed(session, run, closed_at, CloseCause.TIMEOUT)

        response = client.get(_one(run.id), headers=HEADERS)

        assert response.status_code == 200
        assert response.get_json() == {
            "id": str(run.id),
            "project_id": str(opened.id),
            "environment": CALLER,
            "session": CALLER_SESSION,
            "opened_at": "2026-10-12T09:00:00Z",
            "closed_at": "2026-10-12T09:30:00Z",
            "close_cause": "timeout",
            "turns": 1,
            "in_flight": False,
        }

    def test_a_later_session_of_its_environment_reads_it(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        recipebox: Environment,
        fleet: User,
    ) -> None:
        run = _made(session, opened, recipebox, caller_session="monday", opener=fleet)

        response = client.get(
            _one(run.id),
            headers={
                CALLER_ENVIRONMENT_HEADER: CALLER,
                CALLER_SESSION_HEADER: "tuesday",
            },
        )

        assert response.status_code == 200
        assert response.get_json()["session"] == "monday"

    @pytest.mark.parametrize(
        "headers", [OTHERS_HEADERS, {}], ids=["another-environment", "no-environment"]
    )
    def test_another_callers_is_answered_as_an_id_that_never_was_404(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        recipebox: Environment,
        fleet: User,
        headers: dict[str, str],
    ) -> None:
        run = _made(session, opened, recipebox, opener=fleet)
        never = uuid.uuid4()

        anothers = client.get(_one(run.id), headers=headers)
        unknown = client.get(_one(never), headers=HEADERS)

        assert (anothers.status_code, unknown.status_code) == (404, 404)
        assert anothers.get_json()["error"] == f"Conversation {run.id} was not found"
        assert _refusal(anothers, run.id) == _refusal(unknown, never)

    def test_a_person_reads_none_409(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        recipebox: Environment,
        service_user: User,
        person: User,
    ) -> None:
        run = _made(session, opened, recipebox, opener=service_user)
        _sign_in(client, person.subject)

        response = client.get(_one(run.id), headers=HEADERS)

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            f"Cannot read the conversation {run.id} with Pilot because you do not"
            " call as a service user"
        )

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, service_user: User
    ) -> None:
        _sign_in(client, service_user.subject, roles=())

        assert client.get(_one(uuid.uuid4()), headers=HEADERS).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.get(_one(uuid.uuid4()), headers=HEADERS).status_code == 401


class TestListConversations:
    @pytest.fixture
    def bikes(self, session: DbSession, person: User) -> Project:
        other = Project(
            created_by_user_id=person.id,
            state_code=ProjectState.OPEN,
            slug="bike-log",
            name="Bike log",
        )
        session.add(other)
        session.flush()
        return other

    def test_it_lists_the_callers_environments_open_and_closed_in_order_200(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        bikes: Project,
        recipebox: Environment,
        fleet: User,
    ) -> None:
        automation = Environment(id=OTHER, name="Automation", exempt=False)
        session.add(automation)
        session.flush()
        later = _made(
            session,
            bikes,
            recipebox,
            caller_session="tuesday",
            opened_at=datetime(2026, 10, 13, 9, 0, tzinfo=UTC),
            state=SessionState.RUNNING,
            opener=fleet,
        )
        earlier = _made(
            session,
            opened,
            recipebox,
            caller_session="monday",
            opened_at=datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
            opener=fleet,
        )
        _closed(
            session,
            earlier,
            datetime(2026, 10, 12, 9, 30, tzinfo=UTC),
            CloseCause.ENDED,
        )
        _made(session, opened, automation, opener=fleet)

        response = client.get(
            ROOT,
            headers={
                CALLER_ENVIRONMENT_HEADER: CALLER,
                CALLER_SESSION_HEADER: "wednesday",
            },
        )

        assert response.status_code == 200
        assert response.get_json() == {
            "conversations": [
                {
                    "id": str(earlier.id),
                    "project_id": str(opened.id),
                    "environment": CALLER,
                    "session": "monday",
                    "opened_at": "2026-10-12T09:00:00Z",
                    "closed_at": "2026-10-12T09:30:00Z",
                    "close_cause": "ended",
                    "turns": 1,
                    "in_flight": False,
                },
                {
                    "id": str(later.id),
                    "project_id": str(bikes.id),
                    "environment": CALLER,
                    "session": "tuesday",
                    "opened_at": "2026-10-13T09:00:00Z",
                    "closed_at": None,
                    "close_cause": None,
                    "turns": 1,
                    "in_flight": True,
                },
            ]
        }

    def test_an_address_lists_that_projects_alone(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        bikes: Project,
        recipebox: Environment,
        fleet: User,
    ) -> None:
        _made(session, opened, recipebox, opener=fleet)
        bike = _made(session, bikes, recipebox, opener=fleet)

        by_slug = client.get(f"{ROOT}?address=bike-log", headers=HEADERS)
        by_id = client.get(f"{ROOT}?address={bikes.id}", headers=HEADERS)

        assert by_slug.status_code == 200
        assert [row["id"] for row in by_slug.get_json()["conversations"]] == [
            str(bike.id)
        ]
        assert by_id.get_json() == by_slug.get_json()

    def test_a_call_that_names_no_environment_lists_none(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        recipebox: Environment,
        fleet: User,
    ) -> None:
        _made(session, opened, recipebox, opener=fleet)

        response = client.get(ROOT)

        assert response.status_code == 200
        assert response.get_json() == {"conversations": []}

    def test_no_project_is_at_the_address_404(
        self, client: FlaskClient, fleet: User
    ) -> None:
        response = client.get(f"{ROOT}?address=no-such-project", headers=HEADERS)

        assert response.status_code == 404

    def test_an_empty_address_is_400(self, client: FlaskClient, fleet: User) -> None:
        assert client.get(f"{ROOT}?address=", headers=HEADERS).status_code == 400

    def test_a_person_lists_none_409(self, client: FlaskClient, person: User) -> None:
        _sign_in(client, person.subject)

        response = client.get(ROOT, headers=HEADERS)

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot list the conversations with Pilot because you do not call as a"
            " service user"
        )

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, service_user: User
    ) -> None:
        _sign_in(client, service_user.subject, roles=())

        assert client.get(ROOT, headers=HEADERS).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.get(ROOT, headers=HEADERS).status_code == 401


class TestSendConversationMessage:
    def test_a_message_to_its_idle_conversation_is_its_next_turn_201(
        self,
        client: FlaskClient,
        session: DbSession,
        fake: ServedFakeController,
        services: Services,
        opened: Project,
        fleet: User,
    ) -> None:
        run_id = _idle(client, session, fake, services)

        response = client.post(
            _messages(run_id), json={"words": "And the bread?"}, headers=HEADERS
        )

        assert response.status_code == 201, response.get_json()
        assert response.get_json() == {
            "conversation": str(run_id),
            "seq": 2,
            "error": None,
        }
        turn = session.scalars(select(Turn).where(Turn.seq == 2)).one()
        assert (turn.session_id, turn.author_user_id, turn.message, turn.words) == (
            run_id,
            fleet.id,
            "And the bread?",
            "And the bread?",
        )
        assert _read(session, run_id).state_code == SessionState.RUNNING

    def test_a_message_while_a_turn_is_in_flight_is_409_and_nothing_is_queued(
        self,
        client: FlaskClient,
        session: DbSession,
        services: Services,
        opened: Project,
        fleet: User,
    ) -> None:
        run_id = uuid.UUID(_open(client).get_json()["id"])

        response = client.post(
            _messages(run_id), json={"words": "And the bread?"}, headers=HEADERS
        )

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot send a message to Pilot in Soup club because a turn of its"
            " conversation is in flight"
        )
        assert _turns(session) == 1

    def test_a_closed_conversation_takes_none_409(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        recipebox: Environment,
        fleet: User,
    ) -> None:
        run = _made(session, opened, recipebox, opener=fleet)
        _closed(session, run, datetime.now(UTC), CloseCause.ENDED)

        response = client.post(
            _messages(run.id), json={"words": "Still there?"}, headers=HEADERS
        )

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot send a message to Pilot in Soup club because its conversation"
            " is closed"
        )
        assert _turns(session) == 1

    def test_under_the_stores_update_none_is_taken_409(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        recipebox: Environment,
        fleet: User,
    ) -> None:
        run = _made(session, opened, recipebox, opener=fleet)
        hold(session)
        session.commit()

        response = client.post(
            _messages(run.id), json={"words": "Still there?"}, headers=HEADERS
        )

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot send a message to Pilot in Soup club because Pilot is updating"
        )
        assert _turns(session) == 1

    @pytest.mark.parametrize(
        "headers", [OTHERS_HEADERS, {}], ids=["another-environment", "no-environment"]
    )
    def test_another_callers_takes_none_and_is_answered_as_an_id_that_never_was_404(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        recipebox: Environment,
        fleet: User,
        headers: dict[str, str],
    ) -> None:
        run = _made(session, opened, recipebox, opener=fleet)
        never = uuid.uuid4()

        anothers = client.post(
            _messages(run.id), json={"words": "Mine now."}, headers=headers
        )
        unknown = client.post(
            _messages(never), json={"words": "Mine now."}, headers=HEADERS
        )

        assert (anothers.status_code, unknown.status_code) == (404, 404)
        assert _refusal(anothers, run.id) == _refusal(unknown, never)
        assert _turns(session) == 1
        assert _read(session, run.id).state_code == SessionState.IDLE

    @pytest.mark.parametrize("body", [{}, {"words": " \n"}], ids=["none", "blank"])
    def test_a_message_without_words_is_400(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        recipebox: Environment,
        fleet: User,
        body: dict[str, str],
    ) -> None:
        run = _made(session, opened, recipebox, opener=fleet)

        response = client.post(_messages(run.id), json=body, headers=HEADERS)

        assert response.status_code == 400
        assert _turns(session) == 1

    def test_a_person_sends_none_409(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        recipebox: Environment,
        service_user: User,
        person: User,
    ) -> None:
        run = _made(session, opened, recipebox, opener=service_user)
        _sign_in(client, person.subject)

        response = client.post(
            _messages(run.id), json={"words": "Let me in."}, headers=HEADERS
        )

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            f"Cannot send a message to Pilot in the conversation {run.id} because"
            " you do not call as a service user"
        )
        assert _turns(session) == 1

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, service_user: User
    ) -> None:
        _sign_in(client, service_user.subject, roles=())

        response = client.post(
            _messages(uuid.uuid4()), json={"words": "Hi"}, headers=HEADERS
        )

        assert response.status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.post(
            _messages(uuid.uuid4()), json={"words": "Hi"}, headers=HEADERS
        )

        assert response.status_code == 401


class TestInterruptConversation:
    def test_it_stops_the_turn_in_flight_and_keeps_the_conversation_200(
        self,
        client: FlaskClient,
        session: DbSession,
        services: Services,
        opened: Project,
        fleet: User,
    ) -> None:
        run_id = uuid.UUID(_open(client).get_json()["id"])
        clear_after_commit_callbacks()

        response = client.post(_interrupt(run_id), headers=HEADERS)

        assert response.status_code == 200, response.get_json()
        body = response.get_json()
        assert (body["id"], body["closed_at"], body["close_cause"]) == (
            str(run_id),
            None,
            None,
        )
        assert _read(session, run_id).state_code == SessionState.STOPPED
        assert _row(session, run_id).closed_at is None

    def test_with_no_turn_in_flight_it_changes_nothing_200(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        recipebox: Environment,
        fleet: User,
    ) -> None:
        run = _made(session, opened, recipebox, opener=fleet)

        response = client.post(_interrupt(run.id), headers=HEADERS)

        assert response.status_code == 200
        assert response.get_json()["in_flight"] is False
        assert _read(session, run.id).state_code == SessionState.IDLE

    @pytest.mark.parametrize(
        "headers", [OTHERS_HEADERS, {}], ids=["another-environment", "no-environment"]
    )
    def test_another_callers_runs_on_and_is_answered_as_an_id_that_never_was_404(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        recipebox: Environment,
        fleet: User,
        headers: dict[str, str],
    ) -> None:
        run = _made(
            session, opened, recipebox, state=SessionState.RUNNING, opener=fleet
        )
        never = uuid.uuid4()

        anothers = client.post(_interrupt(run.id), headers=headers)
        unknown = client.post(_interrupt(never), headers=HEADERS)

        assert (anothers.status_code, unknown.status_code) == (404, 404)
        assert _refusal(anothers, run.id) == _refusal(unknown, never)
        assert _read(session, run.id).state_code == SessionState.RUNNING

    def test_a_person_interrupts_none_409(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        recipebox: Environment,
        service_user: User,
        person: User,
    ) -> None:
        run = _made(
            session, opened, recipebox, state=SessionState.RUNNING, opener=service_user
        )
        _sign_in(client, person.subject)

        response = client.post(_interrupt(run.id), headers=HEADERS)

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            f"Cannot interrupt the conversation {run.id} with Pilot because you do"
            " not call as a service user"
        )
        assert _read(session, run.id).state_code == SessionState.RUNNING

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, service_user: User
    ) -> None:
        _sign_in(client, service_user.subject, roles=())

        response = client.post(_interrupt(uuid.uuid4()), headers=HEADERS)

        assert response.status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.post(_interrupt(uuid.uuid4()), headers=HEADERS)

        assert response.status_code == 401


class TestEndConversation:
    def test_it_closes_the_conversation_ended_200(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        recipebox: Environment,
        fleet: User,
    ) -> None:
        run = _made(session, opened, recipebox, opener=fleet)

        response = client.post(_end(run.id), headers=HEADERS)

        assert response.status_code == 200, response.get_json()
        row = _row(session, run.id)
        assert row.closed_at is not None
        assert row.close_cause_code is CloseCause.ENDED
        body = response.get_json()
        assert (body["id"], body["closed_at"], body["close_cause"]) == (
            str(run.id),
            _stamp(row.closed_at),
            "ended",
        )

    def test_a_turn_in_flight_is_stopped_first(
        self,
        client: FlaskClient,
        session: DbSession,
        services: Services,
        opened: Project,
        fleet: User,
    ) -> None:
        run_id = uuid.UUID(_open(client).get_json()["id"])
        clear_after_commit_callbacks()

        response = client.post(_end(run_id), headers=HEADERS)

        assert response.status_code == 200, response.get_json()
        assert response.get_json()["close_cause"] == "ended"
        assert _read(session, run_id).state_code == SessionState.STOPPED

    def test_one_closed_already_stays_as_it_closed_200(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        recipebox: Environment,
        fleet: User,
    ) -> None:
        run = _made(session, opened, recipebox, opener=fleet)
        closed_at = datetime(2026, 10, 12, 9, 30, tzinfo=UTC)
        _closed(session, run, closed_at, CloseCause.FINISHED)

        response = client.post(_end(run.id), headers=HEADERS)

        assert response.status_code == 200
        body = response.get_json()
        assert (body["closed_at"], body["close_cause"]) == (
            "2026-10-12T09:30:00Z",
            "finished",
        )

    @pytest.mark.parametrize(
        "headers", [OTHERS_HEADERS, {}], ids=["another-environment", "no-environment"]
    )
    def test_another_callers_stays_open_and_is_answered_as_an_id_that_never_was_404(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        recipebox: Environment,
        fleet: User,
        headers: dict[str, str],
    ) -> None:
        run = _made(session, opened, recipebox, opener=fleet)
        never = uuid.uuid4()

        anothers = client.post(_end(run.id), headers=headers)
        unknown = client.post(_end(never), headers=HEADERS)

        assert (anothers.status_code, unknown.status_code) == (404, 404)
        assert _refusal(anothers, run.id) == _refusal(unknown, never)
        assert _row(session, run.id).closed_at is None

    def test_a_person_ends_none_409(
        self,
        client: FlaskClient,
        session: DbSession,
        opened: Project,
        recipebox: Environment,
        service_user: User,
        person: User,
    ) -> None:
        run = _made(session, opened, recipebox, opener=service_user)
        _sign_in(client, person.subject)

        response = client.post(_end(run.id), headers=HEADERS)

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            f"Cannot end the conversation {run.id} with Pilot because you do not"
            " call as a service user"
        )
        assert _row(session, run.id).closed_at is None

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, service_user: User
    ) -> None:
        _sign_in(client, service_user.subject, roles=())

        assert client.post(_end(uuid.uuid4()), headers=HEADERS).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.post(_end(uuid.uuid4()), headers=HEADERS).status_code == 401
