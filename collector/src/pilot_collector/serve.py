"""The collector's own route (F152.13): a conversation's reading, served to
Pilot's backend, its only caller.

`GET /readings/<session_id>` is a main thread's reading and
`GET /readings/<session_id>/<agent_id>` a sub-agent's. A call carries the
collector's bearer, the one its own calls to Pilot carry, and names the
version of the reading it reads in `X-Pilot-Reading-Version`. It is answered,
in this order:

- `401`, without the bearer;
- `426`, with the versions served as `{min, max}`, where it names none or
  one outside them;
- `404` with the code `TRANSCRIPT_GONE`, where the home has no file a walk
  lists under those ids; a `404` without it is a path that is no reading's;
- `304`, where `If-None-Match` names the file's validator: the file was
  found and nothing of it read;
- `200`, the reading (`pilot_collection.reading`), as JSON, gzip-compressed
  whatever the call accepts and sent in parts as it is compressed.

The validator is the file's size and time, as the `ETag` of a `200` and a
`304`: `"<bytes>-<microseconds since 1970>"`, never a date.
"""

import hmac
import json
import re
import socket
import zlib
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from wsgiref.types import StartResponse, WSGIEnvironment

from pilot_collection.reading import ReadingVersionRangeSchema
from waitress.server import BaseWSGIServer, MultiSocketServer, create_server

from pilot_collector.home import PROJECTS, find
from pilot_collector.reading import reading
from pilot_collector.settings import Settings

READING_MIN = 1
READING_MAX = 1
"""The versions of the reading the route serves, both ends included."""

GONE = "TRANSCRIPT_GONE"
"""The `code` of the 404 for ids the home has no file under."""

_ROUTE = "readings"

_VERSION = re.compile(r"\d{1,9}")

_EPOCH = datetime.fromtimestamp(0, UTC)

_PART = 65_536
"""The bytes of a reading compressed at a time."""

_JSON = ("Content-Type", "application/json")

type _Answer = tuple[str, list[tuple[str, str]], Iterable[bytes]]


def validator(file_size: int, file_modified_at: datetime) -> str:
    """A file's size and time as an entity tag."""
    since = (file_modified_at - _EPOCH) // timedelta(microseconds=1)
    return f'"{file_size}-{since}"'


def _said(status: str, body: dict[str, Any]) -> _Answer:
    return status, [_JSON], [json.dumps(body).encode()]


def _gone() -> _Answer:
    return _said(
        "404 Not Found",
        {"error": "The home has no transcript of those ids", "code": GONE},
    )


def _named(header: str) -> set[str]:
    """The entity tags an `If-None-Match` names, a weak one as its tag."""
    return {tag.strip().removeprefix("W/") for tag in header.split(",")}


def _compressed(document: bytes) -> Iterator[bytes]:
    """The document as gzip, a part at a time."""
    packer = zlib.compressobj(wbits=zlib.MAX_WBITS | 16)
    whole = memoryview(document)
    for start in range(0, len(whole), _PART):
        packed = packer.compress(whole[start : start + _PART])
        if packed:
            yield packed
    yield packer.flush()


class Readings:
    """The route as a WSGI application, over the transcripts under
    `projects`, for calls that carry `token` as their bearer."""

    def __init__(self, projects: Path, token: str) -> None:
        self._projects = projects
        self._bearer = f"Bearer {token}".encode()

    def __call__(
        self, environ: WSGIEnvironment, start_response: StartResponse
    ) -> Iterable[bytes]:
        status, headers, body = self._answer(environ)
        start_response(status, headers)
        return body

    def _answer(self, environ: WSGIEnvironment) -> _Answer:
        carried: str = environ.get("HTTP_AUTHORIZATION", "")
        if not hmac.compare_digest(carried.encode("latin-1"), self._bearer):
            return _said(
                "401 Unauthorized",
                {"error": "The call does not carry the collector's bearer"},
            )
        version: str | None = environ.get("HTTP_X_PILOT_READING_VERSION")
        if (
            version is None
            or not _VERSION.fullmatch(version)
            or not READING_MIN <= int(version) <= READING_MAX
        ):
            served = ReadingVersionRangeSchema(min=READING_MIN, max=READING_MAX)
            return _said("426 Upgrade Required", served.model_dump())
        path: str = environ["PATH_INFO"]
        root, *ids = path.removeprefix("/").split("/")
        if (
            environ["REQUEST_METHOD"] != "GET"
            or root != _ROUTE
            or len(ids) not in (1, 2)
            or not all(ids)
        ):
            return _said(
                "404 Not Found", {"error": "The collector serves no such path"}
            )
        listed = find(self._projects, *ids)
        if listed is None:
            return _gone()
        tag = validator(listed.file_size, listed.file_modified_at)
        if tag in _named(environ.get("HTTP_IF_NONE_MATCH", "")):
            return "304 Not Modified", [("ETag", tag)], []
        try:
            read = reading(listed.transcript)
        except FileNotFoundError:
            return _gone()
        headers = [
            _JSON,
            ("Content-Encoding", "gzip"),
            ("ETag", validator(read.file_size, read.file_modified_at)),
        ]
        return "200 OK", headers, _compressed(read.model_dump_json().encode())


def server(settings: Settings) -> tuple[BaseWSGIServer | MultiSocketServer, int]:
    """The route's server, whose `run` serves until the process ends, and
    the port it listens on, on every address of the host: the one the
    settings name, or where they name 0, one that was free."""
    listening = socket.create_server(("0.0.0.0", settings.COLLECTOR_PORT))
    port: int = listening.getsockname()[1]
    readings = Readings(
        settings.COLLECTOR_HOME / PROJECTS,
        settings.COLLECTOR_TOKEN.get_secret_value(),
    )
    return create_server(readings, sockets=[listening]), port
