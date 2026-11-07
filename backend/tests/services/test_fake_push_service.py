"""The fake push service (TEST-1): a push taken as a push service takes one
(RFC 8030, RFC 8291, RFC 8292), decrypted as the browser would, the answers a
test asks for, and the fake's verbs."""

import json
import os
import time
from typing import Any

import jwt
import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from werkzeug.test import Client, TestResponse

from app.services.fake_push_service import (
    FakePush,
    FakePushService,
    FakePushServiceProblem,
    FakeSubscription,
    FakeSubscriptionKeys,
    unseal,
)
from app.services.web_push import (
    RECORD_SIZE,
    Push,
    VapidKey,
    encrypt,
)
from app.utils.base64url import b64, unb64
from tests.support.fake_push_service import ServedFakePushService, mint_vapid_key

ORIGIN = "http://localhost"
CONTACT = "https://pilot.example.com"
PUSH = Push("Garden sensors", "Pick the board", "project-1", f"{CONTACT}/", True)

# RFC 8291 Appendix A's published example, as in test_web_push.py.
RFC_PLAINTEXT = "V2hlbiBJIGdyb3cgdXAsIEkgd2FudCB0byBiZSBhIHdhdGVybWVsb24"
RFC_UA_PUBLIC = (
    "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcx"
    "aOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
)
RFC_AUTH_SECRET = "BTBZMqHH6r4Tts7J_aSIgg"
RFC_ECDH_SECRET = "kyrL1jIIOHEzg3sM2ZWRHDRB62YACZhhSlknJ672kSs"
RFC_BODY = (
    "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml"
    "mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8"
)
RFC_CIPHERTEXT = (
    "8pfeW0KbunFT06SuDKoJH9Ql87S1QUrdirN6GcG7sFz1y1sqLgVi1VhjVkHsUoEsbI_0LpXMuGvnzQ"
)


@pytest.fixture
def key() -> VapidKey:
    return VapidKey(mint_vapid_key())


@pytest.fixture
def fake() -> FakePushService:
    return FakePushService()


@pytest.fixture
def browser(fake: FakePushService, key: VapidKey) -> FakeSubscription:
    return fake.subscribe(key.public_key, origin=ORIGIN)


def _body(browser: FakeSubscription, payload: bytes) -> bytes:
    return encrypt(
        payload,
        unb64(browser.keys.p256dh),
        unb64(browser.keys.auth),
        salt=os.urandom(16),
        server_key=ec.generate_private_key(ec.SECP256R1()),
    )


def _headers(key: VapidKey, browser: FakeSubscription, **extra: str) -> dict[str, str]:
    headers = {
        "Authorization": key.authorization(browser.endpoint, CONTACT),
        "Content-Encoding": "aes128gcm",
        "TTL": "60",
        "Urgency": "high",
    }
    headers.update(extra)
    return {name: value for name, value in headers.items() if value}


def _post(
    fake: FakePushService,
    browser: FakeSubscription,
    key: VapidKey,
    *,
    body: bytes | None = None,
    **headers: str,
) -> TestResponse:
    data = _body(browser, PUSH.payload()) if body is None else body
    return Client(fake).post(
        browser.endpoint.removeprefix(ORIGIN),
        data=data,
        headers=_headers(key, browser, **headers),
    )


def _claim(pem: str, **claims: Any) -> str:
    """The Authorization of a claim signed with `pem`, its claims as given, one
    given None left out."""
    payload = {
        "aud": ORIGIN,
        "exp": int(time.time()) + 3600,
        "sub": CONTACT,
        **claims,
    }
    token = jwt.encode(
        {name: value for name, value in payload.items() if value is not None},
        serialization.load_pem_private_key(pem.encode(), password=None),
        algorithm="ES256",
    )
    return f"vapid t={token}, k={VapidKey(pem).public_key}"


def _error(response: TestResponse) -> tuple[int, str]:
    return response.status_code, response.get_json()["error"]


