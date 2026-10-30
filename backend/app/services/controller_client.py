"""Pilot's client of the KubeCoder controller (design 2 §14, D10).

One synchronous client under Pilot's named client credential, making the calls
of design 2 §2. The two streams, a session's response stream on `format=raw`
and the fleet `/stream`, are iterators of frames. The contract is KubeCoder's
`docs/api/controller-api.md` and `docs/api/worker-api.md`.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import Any, Literal
from urllib.parse import quote

import requests
from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic.alias_generators import to_camel
from urllib3.exceptions import HTTPError

from app.core_exceptions import ExternalServiceException
from app.services.controller_outage import ControllerOutage
from app.services.health_service import CheckResult, CheckStatus, HealthService

STREAM_READ_TIMEOUT_SECONDS = 60
"""A stream silent this long has dropped; the controller's keepalive is every 20 s."""

WAIT_MS_CAP = 3_600_000
"""The longest `waitMs` the controller holds a call for; it clamps a longer one."""

FILE_SIZE_CAP = 16 * 1024 * 1024
"""The most bytes a file route reads or writes: `413 file-too-large` past it."""

CONTENT_SHA256_HEADER = "KubeCoder-Content-Sha256"
"""The header a file read or write answers with: the bytes' lowercase hex SHA-256."""

LISTING_PAGE_CAP = 1000
"""The most entries a page of a folder's listing holds: its `limit`'s bound."""

_CONNECT_TIMEOUT_SECONDS = 10
_CALL_TIMEOUT_SECONDS = 30
_READINESS_TIMEOUT_SECONDS = 2
_READ_CHUNK_BYTES = 65536

EnvironmentStatus = Literal[
    "provisioning", "starting", "running", "stopping", "stopped", "deleting", "error"
]
HeadlessStatus = Literal["starting", "idle", "busy", "interrupting", "ended", "error"]
EnvironmentWait = Literal["ready", "settled"]
UsageWindowCode = Literal["five_hour", "seven_day"]
StaleReason = Literal[
    "no-reading-yet",
    "no-credential",
    "token-expired",
    "token-rejected",
    "rate-limited",
    "endpoint-error",
]


class ControllerProblemType(StrEnum):
    """The controller's problem types its callers switch on."""

    NOT_FOUND = "not-found"
    CONFLICT = "conflict"
    NAME_CONFLICT = "name-conflict"
    SESSION_BUSY = "session-busy"
    ADMISSION_BLOCKED = "admission-blocked"
    NAMESPACE_NOT_WHITELISTED = "namespace-not-whitelisted"
    VALIDATION_ERROR = "validation-error"
    CAPABILITY_UNAVAILABLE = "capability-unavailable"
    WORKER_UNREACHABLE = "worker-unreachable"
    ENVIRONMENT_UNREADABLE = "environment-unreadable"
    PATH_OUTSIDE_WORK = "path-outside-work"
    NOT_A_FILE = "not-a-file"
    NOT_A_DIRECTORY = "not-a-directory"
    FILE_TOO_LARGE = "file-too-large"


_PROBLEM_STATUS = {
    ControllerProblemType.NOT_FOUND: 404,
    ControllerProblemType.CONFLICT: 409,
    ControllerProblemType.NAME_CONFLICT: 409,
    ControllerProblemType.SESSION_BUSY: 409,
    ControllerProblemType.ADMISSION_BLOCKED: 409,
    ControllerProblemType.NAMESPACE_NOT_WHITELISTED: 403,
    ControllerProblemType.VALIDATION_ERROR: 422,
    ControllerProblemType.CAPABILITY_UNAVAILABLE: 409,
    ControllerProblemType.WORKER_UNREACHABLE: 502,
    ControllerProblemType.ENVIRONMENT_UNREADABLE: 503,
    ControllerProblemType.PATH_OUTSIDE_WORK: 403,
    ControllerProblemType.NOT_A_FILE: 409,
    ControllerProblemType.NOT_A_DIRECTORY: 409,
    ControllerProblemType.FILE_TOO_LARGE: 413,
}


