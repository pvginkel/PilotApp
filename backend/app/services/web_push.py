"""Web push (F94, F142; DB 301, 302, 311, 314): a push to a person goes to
every browser they turned notifications on in, each through its own push
service (RFC 8030), the payload encrypted to that browser (RFC 8291) and the
request signed with the stage's VAPID key (RFC 8292), whose contact is the
stage's own address.

A push service that answers a subscription gone, `404` or `410`, has the row
deleted (DB 311); any other failure is logged and counted, and never retried:
the next change pushes anew (DB 314). Each subscription names its own push
service, so no one system is checked for readiness; the counter shows them
failing.
"""

import json
import logging
import os
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from typing import cast
from urllib.parse import urlsplit

import jwt
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from prometheus_client import Counter
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import PushSubscription
from app.utils.base64url import b64, unb64

logger = logging.getLogger(__name__)

RECORD_SIZE = 4096
"""The one record's size, the most of a body every push service takes (RFC
8291 §4)."""
_HEADER_SIZE = 86
"""The salt, the record size, and the length and value of the 65-octet key."""
_TAG_SIZE = 16
MAX_PLAINTEXT = RECORD_SIZE - _HEADER_SIZE - 1 - _TAG_SIZE
"""The most a payload may be: 3993 octets, its delimiter and the tag after it
(RFC 8291 §4)."""
_LAST_RECORD = b"\x02"

_TTL_SECONDS = 86400
"""How long a push service keeps a push for a browser it cannot reach."""
_CLAIM_SECONDS = 12 * 3600
"""How long a push's VAPID claim holds, within the 24 hours RFC 8292 §2
allows."""
_CONNECT_TIMEOUT_SECONDS = 10
_CALL_TIMEOUT_SECONDS = 30

_CUT = "…"


class PushOutcome(StrEnum):
    """How a push to one subscription ended: its service took it, answered the
    subscription gone, refused the push with another 4xx, or gave no answer of
    its own (a connection error, a timeout, a 5xx)."""

    SENT = "sent"
    GONE = "gone"
    REFUSED = "refused"
    UNANSWERED = "unanswered"


WEB_PUSH_SENDS_TOTAL = Counter(
    "pilot_web_push_sends_total",
    "Pushes to a browser's push service, by outcome (sent, gone, refused, unanswered)",
    ["outcome"],
)


@dataclass(frozen=True)
class Push:
    """What a push carries, the service worker's input: it shows the push as a
    notification under `tag`, which a tap opens at `url`."""

    title: str
    """The notification's title, plain text."""
    body: str
    """The notification's text, plain text."""
    tag: str
    """What the notification replaces: the one shown under the same tag."""
    url: str
    """Where a tap on the notification opens the app."""
    renotify: bool
    """True alerts; False replaces what shows under `tag` silently."""

    def payload(self) -> bytes:
        """The push as its JSON, UTF-8: `{"title", "body", "tag", "url",
        "renotify"}`, `body` cut, an ellipsis ending it, so that the whole
        fits one record (`MAX_PLAINTEXT`)."""
        fields: dict[str, str | bool] = {
            "title": self.title,
            "body": self.body,
            "tag": self.tag,
            "url": self.url,
            "renotify": self.renotify,
        }
        if not _fits(fields):
            fields["body"] = _cut(fields, self.body)
        return _encoded(fields)


class VapidKey:
    """The stage's VAPID key pair (RFC 8292): the private key signs each
    push's claim, and the public key is the one a browser subscribes with."""

    def __init__(self, pem: str) -> None:
        """`pem` is a P-256 private key, as `AppSettings` takes it."""
        self._key = cast(
            ec.EllipticCurvePrivateKey,
            serialization.load_pem_private_key(pem.encode(), password=None),
        )
        self.public_key = b64(point(self._key.public_key()))
        """The public key, base64url, uncompressed: a browser's
        `applicationServerKey`."""

    def authorization(self, endpoint: str, contact: str) -> str:
        """The `Authorization` of a push to `endpoint`: a claim for the push
        service's origin, its contact `contact`, signed, and the public key
        (RFC 8292 §3)."""
        parts = urlsplit(endpoint)
        claims = {
            "aud": f"{parts.scheme}://{parts.netloc}",
            "exp": int(time.time()) + _CLAIM_SECONDS,
            "sub": contact,
        }
        token = jwt.encode(claims, self._key, algorithm="ES256")
        return f"vapid t={token}, k={self.public_key}"


