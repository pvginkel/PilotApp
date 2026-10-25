"""A Session's current line, as the session start sets it and the relay
rebuilds it (design 2 §9.5, Q5; V15)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.current_line import (
    CurrentLine,
    after_line,
    after_partial,
    at_send,
    while_starting,
)

AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
LATER = AT + timedelta(seconds=5)

READ = {"tool": "Read", "input": {"file_path": "/work/Example/plan.json"}}
TASK = {
    "tool": "Task",
    "input": {"subagent_type": "Explore", "description": "Find the badge"},
}


def _call(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "tool_use",
        "id": "toolu_example",
        "name": step["tool"],
        "input": step["input"],
    }


def _assistant(*blocks: dict[str, Any], parent: str | None = None) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": list(blocks)},
        "parent_tool_use_id": parent,
    }


def _tool_result(parent: str | None = None) -> dict[str, Any]:
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "toolu_example"}],
        },
        "parent_tool_use_id": parent,
    }


def _block_start(kind: str, **block: Any) -> dict[str, Any]:
    return {
        "type": "stream_event",
        "event": {
            "type": "content_block_start",
            "content_block": {"type": kind, **block},
        },
        "parent_tool_use_id": None,
    }


def _call_start(tool: str) -> dict[str, Any]:
    """A tool call's block start, as `claude` streams it: its `name`, and its
    input still to stream in."""
    return _block_start("tool_use", id="toolu_example", name=tool, input={})


TEXT_DELTA = {
    "type": "stream_event",
    "event": {
        "type": "content_block_delta",
        "delta": {"type": "text_delta", "text": "The badge"},
    },
    "parent_tool_use_id": None,
}

WORKING: CurrentLine = {"state": "working", "since": AT.isoformat(), "step": READ}


class TestWhileStarting:
    def test_a_start_records_words_are_the_line_from_its_time(self) -> None:
        assert while_starting("Starting Example-1…", AT) == {
            "state": "starting",
            "since": AT.isoformat(),
            "text": "Starting Example-1…",
        }


class TestAtSend:
    def test_a_sent_turn_is_thinking(self) -> None:
        assert at_send(None, AT) == {"state": "thinking", "since": AT.isoformat()}

    def test_the_session_starts_line_stands_until_the_first_line(self) -> None:
        starting = {"state": "starting", "since": AT.isoformat(), "text": "Creating…"}

        assert at_send(starting, LATER) == starting
        assert after_line(starting, {"type": "system", "subtype": "init"}, LATER) == {
            "state": "thinking",
            "since": LATER.isoformat(),
        }


class TestAfterLine:
    def test_the_turns_first_line_is_thinking(self) -> None:
        line = after_line(None, {"type": "system", "subtype": "init"}, AT)

        assert line == {"state": "thinking", "since": AT.isoformat()}

    def test_the_streams_first_line_ends_starting_and_its_words(self) -> None:
        starting = {"state": "starting", "since": AT.isoformat(), "text": "Creating…"}

        line = after_line(starting, {"type": "rate_limit_event"}, LATER)

        assert line == {"state": "thinking", "since": LATER.isoformat()}

    def test_a_tool_call_is_working_with_its_step(self) -> None:
        line = after_line(None, _assistant(_call(READ)), AT)

        assert line == WORKING

    def test_a_sub_agents_call_is_waiting_with_the_agent(self) -> None:
        line = after_line(WORKING, _assistant(_call(TASK)), LATER)

        assert line == {
            "state": "waiting",
            "since": LATER.isoformat(),
            "step": TASK,
            "agent": {"type": "Explore", "description": "Find the badge"},
        }

    def test_the_last_call_of_a_line_is_the_step(self) -> None:
        line = after_line(
            None, _assistant({"type": "text"}, _call(TASK), _call(READ)), AT
        )

        assert line == WORKING

    def test_a_sub_agents_lines_imply_nothing_of_the_main_thread(self) -> None:
        waiting = after_line(None, _assistant(_call(TASK)), AT)

        for sub_line in (
            _assistant(_call(READ), parent="toolu_example"),
            _tool_result(parent="toolu_example"),
            _assistant({"type": "text"}, parent="toolu_example"),
        ):
            assert after_line(waiting, sub_line, LATER) == waiting

    def test_a_tool_result_is_thinking_and_keeps_the_step(self) -> None:
        waiting = after_line(None, _assistant(_call(TASK)), AT)

        line = after_line(waiting, _tool_result(), LATER)

        assert line == {"state": "thinking", "since": LATER.isoformat(), "step": TASK}

    def test_an_assistant_line_without_a_call_is_thinking(self) -> None:
        writing = {"state": "writing", "since": AT.isoformat(), "step": READ}

        line = after_line(writing, _assistant({"type": "text", "text": "Done."}), LATER)

        assert line == {"state": "thinking", "since": LATER.isoformat(), "step": READ}

    def test_a_line_that_implies_nothing_keeps_the_state_and_its_since(self) -> None:
        for line in (
            {"type": "rate_limit_event"},
            {"type": "result", "subtype": "success"},
            {"type": "system", "subtype": "task_started"},
            "a line that is not JSON",
            "",
        ):
            assert after_line(WORKING, line, LATER) == WORKING

    def test_a_new_step_in_the_same_state_moves_since(self) -> None:
        bash = {"tool": "Bash", "input": {"command": "make test"}}

        line = after_line(WORKING, _assistant(_call(bash)), LATER)

        assert line == {"state": "working", "since": LATER.isoformat(), "step": bash}


class TestAfterPartial:
    def test_a_text_blocks_start_and_its_deltas_are_writing(self) -> None:
        line = after_partial(WORKING, _block_start("text"), LATER)

        assert line == {"state": "writing", "since": LATER.isoformat(), "step": READ}
        assert after_partial(line, TEXT_DELTA, LATER + timedelta(seconds=1)) is None
        assert after_partial(None, TEXT_DELTA, AT) == {
            "state": "writing",
            "since": AT.isoformat(),
        }

    def test_a_thinking_block_is_thinking_and_a_tool_call_working(self) -> None:
        writing = {"state": "writing", "since": AT.isoformat()}

        assert after_partial(writing, _block_start("thinking"), LATER) == {
            "state": "thinking",
            "since": LATER.isoformat(),
        }
        assert after_partial(writing, _call_start("Edit"), LATER) == {
            "state": "working",
            "since": LATER.isoformat(),
            "step": {"tool": "Edit", "input": None},
        }

    def test_it_drops_the_agent_and_the_starting_words(self) -> None:
        waiting = after_line(None, _assistant(_call(TASK)), AT)
        starting = {"state": "starting", "since": AT.isoformat(), "text": "Creating…"}

        assert after_partial(waiting, _block_start("text"), LATER) == {
            "state": "writing",
            "since": LATER.isoformat(),
            "step": TASK,
        }
        assert after_partial(starting, _block_start("text"), LATER) == {
            "state": "writing",
            "since": LATER.isoformat(),
        }

    def test_a_block_of_another_kind_implies_nothing(self) -> None:
        assert after_partial(WORKING, _block_start("image"), LATER) is None


class TestACallWhoseInputStreamsIn:
    """The line between two tool calls (P-48; V16): from its block's start the
    step is the call whose input streams in, never the previous, finished one."""

    EDIT = {"tool": "Edit", "input": {"file_path": "/work/Example/plan.json"}}

    def test_its_start_names_its_tool_with_no_input(self) -> None:
        finished = after_line(WORKING, _tool_result(), AT)

        line = after_partial(finished, _call_start("Edit"), LATER)

        assert line == {
            "state": "working",
            "since": LATER.isoformat(),
            "step": {"tool": "Edit", "input": None},
        }

    def test_its_line_fills_its_input_in_and_keeps_its_since(self) -> None:
        streaming = after_partial(
            after_line(WORKING, _tool_result(), AT), _call_start("Edit"), AT
        )

        line = after_line(streaming, _assistant(_call(self.EDIT)), LATER)

        assert line == {"state": "working", "since": AT.isoformat(), "step": self.EDIT}

    def test_a_call_of_the_tool_just_called_is_a_new_step(self) -> None:
        """A second `Read` while the first one's `Read` is still the step."""
        line = after_partial(WORKING, _call_start("Read"), LATER)

        assert line == {
            "state": "working",
            "since": LATER.isoformat(),
            "step": {"tool": "Read", "input": None},
        }

    def test_its_start_told_again_leaves_the_line_as_it_is(self) -> None:
        streaming = after_partial(WORKING, _call_start("Edit"), AT)

        assert after_partial(streaming, _call_start("Edit"), LATER) is None

    def test_a_sub_agents_call_starts_working_until_its_line(self) -> None:
        line = after_partial(WORKING, _call_start("Task"), AT)

        assert line == {
            "state": "working",
            "since": AT.isoformat(),
            "step": {"tool": "Task", "input": None},
        }
        assert after_line(line, _assistant(_call(TASK)), LATER) == {
            "state": "waiting",
            "since": LATER.isoformat(),
            "step": TASK,
            "agent": {"type": "Explore", "description": "Find the badge"},
        }
