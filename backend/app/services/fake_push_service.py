"""A fake push service, for the suites (TEST-1), in the notification bridge's
fake's place: no suite reaches a real one.

A WSGI application the real `WebPushService` reaches by a subscription's
endpoint: served on a thread under pytest (`tests/support/fake_push_service.py`),
and mounted for Playwright under `/api/testing/push-service`
(`app/api/testing_push_service.py`). It plays a browser and its push service
at once: it issues subscriptions whose endpoints are its own, keeps each
browser's private key and secret, and decrypts what each push carries, so a
test reads every push a subscription took and whether it alerted.

A push is taken as a push service takes one (RFC 8030 §5, RFC 8292): signed
with the key the browser subscribed with, by a claim for the fake's origin
that has a contact and expires within 24 hours, `aes128gcm`, with a `TTL`, an
`Urgency` if any of RFC 8030's, and a body of one record. It answers `201`, a
refusal `400`, `401`, `403` or `413` as the push services do, and an endpoint
it never issued `404`. A test makes a subscription fail: answered gone (`410`),
refused (`429`), in error (`500`), or not at all, its connection closed.

Simplifications of a real push service and browser: a push that does not
decrypt, or whose payload is not the push's JSON, is refused with `400`, where
a push service, which reads no payload, takes it and the browser drops it; a
push is kept at once, as if every browser were reachable; a push's `Topic` is
not read; nothing expires.
"""

from __future__ import annotations

import json
import secrets
import socket
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import jwt
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import ValidationError, validate_call
from pydantic_core import to_jsonable_python
from werkzeug.exceptions import HTTPException
from werkzeug.routing import Map, Rule
from werkzeug.wrappers import Request, Response

from app.services.web_push import RECORD_SIZE, content_keys, point
from app.utils.base64url import b64, unb64

if TYPE_CHECKING:
    from _typeshed.wsgi import StartResponse, WSGIEnvironment

PushFailure = Literal["gone", "refused", "error", "unanswered"]
"""How a subscription a test made fail answers a push: `410 Gone` (`gone`),
`429 Too Many Requests` (`refused`), `500` (`error`), or with its connection
closed and nothing sent (`unanswered`, under werkzeug's server, which hands
the app its socket)."""

_FAILURE_STATUS = {"gone": 410, "refused": 429, "error": 500}
_URGENCIES = frozenset({"very-low", "low", "normal", "high"})
_MAX_CLAIM_SECONDS = 24 * 3600
_SALT_SIZE = 16

_ROUTES = Map(
    [
        Rule("/push/<token>", endpoint="push", methods=["POST"]),
        Rule("/fake/<verb>", endpoint="verb", methods=["POST"]),
    ]
)


class FakePushServiceProblem(Exception):
    """An answer of the fake's other than `201`: a push service's refusal, or a
    verb the fake refuses; a verb called in process raises it."""

    def __init__(self, status: int, error: str) -> None:
        super().__init__(f"{status}: {error}")
        self.status = status
        self.error = error

    def response(self) -> Response:
        return Response(
            json.dumps({"error": self.error}),
            status=self.status,
            content_type="application/json",
        )


@dataclass(frozen=True)
class FakeSubscriptionKeys:
    p256dh: str
    auth: str


@dataclass(frozen=True)
class FakeSubscription:
    """A subscription the fake issued, as a browser's `PushSubscription.toJSON()`
    gives it."""

    endpoint: str
    keys: FakeSubscriptionKeys


@dataclass(frozen=True)
class FakePush:
    """A push a subscription took: what its payload carried, decrypted, and
    the headers it came with. `renotify` true alerted."""

    title: str
    body: str
    tag: str
    url: str
    renotify: bool
    urgency: str
    ttl: int


@dataclass
class _Browser:
    endpoint: str
    private_key: ec.EllipticCurvePrivateKey
    auth: bytes
    application_server_key: str
    failure: PushFailure | None = None
    pushes: list[FakePush] = field(default_factory=list)


