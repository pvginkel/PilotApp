"""YouTrack's deliveries as the Webhook Triggers app posts them, invented."""

from typing import Any

TOKEN = "an-invented-webhook-token-of-32-chars"
UPDATED = 1792833000000
"""2026-10-24T09:10:00Z, in epoch milliseconds."""


def youtrack_delivery(
    card: str = "ANS-312",
    from_state: str | None = "In Progress",
    to_state: str | None = "Done",
    **changes: Any,
) -> dict[str, Any]:
    """An `issueUpdated` delivery of the Webhook Triggers app's, its card's
    State changed and its summary with it."""
    delivery: dict[str, Any] = {
        "event": "issueUpdated",
        "timestamp": "2026-10-24T09:10:01.250Z",
        "id": card,
        "summary": "The badge's colour",
        "description": "Pick one",
        "project": {"key": "0-7", "name": "Answers", "shortName": "ANS"},
        "updated": UPDATED,
        "updatedBy": {
            "login": "pieter",
            "fullName": "Pieter Example",
            "email": "pieter@example.com",
        },
        "changedFields": [
            {"name": "summary", "oldValue": "The badge", "value": "The badge's colour"},
            {
                "name": "State",
                "oldValue": (
                    None
                    if from_state is None
                    else {"name": from_state, "presentation": from_state}
                ),
                "value": (
                    None
                    if to_state is None
                    else {"name": to_state, "presentation": to_state}
                ),
            },
        ],
    }
    delivery.update(changes)
    return delivery
