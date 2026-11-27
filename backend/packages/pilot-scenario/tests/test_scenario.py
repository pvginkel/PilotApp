"""The one scenario: in the dev seed's own world, a story that holds
together, and in a vocabulary of its own, with no kind of the workflow's
(F122.4), the stub labeller's words among it."""

import re
from collections.abc import Iterator
from dataclasses import fields, is_dataclass, replace
from datetime import UTC, datetime
from typing import Any

import pytest
from pilot_scenario import SCENARIO, Builder, Scenario, labeller
from pilot_scenario.script import Call, Group, Session, Unit

WORKFLOW = {"slice", "stage", "phase"}
"""The workflow's kinds of work, which no scenario speaks of."""


def _words(part: Any) -> Iterator[str]:
    """Every word a part of a script, or what is said of it, is written in,
    in lower case: a string is split at whatever is no letter and at a
    capital inside it; of a mapping its values are."""
    if isinstance(part, str):
        for word in re.findall(r"[A-Z]?[a-z]+|[A-Z]+", part):
            yield word.lower()
    elif isinstance(part, tuple | list):
        for each in part:
            yield from _words(each)
    elif isinstance(part, dict):
        for each in part.values():
            yield from _words(each)
    elif is_dataclass(part):
        for field in fields(part):
            yield from _words(getattr(part, field.name))


def _workflow_words(scenario: Scenario) -> set[str]:
    """The words of the workflow the scenario is written in, one or many."""
    return {word for word in _words(scenario) if word.removesuffix("s") in WORKFLOW}


def _calls(session: Session) -> Iterator[Call]:
    """The Calls of the session's main thread, in order."""
    for launch in session.launches:
        for prompt in launch.prompts:
            yield from (step for step in prompt.steps if isinstance(step, Call))


class TestItsVocabulary:
    def test_the_scenario_has_no_word_of_the_workflow(self) -> None:
        assert _workflow_words(SCENARIO) == set()

    @pytest.mark.parametrize(
        ("scenario", "found"),
        [
            pytest.param(
                replace(SCENARIO, kinds=("slice", "leg")), {"slice"}, id="a kind"
            ),
            pytest.param(
                replace(SCENARIO, units=(Unit("errand", "The second Phase"),)),
                {"phase"},
                id="a unit's name",
            ),
            pytest.param(
                replace(
                    SCENARIO,
                    sessions=(
                        replace(SCENARIO.sessions[0], directory="/work/StagesOfStew"),
                    ),
                ),
                {"stages"},
                id="a session's directory",
            ),
            pytest.param(
                replace(
                    SCENARIO,
                    sessions=(
                        replace(
                            SCENARIO.sessions[0],
                            sub_agents=(
                                replace(
                                    SCENARIO.sessions[0].sub_agents[0],
                                    name="the_slice-counter",
                                ),
                            ),
                        ),
                    ),
                ),
                {"slice"},
                id="a sub-agent's name",
            ),
            pytest.param(
                replace(
                    SCENARIO,
                    sessions=(
                        replace(
                            SCENARIO.sessions[1],
                            group=Group(
                                key="bike-log-first-rides",
                                name="The first rides",
                                summary="Each ride had three phases.",
                            ),
                        ),
                    ),
                ),
                {"phases"},
                id="a group's summary",
            ),
        ],
    )
    def test_a_word_of_the_workflow_is_found(
        self, scenario: Scenario, found: set[str]
    ) -> None:
        assert _workflow_words(scenario) == found

    def test_the_stub_labeller_says_no_word_of_the_workflow(self) -> None:
        """Its lists, the run records it reads of the scenario and the
        labels it gives the scenario's files."""
        builder = Builder(SCENARIO, datetime(2026, 11, 12, 9, 30, tzinfo=UTC))
        records = builder.records()
        said = [
            labeller.vocabularies(records),
            records,
            *(publication["labelling"] for publication in builder.publications()),
        ]

        assert {w for w in _words(said) if w.removesuffix("s") in WORKFLOW} == set()
        assert {
            w
            for w in _words(labeller.vocabularies({"kinds": ["errand", "phase"]}))
            if w.removesuffix("s") in WORKFLOW
        } == {"phase"}

    def test_its_kinds_of_work_are_its_own(self) -> None:
        assert SCENARIO.kinds == ("errand", "leg")
        assert not set(SCENARIO.kinds) & WORKFLOW


