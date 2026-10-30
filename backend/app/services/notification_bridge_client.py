"""Pilot's client of the notification bridge (F94, F134, F142).

The bridge, `pvginkel/Notifications`, shows a person's notifications on their
phone under the bearer of the person's own registration: a submit shows or
updates the notification of a sequence id, a dismiss takes it down, and a
submit with no sequence id is a one-shot, which nothing updates or dismisses.
Its contract is that repo's README.

A call went out, was refused, or got no answer; only one that went out
returns. A `200` says that the body was valid and every channel of the
registration was tried, not that anything was delivered: a channel's error in
it is logged. A submit can take about a minute, so no request thread makes a
call.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any, Literal

import requests
from prometheus_client import Counter
from pydantic import TypeAdapter, ValidationError

from app.core_exceptions import ExternalServiceException
from app.services.health_service import CheckResult, CheckStatus, HealthService

logger = logging.getLogger(__name__)

BridgePriority = Literal["min", "low", "default", "high", "max"]
"""The bridge's priorities, lowest first: a submit above its sequence's
priority alerts, any other updates in place silently (README § Priorities)."""

_CONNECT_TIMEOUT_SECONDS = 10
_CALL_TIMEOUT_SECONDS = 120
"""Above the bridge's slowest answer: a submit makes up to two calls to ntfy
and four to Telegram per chat, each given up after a 10 s stall (README § The
per-channel result)."""
_READINESS_TIMEOUT_SECONDS = 2

_CHANNEL_OK = "ok"
_CHANNEL_RESULTS = TypeAdapter(dict[str, str])


class BridgeCall(StrEnum):
    """A call of the bridge's, as the counter labels it."""

    SUBMIT = "submit"
    DISMISS = "dismiss"
    ONE_SHOT = "one_shot"


class BridgeOutcome(StrEnum):
    """How a call ended: it went out, was refused, or got no answer."""

    SENT = "sent"
    REFUSED = "refused"
    UNANSWERED = "unanswered"


NOTIFICATION_BRIDGE_CALLS_TOTAL = Counter(
    "pilot_notification_bridge_calls_total",
    "Calls to the notification bridge, by call (submit, dismiss, one_shot) and "
    "outcome (sent, refused, unanswered)",
    ["call", "outcome"],
)


class NotificationBridgeFailure(ExternalServiceException):
    """The bridge did not take the call: it refused it, or gave no answer."""

    outcome: BridgeOutcome


class NotificationBridgeRefused(NotificationBridgeFailure):
    """The bridge refused the call, with a 4xx: a token no registration holds
    (`401`), a body it does not take (`400`), a message over its limit (`413`),
    or a path or method it has no route for. A refused call reached no
    channel; `reason` is the bridge's own `error` where it gave one."""

    outcome = BridgeOutcome.REFUSED

    def __init__(self, operation: str, status: int, reason: str) -> None:
        self.status = status
        self.reason = reason
        super().__init__(operation, f"the bridge refused it with {status}: {reason}")


class NotificationBridgeUnanswered(NotificationBridgeFailure):
    """The bridge gave no answer of its own: a connection error, a timeout, a
    5xx, or a status or body the bridge never answers with. A call that timed
    out may still have reached the phone."""

    outcome = BridgeOutcome.UNANSWERED


