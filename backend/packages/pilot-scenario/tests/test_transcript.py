"""The scenario as transcript files (F122.3): each thread a file in Claude
Code's line shapes, in a home laid out as the fleet's is, and each
publication what its file says: read back off the lines here, a thread's
ids and place, its Launches, Prompts, Calls and Tool Calls are the
publication's."""

import json
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pilot_scenario import SCENARIO, Builder, HomeFile, Scenario
from pilot_scenario.script import Call, Launch, Prompt, Session, Tokens, ToolUse
from pilot_scenario.transcript import folder, stamp, text

UNTIL = datetime(2026, 11, 12, 9, 30, 0, 250_000, tzinfo=UTC)

HALVING = "8766dbc8-267a-5322-9a1d-cc49ad56eedd"
COUNTING = "6d6212072d4d5b429"
GEARS = "037915e7-de88-5550-9746-3e7a4472413a"

SAVED = re.compile(
    r"<persisted-output>\nOutput too large \([\d.]+KB\)\. Full output saved to: (\S+)\n"
)
SAVED_STATED = re.compile(
    r"Error: result \(([\d,]+) characters\) exceeds maximum allowed tokens\."
    r" Output has been saved to (\S+)\.\n"
)

FACTS = {
    "session_id",
    "agent_id",
    "file_size",
    "file_modified_at",
    "working_directory",
    "environment",
}
"""What a publication says of its thread that its file's name, size, time
and lines say."""

CALL_FACTS = ("message_id", "prompt", "completed_at", "model", "tokens")
TOOL_CALL_FACTS = (
    "tool_use_id",
    "tool",
    "mcp_server",
    "first_argument",
    "requested_at",
    "returned_at",
    "failed",
    "exit_code",
    "interrupted",
    "result_characters",
    "saved_characters",
)


def _lines(file: HomeFile) -> list[dict[str, Any]]:
    return [json.loads(line) for line in file.content.splitlines()]


def _transcripts(builder: Builder) -> list[HomeFile]:
    return [file for file in builder.files() if file.path.endswith(".jsonl")]


def _time(line: dict[str, Any]) -> str:
    """A line's time as a publication writes one."""
    return datetime.fromisoformat(line["timestamp"]).isoformat()


def _blocks(line: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    content = line.get("message", {}).get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if block["type"] == kind]


def _tool_call(
    asked: dict[str, Any],
    requested: dict[str, Any],
    result: dict[str, Any] | None,
    home: dict[str, HomeFile],
) -> dict[str, Any]:
    """A Tool Call read off its request's block and line and its result's
    line."""
    read: dict[str, Any] = {
        "tool_use_id": asked["id"],
        "tool": asked["name"],
        "requested_at": _time(requested),
        "failed": False,
        "interrupted": False,
    }
    if asked["name"].startswith("mcp__"):
        read["mcp_server"] = asked["name"].split("__")[1]
    if asked["input"]:
        given = asked["input"]
        read["first_argument"] = (
            given["description"]
            if asked["name"] == "Agent"
            else next(iter(given.values()))
        )
    if result is None:
        return read
    (block,) = _blocks(result, "tool_result")
    said = block["content"]
    if isinstance(said, list):
        said = "".join(part["text"] for part in said)
    record = result["toolUseResult"]
    read |= {
        "returned_at": _time(result),
        "failed": block.get("is_error", False),
        "result_characters": len(said),
    }
    if asked["name"] == "Bash":
        exited = re.match(r"Exit code (-?\d+)", said) if read["failed"] else None
        if exited is not None:
            read["exit_code"] = int(exited.group(1))
        elif not read["failed"]:
            read["interrupted"] = record["interrupted"]
    if (saved := SAVED.match(said)) is not None:
        on_disk = home[saved.group(1).split("/.claude/")[1]]
        read["saved_characters"] = len(on_disk.content.decode())
    elif (stated := SAVED_STATED.match(said)) is not None:
        read["saved_characters"] = int(stated.group(1).replace(",", ""))
    return read


