"""A transcript's file read into its whole publication: the scenario's
files read as the builder's publications, and each rule of the reading on a
file built for it."""

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pilot_collection.publication import PublicationSchema, PublishedToolCallSchema
from pilot_scenario import COLLECTOR, SCENARIO, Builder, Scenario
from pilot_scenario.script import Call, Launch, Prompt, Session, Tokens

from pilot_collector import VERSION
from pilot_collector.home import transcript
from pilot_collector.reader import UnreadableError, read
from tests import support
from tests.support import (
    AGENT,
    BODY,
    DIRECTORY,
    FOLDER,
    MANAGED,
    SESSION,
    Line,
    answering,
    assistant,
    attached,
    beside,
    boundary,
    chained,
    cost,
    denied,
    erred,
    expanded,
    fallback,
    fell_back,
    filed,
    finished,
    hook_failed,
    hooked,
    instructions,
    interruption,
    invoked,
    linked,
    loaded,
    moment,
    nested,
    over_the_tokens,
    queue,
    request,
    requesting,
    result,
    retried,
    saved,
    sent,
    shaped,
    snapshot,
    summary,
    synthetic,
    taken,
    too_large,
    typed,
    user,
)

UNTIL = datetime(2026, 11, 12, 9, 30, 0, 250_000, tzinfo=UTC)

INTERRUPTED = "[Request interrupted by user for tool use]"
"""Claude Code's words for the result of a tool call the person interrupted."""

NOTIFIED = (
    "<task-notification>\n<task-id>b7wq2k</task-id>\n<status>completed</status>\n"
    "<summary>The dye vat settled</summary>\n</task-notification>"
)
"""A task notification, as a background task's end is announced."""

SETTINGS = support.settings()

LOOM = {
    "name": "Weave",
    "description": "Weave a row of the cloth.",
    "input_schema": {"type": "object", "properties": {"row": {"type": "integer"}}},
}
"""A tool a request sends."""

SCHEMAS = len(json.dumps([LOOM], separators=(",", ":")))
"""The characters of that tool's schema as JSON."""

SPLIT = "__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__"
"""The marker a snapshot's system prompt holds where Claude Code splits it."""

THREAD = (
    "session_id",
    "agent_id",
    "file_size",
    "file_modified_at",
    "collector",
    "working_directory",
    "repository",
    "environment",
)
PROMPT = ("received_at", "source", "characters", "hook_runs")
CHOICES = (
    "requested_model",
    "effort",
    "stop_reason",
    "thinking_tokens",
    "attributed_skill",
    "attributed_plugin",
)
"""What Claude Code records of a Call's own choices."""
CALL = (
    "message_id",
    "prompt",
    "predecessor",
    "compaction",
    "sent_at",
    "completed_at",
    "model",
    *CHOICES,
    "miss_cause",
    "tokens",
    "tool_calls",
    "events",
    "context_parts",
)
OPENING = ("system_prompt", "tool_schemas", "instruction_file", "prompt")
"""The Context Part Kinds a Launch's first Call carries that no later Call
does."""


def _resumed() -> Scenario:
    """A thread two processes wrote, in a directory under no checkout,
    hosted by no environment: the first was killed, and the second, under a
    later version, took a queued prompt and went back to the first's
    Call."""
    first = Prompt(
        at=0,
        source="typed",
        characters=24,
        steps=(
            Call(at=6, name="the first", tokens=Tokens(input=12, output=7)),
            Call(at=9, tokens=Tokens(cache_read=30, output=2)),
        ),
    )
    second = Prompt(
        at=44,
        source="queued",
        characters=15,
        steps=(Call(at=52, back_to="the first", tokens=Tokens(output=4)),),
    )
    return Scenario(
        name="a resumed thread",
        people=("cleo",),
        projects=(),
        kinds=(),
        units=(),
        sessions=(
            Session(
                name="resumed",
                directory="/tmp/looms",
                person="cleo",
                launches=(
                    Launch(
                        versions=(("claude-code", "2.1.317"),),
                        prompts=(first,),
                        killed=True,
                    ),
                    Launch(versions=(("claude-code", "2.1.318"),), prompts=(second,)),
                ),
            ),
        ),
    )


def _cut(publication: dict[str, Any]) -> dict[str, Any]:
    """A publication of the builder's cut to the facts the reader reads."""
    cut = {name: publication[name] for name in THREAD if name in publication}
    if "launches" in publication:
        cut["launches"] = publication["launches"]
    cut["compactions"] = publication.get("compactions", [])
    cut["calls"] = [
        {name: call[name] for name in CALL if name in call}
        for call in publication["calls"]
    ]
    return cut


def _read(projects: Path, lines: list[Line] | bytes) -> PublicationSchema:
    """The publication of a main thread's file holding `lines`."""
    return read(filed(projects, lines), SETTINGS).publication


def _tool_call(projects: Path, *lines: Line) -> PublishedToolCallSchema:
    """The one tool call of a main thread's file that holds a prompt and
    `lines`."""
    (asked,) = _tool_calls(_read(projects, [typed(0), *lines]))
    return asked


def _tool_calls(publication: PublicationSchema) -> list[PublishedToolCallSchema]:
    return [asked for call in publication.calls for asked in call.tool_calls]


def _sources(publication: PublicationSchema) -> list[str]:
    return [
        prompt.source for launch in publication.launches for prompt in launch.prompts
    ]


def _sends(publication: PublicationSchema) -> list[tuple[str, datetime | None]]:
    """Each Call's `message_id` and when it was sent."""
    return [(call.message_id, call.sent_at) for call in publication.calls]


def _chains(publication: PublicationSchema) -> list[tuple[str | None, int | None]]:
    """Each Call's predecessor and the compaction its chain crossed."""
    return [(call.predecessor, call.compaction) for call in publication.calls]


def _missed(**spent: int) -> list[Line]:
    """A prompt and two Calls, the first leaving 1,000 tokens in the cache
    and the second spending `spent`: a chain."""
    return linked(
        [
            typed(0),
            assistant(4, "msg_01", cache_write_5m=1_000),
            assistant(9, "msg_02", "claude-opus-4-5", **spent),
        ]
    )


def _events(
    publication: PublicationSchema,
) -> list[list[tuple[str, bool, int, str | None]]]:
    """Each Call's Events: its kind, whether it is an error, its second and
    its detail."""
    return [
        [
            (
                event.kind,
                event.is_error,
                round((event.at - moment(0)).total_seconds()),
                event.detail,
            )
            for event in call.events
        ]
        for call in publication.calls
    ]


class TestTheScenario:
    @pytest.mark.parametrize(
        "scenario", [SCENARIO, _resumed()], ids=["the scenario", "a resumed thread"]
    )
    def test_each_file_reads_as_the_builders_publication(
        self, scenario: Scenario, tmp_path: Path
    ) -> None:
        builder = Builder(scenario, UNTIL)
        builder.write(tmp_path)
        projects = tmp_path / "projects"
        files = [file for file in builder.files() if file.path.endswith(".jsonl")]

        assert len(files) == len(builder.publications())
        for file, publication in zip(files, builder.publications(), strict=True):
            named = transcript(projects, tmp_path / file.path)
            assert named is not None
            expected = PublicationSchema.model_validate(_cut(publication))
            assert (
                read(named, SETTINGS).publication.model_dump() == expected.model_dump()
            )

    def test_the_scenario_has_each_fact_the_reading_is_proved_on(self) -> None:
        """The reading above proves nothing of a fact no thread has."""
        publications = Builder(SCENARIO, UNTIL).publications()
        resumed = Builder(_resumed(), UNTIL).publications()
        prompts = [
            prompt
            for publication in publications
            for launch in publication.get("launches", [])
            for prompt in launch["prompts"]
        ]
        tokens = {
            kind
            for publication in publications
            for call in publication["calls"]
            for kind in call["tokens"]
        }

        assert any("agent_id" in publication for publication in publications)
        assert {prompt["source"] for prompt in prompts} >= {"sdk", "typed"}
        assert tokens == {
            "input",
            "cache_write_5m",
            "cache_write_1h",
            "cache_read",
            "output",
        }
        assert all("environment" in one for one in publications if "launches" in one)
        tool_calls = [
            asked
            for publication in publications
            for call in publication["calls"]
            for asked in call.get("tool_calls", [])
        ]
        assert {asked["tool"] for asked in tool_calls} >= {"Bash", "Edit", "Agent"}
        assert any("mcp_server" in asked for asked in tool_calls)
        assert any(asked.get("exit_code") for asked in tool_calls)
        assert any(asked["interrupted"] for asked in tool_calls)
        assert sum("saved_characters" in asked for asked in tool_calls) == 2
        assert any(
            "agent_id" in publication and call.get("tool_calls")
            for publication in publications
            for call in publication["calls"]
        )
        assert len(resumed[0]["launches"]) == 2
        assert _resumed().sessions[0].launches[0].killed
        assert {
            used["component"]
            for publication in publications
            for launch in publication.get("launches", [])
            for used in launch["components"]
        } == {"claude-code", "plugin:pantry"}
        assert "environment" not in resumed[0] and "repository" not in resumed[0]
        (compaction,) = [
            compaction
            for publication in publications
            for compaction in publication.get("compactions", [])
        ]
        assert {"tokens_after", "duration_ms"} <= set(compaction)
        assert all(
            "sent_at" in call
            for publication in publications
            for call in publication["calls"]
        )
        assert not any("sent_at" in call for call in resumed[0]["calls"])
        for threads in (publications, resumed):
            calls = [thread["calls"] for thread in threads]
            assert any("predecessor" not in thread[0] for thread in calls)
            assert any(
                later["predecessor"] != earlier["message_id"]
                for thread in calls
                for earlier, later in zip(thread, thread[1:], strict=False)
            )
        assert [
            call["predecessor"]
            for publication in publications
            for call in publication["calls"]
            if "compaction" in call
        ] == ["msg_0004"]
        calls = [call for publication in publications for call in publication["calls"]]
        assert [call["requested_model"] for call in calls if "requested_model" in call]
        assert [call["stop_reason"] for call in calls if "stop_reason" in call]
        for chosen in ("effort", "thinking_tokens", "attributed_skill"):
            assert any(chosen in call for call in calls)
            assert not all(chosen in call for call in calls)
        assert any("attributed_plugin" in call for call in calls)
        assert {call["miss_cause"] for call in calls if "miss_cause" in call} == {
            "compaction",
            "rewind",
            "ttl",
        }
        assert [
            event["kind"] for call in calls for event in call.get("events", [])
        ] == ["api_retry"]
        assert {
            asked["denial_kind"] for asked in tool_calls if "denial_kind" in asked
        } == {"rule", "person", "hook"}
        runs = [prompt.get("hook_runs", []) for prompt in prompts]
        assert {run["failed"] for ran in runs for run in ran} == {True, False}
        assert any(len(ran) > 1 for ran in runs)
        for publication in publications:
            first, *later = publication["calls"]
            assert {part["kind"] for part in first["context_parts"]} >= set(OPENING)
            assert not any(
                part["kind"] in ("system_prompt", "tool_schemas", "prompt")
                for call in later
                for part in call.get("context_parts", [])
            )
        assert {
            (later > 0, part["kind"])
            for publication in publications
            for later, call in enumerate(publication["calls"])
            for part in call.get("context_parts", [])
        } >= {
            (False, "reminder"),
            (True, "reminder"),
            (True, "instruction_file"),
            (True, "skill_body"),
            (True, "compact_summary"),
        }
        assert [
            [part["kind"] for part in call.get("context_parts", [])]
            for call in resumed[0]["calls"]
        ] == [["prompt"], [], ["prompt"]]

    def test_a_reading_is_a_call_pilot_takes_by_its_shape(self, tmp_path: Path) -> None:
        builder = Builder(SCENARIO, UNTIL)
        builder.write(tmp_path)
        named = transcript(tmp_path / "projects", tmp_path / builder.files()[0].path)
        assert named is not None

        sent = read(named, SETTINGS).publication.model_dump_json(exclude_none=True)

        assert (
            PublicationSchema.model_validate_json(sent)
            == read(named, SETTINGS).publication
        )


class TestTheCollectionRecord:
    def test_the_ids_are_its_places_and_the_version_the_collectors(
        self, tmp_path: Path
    ) -> None:
        lines = [typed(0), assistant(4, output=3)]

        main = read(filed(tmp_path, lines), SETTINGS).publication
        sub = read(filed(tmp_path, lines, AGENT), SETTINGS).publication

        assert (main.session_id, main.agent_id) == (SESSION, None)
        assert (sub.session_id, sub.agent_id) == (SESSION, AGENT)
        assert main.collector.version == VERSION == COLLECTOR

    def test_the_size_is_the_files_bytes_and_the_time_its_own_to_the_microsecond(
        self, tmp_path: Path
    ) -> None:
        named = filed(tmp_path, [typed(0, "Schußfaden"), assistant(4, output=3)])
        written = 1_794_474_000_123_456_789
        os.utime(named.path, ns=(written, written))

        publication = read(named, SETTINGS).publication

        assert publication.file_size == named.path.stat().st_size
        assert publication.file_modified_at == datetime(
            2026, 11, 12, 9, 0, 0, 123_456, tzinfo=UTC
        )

    def test_a_line_still_being_written_is_not_read_and_its_bytes_count(
        self, tmp_path: Path
    ) -> None:
        whole = support.content([typed(0), assistant(4, "msg_01", output=3)])
        begun = support.content([assistant(9, "msg_02", output=5)])[:-40]

        publication = _read(tmp_path, whole + begun)

        assert [call.message_id for call in publication.calls] == ["msg_01"]
        assert publication.file_size == len(whole) + len(begun)