@dataclass(frozen=True)
class _Target:
    id: int
    endpoint: str
    p256dh: str
    auth: str


type OpenTransaction = Callable[[], AbstractContextManager[Session]]
"""Opens a transaction of its own, committed when its block ends: a turn's,
on its connection (`Turn.transaction`)."""


class WebPushService:
    """Pushes to a person's browsers, signed with the stage's key; with no key,
    the deployment pushes nothing."""

    def __init__(self, private_key: str | None, contact: str) -> None:
        """
        Args:
            private_key: the stage's VAPID key, P-256 in PEM; None pushes
                nothing
            contact: the stage's own address, the claims' `sub`
        """
        self._key = None if private_key is None else VapidKey(private_key)
        self._contact = contact

    @property
    def public_key(self) -> str | None:
        """The stage's public key, base64url, which a browser subscribes with;
        None where the deployment pushes nothing."""
        return None if self._key is None else self._key.public_key

    def push(
        self,
        user_id: uuid.UUID,
        push: Push,
        transaction: OpenTransaction,
    ) -> bool:
        """Push `push` to every subscription of the person's, one after the
        other; delete each one its push service answered gone. Whether any of
        them took it: False with none, or with no key.

        The read of the subscriptions and the delete are transactions of
        their own, each opened by `transaction`, a turn's on its connection
        (`Turn.transaction`); none is open across the push services' calls.
        """
        if self._key is None:
            return False
        with transaction() as db:
            targets = [
                _Target(row.id, row.endpoint, row.p256dh, row.auth)
                for row in db.scalars(
                    select(PushSubscription)
                    .where(PushSubscription.user_id == user_id)
                    .order_by(PushSubscription.id)
                )
            ]
        payload = push.payload()
        outcomes = [
            (target, self._send(self._key, user_id, target, payload, push.renotify))
            for target in targets
        ]
        gone = [
            target.id for target, outcome in outcomes if outcome is PushOutcome.GONE
        ]
        if gone:
            with transaction() as db:
                # By the person too: a row another person's write took over
                # since the read is theirs now.
                db.execute(
                    delete(PushSubscription).where(
                        PushSubscription.id.in_(gone),
                        PushSubscription.user_id == user_id,
                    )
                )
        return any(outcome is PushOutcome.SENT for _, outcome in outcomes)

    def _send(
        self,
        key: VapidKey,
        user_id: uuid.UUID,
        target: _Target,
        payload: bytes,
        renotify: bool,
    ) -> PushOutcome:
        service = urlsplit(target.endpoint).netloc
        body = encrypt(
            payload,
            unb64(target.p256dh),
            unb64(target.auth),
            salt=os.urandom(16),
            server_key=ec.generate_private_key(ec.SECP256R1()),
        )
        try:
            response = requests.post(
                target.endpoint,
                data=body,
                headers={
                    "Authorization": key.authorization(target.endpoint, self._contact),
                    "Content-Encoding": "aes128gcm",
                    "Content-Type": "application/octet-stream",
                    "TTL": str(_TTL_SECONDS),
                    "Urgency": "high" if renotify else "normal",
                },
                timeout=(_CONNECT_TIMEOUT_SECONDS, _CALL_TIMEOUT_SECONDS),
                allow_redirects=False,
            )
        except requests.RequestException as error:
            outcome = PushOutcome.UNANSWERED
            logger.warning(
                "The push service %s did not answer a push to subscription %s "
                "of user %s: %s",
                service,
                target.id,
                user_id,
                error,
            )
        else:
            outcome = _outcome(response.status_code)
            if outcome is PushOutcome.GONE:
                logger.info(
                    "The push service %s answered subscription %s of user %s "
                    "gone (%s); it is deleted",
                    service,
                    target.id,
                    user_id,
                    response.status_code,
                )
            elif outcome is PushOutcome.REFUSED:
                logger.warning(
                    "The push service %s refused a push to subscription %s of "
                    "user %s with %s: %s",
                    service,
                    target.id,
                    user_id,
                    response.status_code,
                    response.text.strip() or response.reason,
                )
            elif outcome is PushOutcome.UNANSWERED:
                logger.warning(
                    "The push service %s did not take a push to subscription "
                    "%s of user %s: %s %s",
                    service,
                    target.id,
                    user_id,
                    response.status_code,
                    response.reason,
                )
        WEB_PUSH_SENDS_TOTAL.labels(outcome=outcome).inc()
        return outcome


