"""The builder: a scenario's conversations as a collector publishes them
whole, the Turns of Pilot's its sessions ran under, the ids it gives them and
its times laid back from its last moment (F122.2). What its files say is
`test_transcript.py`'s."""

import ast
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pilot_scenario
import pytest
from pilot_scenario import COLLECTOR, SCENARIO, Builder, Scenario, SentTurn, labeller
from pilot_scenario.script import (
    Call,
    Carried,
    Compaction,
    Launch,
    Occurrence,
    Prompt,
    Retry,
    Session,
    SubAgent,
    Tokens,
    ToolUse,
)
from pilot_scenario.transcript import stamp

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


def _one(*steps: Call | Compaction) -> Scenario:
    """A scenario of one session a person typed one prompt in, the steps
    following it."""
    prompt = Prompt(at=0, source="typed", characters=20, steps=steps)
    return Scenario(
        name="one",
        people=("ada",),
        projects=(),
        kinds=(),
        units=(),
        sessions=(
            Session(
                name="one",
                directory="/tmp/rides",
                person="ada",
                launches=(
                    Launch(versions=(("claude-code", "2.1.317"),), prompts=(prompt,)),
                ),
            ),
        ),
    )


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

    def test_its_last_moment_is_cut_to_the_millisecond_a_line_is_written_to(
        self,
    ) -> None:
        later = Builder(SCENARIO, UNTIL + timedelta(microseconds=123_987))

        assert later.when(LENGTH) == UNTIL + timedelta(milliseconds=123)

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
            if name
            not in ("session_id", "launches", "compactions", "calls", "labelling")
        } == {
            "file_size": len(Builder(SCENARIO, UNTIL).files()[0].content),
            "file_modified_at": _at(221),
            "collector": {"version": "1.4.0"},
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
                    "source": "sdk",
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
            "sent_at": _at(79),
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
                    "tool_use_id": "toolu_0004",
                    "tool": "mcp__pantry__list_recipes",
                    "mcp_server": "pantry",
                    "first_argument": "stew",
                    "requested_at": _at(92),
                    "returned_at": _at(93),
                    "failed": False,
                    "interrupted": False,
                    "result_characters": 1_240,
                    "saved_characters": 48_300,
                },
                {
                    "tool_use_id": "toolu_0005",
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
                {"kind": "api_retry", "is_error": True, "at": _at(101), "detail": "529"}
            ],
            "context_parts": [
                {"kind": "skill_body", "name": "pantry:scaling", "characters": 4_300}
            ],
        }

    def test_a_launchs_first_call_carries_the_prompts_received_before_it(
        self,
    ) -> None:
        """Beside its system prompt, its tools, its instruction files and
        what was injected before it, as the script has them; no later Call
        carries a Prompt."""
        first, *later = _built()["halving"]["calls"]
        waited = Prompt(at=0, source="typed", characters=20)
        answered = Prompt(
            at=5, source="typed", characters=12, steps=(Call(at=9, tokens=Tokens()),)
        )
        session = replace(
            _one().sessions[0],
            launches=(
                Launch(
                    versions=(("claude-code", "2.1.317"),), prompts=(waited, answered)
                ),
            ),
        )
        (two,) = Builder(replace(_one(), sessions=(session,)), UNTIL).publications()

        assert first["context_parts"] == [
            {"kind": "system_prompt", "characters": 9_100},
            {"kind": "tool_schemas", "characters": 45_200},
            {
                "kind": "instruction_file",
                "name": "/etc/claude-code/CLAUDE.md",
                "characters": 2_350,
            },
            {
                "kind": "instruction_file",
                "name": "/work/RecipeBox/CLAUDE.md",
                "characters": 3_750,
            },
            {"kind": "reminder", "name": "skill_listing", "characters": 2_870},
            {"kind": "reminder", "name": "date", "characters": 96},
            {"kind": "prompt", "characters": 412},
        ]
        assert not any(
            part["kind"] == "prompt"
            for call in later
            for part in call.get("context_parts", [])
        )
        assert two["calls"][0]["context_parts"] == [
            {"kind": "prompt", "characters": 20},
            {"kind": "prompt", "characters": 12},
        ]

    def test_a_call_was_sent_at_its_moment_before_it_completed(self) -> None:
        halving = _built()["halving"]

        assert _calls(halving, "sent_at") == [
            _at(5),
            _at(21),
            _at(79),
            _at(102),
            _at(151),
            _at(208),
        ]
        assert all(
            call["sent_at"] < call["completed_at"]
            for publication in _built().values()
            for call in publication["calls"]
        )

    def test_a_calls_own_choices_are_the_scripts(self) -> None:
        """A model asked for where a fallback had another answer, and an end
        that was no ordinary one."""
        counting = _built()["counting"]

        assert _calls(counting, "model") == ["claude-haiku-4-5-20251001"] * 3
        assert _calls(counting, "requested_model") == [None, "claude-opus-4-5", None]
        assert _calls(counting, "stop_reason") == [None, None, "max_tokens"]
        assert _calls(_built()["halving"], "thinking_tokens") == [
            188,
            None,
            None,
            None,
            None,
            None,
        ]

    def test_an_event_is_on_the_last_call_before_it_else_on_the_first(
        self,
    ) -> None:
        """A failed attempt at a request is before the Call that answered
        it, and an occurrence after its own."""
        scenario = _one(
            Call(
                at=6,
                sent=5,
                retried=(Retry(sent=2, failed=3, status=529), Retry(sent=4, failed=4)),
                tokens=Tokens(input=10, output=2),
                occurred=(Occurrence(7, "interrupt"),),
            ),
            Call(
                at=12,
                sent=10,
                retried=(Retry(sent=8, failed=9, status=500),),
                tokens=Tokens(input=10, output=2),
                occurred=(Occurrence(13, "api_error", detail="429"),),
            ),
        )
        first, second = Builder(scenario, UNTIL).publications()[0]["calls"]

        def at(moment: int) -> str:
            return Builder(scenario, UNTIL).time(moment)

        assert first["events"] == [
            {"kind": "api_retry", "is_error": True, "at": at(3), "detail": "529"},
            {"kind": "api_retry", "is_error": True, "at": at(4)},
            {"kind": "interrupt", "is_error": False, "at": at(7)},
            {"kind": "api_retry", "is_error": True, "at": at(9), "detail": "500"},
        ]
        assert second["events"] == [
            {"kind": "api_error", "is_error": True, "at": at(13), "detail": "429"}
        ]

    def test_a_call_the_script_marks_with_a_miss_and_no_other_is_one(self) -> None:
        """Assertion 546: more than half of the lesser of what its
        predecessor left and its own context was not read from the cache,
        and that context is at least nine tenths of what was left."""
        for publication in Builder(SCENARIO, UNTIL).publications():
            calls = {call["message_id"]: call for call in publication["calls"]}
            for call in publication["calls"]:
                spent = call["tokens"]
                context = sum(
                    spent.get(kind, 0)
                    for kind in (
                        "input",
                        "cache_write_5m",
                        "cache_write_1h",
                        "cache_read",
                    )
                )
                missed = False
                if "predecessor" in call:
                    before = calls[call["predecessor"]]["tokens"]
                    left = sum(
                        before.get(kind, 0)
                        for kind in ("cache_write_5m", "cache_write_1h", "cache_read")
                    )
                    compared = min(left, context)
                    unread = compared - spent.get("cache_read", 0)
                    missed = 2 * unread > compared and 10 * context >= 9 * left
                assert ("miss_cause" in call) is missed, call["message_id"]

    def test_a_command_the_person_interrupted_says_so(self) -> None:
        gears = _built()["gears"]

        assert gears["calls"][2]["tool_calls"] == [
            {
                "tool_use_id": "toolu_0002",
                "tool": "Bash",
                "first_argument": "python ratios.py --every-gear",
                "requested_at": _at(362),
                "returned_at": _at(371),
                "failed": False,
                "interrupted": True,
                "result_characters": 148,
            }
        ]

    def test_a_denied_call_names_its_denial_and_failed(self) -> None:
        built = _built()

        assert [
            (asked["tool_use_id"], asked["denial_kind"], asked["failed"])
            for thread in ("counting", "gears")
            for call in built[thread]["calls"]
            for asked in call.get("tool_calls", [])
            if "denial_kind" in asked
        ] == [
            ("toolu_0010", "hook", True),
            ("toolu_0011", "rule", True),
            ("toolu_0003", "person", True),
        ]

    def test_a_prompts_hook_runs_are_the_scripts(self) -> None:
        gears = _built()["gears"]

        assert gears["launches"][0]["prompts"][0]["hook_runs"] == [
            {
                "command": "log_ride.sh",
                "duration_ms": 40,
                "failed": False,
                "prevented_end": False,
            },
            {
                "command": "sync_notes.sh",
                "duration_ms": 1_210,
                "failed": True,
                "prevented_end": False,
            },
        ]

    def test_a_prompts_source_is_in_claude_codes_word(self) -> None:
        built = _built()

        assert [
            prompt["source"]
            for thread in ("halving", "gears")
            for launch in built[thread]["launches"]
            for prompt in launch["prompts"]
        ] == ["sdk", "typed", "typed", "typed", "typed"]

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

    def test_a_session_of_a_group_names_it_on_its_main_thread_as_the_stub_adopts_it(
        self,
    ) -> None:
        """A group is a label, the stub labeller's adoption of the main
        thread, which a publication carries with its labelling."""
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

    def test_a_launch_ends_at_its_last_lines_time_whatever_came_before(
        self,
    ) -> None:
        """A tool that took longer returns before one requested after it
        that took less, whose result is the last line."""
        call = Call(
            at=5,
            tokens=Tokens(input=10),
            tools=(
                ToolUse("Bash", "sleep 6", took=6, characters=40),
                ToolUse("Read", "rides/gears.md", took=1, characters=40),
            ),
        )

        (publication,) = Builder(_one(call), UNTIL).publications()

        def at(moment: int) -> str:
            return (UNTIL - timedelta(seconds=11 - moment)).isoformat()

        (launch,) = publication["launches"]
        assert (launch["started_at"], launch["ended_at"]) == (at(0), at(6))

    def test_a_launch_names_each_plugin_a_skill_of_it_loaded_after_claude_code(
        self,
    ) -> None:
        scaling = Call(
            at=5,
            tokens=Tokens(input=10),
            tools=(
                ToolUse("Skill", "pantry:scaling", took=1, characters=31),
                ToolUse("Skill", "notes", took=1, characters=22),
            ),
        )
        loaded = Call(
            at=9,
            tokens=Tokens(input=4),
            carried=(
                Carried("skill_body", 400, "notes"),
                Carried("skill_body", 400, "pantry:scaling"),
            ),
        )
        scenario = _one(scaling, loaded)
        session = scenario.sessions[0]
        (launch,) = session.launches
        runs = (("plugin:pantry", "0.3.1"), *launch.versions)
        scenario = replace(
            scenario,
            sessions=(replace(session, launches=(replace(launch, versions=runs),)),),
        )

        (publication,) = Builder(scenario, UNTIL).publications()

        assert publication["launches"][0]["components"] == [
            {"component": "claude-code", "version": "2.1.317"},
            {"component": "plugin:pantry", "version": "0.3.1"},
        ]

    @pytest.mark.parametrize(
        ("versions", "refused"),
        [
            (
                (("claude-code", "2.1.317"),),
                "its Launch names `plugin:pantry`",
            ),
            (
                (
                    ("claude-code", "2.1.317"),
                    ("plugin:pantry", "0.3.1"),
                    ("plugin:notes", "1.0.0"),
                ),
                "no line names `plugin:notes`",
            ),
            (
                (("claude-code", "2.1.317"), ("plugin:pantry", "0.3.1"), ("cli", "1")),
                "no line names `cli`",
            ),
        ],
        ids=[
            "a plugin's skill its Launch runs no version of",
            "a plugin no skill of is loaded",
            "a component no line names",
        ],
    )
    def test_a_component_its_lines_do_not_name_is_refused(
        self, versions: tuple[tuple[str, str], ...], refused: str
    ) -> None:
        call = Call(
            at=5,
            tokens=Tokens(input=10),
            tools=(ToolUse("Skill", "pantry:scaling", took=1, characters=31),),
        )
        loaded = Call(
            at=9,
            tokens=Tokens(input=4),
            carried=(Carried("skill_body", 400, "pantry:scaling"),),
        )
        scenario = _one(call, loaded)
        session = scenario.sessions[0]
        (launch,) = session.launches
        scenario = replace(
            scenario,
            sessions=(
                replace(session, launches=(replace(launch, versions=versions),)),
            ),
        )

        with pytest.raises(ValueError, match=refused):
            Builder(scenario, UNTIL).publications()

    def test_a_killed_process_ends_at_its_last_line_and_the_next_starts_a_launch(
        self,
    ) -> None:
        first = Launch(
            versions=(("claude-code", "2.1.317"),),
            prompts=(
                Prompt(
                    at=0,
                    source="typed",
                    characters=20,
                    steps=(Call(at=5, tokens=Tokens(input=10)),),
                ),
            ),
            killed=True,
        )
        later = Launch(
            versions=(("claude-code", "2.1.318"),),
            prompts=(
                Prompt(
                    at=40,
                    source="sdk",
                    characters=12,
                    steps=(Call(at=44, tokens=Tokens(input=4)),),
                ),
            ),
        )
        scenario = _one()
        session = scenario.sessions[0]
        scenario = replace(
            scenario, sessions=(replace(session, launches=(first, later)),)
        )

        (publication,) = Builder(scenario, UNTIL).publications()

        def at(moment: int) -> str:
            return (UNTIL - timedelta(seconds=44 - moment)).isoformat()

        assert [
            (launch["started_at"], launch["ended_at"], launch["components"])
            for launch in publication["launches"]
        ] == [
            (at(0), at(5), [{"component": "claude-code", "version": "2.1.317"}]),
            (at(40), at(44), [{"component": "claude-code", "version": "2.1.318"}]),
        ]

    def test_a_process_after_a_killed_one_under_its_version_is_refused(
        self,
    ) -> None:
        """The two are one Launch in the file."""
        prompt = Prompt(at=0, source="typed", characters=20)
        scenario = _one()
        session = scenario.sessions[0]
        (launch,) = session.launches
        killed = replace(launch, prompts=(prompt,), killed=True)
        later = replace(launch, prompts=(replace(prompt, at=40),))
        scenario = replace(
            scenario, sessions=(replace(session, launches=(killed, later)),)
        )

        with pytest.raises(ValueError, match="joins its Launch"):
            Builder(scenario, UNTIL).publications()

    def test_prompts_are_counted_through_the_launches(self) -> None:
        """A thread a process resumed: its second Launch's Prompt is the
        thread's second, and each Launch starts as its first Prompt arrives
        and ends at its own last line."""
        resumed = Scenario(
            name="resumed",
            people=("ada",),
            projects=(),
            kinds=(),
            units=(),
            sessions=(
                Session(
                    name="resumed",
                    directory="/tmp/rides",
                    person="ada",
                    launches=(
                        Launch(
                            versions=(("claude-code", "2.1.317"),),
                            prompts=(
                                Prompt(
                                    at=0,
                                    source="typed",
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
                            versions=(("claude-code", "2.1.318"),),
                            prompts=(
                                Prompt(
                                    at=41,
                                    source="queued",
                                    characters=12,
                                    steps=(
                                        Compaction(at=44, trigger="manual", before=900),
                                        Call(
                                            at=50,
                                            tokens=Tokens(output=3),
                                            carried=(Carried("compact_summary", 640),),
                                        ),
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
        ] == [(at(0), at(5)), (at(41), at(50))]
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


def _nested(*order: str) -> Scenario:
    """A scenario of one session whose main thread's call starts `tracing`,
    and a call of `tracing`'s `counting`, the sub-agents in that `order`."""
    agents = {
        "tracing": SubAgent(
            name="tracing",
            type="general-purpose",
            steps=(
                Call(
                    at=8,
                    tokens=Tokens(input=40, output=6),
                    tools=(
                        ToolUse(
                            "Agent",
                            "Count the spokes",
                            took=10,
                            characters=90,
                            spawns="counting",
                        ),
                    ),
                ),
            ),
        ),
        "counting": SubAgent(
            name="counting",
            type="Explore",
            steps=(Call(at=12, tokens=Tokens(input=30, output=2)),),
        ),
    }
    agent = ToolUse(
        "Agent", "Trace the chain", took=30, characters=200, spawns="tracing"
    )
    scenario = _one(Call(at=4, tokens=Tokens(input=20, output=5), tools=(agent,)))
    (session,) = scenario.sessions
    started = replace(session, sub_agents=tuple(agents[name] for name in order))
    return replace(scenario, sessions=(started,))


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

    def test_one_a_sub_agents_call_started_names_that_call(self) -> None:
        main, tracing, counting = Builder(
            _nested("tracing", "counting"), UNTIL
        ).publications()

        (started,) = tracing["calls"][0]["tool_calls"]
        assert tracing["spawned_by"] == main["calls"][0]["tool_calls"][0]["tool_use_id"]
        assert counting["spawned_by"] == started["tool_use_id"]
        assert (
            counting["description"] == started["first_argument"] == "Count the spokes"
        )
        assert counting["agent_type"] == "Explore"

    def test_one_no_thread_before_it_starts_is_refused(self) -> None:
        with pytest.raises(ValueError, match="none starts `counting`"):
            Builder(_nested("counting", "tracing"), UNTIL).publications()

    def test_its_first_call_carries_its_task(self) -> None:
        first, *later = _built()["counting"]["calls"]

        assert first["context_parts"][-1] == {"kind": "prompt", "characters": 220}
        assert not any("context_parts" in call for call in later)

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
        assert _calls(built["counting"], "sent_at") == [_at(34), _at(49), _at(60)]


HALVING = "8766dbc8-267a-5322-9a1d-cc49ad56eedd"
GEARS = "037915e7-de88-5550-9746-3e7a4472413a"
STEW = "recipe-box|Scale the recipes|Halve the stew"
"""The key of the unit the halving ran."""


class TestItsLabels:
    def test_every_thread_carries_the_stubs_labelling_of_its_file(self) -> None:
        """What a collector publishes under the stub, where Pilot hands
        nothing for the conversation: the `label` line's stamp, labels,
        units, suites and builds under the stub's version, but for the
        transcript's own label, which is the `group`, and the batchable
        condition, which the record keeps no place for."""
        builder = Builder(SCENARIO, UNTIL)
        publications = builder.publications()
        contents = [
            file.content for file in builder.files() if file.path.endswith(".jsonl")
        ]

        for publication, content in zip(publications, contents, strict=True):
            main = "agent_id" not in publication
            handed = {
                "agent_id": publication.get("agent_id"),
                "mode": "whole",
                "calls": [
                    {
                        "id": call["message_id"],
                        "position": n,
                        "launch": 1 if main else None,
                    }
                    for n, call in enumerate(publication["calls"], start=1)
                ],
                "launches": [
                    {"n": 1, "started_at": publication["launches"][0]["started_at"]}
                ]
                if main
                else [],
            }
            if not main:
                handed["agent_type"] = publication["agent_type"]
            answer = labeller.label(
                content,
                handed,
                {"session_id": publication["session_id"]},
                frozenset(),
                builder.records(),
            )
            labelling = publication["labelling"]
            assert labelling["version"] == labeller.VERSION
            assert labelling["stamp"] == answer["stamp"]
            assert set(labelling["labels"]) == set(answer["labels"]) - {"transcript"}
            assert labelling["labels"]["calls"] == [
                {
                    name: label
                    for name, label in call.items()
                    if name != "batchable_condition"
                }
                for call in answer["labels"]["calls"]
            ]
            for name in ("launches", "segments", "tool_calls", "events", "documents"):
                assert labelling["labels"][name] == answer["labels"][name]
            for name in ("units", "test_suites", "ci_builds"):
                assert labelling[name] == answer[name]

    def test_the_halvings_labels_are_the_scenarios_own(self) -> None:
        halving = _built()["halving"]["labelling"]

        assert halving["labels"]["launches"] == [{"n": 1, "work_unit": STEW}]
        assert [unit["key"] for unit in halving["units"]] == [
            "recipe-box|Scale the recipes",
            STEW,
        ]
        assert [
            (call["call_class"], call["segment"], call["wait_cause"])
            for call in halving["labels"]["calls"]
        ] == [
            ("look", 1, "lighting"),
            ("send", 2, "stove"),
            ("spill", 2, "helper"),
            ("stir", 2, "stove"),
            ("run", 3, "stove"),
            ("muse", 4, "stove"),
        ]
        assert halving["labels"]["segments"] == [
            {"position": 1, "kind": "prep"},
            {"position": 2, "kind": "cook"},
            {"position": 3, "kind": "simmer"},
            {"position": 4, "kind": "cook"},
        ]
        assert halving["labels"]["events"] == [
            {
                "call": "msg_0003",
                "kind": "burnt",
                "at": stamp(datetime.fromisoformat(_at(95))),
                "detail": "scale.py",
            }
        ]

    def test_a_line_claude_code_wrote_itself_is_handed_and_its_labels_left_out(
        self,
    ) -> None:
        """The labeller counts each assistant line's message as a Call, a
        request that failed for good among them, which the publication holds
        as an Event of the Call before it: its labels are not the
        publication's, and every Call it holds names a Segment."""
        scenario = _one(
            Call(
                at=6,
                tokens=Tokens(input=10, output=2),
                occurred=(Occurrence(7, "api_error", detail="429"),),
            ),
            Call(at=12, tokens=Tokens(input=10, output=2)),
        )

        (publication,) = Builder(scenario, UNTIL).publications()

        labels = publication["labelling"]["labels"]
        assert [call["id"] for call in labels["calls"]] == ["msg_0001", "msg_0002"]
        assert [call["segment"] for call in labels["calls"]] == [1, 1]
        assert labels["segments"] == [{"position": 1, "kind": "cook"}]

    def test_a_sub_agent_carries_no_unit_and_its_breach_of_a_rule(self) -> None:
        counting = _built()["counting"]["labelling"]

        assert counting["labels"]["launches"] == []
        assert counting["units"] == []
        assert [
            (row["command_class"], row["rules"])
            for row in counting["labels"]["tool_calls"]
        ] == [("search", []), (None, ["no_pantry_token"]), ("fetch", [])]

    def test_its_run_records_are_its_units_what_ran_them_and_its_groups(self) -> None:
        assert Builder(SCENARIO, UNTIL).records() == {
            "kinds": ["errand", "leg"],
            "units": [
                {
                    "key": "recipe-box|Scale the recipes",
                    "kind": "errand",
                    "title": "Scale the recipes",
                    "part_of": None,
                    "measures": [{"measure": "parts", "amount": 2}],
                },
                {
                    "key": STEW,
                    "kind": "leg",
                    "title": "Halve the stew",
                    "part_of": "recipe-box|Scale the recipes",
                    "started_at": _at(0),
                    "ended_at": _at(224),
                    "outcome": labeller.SERVED,
                },
                {
                    "key": "recipe-box|Scale the recipes|Halve the dumplings",
                    "kind": "leg",
                    "title": "Halve the dumplings",
                    "part_of": "recipe-box|Scale the recipes",
                },
            ],
            "ran": {HALVING: STEW},
            "groups": [
                {
                    "key": "bike-log-first-rides",
                    "name": "Bike log: the first rides",
                    "summary": (
                        "The gear tables and ride notes Ada kept by hand, before"
                        " Pilot kept the log."
                    ),
                    "repository": "BikeLog",
                    "conversations": [GEARS],
                }
            ],
        }

    def test_they_are_written_where_the_stub_reads_them(self, tmp_path: Path) -> None:
        builder = Builder(SCENARIO, UNTIL)

        builder.write(tmp_path)

        held = tmp_path / "plugins" / "data" / labeller.DATA / labeller.RECORDS
        assert json.loads(held.read_text()) == builder.records()

    def test_its_vocabularies_are_the_stubs_as_a_collector_declares_them(
        self,
    ) -> None:
        """Every list the record keeps, the kinds of work the scenario's,
        and the nestings; the groups and the batchable condition left
        out."""
        builder = Builder(SCENARIO, UNTIL)
        declared = labeller.vocabularies(builder.records())

        vocabularies = builder.vocabularies()

        assert set(vocabularies) == {"version", "lists", "nesting"}
        assert vocabularies["version"] == labeller.VERSION
        assert set(vocabularies["lists"]) == set(declared["lists"]) - {
            "batchable_condition"
        }
        assert [kind["code"] for kind in vocabularies["lists"]["work_unit_kind"]] == [
            "errand",
            "leg",
        ]
        assert vocabularies["nesting"] == [{"inner": "leg", "outer": "errand"}]


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