class TestThePlace:
    def test_the_working_directory_is_the_first_lines_that_carries_one(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            [
                beside("permission-mode", permissionMode="default"),
                queue("enqueue", 0, "Warp the loom."),
                typed(1) | {"cwd": "/work/Loom/patterns"},
                assistant(4, output=3) | {"cwd": "/work/Shuttle"},
            ],
        )

        assert publication.working_directory == "/work/Loom/patterns"
        assert publication.repository == "Loom"

    @pytest.mark.parametrize(
        ("directory", "repository"),
        [
            ("/work/Loom", "Loom"),
            ("/work/Loom/src/heddles", "Loom"),
            ("/work/Loom/.claude/worktrees/twill", "Loom"),
            ("/work", None),
            ("/work/scratch", None),
            ("/work/scratch/Shuttle", None),
            ("/workshop/Loom", None),
            ("/tmp/looms", None),
            ("/srv/checkouts/Loom", None),
        ],
    )
    def test_the_repository_is_the_checkout_that_holds_the_directory(
        self, directory: str, repository: str | None, tmp_path: Path
    ) -> None:
        publication = _read(tmp_path, [typed(0) | {"cwd": directory}])

        assert publication.repository == repository

    def test_the_checkout_roots_are_a_setting(self, tmp_path: Path) -> None:
        settings = support.settings(
            COLLECTOR_CHECKOUT_ROOTS=["/srv/checkouts", "/srv/more"]
        )
        elsewhere = filed(tmp_path, [typed(0) | {"cwd": "/srv/more/Shuttle/src"}])

        assert read(elsewhere, settings).publication.repository == "Shuttle"
        assert (
            read(filed(tmp_path, [typed(0)]), settings).publication.repository is None
        )

    def test_the_environment_is_the_id_the_managed_file_opens_with(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            [
                typed(0),
                instructions(
                    0,
                    loaded("User", "# Environment: not-this", "/home/ubuntu/CLAUDE.md"),
                    loaded(
                        "Managed", "# Environment: cleo-loom-7a41d9\n\nA workspace."
                    ),
                    loaded("Project", "# House rules", f"{DIRECTORY}/CLAUDE.md"),
                ),
            ],
        )

        assert publication.environment == "cleo-loom-7a41d9"

    def test_a_file_that_names_two_environments_is_its_first_ones(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            [
                typed(0),
                instructions(0, loaded("Managed", "# Environment: cleo-loom-7a41d9\n")),
                cost(),
                typed(60),
                instructions(
                    60, loaded("Managed", "# Environment: cleo-loom-b02e55\n")
                ),
            ],
        )

        assert publication.environment == "cleo-loom-7a41d9"

    def test_the_pattern_that_finds_the_id_is_a_setting(self, tmp_path: Path) -> None:
        settings = support.settings(
            COLLECTOR_ENVIRONMENT_PATTERN=re.compile(r"# Host: (\S+)")
        )
        hosted = filed(
            tmp_path,
            [typed(0), instructions(0, loaded("Managed", "# Host: loom-9\n"))],
        )

        assert read(hosted, settings).publication.environment == "loom-9"
        assert read(hosted, SETTINGS).publication.environment is None

    def test_the_id_is_read_where_the_managed_file_opens_and_nowhere_else(
        self, tmp_path: Path
    ) -> None:
        quoted = "# Environment: cleo-loom-7a41d9\n"
        publication = _read(
            tmp_path,
            [
                typed(0, quoted),
                instructions(0, loaded("Managed", f"# Workspace\n\n{quoted}")),
                chained(
                    "attachment", 1, attachment={"type": "file", "content": quoted}
                ),
                result(2) | {"toolUseResult": quoted},
                beside("api-request-blob", content=quoted),
            ],
        )

        assert publication.environment is None

    def test_a_sub_agents_thread_names_no_environment(self, tmp_path: Path) -> None:
        lines = [
            user(0, "Count the heddles."),
            instructions(0, loaded("Managed", "# Environment: cleo-loom-7a41d9\n")),
            assistant(3, output=2),
        ]

        assert (
            read(filed(tmp_path, lines, AGENT), SETTINGS).publication.environment
            is None
        )
        assert _read(tmp_path, lines).environment == "cleo-loom-7a41d9"


class TestLaunches:
    def test_a_launch_starts_at_the_first_timed_line_and_after_each_cost_line(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            [
                beside("permission-mode", permissionMode="default"),
                typed(1),
                assistant(4, "msg_01", output=3),
                beside("last-prompt", lastPrompt="Warp the loom."),
                cost(),
                beside("permission-mode", permissionMode="default"),
                queue("enqueue", 60, "Thread the heddles."),
                queue("dequeue", 62),
                user(62, "Thread the heddles.", promptSource="queued"),
                assistant(70, "msg_02", output=5),
            ],
        )

        assert [launch.started_at for launch in publication.launches] == [
            moment(1),
            moment(60),
        ]
        assert [len(launch.prompts) for launch in publication.launches] == [1, 1]

    def test_an_exits_cost_line_written_twice_starts_one_launch(
        self, tmp_path: Path
    ) -> None:
        exit_twice = [
            cost(),
            beside("last-prompt", lastPrompt="Warp the loom."),
            beside("cost-state", totalDuration=1_250),
        ]
        first = [typed(1), assistant(4, "msg_01", output=3), *exit_twice]
        second = [typed(60), assistant(64, "msg_02", output=3), *exit_twice]

        assert len(_read(tmp_path, first).launches) == 1
        assert [
            launch.started_at for launch in _read(tmp_path, first + second).launches
        ] == [moment(1), moment(60)]

    def test_a_process_picked_up_under_the_same_version_joins_the_launch_before(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            [
                typed(1),
                assistant(4, "msg_01", output=3),
                beside("permission-mode", permissionMode="default"),
                typed(600),
                assistant(604, "msg_02", output=3),
            ],
        )

        (launch,) = publication.launches
        assert (launch.started_at, launch.ended_at) == (moment(1), moment(604))
        assert len(launch.prompts) == 2

    def test_a_line_that_names_another_version_starts_a_launch(
        self, tmp_path: Path
    ) -> None:
        """A process that follows a killed one under another version, which
        writes no line before its prompt's that carries a time."""
        later = {"version": "2.1.318"}
        publication = _read(
            tmp_path,
            [
                typed(1),
                assistant(4, "msg_01", output=3),
                beside("permission-mode", permissionMode="default"),
                typed(600) | later,
                assistant(604, "msg_02", output=3) | later,
            ],
        )

        assert [
            (
                launch.started_at,
                launch.ended_at,
                [(used.component, used.version) for used in launch.components],
                len(launch.prompts),
            )
            for launch in publication.launches
        ] == [
            (moment(1), moment(4), [("claude-code", "2.1.317")], 1),
            (moment(600), moment(604), [("claude-code", "2.1.318")], 1),
        ]
        assert [call.prompt for call in publication.calls] == [1, 2]

    def test_the_queues_lines_before_a_line_naming_another_version_start_its_launch(
        self, tmp_path: Path
    ) -> None:
        """They name no version: the process that wrote them is told by the
        line that does."""
        later = {"version": "2.1.318"}
        publication = _read(
            tmp_path,
            [
                typed(1),
                assistant(4, "msg_01", output=3),
                queue("enqueue", 600, "Thread the heddles."),
                queue("dequeue", 600.1),
                user(600.2, "Thread the heddles.", promptSource="queued") | later,
                assistant(604, "msg_02", output=3) | later,
            ],
        )

        assert [
            (launch.started_at, launch.ended_at) for launch in publication.launches
        ] == [(moment(1), moment(4)), (moment(600), moment(604))]
        assert publication.launches[1].prompts[0].received_at == moment(600)

    def test_the_queues_lines_a_line_of_its_own_version_follows_stay_the_launchs(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            [
                typed(1),
                assistant(4, "msg_01", output=3),
                queue("enqueue", 5, "Thread the heddles."),
                user(6, "Thread the heddles.", promptSource="queued"),
                assistant(8, "msg_02", output=3),
                queue("enqueue", 9, "Beat the weft."),
                typed(600) | {"version": "2.1.318"},
            ],
        )

        assert [
            (launch.started_at, launch.ended_at) for launch in publication.launches
        ] == [(moment(1), moment(8)), (moment(9), moment(600))]

    def test_a_launch_ran_the_version_its_first_line_naming_one_names(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            [
                queue("enqueue", 0, "Warp the loom."),
                typed(1) | {"version": "2.1.317"},
                assistant(4, "msg_01", output=3) | {"version": "2.1.317"},
                cost(),
                queue("enqueue", 59, "Beat the weft."),
                typed(60) | {"version": "2.1.320"},
            ],
        )

        assert [
            [(used.component, used.version) for used in launch.components]
            for launch in publication.launches
        ] == [[("claude-code", "2.1.317")], [("claude-code", "2.1.320")]]
        assert [launch.started_at for launch in publication.launches] == [
            moment(0),
            moment(59),
        ]

    def test_a_launch_ends_at_its_last_line_with_a_time(self, tmp_path: Path) -> None:
        """The open Launch's last so far: no line tells a running process
        from a killed one."""
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(1),
                    requesting(4, "toolu_01", message_id="msg_01"),
                    result(7, "toolu_01"),
                    beside("last-prompt", lastPrompt="Warp the loom."),
                    cost(),
                    typed(60),
                    assistant(64, "msg_02", output=3),
                    queue("enqueue", 70, "Beat the weft."),
                ]
            ),
        )

        assert [launch.ended_at for launch in publication.launches] == [
            moment(7),
            moment(70),
        ]

    def test_a_launch_starts_at_its_first_line_and_ends_at_its_last_whatever_their_times(
        self, tmp_path: Path
    ) -> None:
        """A history copied in as a session is picked up carries the times it
        was first written at."""
        publication = _read(
            tmp_path,
            [
                queue("enqueue", 3_600, "Warp the loom."),
                typed(10),
                assistant(14, "msg_01", output=3),
            ],
        )

        (launch,) = publication.launches
        assert (launch.started_at, launch.ended_at) == (moment(3_600), moment(14))

    def test_no_time_is_read_off_a_cost_line(self, tmp_path: Path) -> None:
        """A `--resume` carries the process before's start over in its own
        cost line."""
        began = (moment(-7_200) - datetime.fromtimestamp(0, UTC)).total_seconds()
        cost_line = cost() | {"startTime": int(began * 1_000)}
        publication = _read(
            tmp_path,
            [
                typed(1),
                assistant(4, "msg_01", output=3),
                cost_line,
                typed(60),
                assistant(64, "msg_02", output=3),
                cost_line,
            ],
        )

        assert [
            (launch.started_at, launch.ended_at) for launch in publication.launches
        ] == [(moment(1), moment(4)), (moment(60), moment(64))]

    def test_a_launch_whose_lines_name_no_version_is_not_published(
        self, tmp_path: Path
    ) -> None:
        exited = [typed(1), assistant(4, "msg_01", output=3), cost()]
        queued = [*exited, queue("enqueue", 60, "Thread the heddles.")]

        assert len(_read(tmp_path, exited).launches) == 1
        assert len(_read(tmp_path, queued).launches) == 1
        assert [
            launch.started_at
            for launch in _read(
                tmp_path,
                [*queued, user(62, "Thread the heddles.", promptSource="queued")],
            ).launches
        ] == [moment(1), moment(60)]

    def test_a_launch_that_received_a_prompt_and_names_no_version_is_refused(
        self, tmp_path: Path
    ) -> None:
        """Dropped with its Prompts, it would leave every later Call's
        prompt a place too high."""
        unnamed = user(62, "Thread the heddles.", promptSource="queued")
        del unnamed["version"]

        with pytest.raises(
            UnreadableError,
            match="a launch received a prompt and none of its lines names"
            " Claude Code's version",
        ):
            _read(
                tmp_path,
                [
                    typed(1),
                    assistant(4, "msg_01", output=3),
                    cost(),
                    queue("enqueue", 60, "Thread the heddles."),
                    unnamed,
                ],
            )

    def test_a_file_with_no_timed_line_has_no_launch(self, tmp_path: Path) -> None:
        publication = _read(
            tmp_path, [beside("ai-title", aiTitle="Looms", cwd=DIRECTORY), cost()]
        )

        assert publication.launches == []

    def test_a_sub_agents_thread_has_no_launch(self, tmp_path: Path) -> None:
        lines = [typed(0), assistant(4, output=3), cost(), typed(60)]

        publication = read(filed(tmp_path, lines, AGENT), SETTINGS).publication

        assert publication.launches == []
        assert [call.prompt for call in publication.calls] == [None]


def _components(publication: PublicationSchema) -> list[list[tuple[str, str]]]:
    """Each Launch's components and their versions."""
    return [
        [(used.component, used.version) for used in launch.components]
        for launch in publication.launches
    ]


AGENT_PROMPT = (
    "You write one phase. Read"
    f" {support.CACHE}/dev/0.10.92/docs/close-out.md before you hand back."
)
"""The system prompt of a session started as a plugin's agent."""


class TestComponents:
    def test_a_plugins_skill_names_the_version_its_process_loaded(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    expanded(1, None, support.plugin_body("dev", "0.10.92", "writing")),
                    assistant(4, "msg_01", output=3),
                ]
            ),
        )

        (launch,) = publication.launches
        assert _components(publication) == [
            [("claude-code", support.VERSION), ("plugin:dev", "0.10.92")]
        ]
        assert [used.released_at for used in launch.components] == [None, None]

    def test_the_skills_an_invoked_skills_attachment_shows_again_name_theirs(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    invoked(
                        1,
                        ("kubecoder:usage", support.plugin_body("kubecoder", "0.15.4")),
                        ("weave", BODY),
                    ),
                    assistant(4, "msg_01", output=3),
                ]
            ),
        )

        assert _components(publication) == [
            [("claude-code", support.VERSION), ("plugin:kubecoder", "0.15.4")]
        ]

    @pytest.mark.parametrize(
        "recorded",
        [
            [
                shaped(0.5, system=(AGENT_PROMPT,)),
                request(1, shapeHash="shape-1"),
                sent(assistant(4, "msg_01", output=3)),
            ],
            [snapshot(0.5, AGENT_PROMPT), assistant(4, "msg_01", output=3)],
        ],
        ids=["the shape its request sent", "a snapshot"],
    )
    def test_a_plugins_agents_system_prompt_names_its_version(
        self, recorded: list[Line], tmp_path: Path
    ) -> None:
        publication = _read(tmp_path, linked([typed(0), *recorded]))

        assert _components(publication) == [
            [("claude-code", support.VERSION), ("plugin:dev", "0.10.92")]
        ]

    def test_a_later_launchs_first_request_names_its_shapes_plugins_again(
        self, tmp_path: Path
    ) -> None:
        """A process picked up names the shapes an earlier one's lines
        record."""
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    shaped(0.5, system=(AGENT_PROMPT,)),
                    request(1, shapeHash="shape-1"),
                    sent(assistant(4, "msg_01", output=3)),
                    cost(),
                    typed(60),
                    request(61, "request-2", shapeHash="shape-1"),
                    sent(assistant(64, "msg_02", output=3), "request-2"),
                ]
            ),
        )

        assert (
            _components(publication)
            == [[("claude-code", support.VERSION), ("plugin:dev", "0.10.92")]] * 2
        )

    def test_the_shape_a_later_calls_request_names_names_no_plugin(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    shaped(0.5),
                    request(1, shapeHash="shape-1"),
                    sent(assistant(4, "msg_01", output=3)),
                    shaped(5, "shape-2", system=(AGENT_PROMPT,)),
                    request(6, "request-2", shapeHash="shape-2"),
                    sent(assistant(9, "msg_02", output=3), "request-2"),
                ]
            ),
        )

        assert _components(publication) == [[("claude-code", support.VERSION)]]

    def test_a_path_quoted_names_no_version(self, tmp_path: Path) -> None:
        """By a prompt, a tool's result, the model, or a skill's body past
        its base directory."""
        quoted = f"Read {support.CACHE}/dev/0.9.13/skills/writing/SKILL.md first."
        said = answering(
            4,
            "msg_01",
            {"type": "text", "text": quoted},
            {"type": "tool_use", "id": "toolu_01", "name": "Read", "input": {}},
        )
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0, quoted),
                    said,
                    result(6, "toolu_01", quoted),
                    expanded(7, None, f"{BODY}\n{quoted}"),
                    assistant(9, "msg_02", output=3),
                ]
            ),
        )

        assert _components(publication) == [[("claude-code", support.VERSION)]]

    def test_a_plugin_keeps_the_version_first_named(self, tmp_path: Path) -> None:
        """A Launch names one version of each Component, which Pilot refuses
        two of."""
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    expanded(1, None, support.plugin_body("dev", "0.9.13")),
                    expanded(2, None, support.plugin_body("kubecoder", "0.15.4")),
                    expanded(3, None, support.plugin_body("dev", "0.9.20")),
                    assistant(4, "msg_01", output=3),
                ]
            ),
        )

        assert _components(publication) == [
            [
                ("claude-code", support.VERSION),
                ("plugin:dev", "0.9.13"),
                ("plugin:kubecoder", "0.15.4"),
            ]
        ]

    def test_each_launch_names_the_plugins_its_own_lines_name(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    expanded(1, None, support.plugin_body("dev", "0.9.13")),
                    assistant(4, "msg_01", output=3),
                    cost(),
                    typed(60),
                    assistant(64, "msg_02", output=3),
                    cost(),
                    typed(90),
                    expanded(91, None, support.plugin_body("dev", "0.9.20")),
                    assistant(94, "msg_03", output=3),
                ]
            ),
        )

        assert _components(publication) == [
            [("claude-code", support.VERSION), ("plugin:dev", "0.9.13")],
            [("claude-code", support.VERSION)],
            [("claude-code", support.VERSION), ("plugin:dev", "0.9.20")],
        ]


