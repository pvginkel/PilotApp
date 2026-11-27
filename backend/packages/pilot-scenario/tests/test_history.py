"""A history's days (`pilot_scenario.history`): each drawn the same from its
seed and its date every time, holding its share of the history's Calls, in
the scenario's words, and built at its own times."""

import re
from collections.abc import Iterator
from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pilot_scenario.history import ZONE, History, Place
from pilot_scenario.script import Call, Group, Session

TUESDAY = date(2026, 11, 17)

WORKFLOW = {"slice", "stage", "phase"}

RIDES = Group(key="bike-log-first-rides", name="The first rides", summary="By hand.")

HISTORY = History(
    name="test",
    seed=7,
    calls_a_day=600,
    places=(
        Place("recipe-box", "Recipe box", "RecipeBox", 3, ("stew", "spice")),
        Place("bike-log", "Bike log", "BikeLog", 2, ("gears", "chain"), RIDES),
    ),
    long_calls=90,
)


def _words(part: Any) -> Iterator[str]:
    if isinstance(part, str):
        for word in re.findall(r"[A-Z]?[a-z]+|[A-Z]+", part):
            yield word.lower()
    elif isinstance(part, tuple | list):
        for each in part:
            yield from _words(each)
    elif is_dataclass(part) and not isinstance(part, type):
        for field in fields(part):
            yield from _words(getattr(part, field.name))


def _calls(session: Session) -> int:
    threads = [
        *(prompt.steps for launch in session.launches for prompt in launch.prompts),
        *(agent.steps for agent in session.sub_agents),
    ]
    return sum(isinstance(step, Call) for steps in threads for step in steps)


class TestTheDays:
    def test_a_day_is_drawn_the_same_every_time(self) -> None:
        assert HISTORY.draw(TUESDAY) == HISTORY.draw(TUESDAY)
        assert HISTORY.draw(TUESDAY) != HISTORY.draw(TUESDAY + timedelta(days=7))

    def test_another_seed_draws_another_day(self) -> None:
        other = History("test", 8, HISTORY.calls_a_day, HISTORY.places)

        assert other.draw(TUESDAY).scenario != HISTORY.draw(TUESDAY).scenario

    def test_a_day_holds_its_target_in_its_conversations_calls(self) -> None:
        day = HISTORY.draw(TUESDAY)

        assert day.calls >= HISTORY.target(TUESDAY)
        assert day.calls == sum(_calls(session) for session in day.scenario.sessions)

    def test_a_weekend_day_holds_fewer_than_a_weekday(self) -> None:
        saturday = TUESDAY + timedelta(days=4)

        for week in range(8):
            later = timedelta(days=7 * week)
            assert HISTORY.target(saturday + later) < HISTORY.target(TUESDAY + later)

    def test_a_wednesday_opens_on_the_long_conversation_by_hand(self) -> None:
        first = HISTORY.draw(TUESDAY + timedelta(days=1)).scenario.sessions[0]
        without = History("test", 7, 600, HISTORY.places).draw(
            TUESDAY + timedelta(days=1)
        )

        assert first.person is not None
        assert first.launches[0].prompts[0].steps
        assert (
            sum(
                isinstance(step, Call)
                for launch in first.launches
                for prompt in launch.prompts
                for step in prompt.steps
            )
            == 90
        )
        assert without.scenario.sessions[0] != first

    def test_the_days_run_back_from_the_last_until_their_targets_reach_the_calls(
        self,
    ) -> None:
        held = HISTORY.days(5_000, TUESDAY)

        assert held == [TUESDAY - timedelta(days=n) for n in range(len(held))]
        assert (
            sum(map(HISTORY.target, held))
            >= 5_000
            > sum(map(HISTORY.target, held[:-1]))
        )

    def test_a_day_has_no_word_of_the_workflow(self) -> None:
        day = HISTORY.draw(TUESDAY, 3_000)

        assert {
            word for word in _words(day.scenario) if word.removesuffix("s") in WORKFLOW
        } == set()

    def test_a_session_is_pilots_on_one_of_its_places_or_a_persons(self) -> None:
        sessions = HISTORY.draw(TUESDAY, 3_000).scenario.sessions
        kinds = {session.ran.kind for session in sessions if session.ran is not None}

        for session in sessions:
            assert (session.ran is None) != (session.person is None), session.name
            if session.ran is not None:
                assert session.ran.project in ("recipe-box", "bike-log")
                assert (session.ran.title is not None) == (
                    session.ran.kind in ("work", "job")
                )
                assert (session.ran.chat is not None) == (session.ran.kind == "chat")
        assert kinds == {"work", "job", "chat", "conversation"}

    def test_a_group_is_of_a_place_that_has_one(self) -> None:
        sessions = [
            session
            for back in range(40)
            for session in HISTORY.draw(
                TUESDAY - timedelta(days=back)
            ).scenario.sessions
        ]
        grouped = [session for session in sessions if session.group is not None]

        assert grouped
        assert {session.group for session in grouped} == {RIDES}
        assert {session.directory for session in grouped} == {"/work/BikeLog"}


class TestItsTimes:
    def test_a_days_moment_0_is_its_local_midnight(self) -> None:
        day = HISTORY.draw(TUESDAY)

        assert day.start == datetime(2026, 11, 17, tzinfo=ZONE).astimezone(UTC)
        assert day.builder().when(0) == day.start

    def test_before_a_moment_keeps_the_conversations_over_by_then(self) -> None:
        day = HISTORY.draw(TUESDAY)
        noon = day.start + timedelta(hours=12)

        kept = day.before(noon)
        builder = kept.builder()

        assert 0 < len(kept.scenario.sessions) < len(day.scenario.sessions)
        assert kept.calls == sum(_calls(s) for s in kept.scenario.sessions)
        assert all(
            publication["file_modified_at"] < noon.isoformat()
            for publication in builder.publications()
        )
        assert set(kept.standing) <= {s.name for s in kept.scenario.sessions}
        assert builder.when(0) == day.start
