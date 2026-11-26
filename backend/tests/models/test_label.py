"""Work Unit, Work Unit Measure, Segment, Rule Breach, Test Suite, Test, Test
Run, Test Failure, CI Build and CI Wait: what a row of the labels must hold
(DB §2.8, §2.9; the assertions of §4.31)."""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.models import (
    BuildResult,
    Call,
    CIBuild,
    CIWait,
    ComponentVersion,
    ReworkKind,
    Rule,
    RuleBreach,
    Segment,
    SegmentKind,
    Test,
    TestFailure,
    TestRun,
    TestSuite,
    ToolCall,
    Transcript,
    UnitMeasure,
    UnitOutcome,
    WorkUnit,
    WorkUnitMeasure,
)
from tests.support import labels, transcripts
from tests.support.database import violated_constraint
from tests.support.labels import COURSE, DISH, MENU
from tests.support.transcripts import OTHER, STARTED

AUTUMN = "RecipeBox/autumn_menu"
"""The key of an invented menu."""


@pytest.fixture
def collector(session: DbSession) -> ComponentVersion:
    """The collector's version that reads the transcripts."""
    return transcripts.component_version(session)


@pytest.fixture
def thread(session: DbSession, collector: ComponentVersion) -> Transcript:
    """A main thread."""
    return transcripts.transcript(session, collector)


@pytest.fixture
def request_(session: DbSession, thread: Transcript) -> Call:
    """The main thread's first Call."""
    return transcripts.call(session, thread, 1)


@pytest.fixture
def run_command(session: DbSession, request_: Call) -> ToolCall:
    """A command the first Call ran."""
    return transcripts.tool_call(session, request_)


@pytest.fixture
def menu(session: DbSession) -> WorkUnit:
    """A menu, the top of the kitchen's units."""
    return labels.work_unit(session, AUTUMN)


@pytest.fixture
def backend(session: DbSession) -> TestSuite:
    return labels.suite(session)


def _count(db: DbSession, entity: type) -> int:
    return db.scalar(select(func.count()).select_from(entity)) or 0


def _run(transcript: Transcript, suite: TestSuite, **runner: int) -> TestRun:
    """A green Test Run of the suite the Transcript's labels carry, by the
    one runner given."""
    return TestRun(
        transcript_id=transcript.id, suite_id=suite.id, passed=True, tests=412, **runner
    )


