"""Conversation: what a row must hold (DB decision 77, assertions 330 to 335)."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.models import Conversation, Environment, Project, Session, User
from app.models.reference import CloseCause, SessionState
from tests.support.database import violated_constraint

CLOSED_AT = datetime(2026, 11, 14, 11, 20, tzinfo=UTC)
CALLER = "example-recipebox-1a2b3c"


@pytest.fixture
def caller(session: DbSession) -> Environment:
    """The environment a conversation is opened from, not Pilot's own."""
    row = Environment(id=CALLER, name="RecipeBox-2", exempt=False)
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def other_project(session: DbSession, person: User) -> Project:
    """A second project of ``person``'s."""
    other = Project(created_by_user_id=person.id)
    session.add(other)
    session.flush()
    return other


def _run(
    session: DbSession,
    project: Project,
    environment: Environment,
    kind_code: str = "conversation",
) -> Session:
    run = Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code=kind_code,
        cwd="/work/PilotProjects",
        token_hash=uuid.uuid4().hex * 2,
        state_code=SessionState.STARTING,
    )
    session.add(run)
    session.flush()
    return run


def _conversation(run: Session, **overrides: object) -> Conversation:
    values: dict[str, object] = {
        "id": run.id,
        "project_id": run.project_id,
        "session_kind_code": "conversation",
        "caller_environment_id": CALLER,
        "caller_session": "ui-sweep-triage",
    }
    values.update(overrides)
    return Conversation(**values)


class TestConversation:
    def test_a_conversation_is_its_sessions_identity(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        caller: Environment,
    ) -> None:
        """It runs in the store and names the environment it was opened
        from, two facts (DB 333)."""
        run = _run(session, project, environment)
        conversation = _conversation(run)
        session.add(conversation)
        session.flush()
        session.expire(conversation)

        assert (
            conversation.id,
            conversation.caller_environment_id,
            conversation.caller_session,
            conversation.closed_at,
            conversation.close_cause_code,
        ) == (run.id, CALLER, "ui-sweep-triage", None, None)
        assert run.environment_id == environment.id != CALLER

    def test_a_call_that_named_no_session_has_none(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        caller: Environment,
    ) -> None:
        conversation = _conversation(
            _run(session, project, environment), caller_session=None
        )
        session.add(conversation)
        session.flush()
        session.expire(conversation)

        assert conversation.caller_session is None

    def test_an_empty_session_name_is_no_name(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        caller: Environment,
    ) -> None:
        conversation = _conversation(
            _run(session, project, environment), caller_session=""
        )
        session.add(conversation)
        session.flush()
        session.expire(conversation)

        assert conversation.caller_session is None

    def test_it_is_opened_from_an_environment_pilot_has_a_row_of(
        self, session: DbSession, project: Project, environment: Environment
    ) -> None:
        session.add(_conversation(_run(session, project, environment)))

        assert violated_constraint(session) == (
            "conversations_caller_environment_id_fkey"
        )

    def test_the_store_itself_may_be_where_it_is_opened_from(
        self, session: DbSession, project: Project, environment: Environment
    ) -> None:
        """DB 333: a brain session's own call."""
        conversation = _conversation(
            _run(session, project, environment), caller_environment_id=environment.id
        )
        session.add(conversation)
        session.flush()

        assert conversation.caller_environment_id == environment.id

    @pytest.mark.parametrize(
        "cause", [cause for cause in CloseCause if cause is not CloseCause.CREATED]
    )
    def test_it_closes_with_its_cause(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        caller: Environment,
        cause: CloseCause,
    ) -> None:
        conversation = _conversation(
            _run(session, project, environment),
            closed_at=CLOSED_AT,
            close_cause_code=cause,
        )
        session.add(conversation)
        session.flush()
        session.expire(conversation)

        assert (conversation.closed_at, conversation.close_cause_code) == (
            CLOSED_AT,
            cause,
        )

    def test_none_is_closed_at_create_project(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        caller: Environment,
    ) -> None:
        """DB 334: none opens on a draft, so `created` is a Chat's alone."""
        session.add(
            _conversation(
                _run(session, project, environment),
                closed_at=CLOSED_AT,
                close_cause_code=CloseCause.CREATED,
            )
        )

        assert violated_constraint(session) == "ck_conversations_close_cause"

    @pytest.mark.parametrize(
        ("closed_at", "cause"),
        [
            pytest.param(CLOSED_AT, None, id="closed-without-a-cause"),
            pytest.param(None, CloseCause.ENDED, id="a-cause-while-open"),
        ],
    )
    def test_a_close_has_its_cause(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        caller: Environment,
        closed_at: datetime | None,
        cause: CloseCause | None,
    ) -> None:
        session.add(
            _conversation(
                _run(session, project, environment),
                closed_at=closed_at,
                close_cause_code=cause,
            )
        )

        assert violated_constraint(session) == "ck_conversations_close"

    @pytest.mark.parametrize("kind_code", ["chat", "work", "job"])
    def test_another_kinds_session_is_no_conversation(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        caller: Environment,
        kind_code: str,
    ) -> None:
        """DB assertion 149: a `conversation` Session is a Conversation."""
        run = _run(session, project, environment, kind_code=kind_code)
        session.add(_conversation(run, session_kind_code=kind_code))

        assert violated_constraint(session) == "ck_conversations_session_kind"

    def test_its_kind_is_its_sessions(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        caller: Environment,
    ) -> None:
        run = _run(session, project, environment, kind_code="chat")
        session.add(_conversation(run))

        assert violated_constraint(session) == (
            "conversations_project_id_id_session_kind_code_fkey"
        )

    def test_its_project_is_its_sessions(
        self,
        session: DbSession,
        project: Project,
        other_project: Project,
        environment: Environment,
        caller: Environment,
    ) -> None:
        run = _run(session, project, environment)
        session.add(_conversation(run, project_id=other_project.id))

        assert violated_constraint(session) == (
            "conversations_project_id_id_session_kind_code_fkey"
        )

    def test_a_project_has_several_open_at_once(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        caller: Environment,
    ) -> None:
        """DB 335: from one calling session or from several."""
        session.add_all(
            [
                _conversation(_run(session, project, environment), caller_session=name)
                for name in ("ui-sweep-triage", "ui-sweep-triage", "ga-prep", None)
            ]
        )
        session.flush()

        assert session.scalars(
            select(Conversation.caller_session)
            .where(
                Conversation.project_id == project.id,
                Conversation.closed_at.is_(None),
            )
            .order_by(Conversation.caller_session)
        ).all() == ["ga-prep", "ui-sweep-triage", "ui-sweep-triage", None]
