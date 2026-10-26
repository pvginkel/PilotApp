"""Chat and Chat Read: what a row must hold."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.models import Chat, ChatRead, Environment, Project, Session, User
from app.models.reference import ChatKind, CloseCause, SessionState
from tests.support.database import violated_constraint

CLOSED_AT = datetime(2026, 10, 26, 12, 10, tzinfo=UTC)


def _run(
    session: DbSession,
    project: Project,
    environment: Environment,
    kind_code: str = "chat",
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


def _chat(run: Session, **overrides: object) -> Chat:
    values: dict[str, object] = {
        "id": run.id,
        "project_id": run.project_id,
        "session_kind_code": "chat",
        "kind_code": ChatKind.PROJECT,
    }
    values.update(overrides)
    return Chat(**values)


@pytest.fixture
def other_project(session: DbSession, person: User) -> Project:
    """A second draft of ``person``'s."""
    draft = Project(created_by_user_id=person.id)
    session.add(draft)
    session.flush()
    return draft


class TestChat:
    def test_a_chat_is_its_sessions_identity(
        self, session: DbSession, project: Project, environment: Environment
    ) -> None:
        run = _run(session, project, environment)
        chat = _chat(run)
        session.add(chat)
        session.flush()
        session.expire(chat)

        assert (chat.id, chat.kind_code, chat.closed_at, chat.close_cause_code) == (
            run.id,
            ChatKind.PROJECT,
            None,
            None,
        )

    @pytest.mark.parametrize("cause", list(CloseCause))
    def test_it_closes_with_its_cause(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        cause: CloseCause,
    ) -> None:
        """`finished` and `reopened` with the first two (DB decision 57)."""
        chat = _chat(
            _run(session, project, environment),
            closed_at=CLOSED_AT,
            close_cause_code=cause,
        )
        session.add(chat)
        session.flush()
        session.expire(chat)

        assert (chat.closed_at, chat.close_cause_code) == (CLOSED_AT, cause)

    @pytest.mark.parametrize(
        ("closed_at", "cause"),
        [
            pytest.param(CLOSED_AT, None, id="closed-without-a-cause"),
            pytest.param(None, CloseCause.TIMEOUT, id="a-cause-while-open"),
        ],
    )
    def test_a_close_has_its_cause(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        closed_at: datetime | None,
        cause: CloseCause | None,
    ) -> None:
        session.add(
            _chat(
                _run(session, project, environment),
                closed_at=closed_at,
                close_cause_code=cause,
            )
        )

        assert violated_constraint(session) == "ck_chats_close"

    @pytest.mark.parametrize("kind_code", ["work", "job"])
    def test_a_works_session_is_no_chat(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        kind_code: str,
    ) -> None:
        """DB assertion 149: a `chat` Session is a Chat, a `work` or `job`
        one a Work."""
        run = _run(session, project, environment, kind_code=kind_code)
        session.add(_chat(run, session_kind_code=kind_code))

        assert violated_constraint(session) == "ck_chats_session_kind"

    def test_its_kind_is_its_sessions(
        self, session: DbSession, project: Project, environment: Environment
    ) -> None:
        run = _run(session, project, environment, kind_code="work")
        session.add(_chat(run))

        assert violated_constraint(session) == (
            "chats_project_id_id_session_kind_code_fkey"
        )

    def test_its_project_is_its_sessions(
        self,
        session: DbSession,
        project: Project,
        other_project: Project,
        environment: Environment,
    ) -> None:
        run = _run(session, project, environment)
        session.add(_chat(run, project_id=other_project.id))

        assert violated_constraint(session) == (
            "chats_project_id_id_session_kind_code_fkey"
        )

    def test_a_project_has_one_chat_open_at_a_time(
        self, session: DbSession, project: Project, environment: Environment
    ) -> None:
        session.add_all(
            [
                _chat(_run(session, project, environment), kind_code=kind)
                for kind in (ChatKind.DEFINITION, ChatKind.PROJECT)
            ]
        )

        assert violated_constraint(session) == "uq_chats_open"

    def test_closed_chats_stand_beside_the_open_one(
        self,
        session: DbSession,
        project: Project,
        other_project: Project,
        environment: Environment,
    ) -> None:
        chats = [
            _chat(
                _run(session, project, environment),
                kind_code=ChatKind.DEFINITION,
                closed_at=CLOSED_AT,
                close_cause_code=CloseCause.CREATED,
            ),
            _chat(
                _run(session, project, environment),
                closed_at=CLOSED_AT,
                close_cause_code=CloseCause.TIMEOUT,
            ),
            _chat(_run(session, project, environment)),
            _chat(_run(session, other_project, environment)),
        ]
        session.add_all(chats)
        session.flush()

        assert [chat.closed_at is None for chat in chats] == [False, False, True, True]


class TestChatRead:
    def test_a_persons_place_in_a_projects_chat_is_written(
        self, session: DbSession, person: User, project: Project
    ) -> None:
        read = ChatRead(user_id=person.id, project_id=project.id, read_at=CLOSED_AT)
        session.add(read)
        session.flush()
        session.expire(read)

        assert read.read_at == CLOSED_AT

    def test_one_per_person_and_project(
        self, session: DbSession, person: User, project: Project
    ) -> None:
        session.add(
            ChatRead(user_id=person.id, project_id=project.id, read_at=CLOSED_AT)
        )
        session.flush()
        session.expunge_all()
        session.add(
            ChatRead(user_id=person.id, project_id=project.id, read_at=CLOSED_AT)
        )

        assert violated_constraint(session) == "chat_reads_pkey"

    def test_a_person_has_one_per_project(
        self,
        session: DbSession,
        person: User,
        project: Project,
        other_project: Project,
    ) -> None:
        session.add_all(
            [
                ChatRead(user_id=person.id, project_id=read.id, read_at=CLOSED_AT)
                for read in (project, other_project)
            ]
        )
        session.flush()

        assert set(
            session.scalars(
                select(ChatRead.project_id).where(ChatRead.user_id == person.id)
            )
        ) == {project.id, other_project.id}