class TestWorkUnit:
    def test_a_unit_holds_what_the_labeller_gave(
        self, session: DbSession, menu: WorkUnit
    ) -> None:
        labels.declared(session, UnitOutcome, "served")
        labels.declared(session, ReworkKind, "recooked")
        course = labels.work_unit(session, f"{AUTUMN}|starter", COURSE, menu)
        first = labels.work_unit(
            session, f"{AUTUMN}|starter|soup|1", DISH, course, role="soup", round=1
        )
        again = labels.work_unit(
            session,
            f"{AUTUMN}|starter|soup|2",
            DISH,
            course,
            occasioned_by_id=first.id,
            rework_kind_code="recooked",
            title="Soup, again",
            variant="cold",
            role="soup",
            round=2,
            outcome_code="served",
            ended_at=STARTED + timedelta(hours=1),
            card="RB-12",
        )
        session.expunge_all()

        held = session.get(WorkUnit, again.id)
        assert held is not None
        assert (
            held.kind_code,
            held.part_of_id,
            held.part_of_kind_code,
            held.occasioned_by_id,
            held.rework_kind_code,
            held.title,
            held.variant,
            held.role,
            held.round,
            held.outcome_code,
            held.ended_at,
            held.card,
        ) == (
            DISH,
            course.id,
            COURSE,
            first.id,
            "recooked",
            "Soup, again",
            "cold",
            "soup",
            2,
            "served",
            STARTED + timedelta(hours=1),
            "RB-12",
        )

    def test_a_top_unit_sits_in_none(self, menu: WorkUnit) -> None:
        assert (menu.part_of_id, menu.part_of_kind_code) == (None, None)

    def test_its_key_is_unique(self, session: DbSession, menu: WorkUnit) -> None:
        session.add(WorkUnit(key=AUTUMN, kind_code=MENU, title="Again"))

        assert violated_constraint(session) == "work_units_key_key"

    def test_it_is_classified_by_a_work_unit_kind(self, session: DbSession) -> None:
        session.add(WorkUnit(key=AUTUMN, kind_code="banquet", title="Autumn"))

        assert violated_constraint(session) == "work_units_kind_code_fkey"

    def test_it_sits_only_where_a_nesting_pairs_its_kind_with_the_others(
        self, session: DbSession, menu: WorkUnit
    ) -> None:
        """DB 551: a dish sits in a course, never in a menu."""
        session.add(
            WorkUnit(
                key=f"{AUTUMN}|soup",
                kind_code=DISH,
                title="Soup",
                part_of_id=menu.id,
                part_of_kind_code=MENU,
            )
        )

        assert (
            violated_constraint(session)
            == "work_units_kind_code_part_of_kind_code_fkey"
        )

    def test_the_kind_it_names_with_the_unit_it_sits_in_is_that_units(
        self, session: DbSession, menu: WorkUnit
    ) -> None:
        session.add(
            WorkUnit(
                key=f"{AUTUMN}|soup",
                kind_code=DISH,
                title="Soup",
                part_of_id=menu.id,
                part_of_kind_code=COURSE,
            )
        )

        assert (
            violated_constraint(session)
            == "work_units_part_of_id_part_of_kind_code_fkey"
        )

    def test_it_names_the_kind_of_the_unit_it_sits_in(
        self, session: DbSession, menu: WorkUnit
    ) -> None:
        session.add(
            WorkUnit(
                key=f"{AUTUMN}|starter", kind_code=COURSE, title="S", part_of_id=menu.id
            )
        )

        assert violated_constraint(session) == "ck_work_units_part_of"

    def test_it_is_not_part_of_itself(self, session: DbSession, menu: WorkUnit) -> None:
        """DB 552."""
        menu.part_of_id, menu.part_of_kind_code = menu.id, MENU

        assert violated_constraint(session) == "ck_work_units_not_itself"

    def test_it_is_not_occasioned_by_itself(
        self, session: DbSession, menu: WorkUnit
    ) -> None:
        """DB 552."""
        menu.occasioned_by_id = menu.id

        assert violated_constraint(session) == "ck_work_units_not_itself"

    def test_its_round_is_from_one(self, session: DbSession) -> None:
        labels.kinds(session)
        session.add(WorkUnit(key=AUTUMN, kind_code=MENU, title="Autumn", round=0))

        assert violated_constraint(session) == "ck_work_units_round"

    @pytest.mark.parametrize(
        ("column", "constraint"),
        [
            ("outcome_code", "work_units_outcome_code_fkey"),
            ("rework_kind_code", "work_units_rework_kind_code_fkey"),
        ],
    )
    def test_what_classifies_it_is_a_declared_value(
        self, session: DbSession, column: str, constraint: str
    ) -> None:
        labels.kinds(session)
        session.add(
            WorkUnit(key=AUTUMN, kind_code=MENU, title="Autumn", **{column: "other"})
        )

        assert violated_constraint(session) == constraint


class TestWorkUnitMeasure:
    def test_a_unit_is_sized_by_its_measures(
        self, session: DbSession, menu: WorkUnit
    ) -> None:
        labels.declared(session, UnitMeasure, "planned_dishes", unit="dishes")
        labels.declared(session, UnitMeasure, "tastings", unit="tastings")
        session.add_all(
            [
                WorkUnitMeasure(
                    work_unit_id=menu.id, measure_code="planned_dishes", amount=9
                ),
                WorkUnitMeasure(
                    work_unit_id=menu.id, measure_code="tastings", amount=0
                ),
            ]
        )
        session.flush()

        held = session.execute(
            select(WorkUnitMeasure.measure_code, WorkUnitMeasure.amount)
            .where(WorkUnitMeasure.work_unit_id == menu.id)
            .order_by(WorkUnitMeasure.measure_code)
        ).all()
        assert held == [("planned_dishes", Decimal(9)), ("tastings", Decimal(0))]

    def test_a_unit_has_one_figure_of_a_measure(
        self, session: DbSession, menu: WorkUnit
    ) -> None:
        labels.declared(session, UnitMeasure, "tastings", unit="tastings")
        session.add(
            WorkUnitMeasure(work_unit_id=menu.id, measure_code="tastings", amount=2)
        )
        session.flush()
        session.add(
            WorkUnitMeasure(work_unit_id=menu.id, measure_code="tastings", amount=3)
        )

        assert violated_constraint(session) == "work_unit_measures_pkey"

    def test_it_is_classified_by_a_unit_measure(
        self, session: DbSession, menu: WorkUnit
    ) -> None:
        session.add(
            WorkUnitMeasure(work_unit_id=menu.id, measure_code="other", amount=1)
        )

        assert violated_constraint(session) == "work_unit_measures_measure_code_fkey"

    def test_it_sizes_a_work_unit(self, session: DbSession) -> None:
        labels.declared(session, UnitMeasure, "tastings", unit="tastings")
        session.add(
            WorkUnitMeasure(work_unit_id=404, measure_code="tastings", amount=1)
        )

        assert violated_constraint(session) == "work_unit_measures_work_unit_id_fkey"


