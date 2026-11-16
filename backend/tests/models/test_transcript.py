"""Transcript, Launch, Launch Component, Prompt, Hook Run and Compaction, with
Repository and Component Version: what a row must hold (DB §2.6; the
assertions of §4.31 and §4.33)."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import (
    Compaction,
    CompactionTrigger,
    Component,
    ComponentVersion,
    Environment,
    HookRun,
    Launch,
    LaunchComponent,
    Project,
    Prompt,
    PromptSource,
    Repository,
    Transcript,
)
from app.models.reference import SessionState
from tests.support import transcripts
from tests.support.database import violated_constraint
from tests.support.transcripts import CAMP, OTHER, STARTED, SUB_AGENT
from tests.support.turns import turn_at


@pytest.fixture
def collector(session: DbSession) -> ComponentVersion:
    """The collector's version that reads the transcripts."""
    return transcripts.component_version(session)


@pytest.fixture
def thread(session: DbSession, collector: ComponentVersion) -> Transcript:
    """A main thread."""
    return transcripts.transcript(session, collector)


@pytest.fixture
def start(session: DbSession, thread: Transcript) -> Launch:
    """The main thread's first Launch."""
    return transcripts.launch(session, thread)


def _count(db: DbSession, entity: type) -> int:
    return db.scalar(select(func.count()).select_from(entity)) or 0


def _thread(collector: ComponentVersion, **overrides: Any) -> Transcript:
    """A thread of the main thread's session, not yet added."""
    values: dict[str, Any] = {
        "session_id": CAMP,
        "working_directory": "/work/RecipeBox",
        "file_size": 1,
        "file_modified_at": STARTED,
        "collected_at": STARTED,
        "replayed_size": 1,
        "read_under_id": collector.id,
    }
    values.update(overrides)
    return Transcript(**values)


class TestRepository:
    def test_its_name_is_unique(self, session: DbSession) -> None:
        session.add_all([Repository(name="RecipeBox"), Repository(name="RecipeBox")])

        assert violated_constraint(session) == "repositories_name_key"


class TestComponentVersion:
    def test_a_component_has_its_versions(self, session: DbSession) -> None:
        first = transcripts.component_version(session, "plugin:garden", "0.4.1")
        second = transcripts.component_version(session, "plugin:garden", "0.4.2")

        assert first.id != second.id
        assert first.released_at is None

    def test_a_version_is_unique_in_its_component(
        self, session: DbSession, collector: ComponentVersion
    ) -> None:
        session.add(ComponentVersion(component_code="collector", version="1.0.0"))

        assert (
            violated_constraint(session)
            == "component_versions_component_code_version_key"
        )

    def test_it_is_a_version_of_a_component(self, session: DbSession) -> None:
        session.add(ComponentVersion(component_code="other", version="1.0.0"))

        assert violated_constraint(session) == "component_versions_component_code_fkey"