class TestFakePushServiceSubscriptions:
    def test_a_subscription_is_a_browsers_under_the_origin(
        self, browser: FakeSubscription
    ) -> None:
        assert browser.endpoint.startswith(f"{ORIGIN}/push/")
        ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), unb64(browser.keys.p256dh)
        )
        assert len(unb64(browser.keys.auth)) == 16

    def test_every_subscription_has_its_own_endpoint_and_keys(
        self, fake: FakePushService, key: VapidKey, browser: FakeSubscription
    ) -> None:
        other = fake.subscribe(key.public_key, origin=f"{ORIGIN}/")

        assert other.endpoint.startswith(f"{ORIGIN}/push/")
        assert other.endpoint != browser.endpoint
        assert other.keys != browser.keys

    def test_a_key_that_is_no_p256_point_is_refused(
        self, fake: FakePushService
    ) -> None:
        with pytest.raises(FakePushServiceProblem, match="no P-256 public key"):
            fake.subscribe(b64(b"\x04" + b"\x00" * 64), origin=ORIGIN)


class TestFakePushServicePushes:
    def test_a_push_is_taken_and_kept_decrypted(
        self, fake: FakePushService, key: VapidKey, browser: FakeSubscription
    ) -> None:
        response = _post(fake, browser, key)

        assert response.status_code == 201
        assert response.headers["Location"].startswith(browser.endpoint)
        assert fake.pushes(browser.endpoint) == [
            FakePush(
                "Garden sensors",
                "Pick the board",
                "project-1",
                f"{CONTACT}/",
                True,
                "high",
                60,
            )
        ]

    def test_pushes_are_kept_in_order_per_subscription(
        self, fake: FakePushService, key: VapidKey, browser: FakeSubscription
    ) -> None:
        other = fake.subscribe(key.public_key, origin=ORIGIN)
        update = Push("Garden sensors", "", "project-1", f"{CONTACT}/", False)

        _post(fake, browser, key)
        _post(fake, browser, key, body=_body(browser, update.payload()), Urgency="")

        assert [p.renotify for p in fake.pushes(browser.endpoint)] == [True, False]
        assert fake.pushes(browser.endpoint)[1].urgency == "normal"
        assert fake.pushes(other.endpoint) == []

    def test_an_endpoint_it_never_issued_is_not_found(
        self, fake: FakePushService, key: VapidKey, browser: FakeSubscription
    ) -> None:
        response = Client(fake).post(
            "/push/never-issued", data=b"", headers=_headers(key, browser)
        )

        assert _error(response) == (404, "no such subscription")

    @pytest.mark.parametrize(
        ("authorization", "status", "error"),
        [
            ("", 401, "carries no vapid t= and k="),
            ("WebPush t=x, k=y", 401, "carries no vapid t= and k="),
            ("vapid t=not-a-jwt", 401, "carries no vapid t= and k="),
        ],
    )
    def test_a_push_with_no_claim_is_refused(
        self,
        fake: FakePushService,
        key: VapidKey,
        browser: FakeSubscription,
        authorization: str,
        status: int,
        error: str,
    ) -> None:
        response = _post(fake, browser, key, Authorization=authorization)

        assert _error(response) == (status, f"the push {error}")
        assert fake.pushes(browser.endpoint) == []

    def test_a_push_signed_with_another_key_is_forbidden(
        self, fake: FakePushService, key: VapidKey, browser: FakeSubscription
    ) -> None:
        other = VapidKey(mint_vapid_key())

        response = _post(
            fake,
            browser,
            key,
            Authorization=other.authorization(browser.endpoint, CONTACT),
        )

        assert _error(response) == (
            403,
            "the push's key is not the one the subscription was made with",
        )

    @pytest.mark.parametrize(
        ("claims", "error"),
        [
            ({"aud": "http://elsewhere.example"}, "the claim does not hold"),
            ({"exp": int(time.time()) - 60}, "the claim does not hold"),
            ({"exp": int(time.time()) + 25 * 3600}, "expires over 24 hours"),
            ({"sub": ""}, "the claim's sub is no contact"),
        ],
    )
    def test_a_claim_that_does_not_hold_is_refused(
        self,
        fake: FakePushService,
        claims: dict[str, Any],
        error: str,
    ) -> None:
        pem = mint_vapid_key()
        signed = fake.subscribe(VapidKey(pem).public_key, origin=ORIGIN)

        response = _post(
            fake, signed, VapidKey(pem), Authorization=_claim(pem, **claims)
        )

        status, message = _error(response)
        assert status == 401
        assert error in message

    def test_a_claim_with_no_contact_is_refused(self, fake: FakePushService) -> None:
        pem = mint_vapid_key()
        signed = fake.subscribe(VapidKey(pem).public_key, origin=ORIGIN)

        response = _post(
            fake, signed, VapidKey(pem), Authorization=_claim(pem, sub=None)
        )

        assert response.status_code == 401
        assert "sub" in response.get_json()["error"]

    @pytest.mark.parametrize(
        ("headers", "error"),
        [
            ({"Content-Encoding": "aesgcm"}, "Content-Encoding must be aes128gcm"),
            ({"TTL": ""}, "TTL must be a number of seconds"),
            ({"TTL": "-1"}, "TTL must be a number of seconds"),
            ({"Urgency": "urgent"}, "Urgency urgent is none of RFC 8030's"),
        ],
    )
    def test_a_push_without_its_headers_is_refused(
        self,
        fake: FakePushService,
        key: VapidKey,
        browser: FakeSubscription,
        headers: dict[str, str],
        error: str,
    ) -> None:
        response = _post(fake, browser, key, **headers)

        assert _error(response) == (400, error)

    def test_a_body_over_one_record_is_too_large(
        self, fake: FakePushService, key: VapidKey, browser: FakeSubscription
    ) -> None:
        response = _post(fake, browser, key, body=b"x" * (RECORD_SIZE + 1))

        assert _error(response) == (413, f"the body is 4097 octets, over {RECORD_SIZE}")

    @pytest.mark.parametrize(
        "body", [b"short", b"\x00" * 16 + b"\x00\x00\x10\x00" + b"\x41" + b"\x04" * 65]
    )
    def test_a_body_that_does_not_decrypt_is_refused(
        self,
        fake: FakePushService,
        key: VapidKey,
        browser: FakeSubscription,
        body: bytes,
    ) -> None:
        response = _post(fake, browser, key, body=body)

        assert response.status_code == 400

    def test_a_body_encrypted_to_another_browser_is_refused(
        self, fake: FakePushService, key: VapidKey, browser: FakeSubscription
    ) -> None:
        other = fake.subscribe(key.public_key, origin=ORIGIN)

        response = _post(fake, browser, key, body=_body(other, PUSH.payload()))

        assert _error(response) == (400, "the body does not decrypt")

    @pytest.mark.parametrize(
        "payload",
        [
            b"not json",
            b"[]",
            json.dumps({"title": "t", "body": "b", "tag": "g", "url": "u"}).encode(),
            json.dumps(
                {"title": "t", "body": "b", "tag": "g", "url": "u", "renotify": "yes"}
            ).encode(),
            json.dumps(
                {"title": 1, "body": "b", "tag": "g", "url": "u", "renotify": True}
            ).encode(),
        ],
    )
    def test_a_payload_that_is_not_the_pushs_json_is_refused(
        self,
        fake: FakePushService,
        key: VapidKey,
        browser: FakeSubscription,
        payload: bytes,
    ) -> None:
        response = _post(fake, browser, key, body=_body(browser, payload))

        assert response.status_code == 400
        assert fake.pushes(browser.endpoint) == []

    def test_it_opens_rfc_8291s_example(self) -> None:
        assert unseal(
            unb64(RFC_BODY) + unb64(RFC_CIPHERTEXT),
            unb64(RFC_ECDH_SECRET),
            unb64(RFC_AUTH_SECRET),
            unb64(RFC_UA_PUBLIC),
        ) == unb64(RFC_PLAINTEXT)