class TestSegment:
    def test_a_transcript_is_divided_into_its_segments(
        self, session: DbSession, thread: Transcript
    ) -> None:
        for kind in ("prep", "cook"):
            labels.declared(session, SegmentKind, kind)
        session.add_all(
            [
                Segment(transcript_id=thread.id, position=place, kind_code=kind)
                for place, kind in enumerate(("prep", "cook", "prep"), start=1)
            ]
        )
        session.flush()

        held = session.execute(
            select(Segment.position, Segment.kind_code)
            .where(Segment.transcript_id == thread.id)
            .order_by(Segment.position)
        ).all()
        assert held == [(1, "prep"), (2, "cook"), (3, "prep")]

    def test_its_position_is_unique_in_its_transcript(
        self, session: DbSession, thread: Transcript
    ) -> None:
        labels.declared(session, SegmentKind, "prep")
        session.add(Segment(transcript_id=thread.id, position=1, kind_code="prep"))
        session.flush()
        session.add(Segment(transcript_id=thread.id, position=1, kind_code="prep"))

        assert violated_constraint(session) == "segments_transcript_id_position_key"

    def test_another_transcript_holds_the_same_position(
        self, session: DbSession, thread: Transcript, collector: ComponentVersion
    ) -> None:
        other = transcripts.transcript(session, collector, session_id=OTHER)
        labels.declared(session, SegmentKind, "prep")
        session.add_all(
            [
                Segment(transcript_id=held.id, position=1, kind_code="prep")
                for held in (thread, other)
            ]
        )
        session.flush()

        assert _count(session, Segment) == 2

    def test_its_position_is_from_one(
        self, session: DbSession, thread: Transcript
    ) -> None:
        labels.declared(session, SegmentKind, "prep")
        session.add(Segment(transcript_id=thread.id, position=0, kind_code="prep"))

        assert violated_constraint(session) == "ck_segments_position"

    def test_it_is_classified_by_a_segment_kind(
        self, session: DbSession, thread: Transcript
    ) -> None:
        session.add(Segment(transcript_id=thread.id, position=1, kind_code="other"))

        assert violated_constraint(session) == "segments_kind_code_fkey"

    def test_it_divides_a_transcript(self, session: DbSession) -> None:
        labels.declared(session, SegmentKind, "prep")
        session.add(
            Segment(
                transcript_id=uuid.UUID("00000000-0000-4000-8000-000000000404"),
                position=1,
                kind_code="prep",
            )
        )

        assert violated_constraint(session) == "segments_transcript_id_fkey"


class TestRuleBreach:
    def test_a_tool_call_commits_its_breaches(
        self, session: DbSession, run_command: ToolCall
    ) -> None:
        for rule in ("no_tasting_from_the_pot", "no_open_flame"):
            labels.declared(session, Rule, rule, home="/kitchen/RULES.md")
            session.add(RuleBreach(tool_call_id=run_command.id, rule_code=rule))
        session.flush()

        assert _count(session, RuleBreach) == 2

    def test_it_breaches_a_rule(
        self, session: DbSession, run_command: ToolCall
    ) -> None:
        session.add(RuleBreach(tool_call_id=run_command.id, rule_code="other"))

        assert violated_constraint(session) == "rule_breaches_rule_code_fkey"

    def test_it_goes_with_its_tool_call(
        self, session: DbSession, run_command: ToolCall
    ) -> None:
        labels.declared(session, Rule, "no_open_flame", home="/kitchen/RULES.md")
        session.add(RuleBreach(tool_call_id=run_command.id, rule_code="no_open_flame"))
        session.flush()
        session.expunge_all()

        session.execute(
            ToolCall.__table__.delete().where(ToolCall.id == run_command.id)
        )

        assert _count(session, RuleBreach) == 0


