"""/api/people/self: the signed-in person, the handle step (F137), and on
their profile the notification token and the alarms switch (F134, F134.1,
F142.1; DB decision 17)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import scoped_session
from app.models import Alarm, Project, ProjectMember, User
from app.models.reference import Condition, NotificationPriority, UserKind
from app.services.container import ServiceContainer
from app.services.notification_settings_service import ONE_SHOT_MESSAGE
from tests.support.fake_notification_bridge import (
    ServedFakeNotificationBridge,
    bridge_client_of,
)
from tests.support.supervisor import wait_until

SELF = "/api/people/self"
HANDLE = "/api/people/self/handle"
TOKEN = "/api/people/self/notification-token"
ALARMS = "/api/people/self/alarms"
ADA_TOKEN = "token-of-ada"


def _sign_in(
    client: FlaskClient,
    subject: str = "subject-ben",
    name: str | None = "Ben Example",
    email: str | None = "ben@example.com",
    roles: tuple[str, ...] = ("editor",),
) -> None:
    response = client.post(
        "/api/testing/auth/session",
        json={"subject": subject, "name": name, "email": email, "roles": list(roles)},
    )
    assert response.status_code == 201


def _people(session: Session) -> int:
    return session.scalar(
        select(func.count()).select_from(User).where(User.kind_code == UserKind.PERSON)
    )


def _row(session: Session, subject: str) -> User:
    return session.scalars(select(User).where(User.subject == subject)).one()


def _error(response: Any) -> str:
    return response.get_json()["error"]


class TestGetSelf:
    def test_a_first_sign_in_has_the_prefill_and_no_handle(
        self, client: FlaskClient, session: Session
    ) -> None:
        _sign_in(client)

        response = client.get(SELF)

        assert response.status_code == 200
        assert response.get_json() == {
            "handle": None,
            "handle_prefill": "ben",
            "name": "Ben Example",
            "initials": "BE",
            "avatar_slot": None,
            "notification_token_set": None,
            "alarms": None,
        }
        assert _people(session) == 0

    def test_a_token_without_a_name_has_an_empty_prefill(
        self, client: FlaskClient
    ) -> None:
        _sign_in(client, name=None)

        assert client.get(SELF).get_json() == {
            "handle": None,
            "handle_prefill": "",
            "name": None,
            "initials": None,
            "avatar_slot": None,
            "notification_token_set": None,
            "alarms": None,
        }

    def test_the_local_user_goes_through_the_same_step(
        self, client: FlaskClient
    ) -> None:
        """With OIDC off and no session, the caller is the template's local admin."""
        assert client.get(SELF).get_json() == {
            "handle": None,
            "handle_prefill": "local",
            "name": "Local Admin",
            "initials": "LA",
            "avatar_slot": None,
            "notification_token_set": None,
            "alarms": None,
        }

    def test_a_person_reads_their_row(self, client: FlaskClient, person: User) -> None:
        _sign_in(client, subject="subject-ada", name="Ada Example")

        response = client.get(SELF)

        assert response.status_code == 200
        assert response.get_json() == {
            "handle": "ada",
            "handle_prefill": None,
            "name": "Ada Example",
            "initials": "AE",
            "avatar_slot": 1,
            "notification_token_set": False,
            "alarms": True,
        }

    def test_a_later_sign_in_refreshes_the_row(
        self, client: FlaskClient, person: User
    ) -> None:
        _sign_in(
            client, subject="subject-ada", name="Ada Lovelace", email="ada@example.org"
        )

        body = client.get(SELF).get_json()

        assert (body["name"], body["initials"]) == ("Ada Lovelace", "AL")
        assert (person.name, person.email) == ("Ada Lovelace", "ada@example.org")
        assert person.last_seen_at is not None

    def test_a_later_sign_in_without_a_name_keeps_the_records(
        self, client: FlaskClient, person: User
    ) -> None:
        _sign_in(client, subject="subject-ada", name=None)

        assert client.get(SELF).get_json()["name"] == "Ada Example"
        assert person.name == "Ada Example"

    def test_without_editor_it_is_refused(self, client: FlaskClient) -> None:
        _sign_in(client, roles=())

        assert client.get(SELF).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.get(SELF).status_code == 401


