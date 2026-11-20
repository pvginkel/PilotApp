"""A transcript's file read into its reading: the scenario's files read as
the conversations their publications are the facts of, and each rule of the
reading on a file built for it."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pilot_collection.reading import (
    ReadCallSchema,
    ReadingSchema,
    ToolCallBlockSchema,
    UserBlockSchema,
)
from pilot_scenario import SCENARIO, Builder

from pilot_collector.home import modified_at, transcript
from pilot_collector.reader import UnreadableError, read
from pilot_collector.reading import reading
from tests import support
from tests.support import (
    AGENT,
    SESSION,
    Line,
    answering,
    assistant,
    beside,
    chained,
    content,
    cost,
    filed,
    image,
    moment,
    queue,
    requesting,
    result,
    synthetic,
    typed,
    user,
    words,
)

UNTIL = datetime(2026, 11, 12, 9, 30, 0, 250_000, tzinfo=UTC)

SETTINGS = support.settings()


def _reading(projects: Path, lines: list[Line], agent: str | None = None) -> Any:
    """The reading of a thread's file holding `lines`, as the JSON it is
    served as says it."""
    return reading(filed(projects, lines, agent)).model_dump(mode="json")


def _asked(call: ReadCallSchema) -> list[ToolCallBlockSchema]:
    return [block for block in call.sent if isinstance(block, ToolCallBlockSchema)]


def _scenario(home: Path) -> list[tuple[dict[str, Any], ReadingSchema]]:
    """Each thread of the scenario: the builder's publication of it, and
    the reading of the file the builder wrote for it."""
    builder = Builder(SCENARIO, UNTIL)
    builder.write(home)
    files = [file for file in builder.files() if file.path.endswith(".jsonl")]
    threads = []
    for file, publication in zip(files, builder.publications(), strict=True):
        named = transcript(home / "projects", home / file.path)
        assert named is not None
        threads.append((publication, reading(named)))
    return threads


class TestTheScenario:
    def test_each_files_calls_are_its_facts_calls(self, tmp_path: Path) -> None:
        """A Call by the id its fact carries, in the file's order, and each
        with the tool calls its fact has, their results on them."""
        threads = _scenario(tmp_path)

        assert sum(len(got.calls) for _, got in threads) > 10
        for publication, got in threads:
            assert (got.session_id, got.agent_id) == (
                publication["session_id"],
                publication.get("agent_id"),
            )
            assert [call.message_id for call in got.calls] == [
                call["message_id"] for call in publication["calls"]
            ]
            for call, fact in zip(got.calls, publication["calls"], strict=True):
                asked = _asked(call)
                facts = fact.get("tool_calls", [])
                assert [each.tool_use_id for each in asked] == [
                    each["tool_use_id"] for each in facts
                ]
                for each, held in zip(asked, facts, strict=True):
                    assert each.tool == held["tool"]
                    assert each.at == datetime.fromisoformat(held["requested_at"])
                    assert each.result is not None
                    assert each.result.at == datetime.fromisoformat(held["returned_at"])
                    assert each.result.error == held["failed"]
                    assert len(each.result.text) == held["result_characters"]

    def test_a_reading_is_the_reading_of_the_file_the_facts_were_read_off(
        self, tmp_path: Path
    ) -> None:
        builder = Builder(SCENARIO, UNTIL)
        builder.write(tmp_path)
        (first, *_) = [file for file in builder.files() if file.path.endswith(".jsonl")]
        named = transcript(tmp_path / "projects", tmp_path / first.path)
        assert named is not None

        publication = read(named, SETTINGS).publication
        got = reading(named)

        assert (got.file_size, got.file_modified_at) == (
            publication.file_size,
            publication.file_modified_at,
        )
        assert [call.message_id for call in got.calls] == [
            call.message_id for call in publication.calls
        ]

    def test_an_agent_call_names_the_transcript_it_started(
        self, tmp_path: Path
    ) -> None:
        threads = _scenario(tmp_path)
        started = {
            each.tool_use_id: (got.session_id, each.started)
            for _, got in threads
            for call in got.calls
            for each in _asked(call)
            if each.started is not None
        }
        spawned = {
            publication["spawned_by"]: (
                publication["session_id"],
                publication["agent_id"],
            )
            for publication, _ in threads
            if "agent_id" in publication
        }

        assert spawned
        assert started == spawned

    def test_a_failed_tools_result_is_on_its_call_as_an_error(
        self, tmp_path: Path
    ) -> None:
        results = [
            (each.result, held)
            for publication, got in _scenario(tmp_path)
            for call, fact in zip(got.calls, publication["calls"], strict=True)
            for each, held in zip(_asked(call), fact.get("tool_calls", []), strict=True)
        ]
        failed = [result for result, held in results if held.get("exit_code")]

        assert failed
        for said in failed:
            assert said is not None and said.error
            assert said.text.startswith("Exit code ")

    def test_a_line_says_who_wrote_it(self, tmp_path: Path) -> None:
        """Pilot's brief and a person's typing on a main thread, with a
        notice for each compaction's summary, and the parent agent's task on
        a sub-agent's."""
        threads = _scenario(tmp_path)
        sources = {
            prompt["source"]
            for publication, _ in threads
            for launch in publication.get("launches", [])
            for prompt in launch["prompts"]
        }
        assert sources == {"sdk", "typed"}

        for publication, got in threads:
            blocks = [block for call in got.calls for block in call.received]
            writers = [
                block.writer
                for block in blocks + got.after
                if isinstance(block, UserBlockSchema)
            ]
            if "agent_id" in publication:
                assert writers == ["parent"]
                continue
            assert [writer for writer in writers if writer != "notice"] == [
                {"sdk": "brief", "typed": "person"}[prompt["source"]]
                for launch in publication["launches"]
                for prompt in launch["prompts"]
            ]
            assert writers.count("notice") == len(publication.get("compactions", []))
        assert any("compactions" in publication for publication, _ in threads)


