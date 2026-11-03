"""Card transitions from the tracker (F136): a delivery posted to
`/api/tracker-events/<tracker>`, admitted and read by that tracker's adapter
and matched against the open card waits inside the request (F136.2), so that
the reply says how many waits fired. Nothing is read from the tracker
(F136.3): no poll, no recovery of a missed delivery, no dedupe of a
redelivered one.

`youtrack` is the one tracker: YouTrack's Webhook Triggers app posts every
card update, its `issueUpdated` event, with the instance's webhook token in
`X-YouTrack-Token`; a delivery with no `State` change is answered and dropped.
"""

import hmac
import logging
from datetime import UTC, datetime
from typing import Any, Protocol

from prometheus_client import Counter
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel
from werkzeug.datastructures import Headers

from app.app_config import AppSettings
from app.exceptions import (
    AuthenticationException,
    RecordNotFoundException,
    ValidationException,
)
from app.services.wait_service import ReportedTransition, WaitService

logger = logging.getLogger(__name__)

YOUTRACK = "youtrack"

RECEIVED_TOTAL = Counter(
    "pilot_tracker_events_received_total",
    "Deliveries posted to the tracker-events endpoint of a known tracker",
    ["tracker"],
)
REFUSED_TOTAL = Counter(
    "pilot_tracker_events_refused_total",
    "Deliveries refused, by reason: token, the tracker's token did not verify;"
    " body, the tracker's adapter could not read the delivery",
    ["tracker", "reason"],
)
FIRED_TOTAL = Counter(
    "pilot_tracker_waits_fired_total",
    "Card waits the tracker's deliveries fired",
    ["tracker"],
)


class TrackerAdapter(Protocol):
    def admits(self, headers: Headers) -> bool:
        """Whether the delivery carries the tracker's credential."""
        ...

    def read(self, body: bytes) -> ReportedTransition | None:
        """The card's change of state the delivery reports, none when it
        reports none.

        Raises:
            ValueError: the delivery cannot be read.
        """
        ...


class TrackerEventService:
    def __init__(self, wait_service: WaitService, app_settings: AppSettings) -> None:
        self.wait_service = wait_service
        self.adapters: dict[str, TrackerAdapter] = {
            YOUTRACK: YouTrackAdapter(app_settings.youtrack_webhook_token)
        }

    def admit(self, tracker: str, headers: Headers) -> None:
        """Count a delivery to `tracker`, and let it through when it carries
        the tracker's credential.

        Raises:
            RecordNotFoundException: no tracker is named `tracker`; not
                counted.
            AuthenticationException: the delivery does not carry the
                tracker's credential, and always while it is unset.
        """
        adapter = self._adapter(tracker)
        RECEIVED_TOTAL.labels(tracker=tracker).inc()
        if not adapter.admits(headers):
            REFUSED_TOTAL.labels(tracker=tracker, reason="token").inc()
            raise AuthenticationException(
                f"Cannot take the {tracker} delivery because it does not carry"
                " the tracker's token"
            )

    def take(self, tracker: str, body: bytes) -> int:
        """Fire the card waits the change of state `body` reports matches
        (F136.2); a delivery that reports none, or matches none, is dropped.

        Returns:
            How many waits fired.

        Raises:
            RecordNotFoundException: no tracker is named `tracker`.
            ValidationException: the tracker's adapter cannot read `body`.
        """
        adapter = self._adapter(tracker)
        try:
            transition = adapter.read(body)
        except ValueError as error:
            REFUSED_TOTAL.labels(tracker=tracker, reason="body").inc()
            raise ValidationException(
                f"Cannot read the {tracker} delivery because {error}"
            ) from error
        if transition is None:
            return 0
        fired = self.wait_service.fire_transition(transition)
        if fired:
            FIRED_TOTAL.labels(tracker=tracker).inc(fired)
            logger.info(
                "%s entered %r: %d card waits fired",
                transition.card,
                transition.to_state,
                fired,
            )
        return fired

    def _adapter(self, tracker: str) -> TrackerAdapter:
        adapter = self.adapters.get(tracker)
        if adapter is None:
            raise RecordNotFoundException("Tracker", tracker)
        return adapter


class _Read(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)


class _Change(_Read):
    """An entry of `changedFields`: a field's name and its two values, each
    as the app serializes the field's kind."""

    name: str
    old_value: Any = None
    value: Any = None


class _Delivery(_Read):
    """What every delivery of the app carries."""

    event: str
    changed_fields: list[_Change] = Field(default_factory=list)


class _User(_Read):
    login: str | None = None


class _Update(_Read):
    """What an update that changed the card's State must carry besides."""

    id: str = Field(min_length=1)
    # Epoch milliseconds up to the last a datetime holds.
    updated: int = Field(ge=0, lt=253402300800000)
    updated_by: _User | None = None


class YouTrackAdapter:
    """The Webhook Triggers app's `issueUpdated` delivery: the card is `id`,
    its readable id; the state it left `oldValue.name` and the state it
    entered `value.name` on the `State` entry of `changedFields`; when,
    `updated`, in epoch milliseconds; by whom, `updatedBy.login`."""

    TOKEN_HEADER = "X-YouTrack-Token"
    EVENT = "issueUpdated"
    STATE_FIELD = "State"

    def __init__(self, token: str) -> None:
        """
        Args:
            token: The instance's webhook token; empty refuses every delivery
        """
        self._token = token

    def admits(self, headers: Headers) -> bool:
        return bool(self._token) and hmac.compare_digest(
            headers.get(self.TOKEN_HEADER, "").encode(), self._token.encode()
        )

    def read(self, body: bytes) -> ReportedTransition | None:
        try:
            delivery = _Delivery.model_validate_json(body)
            change = next(
                (
                    change
                    for change in delivery.changed_fields
                    if change.name == self.STATE_FIELD
                ),
                None,
            )
            if delivery.event != self.EVENT or change is None:
                return None
            update = _Update.model_validate_json(body)
        except ValidationError as error:
            raise ValueError(_described(error)) from error
        entered = _state(change.value, "value")
        if entered is None:
            return None
        return ReportedTransition(
            card=update.id,
            from_state=_state(change.old_value, "oldValue"),
            to_state=entered,
            at=datetime.fromtimestamp(update.updated / 1000, UTC),
            by=None if update.updated_by is None else update.updated_by.login,
        )


def _state(value: Any, field: str) -> str | None:
    """The name of a State value, an enum's element; none for an empty field
    or an element with no name.

    Raises:
        ValueError: `value` is no enum's element.
    """
    if value is None:
        return None
    name = value.get("name") if isinstance(value, dict) else None
    if not isinstance(value, dict) or not isinstance(name, str | None):
        raise ValueError(f"the State entry's `{field}` is no state")
    return name


def _described(error: ValidationError) -> str:
    """The first of the delivery's faults: where it is, and what is wrong."""
    first = error.errors(include_url=False)[0]
    where = ".".join(str(part) for part in first["loc"])
    return f"its `{where}` is wrong: {first['msg']}" if where else first["msg"]
