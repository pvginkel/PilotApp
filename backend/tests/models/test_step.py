"""Step Kind, Step Transcript and Step Timing: what a row must hold (DB §2.5
and §2.11; assertions 355 to 358, 562 to 565 and 572 to 574)."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.models import (
    ComponentVersion,
    Environment,
    Item,
    ProgressStep,
    Project,
    Session,
    StepKind,
    StepTiming,
    StepTranscript,
    Transcript,
    Work,
)
from app.models.reference import ProgressState, SessionState
from app.models.step import names_main_thread, repo_of_work
from tests.support import transcripts
from tests.support.database import violated_constraint
from tests.support.transcripts import CAMP, OTHER, SUB_AGENT

ENDED = datetime(2026, 11, 12, 14, 30, 12, tzinfo=UTC)
SEEDED = "001_deploy/run/sweep-1"
"""A key the plugin's seed gives a past run's step."""


def _a_run(
    db: DbSession,
    project: Project,
    creator: Session,
    seq: int,
    environment: Environment | None,
    repo: str | None = None,
) -> uuid.UUID:
    """A worker's run of `project`, placed in `repo` and running in
    `environment`; its id."""
    work_id = uuid.uuid4()
    db.add_all(
        [
            Item(
                id=work_id,
                project_id=project.id,
                seq=seq,
                kind_code="work",
                title="Fixing the client for v4",
                created_by_session_id=creator.id,
            ),
            Session(
                id=work_id,
                project_id=project.id,
                environment_id=environment.id if environment else None,
                kind_code="work",
                cwd="/work/Example",
                token_hash=uuid.uuid4().hex * 2,
                state_code=SessionState.STARTING,
            ),
        ]
    )
    db.flush()
    db.add(
        Work(
            id=work_id,
            project_id=project.id,
            session_kind_code="work",
            autopilot=False,
            repo=repo,
        )
    )
    db.flush()
    return work_id


def _a_step(db: DbSession, work_id: uuid.UUID, code: str, position: int = 1) -> None:
    db.add(
        ProgressStep(
            work_id=work_id,
            code=code,
            label=f"Step {code}",
            position=position,
            state_code=ProgressState.PENDING,
        )
    )
    db.flush()


def _timing(work_id: uuid.UUID, **overrides: Any) -> StepTiming:
    """A `code-writer` step's timing, written live under the code
    `P1.code-writer-1` unless `overrides` say otherwise."""
    values: dict[str, Any] = {
        "work_id": work_id,
        "kind_code": "code-writer",
        "ended_at": ENDED,
        "duration": 1_442,
        "code": "P1.code-writer-1",
    }
    values.update(overrides)
    return StepTiming(**values)


def _seeded(work_id: uuid.UUID, **overrides: Any) -> StepTiming:
    """A timing the seed published, under `SEEDED` in `pvginkel/Example`
    unless `overrides` say otherwise."""
    values: dict[str, Any] = {"code": None, "key": SEEDED, "repo": "pvginkel/Example"}
    values.update(overrides)
    return _timing(work_id, **values)


def _count(db: DbSession, entity: type) -> int:
    return db.scalar(select(func.count()).select_from(entity)) or 0


@pytest.fixture
def run(
    session: DbSession,
    project: Project,
    environment: Environment,
    project_session: Session,
) -> uuid.UUID:
    """A worker's run, placed in no repository."""
    return _a_run(session, project, project_session, 2, environment)


@pytest.fixture
def other_run(
    session: DbSession,
    project: Project,
    environment: Environment,
    project_session: Session,
) -> uuid.UUID:
    """A second run of the project."""
    return _a_run(session, project, project_session, 3, environment)


@pytest.fixture
def kind(session: DbSession) -> StepKind:
    """The kind the timings here are of."""
    return transcripts.reference(session, StepKind, "code-writer")


@pytest.fixture
def collector(session: DbSession) -> ComponentVersion:
    """The collector's version that reads the transcripts."""
    return transcripts.component_version(session)


