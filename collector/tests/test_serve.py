"""The collector's route: a conversation's reading over HTTP, as Pilot's
backend is served it."""

import gzip
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from pilot_collection.reading import ReadingSchema

from pilot_collector.reading import reading
from pilot_collector.serve import GONE, server, validator
from tests.support import (
    AGENT,
    SESSION,
    answering,
    chained,
    content,
    filed,
    image,
    requesting,
    result,
    settings,
    typed,
    words,
)

TOKEN = "an-invented-collector-token"
VERSION = {"X-Pilot-Reading-Version": "1"}
BEARER = {"Authorization": f"Bearer {TOKEN}"}

LINES = [
    typed(0),
    requesting(3, "toolu_01", tool="Read"),
    result(5, "toolu_01", [words("A swatch."), image(90_000)]),
    answering(8, "msg_02", words("It is twill.")),
]


@pytest.fixture
def home(tmp_path: Path) -> Path:
    (tmp_path / "projects").mkdir()
    return tmp_path


@contextmanager
def _serving(home: Path, headers: dict[str, str]) -> Iterator[httpx.Client]:
    """The route served over `home` on a port of its own, and a caller of
    it that sends `headers`."""
    serving, port = server(
        settings(COLLECTOR_HOME=home, COLLECTOR_TOKEN=TOKEN, COLLECTOR_PORT=0)
    )
    threading.Thread(target=serving.run, daemon=True).start()
    address = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(base_url=address, headers=headers) as client:
            yield client
    finally:
        serving.close()


@pytest.fixture
def backend(home: Path) -> Iterator[httpx.Client]:
    """Pilot's backend as the route's caller: it carries the bearer and
    names the reading's version."""
    with _serving(home, BEARER | VERSION) as client:
        yield client


@pytest.fixture
def stranger(home: Path) -> Iterator[httpx.Client]:
    """A caller that sends no header of its own."""
    with _serving(home, {}) as client:
        yield client


class TestAReading:
    def test_a_main_threads_is_served_by_its_session(
        self, home: Path, backend: httpx.Client
    ) -> None:
        named = filed(home / "projects", LINES)

        answer = backend.get(f"/readings/{SESSION}")

        assert answer.status_code == 200
        assert answer.headers["Content-Type"] == "application/json"
        served = ReadingSchema.model_validate_json(answer.content)
        assert served == reading(named)
        assert [call.message_id for call in served.calls] == ["msg_01", "msg_02"]

    def test_a_sub_agents_is_served_by_its_session_and_its_agent(
        self, home: Path, backend: httpx.Client
    ) -> None:
        filed(home / "projects", LINES)
        named = filed(home / "projects", [typed(0, "Dye the wool.")], AGENT)

        answer = backend.get(f"/readings/{SESSION}/{AGENT}")

        assert answer.status_code == 200
        served = ReadingSchema.model_validate_json(answer.content)
        assert served == reading(named)
        assert served.agent_id == AGENT

    def test_it_is_compressed_and_sent_in_parts(
        self, home: Path, backend: httpx.Client
    ) -> None:
        """Whatever the call accepts: the body is gzip, with no length
        ahead of it."""
        named = filed(home / "projects", LINES)

        with backend.stream(
            "GET", f"/readings/{SESSION}", headers={"Accept-Encoding": "identity"}
        ) as answer:
            sent = b"".join(answer.iter_raw())

        assert answer.headers["Content-Encoding"] == "gzip"
        assert answer.headers["Transfer-Encoding"] == "chunked"
        assert "Content-Length" not in answer.headers
        assert gzip.decompress(sent) == reading(named).model_dump_json().encode()

    def test_it_holds_no_images_bytes(self, home: Path, backend: httpx.Client) -> None:
        filed(home / "projects", LINES)

        answer = backend.get(f"/readings/{SESSION}")

        assert len(content(LINES)) > 120_000
        assert len(answer.content) < 2_000
        assert '"images":[{"media_type":"image/png","size":90000}]' in answer.text

    def test_a_file_the_collector_cannot_read_is_not_served_in_part(
        self, home: Path, backend: httpx.Client
    ) -> None:
        filed(home / "projects", [*LINES, chained("assistant", 9)])

        answer = backend.get(f"/readings/{SESSION}")

        assert answer.status_code == 500
        assert "msg_01" not in answer.text


