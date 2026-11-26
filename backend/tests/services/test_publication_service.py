"""A publication of a transcript, whole or appended, written into the
record: its Launches with their versions, its Prompts with their Hook Runs,
its Compactions and its Calls with their tokens, Tool Calls, Events and
Context Parts (F152.3, F152.4, F152.15; DB decisions 79 and 81, the
assertions of §4.31 and §4.33).

The rule that protects the most: a publication writes only the rows that
differ, and a row keeps its identity wherever the call names the same fact
again (`TestRepublished`). What a whole call no longer names goes, and only
that (`TestRewritten`; F152.17, decision 81 point 4). An appended call
writes from its boundary on alone (`TestAppended`), and one that does not
continue what Pilot holds is refused whole (`TestNotAppendable`). The rows a
replay at rest writes are logged (`TestReplayedAtRest`; F152.16, decision 81
point 2). A Launch a Turn of Pilot's started stands under its Session and
Turn (`TestRan`). A Call is written with its caches, its Transcript with its
first and its last Call's time (`TestCaches`; DB §7.4). What Pilot holds is
handed to a walk as its inventory (`TestInventory`; F152.2)."""

import logging
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from flask import Flask
from pilot_collection.publication import PublicationSchema
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.exceptions import (
    AuthenticationException,
    CollectorProtocolUnsupportedException,
    NoServiceUserException,
    PublicationInvalidException,
    PublicationNotAppendableException,
    TranscriptNotAdoptableException,
)
from app.models import (
    Call,
    Compaction,
    CompactionTrigger,
    Component,
    ComponentVersion,
    ContextPart,
    ContextPartKind,
    DenialKind,
    Document,
    Environment,
    Event,
    EventKind,
    HookRun,
    Launch,
    LaunchComponent,
    MissCause,
    Model,
    Project,
    Prompt,
    PromptSource,
    Repository,
    StopReason,
    Tool,
    ToolCall,
    Transcript,
    Turn,
    User,
)
from app.models.reference import ProjectState, UserKind
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerEnvironment
from app.services.price_service import FilePrice, PriceLoad
from app.services.publication_service import (
    COLLECTOR_PROTOCOL_MAX,
    COLLECTOR_PROTOCOL_MIN,
    PublicationService,
)
from tests.support import transcripts
from tests.support.adoption import FIRST_MENUS
from tests.support.database import Written, writes
from tests.support.locks import in_thread, lock_waits
from tests.support.publications import (
    COLLECTOR_TOKEN,
    SPAWNING,
    appended,
    builds_on,
    call,
    collector_headers,
    compaction,
    context_part,
    event,
    group,
    hook_run,
    labelling,
    launch,
    prompt,
    sub_agent,
    tool_call,
    whole,
)
from tests.support.statements import sent
from tests.support.supervisor import wait_until
from tests.support.transcripts import (
    CAMP,
    HAIKU,
    OPUS,
    OTHER,
    SONNET,
    STARTED,
    SUB_AGENT,
)
from tests.support.turns import end_turns, turn_at

CLAUDE_CODE = {"component": "claude-code", "version": "2.1.317"}
DEEPER = "c81d5e02f7a9b3d64"
"""Claude Code's id of a second invented sub-agent."""
RECIPES = "Find where the recipes are scaled"
LOGGER = "app.services.publication_service"
PANTRY = "claude-pantry-2"
"""An invented model, of a family the price file knows nothing of."""
PANTRY_INPUT = FilePrice(
    PANTRY, "input", None, Decimal("3"), datetime(2026, 1, 1, tzinfo=UTC)
)
"""A row of an invented price file: its input rate."""
PLACEMENT_LOGGER = "app.services.launch_placement"


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
    model that was not asked for and cut off at the output cap.

    The first carries the context a Launch opens with. The second asks an
    MCP tool and starts the sub-agent, and meets an API error and its retry.
    The third runs a failing command whose output was saved and one a hook
    blocked. The fourth's command the person interrupted."""
    return [
        call(
            1,
            prompt=1,
            sent_at=_at(0),
            tool_calls=[tool_call(1)],
            context_parts=[
                context_part(),
                context_part(kind="tool_schemas", characters=45_300),
                context_part(
                    kind="instruction_file", name="CLAUDE.md", characters=2_400
                ),
            ],
        ),
        call(
            2,
            prompt=1,
            predecessor="msg_0001",
            thinking_tokens=640,
            effort="high",
            tool_calls=[
                tool_call(
                    2,
                    tool="mcp__pantry__find_items",
                    mcp_server="pantry",
                    first_argument="flour",
                ),
                tool_call(
                    31, tool="Agent", first_argument=RECIPES, result_characters=640
                ),
            ],
            events=[
                event(),
                event(
                    kind="api_retry",
                    is_error=False,
                    at=(STARTED + timedelta(minutes=2, seconds=19)).isoformat(),
                    detail=None,
                ),
            ],
        ),
        call(
            3,
            tool_calls=[
                tool_call(
                    3,
                    first_argument="pytest tests/scaling",
                    failed=True,
                    exit_code=1,
                    result_characters=2_000,
                    saved_characters=412_000,
                ),
                tool_call(
                    4,
                    first_argument="git commit -m scaling",
                    failed=True,
                    denial_kind="hook",
                    result_characters=96,
                ),
            ],
            context_parts=[
                context_part(
                    kind="skill_body", name="recipe-scaling", characters=11_800
                )
            ],
            prompt=2,
            predecessor="msg_0002",
            compaction=1,
            model=HAIKU,
            requested_model=SONNET,
            stop_reason="max_tokens",
            miss_cause="compaction",
            attributed_skill="recipe-scaling",
            attributed_plugin="kitchen",
            tokens={"input": 90, "cache_write_5m": 12_000, "output": 4_096},
        ),
        call(
            4,
            prompt=3,
            predecessor="msg_0003",
            tool_calls=[
                tool_call(5, interrupted=True, returned_at=None, result_characters=None)
            ],
            events=[event(kind="interrupt", is_error=False, at=_at(11), detail=None)],
        ),
    ]


def _camp(**overrides: Any) -> PublicationSchema:
    """The main thread's publication: two Launches, three Prompts, a
    Compaction and four Calls, with what each Call did."""
    values: dict[str, Any] = {
        "launches": [_first_launch(), _second_launch()],
        "compactions": [compaction(tokens_after=21_000, duration_ms=5_200)],
        "calls": _calls(),
    }
    return whole(**values | overrides)


def _grown(**overrides: Any) -> PublicationSchema:
    """The main thread's appended publication once its file grew: from its
    fourth Call on, the last Pilot holds, with a fifth after it, under the
    Launch that resumed it and none of that Launch's Prompts."""
    values: dict[str, Any] = {
        "call": 4,
        "launch": 2,
        "prompt": 4,
        "compaction": 2,
        "launches": [_second_launch(prompts=[])],
        "calls": [_calls()[3], call(5, prompt=3, predecessor="msg_0004")],
    }
    return appended(**values | overrides)


def _count(db: DbSession, entity: type) -> int:
    return db.scalar(select(func.count()).select_from(entity)) or 0


def _ids(db: DbSession) -> dict[str, list[Any]]:
    """The id of every row a transcript's publication writes, by table, in
    its rows' order."""
    return {
        entity.__tablename__: list(db.scalars(select(entity.id).order_by(entity.id)))
        for entity in (
            Transcript,
            Launch,
            Prompt,
            HookRun,
            Compaction,
            Call,
            ToolCall,
            Event,
            ContextPart,
        )
    }


def _tool_call_id(db: DbSession, tool_use_id: str = SPAWNING) -> int:
    """The id of the one Tool Call of that name Pilot holds."""
    return db.scalars(
        select(ToolCall.id).where(ToolCall.tool_use_id == tool_use_id)
    ).one()


def _spawned_by(db: DbSession, thread: Transcript) -> int | None:
    """The Tool Call the thread is joined to as its spawning call."""
    return db.scalars(
        select(Transcript.spawned_by_id).where(Transcript.id == thread.id)
    ).one()


def _at_time(minutes: int) -> datetime:
    return STARTED + timedelta(minutes=minutes)


def _ran(db: DbSession) -> list[tuple[Any, int | None]]:
    """The Session and the Turn each Launch Pilot holds stands under, in the
    Launches' order."""
    return [
        (row.session_id, row.turn_seq)
        for row in db.execute(
            select(Launch.session_id, Launch.turn_seq).order_by(Launch.id)
        )
    ]


def _projects(db: DbSession, thread: Transcript) -> list[Any]:
    """The Projects the Transcript is on: those of the Sessions that ran its
    Launches (DB 540)."""
    return list(
        db.scalars(
            select(models.Session.project_id)
            .join(Launch, Launch.session_id == models.Session.id)
            .where(Launch.transcript_id == thread.id)
            .distinct()
        )
    )


def _caches(db: DbSession, thread: Transcript) -> list[tuple[Any, ...]]:
    """The caches of each Call of the Transcript, in the file's order: its
    wait, whether it is a rewind, a miss and past the cache's lifetime, and
    the Launch it was made in, by its place among the Launches Pilot
    holds."""
    places = {
        launch_id: place
        for place, launch_id in enumerate(
            db.scalars(select(Launch.id).order_by(Launch.id)), start=1
        )
    }
    return [
        (
            row.waited_seconds,
            row.rewind,
            row.cache_miss,
            row.past_ttl,
            places.get(row.launch_id),
        )
        for row in db.execute(
            select(
                Call.waited_seconds,
                Call.rewind,
                Call.cache_miss,
                Call.past_ttl,
                Call.launch_id,
            )
            .where(Call.transcript_id == thread.id)
            .order_by(Call.position)
        )
    ]


def _call_times(db: DbSession, thread: Transcript) -> tuple[Any, Any]:
    """The Transcript's first and last Call's time, as the record holds
    them."""
    row = db.execute(
        select(Transcript.first_call_at, Transcript.last_call_at).where(
            Transcript.id == thread.id
        )
    ).one()
    return row.first_call_at, row.last_call_at


@pytest.fixture
def publications(container: ServiceContainer) -> PublicationService:
    return container.publication_service()


@pytest.fixture
def waited(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
    project_session: models.Session,
) -> models.Session:
    """A Session of Pilot's that is a Work, created before the conversation
    began, its Turn in flight since then, whose step names the main thread:
    the one that waited on the loop a driver ran the thread in."""
    project_session.created_at = _at_time(-10)
    container.record_service().place_work(project, project_session, "Scaling")
    turn_at(session, project_session, _at_time(-9))
    transcripts.named_by_step(session, project_session)
    return project_session


