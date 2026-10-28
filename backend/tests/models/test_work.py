"""Work: what a row must hold."""

import uuid

import pytest
from sqlalchemy.orm import Session as DbSession

from app.models import Environment, Item, Project, Session, User, Work
from app.models.reference import SessionState, WorkTrigger
from tests.support.database import violated_constraint


def _run(
    project: Project,
    environment: Environment,
    run_id: uuid.UUID,
    kind_code: str = "work",
) -> Session:
    return Session(
        id=run_id,
        project_id=project.id,
        environment_id=environment.id,
        kind_code=kind_code,
        cwd="/work/Example",
        token_hash=uuid.uuid4().hex * 2,
        state_code=SessionState.STARTING,
    )


def _entry(project: Project, creator: Session, entry_id: uuid.UUID, seq: int) -> Item:
    return Item(
        id=entry_id,
        project_id=project.id,
        seq=seq,
        kind_code="work",
        title="Fixing the client for v4",
        created_by_session_id=creator.id,
    )


def _work(project: Project, work_id: uuid.UUID, **overrides: object) -> Work:
    values: dict[str, object] = {
        "id": work_id,
        "project_id": project.id,
        "session_kind_code": "work",
        "autopilot": False,
    }
    values.update(overrides)
    return Work(**values)


@pytest.fixture
def other_project(session: DbSession, person: User) -> Project:
    """A second draft of ``person``'s."""
    draft = Project(created_by_user_id=person.id)
    session.add(draft)
    session.flush()
    return draft


class TestWork:
    def test_a_workers_run_is_one_item_and_one_session(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
    ) -> None:
        work_id = uuid.uuid4()
        session.add_all(
            [
                _entry(project, project_session, work_id, seq=2),
                _run(project, environment, work_id),
                _work(project, work_id),
            ]
        )
        session.flush()

        work = session.get_one(Work, work_id)
        assert work.trigger_code is None
        assert work.trigger_item_id is None
        assert session.get_one(Item, work_id).project_id == project.id
        assert session.get_one(Session, work_id).project_id == project.id

    def test_a_workers_run_is_placed_in_a_repository(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
    ) -> None:
        work_id = uuid.uuid4()
        session.add_all(
            [
                _entry(project, project_session, work_id, seq=2),
                _run(project, environment, work_id),
                _work(project, work_id, repo="pvginkel/Example"),
            ]
        )
        session.flush()
        session.expire_all()

        assert session.get_one(Work, work_id).repo == "pvginkel/Example"

    def test_a_job_has_its_trigger_and_the_item_that_triggered_it(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
        item: Item,
    ) -> None:
        work_id = uuid.uuid4()
        session.add_all(
            [
                _entry(project, project_session, work_id, seq=2),
                _run(project, environment, work_id, kind_code="job"),
                _work(
                    project,
                    work_id,
                    session_kind_code="job",
                    trigger_code=WorkTrigger.ITEM_DONE,
                    trigger_item_id=item.id,
                    autopilot=True,
                ),
            ]
        )
        session.flush()
        session.expire_all()

        work = session.get_one(Work, work_id)
        assert work.trigger_code == WorkTrigger.ITEM_DONE
        assert work.trigger_item_id == item.id
        assert work.autopilot is True

    def test_a_workers_resume_names_the_item_whose_done_resumed_it(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
        item: Item,
    ) -> None:
        work_id = uuid.uuid4()
        session.add_all(
            [
                _entry(project, project_session, work_id, seq=2),
                _run(project, environment, work_id),
                _work(project, work_id, trigger_item_id=item.id),
            ]
        )
        session.flush()

        assert session.get_one(Work, work_id).trigger_item_id == item.id

    def test_a_work_is_an_item(
        self, session: DbSession, project: Project, environment: Environment
    ) -> None:
        work_id = uuid.uuid4()
        session.add_all([_run(project, environment, work_id), _work(project, work_id)])

        assert violated_constraint(session) == "work_project_id_id_fkey"

    def test_a_work_is_a_session(
        self, session: DbSession, project: Project, project_session: Session
    ) -> None:
        work_id = uuid.uuid4()
        session.add_all(
            [_entry(project, project_session, work_id, seq=2), _work(project, work_id)]
        )

        assert (
            violated_constraint(session) == "work_project_id_id_session_kind_code_fkey"
        )

    def test_its_item_and_its_session_are_of_one_project(
        self,
        session: DbSession,
        project: Project,
        other_project: Project,
        environment: Environment,
        project_session: Session,
    ) -> None:
        work_id = uuid.uuid4()
        session.add_all(
            [
                _entry(project, project_session, work_id, seq=2),
                _run(other_project, environment, work_id),
                _work(project, work_id),
            ]
        )

        assert (
            violated_constraint(session) == "work_project_id_id_session_kind_code_fkey"
        )

    def test_its_session_kind_is_its_sessions(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
    ) -> None:
        work_id = uuid.uuid4()
        session.add_all(
            [
                _entry(project, project_session, work_id, seq=2),
                _run(project, environment, work_id),
                _work(
                    project,
                    work_id,
                    session_kind_code="job",
                    trigger_code=WorkTrigger.SETUP,
                ),
            ]
        )

        assert (
            violated_constraint(session) == "work_project_id_id_session_kind_code_fkey"
        )

    def test_a_chat_is_never_a_work(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
    ) -> None:
        work_id = uuid.uuid4()
        session.add_all(
            [
                _entry(project, project_session, work_id, seq=2),
                _run(project, environment, work_id, kind_code="chat"),
                _work(project, work_id, session_kind_code="chat"),
            ]
        )

        assert violated_constraint(session) == "ck_work_session_kind"

    def test_a_job_has_a_trigger(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
    ) -> None:
        work_id = uuid.uuid4()
        session.add_all(
            [
                _entry(project, project_session, work_id, seq=2),
                _run(project, environment, work_id, kind_code="job"),
                _work(project, work_id, session_kind_code="job"),
            ]
        )

        assert violated_constraint(session) == "ck_work_trigger"

    def test_a_workers_run_has_no_trigger(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
    ) -> None:
        work_id = uuid.uuid4()
        session.add_all(
            [
                _entry(project, project_session, work_id, seq=2),
                _run(project, environment, work_id),
                _work(project, work_id, trigger_code=WorkTrigger.WORKER_TURN_ENDED),
            ]
        )

        assert violated_constraint(session) == "ck_work_trigger"

    def test_its_trigger_item_is_of_its_project(
        self,
        session: DbSession,
        project: Project,
        other_project: Project,
        environment: Environment,
        project_session: Session,
    ) -> None:
        elsewhere = _entry(other_project, project_session, uuid.uuid4(), seq=1)
        work_id = uuid.uuid4()
        session.add_all(
            [
                elsewhere,
                _entry(project, project_session, work_id, seq=2),
                _run(project, environment, work_id),
                _work(project, work_id, trigger_item_id=elsewhere.id),
            ]
        )

        assert violated_constraint(session) == "work_project_id_trigger_item_id_fkey"

    def test_its_trigger_item_is_another_item(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
    ) -> None:
        work_id = uuid.uuid4()
        session.add_all(
            [
                _entry(project, project_session, work_id, seq=2),
                _run(project, environment, work_id),
                _work(project, work_id, trigger_item_id=work_id),
            ]
        )

        assert violated_constraint(session) == "ck_work_trigger_item"

    def test_a_job_is_placed_in_no_repository(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
    ) -> None:
        work_id = uuid.uuid4()
        session.add_all(
            [
                _entry(project, project_session, work_id, seq=2),
                _run(project, environment, work_id, kind_code="job"),
                _work(
                    project,
                    work_id,
                    session_kind_code="job",
                    trigger_code=WorkTrigger.SETUP,
                    repo="pvginkel/Example",
                ),
            ]
        )

        assert violated_constraint(session) == "ck_work_repo"


