"""/api/people/self: the signed-in person, the handle step (F137), and on
their profile the alarms switch and a browser's subscription (F142.1,
F146)."""

import secrets
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from flask.testing import FlaskClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PushSubscription, User
from app.models.reference import UserKind
from app.services.web_push import point
from app.utils.base64url import b64

# A browser's keys in the form the Push API gives them: a P-256 point and a
# 16-octet secret, base64url, minted for the module.
BROWSER_P256DH = b64(point(ec.generate_private_key(ec.SECP256R1()).public_key()))
BROWSER_AUTH = b64(secrets.token_bytes(16))

SELF = "/api/people/self"
HANDLE = "/api/people/self/handle"
ALARMS = "/api/people/self/alarms"
SUBSCRIPTIONS = "/api/people/self/push-subscriptions"
PHONE = "https://push.example.com/send/phone-of-ada"


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
            "alarms": True,
        }

    def test_a_person_reads_their_alarms_switch_as_turned(
        self, client: FlaskClient, person: User, session: Session
    ) -> None:
        person.alarms = False
        session.flush()
        _sign_in(client, subject="subject-ada", name="Ada Example")

        assert client.get(SELF).get_json()["alarms"] is False

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


def _subscription(endpoint: str = PHONE, **keys: object) -> dict[str, object]:
    return {
        "endpoint": endpoint,
        "expirationTime": None,
        "keys": {"p256dh": BROWSER_P256DH, "auth": BROWSER_AUTH, **keys},
    }


def _subscriptions(session: Session) -> list[tuple[str, str]]:
    session.expire_all()
    return [
        (endpoint, handle)
        for endpoint, handle in session.execute(
            select(PushSubscription.endpoint, User.handle)
            .join(User, User.id == PushSubscription.user_id)
            .order_by(PushSubscription.endpoint)
        )
    ]


class TestSubscribeBrowser:
    def test_the_browsers_subscription_is_written_for_the_person(
        self, client: FlaskClient, session: Session, person: User
    ) -> None:
        _sign_in(client, subject="subject-ada")

        response = client.post(SUBSCRIPTIONS, json=_subscription())

        assert response.status_code == 204
        row = session.scalars(select(PushSubscription)).one()
        assert (row.endpoint, row.user_id, row.p256dh, row.auth) == (
            PHONE,
            person.id,
            BROWSER_P256DH,
            BROWSER_AUTH,
        )

    def test_an_endpoint_another_person_held_becomes_the_callers(
        self, client: FlaskClient, session: Session, person: User
    ) -> None:
        _sign_in(client, subject="subject-ada")
        assert client.post(SUBSCRIPTIONS, json=_subscription()).status_code == 204
        _sign_in(client)
        assert client.post(HANDLE, json={"handle": "ben"}).status_code == 201

        response = client.post(SUBSCRIPTIONS, json=_subscription())

        assert response.status_code == 204
        assert _subscriptions(session) == [(PHONE, "ben")]

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({}, id="missing"),
            pytest.param({"endpoint": PHONE}, id="no-keys"),
            pytest.param(_subscription("push.example.com/send/x"), id="relative"),
            pytest.param(_subscription("ftp://push.example.com/x"), id="not-http"),
            pytest.param(_subscription(p256dh="not-a-key"), id="p256dh-garbage"),
            pytest.param(
                _subscription(p256dh=b64(b"\x04" + b"\x00" * 64)),
                id="p256dh-off-the-curve",
            ),
            pytest.param(_subscription(auth=b64(b"short")), id="auth-short"),
            pytest.param(_subscription(auth="!!"), id="auth-garbage"),
            pytest.param(_subscription(auth=None), id="auth-null"),
        ],
    )
    def test_a_body_that_is_no_browsers_subscription_is_refused(
        self, client: FlaskClient, session: Session, person: User, body: object
    ) -> None:
        _sign_in(client, subject="subject-ada")

        assert client.post(SUBSCRIPTIONS, json=body).status_code == 400
        assert _subscriptions(session) == []

    def test_before_the_handle_it_is_refused(
        self, client: FlaskClient, session: Session
    ) -> None:
        _sign_in(client)

        response = client.post(SUBSCRIPTIONS, json=_subscription())

        assert response.status_code == 409
        assert _error(response) == (
            "Cannot turn your notifications on in this browser because you have "
            "not chosen your handle yet"
        )
        assert _subscriptions(session) == []

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, person: User
    ) -> None:
        _sign_in(client, subject="subject-ada", roles=())

        assert client.post(SUBSCRIPTIONS, json=_subscription()).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.post(SUBSCRIPTIONS, json=_subscription()).status_code == 401


class TestUnsubscribeBrowser:
    def test_the_persons_subscription_of_the_endpoint_is_deleted(
        self, client: FlaskClient, session: Session, person: User
    ) -> None:
        _sign_in(client, subject="subject-ada")
        other = "https://push.example.org/wpush/desktop-of-ada"
        client.post(SUBSCRIPTIONS, json=_subscription())
        client.post(SUBSCRIPTIONS, json=_subscription(other))

        response = client.delete(SUBSCRIPTIONS, query_string={"endpoint": PHONE})

        assert response.status_code == 204
        assert _subscriptions(session) == [(other, "ada")]

    def test_another_persons_subscription_of_the_endpoint_stays(
        self, client: FlaskClient, session: Session, person: User
    ) -> None:
        _sign_in(client, subject="subject-ada")
        client.post(SUBSCRIPTIONS, json=_subscription())
        _sign_in(client)
        assert client.post(HANDLE, json={"handle": "ben"}).status_code == 201

        response = client.delete(SUBSCRIPTIONS, query_string={"endpoint": PHONE})

        assert response.status_code == 204
        assert _subscriptions(session) == [(PHONE, "ada")]

    def test_an_endpoint_the_person_does_not_hold_is_nothing_to_delete(
        self, client: FlaskClient, person: User
    ) -> None:
        _sign_in(client, subject="subject-ada")

        response = client.delete(SUBSCRIPTIONS, query_string={"endpoint": PHONE})

        assert response.status_code == 204

    @pytest.mark.parametrize(
        "query",
        [
            pytest.param({}, id="missing"),
            pytest.param({"endpoint": "push.example.com/x"}, id="relative"),
        ],
    )
    def test_a_query_with_no_endpoint_is_refused(
        self, client: FlaskClient, person: User, query: dict[str, str]
    ) -> None:
        _sign_in(client, subject="subject-ada")

        assert client.delete(SUBSCRIPTIONS, query_string=query).status_code == 400

    def test_before_the_handle_it_is_refused(self, client: FlaskClient) -> None:
        _sign_in(client)

        response = client.delete(SUBSCRIPTIONS, query_string={"endpoint": PHONE})

        assert response.status_code == 409
        assert _error(response) == (
            "Cannot turn your notifications off in this browser because you have "
            "not chosen your handle yet"
        )

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, person: User
    ) -> None:
        _sign_in(client, subject="subject-ada", roles=())

        response = client.delete(SUBSCRIPTIONS, query_string={"endpoint": PHONE})

        assert response.status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.delete(SUBSCRIPTIONS, query_string={"endpoint": PHONE})

        assert response.status_code == 401