class TestPrompts:
    def test_a_prompt_is_a_user_line_whose_source_claude_code_names(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            [
                user(0, "Warp the loom.", promptSource="sdk"),
                user(10, "Tie on.", promptSource="typed"),
                user(20, "A shed finished.", promptSource="system"),
                user(30, "Beat.", promptSource="queued"),
                user(40, "Weave on.", promptSource="suggestion_accepted"),
            ],
        )

        (launch,) = publication.launches
        assert [
            (prompt.received_at, prompt.source, prompt.characters)
            for prompt in launch.prompts
        ] == [
            (moment(0), "sdk", 14),
            (moment(10), "typed", 7),
            (moment(20), "system", 16),
            (moment(30), "queued", 5),
            (moment(40), "suggestion_accepted", 9),
        ]

    @pytest.mark.parametrize(
        ("fields", "source"),
        [
            ({"turnOrigin": "human"}, "typed"),
            ({"turnOrigin": "sdk"}, "sdk"),
            ({"turnOrigin": "task_notification"}, "system"),
            ({"origin": {"kind": "human"}}, "typed"),
            ({"origin": {"kind": "task-notification"}}, "system"),
            ({"turnOrigin": "scheduled"}, "scheduled"),
            ({"origin": {"kind": "peer"}}, "peer"),
            ({"turnOrigin": "sdk", "origin": {"kind": "human"}}, "sdk"),
            ({"promptSource": "queued", "turnOrigin": "human"}, "queued"),
            (
                {"promptSource": "system", "origin": {"kind": "peer"}, "isMeta": True},
                "system",
            ),
            (
                {
                    "turnOrigin": "task_notification",
                    "permissionMode": "default",
                    "entrypoint": "cli",
                },
                "system",
            ),
        ],
    )
    def test_an_older_fields_word_is_read_in_the_newer_where_it_means_the_same(
        self, fields: dict[str, Any], source: str, tmp_path: Path
    ) -> None:
        publication = _read(tmp_path, [user(0, "Warp the loom.", **fields)])

        assert _sources(publication) == [source]

    @pytest.mark.parametrize(
        ("entrypoint", "mode", "source"),
        [
            ("cli", "default", "typed"),
            ("cli", "acceptEdits", "typed"),
            ("sdk-cli", "bypassPermissions", "sdk"),
            ("sdk-ts", "default", "sdk"),
        ],
    )
    def test_an_older_prompt_that_names_no_source_is_read_by_its_entry_point(
        self, entrypoint: str, mode: str, source: str, tmp_path: Path
    ) -> None:
        """Before Claude Code 2.1.161 a prompt a person typed or a caller
        sent names no source: `sdk` in a headless session, `typed` in an
        interactive one."""
        older = user(0, "Warp the loom.", permissionMode=mode, entrypoint=entrypoint)

        publication = _read(tmp_path, [older, assistant(4, output=3)])

        assert _sources(publication) == [source]
        assert [call.prompt for call in publication.calls] == [1]

    @pytest.mark.parametrize(
        "line",
        [
            user(5, "Warp the loom."),
            user(5, "Warp the loom.", permissionMode="default"),
            user(5, "Warp the loom.", entrypoint="cli"),
            user(5, "Warp the loom.", permissionMode="default", entrypoint="desktop"),
            user(5, [{"type": "text", "text": "[Request interrupted by user]"}]),
            user(5, "The skill's words.", isMeta=True, origin={"kind": "human"}),
            user(
                5,
                "The skill's words.",
                isMeta=True,
                permissionMode="default",
                entrypoint="cli",
            ),
            user(5, "What came before.", isCompactSummary=True),
            result(5),
            taken(5, "! ls looms", "bash"),
            chained(
                "attachment",
                5,
                attachment={
                    "type": "hook_additional_context",
                    "content": ["Mind the selvedge."],
                    "hookEvent": "UserPromptSubmit",
                },
            ),
        ],
        ids=[
            "no word",
            "no word, a permission mode and no entry point",
            "no word, an entry point and no permission mode",
            "no word, an entry point neither headless nor interactive",
            "an interruption",
            "a skill's words",
            "a skill's words, in an older session",
            "a compaction's summary",
            "a tool's result",
            "a message taken in the middle of a run of another mode",
            "a hook's added context",
        ],
    )
    def test_a_line_whose_source_claude_code_does_not_name_is_no_prompt(
        self, line: Line, tmp_path: Path
    ) -> None:
        publication = _read(tmp_path, [typed(0), line, assistant(9, output=3)])

        assert _sources(publication) == ["typed"]
        assert [call.prompt for call in publication.calls] == [1]

    def test_a_prompts_length_is_its_words_a_lists_text_blocks_together(
        self, tmp_path: Path
    ) -> None:
        blocks = [
            {"type": "text", "text": "Match this "},
            {"type": "image", "source": {"type": "base64", "data": "aGVkZGxl"}},
            {"type": "text", "text": "twill."},
        ]

        publication = _read(tmp_path, [typed(0, "Schußfaden"), typed(5, blocks)])

        (launch,) = publication.launches
        assert [prompt.characters for prompt in launch.prompts] == [10, 17]

    def test_a_prompt_that_waited_was_received_when_it_was_queued(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            [
                queue("enqueue", 0, "Warp the loom."),
                queue("dequeue", 2),
                user(2.5, "Warp the loom.", promptSource="sdk"),
            ],
        )

        (launch,) = publication.launches
        assert launch.started_at == moment(0)
        assert [prompt.received_at for prompt in launch.prompts] == [moment(0)]

    def test_a_prompt_takes_the_queues_first_of_its_text_and_no_other(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            [
                typed(0),
                queue("enqueue", 10, "A shed finished."),
                queue("enqueue", 11, "Beat."),
                queue("enqueue", 12, "Beat."),
                typed(20, "Tie on."),
                queue("dequeue", 30),
                user(31, "Beat.", promptSource="queued"),
                queue("dequeue", 40),
                user(41, [{"type": "text", "text": "Beat."}], promptSource="queued"),
                queue("dequeue", 50),
                user(51, "Beat.", promptSource="queued"),
                queue("dequeue", 60),
                user(61, "A shed finished.", promptSource="system"),
            ],
        )

        (launch,) = publication.launches
        assert [prompt.received_at for prompt in launch.prompts] == [
            moment(0),
            moment(20),
            moment(11),
            moment(12),
            moment(51),
            moment(10),
        ]

    def test_a_prompt_the_queue_let_go_of_lends_no_later_one_its_time(
        self, tmp_path: Path
    ) -> None:
        """A `remove` names the prompt it takes out by its text, and one
        that names none takes none out; a `popAll` empties the queue."""
        publication = _read(
            tmp_path,
            [
                typed(0),
                queue("enqueue", 20, "Tie on."),
                queue("enqueue", 21, "Weave on."),
                queue("popAll", 22, "Tie on.\nWeave on."),
                queue("enqueue", 30, "Thread the heddles."),
                queue("remove", 31),
                queue("enqueue", 40, "Beat."),
                queue("remove", 42, "Beat."),
                user(100, "Beat.", promptSource="queued"),
                user(110, "Tie on.", promptSource="queued"),
                user(120, "Weave on.", promptSource="queued"),
                user(130, "Thread the heddles.", promptSource="queued"),
            ],
        )

        (launch,) = publication.launches
        assert [prompt.received_at for prompt in launch.prompts] == [
            moment(0),
            moment(100),
            moment(110),
            moment(120),
            moment(30),
        ]

    def test_a_message_taken_in_the_middle_of_a_run_is_a_prompt(
        self, tmp_path: Path
    ) -> None:
        """A task notification reads `system` and a person's message
        `queued`, received when it was queued, else at its own time; the
        Calls after it follow it."""
        publication = _read(
            tmp_path,
            [
                typed(0),
                assistant(4, "msg_01", output=3),
                queue("enqueue", 5, NOTIFIED),
                taken(8, NOTIFIED, "task-notification"),
                assistant(9, "msg_02", output=3),
                queue("enqueue", 10, "Beat."),
                taken(13, [{"type": "text", "text": "Beat."}]),
                assistant(14, "msg_03", output=3),
                taken(20, "Weave on."),
                assistant(21, "msg_04", output=3),
            ],
        )

        (launch,) = publication.launches
        assert [
            (prompt.received_at, prompt.source, prompt.characters)
            for prompt in launch.prompts
        ] == [
            (moment(0), "typed", 14),
            (moment(5), "system", len(NOTIFIED)),
            (moment(10), "queued", 5),
            (moment(20), "queued", 9),
        ]
        assert [call.prompt for call in publication.calls] == [1, 2, 3, 4]

    def test_one_a_remove_took_out_of_the_queue_first_was_received_when_queued(
        self, tmp_path: Path
    ) -> None:
        """Claude Code writes the queue's `remove` of a message it takes in
        the middle of a run before the attachment or after it."""
        publication = _read(
            tmp_path,
            [
                typed(0),
                queue("enqueue", 10, "Beat."),
                queue("enqueue", 11, "Tie on."),
                queue("remove", 12, "Tie on."),
                queue("remove", 12, "Beat."),
                assistant(12.5, "msg_01", output=3),
                taken(13, "Beat."),
                taken(13, "Tie on."),
                queue("enqueue", 20, "Weave on."),
                taken(22, "Weave on."),
                queue("remove", 22, "Weave on."),
            ],
        )

        (launch,) = publication.launches
        assert [prompt.received_at for prompt in launch.prompts] == [
            moment(0),
            moment(10),
            moment(11),
            moment(20),
        ]

    def test_one_takes_its_text_out_of_the_queue(self, tmp_path: Path) -> None:
        """So a later prompt of its text was received at its own time."""
        publication = _read(
            tmp_path,
            [
                typed(0),
                queue("enqueue", 10, "Beat."),
                taken(13, "Beat."),
                user(100, "Beat.", promptSource="queued"),
            ],
        )

        (launch,) = publication.launches
        assert [prompt.received_at for prompt in launch.prompts] == [
            moment(0),
            moment(10),
            moment(100),
        ]

    def test_a_process_that_exits_lends_the_next_one_none_a_remove_took_out(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            [
                typed(0),
                queue("enqueue", 10, "Beat."),
                queue("remove", 11, "Beat."),
                cost(),
                typed(60),
                taken(70, "Beat."),
            ],
        )

        assert [
            [prompt.received_at for prompt in launch.prompts]
            for launch in publication.launches
        ] == [[moment(0)], [moment(60), moment(70)]]

    def test_a_sub_agents_message_taken_in_the_middle_of_a_run_is_no_prompt(
        self, tmp_path: Path
    ) -> None:
        lines = [user(0, "Count the heddles."), taken(3, "Beat."), assistant(4)]

        publication = read(filed(tmp_path, lines, AGENT), SETTINGS).publication

        assert [call.prompt for call in publication.calls] == [None]

    def test_a_queued_prompt_a_process_never_took_lends_the_next_process_no_time(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            [
                typed(0),
                queue("enqueue", 10, "Beat."),
                cost(),
                user(100, "Beat.", promptSource="queued"),
            ],
        )

        assert [
            [prompt.received_at for prompt in launch.prompts]
            for launch in publication.launches
        ] == [[moment(0)], [moment(100)]]


