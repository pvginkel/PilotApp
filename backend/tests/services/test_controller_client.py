"""The controller's client against the fake over real HTTP and SSE (design 2 §12, §14)."""

import json
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from flask import Flask
from werkzeug.serving import make_server

from app.core_exceptions import ExternalServiceException
from app.services import controller_client as controller_client_module
from app.services.container import ServiceContainer
from app.services.controller_client import (
    ControllerClient,
    ControllerProblem,
    ControllerProblemType,
    GoneFrame,
    HeadlessCreateRequest,
    IncompleteFrame,
    RawFrame,
    ResultFrame,
    SessionsFrame,
    StateFrame,
)
from app.services.fake_controller import FinishOutcome
from app.services.health_service import CheckStatus, HealthService
from tests.support.fake_controller import (
    FAKE_CONTROLLER_TOKEN,
    ServedFakeController,
    raw_turn,
)
from tests.support.tls import InventedCa, invent_ca

ENV = "example-env-1"


@pytest.fixture
def health_service(container: ServiceContainer) -> HealthService:
    return HealthService(
        lifecycle_coordinator=container.lifecycle_coordinator(),
        settings=container.config(),
    )


@pytest.fixture
def running(fake_controller: ServedFakeController) -> ServedFakeController:
    """``fake_controller`` with ``ENV`` running."""
    fake_controller.add_environment(ENV, name="Example", status="running")
    return fake_controller


@pytest.fixture
def session_name(
    running: ServedFakeController, controller_client: ControllerClient
) -> str:
    """A headless session in ``ENV``, idle."""
    return controller_client.create_headless_session(ENV, HeadlessCreateRequest()).name