class ControllerProblem(ExternalServiceException):
    """The controller answered with a problem its callers switch on.

    A request that lets it through is answered 502, as for any failing upstream.
    """

    def __init__(
        self,
        operation: str,
        problem_type: ControllerProblemType,
        title: str,
        detail: str | None = None,
    ) -> None:
        self.problem_type = problem_type
        self.title = title
        self.detail = detail
        super().__init__(
            operation,
            f"the controller answered {_PROBLEM_STATUS[problem_type]} "
            f"{problem_type}: {_reason(title, detail)}",
        )


class ControllerUnreachable(ExternalServiceException):
    """The controller did not answer: a connection error, a timeout, or a 5xx
    without its own problem+json, which an ingress in front of it writes. The
    call turned the outage on (review O2)."""


class _ControllerModel(BaseModel):
    """A shape of the controller's: camelCase on the wire, fields Pilot reads."""

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="ignore", frozen=True
    )


class ControllerPod(_ControllerModel):
    started_at: datetime | None = None
    """When the pod started, the kubelet's stamp: one pod's identity, which a
    container's restart in it leaves as it is."""
    restart_count: int
    restart_reason: str | None = None


class _Enabled(_ControllerModel):
    enabled: bool


class _Capabilities(_ControllerModel):
    capacity_exempt: _Enabled


class ControllerEnvironment(_ControllerModel):
    """An environment as the controller projects it."""

    env_id: str
    name: str | None = None
    managed_by: str | None = None
    """The client that manages it, recorded by a create with `managed: true`."""
    repo: str
    status: EnvironmentStatus
    pod: ControllerPod | None = None
    setup_running: bool
    capabilities: _Capabilities

    @property
    def exempt(self) -> bool:
        """`capabilities.capacityExempt.enabled`: the environment stands outside
        its node's count (F73.1)."""
        return self.capabilities.capacity_exempt.enabled


class EnvironmentList(_ControllerModel):
    items: list[ControllerEnvironment]
    unprojectable: list[str]
    """Environments still there that the controller could not describe."""


class SessionView(_ControllerModel):
    """A row of an environment's session set: its list, and a `sessions` frame."""

    name: str
    title: str
    state: Literal["running", "stopped"]
    mode: Literal["interactive", "headless"]
    working: bool
    session_id: str | None = None


class SessionSnapshot(_ControllerModel):
    """A session's status snapshot; the headless fields are null on an interactive one."""

    name: str
    mode: Literal["interactive", "headless"]
    status: HeadlessStatus | None = None
    turn: int | None = None
    session_id: str | None = None


class _SessionList(_ControllerModel):
    sessions: list[SessionView]


class _SessionLog(_ControllerModel):
    lines: list[str]


class HeadlessCreateRequest(_ControllerModel):
    """The headless create's body; a field left None is not sent."""

    cwd: str | None = None
    resume: str | None = None
    """A Claude conversation id: the Session's `conversation_id`."""
    agent: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    env: list[str] | None = None
    mcp_config: list[str] | None = None
    strict_mcp_config: bool | None = None
    disable_slash_commands: bool | None = None
    enable_cross_session_messaging: bool | None = None
    sandbox: bool | None = None
    """Box every turn in a kernel-enforced write scope: `$HOME`, `/tmp`, the
    cwd and each of `sandbox_writable_dirs` writable, every other mount
    read-only. A turn whose box cannot be built fails at its spawn."""
    sandbox_read_only_cwd: bool | None = None
    """The cwd a read-only root of the box; True implies `sandbox`."""
    sandbox_writable_dirs: list[str] | None = None
    """Absolute paths of existing folders, writable roots of the box; a
    non-empty list implies `sandbox`."""


class ControllerUsageWindow(_ControllerModel):
    """One window's figure in a usage reading."""

    window: UsageWindowCode
    share: float
    """The window's use as a fraction, unclamped: it may pass 1."""
    resets_at: datetime


class ControllerUsageReading(_ControllerModel):
    """The subscription's usage, as the controller's poll last read it."""

    taken_at: datetime | None
    """When the endpoint answered these figures; None before its first answer."""
    stale: bool
    """The latest poll got no answer: the figures are the last answer's."""
    stale_reason: StaleReason | None
    windows: list[ControllerUsageWindow]
    """A window the endpoint left out is missing; empty before the first answer."""


@dataclass(frozen=True)
class FileContent:
    """A file as a read of it answered."""

    data: bytes
    sha256: str
    """The controller's lowercase hex SHA-256 of `data`."""