class TestTheValidator:
    def test_it_is_the_files_size_and_time(
        self, home: Path, backend: httpx.Client
    ) -> None:
        named = filed(home / "projects", LINES)
        status = named.path.stat()

        answer = backend.get(f"/readings/{SESSION}")

        tag = f'"{status.st_size}-{status.st_mtime_ns // 1000}"'
        assert answer.headers["ETag"] == tag
        served = ReadingSchema.model_validate_json(answer.content)
        assert validator(served.file_size, served.file_modified_at) == tag

    @pytest.mark.parametrize("named", ["{}", "W/{}", '"0-0", {}'])
    def test_a_call_that_names_it_is_answered_not_changed(
        self, home: Path, backend: httpx.Client, named: str
    ) -> None:
        filed(home / "projects", LINES)
        tag = backend.get(f"/readings/{SESSION}").headers["ETag"]

        answer = backend.get(
            f"/readings/{SESSION}", headers={"If-None-Match": named.format(tag)}
        )

        assert answer.status_code == 304
        assert answer.headers["ETag"] == tag
        assert answer.content == b""

    def test_a_file_that_grew_is_served_again(
        self, home: Path, backend: httpx.Client
    ) -> None:
        named = filed(home / "projects", LINES)
        before = backend.get(f"/readings/{SESSION}").headers["ETag"]
        with named.path.open("ab") as file:
            file.write(content([answering(12, "msg_03", words("And satin."))]))

        answer = backend.get(f"/readings/{SESSION}", headers={"If-None-Match": before})

        assert answer.status_code == 200
        assert answer.headers["ETag"] != before
        served = ReadingSchema.model_validate_json(answer.content)
        assert [call.message_id for call in served.calls][-1] == "msg_03"


class TestATranscriptTheHomeLacks:
    @pytest.mark.parametrize(
        "ids",
        [
            "7d1e0c3a-5b2f-4a68-9c0d-e4f1a2b3c4d5",
            f"{SESSION}/b7e2d4f6a8c0e1357",
            f"../{AGENT}",
            f"{SESSION}/..",
        ],
    )
    def test_it_is_answered_gone(
        self, home: Path, backend: httpx.Client, ids: str
    ) -> None:
        filed(home / "projects", LINES)
        filed(home / "projects", [typed(0)], AGENT)

        answer = backend.get(httpx.URL(f"/readings/{ids}".replace("..", "%2E%2E")))

        assert answer.status_code == 404
        assert answer.json()["code"] == GONE

    @pytest.mark.parametrize(
        "path", ["/", "/readings", "/readings/", f"/transcripts/{SESSION}", "/a/b/c/d"]
    )
    def test_a_path_that_is_no_readings_is_not_answered_gone(
        self, home: Path, backend: httpx.Client, path: str
    ) -> None:
        filed(home / "projects", LINES)

        answer = backend.get(path)

        assert answer.status_code == 404
        assert "code" not in answer.json()

    def test_a_reading_is_asked_for_and_never_sent(
        self, home: Path, backend: httpx.Client
    ) -> None:
        filed(home / "projects", LINES)

        answer = backend.post(f"/readings/{SESSION}")

        assert answer.status_code == 404
        assert "code" not in answer.json()


class TestTheCaller:
    @pytest.mark.parametrize(
        "carried",
        [{}, {"Authorization": "Bearer another-token"}, {"Authorization": TOKEN}],
    )
    def test_a_call_without_the_bearer_is_refused(
        self, home: Path, stranger: httpx.Client, carried: dict[str, str]
    ) -> None:
        """Before its version is read, and whatever it asks for."""
        filed(home / "projects", LINES)

        for path in (f"/readings/{SESSION}", "/"):
            answer = stranger.get(path, headers=carried)

            assert answer.status_code == 401
            assert "bearer" in answer.json()["error"]

    @pytest.mark.parametrize("named", [None, "0", "2", "1.0", "one", ""])
    def test_a_call_outside_the_readings_versions_is_refused_with_those_served(
        self, home: Path, stranger: httpx.Client, named: str | None
    ) -> None:
        filed(home / "projects", LINES)
        version = {} if named is None else {"X-Pilot-Reading-Version": named}

        answer = stranger.get(f"/readings/{SESSION}", headers=BEARER | version)

        assert answer.status_code == 426
        assert answer.json() == {"min": 1, "max": 1}