class TestTranscript:
    def test_a_main_thread_holds_what_its_publication_gave(
        self,
        session: DbSession,
        collector: ComponentVersion,
        environment: Environment,
    ) -> None:
        repository = Repository(name="RecipeBox")
        session.add(repository)
        session.flush()
        thread = transcripts.transcript(
            session,
            collector,
            environment_id=environment.id,
            repository_id=repository.id,
        )
        session.expire(thread)

        assert thread.id is not None
        assert (thread.session_id, thread.agent_id) == (CAMP, None)
        assert (thread.main_id, thread.spawned_by_id) == (None, None)
        assert thread.working_directory == "/work/RecipeBox"
        assert thread.environment_id == environment.id
        assert thread.repository_id == repository.id
        assert thread.file_size == thread.replayed_size == 48_112
        assert thread.file_modified_at == STARTED + timedelta(minutes=12)
        assert thread.collected_at == STARTED + timedelta(minutes=13)
        assert thread.read_under_id == collector.id

    def test_one_under_no_environment_and_no_repository_is_held(
        self, session: DbSession, thread: Transcript
    ) -> None:
        session.expire(thread)

        assert (thread.environment_id, thread.repository_id) == (None, None)

    def test_a_file_passes_what_an_int_holds(
        self, session: DbSession, collector: ComponentVersion
    ) -> None:
        thread = transcripts.transcript(
            session, collector, file_size=2**40, replayed_size=2**40
        )
        session.expire(thread)

        assert thread.file_size == 2**40

    def test_a_session_id_names_one_main_thread(
        self, session: DbSession, collector: ComponentVersion, thread: Transcript
    ) -> None:
        session.add(_thread(collector, working_directory="/work/BikeLog"))

        assert violated_constraint(session) == "uq_transcripts_session_id_agent_id"

    def test_another_session_id_names_another_main_thread(
        self, session: DbSession, collector: ComponentVersion, thread: Transcript
    ) -> None:
        other = transcripts.transcript(session, collector, session_id=OTHER)

        assert other.id != thread.id

    def test_an_agent_id_names_one_thread_of_its_session(
        self, session: DbSession, collector: ComponentVersion, thread: Transcript
    ) -> None:
        transcripts.transcript(session, collector, agent_id=SUB_AGENT)
        session.add(_thread(collector, agent_id=SUB_AGENT))

        assert violated_constraint(session) == "uq_transcripts_session_id_agent_id"

    def test_a_session_has_a_thread_per_sub_agent(
        self, session: DbSession, collector: ComponentVersion, thread: Transcript
    ) -> None:
        session.add_all(
            _thread(collector, agent_id=agent, main_id=thread.id)
            for agent in (SUB_AGENT, "c81d5f20a36b9e741")
        )
        session.flush()

        assert _count(session, Transcript) == 3

    def test_a_sub_agents_thread_is_held_before_its_main_thread_and_joined_to_it(
        self, session: DbSession, collector: ComponentVersion
    ) -> None:
        """Whichever a collector publishes first (DB 534, once both are
        held)."""
        sub_agent = transcripts.transcript(
            session,
            collector,
            agent_id=SUB_AGENT,
            agent_type="Explore",
            description="Find where the units are converted.",
        )
        assert sub_agent.main_id is None

        thread = transcripts.transcript(session, collector)
        sub_agent.main_id = thread.id
        session.flush()
        session.expire(sub_agent)

        assert sub_agent.main_id == thread.id
        assert sub_agent.agent_type == "Explore"
        assert sub_agent.description == "Find where the units are converted."

    def test_its_main_thread_is_a_transcript(
        self, session: DbSession, collector: ComponentVersion
    ) -> None:
        session.add(_thread(collector, agent_id=SUB_AGENT, main_id=uuid.uuid4()))

        assert violated_constraint(session) == "transcripts_main_id_fkey"

    def test_a_main_thread_has_no_main_thread(
        self, session: DbSession, collector: ComponentVersion, thread: Transcript
    ) -> None:
        other = transcripts.transcript(session, collector, session_id=OTHER)
        other.main_id = thread.id

        assert violated_constraint(session) == "ck_transcripts_main_thread"

    def test_a_main_thread_has_no_spawning_call(
        self, session: DbSession, collector: ComponentVersion, thread: Transcript
    ) -> None:
        spawning = transcripts.tool_call(session, transcripts.call(session, thread, 1))
        other = transcripts.transcript(session, collector, session_id=OTHER)
        other.spawned_by_id = spawning.id

        assert violated_constraint(session) == "ck_transcripts_main_thread"

    def test_a_main_thread_names_no_spawning_call(
        self, session: DbSession, thread: Transcript
    ) -> None:
        thread.spawned_by_tool_use_id = "toolu_0031"

        assert violated_constraint(session) == "ck_transcripts_main_thread"

    def test_a_sub_agents_thread_names_a_spawning_call_pilot_does_not_hold(
        self, session: DbSession, collector: ComponentVersion
    ) -> None:
        """DB decision 79.16."""
        sub_agent = transcripts.transcript(
            session,
            collector,
            agent_id=SUB_AGENT,
            spawned_by_tool_use_id="toolu_0031",
        )
        session.expire(sub_agent)

        assert (sub_agent.spawned_by_tool_use_id, sub_agent.spawned_by_id) == (
            "toolu_0031",
            None,
        )

    def test_only_a_main_thread_is_hosted_by_an_environment(
        self,
        session: DbSession,
        collector: ComponentVersion,
        environment: Environment,
    ) -> None:
        """DB 536."""
        session.add(
            _thread(collector, agent_id=SUB_AGENT, environment_id=environment.id)
        )

        assert violated_constraint(session) == "ck_transcripts_environment"

    @pytest.mark.parametrize(
        ("column", "value", "constraint"),
        [
            (
                "environment_id",
                "example-other-000000",
                "transcripts_environment_id_fkey",
            ),
            ("repository_id", 404, "transcripts_repository_id_fkey"),
            ("read_under_id", 404, "transcripts_read_under_id_fkey"),
        ],
    )
    def test_what_it_names_is_held(
        self,
        session: DbSession,
        thread: Transcript,
        column: str,
        value: object,
        constraint: str,
    ) -> None:
        setattr(thread, column, value)

        assert violated_constraint(session) == constraint

    def test_a_sub_agents_spawning_call_is_a_tool_call(
        self, session: DbSession, collector: ComponentVersion
    ) -> None:
        sub_agent = transcripts.transcript(session, collector, agent_id=SUB_AGENT)
        sub_agent.spawned_by_id = 404

        assert violated_constraint(session) == "transcripts_spawned_by_id_fkey"

    def test_its_replayed_size_is_at_most_its_file_size(
        self, session: DbSession, thread: Transcript
    ) -> None:
        """DB 605: an appended publication moves the file's size alone."""
        thread.file_size = 60_000
        session.flush()

        thread.replayed_size = 60_001

        assert violated_constraint(session) == "ck_transcripts_replayed_size"

    def test_its_sizes_are_never_negative(
        self, session: DbSession, thread: Transcript
    ) -> None:
        thread.replayed_size = -1

        assert violated_constraint(session) == "ck_transcripts_replayed_size"

    def test_its_file_size_is_never_negative(
        self, session: DbSession, thread: Transcript
    ) -> None:
        thread.file_size = thread.replayed_size = -1

        assert violated_constraint(session) == "ck_transcripts_file_size"


