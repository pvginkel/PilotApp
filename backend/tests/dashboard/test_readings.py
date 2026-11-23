"""A conversation's reading kept by the backend (F154.7): asked of the
collector conditionally at every read, kept on scratch storage beside its
validator and evicted by total size, the least recently read first; the
collector's refusal and a gone transcript states of the read."""

import gzip
import os
import threading
import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.dashboard import readings
from app.dashboard.readings import (
    NO_BEARER,
    NO_COLLECTOR,
    Gone,
    Kept,
    ReadingCache,
    ReadingsService,
    Refused,
    Served,
)
from app.models import Call, Project, Transcript
from app.services.container import ServiceContainer
from app.services.fake_collector import FakeAsk, validator
from tests.support.fake_collector import ServedFakeCollector, invented_reading
from tests.support.publications import COLLECTOR_TOKEN

MAIN = "4f1c9e2a-7b3d-4a68-9c05-e1d2b3a4f567"
AGENT = "a7c2e9f41b3d5e860"

WAIT_SECONDS = 5.0


def _thread(session_id: str = MAIN, agent_id: str | None = None) -> Transcript:
    """A Transcript as a read names one: its id and Claude Code's ids."""
    return Transcript(id=uuid.uuid4(), session_id=session_id, agent_id=agent_id)


def _kept(folder: Path) -> list[str]:
    return sorted(entry.name for entry in folder.iterdir())


class TestReadingCache:
    def test_it_keeps_a_reading_beside_its_validator_one_file_a_transcript(
        self, tmp_path: Path
    ) -> None:
        cache = ReadingCache(tmp_path, 1000)
        thread = uuid.uuid4()

        cache.keep(thread, '"4096-1"', b"\x1f\x8bfirst")

        assert cache.take(thread) == Kept('"4096-1"', b"\x1f\x8bfirst")
        assert _kept(tmp_path) == [str(thread)]
        assert (tmp_path / str(thread)).read_bytes() == b'"4096-1"\n\x1f\x8bfirst'

    def test_a_reading_kept_again_takes_the_place_of_the_one_before(
        self, tmp_path: Path
    ) -> None:
        cache = ReadingCache(tmp_path, 1000)
        thread = uuid.uuid4()
        cache.keep(thread, '"4096-1"', b"first")

        cache.keep(thread, '"5120-2"', b"second")

        assert cache.take(thread) == Kept('"5120-2"', b"second")
        assert _kept(tmp_path) == [str(thread)]

    def test_none_is_kept_of_a_transcript_never_kept(self, tmp_path: Path) -> None:
        assert ReadingCache(tmp_path, 1000).take(uuid.uuid4()) is None

    def test_past_its_size_the_least_recently_read_go_first(
        self, tmp_path: Path
    ) -> None:
        cache = ReadingCache(tmp_path, 300)
        first, second, third = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        cache.keep(first, "a", b"x" * 98)
        cache.keep(second, "b", b"x" * 98)
        cache.keep(third, "c", b"x" * 98)
        assert cache.take(first) is not None

        cache.keep(uuid.uuid4(), "d", b"x" * 98)

        assert cache.take(second) is None
        assert cache.take(first) is not None
        assert cache.take(third) is not None
        assert len(_kept(tmp_path)) == 3

    def test_the_reading_just_kept_stays_alone_when_it_is_larger_than_the_bound(
        self, tmp_path: Path
    ) -> None:
        cache = ReadingCache(tmp_path, 100)
        earlier, larger = uuid.uuid4(), uuid.uuid4()
        cache.keep(earlier, "a", b"x" * 50)

        cache.keep(larger, "b", b"x" * 500)

        assert cache.take(earlier) is None
        assert cache.take(larger) == Kept("b", b"x" * 500)
        assert _kept(tmp_path) == [str(larger)]

    def test_a_reading_dropped_is_forgotten(self, tmp_path: Path) -> None:
        cache = ReadingCache(tmp_path, 1000)
        thread = uuid.uuid4()
        cache.keep(thread, "a", b"first")

        cache.drop(thread)
        cache.drop(uuid.uuid4())

        assert cache.take(thread) is None
        assert _kept(tmp_path) == []

    def test_at_its_start_it_takes_what_a_process_before_kept_by_its_reads(
        self, tmp_path: Path
    ) -> None:
        older, newer = uuid.uuid4(), uuid.uuid4()
        cache = ReadingCache(tmp_path, 300)
        cache.keep(older, "a", b"x" * 98)
        cache.keep(newer, "b", b"x" * 98)
        os.utime(tmp_path / str(older), ns=(1, 1))
        os.utime(tmp_path / str(newer), ns=(2, 2))
        (tmp_path / f"{uuid.uuid4()}.0a1b2c3d.writing").write_bytes(b"half")
        (tmp_path / "notes.txt").write_bytes(b"not the cache's")

        again = ReadingCache(tmp_path, 300)
        again.keep(uuid.uuid4(), "c", b"x" * 98)
        again.keep(uuid.uuid4(), "d", b"x" * 98)

        assert again.take(older) is None
        assert again.take(newer) == Kept("b", b"x" * 98)
        assert "notes.txt" in _kept(tmp_path)
        assert not [name for name in _kept(tmp_path) if name.endswith(".writing")]

    def test_at_its_start_it_evicts_past_a_bound_set_lower(
        self, tmp_path: Path
    ) -> None:
        older, newer = uuid.uuid4(), uuid.uuid4()
        cache = ReadingCache(tmp_path, 1000)
        cache.keep(older, "a", b"x" * 98)
        cache.keep(newer, "b", b"x" * 98)
        os.utime(tmp_path / str(older), ns=(1, 1))
        os.utime(tmp_path / str(newer), ns=(2, 2))

        again = ReadingCache(tmp_path, 150)

        assert again.take(older) is None
        assert again.take(newer) is not None


