"""The scenario as transcript files (F122.3): each thread a file in Claude
Code's line shapes, in a home laid out as the fleet's is, and each
publication what its file says: read back off the lines here, a thread's
ids and place, its Launches, Prompts and their Hook Runs, its Calls and Tool
Calls with their denials, its Compactions, each Call's place on the chain
and when it was sent, the Events, and each Call's context parts are the
publication's."""

import json
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pilot_scenario import SCENARIO, Builder, HomeFile, Scenario
from pilot_scenario.script import (
    Call,
    Carried,
    Compaction,
    HookRun,
    Launch,
    Occurrence,
    Prompt,
    Session,
    Tokens,
    ToolUse,
)
from pilot_scenario.transcript import (
    INTERRUPTION,
    MANAGED,
    SYNTHETIC,
    folder,
    stamp,
    text,
)

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
    "compactions",
}
"""What a publication says of its thread that its file's name, size, time
and lines say."""

LAUNCH_FACTS = ("started_at", "ended_at", "components", "prompts")
CALL_FACTS = (
    "message_id",
    "prompt",
    "predecessor",
    "compaction",
    "sent_at",
    "completed_at",
    "model",
    "requested_model",
    "effort",
    "stop_reason",
    "thinking_tokens",
    "attributed_skill",
    "attributed_plugin",
    "tokens",
    "events",
)
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
    "denial_kind",
    "result_characters",
    "saved_characters",
)
SUMMARY = "compact_summary"
"""The Context Part Kind of a compaction's summary."""
DENIALS = {"permission-rule": "rule", "user-rejected": "person"}
"""A Denial Kind by the `toolDenialKind` a result's line names."""


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
    if said.startswith(f"PreToolUse:{asked['name']} hook error:"):
        read["denial_kind"] = "hook"
    elif "toolDenialKind" in result:
        read["denial_kind"] = DENIALS[result["toolDenialKind"]]
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


def _is_boundary(line: dict[str, Any]) -> bool:
    return bool(line["type"] == "system" and line["subtype"] == "compact_boundary")


def _chain(
    line: dict[str, Any], lines: list[dict[str, Any]]
) -> tuple[str | None, int | None]:
    """The Call the chain reaches from the line, by its `message.id`, and
    the compaction it crosses on the way, by its place among the file's: up
    each line's `parentUuid` and a boundary's `logicalParentUuid`."""
    named = {each["uuid"]: each for each in lines if "uuid" in each}
    boundaries = [each["uuid"] for each in lines if _is_boundary(each)]
    crossed = None
    while True:
        boundary = _is_boundary(line)
        if boundary and crossed is None:
            crossed = boundaries.index(line["uuid"]) + 1
        follows = line["logicalParentUuid" if boundary else "parentUuid"]
        if follows is None:
            return None, crossed
        line = named[follows]
        if line["type"] == "assistant" and line["message"]["model"] != SYNTHETIC:
            return line["message"]["id"], crossed


