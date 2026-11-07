"""/api/web-push: what a browser needs to turn its notifications on (F146)."""

from flask.testing import FlaskClient

from app.services.web_push import VapidKey, WebPushService

WEB_PUSH = "/api/web-push"


def _sign_in(client: FlaskClient, roles: tuple[str, ...] = ("editor",)) -> None:
    response = client.post(
        "/api/testing/auth/session",
        json={"subject": "subject-ada", "name": "Ada Example", "roles": list(roles)},
    )
    assert response.status_code == 201


class TestGetWebPush:
    def test_it_answers_the_stages_public_key(
        self, client: FlaskClient, web_push_service: WebPushService, vapid_key: str
    ) -> None:
        _sign_in(client)

        response = client.get(WEB_PUSH)

        assert response.status_code == 200
        assert response.get_json() == {"public_key": VapidKey(vapid_key).public_key}

    def test_with_no_key_it_answers_none(self, client: FlaskClient) -> None:
        _sign_in(client)

        response = client.get(WEB_PUSH)

        assert response.status_code == 200
        assert response.get_json() == {"public_key": None}

    def test_without_editor_it_is_refused(self, client: FlaskClient) -> None:
        _sign_in(client, roles=())

        assert client.get(WEB_PUSH).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.get(WEB_PUSH).status_code == 401
