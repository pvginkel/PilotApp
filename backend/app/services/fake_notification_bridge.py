"""A fake of the notification bridge, for the suites (the Q1 ruling, TEST-1).

A WSGI application the real NotificationBridgeClient reaches by URL: served on
a thread under pytest (`tests/support/fake_notification_bridge.py`), and
mounted for Playwright under `/api/testing/notification-bridge`
(`app/api/testing_notification_bridge.py`). It knows the registrations a test
gives it, each by a name and its token, refuses any other bearer with `401`,
and takes the bridge's bodies with the bridge's limits, status codes and
reasons (pvginkel/Notifications: the README, and
`bridge/src/notification_bridge/api.py`, whose parse this ports). A
registration shows, per sequence id, what its last submit carried and whether
that submit alerted, by the bridge's priority rule (README § Priorities); it
keeps the one-shots it took, and every call it took, in order, but for a call
answered with a channel's error, which it keeps nothing of.

A test drives it through its verbs, the public methods below: in process under
pytest, and over HTTP as `POST /fake/<verb>`, the verb's name hyphenated and
its keyword arguments the JSON body.

Simplifications of the real bridge: a registration has one channel, `ntfy`; a
channel a test makes fail answers its error in the `200` and changes nothing
the registration shows; a submit alerts when it shows a notification anew or
raises its priority, to `default` or above, as Telegram notifies and ntfy's
scale sounds; nothing is forgotten after 90 days; `/metrics` is not served.
"""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, get_args
from urllib.parse import urlsplit

from pydantic import ValidationError, validate_call
from pydantic_core import to_jsonable_python
from werkzeug.exceptions import HTTPException
from werkzeug.routing import Map, Rule
from werkzeug.wrappers import Request, Response

from app.services.notification_bridge_client import BridgePriority

if TYPE_CHECKING:
    from _typeshed.wsgi import StartResponse, WSGIEnvironment

Unanswered = Literal["none", "error", "stall"]
"""How a call goes unanswered while the bridge is unreachable: its connection
closed with no answer (`none`, under werkzeug's server, which hands the app its
socket), a `500` the bridge's server writes for a crash (`error`), or held
until the bridge is reachable again, then answered (`stall`)."""

_PRIORITIES: tuple[BridgePriority, ...] = get_args(BridgePriority)
_ALERTING: frozenset[BridgePriority] = frozenset({"default", "high", "max"})

_MAX_SEQUENCE_ID = 256
_MAX_TITLE = 250
_MAX_MESSAGE = 4096
_MAX_URL = 2048

_ROUTES = Map(
    [
        Rule("/healthz", endpoint="healthz", methods=["GET"]),
        Rule("/v1/submit", endpoint="submit", methods=["POST"]),
        Rule("/v1/dismiss", endpoint="dismiss", methods=["POST"]),
        Rule("/fake/<verb>", endpoint="verb", methods=["POST"]),
    ]
)


class FakeNotificationBridgeProblem(Exception):
    """An answer of the fake's other than `200`: the bridge's refusal, or a verb
    the fake refuses; a verb called in process raises it."""

    def __init__(self, status: int, error: str) -> None:
        super().__init__(f"{status}: {error}")
        self.status = status
        self.error = error

    def response(self) -> Response:
        headers = {"WWW-Authenticate": "Bearer"} if self.status == 401 else None
        return _json({"error": self.error}, self.status, headers)


@dataclass(frozen=True)
class FakeNotification:
    """A notification a registration took: its fields, and whether the submit
    alerted. A one-shot's `sequence_id` is None."""

    sequence_id: str | None
    priority: BridgePriority
    title: str | None
    message: str
    url: str | None
    alerted: bool


@dataclass(frozen=True)
class FakeCall:
    """A call a registration took with no channel error set: a submit, a
    one-shot's `sequence_id` None, or a dismiss, which never alerts."""

    call: Literal["submit", "dismiss"]
    sequence_id: str | None
    alerted: bool


