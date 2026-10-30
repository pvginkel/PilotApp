"""Pilot's client of the notification bridge, against the bridge's fake (the Q1
ruling)."""

import logging
import threading
from collections.abc import Callable, Generator

import pytest
import requests
from flask import Flask
from werkzeug.serving import make_server

from app.services import notification_bridge_client as bridge_module
from app.services.container import ServiceContainer
from app.services.fake_notification_bridge import FakeNotification
from app.services.health_service import CheckStatus, HealthService
from app.services.notification_bridge_client import (
    NOTIFICATION_BRIDGE_CALLS_TOTAL,
    BridgeOutcome,
    NotificationBridgeClient,
    NotificationBridgeRefused,
    NotificationBridgeUnanswered,
)
from tests.support.fake_notification_bridge import ServedFakeNotificationBridge
from tests.support.supervisor import metric_value, wait_until

TOKEN = "invented-ada-token"
URL = "https://pilot.example.invalid/projects/1"

Call = Callable[[NotificationBridgeClient, str], None]

CALLS: list[tuple[str, Call]] = [
    ("submit", lambda client, token: client.submit(token, "project-1", message="m")),
    ("dismiss", lambda client, token: client.dismiss(token, "project-1")),
    ("one_shot", lambda client, token: client.send_one_shot(token, message="m")),
]
CALL_IDS = [name for name, _ in CALLS]


@pytest.fixture
def bridge(
    fake_notification_bridge: ServedFakeNotificationBridge,
) -> ServedFakeNotificationBridge:
    """The fake, with Ada's registration under ``TOKEN``."""
    fake_notification_bridge.add_registration("ada", TOKEN)
    return fake_notification_bridge


@pytest.fixture
def client(
    bridge: ServedFakeNotificationBridge,
    notification_bridge_client: NotificationBridgeClient,
) -> NotificationBridgeClient:
    return notification_bridge_client


def _client_on(container: ServiceContainer, base_url: str) -> NotificationBridgeClient:
    return NotificationBridgeClient(
        base_url,
        HealthService(container.lifecycle_coordinator(), container.config()),
    )


