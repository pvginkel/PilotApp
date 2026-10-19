"""/api/people/self: the signed-in person, and the handle step (F137)."""

from typing import Any

import pytest
from flask.testing import FlaskClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import User
from app.models.reference import UserKind

SELF = "/api/people/self"
HANDLE = "/api/people/self/handle"


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
