"""Save Error: what a row must hold."""

from sqlalchemy.orm import Session as DbSession

from app.models import Environment, SaveError
from app.models.reference import ErrorKind
from tests.support.database import violated_constraint


class TestSaveError:
    def test_a_fault_is_held_against_a_path(
        self, session: DbSession, environment: Environment
    ) -> None:
        fault = SaveError(
            environment_id=environment.id,
            path="draft-1/items/2-which-provider.md",
            kind_code=ErrorKind.PARSE,
            line=14,
            message="block D1: options is not a list",
        )
        session.add(fault)
        session.flush()
        session.refresh(fault)

        assert fault.created_at is not None

    def test_a_fault_may_have_no_line(
        self, session: DbSession, environment: Environment
    ) -> None:
        fault = SaveError(
            environment_id=environment.id,
            path="draft-1/plan.json",
            kind_code=ErrorKind.PARSE,
            message="plan.json is not a JSON object",
        )
        session.add(fault)
        session.flush()

        assert fault.line is None

    def test_a_fault_is_held_by_an_environment(self, session: DbSession) -> None:
        session.add(
            SaveError(
                environment_id="no-such-env",
                path="draft-1/project.md",
                kind_code=ErrorKind.REVERTED,
                message="line 31 reverted: `answer:` is the record's",
            )
        )

        assert violated_constraint(session) == "save_errors_environment_id_fkey"