@contextmanager
def _scripted(
    status: str, headers: list[tuple[str, str]], body: Iterable[bytes]
) -> Iterator[str]:
    """A server answering every request with one canned response; its base URL."""

    def application(
        environ: Any, start_response: Callable[..., Any]
    ) -> Iterable[bytes]:
        start_response(status, headers)
        return body

    server = make_server("127.0.0.1", 0, application, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _problem(
    status: int, problem_type: str
) -> tuple[str, list[tuple[str, str]], list[bytes]]:
    body = json.dumps(
        {"type": problem_type, "title": "a scripted problem", "status": status}
    )
    return (
        f"{status} Scripted",
        [("Content-Type", "application/problem+json")],
        [body.encode()],
    )


def _offsets(lines: list[str]) -> list[int]:
    offsets, size = [], 0
    for line in lines:
        size += len(line.encode()) + 1
        offsets.append(size)
    return offsets


class TestControllerClient:
    # -- Environments -----------------------------------------------------

    def test_list_environments_is_empty_on_an_empty_fleet(
        self, controller_client: ControllerClient
    ) -> None:
        listing = controller_client.list_environments()

        assert listing.items == []
        assert listing.unprojectable == []

    def test_list_environments_reads_what_pilot_keeps(
        self, fake_controller: ServedFakeController, controller_client: ControllerClient
    ) -> None:
        fake_controller.add_environment(
            "env-a", name="A", status="running", exempt=True
        )
        fake_controller.add_environment("env-b", repo="example/Other")
        fake_controller.restart("env-a")
        fake_controller.set_status("env-a", "running")

        a, b = controller_client.list_environments().items

        assert (a.env_id, a.name, a.status, a.exempt) == ("env-a", "A", "running", True)
        assert a.pod is not None and a.pod.restart_count == 1
        assert a.pod.restart_reason == "Error"
        assert a.pod.started_at == fake_controller.environment("env-a").pod_started_at
        assert a.pod.started_at is not None and a.pod.started_at.tzinfo is not None
        assert (b.env_id, b.name, b.repo, b.status) == (
            "env-b",
            None,
            "example/Other",
            "stopped",
        )
        assert b.exempt is False
        assert b.pod is None

    def test_a_wrong_credential_is_a_failure_no_caller_switches_on(
        self, fake_controller: ServedFakeController, health_service: HealthService
    ) -> None:
        client = ControllerClient(fake_controller.url, "not-the-token", health_service)

        with pytest.raises(ExternalServiceException) as caught:
            client.list_environments()

        assert not isinstance(caught.value, ControllerProblem)
        assert caught.value.cause.startswith(
            "the controller answered 401 unauthenticated"
        )

    def test_the_credential_is_sent_as_a_bearer(
        self, fake_controller: ServedFakeController, controller_client: ControllerClient
    ) -> None:
        controller_client.list_environments()

        assert fake_controller.calls == ["GET /environments"]

    def test_get_environment(
        self, running: ServedFakeController, controller_client: ControllerClient
    ) -> None:
        environment = controller_client.get_environment(ENV)

        assert (environment.env_id, environment.status) == (ENV, "running")
        assert environment.setup_running is False

    def test_get_environment_of_an_unknown_one_is_not_found(
        self, controller_client: ControllerClient
    ) -> None:
        with pytest.raises(ControllerProblem) as caught:
            controller_client.get_environment("no-such-env")

        assert caught.value.problem_type is ControllerProblemType.NOT_FOUND
        assert caught.value.operation == "read environment no-such-env"
        assert caught.value.cause == (
            "the controller answered 404 not-found: no environment no-such-env"
        )

    def test_get_environment_waits_until_it_is_there(
        self, fake_controller: ServedFakeController, controller_client: ControllerClient
    ) -> None:
        fake_controller.add_environment(ENV, status="starting")
        threading.Timer(0.2, fake_controller.set_status, (ENV, "running")).start()

        environment = controller_client.get_environment(
            ENV, wait="settled", wait_ms=10_000
        )

        assert environment.status == "running"
        assert fake_controller.calls == [
            f"GET /environments/{ENV}?wait=settled&waitMs=10000"
        ]

    def test_get_environment_wait_ends_early_on_an_error(
        self, fake_controller: ServedFakeController, controller_client: ControllerClient
    ) -> None:
        fake_controller.add_environment(ENV, status="starting")
        threading.Timer(0.2, fake_controller.set_status, (ENV, "error")).start()

        started = time.perf_counter()
        environment = controller_client.get_environment(
            ENV, wait="ready", wait_ms=10_000
        )

        assert environment.status == "error"
        assert time.perf_counter() - started < 5

    def test_get_environment_answers_the_snapshot_when_the_wait_runs_out(
        self, fake_controller: ServedFakeController, controller_client: ControllerClient
    ) -> None:
        fake_controller.add_environment(ENV, status="starting")

        environment = controller_client.get_environment(ENV, wait="ready", wait_ms=100)

        assert environment.status == "starting"

    def test_start_environment_of_a_stopped_one_is_started(
        self, fake_controller: ServedFakeController, controller_client: ControllerClient
    ) -> None:
        fake_controller.add_environment(ENV)

        outcome = controller_client.start_environment(ENV)

        assert outcome.started is True
        assert outcome.environment.status == "starting"
        assert controller_client.get_environment(ENV).status == "running"

    def test_start_environment_of_a_running_one_was_not_started_by_the_call(
        self, running: ServedFakeController, controller_client: ControllerClient
    ) -> None:
        outcome = controller_client.start_environment(ENV)

        assert outcome.started is False
        assert outcome.environment.status == "running"

    def test_start_environment_on_a_capped_node_is_admission_blocked(
        self, fake_controller: ServedFakeController, controller_client: ControllerClient
    ) -> None:
        fake_controller.add_environment(ENV)
        fake_controller.capped(ENV)

        with pytest.raises(ControllerProblem) as caught:
            controller_client.start_environment(ENV)

        assert caught.value.problem_type is ControllerProblemType.ADMISSION_BLOCKED
        assert fake_controller.environment(ENV).status == "stopped"

    def test_start_environment_of_an_exempt_one_is_never_capped(
        self, fake_controller: ServedFakeController, controller_client: ControllerClient
    ) -> None:
        fake_controller.add_environment(ENV, exempt=True)
        fake_controller.capped(ENV)

        assert controller_client.start_environment(ENV).started is True

    def test_start_environment_of_a_deleting_one_is_a_conflict(
        self, fake_controller: ServedFakeController, controller_client: ControllerClient
    ) -> None:
        fake_controller.add_environment(ENV, status="deleting")

        with pytest.raises(ControllerProblem) as caught:
            controller_client.start_environment(ENV)

        assert caught.value.problem_type is ControllerProblemType.CONFLICT

    def test_start_environment_of_an_unknown_one_is_not_found(
        self, controller_client: ControllerClient
    ) -> None:
        with pytest.raises(ControllerProblem) as caught:
            controller_client.start_environment("no-such-env")

        assert caught.value.problem_type is ControllerProblemType.NOT_FOUND

    def test_stop_environment(
        self, running: ServedFakeController, controller_client: ControllerClient
    ) -> None:
        assert controller_client.stop_environment(ENV).status == "stopping"
        assert controller_client.get_environment(ENV).status == "stopped"
        assert controller_client.stop_environment(ENV).status == "stopped"

    def test_stop_environment_of_a_deleting_one_is_a_conflict(
        self, fake_controller: ServedFakeController, controller_client: ControllerClient
    ) -> None:
        fake_controller.add_environment(ENV, status="deleting")

        with pytest.raises(ControllerProblem) as caught:
            controller_client.stop_environment(ENV)

        assert caught.value.problem_type is ControllerProblemType.CONFLICT

    def test_stop_environment_of_an_unknown_one_is_not_found(
        self, controller_client: ControllerClient
    ) -> None:
        with pytest.raises(ControllerProblem) as caught:
            controller_client.stop_environment("no-such-env")

        assert caught.value.problem_type is ControllerProblemType.NOT_FOUND

    # -- Headless sessions --------------------------------------------------

    def test_create_headless_session(
        self, running: ServedFakeController, controller_client: ControllerClient
    ) -> None:
        snapshot = controller_client.create_headless_session(
            ENV, HeadlessCreateRequest()
        )

        assert (snapshot.name, snapshot.mode, snapshot.status) == (
            "claude-1",
            "headless",
            "idle",
        )
        assert snapshot.session_id == ""
        assert snapshot.turn == 0

    def test_create_headless_session_resumes_a_conversation(
        self, running: ServedFakeController, controller_client: ControllerClient
    ) -> None:
        snapshot = controller_client.create_headless_session(
            ENV, HeadlessCreateRequest(cwd="Example/docs", resume="conversation-1")
        )

        assert snapshot.session_id == "conversation-1"
        assert running.session(ENV, snapshot.name).cwd == "/work/Example/docs"

    def test_create_headless_session_sends_every_field_under_its_wire_name(
        self, running: ServedFakeController, controller_client: ControllerClient
    ) -> None:
        request = HeadlessCreateRequest(
            cwd="Example",
            resume="conversation-1",
            agent="claude",
            model="example-model",
            reasoning_effort="high",
            env=["TZ=UTC"],
            mcp_config=[".mcp.json"],
            strict_mcp_config=True,
            disable_slash_commands=True,
            enable_cross_session_messaging=False,
        )

        # The fake refuses a field the controller does not know.
        assert (
            controller_client.create_headless_session(ENV, request).name == "claude-1"
        )

    @pytest.mark.parametrize(
        ("arrange", "problem_type"),
        [
            (lambda fake: fake.add_environment(ENV, status="starting"), "conflict"),
            (
                lambda fake: (
                    fake.add_environment(ENV, status="running"),
                    fake.unreachable(ENV),
                ),
                "worker-unreachable",
            ),
            (lambda fake: None, "not-found"),
        ],
    )
    def test_create_headless_session_behind_the_gate(
        self,
        fake_controller: ServedFakeController,
        controller_client: ControllerClient,
        arrange: Callable[[ServedFakeController], Any],
        problem_type: str,
    ) -> None:
        arrange(fake_controller)

        with pytest.raises(ControllerProblem) as caught:
            controller_client.create_headless_session(ENV, HeadlessCreateRequest())

        assert caught.value.problem_type == problem_type

    def test_send_message_makes_the_session_busy(
        self,
        running: ServedFakeController,
        controller_client: ControllerClient,
        session_name: str,
    ) -> None:
        controller_client.send_message(ENV, session_name, "Check the badge.")

        snapshot = controller_client.get_session(ENV, session_name)
        assert snapshot.status == "busy"
        assert snapshot.session_id

    def test_send_message_during_a_turn_is_session_busy(
        self,
        running: ServedFakeController,
        controller_client: ControllerClient,
        session_name: str,
    ) -> None:
        running.busy(ENV, session_name)

        with pytest.raises(ControllerProblem) as caught:
            controller_client.send_message(ENV, session_name, "Check the badge.")

        assert caught.value.problem_type is ControllerProblemType.SESSION_BUSY
        assert caught.value.cause.startswith("the controller answered 409 session-busy")

    def test_send_message_to_an_unknown_session_is_not_found(
        self, running: ServedFakeController, controller_client: ControllerClient
    ) -> None:
        with pytest.raises(ControllerProblem) as caught:
            controller_client.send_message(ENV, "claude-9", "Check the badge.")

        assert caught.value.problem_type is ControllerProblemType.NOT_FOUND

    def test_send_message_to_an_environment_that_restarted_is_a_conflict(
        self,
        running: ServedFakeController,
        controller_client: ControllerClient,
        session_name: str,
    ) -> None:
        running.restart(ENV)

        with pytest.raises(ControllerProblem) as caught:
            controller_client.send_message(ENV, session_name, "Check the badge.")

        assert caught.value.problem_type is ControllerProblemType.CONFLICT

    def test_interrupt_ends_the_turn_in_flight_as_interrupted(
        self,
        running: ServedFakeController,
        controller_client: ControllerClient,
        session_name: str,
    ) -> None:
        controller_client.send_message(ENV, session_name, "Check the badge.")

        controller_client.interrupt(ENV, session_name)

        assert controller_client.get_session(ENV, session_name).status == "idle"
        assert running.session(ENV, session_name).result == {
            "turn": 1,
            "result": "",
            "isError": False,
            "interrupted": True,
        }

    def test_interrupt_of_an_idle_session_does_nothing(
        self,
        running: ServedFakeController,
        controller_client: ControllerClient,
        session_name: str,
    ) -> None:
        controller_client.interrupt(ENV, session_name)

        assert controller_client.get_session(ENV, session_name).turn == 0

    def test_interrupt_of_an_unknown_session_is_not_found(
        self, running: ServedFakeController, controller_client: ControllerClient
    ) -> None:
        with pytest.raises(ControllerProblem) as caught:
            controller_client.interrupt(ENV, "claude-9")

        assert caught.value.problem_type is ControllerProblemType.NOT_FOUND

    def test_end_session_is_idempotent(
        self,
        running: ServedFakeController,
        controller_client: ControllerClient,
        session_name: str,
    ) -> None:
        controller_client.end_session(ENV, session_name)
        controller_client.end_session(ENV, session_name)

        assert controller_client.list_sessions(ENV) == []

    def test_end_session_in_an_environment_not_running_is_a_conflict(
        self,
        running: ServedFakeController,
        controller_client: ControllerClient,
        session_name: str,
    ) -> None:
        running.set_status(ENV, "stopped")

        with pytest.raises(ControllerProblem) as caught:
            controller_client.end_session(ENV, session_name)

        assert caught.value.problem_type is ControllerProblemType.CONFLICT

    def test_get_session_of_an_unknown_one_is_not_found(
        self, running: ServedFakeController, controller_client: ControllerClient
    ) -> None:
        with pytest.raises(ControllerProblem) as caught:
            controller_client.get_session(ENV, "claude-9")

        assert caught.value.problem_type is ControllerProblemType.NOT_FOUND

    def test_list_sessions(
        self,
        running: ServedFakeController,
        controller_client: ControllerClient,
        session_name: str,
    ) -> None:
        assert controller_client.list_sessions(ENV)[0].working is False

        controller_client.send_message(ENV, session_name, "Check the badge.")

        (view,) = controller_client.list_sessions(ENV)
        assert (view.name, view.mode, view.state, view.working) == (
            session_name,
            "headless",
            "running",
            True,
        )
        assert view.title

    def test_list_sessions_of_an_unreachable_worker(
        self, running: ServedFakeController, controller_client: ControllerClient
    ) -> None:
        running.unreachable(ENV)

        with pytest.raises(ControllerProblem) as caught:
            controller_client.list_sessions(ENV)

        assert caught.value.problem_type is ControllerProblemType.WORKER_UNREACHABLE
        assert caught.value.cause.startswith(
            "the controller answered 502 worker-unreachable"
        )

    def test_read_log(
        self,
        running: ServedFakeController,
        controller_client: ControllerClient,
        session_name: str,
    ) -> None:
        running.write_log(
            ENV, session_name, ["[init]", "[text] hello", "[result] done"]
        )

        assert controller_client.read_log(ENV, session_name) == [
            "[init]",
            "[text] hello",
            "[result] done",
        ]
        assert controller_client.read_log(ENV, session_name, head=1) == ["[init]"]
        assert controller_client.read_log(ENV, session_name, tail=2) == [
            "[text] hello",
            "[result] done",
        ]

    def test_read_log_of_an_unknown_session_is_not_found(
        self, running: ServedFakeController, controller_client: ControllerClient
    ) -> None:
        with pytest.raises(ControllerProblem) as caught:
            controller_client.read_log(ENV, "claude-9")

        assert caught.value.problem_type is ControllerProblemType.NOT_FOUND

    # -- The response stream ------------------------------------------------

    @pytest.mark.parametrize("turn", ["turn_text", "turn_tool", "turn_subagent"])
    def test_a_turn_comes_back_line_for_line_then_its_result(
        self,
        running: ServedFakeController,
        controller_client: ControllerClient,
        session_name: str,
        turn: str,
    ) -> None:
        lines = raw_turn(turn)
        controller_client.send_message(ENV, session_name, "Check the badge.")
        running.play(ENV, session_name, lines)
        running.finish(ENV, session_name, result="The badge reads green.")

        with controller_client.open_response_stream(ENV, session_name, 0) as stream:
            frames = list(stream)

        assert frames[:-1] == [
            RawFrame(offset, line)
            for offset, line in zip(_offsets(lines), lines, strict=True)
        ]
        assert frames[-1] == ResultFrame(
            turn=1,
            result="The badge reads green.",
            is_error=False,
            interrupted=False,
            payload={
                "turn": 1,
                "result": "The badge reads green.",
                "isError": False,
                "interrupted": False,
            },
        )
        assert running.calls[-1] == (
            f"GET /environments/{ENV}/sessions/headless/{session_name}/response"
            "?format=raw&offset=0"
        )

    def test_frames_come_as_the_lines_are_printed(
        self,
        running: ServedFakeController,
        controller_client: ControllerClient,
        session_name: str,
    ) -> None:
        first, second = raw_turn("turn_text")[:2]
        controller_client.send_message(ENV, session_name, "Check the badge.")
        running.play(ENV, session_name, [first])

        with controller_client.open_response_stream(ENV, session_name, 0) as stream:
            frames = iter(stream)
            assert next(frames).line == first
            # Keepalives pass while the stream is open and quiet.
            time.sleep(0.5)
            running.play(ENV, session_name, [second])
            assert next(frames).line == second
            running.finish(ENV, session_name)
            assert isinstance(next(frames), ResultFrame)

    def test_a_stream_resumes_after_the_offset_it_is_opened_at(
        self,
        running: ServedFakeController,
        controller_client: ControllerClient,
        session_name: str,
    ) -> None:
        lines = raw_turn("turn_text")
        controller_client.send_message(ENV, session_name, "Check the badge.")
        offsets = running.play(ENV, session_name, lines)
        running.finish(ENV, session_name)

        with controller_client.open_response_stream(
            ENV, session_name, offsets[4]
        ) as stream:
            frames = list(stream)

        assert [f.line for f in frames if isinstance(f, RawFrame)] == lines[5:]
        assert isinstance(frames[-1], ResultFrame)

    def test_the_result_stays_until_the_next_send(
        self,
        running: ServedFakeController,
        controller_client: ControllerClient,
        session_name: str,
    ) -> None:
        controller_client.send_message(ENV, session_name, "Check the badge.")
        offsets = running.play(ENV, session_name, raw_turn("turn_text"))
        running.finish(ENV, session_name)

        with controller_client.open_response_stream(
            ENV, session_name, offsets[-1]
        ) as stream:
            assert [type(f) for f in stream] == [ResultFrame]

        controller_client.send_message(ENV, session_name, "And the layout?")
        with controller_client.open_response_stream(
            ENV, session_name, offsets[-1]
        ) as stream:
            frames = iter(stream)
            running.play(ENV, session_name, ["second turn"])
            assert next(frames) == RawFrame(
                offsets[-1] + len("second turn") + 1, "second turn"
            )
            running.finish(ENV, session_name)
            result = next(frames)
        assert isinstance(result, ResultFrame) and result.turn == 2

    @pytest.mark.parametrize(
        ("outcome", "is_error", "interrupted", "status"),
        [
            ("success", False, False, "idle"),
            ("error", True, False, "idle"),
            ("interrupted", False, True, "idle"),
            ("spawn-failure", True, False, "error"),
            ("ended", True, False, "ended"),
        ],
    )
    def test_each_outcome_reaches_the_result_frame(
        self,
        running: ServedFakeController,
        controller_client: ControllerClient,
        session_name: str,
        outcome: FinishOutcome,
        is_error: bool,
        interrupted: bool,
        status: str,
    ) -> None:
        controller_client.send_message(ENV, session_name, "Check the badge.")
        running.finish(ENV, session_name, outcome=outcome, result="text")

        with controller_client.open_response_stream(ENV, session_name, 0) as stream:
            (frame,) = list(stream)

        assert isinstance(frame, ResultFrame)
        assert (frame.is_error, frame.interrupted, frame.result) == (
            is_error,
            interrupted,
            "text",
        )
        assert controller_client.get_session(ENV, session_name).status == status

    def test_lines_pass_verbatim_and_offsets_count_bytes(
        self,
        running: ServedFakeController,
        controller_client: ControllerClient,
        session_name: str,
    ) -> None:
        lines = ["", "not json at all", '{"type":"assistant","text":"grün ✓"}', "a\rb"]
        controller_client.send_message(ENV, session_name, "Check the badge.")
        running.play(ENV, session_name, lines)
        running.finish(ENV, session_name)

        with controller_client.open_response_stream(ENV, session_name, 0) as stream:
            frames = list(stream)[:-1]

        assert frames == [
            RawFrame(o, line) for o, line in zip(_offsets(lines), lines, strict=True)
        ]
        assert (
            frames[2].offset
            == 1 + 16 + len('{"type":"assistant","text":"grün ✓"}'.encode()) + 1
        )

    def test_a_bounded_stream_ends_incomplete(
        self,
        running: ServedFakeController,
        controller_client: ControllerClient,
        session_name: str,
    ) -> None:
        controller_client.send_message(ENV, session_name, "Check the badge.")

        with controller_client.open_response_stream(
            ENV, session_name, 0, wait_ms=300
        ) as stream:
            frames = list(stream)

        assert frames == [IncompleteFrame("busy")]

    @pytest.mark.parametrize(
        ("arrange", "problem_type"),
        [
            (lambda fake, name: fake.set_status(ENV, "stopping"), "conflict"),
            (lambda fake, name: fake.unreachable(ENV), "worker-unreachable"),
            (lambda fake, name: fake.restart(ENV), "conflict"),
        ],
    )
    def test_open_response_stream_behind_the_gate(
        self,
        running: ServedFakeController,
        controller_client: ControllerClient,
        session_name: str,
        arrange: Callable[[ServedFakeController, str], Any],
        problem_type: str,
    ) -> None:
        arrange(running, session_name)

        with pytest.raises(ControllerProblem) as caught:
            controller_client.open_response_stream(ENV, session_name, 0)

        assert caught.value.problem_type == problem_type

    def test_open_response_stream_of_a_reaped_session_is_not_found(
        self,
        running: ServedFakeController,
        controller_client: ControllerClient,
        session_name: str,
    ) -> None:
        running.restart(ENV)
        running.set_status(ENV, "running")

        with pytest.raises(ControllerProblem) as caught:
            controller_client.open_response_stream(ENV, session_name, 0)

        assert caught.value.problem_type is ControllerProblemType.NOT_FOUND

    @pytest.mark.parametrize(
        "cut",
        [
            lambda fake: fake.drop_streams(),
            lambda fake: fake.restart(ENV),
        ],
    )
    def test_a_stream_cut_before_the_result_raises(
        self,
        running: ServedFakeController,
        controller_client: ControllerClient,
        session_name: str,
        cut: Callable[[ServedFakeController], None],
    ) -> None:
        controller_client.send_message(ENV, session_name, "Check the badge.")
        running.play(ENV, session_name, ["one line"])

        with controller_client.open_response_stream(ENV, session_name, 0) as stream:
            frames = iter(stream)
            assert next(frames).line == "one line"
            cut(running)
            with pytest.raises(ExternalServiceException) as caught:
                next(frames)

        assert caught.value.cause == "the stream ended before the turn's result"

    def test_a_silent_stream_drops_at_the_read_timeout(
        self,
        container: ServiceContainer,
        health_service: HealthService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = ServedFakeController(keepalive_seconds=30)
        try:
            fake.add_environment(ENV, status="running")
            client = ControllerClient(fake.url, FAKE_CONTROLLER_TOKEN, health_service)
            name = client.create_headless_session(ENV, HeadlessCreateRequest()).name
            client.send_message(ENV, name, "Check the badge.")
            monkeypatch.setattr(
                controller_client_module, "STREAM_READ_TIMEOUT_SECONDS", 0.3
            )

            with client.open_response_stream(ENV, name, 0) as stream:
                with pytest.raises(ExternalServiceException) as caught:
                    list(stream)

            assert caught.value.cause.startswith("the stream dropped:")
        finally:
            fake.close()

    def test_close_wakes_a_blocked_read_and_ends_the_stream_quietly(
        self, container: ServiceContainer, health_service: HealthService
    ) -> None:
        fake = ServedFakeController(keepalive_seconds=30)
        try:
            fake.add_environment(ENV, status="running")
            client = ControllerClient(fake.url, FAKE_CONTROLLER_TOKEN, health_service)
            name = client.create_headless_session(ENV, HeadlessCreateRequest()).name
            client.send_message(ENV, name, "Check the badge.")
            fake.play(ENV, name, ["one line"])
            stream = client.open_response_stream(ENV, name, 0)
            first = threading.Event()
            outcome: list[object] = []

            def read() -> None:
                try:
                    for frame in stream:
                        outcome.append(frame)
                        first.set()
                    outcome.append("ended")
                except Exception as error:
                    outcome.append(error)

            reader = threading.Thread(target=read)
            reader.start()
            assert first.wait(5)

            stream.close()
            reader.join(5)

            assert not reader.is_alive()
            assert outcome == [RawFrame(9, "one line"), "ended"]
        finally:
            fake.close()

    # -- The fleet stream ---------------------------------------------------

    def test_the_fleet_stream_seeds_each_environments_sessions(
        self,
        running: ServedFakeController,
        controller_client: ControllerClient,
        session_name: str,
    ) -> None:
        running.add_environment("env-2")

        with controller_client.open_fleet_stream() as stream:
            frames = iter(stream)
            seeded = [next(frames), next(frames)]

        assert [(f.env_id, [s.name for s in f.sessions]) for f in seeded] == [  # type: ignore[union-attr]
            (ENV, [session_name]),
            ("env-2", []),
        ]

    def test_the_fleet_stream_carries_state_sessions_and_gone(
        self, fake_controller: ServedFakeController, controller_client: ControllerClient
    ) -> None:
        with controller_client.open_fleet_stream() as stream:
            frames = iter(stream)
            fake_controller.add_environment(ENV, exempt=True)
            added = next(frames)
            controller_client.start_environment(ENV)
            starting, running = next(frames), next(frames)
            controller_client.create_headless_session(ENV, HeadlessCreateRequest())
            sessions = next(frames)
            fake_controller.remove_environment(ENV)
            swept, gone = next(frames), next(frames)

        assert isinstance(added, StateFrame) and added.environment.exempt is True
        assert [starting.environment.status, running.environment.status] == [  # type: ignore[union-attr]
            "starting",
            "running",
        ]
        assert isinstance(sessions, SessionsFrame)
        assert [s.name for s in sessions.sessions] == ["claude-1"]
        assert swept == SessionsFrame(ENV, ())
        assert gone == GoneFrame(ENV)

    def test_the_fleet_stream_skips_the_channels_pilot_does_not_read(
        self, health_service: HealthService
    ) -> None:
        environment = {
            "envId": ENV,
            "repo": "example/Example",
            "status": "stopped",
            "setupRunning": False,
            "capabilities": {"capacityExempt": {"enabled": False}},
        }
        body = [
            b": keepalive\n\n",
            b'event: notification\nid: 7\ndata: {"envId":"x","message":"hi"}\n\n',
            b'event: enrollment\ndata: {"requestId":"secret"}\n\n',
            b'event: timer-gone\ndata: {"timerId":"t"}\n\n',
            b"event: state\ndata: " + json.dumps(environment).encode() + b"\n\n",
        ]
        with _scripted("200 OK", [("Content-Type", "text/event-stream")], body) as url:
            client = ControllerClient(url, "t", health_service)
            with client.open_fleet_stream() as stream:
                frames = iter(stream)
                frame = next(frames)
                with pytest.raises(ExternalServiceException) as caught:
                    next(frames)

        assert isinstance(frame, StateFrame) and frame.environment.env_id == ENV
        assert caught.value.cause == "the controller ended the stream"

    def test_close_ends_the_fleet_stream_quietly(
        self, fake_controller: ServedFakeController, controller_client: ControllerClient
    ) -> None:
        stream = controller_client.open_fleet_stream()
        threading.Timer(0.3, stream.close).start()

        assert list(stream) == []

    # -- What the controller answers that no fake does ------------------------

    def test_a_problem_no_caller_switches_on_is_a_failing_upstream(
        self, health_service: HealthService
    ) -> None:
        with _scripted(*_problem(500, "internal")) as url:
            client = ControllerClient(url, "t", health_service)
            with pytest.raises(ExternalServiceException) as caught:
                client.list_environments()

        assert not isinstance(caught.value, ControllerProblem)
        assert (
            caught.value.cause
            == "the controller answered 500 internal: a scripted problem"
        )

    def test_a_problem_type_under_another_status_is_not_switched_on(
        self, health_service: HealthService
    ) -> None:
        with _scripted(*_problem(500, "not-found")) as url:
            client = ControllerClient(url, "t", health_service)
            with pytest.raises(ExternalServiceException) as caught:
                client.get_environment(ENV)

        assert not isinstance(caught.value, ControllerProblem)

    def test_a_routers_404_is_not_an_unknown_environment(
        self, health_service: HealthService
    ) -> None:
        body = [b'{"detail":"Not Found"}']
        with _scripted(
            "404 Not Found", [("Content-Type", "application/json")], body
        ) as url:
            client = ControllerClient(url, "t", health_service)
            with pytest.raises(ExternalServiceException) as caught:
                client.get_environment(ENV)

        assert not isinstance(caught.value, ControllerProblem)
        assert caught.value.cause == "the controller answered 404: Not Found"

    def test_an_unexpected_success_status_is_a_failing_upstream(
        self, health_service: HealthService
    ) -> None:
        with _scripted(
            "200 OK", [("Content-Type", "application/json")], [b"{}"]
        ) as url:
            client = ControllerClient(url, "t", health_service)
            with pytest.raises(ExternalServiceException) as caught:
                client.send_message(ENV, "claude-1", "Check the badge.")

        assert caught.value.cause.startswith("the controller answered 200")

    def test_an_answer_that_does_not_parse_is_a_failing_upstream(
        self, health_service: HealthService
    ) -> None:
        body = [b'{"items": [{"envId": "x"}], "unprojectable": []}']
        with _scripted("200 OK", [("Content-Type", "application/json")], body) as url:
            client = ControllerClient(url, "t", health_service)
            with pytest.raises(ExternalServiceException) as caught:
                client.list_environments()

        assert caught.value.cause.startswith("the controller's answer does not parse")

    def test_a_controller_that_does_not_answer_is_a_failing_upstream(
        self, health_service: HealthService
    ) -> None:
        client = ControllerClient("http://127.0.0.1:9", "t", health_service)

        with pytest.raises(ExternalServiceException) as caught:
            client.list_environments()

        assert caught.value.cause.startswith("the controller did not answer")

    @pytest.mark.parametrize(
        ("body", "cause"),
        [
            (b"event: raw\ndata: a line\n\n", "a raw frame came without its id"),
            (
                b'event: message\ndata: {"text":"hi"}\n\n',
                "the stream sent a 'message' frame, not one of format=raw's",
            ),
        ],
    )
    def test_a_response_frame_outside_the_contract_raises(
        self, health_service: HealthService, body: bytes, cause: str
    ) -> None:
        with _scripted(
            "200 OK", [("Content-Type", "text/event-stream")], [body]
        ) as url:
            client = ControllerClient(url, "t", health_service)
            with client.open_response_stream(ENV, "claude-1", 0) as stream:
                with pytest.raises(ExternalServiceException) as caught:
                    list(stream)

        assert caught.value.cause == cause

    def test_frames_split_across_reads_and_joined_in_one_parse_alike(
        self, health_service: HealthService
    ) -> None:
        body = [
            b"event: ra",
            b"w\nid: 4\ndata: abc\n",
            b"\nevent: raw\nid: 9\ndata: defg\n\nevent: result\ndata: ",
            b'{"turn":1}\n\n',
        ]
        with _scripted("200 OK", [("Content-Type", "text/event-stream")], body) as url:
            client = ControllerClient(url, "t", health_service)
            with client.open_response_stream(ENV, "claude-1", 0) as stream:
                frames = list(stream)

        assert frames == [
            RawFrame(4, "abc"),
            RawFrame(9, "defg"),
            ResultFrame(1, None, False, False, {"turn": 1}),
        ]

    # -- Readiness ----------------------------------------------------------

    def test_its_readiness_check_reports_the_controller(
        self,
        app: Flask,
        fake_controller: ServedFakeController,
        health_service: HealthService,
    ) -> None:
        ControllerClient(fake_controller.url, FAKE_CONTROLLER_TOKEN, health_service)

        with app.app_context():
            body, status = health_service.check_readyz()

        assert status == 200
        assert body["checks"]["controller"]["status"] == "ok"

    def test_a_controller_down_degrades_readiness_without_failing_it(
        self, app: Flask, health_service: HealthService
    ) -> None:
        ControllerClient("http://127.0.0.1:9", "t", health_service)

        with app.app_context():
            body, status = health_service.check_readyz()

        assert status == 200
        assert body["status"] == "degraded"
        assert body["checks"]["controller"]["status"] == "error"

    def test_check_readiness_reads_the_controllers_own_readyz(
        self, health_service: HealthService
    ) -> None:
        body = [b'{"status":"not-ready","checks":{}}']
        with _scripted(
            "503 Unavailable", [("Content-Type", "application/json")], body
        ) as url:
            result = ControllerClient(url, "t", health_service).check_readiness()

        assert result.status is CheckStatus.ERROR
        assert result.detail == "the controller answered 503"


class TestControllerTls:
    """The controller's certificate is verified against `ca_file`: the homelab's
    authority signs `kubecoder.home`'s, and no public root does."""

    @pytest.fixture
    def authority(self, tmp_path: Path) -> InventedCa:
        return invent_ca(tmp_path)

    @pytest.fixture
    def tls_controller(self, authority: InventedCa) -> Iterator[ServedFakeController]:
        fake = ServedFakeController(keepalive_seconds=0.2, tls=authority)
        try:
            yield fake
        finally:
            fake.close()

    def test_a_controller_its_ca_file_vouches_for_is_reached(
        self,
        app: Flask,
        authority: InventedCa,
        tls_controller: ServedFakeController,
        health_service: HealthService,
    ) -> None:
        tls_controller.add_environment(ENV, name="Example", status="running")
        client = ControllerClient(
            tls_controller.url,
            FAKE_CONTROLLER_TOKEN,
            health_service,
            ca_file=authority.ca_file,
        )

        environments = client.list_environments().items
        with client.open_fleet_stream() as stream:
            seed = next(iter(stream))
        with app.app_context():
            body, _ = health_service.check_readyz()

        assert [environment.env_id for environment in environments] == [ENV]
        assert seed == SessionsFrame(env_id=ENV, sessions=())
        assert body["checks"]["controller"]["status"] == "ok"

    @pytest.mark.parametrize(
        "ca_file", ["none", "another-authority"], ids=["default-trust", "another-ca"]
    )
    def test_a_certificate_its_ca_file_does_not_vouch_for_is_refused(
        self,
        tmp_path: Path,
        tls_controller: ServedFakeController,
        health_service: HealthService,
        ca_file: str,
    ) -> None:
        other = None
        if ca_file == "another-authority":
            directory = tmp_path / "other"
            directory.mkdir()
            other = invent_ca(directory).ca_file
        client = ControllerClient(
            tls_controller.url, FAKE_CONTROLLER_TOKEN, health_service, ca_file=other
        )

        with pytest.raises(ExternalServiceException) as caught:
            client.list_environments()

        assert "CERTIFICATE_VERIFY_FAILED" in caught.value.cause