class TestACall:
    def test_it_holds_what_came_in_before_it_and_what_it_put_out(
        self, tmp_path: Path
    ) -> None:
        got = _reading(
            tmp_path,
            [
                typed(0, "Warp the loom."),
                answering(4, "msg_01", words("The warp is on.")),
                typed(9, "Now the weft."),
                answering(12, "msg_02", words("The weft runs.")),
                typed(20, "And rest."),
            ],
        )

        person = {"kind": "user", "writer": "person"}
        assert got["calls"] == [
            {
                "message_id": "msg_01",
                "received": [person | {"at": _at(0), "text": "Warp the loom."}],
                "sent": [{"kind": "text", "at": _at(4), "text": "The warp is on."}],
            },
            {
                "message_id": "msg_02",
                "received": [person | {"at": _at(9), "text": "Now the weft."}],
                "sent": [{"kind": "text", "at": _at(12), "text": "The weft runs."}],
            },
        ]
        assert got["after"] == [person | {"at": _at(20), "text": "And rest."}]

    def test_its_blocks_are_its_lines_blocks_in_the_files_order(
        self, tmp_path: Path
    ) -> None:
        """A response is a line a block, all under its id."""
        thinking = {"type": "thinking", "thinking": "", "signature": "c2lnbmVk"}
        thought = {"type": "thinking", "thinking": "Twill, then.", "signature": "c2k="}
        got = _reading(
            tmp_path,
            [
                typed(0),
                answering(3, "msg_01", thinking),
                answering(4, "msg_01", thought, words("Twill it is.")),
                requesting(5, "toolu_01", "Bash", {"command": "ls looms"}, "msg_01"),
            ],
        )

        (call,) = got["calls"]
        assert call["sent"] == [
            {"kind": "thinking", "at": _at(3), "text": ""},
            {"kind": "thinking", "at": _at(4), "text": "Twill, then."},
            {"kind": "text", "at": _at(4), "text": "Twill it is."},
            {
                "kind": "tool_call",
                "at": _at(5),
                "tool_use_id": "toolu_01",
                "tool": "Bash",
                "input": {"command": "ls looms"},
                "started": None,
                "result": None,
            },
        ]

    def test_a_line_of_an_earlier_call_goes_to_that_call(self, tmp_path: Path) -> None:
        got = _reading(
            tmp_path,
            [
                typed(0),
                answering(3, "msg_01", words("One.")),
                answering(4, "msg_02", words("Two.")),
                answering(5, "msg_01", words("One again.")),
            ],
        )

        assert [
            (call["message_id"], [block["text"] for block in call["sent"]])
            for call in got["calls"]
        ] == [("msg_01", ["One.", "One again."]), ("msg_02", ["Two."])]

    def test_a_line_claude_code_wrote_in_a_responses_place_is_no_call(
        self, tmp_path: Path
    ) -> None:
        got = _reading(
            tmp_path,
            [
                typed(0),
                synthetic(2, "API Error: the loom is busy"),
                answering(6, "msg_01", words("The warp is on.")),
                synthetic(9, "No response requested."),
            ],
        )

        (call,) = got["calls"]
        assert call["received"][1] == {
            "kind": "synthetic",
            "at": _at(2),
            "text": "API Error: the loom is busy",
        }
        assert got["after"] == [
            {"kind": "synthetic", "at": _at(9), "text": "No response requested."}
        ]

    def test_a_line_with_no_time_and_a_line_beside_the_chain_are_no_blocks(
        self, tmp_path: Path
    ) -> None:
        untimed = assistant(5, "msg_02")
        del untimed["timestamp"]
        got = _reading(
            tmp_path,
            [
                beside("permission-mode", permissionMode="default"),
                queue("enqueue", 0, "Warp the loom."),
                queue("dequeue", 0),
                typed(0),
                chained("progress", 2, data={"type": "hook_progress"}),
                answering(4, "msg_01", words("The warp is on.")),
                untimed,
                beside("last-prompt", lastPrompt="Warp the loom."),
                cost(),
            ],
        )

        (call,) = got["calls"]
        assert [block["kind"] for block in call["received"]] == ["user"]
        assert got["after"] == []


