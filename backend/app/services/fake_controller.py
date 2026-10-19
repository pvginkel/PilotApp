"""A fake of the KubeCoder controller, for the suites (design 2 §12, Q6).

A WSGI application the real ControllerClient reaches by URL: served on a thread
under pytest (`tests/support/fake_controller.py`), and mounted for Playwright
under `/api/testing/controller` (`app/api/testing_controller.py`). It holds
environments and headless sessions with the controller's state machines,
answers with the controller's status codes and problem+json, and serves the
response stream and the fleet stream in the controller's SSE framing.

A test drives it through its verbs, the public methods below: in process under
pytest, and over HTTP as `POST /fake/<verb>`, the verb's name hyphenated and its
keyword arguments the JSON body.

Simplifications of the real controller: a headless session's conversation id
is minted by its first send; an environment that is not `running` holds no
headless session; `wait=settled` is `wait=ready`, since no setup runs here.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Any, Literal

from pydantic import ValidationError, validate_call
from werkzeug.exceptions import HTTPException
from werkzeug.routing import Map, Rule
from werkzeug.wrappers import Request, Response

from app.services.controller_client import (
    WAIT_MS_CAP,
    EnvironmentStatus,
    HeadlessStatus,
)

if TYPE_CHECKING:
    from _typeshed.wsgi import StartResponse, WSGIEnvironment

FinishOutcome = Literal["success", "error", "interrupted", "spawn-failure", "ended"]
"""How a turn ends: `claude`'s own result, a failed one, an interrupt, or one of
the failures the worker alone reports — the spawn failing, the session ending."""

# outcome: (isError, interrupted, the session's status after it)
_OUTCOMES: dict[FinishOutcome, tuple[bool, bool, HeadlessStatus]] = {
    "success": (False, False, "idle"),
    "error": (True, False, "idle"),
    "interrupted": (False, True, "idle"),
    "spawn-failure": (True, False, "error"),
    "ended": (True, False, "ended"),
}

_CREATE_FIELDS = {
    "cwd",
    "resume",
    "agent",
    "model",
    "reasoningEffort",
    "env",
    "mcpConfig",
    "strictMcpConfig",
    "disableSlashCommands",
    "enableCrossSessionMessaging",
}

_KEEPALIVE = b": keepalive\n\n"


class FakeControllerProblem(Exception):
    """A problem+json answer of the fake's; a verb called in process raises it."""

    def __init__(self, status: int, problem_type: str, title: str) -> None:
        super().__init__(f"{status} {problem_type}: {title}")
        self.status = status
        self.problem_type = problem_type
        self.title = title

    def response(self) -> Response:
        body = {"type": self.problem_type, "title": self.title, "status": self.status}
        return Response(
            _compact(body),
            status=self.status,
            content_type="application/problem+json",
        )


@dataclass(eq=False)
class FakeEnvironment:
    env_id: str
    name: str | None
    repo: str
    status: EnvironmentStatus
    exempt: bool
    restart_count: int = 0
    restart_reason: str | None = None
    settles_to: EnvironmentStatus | None = "running"
    """What a start brings it to at once; None leaves it `starting`."""
    unreachable: bool = False
    capped: bool = False
    unprojectable: bool = False
    sessions_created: int = 0

    def to_json(self) -> dict[str, Any]:
        running = self.status == "running"
        pod = None
        if self.status != "stopped":
            pod = {
                "phase": "Running" if running else "Pending",
                "ready": running,
                "restartCount": self.restart_count,
                "restartReason": self.restart_reason,
                "restartExitCode": None,
            }
        return {
            "envId": self.env_id,
            "name": self.name,
            "repo": self.repo,
            "ref": "main",
            "status": self.status,
            "mode": "normal",
            "statusReason": None,
            "pod": pod,
            "setup": {"overall": "succeeded", "steps": []} if running else None,
            "setupRunning": False,
            "issues": [],
            "capabilities": {"capacityExempt": {"enabled": self.exempt}},
        }


