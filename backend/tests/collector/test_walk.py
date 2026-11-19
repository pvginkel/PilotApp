"""The collector's walk against Pilot's routes (F152.2): a home of the
scenario's transcript files, walked by the collector's own code over HTTP,
and what Pilot's record then holds."""

import json
import logging
import os
import shutil
import threading
import time
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pilot_collector
import pytest
from dependency_injector import providers
from flask import Flask
from pilot_collector import home as collector_home
from pilot_collector import reader, walk
from pilot_collector.home import transcript
from pilot_collector.pilot import NotAdmitted, Pilot, Refused
from pilot_collector.settings import Settings
from pilot_collector.walk import Walker
from pilot_scenario import SCENARIO, Builder
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession
from werkzeug.serving import make_server

from app.extensions import db
from app.models import Call, ComponentVersion, Transcript, Walk
from app.services import publication_service
from tests.support.publications import COLLECTOR_TOKEN, collector_headers

UNTIL = datetime(2026, 11, 12, 9, 30, tzinfo=UTC)
"""When the scenario's last line was written."""

RECIPES = "8766dbc8-267a-5322-9a1d-cc49ad56eedd"
"""The scenario's conversation with a sub-agent and two saved outputs."""
SCALER = f"{RECIPES}/6d6212072d4d5b429"
"""Its sub-agent's thread."""
RIDES = "037915e7-de88-5550-9746-3e7a4472413a"
"""The scenario's other conversation, the last to be written."""
SCENARIOS = {RECIPES, SCALER, RIDES}

TOURS = "5e1f7a3c-9b24-4d68-8c05-b3a6d9e2f417"
"""Claude Code's id of a conversation the scenario has not."""

OLDER = "0.9.0"
"""A version of the collector's before this one."""

LOGGER = "pilot_collector.walk"


@pytest.fixture
def pilot_url(committed_app: Flask) -> Generator[str]:
    """Pilot served over HTTP on a database of its own, where every call's
    commit is real."""
    server = make_server("127.0.0.1", 0, committed_app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """A fleet's home that holds the scenario's transcripts."""
    Builder(SCENARIO, UNTIL).write(tmp_path)
    return tmp_path


@pytest.fixture
def stop() -> threading.Event:
    return threading.Event()


@pytest.fixture
def walker(pilot_url: str, home: Path, stop: threading.Event) -> Generator[Walker]:
    """The collector's walk of that home for that Pilot."""
    with Pilot(pilot_url, COLLECTOR_TOKEN) as pilot:
        yield Walker(pilot, _settings(pilot_url, home), stop)


def _settings(pilot_url: str, home: Path) -> Settings:
    return Settings(
        COLLECTOR_PILOT_URL=pilot_url,
        COLLECTOR_TOKEN=COLLECTOR_TOKEN,
        COLLECTOR_HOME=home,
    )


def _configure(app: Flask, interval: float = 30.0, settling: float = 600.0) -> None:
    """The walk's two settings as Pilot's inventory hands them over."""
    container = app.container
    settings = container.app_config().model_copy(
        update={
            "collector_walk_interval_seconds": interval,
            "collector_settling_seconds": settling,
        }
    )
    container.app_config.override(providers.Object(settings))


def _path(home: Path, name: str, folder: str = "-work-RecipeBox") -> Path:
    """Where the transcript of that name is filed."""
    session, _, agent = name.partition("/")
    if agent:
        return (
            home / "projects" / folder / session / "subagents" / f"agent-{agent}.jsonl"
        )
    return home / "projects" / folder / f"{session}.jsonl"


def _file(home: Path, name: str) -> Path:
    """A scenario's transcript's file."""
    return _path(home, name, "-work-BikeLog" if name == RIDES else "-work-RecipeBox")


def _copied(home: Path, name: str = TOURS, of: str = RIDES) -> Path:
    """A file the home did not have: another conversation's lines under an
    id of its own, written now."""
    path = _path(home, name, "-work-BikeLog")
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_file(home, of), path)
    return path


def _aged(path: Path, minutes: float) -> None:
    """Set the file's time to that long ago."""
    at = time.time_ns() - int(minutes * 60 * 10**9)
    os.utime(path, ns=(at, at))


