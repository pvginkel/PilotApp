"""A walk's work: the home's listing compared with Pilot's inventory. The
walk itself is proved against Pilot's routes in the backend's suite,
`backend/tests/collector/test_walk.py`."""

import logging
import socket
import threading
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pilot_collection.inventory import InventorySchema

from pilot_collector import VERSION
from pilot_collector.home import Listed, Transcript
from pilot_collector.labeller import Stamps
from pilot_collector.pilot import Pilot
from pilot_collector.walk import Walker, Work, plan
from tests.support import AGENT, FOLDER, SESSION, filed, settings, typed

PROJECTS = Path("/home/ubuntu/.claude/projects")
OTHER = "9d3b7e52-1c4a-4f80-b6e9-05a7c3f1d248"
THIRD = "c2a8f6d0-3b17-4e59-a4c1-6f9e0d2b7a35"
STOOD = datetime(2026, 11, 12, 10, 2, 3, 456789, tzinfo=UTC)
"""A file's time."""
NOW = STOOD + timedelta(hours=1)
SETTLING = 600.0


def _listed(
    session: str = SESSION,
    agent: str | None = None,
    size: int = 61_000,
    at: datetime = STOOD,
) -> Listed:
    path = PROJECTS / FOLDER / f"{session}.jsonl"
    return Listed(Transcript(PROJECTS, path, session, agent), size, at)


def _held(
    session: str = SESSION, agent: str | None = None, **facts: Any
) -> dict[str, Any]:
    """A transcript as the inventory names one: held as `_listed` lists it,
    read whole under this version, but for `facts`."""
    held: dict[str, Any] = {
        "session_id": session,
        "agent_id": agent,
        "file_size": 61_000,
        "file_modified_at": STOOD.isoformat(),
        "replayed_size": 61_000,
        "collector": VERSION,
        "labeller": "1.0.0",
        "stamp": "1:Qm9hdHMgb24gdGhlIGxha2U",
    }
    return held | facts


def _inventory(*held: dict[str, Any]) -> InventorySchema:
    """Pilot's inventory holding `held`, with the conversation of `SESSION`
    that a Session of Pilot's ran."""
    return InventorySchema.model_validate(
        {
            "walk_interval_seconds": 30.0,
            "settling_seconds": SETTLING,
            "transcripts": list(held),
            "conversations": [
                {
                    "session_id": SESSION,
                    "sessions": [
                        {
                            "id": "0b6f3c2a-8d41-4e7a-9c15-2f8e6d4a7b30",
                            "kind": "work",
                            "created_at": (STOOD - timedelta(hours=1)).isoformat(),
                            "brief": "Survey the lake.",
                            "repo": "example/Camp",
                            "clarification": False,
                            "holds": [],
                            "turns": [
                                {
                                    "started_at": (
                                        STOOD - timedelta(minutes=59)
                                    ).isoformat(),
                                    "cause": "brief",
                                }
                            ],
                        }
                    ],
                    "documents": [],
                }
            ],
        }
    )


class TestAWalksWork:
    def test_a_transcript_the_inventory_lacks_is_published(self) -> None:
        listed = _listed()

        assert plan([listed], _inventory(), NOW) == Work([listed], [])

    def test_one_held_as_its_file_stands_is_left(self) -> None:
        assert plan([_listed()], _inventory(_held()), NOW) == Work([], [])

    @pytest.mark.parametrize(
        "listed",
        [
            _listed(size=61_001),
            _listed(size=60_999),
            _listed(at=STOOD + timedelta(microseconds=1)),
            _listed(at=STOOD - timedelta(microseconds=1)),
        ],
    )
    def test_one_held_at_another_size_or_time_is_published(
        self, listed: Listed
    ) -> None:
        assert plan([listed], _inventory(_held()), NOW) == Work([listed], [])

    def test_the_inventorys_time_is_an_instant_whatever_its_offset(self) -> None:
        """Pilot writes the time under its database session's time zone."""
        amsterdam = STOOD.astimezone(timezone(timedelta(hours=1))).isoformat()
        assert amsterdam.endswith("+01:00")

        work = plan([_listed()], _inventory(_held(file_modified_at=amsterdam)), NOW)

        assert work == Work([], [])

    def test_a_sub_agents_thread_is_held_by_both_its_ids(self) -> None:
        main, sub_agent = _listed(), _listed(agent=AGENT)

        work = plan([main, sub_agent], _inventory(_held()), NOW)

        assert work == Work([sub_agent], [])

    def test_one_read_under_another_version_is_behind(self) -> None:
        listed = _listed()

        work = plan([listed], _inventory(_held(collector="0.9.0")), NOW)

        assert work == Work([], [listed])

    def test_one_published_appended_since_is_behind_once_its_file_has_settled(
        self,
    ) -> None:
        listed = _listed(at=NOW - timedelta(seconds=SETTLING))
        held = _held(
            file_modified_at=listed.file_modified_at.isoformat(), replayed_size=48_112
        )

        assert plan([listed], _inventory(held), NOW) == Work([], [listed])

    def test_one_published_appended_since_waits_while_its_file_settles(self) -> None:
        listed = _listed(at=NOW - timedelta(seconds=SETTLING - 1))
        held = _held(
            file_modified_at=listed.file_modified_at.isoformat(), replayed_size=48_112
        )

        assert plan([listed], _inventory(held), NOW) == Work([], [])

    def test_a_changed_file_is_published_once_whatever_else_differs(self) -> None:
        listed = _listed(size=61_400)
        held = _held(collector="0.9.0", replayed_size=48_112)

        assert plan([listed], _inventory(held), NOW) == Work([listed], [])

    def test_what_pilot_holds_and_the_home_lacks_is_left_alone(self) -> None:
        work = plan([_listed()], _inventory(_held(), _held(OTHER)), NOW)

        assert work == Work([], [])

    def test_each_turn_takes_the_most_recently_changed_first(self) -> None:
        def aged(session: str, minutes: int) -> Listed:
            return _listed(session, at=STOOD - timedelta(minutes=minutes))

        new = [aged("new-b", 5), aged("new-a", 1), aged("new-c", 9)]
        old = [aged(SESSION, 8), aged(OTHER, 2), aged(THIRD, 4)]
        inventory = _inventory(
            *(
                _held(
                    each.transcript.session_id,
                    file_modified_at=each.file_modified_at.isoformat(),
                    collector="0.9.0",
                )
                for each in old
            )
        )

        work = plan(old + new, inventory, NOW)

        assert [each.transcript.name for each in work.changed] == [
            "new-a",
            "new-b",
            "new-c",
        ]
        assert [each.transcript.name for each in work.behind] == [OTHER, THIRD, SESSION]