@dataclass(eq=False)
class FakeSession:
    """A headless session, its raw file as `lines`: each line with the file's
    byte offset after it."""

    env_id: str
    name: str
    cwd: str
    session_id: str
    status: HeadlessStatus = "idle"
    turn: int = 0
    size: int = 0
    lines: list[tuple[int, str]] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    """The last turn's result frame, held until the next send."""

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": "An example session",
            "mode": "headless",
            "cwd": self.cwd,
            "lastActivityAt": "2026-01-01T00:00:00Z",
            "attached": None,
            "status": self.status,
            "turn": self.turn,
            "sessionId": self.session_id,
            "agent": None,
            "model": None,
        }

    def view(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": "An example session",
            "state": "running",
            "mode": "headless",
            "cwd": self.cwd,
            "lastActivityAt": "2026-01-01T00:00:00Z",
            "working": self.status in ("busy", "interrupting"),
            "sessionId": self.session_id,
        }


@dataclass(eq=False)
class _Subscriber:
    frames: list[bytes] = field(default_factory=list)


_ROUTES = Map(
    [
        Rule("/readyz", endpoint="readyz", methods=["GET"]),
        Rule("/stream", endpoint="fleet_stream", methods=["GET"]),
        Rule("/environments", endpoint="list_environments", methods=["GET"]),
        Rule("/environments/<env_id>", endpoint="get_environment", methods=["GET"]),
        Rule("/environments/<env_id>/start", endpoint="start", methods=["POST"]),
        Rule("/environments/<env_id>/stop", endpoint="stop", methods=["POST"]),
        Rule(
            "/environments/<env_id>/sessions",
            endpoint="list_sessions",
            methods=["GET"],
        ),
        Rule(
            "/environments/<env_id>/sessions/headless",
            endpoint="create_session",
            methods=["POST"],
        ),
        Rule(
            "/environments/<env_id>/sessions/<name>",
            endpoint="get_session",
            methods=["GET"],
        ),
        Rule(
            "/environments/<env_id>/sessions/<name>",
            endpoint="end_session",
            methods=["DELETE"],
        ),
        Rule(
            "/environments/<env_id>/sessions/headless/<name>/messages",
            endpoint="send",
            methods=["POST"],
        ),
        Rule(
            "/environments/<env_id>/sessions/headless/<name>/interrupt",
            endpoint="interrupt",
            methods=["POST"],
        ),
        Rule(
            "/environments/<env_id>/sessions/headless/<name>/response",
            endpoint="response",
            methods=["GET"],
        ),
        Rule(
            "/environments/<env_id>/sessions/headless/<name>/log",
            endpoint="log",
            methods=["GET"],
        ),
        Rule("/fake/<verb>", endpoint="verb", methods=["POST"]),
    ]
)