class TestItsWorld:
    def test_it_is_the_dev_seeds_world(self) -> None:
        assert SCENARIO.people == ("ada", "ben")
        assert SCENARIO.projects == ("recipe-box", "bike-log")

    def test_a_session_is_pilots_or_a_persons_of_that_world(self) -> None:
        for session in SCENARIO.sessions:
            assert (session.ran is None) != (session.person is None), session.name
            if session.ran is not None:
                assert session.ran.project in SCENARIO.projects
            else:
                assert session.person in SCENARIO.people

    def test_a_group_is_named_for_a_session_no_turn_of_pilots_ran(self) -> None:
        """An adopted project adopts no conversation a session of Pilot's
        ran."""
        assert [
            (session.name, None if session.group is None else session.group.key)
            for session in SCENARIO.sessions
        ] == [("halving", None), ("gears", "bike-log-first-rides")]
        assert all(
            session.ran is None
            for session in SCENARIO.sessions
            if session.group is not None
        )

    def test_it_takes_in_a_turn_of_pilots_a_session_a_person_ran_and_a_sub_agent(
        self,
    ) -> None:
        assert [
            (session.name, session.ran is not None, len(session.sub_agents))
            for session in SCENARIO.sessions
        ] == [("halving", True, 1), ("gears", False, 0)]


class TestItsStory:
    def test_a_units_kind_is_one_of_the_scenarios(self) -> None:
        assert {unit.kind for unit in SCENARIO.units} == set(SCENARIO.kinds)

    def test_a_unit_is_part_of_one_of_the_kind_before_its_own(self) -> None:
        units = {unit.name: unit for unit in SCENARIO.units}
        assert len(units) == len(SCENARIO.units)
        for unit in SCENARIO.units:
            rank = SCENARIO.kinds.index(unit.kind)
            if rank == 0:
                assert unit.within is None
                assert unit.project in SCENARIO.projects
            else:
                assert unit.within is not None, unit.name
                assert units[unit.within].kind == SCENARIO.kinds[rank - 1]
                assert unit.project is None

    def test_a_session_ran_a_unit_of_the_scenarios(self) -> None:
        units = {unit.name for unit in SCENARIO.units}
        ran = [session.unit for session in SCENARIO.sessions]

        assert ran == ["Halve the stew", None]
        assert {unit for unit in ran if unit is not None} <= units

    def test_a_session_has_a_name_of_its_own(self) -> None:
        names = [session.name for session in SCENARIO.sessions]

        assert len(set(names)) == len(names)

    def test_a_sub_agent_is_started_by_one_tool_call_of_its_main_thread(self) -> None:
        for session in SCENARIO.sessions:
            spawned = [
                use.spawns
                for call in _calls(session)
                for use in call.tools
                if use.spawns is not None
            ]
            assert spawned == [agent.name for agent in session.sub_agents]

    def test_a_rewind_goes_back_to_an_earlier_call_of_its_thread(self) -> None:
        rewinds = 0
        for session in SCENARIO.sessions:
            earlier: set[str] = set()
            for call in _calls(session):
                if call.back_to is not None:
                    assert call.back_to in earlier
                    rewinds += 1
                if call.name is not None:
                    earlier.add(call.name)
        assert rewinds == 1

    def test_a_turn_of_pilots_is_in_flight_as_its_launch_starts(self) -> None:
        for session in SCENARIO.sessions:
            if session.ran is None:
                continue
            (launch,) = session.launches
            (turn,) = session.ran.turns
            assert turn.at <= launch.prompts[0].at <= turn.ended
