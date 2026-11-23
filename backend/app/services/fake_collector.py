"""A fake of the collector's readings (F122.5), for the suites: no suite asks
a collector for a conversation's reading.

A WSGI application the real `ReadingsService` reaches by its COLLECTOR_URL:
served on a thread under pytest (`tests/support/fake_collector.py`), and
mounted for Playwright under `/api/testing/collector`
(`app/api/testing_collector.py`). It answers the collector's route
(`pilot_collector.serve`) as the collector does, in its order:
`GET /readings/<session_id>` a main thread's reading and
`GET /readings/<session_id>/<agent_id>` a sub-agent's; `401` without its
bearer; `426` with the versions it serves, `{min, max}`, where the ask names
none or another; `404` with the code `TRANSCRIPT_GONE` for ids it holds no
reading of; `304` where `If-None-Match` names the reading's validator; else
`200`, the reading as JSON, gzip-compressed, its validator the `ETag`,
`"<bytes>-<microseconds since 1970>"` of the file's size and time.

The readings it holds are those of the scenario a load handed it
(`ScenarioService.load`), each the collector's own reading of the scenario's
files as that load built them, so that a reading's calls are the facts'
calls; and those a test hands it (`serve`). The scenario's are read through
the collector's code, which the backend's dev group installs, at the first
verb or ask after the load, so the fake serves them only where that group is
installed: the suites.

A test drives it through its verbs, the public methods below: in process
under pytest, and over HTTP as `POST /fake/<verb>`, the verb's name
hyphenated and its keyword arguments the JSON body. A conversation's reading
is made gone (`gone`) or too large for the page (`too_large`), every ask is
refused (`refuse`), and `asks` lists the asks taken.

Simplifications of the collector: it reads no file at an ask, so a reading
changes only by a load or a verb; a refusal is every ask's, whatever it
names; a reading is sent in one part, with its length.
"""

from __future__ import annotations

import gzip
import json
import re
import tempfile
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pilot_collection.reading import ReadingSchema, UserBlockSchema
from pilot_scenario import Builder
from pilot_scenario.transcript import text
from pydantic import ValidationError, validate_call
from pydantic_core import to_jsonable_python
from werkzeug.exceptions import HTTPException
from werkzeug.routing import Map, Rule
from werkzeug.wrappers import Request, Response

if TYPE_CHECKING:
    from _typeshed.wsgi import StartResponse, WSGIEnvironment

SERVED_VERSION = 1
"""The version of the reading the fake serves, as the collector does today."""

GONE = "TRANSCRIPT_GONE"

TOO_LARGE = 3_000_000
"""The characters `too_large` adds by default: past the 2 MB of texts the
reader takes in one answer (F154.7)."""

Refusal = Literal["version", "unreadable"]
"""How a refused ask is answered: as a collector that serves another version
of the reading refuses one (`426`, `{min: 2, max: 2}`), or as one that
cannot read the file (`500`, with nothing of the reading)."""

_EPOCH = datetime.fromtimestamp(0, UTC)

_VERSION = re.compile(r"\d{1,9}")

_ROUTES = Map(
    [
        Rule("/readings/<session_id>", endpoint="reading", methods=["GET"]),
        Rule("/readings/<session_id>/<agent_id>", endpoint="reading", methods=["GET"]),
        Rule("/fake/<verb>", endpoint="verb", methods=["POST"]),
    ]
)


class FakeCollectorProblem(Exception):
    """A verb the fake refuses; a verb called in process raises it."""

    def __init__(self, status: int, error: str) -> None:
        super().__init__(f"{status}: {error}")
        self.status = status
        self.error = error


@dataclass(frozen=True)
class FakeAsk:
    """An ask the fake took: the reading it named, the validator it named in
    `If-None-Match`, none where it named none, and the status answered."""

    session_id: str
    agent_id: str | None
    validator: str | None
    status: int


def validator(reading: ReadingSchema) -> str:
    """The reading's validator, its file's size and time, as the collector
    writes it."""
    since = (reading.file_modified_at - _EPOCH) // timedelta(microseconds=1)
    return f'"{reading.file_size}-{since}"'


