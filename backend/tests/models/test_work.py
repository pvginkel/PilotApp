"""Work, Progress Step and Clarification Run: what a row must hold."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.models import (
    ClarificationRun,
    Environment,
    Item,
    ProgressStep,
    Project,
    Session,
    User,
    Work,
)
from app.models.reference import ProgressState, SessionState, WorkTrigger
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


class TestClarificationRun:
    """The role of a worker's run that puts a pass's questions to the writer,
    naming the pass and holding the reply (DB decision 63; 252, 253, 255)."""

    def test_a_run_clarifies_a_pass_and_holds_the_reply_with_its_time(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
    ) -> None:
        passed = _job(session, project, environment, project_session, seq=2)
        run = _job(
            session, project, environment, project_session, seq=3, kind_code="work"
        )
        at = datetime(2026, 9, 24, 14, 21, tzinfo=UTC)
        session.add(
            ClarificationRun(
                id=run, pass_id=passed, reply="## D1\nThe lake.", replied_at=at
            )
        )
        session.flush()
        session.expire_all()

        clarification = session.get_one(ClarificationRun, run)
        assert (
            clarification.pass_id,
            clarification.reply,
            clarification.replied_at,
        ) == (
            passed,
            "## D1\nThe lake.",
            at,
        )

    @pytest.mark.parametrize(
        ("reply", "replied_at"),
        [("## D1\nThe lake.", None), (None, datetime(2026, 9, 24, tzinfo=UTC))],
    )
    def test_its_reply_and_its_time_are_written_together(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
        reply: str | None,
        replied_at: datetime | None,
    ) -> None:
        passed = _job(session, project, environment, project_session, seq=2)
        run = _job(
            session, project, environment, project_session, seq=3, kind_code="work"
        )
        session.add(
            ClarificationRun(id=run, pass_id=passed, reply=reply, replied_at=replied_at)
        )

        assert violated_constraint(session) == "ck_clarification_runs_reply"

    def test_a_run_never_clarifies_itself(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
    ) -> None:
        run = _job(
            session, project, environment, project_session, seq=2, kind_code="work"
        )
        session.add(ClarificationRun(id=run, pass_id=run))

        assert violated_constraint(session) == "ck_clarification_runs_pass"

    def test_a_pass_is_clarified_once(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
    ) -> None:
        passed = _job(session, project, environment, project_session, seq=2)
        first = _job(
            session, project, environment, project_session, seq=3, kind_code="work"
        )
        second = _job(
            session, project, environment, project_session, seq=4, kind_code="work"
        )
        session.add(ClarificationRun(id=first, pass_id=passed))
        session.flush()
        session.add(ClarificationRun(id=second, pass_id=passed))

        assert violated_constraint(session) == "uq_clarification_runs_pass_id"

    def test_it_is_a_works_role(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
    ) -> None:
        passed = _job(session, project, environment, project_session, seq=2)
        session.add(ClarificationRun(id=uuid.uuid4(), pass_id=passed))

        assert violated_constraint(session) == "clarification_runs_id_fkey"


STARTED = datetime(2026, 11, 2, 11, 20, tzinfo=UTC)
ENDED = STARTED + timedelta(minutes=21)


def _step(
    work_id: uuid.UUID, code: str, position: int, **overrides: object
) -> ProgressStep:
    values: dict[str, object] = {
        "work_id": work_id,
        "code": code,
        "label": f"Step {code}",
        "position": position,
        "state_code": ProgressState.PENDING,
    }
    values.update(overrides)
    return ProgressStep(**values)


def _violated_at_commit(session: DbSession) -> str:
    """Flush, check the deferred constraints as a commit does, and return the
    name of the one violated."""
    session.flush()
    with pytest.raises(IntegrityError) as raised:
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    return raised.value.orig.diag.constraint_name


class TestProgressStep:
    """The steps a Work's run lists (DB decision 69, assertions 283 to 288)."""

    @pytest.fixture
    def run(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
    ) -> uuid.UUID:
        return _job(
            session, project, environment, project_session, seq=2, kind_code="work"
        )

    def test_a_work_lists_its_steps_in_order_with_their_states_and_stamps(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        session.add_all(
            [
                _step(run, "docs", 3),
                _step(
                    run,
                    "P1.code",
                    1,
                    label="P1 · the v4 client",
                    state_code=ProgressState.DONE,
                    started_at=STARTED,
                    ended_at=ENDED,
                ),
                _step(run, "test", 2, state_code=ProgressState.ACTIVE, started_at=ENDED),
            ]
        )
        session.flush()
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        session.expire_all()

        steps = session.scalars(
            select(ProgressStep)
            .where(ProgressStep.work_id == run)
            .order_by(ProgressStep.position)
        ).all()

        assert [
            (step.code, step.label, step.state_code, step.started_at, step.ended_at)
            for step in steps
        ] == [
            ("P1.code", "P1 · the v4 client", ProgressState.DONE, STARTED, ENDED),
            ("test", "Step test", ProgressState.ACTIVE, ENDED, None),
            ("docs", "Step docs", ProgressState.PENDING, None, None),
        ]

    def test_its_code_is_unique_in_its_work(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        session.add(_step(run, "test", 1))
        session.flush()
        session.add(_step(run, "test", 2))

        assert violated_constraint(session) == "progress_steps_pkey"

    def test_two_works_may_list_one_code(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        project_session: Session,
        run: uuid.UUID,
    ) -> None:
        other = _job(
            session, project, environment, project_session, seq=3, kind_code="work"
        )
        session.add_all([_step(run, "test", 1), _step(other, "test", 1)])
        session.flush()
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

        assert session.get(ProgressStep, (other, "test")) is not None

    def test_its_position_is_unique_in_its_work(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        session.add_all([_step(run, "test", 1), _step(run, "docs", 1)])

        assert _violated_at_commit(session) == "uq_progress_steps_work_id_position"

    def test_a_whole_list_is_reordered_in_one_transaction(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        """The positions' uniqueness is checked at the commit, so a replace's
        updates may pass through a repeated position on the way."""
        first, second = _step(run, "test", 1), _step(run, "docs", 2)
        session.add_all([first, second])
        session.flush()
        first.position = 2
        session.flush()
        second.position = 1
        session.flush()
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        session.expire_all()

        assert session.scalars(
            select(ProgressStep.code)
            .where(ProgressStep.work_id == run)
            .order_by(ProgressStep.position)
        ).all() == ["docs", "test"]

    def test_its_position_starts_at_one(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        session.add(_step(run, "test", 0))

        assert violated_constraint(session) == "ck_progress_steps_position"

    def test_an_active_step_has_its_start(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        session.add(_step(run, "test", 1, state_code=ProgressState.ACTIVE))

        assert violated_constraint(session) == "ck_progress_steps_started"

    def test_a_done_step_has_its_start(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        session.add(
            _step(run, "test", 1, state_code=ProgressState.DONE, ended_at=ENDED)
        )

        assert violated_constraint(session) == "ck_progress_steps_started"

    def test_a_step_moved_back_to_pending_keeps_its_start(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        session.add(_step(run, "test", 1, started_at=STARTED))
        session.flush()
        session.expire_all()

        assert session.get_one(ProgressStep, (run, "test")).started_at == STARTED

    def test_a_done_step_has_its_end(self, session: DbSession, run: uuid.UUID) -> None:
        session.add(
            _step(run, "test", 1, state_code=ProgressState.DONE, started_at=STARTED)
        )

        assert violated_constraint(session) == "ck_progress_steps_ended"

    def test_only_a_done_step_has_an_end(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        session.add(
            _step(
                run,
                "test",
                1,
                state_code=ProgressState.ACTIVE,
                started_at=STARTED,
                ended_at=ENDED,
            )
        )

        assert violated_constraint(session) == "ck_progress_steps_ended"

    def test_it_is_a_works_step(self, session: DbSession) -> None:
        session.add(_step(uuid.uuid4(), "test", 1))

        assert violated_constraint(session) == "progress_steps_work_id_fkey"
