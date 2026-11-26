"""The tally: a scenario for exact figures in the dev seed's own world, all
of it Pilot's, with no word of the workflow (F122.4), giving each figure of
the dashboard a case."""

import re
from collections.abc import Iterator
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from typing import Any

from pilot_scenario import TALLY, Builder
from pilot_scenario.script import Call, Compaction, Session, Turn

UNTIL = datetime(2026, 11, 26, 12, tzinfo=UTC)

WORKFLOW = {"slice", "stage", "phase"}


def _words(part: Any) -> Iterator[str]:
    if isinstance(part, str):
        for word in re.findall(r"[A-Z]?[a-z]+|[A-Z]+", part):
            yield word.lower()
    elif isinstance(part, tuple):
        for each in part:
            yield from _words(each)
    elif is_dataclass(part):
        for field in fields(part):
            yield from _words(getattr(part, field.name))


def _calls(session: Session) -> list[Call]:
    """Every Call of the session, its main thread's and its sub-agents'."""
    steps = [
        *(
            step
            for launch in session.launches
            for p in launch.prompts
            for step in p.steps
        ),
        *(step for agent in session.sub_agents for step in agent.steps),
    ]
    return [step for step in steps if isinstance(step, Call)]


def _turns() -> list[Turn]:
    """The tally's Turns of Pilot's, in its sessions' order."""
    return [
        turn
        for session in TALLY.sessions
        if session.ran is not None
        for turn in session.ran.turns
    ]


def _calls_published() -> list[dict[str, Any]]:
    return [
        call
        for publication in Builder(TALLY, UNTIL).publications()
        for call in publication["calls"]
    ]


class TestItsWorld:
    def test_it_is_the_dev_seeds_world(self) -> None:
        assert TALLY.people == ("ada", "ben")
        assert TALLY.projects == ("recipe-box", "bike-log")

    def test_it_has_no_word_of_the_workflow(self) -> None:
        assert {
            word for word in _words(TALLY) if word.removesuffix("s") in WORKFLOW
        } == set()

    def test_it_is_all_pilots_so_that_its_projects_hold_it_whole(self) -> None:
        for session in TALLY.sessions:
            assert session.ran is not None, session.name
            assert session.person is None and session.group is None
            assert session.ran.project in TALLY.projects

    def test_a_turn_a_person_sent_is_one_of_its_peoples(self) -> None:
        turns = _turns()

        assert [(turn.cause, turn.author) for turn in turns] == [
            ("brief", None),
            ("continuation", None),
            ("person", "ada"),
            ("person", "ben"),
            ("brief", None),
        ]


class TestItsRuns:
    def test_a_work_items_run_a_chat_and_a_job(self) -> None:
        assert [
            (run.project, run.kind, run.title, run.trigger, run.chat, len(run.turns))
            for run in Builder(TALLY, UNTIL).runs()
        ] == [
            ("recipe-box", "work", "Sort the spices", None, None, 2),
            ("recipe-box", "chat", None, None, "project", 2),
            ("bike-log", "job", "Tidy the ride notes", "item_done", None, 1),
        ]

    def test_each_turn_starts_a_launch_of_its_own(self) -> None:
        for session in TALLY.sessions:
            assert session.ran is not None
            assert len(session.launches) == len(session.ran.turns)
            for turn, launch in zip(session.ran.turns, session.launches, strict=True):
                assert turn.at <= launch.prompts[0].at <= turn.ended


class TestItsFigures:
    def test_sixteen_calls_over_five_turns(self) -> None:
        """Two counts a ratio is made of: 3.2 Calls a Turn."""
        assert sum(len(_calls(session)) for session in TALLY.sessions) == 16
        assert len(_turns()) == 5
        assert len(_calls_published()) == 16

    def test_five_threads_a_sub_agents_among_them(self) -> None:
        publications = Builder(TALLY, UNTIL).publications()

        assert [
            (publication.get("agent_type"), publication.get("description"))
            for publication in publications
        ] == [
            (None, None),
            ("Explore", "Find where the jars are counted"),
            (None, None),
            (None, None),
        ]

    def test_a_miss_after_a_compaction_and_one_after_a_wait_past_its_cache(
        self,
    ) -> None:
        misses = [call.miss for session in TALLY.sessions for call in _calls(session)]
        compactions = [
            step.at
            for session in TALLY.sessions
            for launch in session.launches
            for prompt in launch.prompts
            for step in prompt.steps
            if isinstance(step, Compaction)
        ]

        assert sorted(miss for miss in misses if miss is not None) == [
            "compaction",
            "ttl",
        ]
        assert compactions == [110]

    def test_one_call_writes_a_cache_large_enough_to_cost_more_than_a_dollar(
        self,
    ) -> None:
        large = [
            call
            for session in TALLY.sessions
            for call in _calls(session)
            if call.tokens.cache_write_1h > 50_000
        ]

        assert [(call.at, call.tokens.cache_write_1h) for call in large] == [
            (2_430, 96_800)
        ]