class _FileEntry(_ControllerModel):
    path: str
    """Its absolute path under the listed folder's resolved path; a folder's ends in `/`."""
    is_directory: bool


class _FileListing(_ControllerModel):
    files: list[_FileEntry]
    limit_hit: bool


@dataclass(frozen=True)
class StartOutcome:
    environment: ControllerEnvironment
    started: bool
    """True on `202`: this call scheduled the bring-up. False on `200`: the
    environment was running already."""


@dataclass(frozen=True)
class RawFrame:
    """One line of the session's raw file, as `claude` printed it."""

    offset: int
    """The raw file's byte offset after the line: the `offset` that resumes after it."""
    line: str


@dataclass(frozen=True)
class ResultFrame:
    """The worker's terminal frame of a turn. It carries no offset."""

    turn: int
    result: str | None
    is_error: bool
    interrupted: bool
    payload: dict[str, Any]
    """The frame's data, as the worker sent it."""


@dataclass(frozen=True)
class IncompleteFrame:
    """A bounded stream's end before the turn's result."""

    status: HeadlessStatus


ResponseFrame = RawFrame | ResultFrame | IncompleteFrame


@dataclass(frozen=True)
class StateFrame:
    environment: ControllerEnvironment


@dataclass(frozen=True)
class GoneFrame:
    env_id: str


@dataclass(frozen=True)
class SessionsFrame:
    """An environment's whole session set."""

    env_id: str
    sessions: tuple[SessionView, ...]


@dataclass(frozen=True)
class UsageFrame:
    """The subscription's usage reading, whole: the seed on connect, then each
    change of anything but its `takenAt`."""

    reading: ControllerUsageReading


FleetFrame = StateFrame | GoneFrame | SessionsFrame | UsageFrame


@dataclass(frozen=True)
class _Event:
    name: str
    data: str
    id: str | None


class _ResultData(_ControllerModel):
    turn: int
    result: str | None = None
    is_error: bool = False
    interrupted: bool = False


class _GoneData(_ControllerModel):
    env_id: str


class _SessionsData(_ControllerModel):
    env_id: str
    sessions: list[SessionView]


class _ProblemData(_ControllerModel):
    type: str | None = None
    title: str | None = None
    detail: str | None = None


def _parse[ModelT: BaseModel](model: type[ModelT], data: str, operation: str) -> ModelT:
    try:
        return model.model_validate_json(data)
    except ValidationError as error:
        raise ExternalServiceException(
            operation, f"the controller's answer does not parse: {error}"
        ) from error


def _events(chunks: Iterator[bytes]) -> Iterator[_Event]:
    """The SSE events of a byte stream. A line ends at `\\n` alone: a raw line's
    data is `claude`'s line as printed, carriage returns included."""
    pending: list[bytes] = []
    name, data, event_id, seen_data = "message", list[str](), None, False
    for chunk in chunks:
        if b"\n" not in chunk:
            pending.append(chunk)
            continue
        lines = (b"".join(pending) + chunk).split(b"\n")
        pending = [lines.pop()]
        for raw in lines:
            line = raw.decode()
            if not line:
                if seen_data:
                    yield _Event(name, "\n".join(data), event_id)
                name, data, event_id, seen_data = "message", [], None, False
            elif not line.startswith(":"):
                field, _, value = line.partition(":")
                value = value.removeprefix(" ")
                if field == "event":
                    name = value
                elif field == "data":
                    data.append(value)
                    seen_data = True
                elif field == "id":
                    event_id = value


