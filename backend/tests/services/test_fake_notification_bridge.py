"""The fake notification bridge (the Q1 ruling): the bridge's paths, fields,
limits, status codes and priority rule, as `pvginkel/Notifications` pins them
(its README and `bridge/tests/test_api.py`), and the fake's verbs."""

import json
import threading
from typing import Any

import pytest
import requests
from werkzeug.test import Client, TestResponse

from app.services.fake_notification_bridge import (
    FakeCall,
    FakeNotification,
    FakeNotificationBridge,
    FakeNotificationBridgeProblem,
)
from tests.support.fake_notification_bridge import ServedFakeNotificationBridge

TOKEN = "invented-ada-token"
PRIORITIES = ["min", "low", "default", "high", "max"]

URL = "https://jenkins.example.invalid/job/ansible/61/"
# 2048 characters, the most a url may have.
LONGEST_URL = "https://example.invalid/" + "u" * 2024
# A body nested past the interpreter's recursion limit.
DEEP = b'{"message": ' + b"[" * 200_000 + b"]" * 200_000 + b"}"


@pytest.fixture
def fake() -> FakeNotificationBridge:
    """The fake, with Ada's registration under ``TOKEN``."""
    fake = FakeNotificationBridge()
    fake.add_registration("ada", TOKEN)
    return fake


def _post(
    fake: FakeNotificationBridge,
    path: str,
    body: Any,
    authorization: str | None = f"Bearer {TOKEN}",
) -> TestResponse:
    data = body if isinstance(body, bytes) else json.dumps(body)
    headers = {} if authorization is None else {"Authorization": authorization}
    return Client(fake).post(path, data=data, headers=headers)


def _submit(fake: FakeNotificationBridge, **fields: Any) -> TestResponse:
    return _post(fake, "/v1/submit", fields)


def _dismiss(fake: FakeNotificationBridge, sequence_id: str) -> TestResponse:
    return _post(fake, "/v1/dismiss", {"sequence_id": sequence_id})


def _alerted(fake: FakeNotificationBridge, sequence_id: str) -> bool:
    return fake.shown("ada")[sequence_id].alerted