class TestChooseHandle:
    def test_the_handle_puts_the_person_on_the_record(
        self, client: FlaskClient, session: Session
    ) -> None:
        _sign_in(client)

        response = client.post(HANDLE, json={"handle": "ben"})

        assert response.status_code == 201
        assert response.get_json() == {
            "handle": "ben",
            "handle_prefill": None,
            "name": "Ben Example",
            "initials": "BE",
            "avatar_slot": 1,
            "notification_token_set": False,
            "alarms": True,
        }
        person = _row(session, "subject-ben")
        assert (person.handle, person.email) == ("ben", "ben@example.com")
        assert client.get(SELF).get_json()["handle"] == "ben"

    def test_without_a_name_the_handle_is_the_name(
        self, client: FlaskClient, session: Session
    ) -> None:
        _sign_in(client, name=None)

        body = client.post(HANDLE, json={"handle": "ben"}).get_json()

        assert (body["name"], body["initials"]) == ("ben", "B")
        assert _row(session, "subject-ben").name == "ben"

    def test_the_second_person_takes_the_next_slot(
        self, client: FlaskClient, person: User
    ) -> None:
        _sign_in(client)

        assert (
            client.post(HANDLE, json={"handle": "ben"}).get_json()["avatar_slot"] == 2
        )

    def test_a_handle_out_of_the_pattern_is_refused_with_its_reason(
        self, client: FlaskClient, session: Session
    ) -> None:
        _sign_in(client)

        response = client.post(HANDLE, json={"handle": "Ben"})

        assert response.status_code == 400
        assert _error(response) == (
            "Cannot choose the handle 'Ben' because a handle holds only lower-case "
            "letters, digits and hyphens"
        )
        assert _people(session) == 0

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({}, id="missing"),
            pytest.param({"handle": None}, id="null"),
            pytest.param({"handle": 7}, id="not-a-string"),
        ],
    )
    def test_a_request_without_a_handle_is_refused(
        self, client: FlaskClient, session: Session, body: dict[str, Any]
    ) -> None:
        _sign_in(client)

        assert client.post(HANDLE, json=body).status_code == 400
        assert _people(session) == 0

    def test_agent_is_refused(self, client: FlaskClient, session: Session) -> None:
        _sign_in(client)

        response = client.post(HANDLE, json={"handle": "agent"})

        assert response.status_code == 409
        assert (
            _error(response) == "Cannot choose the handle 'agent' because it is Pilot's"
        )
        assert _people(session) == 0

    def test_another_persons_handle_is_refused(
        self, client: FlaskClient, person: User, session: Session
    ) -> None:
        _sign_in(client)

        response = client.post(HANDLE, json={"handle": "ada"})

        assert response.status_code == 409
        assert _error(response) == (
            "Cannot choose the handle 'ada' because another person has it"
        )
        assert _people(session) == 1

    def test_the_handle_never_changes(self, client: FlaskClient, person: User) -> None:
        _sign_in(client, subject="subject-ada")

        response = client.post(HANDLE, json={"handle": "ada-lovelace"})

        assert response.status_code == 409
        assert _error(response) == (
            "Cannot choose the handle 'ada-lovelace' because your handle is 'ada' "
            "already, and a handle never changes"
        )
        assert client.get(SELF).get_json()["handle"] == "ada"

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, session: Session
    ) -> None:
        _sign_in(client, roles=())

        assert client.post(HANDLE, json={"handle": "ben"}).status_code == 403
        assert _people(session) == 0

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient, session: Session
    ) -> None:
        assert oidc_client.post(HANDLE, json={"handle": "ben"}).status_code == 401
        assert _people(session) == 0


def _seal(container: ServiceContainer, token: str) -> str:
    return container.notification_token_cipher().seal(token)


class TestGetSelfNotificationSettings:
    def test_a_saved_token_reads_as_set_and_is_never_answered(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        person: User,
        session: Session,
    ) -> None:
        person.notification_token = _seal(container, ADA_TOKEN)
        person.alarms = False
        session.flush()
        _sign_in(client, subject="subject-ada", name="Ada Example")

        response = client.get(SELF)

        assert response.get_json()["notification_token_set"] is True
        assert response.get_json()["alarms"] is False
        assert ADA_TOKEN not in response.get_data(as_text=True)
        assert person.notification_token not in response.get_data(as_text=True)