class TestCalls:
    def test_a_call_is_its_responses_lines_and_its_facts_the_last_ones(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            [
                typed(0),
                assistant(4.0, "msg_01", input=12, cache_read=900, output=1),
                assistant(4.5, "msg_01", input=12, cache_read=900, output=1),
                assistant(
                    5.25,
                    "msg_01",
                    input=12,
                    cache_write_5m=40,
                    cache_write_1h=700,
                    cache_read=900,
                    output=318,
                ),
                result(8),
                assistant(9, "msg_02", "claude-haiku-4-5", output=6),
            ],
        )

        first, second = publication.calls
        assert first.message_id == "msg_01"
        assert first.completed_at == moment(5.25)
        assert first.model == "claude-opus-4-5"
        assert first.tokens == {
            "input": 12,
            "cache_write_5m": 40,
            "cache_write_1h": 700,
            "cache_read": 900,
            "output": 318,
        }
        assert (second.message_id, second.model) == ("msg_02", "claude-haiku-4-5")
        assert second.tokens == {"output": 6}

    def test_a_call_is_placed_by_its_first_line(self, tmp_path: Path) -> None:
        publication = _read(
            tmp_path,
            [
                typed(0),
                assistant(4, "msg_01", output=1),
                assistant(5, "msg_02", output=2),
                assistant(6, "msg_01", output=9),
                assistant(7, "msg_03", output=3),
            ],
        )

        assert [
            (call.message_id, call.completed_at, call.tokens)
            for call in publication.calls
        ] == [
            ("msg_01", moment(6), {"output": 9}),
            ("msg_02", moment(5), {"output": 2}),
            ("msg_03", moment(7), {"output": 3}),
        ]

    def test_a_call_follows_the_prompt_before_its_first_line(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            [
                assistant(0, "msg_01", output=1),
                typed(1),
                assistant(4, "msg_02", output=1),
                typed(5, "Tie on."),
                assistant(6, "msg_02", output=7),
                assistant(7, "msg_03", output=1),
                cost(),
                typed(60, "Beat."),
                assistant(64, "msg_04", output=1),
            ],
        )

        assert [(call.message_id, call.prompt) for call in publication.calls] == [
            ("msg_01", None),
            ("msg_02", 1),
            ("msg_03", 2),
            ("msg_04", 3),
        ]

    def test_a_line_claude_code_wrote_itself_is_no_call(self, tmp_path: Path) -> None:
        publication = _read(
            tmp_path,
            [
                typed(0),
                assistant(4, "msg_01", output=3),
                assistant(5, "5c0e-a1", "<synthetic>") | {"isApiErrorMessage": True},
            ],
        )

        assert [call.message_id for call in publication.calls] == ["msg_01"]

    def test_a_sub_agents_calls_are_read_as_a_main_threads(
        self, tmp_path: Path
    ) -> None:
        lines = [
            user(0, "Count the heddles."),
            assistant(3, "msg_07", input=5, output=1),
            assistant(4, "msg_07", input=5, output=22),
        ]

        (call,) = read(filed(tmp_path, lines, AGENT), SETTINGS).publication.calls

        assert (call.message_id, call.completed_at) == ("msg_07", moment(4))
        assert call.tokens == {"input": 5, "output": 22}


class TestASendingTime:
    def test_a_call_was_sent_when_the_request_its_lines_name_was_written(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            [
                typed(0),
                request(1, "request-1"),
                sent(assistant(4, "msg_01", output=1), "request-1"),
                sent(assistant(5, "msg_01", output=3), "request-1"),
                result(6),
                request(6.5, "request-2"),
                sent(assistant(9, "msg_02"), "request-2"),
            ],
        )

        assert _sends(publication) == [("msg_01", moment(1)), ("msg_02", moment(6.5))]

    def test_a_retried_request_was_sent_when_the_last_its_call_names_was(
        self, tmp_path: Path
    ) -> None:
        """A retry writes its request line again, and the Call names the
        last."""
        publication = _read(
            tmp_path,
            [
                typed(0),
                request(1, "request-1"),
                request(1.3, "request-2"),
                sent(assistant(4, "msg_01"), "request-2"),
            ],
        )

        assert _sends(publication) == [("msg_01", moment(1.3))]

    def test_a_call_that_names_no_request_was_sent_at_none(
        self, tmp_path: Path
    ) -> None:
        """A version that records no send writes no request line, and no
        `requestRef` names one."""
        publication = _read(
            tmp_path, [typed(0), request(1), assistant(4, "msg_01", output=1)]
        )

        assert _sends(publication) == [("msg_01", None)]

    def test_a_request_its_file_holds_no_line_of_was_sent_at_none(
        self, tmp_path: Path
    ) -> None:
        """A fork's requests are written in its main thread's file, and a
        history copied in names those of the file it was copied from."""
        publication = _read(
            tmp_path,
            [typed(0), request(1), sent(assistant(4), "a-request-of-another-file")],
        )

        assert _sends(publication) == [("msg_01", None)]

    def test_a_request_written_after_its_calls_first_line_is_not_its_send(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            [
                typed(0),
                sent(assistant(4, "msg_01", output=1)),
                request(4.5),
                sent(assistant(5, "msg_01", output=3)),
            ],
        )

        assert _sends(publication) == [("msg_01", None)]

    def test_the_request_written_before_a_responses_lines_is_the_next_calls(
        self, tmp_path: Path
    ) -> None:
        """Claude Code may write the next request before the lines of the
        response it follows."""
        publication = _read(
            tmp_path,
            [
                typed(0),
                request(1, "request-1"),
                request(4.2, "request-2"),
                sent(assistant(4, "msg_01"), "request-1"),
                sent(assistant(9, "msg_02"), "request-2"),
            ],
        )

        assert _sends(publication) == [("msg_01", moment(1)), ("msg_02", moment(4.2))]

    def test_a_request_a_call_named_and_those_before_it_are_no_later_calls(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            [
                typed(0),
                request(1, "request-1"),
                request(2, "request-2"),
                sent(assistant(4, "msg_01"), "request-2"),
                sent(assistant(9, "msg_02"), "request-1"),
                sent(assistant(12, "msg_03"), "request-2"),
            ],
        )

        assert _sends(publication) == [
            ("msg_01", moment(2)),
            ("msg_02", None),
            ("msg_03", None),
        ]

    def test_a_line_claude_code_wrote_itself_takes_no_request(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            [
                typed(0),
                request(1),
                sent(synthetic(2, "API Error: 529 overloaded")),
                sent(assistant(4)),
            ],
        )

        assert _sends(publication) == [("msg_01", moment(1))]

    def test_a_sub_agents_calls_are_sent_as_a_main_threads(
        self, tmp_path: Path
    ) -> None:
        lines = [
            user(0, "Count the heddles."),
            request(1),
            sent(assistant(3, "msg_07")),
        ]

        publication = read(filed(tmp_path, lines, AGENT), SETTINGS).publication

        assert _sends(publication) == [("msg_07", moment(1))]


class TestOwnChoices:
    def test_a_calls_choices_are_what_its_lines_name(self, tmp_path: Path) -> None:
        (call,) = _read(
            tmp_path,
            [
                typed(0),
                finished(assistant(4, output=12), 60, "max_tokens")
                | {
                    "requestedModel": "claude-opus-4-1",
                    "effort": "high",
                    "attributionSkill": "loom:warping",
                    "attributionPlugin": "loom",
                },
            ],
        ).calls

        assert (call.model, call.requested_model) == (
            "claude-opus-4-5",
            "claude-opus-4-1",
        )
        assert (call.effort, call.attributed_skill, call.attributed_plugin) == (
            "high",
            "loom:warping",
            "loom",
        )
        assert (call.thinking_tokens, call.stop_reason) == (60, "max_tokens")

    def test_a_model_asked_for_that_answered_is_none(self, tmp_path: Path) -> None:
        """Pilot refuses a `requested_model` that is the Call's `model`."""
        (call,) = _read(
            tmp_path,
            [typed(0), assistant(4) | {"requestedModel": "claude-opus-4-5"}],
        ).calls

        assert call.requested_model is None

    def test_a_fallback_block_names_the_model_asked_for(self, tmp_path: Path) -> None:
        """A fallback's request may name the model that answered it."""
        (call,) = _read(
            tmp_path,
            [
                typed(0),
                answering(4, "msg_01", fallback("claude-opus-4-1"))
                | {"requestedModel": "claude-opus-4-5"},
                assistant(5) | {"requestedModel": "claude-opus-4-5"},
            ],
        ).calls

        assert call.requested_model == "claude-opus-4-1"

    def test_a_fallbacks_line_names_the_model_its_requests_call_asked_for(
        self, tmp_path: Path
    ) -> None:
        """It follows the Call, and names the request the Call answered."""
        publication = _read(
            tmp_path,
            [
                typed(0),
                assistant(4, "msg_01") | {"requestId": "req_01"},
                assistant(9, "msg_02") | {"requestId": "req_02"},
                assistant(10, "msg_02") | {"requestId": "req_02"},
                fell_back(10.2, "req_02", "claude-opus-4-1"),
            ],
        )

        assert [
            (call.message_id, call.requested_model) for call in publication.calls
        ] == [
            ("msg_01", None),
            ("msg_02", "claude-opus-4-1"),
        ]

    def test_a_fallbacks_line_that_names_no_calls_request_is_none(
        self, tmp_path: Path
    ) -> None:
        (call,) = _read(
            tmp_path,
            [
                typed(0),
                assistant(4) | {"requestId": "req_01"},
                fell_back(4.2, "req_of_no_call", "claude-opus-4-1"),
            ],
        ).calls

        assert call.requested_model is None

    def test_a_calls_thinking_and_end_are_its_last_lines(self, tmp_path: Path) -> None:
        (call,) = _read(
            tmp_path,
            [
                typed(0),
                finished(assistant(4, output=3), 12, "refusal"),
                finished(assistant(5, output=40), 31, "max_tokens"),
            ],
        ).calls

        assert (call.thinking_tokens, call.stop_reason) == (31, "max_tokens")

    @pytest.mark.parametrize("ended", ["end_turn", "tool_use", None])
    def test_an_ordinary_end_is_no_stop_reason(
        self, ended: str | None, tmp_path: Path
    ) -> None:
        (call,) = _read(tmp_path, [typed(0), finished(assistant(4), 0, ended)]).calls

        assert (call.thinking_tokens, call.stop_reason) == (0, None)

    def test_a_choice_the_lines_name_once_is_the_calls(self, tmp_path: Path) -> None:
        """Before Claude Code 2.1.293 a Call's effort is on some of its
        lines alone."""
        (call,) = _read(
            tmp_path,
            [
                typed(0),
                assistant(4) | {"effort": "medium", "attributionSkill": "loom"},
                assistant(5, output=8),
            ],
        ).calls

        assert (call.effort, call.attributed_skill) == ("medium", "loom")

    def test_an_older_calls_lines_record_no_choice(self, tmp_path: Path) -> None:
        """Its lines name no model asked for, effort or attribution, count
        no thinking tokens, and, before Claude Code 2.1.300, its last line
        may say no end."""
        (call,) = _read(tmp_path, [typed(0), assistant(4), assistant(5)]).calls

        assert call.model_dump(include=set(CHOICES)) == dict.fromkeys(CHOICES)

    def test_a_sub_agents_choices_are_read_as_a_main_threads(
        self, tmp_path: Path
    ) -> None:
        lines = [
            user(0, "Count the heddles."),
            finished(assistant(3, "msg_07", "claude-haiku-4-5"), 9, "refusal")
            | {"requestedModel": "claude-opus-4-5", "effort": "low"},
        ]

        (call,) = read(filed(tmp_path, lines, AGENT), SETTINGS).publication.calls

        assert (call.requested_model, call.effort) == ("claude-opus-4-5", "low")
        assert (call.thinking_tokens, call.stop_reason) == (9, "refusal")


class TestCompactions:
    def test_a_compaction_is_a_boundary_with_what_its_record_gives(
        self, tmp_path: Path
    ) -> None:
        lines = [
            typed(0),
            assistant(4, "msg_01"),
            boundary(30, "manual", 160_400, postTokens=21_300, durationMs=38_000),
            summary(29.7),
            assistant(40, "msg_02"),
            boundary(90, "auto", 171_000, postTokens=19_800, durationMs=41_500),
        ]

        publication = _read(tmp_path, linked(lines))

        assert [made.model_dump() for made in publication.compactions] == [
            {
                "at": moment(30),
                "trigger": "manual",
                "tokens_before": 160_400,
                "tokens_after": 21_300,
                "duration_ms": 38_000,
            },
            {
                "at": moment(90),
                "trigger": "auto",
                "tokens_before": 171_000,
                "tokens_after": 19_800,
                "duration_ms": 41_500,
            },
        ]

    def test_a_version_that_records_neither_gives_no_tokens_after_and_no_duration(
        self, tmp_path: Path
    ) -> None:
        """Before Claude Code 2.1.126 a boundary's record holds its trigger
        and the tokens before it alone."""
        lines = [user(0), assistant(4, "msg_01"), boundary(30, before=88_000)]

        (made,) = read(filed(tmp_path, lines, AGENT), SETTINGS).publication.compactions

        assert (made.trigger, made.tokens_before) == ("auto", 88_000)
        assert (made.tokens_after, made.duration_ms) == (None, None)

    def test_its_summary_is_no_prompt(self, tmp_path: Path) -> None:
        lines = [typed(0), assistant(4, "msg_01"), boundary(30), summary(29.7)]

        assert _sources(_read(tmp_path, linked(lines))) == ["typed"]

    def test_a_system_line_of_another_subtype_is_none(self, tmp_path: Path) -> None:
        lines = [
            typed(0),
            assistant(4, "msg_01"),
            chained("system", 6, subtype="turn_duration", durationMs=6_000),
        ]

        assert _read(tmp_path, linked(lines)).compactions == []

    def test_a_boundary_that_carries_no_record_is_named(self, tmp_path: Path) -> None:
        unrecorded = boundary(30)
        del unrecorded["compactMetadata"]

        with pytest.raises(UnreadableError, match="line 2 is not a line .* KeyError"):
            _read(tmp_path, [typed(0), unrecorded])