class TestTestSuite:
    def test_its_code_is_unique(self, session: DbSession, backend: TestSuite) -> None:
        session.add(TestSuite(code=backend.code, name="Again"))

        assert violated_constraint(session) == "test_suites_code_key"


class TestTest:
    def test_its_name_is_unique_in_its_suite(
        self, session: DbSession, backend: TestSuite
    ) -> None:
        session.add(Test(suite_id=backend.id, name="tests/test_oven.py::test_heats"))
        session.flush()
        session.add(Test(suite_id=backend.id, name="tests/test_oven.py::test_heats"))

        assert violated_constraint(session) == "tests_suite_id_name_key"

    def test_another_suite_names_the_same_test(
        self, session: DbSession, backend: TestSuite
    ) -> None:
        other = labels.suite(session, "RecipeBox/collector/test")
        session.add_all(
            [Test(suite_id=held.id, name="test_heats") for held in (backend, other)]
        )
        session.flush()

        assert _count(session, Test) == 2

    def test_it_is_named_by_a_suite(self, session: DbSession) -> None:
        session.add(Test(suite_id=404, name="test_heats"))

        assert violated_constraint(session) == "tests_suite_id_fkey"


class TestTestRun:
    def test_a_tool_call_runs_one_per_suite(
        self,
        session: DbSession,
        thread: Transcript,
        run_command: ToolCall,
        backend: TestSuite,
    ) -> None:
        frontend = labels.suite(session, "RecipeBox/frontend/test")
        session.add_all(
            [
                _run(thread, backend, tool_call_id=run_command.id),
                TestRun(
                    transcript_id=thread.id,
                    tool_call_id=run_command.id,
                    suite_id=frontend.id,
                    started_at=STARTED,
                    ended_at=STARTED + timedelta(minutes=4),
                    passed=False,
                    tests=96,
                    retries_allowed=2,
                ),
            ]
        )
        session.flush()

        runs = session.execute(
            select(
                TestRun.suite_id, TestRun.passed, TestRun.tests, TestRun.retries_allowed
            )
            .where(TestRun.tool_call_id == run_command.id)
            .order_by(TestRun.id)
        ).all()
        assert runs == [(backend.id, True, 412, None), (frontend.id, False, 96, 2)]

    def test_a_work_unit_runs_one_its_stages_transcript_carries(
        self,
        session: DbSession,
        thread: Transcript,
        menu: WorkUnit,
        backend: TestSuite,
    ) -> None:
        session.add(_run(thread, backend, work_unit_id=menu.id))
        session.flush()

        assert _count(session, TestRun) == 1

    def test_a_ci_build_runs_one(
        self, session: DbSession, thread: Transcript, backend: TestSuite
    ) -> None:
        build = labels.ci_build(session)
        session.add(_run(thread, backend, ci_build_id=build.id))
        session.flush()

        assert _count(session, TestRun) == 1

    def test_it_is_run_by_one_of_its_three_runners(
        self, session: DbSession, thread: Transcript, backend: TestSuite
    ) -> None:
        """DB 533."""
        session.add(_run(thread, backend))

        assert violated_constraint(session) == "ck_test_runs_runner"

    def test_it_is_run_by_no_more_than_one(
        self,
        session: DbSession,
        thread: Transcript,
        run_command: ToolCall,
        menu: WorkUnit,
        backend: TestSuite,
    ) -> None:
        """DB 533."""
        session.add(
            _run(thread, backend, tool_call_id=run_command.id, work_unit_id=menu.id)
        )

        assert violated_constraint(session) == "ck_test_runs_runner"

    def test_a_tool_calls_run_carries_its_tool_calls_transcript(
        self,
        session: DbSession,
        collector: ComponentVersion,
        run_command: ToolCall,
        backend: TestSuite,
    ) -> None:
        other = transcripts.transcript(session, collector, session_id=OTHER)
        session.add(_run(other, backend, tool_call_id=run_command.id))

        assert (
            violated_constraint(session) == "test_runs_transcript_id_tool_call_id_fkey"
        )

    @pytest.mark.parametrize(
        ("runner", "constraint"),
        [
            ("work_unit_id", "test_runs_work_unit_id_fkey"),
            ("ci_build_id", "test_runs_ci_build_id_fkey"),
        ],
    )
    def test_its_runner_is_held(
        self,
        session: DbSession,
        thread: Transcript,
        backend: TestSuite,
        runner: str,
        constraint: str,
    ) -> None:
        session.add(_run(thread, backend, **{runner: 404}))

        assert violated_constraint(session) == constraint

    def test_it_runs_a_suite(
        self, session: DbSession, thread: Transcript, run_command: ToolCall
    ) -> None:
        session.add(
            TestRun(
                transcript_id=thread.id,
                tool_call_id=run_command.id,
                suite_id=404,
                passed=True,
                tests=1,
            )
        )

        assert violated_constraint(session) == "test_runs_suite_id_fkey"

    @pytest.mark.parametrize("counts", [{"tests": -1}, {"retries_allowed": -1}])
    def test_its_counts_are_never_negative(
        self,
        session: DbSession,
        thread: Transcript,
        run_command: ToolCall,
        backend: TestSuite,
        counts: dict[str, int],
    ) -> None:
        run = _run(thread, backend, tool_call_id=run_command.id)
        for count, given in counts.items():
            setattr(run, count, given)
        session.add(run)

        assert violated_constraint(session) == "ck_test_runs_counts"

    def test_it_goes_with_its_tool_call_and_its_failures_with_it(
        self,
        session: DbSession,
        thread: Transcript,
        run_command: ToolCall,
        backend: TestSuite,
    ) -> None:
        run = _run(thread, backend, tool_call_id=run_command.id)
        oven = Test(suite_id=backend.id, name="test_heats")
        session.add_all([run, oven])
        session.flush()
        session.add(
            TestFailure(
                test_run_id=run.id,
                test_id=oven.id,
                suite_id=backend.id,
                attempts=1,
                flaky=False,
            )
        )
        session.flush()
        session.expunge_all()

        session.execute(
            ToolCall.__table__.delete().where(ToolCall.id == run_command.id)
        )

        assert (_count(session, TestRun), _count(session, TestFailure)) == (0, 0)