def _job(
    session: DbSession,
    project: Project,
    environment: Environment,
    creator: Session,
    seq: int,
    kind_code: str = "job",
) -> uuid.UUID:
    """A Work of `kind_code` in `project`, the setup when a job; its id."""
    work_id = uuid.uuid4()
    session.add_all(
        [
            _entry(project, creator, work_id, seq=seq),
            _run(project, environment, work_id, kind_code=kind_code),
        ]
    )
    session.flush()
    session.add(
        _work(
            project,
            work_id,
            session_kind_code=kind_code,
            trigger_code=WorkTrigger.SETUP if kind_code == "job" else None,
        )
    )
    session.flush()
    return work_id


class TestRetriedBy:
    """A person's Retry of a failed or stopped job: the job retried names the
    job the Retry placed, a recursive list (DB Work)."""

    def test_a_job_is_retried_by_another_job_of_its_project(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
    ) -> None:
        failed = _job(session, project, environment, project_session, seq=2)
        retry = _job(session, project, environment, project_session, seq=3)

        session.get_one(Work, failed).retried_by_id = retry
        session.flush()
        session.expire_all()

        assert session.get_one(Work, failed).retried_by_id == retry
        assert session.get_one(Work, retry).retried_by_id is None

    def test_its_retry_is_of_its_project(
        self,
        session: DbSession,
        project: Project,
        other_project: Project,
        environment: Environment,
        project_session: Session,
    ) -> None:
        failed = _job(session, project, environment, project_session, seq=2)
        elsewhere = _job(session, other_project, environment, project_session, seq=1)

        session.get_one(Work, failed).retried_by_id = elsewhere

        assert (
            violated_constraint(session)
            == "work_project_id_retried_by_id_session_kind_code_fkey"
        )

    def test_its_retry_is_a_job(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
    ) -> None:
        failed = _job(session, project, environment, project_session, seq=2)
        run = _job(
            session, project, environment, project_session, seq=3, kind_code="work"
        )

        session.get_one(Work, failed).retried_by_id = run

        assert (
            violated_constraint(session)
            == "work_project_id_retried_by_id_session_kind_code_fkey"
        )

    def test_a_workers_run_is_never_retried(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
    ) -> None:
        first = _job(
            session, project, environment, project_session, seq=2, kind_code="work"
        )
        second = _job(
            session, project, environment, project_session, seq=3, kind_code="work"
        )

        session.get_one(Work, first).retried_by_id = second

        assert violated_constraint(session) == "ck_work_retried_by"

    def test_a_job_is_not_its_own_retry(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
    ) -> None:
        failed = _job(session, project, environment, project_session, seq=2)

        session.get_one(Work, failed).retried_by_id = failed

        assert violated_constraint(session) == "ck_work_retried_by"

    def test_a_retry_retries_one_job(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
    ) -> None:
        first = _job(session, project, environment, project_session, seq=2)
        second = _job(session, project, environment, project_session, seq=3)
        retry = _job(session, project, environment, project_session, seq=4)
        session.get_one(Work, first).retried_by_id = retry
        session.flush()

        session.get_one(Work, second).retried_by_id = retry

        assert violated_constraint(session) == "uq_work_retried_by_id"