class TestLaunch:
    def test_one_still_running_has_no_end(
        self, session: DbSession, start: Launch
    ) -> None:
        session.expire(start)

        assert (start.started_at, start.ended_at) == (STARTED, None)

    def test_a_transcript_is_continued_by_its_launches(
        self, session: DbSession, thread: Transcript, start: Launch
    ) -> None:
        start.ended_at = STARTED + timedelta(minutes=12)
        resumed = transcripts.launch(
            session, thread, started_at=STARTED + timedelta(hours=2)
        )

        launches = session.scalars(
            select(Launch.id)
            .where(Launch.transcript_id == thread.id)
            .order_by(Launch.started_at)
        ).all()
        assert launches == [start.id, resumed.id]

    def test_it_continues_a_transcript(self, session: DbSession) -> None:
        session.add(Launch(transcript_id=uuid.uuid4(), started_at=STARTED))

        assert violated_constraint(session) == "launches_transcript_id_fkey"

    def test_one_no_session_of_pilots_ran_has_no_session_and_no_turn(
        self, session: DbSession, start: Launch
    ) -> None:
        session.expire(start)

        assert (start.session_id, start.turn_seq) == (None, None)

    def test_one_a_turn_started_is_under_its_session_and_that_turn(
        self, session: DbSession, start: Launch, project_session: models.Session
    ) -> None:
        """DB 385, 386."""
        turn_at(session, project_session, STARTED)
        second = turn_at(session, project_session, STARTED + timedelta(hours=1))
        start.session_id = project_session.id
        start.turn_seq = second.seq
        session.flush()
        session.expire(start)

        assert (start.session_id, start.turn_seq) == (project_session.id, 2)

    def test_one_started_between_two_turns_has_its_session_and_no_turn(
        self, session: DbSession, start: Launch, project_session: models.Session
    ) -> None:
        start.session_id = project_session.id
        session.flush()
        session.expire(start)

        assert (start.session_id, start.turn_seq) == (project_session.id, None)

    def test_one_with_a_turn_has_a_session(
        self, session: DbSession, start: Launch
    ) -> None:
        """DB 537."""
        start.turn_seq = 1

        assert violated_constraint(session) == "ck_launches_turn"

    def test_its_turn_is_a_turn_of_its_session(
        self,
        session: DbSession,
        start: Launch,
        project: Project,
        project_session: models.Session,
    ) -> None:
        """DB 537."""
        other = models.Session(
            project_id=project.id,
            environment_id=project_session.environment_id,
            kind_code="work",
            cwd="/work/Example",
            token_hash="2" * 64,
            state_code=SessionState.RUNNING,
        )
        session.add(other)
        session.flush()
        turn_at(session, other, STARTED)
        start.session_id = project_session.id
        start.turn_seq = 1

        assert violated_constraint(session) == "launches_session_id_turn_seq_fkey"

    def test_its_session_is_a_session(self, session: DbSession, start: Launch) -> None:
        start.session_id = uuid.uuid4()

        assert violated_constraint(session) == "launches_session_id_fkey"