class TestFakePushServiceFailures:
    @pytest.mark.parametrize(
        ("failure", "status"), [("gone", 410), ("refused", 429), ("error", 500)]
    )
    def test_a_failing_subscription_answers_its_failure_and_keeps_nothing(
        self,
        fake: FakePushService,
        key: VapidKey,
        browser: FakeSubscription,
        failure: str,
        status: int,
    ) -> None:
        fake.fail(browser.endpoint, failure)  # type: ignore[arg-type]

        response = _post(fake, browser, key)

        assert _error(response) == (status, f"the subscription is {failure}")
        assert fake.pushes(browser.endpoint) == []

    def test_an_unanswered_subscription_closes_the_connection(
        self, key: VapidKey
    ) -> None:
        served = ServedFakePushService()
        try:
            browser = served.browser(key.public_key)
            served.fail(browser.endpoint, "unanswered")

            with pytest.raises(requests.ConnectionError):
                requests.post(
                    browser.endpoint,
                    data=_body(browser, PUSH.payload()),
                    headers=_headers(key, browser),
                    timeout=5,
                )
        finally:
            served.close()

    def test_a_subscription_takes_pushes_again_once_its_failure_is_cleared(
        self, fake: FakePushService, key: VapidKey, browser: FakeSubscription
    ) -> None:
        fake.fail(browser.endpoint)
        fake.fail(browser.endpoint, None)

        assert _post(fake, browser, key).status_code == 201
        assert len(fake.pushes(browser.endpoint)) == 1

    def test_a_subscription_it_never_issued_is_refused_to_a_verb(
        self, fake: FakePushService
    ) -> None:
        with pytest.raises(FakePushServiceProblem, match="issued no subscription"):
            fake.pushes(f"{ORIGIN}/push/never-issued")
        with pytest.raises(FakePushServiceProblem, match="issued no subscription"):
            fake.fail(f"{ORIGIN}/push/never-issued")

    def test_reset_forgets_every_subscription(
        self, fake: FakePushService, key: VapidKey, browser: FakeSubscription
    ) -> None:
        fake.reset()

        assert _post(fake, browser, key).status_code == 404


