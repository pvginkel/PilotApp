"""The collector's walk against Pilot's routes (F152.2): a home of the
scenario's transcript files, walked by the collector's own code over HTTP,
and what Pilot's record then holds, of a file published whole and of one
that grew, published appended (F152.15)."""

import json
import logging
import os
import re
import shutil
import threading
import time
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pilot_collector
import pytest
from dependency_injector import providers
from flask import Flask
from pilot_collection.publication import PublicationSchema
from pilot_collector import home as collector_home
from pilot_collector import reader, walk
from pilot_collector.home import transcript
from pilot_collector.pilot import NotAdmitted, NotAppendable, Pilot, Refused
from pilot_collector.settings import Settings
from pilot_collector.walk import Walker
from pilot_scenario import SCENARIO, Builder, Scenario, script
from pilot_scenario.transcript import stamp
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import aliased
from werkzeug.serving import make_server

from app.extensions import db
from app.models import (
    Call,
    Compaction,
    ComponentVersion,
    Event,
    HookRun,
    Launch,
    LaunchComponent,
    Prompt,
    ToolCall,
    Transcript,
    Walk,
)
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
PUBLICATIONS = "app.services.publication_service"
"""The logger of Pilot's side of a publication."""


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


def _settings(pilot_url: str, home: Path, **given: Any) -> Settings:
    return Settings(
        COLLECTOR_PILOT_URL=pilot_url,
        COLLECTOR_TOKEN=COLLECTOR_TOKEN,
        COLLECTOR_HOME=home,
        **given,
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
        the home did not have: the first is published appended, the others
        whole (F152.17)."""
        walker.walk()
        before = _held(committed_app)
        _grown(_file(home, RECIPES))
        _aged(_file(home, SCALER), minutes=3)
        _copied(home)

        walked = walker.walk()

        assert (walked.published, walked.appended) == (3, 1)
        held = _held(committed_app)
        assert held[RIDES] == before[RIDES]
        for name in (RECIPES, SCALER):
            assert held[name]["stands"] == _stands(_file(home, name))
            assert held[name]["stands"] != before[name]["stands"]
        assert held[RECIPES]["replayed_size"] == before[RECIPES]["stands"][0]
        assert held[SCALER]["replayed_size"] == held[SCALER]["stands"][0]
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
        whole = reader.read(
            transcript(home / "projects", path), walker._settings
        ).publication
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
                reader.read(
                    each.transcript, walker._settings
                ).publication.model_dump_json(exclude_none=True)
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
        faulty = reader.read(found, walker._settings).publication.model_copy(
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
        monkeypatch.setattr(publication_service, "COLLECTOR_PROTOCOL_MIN", 3)
        monkeypatch.setattr(publication_service, "COLLECTOR_PROTOCOL_MAX", 4)

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
                "The walk ended early: Pilot takes the protocol versions 3 to 4,"
                " and the collector speaks 2",
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
            newer.setattr(publication_service, "COLLECTOR_PROTOCOL_MIN", 3)
            newer.setattr(publication_service, "COLLECTOR_PROTOCOL_MAX", 4)
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


def _whole_instead(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Why the walk published a transcript whole that it held a carry of:
    each of its lines' reasons."""
    told = "is published whole, not from its boundary on: "
    return [
        record.getMessage().partition(told)[2]
        for record in caplog.records
        if record.name == LOGGER and told in record.getMessage()
    ]


def _replays(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Pilot's lines for a replay at rest that wrote a row."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == PUBLICATIONS and "replay at rest" in record.getMessage()
    ]


def _sent(walker: Walker, monkeypatch: pytest.MonkeyPatch) -> list[PublicationSchema]:
    """The publications the walker sends Pilot from here on, in their
    order, refused or not."""
    sent: list[PublicationSchema] = []
    publish = walker._pilot.publish

    def kept(publication: PublicationSchema) -> None:
        sent.append(publication)
        publish(publication)

    monkeypatch.setattr(walker._pilot, "publish", kept)
    return sent


def _resumed(lines: list[bytes]) -> list[bytes]:
    """The lines a second process of the conversation writes an hour after
    the first wrote `lines`: the same lines, every id of a line, a response
    and a request in them another."""
    read = [json.loads(line) for line in lines]
    ids = {line["uuid"] for line in read if "uuid" in line}
    for line in read:
        if line["type"] == "api-request":
            ids.add(line["id"])
        if line["type"] == "assistant":
            ids.add(line["message"]["id"])
            ids.update(
                block["id"]
                for block in line["message"]["content"]
                if block["type"] == "tool_use"
            )

    def later(value: Any, key: str | None = None) -> Any:
        if isinstance(value, dict):
            return {name: later(under, name) for name, under in value.items()}
        if isinstance(value, list):
            return [later(under) for under in value]
        if key == "timestamp":
            at = datetime.fromisoformat(value) + timedelta(hours=1)
            return at.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if isinstance(value, str) and value in ids:
            return f"{value}-resumed"
        return value

    return [json.dumps(later(line)).encode() + b"\n" for line in read]


def _added(path: Path, *lines: bytes) -> None:
    with path.open("ab") as file:
        file.write(b"".join(lines))


def _line(**fields: Any) -> bytes:
    """A line of a thread's chain, as Claude Code writes one."""
    return json.dumps(fields).encode() + b"\n"


def _thread(record: DbSession, name: str) -> Transcript:
    session_id, _, agent_id = name.partition("/")
    return record.scalars(
        select(Transcript).where(
            Transcript.session_id == session_id,
            Transcript.agent_id.is_not_distinct_from(agent_id or None),
        )
    ).one()


def _row(row: Any, **places: Any) -> dict[str, Any]:
    """A row's facts with no id of Pilot's: `places` stand for those that
    name another row."""
    facts = {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
        if column.name not in ("id", "transcript_id")
    }
    return facts | places


def _facts(app: Flask, name: str) -> dict[str, Any]:
    """What Pilot holds of the transcript of that name, in the file's
    order, each row named by its place: the same for two transcripts whose
    files hold the same lines. A Call's Launch is named by its place among
    the transcript's own, and left out where it is its main thread's: that
    one is read from another file."""
    with _record(app) as record:
        thread = _thread(record, name)
        launches = record.scalars(
            select(Launch).where(Launch.transcript_id == thread.id).order_by(Launch.id)
        ).all()
        launch = {row.id: place for place, row in enumerate(launches, start=1)}
        components = record.execute(
            select(
                LaunchComponent.launch_id,
                LaunchComponent.component_code,
                ComponentVersion.version,
            )
            .join(
                ComponentVersion,
                ComponentVersion.id == LaunchComponent.component_version_id,
            )
            .where(LaunchComponent.launch_id.in_(list(launch)))
        ).all()
        prompts = record.scalars(
            select(Prompt).where(Prompt.transcript_id == thread.id).order_by(Prompt.id)
        ).all()
        prompt = {row.id: place for place, row in enumerate(prompts, start=1)}
        hook_runs = record.scalars(
            select(HookRun)
            .where(HookRun.prompt_id.in_(list(prompt)))
            .order_by(HookRun.id)
        ).all()
        compactions = record.scalars(
            select(Compaction)
            .where(Compaction.transcript_id == thread.id)
            .order_by(Compaction.id)
        ).all()
        compaction = {row.id: place for place, row in enumerate(compactions, start=1)}
        calls = record.scalars(
            select(Call).where(Call.transcript_id == thread.id).order_by(Call.position)
        ).all()
        call = {row.id: row.position for row in calls}
        tool_calls = record.scalars(
            select(ToolCall)
            .where(ToolCall.transcript_id == thread.id)
            .order_by(ToolCall.id)
        ).all()
        events = record.scalars(
            select(Event)
            .join(Call, Call.id == Event.call_id)
            .where(Call.transcript_id == thread.id)
            .order_by(Event.id)
        ).all()
        return {
            "thread": (
                thread.working_directory,
                thread.repository_id,
                thread.environment_id,
            ),
            "launches": [_row(row) for row in launches],
            "components": sorted(
                (launch[launch_id], code, version)
                for launch_id, code, version in components
            ),
            "prompts": [_row(row, launch_id=launch[row.launch_id]) for row in prompts],
            "hook_runs": sorted(
                (_row(row, prompt_id=prompt[row.prompt_id]) for row in hook_runs),
                key=lambda run: run["prompt_id"],
            ),
            "compactions": [_row(row) for row in compactions],
            "calls": [
                _row(
                    row,
                    prompt_id=row.prompt_id and prompt[row.prompt_id],
                    predecessor_id=row.predecessor_id and call[row.predecessor_id],
                    compaction_id=row.compaction_id and compaction[row.compaction_id],
                    launch_id=launch.get(row.launch_id),
                )
                for row in calls
            ],
            "tool_calls": sorted(
                (_row(row, call_id=call[row.call_id]) for row in tool_calls),
                key=lambda asked: asked["call_id"],
            ),
            "events": sorted(
                (_row(row, call_id=call[row.call_id]) for row in events),
                key=lambda event: (event["call_id"], event["at"]),
            ),
        }


def _nested() -> Scenario:
    """A conversation whose main thread's call starts `tracing`, whose own
    calls start `counting` and then a fork the script has no thread of."""
    tracing = script.SubAgent(
        name="tracing",
        type="general-purpose",
        steps=(
            script.Call(
                at=8,
                tokens=script.Tokens(input=40, output=6),
                tools=(
                    script.ToolUse(
                        "Agent",
                        "Count the spokes",
                        took=10,
                        characters=90,
                        spawns="counting",
                    ),
                ),
            ),
            script.Call(
                at=22,
                tokens=script.Tokens(cache_read=40, output=3),
                tools=(
                    script.ToolUse("Agent", "Try the twill", took=9, characters=60),
                ),
            ),
        ),
    )
    counting = script.SubAgent(
        name="counting",
        type="Explore",
        steps=(script.Call(at=12, tokens=script.Tokens(input=30, output=2)),),
    )
    agent = script.ToolUse(
        "Agent", "Trace the warp", took=40, characters=200, spawns="tracing"
    )
    first = script.Prompt(
        at=0,
        source="typed",
        characters=20,
        steps=(
            script.Call(at=4, tokens=script.Tokens(input=20, output=5), tools=(agent,)),
        ),
    )
    return Scenario(
        name="nested",
        people=("cleo",),
        projects=(),
        kinds=(),
        units=(),
        sessions=(
            script.Session(
                name="nested",
                directory="/tmp/looms",
                person="cleo",
                launches=(
                    script.Launch(
                        versions=(("claude-code", "2.1.317"),), prompts=(first,)
                    ),
                ),
                sub_agents=(tracing, counting),
            ),
        ),
    )


FORK = "f0f1f2f3f4f5f6f70"
"""Claude Code's id of the fork `tracing` started."""


def _forked(home: Path, parent: Path, spawning: str, kind: str) -> None:
    """A sub-agent's file and record beside its parent's, started by the
    call `spawning` of the parent's, its record naming its type `kind`: a
    fork's, the parent's lines copied through the one that holds that call,
    then the fork's own, the call's result and a Call."""
    copies: list[dict[str, Any]] = []
    for line in _lines(parent):
        copies.append(line | {"agentId": FORK})
        content = line.get("message", {}).get("content")
        if line["type"] == "assistant" and any(
            block["type"] == "tool_use" and block["id"] == spawning for block in content
        ):
            break
    spawned = copies[-1]
    at = datetime.fromisoformat(spawned["timestamp"])
    returned = {
        "parentUuid": spawned["uuid"],
        "isSidechain": True,
        "agentId": FORK,
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": spawning, "content": "Twill."}
            ],
        },
        "uuid": f"{FORK}-returned",
        "timestamp": stamp(at + timedelta(seconds=1)),
        "cwd": spawned["cwd"],
        "sessionId": spawned["sessionId"],
        "version": spawned["version"],
    }
    own = {name: fact for name, fact in spawned.items() if name != "requestRef"} | {
        "parentUuid": returned["uuid"],
        "uuid": f"{FORK}-own",
        "timestamp": stamp(at + timedelta(seconds=3)),
        "message": spawned["message"]
        | {"id": "msg_fork", "content": [{"type": "text", "text": "Twill it is."}]},
    }
    path = parent.with_name(f"agent-{FORK}.jsonl")
    _written(path, [*copies, returned, own])
    record = {"agentType": kind, "description": "Try the twill", "toolUseId": spawning}
    path.with_name(f"agent-{FORK}.meta.json").write_text(json.dumps(record))


