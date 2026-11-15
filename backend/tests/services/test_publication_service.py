"""A whole publication of a transcript, written into the record: its
Launches with their versions, its Prompts with their Hook Runs, its
Compactions and its Calls with their tokens (F152.3, F152.4; DB decisions 79
and 81, the assertions of §4.31 and §4.33).

The rule that protects the most: a publication writes only the rows that
differ, and a row keeps its identity wherever the call names the same fact
again (`TestRepublished`)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flask import Flask
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.database import scoped_session
from app.exceptions import PublicationInvalidException
from app.models import (
    Call,
    Compaction,
    CompactionTrigger,
    Component,
    ComponentVersion,
    Environment,
    HookRun,
    Launch,
    LaunchComponent,
    MissCause,
    Model,
    Prompt,
    PromptSource,
    Repository,
    StopReason,
    Transcript,
)
from app.schemas.publication import PublicationSchema
from app.services.container import ServiceContainer
from app.services.publication_service import PublicationService
from tests.support import transcripts
from tests.support.database import Written, writes
from tests.support.locks import in_thread, lock_waits
from tests.support.publications import (
    call,
    compaction,
    hook_run,
    launch,
    prompt,
    sub_agent,
    whole,
)
from tests.support.supervisor import wait_until
from tests.support.transcripts import CAMP, HAIKU, OPUS, OTHER, STARTED, SUB_AGENT

CLAUDE_CODE = {"component": "claude-code", "version": "2.1.317"}


def _at(minutes: int) -> str:
    return (STARTED + timedelta(minutes=minutes)).isoformat()


def _first_launch(**overrides: Any) -> dict[str, Any]:
    """The Launch the conversation began under: two Prompts, the first with
    two Hook Runs."""
    values: dict[str, Any] = {
        "ended_at": _at(9),
        "components": [CLAUDE_CODE, {"component": "plugin:dev", "version": "0.10.49"}],
        "prompts": [
            prompt(
                hook_runs=[
                    hook_run(),
                    hook_run(
                        command="hold_open.sh", duration_ms=40, prevented_end=True
                    ),
                ]
            ),
            prompt(received_at=_at(4), source="task_notification", characters=88),
        ],
    }
    return launch(**values | overrides)


def _second_launch(**overrides: Any) -> dict[str, Any]:
    """The Launch that resumed it, under a newer plugin, still running."""
    values: dict[str, Any] = {
        "started_at": _at(10),
        "components": [CLAUDE_CODE, {"component": "plugin:dev", "version": "0.10.53"}],
        "prompts": [prompt(received_at=_at(10), characters=31)],
    }
    return launch(**values | overrides)


def _calls() -> list[dict[str, Any]]:
    """Four Calls: the third after the Compaction, a miss answered by the
    model that was not asked for and cut off at the output cap."""
    return [
        call(1, prompt=1, sent_at=_at(0)),
        call(2, prompt=1, predecessor="msg_0001", thinking_tokens=640, effort="high"),
        call(
            3,
            prompt=2,
            predecessor="msg_0002",
            compaction=1,
            model=HAIKU,
            requested_model=OPUS,
            stop_reason="max_tokens",
            miss_cause="compaction",
            attributed_skill="recipe-scaling",
            attributed_plugin="kitchen",
            tokens={"input": 90, "cache_write_5m": 12_000, "output": 4_096},
        ),
        call(4, prompt=3, predecessor="msg_0003"),
    ]


def _camp(**overrides: Any) -> PublicationSchema:
    """The main thread's publication: two Launches, three Prompts, a
    Compaction and four Calls."""
    values: dict[str, Any] = {
        "launches": [_first_launch(), _second_launch()],
        "compactions": [compaction(tokens_after=21_000, duration_ms=5_200)],
        "calls": _calls(),
    }
    return whole(**values | overrides)


def _count(db: DbSession, entity: type) -> int:
    return db.scalar(select(func.count()).select_from(entity)) or 0


def _ids(db: DbSession) -> dict[str, list[Any]]:
    """The id of every row a transcript's publication writes, by table, in
    its rows' order."""
    return {
        entity.__tablename__: list(db.scalars(select(entity.id).order_by(entity.id)))
        for entity in (Transcript, Launch, Prompt, HookRun, Compaction, Call)
    }


@pytest.fixture
def publications(container: ServiceContainer) -> PublicationService:
    return container.publication_service()