class FakeController:
    """The controller, with the environments and sessions a test gives it.

    `calls` is every controller call it answered, `METHOD /path?query`, in order.
    """

    def __init__(self, token: str, keepalive_seconds: float = 20.0) -> None:
        self._token = token
        self._keepalive = keepalive_seconds
        self._changed = threading.Condition()
        self._environments: dict[str, FakeEnvironment] = {}
        self._sessions: dict[tuple[str, str], FakeSession] = {}
        self._subscribers: list[_Subscriber] = []
        self._drops = 0
        self._closed = False
        self.calls: list[str] = []
        self._endpoints: dict[str, Callable[..., Response]] = {
            "readyz": self._readyz,
            "fleet_stream": self._fleet_stream,
            "list_environments": self._list_environments,
            "get_environment": self._get_environment,
            "start": self._start,
            "stop": self._stop,
            "list_sessions": self._list_sessions,
            "create_session": self._create_session,
            "get_session": self._get_session,
            "end_session": self._end_session,
            "send": self._send,
            "interrupt": self._interrupt,
            "response": self._response,
            "log": self._log,
            "verb": self._verb,
        }
        self._verbs: dict[str, Callable[..., Any]] = {
            "add-environment": self.add_environment,
            "remove-environment": self.remove_environment,
            "set-status": self.set_status,
            "set-exempt": self.set_exempt,
            "settle-starts": self.settle_starts,
            "restart": self.restart,
            "unreachable": self.unreachable,
            "capped": self.capped,
            "unprojectable": self.unprojectable,
            "busy": self.busy,
            "play": self.play,
            "finish": self.finish,
            "write-log": self.write_log,
            "publish-state": self.publish_state,
            "publish-sessions": self.publish_sessions,
            "drop-streams": self.drop_streams,
            "reset": self.reset,
        }

    def __call__(
        self, environ: WSGIEnvironment, start_response: StartResponse
    ) -> Iterable[bytes]:
        response = self._respond(Request(environ))
        return response(environ, start_response)

    # -- Reads, for a test ----------------------------------------------------

    def environment(self, env_id: str) -> FakeEnvironment:
        with self._changed:
            return self._environment(env_id)

    def session(self, env_id: str, name: str) -> FakeSession:
        with self._changed:
            return self._session(env_id, name)

    def sessions(self, env_id: str) -> list[FakeSession]:
        with self._changed:
            return [s for s in self._sessions.values() if s.env_id == env_id]

    # -- Verbs ----------------------------------------------------------------

    @validate_call
    def add_environment(
        self,
        env_id: str,
        name: str | None = None,
        repo: str = "example/Example",
        status: EnvironmentStatus = "stopped",
        exempt: bool = False,
    ) -> None:
        """An environment of the fleet; a `state` frame announces it."""
        with self._changed:
            environment = FakeEnvironment(env_id, name, repo, status, exempt)
            self._environments[env_id] = environment
            self._publish(self._state_frame(environment))

    @validate_call
    def remove_environment(self, env_id: str) -> None:
        """The environment is gone: a `gone` frame, its sessions with it."""
        with self._changed:
            environment = self._environment(env_id)
            self._sweep(environment)
            del self._environments[env_id]
            gone = _compact({"envId": env_id})
            self._publish(f"event: gone\ndata: {gone}\n\n".encode())

    @validate_call
    def set_status(self, env_id: str, status: EnvironmentStatus) -> None:
        """The environment reaches `status`; waits on it end as it does."""
        with self._changed:
            self._set_status(self._environment(env_id), status)

    @validate_call
    def set_exempt(self, env_id: str, exempt: bool) -> None:
        with self._changed:
            environment = self._environment(env_id)
            environment.exempt = exempt
            self._publish(self._state_frame(environment))

    @validate_call
    def settle_starts(self, env_id: str, status: EnvironmentStatus | None) -> None:
        """What a start brings the environment to at once; None leaves it
        `starting` until `set_status`."""
        with self._changed:
            self._environment(env_id).settles_to = status

    @validate_call
    def restart(self, env_id: str) -> None:
        """The pod restarted: its sessions and their files are gone, and the
        environment reads `starting` until `set_status` brings it back."""
        with self._changed:
            environment = self._environment(env_id)
            environment.restart_count += 1
            environment.restart_reason = "Error"
            self._set_status(environment, "starting")

    @validate_call
    def unreachable(self, env_id: str, on: bool = True) -> None:
        """The environment's worker cannot be reached: `502 worker-unreachable`."""
        with self._changed:
            self._environment(env_id).unreachable = on

    @validate_call
    def capped(self, env_id: str, on: bool = True) -> None:
        """The node is at its cap: a start is `409 admission-blocked`, unless
        the environment is exempt."""
        with self._changed:
            self._environment(env_id).capped = on

    @validate_call
    def unprojectable(self, env_id: str, on: bool = True) -> None:
        """The controller cannot describe the environment: its list names it
        under `unprojectable` rather than among its items."""
        with self._changed:
            self._environment(env_id).unprojectable = on

    @validate_call
    def busy(self, env_id: str, name: str) -> None:
        """A turn is in flight: a send is `409 session-busy`. The previous
        turn's result is no longer held, as after a send."""
        with self._changed:
            session = self._session(env_id, name)
            session.status = "busy"
            session.result = None
            self._publish(self._sessions_frame(env_id))

    @validate_call
    def play(self, env_id: str, name: str, lines: list[str]) -> list[int]:
        """`claude` prints `lines`: the raw file grows by them, and an open
        stream sends them. Returns each line's offset."""
        with self._changed:
            session = self._session(env_id, name)
            offsets: list[int] = []
            for line in lines:
                if "\n" in line:
                    raise FakeControllerProblem(
                        422, "validation-error", "a raw line holds no newline"
                    )
                session.size += len(line.encode()) + 1
                session.lines.append((session.size, line))
                offsets.append(session.size)
            self._changed.notify_all()
            return offsets

    @validate_call
    def finish(
        self,
        env_id: str,
        name: str,
        outcome: FinishOutcome = "success",
        result: str = "",
    ) -> None:
        """The turn in flight ends: its result frame is held until the next send."""
        with self._changed:
            session = self._session(env_id, name)
            if session.status not in ("busy", "interrupting"):
                raise FakeControllerProblem(
                    409, "conflict", f"session {name} has no turn in flight"
                )
            self._resolve(session, outcome, result)

    @validate_call
    def write_log(self, env_id: str, name: str, lines: list[str]) -> None:
        """The session's condensed log grows by `lines`."""
        with self._changed:
            self._session(env_id, name).log.extend(lines)

    @validate_call
    def publish_state(self, env_id: str) -> None:
        with self._changed:
            self._publish(self._state_frame(self._environment(env_id)))

    @validate_call
    def publish_sessions(self, env_id: str) -> None:
        with self._changed:
            self._environment(env_id)
            self._publish(self._sessions_frame(env_id))

    def drop_streams(self) -> None:
        """Every open stream ends at once, as a dropped connection does."""
        with self._changed:
            self._drops += 1
            self._changed.notify_all()

    def reset(self) -> None:
        """Forget every environment, session and call; drop every stream."""
        with self._changed:
            self._environments.clear()
            self._sessions.clear()
            self.calls.clear()
            self._drops += 1
            self._changed.notify_all()

    def close(self) -> None:
        """End every open stream and held call, for good."""
        with self._changed:
            self._closed = True
            self._changed.notify_all()

    # -- HTTP -----------------------------------------------------------------

    def _respond(self, request: Request) -> Response:
        adapter = _ROUTES.bind_to_environ(request.environ)
        try:
            endpoint, arguments = adapter.match()
        except HTTPException as error:
            # The controller's router answers a path or method it has no route
            # for itself, with no problem type.
            return Response(
                json.dumps({"detail": error.name}),
                status=error.code,
                content_type="application/json",
            )
        try:
            if endpoint not in ("readyz", "verb"):
                with self._changed:
                    path = request.full_path.removesuffix("?")
                    self.calls.append(f"{request.method} {path}")
                if request.headers.get("Authorization") != f"Bearer {self._token}":
                    raise FakeControllerProblem(
                        401,
                        "unauthenticated",
                        "the bearer is not a client's credential",
                    )
            return self._endpoints[endpoint](request, **arguments)
        except FakeControllerProblem as problem:
            return problem.response()

    def _readyz(self, request: Request) -> Response:
        return _json({"status": "ok", "checks": {}})

    def _verb(self, request: Request, verb: str) -> Response:
        method = self._verbs.get(verb)
        if method is None:
            raise FakeControllerProblem(
                404, "not-found", f"the fake has no verb {verb}"
            )
        arguments = request.get_json(silent=True) or {}
        if not isinstance(arguments, dict):
            raise FakeControllerProblem(
                422, "validation-error", "a verb's body is its keyword arguments"
            )
        try:
            answer = method(**arguments)
        except ValidationError as error:
            raise FakeControllerProblem(422, "validation-error", str(error)) from error
        if answer is None:
            return Response(status=204)
        return _json(answer)

    def _list_environments(self, request: Request) -> Response:
        with self._changed:
            environments = self._environments.values()
            items = [e.to_json() for e in environments if not e.unprojectable]
            unprojectable = [e.env_id for e in environments if e.unprojectable]
        return _json({"items": items, "unprojectable": unprojectable})

    def _get_environment(self, request: Request, env_id: str) -> Response:
        wait = request.args.get("wait", "none")
        if wait not in ("none", "ready", "settled"):
            raise FakeControllerProblem(422, "validation-error", f"wait={wait}")
        with self._changed:
            environment = self._environment(env_id)
            if wait != "none":
                wait_ms = min(
                    request.args.get("waitMs", 900_000, type=int), WAIT_MS_CAP
                )
                self._changed.wait_for(
                    lambda: (
                        self._closed
                        or environment.status
                        in ("running", "error", "stopped", "deleting")
                    ),
                    timeout=wait_ms / 1000,
                )
            body = environment.to_json()
        return _json(body)

    def _start(self, request: Request, env_id: str) -> Response:
        with self._changed:
            environment = self._environment(env_id)
            if environment.status == "deleting":
                raise FakeControllerProblem(409, "conflict", f"{env_id} is deleting")
            if environment.status == "running":
                return _json(environment.to_json())
            if environment.capped and not environment.exempt:
                raise FakeControllerProblem(
                    409,
                    "admission-blocked",
                    "node example-node is at its environment limit",
                )
            self._set_status(environment, "starting")
            body = environment.to_json()
            if environment.settles_to is not None:
                self._set_status(environment, environment.settles_to)
        return _json(body, 202)

    def _stop(self, request: Request, env_id: str) -> Response:
        with self._changed:
            environment = self._environment(env_id)
            if environment.status == "deleting":
                raise FakeControllerProblem(409, "conflict", f"{env_id} is deleting")
            if environment.status == "stopped":
                return _json(environment.to_json())
            self._set_status(environment, "stopping")
            body = environment.to_json()
            self._set_status(environment, "stopped")
        return _json(body, 202)

    def _list_sessions(self, request: Request, env_id: str) -> Response:
        with self._changed:
            self._gate(env_id)
            views = [s.view() for s in self._sessions.values() if s.env_id == env_id]
        return _json({"sessions": views})

    def _create_session(self, request: Request, env_id: str) -> Response:
        body = request.get_json(silent=True) or {}
        unknown = set(body) - _CREATE_FIELDS
        if unknown:
            raise FakeControllerProblem(
                422, "validation-error", f"unknown fields {sorted(unknown)}"
            )
        with self._changed:
            environment = self._gate(env_id)
            environment.sessions_created += 1
            cwd = body.get("cwd") or "Example"
            session = FakeSession(
                env_id,
                f"claude-{environment.sessions_created}",
                cwd if cwd.startswith("/") else f"/work/{cwd}",
                body.get("resume") or "",
            )
            self._sessions[(env_id, session.name)] = session
            self._publish(self._sessions_frame(env_id))
            snapshot = session.snapshot()
        return _json(snapshot)

    def _get_session(self, request: Request, env_id: str, name: str) -> Response:
        with self._changed:
            self._gate(env_id)
            snapshot = self._session(env_id, name).snapshot()
        return _json(snapshot)

    def _end_session(self, request: Request, env_id: str, name: str) -> Response:
        with self._changed:
            self._gate(env_id)
            if self._sessions.pop((env_id, name), None) is not None:
                self._publish(self._sessions_frame(env_id))
        return Response(status=204)

    def _send(self, request: Request, env_id: str, name: str) -> Response:
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("message"), str):
            raise FakeControllerProblem(422, "validation-error", "message is required")
        with self._changed:
            self._gate(env_id)
            session = self._session(env_id, name)
            if session.status not in ("idle", "error"):
                raise FakeControllerProblem(
                    409, "session-busy", f"session {name} has a turn in flight"
                )
            session.status = "busy"
            session.result = None
            session.session_id = session.session_id or str(uuid.uuid4())
            self._publish(self._sessions_frame(env_id))
        return Response(status=202)

    def _interrupt(self, request: Request, env_id: str, name: str) -> Response:
        with self._changed:
            self._gate(env_id)
            session = self._session(env_id, name)
            if session.status == "busy":
                self._resolve(session, "interrupted", "")
        return Response(status=204)

    def _log(self, request: Request, env_id: str, name: str) -> Response:
        head = request.args.get("head", type=int)
        tail = request.args.get("tail", type=int)
        with self._changed:
            self._gate(env_id)
            lines = list(self._session(env_id, name).log)
        if head is not None:
            lines = lines[:head]
        if tail is not None:
            lines = lines[-tail:] if tail else []
        return _json({"lines": lines})

    def _response(self, request: Request, env_id: str, name: str) -> Response:
        stream_format = request.args.get("format", "")
        if stream_format != "raw":
            raise FakeControllerProblem(
                422, "validation-error", "the fake serves format=raw alone"
            )
        offset = max(request.args.get("offset", 0, type=int), 0)
        wait_ms = request.args.get("waitMs", type=int)
        deadline = None if wait_ms is None else time.perf_counter() + wait_ms / 1000
        with self._changed:
            self._gate(env_id)
            session = self._session(env_id, name)
            sent = sum(
                1
                for end, line in session.lines
                if end - len(line.encode()) - 1 < offset
            )
            frames = self._response_frames(session, sent, deadline, self._drops)
        return _event_stream(frames)

    def _response_frames(
        self, session: FakeSession, sent: int, deadline: float | None, drops: int
    ) -> Iterator[bytes]:
        while True:
            with self._changed:
                self._changed.wait_for(
                    partial(self._response_due, session, sent, deadline, drops),
                    timeout=_until(deadline, self._keepalive),
                )
                if self._cut(session, drops):
                    return
                lines = session.lines[sent:]
                result = session.result
                status = session.status
            sent += len(lines)
            for end, line in lines:
                yield f"event: raw\nid: {end}\ndata: {line}\n\n".encode()
            if result is not None:
                yield f"event: result\ndata: {_compact(result)}\n\n".encode()
                return
            if _past(deadline):
                yield f"event: incomplete\ndata: {_compact(status)}\n\n".encode()
                return
            if not lines:
                yield _KEEPALIVE

    def _response_due(
        self, session: FakeSession, sent: int, deadline: float | None, drops: int
    ) -> bool:
        """Whether a response stream that sent `sent` lines has more to send."""
        return (
            self._cut(session, drops)
            or len(session.lines) > sent
            or session.result is not None
            or _past(deadline)
        )

    def _fleet_stream(self, request: Request) -> Response:
        with self._changed:
            subscriber = _Subscriber(
                [self._sessions_frame(env_id) for env_id in self._environments]
            )
            self._subscribers.append(subscriber)
            frames = self._fleet_frames(subscriber, self._drops)
        return _event_stream(frames)

    def _fleet_frames(self, subscriber: _Subscriber, drops: int) -> Iterator[bytes]:
        try:
            while True:
                with self._changed:
                    self._changed.wait_for(
                        lambda: (
                            subscriber.frames or self._closed or self._drops != drops
                        ),
                        timeout=self._keepalive,
                    )
                    if self._closed or self._drops != drops:
                        return
                    frames = list(subscriber.frames)
                    subscriber.frames.clear()
                yield from frames or [_KEEPALIVE]
        finally:
            with self._changed:
                self._subscribers.remove(subscriber)

    # -- State, under the lock ------------------------------------------------

    def _environment(self, env_id: str) -> FakeEnvironment:
        environment = self._environments.get(env_id)
        if environment is None:
            raise FakeControllerProblem(404, "not-found", f"no environment {env_id}")
        return environment

    def _session(self, env_id: str, name: str) -> FakeSession:
        session = self._sessions.get((env_id, name))
        if session is None:
            raise FakeControllerProblem(
                404, "not-found", "no headless session with that name"
            )
        return session

    def _gate(self, env_id: str) -> FakeEnvironment:
        """The worker-proxied routes' gate, in the controller's order."""
        environment = self._environment(env_id)
        if environment.status != "running":
            raise FakeControllerProblem(
                409, "conflict", f"{env_id} is {environment.status}, not running"
            )
        if environment.unreachable:
            raise FakeControllerProblem(
                502, "worker-unreachable", f"the worker of {env_id} does not answer"
            )
        return environment

    def _set_status(
        self, environment: FakeEnvironment, status: EnvironmentStatus
    ) -> None:
        environment.status = status
        if status != "running":
            self._sweep(environment)
        self._publish(self._state_frame(environment))

    def _sweep(self, environment: FakeEnvironment) -> None:
        """The pod is gone or going: its headless sessions and their files with it."""
        names = [
            key
            for key, session in self._sessions.items()
            if session.env_id == environment.env_id
        ]
        for key in names:
            del self._sessions[key]
        if names:
            self._publish(self._sessions_frame(environment.env_id))

    def _resolve(self, session: FakeSession, outcome: FinishOutcome, text: str) -> None:
        is_error, interrupted, status = _OUTCOMES[outcome]
        session.turn += 1
        session.result = {
            "turn": session.turn,
            "result": text,
            "isError": is_error,
            "interrupted": interrupted,
        }
        session.status = status
        self._publish(self._sessions_frame(session.env_id))

    def _cut(self, session: FakeSession, drops: int) -> bool:
        """Whether a response stream of `session` opened at `drops` has dropped."""
        return (
            self._closed
            or self._drops != drops
            or self._sessions.get((session.env_id, session.name)) is not session
        )

    def _publish(self, frame: bytes) -> None:
        for subscriber in self._subscribers:
            subscriber.frames.append(frame)
        self._changed.notify_all()

    def _state_frame(self, environment: FakeEnvironment) -> bytes:
        data = _compact(environment.to_json())
        return f"event: state\ndata: {data}\n\n".encode()

    def _sessions_frame(self, env_id: str) -> bytes:
        views = [s.view() for s in self._sessions.values() if s.env_id == env_id]
        data = _compact({"envId": env_id, "sessions": views})
        return f"event: sessions\ndata: {data}\n\n".encode()


def _compact(body: Any) -> str:
    """JSON as the controller and the worker write it, with no spaces."""
    return json.dumps(body, separators=(",", ":"))


def _json(body: Any, status: int = 200) -> Response:
    return Response(_compact(body), status=status, content_type="application/json")


def _event_stream(frames: Iterator[bytes]) -> Response:
    return Response(
        _headers_first(frames),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


def _headers_first(frames: Iterator[bytes]) -> Iterator[bytes]:
    """The frames after an empty write, which sends the headers at once, as the
    controller does when a stream opens."""
    yield b""
    yield from frames


def _past(deadline: float | None) -> bool:
    return deadline is not None and time.perf_counter() >= deadline


def _until(deadline: float | None, keepalive: float) -> float:
    if deadline is None:
        return keepalive
    return max(0.0, min(keepalive, deadline - time.perf_counter()))