class TestTestFailure:
    @pytest.fixture
    def run(
        self,
        session: DbSession,
        thread: Transcript,
        run_command: ToolCall,
        backend: TestSuite,
    ) -> TestRun:
        """A red run of the backend's suite."""
        run = _run(thread, backend, tool_call_id=run_command.id)
        run.passed = False
        session.add(run)
        session.flush()
        return run

    def _test(self, session: DbSession, suite: TestSuite, name: str) -> Test:
        test = Test(suite_id=suite.id, name=name)
        session.add(test)
        session.flush()
        return test

    def test_a_run_records_its_failures_a_flake_among_them(
        self, session: DbSession, run: TestRun, backend: TestSuite
    ) -> None:
        heats = self._test(session, backend, "test_heats")
        cools = self._test(session, backend, "test_cools")
        session.add_all(
            [
                TestFailure(
                    test_run_id=run.id,
                    test_id=heats.id,
                    suite_id=backend.id,
                    attempts=3,
                    flaky=False,
                ),
                TestFailure(
                    test_run_id=run.id,
                    test_id=cools.id,
                    suite_id=backend.id,
                    attempts=2,
                    flaky=True,
                ),
            ]
        )
        session.flush()

        failures = session.execute(
            select(Test.name, TestFailure.attempts, TestFailure.flaky)
            .join(Test, Test.id == TestFailure.test_id)
            .where(TestFailure.test_run_id == run.id)
            .order_by(Test.name)
        ).all()
        assert failures == [("test_cools", 2, True), ("test_heats", 3, False)]

    def test_a_test_fails_once_in_a_run(
        self, session: DbSession, run: TestRun, backend: TestSuite
    ) -> None:
        heats = self._test(session, backend, "test_heats")
        for _ in range(2):
            session.add(
                TestFailure(
                    test_run_id=run.id,
                    test_id=heats.id,
                    suite_id=backend.id,
                    attempts=1,
                    flaky=False,
                )
            )

        assert violated_constraint(session) == "test_failures_pkey"

    def test_its_test_is_named_by_its_runs_suite(
        self, session: DbSession, run: TestRun, backend: TestSuite
    ) -> None:
        """DB 556."""
        other = labels.suite(session, "RecipeBox/frontend/test")
        stranger = self._test(session, other, "test_heats")
        session.add(
            TestFailure(
                test_run_id=run.id,
                test_id=stranger.id,
                suite_id=backend.id,
                attempts=1,
                flaky=False,
            )
        )

        assert violated_constraint(session) == "test_failures_test_id_suite_id_fkey"

    def test_the_suite_it_carries_is_its_runs(
        self, session: DbSession, run: TestRun
    ) -> None:
        """DB 556."""
        other = labels.suite(session, "RecipeBox/frontend/test")
        stranger = self._test(session, other, "test_heats")
        session.add(
            TestFailure(
                test_run_id=run.id,
                test_id=stranger.id,
                suite_id=other.id,
                attempts=1,
                flaky=False,
            )
        )

        assert violated_constraint(session) == "test_failures_test_run_id_suite_id_fkey"

    def test_its_attempts_are_from_one(
        self, session: DbSession, run: TestRun, backend: TestSuite
    ) -> None:
        heats = self._test(session, backend, "test_heats")
        session.add(
            TestFailure(
                test_run_id=run.id,
                test_id=heats.id,
                suite_id=backend.id,
                attempts=0,
                flaky=False,
            )
        )

        assert violated_constraint(session) == "ck_test_failures_attempts"