class ControllerStream[FrameT]:
    """One of the controller's SSE streams, open: iterate it once for its frames.

    A stream that ends before its terminal frame, or is silent past the read
    timeout, raises ExternalServiceException. `close()` may come from any
    thread: it wakes a read blocked on the socket, and the iteration then ends
    without raising.
    """

    def __init__(
        self,
        response: requests.Response,
        operation: str,
        decode: Callable[[_Event], FrameT | None],
        is_terminal: Callable[[FrameT], bool],
        end_cause: str,
    ) -> None:
        self._response = response
        self._operation = operation
        self._decode = decode
        self._is_terminal = is_terminal
        self._end_cause = end_cause
        self._lock = threading.Lock()
        self._closed = False
        self._released = False

    def __iter__(self) -> Iterator[FrameT]:
        try:
            for event in _events(self._chunks()):
                frame = self._decode(event)
                if frame is None:
                    continue
                yield frame
                if self._is_terminal(frame):
                    return
            if not self._closed:
                raise ExternalServiceException(self._operation, self._end_cause)
        finally:
            self._release()

    def close(self) -> None:
        """End the stream: a read blocked on it returns, and its iteration ends."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._released:
                return
            try:
                self._response.raw.shutdown()
            except RuntimeError:
                # The body was read to its end, which released the connection:
                # no read is blocked on it.
                pass

    def __enter__(self) -> ControllerStream[FrameT]:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
        self._release()

    def _chunks(self) -> Iterator[bytes]:
        try:
            while chunk := self._response.raw.read1(_READ_CHUNK_BYTES):
                yield chunk
        except (HTTPError, OSError) as error:
            if not self._closed:
                raise ExternalServiceException(
                    self._operation, f"the stream dropped: {error}"
                ) from error

    def _release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
            self._response.close()


class ControllerClient:
    """The KubeCoder controller, under Pilot's named client credential.

    A call the controller answers with a problem its callers switch on raises
    ControllerProblem; a call it does not answer raises ControllerUnreachable
    and turns the outage on; any other failure raises ExternalServiceException.
    A stream that drops once its call was answered turns nothing on.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        health_service: HealthService,
        outage: ControllerOutage,
        ca_file: Path | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._outage = outage
        self._headers = {"Authorization": f"Bearer {token}"}
        self._verify: str | bool = str(ca_file) if ca_file is not None else True
        # Not critical: Pilot serves its record without the controller.
        health_service.register_check(
            "controller", self.check_readiness, critical=False
        )

    def check_readiness(self) -> CheckResult:
        """Readiness check: the controller answers its own `/readyz`."""
        response = requests.get(
            f"{self._base_url}/readyz",
            timeout=_READINESS_TIMEOUT_SECONDS,
            verify=self._verify,
        )
        if response.status_code != 200:
            return CheckResult(
                CheckStatus.ERROR, f"the controller answered {response.status_code}"
            )
        return CheckResult(CheckStatus.OK)

    def probe(self) -> None:
        """The gate's probe (design 2 §13.4): returns once the controller
        answers its own `/readyz` with `200`."""
        self._call(
            "GET",
            "/readyz",
            "probe the controller",
            expect=(200,),
            timeout=_READINESS_TIMEOUT_SECONDS,
        )

    def list_environments(self) -> EnvironmentList:
        operation = "list the controller's environments"
        response = self._call("GET", "/environments", operation, expect=(200,))
        return _parse(EnvironmentList, response.text, operation)

    def get_environment(
        self,
        env_id: str,
        wait: EnvironmentWait | None = None,
        wait_ms: int = WAIT_MS_CAP,
    ) -> ControllerEnvironment:
        """The environment; with `wait`, once it is there, it reads `error`,
        `stopped` or `deleting`, or `wait_ms` ran out, whichever comes first."""
        operation = f"read environment {env_id}"
        params: dict[str, str | int] = {}
        timeout: float = _CALL_TIMEOUT_SECONDS
        if wait is not None:
            params = {"wait": wait, "waitMs": wait_ms}
            timeout += min(wait_ms, WAIT_MS_CAP) / 1000
        response = self._call(
            "GET",
            f"/environments/{_segment(env_id)}",
            operation,
            expect=(200,),
            params=params,
            timeout=timeout,
        )
        return _parse(ControllerEnvironment, response.text, operation)

    def start_environment(self, env_id: str) -> StartOutcome:
        """Start the environment, without `wait`: only then does the status say
        whether this call scheduled the bring-up."""
        operation = f"start environment {env_id}"
        response = self._call(
            "POST",
            f"/environments/{_segment(env_id)}/start",
            operation,
            expect=(200, 202),
        )
        environment = _parse(ControllerEnvironment, response.text, operation)
        return StartOutcome(environment, started=response.status_code == 202)

    def stop_environment(self, env_id: str) -> ControllerEnvironment:
        operation = f"stop environment {env_id}"
        response = self._call(
            "POST",
            f"/environments/{_segment(env_id)}/stop",
            operation,
            expect=(200, 202),
        )
        return _parse(ControllerEnvironment, response.text, operation)

    def create_environment(
        self, repo: str, name: str | None = None
    ) -> ControllerEnvironment:
        """Create an environment of `repo`, `owner/Name`, managed by Pilot's
        client, without `wait`: the answer, `provisioning`, carries its env id
        before its bring-up ends in a running pod."""
        operation = f"create an environment of {repo}"
        body: dict[str, Any] = {"repo": repo, "managed": True}
        if name is not None:
            body["name"] = name
        response = self._call(
            "POST", "/environments", operation, expect=(202,), json_body=body
        )
        return _parse(ControllerEnvironment, response.text, operation)

    def reset_environment(self, env_id: str) -> ControllerEnvironment:
        """Reset a stopped environment, without `wait`: its folder cleared and
        its bring-up run again, it answers `starting` and ends in a running
        pod, as a start does."""
        operation = f"reset environment {env_id}"
        response = self._call(
            "POST",
            f"/environments/{_segment(env_id)}/reset",
            operation,
            expect=(202,),
        )
        return _parse(ControllerEnvironment, response.text, operation)

    def rename_environment(self, env_id: str, name: str) -> ControllerEnvironment:
        """Set the environment's display name; a blank `name` clears it."""
        operation = f"rename environment {env_id}"
        response = self._call(
            "POST",
            f"/environments/{_segment(env_id)}/rename",
            operation,
            expect=(200,),
            json_body={"name": name},
        )
        return _parse(ControllerEnvironment, response.text, operation)

    def delete_environment(self, env_id: str) -> None:
        """Delete the environment; one already gone, answered `404`, is deleted."""
        try:
            self._call(
                "DELETE",
                f"/environments/{_segment(env_id)}",
                f"delete environment {env_id}",
                expect=(202,),
            )
        except ControllerProblem as problem:
            if problem.problem_type is not ControllerProblemType.NOT_FOUND:
                raise

    def create_headless_session(
        self, env_id: str, request: HeadlessCreateRequest
    ) -> SessionSnapshot:
        operation = f"create a headless session in environment {env_id}"
        response = self._call(
            "POST",
            f"/environments/{_segment(env_id)}/sessions/headless",
            operation,
            expect=(200,),
            json_body=request.model_dump(by_alias=True, exclude_none=True),
        )
        return _parse(SessionSnapshot, response.text, operation)

    def send_message(self, env_id: str, name: str, message: str) -> None:
        """Send a turn: on return, the session is `busy` with it."""
        self._call(
            "POST",
            f"{_headless(env_id, name)}/messages",
            f"send a turn to session {name} in environment {env_id}",
            expect=(202,),
            json_body={"message": message},
        )

    def interrupt(self, env_id: str, name: str) -> None:
        self._call(
            "POST",
            f"{_headless(env_id, name)}/interrupt",
            f"interrupt session {name} in environment {env_id}",
            expect=(204,),
        )

    def end_session(self, env_id: str, name: str) -> None:
        """End the session, deleting its files; ending one already gone is a no-op."""
        self._call(
            "DELETE",
            _session(env_id, name),
            f"end session {name} in environment {env_id}",
            expect=(204,),
        )

    def get_session(self, env_id: str, name: str) -> SessionSnapshot:
        operation = f"read session {name} in environment {env_id}"
        response = self._call("GET", _session(env_id, name), operation, expect=(200,))
        return _parse(SessionSnapshot, response.text, operation)

    def list_sessions(self, env_id: str) -> list[SessionView]:
        operation = f"list the sessions of environment {env_id}"
        response = self._call(
            "GET",
            f"/environments/{_segment(env_id)}/sessions",
            operation,
            expect=(200,),
        )
        return _parse(_SessionList, response.text, operation).sessions

    def read_log(
        self, env_id: str, name: str, head: int | None = None, tail: int | None = None
    ) -> list[str]:
        """The session's condensed log lines: the first `head`, the last `tail`."""
        operation = f"read the log of session {name} in environment {env_id}"
        params: dict[str, str | int] = {
            key: value
            for key, value in (("head", head), ("tail", tail))
            if value is not None
        }
        response = self._call(
            "GET",
            f"{_headless(env_id, name)}/log",
            operation,
            expect=(200,),
            params=params,
        )
        return _parse(_SessionLog, response.text, operation).lines

    def read_file(self, env_id: str, path: str) -> FileContent:
        """The file at `path`, an absolute path under the environment's
        `/work`, read off its share: a stopped environment's too."""
        operation = f"read {path} in environment {env_id}"
        response = self._call(
            "GET",
            f"/environments/{_segment(env_id)}/file",
            operation,
            expect=(200,),
            params={"path": path},
        )
        return FileContent(response.content, _content_sha256(response, operation))

    def write_file(self, env_id: str, path: str, data: bytes) -> str:
        """Overwrite the file at `path` with `data`, or create it and the
        folders it needs, on the environment's share: a stopped environment's
        too. The SHA-256 of what it wrote.

        It sends no `expectedSha256`: a write is a whole overwrite. Its
        `409 conflict` is the controller's own work on the tree — a bring-up
        under way, a delete accepted, the pod changing the path during the
        call — which the controller's contract says to retry once settled.
        """
        operation = f"write {path} in environment {env_id}"
        response = self._call(
            "PUT",
            f"/environments/{_segment(env_id)}/file",
            operation,
            expect=(204,),
            params={"path": path},
            content=data,
        )
        return _content_sha256(response, operation)

    def list_folder_files(self, env_id: str, path: str) -> list[str]:
        """Every file under the folder at `path`, its subfolders' included, in
        path order: each `path` joined with the file's path relative to it, so
        a file a link leads to is named through the folder, as the read
        follows it. A link loop under it is the controller's `409 conflict`."""
        files: list[str] = []
        folders = [path]
        while folders:
            folder = folders.pop()
            prefix = folder.rstrip("/")
            for entry in self._list_folder(env_id, folder):
                child = f"{prefix}/{entry.path.rstrip('/').rsplit('/', 1)[-1]}"
                if entry.is_directory:
                    folders.append(f"{child}/")
                else:
                    files.append(child)
        return sorted(files)

    def _list_folder(self, env_id: str, path: str) -> list[_FileEntry]:
        """Every entry of the folder at `path`, over as many pages as it takes."""
        operation = f"list {path} in environment {env_id}"
        entries: list[_FileEntry] = []
        while True:
            response = self._call(
                "GET",
                f"/environments/{_segment(env_id)}/files",
                operation,
                expect=(200,),
                params={
                    "path": path,
                    "offset": len(entries),
                    "limit": LISTING_PAGE_CAP,
                },
            )
            page = _parse(_FileListing, response.text, operation)
            entries.extend(page.files)
            if not page.limit_hit:
                return entries

    def open_response_stream(
        self, env_id: str, name: str, offset: int, wait_ms: int | None = None
    ) -> ControllerStream[ResponseFrame]:
        """The turn's raw lines from `offset` on, then its result: open it after
        the send's `202`, or it delivers the previous turn's buffered result.
        With `wait_ms` it ends at that bound with an `incomplete` frame."""
        operation = (
            f"read the response stream of session {name} in environment {env_id}"
        )
        params: dict[str, str | int] = {"format": "raw", "offset": offset}
        if wait_ms is not None:
            params["waitMs"] = wait_ms
        response = self._call(
            "GET",
            f"{_headless(env_id, name)}/response",
            operation,
            expect=(200,),
            params=params,
            timeout=STREAM_READ_TIMEOUT_SECONDS,
            stream=True,
        )
        return ControllerStream(
            response,
            operation,
            lambda event: _response_frame(event, operation),
            lambda frame: not isinstance(frame, RawFrame),
            "the stream ended before the turn's result",
        )

    def open_fleet_stream(self) -> ControllerStream[FleetFrame]:
        """Every environment's `state`, `gone` and `sessions` frames, and the
        `usage` frames, as they come.

        The state channel opens with no snapshot: open the stream first, then
        list the environments, and apply the list before the frames that came
        meanwhile. The usage channel's first frame is the reading at the
        connect. The other channels' frames are not Pilot's and are skipped.
        """
        operation = "read the controller's fleet stream"
        response = self._call(
            "GET",
            "/stream",
            operation,
            expect=(200,),
            timeout=STREAM_READ_TIMEOUT_SECONDS,
            stream=True,
        )
        return ControllerStream(
            response,
            operation,
            lambda event: _fleet_frame(event, operation),
            lambda frame: False,
            "the controller ended the stream",
        )

    def _call(
        self,
        method: str,
        path: str,
        operation: str,
        *,
        expect: tuple[int, ...],
        params: dict[str, str | int] | None = None,
        json_body: dict[str, Any] | None = None,
        content: bytes | None = None,
        timeout: float = _CALL_TIMEOUT_SECONDS,
        stream: bool = False,
    ) -> requests.Response:
        headers = self._headers
        if content is not None:
            headers = {**headers, "Content-Type": "application/octet-stream"}
        try:
            response = requests.request(
                method,
                f"{self._base_url}{path}",
                params=params,
                json=json_body,
                data=content,
                headers=headers,
                timeout=(_CONNECT_TIMEOUT_SECONDS, timeout),
                stream=stream,
                verify=self._verify,
            )
        except requests.RequestException as error:
            self._outage.call_unanswered()
            raise ControllerUnreachable(
                operation, f"the controller did not answer: {error}"
            ) from error
        if response.status_code in expect:
            return response
        failure = _failure(operation, response)
        response.close()
        if isinstance(failure, ControllerUnreachable):
            self._outage.call_unanswered()
        raise failure


