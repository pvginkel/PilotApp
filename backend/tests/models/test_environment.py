"""Environment: what a row must hold."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session as DbSession

from app.models import Environment
from tests.support.database import violated_constraint

CREATED_AT = datetime(2026, 10, 24, 9, 30, tzinfo=UTC)


def _own(**overrides: object) -> Environment:
    """An environment Pilot created from a repository."""
    values: dict[str, object] = {
        "id": "pvginkel-example-3f9a2c",
        "name": "example",
        "exempt": False,
        "server_created_at": CREATED_AT,
        "repo": "pvginkel/Example",
    }
    values.update(overrides)
    return Environment(**values)


class TestEnvironment:
    def test_one_pilot_did_not_create_has_no_repository_and_no_deadline(
        self, session: DbSession, environment: Environment
    ) -> None:
        session.expire(environment)

        assert environment.server_created_at is None
        assert environment.repo is None
        assert environment.delete_due_at is None

    def test_pilots_own_holds_its_repository_and_its_delete_deadline(
        self, session: DbSession
    ) -> None:
        own = _own(delete_due_at=CREATED_AT + timedelta(days=7))
        session.add(own)
        session.flush()
        session.expire(own)

        assert own.server_created_at == CREATED_AT
        assert own.repo == "pvginkel/Example"
        assert own.delete_due_at == CREATED_AT + timedelta(days=7)

    def test_pilots_own_was_created_from_a_repository(self, session: DbSession) -> None:
        session.add(_own(repo=None))

        assert violated_constraint(session) == "ck_environments_repo"

    def test_only_pilots_own_has_a_repository(self, session: DbSession) -> None:
        session.add(_own(server_created_at=None))

        assert violated_constraint(session) == "ck_environments_repo"

    def test_only_pilots_own_has_a_delete_deadline(
        self, session: DbSession, environment: Environment
    ) -> None:
        environment.delete_due_at = CREATED_AT

        assert violated_constraint(session) == "ck_environments_delete_due_at"
