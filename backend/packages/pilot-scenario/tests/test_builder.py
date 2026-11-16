"""The builder: a scenario's conversations as a collector publishes them
whole, the Turns of Pilot's its sessions ran under, the ids it gives them and
its times laid back from its last moment (F122.2)."""

import ast
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pilot_scenario
from pilot_scenario import COLLECTOR, SCENARIO, Builder, Scenario, SentTurn
from pilot_scenario.script import (
    Call,
    Compaction,
    Launch,
    Prompt,
    Session,
    Tokens,
    ToolUse,
)

UNTIL = datetime(2026, 11, 12, 9, 30, tzinfo=UTC)
LENGTH = 972
"""The scenario's last moment: Ada's last Call."""


def _at(moment: int) -> str:
    """The time of a moment of the scenario built until `UNTIL`."""
    return (UNTIL - timedelta(seconds=LENGTH - moment)).isoformat()


def _built() -> dict[str, dict[str, Any]]:
    """The scenario's publications, by the thread's name."""
    halving, counting, gears = Builder(SCENARIO, UNTIL).publications()
    return {"halving": halving, "counting": counting, "gears": gears}


def _calls(publication: dict[str, Any], fact: str) -> list[Any]:
    return [call.get(fact) for call in publication["calls"]]


class TestABuild:
    def test_a_thread_is_one_publication_a_main_thread_before_its_sub_agents(
        self,
    ) -> None:
        builder = Builder(SCENARIO, UNTIL)
        halving, gears = SCENARIO.sessions

        assert [
            (publication["session_id"], publication.get("agent_id"))
            for publication in builder.publications()
        ] == [
            (builder.conversation(halving), None),
            (
                builder.conversation(halving),
                builder.agent(halving, halving.sub_agents[0]),
            ),
            (builder.conversation(gears), None),
        ]

    def test_a_conversations_ids_are_the_scenarios_own(self) -> None:
        first = Builder(SCENARIO, UNTIL)
        later = Builder(SCENARIO, UNTIL + timedelta(days=3))
        other = Builder(replace(SCENARIO, name="breakfast"), UNTIL)
        halving = SCENARIO.sessions[0]
        counting = halving.sub_agents[0]

        assert first.conversation(halving) == later.conversation(halving)
        assert first.agent(halving, counting) == later.agent(halving, counting)
        assert first.conversation(halving) != other.conversation(halving)
        assert first.agent(halving, counting) != other.agent(halving, counting)
        assert first.conversation(halving) == "8766dbc8-267a-5322-9a1d-cc49ad56eedd"
        assert first.agent(halving, counting) == "6d6212072d4d5b429"

    def test_its_times_are_laid_back_from_its_last_moment(self) -> None:
        built = _built()

        assert built["gears"]["file_modified_at"] == UNTIL.isoformat()
        assert built["halving"]["launches"][0]["started_at"] == _at(4)
        assert Builder(SCENARIO, UNTIL).when(0) == UNTIL - timedelta(seconds=LENGTH)

    def test_a_publication_is_json_and_whole(self) -> None:
        for publication in Builder(SCENARIO, UNTIL).publications():
            assert json.loads(json.dumps(publication)) == publication
            assert "appended" not in publication
            assert publication["collector"] == {"version": COLLECTOR}