def _failure(operation: str, response: requests.Response) -> ExternalServiceException:
    """What a status the call did not expect means: a 5xx without the
    controller's own problem+json is not the controller's answer."""
    problem = _ProblemData()
    if response.headers.get("Content-Type", "").startswith("application/problem+json"):
        problem = _parse(_ProblemData, response.text, operation)
    elif response.status_code >= 500:
        return ControllerUnreachable(
            operation,
            f"the controller did not answer: {response.status_code} "
            f"{response.reason}, not the controller's own",
        )
    title = problem.title or response.reason
    for known, status in _PROBLEM_STATUS.items():
        if problem.type == known and response.status_code == status:
            return ControllerProblem(operation, known, title, problem.detail)
    answer = " ".join(
        str(part) for part in (response.status_code, problem.type) if part
    )
    return ExternalServiceException(
        operation,
        f"the controller answered {answer}: {_reason(title, problem.detail)}",
    )


def _reason(title: str, detail: str | None) -> str:
    return title if detail is None else f"{title}; {detail}"


def _content_sha256(response: requests.Response, operation: str) -> str:
    sha256 = response.headers.get(CONTENT_SHA256_HEADER)
    if sha256 is None:
        raise ExternalServiceException(
            operation, f"the answer came without its {CONTENT_SHA256_HEADER}"
        )
    return sha256