class TestLaunchComponent:
    def test_a_launch_runs_with_a_version_of_each_component(
        self, session: DbSession, start: Launch
    ) -> None:
        versions = [
            transcripts.component_version(session, "claude-code", "2.1.317"),
            transcripts.component_version(session, "plugin:garden", "0.4.1"),
        ]
        session.add_all(
            LaunchComponent(
                launch_id=start.id,
                component_version_id=version.id,
                component_code=version.component_code,
            )
            for version in versions
        )
        session.flush()

        assert _count(session, LaunchComponent) == 2

    def test_a_launch_runs_with_one_version_of_a_component(
        self, session: DbSession, start: Launch
    ) -> None:
        """DB 541."""
        session.add_all(
            LaunchComponent(
                launch_id=start.id,
                component_version_id=transcripts.component_version(
                    session, "claude-code", version
                ).id,
                component_code="claude-code",
            )
            for version in ("2.1.317", "2.1.318")
        )

        assert (
            violated_constraint(session)
            == "launch_components_launch_id_component_code_key"
        )

    def test_the_component_it_carries_is_its_versions(
        self, session: DbSession, start: Launch
    ) -> None:
        version = transcripts.component_version(session, "claude-code", "2.1.317")
        transcripts.reference(session, Component, "plugin:garden")
        session.add(
            LaunchComponent(
                launch_id=start.id,
                component_version_id=version.id,
                component_code="plugin:garden",
            )
        )

        assert (
            violated_constraint(session)
            == "launch_components_component_version_id_component_code_fkey"
        )

    def test_it_is_a_use_by_a_launch(
        self, session: DbSession, collector: ComponentVersion
    ) -> None:
        session.add(
            LaunchComponent(
                launch_id=404,
                component_version_id=collector.id,
                component_code="collector",
            )
        )

        assert violated_constraint(session) == "launch_components_launch_id_fkey"

    def test_it_goes_with_its_launch(
        self, session: DbSession, start: Launch, collector: ComponentVersion
    ) -> None:
        session.add(
            LaunchComponent(
                launch_id=start.id,
                component_version_id=collector.id,
                component_code="collector",
            )
        )
        session.flush()
        session.expunge_all()

        session.execute(Launch.__table__.delete().where(Launch.id == start.id))

        assert _count(session, LaunchComponent) == 0
        assert session.get(ComponentVersion, collector.id) is not None


class TestPrompt:
    def test_a_launch_receives_its_prompts(
        self, session: DbSession, start: Launch
    ) -> None:
        opening = transcripts.prompt(session, start)
        transcripts.reference(session, PromptSource, "task_notification")
        notice = transcripts.prompt(
            session,
            start,
            received_at=STARTED + timedelta(minutes=4),
            source_code="task_notification",
            characters=0,
        )
        session.expire_all()

        assert (opening.source_code, opening.characters) == ("person", 212)
        assert (notice.source_code, notice.characters) == ("task_notification", 0)
        assert opening.transcript_id == notice.transcript_id == start.transcript_id

    def test_the_transcript_it_carries_is_its_launchs(
        self, session: DbSession, collector: ComponentVersion, start: Launch
    ) -> None:
        other = transcripts.transcript(session, collector, session_id=OTHER)
        session.add(
            Prompt(
                transcript_id=other.id,
                launch_id=start.id,
                received_at=STARTED,
                source_code=transcripts.reference(session, PromptSource, "person").code,
                characters=212,
            )
        )

        assert violated_constraint(session) == "prompts_transcript_id_launch_id_fkey"

    def test_it_is_classified_by_a_prompt_source(
        self, session: DbSession, start: Launch
    ) -> None:
        opening = transcripts.prompt(session, start)
        opening.source_code = "other"

        assert violated_constraint(session) == "prompts_source_code_fkey"

    def test_its_length_is_never_negative(
        self, session: DbSession, start: Launch
    ) -> None:
        opening = transcripts.prompt(session, start)
        opening.characters = -1

        assert violated_constraint(session) == "ck_prompts_characters"

    def test_it_goes_with_its_launch_and_its_hook_runs_with_it(
        self, session: DbSession, thread: Transcript, start: Launch
    ) -> None:
        opening = transcripts.prompt(session, start)
        session.add(
            HookRun(
                prompt_id=opening.id,
                command="signal_activity.sh",
                duration_ms=151,
                failed=False,
                prevented_end=False,
            )
        )
        session.flush()
        session.expunge_all()

        session.execute(Launch.__table__.delete().where(Launch.id == start.id))

        assert _count(session, Prompt) == _count(session, HookRun) == 0
        assert session.get(Transcript, thread.id) is not None


