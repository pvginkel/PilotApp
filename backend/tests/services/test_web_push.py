"""Web push (F94, F142; DB 311, 314): a push's payload, its encryption and its
claim, and the push to every browser of a person's, on the fake push
service."""

import json
import logging
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PushSubscription, User
from app.models.reference import UserKind
from app.services.container import ServiceContainer
from app.services.fake_push_service import FakePush, FakeSubscription, unseal
from app.services.push_subscription_service import PushSubscriptionService
from app.services.web_push import (
    MAX_PLAINTEXT,
    WEB_PUSH_SENDS_TOTAL,
    Push,
    PushOutcome,
    VapidKey,
    WebPushService,
    encrypt,
    point,
    seal,
)
from app.utils.base64url import b64, unb64
from tests.support.fake_push_service import (
    ServedFakePushService,
    mint_vapid_key,
    web_push_of,
)
from tests.support.supervisor import metric_value

PROJECT_ID = "5b7f3c1e-0d2a-4e8b-9c61-2f4a8d0e7b13"
URL = f"http://localhost:3500/projects/{PROJECT_ID}"
ALERT = Push(
    title="Garden sensors",
    body="Pick the board, +1",
    tag=PROJECT_ID,
    url=URL,
    renotify=True,
)

# RFC 8291 Appendix A, its published example: the inputs and the shared
# secret it derives, with neither private key.
RFC_PLAINTEXT = "V2hlbiBJIGdyb3cgdXAsIEkgd2FudCB0byBiZSBhIHdhdGVybWVsb24"
RFC_AS_PUBLIC = (
    "BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIg"
    "Dll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8"
)
RFC_UA_PUBLIC = (
    "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcx"
    "aOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
)
RFC_SALT = "DGv6ra1nlYgDCS1FRnbzlw"
RFC_AUTH_SECRET = "BTBZMqHH6r4Tts7J_aSIgg"
RFC_ECDH_SECRET = "kyrL1jIIOHEzg3sM2ZWRHDRB62YACZhhSlknJ672kSs"
RFC_HEADER = (
    "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml"
    "mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8"
)
RFC_CIPHERTEXT = (
    "8pfeW0KbunFT06SuDKoJH9Ql87S1QUrdirN6GcG7sFz1y1sqLgVi1VhjVkHsUoEsbI_0LpXMuGvnzQ"
)


def _payload(push: Push) -> dict[str, object]:
    return json.loads(push.payload())


def _size(fields: dict[str, object]) -> int:
    return len(json.dumps(fields, ensure_ascii=False, separators=(",", ":")).encode())


def _pushed(push: Push, urgency: str) -> FakePush:
    return FakePush(
        push.title, push.body, push.tag, push.url, push.renotify, urgency, 86400
    )


def _sends(outcome: PushOutcome) -> float:
    return metric_value(WEB_PUSH_SENDS_TOTAL, outcome=outcome)


def _bea(session: Session) -> User:
    bea = User(
        kind_code=UserKind.PERSON,
        subject="subject-bea",
        handle="bea",
        name="Bea Example",
        avatar_slot=2,
    )
    session.add(bea)
    session.flush()
    return bea


def _subscribe(session: Session, person: User, browser: FakeSubscription) -> None:
    PushSubscriptionService(session).subscribe(
        person, browser.endpoint, browser.keys.p256dh, browser.keys.auth
    )


def _holders(session: Session) -> dict[str, object]:
    session.expire_all()
    return {
        row.endpoint: row.user_id for row in session.scalars(select(PushSubscription))
    }


class TestPushPayload:
    def test_it_carries_the_five_fields_as_json(self) -> None:
        assert _payload(ALERT) == {
            "title": "Garden sensors",
            "body": "Pick the board, +1",
            "tag": PROJECT_ID,
            "url": URL,
            "renotify": True,
        }

    def test_the_text_is_plain_with_no_markdown_escape(self) -> None:
        push = Push("A_b *c*", "Review [the plan] #1, +2", "t", URL, False)

        assert _payload(push)["title"] == "A_b *c*"
        assert _payload(push)["body"] == "Review [the plan] #1, +2"

    def test_a_text_that_fits_is_not_cut(self) -> None:
        overhead = len(Push("T", "", "t", URL, True).payload())
        push = Push("T", "x" * (MAX_PLAINTEXT - overhead), "t", URL, True)

        assert len(push.payload()) == MAX_PLAINTEXT
        assert _payload(push)["body"] == "x" * (MAX_PLAINTEXT - overhead)

    @pytest.mark.parametrize(
        "body", ["x" * 5000, "ë" * 3000, "Ask 🌱, " * 1000, '"\\' * 2000]
    )
    def test_a_longer_text_is_cut_to_fit_with_an_ellipsis(self, body: str) -> None:
        push = Push("Garden sensors", body, PROJECT_ID, URL, True)

        cut = _payload(push)["body"]

        assert len(push.payload()) <= MAX_PLAINTEXT
        assert isinstance(cut, str) and cut.endswith("…")
        kept = len(cut) - 1
        assert body.startswith(cut[:kept])
        longer = {**_payload(push), "body": body[: kept + 1] + "…"}
        assert _size(longer) > MAX_PLAINTEXT