def _response_frame(event: _Event, operation: str) -> ResponseFrame:
    if event.name == "raw":
        if event.id is None:
            raise ExternalServiceException(operation, "a raw frame came without its id")
        return RawFrame(int(event.id), event.data)
    if event.name == "result":
        result = _parse(_ResultData, event.data, operation)
        return ResultFrame(
            result.turn,
            result.result,
            result.is_error,
            result.interrupted,
            json.loads(event.data),
        )
    if event.name == "incomplete":
        status: HeadlessStatus = json.loads(event.data)
        return IncompleteFrame(status)
    raise ExternalServiceException(
        operation, f"the stream sent a {event.name!r} frame, not one of format=raw's"
    )


def _fleet_frame(event: _Event, operation: str) -> FleetFrame | None:
    if event.name == "state":
        return StateFrame(_parse(ControllerEnvironment, event.data, operation))
    if event.name == "gone":
        return GoneFrame(_parse(_GoneData, event.data, operation).env_id)
    if event.name == "sessions":
        sessions = _parse(_SessionsData, event.data, operation)
        return SessionsFrame(sessions.env_id, tuple(sessions.sessions))
    if event.name == "usage":
        return UsageFrame(_parse(ControllerUsageReading, event.data, operation))
    # An `enrollment` frame carries the one secret of an enrolling machine's
    # handoff: it is skipped unread, never logged.
    return None


def _segment(value: str) -> str:
    return quote(value, safe="")


def _session(env_id: str, name: str) -> str:
    return f"/environments/{_segment(env_id)}/sessions/{_segment(name)}"


def _headless(env_id: str, name: str) -> str:
    return f"/environments/{_segment(env_id)}/sessions/headless/{_segment(name)}"
