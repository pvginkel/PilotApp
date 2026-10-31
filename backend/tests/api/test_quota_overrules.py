"""/api/quota-overrules: a person's overrule of the week's usage halt, the gold
bar's button (F135.2; DB Quota Overrule)."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from dependency_injector import providers
from flask.testing import FlaskClient
from sqlalchemy.orm import Session

from app.models import UsageReading, User, WindowShare
from app.models.reference import UsageWindow
from app.services.container import ServiceContainer
from app.services.sse_connection_manager import SSEConnectionManager
from app.services.usage_halts import UsageWatcher
from app.services.usage_service import UsageService
from tests.support.supervisor import Supervise

OVERRULES = "/api/quota-overrules"

TAKEN_AT = datetime(2026, 10, 6, 18, tzinfo=UTC)


def _week(session: Session, share: float) -> None:
    reading = UsageReading(taken_at=TAKEN_AT, received_at=TAKEN_AT, stale=False)
    session.add(reading)
    session.flush()
    session.add(
        WindowShare(
            reading_id=reading.id,
            window_code=UsageWindow.SEVEN_DAY,
            share=share,
            resets_at=TAKEN_AT + timedelta(days=1),
        )
    )
    session.flush()


def _sign_in(
    client: FlaskClient,
    subject: str = "subject-ada",
    roles: tuple[str, ...] = ("editor",),
) -> None:
    response = client.post(
        "/api/testing/auth/session",
        json={"subject": subject, "name": "Ada Example", "roles": list(roles)},
    )
    assert response.status_code == 201


class _Watcher:
    """The usage watcher, as a made overrule calls it once committed."""

    def __init__(self) -> None:
        self.overruled_calls = 0

    def overruled(self) -> None:
        self.overruled_calls += 1


class _Gate:
    """The session start, as the watcher asks it again and for the nudges
    owed."""

    def __init__(self) -> None:
        self.released = 0
        self.nudged = 0

    def release_held(self) -> None:
        self.released += 1

    def send_nudges(self) -> None:
        self.nudged += 1


@pytest.fixture
def watcher(container: ServiceContainer) -> _Watcher:
    watcher = _Watcher()
    container.usage_watcher.override(providers.Object(watcher))
    return watcher


class TestMakeQuotaOverrule:
    def test_the_allowance_is_made_and_the_weeks_halt_lifts(
        self,
        client: FlaskClient,
        session: Session,
        person: User,
        watcher: _Watcher,
    ) -> None:
        _week(session, 0.91)
        _sign_in(client)

        response = client.post(OVERRULES, json={"kind": "allowance"})

        assert response.status_code == 201
        body = response.get_json()
        assert body == {
            "id": body["id"],
            "kind": "allowance",
            "target": 0.96,
            "made_at": body["made_at"],
        }
        assert client.get("/api/conditions").get_json() == {"conditions": []}
        assert watcher.overruled_calls == 1

    def test_once_committed_every_persons_connections_hear_the_halt_lift(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        supervise: Supervise,
        session: Session,
        person: User,
    ) -> None:
        # The watcher itself, among the request's after-commit callbacks.
        gate = _Gate()
        container.session_start_service.override(providers.Object(gate))
        container.usage_watcher.override(
            providers.Object(
                UsageWatcher(
                    container=container,
                    supervisor=supervise(container)[0],
                    usage_service=UsageService(container=container),
                    usage_halts=container.usage_halts(),
                )
            )
        )
        _week(session, 0.91)
        _sign_in(client)
        manager: SSEConnectionManager = container.sse_connection_manager()
        assert person.subject is not None
        connection = manager.on_connect("ada-1", person.subject)
        try:
            response = client.post(OVERRULES, json={"kind": "allowance"})

            frame = connection.next_frame(timeout=0)
        finally:
            manager.on_disconnect(connection)

        assert response.status_code == 201
        assert frame is not None
        assert json.loads(frame.removeprefix("data: "))["payload"] == {"conditions": []}
        assert (gate.released, gate.nudged) == (1, 1)

    def test_run_out_at_the_second_limit_has_no_target(
        self,
        client: FlaskClient,
        session: Session,
        person: User,
        watcher: _Watcher,
    ) -> None:
        _week(session, 0.98)
        _sign_in(client)

        response = client.post(OVERRULES, json={"kind": "run_out"})

        assert response.status_code == 201
        assert (response.get_json()["kind"], response.get_json()["target"]) == (
            "run_out",
            None,
        )

    def test_while_the_weeks_halt_does_not_hold_it_is_a_conflict(
        self,
        client: FlaskClient,
        session: Session,
        person: User,
        watcher: _Watcher,
    ) -> None:
        _week(session, 0.5)
        _sign_in(client)

        response = client.post(OVERRULES, json={"kind": "allowance"})

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot add the week's allowance because the week's halt does not hold"
        )
        assert watcher.overruled_calls == 0

    def test_while_another_holds_it_is_a_conflict(
        self,
        client: FlaskClient,
        session: Session,
        person: User,
        watcher: _Watcher,
    ) -> None:
        _week(session, 0.91)
        _sign_in(client)
        client.post(OVERRULES, json={"kind": "allowance"})

        response = client.post(OVERRULES, json={"kind": "allowance"})

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot add the week's allowance because an overrule holds already"
        )

    def test_the_kind_the_halt_does_not_offer_is_a_conflict(
        self,
        client: FlaskClient,
        session: Session,
        person: User,
        watcher: _Watcher,
    ) -> None:
        _week(session, 0.91)
        _sign_in(client)

        response = client.post(OVERRULES, json={"kind": "run_out"})

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot run out the week's quota because the week's share is under the "
            "second limit, where the allowance is offered"
        )

    def test_at_the_wall_it_is_a_conflict(
        self,
        client: FlaskClient,
        session: Session,
        person: User,
        watcher: _Watcher,
    ) -> None:
        _week(session, 1.0)
        _sign_in(client)

        response = client.post(OVERRULES, json={"kind": "run_out"})

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot run out the week's quota because the week's share is at the "
            "wall, where no overrule is offered"
        )

    def test_a_caller_without_a_handle_is_a_conflict(
        self, client: FlaskClient, session: Session, watcher: _Watcher
    ) -> None:
        _week(session, 0.91)
        _sign_in(client, subject="subject-newcomer")

        response = client.post(OVERRULES, json={"kind": "allowance"})

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot add the week's allowance because you have not chosen your "
            "handle yet"
        )

    @pytest.mark.parametrize(
        "body", [{"kind": "add_five"}, {}], ids=["a-stale-kind", "no-kind"]
    )
    def test_a_kind_that_is_no_overrules_is_a_bad_request(
        self,
        client: FlaskClient,
        person: User,
        watcher: _Watcher,
        body: dict[str, str],
    ) -> None:
        _sign_in(client)

        assert client.post(OVERRULES, json=body).status_code == 400

    def test_without_editor_it_is_refused(self, client: FlaskClient) -> None:
        _sign_in(client, subject="someone", roles=())

        response = client.post(OVERRULES, json={"kind": "allowance"})

        assert response.status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.post(OVERRULES, json={"kind": "allowance"})

        assert response.status_code == 401
