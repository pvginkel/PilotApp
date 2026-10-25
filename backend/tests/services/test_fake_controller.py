"""The fake controller's own surface: its verbs over HTTP, and what the client
never sends it (design 2 §12). Its controller routes are under test through
the real client, in `test_controller_client.py`."""

import json
import socket

import pytest
from pydantic import ValidationError
from werkzeug.test import Client, TestResponse

from app.services.fake_controller import (
    CLIENT_NAME,
    FakeController,
    FakeControllerProblem,
)

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
            "settle-creates",
            "restart",
            "recreate-pod",
            "unreachable",
            "outage",
            "capped",
            "not-whitelisted",
            "unprojectable",
            "unreadable",
            "put-file",
            "file-text",
            "remove-file",
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
        fake.capped()
        fake.not_whitelisted("example")
        fake.settle_creates(None)

        fake.reset()

        assert fake.calls == []
        listing = http.get("/environments", headers=BEARER).get_json()
        assert listing == {"items": [], "unprojectable": []}
        created = _create(http, {"repo": "example/Example"})
        assert created.status_code == 202
        assert fake.environment(created.get_json()["envId"]).status == "running"

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

    # -- Pilot's own environments: the create, reset, rename and delete --------

    def test_every_environment_carries_its_manager(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1")
        managed = _create(http, {"repo": "example/Example", "managed": True})
        unmanaged = _create(http, {"repo": "example/Example"})

        listing = http.get("/environments", headers=BEARER).get_json()

        managers = {item["envId"]: item["managedBy"] for item in listing["items"]}
        assert managers == {
            "env-1": None,
            managed.get_json()["envId"]: CLIENT_NAME,
            unmanaged.get_json()["envId"]: None,
        }

    def test_the_list_filters_by_manager_repo_and_status(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1")
        fake.add_environment("env-2", repo="example/Other", status="running")
        fake.add_environment("env-3", repo="example/Other")
        fake.unprojectable("env-3")
        managed = _create(http, {"repo": "example/Other", "managed": True})
        env_id = managed.get_json()["envId"]

        def listed(query: str) -> tuple[list[str], list[str]]:
            listing = http.get(f"/environments?{query}", headers=BEARER).get_json()
            return [item["envId"] for item in listing["items"]], listing[
                "unprojectable"
            ]

        assert listed("managedBy=pilot") == ([env_id], ["env-3"])
        assert listed("managedBy=%20Pilot%20") == ([env_id], ["env-3"])
        assert listed("managedBy=other") == ([], ["env-3"])
        assert listed("repo=example/Other") == (["env-2", env_id], ["env-3"])
        assert listed("repo=example/other") == ([], ["env-3"])
        assert listed("status=stopped") == (["env-1"], ["env-3"])
        assert listed("repo=example/Other&status=running&managedBy=pilot") == (
            [env_id],
            ["env-3"],
        )

    def test_the_list_refuses_an_unknown_status(self, http: Client) -> None:
        response = http.get("/environments?status=sleeping", headers=BEARER)

        assert response.status_code == 422

    def test_create_answers_provisioning_with_its_location(
        self, fake: FakeController, http: Client
    ) -> None:
        response = _create(http, {"repo": "example/Example", "name": " Example "})

        body = response.get_json()
        assert response.status_code == 202
        assert response.headers["Location"] == f"/environments/{body['envId']}"
        assert (body["status"], body["name"], body["pod"]) == (
            "provisioning",
            "Example",
            None,
        )
        environment = fake.environment(body["envId"])
        assert (environment.status, environment.resets) == ("running", 0)
        assert environment.pod_started_at is not None

    def test_settle_creates_holds_a_create_and_its_starts(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.settle_creates(None)
        held = _create(http, {"repo": "example/Example"}).get_json()["envId"]
        fake.settle_creates("error")
        failed = _create(http, {"repo": "example/Example"}).get_json()["envId"]
        fake.set_status(held, "stopped")
        http.post(f"/environments/{held}/start", headers=BEARER)

        assert fake.environment(held).status == "starting"
        assert fake.environment(failed).status == "error"

    @pytest.mark.parametrize(
        "body",
        [
            ["example/Example"],
            {},
            {"repo": 1},
            {"repo": "example/Example", "managed": "yes"},
            {"repo": "example/Example", "name": 5},
            {"repo": "example/Example", "profile": "claude-dev"},
        ],
    )
    def test_create_refuses_a_body_of_another_shape(
        self, fake: FakeController, http: Client, body: object
    ) -> None:
        response = _create(http, body)

        assert response.status_code == 422
        assert response.get_json()["type"] == "validation-error"
        assert http.get("/environments", headers=BEARER).get_json()["items"] == []

    def test_create_refuses_in_the_controllers_order(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1", name="Taken")
        fake.not_whitelisted("elsewhere")
        fake.capped()

        def refused(body: dict[str, object]) -> tuple[int, str]:
            answer = _create(http, body).get_json()
            return answer["status"], answer["type"]

        assert refused({"repo": "Elsewhere", "name": "taken"}) == (
            422,
            "validation-error",
        )
        assert refused({"repo": "elsewhere/Example", "name": "x" * 65}) == (
            422,
            "validation-error",
        )
        assert refused({"repo": "Elsewhere/Example", "name": "taken"}) == (
            403,
            "namespace-not-whitelisted",
        )
        assert refused({"repo": "example/Example", "name": "TAKEN"}) == (
            409,
            "name-conflict",
        )
        assert refused({"repo": "example/Example"}) == (409, "admission-blocked")
        assert [item["envId"] for item in _listing(http)] == ["env-1"]

    def test_lifting_a_refusal_lets_the_create_through(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.not_whitelisted("example")
        fake.capped()

        fake.not_whitelisted("example", on=False)
        fake.capped(on=False)

        assert _create(http, {"repo": "example/Example"}).status_code == 202

    def test_a_node_at_its_cap_refuses_every_non_exempt_start(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1")
        fake.add_environment("env-2", exempt=True)
        fake.capped()

        blocked = http.post("/environments/env-1/start", headers=BEARER)
        started = http.post("/environments/env-2/start", headers=BEARER)

        assert (blocked.status_code, blocked.get_json()["type"]) == (
            409,
            "admission-blocked",
        )
        assert started.status_code == 202

    def test_a_reset_ends_in_a_running_pod_through_starting(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1")
        stream = http.get("/stream", headers=BEARER, buffered=False)
        frames = iter(stream.response)
        assert next(frames) == b""
        next(frames)

        response = http.post("/environments/env-1/reset", headers=BEARER)
        published = [next(frames), next(frames)]
        fake.close()
        stream.close()

        assert response.status_code == 202
        assert response.get_json()["status"] == "starting"
        assert [_state(frame)["status"] for frame in published] == [
            "starting",
            "running",
        ]
        assert fake.environment("env-1").resets == 1

    def test_a_held_reset_stays_starting(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1")
        fake.settle_starts("env-1", None)

        http.post("/environments/env-1/reset", headers=BEARER)

        assert fake.environment("env-1").status == "starting"
        assert fake.environment("env-1").resets == 1

    def test_reset_refuses_in_the_controllers_order(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1", status="running")
        fake.capped()

        response = http.post("/environments/env-1/reset", headers=BEARER)

        assert (response.status_code, response.get_json()["type"]) == (
            409,
            "conflict",
        )
        assert fake.environment("env-1").resets == 0

    @pytest.mark.parametrize("body", [{}, {"name": None}, {"name": 5}, ["x"]])
    def test_rename_refuses_a_body_of_another_shape(
        self, fake: FakeController, http: Client, body: object
    ) -> None:
        fake.add_environment("env-1", name="Example")

        response = http.post("/environments/env-1/rename", json=body, headers=BEARER)

        assert response.status_code == 422
        assert fake.environment("env-1").name == "Example"

    def test_rename_refuses_in_the_controllers_order(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1", name="Example", status="deleting")
        fake.add_environment("env-2", name="Taken")

        response = http.post(
            "/environments/env-1/rename", json={"name": "taken"}, headers=BEARER
        )

        assert (response.status_code, response.get_json()["type"]) == (
            409,
            "conflict",
        )
        assert fake.environment("env-1").name == "Example"

    def test_a_rename_is_announced(self, fake: FakeController, http: Client) -> None:
        fake.add_environment("env-1", name="Example")
        stream = http.get("/stream", headers=BEARER, buffered=False)
        frames = iter(stream.response)
        assert next(frames) == b""
        next(frames)

        http.post("/environments/env-1/rename", json={"name": ""}, headers=BEARER)
        published = next(frames)
        fake.close()
        stream.close()

        assert _state(published)["name"] is None

    def test_a_delete_answers_deleting_then_the_environment_is_gone(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1", status="running")
        http.post("/environments/env-1/sessions/headless", headers=BEARER)
        stream = http.get("/stream", headers=BEARER, buffered=False)
        frames = iter(stream.response)
        assert next(frames) == b""
        next(frames)

        response = http.delete("/environments/env-1", headers=BEARER)
        sessions, deleting, gone = next(frames), next(frames), next(frames)
        again = http.delete("/environments/env-1", headers=BEARER)
        listing = _listing(http)
        fake.close()
        stream.close()

        assert response.status_code == 202
        assert response.get_json()["status"] == "deleting"
        assert sessions == b'event: sessions\ndata: {"envId":"env-1","sessions":[]}\n\n'
        assert _state(deleting)["status"] == "deleting"
        assert gone == b'event: gone\ndata: {"envId":"env-1"}\n\n'
        assert (again.status_code, again.get_json()["type"]) == (404, "not-found")
        assert listing == []

    # -- An environment's files ------------------------------------------------

    def test_a_file_is_put_and_read_back_over_http(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1")

        put = http.post(
            "/fake/put-file",
            json={"env_id": "env-1", "path": "/work/a/b.md", "content": "ä\n"},
        )
        text = http.post(
            "/fake/file-text", json={"env_id": "env-1", "path": "/work/a/b.md"}
        )
        none = http.post("/fake/file-text", json={"env_id": "env-1", "path": "/work/c"})

        assert put.status_code == 204
        assert fake.environment("env-1").files == {"/work/a/b.md": "ä\n".encode()}
        assert text.get_json() == "ä\n"
        assert none.get_json() is None

    def test_file_text_of_bytes_that_are_not_utf8_is_refused(
        self, fake: FakeController
    ) -> None:
        fake.add_environment("env-1")
        fake.put_file("env-1", "/work/logo.png", b"\x89PNG\xff")

        with pytest.raises(FakeControllerProblem) as caught:
            fake.file_text("env-1", "/work/logo.png")

        assert caught.value.status == 422

    def test_a_removed_file_is_gone_and_its_empty_folder_with_it(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1")
        fake.put_file("env-1", "/work/a/b.md", b"b")

        fake.remove_file("env-1", "/work/a/b.md")

        assert fake.file_text("env-1", "/work/a/b.md") is None
        listing = http.get("/environments/env-1/files?path=/work/a", headers=BEARER)
        assert listing.status_code == 404
        with pytest.raises(FakeControllerProblem) as caught:
            fake.remove_file("env-1", "/work/a/b.md")
        assert caught.value.status == 404

    @pytest.mark.parametrize(
        ("path", "status", "problem_type"),
        [
            ("/etc/a.md", 403, "path-outside-work"),
            ("/work/../a.md", 403, "path-outside-work"),
            ("a.md", 403, "path-outside-work"),
            ("/work", 409, "not-a-file"),
            ("/work/a", 409, "not-a-file"),
            ("/work/a/b.md/c.md", 409, "not-a-directory"),
        ],
    )
    def test_put_file_keeps_the_tree_one_a_pod_could_hold(
        self, fake: FakeController, path: str, status: int, problem_type: str
    ) -> None:
        fake.add_environment("env-1")
        fake.put_file("env-1", "/work/a/b.md", b"b")

        with pytest.raises(FakeControllerProblem) as caught:
            fake.put_file("env-1", path, b"x")

        assert (caught.value.status, caught.value.problem_type) == (
            status,
            problem_type,
        )
        assert fake.environment("env-1").files == {"/work/a/b.md": b"b"}

    def test_a_path_is_normalised(self, fake: FakeController, http: Client) -> None:
        fake.add_environment("env-1")
        fake.put_file("env-1", "/work/a/./c/../b.md", b"b")

        response = http.get(
            "/environments/env-1/file?path=/work//a/b.md", headers=BEARER
        )

        assert fake.environment("env-1").files == {"/work/a/b.md": b"b"}
        assert response.get_data() == b"b"

    def test_a_listing_names_folders_first_each_in_case_insensitive_order(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1")
        for path in ("/work/b.md", "/work/A.md", "/work/z/x.md", "/work/C/d/e.md"):
            fake.put_file("env-1", path, b"x")

        first = http.get("/environments/env-1/files?limit=3", headers=BEARER)
        rest = http.get("/environments/env-1/files?offset=3&limit=3", headers=BEARER)

        assert first.get_json() == {
            "files": [
                {"path": "/work/C/", "isDirectory": True},
                {"path": "/work/z/", "isDirectory": True},
                {"path": "/work/A.md", "isDirectory": False},
            ],
            "totalCount": 4,
            "limitHit": True,
        }
        assert rest.get_json() == {
            "files": [{"path": "/work/b.md", "isDirectory": False}],
            "totalCount": 4,
            "limitHit": False,
        }

    @pytest.mark.parametrize(
        "query", ["offset=-1", "limit=0", "limit=1001"], ids=["offset", "low", "high"]
    )
    def test_a_listing_refuses_a_page_out_of_range(
        self, fake: FakeController, http: Client, query: str
    ) -> None:
        fake.add_environment("env-1")

        response = http.get(f"/environments/env-1/files?{query}", headers=BEARER)

        assert response.status_code == 422

    @pytest.mark.parametrize("method", ["GET", "PUT"])
    def test_a_file_route_needs_a_path(
        self, fake: FakeController, http: Client, method: str
    ) -> None:
        fake.add_environment("env-1")

        response = http.open("/environments/env-1/file", method=method, headers=BEARER)

        assert response.status_code == 422
        assert fake.environment("env-1").files == {}

    def test_a_write_answers_the_sha256_of_what_it_wrote(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1")

        response = http.put(
            "/environments/env-1/file?path=/work/a.md", data=b"a", headers=BEARER
        )

        assert response.status_code == 204
        assert response.headers["KubeCoder-Content-Sha256"] == (
            "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb"
        )
        assert fake.environment("env-1").files == {"/work/a.md": b"a"}

    def test_a_write_takes_no_expected_hash(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1")

        response = http.put(
            f"/environments/env-1/file?path=/work/a.md&expectedSha256={'0' * 64}",
            data=b"a",
            headers=BEARER,
        )

        assert response.status_code == 422
        assert fake.environment("env-1").files == {}

    def test_a_reset_clears_the_tree_and_a_stop_keeps_it(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1", status="running")
        fake.add_environment("env-2", status="running")
        fake.put_file("env-1", "/work/a.md", b"a")
        fake.put_file("env-2", "/work/a.md", b"a")

        http.post("/environments/env-1/stop", headers=BEARER)
        http.post("/environments/env-2/stop", headers=BEARER)
        http.post("/environments/env-2/reset", headers=BEARER)

        assert fake.environment("env-1").files == {"/work/a.md": b"a"}
        assert fake.environment("env-2").files == {}

    def test_an_unreadable_environment_is_unreadable_to_its_read_too(
        self, fake: FakeController, http: Client
    ) -> None:
        fake.add_environment("env-1")
        fake.unreadable("env-1")

        refused = http.get("/environments/env-1", headers=BEARER)
        fake.unreadable("env-1", on=False)
        read = http.get("/environments/env-1", headers=BEARER)

        assert (refused.status_code, refused.get_json()["type"]) == (
            503,
            "environment-unreadable",
        )
        assert read.status_code == 200


def _create(http: Client, body: object) -> TestResponse:
    return http.post("/environments", json=body, headers=BEARER)


def _listing(http: Client) -> list[dict[str, object]]:
    items: list[dict[str, object]] = http.get(
        "/environments", headers=BEARER
    ).get_json()["items"]
    return items


def _state(frame: bytes) -> dict[str, object]:
    text = frame.decode()
    assert text.startswith("event: state\ndata: ")
    state: dict[str, object] = json.loads(text.removeprefix("event: state\ndata: "))
    return state
