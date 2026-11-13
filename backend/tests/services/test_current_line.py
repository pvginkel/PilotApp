"""A Session's current line, as the session start sets it and the relay
rebuilds it (design 2 §9.5, Q5; V15)."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.current_line import (
    CurrentLine,
    after_line,
    after_partial,
    at_send,
    while_starting,
)
from tests.support.fake_controller import raw_turn

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


IMPORT = {"type": "local_bash", "description": "Wait for the nightly import"}


def _task_started(
    task: str = "t1", description: str = "Wait for the nightly import", **keys: Any
) -> dict[str, Any]:
    return {
        "type": "system",
        "subtype": "task_started",
        "task_id": task,
        "tool_use_id": "toolu_example",
        "description": description,
        "is_backgrounded": True,
        "task_type": "local_bash",
        **keys,
    }


def _task_notification(task: str = "t1") -> dict[str, Any]:
    return {
        "type": "system",
        "subtype": "task_notification",
        "task_id": task,
        "tool_use_id": "toolu_example",
        "status": "completed",
    }


RESULT = {"type": "result", "subtype": "success"}
INIT = {"type": "system", "subtype": "init"}


def _after(previous: CurrentLine | None, *lines: Any) -> CurrentLine:
    """The line once `lines` are recorded, each a second after the one before."""
    line = previous
    for index, each in enumerate(lines):
        line = after_line(line, each, LATER + timedelta(seconds=index))
    assert line is not None
    return line


class TestABackgroundTask:
    """A task the model left running in the background when its own turn ended
    (P-253): the line says it waits on it until the task's notification."""

    def test_a_turn_that_leaves_a_command_running_waits_on_it_to_its_notification(
        self,
    ) -> None:
        """The fixture's turn, in the shape `claude` prints one: the call, its
        task, the model's `result`, the worker's nudge answered WAITING, the
        notification, the delivery turn."""
        states: list[tuple[str, str]] = []
        line: CurrentLine | None = None
        for index, raw in enumerate(raw_turn("turn_background")):
            recorded = json.loads(raw)
            line = after_line(line, recorded, AT + timedelta(seconds=index))
            states.append((recorded.get("subtype", recorded["type"]), line["state"]))
            if line["state"] == "background":
                assert line["task"] == IMPORT
                assert line["since"] == (AT + timedelta(seconds=8)).isoformat()

        assert states == [
            ("init", "thinking"),
            ("status", "thinking"),
            ("assistant", "working"),
            ("background_tasks_changed", "working"),
            ("task_started", "working"),
            ("user", "thinking"),
            ("status", "thinking"),
            ("assistant", "thinking"),
            ("success", "background"),
            ("init", "background"),
            ("status", "background"),
            ("assistant", "background"),
            ("success", "background"),
            ("task_updated", "background"),
            ("task_notification", "thinking"),
            ("background_tasks_changed", "thinking"),
            ("init", "thinking"),
            ("status", "thinking"),
            ("assistant", "thinking"),
            ("success", "thinking"),
        ]
        assert line is not None and "tasks" not in line and "task" not in line

    def test_the_models_result_with_a_task_in_the_background_is_background(
        self,
    ) -> None:
        line = _after(WORKING, _task_started(), _tool_result(), RESULT)

        assert line == {
            "state": "background",
            "since": (LATER + timedelta(seconds=2)).isoformat(),
            "step": READ,
            "task": IMPORT,
            "tasks": [{"id": "t1", **IMPORT, "backgrounded": True}],
        }

    def test_a_task_in_the_foreground_is_not_waited_on(self) -> None:
        started = _task_started(is_backgrounded=False, task_type="local_agent")

        line = _after(WORKING, started, _tool_result(), RESULT)

        assert line["state"] == "thinking"

    def test_a_task_started_without_the_key_is_in_the_foreground(self) -> None:
        started = _task_started()
        del started["is_backgrounded"]

        assert _after(WORKING, started, _tool_result(), RESULT)["state"] == "thinking"

    def test_a_command_moved_to_the_background_at_its_timeout_is_waited_on(
        self,
    ) -> None:
        moved = {
            "type": "system",
            "subtype": "task_updated",
            "task_id": "t1",
            "patch": {"is_backgrounded": True},
        }

        line = _after(
            WORKING, _task_started(is_backgrounded=False), moved, _tool_result(), RESULT
        )

        assert line["state"] == "background"
        assert line["task"] == IMPORT

    def test_a_sub_agents_own_task_is_not_waited_on(self) -> None:
        line = _after(
            WORKING, _task_started(owned_by_subagent=True), _tool_result(), RESULT
        )

        assert line["state"] == "thinking"
        assert "tasks" not in line

    def test_a_task_that_ended_before_the_models_result_is_not_waited_on(self) -> None:
        line = _after(
            WORKING, _task_started(), _tool_result(), _task_notification(), RESULT
        )

        assert line == {
            "state": "thinking",
            "since": (LATER + timedelta(seconds=1)).isoformat(),
            "step": READ,
        }

    def test_nothing_but_a_call_moves_it_before_the_notification(self) -> None:
        waiting = _after(WORKING, _task_started(), _tool_result(), RESULT)

        for line in (
            INIT,
            {"type": "system", "subtype": "status", "status": "requesting"},
            _assistant({"type": "thinking", "thinking": ""}),
            _assistant({"type": "text", "text": "WAITING"}),
            {"type": "rate_limit_event"},
            RESULT,
        ):
            assert after_line(waiting, line, LATER + timedelta(minutes=1)) == waiting
        for partial in (_block_start("thinking"), _block_start("text"), TEXT_DELTA):
            assert after_partial(waiting, partial, LATER + timedelta(minutes=1)) is None

    def test_a_call_made_while_it_waits_is_working_and_its_turns_end_waits_again(
        self,
    ) -> None:
        waiting = _after(WORKING, _task_started(), _tool_result(), RESULT)
        bash = {"tool": "Bash", "input": {"command": "tail import.log"}}

        streaming = after_partial(waiting, _call_start("Bash"), LATER)
        assert streaming is not None
        assert streaming["state"] == "working"
        assert streaming["step"] == {"tool": "Bash", "input": None}
        assert "task" not in streaming
        working = _after(streaming, _assistant(_call(bash)))
        assert working["state"] == "working"
        assert _after(working, _tool_result())["state"] == "thinking"
        again = _after(working, _tool_result(), _assistant({"type": "text"}), RESULT)
        assert again["state"] == "background"
        assert again["task"] == IMPORT

    def test_of_two_it_waits_on_the_one_started_last_that_still_runs(self) -> None:
        build = _task_started("t2", "Build the image")
        waiting = _after(WORKING, _task_started(), build, _tool_result(), RESULT)

        assert waiting["task"] == {
            "type": "local_bash",
            "description": "Build the image",
        }
        on_the_first = _after(waiting, _task_notification("t2"))
        assert on_the_first["state"] == "background"
        assert on_the_first["task"] == IMPORT
        assert on_the_first["since"] == waiting["since"]
        assert _after(on_the_first, _task_notification("t1")) == {
            "state": "thinking",
            "since": LATER.isoformat(),
            "step": READ,
        }

    def test_a_notification_of_a_task_it_does_not_hold_changes_nothing(self) -> None:
        waiting = _after(WORKING, _task_started(), _tool_result(), RESULT)

        assert after_line(waiting, _task_notification("t9"), LATER) == waiting
