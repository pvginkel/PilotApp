"""A transcript's file read into its whole publication: the scenario's
files read as the builder's publications, and each rule of the reading on a
file built for it."""

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pilot_collection.publication import PublicationSchema
from pilot_scenario import COLLECTOR, SCENARIO, Builder, Scenario
from pilot_scenario.script import Call, Launch, Prompt, Session, Tokens

from pilot_collector import VERSION
from pilot_collector.home import transcript
from pilot_collector.reader import UnreadableError, read
from pilot_collector.settings import Settings
from tests import support
from tests.support import (
    AGENT,
    DIRECTORY,
    SESSION,
    Line,
    assistant,
    beside,
    chained,
    cost,
    filed,
    instructions,
    loaded,
    moment,
    queue,
    result,
    typed,
    user,
)

UNTIL = datetime(2026, 11, 12, 9, 30, 0, 250_000, tzinfo=UTC)

SETTINGS = Settings()

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
PROMPT = ("received_at", "source", "characters")
CALL = ("message_id", "prompt", "completed_at", "model", "tokens")


def _resumed() -> Scenario:
    """A thread two processes wrote, in a directory under no checkout,
    hosted by no environment: the second took a queued prompt and went back
    to the first's Call."""
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
                    Launch(versions=(("claude-code", "2.1.317"),), prompts=(first,)),
                    Launch(versions=(("claude-code", "2.1.318"),), prompts=(second,)),
                ),
            ),
        ),
    )


def _cut(publication: dict[str, Any]) -> dict[str, Any]:
    """A publication of the builder's cut to the facts the reader reads."""
    cut = {name: publication[name] for name in THREAD if name in publication}
    if "launches" in publication:
        cut["launches"] = [
            {
                "started_at": launch["started_at"],
                "components": [
                    used
                    for used in launch["components"]
                    if used["component"] == "claude-code"
                ],
                "prompts": [
                    {name: prompt[name] for name in PROMPT}
                    for prompt in launch["prompts"]
                ],
            }
            for launch in publication["launches"]
        ]
    cut["calls"] = [
        {name: call[name] for name in CALL if name in call}
        for call in publication["calls"]
    ]
    return cut


def _read(projects: Path, lines: list[Line] | bytes) -> PublicationSchema:
    """The publication of a main thread's file holding `lines`."""
    return read(filed(projects, lines), SETTINGS)