class TestFakePushServiceVerbs:
    def test_a_test_drives_it_over_http(
        self, fake: FakePushService, key: VapidKey
    ) -> None:
        client = Client(fake)

        subscribed = client.post(
            "/fake/subscribe",
            json={"application_server_key": key.public_key, "origin": "http://x"},
        )
        browser = FakeSubscription(
            subscribed.get_json()["endpoint"],
            FakeSubscriptionKeys(**subscribed.get_json()["keys"]),
        )
        pushed = _post(fake, browser, key)
        pushes = client.post("/fake/pushes", json={"endpoint": browser.endpoint})
        failed = client.post(
            "/fake/fail", json={"endpoint": browser.endpoint, "failure": "gone"}
        )
        reset = client.post("/fake/reset")

        assert subscribed.status_code == 200
        assert browser.endpoint.startswith(f"{ORIGIN}/push/")
        assert pushed.status_code == 201
        assert [p["body"] for p in pushes.get_json()] == ["Pick the board"]
        assert failed.status_code == 204
        assert reset.status_code == 204

    def test_an_unknown_verb_is_refused(self, fake: FakePushService) -> None:
        response = Client(fake).post("/fake/dismiss", json={})

        assert _error(response) == (404, "the fake has no verb dismiss")

    @pytest.mark.parametrize(
        ("verb", "body"),
        [
            ("pushes", {}),
            ("fail", {"endpoint": "e", "failure": "lost"}),
            ("reset", {"everything": True}),
            ("pushes", ["e"]),
        ],
    )
    def test_arguments_it_does_not_take_are_refused(
        self, fake: FakePushService, verb: str, body: Any
    ) -> None:
        response = Client(fake).post(f"/fake/{verb}", json=body)

        assert response.status_code == 422

    def test_a_verbs_own_refusal_answers_its_status(
        self, fake: FakePushService
    ) -> None:
        response = Client(fake).post("/fake/pushes", json={"endpoint": "e"})

        assert _error(response) == (404, "the fake issued no subscription e")

    def test_a_path_or_method_it_has_no_route_for_is_refused(
        self, fake: FakePushService
    ) -> None:
        assert Client(fake).get("/push/x").status_code == 405
        assert Client(fake).post("/elsewhere").status_code == 404