class TestAMainThread:
    def test_the_thread_pilot_ran(self) -> None:
        halving = _built()["halving"]

        assert {
            name: fact
            for name, fact in halving.items()
            if name not in ("session_id", "launches", "compactions", "calls")
        } == {
            "file_size": 61_904,
            "file_modified_at": _at(221),
            "collector": {"version": "1.0.0"},
            "working_directory": "/work/RecipeBox",
            "repository": "RecipeBox",
            "environment": "ben-recipebox-51f0c2",
        }

    def test_its_launch_ends_at_its_last_line(self) -> None:
        (launch,) = _built()["halving"]["launches"]

        assert launch == {
            "started_at": _at(4),
            "ended_at": _at(221),
            "components": [
                {"component": "claude-code", "version": "2.1.317"},
                {"component": "plugin:pantry", "version": "0.3.1"},
            ],
            "prompts": [
                {
                    "received_at": _at(4),
                    "source": "person",
                    "characters": 412,
                    "hook_runs": [
                        {
                            "command": "tidy_up.sh",
                            "duration_ms": 151,
                            "failed": False,
                            "prevented_end": False,
                        }
                    ],
                }
            ],
        }

    def test_a_call_is_named_for_its_place_and_follows_the_one_before_it(
        self,
    ) -> None:
        halving = _built()["halving"]

        assert _calls(halving, "message_id") == [
            "msg_0001",
            "msg_0002",
            "msg_0003",
            "msg_0004",
            "msg_0005",
            "msg_0006",
        ]
        assert _calls(halving, "predecessor") == [
            None,
            "msg_0001",
            "msg_0002",
            "msg_0003",
            "msg_0004",
            "msg_0005",
        ]
        assert _calls(halving, "prompt") == [1, 1, 1, 1, 1, 1]

    def test_a_call_as_the_file_has_it(self) -> None:
        call = _built()["halving"]["calls"][2]

        assert call == {
            "message_id": "msg_0003",
            "prompt": 1,
            "predecessor": "msg_0002",
            "completed_at": _at(92),
            "model": "claude-opus-4-5",
            "effort": "high",
            "attributed_skill": "pantry:scaling",
            "attributed_plugin": "pantry",
            "tokens": {
                "input": 9,
                "cache_write_1h": 2_480,
                "cache_read": 23_700,
                "output": 402,
            },
            "tool_calls": [
                {
                    "tool_use_id": "toolu_0003",
                    "tool": "mcp__pantry__list_recipes",
                    "mcp_server": "pantry",
                    "first_argument": "stew",
                    "requested_at": _at(92),
                    "returned_at": _at(93),
                    "failed": False,
                    "interrupted": False,
                    "result_characters": 312,
                },
                {
                    "tool_use_id": "toolu_0004",
                    "tool": "Bash",
                    "first_argument": "python scale.py stew 0.5",
                    "requested_at": _at(92),
                    "returned_at": _at(95),
                    "failed": True,
                    "exit_code": 2,
                    "interrupted": False,
                    "result_characters": 420,
                },
            ],
            "events": [
                {"kind": "api_error", "is_error": True, "at": _at(101), "detail": "529"}
            ],
            "context_parts": [
                {"kind": "skill_body", "name": "pantry:scaling", "characters": 4_300}
            ],
        }

    def test_a_compaction_is_crossed_by_the_call_after_it_alone(self) -> None:
        halving = _built()["halving"]

        assert halving["compactions"] == [
            {
                "at": _at(150),
                "trigger": "auto",
                "tokens_before": 160_400,
                "tokens_after": 21_300,
                "duration_ms": 38_000,
            }
        ]
        assert _calls(halving, "compaction") == [None, None, None, None, 1, None]
        assert _calls(halving, "miss_cause") == [
            None,
            None,
            None,
            None,
            "compaction",
            None,
        ]

    def test_a_rewind_follows_the_call_it_went_back_to(self) -> None:
        gears = _built()["gears"]

        assert _calls(gears, "predecessor") == [
            None,
            "msg_0001",
            "msg_0002",
            "msg_0002",
            "msg_0004",
        ]
        assert _calls(gears, "miss_cause") == [None, None, None, "rewind", "ttl"]

    def test_a_calls_prompt_is_its_place_among_the_threads(self) -> None:
        gears = _built()["gears"]

        assert _calls(gears, "prompt") == [1, 1, 2, 3, 4]
        assert [
            prompt["received_at"] for prompt in gears["launches"][0]["prompts"]
        ] == [_at(300), _at(350), _at(390), _at(960)]

    def test_a_session_a_person_ran_names_where_it_ran(self) -> None:
        gears = _built()["gears"]

        assert (gears["environment"], gears["repository"]) == (
            "ada-bikelog-3c9e1f",
            "BikeLog",
        )
        assert gears["working_directory"] == "/work/BikeLog"
        assert "agent_id" not in gears

    def test_a_session_of_a_group_names_it_on_its_main_thread(self) -> None:
        built = _built()

        assert built["gears"]["group"] == {
            "key": "bike-log-first-rides",
            "name": "Bike log: the first rides",
            "summary": (
                "The gear tables and ride notes Ada kept by hand, before Pilot kept"
                " the log."
            ),
        }
        assert "group" not in built["halving"]
        assert "group" not in built["counting"]

    def test_prompts_are_counted_through_the_launches(self) -> None:
        """A thread a process resumed: its second Launch's Prompt is the
        thread's second, and each Launch ends at its own last line."""
        resumed = Scenario(
            name="resumed",
            people=("ada",),
            projects=(),
            kinds=(),
            units=(),
            sessions=(
                Session(
                    name="resumed",
                    directory="/work/BikeLog",
                    size=2_048,
                    person="ada",
                    launches=(
                        Launch(
                            at=0,
                            versions=(("claude-code", "2.1.317"),),
                            prompts=(
                                Prompt(
                                    at=0,
                                    source="person",
                                    characters=20,
                                    steps=(
                                        Call(
                                            at=5,
                                            tokens=Tokens(input=10),
                                            tools=(ToolUse("Bash", "sleep 600"),),
                                        ),
                                    ),
                                ),
                            ),
                        ),
                        Launch(
                            at=40,
                            versions=(("claude-code", "2.1.318"),),
                            prompts=(
                                Prompt(
                                    at=41,
                                    source="person",
                                    characters=12,
                                    steps=(
                                        Compaction(at=44, trigger="manual", before=900),
                                        Call(at=50, tokens=Tokens(output=3)),
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )

        (publication,) = Builder(resumed, UNTIL).publications()

        def at(moment: int) -> str:
            return (UNTIL - timedelta(seconds=50 - moment)).isoformat()

        assert [
            (launch["started_at"], launch["ended_at"])
            for launch in publication["launches"]
        ] == [(at(0), at(5)), (at(40), at(50))]
        assert _calls(publication, "prompt") == [1, 2]
        assert _calls(publication, "compaction") == [None, 1]
        assert publication["compactions"] == [
            {"at": at(44), "trigger": "manual", "tokens_before": 900}
        ]
        assert publication["calls"][0]["tool_calls"] == [
            {
                "tool_use_id": "toolu_0001",
                "tool": "Bash",
                "first_argument": "sleep 600",
                "requested_at": at(5),
                "failed": False,
                "interrupted": False,
            }
        ]
        assert publication["calls"][1]["tokens"] == {"output": 3}
        assert "environment" not in publication
        assert "repository" not in publication


class TestASubAgent:
    def test_it_names_the_call_that_started_it(self) -> None:
        built = _built()
        (spawning,) = [
            tool_call
            for call in built["halving"]["calls"]
            for tool_call in call.get("tool_calls", [])
            if tool_call["tool"] == "Agent"
        ]

        assert spawning["tool_use_id"] == "toolu_0002"
        assert built["counting"]["spawned_by"] == "toolu_0002"
        assert built["counting"]["description"] == spawning["first_argument"]
        assert built["counting"]["agent_type"] == "Explore"

    def test_its_ids_repeat_none_of_its_main_threads(self) -> None:
        """A conversation's threads name their messages and tool calls
        through all of them, as Claude's own ids never repeat: a sub-agent
        holding its main thread's tool_use_id is joined to no call."""
        built = _built()

        def ids(thread: dict[str, Any]) -> tuple[set[str], set[str]]:
            return set(_calls(thread, "message_id")), {
                tool_call["tool_use_id"]
                for call in thread["calls"]
                for tool_call in call.get("tool_calls", [])
            }

        (main_messages, main_tools), (agent_messages, agent_tools) = (
            ids(built["halving"]),
            ids(built["counting"]),
        )
        assert agent_messages and agent_tools
        assert not main_messages & agent_messages
        assert not main_tools & agent_tools

    def test_it_is_a_thread_of_its_sessions_conversation(self) -> None:
        built = _built()

        assert built["counting"]["session_id"] == built["halving"]["session_id"]
        assert built["counting"]["working_directory"] == "/work/RecipeBox"
        assert built["counting"]["repository"] == "RecipeBox"
        assert built["counting"]["file_size"] == 9_480
        assert built["counting"]["file_modified_at"] == _at(74)

    def test_it_has_no_launch_no_prompt_and_no_environment(self) -> None:
        counting = _built()["counting"]

        assert "launches" not in counting
        assert "environment" not in counting
        assert _calls(counting, "prompt") == [None, None, None]
        assert _calls(counting, "model") == ["claude-haiku-4-5-20251001"] * 3

    def test_it_runs_while_its_spawning_call_waits(self) -> None:
        built = _built()
        spawning = built["halving"]["calls"][1]["tool_calls"][0]

        assert spawning["requested_at"] == _at(33)
        assert spawning["returned_at"] == _at(78)
        assert _calls(built["counting"], "completed_at") == [_at(46), _at(58), _at(74)]


class TestTheTurnsOfPilots:
    def test_the_turn_a_session_ran_under(self) -> None:
        builder = Builder(SCENARIO, UNTIL)

        assert builder.turns() == [
            SentTurn(
                project="recipe-box",
                conversation=builder.conversation(SCENARIO.sessions[0]),
                directory="/work/RecipeBox",
                environment="ben-recipebox-51f0c2",
                message="Halve the stew: it serves eight, and the pot holds four.",
                sent_at=UNTIL - timedelta(seconds=LENGTH),
                ended_at=UNTIL - timedelta(seconds=LENGTH - 224),
            )
        ]

    def test_it_is_sent_before_its_conversations_launch_starts(self) -> None:
        builder = Builder(SCENARIO, UNTIL)
        (turn,) = builder.turns()
        halving = builder.publications()[0]

        assert turn.conversation == halving["session_id"]
        assert turn.sent_at.isoformat() <= halving["launches"][0]["started_at"]
        assert halving["launches"][0]["started_at"] <= turn.ended_at.isoformat()


class TestThePackage:
    def test_it_imports_nothing_but_the_standard_library(self) -> None:
        source = Path(pilot_scenario.__file__).parent
        imported: set[str] = set()
        for module in source.glob("*.py"):
            for node in ast.walk(ast.parse(module.read_text())):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    assert node.module is not None
                    imported.add(node.module.split(".")[0])

        assert "pilot_scenario" in imported
        assert imported - {"pilot_scenario"} <= sys.stdlib_module_names