class NotificationBridgeClient:
    """The notification bridge, each call under one person's bearer."""

    def __init__(self, base_url: str, health_service: HealthService) -> None:
        self._base_url = base_url.rstrip("/")
        # Not critical: Pilot serves its record without the bridge.
        health_service.register_check(
            "notification_bridge", self.check_readiness, critical=False
        )

    def check_readiness(self) -> CheckResult:
        """Readiness check: the bridge answers its `/healthz`, which takes no
        token."""
        response = requests.get(
            f"{self._base_url}/healthz", timeout=_READINESS_TIMEOUT_SECONDS
        )
        if response.status_code != 200:
            return CheckResult(
                CheckStatus.ERROR, f"the bridge answered {response.status_code}"
            )
        return CheckResult(CheckStatus.OK)

    def submit(
        self,
        token: str,
        sequence_id: str,
        *,
        message: str,
        title: str | None = None,
        priority: BridgePriority = "default",
        url: str | None = None,
    ) -> None:
        """Show the notification of `sequence_id`, or update the one shown: in
        place and silently at the same or a lower priority, re-shown and
        alerting at a higher one. The `url` is not kept: each submit carries
        the one the notification links to."""
        self._call(
            BridgeCall.SUBMIT,
            "/v1/submit",
            f"submit notification {sequence_id} to the bridge",
            token,
            {
                "sequence_id": sequence_id,
                "message": message,
                "title": title,
                "priority": priority,
                "url": url,
            },
        )

    def dismiss(self, token: str, sequence_id: str) -> None:
        """Take the notification of `sequence_id` down, which frees the id; a
        sequence id the bridge shows nothing for is taken all the same."""
        self._call(
            BridgeCall.DISMISS,
            "/v1/dismiss",
            f"dismiss notification {sequence_id} at the bridge",
            token,
            {"sequence_id": sequence_id},
        )

    def send_one_shot(
        self,
        token: str,
        *,
        message: str,
        title: str | None = None,
        priority: BridgePriority = "default",
        url: str | None = None,
    ) -> None:
        """Show a notification of its own, which nothing updates or dismisses."""
        self._call(
            BridgeCall.ONE_SHOT,
            "/v1/submit",
            "send a one-shot notification through the bridge",
            token,
            {"message": message, "title": title, "priority": priority, "url": url},
        )

    def _call(
        self,
        call: BridgeCall,
        path: str,
        operation: str,
        token: str,
        body: dict[str, Any],
    ) -> None:
        try:
            self._post(path, operation, token, body)
        except NotificationBridgeFailure as failure:
            NOTIFICATION_BRIDGE_CALLS_TOTAL.labels(
                call=call, outcome=failure.outcome
            ).inc()
            raise
        NOTIFICATION_BRIDGE_CALLS_TOTAL.labels(
            call=call, outcome=BridgeOutcome.SENT
        ).inc()

    def _post(
        self, path: str, operation: str, token: str, body: dict[str, Any]
    ) -> None:
        try:
            response = requests.post(
                f"{self._base_url}{path}",
                json={key: value for key, value in body.items() if value is not None},
                headers={"Authorization": f"Bearer {token}"},
                timeout=(_CONNECT_TIMEOUT_SECONDS, _CALL_TIMEOUT_SECONDS),
                allow_redirects=False,
            )
        except requests.RequestException as error:
            raise NotificationBridgeUnanswered(
                operation, f"the bridge did not answer: {error}"
            ) from error
        if 400 <= response.status_code < 500:
            raise NotificationBridgeRefused(
                operation, response.status_code, _refusal_reason(response)
            )
        if response.status_code != 200:
            raise NotificationBridgeUnanswered(
                operation,
                f"the bridge did not answer: {response.status_code} {response.reason}",
            )
        try:
            channels = _CHANNEL_RESULTS.validate_json(response.content)
        except ValidationError as error:
            raise NotificationBridgeUnanswered(
                operation, "the bridge's 200 is not its per-channel result"
            ) from error
        for channel, result in channels.items():
            if result != _CHANNEL_OK:
                logger.warning(
                    "The bridge took the call to %s, but its channel %s failed: %s",
                    operation,
                    channel,
                    result,
                )


def _refusal_reason(response: requests.Response) -> str:
    """The bridge's `error`, or the status's reason where the answer has none."""
    try:
        body = response.json()
    except requests.JSONDecodeError:
        return response.reason
    error = body.get("error") if isinstance(body, dict) else None
    return error if isinstance(error, str) else response.reason