class TestStepKind:
    def test_a_kind_is_held_once_under_its_code(
        self, session: DbSession, kind: StepKind
    ) -> None:
        session.expunge(kind)
        session.add(StepKind(code="code-writer", name="code-writer"))

        assert violated_constraint(session) == "step_kinds_pkey"


class TestStepTranscript:
    """A step's naming of the main threads that did its work (DB 355 to 358,
    574)."""

    def test_a_step_names_several_threads_and_a_thread_is_named_by_several_steps(
        self, session: DbSession, run: uuid.UUID, other_run: uuid.UUID
    ) -> None:
        """A test step names the test-agent's thread and the test-fixer's; a
        continuation's step names the thread its first run's step named."""
        _a_step(session, run, "Test")
        _a_step(session, other_run, "Test")
        session.add_all(
            [
                StepTranscript(work_id=run, code="Test", session_id=CAMP),
                StepTranscript(work_id=run, code="Test", session_id=OTHER),
                StepTranscript(work_id=other_run, code="Test", session_id=CAMP),
            ]
        )
        session.flush()

        assert session.execute(
            select(StepTranscript.work_id, StepTranscript.session_id).order_by(
                StepTranscript.session_id, StepTranscript.work_id
            )
        ).all() == sorted([(run, CAMP), (other_run, CAMP)]) + [(run, OTHER)]

    def test_a_step_names_a_thread_once(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        _a_step(session, run, "Test")
        session.add(StepTranscript(work_id=run, code="Test", session_id=CAMP))
        session.flush()
        session.expunge_all()
        session.add(StepTranscript(work_id=run, code="Test", session_id=CAMP))

        assert violated_constraint(session) == "step_transcripts_pkey"

    def test_it_is_a_steps_naming(self, session: DbSession, run: uuid.UUID) -> None:
        """DB 356: a step of the Work's list, not the Work alone."""
        session.add(StepTranscript(work_id=run, code="Test", session_id=CAMP))

        assert violated_constraint(session) == "step_transcripts_work_id_code_fkey"

    def test_it_goes_with_its_step(self, session: DbSession, run: uuid.UUID) -> None:
        """DB 288: a step its Work's list no longer holds takes its namings
        with it, another step's staying."""
        _a_step(session, run, "Test", 1)
        _a_step(session, run, "Docs", 2)
        session.add_all(
            [
                StepTranscript(work_id=run, code="Test", session_id=CAMP),
                StepTranscript(work_id=run, code="Docs", session_id=OTHER),
            ]
        )
        session.flush()

        session.delete(session.get_one(ProgressStep, (run, "Test")))
        session.flush()

        assert session.scalars(select(StepTranscript.code)).all() == ["Docs"]

    def _named(self, session: DbSession, run: uuid.UUID) -> list[uuid.UUID | None]:
        """The Transcript each of the run's namings finds, none where it
        finds none."""
        return list(
            session.scalars(
                select(Transcript.id)
                .select_from(StepTranscript)
                .outerjoin(Transcript, names_main_thread())
                .where(StepTranscript.work_id == run)
                .order_by(StepTranscript.session_id)
            )
        )

    def test_its_transcript_is_none_until_it_is_collected(
        self, session: DbSession, run: uuid.UUID, collector: ComponentVersion
    ) -> None:
        """A step is published as its round starts, before the collector's
        next walk (DB 358)."""
        _a_step(session, run, "Docs")
        session.add(StepTranscript(work_id=run, code="Docs", session_id=CAMP))
        session.flush()

        assert self._named(session, run) == [None]

        thread = transcripts.transcript(session, collector)

        assert self._named(session, run) == [thread.id]

    def test_its_transcript_is_the_main_thread_of_its_session_id(
        self, session: DbSession, run: uuid.UUID, collector: ComponentVersion
    ) -> None:
        """DB 574: of the threads of one session id, the one with no
        `agent_id`; another session's thread is another naming's."""
        _a_step(session, run, "Test")
        session.add_all(
            [
                StepTranscript(work_id=run, code="Test", session_id=CAMP),
                StepTranscript(work_id=run, code="Test", session_id=OTHER),
            ]
        )
        thread = transcripts.transcript(session, collector)
        transcripts.transcript(
            session, collector, agent_id=SUB_AGENT, main_id=thread.id
        )
        other = transcripts.transcript(session, collector, session_id=OTHER)

        assert self._named(session, run) == [thread.id, other.id]

    def test_a_sub_agents_thread_held_before_its_main_thread_is_not_it(
        self, session: DbSession, run: uuid.UUID, collector: ComponentVersion
    ) -> None:
        """A sub-agent's thread stands with no `main_id` until its main
        thread is published, and is no main thread for that."""
        _a_step(session, run, "Test")
        session.add(StepTranscript(work_id=run, code="Test", session_id=CAMP))
        sub_agent = transcripts.transcript(session, collector, agent_id=SUB_AGENT)
        assert sub_agent.main_id is None

        assert self._named(session, run) == [None]


class TestStepTiming:
    """A finished step, kept as the run published it (DB 562 to 565, 572,
    573)."""

    def test_one_written_live_holds_its_steps_code_and_what_the_run_gave(
        self, session: DbSession, run: uuid.UUID, kind: StepKind
    ) -> None:
        session.add(_timing(run, listed_ahead=True, marked=False))
        session.flush()
        session.expire_all()

        timing = session.scalars(select(StepTiming)).one()
        assert (
            timing.work_id,
            timing.kind_code,
            timing.ended_at,
            timing.duration,
            timing.listed_ahead,
            timing.marked,
            timing.code,
            timing.key,
            timing.repo,
        ) == (
            run,
            "code-writer",
            ENDED,
            1_442,
            True,
            False,
            "P1.code-writer-1",
            None,
            None,
        )

    def test_a_seeded_one_holds_its_key_and_its_repo_and_no_mark(
        self, session: DbSession, run: uuid.UUID, kind: StepKind
    ) -> None:
        """Its listing is unknown where the seed gives none."""
        session.add(_seeded(run))
        session.flush()
        session.expire_all()

        timing = session.scalars(select(StepTiming)).one()
        assert (
            timing.key,
            timing.repo,
            timing.code,
            timing.listed_ahead,
            timing.marked,
        ) == (SEEDED, "pvginkel/Example", None, None, None)

    def test_a_work_publishes_several(
        self, session: DbSession, run: uuid.UUID, kind: StepKind
    ) -> None:
        """Live and seeded on one Work, the seeded ones with no code each."""
        session.add_all(
            [
                _timing(run),
                _timing(run, code="P1.code-writer-2", listed_ahead=False, marked=True),
                _seeded(run),
                _seeded(run, key="001_deploy/run/P1.code-writer-1"),
            ]
        )
        session.flush()

        assert _count(session, StepTiming) == 4

    def test_it_has_a_code_or_a_key(
        self, session: DbSession, run: uuid.UUID, kind: StepKind
    ) -> None:
        session.add(_timing(run, code=None))

        assert violated_constraint(session) == "ck_step_timings_code_or_key"

    def test_it_never_has_both_a_code_and_a_key(
        self, session: DbSession, run: uuid.UUID, kind: StepKind
    ) -> None:
        session.add(_seeded(run, code="sweep-1"))

        assert violated_constraint(session) == "ck_step_timings_code_or_key"

    def test_a_step_of_a_work_is_timed_once(
        self, session: DbSession, run: uuid.UUID, kind: StepKind
    ) -> None:
        session.add_all([_timing(run), _timing(run, duration=2_890)])

        assert violated_constraint(session) == "uq_step_timings_work_id_code"

    def test_two_works_may_time_one_code(
        self,
        session: DbSession,
        run: uuid.UUID,
        other_run: uuid.UUID,
        kind: StepKind,
    ) -> None:
        session.add_all([_timing(run), _timing(other_run)])
        session.flush()

        assert _count(session, StepTiming) == 2

    def test_a_key_is_held_once_in_its_repo_whichever_work_seeded_it(
        self,
        session: DbSession,
        run: uuid.UUID,
        other_run: uuid.UUID,
        kind: StepKind,
    ) -> None:
        session.add_all([_seeded(run), _seeded(other_run)])

        assert violated_constraint(session) == "uq_step_timings_repo_key"

    def test_two_repos_may_hold_one_key(
        self, session: DbSession, run: uuid.UUID, kind: StepKind
    ) -> None:
        session.add_all([_seeded(run), _seeded(run, repo="pvginkel/Other")])
        session.flush()

        assert _count(session, StepTiming) == 2

    def test_a_seeded_one_has_a_repo(
        self, session: DbSession, run: uuid.UUID, kind: StepKind
    ) -> None:
        session.add(_seeded(run, repo=None))

        assert violated_constraint(session) == "ck_step_timings_seeded_repo"

    def test_a_seeded_one_has_no_mark(
        self, session: DbSession, run: uuid.UUID, kind: StepKind
    ) -> None:
        session.add(_seeded(run, marked=False))

        assert violated_constraint(session) == "ck_step_timings_seeded_marked"

    def test_its_duration_is_never_negative(
        self, session: DbSession, run: uuid.UUID, kind: StepKind
    ) -> None:
        session.add(_timing(run, duration=-1))

        assert violated_constraint(session) == "ck_step_timings_duration"

    def test_its_kind_is_a_step_kind(self, session: DbSession, run: uuid.UUID) -> None:
        session.add(_timing(run))

        assert violated_constraint(session) == "step_timings_kind_code_fkey"

    def test_it_is_a_works_timing(self, session: DbSession, kind: StepKind) -> None:
        session.add(_timing(uuid.uuid4()))

        assert violated_constraint(session) == "step_timings_work_id_fkey"

    def test_it_stays_when_its_step_is_deleted(
        self, session: DbSession, run: uuid.UUID, kind: StepKind
    ) -> None:
        """DB 573."""
        _a_step(session, run, "P1.code-writer-1")
        session.add(_timing(run))
        session.flush()

        session.delete(session.get_one(ProgressStep, (run, "P1.code-writer-1")))
        session.flush()

        assert session.scalars(select(StepTiming.code)).all() == ["P1.code-writer-1"]


class TestRepoOfWork:
    """The repo a Work's timings are written with (DB 572)."""

    @pytest.fixture
    def own(self, session: DbSession) -> Environment:
        """An environment Pilot created from a repository."""
        created = Environment(
            id="pvginkel-other-1a2b3c",
            name="Other-1",
            exempt=False,
            server_created_at=ENDED,
            repo="pvginkel/Other",
        )
        session.add(created)
        session.flush()
        return created

    def test_it_is_the_works_repo_label(
        self,
        session: DbSession,
        project: Project,
        project_session: Session,
        own: Environment,
    ) -> None:
        """The label, whatever its environment was created from."""
        work_id = _a_run(
            session, project, project_session, 2, own, repo="pvginkel/Example"
        )

        assert session.scalar(repo_of_work(work_id)) == "pvginkel/Example"

    def test_a_work_with_no_label_has_its_environments(
        self,
        session: DbSession,
        project: Project,
        project_session: Session,
        own: Environment,
    ) -> None:
        work_id = _a_run(session, project, project_session, 2, own)

        assert session.scalar(repo_of_work(work_id)) == "pvginkel/Other"

    def test_a_labelled_work_in_no_environment_keeps_its_label(
        self, session: DbSession, project: Project, project_session: Session
    ) -> None:
        work_id = _a_run(
            session, project, project_session, 2, None, repo="pvginkel/Example"
        )

        assert session.scalar(repo_of_work(work_id)) == "pvginkel/Example"

    def test_one_with_neither_has_none(
        self, session: DbSession, run: uuid.UUID
    ) -> None:
        """No label, and an environment Pilot did not create."""
        assert session.scalar(repo_of_work(run)) is None

    def test_one_with_no_label_in_no_environment_has_none(
        self, session: DbSession, project: Project, project_session: Session
    ) -> None:
        work_id = _a_run(session, project, project_session, 2, None)

        assert session.scalar(repo_of_work(work_id)) is None