class TestWhatClaudeCodeAdded:
    @pytest.mark.parametrize(
        ("holds", "text"),
        [
            ({"text": "12,000 tokens are left."}, "12,000 tokens are left."),
            ({"content": "Dye, then dry.", "itemCount": 2}, "Dye, then dry."),
            ({"prompt": "And the weft?", "commandMode": "prompt"}, "And the weft?"),
            ({"newDate": "2026-11-13"}, '{"newDate": "2026-11-13"}'),
            (
                {"content": {"lines": 3}, "path": "é"},
                '{"content": {"lines": 3}, "path": "é"}',
            ),
            ({}, "{}"),
        ],
    )
    def test_an_attachment_is_a_block_with_its_words_or_what_it_holds(
        self, tmp_path: Path, holds: dict[str, Any], text: str
    ) -> None:
        attached = chained("attachment", 2, attachment={"type": "a_reminder"} | holds)
        got = _reading(tmp_path, [typed(0), attached, answering(4, "msg_01")])

        (call,) = got["calls"]
        assert call["received"][1] == {
            "kind": "attachment",
            "at": _at(2),
            "type": "a_reminder",
            "text": text,
        }

    def test_an_image_an_attachment_holds_is_said_with_its_size_and_not_its_bytes(
        self, tmp_path: Path
    ) -> None:
        """A prompt that waited in the queue with an image a person pasted."""
        prompt = [image(1_000), words("Is this twill?")]
        queued = {"type": "queued_command", "prompt": prompt, "commandMode": "prompt"}
        got = _reading(tmp_path, [chained("attachment", 2, attachment=queued)])

        (attached,) = got["after"]
        assert json.loads(attached["text"]) == {
            "prompt": [
                {"type": "image", "media_type": "image/png", "size": 1_000},
                {"type": "text", "text": "Is this twill?"},
            ],
            "commandMode": "prompt",
        }

    def test_an_image_file_an_attachment_holds_is_said_with_its_size_and_not_its_bytes(
        self, tmp_path: Path
    ) -> None:
        """A file a person named with `@`, held as the Read tool records an
        image it read."""
        data = image(3_000)["source"]["data"]
        read = {"base64": data, "type": "image/png", "originalSize": 4_100}
        named = {
            "type": "file",
            "filename": "/work/Loom/swatch.png",
            "content": {"type": "image", "file": read},
        }
        got = _reading(tmp_path, [chained("attachment", 2, attachment=named)])

        (attached,) = got["after"]
        assert json.loads(attached["text"]) == {
            "filename": "/work/Loom/swatch.png",
            "content": {"type": "image", "media_type": "image/png", "size": 3_000},
        }

    def test_the_instruction_files_are_an_attachment_on_a_sub_agents_thread_too(
        self, tmp_path: Path
    ) -> None:
        loaded = support.loaded("Managed", "# Environment: cleo-loom-7a41d9\n")
        got = _reading(
            tmp_path, [user(0, "Dye it."), support.instructions(0, loaded)], AGENT
        )

        _, attached = got["after"]
        assert (attached["kind"], attached["type"]) == ("attachment", "instructions")
        assert "# Environment: cleo-loom-7a41d9" in attached["text"]

    @pytest.mark.parametrize(
        ("fields", "subtype", "text"),
        [
            (
                {"subtype": "local_command", "content": "<x>ok</x>"},
                "local_command",
                "<x>ok</x>",
            ),
            ({"subtype": "turn_duration", "durationMs": 4_200}, "turn_duration", None),
            ({"subtype": "api_error", "content": {"status": 529}}, "api_error", None),
            ({"content": "A word."}, None, "A word."),
        ],
    )
    def test_a_system_line_is_a_block_with_its_subtype_and_its_words(
        self,
        tmp_path: Path,
        fields: dict[str, Any],
        subtype: str | None,
        text: str | None,
    ) -> None:
        got = _reading(tmp_path, [typed(0), chained("system", 7, **fields)])

        assert got["after"][1] == {
            "kind": "system",
            "at": _at(7),
            "subtype": subtype,
            "text": text,
        }