class TestEncryption:
    def test_it_seals_rfc_8291s_example_to_its_body(self) -> None:
        body = seal(
            unb64(RFC_PLAINTEXT),
            unb64(RFC_ECDH_SECRET),
            unb64(RFC_AUTH_SECRET),
            unb64(RFC_UA_PUBLIC),
            unb64(RFC_AS_PUBLIC),
            unb64(RFC_SALT),
        )

        assert body == unb64(RFC_HEADER) + unb64(RFC_CIPHERTEXT)

    def test_the_browser_opens_what_it_encrypts(self) -> None:
        browser = ec.generate_private_key(ec.SECP256R1())
        sender = ec.generate_private_key(ec.SECP256R1())
        auth = b"0123456789abcdef"

        body = encrypt(
            b"payload",
            point(browser.public_key()),
            auth,
            salt=b"s" * 16,
            server_key=sender,
        )

        assert body[:16] == b"s" * 16
        assert body[21:86] == point(sender.public_key())
        secret = browser.exchange(ec.ECDH(), sender.public_key())
        assert unseal(body, secret, auth, point(browser.public_key())) == b"payload"


class TestVapidKey:
    def test_its_public_key_is_the_private_keys(self, vapid_key: str) -> None:
        key = VapidKey(vapid_key)

        public = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), unb64(key.public_key)
        )
        assert len(unb64(key.public_key)) == 65
        assert b64(point(public)) == key.public_key

    def test_the_claim_is_for_the_origin_signed_and_within_a_day(
        self, vapid_key: str
    ) -> None:
        key = VapidKey(vapid_key)

        header = key.authorization(
            "https://push.example.com:8443/send/abc?x=1", "https://pilot.example.com"
        )

        scheme, _, credentials = header.partition(" ")
        parts = dict(part.split("=", 1) for part in credentials.split(", "))
        assert scheme == "vapid"
        assert parts["k"] == key.public_key
        claims = jwt.decode(
            parts["t"],
            ec.EllipticCurvePublicKey.from_encoded_point(
                ec.SECP256R1(), unb64(parts["k"])
            ),
            algorithms=["ES256"],
            audience="https://push.example.com:8443",
        )
        assert claims["sub"] == "https://pilot.example.com"
        assert time.time() < claims["exp"] <= time.time() + 24 * 3600