class TestACallsChain:
    def test_its_predecessor_is_the_nearest_call_up_its_chain(
        self, tmp_path: Path
    ) -> None:
        lines = [
            typed(0),
            requesting(4, "toolu_01", message_id="msg_01"),
            result(6, "toolu_01"),
            typed(8),
            assistant(10, "msg_02", output=1),
            assistant(11, "msg_02", output=5),
            assistant(14, "msg_03"),
        ]

        assert _chains(_read(tmp_path, linked(lines))) == [
            (None, None),
            ("msg_01", None),
            ("msg_02", None),
        ]

    def test_a_chain_from_a_parallel_tool_call_lands_on_the_call_before(
        self, tmp_path: Path
    ) -> None:
        """Each result follows its own request's line, so the next Call's
        chain reaches a line of the Call before that is not its last."""
        lines = linked(
            [
                typed(0),
                requesting(4, "toolu_01", message_id="msg_01"),
                requesting(4.1, "toolu_02", message_id="msg_01"),
                result(7, "toolu_02"),
                result(6, "toolu_01"),
                assistant(9, "msg_02"),
            ]
        )
        lines[4]["parentUuid"] = "line-2"

        assert _chains(_read(tmp_path, lines)) == [(None, None), ("msg_01", None)]

    def test_a_rewind_follows_the_call_it_went_back_to(self, tmp_path: Path) -> None:
        lines = linked(
            [
                typed(0),
                assistant(4, "msg_01"),
                typed(8),
                assistant(10, "msg_02"),
                typed(20),
                assistant(24, "msg_03"),
            ]
        )
        lines[4]["parentUuid"] = "line-2"

        assert _chains(_read(tmp_path, lines)) == [
            (None, None),
            ("msg_01", None),
            ("msg_01", None),
        ]

    def test_a_line_claude_code_wrote_itself_is_no_predecessor(
        self, tmp_path: Path
    ) -> None:
        lines = [
            typed(0),
            assistant(4, "msg_01"),
            synthetic(6, "No response requested."),
            assistant(9, "msg_02"),
        ]

        assert _chains(_read(tmp_path, linked(lines)))[1] == ("msg_01", None)

    def test_a_chain_that_crosses_a_compaction_names_it_and_goes_on_past_it(
        self, tmp_path: Path
    ) -> None:
        lines = [
            typed(0),
            assistant(4, "msg_01"),
            boundary(30),
            summary(29.7),
            assistant(40, "msg_02"),
            assistant(44, "msg_03"),
            boundary(70),
            summary(69.7),
            typed(80),
            assistant(84, "msg_04"),
        ]

        assert _chains(_read(tmp_path, linked(lines))) == [
            (None, None),
            ("msg_01", 1),
            ("msg_02", None),
            ("msg_03", 2),
        ]

    def test_a_boundary_continues_the_line_it_names_whichever_lies_before_it(
        self, tmp_path: Path
    ) -> None:
        """A compaction the person asked for names the last line of the
        turn before the request."""
        lines = linked(
            [
                typed(0),
                assistant(4, "msg_01"),
                typed(8, "/compact"),
                assistant(9, "msg_02"),
                boundary(30, "manual"),
                summary(29.7),
                assistant(40, "msg_03"),
            ]
        )
        assert lines[4]["logicalParentUuid"] == "line-4"
        lines[4]["logicalParentUuid"] = "line-2"

        assert _chains(_read(tmp_path, lines))[2] == ("msg_01", 1)

    def test_a_boundary_that_names_no_line_of_the_file_leaves_its_compaction_alone(
        self, tmp_path: Path
    ) -> None:
        lines = linked(
            [
                typed(0),
                assistant(4, "msg_01"),
                boundary(30),
                summary(29.7),
                assistant(40, "msg_02"),
            ]
        )
        lines[2]["logicalParentUuid"] = "a-line-of-another-file"

        assert _chains(_read(tmp_path, lines)) == [(None, None), (None, 1)]

    def test_the_nearest_of_the_compactions_a_chain_crosses_is_the_calls(
        self, tmp_path: Path
    ) -> None:
        lines = [
            typed(0),
            assistant(4, "msg_01"),
            boundary(30),
            summary(29.7),
            boundary(50),
            summary(49.7),
            assistant(60, "msg_02"),
        ]

        publication = _read(tmp_path, linked(lines))

        assert len(publication.compactions) == 2
        assert _chains(publication)[1] == ("msg_01", 2)

    @pytest.mark.parametrize(
        "follows",
        [None, "a-line-of-another-file", "line-4"],
        ids=["no line", "a line the file does not hold", "a line after it"],
    )
    def test_a_chain_that_reaches_no_call_has_no_predecessor(
        self, follows: str | None, tmp_path: Path
    ) -> None:
        """A chain's first Call, one after a line in the middle of the file
        that follows none, and one whose chain leaves the file or turns back
        on itself."""
        lines = linked(
            [typed(0), assistant(4, "msg_01"), typed(10), assistant(14, "msg_02")]
        )
        lines[2]["parentUuid"] = follows

        assert _chains(_read(tmp_path, lines)) == [(None, None), (None, None)]

    @pytest.mark.parametrize(
        "between",
        [
            [requesting(4.1, "toolu_01", message_id="msg_01"), result(6, "toolu_01")],
            [
                chained("system", 5, subtype="turn_duration", durationMs=1_000),
                chained("system", 6, subtype="turn_duration", durationMs=1_000),
            ],
        ],
        ids=["a tool's result before its request's line", "a `system` line"],
    )
    def test_a_chain_goes_on_through_a_line_written_before_the_line_it_follows(
        self, between: list[Line], tmp_path: Path
    ) -> None:
        """Claude Code writes some lines before the line their `parentUuid`
        names."""
        lines = linked(
            [typed(0), assistant(4, "msg_01"), *between, assistant(9, "msg_02")]
        )
        early = [lines[at] for at in (0, 1, 3, 2, 4)]

        assert _chains(_read(tmp_path, lines)) == [(None, None), ("msg_01", None)]
        assert _chains(_read(tmp_path, early)) == [(None, None), ("msg_01", None)]

    def test_a_chain_goes_on_through_a_line_written_after_the_call_it_leads_from(
        self, tmp_path: Path
    ) -> None:
        """The line a Call's chain waits for is written once two later Calls
        have begun."""
        lines = linked(
            [
                typed(0),
                assistant(4, "msg_01"),
                chained("system", 5, subtype="turn_duration", durationMs=1_000),
                chained("system", 6, subtype="turn_duration", durationMs=1_000),
                assistant(9, "msg_02"),
                typed(12),
                assistant(14, "msg_03"),
            ]
        )
        late = [lines[at] for at in (0, 1, 3, 4, 5, 6, 2)]

        assert _chains(_read(tmp_path, late)) == [
            (None, None),
            ("msg_01", None),
            ("msg_02", None),
        ]

    def test_a_chain_crosses_a_boundary_written_after_the_line_that_follows_it(
        self, tmp_path: Path
    ) -> None:
        lines = linked(
            [
                typed(0),
                assistant(4, "msg_01"),
                boundary(30),
                summary(29.7),
                assistant(40, "msg_02"),
            ]
        )
        early = [lines[at] for at in (0, 1, 3, 2, 4)]

        assert _chains(_read(tmp_path, early)) == [(None, None), ("msg_01", 1)]

    def test_a_chain_passes_a_line_of_its_own_call(self, tmp_path: Path) -> None:
        """A Call's second line is written before its first, which it
        follows."""
        lines = linked(
            [
                typed(0),
                assistant(4, "msg_01"),
                typed(8),
                assistant(10, "msg_02", output=1),
                assistant(11, "msg_02", output=5),
                assistant(14, "msg_03"),
            ]
        )
        early = [lines[at] for at in (0, 1, 2, 4, 3, 5)]

        assert _chains(_read(tmp_path, early)) == [
            (None, None),
            ("msg_01", None),
            ("msg_02", None),
        ]

    def test_a_chain_passes_a_call_that_began_later_in_the_file(
        self, tmp_path: Path
    ) -> None:
        """A predecessor is an earlier Call: `msg_03`'s chain runs through
        `msg_02`'s line, written after `msg_03` began."""
        lines = linked(
            [
                typed(0),
                assistant(4, "msg_01"),
                typed(8),
                assistant(10, "msg_02"),
                typed(12),
                assistant(14, "msg_03"),
            ]
        )
        late = [lines[at] for at in (0, 1, 2, 4, 5, 3)]

        publication = _read(tmp_path, late)

        assert [call.message_id for call in publication.calls] == [
            "msg_01",
            "msg_03",
            "msg_02",
        ]
        assert _chains(publication) == [
            (None, None),
            ("msg_01", None),
            ("msg_01", None),
        ]

    def test_a_sub_agents_chain_is_read_as_a_main_threads(self, tmp_path: Path) -> None:
        lines = linked(
            [
                user(0),
                assistant(4, "msg_01"),
                boundary(30),
                summary(29.7),
                assistant(40, "msg_02"),
            ]
        )

        publication = read(filed(tmp_path, lines, AGENT), SETTINGS).publication

        assert len(publication.compactions) == 1
        assert _chains(publication) == [(None, None), ("msg_01", 1)]


class TestACacheMiss:
    @pytest.mark.parametrize(
        ("spent", "missed"),
        [
            ({"cache_read": 1_000, "cache_write_5m": 50}, False),
            ({"cache_read": 500, "cache_write_5m": 550}, False),
            ({"cache_read": 499, "cache_write_5m": 551}, True),
            ({"cache_write_5m": 899}, False),
            ({"cache_write_5m": 900}, True),
            ({"input": 900}, True),
            ({"cache_read": 300, "cache_write_5m": 5_000}, True),
        ],
        ids=[
            "read all",
            "half unread",
            "more than half unread",
            "under nine tenths",
            "nine tenths",
            "its input counts",
            "more than was left",
        ],
    )
    def test_a_call_missed_where_more_than_half_of_what_was_left_was_unread(
        self, spent: dict[str, int], missed: bool, tmp_path: Path
    ) -> None:
        """DB 546: of the lesser of what its predecessor left and its own
        context, and with that context at least nine tenths of what was
        left."""
        publication = _read(tmp_path, _missed(**spent))

        assert [call.miss_cause for call in publication.calls] == [
            None,
            "unknown" if missed else None,
        ]

    def test_a_call_with_no_predecessor_missed_nothing(self, tmp_path: Path) -> None:
        lines = [typed(0), assistant(4, "msg_01", cache_write_5m=1_000)]

        assert _read(tmp_path, linked(lines)).calls[0].miss_cause is None
        assert (
            _read(tmp_path, _missed(cache_write_5m=1_000)[:2]).calls[0].miss_cause
            is None
        )

    def test_what_a_predecessor_left_is_what_it_read_and_wrote(
        self, tmp_path: Path
    ) -> None:
        lines = linked(
            [
                typed(0),
                assistant(4, "msg_01", cache_read=600, cache_write_1h=400),
                assistant(9, "msg_02", cache_read=400, cache_write_5m=600),
            ]
        )

        assert _read(tmp_path, lines).calls[1].miss_cause == "unknown"

    @pytest.mark.parametrize(
        ("changed", "cause"),
        [
            ({"model": "claude-haiku-4-5"}, "model"),
            ({"effort": "low"}, "model"),
            ({"version": "2.1.318"}, "version"),
            ({}, "unknown"),
        ],
        ids=["the model", "the effort", "the version", "nothing"],
    )
    def test_a_cause_is_what_changed_from_its_predecessor(
        self, changed: dict[str, str], cause: str, tmp_path: Path
    ) -> None:
        lines = _missed(cache_write_5m=1_000)
        lines[1] |= {"effort": "high"}
        lines[2] |= {"effort": "high"} | {
            name: value for name, value in changed.items() if name != "model"
        }
        if "model" in changed:
            lines[2]["message"]["model"] = changed["model"]

        assert _read(tmp_path, lines).calls[1].miss_cause == cause

    def test_an_effort_one_of_them_names_alone_changed_nothing(
        self, tmp_path: Path
    ) -> None:
        lines = _missed(cache_write_5m=1_000)
        lines[2] |= {"effort": "low"}

        assert _read(tmp_path, lines).calls[1].miss_cause == "unknown"

    def test_a_chain_that_crossed_a_compaction_is_the_first_cause(
        self, tmp_path: Path
    ) -> None:
        lines = linked(
            [
                typed(0),
                assistant(4, "msg_01", cache_write_5m=1_000),
                boundary(500),
                summary(499.7),
                assistant(510, "msg_02", model="claude-haiku-4-5", cache_write_5m=950),
            ]
        )

        assert _read(tmp_path, lines).calls[1].miss_cause == "compaction"

    @pytest.mark.parametrize(
        ("written", "seconds", "cause"),
        [
            ("cache_write_5m", 304, "unknown"),
            ("cache_write_5m", 304.001, "ttl"),
            ("cache_write_1h", 3_604, "unknown"),
            ("cache_write_1h", 3_604.001, "ttl"),
        ],
        ids=[
            "five minutes",
            "past five minutes",
            "an hour",
            "past an hour",
        ],
    )
    def test_a_wait_past_what_its_predecessor_left_lasts_is_ttl(
        self, written: str, seconds: float, cause: str, tmp_path: Path
    ) -> None:
        """What a Call wrote to the cache that lasts an hour lasts an hour,
        and anything else five minutes; the wait runs from the predecessor's
        completion to the Call's completion, where it names no request."""
        lines = linked(
            [
                typed(0),
                assistant(4, "msg_01", "claude-opus-4-5", **{written: 1_000}),
                assistant(seconds, "msg_02", cache_write_5m=1_000),
            ]
        )

        assert _read(tmp_path, lines).calls[1].miss_cause == cause

    def test_a_wait_runs_to_the_calls_sending_time(self, tmp_path: Path) -> None:
        lines = linked(
            [
                typed(0),
                assistant(4, "msg_01", cache_write_5m=1_000),
                request(300),
                sent(assistant(900, "msg_02", cache_write_5m=1_000)),
            ]
        )

        assert _read(tmp_path, lines).calls[1].miss_cause == "unknown"

    def test_a_predecessor_that_is_not_the_call_before_is_a_rewind(
        self, tmp_path: Path
    ) -> None:
        lines = linked(
            [
                typed(0),
                assistant(4, "msg_01", cache_write_5m=1_000),
                typed(8),
                assistant(10, "msg_02", cache_read=1_000),
                typed(20),
                assistant(24, "msg_03", cache_write_5m=1_000),
            ]
        )
        lines[4]["parentUuid"] = "line-2"

        assert [call.miss_cause for call in _read(tmp_path, lines).calls] == [
            None,
            None,
            "rewind",
        ]

    @pytest.mark.parametrize(
        ("first", "second", "cause"),
        [
            ({"shapeHash": "a1"}, {"shapeHash": "b2"}, "system"),
            ({"shapeHash": "a1"}, {}, "unknown"),
            ({"keep": 3, "tail": ["d", "e"]}, {"keep": 4, "tail": ["f"]}, "history"),
            ({"keep": 3, "tail": ["d", "e"]}, {"keep": 5, "tail": []}, "unknown"),
            ({"keep": 3, "tail": ["d", "e"]}, {"keep": 0, "tail": ["f"]}, "unknown"),
        ],
        ids=[
            "another shape",
            "a shape one names alone",
            "fewer kept than were sent",
            "all kept",
            "none kept",
        ],
    )
    def test_a_cause_is_what_its_request_sent_unlike_its_predecessors(
        self,
        first: dict[str, Any],
        second: dict[str, Any],
        cause: str,
        tmp_path: Path,
    ) -> None:
        lines = linked(
            [
                typed(0),
                request(1, "request-1", **first),
                sent(assistant(4, "msg_01", cache_write_5m=1_000), "request-1"),
                request(5, "request-2", **second),
                sent(assistant(9, "msg_02", cache_write_5m=1_000), "request-2"),
            ]
        )

        assert _read(tmp_path, lines).calls[1].miss_cause == cause

    @pytest.mark.parametrize(
        ("causes", "cause"),
        [
            ({"model"}, "model"),
            ({"ttl"}, "ttl"),
            ({"rewind"}, "rewind"),
            ({"version"}, "version"),
            ({"system"}, "system"),
            ({"history"}, "history"),
            ({"model", "ttl"}, "model"),
            ({"ttl", "rewind"}, "ttl"),
            ({"rewind", "version"}, "rewind"),
            ({"version", "system"}, "version"),
            ({"system", "history"}, "system"),
        ],
        ids=lambda given: "+".join(sorted(given)) if isinstance(given, set) else None,
    )
    def test_the_first_cause_that_holds_is_the_calls(
        self, causes: set[str], cause: str, tmp_path: Path
    ) -> None:
        """The third Call misses: it follows the second, which read what the
        first left, or with a rewind the first."""
        lines = linked(
            [
                typed(0),
                request(1, "request-1", shapeHash="a1", keep=0, tail=["a", "b", "c"]),
                sent(assistant(4, "msg_01", cache_write_5m=1_000), "request-1"),
                typed(6),
                request(7, "request-2", shapeHash="a1", keep=3, tail=["d"]),
                sent(assistant(8, "msg_02", cache_read=1_000), "request-2"),
                typed(10),
                request(
                    310 if "ttl" in causes else 11,
                    "request-3",
                    shapeHash="b2" if "system" in causes else "a1",
                    keep=1 if "history" in causes else 4,
                    tail=["e"],
                ),
                sent(
                    assistant(
                        312 if "ttl" in causes else 12,
                        "msg_03",
                        "claude-haiku-4-5" if "model" in causes else "claude-opus-4-5",
                        cache_write_5m=1_000,
                    ),
                    "request-3",
                ),
            ]
        )
        if "rewind" in causes:
            lines[6]["parentUuid"] = "line-2"
        if "version" in causes:
            lines[8]["version"] = "2.1.318"

        assert [call.miss_cause for call in _read(tmp_path, lines).calls] == [
            None,
            None,
            cause,
        ]

    def test_a_sub_agents_misses_are_read_as_a_main_threads(
        self, tmp_path: Path
    ) -> None:
        lines = _missed(cache_write_5m=1_000)[1:]
        named = filed(tmp_path, [user(0, "Count the threads."), *lines], AGENT)

        assert [
            call.miss_cause for call in read(named, SETTINGS).publication.calls
        ] == [
            None,
            "unknown",
        ]