class TestRead:
    def test_the_first_read_asks_for_the_whole_reading_and_keeps_it(
        self,
        readings_service: ReadingsService,
        fake_collector: ServedFakeCollector,
        tmp_path: Path,
    ) -> None:
        reading = invented_reading()
        fake_collector.serve(reading)
        thread = _thread()

        read = readings_service.read(thread)

        assert read == Served(reading)
        assert fake_collector.asks() == [FakeAsk(MAIN, None, None, 200)]
        kept = (tmp_path / "readings" / str(thread.id)).read_bytes()
        tag, _, body = kept.partition(b"\n")
        assert tag.decode() == validator(reading)
        assert gzip.decompress(body) == reading.model_dump_json().encode()

    def test_a_read_again_asks_conditionally_and_serves_what_is_kept(
        self, readings_service: ReadingsService, fake_collector: ServedFakeCollector
    ) -> None:
        reading = invented_reading()
        fake_collector.serve(reading)
        thread = _thread()
        readings_service.read(thread)

        read = readings_service.read(thread)

        assert read == Served(reading)
        assert fake_collector.asks()[1:] == [
            FakeAsk(MAIN, None, validator(reading), 304)
        ]

    def test_a_reading_that_changed_is_served_and_kept_in_place_of_the_one_before(
        self, readings_service: ReadingsService, fake_collector: ServedFakeCollector
    ) -> None:
        fake_collector.serve(invented_reading())
        thread = _thread()
        readings_service.read(thread)
        grown = invented_reading().model_copy(
            update={
                "file_size": 8192,
                "file_modified_at": invented_reading().file_modified_at
                + timedelta(minutes=1),
            }
        )
        fake_collector.serve(grown)

        changed = readings_service.read(thread)
        again = readings_service.read(thread)

        assert changed == again == Served(grown)
        assert [ask.status for ask in fake_collector.asks()] == [200, 200, 304]
        assert fake_collector.asks()[2].validator == validator(grown)

    def test_a_sub_agents_reading_is_asked_by_both_its_ids(
        self, readings_service: ReadingsService, fake_collector: ServedFakeCollector
    ) -> None:
        reading = invented_reading(agent_id=AGENT)
        fake_collector.serve(invented_reading())
        fake_collector.serve(reading)

        read = readings_service.read(_thread(agent_id=AGENT))

        assert read == Served(reading)
        assert fake_collector.asks() == [FakeAsk(MAIN, AGENT, None, 200)]

    def test_a_transcript_gone_from_the_home_is_gone_and_no_longer_kept(
        self,
        readings_service: ReadingsService,
        fake_collector: ServedFakeCollector,
        tmp_path: Path,
    ) -> None:
        fake_collector.serve(invented_reading())
        thread = _thread()
        readings_service.read(thread)
        fake_collector.gone(MAIN)

        read = readings_service.read(thread)
        again = readings_service.read(thread)

        assert read == again == Gone()
        assert _kept(tmp_path / "readings") == []
        assert fake_collector.asks()[2] == FakeAsk(MAIN, None, None, 404)

    def test_a_transcript_the_home_never_had_is_gone(
        self, readings_service: ReadingsService
    ) -> None:
        assert readings_service.read(_thread()) == Gone()

    def test_a_collector_of_another_version_refuses_the_read_and_says_so(
        self,
        readings_service: ReadingsService,
        fake_collector: ServedFakeCollector,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        fake_collector.serve(invented_reading())
        thread = _thread()
        readings_service.read(thread)
        fake_collector.refuse()

        read = readings_service.read(thread)

        why = (
            "the collector serves readings of versions 2 to 2, and Pilot reads "
            "version 1"
        )
        assert read == Refused(why)
        assert f"The reading of transcript {thread.id} was refused: {why}" in (
            caplog.messages
        )

    def test_a_refused_read_leaves_the_reading_kept_for_the_next(
        self, readings_service: ReadingsService, fake_collector: ServedFakeCollector
    ) -> None:
        reading = invented_reading()
        fake_collector.serve(reading)
        thread = _thread()
        readings_service.read(thread)
        fake_collector.refuse("unreadable")
        assert readings_service.read(thread) == Refused("the collector answered 500")
        fake_collector.refuse(None)

        read = readings_service.read(thread)

        assert read == Served(reading)
        assert fake_collector.asks()[2] == FakeAsk(MAIN, None, validator(reading), 304)

    def test_a_read_without_the_collectors_bearer_is_refused(
        self, fake_collector: ServedFakeCollector, tmp_path: Path
    ) -> None:
        fake_collector.serve(invented_reading())
        service = ReadingsService(fake_collector.url, "not-the-bearer", tmp_path, 1000)

        assert service.read(_thread()) == Refused(
            "the collector refused Pilot's bearer, COLLECTOR_TOKEN"
        )

    def test_a_path_the_collector_serves_no_reading_on_is_refused(
        self, fake_collector: ServedFakeCollector, tmp_path: Path
    ) -> None:
        service = ReadingsService(
            f"{fake_collector.url}/elsewhere", COLLECTOR_TOKEN, tmp_path, 1000
        )

        assert service.read(_thread()) == Refused(
            "the collector answered 404: Not Found"
        )

    def test_a_collector_that_cannot_be_reached_refuses_the_read(
        self, tmp_path: Path
    ) -> None:
        closed = ServedFakeCollector()
        closed.close()
        service = ReadingsService(closed.url, COLLECTOR_TOKEN, tmp_path, 1000)

        read = service.read(_thread())

        assert isinstance(read, Refused)
        assert read.why.startswith("the collector could not be reached: ConnectError: ")

    def test_with_no_collector_every_read_is_refused(self, tmp_path: Path) -> None:
        service = ReadingsService(None, COLLECTOR_TOKEN, tmp_path, 1000)

        assert service.read(_thread()) == Refused(NO_COLLECTOR)

    def test_with_no_bearer_every_read_is_refused(
        self, fake_collector: ServedFakeCollector, tmp_path: Path
    ) -> None:
        service = ReadingsService(fake_collector.url, "", tmp_path, 1000)

        assert service.read(_thread()) == Refused(NO_BEARER)
        assert fake_collector.asks() == []

    def test_with_no_folder_it_keeps_readings_in_one_of_its_own(
        self, fake_collector: ServedFakeCollector
    ) -> None:
        fake_collector.serve(invented_reading())
        service = ReadingsService(
            fake_collector.url, COLLECTOR_TOKEN, None, 64 * 1024 * 1024
        )
        thread = _thread()

        service.read(thread)
        service.read(thread)

        assert [ask.status for ask in fake_collector.asks()] == [200, 304]

    def test_past_the_bound_a_reading_least_recently_read_is_asked_whole_again(
        self, fake_collector: ServedFakeCollector, tmp_path: Path
    ) -> None:
        first, second = _thread(), _thread(session_id=str(uuid.uuid4()))
        fake_collector.serve(invented_reading())
        fake_collector.serve(invented_reading(session_id=second.session_id))
        service = ReadingsService(fake_collector.url, COLLECTOR_TOKEN, tmp_path, 1)
        service.read(first)

        service.read(second)
        service.read(first)

        assert [ask.validator for ask in fake_collector.asks()] == [None, None, None]


class _Watched(readings._Ask):
    """An ask under way that says when a second read waits for it."""

    waited = threading.Event()

    def __init__(self) -> None:
        super().__init__()
        done = self.done
        original = done.wait

        def wait(timeout: float | None = None) -> bool:
            _Watched.waited.set()
            return original(timeout)

        done.wait = wait  # type: ignore[method-assign]


@pytest.fixture
def watched(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[_Watched]]:
    _Watched.waited = threading.Event()
    monkeypatch.setattr(readings, "_Ask", _Watched)
    yield _Watched


class TestOneAskAtOnce:
    def test_two_reads_of_one_cold_conversation_share_one_ask(
        self,
        readings_service: ReadingsService,
        fake_collector: ServedFakeCollector,
        watched: type[_Watched],
    ) -> None:
        fake_collector.serve(invented_reading())
        asked, release = threading.Event(), threading.Event()

        def hold() -> None:
            asked.set()
            assert release.wait(WAIT_SECONDS)

        fake_collector.on_ask = hold
        thread = _thread()
        reads: dict[str, object] = {}

        def read(name: str) -> None:
            reads[name] = readings_service.read(thread)

        first = threading.Thread(target=read, args=("first",))
        first.start()
        assert asked.wait(WAIT_SECONDS)
        second = threading.Thread(target=read, args=("second",))
        second.start()
        assert watched.waited.wait(WAIT_SECONDS)
        release.set()
        first.join(WAIT_SECONDS)
        second.join(WAIT_SECONDS)

        assert isinstance(reads["first"], Served)
        assert reads["second"] is reads["first"]
        assert fake_collector.asks() == [FakeAsk(MAIN, None, None, 200)]

    def test_a_read_after_the_ask_ended_asks_again(
        self, readings_service: ReadingsService, fake_collector: ServedFakeCollector
    ) -> None:
        fake_collector.serve(invented_reading())
        thread = _thread()

        readings_service.read(thread)
        readings_service.read(thread)

        assert len(fake_collector.asks()) == 2


@pytest.mark.usefixtures("service_user")
class TestTheScenariosReadings:
    def test_a_loaded_conversations_calls_are_its_facts_calls(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        fake_collector: ServedFakeCollector,
        readings_service: ReadingsService,
    ) -> None:
        loaded = container.scenario_service().load({"recipe-box": project.id})

        for thread in loaded:
            read = readings_service.read(thread)

            assert isinstance(read, Served)
            assert (read.reading.session_id, read.reading.agent_id) == (
                thread.session_id,
                thread.agent_id,
            )
            assert (read.reading.file_size, read.reading.file_modified_at) == (
                thread.file_size,
                thread.file_modified_at,
            )
            assert [call.message_id for call in read.reading.calls] == list(
                session.scalars(
                    select(Call.message_id)
                    .where(Call.transcript_id == thread.id)
                    .order_by(Call.position)
                )
            )
        assert len(loaded) == 3