class TestSaveNotificationToken:
    """The answers a save gives at once, before any task; the session app
    has no bridge."""

    @pytest.mark.parametrize(
        "token",
        [
            pytest.param("", id="empty"),
            pytest.param("token of ada", id="space"),
            pytest.param("token-of-ada\r\nX-Injected: 1", id="line-break"),
            pytest.param("token-of-ada\u200b", id="zero-width-space"),
        ],
    )
    def test_a_token_that_is_not_visible_ascii_is_refused(
        self, client: FlaskClient, person: User, token: str
    ) -> None:
        _sign_in(client, subject="subject-ada")

        response = client.put(TOKEN, json={"token": token})

        assert response.status_code == 400
        assert _error(response) == (
            "Cannot save your notification token because a token holds only "
            "visible ASCII characters, with no spaces or line breaks"
        )
        assert person.notification_token is None

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({}, id="missing"),
            pytest.param({"token": None}, id="null"),
            pytest.param({"token": 7}, id="not-a-string"),
        ],
    )
    def test_a_request_without_a_token_is_refused(
        self, client: FlaskClient, person: User, body: dict[str, Any]
    ) -> None:
        _sign_in(client, subject="subject-ada")

        assert client.put(TOKEN, json=body).status_code == 400
        assert person.notification_token is None

    def test_with_no_bridge_it_is_refused(
        self, client: FlaskClient, person: User
    ) -> None:
        _sign_in(client, subject="subject-ada")

        response = client.put(TOKEN, json={"token": ADA_TOKEN})

        assert response.status_code == 409
        assert _error(response) == (
            "Cannot save your notification token because no notification bridge "
            "is configured"
        )
        assert person.notification_token is None

    def test_before_the_handle_it_is_refused(self, client: FlaskClient) -> None:
        _sign_in(client)

        response = client.put(TOKEN, json={"token": ADA_TOKEN})

        assert response.status_code == 409
        assert _error(response) == (
            "Cannot save your notification token because you have not chosen "
            "your handle yet"
        )

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, person: User
    ) -> None:
        _sign_in(client, subject="subject-ada", roles=())

        assert client.put(TOKEN, json={"token": ADA_TOKEN}).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.put(TOKEN, json={"token": ADA_TOKEN}).status_code == 401


@pytest.fixture
def bridged(
    committed_app: Flask, fake_notification_bridge: ServedFakeNotificationBridge
) -> Iterator[FlaskClient]:
    """A client of an app on a database of its own, whose bridge is the fake,
    which has Ada's registration; signed in as Ada, who chose her handle."""
    container = committed_app.container
    bridge_client_of(container, fake_notification_bridge)
    container.app_config.override(
        container.app_config().model_copy(
            update={"notification_bridge_url": fake_notification_bridge.url}
        )
    )
    fake_notification_bridge.add_registration("ada", ADA_TOKEN)
    with committed_app.test_client() as client:
        _sign_in(client, subject="subject-ada", name="Ada Example")
        assert client.post(HANDLE, json={"handle": "ada"}).status_code == 201
        yield client


def _finished(client: FlaskClient, task_id: str) -> dict[str, Any]:
    """The save's task, as its caller reads it, once it completed or failed."""

    def status() -> dict[str, Any]:
        response = client.get(f"/api/tasks/{task_id}/status")
        assert response.status_code == 200
        return response.get_json()

    wait_until(
        lambda: status()["status"] in ("completed", "failed"),
        "the save's task finished",
    )
    return status()


def _held(app: Flask) -> str | None:
    """Ada's token, as committed, opened."""
    container: ServiceContainer = app.container
    with scoped_session(container) as db:
        person = db.scalars(select(User).where(User.handle == "ada")).one()
        return container.notification_token_cipher().open(person)


class TestSaveNotificationTokenTask:
    def test_the_save_is_a_task_of_the_callers_that_stores_the_token_after_its_one_shot(
        self,
        committed_app: Flask,
        bridged: FlaskClient,
        fake_notification_bridge: ServedFakeNotificationBridge,
    ) -> None:
        response = bridged.put(TOKEN, json={"token": ADA_TOKEN})

        assert response.status_code == 202
        assert set(response.get_json()) == {"task_id", "status"}
        assert response.get_json()["status"] == "pending"
        task = _finished(bridged, response.get_json()["task_id"])
        assert task["status"] == "completed"
        assert task["subject"] == "subject-ada"
        assert task["result"]["notification_token_set"] is True
        assert ADA_TOKEN not in str(task)
        assert [shot.message for shot in fake_notification_bridge.one_shots("ada")] == [
            ONE_SHOT_MESSAGE
        ]
        assert _held(committed_app) == ADA_TOKEN
        assert bridged.get(SELF).get_json()["notification_token_set"] is True

    def test_a_token_the_bridge_refuses_fails_the_save_with_its_reason(
        self,
        committed_app: Flask,
        bridged: FlaskClient,
        fake_notification_bridge: ServedFakeNotificationBridge,
    ) -> None:
        response = bridged.put(TOKEN, json={"token": "token-of-nobody"})

        task = _finished(bridged, response.get_json()["task_id"])
        assert task["status"] == "failed"
        assert task["error"].endswith(
            "the bridge refused it with 401: unknown bearer token"
        )
        assert _held(committed_app) is None
        assert bridged.get(SELF).get_json()["notification_token_set"] is False