def _read(file: HomeFile, home: dict[str, HomeFile]) -> dict[str, Any]:
    """The facts of a thread as its file says them, in a publication's
    words: an independent reading, with none of the builder's code."""
    filed = re.fullmatch(
        r"projects/([^/]+)/([0-9a-f-]{36})(?:/subagents/agent-([0-9a-f]+))?\.jsonl",
        file.path,
    )
    assert filed is not None
    lines = _lines(file)
    read: dict[str, Any] = {
        "session_id": filed.group(2),
        "file_size": len(file.content),
        "file_modified_at": file.modified_at.isoformat(),
        "working_directory": next(line["cwd"] for line in lines if "cwd" in line),
    }
    assert filed.group(1) == folder(read["working_directory"])
    main = filed.group(3) is None
    if not main:
        read["agent_id"] = filed.group(3)
        assert {line["agentId"] for line in lines if "uuid" in line} == {
            read["agent_id"]
        }
    results = {
        block["tool_use_id"]: line
        for line in lines
        for block in _blocks(line, "tool_result")
    }
    launches: list[dict[str, Any]] = []
    calls: dict[str, dict[str, Any]] = {}
    exited, prompts, enqueued = True, 0, None
    for line in lines:
        if line["type"] == "cost-state":
            exited = True
        if "timestamp" not in line:
            continue
        if main and exited:
            launches.append(
                {
                    "started_at": _time(line),
                    "components": [
                        {"component": "claude-code", "version": line["version"]}
                    ]
                    if "version" in line
                    else None,
                    "prompts": [],
                }
            )
            exited = False
        if main and launches[-1]["components"] is None and "version" in line:
            launches[-1]["components"] = [
                {"component": "claude-code", "version": line["version"]}
            ]
        if line["type"] == "queue-operation" and line["operation"] == "enqueue":
            enqueued = line
        elif line["type"] == "attachment" and main:
            for instructions in line["attachment"]["files"]:
                named = re.match(r"# Environment: (\S+)\n", instructions["content"])
                if instructions["type"] == "Managed" and named is not None:
                    read.setdefault("environment", named.group(1))
        elif line["type"] == "user" and main and "promptSource" in line:
            said = line["message"]["content"]
            if enqueued is not None:
                assert enqueued["content"] == said
            prompts += 1
            launches[-1]["prompts"].append(
                {
                    "received_at": _time(enqueued or line),
                    "source": line["promptSource"],
                    "characters": len(said),
                }
            )
            enqueued = None
        elif line["type"] == "assistant":
            message = line["message"]
            call = calls.setdefault(
                message["id"], {"message_id": message["id"], "tool_calls": []}
            )
            if main:
                call.setdefault("prompt", prompts)
            spent = message["usage"]
            written = spent["cache_creation"]
            assert spent["cache_creation_input_tokens"] == sum(written.values())
            counted = {
                "input": spent["input_tokens"],
                "cache_write_5m": written["ephemeral_5m_input_tokens"],
                "cache_write_1h": written["ephemeral_1h_input_tokens"],
                "cache_read": spent["cache_read_input_tokens"],
                "output": spent["output_tokens"],
            }
            call |= {
                "completed_at": _time(line),
                "model": message["model"],
                "tokens": {kind: tokens for kind, tokens in counted.items() if tokens},
            }
            call["tool_calls"] += [
                _tool_call(asked, line, results.get(asked["id"]), home)
                for asked in _blocks(line, "tool_use")
            ]
    if main:
        read["launches"] = launches
    read["calls"] = list(calls.values())
    return read