@pytest.fixture
def not_the_bridge() -> Generator[str]:
    """A server that answers every call `200` with a page of its own."""

    def page(environ: object, start_response: Callable[..., object]) -> list[bytes]:
        start_response("200 OK", [("Content-Type", "text/html")])
        return [b"<html>Welcome</html>"]

    server = make_server("127.0.0.1", 0, page, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class TestNotificationBridgeClient:
    def test_a_submit_shows_the_notification_of_its_sequence_id(
        self, bridge: ServedFakeNotificationBridge, client: NotificationBridgeClient
    ) -> None:
        client.submit(
            TOKEN,
            "project-1",
            message="Decision waiting: **Schema**",
            title="Example",
            priority="high",
            url=URL,
        )

        assert bridge.shown("ada") == {
            "project-1": FakeNotification(
                "project-1",
                "high",
                "Example",
                "Decision waiting: **Schema**",
                URL,
                True,
            )
        }

    def test_a_submit_sends_no_title_or_url_it_has_none_of_at_default(
        self, bridge: ServedFakeNotificationBridge, client: NotificationBridgeClient
    ) -> None:
        client.submit(TOKEN, "project-1", message="Running")

        assert bridge.shown("ada")["project-1"] == FakeNotification(
            "project-1", "default", None, "Running", None, True
        )

    def test_a_submit_under_the_same_sequence_id_updates_it(
        self, bridge: ServedFakeNotificationBridge, client: NotificationBridgeClient
    ) -> None:
        client.submit(TOKEN, "project-1", message="1 waiting", priority="default")
        client.submit(TOKEN, "project-1", message="Running", priority="min", url=URL)

        assert bridge.shown("ada") == {
            "project-1": FakeNotification(
                "project-1", "min", None, "Running", URL, False
            )
        }

    def test_a_dismiss_takes_the_notification_down(
        self, bridge: ServedFakeNotificationBridge, client: NotificationBridgeClient
    ) -> None:
        client.submit(TOKEN, "project-1", message="Running")
        client.submit(TOKEN, "project-2", message="Draft")

        client.dismiss(TOKEN, "project-1")

        assert list(bridge.shown("ada")) == ["project-2"]

    def test_a_one_shot_shows_a_notification_of_its_own(
        self, bridge: ServedFakeNotificationBridge, client: NotificationBridgeClient
    ) -> None:
        client.send_one_shot(TOKEN, message="Pilot will notify you here", title="Pilot")

        assert bridge.one_shots("ada") == [
            FakeNotification(
                None, "default", "Pilot", "Pilot will notify you here", None, True
            )
        ]
        assert bridge.shown("ada") == {}

    @pytest.mark.parametrize("call", [call for _, call in CALLS], ids=CALL_IDS)
    def test_an_unknown_token_is_refused(
        self,
        bridge: ServedFakeNotificationBridge,
        client: NotificationBridgeClient,
        call: Call,
    ) -> None:
        with pytest.raises(NotificationBridgeRefused) as refused:
            call(client, "invented-unknown-token")

        assert (refused.value.status, refused.value.reason) == (
            401,
            "unknown bearer token",
        )
        assert refused.value.outcome is BridgeOutcome.REFUSED
        assert "invented-unknown-token" not in str(refused.value)
        assert bridge.calls("ada") == []

    def test_a_refusal_says_what_was_refused_and_why(
        self, client: NotificationBridgeClient
    ) -> None:
        with pytest.raises(NotificationBridgeRefused) as refused:
            client.submit(TOKEN, "project-1", message="m", url="/projects/1")

        assert str(refused.value) == (
            "Cannot submit notification project-1 to the bridge because external "
            "service failed: the bridge refused it with 400: url must be an "
            "absolute http or https URL"
        )

    def test_a_message_over_the_limit_is_refused_with_413(
        self, bridge: ServedFakeNotificationBridge, client: NotificationBridgeClient
    ) -> None:
        with pytest.raises(NotificationBridgeRefused) as refused:
            client.send_one_shot(TOKEN, message="m" * 4097)

        assert (refused.value.status, refused.value.reason) == (
            413,
            "message is 4097 characters, over the limit of 4096",
        )
        assert bridge.one_shots("ada") == []

    def test_a_path_the_bridge_has_no_route_for_is_refused_by_its_reason(
        self, container: ServiceContainer, bridge: ServedFakeNotificationBridge
    ) -> None:
        client = _client_on(container, f"{bridge.url}/nowhere")

        with pytest.raises(NotificationBridgeRefused) as refused:
            client.dismiss(TOKEN, "project-1")

        assert (refused.value.status, refused.value.reason) == (404, "NOT FOUND")

    @pytest.mark.parametrize("answer", ["none", "error"])
    @pytest.mark.parametrize("call", [call for _, call in CALLS], ids=CALL_IDS)
    def test_a_bridge_that_does_not_answer_leaves_the_call_unanswered(
        self,
        bridge: ServedFakeNotificationBridge,
        client: NotificationBridgeClient,
        call: Call,
        answer: str,
    ) -> None:
        bridge.unreachable(answer=answer)

        with pytest.raises(NotificationBridgeUnanswered) as unanswered:
            call(client, TOKEN)

        assert unanswered.value.outcome is BridgeOutcome.UNANSWERED
        assert str(unanswered.value).startswith("Cannot ")
        assert TOKEN not in str(unanswered.value)
        assert bridge.calls("ada") == []

    def test_a_bridge_that_is_not_there_leaves_the_call_unanswered(
        self, container: ServiceContainer
    ) -> None:
        unbound = make_server("127.0.0.1", 0, lambda e, s: [])
        url = f"http://127.0.0.1:{unbound.server_port}"
        unbound.server_close()
        client = _client_on(container, url)

        with pytest.raises(NotificationBridgeUnanswered, match="did not answer"):
            client.submit(TOKEN, "project-1", message="m")

    def test_a_200_that_is_not_the_per_channel_result_is_unanswered(
        self, container: ServiceContainer, not_the_bridge: str
    ) -> None:
        client = _client_on(container, not_the_bridge)

        with pytest.raises(
            NotificationBridgeUnanswered, match="not its per-channel result"
        ):
            client.submit(TOKEN, "project-1", message="m")

    def test_a_call_that_times_out_is_unanswered_and_may_land_later(
        self,
        bridge: ServedFakeNotificationBridge,
        client: NotificationBridgeClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(bridge_module, "_CALL_TIMEOUT_SECONDS", 0.2)
        bridge.unreachable(answer="stall")

        with pytest.raises(NotificationBridgeUnanswered, match="did not answer"):
            client.submit(TOKEN, "project-1", message="m")
        bridge.unreachable(on=False)

        wait_until(lambda: "project-1" in bridge.shown("ada"), "the submit shown")

    def test_the_timeout_sits_above_the_bridges_slowest_submit(self) -> None:
        # One chat: two ntfy calls and four Telegram calls, each up to 10 s.
        assert bridge_module._CALL_TIMEOUT_SECONDS > 6 * 10

    def test_a_channels_error_is_logged_and_the_call_went_out(
        self,
        bridge: ServedFakeNotificationBridge,
        client: NotificationBridgeClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        bridge.channel_error("ada", "publish: HTTP 500: down")
        sent_before = metric_value(
            NOTIFICATION_BRIDGE_CALLS_TOTAL, call="submit", outcome="sent"
        )

        with caplog.at_level(logging.WARNING, logger=bridge_module.__name__):
            client.submit(TOKEN, "project-1", message="m")

        assert [record.getMessage() for record in caplog.records] == [
            "The bridge took the call to submit notification project-1 to the "
            "bridge, but its channel ntfy failed: error: publish: HTTP 500: down"
        ]
        assert (
            metric_value(NOTIFICATION_BRIDGE_CALLS_TOTAL, call="submit", outcome="sent")
            == sent_before + 1
        )

    def test_a_call_every_channel_took_logs_nothing(
        self, client: NotificationBridgeClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG, logger=bridge_module.__name__):
            client.submit(TOKEN, "project-1", message="m")

        assert [r for r in caplog.records if r.name == bridge_module.__name__] == []

    @pytest.mark.parametrize(("name", "call"), CALLS, ids=CALL_IDS)
    def test_every_call_is_counted_by_its_outcome(
        self,
        bridge: ServedFakeNotificationBridge,
        client: NotificationBridgeClient,
        name: str,
        call: Call,
    ) -> None:
        def counted() -> dict[str, float]:
            return {
                outcome: metric_value(
                    NOTIFICATION_BRIDGE_CALLS_TOTAL, call=name, outcome=outcome
                )
                for outcome in BridgeOutcome
            }

        before = counted()

        call(client, TOKEN)
        with pytest.raises(NotificationBridgeRefused):
            call(client, "invented-unknown-token")
        with pytest.raises(NotificationBridgeRefused):
            call(client, "invented-unknown-token")
        bridge.unreachable()
        for _ in range(3):
            with pytest.raises(NotificationBridgeUnanswered):
                call(client, TOKEN)

        after = counted()
        assert {outcome: after[outcome] - before[outcome] for outcome in after} == {
            "sent": 1,
            "refused": 2,
            "unanswered": 3,
        }


class TestNotificationBridgeReadiness:
    def test_it_registers_a_check_that_is_not_critical(
        self,
        app: Flask,
        container: ServiceContainer,
        bridge: ServedFakeNotificationBridge,
    ) -> None:
        health = HealthService(container.lifecycle_coordinator(), container.config())
        NotificationBridgeClient(bridge.url, health)

        with app.app_context():
            body, _ = health.check_readyz()

        assert body["checks"]["notification_bridge"] == {
            "status": "ok",
            "critical": False,
        }

    def test_the_check_passes_while_the_bridge_answers_its_healthz(
        self, client: NotificationBridgeClient
    ) -> None:
        assert client.check_readiness().status is CheckStatus.OK

    def test_the_check_fails_on_an_answer_other_than_200(
        self, bridge: ServedFakeNotificationBridge, client: NotificationBridgeClient
    ) -> None:
        bridge.unreachable(answer="error")

        result = client.check_readiness()

        assert (result.status, result.detail) == (
            CheckStatus.ERROR,
            "the bridge answered 500",
        )

    def test_the_check_raises_when_the_bridge_does_not_answer(
        self, bridge: ServedFakeNotificationBridge, client: NotificationBridgeClient
    ) -> None:
        bridge.unreachable()

        with pytest.raises(requests.ConnectionError):
            client.check_readiness()