def _standing_membership(
    session: Session, project: Project, person: User
) -> ProjectMember:
    sent = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
    member = ProjectMember(
        project_id=project.id,
        user_id=person.id,
        joined_at=sent,
        notification_priority_code=NotificationPriority.DEFAULT,
        notification_text="Not started",
        notification_url=f"https://pilot.example.com/projects/{project.id}",
        notification_sent_at=sent,
    )
    session.add(member)
    session.flush()
    return member


def _standing_alarm(session: Session, person: User) -> Alarm:
    alarm = Alarm(
        user_id=person.id,
        condition_code=Condition.WEEK_HALT,
        standing=True,
        sent_at=datetime(2026, 10, 30, 9, 0, tzinfo=UTC),
    )
    session.add(alarm)
    session.flush()
    return alarm


class TestClearNotificationToken:
    def test_the_token_is_gone_at_once_and_what_stands_reads_dismissed(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        person: User,
        project: Project,
        session: Session,
    ) -> None:
        person.notification_token = _seal(container, ADA_TOKEN)
        member = _standing_membership(session, project, person)
        alarm = _standing_alarm(session, person)
        _sign_in(client, subject="subject-ada", name="Ada Example")

        response = client.delete(TOKEN)

        assert response.status_code == 200
        assert response.get_json()["notification_token_set"] is False
        session.refresh(person)
        session.refresh(member)
        session.refresh(alarm)
        assert person.notification_token is None
        assert (
            member.notification_priority_code,
            member.notification_text,
            member.notification_url,
            member.notification_owed_at,
        ) == (None, None, None, None)
        assert (alarm.standing, alarm.owed_at) == (False, None)

    def test_with_no_token_there_is_nothing_to_clear(
        self, client: FlaskClient, person: User
    ) -> None:
        _sign_in(client, subject="subject-ada")

        response = client.delete(TOKEN)

        assert response.status_code == 200
        assert response.get_json()["notification_token_set"] is False

    def test_before_the_handle_it_is_refused(self, client: FlaskClient) -> None:
        _sign_in(client)

        response = client.delete(TOKEN)

        assert response.status_code == 409
        assert _error(response) == (
            "Cannot clear your notification token because you have not chosen "
            "your handle yet"
        )

    def test_a_token_the_apps_key_does_not_open_is_refused(
        self, client: FlaskClient, person: User, session: Session
    ) -> None:
        person.notification_token = "not-a-ciphertext"
        session.flush()
        _sign_in(client, subject="subject-ada")

        response = client.delete(TOKEN)

        assert response.status_code == 409
        assert _error(response) == (
            "Cannot open the notification token of user ada because the app's "
            "SECRET_KEY does not open its ciphertext"
        )

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, person: User
    ) -> None:
        _sign_in(client, subject="subject-ada", roles=())

        assert client.delete(TOKEN).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.delete(TOKEN).status_code == 401


class TestSwitchAlarms:
    def test_off_and_on_again(
        self, client: FlaskClient, person: User, session: Session
    ) -> None:
        _sign_in(client, subject="subject-ada")

        off = client.put(ALARMS, json={"alarms": False})

        assert off.status_code == 200
        assert off.get_json()["alarms"] is False
        session.refresh(person)
        assert person.alarms is False

        on = client.put(ALARMS, json={"alarms": True})

        assert on.get_json()["alarms"] is True
        session.refresh(person)
        assert person.alarms is True

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({}, id="missing"),
            pytest.param({"alarms": None}, id="null"),
            pytest.param({"alarms": "maybe"}, id="not-a-switch"),
            pytest.param({"alarms": 7}, id="a-number"),
        ],
    )
    def test_a_request_without_a_switch_is_refused(
        self, client: FlaskClient, person: User, body: dict[str, Any]
    ) -> None:
        _sign_in(client, subject="subject-ada")

        assert client.put(ALARMS, json=body).status_code == 400
        assert person.alarms is True

    def test_before_the_handle_it_is_refused(self, client: FlaskClient) -> None:
        _sign_in(client)

        response = client.put(ALARMS, json={"alarms": False})

        assert response.status_code == 409
        assert _error(response) == (
            "Cannot turn your alarms switch because you have not chosen your handle yet"
        )

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, person: User
    ) -> None:
        _sign_in(client, subject="subject-ada", roles=())

        assert client.put(ALARMS, json={"alarms": False}).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.put(ALARMS, json={"alarms": False}).status_code == 401