class TestFakeNotificationBridgeApi:
    def test_the_paths_and_their_methods(self, fake: FakeNotificationBridge) -> None:
        client = Client(fake)

        health = client.get("/healthz")
        nowhere = client.get("/nowhere")

        assert (health.status_code, health.text) == (200, "ok")
        assert _submit(fake, message="m").status_code == 200
        assert _dismiss(fake, "s").status_code == 200
        assert client.get("/v1/submit").status_code == 405
        assert client.get("/v1/dismiss").status_code == 405
        assert (nowhere.status_code, nowhere.mimetype) == (404, "text/plain")

    def test_a_submit_and_a_dismiss_answer_the_channels_result(
        self, fake: FakeNotificationBridge
    ) -> None:
        submitted = _submit(fake, sequence_id="s", priority="high", message="m")
        dismissed = _dismiss(fake, "s")

        assert (submitted.status_code, submitted.get_json()) == (200, {"ntfy": "ok"})
        assert (dismissed.status_code, dismissed.get_json()) == (200, {"ntfy": "ok"})

    @pytest.mark.parametrize(
        "body",
        [
            {"message": "m"},
            {"message": "m", "sequence_id": "s" * 256},
            {"message": "m", "title": "t" * 250},
            {"message": "m", "title": ""},
            {"message": "m" * 4096},
            {"message": "\N{POLICE CARS REVOLVING LIGHT}" * 4096},
            *({"message": "m", "priority": priority} for priority in PRIORITIES),
            {"message": "m", "url": URL},
            {"message": "m", "url": LONGEST_URL},
            {"message": "m", "url": "http://example.invalid/caf%C3%A9?q=a%20b#top"},
            {"message": "m", "url": "http://grafana/d/61"},
            {"message": "m", "url": "http://10.1.0.29:9090/graph"},
            {
                "message": "m",
                "sequence_id": None,
                "priority": None,
                "title": None,
                "url": None,
            },
        ],
    )
    def test_a_submit_takes_every_field_within_its_limit(
        self, fake: FakeNotificationBridge, body: dict[str, Any]
    ) -> None:
        assert _post(fake, "/v1/submit", body).status_code == 200

    @pytest.mark.parametrize(
        ("body", "status", "error"),
        [
            ([], 400, "the body must be a JSON object"),
            ({}, 400, "message is missing"),
            ({"message": None}, 400, "message is missing"),
            ({"message": "m", "colour": "red"}, 400, "unknown fields: colour"),
            ({"message": 61}, 400, "message must be a string"),
            ({"message": " \n\t"}, 400, "message is blank"),
            (
                {"message": "m" * 4097},
                413,
                "message is 4097 characters, over the limit of 4096",
            ),
            (
                {"message": "m", "sequence_id": ""},
                400,
                "sequence_id must be 1 to 256 characters",
            ),
            (
                {"message": "m", "sequence_id": "s" * 257},
                400,
                "sequence_id must be 1 to 256 characters",
            ),
            ({"message": "m", "sequence_id": 61}, 400, "sequence_id must be a string"),
            (
                {"message": "m", "title": "t" * 251},
                400,
                "title is 251 characters, over the limit of 250",
            ),
            ({"message": "m", "title": ["t"]}, 400, "title must be a string"),
            *(
                (
                    {"message": "m", "priority": priority},
                    400,
                    "priority must be one of min, low, default, high, max",
                )
                for priority in ["urgent", "HIGH", 4, ""]
            ),
            (
                {"message": "m" * 4097, "title": "t" * 251},
                400,
                "title is 251 characters, over the limit of 250",
            ),
            (b'{"message": "\\ud800"}', 400, "message holds a lone surrogate"),
            (
                b'{"message": "m", "sequence_id": "\\udfff"}',
                400,
                "sequence_id holds a lone surrogate",
            ),
            ({"message": "m", "url": 61}, 400, "url must be a string"),
            *(
                (
                    {"message": "m", "url": url},
                    400,
                    "url must be an absolute http or https URL",
                )
                for url in [
                    "",
                    "/job/ansible/61/",
                    "jenkins.example.invalid/job/ansible/61/",
                    "//jenkins.example.invalid/job/ansible/61/",
                    "ftp://example.invalid/build.log",
                    "tg://resolve?domain=invented_bot",
                    "javascript:alert(1)",
                    "https://",
                    "https:///job/ansible/61/",
                    "https://[::1/job",
                ]
            ),
            (
                {"message": "m", "url": "https://example.invalid/café"},
                400,
                "url must be ASCII, the rest percent-encoded",
            ),
            *(
                (
                    {"message": "m", "url": url},
                    400,
                    "url holds whitespace or a control character",
                )
                for url in [
                    "https://example.invalid/a b",
                    "https://example.invalid/a\tb",
                    "https://example.invalid/\r\nX-Injected: 1",
                    "https://example.invalid/\x00",
                    "https://example.invalid/\x7f",
                    " https://example.invalid/",
                ]
            ),
            (
                {"message": "m", "url": LONGEST_URL + "u"},
                400,
                "url is 2049 characters, over the limit of 2048",
            ),
            (
                b'{"message": "m", "url": "https://invented/\\ud800"}',
                400,
                "url holds a lone surrogate",
            ),
        ],
    )
    def test_a_submit_refuses_a_malformed_or_oversized_body(
        self, fake: FakeNotificationBridge, body: Any, status: int, error: str
    ) -> None:
        response = _post(fake, "/v1/submit", body)

        assert (response.status_code, response.get_json()) == (
            status,
            {"error": error},
        )
        assert fake.calls("ada") == []

    @pytest.mark.parametrize(
        "body", [b"", b"{", b"\xff", pytest.param(DEEP, id="nested-too-deep")]
    )
    def test_a_submit_refuses_a_body_that_is_not_json(
        self, fake: FakeNotificationBridge, body: bytes
    ) -> None:
        response = _post(fake, "/v1/submit", body)

        assert response.status_code == 400
        assert response.get_json()["error"].startswith("the body is not JSON: ")

    def test_a_dismiss_takes_a_sequence_id_within_its_limit(
        self, fake: FakeNotificationBridge
    ) -> None:
        assert _dismiss(fake, "s" * 256).status_code == 200

    @pytest.mark.parametrize(
        ("body", "error"),
        [
            ({}, "sequence_id is missing"),
            ({"sequence_id": None}, "sequence_id is missing"),
            ({"sequence_id": ""}, "sequence_id must be 1 to 256 characters"),
            ({"sequence_id": "s" * 257}, "sequence_id must be 1 to 256 characters"),
            ({"sequence_id": "s", "message": "m"}, "unknown fields: message"),
            (["s"], "the body must be a JSON object"),
        ],
    )
    def test_a_dismiss_refuses_a_malformed_body(
        self, fake: FakeNotificationBridge, body: Any, error: str
    ) -> None:
        response = _post(fake, "/v1/dismiss", body)

        assert (response.status_code, response.get_json()) == (400, {"error": error})
        assert fake.calls("ada") == []

    @pytest.mark.parametrize("path", ["/v1/submit", "/v1/dismiss"])
    @pytest.mark.parametrize(
        "authorization",
        [
            None,
            "Bearer invented-unknown-token",
            f"Basic {TOKEN}",
            TOKEN,
        ],
    )
    def test_an_unknown_token_is_refused_before_the_body_is_read(
        self, fake: FakeNotificationBridge, path: str, authorization: str | None
    ) -> None:
        response = _post(fake, path, b"not even JSON", authorization)

        assert (response.status_code, response.get_json()) == (
            401,
            {"error": "unknown bearer token"},
        )
        assert response.headers["WWW-Authenticate"] == "Bearer"

    def test_the_scheme_is_case_insensitive(self, fake: FakeNotificationBridge) -> None:
        response = _post(fake, "/v1/submit", {"message": "m"}, f"bearer {TOKEN}")

        assert response.status_code == 200


