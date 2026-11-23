"""A task's progress update, with what the task has answered so far: the
standing edit to the template's task form that lets a page show a task's
answer as it comes."""

import json
from collections.abc import Iterator
from queue import Empty
from typing import Any

import pytest

from app.services.base_task import SubProgressHandle
from app.services.container import ServiceContainer
from app.services.sse_connection_manager import SSEConnection, Target
from app.services.task_service import TaskProgressHandle

SUBJECT = "ada"


@pytest.fixture
def ada(container: ServiceContainer) -> Iterator[SSEConnection]:
    manager = container.sse_connection_manager()
    connection = manager.on_connect("ada-tasks", SUBJECT)
    yield connection
    manager.on_disconnect(connection)


def _progress(connection: SSEConnection) -> list[dict[str, Any]]:
    queued = []
    while True:
        try:
            frame = connection.next_frame(timeout=0)
        except Empty:
            return queued
        assert frame is not None
        envelope = json.loads(frame.removeprefix("data: "))
        assert envelope["type"] == "task_event"
        assert envelope["payload"]["event_type"] == "progress_update"
        queued.append(envelope["payload"]["data"])


class TestTaskProgressHandle:
    def test_an_update_carries_what_the_task_has_answered_so_far(
        self, container: ServiceContainer, ada: SSEConnection
    ) -> None:
        handle = TaskProgressHandle(
            "task-1", container.sse_connection_manager(), Target.subject(SUBJECT)
        )

        handle.send_progress("Counted the calls", 0.5, {"counts": {"project": 2}})

        assert _progress(ada) == [
            {
                "text": "Counted the calls",
                "value": 0.5,
                "data": {"counts": {"project": 2}},
            }
        ]

    def test_an_update_of_its_text_and_value_alone_carries_none(
        self, container: ServiceContainer, ada: SSEConnection
    ) -> None:
        handle = TaskProgressHandle(
            "task-1", container.sse_connection_manager(), Target.subject(SUBJECT)
        )

        handle.send_progress_text("Starting")
        handle.send_progress("Halfway", 0.5)

        assert _progress(ada) == [
            {"text": "Starting", "value": 0.0, "data": None},
            {"text": "Halfway", "value": 0.5, "data": None},
        ]

    def test_a_sub_task_passes_its_data_on_at_its_parents_scale(
        self, container: ServiceContainer, ada: SSEConnection
    ) -> None:
        parent = TaskProgressHandle(
            "task-1", container.sse_connection_manager(), Target.subject(SUBJECT)
        )

        SubProgressHandle(parent, 0.5, 1.0).send_progress("Second half", 0.5, {"n": 1})

        assert _progress(ada) == [
            {"text": "Second half", "value": 0.75, "data": {"n": 1}}
        ]