@dataclass
class _Registration:
    token: str
    channel_error: str | None = None
    shown: dict[str, FakeNotification] = field(default_factory=dict)
    one_shots: list[FakeNotification] = field(default_factory=list)
    calls: list[FakeCall] = field(default_factory=list)


@dataclass(frozen=True)
class _Submission:
    sequence_id: str | None
    priority: BridgePriority
    title: str | None
    message: str
    url: str | None


class FakeNotificationBridge:
    """The bridge, with the registrations a test gives it."""

    def __init__(self) -> None:
        self._changed = threading.Condition()
        self._registrations: dict[str, _Registration] = {}
        self._unanswered: Unanswered | None = None
        self._closed = False
        self._endpoints: dict[str, Callable[..., Response]] = {
            "healthz": self._healthz,
            "submit": self._submit,
            "dismiss": self._dismiss,
            "verb": self._verb,
        }
        self._verbs: dict[str, Callable[..., Any]] = {
            "add-registration": self.add_registration,
            "rotate-token": self.rotate_token,
            "channel-error": self.channel_error,
            "unreachable": self.unreachable,
            "shown": self.shown,
            "one-shots": self.one_shots,
            "calls": self.calls,
            "reset": self.reset,
        }

    def __call__(
        self, environ: WSGIEnvironment, start_response: StartResponse
    ) -> Iterable[bytes]:
        response = self._respond(Request(environ))
        return response(environ, start_response)

    # -- Verbs ----------------------------------------------------------------

    @validate_call
    def add_registration(self, name: str, token: str) -> None:
        """A registration `name`, whose bearer is `token`, showing nothing."""
        with self._changed:
            if name in self._registrations:
                raise FakeNotificationBridgeProblem(
                    409, f"the fake has a registration {name} already"
                )
            self._refuse_a_held_token(token)
            self._registrations[name] = _Registration(token)

    @validate_call
    def rotate_token(self, name: str, token: str) -> None:
        """The registration's bearer is `token` from now on, the old one refused;
        what it shows stays."""
        with self._changed:
            registration = self._registration(name)
            self._refuse_a_held_token(token)
            registration.token = token

    @validate_call
    def channel_error(self, name: str, error: str | None = None) -> None:
        """While `error` is set, the registration's channel fails every call with
        it: the `200` says so, and nothing the registration shows changes."""
        with self._changed:
            self._registration(name).channel_error = error

    @validate_call
    def unreachable(self, on: bool = True, answer: Unanswered = "none") -> None:
        """The bridge does not answer: every call, `/healthz` among them and the
        verbs not, goes unanswered as `answer` says. `on=False` answers again,
        and a stalled call then is."""
        with self._changed:
            self._unanswered = answer if on else None
            self._changed.notify_all()

    @validate_call
    def shown(self, name: str) -> dict[str, FakeNotification]:
        """What the registration shows, per sequence id."""
        with self._changed:
            return dict(self._registration(name).shown)

    @validate_call
    def one_shots(self, name: str) -> list[FakeNotification]:
        """The one-shots the registration took, in order; one answered with a
        channel's error is not among them."""
        with self._changed:
            return list(self._registration(name).one_shots)

    @validate_call
    def calls(self, name: str) -> list[FakeCall]:
        """Every call the registration took, in order; one answered with a
        channel's error is not among them."""
        with self._changed:
            return list(self._registration(name).calls)

    def reset(self) -> None:
        """Forget every registration, and answer again; a stalled call is
        answered."""
        with self._changed:
            self._registrations.clear()
            self._unanswered = None
            self._changed.notify_all()

    def close(self) -> None:
        """Answer every stalled call, for good."""
        with self._changed:
            self._closed = True
            self._changed.notify_all()

    # -- HTTP -----------------------------------------------------------------

    def _respond(self, request: Request) -> Response:
        adapter = _ROUTES.bind_to_environ(request.environ)
        try:
            endpoint, arguments = adapter.match()
        except HTTPException as error:
            # The bridge's router answers a path or method it has no route for
            # in plain text.
            return Response(error.name, status=error.code, content_type="text/plain")
        if endpoint != "verb":
            unanswered = self._wait_while_stalled()
            if unanswered is not None and unanswered != "stall":
                return _unanswered(request, unanswered)
        try:
            return self._endpoints[endpoint](request, **arguments)
        except FakeNotificationBridgeProblem as problem:
            return problem.response()

    def _wait_while_stalled(self) -> Unanswered | None:
        with self._changed:
            while self._unanswered == "stall" and not self._closed:
                self._changed.wait()
            return self._unanswered

    def _healthz(self, request: Request) -> Response:
        return Response("ok", content_type="text/plain")

    def _submit(self, request: Request) -> Response:
        with self._changed:
            registration = self._authenticate(request)
            submission = _parse_submission(request.get_data())
            if registration.channel_error is not None:
                return self._answer(registration)
            if submission.sequence_id is None:
                notification = _notification(submission, _alerts(submission.priority))
                registration.one_shots.append(notification)
            else:
                shown = registration.shown.get(submission.sequence_id)
                anew = shown is None or _rank(submission.priority) > _rank(
                    shown.priority
                )
                notification = _notification(
                    submission, anew and _alerts(submission.priority)
                )
                registration.shown[submission.sequence_id] = notification
            registration.calls.append(
                FakeCall("submit", submission.sequence_id, notification.alerted)
            )
            return self._answer(registration)

    def _dismiss(self, request: Request) -> Response:
        with self._changed:
            registration = self._authenticate(request)
            sequence_id = _parse_dismissal(request.get_data())
            if registration.channel_error is not None:
                return self._answer(registration)
            registration.shown.pop(sequence_id, None)
            registration.calls.append(FakeCall("dismiss", sequence_id, False))
            return self._answer(registration)

    def _verb(self, request: Request, verb: str) -> Response:
        method = self._verbs.get(verb)
        if method is None:
            raise FakeNotificationBridgeProblem(404, f"the fake has no verb {verb}")
        arguments = request.get_json(silent=True) or {}
        if not isinstance(arguments, dict):
            raise FakeNotificationBridgeProblem(
                422, "a verb's body is its keyword arguments"
            )
        try:
            answer = method(**arguments)
        except ValidationError as error:
            raise FakeNotificationBridgeProblem(422, str(error)) from error
        if answer is None:
            return Response(status=204)
        return _json(to_jsonable_python(answer))

    # -- Internals ------------------------------------------------------------

    def _authenticate(self, request: Request) -> _Registration:
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() == "bearer":
            for registration in self._registrations.values():
                if registration.token == token:
                    return registration
        raise FakeNotificationBridgeProblem(401, "unknown bearer token")

    def _answer(self, registration: _Registration) -> Response:
        if registration.channel_error is None:
            return _json({"ntfy": "ok"})
        return _json({"ntfy": f"error: {registration.channel_error}"})

    def _registration(self, name: str) -> _Registration:
        registration = self._registrations.get(name)
        if registration is None:
            raise FakeNotificationBridgeProblem(
                404, f"the fake has no registration {name}"
            )
        return registration

    def _refuse_a_held_token(self, token: str) -> None:
        if any(r.token == token for r in self._registrations.values()):
            raise FakeNotificationBridgeProblem(
                409, "another registration holds that token"
            )


