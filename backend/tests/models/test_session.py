"""Session: what a row must hold."""

from sqlalchemy.orm import Session as DbSession

from app.models import Environment, Project, Session
from app.models.reference import SessionState
from tests.support.database import violated_constraint


def _session(
    project: Project, environment: Environment, **overrides: object
) -> Session:
    values: dict[str, object] = {
        "project_id": project.id,
        "environment_id": environment.id,
        "kind_code": "work",
        "cwd": "/work/Example",
        "token_hash": "0" * 64,
        "state_code": SessionState.STARTING,
    }
    values.update(overrides)
    return Session(**values)


class TestSession:
    def test_a_session_is_written(
        self, session: DbSession, project: Project, environment: Environment
    ) -> None:
        run = _session(project, environment)
        session.add(run)
        session.flush()
        session.refresh(run)

        assert run.turns == 0
        assert run.created_at is not None

    def test_its_kind_is_a_session_kind(
        self, session: DbSession, project: Project, environment: Environment
    ) -> None:
        session.add(_session(project, environment, kind_code="other"))

        assert violated_constraint(session) == "sessions_kind_code_fkey"

    def test_a_token_names_one_session(
        self, session: DbSession, project: Project, environment: Environment
    ) -> None:
        session.add_all([_session(project, environment) for _ in range(2)])

        assert violated_constraint(session) == "uq_sessions_token_hash"