class TestFakeNotificationBridgeRegistrations:
    def test_a_submit_shows_what_it_carries(self, fake: FakeNotificationBridge) -> None:
        _submit(fake, sequence_id="s", priority="high", title="t", message="m", url=URL)

        assert fake.shown("ada") == {
            "s": FakeNotification("s", "high", "t", "m", URL, True)
        }

    @pytest.mark.parametrize(
        ("priority", "alerted"),
        [
            ("min", False),
            ("low", False),
            ("default", True),
            ("high", True),
            ("max", True),
        ],
    )
    def test_a_first_submit_alerts_at_default_or_above(
        self, fake: FakeNotificationBridge, priority: str, alerted: bool
    ) -> None:
        _submit(fake, sequence_id="s", priority=priority, message="m")

        assert _alerted(fake, "s") is alerted

    @pytest.mark.parametrize("later", ["high", "default", "min"])
    def test_the_same_or_a_lower_priority_updates_in_place_silently(
        self, fake: FakeNotificationBridge, later: str
    ) -> None:
        _submit(fake, sequence_id="s", priority="high", message="first")

        _submit(fake, sequence_id="s", priority=later, message="second")

        assert fake.shown("ada")["s"] == FakeNotification(
            "s", later, None, "second", None, False
        )

    @pytest.mark.parametrize(
        ("earlier", "later", "alerted"),
        [
            ("min", "default", True),
            ("default", "high", True),
            ("min", "low", False),
        ],
    )
    def test_a_higher_priority_rises_and_alerts_at_default_or_above(
        self, fake: FakeNotificationBridge, earlier: str, later: str, alerted: bool
    ) -> None:
        _submit(fake, sequence_id="s", priority=earlier, message="m")

        _submit(fake, sequence_id="s", priority=later, message="m")

        assert _alerted(fake, "s") is alerted

    def test_a_sequence_that_went_down_can_rise_again(
        self, fake: FakeNotificationBridge
    ) -> None:
        _submit(fake, sequence_id="s", priority="high", message="m")
        _submit(fake, sequence_id="s", priority="min", message="m")

        _submit(fake, sequence_id="s", priority="default", message="m")

        assert _alerted(fake, "s") is True

    def test_a_dismiss_frees_the_sequence_id(
        self, fake: FakeNotificationBridge
    ) -> None:
        _submit(fake, sequence_id="s", priority="high", message="m")

        _dismiss(fake, "s")
        shown_after_dismiss = fake.shown("ada")
        _submit(fake, sequence_id="s", priority="default", message="m")

        assert shown_after_dismiss == {}
        assert _alerted(fake, "s") is True

    def test_a_dismiss_of_a_sequence_id_never_shown_is_taken(
        self, fake: FakeNotificationBridge
    ) -> None:
        response = _dismiss(fake, "never")

        assert (response.status_code, response.get_json()) == (200, {"ntfy": "ok"})
        assert fake.calls("ada") == [FakeCall("dismiss", "never", False)]

    def test_a_one_shot_is_kept_apart_and_alerts_by_its_priority(
        self, fake: FakeNotificationBridge
    ) -> None:
        _submit(fake, message="one", priority="min")
        _submit(fake, message="two")

        assert fake.one_shots("ada") == [
            FakeNotification(None, "min", None, "one", None, False),
            FakeNotification(None, "default", None, "two", None, True),
        ]
        assert fake.shown("ada") == {}

    def test_sequence_ids_belong_to_their_registration(
        self, fake: FakeNotificationBridge
    ) -> None:
        fake.add_registration("bea", "invented-bea-token")
        _submit(fake, sequence_id="s", priority="high", message="Ada's")

        _post(
            fake,
            "/v1/submit",
            {"sequence_id": "s", "message": "Bea's"},
            "Bearer invented-bea-token",
        )
        _post(fake, "/v1/dismiss", {"sequence_id": "s"}, "Bearer invented-bea-token")

        assert fake.shown("ada")["s"].message == "Ada's"
        assert fake.shown("bea") == {}

    def test_calls_lists_every_call_taken_in_order(
        self, fake: FakeNotificationBridge
    ) -> None:
        _submit(fake, sequence_id="s", priority="min", message="m")
        _submit(fake, sequence_id="s", priority="high", message="m")
        _submit(fake, message="m")
        _submit(fake, sequence_id="s", message="m" * 4097)
        _dismiss(fake, "s")

        assert fake.calls("ada") == [
            FakeCall("submit", "s", False),
            FakeCall("submit", "s", True),
            FakeCall("submit", None, True),
            FakeCall("dismiss", "s", False),
        ]

    def test_a_rotated_token_keeps_what_the_registration_shows_and_refuses_the_old(
        self, fake: FakeNotificationBridge
    ) -> None:
        _submit(fake, sequence_id="s", priority="high", message="m")

        fake.rotate_token("ada", "invented-new-token")
        old = _submit(fake, sequence_id="s", message="m")
        new = _post(
            fake,
            "/v1/submit",
            {"sequence_id": "s", "priority": "high", "message": "again"},
            "Bearer invented-new-token",
        )

        assert old.status_code == 401
        assert new.status_code == 200
        assert fake.shown("ada")["s"] == FakeNotification(
            "s", "high", None, "again", None, False
        )

    def test_a_failing_channel_answers_its_error_and_changes_nothing(
        self, fake: FakeNotificationBridge
    ) -> None:
        _submit(fake, sequence_id="s", message="first")
        fake.channel_error("ada", "publish: HTTP 500: down")

        submitted = _submit(fake, sequence_id="s", message="second")
        dismissed = _dismiss(fake, "s")
        one_shot = _submit(fake, message="m")

        for response in (submitted, dismissed, one_shot):
            assert (response.status_code, response.get_json()) == (
                200,
                {"ntfy": "error: publish: HTTP 500: down"},
            )
        assert fake.shown("ada")["s"].message == "first"
        assert fake.one_shots("ada") == []
        assert fake.calls("ada") == [FakeCall("submit", "s", True)]

    def test_a_channel_answers_again_once_its_error_is_cleared(
        self, fake: FakeNotificationBridge
    ) -> None:
        fake.channel_error("ada", "publish: HTTP 500: down")

        fake.channel_error("ada")

        assert _submit(fake, message="m").get_json() == {"ntfy": "ok"}

    @pytest.mark.parametrize(
        ("name", "token"),
        [("ada", "invented-other-token"), ("bea", TOKEN)],
        ids=["name", "token"],
    )
    def test_a_registration_or_token_given_twice_is_refused(
        self, fake: FakeNotificationBridge, name: str, token: str
    ) -> None:
        with pytest.raises(FakeNotificationBridgeProblem) as problem:
            fake.add_registration(name, token)

        assert problem.value.status == 409

    def test_a_token_another_registration_holds_is_refused_to_a_rotation(
        self, fake: FakeNotificationBridge
    ) -> None:
        fake.add_registration("bea", "invented-bea-token")

        with pytest.raises(FakeNotificationBridgeProblem, match="holds that token"):
            fake.rotate_token("ada", "invented-bea-token")

    @pytest.mark.parametrize("verb", ["shown", "one_shots", "calls"])
    def test_a_registration_it_does_not_have_is_refused(
        self, fake: FakeNotificationBridge, verb: str
    ) -> None:
        with pytest.raises(FakeNotificationBridgeProblem) as problem:
            getattr(fake, verb)("nobody")

        assert (problem.value.status, problem.value.error) == (
            404,
            "the fake has no registration nobody",
        )

    def test_reset_forgets_every_registration_and_answers_again(
        self, fake: FakeNotificationBridge
    ) -> None:
        _submit(fake, sequence_id="s", message="m")
        fake.unreachable(answer="error")

        fake.reset()

        assert _submit(fake, message="m").status_code == 401
        with pytest.raises(FakeNotificationBridgeProblem):
            fake.shown("ada")


