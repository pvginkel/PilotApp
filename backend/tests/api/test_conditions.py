"""/api/conditions: the conditions that hold all work, a line each on the gold
bar (UC *The gold bar*; F125, F135.7; design 2 §13.4)."""

from datetime import UTC, datetime, timedelta

from flask.testing import FlaskClient
from sqlalchemy.orm import Session

from app.models import UsageReading, WindowShare
from app.models.reference import UsageWindow
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
                {
                    "code": "outage",
                    "since": since.isoformat().replace("+00:00", "Z"),
                    "share": None,
                    "taken_at": None,
                    "offer": None,
                    "target": None,
                }
            ]
        }

    def test_a_usage_halt_holds_while_the_latest_reading_is_at_its_limit(
        self, client: FlaskClient, session: Session
    ) -> None:
        now = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)
        reading = UsageReading(taken_at=now, received_at=now, stale=False)
        session.add(reading)
        session.flush()
        session.add(
            WindowShare(
                reading_id=reading.id,
                window_code=UsageWindow.SEVEN_DAY,
                share=0.9,
                resets_at=now + timedelta(days=1),
            )
        )
        session.flush()

        body = client.get(CONDITIONS).get_json()

        assert body == {
            "conditions": [
                {
                    "code": "week_halt",
                    "since": "2026-10-08T09:30:00Z",
                    "share": 0.9,
                    "taken_at": "2026-10-08T09:30:00Z",
                    "offer": "allowance",
                    "target": 0.95,
                }
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