HELD = "1:Qm9hdHMgb24gdGhlIGxha2U"
"""The stamp `_held` holds."""


def _stamps(version: str = "1.0.0", stamp: str | None = HELD) -> Stamps:
    """The labeller `version` answering, its stamp of `SESSION`'s main
    thread `stamp`."""
    return Stamps(version, "d", "f", {(SESSION, None): stamp}, 0.1)


class TestWhatTheLabellerMakesDiffer:
    """A transcript Pilot holds as its file stands is labelled again whole
    where the labeller's major or its stamp differs (F152.6, F152.7)."""

    @pytest.mark.parametrize("version", ["1.3.0", "1.2.1", "1.2.0"])
    def test_one_held_under_another_minor_or_patch_is_left(self, version: str) -> None:
        inventory = _inventory(_held(labeller="1.2.0"))

        assert plan([_listed()], inventory, NOW, _stamps(version)) == Work([], [])

    @pytest.mark.parametrize(
        "held",
        [{"labeller": "1.2.0"}, {"stamp": "1:QW5vdGhlciBsYWtl"}, {"stamp": None}],
        ids=["another major", "another stamp", "no stamp"],
    )
    def test_one_held_under_another_major_or_stamp_is_behind(
        self, held: dict[str, Any]
    ) -> None:
        listed = _listed()

        work = plan(
            [listed],
            _inventory(_held(**held)),
            NOW,
            _stamps("2.0.0" if "labeller" in held else "1.0.0"),
        )

        assert work == Work([], [listed], frozenset({listed.transcript.path}))

    def test_one_no_labeller_labelled_is_behind(self) -> None:
        listed = _listed()

        work = plan(
            [listed], _inventory(_held(labeller=None, stamp=None)), NOW, _stamps()
        )

        assert work == Work([], [listed], frozenset({listed.transcript.path}))

    @pytest.mark.parametrize(
        "stamps", [None, _stamps(stamp=None)], ids=["no labeller", "no stamp"]
    )
    def test_one_no_labeller_stamps_now_is_left(self, stamps: Stamps | None) -> None:
        inventory = _inventory(_held(labeller=None, stamp=None))

        assert plan([_listed()], inventory, NOW, stamps) == Work([], [])

    def test_one_whose_labels_pilot_refused_under_its_stamp_is_left(self) -> None:
        listed = _listed()
        refused = {listed.transcript.path: (61_000, STOOD, "1.0.0", HELD)}
        inventory = _inventory(_held(stamp=None))

        assert plan([listed], inventory, NOW, _stamps(), refused) == Work([], [])
        for given in [
            (61_000, STOOD, "1.0.1", HELD),
            (61_000, STOOD, "1.0.0", "1:QW5vdGhlciBsYWtl"),
            (61_001, STOOD, "1.0.0", HELD),
        ]:
            work = plan(
                [listed], inventory, NOW, _stamps(), {listed.transcript.path: given}
            )
            assert work.behind == [listed]

    def test_a_changed_file_or_another_collector_is_not_the_labellers_alone(
        self,
    ) -> None:
        changed, behind = _listed(size=61_400), _listed(OTHER)
        inventory = _inventory(
            _held(stamp=None), _held(OTHER, collector="0.9.0", stamp=None)
        )
        stamps = Stamps(
            "1.0.0", "d", "f", {(SESSION, None): HELD, (OTHER, None): HELD}, 0.1
        )

        work = plan([changed, behind], inventory, NOW, stamps)

        assert work == Work([changed], [behind])


class TestAWalkWithNoPilot:
    def test_it_ends_where_it_stands_and_the_next_starts_over(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Nothing listens where the collector calls: a port bound and
        never listened on refuses every connection."""
        filed(tmp_path / "projects", [typed(0)])
        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            url = f"http://127.0.0.1:{taken.getsockname()[1]}"
            with Pilot(url, "an-invented-collector-token") as pilot:
                walker = Walker(
                    pilot, settings(COLLECTOR_HOME=tmp_path), threading.Event()
                )
                with caplog.at_level(logging.WARNING, "pilot_collector.walk"):
                    walks = [walker.walk(), walker.walk()]

        assert [(walk.published, walk.ended) for walk in walks] == [(0, False)] * 2
        assert [record.levelname for record in caplog.records] == ["WARNING"] * 2
        assert "The walk ended early: Pilot did not answer: ConnectError" in caplog.text