def _parents(app: Flask, session_id: str) -> dict[str, tuple[str | None, str] | None]:
    """Each sub-agent's thread of that conversation Pilot holds, by its
    sub-agent's id: the thread of the Tool Call Pilot joined it to, by its
    sub-agent's id, none for a main thread, and the call's `tool_use_id`;
    none where Pilot joined it to none."""
    holder = aliased(Transcript)
    with _record(app) as record:
        rows = record.execute(
            select(Transcript.agent_id, holder.agent_id, ToolCall.tool_use_id)
            .outerjoin(ToolCall, ToolCall.id == Transcript.spawned_by_id)
            .outerjoin(holder, holder.id == ToolCall.transcript_id)
            .where(
                Transcript.session_id == session_id, Transcript.agent_id.is_not(None)
            )
        ).all()
    return {
        agent: None if tool_use_id is None else (holder_agent, tool_use_id)
        for agent, holder_agent, tool_use_id in rows
    }


class TestASubAgentsSpawningCall:
    """F152.5: a sub-agent's spawning call, as its record names it."""

    @pytest.mark.parametrize(
        ("kind", "copied"),
        [("fork", False), ("general-purpose", True)],
        ids=["a fork", "a sub-agent whose copies are its own"],
    )
    def test_each_is_joined_to_the_call_that_started_it_in_one_thread(
        self,
        committed_app: Flask,
        home: Path,
        walker: Walker,
        kind: str,
        copied: bool,
    ) -> None:
        """A nested sub-agent's is its parent sub-agent's call; a fork's
        copies of its parent's lines are no facts of its, so a call it copied
        stands in its parent's thread alone. Read as its own, the copy is a
        second thread holding it, and Pilot joins no sub-agent to it."""
        builder = Builder(_nested(), UNTIL)
        builder.write(home)
        main, tracing, counting = builder.publications()
        a1 = main["calls"][0]["tool_calls"][0]["tool_use_id"]
        b1, f1 = (
            asked["tool_use_id"]
            for call in tracing["calls"]
            for asked in call["tool_calls"]
        )
        parent = home / next(
            file.path for file in builder.files() if tracing["agent_id"] in file.path
        )
        _forked(home, parent, f1, kind)

        walker.walk()

        assert _parents(committed_app, main["session_id"]) == {
            tracing["agent_id"]: (None, a1),
            counting["agent_id"]: None if copied else (tracing["agent_id"], b1),
            FORK: (tracing["agent_id"], f1),
        }
        calls = _calls_of(committed_app, f"{main['session_id']}/{FORK}")
        assert calls == (3 if copied else 1)