class TestPublished:
    """What Pilot holds after a transcript's first publication."""

    def test_the_transcript_is_held_as_its_file_stands(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        before = datetime.now(UTC)

        thread = publications.publish(_camp())

        held = session.execute(
            select(
                Transcript.id,
                Transcript.session_id,
                Transcript.agent_id,
                Transcript.working_directory,
                Transcript.file_size,
                Transcript.file_modified_at,
                Transcript.replayed_size,
            )
        ).one()
        assert held == (
            thread.id,
            CAMP,
            None,
            "/work/RecipeBox",
            48_112,
            STARTED + timedelta(minutes=12),
            48_112,
        )
        assert before <= thread.collected_at <= datetime.now(UTC)

    def test_it_is_read_under_the_collectors_version(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(
            _camp(collector={"version": "1.0.0", "released_at": _at(-600)})
        )

        version = session.get_one(ComponentVersion, thread.read_under_id)
        assert (version.component_code, version.version, version.released_at) == (
            "collector",
            "1.0.0",
            STARTED - timedelta(minutes=600),
        )

    def test_its_launches_are_held_in_the_files_order(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(_camp())

        assert session.execute(
            select(Launch.transcript_id, Launch.started_at, Launch.ended_at).order_by(
                Launch.id
            )
        ).all() == [
            (thread.id, STARTED, STARTED + timedelta(minutes=9)),
            (thread.id, STARTED + timedelta(minutes=10), None),
        ]

    def test_a_launch_runs_with_the_versions_the_call_names(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())

        first, second = session.scalars(select(Launch.id).order_by(Launch.id))
        used = session.execute(
            select(
                LaunchComponent.launch_id,
                LaunchComponent.component_code,
                ComponentVersion.component_code,
                ComponentVersion.version,
            )
            .join(
                ComponentVersion,
                ComponentVersion.id == LaunchComponent.component_version_id,
            )
            .order_by(LaunchComponent.launch_id, LaunchComponent.component_code)
        ).all()
        assert used == [
            (first, "claude-code", "claude-code", "2.1.317"),
            (first, "plugin:dev", "plugin:dev", "0.10.49"),
            (second, "claude-code", "claude-code", "2.1.317"),
            (second, "plugin:dev", "plugin:dev", "0.10.53"),
        ]

    def test_a_version_two_launches_ran_with_is_one_row(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())

        assert session.execute(
            select(ComponentVersion.component_code, ComponentVersion.version).order_by(
                ComponentVersion.component_code, ComponentVersion.version
            )
        ).all() == [
            ("claude-code", "2.1.317"),
            ("collector", "1.0.0"),
            ("plugin:dev", "0.10.49"),
            ("plugin:dev", "0.10.53"),
        ]

    def test_a_prompt_hangs_on_the_launch_that_received_it(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(_camp())

        first, second = session.scalars(select(Launch.id).order_by(Launch.id))
        assert session.execute(
            select(
                Prompt.transcript_id,
                Prompt.launch_id,
                Prompt.received_at,
                Prompt.source_code,
                Prompt.characters,
            ).order_by(Prompt.id)
        ).all() == [
            (thread.id, first, STARTED, "person", 212),
            (
                thread.id,
                first,
                STARTED + timedelta(minutes=4),
                "task_notification",
                88,
            ),
            (thread.id, second, STARTED + timedelta(minutes=10), "person", 31),
        ]

    def test_a_hook_run_hangs_on_the_prompt_whose_run_it_ended(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())

        opening = session.scalars(select(Prompt.id).order_by(Prompt.id)).first()
        assert session.execute(
            select(
                HookRun.prompt_id,
                HookRun.command,
                HookRun.duration_ms,
                HookRun.failed,
                HookRun.prevented_end,
            ).order_by(HookRun.id)
        ).all() == [
            (opening, "signal_activity.sh", 151, False, False),
            (opening, "hold_open.sh", 40, False, True),
        ]

    def test_its_compactions_are_held(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(_camp())

        assert session.execute(
            select(
                Compaction.transcript_id,
                Compaction.at,
                Compaction.trigger_code,
                Compaction.tokens_before,
                Compaction.tokens_after,
                Compaction.duration_ms,
            )
        ).all() == [
            (thread.id, STARTED + timedelta(minutes=8), "auto", 160_000, 21_000, 5_200)
        ]

    def test_its_calls_stand_at_their_place_in_the_file(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(_camp())

        assert session.execute(
            select(
                Call.transcript_id, Call.message_id, Call.position, Call.completed_at
            ).order_by(Call.position)
        ).all() == [
            (thread.id, f"msg_{place:04}", place, STARTED + timedelta(minutes=place))
            for place in (1, 2, 3, 4)
        ]

    def test_a_call_names_its_prompt_its_predecessor_and_its_compaction(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())

        prompts = list(session.scalars(select(Prompt.id).order_by(Prompt.id)))
        crossed = session.scalars(select(Compaction.id)).one()
        calls = dict(session.execute(select(Call.position, Call.id)).all())
        assert session.execute(
            select(
                Call.position, Call.prompt_id, Call.predecessor_id, Call.compaction_id
            ).order_by(Call.position)
        ).all() == [
            (1, prompts[0], None, None),
            (2, prompts[0], calls[1], None),
            (3, prompts[1], calls[2], crossed),
            (4, prompts[2], calls[3], None),
        ]

    def test_a_call_holds_its_tokens_by_kind_and_none_where_the_call_counts_none(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())

        assert session.execute(
            select(
                Call.input_tokens,
                Call.cache_write_5m_tokens,
                Call.cache_write_1h_tokens,
                Call.cache_read_tokens,
                Call.output_tokens,
                Call.thinking_tokens,
            )
            .where(Call.position.in_([2, 3]))
            .order_by(Call.position)
        ).all() == [
            (1_204, 0, 3_310, 48_112, 2_870, 640),
            (90, 12_000, 0, 0, 4_096, None),
        ]

    def test_a_call_holds_what_was_asked_and_how_it_ended(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())

        facts = select(
            Call.sent_at,
            Call.model_code,
            Call.requested_model_code,
            Call.effort,
            Call.stop_reason_code,
            Call.miss_cause_code,
            Call.attributed_skill,
            Call.attributed_plugin,
        )
        assert session.execute(facts.where(Call.position == 1)).one() == (
            STARTED,
            OPUS,
            None,
            None,
            None,
            None,
            None,
            None,
        )
        assert session.execute(facts.where(Call.position == 2)).one()[3] == "high"
        assert session.execute(facts.where(Call.position == 3)).one() == (
            None,
            HAIKU,
            OPUS,
            None,
            "max_tokens",
            "compaction",
            "recipe-scaling",
            "kitchen",
        )

    @pytest.mark.parametrize(
        ("entity", "codes"),
        [
            (Component, ["claude-code", "collector", "plugin:dev"]),
            (CompactionTrigger, ["auto"]),
            (MissCause, ["compaction"]),
            (Model, [HAIKU, OPUS]),
            (PromptSource, ["person", "task_notification"]),
            (StopReason, ["max_tokens"]),
        ],
    )
    def test_a_reference_code_pilot_has_not_met_is_written_named_by_its_code(
        self,
        session: DbSession,
        publications: PublicationService,
        entity: Any,
        codes: list[str],
    ) -> None:
        publications.publish(_camp())

        assert session.execute(
            select(entity.code, entity.name).order_by(entity.code)
        ).all() == [(code, code) for code in codes]

    def test_a_reference_code_pilot_has_met_is_left_as_it_stands(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        session.add(Model(code=OPUS, name="Opus 4.5"))
        session.flush()

        publications.publish(_camp())

        assert session.execute(
            select(Model.code, Model.name).order_by(Model.code)
        ).all() == [
            (HAIKU, HAIKU),
            (OPUS, "Opus 4.5"),
        ]

    def test_a_transcript_with_nothing_in_it_is_held(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(whole())

        assert _count(session, Transcript) == 1
        assert _count(session, Launch) == 0
        assert _count(session, Call) == 0


class TestScope:
    """Every transcript is taken, under the environment and the repository
    its publication names (F152.4)."""

    def test_an_environment_pilot_never_touched_is_written_named_by_its_id(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(_camp(environment="env-9c41"))

        assert thread.environment_id == "env-9c41"
        assert session.execute(
            select(
                Environment.id,
                Environment.name,
                Environment.exempt,
                Environment.server_created_at,
                Environment.last_seen_at,
            )
        ).all() == [("env-9c41", "env-9c41", False, None, None)]

    def test_an_environment_pilot_holds_is_left_as_it_stands(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        session.add(Environment(id="env-9c41", name="Recipes-1", exempt=True))
        session.flush()

        with writes(session) as wrote:
            thread = publications.publish(_camp(environment="env-9c41"))

        assert thread.environment_id == "env-9c41"
        assert "environments" not in wrote
        assert session.execute(select(Environment.name, Environment.exempt)).all() == [
            ("Recipes-1", True)
        ]

    def test_a_repository_is_written_by_its_checkouts_name(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(_camp(repository="RecipeBox"))

        assert session.execute(select(Repository.id, Repository.name)).all() == [
            (thread.repository_id, "RecipeBox")
        ]

    def test_two_transcripts_of_one_checkout_share_its_repository(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        first = publications.publish(_camp(repository="RecipeBox"))

        second = publications.publish(whole(session_id=OTHER, repository="RecipeBox"))

        assert second.repository_id == first.repository_id
        assert _count(session, Repository) == 1

    def test_one_that_names_neither_lands_under_neither(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(_camp())

        assert (thread.environment_id, thread.repository_id) == (None, None)
        assert _count(session, Environment) == 0
        assert _count(session, Repository) == 0

    def test_a_sub_agents_thread_is_held_with_its_type_and_its_task(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(
            sub_agent(
                repository="RecipeBox", calls=[call(1), call(2, predecessor="msg_0001")]
            )
        )

        assert session.execute(
            select(
                Transcript.session_id,
                Transcript.agent_id,
                Transcript.agent_type,
                Transcript.description,
                Transcript.repository_id.is_not(None),
            )
        ).all() == [
            (CAMP, SUB_AGENT, "Explore", "Find where the recipes are scaled", True)
        ]
        assert _count(session, Call) == 2
        assert _count(session, Launch) == 0

    def test_a_sub_agents_thread_that_comes_first_waits_for_its_main_thread(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(sub_agent())

        assert thread.main_id is None

        main = publications.publish(_camp())

        assert (
            session.scalars(
                select(Transcript.main_id).where(Transcript.id == thread.id)
            ).one()
            == main.id
        )

    def test_a_sub_agents_thread_that_comes_second_is_under_its_main_thread(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        main = publications.publish(_camp())

        thread = publications.publish(sub_agent())

        assert thread.main_id == main.id
        assert main.main_id is None

    def test_a_sub_agents_thread_stays_under_its_main_thread_when_either_comes_again(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        main = publications.publish(_camp())
        thread = publications.publish(sub_agent())

        publications.publish(_camp(file_size=50_000))
        publications.publish(sub_agent(file_size=50_000))

        assert session.execute(
            select(Transcript.id, Transcript.main_id).order_by(Transcript.agent_id)
        ).all() == [(thread.id, main.id), (main.id, None)]

    def test_a_main_thread_takes_no_other_conversations_sub_agents(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(sub_agent())

        publications.publish(whole(session_id=OTHER))

        assert (
            session.scalars(
                select(Transcript.main_id).where(Transcript.id == thread.id)
            ).one()
            is None
        )

    def test_two_conversations_calls_of_one_message_id_are_two_calls(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(whole(calls=[call(1)]))

        publications.publish(whole(session_id=OTHER, calls=[call(1)]))

        assert _count(session, Call) == 2

    @pytest.mark.parametrize(
        "entity",
        [
            Transcript,
            Launch,
            LaunchComponent,
            ComponentVersion,
            Prompt,
            HookRun,
            Compaction,
            Call,
            Repository,
        ],
    )
    def test_nothing_held_of_a_conversation_names_a_person_or_a_member(
        self, entity: Any
    ) -> None:
        """Every conversation is open to everyone signed in: no row of one
        says who ran it."""
        named = {key.column.table.name for key in entity.__table__.foreign_keys}

        assert not named & {"users", "project_members"}


class TestRepublished:
    """A transcript published again: only the rows that differ are written,
    and a row the call names again keeps its identity."""

    def test_an_unchanged_transcript_writes_its_own_row_alone(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp(repository="RecipeBox", environment="env-9c41"))
        ids = _ids(session)

        with writes(session) as wrote:
            publications.publish(_camp(repository="RecipeBox", environment="env-9c41"))

        assert wrote == {"transcripts": Written(updated=1)}
        assert _ids(session) == ids

    def test_new_calls_are_the_rows_written(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        ids = _ids(session)
        grown = [
            *_calls(),
            call(5, prompt=3, predecessor="msg_0004"),
            call(6, prompt=3, predecessor="msg_0005"),
        ]

        with writes(session) as wrote:
            publications.publish(_camp(calls=grown, file_size=61_000))

        assert wrote == {
            "transcripts": Written(updated=1),
            "calls": Written(inserted=2),
        }
        after = _ids(session)
        assert after["calls"][:4] == ids["calls"]
        assert session.execute(
            select(Call.position, Call.predecessor_id)
            .where(Call.position > 4)
            .order_by(Call.position)
        ).all() == [(5, after["calls"][3]), (6, after["calls"][4])]

    def test_a_call_whose_facts_differ_is_the_row_written(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        ids = _ids(session)
        calls = _calls()
        calls[3] |= {"stop_reason": "refusal", "tokens": {"output": 12}}

        with writes(session) as wrote:
            publications.publish(_camp(calls=calls))

        assert wrote == {
            "transcripts": Written(updated=1),
            "calls": Written(updated=1),
            "stop_reasons": Written(inserted=1),
        }
        assert _ids(session) == ids
        assert session.execute(
            select(Call.stop_reason_code, Call.input_tokens, Call.output_tokens).where(
                Call.position == 4
            )
        ).one() == ("refusal", 0, 12)

    def test_each_row_whose_facts_differ_is_written_in_its_place(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        ids = _ids(session)
        first = _first_launch()
        first["prompts"][1]["characters"] = 90
        first["prompts"][0]["hook_runs"][1]["failed"] = True

        with writes(session) as wrote:
            publications.publish(
                _camp(
                    launches=[first, _second_launch(ended_at=_at(14))],
                    compactions=[compaction(tokens_after=20_000, duration_ms=5_200)],
                )
            )

        assert wrote == {
            "transcripts": Written(updated=1),
            "launches": Written(updated=1),
            "prompts": Written(updated=1),
            "hook_runs": Written(updated=1),
            "compactions": Written(updated=1),
        }
        assert _ids(session) == ids
        assert session.execute(select(Launch.ended_at).order_by(Launch.id)).all() == [
            (STARTED + timedelta(minutes=9),),
            (STARTED + timedelta(minutes=14),),
        ]
        assert session.scalars(select(Prompt.characters).order_by(Prompt.id)).all() == [
            212,
            90,
            31,
        ]
        assert session.scalars(select(HookRun.failed).order_by(HookRun.id)).all() == [
            False,
            True,
        ]
        assert session.scalars(select(Compaction.tokens_after)).one() == 20_000

    def test_a_launch_begun_since_is_written_after_the_held_ones(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        ids = _ids(session)
        third = launch(
            started_at=_at(20),
            prompts=[prompt(received_at=_at(20), hook_runs=[hook_run()])],
        )

        with writes(session) as wrote:
            publications.publish(
                _camp(
                    launches=[_first_launch(), _second_launch(ended_at=_at(14)), third],
                    calls=[*_calls(), call(21, prompt=4, predecessor="msg_0004")],
                )
            )

        assert wrote == {
            "transcripts": Written(updated=1),
            "launches": Written(inserted=1, updated=1),
            "launch_components": Written(inserted=1),
            "prompts": Written(inserted=1),
            "hook_runs": Written(inserted=1),
            "calls": Written(inserted=1),
        }
        after = _ids(session)
        assert after["launches"][:2] == ids["launches"]
        assert session.execute(
            select(Prompt.launch_id, Call.position)
            .join(Call, Call.prompt_id == Prompt.id)
            .where(Prompt.id == after["prompts"][3])
        ).all() == [(after["launches"][2], 5)]

    def test_a_launch_named_under_another_version_takes_it(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        newer = {"component": "plugin:dev", "version": "0.10.56"}

        with writes(session) as wrote:
            publications.publish(
                _camp(
                    launches=[
                        _first_launch(),
                        _second_launch(components=[CLAUDE_CODE, newer]),
                    ]
                )
            )

        assert wrote == {
            "transcripts": Written(updated=1),
            "component_versions": Written(inserted=1),
            "launch_components": Written(updated=1),
        }
        second = session.scalars(select(Launch.id).order_by(Launch.id)).all()[1]
        assert session.execute(
            select(ComponentVersion.component_code, ComponentVersion.version)
            .join(
                LaunchComponent,
                LaunchComponent.component_version_id == ComponentVersion.id,
            )
            .where(LaunchComponent.launch_id == second)
            .order_by(ComponentVersion.component_code)
        ).all() == [("claude-code", "2.1.317"), ("plugin:dev", "0.10.56")]

    def test_a_file_that_grew_is_held_at_its_new_size_replayed_whole(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """DB 605: `replayed_size` is `file_size` after a whole publication."""
        first = publications.publish(_camp())

        thread = publications.publish(
            _camp(
                file_size=61_000,
                file_modified_at=_at(30),
                collector={"version": "1.1.0"},
            )
        )

        assert thread.id == first.id
        assert session.execute(
            select(
                Transcript.file_size,
                Transcript.replayed_size,
                Transcript.file_modified_at,
                ComponentVersion.version,
            ).join(ComponentVersion, ComponentVersion.id == Transcript.read_under_id)
        ).all() == [(61_000, 61_000, STARTED + timedelta(minutes=30), "1.1.0")]

    def test_the_transcripts_own_facts_follow_the_call(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp(repository="RecipeBox", environment="env-9c41"))

        thread = publications.publish(
            _camp(working_directory="/work/BikeLog", repository="BikeLog")
        )

        assert session.execute(
            select(
                Transcript.working_directory,
                Repository.name,
                Transcript.environment_id,
            ).join(Repository, Repository.id == Transcript.repository_id)
        ).all() == [("/work/BikeLog", "BikeLog", None)]
        assert thread.environment_id is None
        assert _count(session, Environment) == 1
        assert _count(session, Repository) == 2

    def test_a_version_takes_the_release_time_a_later_call_gives(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        released = CLAUDE_CODE | {"released_at": _at(-90)}

        publications.publish(
            _camp(
                launches=[
                    _first_launch(),
                    _second_launch(
                        components=[
                            released,
                            {"component": "plugin:dev", "version": "0.10.53"},
                        ]
                    ),
                ]
            )
        )
        publications.publish(_camp())

        assert session.scalars(
            select(ComponentVersion.released_at).where(
                ComponentVersion.component_code == "claude-code"
            )
        ).one() == STARTED - timedelta(minutes=90)

    def test_a_call_is_found_again_by_its_message_id_wherever_it_stood(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """The held Call moves down, behind one the file now has before it,
        which it names as its predecessor."""
        collector = transcripts.component_version(session)
        thread = transcripts.transcript(session, collector)
        held = transcripts.call(session, thread, 1, message_id="msg_0002")

        publications.publish(whole(calls=[call(1), call(2, predecessor="msg_0001")]))

        before = session.scalars(select(Call.id).where(Call.position == 1)).one()
        assert session.execute(
            select(Call.id, Call.message_id, Call.predecessor_id).where(
                Call.position == 2
            )
        ).one() == (held.id, "msg_0002", before)
        assert _count(session, Transcript) == 1


class TestTurns:
    """Publications of one conversation take turns, each seeing what the one
    before it committed."""

    def test_a_sub_agents_thread_published_beside_its_main_thread_is_under_it(
        self, committed_app: Flask
    ) -> None:
        container = committed_app.container

        def published_second() -> Any:
            with scoped_session(container):
                return container.publication_service().publish(sub_agent()).main_id

        first = container.session_maker()()
        try:
            main_id = PublicationService(first).publish(_camp()).id
            second = in_thread(published_second)
            wait_until(lambda: lock_waits(container) == 1, "the second's turn waiting")
            first.commit()
        finally:
            first.close()

        assert second.result() == main_id

    def test_a_transcript_published_twice_at_once_is_one_transcript(
        self, committed_app: Flask
    ) -> None:
        container = committed_app.container

        def published_second() -> Any:
            with scoped_session(container):
                grown = [*_calls(), call(5, prompt=3, predecessor="msg_0004")]
                return (
                    container.publication_service()
                    .publish(_camp(calls=grown, file_size=61_000))
                    .id
                )

        first = container.session_maker()()
        try:
            thread_id = PublicationService(first).publish(_camp()).id
            second = in_thread(published_second)
            wait_until(lambda: lock_waits(container) == 1, "the second's turn waiting")
            first.commit()
        finally:
            first.close()

        assert second.result() == thread_id
        with scoped_session(container) as db:
            assert db.execute(select(Transcript.id, Transcript.file_size)).all() == [
                (thread_id, 61_000)
            ]
            assert db.scalars(select(Call.position).order_by(Call.position)).all() == [
                1,
                2,
                3,
                4,
                5,
            ]


class TestRefused:
    """A call that contradicts itself or the record's rules for a Transcript
    is refused, and writes nothing."""

    @pytest.mark.parametrize(
        ("publication", "fault"),
        [
            (whole(agent_type="Explore"), "a main thread has no `agent_type`"),
            (
                whole(description="Find where the recipes are scaled"),
                "a main thread has no `description`",
            ),
            (
                sub_agent(environment="env-9c41"),
                "a sub-agent's thread is hosted by no environment",
            ),
            (sub_agent(launches=[launch()]), "a sub-agent's thread has no launches"),
            (
                whole(
                    launches=[
                        launch(),
                        launch(
                            components=[
                                CLAUDE_CODE,
                                {"component": "claude-code", "version": "2.1.320"},
                            ]
                        ),
                    ]
                ),
                "launch 2: two versions of the component `claude-code`",
            ),
            (
                whole(
                    launches=[
                        launch(components=[CLAUDE_CODE | {"released_at": _at(-90)}]),
                        launch(components=[CLAUDE_CODE | {"released_at": _at(-60)}]),
                    ]
                ),
                "version `2.1.317` of the component `claude-code` is given two"
                " release times",
            ),
            (whole(calls=[call(1), call(1)]), "call `msg_0001`: named twice"),
            (
                whole(launches=[launch(prompts=[prompt()])], calls=[call(1, prompt=2)]),
                "call `msg_0001`: `prompt` 2 is past the call's 1 prompts",
            ),
            (
                sub_agent(calls=[call(1, prompt=1)]),
                "call `msg_0001`: `prompt` 1 is past the call's 0 prompts",
            ),
            (
                whole(compactions=[compaction()], calls=[call(1, compaction=2)]),
                "call `msg_0001`: `compaction` 2 is past the call's 1 compactions",
            ),
            (
                whole(calls=[call(1, predecessor="msg_0002"), call(2)]),
                "call `msg_0001`: `predecessor` `msg_0002` is no earlier call",
            ),
            (
                whole(calls=[call(1, predecessor="msg_0001")]),
                "call `msg_0001`: `predecessor` `msg_0001` is no earlier call",
            ),
            (
                whole(calls=[call(1, requested_model=OPUS)]),
                "call `msg_0001`: `requested_model` is its `model`",
            ),
        ],
    )
    def test_a_fault_refuses_the_call(
        self,
        session: DbSession,
        publications: PublicationService,
        publication: PublicationSchema,
        fault: str,
    ) -> None:
        with (
            writes(session) as wrote,
            pytest.raises(PublicationInvalidException) as refused,
        ):
            publications.publish(publication)

        assert refused.value.faults == [fault]
        assert wrote == {}

    def test_every_fault_is_named_at_once(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publication = sub_agent(
            environment="env-9c41",
            calls=[call(1, requested_model=OPUS), call(1, predecessor="msg_0009")],
        )

        with pytest.raises(PublicationInvalidException) as refused:
            publications.publish(publication)

        assert refused.value.faults == [
            "a sub-agent's thread is hosted by no environment",
            "call `msg_0001`: `requested_model` is its `model`",
            "call `msg_0001`: named twice",
            "call `msg_0001`: `predecessor` `msg_0009` is no earlier call",
        ]
        assert refused.value.message == (
            f"Cannot take the publication of transcript {CAMP}/{SUB_AGENT} because "
            + "; ".join(refused.value.faults)
        )
        assert _count(session, Transcript) == 0

    def test_a_version_named_twice_with_one_release_time_is_no_fault(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        released = CLAUDE_CODE | {"released_at": _at(-90)}

        publications.publish(
            whole(
                launches=[
                    launch(components=[released]),
                    launch(components=[CLAUDE_CODE]),
                    launch(components=[released]),
                ]
            )
        )

        assert session.scalars(
            select(ComponentVersion.released_at).where(
                ComponentVersion.component_code == "claude-code"
            )
        ).one() == STARTED - timedelta(minutes=90)