class TestEvents:
    def test_an_api_error_sent_again_is_a_retry_with_its_status(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            [
                typed(0),
                assistant(4, "msg_01"),
                retried(5),
                retried(6, None, attempt=2),
                assistant(9, "msg_02"),
            ],
        )

        assert _events(publication) == [
            [("api_retry", True, 5, "529"), ("api_retry", True, 6, None)],
            [],
        ]

    def test_a_request_that_failed_for_good_is_an_api_error_and_no_call(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path, [typed(0), assistant(4, "msg_01"), erred(5, 429), erred(6, None)]
        )

        assert [call.message_id for call in publication.calls] == ["msg_01"]
        assert _events(publication) == [
            [("api_error", True, 5, "429"), ("api_error", True, 6, None)]
        ]

    def test_a_response_the_person_interrupted_is_an_interrupt_and_no_prompt(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path, [typed(0), assistant(4, "msg_01"), interruption(5)]
        )

        assert _events(publication) == [[("interrupt", False, 5, None)]]
        assert _sources(publication) == ["typed"]

    def test_a_tool_call_the_person_interrupted_is_its_own_and_no_event(
        self, tmp_path: Path
    ) -> None:
        """An Event is stored only where nothing else records the
        occurrence (DB 79.6)."""
        publication = _read(
            tmp_path,
            [
                typed(0),
                requesting(4),
                result(5, said=INTERRUPTED, error=True),
                user(
                    6, [{"type": "text", "text": "[Request interrupted by user] twice"}]
                ),
                user(7, "[Request interrupted by user]"),
            ],
        )

        assert _events(publication) == [[]]
        assert _tool_calls(publication)[0].interrupted

    def test_an_event_is_on_the_last_call_before_it_else_on_the_first(
        self, tmp_path: Path
    ) -> None:
        """Placed by the Calls' first lines, in the file's order."""
        publication = _read(
            tmp_path,
            [
                typed(0),
                retried(1),
                assistant(4, "msg_01", output=1),
                assistant(9, "msg_02"),
                assistant(10, "msg_01", output=3),
                interruption(11),
                erred(12),
            ],
        )

        assert _events(publication) == [
            [("api_retry", True, 1, "529")],
            [("interrupt", False, 11, None), ("api_error", True, 12, "529")],
        ]

    def test_a_sub_agents_events_are_read_as_a_main_threads(
        self, tmp_path: Path
    ) -> None:
        named = filed(
            tmp_path,
            [user(0, "Count the threads."), assistant(4, "msg_01"), retried(5)],
            AGENT,
        )

        assert _events(read(named, SETTINGS).publication) == [
            [("api_retry", True, 5, "529")]
        ]


def _parts(publication: PublicationSchema) -> list[list[tuple[str, str | None, int]]]:
    """Each Call's Context Parts: its kind, its name and its characters."""
    return [
        [(part.kind, part.name, part.characters) for part in call.context_parts]
        for call in publication.calls
    ]


class TestContextParts:
    def test_a_launchs_first_call_carries_its_system_prompt_tools_files_and_prompt(
        self, tmp_path: Path
    ) -> None:
        managed = "# Environment: cleo-loom-4b7d21\n\nWarp before weft."
        project = "# Looms\n\nThread the heddles."
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    instructions(
                        0.1,
                        loaded("Managed", managed),
                        loaded("Project", project, f"{DIRECTORY}/CLAUDE.md"),
                    ),
                    shaped(0.5, system=("You weave.", " Slowly."), tools=(LOOM,)),
                    request(1, shapeHash="shape-1"),
                    sent(assistant(4, "msg_01"), "request-1"),
                    typed(6, "Weft now."),
                    request(7, "request-2", shapeHash="shape-1"),
                    sent(assistant(9, "msg_02"), "request-2"),
                ]
            ),
        )

        assert _parts(publication) == [
            [
                ("system_prompt", None, len("You weave. Slowly.")),
                ("tool_schemas", None, SCHEMAS),
                ("instruction_file", MANAGED, len(managed)),
                ("instruction_file", f"{DIRECTORY}/CLAUDE.md", len(project)),
                ("prompt", None, len("Warp the loom.")),
            ],
            [],
        ]

    def test_each_prompt_received_before_the_first_call_is_a_part(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            linked([typed(0), typed(1, "And the weft."), assistant(4, "msg_01")]),
        )

        assert _parts(publication) == [
            [("prompt", None, len("Warp the loom.")), ("prompt", None, 13)]
        ]

    def test_a_snapshot_gives_them_where_no_line_of_a_shape_does(
        self, tmp_path: Path
    ) -> None:
        """Its marker is no text a request sends; a newer snapshot records
        no tools."""
        older = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    snapshot(0.2, "You weave.", SPLIT, " Slowly.", tools=[LOOM]),
                    assistant(4, "msg_01"),
                ]
            ),
        )
        newer = _read(
            tmp_path,
            linked([typed(0), snapshot(0.2, "You weave."), assistant(4, "msg_01")]),
        )

        assert _parts(older)[0][:2] == [
            ("system_prompt", None, len("You weave. Slowly.")),
            ("tool_schemas", None, SCHEMAS),
        ]
        assert _parts(newer)[0][:2] == [
            ("system_prompt", None, len("You weave.")),
            ("prompt", None, len("Warp the loom.")),
        ]

    def test_the_shape_its_request_sent_is_read_before_a_snapshot(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    snapshot(0.2, "You weave, and you weave well.", tools=[]),
                    shaped(0.5, tools=(LOOM,)),
                    request(1, shapeHash="shape-1"),
                    sent(assistant(4, "msg_01"), "request-1"),
                ]
            ),
        )

        assert _parts(publication)[0][:2] == [
            ("system_prompt", None, len("You weave.")),
            ("tool_schemas", None, SCHEMAS),
        ]

    @pytest.mark.parametrize(
        ("snapshotted", "parts"),
        [
            (True, [("system_prompt", None, len("You spin."))]),
            (False, []),
        ],
        ids=["a snapshot", "none"],
    )
    def test_a_shape_the_file_holds_no_line_of_leaves_what_a_snapshot_records(
        self,
        snapshotted: bool,
        parts: list[tuple[str, str | None, int]],
        tmp_path: Path,
    ) -> None:
        lines = [
            typed(0),
            request(1, shapeHash="shape-9"),
            sent(assistant(4, "msg_01"), "request-1"),
        ]
        if snapshotted:
            lines.insert(1, snapshot(0.2, "You spin."))

        publication = _read(tmp_path, linked(lines))

        assert _parts(publication) == [
            [*parts, ("prompt", None, len("Warp the loom."))]
        ]

    def test_a_shape_that_sends_neither_is_no_part(self, tmp_path: Path) -> None:
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    shaped(0.5, system=()),
                    request(1, shapeHash="shape-1"),
                    sent(assistant(4, "msg_01"), "request-1"),
                ]
            ),
        )

        assert _parts(publication) == [[("prompt", None, len("Warp the loom."))]]

    def test_a_later_launchs_first_call_carries_everything_again(
        self, tmp_path: Path
    ) -> None:
        """A resumed process names a shape an earlier one's lines record, and
        writes no snapshot."""
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    snapshot(0.2, "You weave."),
                    shaped(0.5, tools=(LOOM,)),
                    request(1, shapeHash="shape-1"),
                    sent(assistant(4, "msg_01"), "request-1"),
                    cost(),
                    typed(20, "Weft now."),
                    request(21, "request-2", shapeHash="shape-1"),
                    sent(assistant(24, "msg_02"), "request-2"),
                    typed(30, "And again."),
                    assistant(34, "msg_03"),
                ]
            ),
        )

        opened = [("system_prompt", None, 10), ("tool_schemas", None, SCHEMAS)]
        assert _parts(publication) == [
            [*opened, ("prompt", None, len("Warp the loom."))],
            [*opened, ("prompt", None, len("Weft now."))],
            [],
        ]

    def test_an_older_first_call_carries_its_prompt_alone(self, tmp_path: Path) -> None:
        """Before Claude Code 2.1.261 no line records the system prompt, the
        tools or the instruction files."""
        publication = _read(tmp_path, [typed(0), assistant(4, "msg_01")])

        assert _parts(publication) == [[("prompt", None, len("Warp the loom."))]]

    def test_a_sub_agents_first_call_carries_its_task_and_no_meta_line(
        self, tmp_path: Path
    ) -> None:
        lines = linked(
            [
                user(0, "Count the threads."),
                user(0.1, "Caveat: the loom's own commands ran below.")
                | {"isMeta": True},
                instructions(
                    0.2, loaded("Project", "# Looms", f"{DIRECTORY}/CLAUDE.md")
                ),
                shaped(0.5, tools=(LOOM,)) | {"agentId": AGENT},
                request(1, shapeHash="shape-1") | {"agentId": AGENT},
                sent(assistant(4, "msg_01"), "request-1"),
                user(5, "Count them again."),
                assistant(8, "msg_02"),
            ]
        )

        publication = read(filed(tmp_path, lines, AGENT), SETTINGS).publication

        assert _parts(publication) == [
            [
                ("system_prompt", None, 10),
                ("tool_schemas", None, SCHEMAS),
                ("instruction_file", f"{DIRECTORY}/CLAUDE.md", 7),
                ("prompt", None, len("Count the threads.")),
            ],
            [],
        ]


LOOMS = f"{DIRECTORY}/looms/CLAUDE.md"
"""An instruction file of a folder below the working directory."""