class TestAToolsResult:
    def test_it_sits_on_the_call_it_answers(self, tmp_path: Path) -> None:
        got = _reading(
            tmp_path,
            [
                typed(0),
                requesting(3, "toolu_01", message_id="msg_01"),
                requesting(3, "toolu_02", message_id="msg_01"),
                result(5, "toolu_02", "satin\ntwill", error=False),
                result(6, "toolu_01", "Exit code 2\nno such loom", error=True),
                answering(8, "msg_02", words("One failed.")),
            ],
        )

        first, second = got["calls"][0]["sent"]
        assert first["result"] == {
            "at": _at(6),
            "error": True,
            "text": "Exit code 2\nno such loom",
            "images": [],
        }
        assert second["result"] == {
            "at": _at(5),
            "error": False,
            "text": "satin\ntwill",
            "images": [],
        }
        assert got["calls"][1]["received"] == []

    def test_its_text_is_its_text_blocks_together(self, tmp_path: Path) -> None:
        said = [words("satin "), {"type": "tool_reference", "tool_name": "Weave"}]
        got = _reading(
            tmp_path,
            [typed(0), requesting(3), result(5, said=[*said, words("twill")])],
        )

        (asked,) = got["calls"][0]["sent"]
        assert asked["result"]["text"] == "satin twill"

    def test_one_that_names_no_request_of_the_file_is_a_block_where_it_stands(
        self, tmp_path: Path
    ) -> None:
        got = _reading(
            tmp_path,
            [
                typed(0),
                result(2, "toolu_gone", "From before.", error=True),
                requesting(3, "toolu_01"),
            ],
        )

        (call,) = got["calls"]
        assert call["received"][1] == {
            "kind": "tool_result",
            "at": _at(2),
            "tool_use_id": "toolu_gone",
            "error": True,
            "text": "From before.",
            "images": [],
        }
        assert call["sent"][0]["result"] is None

    def test_a_second_one_for_a_request_is_a_block_where_it_stands(
        self, tmp_path: Path
    ) -> None:
        got = _reading(
            tmp_path,
            [
                typed(0),
                requesting(3, "toolu_01"),
                result(5, "toolu_01", "Done."),
                result(7, "toolu_01", "Done again."),
            ],
        )

        (asked,) = got["calls"][0]["sent"]
        assert asked["result"]["text"] == "Done."
        (again,) = got["after"]
        assert (again["kind"], again["text"]) == ("tool_result", "Done again.")

    def test_a_call_names_the_sub_agent_its_tools_record_names(
        self, tmp_path: Path
    ) -> None:
        record = {"status": "async_launched", "agentId": AGENT, "prompt": "Dye it."}
        got = _reading(
            tmp_path,
            [
                typed(0),
                requesting(3, "toolu_01", "Agent", {"prompt": "Dye it."}),
                requesting(3, "toolu_02", "Bash"),
                result(4, "toolu_01", [words("Started.")], record=record),
                result(5, "toolu_02", "Done.", record={"stdout": "Done."}),
                result(6, "toolu_02", "Late.", record="Error: late"),
            ],
        )

        agent, bash = got["calls"][0]["sent"]
        assert (agent["started"], bash["started"]) == (AGENT, None)