def _grown(path: Path) -> None:
    """Append a line Claude Code writes beside a conversation's chain."""
    with path.open("ab") as file:
        file.write(
            json.dumps({"type": "custom-title", "customTitle": "Menus"}).encode()
        )
        file.write(b"\n")


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_bytes().splitlines()]


def _written(path: Path, lines: list[dict[str, Any]]) -> None:
    path.write_bytes(b"".join(json.dumps(line).encode() + b"\n" for line in lines))


def _directory_a_number(path: Path) -> None:
    lines = _lines(path)
    next(line for line in lines if "cwd" in line)["cwd"] = 0
    _written(path, lines)


def _tool_with_no_name(path: Path) -> None:
    lines = _lines(path)
    asked = next(
        block
        for line in lines
        if line["type"] == "assistant"
        for block in line["message"]["content"]
        if block["type"] == "tool_use"
    )
    asked["name"] = None
    _written(path, lines)


def _line_nested_past_reading(path: Path) -> None:
    with path.open("ab") as file:
        file.write(b"[" * 100_000 + b"]" * 100_000 + b"\n")


def _stands(path: Path) -> tuple[int, datetime]:
    """The file's size and time as a publication names them."""
    status = path.stat()
    return status.st_size, collector_home.modified_at(status)


def _record(app: Flask) -> DbSession:
    with app.app_context():
        return DbSession(db.engine)


def _held(app: Flask) -> dict[str, dict[str, Any]]:
    """Each Transcript Pilot holds, by its name, with its collection
    record."""
    with _record(app) as record:
        rows = record.execute(
            select(
                Transcript.session_id,
                Transcript.agent_id,
                Transcript.file_size,
                Transcript.file_modified_at,
                Transcript.replayed_size,
                Transcript.collected_at,
                ComponentVersion.version,
            ).join(ComponentVersion, ComponentVersion.id == Transcript.read_under_id)
        ).all()
    return {
        row.session_id
        if row.agent_id is None
        else f"{row.session_id}/{row.agent_id}": {
            "stands": (row.file_size, row.file_modified_at),
            "replayed_size": row.replayed_size,
            "collected_at": row.collected_at,
            "collector": row.version,
        }
        for row in rows
    }


def _in_order(app: Flask) -> list[str]:
    """The Transcripts Pilot holds, in the order their last publications
    were taken."""
    held = _held(app)
    return sorted(held, key=lambda name: held[name]["collected_at"])


def _walks(app: Flask) -> int:
    """How many walks' ends Pilot stamped."""
    with _record(app) as record:
        return record.scalar(select(func.count()).select_from(Walk))


def _ends(app: Flask) -> list[datetime]:
    """When Pilot stamped each walk's end, in their order."""
    with _record(app) as record:
        return list(record.scalars(select(Walk.ended_at).order_by(Walk.ended_at)))


def _calls(app: Flask, session_id: str) -> int:
    """How many Calls Pilot holds of that conversation's main thread."""
    with _record(app) as record:
        return record.scalar(
            select(func.count())
            .select_from(Call)
            .join(Transcript, Transcript.id == Call.transcript_id)
            .where(Transcript.session_id == session_id, Transcript.agent_id.is_(None))
        )


def _read_under(monkeypatch: pytest.MonkeyPatch, version: str) -> None:
    """Have the collector be that version of itself."""
    monkeypatch.setattr(reader, "VERSION", version)
    monkeypatch.setattr(walk, "VERSION", version)


def _set_aside(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The walk's lines for the transcripts it set aside."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER and "is set aside" in record.getMessage()
    ]


class _Stop(threading.Event):
    """A walker's stop that keeps how long each wait on it was to last."""

    def __init__(self) -> None:
        super().__init__()
        self.waits: list[float | None] = []

    def wait(self, timeout: float | None = None) -> bool:
        self.waits.append(timeout)
        return super().wait(timeout)