class TestCIBuild:
    def test_a_build_holds_what_its_wait_gave(self, session: DbSession) -> None:
        labels.declared(session, BuildResult, "DONE")
        build = labels.ci_build(
            session,
            commit_sha="4e1f0c2",
            queued_at=STARTED,
            started_at=STARTED + timedelta(seconds=20),
            ended_at=STARTED + timedelta(minutes=9),
            result_code="DONE",
            deployed_at=STARTED + timedelta(minutes=12),
        )
        session.expunge_all()

        held = session.get(CIBuild, build.id)
        assert held is not None
        assert (
            held.job,
            held.number,
            held.commit_sha,
            held.result_code,
            held.deployed_at,
        ) == (
            "RecipeBox/Build-Main",
            812,
            "4e1f0c2",
            "DONE",
            STARTED + timedelta(minutes=12),
        )

    def test_one_whose_wait_named_no_commit_holds_none(
        self, session: DbSession
    ) -> None:
        build = labels.ci_build(session)

        assert (build.commit_sha, build.result_code, build.deployed_at) == (
            None,
            None,
            None,
        )

    def test_its_number_is_unique_in_its_job(self, session: DbSession) -> None:
        labels.ci_build(session)
        session.add(CIBuild(job="RecipeBox/Build-Main", number=812))

        assert violated_constraint(session) == "ci_builds_job_number_key"

    def test_another_job_holds_the_same_number(self, session: DbSession) -> None:
        labels.ci_build(session)
        labels.ci_build(session, "RecipeBox/Deploy")

        assert _count(session, CIBuild) == 2

    def test_its_number_is_from_one(self, session: DbSession) -> None:
        session.add(CIBuild(job="RecipeBox/Build-Main", number=0))

        assert violated_constraint(session) == "ck_ci_builds_number"

    def test_it_is_classified_by_a_build_result(self, session: DbSession) -> None:
        session.add(CIBuild(job="RecipeBox/Build-Main", number=1, result_code="other"))

        assert violated_constraint(session) == "ci_builds_result_code_fkey"


class TestCIWait:
    def test_a_wait_on_a_build_follows_the_pipeline_it_triggered(
        self, session: DbSession, run_command: ToolCall
    ) -> None:
        build = labels.ci_build(session)
        deploy = labels.ci_build(session, "RecipeBox/Deploy", 812)
        session.add_all(
            [
                CIWait(tool_call_id=run_command.id, ci_build_id=held.id)
                for held in (build, deploy)
            ]
        )
        session.flush()

        assert _count(session, CIWait) == 2

    def test_it_waits_on_a_build(
        self, session: DbSession, run_command: ToolCall
    ) -> None:
        session.add(CIWait(tool_call_id=run_command.id, ci_build_id=404))

        assert violated_constraint(session) == "ci_waits_ci_build_id_fkey"

    def test_it_goes_with_its_tool_call_and_its_build_stays(
        self, session: DbSession, run_command: ToolCall
    ) -> None:
        build = labels.ci_build(session)
        session.add(CIWait(tool_call_id=run_command.id, ci_build_id=build.id))
        session.flush()
        session.expunge_all()

        session.execute(
            ToolCall.__table__.delete().where(ToolCall.id == run_command.id)
        )

        assert (_count(session, CIWait), _count(session, CIBuild)) == (0, 1)
