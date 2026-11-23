"""A conversation's reading kept by the backend (F154.7): asked of the
collector, which serves it (F152.13), and kept on scratch storage, never in
the database.

`ReadingsService.read` asks the collector for a Transcript's reading at
every read, conditionally where a reading of it is kept: the collector's
"not changed" is served from what is kept, and a reading it serves is kept
in place of the one before. Two reads of one Transcript at once share one
ask. A read gives the reading (`Served`), or says why it has none: the
collector's home has no file of the Transcript (`Gone`), or the collector
refused the ask, could not be reached, or is not configured (`Refused`).

`ReadingCache` keeps each reading as the collector compressed it, one file a
Transcript, named by its id, whose first line is the reading's validator, the
collector's `ETag`. It keeps a total size at most, the least recently read
going first and the reading just kept never, so that one reading larger than
the bound is kept alone.
"""

import atexit
import gzip
import logging
import os
import secrets
import shutil
import tempfile
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import httpx
from pilot_collection.reading import ReadingSchema, ReadingVersionRangeSchema

from app.models import Transcript

logger = logging.getLogger(__name__)

READING_VERSION = 1
"""The version of the reading Pilot reads, which every ask names in
`X-Pilot-Reading-Version`."""

GONE = "TRANSCRIPT_GONE"
"""The `code` of the collector's 404 for ids its home has no file under."""

NO_COLLECTOR = (
    "Pilot has no collector to read a conversation from: COLLECTOR_URL is not set"
)
"""Why a read is refused where no collector is configured."""

NO_BEARER = (
    "Pilot has no bearer to read a conversation with: COLLECTOR_TOKEN is not set"
)
"""Why a read is refused where the collector's bearer is not configured."""

_TIMEOUT = httpx.Timeout(30.0, connect=5.0)
"""How long an ask waits for the collector: to connect, then for each part
of its answer."""

_WRITING = ".writing"
"""The suffix of a reading's file while it is written, before it takes its
Transcript's name."""


@dataclass(frozen=True)
class Served:
    """The Transcript's reading, as the collector last served it."""

    reading: ReadingSchema


@dataclass(frozen=True)
class Gone:
    """The collector's home has no file of the Transcript: one gone from the
    home, or one that never had a file there."""


@dataclass(frozen=True)
class Refused:
    """No reading was served, and why: the collector refused the ask, could
    not be reached, or is not configured."""

    why: str


type Read = Served | Gone | Refused


@dataclass(frozen=True)
class Kept:
    """A reading kept: its validator, and the reading as the collector
    compressed it."""

    validator: str
    body: bytes


class ReadingCache:
    """The readings kept in `directory`, `max_bytes` of them at most.

    The files of `directory` named by a Transcript's id are taken as kept at
    the start, the most recently read last by their time, which each read
    sets; a file left mid-write is removed, and every other file is left
    alone. The folder is the cache's alone: no other process writes it.
    """

    def __init__(self, directory: Path, max_bytes: int) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self._directory = directory
        self._max_bytes = max_bytes
        self._lock = threading.Lock()
        self._sizes: OrderedDict[uuid.UUID, int] = OrderedDict()
        """Each kept reading's file size, the least recently read first."""
        self._total = 0
        found: list[tuple[int, uuid.UUID, int]] = []
        with os.scandir(directory) as entries:
            for entry in entries:
                if not entry.is_file(follow_symlinks=False):
                    continue
                if entry.name.endswith(_WRITING):
                    os.unlink(entry.path)
                    continue
                transcript_id = _named(entry.name)
                if transcript_id is not None:
                    status = entry.stat(follow_symlinks=False)
                    found.append((status.st_mtime_ns, transcript_id, status.st_size))
        for _, transcript_id, size in sorted(found):
            self._sizes[transcript_id] = size
            self._total += size
        with self._lock:
            self._evict(keeping=None)

    def take(self, transcript_id: uuid.UUID) -> Kept | None:
        """The Transcript's reading kept, read now; none where none is."""
        with self._lock:
            if transcript_id not in self._sizes:
                return None
            path = self._path(transcript_id)
            with path.open("rb") as file:
                validator = file.readline().removesuffix(b"\n").decode()
                body = file.read()
            os.utime(path)
            self._sizes.move_to_end(transcript_id)
        return Kept(validator, body)

    def keep(self, transcript_id: uuid.UUID, validator: str, body: bytes) -> None:
        """Keep the reading in place of the Transcript's one before, the
        most recently read, and evict the least recently read past the
        bound."""
        path = self._path(transcript_id)
        writing = path.with_name(f"{path.name}.{secrets.token_hex(4)}{_WRITING}")
        with writing.open("wb") as file:
            file.write(validator.encode() + b"\n")
            file.write(body)
        size = writing.stat().st_size
        with self._lock:
            os.replace(writing, path)
            self._total += size - self._sizes.pop(transcript_id, 0)
            self._sizes[transcript_id] = size
            self._evict(keeping=transcript_id)

    def drop(self, transcript_id: uuid.UUID) -> None:
        """Forget the Transcript's reading, where one is kept."""
        with self._lock:
            size = self._sizes.pop(transcript_id, None)
            if size is not None:
                self._total -= size
                self._path(transcript_id).unlink()

    def _evict(self, keeping: uuid.UUID | None) -> None:
        for transcript_id in list(self._sizes):
            if self._total <= self._max_bytes or transcript_id == keeping:
                return
            self._total -= self._sizes.pop(transcript_id)
            self._path(transcript_id).unlink()

    def _path(self, transcript_id: uuid.UUID) -> Path:
        return self._directory / str(transcript_id)


