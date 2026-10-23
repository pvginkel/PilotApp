"""The fake controller's own surface: its verbs over HTTP, and what the client
never sends it (design 2 §12). Its controller routes are under test through
the real client, in `test_controller_client.py`."""

import json
import socket

import pytest
from pydantic import ValidationError
from werkzeug.test import Client

from app.services.fake_controller import FakeController, FakeControllerProblem

TOKEN = "fake-token"
BEARER = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def fake() -> FakeController:
    return FakeController(TOKEN, keepalive_seconds=0.1)


@pytest.fixture
def http(fake: FakeController) -> Client:
    return Client(fake)


class TestFakeController:
    def test_a_verb_is_served_with_its_keyword_arguments_as_the_body(
        self, fake: FakeController, http: Client
    ) -> None:
        response = http.post(
            "/fake/add-environment",
            json={"env_id": "env-1", "status": "running", "exempt": True},
        )

        assert response.status_code == 204
        assert fake.environment("env-1").exempt is True

    def test_a_verb_with_an_answer_answers_it(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1", status="running")
        created = http.post("/environments/env-1/sessions/headless", headers=BEARER)
        name = created.get_json()["name"]

        response = http.post(
            "/fake/play", json={"env_id": "env-1", "name": name, "lines": ["ab", "c"]}
        )

        assert response.status_code == 200
        assert response.get_json() == [3, 5]

    @pytest.mark.parametrize(
        "verb",
        [
            "add-environment",
            "remove-environment",
            "set-status",
            "set-exempt",
            "settle-starts",
            "restart",
            "recreate-pod",
            "unreachable",
            "outage",
            "capped",
            "unprojectable",
            "busy",
            "play",
            "finish",
            "write-log",
            "publish-state",
            "publish-sessions",
            "drop-streams",
            "reset",
        ],
    )
    def test_every_verb_is_served(self, http: Client, verb: str) -> None:
        # No argument at all: a verb that takes one refuses with 422, one that
        # takes none answers 204; neither is unknown.
        response = http.post(f"/fake/{verb}", json={})

        assert response.status_code in (204, 422)

    def test_an_unknown_verb_is_not_found(self, http: Client) -> None:
        response = http.post("/fake/explode", json={})

        assert response.status_code == 404
        assert response.get_json()["type"] == "not-found"

    @pytest.mark.parametrize(
        "body", [{"env_id": 1}, {"env_id": "env-1", "status": "sleeping"}, ["env-1"]]
    )
    def test_a_verb_refuses_arguments_it_does_not_take(
        self, http: Client, body: object
    ) -> None:
        response = http.post("/fake/add-environment", json=body)

        assert response.status_code == 422
        assert response.headers["Content-Type"] == "application/problem+json"
        assert response.get_json()["type"] == "validation-error"

    def test_an_unprojectable_environment_is_listed_as_such(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1")
        fake.add_environment("env-2")

        http.post("/fake/unprojectable", json={"env_id": "env-1"})

        listing = http.get("/environments", headers=BEARER).get_json()
        assert [item["envId"] for item in listing["items"]] == ["env-2"]
        assert listing["unprojectable"] == ["env-1"]

    def test_a_verb_on_an_unknown_environment_is_not_found(self, http: Client) -> None:
        response = http.post("/fake/restart", json={"env_id": "env-9"})

        assert response.status_code == 404

    def test_a_verb_called_in_process_validates_its_arguments(
        self, fake: FakeController
    ) -> None:
        with pytest.raises(ValidationError):
            fake.add_environment("env-1", status="sleeping")  # type: ignore[arg-type]

    def test_a_raw_line_holds_no_newline(self, fake: FakeController) -> None:
        fake.add_environment("env-1", status="running")
        Client(fake).post("/environments/env-1/sessions/headless", headers=BEARER)

        with pytest.raises(FakeControllerProblem) as caught:
            fake.play("env-1", "claude-1", ["two\nlines"])

        assert caught.value.status == 422

    def test_finish_needs_a_turn_in_flight(self, fake: FakeController) -> None:
        fake.add_environment("env-1", status="running")
        Client(fake).post("/environments/env-1/sessions/headless", headers=BEARER)

        with pytest.raises(FakeControllerProblem) as caught:
            fake.finish("env-1", "claude-1")

        assert (caught.value.status, caught.value.problem_type) == (409, "conflict")

    def test_a_controller_route_needs_the_bearer(self, http: Client) -> None:
        response = http.get("/environments")

        assert response.status_code == 401
        assert response.get_json() == {
            "type": "unauthenticated",
            "title": "the bearer is not a client's credential",
            "status": 401,
        }

    def test_readyz_needs_no_bearer(self, http: Client) -> None:
        response = http.get("/readyz")

        assert response.status_code == 200
        assert response.get_json() == {"status": "ok", "checks": {}}

    def test_a_path_with_no_route_is_the_routers_answer(self, http: Client) -> None:
        response = http.get("/no/such/route", headers=BEARER)

        assert response.status_code == 404
        assert response.headers["Content-Type"] == "application/json"
        assert response.get_json() == {"detail": "Not Found"}

    def test_calls_are_recorded_with_their_query(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1")
        http.get("/environments", headers=BEARER)
        http.get("/environments/env-1?wait=none", headers=BEARER)
        http.post("/fake/capped", json={"env_id": "env-1"})
        http.get("/readyz")

        assert fake.calls == ["GET /environments", "GET /environments/env-1?wait=none"]

    def test_get_environment_refuses_an_unknown_wait(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1")

        response = http.get("/environments/env-1?wait=forever", headers=BEARER)

        assert response.status_code == 422

    def test_the_response_stream_serves_format_raw_alone(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1", status="running")
        http.post("/environments/env-1/sessions/headless", headers=BEARER)

        response = http.get(
            "/environments/env-1/sessions/headless/claude-1/response", headers=BEARER
        )

        assert response.status_code == 422

    def test_create_refuses_a_field_the_controller_does_not_know(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1", status="running")

        response = http.post(
            "/environments/env-1/sessions/headless",
            json={"prompt": "hi"},
            headers=BEARER,
        )

        assert response.status_code == 422
        assert fake.sessions("env-1") == []

    def test_send_needs_a_message(self, fake: FakeController, http: Client) -> None:
        fake.add_environment("env-1", status="running")
        http.post("/environments/env-1/sessions/headless", headers=BEARER)

        response = http.post(
            "/environments/env-1/sessions/headless/claude-1/messages",
            json={},
            headers=BEARER,
        )

        assert response.status_code == 422
        assert fake.session("env-1", "claude-1").status == "idle"

    def test_a_stopped_environment_holds_no_session(self, fake: FakeController) -> None:
        fake.add_environment("env-1", status="running")
        Client(fake).post("/environments/env-1/sessions/headless", headers=BEARER)

        fake.set_status("env-1", "stopped")

        assert fake.sessions("env-1") == []

    def test_a_held_start_stays_starting(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1")
        fake.settle_starts("env-1", None)

        response = http.post("/environments/env-1/start", headers=BEARER)

        assert response.status_code == 202
        assert fake.environment("env-1").status == "starting"

    def test_a_start_can_settle_in_error(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1")
        fake.settle_starts("env-1", "error")

        http.post("/environments/env-1/start", headers=BEARER)

        assert fake.environment("env-1").status == "error"

    def test_each_new_pod_reports_a_later_start(
        self, fake: FakeController, http: Client
    ) -> None:
        def started_at() -> str | None:
            pod = http.get("/environments/env-1", headers=BEARER).get_json()["pod"]
            return None if pod is None else pod["startedAt"]

        fake.add_environment("env-1")
        assert started_at() is None

        http.post("/environments/env-1/start", headers=BEARER)
        brought_up = started_at()
        fake.restart("env-1")
        fake.set_status("env-1", "running")
        assert started_at() == brought_up

        fake.set_status("env-1", "stopped")
        assert started_at() is None
        fake.set_status("env-1", "running")
        started_again = started_at()
        fake.recreate_pod("env-1")
        fake.set_status("env-1", "running")
        recreated = started_at()

        assert brought_up is not None and started_again is not None
        assert recreated is not None
        assert brought_up < started_again < recreated
        assert recreated.endswith("Z")

    def test_a_recreated_pod_holds_no_session(self, fake: FakeController) -> None:
        fake.add_environment("env-1", status="running")
        Client(fake).post("/environments/env-1/sessions/headless", headers=BEARER)

        fake.recreate_pod("env-1")

        assert fake.sessions("env-1") == []
        assert fake.environment("env-1").status == "starting"

    def test_an_outage_answers_every_call_as_an_ingress_and_still_takes_verbs(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.outage(answer="ingress")

        listing = http.get("/environments", headers=BEARER)
        ready = http.get("/readyz")
        added = http.post("/fake/add-environment", json={"env_id": "env-1"})

        for response in (listing, ready):
            assert response.status_code == 502
            assert response.headers["Content-Type"].startswith("text/html")
            assert "502 Bad Gateway" in response.get_data(as_text=True)
        assert added.status_code == 204
        assert fake.calls == []

    def test_an_outage_with_no_answer_shuts_the_calls_connection(
        self, fake: FakeController, http: Client
    ) -> None:
        class _Connection:
            shut: int | None = None

            def shutdown(self, how: int) -> None:
                self.shut = how

        connection = _Connection()
        fake.outage()

        http.get(
            "/environments",
            headers=BEARER,
            environ_overrides={"werkzeug.socket": connection},
        )

        assert connection.shut == socket.SHUT_RDWR
        assert fake.calls == []

    def test_an_outage_ends_every_open_stream(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1")
        response = http.get("/stream", headers=BEARER, buffered=False)
        frames = iter(response.response)
        assert next(frames) == b""
        next(frames)

        fake.outage(answer="ingress")

        assert list(frames) == []
        response.close()

    def test_answering_again_ends_the_outage(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.outage(answer="ingress")

        fake.outage(on=False)

        assert http.get("/environments", headers=BEARER).status_code == 200

    def test_reset_forgets_everything(self, fake: FakeController, http: Client) -> None:
        fake.add_environment("env-1")
        http.get("/environments", headers=BEARER)
        fake.outage(answer="ingress")

        fake.reset()

        assert fake.calls == []
        listing = http.get("/environments", headers=BEARER).get_json()
        assert listing == {"items": [], "unprojectable": []}

    def test_the_fleet_stream_carries_the_frames_published_on_demand(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1")
        response = http.get("/stream", headers=BEARER, buffered=False)
        frames = iter(response.response)
        assert next(frames) == b""
        seed = next(frames)

        fake.publish_state("env-1")
        fake.set_exempt("env-1", True)
        fake.publish_sessions("env-1")
        published = [next(frames), next(frames), next(frames)]
        fake.close()
        response.close()

        assert seed == b'event: sessions\ndata: {"envId":"env-1","sessions":[]}\n\n'
        state, exempt, sessions = (frame.decode() for frame in published)
        assert state.startswith("event: state\ndata: ")
        environment = json.loads(exempt.removeprefix("event: state\ndata: "))
        assert environment["capabilities"] == {"capacityExempt": {"enabled": True}}
        assert sessions == seed.decode()