def _rank(priority: BridgePriority) -> int:
    return _PRIORITIES.index(priority)


def _alerts(priority: BridgePriority) -> bool:
    return priority in _ALERTING


def _notification(submission: _Submission, alerted: bool) -> FakeNotification:
    return FakeNotification(
        submission.sequence_id,
        submission.priority,
        submission.title,
        submission.message,
        submission.url,
        alerted,
    )


# -- The bridge's parse, ported -----------------------------------------------


def _parse_submission(body: bytes) -> _Submission:
    fields = _fields(body, {"sequence_id", "priority", "title", "message", "url"})
    sequence_id = _sequence_id(fields)

    priority = fields.get("priority", "default")
    if not isinstance(priority, str) or priority not in _PRIORITIES:
        raise FakeNotificationBridgeProblem(
            400, f"priority must be one of {', '.join(_PRIORITIES)}"
        )

    title = _string(fields, "title")
    if title is not None and len(title) > _MAX_TITLE:
        raise FakeNotificationBridgeProblem(
            400, f"title is {len(title)} characters, over the limit of {_MAX_TITLE}"
        )

    message = _string(fields, "message")
    if message is None:
        raise FakeNotificationBridgeProblem(400, "message is missing")
    if len(message) > _MAX_MESSAGE:
        raise FakeNotificationBridgeProblem(
            413,
            f"message is {len(message)} characters, over the limit of {_MAX_MESSAGE}",
        )
    if not message.strip():
        raise FakeNotificationBridgeProblem(400, "message is blank")

    return _Submission(
        sequence_id,
        priority,
        title,
        message,
        _url(fields),
    )