class FakeCollector:
    """The collector's readings route, under the bearer `token`."""

    def __init__(self, token: str) -> None:
        self._bearer = f"Bearer {token}"
        self._lock = threading.Lock()
        self._readings: dict[tuple[str, str | None], ReadingSchema] = {}
        self._scenario: Builder | None = None
        self._refusal: Refusal | None = None
        self._asks: list[FakeAsk] = []
        self._verbs: dict[str, Callable[..., Any]] = {
            "serve": self.serve,
            "gone": self.gone,
            "too-large": self.too_large,
            "refuse": self.refuse,
            "asks": self.asks,
            "reset": self.reset,
        }

    def __call__(
        self, environ: WSGIEnvironment, start_response: StartResponse
    ) -> Iterable[bytes]:
        response = self._respond(Request(environ))
        return response(environ, start_response)

    def scenario(self, builder: Builder) -> None:
        """Hold the scenario's readings as `builder` built its files, each in
        place of any of the same ids, and refuse no ask."""
        with self._lock:
            self._scenario = builder
            self._refusal = None

    # -- Verbs ----------------------------------------------------------------

    @validate_call
    def serve(self, reading: ReadingSchema) -> None:
        """Hold `reading` in place of any of its ids."""
        with self._lock:
            self._held()[reading.session_id, reading.agent_id] = reading

    @validate_call
    def gone(self, session_id: str, agent_id: str | None = None) -> None:
        """The home has no file of those ids from now on."""
        with self._lock:
            self._held().pop((session_id, agent_id), None)

    @validate_call
    def too_large(
        self, session_id: str, agent_id: str | None = None, characters: int = TOO_LARGE
    ) -> None:
        """The reading of those ids grows by a person's line of `characters`
        invented characters after its last Call, its file larger by as many
        bytes and written a second later."""
        with self._lock:
            held = self._held()
            reading = held.get((session_id, agent_id))
            if reading is None:
                raise FakeCollectorProblem(
                    404, f"the fake holds no reading of {session_id} {agent_id}"
                )
            at = reading.file_modified_at + timedelta(seconds=1)
            line = UserBlockSchema(
                kind="user", at=at, writer="person", text=text(characters)
            )
            held[session_id, agent_id] = reading.model_copy(
                update={
                    "file_size": reading.file_size + characters,
                    "file_modified_at": at,
                    "after": [*reading.after, line],
                }
            )

    @validate_call
    def refuse(self, refusal: Refusal | None = "version") -> None:
        """Answer every ask from now on as `refusal` says; none serves them
        again."""
        with self._lock:
            self._refusal = refusal

    @validate_call
    def asks(self) -> list[FakeAsk]:
        """Every ask taken, in order."""
        with self._lock:
            return list(self._asks)

    @validate_call
    def reset(self) -> None:
        """Forget every reading, ask and refusal."""
        with self._lock:
            self._readings.clear()
            self._scenario = None
            self._refusal = None
            self._asks.clear()

    # -- HTTP -----------------------------------------------------------------

    def _respond(self, request: Request) -> Response:
        adapter = _ROUTES.bind_to_environ(request.environ)
        try:
            endpoint, arguments = adapter.match()
            if endpoint == "reading":
                return self._reading(
                    request, arguments["session_id"], arguments.get("agent_id")
                )
            return self._verb(request, arguments["verb"])
        except HTTPException as error:
            return _said(error.code or 500, {"error": error.name})
        except FakeCollectorProblem as problem:
            return _said(problem.status, {"error": problem.error})

    def _reading(
        self, request: Request, session_id: str, agent_id: str | None
    ) -> Response:
        if request.headers.get("Authorization") != self._bearer:
            return _said(
                401, {"error": "The call does not carry the collector's bearer"}
            )
        version = request.headers.get("X-Pilot-Reading-Version", "")
        if not _VERSION.fullmatch(version) or int(version) != SERVED_VERSION:
            return _said(426, {"min": SERVED_VERSION, "max": SERVED_VERSION})
        named = request.headers.get("If-None-Match")
        with self._lock:
            response = self._answer(session_id, agent_id, named)
            self._asks.append(
                FakeAsk(session_id, agent_id, named, response.status_code)
            )
        return response

    def _answer(
        self, session_id: str, agent_id: str | None, named: str | None
    ) -> Response:
        if self._refusal == "version":
            return _said(426, {"min": SERVED_VERSION + 1, "max": SERVED_VERSION + 1})
        if self._refusal == "unreadable":
            return Response(
                "Internal Server Error", status=500, content_type="text/plain"
            )
        reading = self._held().get((session_id, agent_id))
        if reading is None:
            return _said(
                404, {"error": "The home has no transcript of those ids", "code": GONE}
            )
        tag = validator(reading)
        if named is not None and tag in {
            one.strip().removeprefix("W/") for one in named.split(",")
        }:
            return Response(status=304, headers={"ETag": tag})
        return Response(
            gzip.compress(reading.model_dump_json().encode()),
            content_type="application/json",
            headers={"Content-Encoding": "gzip", "ETag": tag},
        )

    def _verb(self, request: Request, verb: str) -> Response:
        method = self._verbs.get(verb)
        if method is None:
            raise FakeCollectorProblem(404, f"the fake has no verb {verb}")
        arguments = request.get_json(silent=True) or {}
        if not isinstance(arguments, dict):
            raise FakeCollectorProblem(422, "a verb's body is its keyword arguments")
        try:
            answer = method(**arguments)
        except ValidationError as error:
            raise FakeCollectorProblem(422, str(error)) from error
        if answer is None:
            return Response(status=204)
        return Response(
            json.dumps(to_jsonable_python(answer)), content_type="application/json"
        )

    def _held(self) -> dict[tuple[str, str | None], ReadingSchema]:
        """The readings held, the scenario a load handed it read first. Under
        the fake's lock."""
        if self._scenario is not None:
            for reading in _read(self._scenario):
                self._readings[reading.session_id, reading.agent_id] = reading
            self._scenario = None
        return self._readings


def _read(builder: Builder) -> list[ReadingSchema]:
    """Each transcript's reading of the scenario's files as `builder` built
    them, by the collector's own code."""
    from pilot_collector.home import PROJECTS, transcripts
    from pilot_collector.reading import reading

    with tempfile.TemporaryDirectory(prefix="fake-collector-") as folder:
        home = Path(folder)
        builder.write(home)
        return [reading(listed.transcript) for listed in transcripts(home / PROJECTS)]


def _said(status: int, body: dict[str, Any]) -> Response:
    return Response(json.dumps(body), status=status, content_type="application/json")