class TestFakeNotificationBridgeUnreachable:
    @pytest.fixture
    def served(
        self, fake_notification_bridge: ServedFakeNotificationBridge
    ) -> ServedFakeNotificationBridge:
        fake_notification_bridge.add_registration("ada", TOKEN)
        return fake_notification_bridge

    def _submit(self, served: ServedFakeNotificationBridge) -> requests.Response:
        return requests.post(
            f"{served.url}/v1/submit",
            json={"sequence_id": "s", "message": "m"},
            headers={"Authorization": f"Bearer {TOKEN}"},
            timeout=5,
        )

    def test_no_answer_closes_every_call_but_the_verbs(
        self, served: ServedFakeNotificationBridge
    ) -> None:
        served.unreachable()

        with pytest.raises(requests.ConnectionError):
            self._submit(served)
        with pytest.raises(requests.ConnectionError):
            requests.get(f"{served.url}/healthz", timeout=5)
        verb = requests.post(
            f"{served.url}/fake/shown", json={"name": "ada"}, timeout=5
        )

        assert (verb.status_code, verb.json()) == (200, {})

    def test_an_error_answers_500(self, served: ServedFakeNotificationBridge) -> None:
        served.unreachable(answer="error")

        response = self._submit(served)

        assert (response.status_code, response.text) == (500, "Internal Server Error")
        assert served.calls("ada") == []

    def test_a_reachable_bridge_answers_again(
        self, served: ServedFakeNotificationBridge
    ) -> None:
        served.unreachable()

        served.unreachable(on=False)

        assert self._submit(served).status_code == 200

    def test_a_stalled_call_is_held_until_the_bridge_answers_again(
        self, served: ServedFakeNotificationBridge
    ) -> None:
        served.unreachable(answer="stall")
        answers: list[requests.Response] = []
        caller = threading.Thread(target=lambda: answers.append(self._submit(served)))
        caller.start()

        caller.join(timeout=0.3)
        held = caller.is_alive()
        served.unreachable(on=False)
        caller.join()

        assert held
        assert answers[0].status_code == 200
        assert "s" in served.shown("ada")

    def test_close_answers_a_stalled_call(
        self, served: ServedFakeNotificationBridge
    ) -> None:
        served.unreachable(answer="stall")
        answers: list[requests.Response] = []
        caller = threading.Thread(target=lambda: answers.append(self._submit(served)))
        caller.start()
        caller.join(timeout=0.3)
        held = caller.is_alive()

        FakeNotificationBridge.close(served)
        caller.join()

        assert held
        assert answers[0].status_code == 200