class TestInjectedParts:
    def test_a_later_call_carries_what_was_injected_before_its_first_line(
        self, tmp_path: Path
    ) -> None:
        """A skill's body, a reminder and an instruction file loaded under
        way, in the file's order; a later Prompt is none."""
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    requesting(4, "toolu_01", "Skill", {"skill": "loom:weave"}),
                    result(5, "toolu_01", "Launching skill: loom:weave"),
                    expanded(5.1),
                    attached(5.2, "date", "Today is a weaving day."),
                    nested(5.3, LOOMS, "# Looms\n\nWarp first."),
                    assistant(9, "msg_02"),
                    attached(9.5, "total_tokens_reminder", "Plenty left."),
                    typed(10, "Weft now."),
                    assistant(14, "msg_03"),
                ]
            ),
        )

        assert _parts(publication) == [
            [("prompt", None, len("Warp the loom."))],
            [
                ("skill_body", "loom:weave", len(BODY)),
                ("reminder", "date", len("Today is a weaving day.")),
                ("instruction_file", LOOMS, len("# Looms\n\nWarp first.")),
            ],
            [("reminder", "total_tokens_reminder", len("Plenty left."))],
        ]
        assert len(_sources(publication)) == 2

    def test_a_launchs_first_call_carries_the_attachments_shown_before_it(
        self, tmp_path: Path
    ) -> None:
        """After its instruction files and before its Prompts: the
        attachment that lists the files is no reminder."""
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    instructions(
                        0.1, loaded("Project", "# Looms", f"{DIRECTORY}/CLAUDE.md")
                    ),
                    attached(0.2, "skill_listing", "- loom:weave: Weave a row."),
                    attached(0.3, "date", "Today is a weaving day."),
                    assistant(4, "msg_01"),
                ]
            ),
        )

        assert _parts(publication) == [
            [
                ("instruction_file", f"{DIRECTORY}/CLAUDE.md", 7),
                ("reminder", "skill_listing", len("- loom:weave: Weave a row.")),
                ("reminder", "date", len("Today is a weaving day.")),
                ("prompt", None, len("Warp the loom.")),
            ]
        ]

    def test_a_reminder_is_as_long_as_all_the_text_it_was_shown(
        self, tmp_path: Path
    ) -> None:
        shown = attached(0.2, "file", "Called Read.") | {
            "rendered": [{"content": "Called Read."}, {"content": "Warp first."}]
        }

        publication = _read(tmp_path, linked([typed(0), shown, assistant(4)]))

        assert _parts(publication)[0][0] == ("reminder", "file", 23)

    @pytest.mark.parametrize(
        "line",
        [
            attached(5, "date"),
            attached(5, "deferred_tools_record", tools=["Weave"]),
            attached(5, "date", "Today is a weaving day.") | {"rendered": []},
            hook_failed(5, "guard.sh"),
            taken(5, "And the weft.") | {"rendered": [{"content": "And the weft."}]},
        ],
        ids=[
            "an older version's",
            "one never shown",
            "one shown nothing",
            "a hook's error",
            "a message taken mid-run",
        ],
    )
    def test_an_attachment_shown_nothing_or_a_message_is_no_part(
        self, line: Line, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            linked([typed(0), assistant(4, "msg_01"), line, assistant(9, "msg_02")]),
        )

        assert _parts(publication)[1] == []

    def test_each_skill_shown_again_is_a_body_of_its_own(self, tmp_path: Path) -> None:
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    assistant(4, "msg_01"),
                    boundary(5),
                    summary(4.7),
                    invoked(5.1, ("loom:weave", "Weave tight."), ("loom:dye", "Dye.")),
                    assistant(9, "msg_02"),
                ]
            ),
        )

        assert _parts(publication)[1] == [
            (
                "compact_summary",
                None,
                len("The loom so far: warped, not yet threaded."),
            ),
            ("skill_body", "loom:weave", len("Weave tight.")),
            ("skill_body", "loom:dye", len("Dye.")),
        ]

    @pytest.mark.parametrize(
        ("source", "skill"),
        [
            ("toolu_01", "loom:weave"),
            (None, None),
            ("toolu_99", None),
            ("toolu_02", None),
        ],
        ids=[
            "its Skill call's",
            "a typed command's",
            "a call of no line",
            "another tool's call",
        ],
    )
    def test_a_skills_body_is_named_by_the_skill_its_call_asked_for(
        self, source: str | None, skill: str | None, tmp_path: Path
    ) -> None:
        asked = requesting(4, "toolu_01", "Skill", {"skill": "loom:weave"})
        asked["message"]["content"].append(
            {"type": "tool_use", "id": "toolu_02", "name": "Bash", "input": {}}
        )
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    asked,
                    result(5, "toolu_01", "Launching skill: loom:weave"),
                    result(5, "toolu_02"),
                    expanded(5.1, source),
                    assistant(9, "msg_02"),
                ]
            ),
        )

        assert _parts(publication)[1] == [("skill_body", skill, len(BODY))]

    @pytest.mark.parametrize(
        "said",
        [
            "# Weave\n\nWeave tight.",
            "Skill /loom:weave is already loaded above; instructions unchanged.",
        ],
        ids=["a command's body", "a skill loaded before"],
    )
    def test_what_a_skill_call_expanded_is_its_body_whatever_it_opens_with(
        self, said: str, tmp_path: Path
    ) -> None:
        body = user(5.1, [support.words(said)]) | {
            "isMeta": True,
            "sourceToolUseID": "toolu_01",
        }
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    requesting(4, "toolu_01", "Skill", {"skill": "loom:weave"}),
                    result(5, "toolu_01", "Launching skill: loom:weave"),
                    body,
                    assistant(9, "msg_02"),
                ]
            ),
        )

        assert _parts(publication)[1] == [("skill_body", "loom:weave", len(said))]

    @pytest.mark.parametrize(
        "mode", ["task-notification", None], ids=["a task's notice", "a message"]
    )
    def test_a_message_a_sub_agent_takes_mid_run_is_a_reminder(
        self, mode: str | None, tmp_path: Path
    ) -> None:
        """A sub-agent's thread holds no Prompt to count it."""
        said = "And the weft."
        given = {} if mode is None else {"commandMode": mode}
        lines = linked(
            [
                user(0, "Count the threads."),
                assistant(4, "msg_01"),
                attached(5, "queued_command", said, prompt=said, **given),
                assistant(9, "msg_02"),
            ]
        )

        publication = read(filed(tmp_path, lines, AGENT), SETTINGS).publication

        assert _parts(publication)[1] == [("reminder", "queued_command", len(said))]

    def test_a_meta_line_that_is_no_skills_body_is_no_part(
        self, tmp_path: Path
    ) -> None:
        caveat = user(5, "Caveat: the loom's own commands ran below.") | {
            "isMeta": True
        }

        publication = _read(
            tmp_path,
            linked([typed(0), assistant(4, "msg_01"), caveat, assistant(9, "msg_02")]),
        )

        assert _parts(publication)[1] == []

    def test_a_compactions_summary_is_the_next_calls(self, tmp_path: Path) -> None:
        publication = _read(
            tmp_path,
            linked(
                [typed(0), assistant(4, "msg_01"), boundary(30), summary(29.7)]
                + [assistant(40, "msg_02")]
            ),
        )

        assert _parts(publication)[1] == [
            ("compact_summary", None, len("The loom so far: warped, not yet threaded."))
        ]

    def test_a_later_instructions_attachment_is_its_files(self, tmp_path: Path) -> None:
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    assistant(4, "msg_01"),
                    instructions(5, loaded("Project", "# Looms", LOOMS)),
                    assistant(9, "msg_02"),
                ]
            ),
        )

        assert _parts(publication)[1] == [("instruction_file", LOOMS, 7)]

    def test_what_was_injected_between_a_calls_lines_is_the_next_calls(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    assistant(4, "msg_01", output=1),
                    attached(4.5, "date", "Today is a weaving day."),
                    assistant(5, "msg_01", output=3),
                    assistant(9, "msg_02"),
                ]
            ),
        )

        assert _parts(publication) == [
            [("prompt", None, len("Warp the loom."))],
            [("reminder", "date", len("Today is a weaving day."))],
        ]

    def test_what_was_injected_before_a_launch_is_no_part_of_it(
        self, tmp_path: Path
    ) -> None:
        """A process that exits sends no request after its last Call."""
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    assistant(4, "msg_01"),
                    attached(5, "date", "Today is a weaving day."),
                    cost(),
                    typed(20, "Weft now."),
                    assistant(24, "msg_02"),
                ]
            ),
        )

        assert _parts(publication) == [
            [("prompt", None, len("Warp the loom."))],
            [("prompt", None, len("Weft now."))],
        ]

    def test_a_sub_agents_injected_parts_are_read_as_a_main_threads(
        self, tmp_path: Path
    ) -> None:
        lines = linked(
            [
                user(0, "Count the threads."),
                attached(0.2, "date", "Today is a weaving day."),
                requesting(4, "toolu_01", "Skill", {"skill": "loom:weave"}),
                result(5, "toolu_01", "Launching skill: loom:weave"),
                expanded(5.1),
                assistant(9, "msg_02"),
            ]
        )

        publication = read(filed(tmp_path, lines, AGENT), SETTINGS).publication

        assert _parts(publication) == [
            [
                ("reminder", "date", len("Today is a weaving day.")),
                ("prompt", None, len("Count the threads.")),
            ],
            [("skill_body", "loom:weave", len(BODY))],
        ]


class TestToolCalls:
    def test_a_tool_call_is_a_calls_request_with_the_result_that_names_its_id(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            [
                typed(0),
                assistant(4, "msg_01", output=1),
                requesting(4.5, "toolu_01", "Read", {"file_path": "warp.md"}),
                requesting(5, "toolu_02", "Bash", {"command": "ls looms"}),
                result(7, "toolu_02", "twill\nsatin", error=False),
                result(9, "toolu_01", "Sixty ends."),
                requesting(12, "toolu_03", "Grep", {"pattern": "weft"}, "msg_02"),
            ],
        )

        first, second = publication.calls
        assert [
            (asked.tool_use_id, asked.tool, asked.requested_at, asked.returned_at)
            for asked in first.tool_calls
        ] == [
            ("toolu_01", "Read", moment(4.5), moment(9)),
            ("toolu_02", "Bash", moment(5), moment(7)),
        ]
        assert [asked.tool_use_id for asked in second.tool_calls] == ["toolu_03"]
        assert first.completed_at == moment(5)

    def test_a_request_no_result_reached_has_no_fact_of_one(
        self, tmp_path: Path
    ) -> None:
        asked = _tool_call(tmp_path, requesting(4))

        assert asked.returned_at is None
        assert (asked.failed, asked.interrupted) == (False, False)
        assert asked.exit_code is None
        assert (asked.result_characters, asked.saved_characters) == (None, None)

    def test_a_request_and_a_result_written_twice_are_one_tool_call(
        self, tmp_path: Path
    ) -> None:
        asked = _tool_call(
            tmp_path,
            requesting(4),
            result(6, said="Twill."),
            requesting(60),
            result(66, said="Twill and satin."),
        )

        assert (asked.requested_at, asked.returned_at) == (moment(4), moment(6))
        assert asked.result_characters == 6

    def test_a_result_that_names_no_request_of_the_file_is_no_tool_calls(
        self, tmp_path: Path
    ) -> None:
        asked = _tool_call(
            tmp_path, result(2, "toolu_00"), requesting(4), result(6, "toolu_09")
        )

        assert (asked.tool_use_id, asked.returned_at) == ("toolu_01", None)

    def test_a_line_claude_code_wrote_itself_requests_no_tool(
        self, tmp_path: Path
    ) -> None:
        synthetic = requesting(5, "toolu_02", message_id="5c0e-a1")
        synthetic["message"]["model"] = "<synthetic>"

        asked = _tool_call(tmp_path, requesting(4), synthetic)

        assert asked.tool_use_id == "toolu_01"

    def test_a_sub_agents_tool_calls_are_read_as_a_main_threads(
        self, tmp_path: Path
    ) -> None:
        lines = [
            user(0, "Count the heddles."),
            requesting(3, given={"command": "wc -l heddles"}),
            result(5, said="Exit code 1\nwc: heddles", error=True),
        ]

        (call,) = read(filed(tmp_path, lines, AGENT), SETTINGS).publication.calls

        (asked,) = call.tool_calls
        assert (asked.tool, asked.first_argument) == ("Bash", "wc -l heddles")
        assert (asked.returned_at, asked.failed) == (moment(5), True)
        assert asked.exit_code == 1

    @pytest.mark.parametrize(
        ("tool", "server"),
        [
            ("mcp__loomhouse__list_patterns", "loomhouse"),
            ("mcp__plugin_dye_vat__mix", "plugin_dye_vat"),
            ("Bash", None),
            ("mcp_tools", None),
            ("mcp__loomhouse", None),
            ("Weave__mcp__twill", None),
        ],
    )
    def test_an_mcp_servers_tool_names_its_server(
        self, tool: str, server: str | None, tmp_path: Path
    ) -> None:
        asked = _tool_call(tmp_path, requesting(4, tool=tool, given={"query": "x"}))

        assert (asked.tool, asked.mcp_server) == (tool, server)

    @pytest.mark.parametrize(
        ("given", "argument"),
        [
            ({"command": "ls looms", "description": "List the looms"}, "ls looms"),
            (
                {"replace_all": False, "file_path": "warp.md", "old_string": "a"},
                "warp.md",
            ),
            ({"limit": 5, "ids": ["a", "b"], "query": "twill"}, "twill"),
            ({"command": "cd looms &&\n  ls\nwc -l *"}, "cd looms &&"),
            ({"command": "\n  \n  ls looms\n"}, "  ls looms"),
            ({"command": "ls looms\r\nwc"}, "ls looms"),
            ({"command": " \n", "description": "Nothing"}, None),
            ({"todos": [{"content": "Tie on"}], "merge": True}, None),
            ({}, None),
        ],
        ids=[
            "the first of its input",
            "the first that is text",
            "past a number and a list",
            "cut to a line",
            "its first line that is not blank",
            "a line a carriage return ends",
            "a blank text",
            "no text",
            "no input",
        ],
    )
    def test_its_argument_is_the_first_text_of_its_input_cut_to_a_line(
        self, given: dict[str, Any], argument: str | None, tmp_path: Path
    ) -> None:
        asked = _tool_call(tmp_path, requesting(4, tool="Loom", given=given))

        assert asked.first_argument == argument

    @pytest.mark.parametrize(
        ("given", "argument"),
        [
            (
                {
                    "description": "Count the heddles",
                    "prompt": "Count every heddle.",
                    "subagent_type": "Explore",
                },
                "Count the heddles",
            ),
            (
                {
                    "subagent_type": "Explore",
                    "description": "Count the heddles",
                    "prompt": "Count every heddle.",
                },
                "Count the heddles",
            ),
            (
                {
                    "model": "haiku",
                    "description": "Count the heddles",
                    "prompt": "Count every heddle.",
                },
                "Count the heddles",
            ),
            (
                {"description": "\n Count the heddles\nand the reeds"},
                " Count the heddles",
            ),
            ({"subagent_type": "Explore", "prompt": "Count every heddle."}, None),
        ],
        ids=[
            "its description first",
            "its type first",
            "a model first",
            "cut to a line",
            "no description",
        ],
    )
    def test_an_agent_calls_argument_is_its_description(
        self, given: dict[str, Any], argument: str | None, tmp_path: Path
    ) -> None:
        asked = _tool_call(tmp_path, requesting(4, tool="Agent", given=given))

        assert asked.first_argument == argument

    @pytest.mark.parametrize(
        ("error", "failed"), [(True, True), (False, False), (None, False)]
    )
    def test_it_failed_where_its_result_is_an_error(
        self, error: bool | None, failed: bool, tmp_path: Path
    ) -> None:
        asked = _tool_call(tmp_path, requesting(4), result(6, error=error))

        assert asked.failed is failed

    @pytest.mark.parametrize(
        ("tool", "said", "error", "exit_code"),
        [
            ("Bash", "Exit code 2\nls: no looms", True, 2),
            ("Bash", "Exit code 137", True, 137),
            ("Bash", "Exit code -1\nKilled", True, -1),
            ("Bash", "The command timed out.", True, None),
            ("Bash", "ls: no looms\nExit code 2", True, None),
            ("Bash", "Exit code 2 was the last run's.", True, None),
            ("Bash", "Exit code 2\nls: no looms", False, None),
            ("Bash", "twill", False, None),
            ("Loom", "Exit code 2\nThe shed jammed.", True, None),
        ],
        ids=[
            "an error that opens with it",
            "an error that is it alone",
            "a negative one",
            "an error that names none",
            "an error that names one further on",
            "an error that opens with the words and no line of them",
            "a result that is no error",
            "a command that exited with 0",
            "another tool's error",
        ],
    )
    def test_an_exit_code_is_the_one_a_commands_error_opens_with(
        self, tool: str, said: str, error: bool, exit_code: int | None, tmp_path: Path
    ) -> None:
        asked = _tool_call(
            tmp_path, requesting(4, tool=tool), result(6, said=said, error=error)
        )

        assert asked.exit_code == exit_code

    @pytest.mark.parametrize(
        ("said", "error", "record", "interrupted"),
        [
            ("twi", False, {"stdout": "twi", "interrupted": True}, True),
            ("twill", False, {"stdout": "twill", "interrupted": False}, False),
            (INTERRUPTED, True, f"Error: {INTERRUPTED}", True),
            (f"Exit code 145\n{INTERRUPTED}\nCommand aborted", True, None, True),
            ("Interrupted by user", True, "Interrupted by user", True),
            (f"{INTERRUPTED} was what the log said.", True, None, False),
            (f"The log:\n{INTERRUPTED}", True, None, False),
            (INTERRUPTED, False, {"stdout": INTERRUPTED, "interrupted": False}, False),
            ("Interrupted by user input on the loom.", True, None, False),
            ("Done.", None, "interrupted", False),
        ],
        ids=[
            "the command's record says so",
            "the command's record says not",
            "an error that is Claude Code's words for it",
            "an error that opens with them past the exit code",
            "an error that is the words of a file's tool",
            "an error that opens with the words and no line of them",
            "an error that quotes them further on",
            "an output that is the words, and no error",
            "an error that opens with other words",
            "a record that is a text",
        ],
    )
    def test_it_was_interrupted_where_its_record_or_its_error_says_so(
        self,
        said: str,
        error: bool | None,
        record: Any,
        interrupted: bool,
        tmp_path: Path,
    ) -> None:
        asked = _tool_call(
            tmp_path, requesting(4), result(6, said=said, error=error, record=record)
        )

        assert asked.interrupted is interrupted

    def test_its_results_size_is_the_characters_of_its_text(
        self, tmp_path: Path
    ) -> None:
        blocks = [
            {"type": "text", "text": "Schußfaden, "},
            {"type": "image", "source": {"type": "base64", "data": "aGVkZGxl"}},
            {"type": "tool_reference", "tool_name": "mcp__loomhouse__list_patterns"},
            {"type": "text", "text": "twill."},
        ]
        publication = _read(
            tmp_path,
            [
                typed(0),
                requesting(4, "toolu_01"),
                requesting(4, "toolu_02"),
                requesting(4, "toolu_03"),
                result(6, "toolu_01", "Schußfaden"),
                result(7, "toolu_02", blocks),
                result(8, "toolu_03", [blocks[2]]),
            ],
        )

        assert [asked.result_characters for asked in _tool_calls(publication)] == [
            10,
            18,
            0,
        ]