class TestAnImage:
    def test_one_in_a_result_is_said_with_its_size_and_not_its_bytes(
        self, tmp_path: Path
    ) -> None:
        said = [words("A swatch."), image(1_000), image(4_001, "image/jpeg")]
        lines = [typed(0), requesting(3, tool="Read"), result(5, said=said)]

        got = _reading(tmp_path, lines)

        (asked,) = got["calls"][0]["sent"]
        assert asked["result"]["text"] == "A swatch."
        assert asked["result"]["images"] == [
            {"media_type": "image/png", "size": 1_000},
            {"media_type": "image/jpeg", "size": 4_001},
        ]
        served = reading(filed(tmp_path, lines)).model_dump_json()
        assert image(1_000)["source"]["data"][:64] not in served

    @pytest.mark.parametrize("size", [0, 1, 2, 3, 4, 5, 6, 1_000])
    def test_its_size_is_the_bytes_its_text_stands_for(
        self, tmp_path: Path, size: int
    ) -> None:
        got = _reading(tmp_path, [typed(0, [words("Look."), image(size)])])

        assert got["after"][1]["size"] == size

    def test_one_in_a_prompt_is_a_block_after_the_prompts_own(
        self, tmp_path: Path
    ) -> None:
        got = _reading(
            tmp_path,
            [typed(0, [image(300), words("Is this "), words("twill?"), image(7)])],
        )

        assert got["after"] == [
            {
                "kind": "user",
                "at": _at(0),
                "writer": "person",
                "text": "Is this twill?",
            },
            {"kind": "image", "at": _at(0), "media_type": "image/png", "size": 300},
            {"kind": "image", "at": _at(0), "media_type": "image/png", "size": 7},
        ]


INTERRUPTED = [{"type": "text", "text": "[Request interrupted by user]"}]