@pytest.fixture
def run(session: DbSession, project_session: models.Session) -> models.Session:
    """A Session of Pilot's on the main thread's conversation: its first
    Turn sent as the first Launch began and ended as that one did, its
    second sent as the second Launch began, in flight."""
    project_session.conversation_id = CAMP
    turn_at(session, project_session, _at_time(0) - timedelta(seconds=4), _at_time(9))
    turn_at(session, project_session, _at_time(10) - timedelta(seconds=4))
    return project_session


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

    def test_a_call_holds_its_context_and_its_cost_at_the_prices_in_force(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())

        # The second at claude-opus-4-5's rates, the third at
        # claude-haiku-4-5-20251001's.
        assert session.execute(
            select(Call.context_tokens, Call.cost)
            .where(Call.position.in_([2, 3]))
            .order_by(Call.position)
        ).all() == [(52_626, Decimal("0.134926")), (12_090, Decimal("0.03557"))]

    def test_a_model_first_met_is_priced_as_the_newest_of_its_family(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        tokens = {"input": 1_000_000, "output": 100_000}
        calls = [call(1, model="claude-opus-9", tokens=tokens)]

        publications.publish(_camp(calls=calls, compactions=[]))

        assert session.execute(
            select(Model.code, Model.priced_as_code)
            .where(Model.code.in_(["claude-opus-9", OPUS]))
            .order_by(Model.code)
        ).all() == [(OPUS, None), ("claude-opus-9", "claude-opus-5-5")]
        # At claude-opus-5-5's rates: $4 and $20 a million.
        assert session.scalars(select(Call.cost)).all() == [Decimal("6")]

    def test_a_model_asked_for_and_first_met_is_priced_as_its_familys_newest(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())

        assert session.scalars(
            select(Model.priced_as_code).where(Model.code == SONNET)
        ).all() == ["claude-sonnet-5-5"]

    def test_a_call_of_a_model_no_price_covers_has_no_cost(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        calls = [call(1, model="pantry-1")]

        publications.publish(_camp(calls=calls, compactions=[]))

        assert session.execute(
            select(Call.cost, Model.priced_as_code).join(
                Model, Model.code == Call.model_code
            )
        ).all() == [(None, None)]

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
            SONNET,
            None,
            "max_tokens",
            "compaction",
            "recipe-scaling",
            "kitchen",
        )

    def test_a_tool_call_hangs_on_the_call_that_requested_it(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(_camp())

        assert session.execute(
            select(
                Call.position,
                ToolCall.transcript_id,
                ToolCall.tool_use_id,
                ToolCall.tool_code,
                ToolCall.first_argument,
            )
            .join(Call, Call.id == ToolCall.call_id)
            .order_by(ToolCall.id)
        ).all() == [
            (1, thread.id, "toolu_0001", "Bash", "ls recipes"),
            (2, thread.id, "toolu_0002", "mcp__pantry__find_items", "flour"),
            (2, thread.id, SPAWNING, "Agent", RECIPES),
            (3, thread.id, "toolu_0003", "Bash", "pytest tests/scaling"),
            (3, thread.id, "toolu_0004", "Bash", "git commit -m scaling"),
            (4, thread.id, "toolu_0005", "Bash", "ls recipes"),
        ]

    def test_a_tool_call_holds_when_it_ran_and_how_it_ended(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())

        facts = select(
            ToolCall.requested_at,
            ToolCall.returned_at,
            ToolCall.failed,
            ToolCall.exit_code,
            ToolCall.interrupted,
            ToolCall.denial_kind_code,
            ToolCall.result_characters,
            ToolCall.saved_characters,
        )

        def held(tool_use_id: str) -> tuple[Any, ...]:
            return tuple(
                session.execute(facts.where(ToolCall.tool_use_id == tool_use_id)).one()
            )

        def at(minutes: int, seconds: int = 0) -> datetime:
            return STARTED + timedelta(minutes=minutes, seconds=seconds)

        assert held("toolu_0001") == (
            at(1),
            at(1, 4),
            False,
            None,
            False,
            None,
            1_180,
            None,
        )
        assert held("toolu_0003") == (
            at(3),
            at(3, 4),
            True,
            1,
            False,
            None,
            2_000,
            412_000,
        )
        assert held("toolu_0004") == (
            at(4),
            at(4, 4),
            True,
            None,
            False,
            "hook",
            96,
            None,
        )
        assert held("toolu_0005") == (
            at(5),
            None,
            False,
            None,
            True,
            None,
            None,
            None,
        )

    def test_an_event_marks_its_call_in_the_files_order(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())

        assert session.execute(
            select(Call.position, Event.kind_code, Event.at, Event.detail)
            .join(Call, Call.id == Event.call_id)
            .order_by(Event.id)
        ).all() == [
            (2, "api_error", STARTED + timedelta(minutes=2, seconds=11), "529"),
            (2, "api_retry", STARTED + timedelta(minutes=2, seconds=19), None),
            (4, "interrupt", STARTED + timedelta(minutes=11), None),
        ]

    def test_a_context_part_hangs_on_the_call_that_first_carried_it(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())

        assert session.execute(
            select(
                Call.position,
                ContextPart.kind_code,
                ContextPart.name,
                ContextPart.characters,
            )
            .join(Call, Call.id == ContextPart.call_id)
            .order_by(ContextPart.id)
        ).all() == [
            (1, "system_prompt", None, 9_100),
            (1, "tool_schemas", None, 45_300),
            (1, "instruction_file", "CLAUDE.md", 2_400),
            (3, "skill_body", "recipe-scaling", 11_800),
        ]

    @pytest.mark.parametrize(
        ("entity", "codes"),
        [
            (Component, ["claude-code", "collector", "plugin:dev"]),
            (CompactionTrigger, ["auto"]),
            (
                ContextPartKind,
                ["instruction_file", "skill_body", "system_prompt", "tool_schemas"],
            ),
            (DenialKind, ["hook"]),
            (EventKind, ["api_error", "api_retry", "interrupt"]),
            (MissCause, ["compaction"]),
            (Model, [SONNET]),
            (PromptSource, ["person", "task_notification"]),
            (StopReason, ["max_tokens"]),
            (Tool, ["Agent", "Bash", "mcp__pantry__find_items"]),
        ],
    )
    def test_a_reference_code_pilot_has_not_met_is_written_named_by_its_code(
        self,
        session: DbSession,
        publications: PublicationService,
        entity: Any,
        codes: list[str],
    ) -> None:
        # The Models the price file names are held before any publication.
        rows = select(entity.code, entity.name).order_by(entity.code)
        held = session.execute(rows).all()

        publications.publish(_camp())

        assert session.execute(rows).all() == sorted(
            [*map(tuple, held), *((code, code) for code in codes)]
        )

    def test_a_reference_code_pilot_has_met_is_left_as_it_stands(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        session.execute(update(Model).where(Model.code == OPUS).values(name="Opus 4.5"))

        publications.publish(_camp())

        assert session.execute(
            select(Model.code, Model.name)
            .where(Model.code.in_([HAIKU, OPUS, SONNET]))
            .order_by(Model.code)
        ).all() == [
            (HAIKU, HAIKU),
            (OPUS, "Opus 4.5"),
            (SONNET, SONNET),
        ]

    def test_a_tool_is_written_with_the_mcp_server_it_is_of(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())

        assert session.execute(
            select(Tool.code, Tool.mcp_server).order_by(Tool.code)
        ).all() == [
            ("Agent", None),
            ("Bash", None),
            ("mcp__pantry__find_items", "pantry"),
        ]

    def test_an_event_kind_is_written_with_whether_it_is_an_error(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())

        assert session.execute(
            select(EventKind.code, EventKind.is_error).order_by(EventKind.code)
        ).all() == [("api_error", True), ("api_retry", False), ("interrupt", False)]

    def test_a_tool_and_an_event_kind_pilot_has_met_are_left_as_they_stand(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        session.add_all(
            [
                Tool(code="Bash", name="Shell", mcp_server="shell"),
                EventKind(code="api_retry", name="Retry", is_error=True),
            ]
        )
        session.flush()

        publications.publish(_camp())

        assert session.execute(
            select(Tool.name, Tool.mcp_server).where(Tool.code == "Bash")
        ).one() == ("Shell", "shell")
        assert session.execute(
            select(EventKind.name, EventKind.is_error).where(
                EventKind.code == "api_retry"
            )
        ).one() == ("Retry", True)

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

    def test_an_environment_the_fleet_stream_reports_is_written_as_reported(
        self,
        session: DbSession,
        publications: PublicationService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Its name and its exemption are the controller's from the row's
        first moment, so no timer of Pilot's stops an exempt environment a
        transcript named first."""
        report = ControllerEnvironment.model_validate(
            {
                "envId": "env-9c41",
                "name": "Recipes-1",
                "repo": "example/RecipeBox",
                "status": "stopped",
                "setupRunning": False,
                "capabilities": {"capacityExempt": {"enabled": True}},
            }
        )
        monkeypatch.setattr(
            publications.fleet_consumer, "environment", {"env-9c41": report}.get
        )
        before = datetime.now(UTC)

        thread = publications.publish(_camp(environment="env-9c41"))

        assert thread.environment_id == "env-9c41"
        row = session.get_one(Environment, "env-9c41")
        assert (row.name, row.exempt, row.last_state) == ("Recipes-1", True, "stopped")
        assert row.last_seen_at is not None and row.last_seen_at >= before
        assert (row.server_created_at, row.server_started_at) == (None, None)

    def test_an_environment_the_fleet_stream_has_not_given_is_written_named_by_its_id(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """With no `last_seen_at`: Pilot's first touch of it asks the
        controller (`TestEnsureEnvironment`)."""
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

    def test_a_sub_agents_thread_that_comes_second_is_joined_to_its_spawning_call(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())

        thread = publications.publish(sub_agent())

        assert thread.spawned_by_tool_use_id == SPAWNING
        assert thread.spawned_by_id == _tool_call_id(session)

    def test_a_sub_agents_thread_that_comes_first_holds_its_spawning_calls_name(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """DB decision 79.16: the name is held until what it names is."""
        thread = publications.publish(sub_agent())

        assert (thread.spawned_by_tool_use_id, thread.spawned_by_id) == (
            SPAWNING,
            None,
        )

        publications.publish(_camp())

        assert _spawned_by(session, thread) == _tool_call_id(session)

    def test_a_spawning_call_its_thread_brings_later_is_joined(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(whole(calls=[call(1)]))
        thread = publications.publish(sub_agent())

        assert thread.spawned_by_id is None

        publications.publish(
            whole(
                calls=[call(1, tool_calls=[tool_call(31, tool="Agent")])],
                file_size=50_000,
            )
        )

        assert _spawned_by(session, thread) == _tool_call_id(session)

    def test_the_join_outlives_a_main_thread_published_again(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        thread = publications.publish(sub_agent())
        spawning = _tool_call_id(session)

        with writes(session) as wrote:
            publications.publish(_camp())

        assert wrote == {"transcripts": Written(updated=1)}
        assert _spawned_by(session, thread) == spawning

    def test_the_join_outlives_a_sub_agents_thread_published_again(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        thread = publications.publish(sub_agent())

        with writes(session) as wrote:
            again = publications.publish(sub_agent())

        assert wrote == {"transcripts": Written(updated=1)}
        assert again.id == thread.id
        assert again.spawned_by_id == _tool_call_id(session)

    def test_a_sub_agent_another_sub_agent_started_is_joined_to_that_ones_call(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """DB 535: its spawning call lies in a thread under its main thread."""
        publications.publish(_camp())
        deeper = publications.publish(
            sub_agent(agent_id=DEEPER, agent_type="Plan", spawned_by="toolu_0041")
        )

        starter = publications.publish(
            sub_agent(calls=[call(1, tool_calls=[tool_call(41, tool="Agent")])])
        )

        assert session.execute(
            select(ToolCall.tool_use_id, ToolCall.transcript_id).where(
                ToolCall.id == _spawned_by(session, deeper)
            )
        ).one() == ("toolu_0041", starter.id)

    def test_a_sub_agent_whose_spawning_call_no_thread_holds_is_joined_to_none(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())

        thread = publications.publish(sub_agent(spawned_by="toolu_0099"))

        assert (thread.spawned_by_tool_use_id, thread.spawned_by_id) == (
            "toolu_0099",
            None,
        )

    def test_a_sub_agent_is_joined_to_no_call_of_another_conversation(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp(session_id=OTHER))

        thread = publications.publish(sub_agent())

        assert thread.spawned_by_id is None

    def test_a_sub_agent_is_joined_to_no_call_of_its_own(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(
            sub_agent(calls=[call(1, tool_calls=[tool_call(31, tool="Agent")])])
        )

        assert thread.spawned_by_id is None

    def test_a_name_two_other_threads_hold_joins_to_neither(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """A `tool_use_id` is unique within its Transcript alone."""
        publications.publish(_camp())
        publications.publish(
            sub_agent(
                agent_id=DEEPER,
                spawned_by=None,
                calls=[call(1, tool_calls=[tool_call(31, tool="Agent")])],
            )
        )

        thread = publications.publish(sub_agent())

        assert thread.spawned_by_id is None

    def test_a_sub_agent_whose_record_names_another_call_is_joined_to_that_one(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        thread = publications.publish(sub_agent())

        publications.publish(sub_agent(spawned_by="toolu_0001"))

        assert _spawned_by(session, thread) == _tool_call_id(session, "toolu_0001")

    def test_a_sub_agent_whose_record_names_no_call_any_more_is_joined_to_none(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        publications.publish(sub_agent())

        thread = publications.publish(sub_agent(spawned_by=None))

        assert (thread.spawned_by_tool_use_id, thread.spawned_by_id) == (None, None)

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
            ToolCall,
            Event,
            ContextPart,
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

    def test_a_call_whose_tokens_differ_is_priced_again(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        calls = _calls()
        calls[3]["tokens"] = {"input": 2_000, "output": 400}

        with writes(session) as wrote:
            publications.publish(_camp(calls=calls))

        assert wrote == {
            "transcripts": Written(updated=1),
            "calls": Written(updated=1),
        }
        assert session.execute(
            select(Call.context_tokens, Call.cost).where(Call.position == 4)
        ).all() == [(2_000, Decimal("0.02"))]

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

    def test_what_a_new_call_did_is_written_with_it(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        ids = _ids(session)
        grown = [
            *_calls(),
            call(
                5,
                prompt=3,
                predecessor="msg_0004",
                tool_calls=[tool_call(6)],
                events=[event(at=_at(13))],
                context_parts=[context_part(kind="reminder", characters=310)],
            ),
        ]

        with writes(session) as wrote:
            publications.publish(_camp(calls=grown, file_size=61_000))

        assert wrote == {
            "transcripts": Written(updated=1),
            "calls": Written(inserted=1),
            "tool_calls": Written(inserted=1),
            "events": Written(inserted=1),
            "context_parts": Written(inserted=1),
            "context_part_kinds": Written(inserted=1),
        }
        after = _ids(session)
        for table in ("tool_calls", "events", "context_parts"):
            assert after[table][:-1] == ids[table]
        new = after["calls"][-1]
        assert (
            session.scalars(
                select(ToolCall.call_id).where(ToolCall.tool_use_id == "toolu_0006")
            ).one()
            == new
        )
        assert (
            session.scalars(
                select(Event.call_id).where(Event.id == after["events"][-1])
            ).one()
            == new
        )
        assert session.execute(
            select(ContextPart.call_id, ContextPart.kind_code).where(
                ContextPart.id == after["context_parts"][-1]
            )
        ).one() == (new, "reminder")

    def test_what_a_held_call_did_since_is_written_after_what_it_held(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        ids = _ids(session)
        calls = _calls()
        calls[1]["tool_calls"].append(tool_call(6))
        calls[1]["events"].append(
            event(kind="api_retry", is_error=False, at=_at(3), detail=None)
        )
        calls[0]["context_parts"].append(context_part(kind="reminder", characters=310))

        with writes(session) as wrote:
            publications.publish(_camp(calls=calls))

        assert wrote == {
            "transcripts": Written(updated=1),
            "tool_calls": Written(inserted=1),
            "events": Written(inserted=1),
            "context_parts": Written(inserted=1),
            "context_part_kinds": Written(inserted=1),
        }
        after = _ids(session)
        for table in ("tool_calls", "events", "context_parts"):
            assert after[table][:-1] == ids[table]
        assert session.execute(
            select(Event.kind_code, Event.at)
            .join(Call, Call.id == Event.call_id)
            .where(Call.position == 2)
            .order_by(Event.id)
        ).all() == [
            ("api_error", STARTED + timedelta(minutes=2, seconds=11)),
            ("api_retry", STARTED + timedelta(minutes=2, seconds=19)),
            ("api_retry", STARTED + timedelta(minutes=3)),
        ]

    def test_a_tool_call_that_returned_since_is_the_row_written(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        ids = _ids(session)
        calls = _calls()
        calls[3]["tool_calls"][0] |= {
            "returned_at": _at(12),
            "interrupted": False,
            "result_characters": 512,
        }

        with writes(session) as wrote:
            publications.publish(_camp(calls=calls))

        assert wrote == {
            "transcripts": Written(updated=1),
            "tool_calls": Written(updated=1),
        }
        assert _ids(session) == ids
        assert session.execute(
            select(
                ToolCall.returned_at, ToolCall.interrupted, ToolCall.result_characters
            ).where(ToolCall.tool_use_id == "toolu_0005")
        ).one() == (STARTED + timedelta(minutes=12), False, 512)

    def test_an_event_and_a_context_part_whose_facts_differ_are_written_in_place(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        ids = _ids(session)
        calls = _calls()
        calls[1]["events"][1]["detail"] = "second try"
        calls[0]["context_parts"][1]["characters"] = 46_000

        with writes(session) as wrote:
            publications.publish(_camp(calls=calls))

        assert wrote == {
            "transcripts": Written(updated=1),
            "events": Written(updated=1),
            "context_parts": Written(updated=1),
        }
        assert _ids(session) == ids
        assert session.execute(
            select(Event.kind_code, Event.detail).where(Event.id == ids["events"][1])
        ).one() == ("api_retry", "second try")
        assert session.execute(
            select(ContextPart.kind_code, ContextPart.characters).where(
                ContextPart.id == ids["context_parts"][1]
            )
        ).one() == ("tool_schemas", 46_000)

    def test_a_tool_call_is_found_again_by_its_tool_use_id_under_another_call(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        held = _tool_call_id(session, "toolu_0001")
        calls = _calls()
        calls[1]["tool_calls"].append(calls[0]["tool_calls"].pop())

        with writes(session) as wrote:
            publications.publish(_camp(calls=calls))

        assert wrote == {
            "transcripts": Written(updated=1),
            "tool_calls": Written(updated=1),
        }
        assert session.execute(
            select(ToolCall.id, Call.position)
            .join(Call, Call.id == ToolCall.call_id)
            .where(ToolCall.tool_use_id == "toolu_0001")
        ).one() == (held, 2)

    def test_two_conversations_tool_calls_of_one_name_are_two_tool_calls(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())

        publications.publish(_camp(session_id=OTHER))

        assert _count(session, ToolCall) == 12

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


class TestRewritten:
    """A transcript whose file no longer has what Pilot holds of it, published
    whole: Pilot follows the file. What the call no longer names goes with
    what hangs on it, the rest stays as it was, and the Transcript stays
    whatever its file lost."""

    def test_the_calls_a_file_lost_go_with_what_hangs_on_them(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        ids = _ids(session)

        with writes(session) as wrote:
            publications.publish(_camp(calls=_calls()[:2]))

        assert wrote == {
            "transcripts": Written(updated=1),
            "calls": Written(deleted=2),
            "tool_calls": Written(deleted=3),
            "events": Written(deleted=1),
            "context_parts": Written(deleted=1),
        }
        assert _ids(session) == ids | {
            "calls": ids["calls"][:2],
            "tool_calls": ids["tool_calls"][:3],
            "events": ids["events"][:2],
            "context_parts": ids["context_parts"][:3],
        }

    def test_the_number_of_calls_lost_is_logged_with_the_conversation(
        self,
        session: DbSession,
        publications: PublicationService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        publications.publish(_camp())

        with caplog.at_level(logging.WARNING, LOGGER):
            publications.publish(_camp(calls=_calls()[:1]))

        assert [
            record.getMessage() for record in caplog.records if record.name == LOGGER
        ] == [f"Transcript {CAMP} no longer has 3 of the calls Pilot held"]

    def test_a_sub_agents_lost_calls_are_logged_with_its_thread(
        self,
        session: DbSession,
        publications: PublicationService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        publications.publish(
            sub_agent(calls=[call(1), call(2, predecessor="msg_0001")])
        )

        with caplog.at_level(logging.WARNING, LOGGER):
            publications.publish(sub_agent(calls=[call(1)]))

        assert [
            record.getMessage() for record in caplog.records if record.name == LOGGER
        ] == [f"Transcript {CAMP}/{SUB_AGENT} no longer has 1 of the calls Pilot held"]
        assert session.scalars(select(Call.message_id)).all() == ["msg_0001"]

    def test_nothing_is_logged_where_no_call_is_lost(
        self,
        session: DbSession,
        publications: PublicationService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Other facts the file lost are no lost call."""
        publications.publish(_camp())
        calls = _calls()
        calls[2]["tool_calls"].pop()
        calls[1]["events"].pop()

        with caplog.at_level(logging.DEBUG, LOGGER):
            publications.publish(_camp())
            publications.publish(
                _camp(calls=[*calls, call(5, prompt=3, predecessor="msg_0004")])
            )

        assert [record for record in caplog.records if record.name == LOGGER] == []

    def test_a_call_lost_from_the_middle_goes_and_the_ones_after_it_move_up(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """The Call that followed the lost one keeps its identity, and names
        the Call the file now has before it."""
        publications.publish(_camp())
        ids = _ids(session)
        calls = _calls()
        del calls[2]
        calls[2]["predecessor"] = "msg_0002"

        with writes(session) as wrote:
            publications.publish(_camp(calls=calls))

        assert wrote == {
            "transcripts": Written(updated=1),
            "calls": Written(updated=1, deleted=1),
            "tool_calls": Written(deleted=2),
            "context_parts": Written(deleted=1),
        }
        first, second, _, fourth = ids["calls"]
        assert session.execute(
            select(
                Call.id, Call.message_id, Call.position, Call.predecessor_id
            ).order_by(Call.position)
        ).all() == [
            (first, "msg_0001", 1, None),
            (second, "msg_0002", 2, first),
            (fourth, "msg_0004", 3, second),
        ]
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    def test_a_call_the_file_has_in_a_lost_calls_place_stands_there(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        ids = _ids(session)
        calls = _calls()
        calls[3] = call(9, prompt=3, predecessor="msg_0003")

        with writes(session) as wrote:
            publications.publish(_camp(calls=calls))

        assert wrote == {
            "transcripts": Written(updated=1),
            "calls": Written(inserted=1, deleted=1),
            "tool_calls": Written(deleted=1),
            "events": Written(deleted=1),
        }
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        after = _ids(session)
        assert after["calls"][:3] == ids["calls"][:3]
        assert session.execute(
            select(Call.id, Call.message_id).where(Call.position == 4)
        ).all() == [(after["calls"][3], "msg_0009")]
        assert after["calls"][3] != ids["calls"][3]

    def test_a_lost_calls_tool_call_the_file_has_under_another_call_stays(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """A Tool Call is found again by its `tool_use_id`, so the one a kept
        Call now requested keeps its identity through its old Call's loss."""
        publications.publish(_camp())
        held = _tool_call_id(session, "toolu_0003")
        calls = _calls()[:2]
        calls[1]["tool_calls"].append(_calls()[2]["tool_calls"][0])

        with writes(session) as wrote:
            publications.publish(_camp(calls=calls))

        assert wrote == {
            "transcripts": Written(updated=1),
            "calls": Written(deleted=2),
            "tool_calls": Written(updated=1, deleted=2),
            "events": Written(deleted=1),
            "context_parts": Written(deleted=1),
        }
        assert session.execute(
            select(ToolCall.id, Call.position)
            .join(Call, Call.id == ToolCall.call_id)
            .where(ToolCall.tool_use_id == "toolu_0003")
        ).one() == (held, 2)

    def test_a_tool_call_a_kept_call_no_longer_requested_goes(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        ids = _ids(session)
        calls = _calls()
        calls[2]["tool_calls"].pop()

        with writes(session) as wrote:
            publications.publish(_camp(calls=calls))

        assert wrote == {
            "transcripts": Written(updated=1),
            "tool_calls": Written(deleted=1),
        }
        gone = ids["tool_calls"][4]
        assert _ids(session) == ids | {
            "tool_calls": [held for held in ids["tool_calls"] if held != gone]
        }
        assert session.scalars(
            select(ToolCall.tool_use_id).order_by(ToolCall.id)
        ).all() == ["toolu_0001", "toolu_0002", SPAWNING, "toolu_0003", "toolu_0005"]

    def test_an_event_and_a_context_part_past_a_kept_calls_last_go(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        ids = _ids(session)
        calls = _calls()
        calls[1]["events"].pop()
        del calls[0]["context_parts"][1:]

        with writes(session) as wrote:
            publications.publish(_camp(calls=calls))

        assert wrote == {
            "transcripts": Written(updated=1),
            "events": Written(deleted=1),
            "context_parts": Written(deleted=2),
        }
        assert _ids(session) == ids | {
            "events": [ids["events"][0], ids["events"][2]],
            "context_parts": [ids["context_parts"][0], ids["context_parts"][3]],
        }

    def test_a_launch_the_file_lost_goes_with_its_versions_prompts_and_hook_runs(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        resumed = _second_launch(
            prompts=[prompt(received_at=_at(10), characters=31, hook_runs=[hook_run()])]
        )
        publications.publish(_camp(launches=[_first_launch(), resumed]))
        ids = _ids(session)
        versions = _count(session, ComponentVersion)

        with writes(session) as wrote:
            publications.publish(_camp(launches=[_first_launch()], calls=_calls()[:3]))

        assert wrote == {
            "transcripts": Written(updated=1),
            "launches": Written(deleted=1),
            "launch_components": Written(deleted=2),
            "prompts": Written(deleted=1),
            "hook_runs": Written(deleted=1),
            "calls": Written(deleted=1),
            "tool_calls": Written(deleted=1),
            "events": Written(deleted=1),
        }
        assert _ids(session) == ids | {
            "launches": ids["launches"][:1],
            "prompts": ids["prompts"][:2],
            "hook_runs": ids["hook_runs"][:2],
            "calls": ids["calls"][:3],
            "tool_calls": ids["tool_calls"][:5],
            "events": ids["events"][:2],
        }
        assert session.scalars(select(LaunchComponent.launch_id)).all() == (
            ids["launches"][:1] * 2
        )
        assert _count(session, ComponentVersion) == versions

    def test_a_call_that_followed_a_lost_launchs_prompt_stays_under_the_one_it_names(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        ids = _ids(session)
        calls = _calls()
        calls[3]["prompt"] = 2

        with writes(session) as wrote:
            publications.publish(_camp(launches=[_first_launch()], calls=calls))

        assert wrote == {
            "transcripts": Written(updated=1),
            "launches": Written(deleted=1),
            "launch_components": Written(deleted=2),
            "prompts": Written(deleted=1),
            "calls": Written(updated=1),
        }
        assert _ids(session) == ids | {
            "launches": ids["launches"][:1],
            "prompts": ids["prompts"][:2],
        }
        assert session.scalars(
            select(Call.prompt_id).order_by(Call.position)
        ).all() == [ids["prompts"][i] for i in (0, 0, 1, 1)]

    def test_a_prompt_and_a_hook_run_past_their_parents_last_go(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """The first Launch lost its second Prompt, and its first Prompt its
        second Hook Run; the Calls after the lost Prompt follow the resumed
        Launch's, now the file's second."""
        publications.publish(_camp())
        ids = _ids(session)
        first = _first_launch()
        del first["prompts"][1:]
        del first["prompts"][0]["hook_runs"][1:]
        calls = _calls()
        calls[3]["prompt"] = 2

        with writes(session) as wrote:
            publications.publish(_camp(launches=[first, _second_launch()], calls=calls))

        assert wrote == {
            "transcripts": Written(updated=1),
            "prompts": Written(deleted=1),
            "hook_runs": Written(deleted=1),
            "calls": Written(updated=1),
        }
        opening, _, resuming = ids["prompts"]
        assert _ids(session) == ids | {
            "prompts": [opening, resuming],
            "hook_runs": ids["hook_runs"][:1],
        }
        assert session.scalars(
            select(Call.prompt_id).order_by(Call.position)
        ).all() == [opening, opening, resuming, resuming]

    def test_a_compaction_the_file_lost_goes(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        ids = _ids(session)
        calls = _calls()
        del calls[2]["compaction"]

        with writes(session) as wrote:
            publications.publish(_camp(compactions=[], calls=calls))

        assert wrote == {
            "transcripts": Written(updated=1),
            "compactions": Written(deleted=1),
            "calls": Written(updated=1),
        }
        assert _ids(session) == ids | {"compactions": []}
        assert session.scalars(select(Call.compaction_id)).all() == [None] * 4

    def test_a_version_a_launch_no_longer_ran_with_goes_from_it_alone(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        ids = _ids(session)
        versions = _count(session, ComponentVersion)

        with writes(session) as wrote:
            publications.publish(
                _camp(
                    launches=[
                        _first_launch(),
                        _second_launch(components=[CLAUDE_CODE]),
                    ]
                )
            )

        assert wrote == {
            "transcripts": Written(updated=1),
            "launch_components": Written(deleted=1),
        }
        opened, resumed = ids["launches"]
        assert session.execute(
            select(LaunchComponent.launch_id, LaunchComponent.component_code).order_by(
                LaunchComponent.launch_id, LaunchComponent.component_code
            )
        ).all() == [
            (opened, "claude-code"),
            (opened, "plugin:dev"),
            (resumed, "claude-code"),
        ]
        assert _count(session, ComponentVersion) == versions

    def test_a_sub_agent_whose_spawning_tool_call_goes_stays_and_keeps_its_name(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        main = publications.publish(_camp())
        thread = publications.publish(sub_agent())
        calls = _calls()
        calls[1]["tool_calls"].pop()

        with writes(session) as wrote:
            publications.publish(_camp(calls=calls))

        assert wrote == {
            "transcripts": Written(updated=2),
            "tool_calls": Written(deleted=1),
        }
        assert session.execute(
            select(
                Transcript.main_id,
                Transcript.spawned_by_id,
                Transcript.spawned_by_tool_use_id,
            ).where(Transcript.id == thread.id)
        ).one() == (main.id, None, SPAWNING)

    def test_a_sub_agent_is_joined_again_when_its_spawning_call_comes_back(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """The Call that started it went, and its Tool Call with it; the one
        the file has again is another row of the same name."""
        publications.publish(_camp())
        thread = publications.publish(sub_agent())
        lost = _tool_call_id(session)
        publications.publish(_camp(calls=_calls()[:1]))
        assert _spawned_by(session, thread) is None

        publications.publish(_camp())

        back = _tool_call_id(session)
        assert back != lost
        assert _spawned_by(session, thread) == back

    def test_a_transcript_whose_file_lost_everything_stays(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """F119.2: nothing removes a Transcript, a sub-agent's under its main
        thread included; a reference code it named stays too."""
        main = publications.publish(_camp())
        thread = publications.publish(
            sub_agent(calls=[call(1, tool_calls=[tool_call(40)])])
        )
        codes = {
            entity: _count(session, entity)
            for entity in (Model, Tool, EventKind, ContextPartKind, PromptSource)
        }

        publications.publish(whole(file_size=0))
        publications.publish(sub_agent(file_size=0))

        after = _ids(session)
        assert set(after.pop("transcripts")) == {main.id, thread.id}
        assert [table for table, held in after.items() if held] == []
        assert _count(session, LaunchComponent) == 0
        assert session.execute(
            select(Transcript.main_id, Transcript.file_size).where(
                Transcript.id == thread.id
            )
        ).one() == (main.id, 0)
        assert {entity: _count(session, entity) for entity in codes} == codes


class TestAppended:
    """A transcript that grew, published appended (F152.15; DB decision 81
    point 1): from its boundary on Pilot holds what the call carries, and
    what lies before it is not written."""

    def test_a_call_made_since_is_the_row_written(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        first = publications.publish(_camp())
        ids = _ids(session)

        with writes(session) as wrote:
            thread = publications.publish(_grown())

        assert thread.id == first.id
        assert wrote == {
            "transcripts": Written(updated=1),
            "calls": Written(inserted=1),
        }
        after = _ids(session)
        assert after == ids | {"calls": [*ids["calls"], after["calls"][4]]}
        assert session.execute(
            select(
                Call.message_id, Call.position, Call.predecessor_id, Call.prompt_id
            ).where(Call.id == after["calls"][4])
        ).one() == ("msg_0005", 5, ids["calls"][3], ids["prompts"][2])

    def test_a_call_made_since_holds_its_cost(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())

        publications.publish(_grown())

        assert session.execute(
            select(Call.context_tokens, Call.cost).where(Call.position == 5)
        ).all() == [(52_626, Decimal("0.134926"))]

    def test_a_call_names_one_before_the_boundary_as_its_predecessor(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        ids = _ids(session)

        with writes(session) as wrote:
            publications.publish(
                _grown(call=5, calls=[call(5, prompt=1, predecessor="msg_0002")])
            )

        assert wrote == {
            "transcripts": Written(updated=1),
            "calls": Written(inserted=1),
        }
        assert session.execute(
            select(Call.position, Call.predecessor_id, Call.prompt_id).where(
                Call.message_id == "msg_0005"
            )
        ).one() == (5, ids["calls"][1], ids["prompts"][0])

    def test_a_held_call_from_the_boundary_on_takes_what_the_call_says(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        ids = _ids(session)
        fourth = _calls()[3] | {
            "thinking_tokens": 120,
            "tool_calls": [tool_call(5, interrupted=True)],
            "events": [
                event(kind="interrupt", is_error=False, at=_at(11), detail=None),
                event(kind="api_retry", is_error=False, at=_at(12), detail=None),
            ],
            "context_parts": [context_part(kind="memory", characters=310)],
        }

        with writes(session) as wrote:
            publications.publish(_grown(calls=[fourth]))

        assert wrote == {
            "transcripts": Written(updated=1),
            "calls": Written(updated=1),
            "tool_calls": Written(updated=1),
            "events": Written(inserted=1),
            "context_parts": Written(inserted=1),
            "context_part_kinds": Written(inserted=1),
        }
        after = _ids(session)
        assert after["calls"] == ids["calls"]
        assert after["tool_calls"] == ids["tool_calls"]
        assert after["events"][:3] == ids["events"]
        assert session.execute(
            select(Call.position, Call.thinking_tokens, ToolCall.returned_at)
            .join(ToolCall, ToolCall.call_id == Call.id)
            .where(Call.message_id == "msg_0004")
        ).one() == (4, 120, STARTED + timedelta(minutes=5, seconds=4))

    def test_what_hung_on_a_carried_call_and_it_no_longer_names_goes(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        ids = _ids(session)
        fourth = _calls()[3] | {"tool_calls": [], "events": []}

        with writes(session) as wrote:
            publications.publish(_grown(calls=[fourth]))

        assert wrote == {
            "transcripts": Written(updated=1),
            "tool_calls": Written(deleted=1),
            "events": Written(deleted=1),
        }
        assert _ids(session) == ids | {
            "tool_calls": ids["tool_calls"][:5],
            "events": ids["events"][:2],
        }

    def test_what_a_call_before_the_boundary_did_is_left_as_pilot_holds_it(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """The second Call's Tool Calls, Events and Context Parts are no part
        of a call whose boundary lies after it."""
        publications.publish(_camp())
        held = session.execute(
            select(ToolCall.tool_use_id, ToolCall.call_id).order_by(ToolCall.id)
        ).all()
        marked = session.execute(
            select(Event.kind_code, Event.call_id).order_by(Event.id)
        ).all()

        publications.publish(
            _grown(
                calls=[
                    _calls()[3],
                    call(
                        5,
                        prompt=3,
                        predecessor="msg_0004",
                        tool_calls=[tool_call(6)],
                        events=[event()],
                    ),
                ]
            )
        )

        assert (
            session.execute(
                select(ToolCall.tool_use_id, ToolCall.call_id).order_by(ToolCall.id)
            ).all()[:6]
            == held
        )
        assert (
            session.execute(
                select(Event.kind_code, Event.call_id).order_by(Event.id)
            ).all()[:3]
            == marked
        )

    def test_a_prompt_received_since_hangs_on_the_launch_the_file_grew_under(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        ids = _ids(session)
        since = prompt(received_at=_at(15), characters=64, hook_runs=[hook_run()])

        with writes(session) as wrote:
            publications.publish(
                _grown(
                    launches=[_second_launch(prompts=[since])],
                    calls=[_calls()[3], call(5, prompt=4, predecessor="msg_0004")],
                )
            )

        assert wrote == {
            "transcripts": Written(updated=1),
            "prompts": Written(inserted=1),
            "hook_runs": Written(inserted=1),
            "calls": Written(inserted=1),
        }
        after = _ids(session)
        assert after["prompts"][:3] == ids["prompts"]
        assert session.execute(
            select(Prompt.launch_id, Prompt.characters, Call.message_id)
            .join(Call, Call.prompt_id == Prompt.id)
            .where(Prompt.id == after["prompts"][3])
        ).all() == [(ids["launches"][1], 64, "msg_0005")]
        assert (
            session.scalars(
                select(HookRun.prompt_id).where(HookRun.id == after["hook_runs"][2])
            ).one()
            == after["prompts"][3]
        )

    def test_a_held_prompt_named_again_takes_the_hook_runs_at_its_runs_end(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        ids = _ids(session)
        third = prompt(received_at=_at(10), characters=31, hook_runs=[hook_run()])

        with writes(session) as wrote:
            publications.publish(
                _grown(prompt=3, launches=[_second_launch(prompts=[third])])
            )

        assert wrote == {
            "transcripts": Written(updated=1),
            "hook_runs": Written(inserted=1),
            "calls": Written(inserted=1),
        }
        after = _ids(session)
        assert after["prompts"] == ids["prompts"]
        assert (
            session.scalars(
                select(HookRun.prompt_id).where(HookRun.id == after["hook_runs"][2])
            ).one()
            == ids["prompts"][2]
        )

    def test_a_boundary_within_a_launch_leaves_its_earlier_prompts(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """The first Launch's second Prompt on: its first, with its two Hook
        Runs, is no part of the call."""
        publications.publish(_camp())
        ids = _ids(session)
        second = prompt(
            received_at=_at(4),
            source="task_notification",
            characters=90,
            hook_runs=[hook_run(command="tidy_pantry.sh")],
        )

        with writes(session) as wrote:
            publications.publish(
                _grown(
                    launch=1,
                    prompt=2,
                    launches=[_first_launch(prompts=[second]), _second_launch()],
                )
            )

        assert wrote == {
            "transcripts": Written(updated=1),
            "prompts": Written(updated=1),
            "hook_runs": Written(inserted=1),
            "calls": Written(inserted=1),
        }
        after = _ids(session)
        assert after["prompts"] == ids["prompts"]
        assert after["hook_runs"][:2] == ids["hook_runs"]
        assert session.execute(
            select(HookRun.prompt_id, HookRun.command).order_by(HookRun.id)
        ).all() == [
            (ids["prompts"][0], "signal_activity.sh"),
            (ids["prompts"][0], "hold_open.sh"),
            (ids["prompts"][1], "tidy_pantry.sh"),
        ]
        assert session.scalars(select(Prompt.characters).order_by(Prompt.id)).all() == [
            212,
            90,
            31,
        ]

    def test_a_compaction_made_since_is_written_after_the_held_one(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        ids = _ids(session)

        with writes(session) as wrote:
            publications.publish(
                _grown(
                    compactions=[compaction(at=_at(13), tokens_before=150_000)],
                    calls=[
                        _calls()[3],
                        call(5, prompt=3, predecessor="msg_0004", compaction=2),
                    ],
                )
            )

        assert wrote == {
            "transcripts": Written(updated=1),
            "compactions": Written(inserted=1),
            "calls": Written(inserted=1),
        }
        after = _ids(session)
        assert after["compactions"][:1] == ids["compactions"]
        assert session.execute(
            select(Call.message_id, Compaction.tokens_before)
            .join(Compaction, Compaction.id == Call.compaction_id)
            .order_by(Call.position)
        ).all() == [("msg_0003", 160_000), ("msg_0005", 150_000)]

    def test_a_held_compaction_named_again_takes_what_the_call_says(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        ids = _ids(session)

        with writes(session) as wrote:
            publications.publish(
                _grown(
                    compaction=1,
                    compactions=[compaction(tokens_after=22_400, duration_ms=5_200)],
                )
            )

        assert wrote == {
            "transcripts": Written(updated=1),
            "compactions": Written(updated=1),
            "calls": Written(inserted=1),
        }
        assert session.execute(
            select(Compaction.id, Compaction.tokens_after)
        ).all() == [(ids["compactions"][0], 22_400)]

    def test_a_launch_begun_since_is_written_and_the_held_one_takes_its_end(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """The Launch the file grew under keeps its identity, and the one
        before it, which the call does not carry, is not written."""
        publications.publish(_camp())
        ids = _ids(session)
        third = launch(
            started_at=_at(20),
            components=[CLAUDE_CODE, {"component": "plugin:dev", "version": "0.10.56"}],
            prompts=[prompt(received_at=_at(20))],
        )

        with writes(session) as wrote:
            publications.publish(
                _grown(
                    launches=[_second_launch(prompts=[], ended_at=_at(14)), third],
                    calls=[_calls()[3], call(5, prompt=4, predecessor="msg_0004")],
                )
            )

        assert wrote == {
            "transcripts": Written(updated=1),
            "launches": Written(inserted=1, updated=1),
            "component_versions": Written(inserted=1),
            "launch_components": Written(inserted=2),
            "prompts": Written(inserted=1),
            "calls": Written(inserted=1),
        }
        after = _ids(session)
        assert after["launches"][:2] == ids["launches"]
        assert session.execute(
            select(Launch.started_at, Launch.ended_at).order_by(Launch.id)
        ).all() == [
            (STARTED, STARTED + timedelta(minutes=9)),
            (STARTED + timedelta(minutes=10), STARTED + timedelta(minutes=14)),
            (STARTED + timedelta(minutes=20), None),
        ]
        assert session.execute(
            select(ComponentVersion.component_code, ComponentVersion.version)
            .join(
                LaunchComponent,
                LaunchComponent.component_version_id == ComponentVersion.id,
            )
            .where(LaunchComponent.launch_id == after["launches"][2])
            .order_by(ComponentVersion.component_code)
        ).all() == [("claude-code", "2.1.317"), ("plugin:dev", "0.10.56")]
        assert session.execute(
            select(Prompt.launch_id, Call.message_id)
            .join(Call, Call.prompt_id == Prompt.id)
            .where(Prompt.id == after["prompts"][3])
        ).all() == [(after["launches"][2], "msg_0005")]

    def test_the_file_is_held_at_its_new_size_and_replayed_as_far_as_it_was(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """DB 605: `replayed_size` is the file's size at its last whole
        publication, through every appended one since."""
        publications.publish(_camp())

        def held() -> Any:
            return session.execute(
                select(
                    Transcript.file_size,
                    Transcript.replayed_size,
                    Transcript.file_modified_at,
                    ComponentVersion.version,
                ).join(
                    ComponentVersion, ComponentVersion.id == Transcript.read_under_id
                )
            ).one()

        publications.publish(_grown())
        assert held() == (61_000, 48_112, STARTED + timedelta(minutes=30), "1.0.0")

        sixth = call(6, prompt=3, predecessor="msg_0005")
        publications.publish(
            _grown(
                call=5,
                file_size=70_000,
                file_modified_at=_at(40),
                builds_on=builds_on(file_size=61_000, file_modified_at=_at(30)),
                calls=[call(5, prompt=3, predecessor="msg_0004"), sixth],
            )
        )
        assert held() == (70_000, 48_112, STARTED + timedelta(minutes=40), "1.0.0")

        publications.publish(
            _camp(
                file_size=70_000,
                file_modified_at=_at(40),
                calls=[*_calls(), call(5, prompt=3, predecessor="msg_0004"), sixth],
            )
        )
        assert held() == (70_000, 70_000, STARTED + timedelta(minutes=40), "1.0.0")
        assert session.scalars(select(Call.position).order_by(Call.position)).all() == [
            1,
            2,
            3,
            4,
            5,
            6,
        ]

    def test_a_sub_agents_thread_is_appended_to(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        main = publications.publish(_camp())
        thread = publications.publish(sub_agent(calls=[call(1)]))

        with writes(session) as wrote:
            publications.publish(
                appended(
                    agent_id=SUB_AGENT,
                    agent_type="Explore",
                    description=RECIPES,
                    spawned_by=SPAWNING,
                    calls=[call(1), call(2, predecessor="msg_0001")],
                )
            )

        assert wrote == {
            "transcripts": Written(updated=1),
            "calls": Written(inserted=1),
        }
        assert session.execute(
            select(
                Transcript.main_id, Transcript.spawned_by_id, Transcript.file_size
            ).where(Transcript.id == thread.id)
        ).one() == (main.id, _tool_call_id(session), 61_000)
        assert session.scalars(
            select(Call.message_id)
            .where(Call.transcript_id == thread.id)
            .order_by(Call.position)
        ).all() == ["msg_0001", "msg_0002"]

    def test_a_spawning_call_an_appended_call_brings_is_joined(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        thread = publications.publish(
            sub_agent(agent_id=DEEPER, spawned_by="toolu_0040")
        )
        assert _spawned_by(session, thread) is None
        fifth = call(
            5,
            prompt=3,
            predecessor="msg_0004",
            tool_calls=[tool_call(40, tool="Agent")],
        )

        publications.publish(_grown(calls=[_calls()[3], fifth]))

        assert _spawned_by(session, thread) == _tool_call_id(session, "toolu_0040")

    def test_a_reference_code_an_appended_call_first_names_is_written(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        fifth = call(5, prompt=3, predecessor="msg_0004", stop_reason="refusal")

        with writes(session) as wrote:
            publications.publish(_grown(calls=[_calls()[3], fifth]))

        assert wrote == {
            "transcripts": Written(updated=1),
            "stop_reasons": Written(inserted=1),
            "calls": Written(inserted=1),
        }


class TestNotAppendable:
    """An appended call that does not continue what Pilot holds of its
    Transcript is refused, and writes nothing: the collector publishes the
    transcript whole (F152.15)."""

    @pytest.mark.parametrize(
        ("publication", "cause"),
        [
            (
                _grown(builds_on=builds_on(file_size=48_000)),
                "Pilot holds it at another size, time or collector's version than"
                " the call builds on",
            ),
            (
                _grown(builds_on=builds_on(file_modified_at=_at(11))),
                "Pilot holds it at another size, time or collector's version than"
                " the call builds on",
            ),
            (
                _grown(builds_on=builds_on(collector="1.1.0")),
                "Pilot holds it at another size, time or collector's version than"
                " the call builds on",
            ),
            (
                _grown(call=6, calls=[call(6, prompt=3)]),
                "the boundary's `call` is 6, and Pilot holds 4 calls",
            ),
            (
                _grown(launch=4, launches=[launch(started_at=_at(20))]),
                "the boundary's `launch` is 4, and Pilot holds 2 launches",
            ),
            (
                _grown(prompt=5),
                "the boundary's `prompt` is 5, which is neither a prompt Pilot"
                " holds under the boundary's launch nor the next under it",
            ),
            (
                _grown(prompt=2, calls=[call(4)]),
                "the boundary's `prompt` is 2, which is neither a prompt Pilot"
                " holds under the boundary's launch nor the next under it",
            ),
            (
                _grown(compaction=3),
                "the boundary's `compaction` is 3, and Pilot holds 1 compactions",
            ),
            (
                _grown(launch=1, prompt=1, launches=[_first_launch()], calls=[call(4)]),
                "the call carries 1 launches from its boundary on, and Pilot holds 2",
            ),
            (
                _grown(
                    launch=1,
                    prompt=1,
                    launches=[_first_launch(prompts=[prompt()]), _second_launch()],
                    calls=[call(4)],
                ),
                "launch 1: the call carries fewer prompts than Pilot holds under it",
            ),
            (
                _grown(prompt=3, calls=[call(4)]),
                "launch 2: the call carries fewer prompts than Pilot holds under it",
            ),
            (
                _grown(compaction=1),
                "the call carries 0 compactions from its boundary on, and Pilot"
                " holds 1",
            ),
            (
                _grown(
                    launches=[
                        launch(
                            started_at=_at(20), prompts=[prompt(received_at=_at(20))]
                        )
                    ],
                    calls=[_calls()[3], call(5, prompt=4, predecessor="msg_0004")],
                ),
                "the boundary's `launch` is 2, where Pilot holds a launch begun at"
                f" {_at(10)}, and the call's first was begun at {_at(20)}",
            ),
            (
                _grown(
                    prompt=3,
                    launches=[_second_launch(prompts=[prompt(received_at=_at(15))])],
                ),
                "the boundary's `prompt` is 3, where Pilot holds a prompt received"
                f" at {_at(10)}, and the call's first was received at {_at(15)}",
            ),
            (
                _grown(
                    launch=1,
                    prompt=2,
                    launches=[
                        _first_launch(prompts=[prompt(received_at=_at(6))]),
                        _second_launch(),
                    ],
                ),
                "the boundary's `prompt` is 2, where Pilot holds a prompt received"
                f" at {_at(4)}, and the call's first was received at {_at(6)}",
            ),
            (
                _grown(compaction=1, compactions=[compaction(at=_at(13))]),
                "the boundary's `compaction` is 1, where Pilot holds a compaction"
                f" made at {_at(8)}, and the call's first was made at {_at(13)}",
            ),
            (
                _grown(call=3, calls=[call(4, prompt=3)]),
                "the call lacks 1 of the calls Pilot holds from its boundary on",
            ),
            (
                _grown(call=5, calls=[call(2, prompt=3)]),
                "call `msg_0002`: Pilot holds it before the boundary",
            ),
            (
                _grown(call=5, calls=[call(5, prompt=3, predecessor="msg_0009")]),
                "call `msg_0005`: `predecessor` `msg_0009` is no call Pilot holds"
                " before the boundary",
            ),
            (
                _grown(
                    calls=[
                        _calls()[3],
                        call(5, predecessor="msg_0004", tool_calls=[tool_call(1)]),
                    ]
                ),
                "tool call `toolu_0001`: Pilot holds it under a call before the"
                " boundary",
            ),
        ],
    )
    def test_a_call_that_does_not_continue_what_pilot_holds_is_refused(
        self,
        session: DbSession,
        publications: PublicationService,
        publication: PublicationSchema,
        cause: str,
    ) -> None:
        publications.publish(_camp())
        ids = _ids(session)

        with (
            writes(session) as wrote,
            pytest.raises(PublicationNotAppendableException) as refused,
        ):
            publications.publish(publication)

        assert refused.value.causes == [cause]
        assert wrote == {}
        assert _ids(session) == ids

    def test_a_transcript_pilot_does_not_hold_is_not_appended_to(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        with (
            writes(session) as wrote,
            pytest.raises(PublicationNotAppendableException) as refused,
        ):
            publications.publish(appended(calls=[call(1)]))

        assert refused.value.causes == ["Pilot does not hold it"]
        assert wrote == {}

    def test_a_sub_agents_thread_pilot_does_not_hold_is_not_appended_to(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """Its main thread, held at what the call builds on, is another
        Transcript."""
        publications.publish(_camp())

        with (
            writes(session) as wrote,
            pytest.raises(PublicationNotAppendableException) as refused,
        ):
            publications.publish(appended(agent_id=SUB_AGENT, calls=[call(1)]))

        assert refused.value.causes == ["Pilot does not hold it"]
        assert wrote == {}

    def test_every_cause_is_named_at_once_under_a_code_of_its_own(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())

        with pytest.raises(PublicationNotAppendableException) as refused:
            publications.publish(
                _grown(call=6, compaction=3, calls=[call(2, prompt=3)])
            )

        assert refused.value.causes == [
            "the boundary's `compaction` is 3, and Pilot holds 1 compactions",
            "the boundary's `call` is 6, and Pilot holds 4 calls",
            "call `msg_0002`: Pilot holds it before the boundary",
        ]
        assert refused.value.message == (
            f"Cannot append to transcript {CAMP} because "
            + "; ".join(refused.value.causes)
        )
        assert refused.value.error_code == "PUBLICATION_NOT_APPENDABLE"

    def test_the_transcript_published_whole_after_a_refusal_is_taken(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        grown = [*_calls(), call(5, prompt=3, predecessor="msg_0004")]
        with pytest.raises(PublicationNotAppendableException):
            publications.publish(_grown(builds_on=builds_on(file_size=48_000)))

        publications.publish(_camp(calls=grown, file_size=61_000))

        assert session.execute(
            select(Transcript.file_size, Transcript.replayed_size)
        ).one() == (61_000, 61_000)
        assert _count(session, Call) == 5

    def test_a_launch_place_one_short_leaves_the_held_launch_as_it_began(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """The file grew by a third Launch, and the call names the second's
        place for it: the second keeps its start and its versions, where a
        check by count alone gave it the third's."""
        publications.publish(_camp())
        third = launch(
            started_at=_at(20),
            components=[CLAUDE_CODE, {"component": "plugin:dev", "version": "0.10.56"}],
        )

        with pytest.raises(PublicationNotAppendableException):
            publications.publish(_grown(launches=[third]))

        assert session.scalars(select(Launch.started_at).order_by(Launch.id)).all() == [
            STARTED,
            STARTED + timedelta(minutes=10),
        ]
        assert _count(session, ComponentVersion) == 4

    def test_a_first_row_named_at_the_same_moment_in_another_zone_is_the_held_one(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        plus_two = timezone(timedelta(hours=2))

        publications.publish(
            _grown(
                launch=1,
                prompt=1,
                compaction=1,
                launches=[
                    _first_launch(
                        started_at=STARTED.astimezone(plus_two).isoformat(),
                        prompts=[
                            prompt(
                                received_at=STARTED.astimezone(plus_two).isoformat(),
                                hook_runs=[
                                    hook_run(),
                                    hook_run(
                                        command="hold_open.sh",
                                        duration_ms=40,
                                        prevented_end=True,
                                    ),
                                ],
                            ),
                            prompt(
                                received_at=_at(4),
                                source="task_notification",
                                characters=88,
                            ),
                        ],
                    ),
                    _second_launch(),
                ],
                compactions=[
                    compaction(
                        at=_at_time(8).astimezone(plus_two).isoformat(),
                        tokens_after=21_000,
                        duration_ms=5_200,
                    )
                ],
            )
        )

        assert _count(session, Call) == 5


class TestReplayedAtRest:
    """A whole publication of the file Pilot holds, part of it taken in
    appended calls: the replay at rest. A row it writes is one the appended
    calls left other than the file read whole gives, and is logged with its
    Transcript and how much of the file was taken in parts (F152.16;
    decision 81 point 2)."""

    FIFTH = call(5, prompt=3, predecessor="msg_0004")

    def _replay(self, **overrides: Any) -> PublicationSchema:
        """The grown file, whole: as `_grown` left Pilot holding it."""
        values: dict[str, Any] = {
            "file_size": 61_000,
            "file_modified_at": _at(30),
            "calls": [*_calls(), self.FIFTH],
        }
        return _camp(**values | overrides)

    def _logged(self, caplog: pytest.LogCaptureFixture) -> list[str]:
        return [
            record.getMessage() for record in caplog.records if record.name == LOGGER
        ]

    def test_one_that_finds_the_file_as_pilot_holds_it_logs_nothing(
        self,
        session: DbSession,
        publications: PublicationService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        publications.publish(_camp())
        publications.publish(_grown())

        with caplog.at_level(logging.DEBUG, LOGGER), writes(session) as wrote:
            publications.publish(self._replay())

        assert wrote == {"transcripts": Written(updated=1)}
        assert self._logged(caplog) == []
        assert session.execute(
            select(Transcript.file_size, Transcript.replayed_size)
        ).one() == (61_000, 61_000)

    def test_a_row_it_changes_is_logged_with_its_transcript(
        self,
        session: DbSession,
        publications: PublicationService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The appended call left the fifth Call's tokens and the fourth's
        Tool Call other than the file has them."""
        publications.publish(_camp())
        left = call(5, prompt=3, predecessor="msg_0004", tokens={"output": 12})
        fourth = _calls()[3] | {
            "tool_calls": [tool_call(5, interrupted=True, result_characters=7)]
        }
        publications.publish(_grown(calls=[fourth, left]))

        with caplog.at_level(logging.WARNING, LOGGER):
            publications.publish(self._replay())

        assert self._logged(caplog) == [
            f"The replay at rest of transcript {CAMP}, 12888 of its 61000 bytes"
            " taken in parts, wrote rows that differ from what Pilot held:"
            " calls 1, tool_calls 1"
        ]
        assert (
            session.scalars(
                select(Call.output_tokens).where(Call.message_id == "msg_0005")
            ).one()
            == 2_870
        )

    def test_a_row_it_adds_and_one_it_removes_are_logged_too(
        self,
        session: DbSession,
        publications: PublicationService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The appended calls left a sixth Call the file does not have, and
        the second Launch without the Prompt it received last."""
        publications.publish(_camp())
        sixth = call(6, prompt=3, predecessor="msg_0005")
        publications.publish(_grown(calls=[_calls()[3], self.FIFTH, sixth]))
        later = prompt(received_at=_at(15), characters=64)

        with caplog.at_level(logging.WARNING, LOGGER):
            publications.publish(
                self._replay(
                    launches=[
                        _first_launch(),
                        _second_launch(
                            prompts=[prompt(received_at=_at(10), characters=31), later]
                        ),
                    ]
                )
            )

        assert self._logged(caplog) == [
            f"Transcript {CAMP} no longer has 1 of the calls Pilot held",
            f"The replay at rest of transcript {CAMP}, 12888 of its 61000 bytes"
            " taken in parts, wrote rows that differ from what Pilot held:"
            " calls 1, prompts 1",
        ]

    def test_a_sub_agents_is_logged_with_its_thread(
        self,
        session: DbSession,
        publications: PublicationService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        publications.publish(sub_agent(calls=[call(1)]))
        publications.publish(
            appended(
                agent_id=SUB_AGENT,
                call=2,
                calls=[call(2, predecessor="msg_0001", effort="low")],
            )
        )

        with caplog.at_level(logging.WARNING, LOGGER):
            publications.publish(
                sub_agent(
                    file_size=61_000,
                    file_modified_at=_at(30),
                    calls=[call(1), call(2, predecessor="msg_0001", effort="high")],
                )
            )

        assert self._logged(caplog) == [
            f"The replay at rest of transcript {CAMP}/{SUB_AGENT}, 12888 of its"
            " 61000 bytes taken in parts, wrote rows that differ from what Pilot"
            " held: calls 1"
        ]

    @pytest.mark.parametrize(
        "other",
        [
            {"file_size": 70_000},
            {"file_modified_at": _at(31)},
            {"collector": {"version": "1.1.0"}},
        ],
        ids=["another size", "another time", "another collector's version"],
    )
    def test_a_whole_call_of_another_file_or_reader_than_pilot_holds_is_none(
        self,
        session: DbSession,
        publications: PublicationService,
        caplog: pytest.LogCaptureFixture,
        other: dict[str, Any],
    ) -> None:
        """A file that changed, or one read anew, gives rows that say
        nothing of the appended calls."""
        publications.publish(_camp())
        publications.publish(_grown())
        changed = call(5, prompt=3, predecessor="msg_0004", effort="max")

        with caplog.at_level(logging.DEBUG, LOGGER):
            publications.publish(self._replay(calls=[*_calls(), changed], **other))

        assert self._logged(caplog) == []
        assert (
            session.scalars(
                select(Call.effort).where(Call.message_id == "msg_0005")
            ).one()
            == "max"
        )

    def test_a_whole_call_of_a_transcript_taken_whole_is_none(
        self,
        session: DbSession,
        publications: PublicationService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        publications.publish(_camp())
        calls = _calls()
        calls[3]["effort"] = "max"

        with caplog.at_level(logging.DEBUG, LOGGER):
            publications.publish(_camp(calls=calls))

        assert self._logged(caplog) == []

    def test_the_replay_is_over_once_it_was_taken(
        self,
        session: DbSession,
        publications: PublicationService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A whole call after it finds `replayed_size` at the file's size."""
        publications.publish(_camp())
        publications.publish(_grown())
        publications.publish(self._replay())
        changed = call(5, prompt=3, predecessor="msg_0004", effort="max")

        with caplog.at_level(logging.DEBUG, LOGGER):
            publications.publish(self._replay(calls=[*_calls(), changed]))

        assert self._logged(caplog) == []

    def test_a_launch_it_places_under_its_session_is_no_row_it_changed(
        self,
        session: DbSession,
        publications: PublicationService,
        project_session: models.Session,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The placing is Pilot's own, and not the file's."""
        turn_at(session, project_session, _at_time(0) - timedelta(seconds=4))
        publications.publish(_camp())
        publications.publish(_grown())
        project_session.conversation_id = CAMP

        with caplog.at_level(logging.DEBUG, LOGGER):
            publications.publish(self._replay())

        assert _ran(session) == [(project_session.id, 1), (project_session.id, 1)]
        assert self._logged(caplog) == []


class TestRan:
    """A Launch a Turn of Pilot's started stands under its Session and that
    Turn, and its transcript so lands on the Session's project (DB decision
    79 point 7; assertions 538 and 540; F152.4)."""

    def test_a_launch_a_turn_of_pilots_started_is_under_its_session_and_turn(
        self, session: DbSession, publications: PublicationService, run: models.Session
    ) -> None:
        publications.publish(_camp())

        assert _ran(session) == [(run.id, 1), (run.id, 2)]

    def test_its_transcript_lands_on_the_sessions_project(
        self, session: DbSession, publications: PublicationService, run: models.Session
    ) -> None:
        thread = publications.publish(_camp())

        assert _projects(session, thread) == [run.project_id]

    def test_a_launch_a_driver_started_is_under_the_session_whose_step_names_it(
        self,
        session: DbSession,
        publications: PublicationService,
        waited: models.Session,
    ) -> None:
        """DB 538; F152.9: a loop session's thread, which no Session's
        `conversation_id` names."""
        thread = publications.publish(_camp())

        assert _ran(session) == [(waited.id, 1), (waited.id, 1)]
        assert _projects(session, thread) == [waited.project_id]

    def test_a_driver_started_launch_named_again_keeps_what_it_was_placed_under(
        self,
        session: DbSession,
        publications: PublicationService,
        waited: models.Session,
    ) -> None:
        publications.publish(_camp())
        end_turns(session, waited)

        with writes(session) as wrote:
            publications.publish(_camp())

        assert _ran(session) == [(waited.id, 1), (waited.id, 1)]
        assert wrote == {"transcripts": Written(updated=1)}

    def test_one_no_session_of_pilots_ran_lands_on_no_project(
        self, session: DbSession, publications: PublicationService, run: models.Session
    ) -> None:
        thread = publications.publish(_camp(session_id=OTHER))

        assert _ran(session) == [(None, None), (None, None)]
        assert _projects(session, thread) == []

    def test_a_launch_started_between_two_turns_has_the_session_and_no_turn(
        self, session: DbSession, publications: PublicationService, run: models.Session
    ) -> None:
        between = _second_launch(
            started_at=(STARTED + timedelta(minutes=9, seconds=30)).isoformat()
        )

        publications.publish(_camp(launches=[_first_launch(), between]))

        assert _ran(session) == [(run.id, 1), (run.id, None)]

    def test_a_launch_an_appended_call_brings_is_placed(
        self, session: DbSession, publications: PublicationService, run: models.Session
    ) -> None:
        publications.publish(_camp())
        turn_at(session, run, STARTED + timedelta(minutes=19, seconds=56))
        third = launch(
            started_at=_at(20),
            components=[CLAUDE_CODE],
            prompts=[prompt(received_at=_at(20))],
        )

        publications.publish(
            _grown(
                launches=[_second_launch(prompts=[], ended_at=_at(14)), third],
                calls=[_calls()[3], call(5, prompt=4, predecessor="msg_0004")],
            )
        )

        assert _ran(session) == [(run.id, 1), (run.id, 2), (run.id, 3)]

    def test_a_placed_launch_named_again_unchanged_is_not_written(
        self, session: DbSession, publications: PublicationService, run: models.Session
    ) -> None:
        publications.publish(_camp())

        with writes(session) as wrote:
            publications.publish(_camp())

        assert wrote == {"transcripts": Written(updated=1)}
        assert _ran(session) == [(run.id, 1), (run.id, 2)]

    def test_a_placed_launch_keeps_its_session_and_turn_through_a_whole_call(
        self, session: DbSession, publications: PublicationService, run: models.Session
    ) -> None:
        """The call names the first Launch again at a start between the two
        Turns, where a Launch first met would have no Turn."""
        publications.publish(_camp())
        restated = _first_launch(
            started_at=(STARTED + timedelta(minutes=9, seconds=30)).isoformat(),
            ended_at=None,
        )

        with writes(session) as wrote:
            publications.publish(_camp(launches=[restated, _second_launch()]))

        assert wrote == {
            "transcripts": Written(updated=1),
            "launches": Written(updated=1),
        }
        assert _ran(session) == [(run.id, 1), (run.id, 2)]

    def test_a_placed_launch_keeps_its_session_and_turn_through_an_appended_call(
        self, session: DbSession, publications: PublicationService, run: models.Session
    ) -> None:
        publications.publish(_camp())
        end_turns(session, run)
        turn_at(session, run, _at_time(15))

        with writes(session) as wrote:
            publications.publish(_grown())

        assert "launches" not in wrote
        assert _ran(session) == [(run.id, 1), (run.id, 2)]

    def test_a_launch_held_before_its_session_named_the_conversation_is_placed(
        self,
        session: DbSession,
        publications: PublicationService,
        project_session: models.Session,
    ) -> None:
        """Whichever publication follows the Session's `conversation_id`
        places what the earlier ones brought."""
        turn_at(session, project_session, _at_time(0) - timedelta(seconds=4))
        publications.publish(_camp())
        assert _ran(session) == [(None, None), (None, None)]
        project_session.conversation_id = CAMP

        publications.publish(_camp())

        assert _ran(session) == [(project_session.id, 1), (project_session.id, 1)]

    def test_an_appended_call_places_a_launch_held_before_its_boundary(
        self,
        session: DbSession,
        publications: PublicationService,
        project_session: models.Session,
    ) -> None:
        turn_at(session, project_session, _at_time(0) - timedelta(seconds=4))
        publications.publish(_camp())
        project_session.conversation_id = CAMP

        publications.publish(_grown())

        assert _ran(session) == [(project_session.id, 1), (project_session.id, 1)]

    def test_a_sub_agents_thread_is_under_the_launch_of_its_main_thread_alone(
        self, session: DbSession, publications: PublicationService, run: models.Session
    ) -> None:
        """A sub-agent's thread has no Launch of its own (DB 536): its
        publication places none."""
        publications.publish(_camp())

        with writes(session) as wrote:
            publications.publish(sub_agent())

        assert "launches" not in wrote
        assert _ran(session) == [(run.id, 1), (run.id, 2)]

    def test_a_launch_the_file_lost_goes_with_its_session_and_turn(
        self, session: DbSession, publications: PublicationService, run: models.Session
    ) -> None:
        publications.publish(_camp())

        publications.publish(_camp(launches=[_first_launch()], calls=_calls()[:3]))

        assert _ran(session) == [(run.id, 1)]
        assert _count(session, Turn) == 2


class TestCaches:
    """A Call is written with its derived caches and its Transcript with its
    first and its last Call's time (DB §7.4; decision 79.14)."""

    def test_each_call_is_written_with_its_caches(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """The third Call's context is under nine tenths of what the second
        left: its chain crossed a compaction, and it missed no cache (DB
        546)."""
        thread = publications.publish(_camp())

        assert _caches(session, thread) == [
            (None, False, False, False, 1),
            (60.0, False, False, False, 1),
            (60.0, False, False, False, 1),
            (60.0, False, False, False, 2),
        ]

    def test_a_wait_past_the_caches_lifetime_a_rewind_and_a_miss_are_told(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """The third Call goes back to the first, 69 minutes after it
        completed, and reads nothing of the hour's cache it left."""
        back = call(
            3,
            predecessor="msg_0001",
            sent_at=_at(70),
            completed_at=_at(71),
            tokens={"input": 1_204, "cache_write_1h": 52_000, "output": 2_870},
        )

        thread = publications.publish(
            _camp(calls=[call(1), call(2, predecessor="msg_0001"), back])
        )

        assert _caches(session, thread) == [
            (None, False, False, False, None),
            (60.0, False, False, False, None),
            (69 * 60.0, True, True, True, None),
        ]

    def test_an_appended_calls_predecessor_before_its_boundary_is_read(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(_camp())
        back = call(
            5,
            prompt=3,
            predecessor="msg_0002",
            sent_at=(STARTED + timedelta(minutes=4, seconds=30)).isoformat(),
        )

        with writes(session) as wrote:
            publications.publish(_grown(call=5, calls=[back]))

        assert _caches(session, thread)[4] == (150.0, True, False, False, 2)
        assert wrote == {
            "transcripts": Written(updated=1),
            "calls": Written(inserted=1),
        }

    def test_a_call_named_again_whose_predecessor_moved_holds_its_caches_anew(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(_camp())
        calls = _calls()
        calls[3] = calls[3] | {"predecessor": "msg_0001"}

        publications.publish(_camp(calls=calls))

        assert _caches(session, thread)[3] == (180.0, True, False, False, 2)

    def test_a_transcript_holds_its_first_and_its_last_calls_time(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(_camp())

        assert _call_times(session, thread) == (_at_time(1), _at_time(4))

    def test_a_transcript_with_no_call_holds_neither(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(_camp())
        held = _call_times(session, thread)

        publications.publish(_camp(calls=[]))

        assert held != (None, None)
        assert _call_times(session, thread) == (None, None)

    def test_an_appended_call_moves_its_last_calls_time_alone(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(_camp())

        publications.publish(_grown())

        assert _call_times(session, thread) == (_at_time(1), _at_time(5))

    def test_an_appended_call_that_carries_no_call_moves_neither(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(_camp())

        publications.publish(_grown(call=5, calls=[]))

        assert _call_times(session, thread) == (_at_time(1), _at_time(4))

    def test_an_appended_call_from_the_files_first_call_on_sets_both(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(_camp(calls=[]))

        publications.publish(
            appended(
                launch=2,
                prompt=4,
                compaction=2,
                launches=[_second_launch(prompts=[])],
                calls=[call(1, prompt=1), call(2, prompt=3, predecessor="msg_0001")],
            )
        )

        assert _call_times(session, thread) == (_at_time(1), _at_time(2))

    def test_an_appended_call_reads_the_first_calls_time_a_transcript_lacks(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """A server from before these times wrote the Transcript and its
        Calls."""
        thread = publications.publish(_camp())
        thread.first_call_at = thread.last_call_at = None
        session.flush()

        publications.publish(_grown())

        assert _call_times(session, thread) == (_at_time(1), _at_time(5))

    def test_a_sub_agents_calls_are_made_in_the_main_threads_launch_that_holds_them(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """DB 543: the first Launch ended nine minutes in, and the second
        began a minute later."""
        publications.publish(_camp())

        thread = publications.publish(
            sub_agent(
                calls=[
                    call(1, completed_at=_at(3)),
                    call(
                        2, completed_at=(STARTED + timedelta(seconds=570)).isoformat()
                    ),
                    call(3, completed_at=_at(12)),
                ]
            )
        )

        assert [launch for *_, launch in _caches(session, thread)] == [1, None, 2]

    def test_a_main_thread_published_later_holds_its_sub_agents_calls(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(
            sub_agent(
                calls=[call(1, completed_at=_at(3)), call(2, completed_at=_at(12))]
            )
        )
        before = _caches(session, thread)

        with writes(session) as wrote:
            publications.publish(_camp())

        assert [launch for *_, launch in before] == [None, None]
        assert [launch for *_, launch in _caches(session, thread)] == [1, 2]
        assert wrote["calls"] == Written(inserted=4, updated=2)

    def test_a_main_thread_named_again_leaves_its_sub_agents_calls_as_they_are(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        publications.publish(sub_agent(calls=[call(1, completed_at=_at(3))]))

        with writes(session) as wrote:
            publications.publish(_camp())

        assert wrote == {"transcripts": Written(updated=1)}

    def test_a_launch_the_main_thread_no_longer_names_leaves_its_sub_agents_calls(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """F152.17: the Launch goes, and the Call it held is in none."""
        publications.publish(_camp())
        thread = publications.publish(
            sub_agent(
                calls=[call(1, completed_at=_at(3)), call(2, completed_at=_at(12))]
            )
        )

        publications.publish(_camp(launches=[_first_launch()], calls=_calls()[:3]))

        assert [launch for *_, launch in _caches(session, thread)] == [1, None]

    def test_a_launch_that_ended_later_holds_the_sub_agents_calls_up_to_its_end(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp(launches=[_first_launch()], calls=_calls()[:3]))
        thread = publications.publish(sub_agent(calls=[call(1, completed_at=_at(12))]))
        before = _caches(session, thread)

        publications.publish(
            _camp(launches=[_first_launch(ended_at=_at(15))], calls=_calls()[:3])
        )

        assert [launch for *_, launch in before] == [None]
        assert [launch for *_, launch in _caches(session, thread)] == [1]


class TestAdopted:
    """A main thread whose labelling names a group is adopted by the group's
    adopted Project, made the first time the group is named and found again
    by its key (F152.8; DB 539, 582, 584). A call with no labelling leaves
    the adoption as it stands (F152.6)."""

    def test_a_group_first_named_makes_its_project_which_adopts_the_transcript(
        self, session: DbSession, publications: PublicationService, service_user: User
    ) -> None:
        thread = publications.publish(_camp(group=group(), labelling=labelling()))

        project = session.scalars(select(Project)).one()
        assert thread.adopted_project_id == project.id
        assert (project.state_code, project.archived, project.adopted_group) == (
            ProjectState.ADOPTED,
            True,
            FIRST_MENUS,
        )
        assert project.name == "Recipe box: the first menus"
        assert project.created_by_user_id == service_user.id

    def test_an_appended_call_names_no_group(
        self, session: DbSession, publications: PublicationService, service_user: User
    ) -> None:
        """It carries no labelling yet, and a group is a label of one."""
        publications.publish(_camp())

        with (
            writes(session) as wrote,
            pytest.raises(PublicationInvalidException) as raised,
        ):
            publications.publish(_grown(group=group()))

        assert raised.value.faults == ["a call with no labelling names no `group`"]
        assert wrote == {}

    def test_a_later_publication_naming_the_group_finds_its_project(
        self, session: DbSession, publications: PublicationService, service_user: User
    ) -> None:
        first = publications.publish(_camp(group=group(), labelling=labelling()))

        second = publications.publish(
            _camp(session_id=OTHER, group=group(), labelling=labelling())
        )
        again = publications.publish(_grown())

        assert _count(session, Project) == 1
        assert (
            first.adopted_project_id
            == second.adopted_project_id
            == again.adopted_project_id
            is not None
        )

    def test_a_republish_of_an_adopted_transcript_writes_no_project(
        self, session: DbSession, publications: PublicationService, service_user: User
    ) -> None:
        publications.publish(_camp(group=group(), labelling=labelling()))

        with writes(session) as wrote:
            publications.publish(_camp(group=group(), labelling=labelling()))

        assert wrote == {"transcripts": Written(updated=1)}

    def test_a_renamed_group_renames_its_project(
        self, session: DbSession, publications: PublicationService, service_user: User
    ) -> None:
        thread = publications.publish(_camp(group=group(), labelling=labelling()))

        publications.publish(
            _camp(
                group=group(name="The first menus", summary="As Ben tells it."),
                labelling=labelling(),
            )
        )

        project = session.get_one(Project, thread.adopted_project_id)
        assert project.name == "The first menus"
        assert session.scalars(select(Document.published_text)).one() == (
            "---\ntitle: The first menus\n---\n\nAs Ben tells it.\n"
        )
        assert _count(session, Project) == 1

    def test_a_transcript_whose_group_goes_is_adopted_by_none_and_its_project_stands(
        self, session: DbSession, publications: PublicationService, service_user: User
    ) -> None:
        """The label is the labelling's, and nothing removes an adopted
        Project."""
        publications.publish(_camp(group=group(), labelling=labelling()))

        thread = publications.publish(_camp(labelling=labelling()))

        assert thread.adopted_project_id is None
        assert session.scalars(select(Project.adopted_group)).all() == [FIRST_MENUS]

    @pytest.mark.parametrize("grown", [False, True], ids=["whole", "appended"])
    def test_a_call_with_no_labelling_leaves_the_transcript_adopted(
        self,
        session: DbSession,
        publications: PublicationService,
        service_user: User,
        grown: bool,
    ) -> None:
        adopted = publications.publish(
            _camp(group=group(), labelling=labelling())
        ).adopted_project_id

        thread = publications.publish(_grown() if grown else _camp())

        assert thread.adopted_project_id == adopted is not None
        assert _count(session, Project) == 1

    def test_a_transcript_whose_group_changes_moves_and_both_projects_stand(
        self, session: DbSession, publications: PublicationService, service_user: User
    ) -> None:
        first = publications.publish(
            _camp(group=group(), labelling=labelling())
        ).adopted_project_id

        thread = publications.publish(
            _camp(
                group=group(key="recipe-box-second-menus", name="The second menus"),
                labelling=labelling(),
            )
        )

        assert thread.adopted_project_id != first
        assert sorted(session.scalars(select(Project.adopted_group))) == [
            FIRST_MENUS,
            "recipe-box-second-menus",
        ]

    def test_a_sub_agents_thread_is_under_its_adopted_main_thread_and_adopted_by_none(
        self, session: DbSession, publications: PublicationService, service_user: User
    ) -> None:
        main = publications.publish(_camp(group=group(), labelling=labelling()))

        thread = publications.publish(sub_agent())

        assert (thread.main_id, thread.adopted_project_id) == (main.id, None)

    def test_a_stage_with_no_service_user_is_refused_and_nothing_is_written(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        with writes(session) as wrote, pytest.raises(NoServiceUserException):
            publications.publish(_camp(group=group(), labelling=labelling()))

        assert wrote == {}

    def test_a_group_whose_project_stands_needs_no_service_user(
        self, session: DbSession, publications: PublicationService, service_user: User
    ) -> None:
        publications.publish(_camp(group=group(), labelling=labelling()))
        service_user.kind_code = UserKind.PERSON
        service_user.avatar_slot = 3
        session.flush()

        thread = publications.publish(
            _camp(session_id=OTHER, group=group(), labelling=labelling())
        )

        assert thread.adopted_project_id is not None

    def test_a_group_named_for_a_transcript_a_session_of_pilots_ran_is_refused(
        self,
        session: DbSession,
        publications: PublicationService,
        run: models.Session,
        service_user: User,
    ) -> None:
        """DB 539."""
        publications.publish(_camp())

        with (
            writes(session) as wrote,
            pytest.raises(TranscriptNotAdoptableException) as raised,
        ):
            publications.publish(_camp(group=group(), labelling=labelling()))

        assert raised.value.message == (
            f"Cannot adopt transcript {CAMP} into the group 'recipe-box-first-menus'"
            " because a session of Pilot's ran it"
        )
        assert raised.value.error_code == "TRANSCRIPT_NOT_ADOPTABLE"
        assert wrote == {}
        assert _ran(session) == [(run.id, 1), (run.id, 2)]

    def test_a_group_named_at_the_first_publication_of_a_sessions_transcript_is_refused(
        self,
        session: DbSession,
        publications: PublicationService,
        run: models.Session,
        service_user: User,
    ) -> None:
        with (
            writes(session) as wrote,
            pytest.raises(TranscriptNotAdoptableException),
        ):
            publications.publish(_camp(group=group(), labelling=labelling()))

        assert wrote == {}

    def test_a_group_named_for_a_transcript_a_sessions_step_names_is_refused(
        self,
        session: DbSession,
        publications: PublicationService,
        waited: models.Session,
        service_user: User,
    ) -> None:
        """A loop session's thread is a Session of Pilot's work as much as
        the thread its own Turn started (DB 538, 539)."""
        with (
            writes(session) as wrote,
            pytest.raises(TranscriptNotAdoptableException),
        ):
            publications.publish(_camp(group=group(), labelling=labelling()))

        assert wrote == {}

    def test_a_transcript_adopted_before_a_session_named_it_stays_adopted(
        self,
        session: DbSession,
        publications: PublicationService,
        project_session: models.Session,
        service_user: User,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """DB 539, the other way round: its Launches stay off the Session,
        and each publication that finds it so logs it."""
        adopted = publications.publish(
            _camp(group=group(), labelling=labelling())
        ).adopted_project_id
        project_session.conversation_id = CAMP
        turn_at(session, project_session, _at_time(0) - timedelta(seconds=4))

        with caplog.at_level(logging.WARNING, logger=PLACEMENT_LOGGER):
            thread = publications.publish(_camp(group=group(), labelling=labelling()))

        assert thread.adopted_project_id == adopted
        assert _ran(session) == [(None, None), (None, None)]
        assert caplog.messages == [
            f"Transcript {CAMP} is adopted by project {adopted}, and a Session of"
            " Pilot's names it: its launches stay off that Session"
        ]

    def test_a_transcript_no_longer_adopted_lands_on_the_session_that_names_it(
        self,
        session: DbSession,
        publications: PublicationService,
        project_session: models.Session,
        service_user: User,
    ) -> None:
        publications.publish(_camp(group=group(), labelling=labelling()))
        project_session.conversation_id = CAMP
        turn_at(session, project_session, _at_time(0) - timedelta(seconds=4))

        thread = publications.publish(_camp(labelling=labelling()))

        assert thread.adopted_project_id is None
        assert _ran(session) == [(project_session.id, 1), (project_session.id, 1)]

    def test_a_session_of_another_conversation_keeps_no_transcript_from_its_group(
        self,
        session: DbSession,
        publications: PublicationService,
        run: models.Session,
        service_user: User,
    ) -> None:
        thread = publications.publish(
            _camp(session_id=OTHER, group=group(), labelling=labelling())
        )

        assert thread.adopted_project_id is not None

    @pytest.mark.parametrize(
        ("publication", "fault"),
        [
            (
                sub_agent(group=group(), labelling=labelling()),
                "a sub-agent's thread names no `group`",
            ),
            (
                whole(group=group(name=" The first menus"), labelling=labelling()),
                "the group's `name` is not one line of words with no space around them",
            ),
            (
                whole(
                    group=group(summary="```question id=Q1\ndefault: Stew\n```"),
                    labelling=labelling(),
                ),
                "the group's `summary` holds an ask",
            ),
        ],
        ids=["a sub-agent's", "a padded name", "an ask in the summary"],
    )
    def test_a_group_that_makes_no_project_document_is_a_fault(
        self,
        session: DbSession,
        publications: PublicationService,
        service_user: User,
        publication: PublicationSchema,
        fault: str,
    ) -> None:
        with (
            writes(session) as wrote,
            pytest.raises(PublicationInvalidException) as raised,
        ):
            publications.publish(publication)

        assert raised.value.faults == [fault]
        assert wrote == {}


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

        with scoped_session(container):
            main_id = container.publication_service().publish(_camp()).id
            second = in_thread(published_second)
            wait_until(lambda: lock_waits(container) == 1, "the second's turn waiting")

        assert second.result() == main_id

    def test_a_sub_agents_thread_published_beside_its_main_thread_is_joined_to_its_call(
        self, committed_app: Flask
    ) -> None:
        container = committed_app.container

        def published_second() -> Any:
            with scoped_session(container):
                thread = container.publication_service().publish(sub_agent())
                return thread.spawned_by_id

        with scoped_session(container) as first:
            container.publication_service().publish(_camp())
            spawning = _tool_call_id(first)
            second = in_thread(published_second)
            wait_until(lambda: lock_waits(container) == 1, "the second's turn waiting")

        assert second.result() == spawning

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

        with scoped_session(container):
            thread_id = container.publication_service().publish(_camp()).id
            second = in_thread(published_second)
            wait_until(lambda: lock_waits(container) == 1, "the second's turn waiting")

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

    def test_a_call_published_beside_a_load_of_the_prices_is_priced_at_what_it_loaded(
        self, committed_app: Flask
    ) -> None:
        container = committed_app.container
        calls = [call(1, model=PANTRY, tokens={"input": 1_000_000})]

        def published() -> Any:
            with scoped_session(container) as db:
                container.publication_service().publish(
                    _camp(calls=calls, compactions=[])
                )
                return db.scalars(select(Call.cost)).one()

        with scoped_session(container):
            container.price_service().load([PANTRY_INPUT])
            second = in_thread(published)
            wait_until(lambda: lock_waits(container) == 1, "the publication waiting")

        assert second.result() == Decimal("3")

    def test_a_load_of_the_prices_beside_a_publication_prices_the_calls_it_wrote(
        self, committed_app: Flask
    ) -> None:
        container = committed_app.container
        # Of a Model first met, which the load prices as the one it names.
        calls = [call(1, model="claude-pantry-3", tokens={"input": 1_000_000})]

        def loaded() -> Any:
            with scoped_session(container):
                return container.price_service().load([PANTRY_INPUT])

        with scoped_session(container):
            container.publication_service().publish(_camp(calls=calls, compactions=[]))
            second = in_thread(loaded)
            wait_until(lambda: lock_waits(container) == 1, "the load waiting")

        assert second.result() == PriceLoad(prices=1, models=1, calls=1)
        with scoped_session(container) as db:
            assert db.scalars(select(Call.cost)).all() == [Decimal("3")]


class TestAdmitted:
    """The gate a collector's call passes before it is read."""

    def test_a_call_with_the_bearer_in_the_served_version_is_let_through(
        self, publications: PublicationService
    ) -> None:
        headers = collector_headers()

        publications.admit(
            headers["Authorization"], headers["X-Pilot-Collector-Protocol"]
        )

    @pytest.mark.parametrize(
        "authorization",
        [None, "", "Bearer", "Bearer another-token", COLLECTOR_TOKEN],
    )
    def test_a_call_without_the_bearer_is_refused(
        self, publications: PublicationService, authorization: str | None
    ) -> None:
        with pytest.raises(AuthenticationException, match="the collector's bearer"):
            publications.admit(authorization, str(COLLECTOR_PROTOCOL_MAX))

    @pytest.mark.parametrize("authorization", ["Bearer ", "Bearer", ""])
    def test_every_call_is_refused_while_the_token_is_empty(
        self, session: DbSession, container: ServiceContainer, authorization: str
    ) -> None:
        settings = container.app_config().model_copy(update={"collector_token": ""})
        publications = PublicationService(
            session,
            settings,
            container.adoption_service(),
            container.fleet_consumer(),
            container.catalogue_service(),
        )

        with pytest.raises(AuthenticationException):
            publications.admit(authorization, str(COLLECTOR_PROTOCOL_MAX))

    @pytest.mark.parametrize("version", [None, "", "0", "3", "one", "+1", "1.0"])
    def test_a_version_outside_the_range_is_refused_with_the_range(
        self, publications: PublicationService, version: str | None
    ) -> None:
        with pytest.raises(CollectorProtocolUnsupportedException) as refused:
            publications.admit(collector_headers()["Authorization"], version)

        assert (refused.value.minimum, refused.value.maximum) == (
            COLLECTOR_PROTOCOL_MIN,
            COLLECTOR_PROTOCOL_MAX,
        )
        assert refused.value.error_code == "COLLECTOR_PROTOCOL_UNSUPPORTED"
        assert repr(version) in refused.value.message

    def test_the_bearer_is_asked_for_before_the_version(
        self, publications: PublicationService
    ) -> None:
        with pytest.raises(AuthenticationException):
            publications.admit("Bearer another-token", "2")


class TestInventory:
    """What a walk compares the home against (F152.2)."""

    def test_the_transcripts_come_by_session_a_main_thread_before_its_sub_agents(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        for publication in (
            sub_agent(agent_id=DEEPER, spawned_by=None),
            _camp(session_id=OTHER),
            sub_agent(),
            _camp(),
        ):
            publications.publish(publication)

        inventory = publications.inventory()

        assert [(held.session_id, held.agent_id) for held in inventory.transcripts] == [
            (CAMP, None),
            (CAMP, SUB_AGENT),
            (CAMP, DEEPER),
            (OTHER, None),
        ]

    def test_a_transcript_is_held_as_its_last_publication_left_it(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """Republished whole by another version after an appended call: the
        file's size and time, the size replayed and the version move."""
        publications.publish(_camp())
        publications.publish(_grown())
        [taken_in_parts] = publications.inventory().transcripts
        later = STARTED + timedelta(hours=2)

        publications.publish(
            _camp(
                calls=[*_calls(), call(5, prompt=3, predecessor="msg_0004")],
                file_size=70_000,
                file_modified_at=later.isoformat(),
                collector={"version": "1.1.0"},
            )
        )

        assert taken_in_parts.model_dump() == {
            "session_id": CAMP,
            "agent_id": None,
            "file_size": 61_000,
            "file_modified_at": STARTED + timedelta(minutes=30),
            "replayed_size": 48_112,
            "collector": "1.0.0",
        }
        [replayed] = publications.inventory().transcripts
        assert replayed.model_dump() == {
            "session_id": CAMP,
            "agent_id": None,
            "file_size": 70_000,
            "file_modified_at": later,
            "replayed_size": 70_000,
            "collector": "1.1.0",
        }

    def test_the_inventory_is_one_read_however_many_transcripts_and_versions(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_camp())
        publications.publish(sub_agent())
        publications.publish(_camp(session_id=OTHER, collector={"version": "1.1.0"}))

        with sent(session) as each:
            inventory = publications.inventory()

        assert len(inventory.transcripts) == 3
        assert len(each.texts) == 1

    def test_the_walks_settings_are_the_servers(
        self, session: DbSession, container: ServiceContainer
    ) -> None:
        settings = container.app_config().model_copy(
            update={
                "collector_walk_interval_seconds": 300.0,
                "collector_settling_seconds": 45.0,
            }
        )
        publications = PublicationService(
            session,
            settings,
            container.adoption_service(),
            container.fleet_consumer(),
            container.catalogue_service(),
        )

        inventory = publications.inventory()

        assert (inventory.walk_interval_seconds, inventory.settling_seconds) == (
            300.0,
            45.0,
        )


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
                "call `msg_0001`: `prompt` 2 is past the transcript's 1 prompts",
            ),
            (
                sub_agent(calls=[call(1, prompt=1)]),
                "call `msg_0001`: `prompt` 1 is past the transcript's 0 prompts",
            ),
            (
                whole(compactions=[compaction()], calls=[call(1, compaction=2)]),
                "call `msg_0001`: `compaction` 2 is past the transcript's 1 compactions",
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
            (whole(spawned_by=SPAWNING), "a main thread has no `spawned_by`"),
            (
                whole(
                    calls=[
                        call(1, tool_calls=[tool_call(1)]),
                        call(2, tool_calls=[tool_call(1)]),
                    ]
                ),
                "call `msg_0002`: tool call `toolu_0001`: named twice",
            ),
            (
                whole(calls=[call(1, tool_calls=[tool_call(1, exit_code=0)])]),
                "call `msg_0001`: tool call `toolu_0001`: `exit_code` is 0",
            ),
            (
                whole(calls=[call(1, tool_calls=[tool_call(1, denial_kind="hook")])]),
                "call `msg_0001`: tool call `toolu_0001`: denied by a hook and not"
                " `failed`",
            ),
            (
                whole(
                    calls=[
                        call(
                            1,
                            tool_calls=[
                                tool_call(
                                    1,
                                    tool="mcp__pantry__find_items",
                                    mcp_server="pantry",
                                ),
                                tool_call(2, tool="mcp__pantry__find_items"),
                            ],
                        )
                    ]
                ),
                "call `msg_0001`: tool call `toolu_0002`: the tool"
                " `mcp__pantry__find_items` is given two `mcp_server`s",
            ),
            (
                whole(calls=[call(1, events=[event(), event(is_error=False)])]),
                "call `msg_0001`: event 2: the kind `api_error` is given as an"
                " error and as none",
            ),
            (
                appended(file_size=48_112),
                "an appended call's file is no larger than the one it builds on",
            ),
            (
                appended(calls=[call(1, predecessor="msg_0002"), call(2)]),
                "call `msg_0001`: `predecessor` `msg_0002` is no earlier call",
            ),
            (
                appended(call=3, prompt=4, calls=[call(3, prompt=5)]),
                "call `msg_0003`: `prompt` 5 is past the transcript's 3 prompts",
            ),
            (
                appended(
                    call=3,
                    compaction=2,
                    compactions=[compaction()],
                    calls=[call(3, compaction=4)],
                ),
                "call `msg_0003`: `compaction` 4 is past the transcript's 2"
                " compactions",
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

    @pytest.mark.parametrize(
        "kind",
        [
            "compaction",
            "rewind",
            "cache_miss",
            "past_ttl",
            "model_fallback",
            "max_tokens",
            "refusal",
            "output_saved",
            "denied",
            "hook_error",
        ],
    )
    def test_an_occurrence_another_entity_records_is_refused_as_an_event(
        self,
        session: DbSession,
        publications: PublicationService,
        kind: str,
    ) -> None:
        """DB 560."""
        publication = whole(
            calls=[call(1), call(2, events=[event(), event(kind=kind, is_error=False)])]
        )

        with (
            writes(session) as wrote,
            pytest.raises(PublicationInvalidException) as refused,
        ):
            publications.publish(publication)

        assert refused.value.faults == [
            f"call `msg_0002`: event 2: an occurrence of the kind `{kind}` is no event"
        ]
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
                ]
            )
        )

        assert session.scalars(
            select(ComponentVersion.released_at).where(
                ComponentVersion.component_code == "claude-code"
            )
        ).one() == STARTED - timedelta(minutes=90)