HOOK = "PreToolUse:Bash hook error: [guard.sh]: The loom is locked."
"""A result in Claude Code's words for a hook's block of a Bash call."""


def _denied(projects: Path, said: str, kind: str | None) -> PublishedToolCallSchema:
    """The one tool call of a file whose result is an error saying `said`,
    its line naming `kind` as its `toolDenialKind`."""
    returned = result(5, said=said, error=True)
    return _tool_call(
        projects, requesting(4), returned if kind is None else denied(returned, kind)
    )


def _runs(publication: PublicationSchema) -> list[list[tuple[str, int, bool, bool]]]:
    """Each Prompt's Hook Runs: the command, its duration, whether it
    failed and whether it prevented the end."""
    return [
        [
            (run.command, run.duration_ms, run.failed, run.prevented_end)
            for run in prompt.hook_runs
        ]
        for launch in publication.launches
        for prompt in launch.prompts
    ]


class TestDenials:
    def test_a_hooks_block_is_a_denial_by_a_hook_whatever_kind_its_line_names(
        self, tmp_path: Path
    ) -> None:
        for kind in ("permission-rule", "user-rejected", None):
            asked = _denied(tmp_path, HOOK, kind)

            assert (asked.denial_kind, asked.failed) == ("hook", True)

    def test_a_rule_and_the_person_deny_by_the_kind_the_line_names(
        self, tmp_path: Path
    ) -> None:
        said = "Permission to use Bash has been denied."

        assert [
            _denied(tmp_path, said, kind).denial_kind
            for kind in ("permission-rule", "user-rejected")
        ] == ["rule", "person"]

    def test_an_older_denial_names_no_kind(self, tmp_path: Path) -> None:
        """Before 2.1.201 the words do not say who denied the call."""
        said = "The user doesn't want to proceed with this tool use."

        assert _denied(tmp_path, said, None).denial_kind is None

    def test_a_call_the_person_interrupted_is_no_denial(self, tmp_path: Path) -> None:
        asked = _denied(tmp_path, "The session ended before the loom.", "interrupted")

        assert (asked.denial_kind, asked.interrupted) == (None, True)

    def test_a_result_that_is_no_error_is_no_denial(self, tmp_path: Path) -> None:
        asked = _tool_call(
            tmp_path,
            requesting(4),
            denied(result(5, said=HOOK, error=False), "permission-rule"),
        )

        assert (asked.denial_kind, asked.failed) == (None, False)

    def test_a_hooks_block_of_another_tool_is_not_the_calls(
        self, tmp_path: Path
    ) -> None:
        said = HOOK.replace("PreToolUse:Bash", "PreToolUse:Write")

        assert [
            _denied(tmp_path, said, kind).denial_kind
            for kind in ("permission-rule", None)
        ] == ["rule", None]

    def test_a_sub_agents_denials_are_read_as_a_main_threads(
        self, tmp_path: Path
    ) -> None:
        lines = [
            user(0, "Count the threads."),
            requesting(4),
            denied(result(5, said=HOOK, error=True), "permission-rule"),
        ]
        publication = read(filed(tmp_path, lines, AGENT), SETTINGS).publication

        assert [asked.denial_kind for asked in _tool_calls(publication)] == ["hook"]


class TestHookRuns:
    def test_a_stop_hooks_summary_is_a_run_of_each_command_on_the_latest_prompt(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    assistant(4, "msg_01"),
                    typed(10, "Beat the weft."),
                    assistant(14, "msg_02"),
                    hooked(15, "tidy.sh", "notes.sh"),
                ]
            ),
        )

        assert _runs(publication) == [
            [],
            [("tidy.sh", 10, False, False), ("notes.sh", 11, False, False)],
        ]

    def test_each_summary_adds_its_runs_to_its_prompts(self, tmp_path: Path) -> None:
        """A hook that kept the run from ending makes it go on."""
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    assistant(4, "msg_01"),
                    hooked(5, "tidy.sh", prevented=True),
                    assistant(8, "msg_02"),
                    hooked(9, "tidy.sh", run="hooks-2"),
                ]
            ),
        )

        assert _runs(publication) == [
            [("tidy.sh", 10, False, True), ("tidy.sh", 10, False, False)]
        ]

    def test_a_run_failed_where_an_error_at_the_stop_event_names_it(
        self, tmp_path: Path
    ) -> None:
        """The error names the summary's run and the command."""
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    hook_failed(1, "tidy.sh", event="SessionStart"),
                    assistant(4, "msg_01"),
                    hook_failed(5, "notes.sh"),
                    hook_failed(5, "tidy.sh", run="hooks-0"),
                    hooked(5, "tidy.sh", "notes.sh", errors=("The shuttle jammed.",)),
                ]
            ),
        )

        assert _runs(publication) == [
            [("tidy.sh", 10, False, False), ("notes.sh", 11, True, False)]
        ]

    def test_a_newer_summary_names_the_places_of_those_that_failed(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    assistant(4, "msg_01"),
                    hooked(
                        5,
                        "tidy.sh",
                        "notes.sh",
                        errors=("The shuttle jammed.",),
                        failedHookErrorIndexes=[0],
                    ),
                ]
            ),
        )

        assert [[run[2] for run in ran] for ran in _runs(publication)] == [
            [True, False]
        ]

    def test_one_hook_and_an_error_is_its_failure(self, tmp_path: Path) -> None:
        """Where a summary names several hooks, an error alone does not say
        whose it is."""
        failing = ("The shuttle jammed.",)
        lines = [
            typed(0),
            assistant(4, "msg_01"),
            hooked(5, "tidy.sh", errors=failing),
            typed(10, "Beat the weft."),
            assistant(14, "msg_02"),
            hooked(15, "tidy.sh", "notes.sh", run="hooks-2", errors=failing),
        ]

        assert [
            [run[2] for run in ran] for ran in _runs(_read(tmp_path, linked(lines)))
        ] == [
            [True],
            [False, False],
        ]

    def test_a_summary_lies_on_the_latest_prompt_wherever_it_was_received(
        self, tmp_path: Path
    ) -> None:
        """A Launch that received none."""
        publication = _read(
            tmp_path,
            linked(
                [
                    typed(0),
                    assistant(4, "msg_01"),
                    cost(),
                    assistant(30, "msg_02"),
                    hooked(31, "tidy.sh"),
                ]
            ),
        )

        assert [len(launch.prompts) for launch in publication.launches] == [1, 0]
        assert _runs(publication) == [[("tidy.sh", 10, False, False)]]

    def test_a_summary_before_any_prompt_lies_on_none(self, tmp_path: Path) -> None:
        publication = _read(
            tmp_path, linked([assistant(4, "msg_01"), hooked(5, "tidy.sh")])
        )

        assert [len(launch.prompts) for launch in publication.launches] == [0]

    def test_a_sub_agents_summary_lies_on_none(self, tmp_path: Path) -> None:
        lines = [
            user(0, "Count the threads."),
            assistant(4, "msg_01"),
            hooked(5, "tidy.sh"),
        ]

        assert read(filed(tmp_path, lines, AGENT), SETTINGS).publication.launches == []


class TestAnOutputSavedToDisk:
    """The two wordings are Claude Code's; the paths and outputs invented."""

    def test_its_full_size_is_the_saved_files_characters(self, tmp_path: Path) -> None:
        output = "Schußfaden und Kettfaden.\n" * 400
        path = saved(tmp_path, "b7q2x9k1m.txt", output.encode())

        asked = _tool_call(
            tmp_path,
            requesting(4),
            result(6, said=too_large(path, "10.6KB"), error=False),
        )

        assert asked.saved_characters == len(output) == 10_400
        assert asked.result_characters == len(too_large(path, "10.6KB"))

    def test_the_file_is_found_by_the_path_the_result_names(
        self, tmp_path: Path
    ) -> None:
        """Under another conversation's folder, on a home filed elsewhere,
        and by no name the tool call's id gives."""
        other = "9d3e7b52-1c4f-4a68-b0d9-5e2f8a1c6b37"
        name = "mcp-loomhouse-list_patterns-1794474000123.txt"
        path = saved(tmp_path, name, b"twill", other)
        saved(tmp_path, "toolu_01.txt", b"not this one")
        elsewhere = path.replace("/home/ubuntu/.claude", "/home/cleo/.config/claude")

        asked = _tool_call(
            tmp_path,
            requesting(4, tool="mcp__loomhouse__list_patterns"),
            result(6, said=over_the_tokens(elsewhere, "48,300 characters")),
        )

        assert asked.saved_characters == 5

    def test_a_saved_file_that_is_no_utf_8_counts_each_such_byte_a_character(
        self, tmp_path: Path
    ) -> None:
        path = saved(tmp_path, "b7q2x9k1m.txt", b"Schu\xdffaden\xff\n")

        asked = _tool_call(
            tmp_path, requesting(4), result(6, said=too_large(path, "30KB"))
        )

        assert asked.saved_characters == 12

    @pytest.mark.parametrize(
        ("stated", "characters"),
        [
            ("48,300 characters", 48_300),
            ("1,343,190 characters", 1_343_190),
            ("912 characters across 1 line", 912),
            ("61,004 characters across 2,210 lines", 61_004),
        ],
    )
    def test_a_file_that_is_gone_leaves_the_characters_the_result_states(
        self, stated: str, characters: int, tmp_path: Path
    ) -> None:
        path = saved(tmp_path, "mcp-loomhouse-list_patterns-17.txt", b"twill")
        (tmp_path / FOLDER / SESSION / "tool-results").rename(tmp_path / "gone")

        asked = _tool_call(
            tmp_path,
            requesting(4),
            result(6, said=over_the_tokens(path, stated), error=True),
        )

        assert asked.saved_characters == characters

    def test_a_file_that_is_gone_leaves_none_where_the_result_states_a_rounded_size(
        self, tmp_path: Path
    ) -> None:
        path = f"/home/ubuntu/.claude/projects/{FOLDER}/{SESSION}/tool-results/b7.txt"

        asked = _tool_call(
            tmp_path, requesting(4), result(6, said=too_large(path, "207.8KB"))
        )

        assert asked.saved_characters is None

    @pytest.mark.parametrize(
        "quoting",
        [
            "The log said:\n{wording}",
            " {wording}",
            "Exit code 1\n{wording}",
            "[{wording}]",
        ],
    )
    @pytest.mark.parametrize("wording", ["too large", "over the tokens"])
    def test_an_output_that_quotes_the_words_was_not_saved(
        self, wording: str, quoting: str, tmp_path: Path
    ) -> None:
        path = saved(tmp_path, "b7q2x9k1m.txt", b"twill")
        said = (
            too_large(path, "30KB")
            if wording == "too large"
            else over_the_tokens(path, "48,300 characters")
        )

        asked = _tool_call(
            tmp_path,
            requesting(4),
            result(6, said=quoting.format(wording=said), error=True),
        )

        assert asked.saved_characters is None

    @pytest.mark.parametrize(
        "path",
        [
            "/etc/passwd",
            "/tool-results/b7q2x9k1m.txt",
            f"/home/ubuntu/.claude/projects/{FOLDER}/{SESSION}/b7q2x9k1m.txt",
            f"/home/ubuntu/.claude/projects/{FOLDER}/../tool-results/b7q2x9k1m.txt",
            f"/home/ubuntu/.claude/projects/../{SESSION}/tool-results/b7q2x9k1m.txt",
            f"/home/ubuntu/.claude/projects/{FOLDER}/{SESSION}/tool-results/..",
        ],
    )
    def test_a_path_that_is_no_saved_outputs_place_is_not_read(
        self, path: str, tmp_path: Path
    ) -> None:
        saved(tmp_path, "b7q2x9k1m.txt", b"twill")
        (tmp_path / "tool-results").mkdir()
        (tmp_path / "tool-results" / "b7q2x9k1m.txt").write_bytes(b"not this one")

        large = _tool_call(
            tmp_path, requesting(4), result(6, said=too_large(path, "30KB"))
        )
        stated = _tool_call(
            tmp_path,
            requesting(4),
            result(6, said=over_the_tokens(path, "48,300 characters")),
        )

        assert large.saved_characters is None
        assert stated.saved_characters == 48_300


class TestAFileTheCollectorCannotRead:
    def test_a_line_that_is_no_json_is_named(self, tmp_path: Path) -> None:
        torn = support.content([typed(0)]) + b'{"type": "assist\n'

        with pytest.raises(UnreadableError, match="line 2 is not a line"):
            _read(tmp_path, torn)

    def test_a_line_that_is_no_object_is_named(self, tmp_path: Path) -> None:
        with pytest.raises(UnreadableError, match="line 1 .* the line is no object"):
            _read(tmp_path, b'["Warp the loom."]\n')

    def test_a_response_that_carries_no_usage_is_named(self, tmp_path: Path) -> None:
        bare = assistant(4, output=3)
        del bare["message"]["usage"]

        with pytest.raises(UnreadableError, match="line 2 .* KeyError: 'usage'"):
            _read(tmp_path, [typed(0), bare])

    def test_a_file_that_names_no_working_directory_is_refused(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(UnreadableError, match="no line names a working directory"):
            _read(tmp_path, [beside("bridge-session", bridgeSessionId="cse_41")])

    def test_a_fact_the_publications_shape_refuses_is_named(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(UnreadableError, match="its facts are no publication"):
            _read(tmp_path, [typed(0), assistant(4, output=2**31)])