class TestWebPushService:
    def test_a_push_reaches_every_browser_of_the_persons_decrypted(
        self,
        session: Session,
        person: User,
        web_push_service: WebPushService,
        fake_push_service: ServedFakePushService,
    ) -> None:
        phone = fake_push_service.browser(web_push_service.public_key or "")
        desktop = fake_push_service.browser(web_push_service.public_key or "")
        _subscribe(session, person, phone)
        _subscribe(session, person, desktop)
        sent = _sends(PushOutcome.SENT)

        assert web_push_service.push(person.id, ALERT, session)

        assert fake_push_service.pushes(phone.endpoint) == [_pushed(ALERT, "high")]
        assert fake_push_service.pushes(desktop.endpoint) == [_pushed(ALERT, "high")]
        assert _sends(PushOutcome.SENT) == sent + 2

    def test_a_silent_update_goes_at_normal_urgency(
        self,
        session: Session,
        person: User,
        web_push_service: WebPushService,
        fake_push_service: ServedFakePushService,
    ) -> None:
        phone = fake_push_service.browser(web_push_service.public_key or "")
        _subscribe(session, person, phone)
        update = Push("Garden sensors", "Pick the board", PROJECT_ID, URL, False)

        assert web_push_service.push(person.id, update, session)

        assert fake_push_service.pushes(phone.endpoint) == [_pushed(update, "normal")]

    def test_it_pushes_no_other_persons_browser(
        self,
        session: Session,
        person: User,
        web_push_service: WebPushService,
        fake_push_service: ServedFakePushService,
    ) -> None:
        bea = _bea(session)
        hers = fake_push_service.browser(web_push_service.public_key or "")
        _subscribe(session, bea, hers)

        assert not web_push_service.push(person.id, ALERT, session)

        assert fake_push_service.pushes(hers.endpoint) == []

    def test_a_person_with_no_subscription_is_pushed_nothing(
        self, session: Session, person: User, web_push_service: WebPushService
    ) -> None:
        sent = _sends(PushOutcome.SENT)

        assert not web_push_service.push(person.id, ALERT, session)

        assert _sends(PushOutcome.SENT) == sent

    def test_with_no_key_it_pushes_nothing_and_has_no_public_key(
        self,
        session: Session,
        container: ServiceContainer,
        person: User,
        vapid_key: str,
        fake_push_service: ServedFakePushService,
    ) -> None:
        phone = fake_push_service.browser(VapidKey(vapid_key).public_key)
        _subscribe(session, person, phone)
        service = WebPushService(None, "http://localhost:3500")

        assert service.public_key is None
        assert not service.push(person.id, ALERT, session)

        assert fake_push_service.pushes(phone.endpoint) == []

    def test_a_subscription_answered_gone_is_deleted_and_the_others_stay(
        self,
        session: Session,
        person: User,
        web_push_service: WebPushService,
        fake_push_service: ServedFakePushService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        phone = fake_push_service.browser(web_push_service.public_key or "")
        desktop = fake_push_service.browser(web_push_service.public_key or "")
        _subscribe(session, person, phone)
        _subscribe(session, person, desktop)
        fake_push_service.fail(phone.endpoint, "gone")
        gone = _sends(PushOutcome.GONE)

        with caplog.at_level(logging.INFO, logger="app.services.web_push"):
            assert web_push_service.push(person.id, ALERT, session)

        assert _holders(session) == {desktop.endpoint: person.id}
        assert fake_push_service.pushes(desktop.endpoint) == [_pushed(ALERT, "high")]
        assert _sends(PushOutcome.GONE) == gone + 1
        assert "gone (410); it is deleted" in caplog.text

    def test_an_unknown_endpoint_is_gone_too(
        self,
        session: Session,
        person: User,
        web_push_service: WebPushService,
        fake_push_service: ServedFakePushService,
    ) -> None:
        phone = fake_push_service.browser(web_push_service.public_key or "")
        _subscribe(session, person, phone)
        fake_push_service.reset()

        assert not web_push_service.push(person.id, ALERT, session)

        assert _holders(session) == {}

    def test_a_gone_endpoint_another_person_took_meanwhile_stays_theirs(
        self,
        session: Session,
        person: User,
        web_push_service: WebPushService,
        fake_push_service: ServedFakePushService,
    ) -> None:
        bea = _bea(session)
        phone = fake_push_service.browser(web_push_service.public_key or "")
        _subscribe(session, person, phone)
        fake_push_service.fail(phone.endpoint, "gone")
        fake_push_service.on_push = lambda: _subscribe(session, bea, phone)

        assert not web_push_service.push(person.id, ALERT, session)

        assert _holders(session) == {phone.endpoint: bea.id}

    @pytest.mark.parametrize(
        ("failure", "outcome", "logged"),
        [
            ("refused", PushOutcome.REFUSED, "refused a push to subscription"),
            ("error", PushOutcome.UNANSWERED, "did not take a push"),
            ("unanswered", PushOutcome.UNANSWERED, "did not answer a push"),
        ],
    )
    def test_another_failure_is_logged_counted_and_never_retried(
        self,
        session: Session,
        person: User,
        web_push_service: WebPushService,
        fake_push_service: ServedFakePushService,
        caplog: pytest.LogCaptureFixture,
        failure: str,
        outcome: PushOutcome,
        logged: str,
    ) -> None:
        phone = fake_push_service.browser(web_push_service.public_key or "")
        _subscribe(session, person, phone)
        fake_push_service.fail(phone.endpoint, failure)  # type: ignore[arg-type]
        failed = _sends(outcome)

        with caplog.at_level(logging.WARNING, logger="app.services.web_push"):
            assert not web_push_service.push(person.id, ALERT, session)

        assert _sends(outcome) == failed + 1
        assert logged in caplog.text
        assert _holders(session) == {phone.endpoint: person.id}
        fake_push_service.fail(phone.endpoint, None)
        assert fake_push_service.pushes(phone.endpoint) == []
        assert web_push_service.push(person.id, ALERT, session)
        assert fake_push_service.pushes(phone.endpoint) == [_pushed(ALERT, "high")]

    def test_a_push_one_browser_took_went_out(
        self,
        session: Session,
        person: User,
        web_push_service: WebPushService,
        fake_push_service: ServedFakePushService,
    ) -> None:
        phone = fake_push_service.browser(web_push_service.public_key or "")
        desktop = fake_push_service.browser(web_push_service.public_key or "")
        _subscribe(session, person, phone)
        _subscribe(session, person, desktop)
        fake_push_service.fail(phone.endpoint, "error")

        assert web_push_service.push(person.id, ALERT, session)

    def test_a_browser_subscribed_with_another_key_refuses_the_push(
        self,
        session: Session,
        container: ServiceContainer,
        person: User,
        vapid_key: str,
        fake_push_service: ServedFakePushService,
    ) -> None:
        phone = fake_push_service.browser(VapidKey(vapid_key).public_key)
        _subscribe(session, person, phone)
        other = web_push_of(container, mint_vapid_key())
        refused = _sends(PushOutcome.REFUSED)

        assert not other.push(person.id, ALERT, session)

        assert _sends(PushOutcome.REFUSED) == refused + 1