def _shaped(shape: dict[str, Any]) -> list[dict[str, Any]]:
    """The context parts a request's shape says it sent: its system prompt's
    text and its tools' schemas as JSON, each where it sent any."""
    parts = []
    system = "".join(block["text"] for block in shape["system"])
    if system:
        parts.append({"kind": "system_prompt", "characters": len(system)})
    if shape["tools"]:
        schemas = json.dumps(shape["tools"], separators=(",", ":"))
        parts.append({"kind": "tool_schemas", "characters": len(schemas)})
    return parts


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
    requests = {line["id"]: line for line in lines if line["type"] == "api-request"}
    shapes = {
        line["shapeHash"]: line["shape"]
        for line in lines
        if line["type"] == "api-request-shape"
    }
    opening: dict[str, list[Any]] | None = None if main else {"files": [], "tasks": []}
    """What the first Call of the Launch open, or of a sub-agent's thread,
    carries, as the lines so far say: none once it began."""
    injected: list[dict[str, Any]] = []
    """The parts the lines since the last Call's first line, or the Launch's
    start, injected."""
    skills = {
        block["id"]: block["input"]["skill"]
        for line in lines
        for block in _blocks(line, "tool_use")
        if block["name"] == "Skill"
    }
    """The skill each `Skill` call asked for, by its id."""
    launches: list[dict[str, Any]] = []
    timed: list[list[tuple[str, str | None]]] = []
    """Each Launch's lines that carry a time: the time, and Claude Code's
    version where the line names one."""
    plugged: list[dict[str, str]] = []
    """The version of each plugin a skill's body of each Launch's names."""
    calls: dict[str, dict[str, Any]] = {}
    exited, prompts, enqueued = True, 0, None
    early: list[dict[str, Any]] = []
    """The Events before the first Call, which it marks."""
    failing: dict[str, set[str]] = {}
    """The Stop hooks' commands that reported an error, by their run's
    `toolUseID`."""

    def occurred(kind: str, is_error: bool, line: dict[str, Any], status: Any) -> None:
        """An Event, on the last Call begun before it, else the first."""
        event = {"kind": kind, "is_error": is_error, "at": _time(line)}
        if status is not None:
            event["detail"] = str(status)
        marks = list(calls.values())[-1] if calls else None
        (early if marks is None else marks.setdefault("events", [])).append(event)

    for line in lines:
        if line["type"] == "cost-state":
            exited = True
        if "timestamp" not in line:
            continue
        if main and not exited:
            own = next((named for _, named in timed[-1] if named), None)
            if own is not None and line.get("version") not in (None, own):
                unnamed = 0
                while timed[-1][-1 - unnamed][1] is None:
                    unnamed += 1
                timed.append(timed[-1][len(timed[-1]) - unnamed :])
                del timed[-2][len(timed[-2]) - unnamed :]
                launches.append({"prompts": []})
                plugged.append({})
                opening = {"files": [], "tasks": []}
                injected = []
        if main and exited:
            launches.append({"prompts": []})
            timed.append([])
            plugged.append({})
            exited = False
            opening = {"files": [], "tasks": []}
            injected = []
        if main:
            timed[-1].append((_time(line), line.get("version")))
        if line["type"] == "queue-operation" and line["operation"] == "enqueue":
            enqueued = line
        elif line["type"] == "attachment":
            attached = line["attachment"]
            if attached["type"] == "hook_non_blocking_error":
                assert main and attached["hookEvent"] == "Stop"
                failing.setdefault(attached["toolUseID"], set()).add(
                    attached["command"]
                )
                continue
            if attached["type"] == "nested_memory":
                loaded = attached["content"]["content"]
                assert line["rendered"] == [
                    {"content": f"Contents of {attached['path']}:\n\n{loaded}"}
                ]
                injected.append(
                    {
                        "kind": "instruction_file",
                        "name": attached["path"],
                        "characters": len(loaded),
                    }
                )
                continue
            if attached["type"] != "instructions":
                (shown,) = line["rendered"]
                injected.append(
                    {
                        "kind": "reminder",
                        "name": attached["type"],
                        "characters": len(shown["content"]),
                    }
                )
                continue
            assert opening is not None
            opening["files"] += [
                {
                    "kind": "instruction_file",
                    "name": instructions["path"],
                    "characters": len(instructions["content"]),
                }
                for instructions in attached["files"]
            ]
            for instructions in attached["files"]:
                named = re.match(r"# Environment: (\S+)\n", instructions["content"])
                if main and instructions["type"] == "Managed" and named is not None:
                    read.setdefault("environment", named.group(1))
        elif line["type"] == "system" and line["subtype"] == "api_error":
            occurred("api_retry", True, line, line["error"].get("status"))
        elif line["type"] == "system" and line["subtype"] == "stop_hook_summary":
            failed = failing.pop(line["toolUseID"], set())
            launches[-1]["prompts"][-1]["hook_runs"] = [
                {
                    "command": hook["command"],
                    "duration_ms": hook["durationMs"],
                    "failed": hook["command"] in failed,
                    "prevented_end": line["preventedContinuation"],
                }
                for hook in line["hookInfos"]
            ]
        elif line["type"] == "assistant" and line["message"]["model"] == SYNTHETIC:
            assert line["isApiErrorMessage"]
            occurred("api_error", True, line, line["apiErrorStatus"])
        elif [block["text"] for block in _blocks(line, "text")] == [INTERRUPTION]:
            occurred("interrupt", False, line, None)
        elif line["type"] == "user" and line.get("isCompactSummary"):
            said = line["message"]["content"]
            injected.append({"kind": "compact_summary", "characters": len(said)})
        elif line["type"] == "user" and line.get("isMeta"):
            (said,) = _blocks(line, "text")
            assert said["text"].startswith("Base directory for this skill: ")
            base = (
                said["text"]
                .split("\n")[0]
                .removeprefix("Base directory for this skill: ")
            )
            if main and "/plugins/cache/" in base:
                _, plugin, version, *_ = base.split("/plugins/cache/")[1].split("/")
                plugged[-1].setdefault(plugin, version)
            injected.append(
                {
                    "kind": "skill_body",
                    "name": skills[line["sourceToolUseID"]],
                    "characters": len(said["text"]),
                }
            )
        elif line["type"] == "user" and main and "promptSource" in line:
            said = line["message"]["content"]
            if enqueued is not None:
                assert enqueued["content"] == said
            prompts += 1
            if opening is not None:
                opening["tasks"].append(len(said))
            launches[-1]["prompts"].append(
                {
                    "received_at": _time(enqueued or line),
                    "source": line["promptSource"],
                    "characters": len(said),
                }
            )
            enqueued = None
        elif (
            line["type"] == "user"
            and not main
            and isinstance(line["message"]["content"], str)
            and opening is not None
        ):
            opening["tasks"].append(len(line["message"]["content"]))
        elif _is_boundary(line):
            made = line["compactMetadata"]
            facts = {
                "at": _time(line),
                "trigger": made["trigger"],
                "tokens_before": made["preTokens"],
                "tokens_after": made.get("postTokens"),
                "duration_ms": made.get("durationMs"),
            }
            read.setdefault("compactions", []).append(
                {name: fact for name, fact in facts.items() if fact is not None}
            )
        elif line["type"] == "assistant":
            message = line["message"]
            if message["id"] not in calls:
                call = {"message_id": message["id"], "tool_calls": []}
                predecessor, compaction = _chain(line, lines)
                if predecessor is not None:
                    call["predecessor"] = predecessor
                if compaction is not None:
                    call["compaction"] = compaction
                if "requestRef" in line:
                    call["sent_at"] = _time(requests[line["requestRef"]])
                if main:
                    call["prompt"] = prompts
                if early:
                    call["events"], early = early, []
                parts = injected
                if opening is not None:
                    parts = (
                        _shaped(shapes[requests[line["requestRef"]]["shapeHash"]])
                        if "requestRef" in line
                        else []
                    )
                    parts += opening["files"] + injected
                    parts += [
                        {"kind": "prompt", "characters": characters}
                        for characters in opening["tasks"]
                    ]
                    opening = None
                if parts:
                    call["context_parts"] = parts
                injected = []
                calls[message["id"]] = call
            call = calls[message["id"]]
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
            for fact, key in (
                ("effort", "effort"),
                ("attributed_skill", "attributionSkill"),
                ("attributed_plugin", "attributionPlugin"),
            ):
                if key in line:
                    call[fact] = line[key]
            asked = [block["from"]["model"] for block in _blocks(line, "fallback")]
            if asked:
                call["requested_model"] = asked[0]
            elif line["requestedModel"] != message["model"]:
                call.setdefault("requested_model", line["requestedModel"])
            if "output_tokens_details" in spent:
                call["thinking_tokens"] = spent["output_tokens_details"][
                    "thinking_tokens"
                ]
            if message["stop_reason"] not in (None, "end_turn", "tool_use"):
                call["stop_reason"] = message["stop_reason"]
            call["tool_calls"] += [
                _tool_call(asked, line, results.get(asked["id"]), home)
                for asked in _blocks(line, "tool_use")
            ]
    for launch, written, plugins in zip(launches, timed, plugged, strict=True):
        launch["started_at"], launch["ended_at"] = written[0][0], written[-1][0]
        launch["components"] = [
            {
                "component": "claude-code",
                "version": next(named for _, named in written if named),
            },
            *(
                {"component": f"plugin:{plugin}", "version": version}
                for plugin, version in plugins.items()
            ),
        ]
    if main:
        read["launches"] = [
            {name: launch[name] for name in LAUNCH_FACTS} for launch in launches
        ]
    read["calls"] = list(calls.values())
    return read