def _facts(publication: dict[str, Any]) -> dict[str, Any]:
    """A publication cut to the facts its file's lines carry."""
    cut = {name: fact for name, fact in publication.items() if name in FACTS}
    if "launches" in publication:
        cut["launches"] = [
            {
                "started_at": launch["started_at"],
                "components": launch["components"][:1],
                "prompts": [
                    {
                        name: prompt[name]
                        for name in ("received_at", "source", "characters")
                    }
                    for prompt in launch["prompts"]
                ],
            }
            for launch in publication["launches"]
        ]
    cut["calls"] = [
        {name: call[name] for name in CALL_FACTS if name in call}
        | {
            "tool_calls": [
                {name: asked[name] for name in TOOL_CALL_FACTS if name in asked}
                for asked in call.get("tool_calls", [])
            ]
        }
        for call in publication["calls"]
    ]
    return cut


def _resumed() -> Scenario:
    """A thread two processes wrote, in a directory under no checkout,
    hosted by no environment: the second took a queued prompt, and went
    back to the first's Call."""
    return Scenario(
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
                                        name="the first",
                                        thinking=40,
                                        tokens=Tokens(input=10, output=9),
                                    ),
                                    Call(
                                        at=8,
                                        tokens=Tokens(input=4, output=2),
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
                                    Call(
                                        at=50,
                                        back_to="the first",
                                        tokens=Tokens(output=3),
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )


class TestTheHome:
    def test_a_thread_is_a_file_where_claude_code_files_it(self) -> None:
        assert [file.path for file in Builder(SCENARIO, UNTIL).files()] == [
            f"projects/-work-RecipeBox/{HALVING}.jsonl",
            f"projects/-work-RecipeBox/{HALVING}/tool-results"
            "/mcp-pantry-list_recipes-toolu_0003.txt",
            f"projects/-work-RecipeBox/{HALVING}/subagents/agent-{COUNTING}.jsonl",
            f"projects/-work-RecipeBox/{HALVING}/tool-results/toolu_0007.txt",
            f"projects/-work-BikeLog/{GEARS}.jsonl",
        ]

    def test_the_files_are_written_under_a_home_at_their_times(
        self, tmp_path: Path
    ) -> None:
        builder = Builder(SCENARIO, UNTIL)

        builder.write(tmp_path)

        written = sorted(
            str(path.relative_to(tmp_path))
            for path in tmp_path.rglob("*")
            if path.is_file()
        )
        assert written == sorted(file.path for file in builder.files())
        for file in builder.files():
            on_disk = tmp_path / file.path
            assert on_disk.read_bytes() == file.content
            assert on_disk.stat().st_mtime_ns == (
                (file.modified_at - datetime.fromtimestamp(0, UTC))
                // timedelta(microseconds=1)
                * 1000
            )

    def test_a_second_build_writes_the_same_files_but_for_their_times(self) -> None:
        first = Builder(SCENARIO, UNTIL).files()
        later = Builder(SCENARIO, UNTIL + timedelta(days=3)).files()

        assert [(file.path, len(file.content)) for file in first] == [
            (file.path, len(file.content)) for file in later
        ]
        assert first[0].content != later[0].content
        assert first[1].content == later[1].content

    def test_a_file_is_json_lines_each_an_object(self) -> None:
        for file in _transcripts(Builder(SCENARIO, UNTIL)):
            assert file.content.endswith(b"\n")
            assert all(isinstance(line, dict) for line in _lines(file))


class TestAPublicationIsWhatItsFileSays:
    @pytest.mark.parametrize(
        "scenario", [SCENARIO, _resumed()], ids=["the scenario", "a resumed thread"]
    )
    def test_each_thread_read_off_its_lines_is_its_publication(
        self, scenario: Scenario
    ) -> None:
        builder = Builder(scenario, UNTIL)
        home = {file.path: file for file in builder.files()}
        transcripts = _transcripts(builder)

        assert len(transcripts) == len(builder.publications())
        for file, publication in zip(transcripts, builder.publications(), strict=True):
            assert _read(file, home) == _facts(publication)

    def test_the_scenarios_threads_carry_each_fact_a_file_says(self) -> None:
        """The reading above proves nothing of a fact no thread has."""
        tool_calls = [
            tool_call
            for publication in Builder(SCENARIO, UNTIL).publications()
            for call in publication["calls"]
            for tool_call in call.get("tool_calls", [])
        ]

        assert {call["tool"] for call in tool_calls} >= {"Bash", "Read", "Agent"}
        assert any(call.get("mcp_server") for call in tool_calls)
        assert any(call["failed"] and call.get("exit_code") for call in tool_calls)
        assert any(call["interrupted"] for call in tool_calls)
        assert sorted(
            (call["tool"], call["saved_characters"])
            for call in tool_calls
            if "saved_characters" in call
        ) == [("Bash", 33_180), ("mcp__pantry__list_recipes", 48_300)]

    def test_a_saved_outputs_file_holds_the_characters_its_call_names(self) -> None:
        home = {file.path: file for file in Builder(SCENARIO, UNTIL).files()}
        stated = f"projects/-work-RecipeBox/{HALVING}/tool-results"

        assert len(home[f"{stated}/toolu_0007.txt"].content) == 33_180
        assert (
            len(home[f"{stated}/mcp-pantry-list_recipes-toolu_0003.txt"].content)
            == 48_300
        )

    def test_a_thread_under_no_checkout_and_no_environment_names_neither(
        self,
    ) -> None:
        builder = Builder(_resumed(), UNTIL)
        (file,) = builder.files()
        (publication,) = builder.publications()

        assert file.path.startswith("projects/-tmp-rides/")
        assert "environment" not in publication
        assert "repository" not in publication
        assert b"# Environment:" not in file.content


class TestTheLines:
    def test_a_line_of_the_chain_follows_the_one_before_it(self) -> None:
        for file in _transcripts(Builder(SCENARIO, UNTIL)):
            chain = [line for line in _lines(file) if "uuid" in line]
            seen: set[str] = set()
            assert chain[0]["parentUuid"] is None
            for line in chain[1:]:
                assert line["parentUuid"] in seen | {chain[0]["uuid"]}
                seen.add(line["uuid"])
            assert len({line["uuid"] for line in chain}) == len(chain)

    def test_a_line_beside_the_chain_carries_no_directory_and_the_queues_alone_a_time(
        self,
    ) -> None:
        (halving, _, _) = _transcripts(Builder(SCENARIO, UNTIL))

        beside = [line for line in _lines(halving) if "uuid" not in line]
        assert [line["type"] for line in beside] == [
            "permission-mode",
            "queue-operation",
            "queue-operation",
            "last-prompt",
            "cost-state",
        ]
        assert not any("cwd" in line for line in beside)
        assert [line["type"] for line in beside if "timestamp" in line] == [
            "queue-operation",
            "queue-operation",
        ]
        assert "cwd" not in _lines(halving)[0]

    def test_a_response_is_a_line_a_block_and_its_last_line_has_its_usage(
        self,
    ) -> None:
        builder = Builder(SCENARIO, UNTIL)
        first = [
            line
            for line in _lines(builder.files()[0])
            if line.get("message", {}).get("id") == "msg_0001"
        ]

        assert [line["message"]["content"][0]["type"] for line in first] == [
            "thinking",
            "text",
            "tool_use",
        ]
        assert [line["message"]["usage"]["output_tokens"] for line in first] == [
            77,
            77,
            310,
        ]
        assert [line["message"]["stop_reason"] for line in first] == [
            None,
            None,
            "tool_use",
        ]
        assert [line["timestamp"] for line in first] == [
            stamp(builder.when(19) - timedelta(milliseconds=80)),
            stamp(builder.when(19) - timedelta(milliseconds=40)),
            stamp(builder.when(19)),
        ]

    def test_a_time_is_written_in_utc_to_the_millisecond(self) -> None:
        assert stamp(UNTIL) == "2026-11-12T09:30:00.250Z"
        assert (
            stamp(datetime.fromisoformat("2026-11-12T10:30:00.250999+01:00"))
            == "2026-11-12T09:30:00.250Z"
        )

    def test_a_process_that_exits_writes_its_cost_line_and_the_next_starts_after_it(
        self,
    ) -> None:
        builder = Builder(_resumed(), UNTIL)
        lines = _lines(builder.files()[0])
        ends = [
            place for place, line in enumerate(lines) if line["type"] == "cost-state"
        ]

        assert len(ends) == 2 and ends[1] == len(lines) - 1
        after = lines[ends[0] + 1 :]
        assert [line["type"] for line in after[:4]] == [
            "permission-mode",
            "queue-operation",
            "queue-operation",
            "user",
        ]
        assert {line["version"] for line in after if "version" in line} == {"2.1.318"}
        assert {line["version"] for line in lines[: ends[0]] if "version" in line} == {
            "2.1.317"
        }

    def test_a_rewinds_prompt_follows_the_call_it_went_back_to(self) -> None:
        lines = _lines(Builder(_resumed(), UNTIL).files()[0])
        first = [
            line for line in lines if line.get("message", {}).get("id") == "msg_0001"
        ]
        (rewound,) = [line for line in lines if line.get("promptSource") == "queued"]

        assert rewound["parentUuid"] == first[-1]["uuid"]

    def test_a_tool_that_never_came_back_has_no_result_line(self) -> None:
        lines = _lines(Builder(_resumed(), UNTIL).files()[0])

        assert [block["name"] for line in lines for block in _blocks(line, "tool_use")]
        assert not [block for line in lines for block in _blocks(line, "tool_result")]

    def test_a_sub_agents_file_opens_with_its_task_and_names_it_on_every_line(
        self,
    ) -> None:
        builder = Builder(SCENARIO, UNTIL)
        main, counting, _ = _transcripts(builder)
        (spawning,) = [
            block
            for line in _lines(main)
            for block in _blocks(line, "tool_use")
            if block["name"] == "Agent"
        ]
        (result,) = [
            line
            for line in _lines(main)
            if isinstance(line.get("toolUseResult"), dict)
            and "agentId" in line["toolUseResult"]
        ]
        lines = _lines(counting)

        assert lines[0]["type"] == "user"
        assert lines[0]["message"]["content"] == spawning["input"]["prompt"]
        assert lines[0]["timestamp"] == stamp(builder.when(33))
        assert "promptSource" not in lines[0]
        assert all(line["isSidechain"] for line in lines)
        assert not any(line["type"] == "cost-state" for line in lines)
        assert result["toolUseResult"]["agentId"] == COUNTING
        assert spawning["input"]["subagent_type"] == "Explore"

    def test_a_sub_agents_file_names_the_environment_its_thread_does_not(
        self,
    ) -> None:
        """A sub-agent's process loads the managed instruction file too,
        and its thread is hosted by no environment."""
        builder = Builder(SCENARIO, UNTIL)
        _, counting, _ = _transcripts(builder)

        assert b"# Environment: ben-recipebox-51f0c2" in counting.content
        assert "environment" not in builder.publications()[1]

    def test_a_result_too_short_for_claude_codes_words_is_refused(self) -> None:
        session = _resumed().sessions[0]
        short = Prompt(
            at=0,
            source="typed",
            characters=20,
            steps=(
                Call(
                    at=5,
                    tokens=Tokens(input=10),
                    tools=(ToolUse("Bash", "ls", took=1, characters=40, saved=90_000),),
                ),
            ),
        )
        launch = Launch(versions=(("claude-code", "2.1.317"),), prompts=(short,))
        scenario = replace(_resumed(), sessions=(replace(session, launches=(launch,)),))

        with pytest.raises(ValueError, match="shorter than Claude Code's own words"):
            Builder(scenario, UNTIL).files()

    def test_invented_words_are_as_long_as_asked(self) -> None:
        assert [len(text(length)) for length in (0, 1, 57, 58, 4_096)] == [
            0,
            1,
            57,
            58,
            4_096,
        ]