def _calls_of(app: Flask, name: str) -> int:
    """How many Calls Pilot holds of the transcript of that name."""
    with _record(app) as record:
        thread = _thread(record, name)
        return record.scalar(
            select(func.count())
            .select_from(Call)
            .where(Call.transcript_id == thread.id)
        )


class TestAFileThatGrows:
    """F152.15, F152.16."""

    @pytest.mark.parametrize(
        ("name", "read_whole"),
        [(RECIPES, 0), (SCALER, 0), (RIDES, 6)],
        ids=["a main thread", "a sub-agent's thread", "a thread that goes back"],
    )
    def test_grown_a_line_at_a_time_pilot_holds_what_one_whole_publication_gives(
        self,
        committed_app: Flask,
        home: Path,
        walker: Walker,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        name: str,
        read_whole: int,
    ) -> None:
        """The file is published at every line it grows by, a main thread's
        through a second process's lines. Once Pilot holds it every step is
        appended, the size at its last whole publication staying put; the
        steps published whole instead are those from a line that goes back
        in the chain, behind the boundary, until the boundary has passed
        it. What Pilot then holds is what the whole file's publication
        gives: its replay at rest writes no row, and the same lines under
        another id, published whole, are held alike."""
        path = _file(home, name)
        lines = path.read_bytes().splitlines(keepends=True)
        main = "/" not in name
        if main:
            lines += _resumed(lines)
        path.write_bytes(b"")
        sent = _sent(walker, monkeypatch)
        replayed: int | None = None
        last: str | None = None
        behind = False
        steps = {"appended": 0, "whole instead": 0}

        with caplog.at_level(logging.INFO, LOGGER):
            walker.walk()
            for line in lines:
                _added(path, line)
                added = json.loads(line)
                follows, last = last, added.get("uuid", last)
                del sent[:]

                walked = walker.walk()

                held = _held(committed_app).get(name)
                if replayed is None:
                    if held is not None:
                        assert (walked.published, walked.appended) == (1, 0)
                        replayed = held["replayed_size"]
                    continue
                assert held is not None and held["stands"] == _stands(path)
                assert walked.published == 1
                if walked.appended:
                    behind = False
                    steps["appended"] += 1
                    assert [each.appended is not None for each in sent] == [True]
                else:
                    assert behind or added["parentUuid"] not in (None, follows)
                    behind = True
                    steps["whole instead"] += 1
                    assert [each.appended is not None for each in sent] == [False]
                    replayed = held["stands"][0]
                assert held["replayed_size"] == replayed
        assert steps == {
            "appended": len(lines) - read_whole - steps_before_the_first(lines),
            "whole instead": read_whole,
        }
        assert set(_whole_instead(caplog)) <= {
            "a line follows one before its boundary that is not the last there"
        }
        assert len(_whole_instead(caplog)) == read_whole

        grown = _facts(committed_app, name)
        assert len(grown["launches"]) == (2 if main else 0)
        crossed = [
            row["compaction_id"] for row in grown["calls"] if row["compaction_id"]
        ]
        assert crossed == ([1, 2] if name == RECIPES else [])
        assert len(grown["compactions"]) == len(crossed)
        assert all(
            row["predecessor_id"] for row in grown["calls"] if row["compaction_id"]
        )
        assert [row["kind_code"] for row in grown["events"]] == (
            ["api_retry"] * 2 if name == RECIPES else []
        )
        assert [
            (run["prompt_id"], run["command"], run["failed"])
            for run in grown["hook_runs"]
        ] == {
            RECIPES: [(1, "tidy_up.sh", False), (2, "tidy_up.sh", False)],
            SCALER: [],
            RIDES: [
                (1, "log_ride.sh", False),
                (1, "sync_notes.sh", True),
                (5, "log_ride.sh", False),
                (5, "sync_notes.sh", True),
            ],
        }[name]
        assert (
            sorted(
                row["denial_kind_code"]
                for row in grown["tool_calls"]
                if row["denial_kind_code"]
            )
            == {RECIPES: [], SCALER: ["hook", "rule"], RIDES: ["person"] * 2}[name]
        )
        assert replayed is not None and replayed < path.stat().st_size
        _configure(committed_app, settling=0.0)
        with caplog.at_level(logging.WARNING, PUBLICATIONS):
            walked = walker.walk()
        assert (walked.published, walked.appended) == (1, 0)
        assert _replays(caplog) == []
        assert _held(committed_app)[name]["replayed_size"] == path.stat().st_size
        assert _facts(committed_app, name) == grown

        other = f"{TOURS}/a1" if not main else TOURS
        _path(home, other, "-work-BikeLog").parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, _path(home, other, "-work-BikeLog"))
        assert walker.walk().published == 1
        assert _facts(committed_app, other) == grown

    def test_the_walks_line_counts_the_appended_among_the_published(
        self,
        committed_app: Flask,
        home: Path,
        walker: Walker,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        walker.walk()
        _grown(_file(home, RIDES))
        _copied(home)

        with caplog.at_level(logging.INFO, LOGGER):
            walker.walk()

        assert (
            "A walk over 4 transcripts: 2 published, 1 of them appended, 0 set aside,"
            " 0 left for the next walk, in "
        ) in caplog.text

    def test_a_sub_agents_thread_that_grew_is_published_appended(
        self,
        committed_app: Flask,
        home: Path,
        walker: Walker,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        walker.walk()
        before = _held(committed_app)[SCALER]
        calls = len(_facts(committed_app, SCALER)["calls"])
        sent = _sent(walker, monkeypatch)
        _grown(_file(home, SCALER))

        walked = walker.walk()

        assert (walked.published, walked.appended) == (1, 1)
        (publication,) = sent
        assert publication.appended is not None
        assert publication.appended.builds_on.model_dump() == {
            "file_size": before["stands"][0],
            "file_modified_at": before["stands"][1],
            "collector": pilot_collector.VERSION,
        }
        assert publication.appended.boundary.model_dump() == {
            "call": calls,
            "launch": 1,
            "prompt": 1,
            "compaction": 1,
        }
        assert publication.launches == []
        held = _held(committed_app)[SCALER]
        assert held["stands"] == _stands(_file(home, SCALER))
        assert held["replayed_size"] == before["stands"][0]


def steps_before_the_first(lines: list[bytes]) -> int:
    """How many of a file's first lines it takes before the collector reads
    it, one that names a working directory among them, and so before its
    first publication, which is whole."""
    return next(
        place for place, line in enumerate(lines, start=1) if "cwd" in json.loads(line)
    )


class TestAFilePublishedWholeInstead:
    """Where a transcript the collector holds a carry of is published whole
    in the same walk (F152.15, F152.17)."""

    def test_a_collector_that_restarted_holds_no_carry(
        self,
        committed_app: Flask,
        pilot_url: str,
        home: Path,
        walker: Walker,
        stop: threading.Event,
    ) -> None:
        walker.walk()
        _grown(_file(home, RIDES))

        walked = Walker(walker._pilot, _settings(pilot_url, home), stop).walk()

        assert (walked.published, walked.appended) == (1, 0)
        held = _held(committed_app)[RIDES]
        assert (
            held["replayed_size"] == held["stands"][0] == _stands(_file(home, RIDES))[0]
        )

    def test_a_carry_built_on_another_file_than_pilot_holds_is_not_used(
        self,
        committed_app: Flask,
        pilot_url: str,
        home: Path,
        walker: Walker,
        stop: threading.Event,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Another collector published the transcript in between."""
        path = _file(home, RIDES)
        walker.walk()
        _grown(path)
        Walker(walker._pilot, _settings(pilot_url, home), stop).walk()
        _grown(path)

        with caplog.at_level(logging.INFO, LOGGER):
            walked = walker.walk()

        assert (walked.published, walked.appended) == (1, 0)
        assert _whole_instead(caplog) == ["Pilot does not hold it as it was last read"]
        held = _held(committed_app)[RIDES]
        assert held["replayed_size"] == held["stands"][0] == _stands(path)[0]
        _grown(path)
        assert walker.walk().appended == 1

    def test_a_line_that_reaches_behind_the_boundary_makes_it_whole(
        self,
        committed_app: Flask,
        home: Path,
        walker: Walker,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A prompt typed after the conversation was taken back to its
        first line."""
        path = _file(home, RIDES)
        first = next(line for line in _lines(path) if "uuid" in line)
        walker.walk()
        prompts = len(_facts(committed_app, RIDES)["prompts"])
        _added(
            path,
            _line(
                type="user",
                uuid="b1c6a0de-52f7-4d3b-9a08-6e4f1d7c2a95",
                parentUuid=first["uuid"],
                timestamp="2026-11-12T09:40:00.000Z",
                cwd=first["cwd"],
                version=first["version"],
                promptSource="typed",
                message={"role": "user", "content": "Start over."},
            ),
        )

        with caplog.at_level(logging.INFO, LOGGER):
            walked = walker.walk()

        assert (walked.published, walked.appended) == (1, 0)
        assert _whole_instead(caplog) == [
            "a line follows one before its boundary that is not the last there"
        ]
        held = _held(committed_app)[RIDES]
        assert held["replayed_size"] == held["stands"][0] == _stands(path)[0]
        assert len(_facts(committed_app, RIDES)["prompts"]) == prompts + 1

    def test_a_result_for_a_request_behind_the_boundary_makes_it_whole(
        self,
        committed_app: Flask,
        home: Path,
        walker: Walker,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        path = _file(home, RIDES)
        walker.walk()
        asked = _facts(committed_app, RIDES)["tool_calls"][0]
        last = [line for line in _lines(path) if "uuid" in line][-1]
        assert asked["call_id"] < _calls(committed_app, RIDES)
        _added(
            path,
            _line(
                type="user",
                uuid="b1c6a0de-52f7-4d3b-9a08-6e4f1d7c2a95",
                parentUuid=last["uuid"],
                timestamp="2026-11-12T09:40:00.000Z",
                cwd=last["cwd"],
                version=last["version"],
                message={
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": asked["tool_use_id"],
                            "content": "Once more.",
                        }
                    ],
                },
            ),
        )

        with caplog.at_level(logging.INFO, LOGGER):
            walked = walker.walk()

        assert (walked.published, walked.appended) == (1, 0)
        assert _whole_instead(caplog) == [
            "a tool's result names a request no line from its boundary on makes"
        ]
        assert _facts(committed_app, RIDES)["tool_calls"][0] == asked

    def test_a_file_that_lost_its_end_no_longer_continues_its_carry(
        self,
        committed_app: Flask,
        home: Path,
        walker: Walker,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        path = _file(home, RIDES)
        walker.walk()
        calls = _calls(committed_app, RIDES)
        lines = path.read_bytes().splitlines(keepends=True)
        path.write_bytes(b"".join(lines[:-4]))

        with caplog.at_level(logging.INFO):
            walked = walker.walk()

        assert (walked.published, walked.appended) == (1, 0)
        assert _whole_instead(caplog) == [
            "its file is no larger than the one last read"
        ]
        lost = calls - _calls(committed_app, RIDES)
        assert lost > 0
        assert (
            f"Transcript {RIDES} no longer has {lost} of the calls Pilot held"
            in caplog.text
        )

    def test_a_file_at_the_same_size_at_another_time_no_longer_continues_it(
        self,
        committed_app: Flask,
        home: Path,
        walker: Walker,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        path = _file(home, RIDES)
        walker.walk()
        _aged(path, minutes=3)

        with caplog.at_level(logging.INFO, LOGGER):
            walked = walker.walk()

        assert (walked.published, walked.appended) == (1, 0)
        assert _whole_instead(caplog) == [
            "its file is no larger than the one last read"
        ]
        assert _held(committed_app)[RIDES]["stands"] == _stands(path)

    def test_a_file_with_other_bytes_before_its_old_end_is_followed(
        self,
        committed_app: Flask,
        home: Path,
        walker: Walker,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The last response's output tokens are other digits, and the file
        grew: Pilot then holds what the file says."""
        path = _file(home, RIDES)
        walker.walk()
        held = path.read_bytes()
        *_, counted = re.finditer(rb'"output_tokens": ?(\d+)', held)
        tokens = int(counted[1])
        other = int("7" * len(counted[1])) if tokens % 10 != 7 else tokens - 1
        assert len(str(other)) == len(counted[1])
        path.write_bytes(
            held[: counted.start(1)] + str(other).encode() + held[counted.end(1) :]
        )
        _grown(path)
        assert _facts(committed_app, RIDES)["calls"][-1]["output_tokens"] == tokens

        with caplog.at_level(logging.INFO, LOGGER):
            walked = walker.walk()

        assert (walked.published, walked.appended) == (1, 0)
        assert _whole_instead(caplog) == ["its file has other bytes before its old end"]
        assert _facts(committed_app, RIDES)["calls"][-1]["output_tokens"] == other
        held_now = _held(committed_app)[RIDES]
        assert held_now["replayed_size"] == held_now["stands"][0] == _stands(path)[0]

    def test_a_grown_file_the_reader_raises_on_is_read_whole_and_set_aside(
        self,
        committed_app: Flask,
        home: Path,
        walker: Walker,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        path = _file(home, RIDES)
        walker.walk()
        held = _held(committed_app)
        _line_nested_past_reading(path)

        with caplog.at_level(logging.INFO, LOGGER):
            walked = walker.walk()

        assert (walked.published, walked.set_aside, walked.ended) == (0, 1, True)
        (reason,) = _whole_instead(caplog)
        assert reason.startswith(
            "reading it from its boundary on raised RecursionError: "
        )
        (logged,) = _set_aside(caplog)
        assert logged.startswith(
            f"The transcript {RIDES}, {path}, is set aside until its file changes:"
            " reading it raised RecursionError: "
        )
        assert _held(committed_app) == held

    def test_an_appended_call_too_large_for_pilot_is_tried_whole_and_set_aside(
        self,
        committed_app: Flask,
        home: Path,
        walker: Walker,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        path = _file(home, RIDES)
        walker.walk()
        held = _held(committed_app)
        committed_app.config["MAX_CONTENT_LENGTH"] = 100
        _grown(path)

        with caplog.at_level(logging.INFO, LOGGER):
            walked = walker.walk()

        assert (walked.published, walked.set_aside, walked.ended) == (0, 1, True)
        (reason,) = _whole_instead(caplog)
        assert reason.startswith("Pilot refused it appended with 413: ")
        (logged,) = _set_aside(caplog)
        assert "Pilot refused it with 413: " in logged
        assert _held(committed_app) == held

        committed_app.config["MAX_CONTENT_LENGTH"] = None
        _grown(path)
        walked = walker.walk()

        assert (walked.published, walked.appended) == (1, 0)


class TestTheBoundarysPlaces:
    """The four places an appended call names, against Pilot's check of
    them: Pilot refuses a call whose first Launch or Prompt is another than
    the row it holds at the boundary's place, and the transcript is then
    published whole in the same walk."""

    @pytest.fixture
    def resumed(self, home: Path, walker: Walker) -> Path:
        """A main thread two processes wrote, the second still running and
        given one more prompt after its last response: Pilot holds it, the
        prompt taken appended."""
        path = _file(home, RIDES)
        lines = path.read_bytes().splitlines(keepends=True)
        path.write_bytes(b"".join(lines + _resumed(lines)[:-2]))
        walker.walk()
        last = [line for line in _lines(path) if "uuid" in line][-1]
        _added(
            path,
            _line(
                type="user",
                uuid="b1c6a0de-52f7-4d3b-9a08-6e4f1d7c2a95",
                parentUuid=last["uuid"],
                timestamp="2026-11-12T10:40:00.000Z",
                cwd=last["cwd"],
                version=last["version"],
                promptSource="typed",
                message={"role": "user", "content": "And the brakes?"},
            ),
        )
        assert walker.walk().appended == 1
        return path

    def test_an_appended_call_names_the_places_of_the_first_it_carries(
        self,
        committed_app: Flask,
        resumed: Path,
        walker: Walker,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The boundary is the file's last Call, in its second Launch, and
        the one Prompt after it is the transcript's last."""
        held = _facts(committed_app, RIDES)
        sent = _sent(walker, monkeypatch)
        _grown(resumed)

        walked = walker.walk()

        assert (walked.published, walked.appended) == (1, 1)
        (publication,) = sent
        assert publication.appended is not None
        assert publication.appended.boundary.model_dump() == {
            "call": len(held["calls"]),
            "launch": 2,
            "prompt": len(held["prompts"]),
            "compaction": 1,
        }
        (launch,) = publication.launches
        (prompt,) = launch.prompts
        assert launch.started_at == held["launches"][1]["started_at"]
        assert prompt.received_at == held["prompts"][-1]["received_at"]
        assert publication.calls[0].message_id == held["calls"][-1]["message_id"]
        assert _facts(committed_app, RIDES) == held

    @pytest.mark.parametrize(
        ("entity", "time", "fact", "did"),
        [
            (Launch, "started_at", "launch", "begun"),
            (Prompt, "received_at", "prompt", "received"),
        ],
        ids=["another launch", "another prompt"],
    )
    def test_pilot_refuses_a_call_whose_first_is_not_the_row_it_holds_there(
        self,
        committed_app: Flask,
        resumed: Path,
        walker: Walker,
        caplog: pytest.LogCaptureFixture,
        entity: Any,
        time: str,
        fact: str,
        did: str,
    ) -> None:
        """Pilot's row at the boundary's place is made another: its time a
        second later than the file says."""
        held = _facts(committed_app, RIDES)
        with _record(committed_app) as record:
            thread = _thread(record, RIDES)
            row = record.scalars(
                select(entity)
                .where(entity.transcript_id == thread.id)
                .order_by(entity.id.desc())
                .limit(1)
            ).one()
            read = getattr(row, time)
            record.execute(
                update(entity)
                .where(entity.id == row.id)
                .values({time: read + timedelta(seconds=1)})
            )
            record.commit()
        place = {"launch": 2, "prompt": len(held["prompts"])}[fact]
        _grown(resumed)

        with caplog.at_level(logging.INFO, LOGGER):
            walked = walker.walk()

        assert (walked.published, walked.appended) == (1, 0)
        assert _whole_instead(caplog) == [
            f"Pilot refused it appended: Cannot append to transcript {RIDES}"
            f" because the boundary's `{fact}` is {place}, where Pilot holds a"
            f" {fact} {did} at {(read + timedelta(seconds=1)).isoformat()}, and"
            f" the call's first was {did} at {read.isoformat()}"
        ]
        assert _facts(committed_app, RIDES) == held
        now = _held(committed_app)[RIDES]
        assert now["replayed_size"] == now["stands"][0] == _stands(resumed)[0]

    def test_pilots_refusal_is_the_clients_own_failure(
        self, committed_app: Flask, pilot_url: str, home: Path, walker: Walker
    ) -> None:
        walker.walk()
        found = transcript(home / "projects", _file(home, RIDES))
        whole = reader.read(found, walker._settings)
        _grown(_file(home, RIDES))
        grown = reader.read(found, walker._settings, whole.carry).publication
        assert grown.appended is not None
        stale = grown.model_copy(
            update={
                "appended": grown.appended.model_copy(
                    update={
                        "builds_on": grown.appended.builds_on.model_copy(
                            update={"collector": OLDER}
                        )
                    }
                )
            }
        )

        with Pilot(pilot_url, COLLECTOR_TOKEN) as pilot:
            with pytest.raises(NotAppendable) as refused:
                pilot.publish(stale)

        assert str(refused.value) == (
            f"Cannot append to transcript {RIDES} because Pilot holds it at another"
            " size, time or collector's version than the call builds on"
        )
        assert _held(committed_app)[RIDES]["stands"][0] == whole.publication.file_size


class TestTheCarrysBound:
    def test_past_it_the_transcript_that_grew_longest_ago_is_published_whole_once(
        self,
        committed_app: Flask,
        pilot_url: str,
        home: Path,
        walker: Walker,
        stop: threading.Event,
    ) -> None:
        """Two carries are kept of three transcripts: after the first walk
        those of the two files changed last. The third then grows, and its
        carry takes the place of the older of the two."""
        bound = Walker(
            walker._pilot,
            _settings(pilot_url, home, COLLECTOR_CARRY_TRANSCRIPTS=2),
            stop,
        )
        bound.walk()
        before = _held(committed_app)
        newest, older, oldest = sorted(
            SCENARIOS, key=lambda name: before[name]["stands"][1], reverse=True
        )

        def grown(*names: str) -> tuple[int, int]:
            for name in names:
                _grown(_file(home, name))
            walked = bound.walk()
            return walked.published, walked.appended

        assert grown(oldest) == (1, 0)
        held = _held(committed_app)[oldest]
        assert held["replayed_size"] == held["stands"][0] > before[oldest]["stands"][0]
        assert grown(oldest, newest) == (2, 2)
        assert grown(older) == (1, 0)
        assert grown(older) == (1, 1)


def _await(holds: Any, seconds: float = 10.0) -> None:
    """Wait until `holds` answers true."""
    until = time.perf_counter() + seconds
    while not holds():
        assert time.perf_counter() < until, "it did not come to hold"
        time.sleep(0.02)