def _facts(publication: dict[str, Any]) -> dict[str, Any]:
    """A publication cut to the facts its file's lines carry."""
    cut = {name: fact for name, fact in publication.items() if name in FACTS}
    if "launches" in publication:
        cut["launches"] = publication["launches"]
    cut["calls"] = []
    for call in publication["calls"]:
        facts = {name: call[name] for name in CALL_FACTS if name in call}
        facts["tool_calls"] = [
            {name: asked[name] for name in TOOL_CALL_FACTS if name in asked}
            for asked in call.get("tool_calls", [])
        ]
        if "context_parts" in call:
            facts["context_parts"] = call["context_parts"]
        cut["calls"].append(facts)
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
                                        occurred=(
                                            Occurrence(9, "interrupt", is_error=False),
                                        ),
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
                                        occurred=(
                                            Occurrence(
                                                51,
                                                "api_error",
                                                is_error=True,
                                                detail="500",
                                            ),
                                        ),
                                    ),
                                    Compaction(at=52, trigger="manual", before=900),
                                    Call(
                                        at=55,
                                        tokens=Tokens(input=6, output=1),
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


class TestTheHome:
    def test_a_thread_is_a_file_where_claude_code_files_it(self) -> None:
        assert [file.path for file in Builder(SCENARIO, UNTIL).files()] == [
            f"projects/-work-RecipeBox/{HALVING}.jsonl",
            f"projects/-work-RecipeBox/{HALVING}/tool-results"
            "/mcp-pantry-list_recipes-toolu_0004.txt",
            f"projects/-work-RecipeBox/{HALVING}/subagents/agent-{COUNTING}.jsonl",
            f"projects/-work-RecipeBox/{HALVING}/tool-results/toolu_0008.txt",
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


def _killed() -> Scenario:
    """The resumed thread, its first process killed."""
    scenario = _resumed()
    session = scenario.sessions[0]
    first, later = session.launches
    killed = (replace(first, killed=True), later)
    return replace(scenario, sessions=(replace(session, launches=killed),))


class TestAPublicationIsWhatItsFileSays:
    @pytest.mark.parametrize(
        "scenario",
        [SCENARIO, _resumed(), _killed()],
        ids=["the scenario", "a resumed thread", "a killed process's thread"],
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

        publications = Builder(SCENARIO, UNTIL).publications()
        (resumed,) = Builder(_resumed(), UNTIL).publications()
        calls = [call for publication in publications for call in publication["calls"]]
        assert [
            sorted(made)
            for publication in [*publications, resumed]
            for made in publication.get("compactions", [])
        ] == [
            ["at", "duration_ms", "tokens_after", "tokens_before", "trigger"],
            ["at", "tokens_before", "trigger"],
        ]
        assert sum("compaction" in call for call in calls) == 1
        assert all("sent_at" in call for call in calls)
        for chosen in (
            "requested_model",
            "effort",
            "stop_reason",
            "thinking_tokens",
            "attributed_skill",
            "attributed_plugin",
        ):
            assert any(chosen in call for call in calls)
        assert not any("sent_at" in call for call in resumed["calls"])
        assert sorted(
            event["kind"]
            for call in [*calls, *resumed["calls"]]
            for event in call.get("events", [])
        ) == ["api_error", "api_retry", "interrupt"]
        assert [call.get("predecessor") for call in resumed["calls"]] == [
            None,
            "msg_0001",
            "msg_0001",
            "msg_0003",
        ]
        assert {call["tool"] for call in tool_calls} >= {"Bash", "Read", "Agent"}
        assert any(call.get("mcp_server") for call in tool_calls)
        assert any(call["failed"] and call.get("exit_code") for call in tool_calls)
        assert any(call["interrupted"] for call in tool_calls)
        assert sorted(
            call["denial_kind"] for call in tool_calls if "denial_kind" in call
        ) == [
            "hook",
            "person",
            "rule",
        ]
        runs = [
            run
            for publication in publications
            for launch in publication.get("launches", [])
            for prompt in launch["prompts"]
            for run in prompt.get("hook_runs", [])
        ]
        assert {run["failed"] for run in runs} == {True, False}
        assert any(
            len(prompt.get("hook_runs", [])) > 1
            for publication in publications
            for launch in publication.get("launches", [])
            for prompt in launch["prompts"]
        )
        assert sorted(
            (call["tool"], call["saved_characters"])
            for call in tool_calls
            if "saved_characters" in call
        ) == [("Bash", 33_180), ("mcp__pantry__list_recipes", 48_300)]

    def test_a_saved_outputs_file_holds_the_characters_its_call_names(self) -> None:
        home = {file.path: file for file in Builder(SCENARIO, UNTIL).files()}
        stated = f"projects/-work-RecipeBox/{HALVING}/tool-results"

        assert len(home[f"{stated}/toolu_0008.txt"].content) == 33_180
        assert (
            len(home[f"{stated}/mcp-pantry-list_recipes-toolu_0004.txt"].content)
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
        """A compaction's boundary follows none, and names the one it
        continues."""
        for file in _transcripts(Builder(SCENARIO, UNTIL)):
            chain = [line for line in _lines(file) if "uuid" in line]
            seen: set[str] = set()
            assert chain[0]["parentUuid"] is None
            for line in chain[1:]:
                follows = line["parentUuid"]
                if _is_boundary(line):
                    assert follows is None
                    follows = line["logicalParentUuid"]
                assert follows in seen | {chain[0]["uuid"]}
                seen.add(line["uuid"])
            assert len({line["uuid"] for line in chain}) == len(chain)

    def test_a_compaction_is_a_boundary_and_the_summary_the_chain_goes_on_from(
        self,
    ) -> None:
        builder = Builder(SCENARIO, UNTIL)
        lines = _lines(builder.files()[0])
        (place,) = [place for place, line in enumerate(lines) if _is_boundary(line)]
        before, made, summary, asked, after = lines[place - 1 : place + 4]

        assert (made["parentUuid"], made["logicalParentUuid"]) == (None, before["uuid"])
        assert made["compactMetadata"] == {
            "trigger": "auto",
            "preTokens": 160_400,
            "postTokens": 21_300,
            "durationMs": 38_000,
        }
        assert made["timestamp"] == stamp(builder.when(150))
        assert (summary["type"], summary["isCompactSummary"]) == ("user", True)
        assert summary["parentUuid"] == made["uuid"]
        assert "promptSource" not in summary and "isMeta" not in summary
        assert summary["timestamp"] == stamp(
            builder.when(150) - timedelta(milliseconds=300)
        )
        assert len(summary["message"]["content"]) == 8_400
        assert asked["type"] == "api-request"
        assert (after["type"], after["parentUuid"]) == ("assistant", summary["uuid"])
        assert {made["version"], summary["version"]} == {"2.1.317"}

    def test_a_boundary_records_what_its_compaction_gives_and_no_more(self) -> None:
        lines = _lines(Builder(_resumed(), UNTIL).files()[0])
        (made,) = [line for line in lines if _is_boundary(line)]

        assert made["compactMetadata"] == {"trigger": "manual", "preTokens": 900}

    def test_a_line_beside_the_chain_carries_no_directory_and_the_queues_and_the_requests_alone_a_time(
        self,
    ) -> None:
        (halving, _, _) = _transcripts(Builder(SCENARIO, UNTIL))

        beside = [line for line in _lines(halving) if "uuid" not in line]
        assert [line["type"] for line in beside] == [
            "permission-mode",
            "queue-operation",
            "queue-operation",
            "api-request-shape",
            *["api-request"] * 7,
            "last-prompt",
            "cost-state",
        ]
        assert not any("cwd" in line for line in beside)
        assert [line["type"] for line in beside if "timestamp" in line] == [
            "queue-operation",
            "queue-operation",
            "api-request-shape",
            *["api-request"] * 7,
        ]
        assert "cwd" not in _lines(halving)[0]

    def test_a_request_is_written_before_its_responses_first_line_which_names_it(
        self,
    ) -> None:
        """An attempt that failed is followed by its error, and named by no
        response."""
        builder = Builder(SCENARIO, UNTIL)
        lines = _lines(builder.files()[0])
        places = [
            place for place, line in enumerate(lines) if line["type"] == "api-request"
        ]

        assert [lines[place]["timestamp"] for place in places] == [
            stamp(builder.when(moment)) for moment in (5, 21, 79, 96, 102, 151, 208)
        ]
        assert len({lines[place]["id"] for place in places}) == len(places)
        (failed,) = [place for place in places if lines[place + 1]["type"] == "system"]
        assert lines[failed + 1]["subtype"] == "api_error"
        assert lines[failed]["id"] not in {line.get("requestRef") for line in lines}
        places.remove(failed)
        for place in places:
            answered = lines[place + 1]["message"]["id"]
            assert {
                line["requestRef"]
                for line in lines
                if line.get("message", {}).get("id") == answered
            } == {lines[place]["id"]}
        assert {lines[place]["version"] for place in places} == {"2.1.317"}
        assert {lines[place]["querySource"] for place in places} == {"sdk"}

    def test_a_requests_shape_is_written_once_before_the_first_request_naming_it(
        self,
    ) -> None:
        """It holds the system prompt and the tools the thread's first Call
        carries."""
        halving, counting, gears = _transcripts(Builder(SCENARIO, UNTIL))

        for file, system, tools in (
            (halving, 9_100, 45_200),
            (counting, 3_900, 11_800),
            (gears, 9_100, 45_200),
        ):
            lines = _lines(file)
            (shape,) = [
                place
                for place, line in enumerate(lines)
                if line["type"] == "api-request-shape"
            ]
            requests = [
                place
                for place, line in enumerate(lines)
                if line["type"] == "api-request"
            ]
            assert shape < requests[0]
            assert {lines[place]["shapeHash"] for place in requests} == {
                lines[shape]["shapeHash"]
            }
            assert _shaped(lines[shape]["shape"]) == [
                {"kind": "system_prompt", "characters": system},
                {"kind": "tool_schemas", "characters": tools},
            ]
        assert [
            line.get("agentId")
            for line in _lines(counting)
            if line["type"] == "api-request-shape"
        ] == [COUNTING]

    def test_a_processs_instruction_files_are_those_its_first_call_carries(
        self,
    ) -> None:
        """Each its path and as long as the script has it; the managed one
        names the environment, and a process that loaded none writes none."""
        halving, counting, _ = _transcripts(Builder(SCENARIO, UNTIL))
        (resumed,) = _transcripts(Builder(_resumed(), UNTIL))

        for file in (halving, counting):
            (attached,) = [
                line["attachment"]
                for line in _lines(file)
                if line["type"] == "attachment"
                and line["attachment"]["type"] == "instructions"
            ]
            assert [
                (loaded["type"], loaded["path"], len(loaded["content"]))
                for loaded in attached["files"]
            ] == [
                ("Managed", MANAGED, 2_350),
                ("Project", "/work/RecipeBox/CLAUDE.md", 3_750),
            ]
            assert attached["files"][0]["content"].startswith(
                "# Environment: ben-recipebox-51f0c2\n\n"
            )
        assert not any(line["type"] == "attachment" for line in _lines(resumed))

    @pytest.mark.parametrize(
        ("carried", "environment", "refused"),
        [
            (
                (Carried("system_prompt", 900),),
                None,
                "read off the shape its request sent: it is `sent`",
            ),
            ((), "cleo-rides-7a1e04", "loads the managed instruction file"),
            ((Carried("instruction_file", 400),), None, "named by its path"),
        ],
        ids=[
            "a system prompt no request sent",
            "a hosted process with no managed file",
            "a file with no path",
        ],
    )
    def test_a_first_call_whose_parts_no_line_can_say_is_refused(
        self, carried: tuple[Carried, ...], environment: str | None, refused: str
    ) -> None:
        session = _resumed().sessions[0]
        prompt = Prompt(
            at=0,
            source="typed",
            characters=20,
            steps=(Call(at=5, tokens=Tokens(input=10), carried=carried),),
        )
        launch = Launch(versions=(("claude-code", "2.1.317"),), prompts=(prompt,))
        scenario = replace(
            _resumed(),
            sessions=(replace(session, launches=(launch,), environment=environment),),
        )

        with pytest.raises(ValueError, match=refused):
            Builder(scenario, UNTIL).files()

    def test_what_a_later_call_carries_is_written_before_its_first_request(
        self,
    ) -> None:
        """A skill's body is the expansion of the `Skill` call that asked
        for it, a reminder an attachment shown to the model, and an
        instruction file loaded later a `nested_memory` one, each as long as
        the script has it."""
        halving, _, gears = _transcripts(Builder(SCENARIO, UNTIL))
        lines = _lines(halving)
        asked = [
            place for place, line in enumerate(lines) if line["type"] == "api-request"
        ]
        (loading,) = [
            (line, block)
            for line in lines
            for block in _blocks(line, "tool_use")
            if block["name"] == "Skill"
        ]
        (body,) = [place for place, line in enumerate(lines) if line.get("isMeta")]
        (said,) = _blocks(lines[body], "text")
        (launched,) = [
            line
            for line in lines
            for block in _blocks(line, "tool_result")
            if block["tool_use_id"] == loading[1]["id"]
        ]
        (noted,) = [
            place
            for place, line in enumerate(lines)
            if line["type"] == "attachment"
            and line["attachment"]["type"] == "bash_output_audience_note"
        ]

        assert loading[1]["input"] == {"skill": "pantry:scaling"}
        assert launched["message"]["content"][0]["content"] == (
            "Launching skill: pantry:scaling"
        )
        assert (lines[body]["type"], lines[body]["sourceToolUseID"]) == (
            "user",
            loading[1]["id"],
        )
        assert said["text"].startswith(
            "Base directory for this skill: /home/ubuntu/.claude/plugins/cache"
            "/larder/pantry/0.3.1/skills/scaling\n\n"
        )
        assert len(said["text"]) == 4_300
        assert asked[1] < body < asked[2]
        assert lines[noted]["rendered"] == [{"content": text(186)}]
        assert asked[2] < noted < asked[3]
        assert lines[asked[3]]["timestamp"] == lines[noted]["timestamp"]
        (nested,) = [
            line
            for line in _lines(gears)
            if line["type"] == "attachment"
            and line["attachment"]["type"] == "nested_memory"
        ]
        assert nested["attachment"]["path"] == "/work/BikeLog/rides/CLAUDE.md"
        assert len(nested["attachment"]["content"]["content"]) == 620

    @pytest.mark.parametrize(
        ("steps", "refused"),
        [
            (
                (
                    Compaction(at=4, trigger="manual", before=900),
                    Call(at=9, tokens=Tokens(output=1)),
                ),
                "a part of the next Call of its Launch",
            ),
            (
                (Call(at=9, tokens=Tokens(output=1), carried=(Carried(SUMMARY, 40),)),),
                "the summary of each compaction since the Call before it",
            ),
            (
                (
                    Compaction(at=4, trigger="manual", before=900),
                    Call(
                        at=9,
                        tokens=Tokens(output=1),
                        carried=(Carried("reminder", 40, "date"), Carried(SUMMARY, 40)),
                    ),
                ),
                "listed as its lines are written",
            ),
            (
                (
                    Call(
                        at=9,
                        tokens=Tokens(output=1),
                        carried=(Carried("reminder", 40),),
                    ),
                ),
                "of the kind `reminder` is named",
            ),
            (
                (
                    Call(
                        at=9,
                        tokens=Tokens(output=1),
                        carried=(Carried("digest_section", 40, "Phase P1"),),
                    ),
                ),
                "No line is written for a part of the kind `digest_section`",
            ),
            (
                (
                    Call(
                        at=9,
                        tokens=Tokens(output=1),
                        tools=(ToolUse("Skill", "loom:weave", took=1, characters=27),),
                        carried=(Carried("skill_body", 900, "loom:weave"),),
                    ),
                ),
                "expansion of a `Skill` call before it",
            ),
        ],
        ids=[
            "a compaction the Call after carries no summary of",
            "a summary with no compaction",
            "a summary after what else was injected",
            "a reminder of no type",
            "a part no line says",
            "a skill's body its own Call asked for",
        ],
    )
    def test_a_later_part_no_line_can_say_is_refused(
        self, steps: tuple[Call | Compaction, ...], refused: str
    ) -> None:
        session = _resumed().sessions[0]
        opened = Call(at=2, tokens=Tokens(input=10))
        prompt = Prompt(at=0, source="typed", characters=20, steps=(opened, *steps))
        launch = Launch(versions=(("claude-code", "2.1.317"),), prompts=(prompt,))
        scenario = replace(_resumed(), sessions=(replace(session, launches=(launch,)),))

        with pytest.raises(ValueError, match=refused):
            Builder(scenario, UNTIL).files()

    def test_a_request_keeps_what_the_last_one_sent_that_its_chain_still_holds(
        self,
    ) -> None:
        """Its process's first keeps none and builds on none; one past a
        compaction keeps none, a rewind fewer than the last sent, and one
        sent again all the attempt that failed sent."""
        halving, _, gears = _transcripts(Builder(SCENARIO, UNTIL))

        def sent(file: HomeFile) -> list[dict[str, Any]]:
            return [line for line in _lines(file) if line["type"] == "api-request"]

        for requests in (sent(halving), sent(gears)):
            assert "base" not in requests[0]
            assert [request["base"] for request in requests[1:]] == [
                request["id"] for request in requests[:-1]
            ]
        assert [
            (request["keep"], len(request["tail"])) for request in sent(halving)
        ] == [
            (0, 4),
            (4, 2),
            (6, 3),
            (9, 3),
            (12, 0),
            (0, 1),
            (1, 2),
        ]
        assert [(request["keep"], len(request["tail"])) for request in sent(gears)] == [
            (0, 3),
            (3, 3),
            (6, 2),
            (7, 1),
            (8, 3),
        ]

    def test_an_attempt_that_failed_is_its_request_and_the_error_it_met(
        self,
    ) -> None:
        """The request is sent again, with what the attempt sent, and the
        chain goes on through the error's line."""
        builder = Builder(SCENARIO, UNTIL)
        lines = _lines(builder.files()[0])
        (place,) = [
            place
            for place, line in enumerate(lines)
            if line["type"] == "system" and line["subtype"] == "api_error"
        ]
        attempt, error, again, answer = lines[place - 1 : place + 3]

        assert error["timestamp"] == stamp(builder.when(101))
        assert (error["error"]["status"], error["retryAttempt"]) == (529, 1)
        assert error["parentUuid"] == lines[place - 2]["uuid"]
        assert (again["base"], again["tail"]) == (attempt["id"], [])
        assert again["requestDigest"] == attempt["requestDigest"]
        assert (answer["parentUuid"], answer["requestRef"]) == (
            error["uuid"],
            again["id"],
        )

    def test_an_occurrence_is_the_line_claude_code_writes_of_it(self) -> None:
        """A request that failed for good is a response Claude Code wrote
        itself, which no request sends, and the person's interruption a
        line of their words; each follows the chain's last line."""
        lines = _lines(Builder(_resumed(), UNTIL).files()[0])
        (failed,) = [line for line in lines if line.get("isApiErrorMessage")]
        (interrupted,) = [
            line for line in lines if _blocks(line, "text") and line["type"] == "user"
        ]
        chained = {line["uuid"]: line for line in lines if "uuid" in line}

        assert (failed["message"]["model"], failed["apiErrorStatus"]) == (
            SYNTHETIC,
            500,
        )
        assert chained[failed["parentUuid"]]["type"] == "assistant"
        assert interrupted["message"]["content"] == [
            {"type": "text", "text": INTERRUPTION}
        ]
        assert "promptSource" not in interrupted
        assert chained[interrupted["parentUuid"]]["type"] == "assistant"

    def test_no_line_is_written_for_an_occurrence_of_another_kind(self) -> None:
        resumed = _resumed()
        (session,) = resumed.sessions
        first, *rest = session.launches
        (prompt,) = first.prompts
        step = prompt.steps[0]
        assert isinstance(step, Call)
        call = replace(step, occurred=(Occurrence(6, "gate_red", is_error=True),))
        steps = (call, *prompt.steps[1:])
        launches = (replace(first, prompts=(replace(prompt, steps=steps),)), *rest)
        other = replace(resumed, sessions=(replace(session, launches=launches),))

        with pytest.raises(ValueError, match="`gate_red`"):
            Builder(other, UNTIL).files()

    def test_a_call_sent_at_no_moment_names_no_request(self) -> None:
        lines = _lines(Builder(_resumed(), UNTIL).files()[0])

        assert not [line for line in lines if line["type"] == "api-request"]
        assert not [line for line in lines if "requestRef" in line]

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

    def test_a_responses_lines_name_its_choices_and_its_last_its_thinking_and_end(
        self,
    ) -> None:
        halving, counting, _ = _transcripts(Builder(SCENARIO, UNTIL))
        first = [
            line
            for line in _lines(halving)
            if line.get("message", {}).get("id") == "msg_0001"
        ]
        last = [
            line
            for line in _lines(counting)
            if line.get("message", {}).get("id") == "msg_0009"
        ]

        assert {line["requestedModel"] for line in first} == {"claude-opus-4-5"}
        assert {line["effort"] for line in first} == {"high"}
        assert [
            line["message"]["usage"]["output_tokens_details"]["thinking_tokens"]
            for line in first
        ] == [47, 47, 188]
        assert [line["message"]["stop_reason"] for line in last] == ["max_tokens"]
        assert not any("effort" in line or "attributionSkill" in line for line in last)

    def test_a_response_a_fallback_answered_opens_with_its_block(self) -> None:
        """It names the model asked for, which the request asked for and
        each of its lines names."""
        lines = _lines(_transcripts(Builder(SCENARIO, UNTIL))[1])
        answered = [
            line for line in lines if line.get("message", {}).get("id") == "msg_0008"
        ]
        (asked,) = [
            line
            for line in lines
            if line["type"] == "api-request" and line["id"] == answered[0]["requestRef"]
        ]

        assert answered[0]["message"]["content"] == [
            {
                "type": "fallback",
                "from": {"model": "claude-opus-4-5"},
                "to": {"model": "claude-haiku-4-5-20251001"},
            }
        ]
        assert {line["message"]["model"] for line in answered} == {
            "claude-haiku-4-5-20251001"
        }
        assert {line["requestedModel"] for line in answered} == {"claude-opus-4-5"}
        assert asked["params"]["model"] == "claude-opus-4-5"

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

    def test_a_killed_process_writes_no_closing_line_and_the_next_another_version(
        self,
    ) -> None:
        lines = _lines(Builder(_killed(), UNTIL).files()[0])
        (end,) = [
            place for place, line in enumerate(lines) if line["type"] == "cost-state"
        ]
        (started,) = [
            place
            for place, line in enumerate(lines)
            if line.get("version") == "2.1.318"
        ][:1]

        assert end == len(lines) - 1
        assert [line["type"] for line in lines[started - 3 : started + 1]] == [
            "permission-mode",
            "queue-operation",
            "queue-operation",
            "user",
        ]
        assert {line["version"] for line in lines[:started] if "version" in line} == {
            "2.1.317"
        }

    def test_a_skill_of_no_plugin_lies_under_the_homes_skills(self) -> None:
        session = _resumed().sessions[0]
        loading = Call(
            at=2,
            tokens=Tokens(input=10),
            tools=(ToolUse("Skill", "notes", took=1, characters=22),),
        )
        loaded = Call(
            at=9,
            tokens=Tokens(output=1),
            carried=(Carried("skill_body", 400, "notes"),),
        )
        prompt = Prompt(at=0, source="typed", characters=20, steps=(loading, loaded))
        launch = Launch(versions=(("claude-code", "2.1.317"),), prompts=(prompt,))
        scenario = replace(_resumed(), sessions=(replace(session, launches=(launch,)),))

        (body,) = [
            line
            for line in _lines(Builder(scenario, UNTIL).files()[0])
            if line.get("isMeta")
        ]

        assert body["message"]["content"][0]["text"].startswith(
            "Base directory for this skill: /home/ubuntu/.claude/skills/notes\n\n"
        )

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
        assert all(line["isSidechain"] for line in lines if "uuid" in line)
        assert [
            (line["agentId"], line["querySource"])
            for line in lines
            if line["type"] == "api-request"
        ] == [(COUNTING, "agent:builtin:Explore")] * 3
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

    def test_a_denied_calls_result_is_an_error_in_claude_codes_words_for_it(
        self,
    ) -> None:
        """A hook's block and a rule's name the kind `permission-rule`, the
        person's `user-rejected`."""
        _, counting, gears = _transcripts(Builder(SCENARIO, UNTIL))
        denied = [
            line
            for file in (counting, gears)
            for line in _lines(file)
            if "toolDenialKind" in line
        ]

        assert [
            (line["toolDenialKind"], block["is_error"], block["content"][:29])
            for line in denied
            for block in _blocks(line, "tool_result")
        ] == [
            ("permission-rule", True, "PreToolUse:Bash hook error: ["),
            ("permission-rule", True, "Permission to use Bash has be"),
            ("user-rejected", True, "The user doesn't want to proc"),
        ]
        assert [line["toolUseResult"][:6] for line in denied] == [
            "Error:",
            "Error:",
            "User r",
        ]

    def test_a_denied_call_whose_result_is_no_error_is_refused(self) -> None:
        session = _resumed().sessions[0]
        denied = Prompt(
            at=0,
            source="typed",
            characters=20,
            steps=(
                Call(
                    at=5,
                    tokens=Tokens(input=10),
                    tools=(
                        ToolUse("Bash", "ls", took=1, characters=60, denied="rule"),
                    ),
                ),
            ),
        )
        launch = Launch(versions=(("claude-code", "2.1.317"),), prompts=(denied,))
        scenario = replace(_resumed(), sessions=(replace(session, launches=(launch,)),))

        with pytest.raises(ValueError, match="A denied call's result is an error"):
            Builder(scenario, UNTIL).files()

    def test_the_stop_hooks_are_a_summary_after_the_runs_last_call(self) -> None:
        """Each that failed reports its error before it, under the run's
        `toolUseID`."""
        lines = _lines(_transcripts(Builder(SCENARIO, UNTIL))[2])
        (summary,) = [
            line for line in lines if line.get("subtype") == "stop_hook_summary"
        ]
        (error,) = [
            line
            for line in lines
            if line["type"] == "attachment"
            and line["attachment"]["type"] == "hook_non_blocking_error"
        ]
        last = [
            line for line in lines if line.get("message", {}).get("id") == "msg_0002"
        ][-1]

        assert error["parentUuid"] == last["uuid"]
        assert summary["parentUuid"] == error["uuid"]
        assert summary["timestamp"] == last["timestamp"]
        assert summary["hookInfos"] == [
            {"command": "log_ride.sh", "durationMs": 40},
            {"command": "sync_notes.sh", "durationMs": 1_210},
        ]
        assert summary["hookErrors"] == [error["attachment"]["stderr"]]
        assert summary["preventedContinuation"] is False
        assert (
            error["attachment"]["hookEvent"],
            error["attachment"]["command"],
            error["attachment"]["toolUseID"],
        ) == ("Stop", "sync_notes.sh", summary["toolUseID"])

    def test_a_hooks_error_is_no_message_a_request_sends(self) -> None:
        lines = _lines(_transcripts(Builder(SCENARIO, UNTIL))[2])
        (error,) = [
            line
            for line in lines
            if line["type"] == "attachment"
            and line["attachment"]["type"] == "hook_non_blocking_error"
        ]
        asked = [line for line in lines if line["type"] == "api-request"]

        assert lines.index(error) < lines.index(asked[2])
        assert (asked[2]["keep"], len(asked[2]["tail"])) == (6, 2)

    def test_hooks_that_differ_on_keeping_the_run_from_ending_are_refused(
        self,
    ) -> None:
        """Claude Code says it of all a summary's hooks at once."""
        resumed = _resumed()
        (session,) = resumed.sessions
        first, *rest = session.launches
        (prompt,) = first.prompts
        hooks = (HookRun("a.sh", took_ms=3), HookRun("b.sh", took_ms=4, held=True))
        held = replace(prompt, hooks=hooks)
        launches = (replace(first, prompts=(held,)), *rest)
        other = replace(resumed, sessions=(replace(session, launches=launches),))

        with pytest.raises(ValueError, match="all its hooks at once"):
            Builder(other, UNTIL).files()

    def test_invented_words_are_as_long_as_asked(self) -> None:
        assert [len(text(length)) for length in (0, 1, 57, 58, 4_096)] == [
            0,
            1,
            57,
            58,
            4_096,
        ]