def encrypt(
    payload: bytes,
    p256dh: bytes,
    auth: bytes,
    *,
    salt: bytes,
    server_key: ec.EllipticCurvePrivateKey,
) -> bytes:
    """`payload` encrypted to the browser whose public key is `p256dh` and
    whose secret is `auth`, as one `aes128gcm` record (RFC 8291 §3.4): fresh
    `salt` and `server_key` for each push."""
    browser_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), p256dh)
    return seal(
        payload,
        server_key.exchange(ec.ECDH(), browser_key),
        auth,
        p256dh,
        point(server_key.public_key()),
        salt,
    )


def seal(
    payload: bytes,
    ecdh_secret: bytes,
    auth: bytes,
    ua_public: bytes,
    as_public: bytes,
    salt: bytes,
) -> bytes:
    """The body of a push: the `aes128gcm` header, `as_public` its key id, then
    the payload and its delimiter encrypted (RFC 8188 §2, RFC 8291 §3.4)."""
    cek, nonce = content_keys(ecdh_secret, auth, ua_public, as_public, salt)
    ciphertext = AESGCM(cek).encrypt(nonce, payload + _LAST_RECORD, None)
    header = salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(as_public)]) + as_public
    return header + ciphertext


def content_keys(
    ecdh_secret: bytes, auth: bytes, ua_public: bytes, as_public: bytes, salt: bytes
) -> tuple[bytes, bytes]:
    """A push's content encryption key and nonce, from the browser's and the
    sender's keys (RFC 8291 §3.3, §3.4) and the salt (RFC 8188 §2.2, §2.3)."""
    ikm = HKDF(
        hashes.SHA256(),
        32,
        salt=auth,
        info=b"WebPush: info\x00" + ua_public + as_public,
    ).derive(ecdh_secret)
    cek = HKDF(
        hashes.SHA256(), 16, salt=salt, info=b"Content-Encoding: aes128gcm\x00"
    ).derive(ikm)
    nonce = HKDF(
        hashes.SHA256(), 12, salt=salt, info=b"Content-Encoding: nonce\x00"
    ).derive(ikm)
    return cek, nonce


def point(key: ec.EllipticCurvePublicKey) -> bytes:
    """`key` as its uncompressed point, 65 octets, as the Push API gives a
    browser's `p256dh`."""
    return key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def _outcome(status: int) -> PushOutcome:
    if 200 <= status < 300:
        return PushOutcome.SENT
    if status in (404, 410):
        return PushOutcome.GONE
    if 400 <= status < 500:
        return PushOutcome.REFUSED
    return PushOutcome.UNANSWERED


def _encoded(fields: dict[str, str | bool]) -> bytes:
    return json.dumps(fields, ensure_ascii=False, separators=(",", ":")).encode()


def _fits(fields: dict[str, str | bool]) -> bool:
    return len(_encoded(fields)) <= MAX_PLAINTEXT


def _cut(fields: dict[str, str | bool], body: str) -> str:
    """The longest start of `body` that, an ellipsis after it, fits."""
    low, high = 0, len(body)
    while low < high:
        middle = (low + high + 1) // 2
        if _fits({**fields, "body": body[:middle] + _CUT}):
            low = middle
        else:
            high = middle - 1
    return body[:low] + _CUT
