"""A work item's status, live on every browser (F80.2's work status): the
events its Session's writers raise once their transaction commits."""

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.engine.bus import EngineEvent, ProjectChanged, WorkMoved
from app.models import Environment, Project
from app.models.reference import SessionState
from app.services.container import ServiceContainer
from app.services.work_status import work_moved
from app.utils.after_commit import clear_after_commit_callbacks


@pytest.fixture(autouse=True)
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


def _session(
    db: DbSession, project: Project, environment: Environment, kind: str
) -> models.Session:
    run = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code=kind,
        cwd="/work/Example",
        token_hash=kind * 16,
        state_code=SessionState.RUNNING,
    )
    db.add(run)
    db.flush()
    return run


class TestWorkMoved:
    @pytest.mark.parametrize("kind", ["work", "job"])
    def test_a_move_of_the_line_is_the_work_items_alone(
        self,
        container: ServiceContainer,
        session: DbSession,
        project: Project,
        environment: Environment,
        engine_events: list[EngineEvent],
        kind: str,
    ) -> None:
        run = _session(session, project, environment, kind)

        with scoped_session(container):
            work_moved(container.engine_bus(), run)

        assert engine_events == [WorkMoved(project.id, run.id)]

    def test_a_move_of_the_state_moves_the_project_too(
        self,
        container: ServiceContainer,
        session: DbSession,
        project: Project,
        environment: Environment,
        engine_events: list[EngineEvent],
    ) -> None:
        run = _session(session, project, environment, "work")

        with scoped_session(container):
            work_moved(container.engine_bus(), run, state=True)

        assert engine_events == [
            WorkMoved(project.id, run.id),
            ProjectChanged(project.id),
        ]

    def test_a_chats_session_raises_nothing(
        self,
        container: ServiceContainer,
        session: DbSession,
        project: Project,
        environment: Environment,
        engine_events: list[EngineEvent],
    ) -> None:
        run = _session(session, project, environment, "chat")

        with scoped_session(container):
            work_moved(container.engine_bus(), run, state=True)

        assert engine_events == []

    def test_the_moves_of_one_transaction_go_out_once(
        self,
        container: ServiceContainer,
        session: DbSession,
        project: Project,
        environment: Environment,
        engine_events: list[EngineEvent],
    ) -> None:
        run = _session(session, project, environment, "work")

        with scoped_session(container):
            work_moved(container.engine_bus(), run, state=True)
            work_moved(container.engine_bus(), run)
            work_moved(container.engine_bus(), run, state=True)

        assert engine_events == [
            WorkMoved(project.id, run.id),
            ProjectChanged(project.id),
        ]

    def test_nothing_goes_out_on_a_rollback(
        self,
        container: ServiceContainer,
        session: DbSession,
        project: Project,
        environment: Environment,
        engine_events: list[EngineEvent],
    ) -> None:
        run = _session(session, project, environment, "work")

        with pytest.raises(RuntimeError), scoped_session(container):
            work_moved(container.engine_bus(), run, state=True)
            raise RuntimeError("the transaction fails")

        assert engine_events == []