def _sources(publication: PublicationSchema) -> list[str]:
    return [
        prompt.source for launch in publication.launches for prompt in launch.prompts
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
            assert read(named, SETTINGS).model_dump() == expected.model_dump()

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
        assert len(resumed[0]["launches"]) == 2
        assert "environment" not in resumed[0] and "repository" not in resumed[0]

    def test_a_reading_is_a_call_pilot_takes_by_its_shape(self, tmp_path: Path) -> None:
        builder = Builder(SCENARIO, UNTIL)
        builder.write(tmp_path)
        named = transcript(tmp_path / "projects", tmp_path / builder.files()[0].path)
        assert named is not None

        sent = read(named, SETTINGS).model_dump_json(exclude_none=True)

        assert PublicationSchema.model_validate_json(sent) == read(named, SETTINGS)


class TestTheCollectionRecord:
    def test_the_ids_are_its_places_and_the_version_the_collectors(
        self, tmp_path: Path
    ) -> None:
        lines = [typed(0), assistant(4, output=3)]

        main = read(filed(tmp_path, lines), SETTINGS)
        sub = read(filed(tmp_path, lines, AGENT), SETTINGS)

        assert (main.session_id, main.agent_id) == (SESSION, None)
        assert (sub.session_id, sub.agent_id) == (SESSION, AGENT)
        assert main.collector.version == VERSION == COLLECTOR

    def test_the_size_is_the_files_bytes_and_the_time_its_own_to_the_microsecond(
        self, tmp_path: Path
    ) -> None:
        named = filed(tmp_path, [typed(0, "Schußfaden"), assistant(4, output=3)])
        written = 1_794_474_000_123_456_789
        os.utime(named.path, ns=(written, written))

        publication = read(named, SETTINGS)

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
        settings = Settings(COLLECTOR_CHECKOUT_ROOTS=["/srv/checkouts", "/srv/more"])
        elsewhere = filed(tmp_path, [typed(0) | {"cwd": "/srv/more/Shuttle/src"}])

        assert read(elsewhere, settings).repository == "Shuttle"
        assert read(filed(tmp_path, [typed(0)]), settings).repository is None

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
        settings = Settings(COLLECTOR_ENVIRONMENT_PATTERN=re.compile(r"# Host: (\S+)"))
        hosted = filed(
            tmp_path,
            [typed(0), instructions(0, loaded("Managed", "# Host: loom-9\n"))],
        )

        assert read(hosted, settings).environment == "loom-9"
        assert read(hosted, SETTINGS).environment is None

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

        assert read(filed(tmp_path, lines, AGENT), SETTINGS).environment is None
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

    def test_a_process_that_follows_a_killed_one_joins_its_launch(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            [
                typed(1),
                assistant(4, "msg_01", output=3),
                beside("permission-mode", permissionMode="default"),
                typed(600) | {"version": "2.1.318"},
                assistant(604, "msg_02", output=3) | {"version": "2.1.318"},
            ],
        )

        (launch,) = publication.launches
        assert launch.started_at == moment(1)
        assert len(launch.prompts) == 2

    def test_a_launch_ran_the_version_its_lines_name_first(
        self, tmp_path: Path
    ) -> None:
        publication = _read(
            tmp_path,
            [
                queue("enqueue", 0, "Warp the loom."),
                typed(1) | {"version": "2.1.317"},
                assistant(4, "msg_01", output=3) | {"version": "2.1.318"},
                cost(),
                typed(60) | {"version": "2.1.320"},
            ],
        )

        assert [
            [(used.component, used.version) for used in launch.components]
            for launch in publication.launches
        ] == [[("claude-code", "2.1.317")], [("claude-code", "2.1.320")]]
        assert publication.launches[0].started_at == moment(0)

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

    def test_a_file_with_no_timed_line_has_no_launch(self, tmp_path: Path) -> None:
        publication = _read(
            tmp_path, [beside("ai-title", aiTitle="Looms", cwd=DIRECTORY), cost()]
        )

        assert publication.launches == []

    def test_a_sub_agents_thread_has_no_launch(self, tmp_path: Path) -> None:
        lines = [typed(0), assistant(4, output=3), cost(), typed(60)]

        publication = read(filed(tmp_path, lines, AGENT), SETTINGS)

        assert publication.launches == []
        assert [call.prompt for call in publication.calls] == [None]


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
        ],
    )
    def test_an_older_fields_word_is_read_in_the_newer_where_it_means_the_same(
        self, fields: dict[str, Any], source: str, tmp_path: Path
    ) -> None:
        publication = _read(tmp_path, [user(0, "Warp the loom.", **fields)])

        assert _sources(publication) == [source]

    @pytest.mark.parametrize(
        "line",
        [
            user(5, "Warp the loom."),
            user(5, "Warp the loom.", permissionMode="default"),
            user(5, [{"type": "text", "text": "[Request interrupted by user]"}]),
            user(5, "The skill's words.", isMeta=True, origin={"kind": "human"}),
            user(5, "What came before.", isCompactSummary=True),
            result(5),
            chained(
                "attachment",
                5,
                attachment={
                    "type": "queued_command",
                    "prompt": "Beat.",
                    "commandMode": "prompt",
                },
            ),
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
            "no word, an older prompt",
            "an interruption",
            "a skill's words",
            "a compaction's summary",
            "a tool's result",
            "a message taken in the middle of a run",
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

        (call,) = read(filed(tmp_path, lines, AGENT), SETTINGS).calls

        assert (call.message_id, call.completed_at) == ("msg_07", moment(4))
        assert call.tokens == {"input": 5, "output": 22}


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