class FakePushService:
    """A push service, with the subscriptions it issued."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._browsers: dict[str, _Browser] = {}
        self._verbs: dict[str, Callable[..., Any]] = {
            "subscribe": self.subscribe,
            "pushes": self.pushes,
            "fail": self.fail,
            "reset": self.reset,
        }

    def __call__(
        self, environ: WSGIEnvironment, start_response: StartResponse
    ) -> Iterable[bytes]:
        response = self._respond(Request(environ))
        return response(environ, start_response)

    # -- Verbs ----------------------------------------------------------------

    @validate_call
    def subscribe(self, application_server_key: str, origin: str) -> FakeSubscription:
        """A browser subscribed with `application_server_key`, the stage's
        public key, its endpoint under `origin`, where the fake is reached.
        Over HTTP, `origin` is where the call reached it, and is not given."""
        server_key = _public_key(application_server_key)
        if server_key is None:
            raise FakePushServiceProblem(
                422, "application_server_key is no P-256 public key in base64url"
            )
        private_key = ec.generate_private_key(ec.SECP256R1())
        token = secrets.token_urlsafe(24)
        browser = _Browser(
            endpoint=f"{origin.rstrip('/')}/push/{token}",
            private_key=private_key,
            auth=secrets.token_bytes(16),
            application_server_key=application_server_key,
        )
        with self._lock:
            self._browsers[token] = browser
        return FakeSubscription(
            browser.endpoint,
            FakeSubscriptionKeys(
                b64(point(private_key.public_key())), b64(browser.auth)
            ),
        )

    @validate_call
    def pushes(self, endpoint: str) -> list[FakePush]:
        """Every push the subscription took, in order."""
        with self._lock:
            return list(self._browser(endpoint).pushes)

    @validate_call
    def fail(self, endpoint: str, failure: PushFailure | None = "error") -> None:
        """The subscription answers every push as `failure` says from now on,
        and keeps none; None takes them again."""
        with self._lock:
            self._browser(endpoint).failure = failure

    @validate_call
    def reset(self) -> None:
        """Forget every subscription."""
        with self._lock:
            self._browsers.clear()

    # -- HTTP -----------------------------------------------------------------

    def _respond(self, request: Request) -> Response:
        adapter = _ROUTES.bind_to_environ(request.environ)
        try:
            endpoint, arguments = adapter.match()
            if endpoint == "push":
                return self._push(request, arguments["token"])
            return self._verb(request, arguments["verb"])
        except HTTPException as error:
            return Response(error.name, status=error.code, content_type="text/plain")
        except FakePushServiceProblem as problem:
            return problem.response()

    def _push(self, request: Request, token: str) -> Response:
        with self._lock:
            browser = self._browsers.get(token)
            if browser is None:
                raise FakePushServiceProblem(404, "no such subscription")
            if browser.failure == "unanswered":
                # The connection shut, the server's write of this answer
                # fails, and it drops the connection with nothing sent.
                request.environ["werkzeug.socket"].shutdown(socket.SHUT_RDWR)
                return Response(status=204)
            if browser.failure is not None:
                raise FakePushServiceProblem(
                    _FAILURE_STATUS[browser.failure],
                    f"the subscription is {browser.failure}",
                )
            _check_claim(request, browser)
            ttl, urgency = _headers(request)
            body = request.get_data()
            if len(body) > RECORD_SIZE:
                raise FakePushServiceProblem(
                    413, f"the body is {len(body)} octets, over {RECORD_SIZE}"
                )
            browser.pushes.append(_push(_decrypt(body, browser), ttl, urgency))
        return Response(
            status=201,
            headers={"Location": f"{request.base_url}/{len(browser.pushes)}"},
        )

    def _verb(self, request: Request, verb: str) -> Response:
        method = self._verbs.get(verb)
        if method is None:
            raise FakePushServiceProblem(404, f"the fake has no verb {verb}")
        arguments = request.get_json(silent=True) or {}
        if not isinstance(arguments, dict):
            raise FakePushServiceProblem(422, "a verb's body is its keyword arguments")
        if verb == "subscribe":
            arguments = {**arguments, "origin": request.url_root}
        try:
            answer = method(**arguments)
        except ValidationError as error:
            raise FakePushServiceProblem(422, str(error)) from error
        if answer is None:
            return Response(status=204)
        return Response(
            json.dumps(to_jsonable_python(answer)), content_type="application/json"
        )

    def _browser(self, endpoint: str) -> _Browser:
        for browser in self._browsers.values():
            if browser.endpoint == endpoint:
                return browser
        raise FakePushServiceProblem(404, f"the fake issued no subscription {endpoint}")


# -- A push, taken as a push service takes it ---------------------------------


def _check_claim(request: Request, browser: _Browser) -> None:
    """The push's VAPID claim (RFC 8292 §2, §3), for the fake's origin, signed
    with the key the browser subscribed with."""
    scheme, _, credentials = request.headers.get("Authorization", "").partition(" ")
    parameters: dict[str, str] = {}
    for part in credentials.split(","):
        name, _, value = part.strip().partition("=")
        parameters[name] = value
    token, key = parameters.get("t"), parameters.get("k")
    if scheme.lower() != "vapid" or not token or not key:
        raise FakePushServiceProblem(401, "the push carries no vapid t= and k=")
    if key != browser.application_server_key:
        raise FakePushServiceProblem(
            403, "the push's key is not the one the subscription was made with"
        )
    public_key = _public_key(key)
    if public_key is None:
        raise FakePushServiceProblem(401, "k is no P-256 public key in base64url")
    try:
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["ES256"],
            audience=request.host_url.rstrip("/"),
            options={"require": ["aud", "exp", "sub"]},
        )
    except jwt.InvalidTokenError as error:
        raise FakePushServiceProblem(
            401, f"the claim does not hold: {error}"
        ) from error
    if claims["exp"] > time.time() + _MAX_CLAIM_SECONDS:
        raise FakePushServiceProblem(401, "the claim expires over 24 hours from now")
    if not isinstance(claims["sub"], str) or not claims["sub"]:
        raise FakePushServiceProblem(401, "the claim's sub is no contact")


def _headers(request: Request) -> tuple[int, str]:
    if request.headers.get("Content-Encoding") != "aes128gcm":
        raise FakePushServiceProblem(400, "Content-Encoding must be aes128gcm")
    ttl = request.headers.get("TTL", "")
    if not ttl.isascii() or not ttl.isdigit():
        raise FakePushServiceProblem(400, "TTL must be a number of seconds")
    urgency = request.headers.get("Urgency", "normal")
    if urgency not in _URGENCIES:
        raise FakePushServiceProblem(400, f"Urgency {urgency} is none of RFC 8030's")
    return int(ttl), urgency


def _decrypt(body: bytes, browser: _Browser) -> bytes:
    """The payload, as the browser decrypts it (RFC 8291 §3.4, RFC 8188 §2)."""
    header_size = _SALT_SIZE + 5
    if len(body) < header_size:
        raise FakePushServiceProblem(400, "the body is shorter than its header")
    key_size = body[_SALT_SIZE + 4]
    as_public = body[header_size : header_size + key_size]
    sender_key = _public_key(b64(as_public))
    if sender_key is None:
        raise FakePushServiceProblem(400, "the header's key id is no P-256 public key")
    secret = browser.private_key.exchange(ec.ECDH(), sender_key)
    payload = unseal(
        body, secret, browser.auth, point(browser.private_key.public_key())
    )
    if payload is None:
        raise FakePushServiceProblem(400, "the body does not decrypt")
    return payload


def unseal(
    body: bytes, ecdh_secret: bytes, auth: bytes, ua_public: bytes
) -> bytes | None:
    """The payload of a push's body of one record, or None if it does not
    decrypt: the reverse of `web_push.seal`."""
    salt = body[:_SALT_SIZE]
    record_size = int.from_bytes(body[_SALT_SIZE : _SALT_SIZE + 4], "big")
    key_size = body[_SALT_SIZE + 4]
    start = _SALT_SIZE + 5 + key_size
    as_public, ciphertext = body[_SALT_SIZE + 5 : start], body[start:]
    if len(ciphertext) > record_size:
        return None
    cek, nonce = content_keys(ecdh_secret, auth, ua_public, as_public, salt)
    try:
        padded = AESGCM(cek).decrypt(nonce, ciphertext, None)
    except InvalidTag:
        return None
    record = padded.rstrip(b"\x00")
    if not record.endswith(b"\x02"):
        return None
    return record[:-1]


def _push(payload: bytes, ttl: int, urgency: str) -> FakePush:
    """The push the payload is, as the service worker reads it."""
    try:
        fields = json.loads(payload)
    except ValueError as error:
        raise FakePushServiceProblem(400, "the payload is not JSON") from error
    if not isinstance(fields, dict) or set(fields) != {
        "title",
        "body",
        "tag",
        "url",
        "renotify",
    }:
        raise FakePushServiceProblem(
            400, "the payload is not {title, body, tag, url, renotify}"
        )
    strings = [fields[name] for name in ("title", "body", "tag", "url")]
    if not all(isinstance(value, str) for value in strings) or not isinstance(
        fields["renotify"], bool
    ):
        raise FakePushServiceProblem(
            400, "title, body, tag and url are strings, renotify a boolean"
        )
    return FakePush(
        title=fields["title"],
        body=fields["body"],
        tag=fields["tag"],
        url=fields["url"],
        renotify=fields["renotify"],
        urgency=urgency,
        ttl=ttl,
    )


def _public_key(value: str) -> ec.EllipticCurvePublicKey | None:
    try:
        return ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), unb64(value)
        )
    except ValueError:
        return None
