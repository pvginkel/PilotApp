"""/api/conditions: the conditions that hold all work, a line each on the gold
bar (UC *The gold bar*; F125; design 2 §13.4)."""

from flask.testing import FlaskClient

from app.services.controller_outage import ControllerOutage

CONDITIONS = "/api/conditions"


class TestGetConditions:
    def test_none_holds_while_the_controller_answers(self, client: FlaskClient) -> None:
        response = client.get(CONDITIONS)

        assert response.status_code == 200
        assert response.get_json() == {"conditions": []}

    def test_the_controller_unreachable_holds_from_its_turn_on(
        self, client: FlaskClient, controller_outage: ControllerOutage
    ) -> None:
        controller_outage.call_unanswered()
        since = controller_outage.since
        assert since is not None

        body = client.get(CONDITIONS).get_json()

        assert body == {
            "conditions": [
                {"code": "outage", "since": since.isoformat().replace("+00:00", "Z")}
            ]
        }

    def test_without_editor_it_is_refused(self, client: FlaskClient) -> None:
        client.post(
            "/api/testing/auth/session", json={"subject": "someone", "roles": []}
        )

        assert client.get(CONDITIONS).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.get(CONDITIONS).status_code == 401