class TestFakeNotificationBridgeVerbs:
    def _verb(
        self, fake: FakeNotificationBridge, verb: str, body: Any = None
    ) -> TestResponse:
        return Client(fake).post(f"/fake/{verb}", json=body)

    def test_a_test_drives_it_over_http(self, fake: FakeNotificationBridge) -> None:
        added = self._verb(fake, "add-registration", {"name": "bea", "token": "b"})
        _post(fake, "/v1/submit", {"sequence_id": "s", "message": "m"}, "Bearer b")
        _post(fake, "/v1/submit", {"message": "hi"}, "Bearer b")
        shown = self._verb(fake, "shown", {"name": "bea"})
        one_shots = self._verb(fake, "one-shots", {"name": "bea"})
        calls = self._verb(fake, "calls", {"name": "bea"})

        assert added.status_code == 204
        assert shown.get_json() == {
            "s": {
                "sequence_id": "s",
                "priority": "default",
                "title": None,
                "message": "m",
                "url": None,
                "alerted": True,
            }
        }
        assert [n["message"] for n in one_shots.get_json()] == ["hi"]
        assert calls.get_json() == [
            {"call": "submit", "sequence_id": "s", "alerted": True},
            {"call": "submit", "sequence_id": None, "alerted": True},
        ]

    def test_the_other_verbs_answer_over_http(
        self, fake: FakeNotificationBridge
    ) -> None:
        rotated = self._verb(fake, "rotate-token", {"name": "ada", "token": "new"})
        failing = self._verb(fake, "channel-error", {"name": "ada", "error": "down"})
        unreachable = self._verb(fake, "unreachable", {"answer": "error"})
        reachable = self._verb(fake, "unreachable", {"on": False})
        reset = self._verb(fake, "reset")

        assert [
            r.status_code for r in (rotated, failing, unreachable, reachable, reset)
        ] == [204] * 5

    def test_an_unknown_verb_is_refused(self, fake: FakeNotificationBridge) -> None:
        response = self._verb(fake, "explode")

        assert (response.status_code, response.get_json()) == (
            404,
            {"error": "the fake has no verb explode"},
        )

    @pytest.mark.parametrize(
        "body",
        [{"name": 1}, {"nobody": "x"}, ["ada"]],
        ids=["wrong-type", "unknown-argument", "not-an-object"],
    )
    def test_arguments_it_does_not_take_are_refused(
        self, fake: FakeNotificationBridge, body: Any
    ) -> None:
        response = self._verb(fake, "shown", body)

        assert response.status_code == 422

    def test_a_verbs_own_refusal_answers_its_status(
        self, fake: FakeNotificationBridge
    ) -> None:
        response = self._verb(fake, "shown", {"name": "nobody"})

        assert (response.status_code, response.get_json()) == (
            404,
            {"error": "the fake has no registration nobody"},
        )
