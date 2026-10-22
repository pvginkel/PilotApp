"""A project's live event on the browsers' SSE connections (F80.2): once a
change to what its timeline, head or tab shows commits, every person's
connections hear of it, as one event naming the project, read off test
connections' queues."""

import json
import uuid
from collections.abc import Callable, Iterator
from queue import Empty
from typing import Any

import pytest
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.engine.bus import ProjectChanged, TreeHashMoved
from app.models import Document, Project, User
from app.services.container import ServiceContainer
from app.services.project_event_service import ProjectEventService
from app.services.sse_connection_manager import SSEConnection, SSEConnectionManager
from app.utils.after_commit import clear_after_commit_callbacks

DECISION = """---
title: Which tent?
---

```decision id=D1
options:
  - Dome
  - Tunnel
```
"""

type Connect = Callable[..., SSEConnection]


@pytest.fixture(autouse=True)
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


@pytest.fixture
def manager(container: ServiceContainer) -> SSEConnectionManager:
    return container.sse_connection_manager()


@pytest.fixture
def events(
    container: ServiceContainer, manager: SSEConnectionManager
) -> Iterator[ProjectEventService]:
    """A service of its own on the app's bus, taken off it afterwards."""
    bus = container.engine_bus()
    service = ProjectEventService(container, bus, manager)
    yield service
    bus.unsubscribe(service.deliver)


@pytest.fixture
def connect(manager: SSEConnectionManager) -> Iterator[Connect]:
    """Opens a test connection, as the stream route registers one."""
    opened: list[SSEConnection] = []

    def open_one(
        request_id: str, subject: str | None, *, local_admin: bool = False
    ) -> SSEConnection:
        connection = manager.on_connect(request_id, subject, local_admin=local_admin)
        opened.append(connection)
        return connection

    yield open_one
    for connection in opened:
        manager.on_disconnect(connection)


def frames(connection: SSEConnection) -> list[dict[str, Any]]:
    """The events queued on the connection, in order."""
    queued = []
    while True:
        try:
            frame = connection.next_frame(timeout=0)
        except Empty:
            return queued
        assert frame is not None
        queued.append(json.loads(frame.removeprefix("data: ")))


def changed(project_id: uuid.UUID) -> dict[str, Any]:
    return {"type": "project_changed", "payload": {"project_id": str(project_id)}}


@pytest.mark.usefixtures("events")
class TestProjectEventService:
    def test_every_persons_connections_hear_of_the_change(
        self,
        container: ServiceContainer,
        connect: Connect,
        project: Project,
        person: User,
    ) -> None:
        ben = container.test_data_service().person("ben", "Ben Example")
        assert ben.subject is not None
        ada_tab, ada_other_tab = (
            connect("ada-1", person.subject),
            connect("ada-2", person.subject),
        )
        ben_tab = connect("ben-1", ben.subject)

        with scoped_session(container):
            container.engine_bus().emit(ProjectChanged(project.id))

        assert [frames(tab) for tab in (ada_tab, ada_other_tab, ben_tab)] == [
            [changed(project.id)]
        ] * 3

    def test_a_connection_of_no_person_hears_nothing(
        self,
        container: ServiceContainer,
        connect: Connect,
        project: Project,
        person: User,
    ) -> None:
        newcomer = connect("newcomer-1", "subject-newcomer")
        unbound = connect("unbound-1", None)

        with scoped_session(container):
            container.engine_bus().emit(ProjectChanged(project.id))

        assert (frames(newcomer), frames(unbound)) == ([], [])

    def test_nothing_goes_out_before_the_commit_or_on_a_rollback(
        self,
        container: ServiceContainer,
        connect: Connect,
        project: Project,
        person: User,
    ) -> None:
        tab = connect("ada-1", person.subject)

        with pytest.raises(RuntimeError), scoped_session(container):
            container.engine_bus().emit(ProjectChanged(project.id))
            assert frames(tab) == []
            raise RuntimeError("the transaction fails")

        assert frames(tab) == []

    def test_the_engines_other_events_send_nothing(
        self,
        container: ServiceContainer,
        connect: Connect,
        project: Project,
        person: User,
    ) -> None:
        tab = connect("ada-1", person.subject)

        with scoped_session(container):
            container.engine_bus().emit(
                TreeHashMoved(f"draft-{project.number}/timeline.json", "a" * 64)
            )

        assert frames(tab) == []

    def test_an_answer_is_one_event_naming_its_project(
        self,
        session: DbSession,
        container: ServiceContainer,
        connect: Connect,
        project: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        with scoped_session(container):
            item = container.document_service().bear_item(
                project, "decision", "Which tent?", project_session, DECISION
            )
        tab = connect("ada-1", person.subject)

        # The answer publishes the text and marks the item done: the path and
        # the timeline both move.
        with scoped_session(container):
            container.record_service().answer(
                session.get_one(Document, item.id), "D1", person, "Dome"
            )

        assert frames(tab) == [changed(project.id)]

    def test_each_project_changed_is_named(
        self,
        session: DbSession,
        container: ServiceContainer,
        connect: Connect,
        project: Project,
        person: User,
    ) -> None:
        other = Project(created_by_user_id=person.id)
        session.add(other)
        session.flush()
        tab = connect("ada-1", person.subject)

        with scoped_session(container):
            container.engine_bus().emit(ProjectChanged(project.id))
            container.engine_bus().emit(ProjectChanged(other.id))

        assert frames(tab) == [changed(project.id), changed(other.id)]