class TestHookRun:
    def test_a_prompt_ends_with_its_hook_runs(
        self, session: DbSession, start: Launch
    ) -> None:
        opening = transcripts.prompt(session, start)
        session.add_all(
            [
                HookRun(
                    prompt_id=opening.id,
                    command="signal_activity.sh",
                    duration_ms=151,
                    failed=False,
                    prevented_end=False,
                ),
                HookRun(
                    prompt_id=opening.id,
                    command="hold_for_background.sh",
                    duration_ms=0,
                    failed=True,
                    prevented_end=True,
                ),
            ]
        )
        session.flush()

        runs = session.execute(
            select(HookRun.command, HookRun.failed, HookRun.prevented_end)
            .where(HookRun.prompt_id == opening.id)
            .order_by(HookRun.id)
        ).all()
        assert runs == [
            ("signal_activity.sh", False, False),
            ("hold_for_background.sh", True, True),
        ]

    def test_it_ends_a_prompt(self, session: DbSession) -> None:
        session.add(
            HookRun(
                prompt_id=404,
                command="signal_activity.sh",
                duration_ms=151,
                failed=False,
                prevented_end=False,
            )
        )

        assert violated_constraint(session) == "hook_runs_prompt_id_fkey"

    def test_its_duration_is_never_negative(
        self, session: DbSession, start: Launch
    ) -> None:
        session.add(
            HookRun(
                prompt_id=transcripts.prompt(session, start).id,
                command="signal_activity.sh",
                duration_ms=-1,
                failed=False,
                prevented_end=False,
            )
        )

        assert violated_constraint(session) == "ck_hook_runs_duration_ms"


class TestCompaction:
    def test_one_holds_what_its_version_records(
        self, session: DbSession, thread: Transcript
    ) -> None:
        bare = transcripts.compaction(session, thread)
        transcripts.reference(session, CompactionTrigger, "manual")
        full = transcripts.compaction(
            session,
            thread,
            trigger_code="manual",
            tokens_after=9_400,
            duration_ms=41_250,
        )
        session.expire_all()

        assert (bare.trigger_code, bare.tokens_before) == ("auto", 160_000)
        assert (bare.tokens_after, bare.duration_ms) == (None, None)
        assert (full.trigger_code, full.tokens_after, full.duration_ms) == (
            "manual",
            9_400,
            41_250,
        )

    def test_it_compacts_a_transcript(self, session: DbSession) -> None:
        transcripts.reference(session, CompactionTrigger, "auto")
        session.add(
            Compaction(
                transcript_id=uuid.uuid4(),
                at=STARTED,
                trigger_code="auto",
                tokens_before=160_000,
            )
        )

        assert violated_constraint(session) == "compactions_transcript_id_fkey"

    def test_it_is_classified_by_a_compaction_trigger(
        self, session: DbSession, thread: Transcript
    ) -> None:
        made = transcripts.compaction(session, thread)
        made.trigger_code = "other"

        assert violated_constraint(session) == "compactions_trigger_code_fkey"

    @pytest.mark.parametrize(
        ("column", "constraint"),
        [
            ("tokens_before", "ck_compactions_tokens"),
            ("tokens_after", "ck_compactions_tokens"),
            ("duration_ms", "ck_compactions_duration_ms"),
        ],
    )
    def test_its_figures_are_never_negative(
        self, session: DbSession, thread: Transcript, column: str, constraint: str
    ) -> None:
        made = transcripts.compaction(session, thread)
        setattr(made, column, -1)

        assert violated_constraint(session) == constraint