class TestWhoWroteALine:
    @pytest.mark.parametrize(
        ("fields", "writer"),
        [
            ({"promptSource": "typed"}, "person"),
            ({"promptSource": "queued"}, "person"),
            ({"promptSource": "suggestion_accepted"}, "person"),
            ({"promptSource": "sdk"}, "brief"),
            ({"promptSource": "system"}, "notice"),
            ({"promptSource": "sdk", "origin": {"kind": "task-notification"}}, "brief"),
            ({"turnOrigin": "human"}, "person"),
            ({"origin": {"kind": "human"}}, "person"),
            ({"turnOrigin": "sdk"}, "brief"),
            ({"origin": {"kind": "task-notification"}}, "notice"),
            ({"origin": {"kind": "scheduled"}}, "notice"),
            ({"isMeta": True}, "notice"),
            ({"isMeta": True, "origin": {"kind": "human"}}, "notice"),
            ({"isCompactSummary": True}, "notice"),
            ({"permissionMode": "default", "entrypoint": "cli"}, "person"),
            ({"permissionMode": "bypassPermissions", "entrypoint": "sdk-cli"}, "brief"),
            ({"permissionMode": "default"}, None),
            ({}, None),
        ],
    )
    def test_a_main_threads_by_its_source(
        self, tmp_path: Path, fields: dict[str, Any], writer: str | None
    ) -> None:
        got = _reading(tmp_path, [user(0, "Warp the loom.", **fields)])

        (block,) = got["after"]
        assert block["writer"] == writer

    @pytest.mark.parametrize(
        ("fields", "writer"),
        [
            ({}, "parent"),
            ({"isMeta": True, "origin": {"kind": "coordinator"}}, "parent"),
            ({"isMeta": True, "origin": {"kind": "peer"}}, "notice"),
            ({"isMeta": True}, "notice"),
            ({"isCompactSummary": True}, "notice"),
        ],
    )
    def test_a_sub_agents_is_its_parents_unless_claude_code_wrote_it(
        self, tmp_path: Path, fields: dict[str, Any], writer: str
    ) -> None:
        got = _reading(tmp_path, [user(0, "Dye the wool.", **fields)], AGENT)

        (block,) = got["after"]
        assert block["writer"] == writer

    @pytest.mark.parametrize("agent", [None, AGENT])
    def test_an_interruption_is_a_notice(
        self, tmp_path: Path, agent: str | None
    ) -> None:
        got = _reading(tmp_path, [user(0, INTERRUPTED)], agent)

        (block,) = got["after"]
        assert (block["writer"], block["text"]) == (
            "notice",
            "[Request interrupted by user]",
        )

    def test_words_beside_a_result_are_a_block_of_their_own(
        self, tmp_path: Path
    ) -> None:
        answered = result(5, "toolu_01", "Stopped.", error=True)
        answered["message"]["content"].append(
            words("[Request interrupted by user for tool use]")
        )
        got = _reading(tmp_path, [typed(0), requesting(3, "toolu_01"), answered])

        assert got["calls"][0]["sent"][0]["result"]["text"] == "Stopped."
        assert got["after"] == [
            {
                "kind": "user",
                "at": _at(5),
                "writer": "notice",
                "text": "[Request interrupted by user for tool use]",
            }
        ]


class TestTheFile:
    def test_the_reading_names_the_thread_and_the_files_size_and_time(
        self, tmp_path: Path
    ) -> None:
        named = filed(tmp_path, [typed(0)], AGENT)

        got = reading(named)

        status = named.path.stat()
        assert (got.session_id, got.agent_id) == (SESSION, AGENT)
        assert (got.file_size, got.file_modified_at) == (
            status.st_size,
            modified_at(status),
        )

    def test_a_line_still_being_written_is_not_read(self, tmp_path: Path) -> None:
        lines = [typed(0), answering(4, "msg_01", words("The warp is on."))]
        whole = content([*lines, answering(9, "msg_02", words("The weft runs."))])
        named = filed(tmp_path, whole[:-40])

        got = reading(named)

        assert [call.message_id for call in got.calls] == ["msg_01"]
        assert got.file_size == len(whole) - 40

    def test_a_line_that_is_none_the_collector_reads_is_named(
        self, tmp_path: Path
    ) -> None:
        named = filed(tmp_path, [typed(0), chained("assistant", 3)])

        with pytest.raises(UnreadableError, match="line 2 is not a line"):
            reading(named)


def _at(seconds: float) -> str:
    """The time `seconds` after the file's start, as a reading's JSON says
    one."""
    return moment(seconds).isoformat().replace("+00:00", "Z")