def _named(name: str) -> uuid.UUID | None:
    """The Transcript a kept reading's file name names; none for a name that
    is no Transcript's id as the cache writes one."""
    try:
        transcript_id = uuid.UUID(name)
    except ValueError:
        return None
    return transcript_id if str(transcript_id) == name else None


@dataclass
class _Ask:
    """An ask of the collector under way, which a read of the same
    Transcript waits for."""

    done: threading.Event = field(default_factory=threading.Event)
    read: Read | None = None


class ReadingsService:
    """A conversation's reading, asked of the collector at `url` with its
    bearer `token`, and kept in `directory`, `max_bytes` at most: with no
    `directory`, in a folder of the system's temporary one made for the
    process and removed at its exit."""

    def __init__(
        self, url: str | None, token: str, directory: Path | None, max_bytes: int
    ) -> None:
        if directory is None:
            directory = Path(tempfile.mkdtemp(prefix="pilot-readings-"))
            atexit.register(shutil.rmtree, directory, ignore_errors=True)
        self._cache = ReadingCache(directory, max_bytes)
        self._client = (
            None if url is None else httpx.Client(base_url=url, timeout=_TIMEOUT)
        )
        self._token = token
        self._lock = threading.Lock()
        self._asks: dict[uuid.UUID, _Ask] = {}

    def read(self, transcript: Transcript) -> Read:
        """The Transcript's reading as the collector serves it now: asked
        conditionally where one is kept, a reading already under way for the
        Transcript taken as this read's."""
        if self._client is None:
            return Refused(NO_COLLECTOR)
        if not self._token:
            return Refused(NO_BEARER)
        while True:
            with self._lock:
                ask = self._asks.get(transcript.id)
                asking = ask is None
                if ask is None:
                    ask = self._asks[transcript.id] = _Ask()
            if not asking:
                ask.done.wait()
                if ask.read is not None:
                    return ask.read
                continue
            try:
                read = self._ask(self._client, transcript)
                ask.read = read
            finally:
                with self._lock:
                    del self._asks[transcript.id]
                ask.done.set()
            return read

    def _ask(self, client: httpx.Client, transcript: Transcript) -> Read:
        kept = self._cache.take(transcript.id)
        headers = {
            "Authorization": f"Bearer {self._token}",
            "X-Pilot-Reading-Version": str(READING_VERSION),
        }
        if kept is not None:
            headers["If-None-Match"] = kept.validator
        ids = [transcript.session_id]
        if transcript.agent_id is not None:
            ids.append(transcript.agent_id)
        path = "readings/" + "/".join(quote(part, safe="") for part in ids)
        try:
            with client.stream("GET", path, headers=headers) as response:
                if response.status_code == 200:
                    body = b"".join(response.iter_raw())
                else:
                    response.read()
        except httpx.HTTPError as error:
            return _refused(
                transcript,
                f"the collector could not be reached: {type(error).__name__}: {error}",
            )
        if response.status_code == 200:
            served = ReadingSchema.model_validate_json(gzip.decompress(body))
            self._cache.keep(transcript.id, response.headers["ETag"], body)
            return Served(served)
        if response.status_code == 304 and kept is not None:
            return Served(ReadingSchema.model_validate_json(gzip.decompress(kept.body)))
        if response.status_code == 404 and _said(response, "code") == GONE:
            self._cache.drop(transcript.id)
            return Gone()
        return _refused(transcript, _why(response))


def _said(response: httpx.Response, key: str) -> str | None:
    """The text a JSON answer gives under `key`, none where it gives none."""
    try:
        said = response.json()
    except ValueError:
        return None
    value = said.get(key) if isinstance(said, dict) else None
    return value if isinstance(value, str) else None


def _why(response: httpx.Response) -> str:
    """Why the collector's answer is no reading."""
    if response.status_code == 401:
        return "the collector refused Pilot's bearer, COLLECTOR_TOKEN"
    if response.status_code == 426:
        served = ReadingVersionRangeSchema.model_validate_json(response.content)
        return (
            f"the collector serves readings of versions {served.min} to "
            f"{served.max}, and Pilot reads version {READING_VERSION}"
        )
    error = _said(response, "error")
    said = "" if error is None else f": {error}"
    return f"the collector answered {response.status_code}{said}"


def _refused(transcript: Transcript, why: str) -> Refused:
    logger.warning("The reading of transcript %s was refused: %s", transcript.id, why)
    return Refused(why)