def _parse_dismissal(body: bytes) -> str:
    sequence_id = _sequence_id(_fields(body, {"sequence_id"}))
    if sequence_id is None:
        raise FakeNotificationBridgeProblem(400, "sequence_id is missing")
    return sequence_id


def _fields(body: bytes, known: set[str]) -> dict[str, object]:
    try:
        fields = json.loads(body)
    except (ValueError, RecursionError) as error:
        raise FakeNotificationBridgeProblem(
            400, f"the body is not JSON: {error}"
        ) from error
    if not isinstance(fields, dict):
        raise FakeNotificationBridgeProblem(400, "the body must be a JSON object")
    unknown = sorted(set(fields) - known)
    if unknown:
        raise FakeNotificationBridgeProblem(
            400, f"unknown fields: {', '.join(unknown)}"
        )
    return {key: value for key, value in fields.items() if value is not None}


def _sequence_id(fields: dict[str, object]) -> str | None:
    sequence_id = _string(fields, "sequence_id")
    if sequence_id is not None and not 1 <= len(sequence_id) <= _MAX_SEQUENCE_ID:
        raise FakeNotificationBridgeProblem(
            400, f"sequence_id must be 1 to {_MAX_SEQUENCE_ID} characters"
        )
    return sequence_id


def _url(fields: dict[str, object]) -> str | None:
    url = _string(fields, "url")
    if url is None:
        return None
    if len(url) > _MAX_URL:
        raise FakeNotificationBridgeProblem(
            400, f"url is {len(url)} characters, over the limit of {_MAX_URL}"
        )
    if not url.isascii():
        raise FakeNotificationBridgeProblem(
            400, "url must be ASCII, the rest percent-encoded"
        )
    if not all("!" <= char <= "~" for char in url):
        raise FakeNotificationBridgeProblem(
            400, "url holds whitespace or a control character"
        )
    try:
        parts = urlsplit(url)
        absolute = parts.scheme in {"http", "https"} and bool(parts.hostname)
    except ValueError:
        absolute = False
    if not absolute:
        raise FakeNotificationBridgeProblem(
            400, "url must be an absolute http or https URL"
        )
    return url


def _string(fields: dict[str, object], key: str) -> str | None:
    value = fields.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise FakeNotificationBridgeProblem(400, f"{key} must be a string")
    try:
        value.encode()
    except UnicodeEncodeError as error:
        raise FakeNotificationBridgeProblem(
            400, f"{key} holds a lone surrogate"
        ) from error
    return value


# -- Answers ------------------------------------------------------------------


def _unanswered(request: Request, answer: Unanswered) -> Response:
    if answer == "error":
        return Response("Internal Server Error", status=500, content_type="text/plain")
    # The connection shut, the server's write of this answer fails, and it
    # drops the connection with nothing sent.
    request.environ["werkzeug.socket"].shutdown(socket.SHUT_RDWR)
    return Response(status=204)


def _json(
    body: Any, status: int = 200, headers: dict[str, str] | None = None
) -> Response:
    return Response(
        json.dumps(body),
        status=status,
        content_type="application/json",
        headers=headers,
    )