class TestAWalk:
    def test_the_first_walk_publishes_every_transcript_on_the_home(
        self, committed_app: Flask, home: Path, walker: Walker
    ) -> None:
        walked = walker.walk()

        assert (walked.listed, walked.published, walked.ended) == (3, 3, True)
        held = _held(committed_app)
        assert {name: each["stands"] for name, each in held.items()} == {
            name: _stands(_file(home, name)) for name in SCENARIOS
        }
        for each in held.values():
            assert each["replayed_size"] == each["stands"][0]
            assert each["collector"] == pilot_collector.VERSION
        built = {
            publication["session_id"]: len(publication["calls"])
            for publication in Builder(SCENARIO, UNTIL).publications()
            if publication.get("agent_id") is None
        }
        assert {name: _calls(committed_app, name) for name in built} == built
        assert _walks(committed_app) == 1

    def test_a_walk_of_a_home_pilot_holds_publishes_nothing_and_tells_its_end(
        self, committed_app: Flask, walker: Walker
    ) -> None:
        walker.walk()
        held = _held(committed_app)

        walked = walker.walk()

        assert (walked.listed, walked.published, walked.ended) == (3, 0, True)
        assert _held(committed_app) == held
        assert _walks(committed_app) == 2

    def test_it_tells_its_end_after_its_last_publication(
        self,
        committed_app: Flask,
        home: Path,
        walker: Walker,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Pilot counts a publication to the walk whose end comes next. The
        second walk publishes in both its turns: a file that grew, and two
        read under an older version of the collector's."""

        def collected() -> list[datetime]:
            return [each["collected_at"] for each in _held(committed_app).values()]

        with monkeypatch.context() as older:
            _read_under(older, OLDER)
            walker.walk()
        before = collected()
        _grown(_file(home, RECIPES))

        walked = walker.walk()

        assert (walked.published, walked.waiting) == (3, 0)
        first, second = _ends(committed_app)
        assert max(before) <= first < min(collected())
        assert max(collected()) <= second

    def test_a_new_file_and_a_changed_one_are_published_and_the_rest_left(
        self, committed_app: Flask, home: Path, walker: Walker
    ) -> None:
        """A file that grew, one at the same size at another time, and one
        the home did not have: each is published whole."""
        walker.walk()
        before = _held(committed_app)
        _grown(_file(home, RECIPES))
        _aged(_file(home, SCALER), minutes=3)
        _copied(home)

        walked = walker.walk()

        assert walked.published == 3
        held = _held(committed_app)
        assert held[RIDES] == before[RIDES]
        for name in (RECIPES, SCALER):
            assert held[name]["stands"] == _stands(_file(home, name))
            assert held[name]["stands"] != before[name]["stands"]
            assert held[name]["replayed_size"] == held[name]["stands"][0]
        assert held[TOURS]["stands"] == _stands(_path(home, TOURS, "-work-BikeLog"))
        assert _calls(committed_app, TOURS) == _calls(committed_app, RIDES)

    def test_a_file_that_lost_its_end_is_published_as_it_stands(
        self, committed_app: Flask, home: Path, walker: Walker
    ) -> None:
        walker.walk()
        calls = _calls(committed_app, RIDES)
        path = _file(home, RIDES)
        lines = path.read_bytes().splitlines(keepends=True)
        kept = next(
            place
            for place, line in enumerate(lines)
            if json.loads(line)["type"] == "assistant"
        )
        path.write_bytes(b"".join(lines[: kept + 1]))

        walked = walker.walk()

        assert walked.published == 1
        assert _held(committed_app)[RIDES]["stands"] == _stands(path)
        assert 1 == _calls(committed_app, RIDES) < calls

    def test_what_pilot_holds_and_the_home_lacks_is_left_alone(
        self, committed_app: Flask, home: Path, walker: Walker
    ) -> None:
        walker.walk()
        held = _held(committed_app)
        _file(home, SCALER).unlink()
        _file(home, RIDES).unlink()

        walked = walker.walk()

        assert (walked.listed, walked.published, walked.ended) == (1, 0, True)
        assert _held(committed_app) == held

    def test_no_symlink_is_published(
        self, committed_app: Flask, home: Path, walker: Walker
    ) -> None:
        linked = _path(home, TOURS, "-work-BikeLog")
        linked.symlink_to(_file(home, RIDES))

        walked = walker.walk()

        assert walked.published == 3
        assert set(_held(committed_app)) == SCENARIOS

    def test_the_walks_interval_is_the_one_the_inventory_hands_over(
        self, committed_app: Flask, walker: Walker
    ) -> None:
        _configure(committed_app, interval=7.5)

        walker.walk()

        assert walker.interval == 7.5


class TestAWalksOrder:
    def test_the_changed_come_first_then_the_behind_each_newest_first(
        self,
        committed_app: Flask,
        home: Path,
        walker: Walker,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Every transcript was read under an older version of the
        collector's, and two files are new, both changed longer ago than
        any of those."""
        with monkeypatch.context() as older:
            _read_under(older, OLDER)
            walker.walk()
        assert {each["collector"] for each in _held(committed_app).values()} == {OLDER}
        files = {name: _file(home, name) for name in SCENARIOS}
        new, newer = f"{TOURS}/a1", f"{TOURS}/a2"
        _aged(_copied(home, new, of=SCALER), minutes=60 * 24 * 30)
        _aged(_copied(home, newer, of=SCALER), minutes=60 * 24 * 29)

        walked = walker.walk()

        assert (walked.published, walked.waiting) == (5, 0)
        behind = sorted(files, key=lambda name: _stands(files[name])[1], reverse=True)
        assert _in_order(committed_app) == [newer, new, *behind]
        assert {each["collector"] for each in _held(committed_app).values()} == {
            pilot_collector.VERSION
        }

    def test_the_behind_wait_for_the_next_walk_once_the_interval_has_passed(
        self,
        committed_app: Flask,
        home: Path,
        walker: Walker,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with monkeypatch.context() as older:
            _read_under(older, OLDER)
            walker.walk()
        _copied(home)
        _configure(committed_app, interval=0.000_001)

        walked = walker.walk()

        assert (walked.published, walked.waiting, walked.ended) == (1, 3, True)
        held = _held(committed_app)
        assert held[TOURS]["collector"] == pilot_collector.VERSION
        assert {held[name]["collector"] for name in SCENARIOS} == {OLDER}
        assert _walks(committed_app) == 2

        _configure(committed_app, interval=30.0)
        walked = walker.walk()

        assert (walked.published, walked.waiting) == (3, 0)
        assert {each["collector"] for each in _held(committed_app).values()} == {
            pilot_collector.VERSION
        }


class TestTheReplayAtRest:
    @pytest.fixture
    def appended(
        self, committed_app: Flask, pilot_url: str, home: Path, walker: Walker
    ) -> Path:
        """A transcript Pilot holds with an appended publication since its
        last whole one, its file unchanged for eleven minutes: the file grew
        by a line that is no fact's, and the call carries nothing."""
        walker.walk()
        path = _file(home, RIDES)
        whole = reader.read(transcript(home / "projects", path), walker._settings)
        _grown(path)
        _aged(path, minutes=11)
        size, at = _stands(path)
        call = whole.model_dump(mode="json", exclude_none=True) | {
            "file_size": size,
            "file_modified_at": at.isoformat(),
            "launches": [],
            "calls": [],
            "appended": {
                "builds_on": {
                    "file_size": whole.file_size,
                    "file_modified_at": whole.file_modified_at.isoformat(),
                    "collector": pilot_collector.VERSION,
                },
                "boundary": {
                    "call": len(whole.calls) + 1,
                    "launch": len(whole.launches) + 1,
                    "prompt": sum(len(each.prompts) for each in whole.launches) + 1,
                    "compaction": 1,
                },
            },
        }
        answer = httpx.post(
            f"{pilot_url}/api/collector/publications",
            json=call,
            headers=collector_headers(),
        )
        assert answer.status_code == 204, answer.text
        held = _held(committed_app)[RIDES]
        assert held["replayed_size"] == whole.file_size < held["stands"][0] == size
        return path

    def test_it_waits_while_the_file_has_not_stood_the_settling_time(
        self, committed_app: Flask, appended: Path, walker: Walker
    ) -> None:
        _configure(committed_app, settling=3600.0)
        held = _held(committed_app)

        walked = walker.walk()

        assert walked.published == 0
        assert _held(committed_app) == held

    def test_a_settled_file_is_published_whole_once(
        self, committed_app: Flask, appended: Path, walker: Walker
    ) -> None:
        _configure(committed_app, settling=600.0)
        calls = _calls(committed_app, RIDES)

        walked = walker.walk()

        assert walked.published == 1
        held = _held(committed_app)[RIDES]
        assert held["replayed_size"] == held["stands"][0] == appended.stat().st_size
        assert _calls(committed_app, RIDES) == calls
        assert walker.walk().published == 0


class TestWhatAWalkSetsAside:
    def test_a_file_it_cannot_read_is_logged_once_as_it_stands(
        self,
        committed_app: Flask,
        home: Path,
        walker: Walker,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        nowhere = _path(home, TOURS, "-work-BikeLog")
        nowhere.write_bytes(b'{"type": "summary", "summary": "Tours"}\n')
        torn = _path(home, f"{TOURS}/a1", "-work-BikeLog")
        torn.parent.mkdir(parents=True)
        torn.write_bytes(b'{"type": "user"\n')

        with caplog.at_level(logging.WARNING, LOGGER):
            walks = [walker.walk(), walker.walk()]

        assert [(walk.published, walk.set_aside) for walk in walks] == [(3, 2), (0, 0)]
        assert all(walk.ended for walk in walks)
        assert sorted(_set_aside(caplog)) == [
            f"The transcript {TOURS}, {nowhere}, is set aside until its file"
            " changes: it cannot be read: no line names a working directory",
            f"The transcript {TOURS}/a1, {torn}, is set aside until its file"
            " changes: it cannot be read: line 1 is not a line the collector"
            " reads: JSONDecodeError: Expecting ',' delimiter: line 1 column 16"
            " (char 15)",
        ]
        assert set(_held(committed_app)) == SCENARIOS

    def test_it_is_taken_again_once_its_file_changes(
        self,
        committed_app: Flask,
        home: Path,
        walker: Walker,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        path = _path(home, TOURS, "-work-BikeLog")
        path.write_bytes(b'{"type": "summary", "summary": "Tours"}\n')

        with caplog.at_level(logging.WARNING, LOGGER):
            walker.walk()
            _grown(path)
            again = walker.walk()
            shutil.copyfile(_file(home, RIDES), path)
            readable = walker.walk()

        assert (again.published, again.set_aside) == (0, 1)
        assert (readable.published, readable.set_aside) == (1, 0)
        assert len(_set_aside(caplog)) == 2
        assert TOURS in _held(committed_app)

    def test_a_file_that_cannot_be_opened_costs_the_walk_that_transcript_alone(
        self,
        committed_app: Flask,
        home: Path,
        walker: Walker,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A folder stands where a result says its output was saved."""
        [saved] = (_file(home, RECIPES).with_suffix("") / "tool-results").glob(
            "mcp-*.txt"
        )
        saved.unlink()
        saved.mkdir()

        with caplog.at_level(logging.WARNING, LOGGER):
            walked = walker.walk()

        assert (walked.published, walked.set_aside, walked.ended) == (2, 1, True)
        assert _set_aside(caplog) == [
            f"The transcript {RECIPES}, {_file(home, RECIPES)}, is set aside until"
            " its file changes: it cannot be read: [Errno 21] Is a directory:"
            f" '{saved}'"
        ]
        assert set(_held(committed_app)) == {SCALER, RIDES}

    @pytest.mark.parametrize(
        ("spoil", "raised"),
        [
            (
                _directory_a_number,
                "TypeError: argument should be a str or an os.PathLike object",
            ),
            (
                _tool_with_no_name,
                "AttributeError: 'NoneType' object has no attribute 'split'",
            ),
            (
                _line_nested_past_reading,
                "RecursionError: maximum recursion depth exceeded",
            ),
        ],
        ids=["a directory that is a number", "a tool with no name", "a nested line"],
    )
    def test_a_file_the_reader_raises_on_costs_the_walk_that_transcript_alone(
        self,
        committed_app: Flask,
        home: Path,
        walker: Walker,
        caplog: pytest.LogCaptureFixture,
        spoil: Any,
        raised: str,
    ) -> None:
        """The newest file of the home is one whose lines the reader does
        not refuse as unreadable."""
        path = _copied(home)
        spoil(path)

        with caplog.at_level(logging.WARNING, LOGGER):
            walks = [walker.walk(), walker.walk()]

        assert [(walk.published, walk.set_aside) for walk in walks] == [(3, 1), (0, 0)]
        assert all(walk.ended for walk in walks)
        [logged] = _set_aside(caplog)
        assert logged.startswith(
            f"The transcript {TOURS}, {path}, is set aside until its file changes:"
            f" reading it raised {raised}"
        )
        assert set(_held(committed_app)) == SCENARIOS

    def test_a_file_gone_since_the_walk_listed_it_is_no_longer_on_the_home(
        self,
        committed_app: Flask,
        home: Path,
        walker: Walker,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        def listed_then_gone(projects: Path) -> list[collector_home.Listed]:
            listed = collector_home.transcripts(projects)
            _file(home, RIDES).unlink()
            return listed

        monkeypatch.setattr(walk, "transcripts", listed_then_gone)

        with caplog.at_level(logging.WARNING, LOGGER):
            walked = walker.walk()

        assert (walked.listed, walked.published, walked.set_aside) == (3, 2, 0)
        assert walked.ended
        assert _set_aside(caplog) == []
        assert set(_held(committed_app)) == {RECIPES, SCALER}

    def test_a_publication_too_large_for_pilot_is_logged_and_the_walk_goes_on(
        self,
        committed_app: Flask,
        home: Path,
        walker: Walker,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Pilot's cap on a body stands between the two largest
        publications of the home."""
        sizes = sorted(
            len(
                reader.read(each.transcript, walker._settings).model_dump_json(
                    exclude_none=True
                )
            )
            for each in collector_home.transcripts(home / "projects")
        )
        committed_app.config["MAX_CONTENT_LENGTH"] = (sizes[-1] + sizes[-2]) // 2

        with caplog.at_level(logging.WARNING, LOGGER):
            walks = [walker.walk(), walker.walk()]
            _aged(_file(home, RECIPES), minutes=1)
            again = walker.walk()

        assert [(walk.published, walk.set_aside) for walk in walks] == [(2, 1), (0, 0)]
        assert all(walk.ended for walk in walks)
        assert (again.published, again.set_aside) == (0, 1)
        logged = _set_aside(caplog)
        assert len(logged) == 2
        assert logged[0].startswith(
            f"The transcript {RECIPES}, {_file(home, RECIPES)}, is set aside until"
            " its file changes: Pilot refused it with 413: "
        )
        assert set(_held(committed_app)) == {SCALER, RIDES}
        assert _walks(committed_app) == 3


class TestPilotsAnswers:
    def test_a_publication_that_does_not_validate_is_refused_with_its_faults(
        self, committed_app: Flask, pilot_url: str, home: Path, walker: Walker
    ) -> None:
        found = transcript(home / "projects", _file(home, SCALER))
        faulty = reader.read(found, walker._settings).model_copy(
            update={"environment": "ben-recipebox-51f0c2"}
        )

        with Pilot(pilot_url, COLLECTOR_TOKEN) as pilot:
            with pytest.raises(Refused) as refused:
                pilot.publish(faulty)

        assert str(refused.value).startswith("400: ")
        assert "a sub-agent's thread is hosted by no environment" in str(refused.value)
        assert _held(committed_app) == {}

    def test_a_walk_under_another_bearer_ends_at_its_first_call(
        self,
        committed_app: Flask,
        pilot_url: str,
        home: Path,
        stop: threading.Event,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with Pilot(pilot_url, "another-invented-token") as pilot:
            walker = Walker(pilot, _settings(pilot_url, home), stop)
            with caplog.at_level(logging.WARNING, LOGGER):
                walked = walker.walk()

            with pytest.raises(NotAdmitted):
                pilot.end_walk()

        assert (walked.listed, walked.published, walked.ended) == (0, 0, False)
        assert [
            (record.levelname, record.getMessage())
            for record in caplog.records
            if record.name == LOGGER
        ] == [
            (
                "ERROR",
                "The walk ended early: Pilot does not take the collector's bearer",
            )
        ]
        assert _held(committed_app) == {}
        assert _walks(committed_app) == 0

    def test_a_walk_in_a_protocol_version_pilot_does_not_take_ends_at_its_first_call(
        self,
        committed_app: Flask,
        walker: Walker,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(publication_service, "COLLECTOR_PROTOCOL_MIN", 2)
        monkeypatch.setattr(publication_service, "COLLECTOR_PROTOCOL_MAX", 3)

        with caplog.at_level(logging.WARNING, LOGGER):
            walked = walker.walk()

        assert (walked.published, walked.ended) == (0, False)
        assert [
            (record.levelname, record.getMessage())
            for record in caplog.records
            if record.name == LOGGER
        ] == [
            (
                "ERROR",
                "The walk ended early: Pilot takes the protocol versions 2 to 3,"
                " and the collector speaks 1",
            )
        ]
        assert _held(committed_app) == {}
        assert _walks(committed_app) == 0

    def test_the_walk_after_one_pilot_did_not_admit_starts_over(
        self,
        committed_app: Flask,
        walker: Walker,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with monkeypatch.context() as newer:
            newer.setattr(publication_service, "COLLECTOR_PROTOCOL_MIN", 2)
            newer.setattr(publication_service, "COLLECTOR_PROTOCOL_MAX", 3)
            walker.walk()

        walked = walker.walk()

        assert (walked.published, walked.ended) == (3, True)
        assert set(_held(committed_app)) == SCENARIOS


class TestTheWalksRhythm:
    def test_a_walk_told_to_stop_publishes_no_further_and_tells_no_end(
        self, committed_app: Flask, walker: Walker, stop: threading.Event
    ) -> None:
        stop.set()

        walked = walker.walk()
        walker.run()

        assert (walked.listed, walked.published, walked.ended) == (3, 0, False)
        assert _held(committed_app) == {}
        assert _walks(committed_app) == 0

    def test_it_walks_at_the_inventorys_interval_until_it_is_stopped(
        self, committed_app: Flask, home: Path, walker: Walker, stop: threading.Event
    ) -> None:
        """One thread walks: a walk begins once the one before it has
        ended, so no two run at a time."""
        _configure(committed_app, interval=0.05)
        walking = threading.Thread(target=walker.run, daemon=True)
        walking.start()
        try:
            _await(lambda: _walks(committed_app) >= 2)
            assert set(_held(committed_app)) == SCENARIOS
            _copied(home)
            _await(lambda: TOURS in _held(committed_app))
        finally:
            stop.set()
            walking.join(timeout=10)

        assert not walking.is_alive()
        walks = _walks(committed_app)
        time.sleep(0.2)
        assert _walks(committed_app) == walks

    def test_it_waits_out_what_a_walk_left_of_the_interval(
        self, committed_app: Flask, pilot_url: str, home: Path
    ) -> None:
        """A walk begins the interval after the one before it began."""
        _configure(committed_app, interval=45.0)
        stop = _Stop()
        with Pilot(pilot_url, COLLECTOR_TOKEN) as pilot:
            walker = Walker(pilot, _settings(pilot_url, home), stop)
            walking = threading.Thread(target=walker.run, daemon=True)
            began = time.perf_counter()
            walking.start()
            try:
                _await(lambda: stop.waits)
                took = time.perf_counter() - began
            finally:
                stop.set()
                walking.join(timeout=10)

        assert not walking.is_alive()
        wait = stop.waits[0]
        assert wait is not None
        assert 45.0 - took <= wait < 45.0
        assert _walks(committed_app) == 1


def _await(holds: Any, seconds: float = 10.0) -> None:
    """Wait until `holds` answers true."""
    until = time.perf_counter() + seconds
    while not holds():
        assert time.perf_counter() < until, "it did not come to hold"
        time.sleep(0.02)
