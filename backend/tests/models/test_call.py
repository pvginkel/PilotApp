"""Call, Price, Tool Call, Event and Context Part, and a Model priced as
another: what a row must hold (DB §2.7, §2.11; the assertions of §4.31)."""

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.models import (
    Call,
    ComponentVersion,
    ContextPart,
    ContextPartKind,
    DenialKind,
    Event,
    EventKind,
    Launch,
    MissCause,
    Model,
    Price,
    StopReason,
    TokenKind,
    Tool,
    ToolCall,
    Transcript,
)
from app.models.call import PRICED_KINDS
from tests.support import transcripts
from tests.support.database import violated_constraint
from tests.support.transcripts import HAIKU, OPUS, OTHER, STARTED, SUB_AGENT

PANTRY = "claude-pantry-2"
"""An invented model."""


@pytest.fixture
def collector(session: DbSession) -> ComponentVersion:
    """The collector's version that reads the transcripts."""
    return transcripts.component_version(session)


@pytest.fixture
def thread(session: DbSession, collector: ComponentVersion) -> Transcript:
    """A main thread, with the model that answers its Calls and the tool
    they call met."""
    transcripts.reference(session, Model, OPUS)
    transcripts.reference(session, Tool, "Bash")
    return transcripts.transcript(session, collector)


@pytest.fixture
def other(session: DbSession, collector: ComponentVersion) -> Transcript:
    """Another main thread."""
    return transcripts.transcript(session, collector, session_id=OTHER)


@pytest.fixture
def request_(session: DbSession, thread: Transcript) -> Call:
    """The main thread's first Call."""
    return transcripts.call(session, thread, 1)


def _count(db: DbSession, entity: type) -> int:
    return db.scalar(select(func.count()).select_from(entity)) or 0


def _violated_at_commit(session: DbSession) -> str:
    """Flush, check the deferred constraints as a commit does, and return the
    name of the one violated."""
    session.flush()
    with pytest.raises(IntegrityError) as raised:
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    return raised.value.orig.diag.constraint_name


class TestCall:
    def test_a_call_holds_what_its_publication_gave(
        self, session: DbSession, thread: Transcript
    ) -> None:
        start = transcripts.launch(session, thread)
        opening = transcripts.prompt(session, start)
        made = transcripts.compaction(session, thread)
        for entity, code in (
            (Model, HAIKU),
            (StopReason, "max_tokens"),
            (MissCause, "compaction"),
        ):
            transcripts.reference(session, entity, code)
        first = transcripts.call(session, thread, 1, prompt_id=opening.id)
        second = transcripts.call(
            session,
            thread,
            2,
            prompt_id=opening.id,
            predecessor_id=first.id,
            compaction_id=made.id,
            sent_at=STARTED + timedelta(seconds=95),
            model_code=HAIKU,
            requested_model_code=OPUS,
            effort="high",
            stop_reason_code="max_tokens",
            thinking_tokens=640,
            attributed_skill="garden:planting",
            attributed_plugin="garden",
            miss_cause_code="compaction",
        )
        session.expire_all()

        assert (first.message_id, first.position) == ("msg_0001", 1)
        assert first.completed_at == STARTED + timedelta(minutes=1)
        assert (first.predecessor_id, first.compaction_id) == (None, None)
        assert (first.sent_at, first.requested_model_code) == (None, None)
        assert (first.effort, first.stop_reason_code) == (None, None)
        assert (first.thinking_tokens, first.miss_cause_code) == (None, None)
        assert (first.attributed_skill, first.attributed_plugin) == (None, None)
        assert (second.prompt_id, second.predecessor_id) == (opening.id, first.id)
        assert second.compaction_id == made.id
        assert second.sent_at == STARTED + timedelta(seconds=95)
        assert (second.model_code, second.requested_model_code) == (HAIKU, OPUS)
        assert (second.effort, second.stop_reason_code) == ("high", "max_tokens")
        assert (second.thinking_tokens, second.miss_cause_code) == (640, "compaction")
        assert second.attributed_skill == "garden:planting"
        assert second.attributed_plugin == "garden"

    def test_its_tokens_are_a_column_per_token_kind_nothing_is_within(
        self, session: DbSession, request_: Call
    ) -> None:
        """Call Token Count has no table (DB §7.7); its kinds are 547's, and
        a Price is of one of them."""
        kinds = set(session.scalars(select(TokenKind.code)))
        coarser = set(
            session.scalars(
                select(TokenKind.within_code).where(TokenKind.within_code.is_not(None))
            )
        )
        session.expire(request_)

        columns = {
            column.name.removesuffix("_tokens")
            for column in Call.__table__.columns
            if column.name.endswith("_tokens")
            and not column.nullable
            and column.computed is None
        }
        assert columns == kinds - coarser == set(PRICED_KINDS)
        assert {kind: getattr(request_, f"{kind}_tokens") for kind in columns} == {
            "input": 1_204,
            "cache_write_5m": 0,
            "cache_write_1h": 3_310,
            "cache_read": 48_112,
            "output": 2_870,
        }

    def test_its_context_tokens_are_its_tokens_of_the_input_and_cache_kinds(
        self, session: DbSession, request_: Call
    ) -> None:
        assert request_.context_tokens == 1_204 + 3_310 + 48_112

        request_.cache_write_5m_tokens = 500
        request_.output_tokens = 9_000
        session.flush()
        session.expire(request_)

        assert request_.context_tokens == 1_204 + 500 + 3_310 + 48_112

    def test_it_holds_no_cost_until_it_is_priced(
        self, session: DbSession, request_: Call
    ) -> None:
        session.expire(request_)

        assert request_.cost is None

    def test_a_sub_agents_call_follows_no_prompt(
        self, session: DbSession, collector: ComponentVersion
    ) -> None:
        sub_agent = transcripts.transcript(session, collector, agent_id=SUB_AGENT)

        request = transcripts.call(session, sub_agent, 1)

        assert request.prompt_id is None

    def test_its_message_id_is_unique_in_its_transcript(
        self, session: DbSession, thread: Transcript, request_: Call
    ) -> None:
        session.add(_call(thread, 2, message_id="msg_0001"))

        assert violated_constraint(session) == "calls_transcript_id_message_id_key"

    def test_another_transcript_holds_the_same_message_id_and_position(
        self, session: DbSession, other: Transcript, request_: Call
    ) -> None:
        transcripts.call(session, other, 1)
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

        assert _count(session, Call) == 2

    def test_its_position_is_unique_in_its_transcript(
        self, session: DbSession, thread: Transcript, request_: Call
    ) -> None:
        session.add(_call(thread, 1, message_id="msg_0002"))

        assert _violated_at_commit(session) == "uq_calls_transcript_id_position"

    def test_a_transcripts_calls_move_up_in_one_transaction(
        self, session: DbSession, thread: Transcript, request_: Call
    ) -> None:
        """The positions' uniqueness is checked at the commit, so a
        publication of a file that lost a Call moves the later ones through
        a repeated position on the way."""
        second = transcripts.call(session, thread, 2)
        third = transcripts.call(session, thread, 3)
        session.delete(request_)
        third.position = 2
        session.flush()
        second.position = 1
        session.flush()
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

        positions = session.execute(
            select(Call.message_id, Call.position)
            .where(Call.transcript_id == thread.id)
            .order_by(Call.position)
        ).all()
        assert positions == [("msg_0002", 1), ("msg_0003", 2)]

    def test_its_position_is_from_one(
        self, session: DbSession, thread: Transcript
    ) -> None:
        session.add(_call(thread, 0))

        assert violated_constraint(session) == "ck_calls_position"

    def test_it_is_made_by_a_transcript(
        self, session: DbSession, thread: Transcript
    ) -> None:
        session.add(_call(thread, 1, transcript_id=uuid.uuid4()))

        assert violated_constraint(session) == "calls_transcript_id_fkey"

    def test_the_prompt_it_follows_is_its_own_transcripts(
        self, session: DbSession, thread: Transcript, other: Transcript
    ) -> None:
        """DB 542."""
        opening = transcripts.prompt(session, transcripts.launch(session, other))
        session.add(_call(thread, 1, prompt_id=opening.id))

        assert violated_constraint(session) == "calls_transcript_id_prompt_id_fkey"

    def test_its_predecessor_is_its_own_transcripts(
        self, session: DbSession, thread: Transcript, other: Transcript
    ) -> None:
        """DB 545."""
        elsewhere = transcripts.call(session, other, 1)
        session.add(_call(thread, 1, predecessor_id=elsewhere.id))

        assert violated_constraint(session) == "calls_transcript_id_predecessor_id_fkey"

    def test_its_compaction_is_its_own_transcripts(
        self, session: DbSession, thread: Transcript, other: Transcript
    ) -> None:
        """DB 545."""
        made = transcripts.compaction(session, other)
        session.add(_call(thread, 1, compaction_id=made.id))

        assert violated_constraint(session) == "calls_transcript_id_compaction_id_fkey"

    def test_a_rewind_forks_the_chain(
        self, session: DbSession, thread: Transcript, request_: Call
    ) -> None:
        """Two Calls follow one (DB 407)."""
        for position in (2, 3):
            transcripts.call(session, thread, position, predecessor_id=request_.id)

        followers = session.scalars(
            select(Call.position).where(Call.predecessor_id == request_.id)
        ).all()
        assert sorted(followers) == [2, 3]

    @pytest.mark.parametrize(
        ("column", "constraint"),
        [
            ("model_code", "calls_model_code_fkey"),
            ("requested_model_code", "calls_requested_model_code_fkey"),
            ("stop_reason_code", "calls_stop_reason_code_fkey"),
            ("miss_cause_code", "calls_miss_cause_code_fkey"),
        ],
    )
    def test_what_classifies_it_is_held(
        self, session: DbSession, request_: Call, column: str, constraint: str
    ) -> None:
        setattr(request_, column, "other")

        assert violated_constraint(session) == constraint

    def test_the_model_asked_for_is_held_where_it_differs(
        self, session: DbSession, request_: Call
    ) -> None:
        request_.requested_model_code = OPUS

        assert violated_constraint(session) == "ck_calls_requested_model"

    @pytest.mark.parametrize(
        "column",
        [
            "input_tokens",
            "cache_write_5m_tokens",
            "cache_write_1h_tokens",
            "cache_read_tokens",
            "output_tokens",
            "thinking_tokens",
        ],
    )
    def test_its_tokens_are_never_negative(
        self, session: DbSession, request_: Call, column: str
    ) -> None:
        setattr(request_, column, -1)

        assert violated_constraint(session) == "ck_calls_tokens"

    def test_a_prompt_a_call_follows_does_not_go(
        self, session: DbSession, thread: Transcript
    ) -> None:
        start = transcripts.launch(session, thread)
        opening = transcripts.prompt(session, start)
        transcripts.call(session, thread, 1, prompt_id=opening.id)
        session.expunge_all()

        with pytest.raises(IntegrityError) as raised:
            session.execute(Launch.__table__.delete().where(Launch.id == start.id))

        assert (
            raised.value.orig.diag.constraint_name
            == "calls_transcript_id_prompt_id_fkey"
        )

    def test_a_call_another_follows_does_not_go(
        self, session: DbSession, thread: Transcript, request_: Call
    ) -> None:
        transcripts.call(session, thread, 2, predecessor_id=request_.id)
        session.delete(request_)

        assert violated_constraint(session) == "calls_transcript_id_predecessor_id_fkey"


def _call(thread: Transcript, position: int, **overrides: object) -> Call:
    """A Call of the main thread, not yet added, answered by the model the
    thread's first Call was."""
    values: dict[str, object] = {
        "transcript_id": thread.id,
        "message_id": f"msg_{position:04}",
        "position": position,
        "completed_at": STARTED + timedelta(minutes=position),
        "model_code": OPUS,
        "input_tokens": 6,
        "cache_write_5m_tokens": 0,
        "cache_write_1h_tokens": 0,
        "cache_read_tokens": 0,
        "output_tokens": 820,
    }
    values.update(overrides)
    return Call(**values)


class TestModel:
    def test_it_is_priced_as_another_model(self, session: DbSession) -> None:
        newer = Model(code="claude-opus-9", name="claude-opus-9", priced_as_code=OPUS)
        session.add(newer)
        session.flush()
        session.expire(newer)

        assert newer.priced_as_code == OPUS

    def test_it_is_not_priced_as_itself(self, session: DbSession) -> None:
        session.add(
            Model(
                code="claude-opus-9",
                name="claude-opus-9",
                priced_as_code="claude-opus-9",
            )
        )

        assert violated_constraint(session) == "ck_models_priced_as"

    def test_the_model_it_is_priced_as_is_held(self, session: DbSession) -> None:
        session.add(
            Model(code="claude-opus-9", name="claude-opus-9", priced_as_code="opus")
        )

        assert violated_constraint(session) == "models_priced_as_code_fkey"


def _price(**overrides: Any) -> Price:
    """An invented model's input rate, the model met."""
    values: dict[str, Any] = {
        "model_code": PANTRY,
        "token_kind_code": "input",
        "rate": Decimal("3"),
        "effective_at": STARTED,
    }
    return Price(**values | overrides)


@pytest.fixture
def pantry(session: DbSession) -> Model:
    """An invented model, which the price file does not name."""
    return transcripts.reference(session, Model, PANTRY)


@pytest.mark.usefixtures("pantry")
class TestPrice:
    def test_a_price_holds_a_models_rate_for_a_kind_from_a_moment_on(
        self, session: DbSession
    ) -> None:
        base = _price()
        tier = _price(above_context=100_001, rate=Decimal("6.5"))
        session.add_all([base, tier])
        session.flush()
        session.expire_all()

        assert (base.model_code, base.token_kind_code) == (PANTRY, "input")
        assert (base.above_context, base.rate) == (None, Decimal("3"))
        assert base.effective_at == STARTED
        assert (tier.above_context, tier.rate) == (100_001, Decimal("6.5"))

    def test_a_models_rate_for_a_kind_changes_from_a_later_moment(
        self, session: DbSession
    ) -> None:
        session.add_all(
            [
                _price(),
                _price(rate=Decimal("4"), effective_at=STARTED + timedelta(days=30)),
            ]
        )

        session.flush()

    @pytest.mark.parametrize("above_context", [None, 100_001])
    def test_two_prices_of_one_model_kind_context_size_and_moment_are_refused(
        self, session: DbSession, above_context: int | None
    ) -> None:
        """DB 549, the base rate's among them, whose context size is none."""
        session.add(_price(above_context=above_context))
        session.flush()
        session.add(_price(above_context=above_context, rate=Decimal("4")))

        assert violated_constraint(session) == (
            "prices_model_code_token_kind_code_above_context_effective_a_key"
        )

    def test_it_is_of_a_kind_nothing_is_within(self, session: DbSession) -> None:
        """DB 547."""
        session.add(_price(token_kind_code="cache_write"))

        assert violated_constraint(session) == "ck_prices_kind"

    def test_it_prices_a_model(self, session: DbSession) -> None:
        session.add(_price(model_code="claude-larder-1"))

        assert violated_constraint(session) == "prices_model_code_fkey"

    def test_its_context_size_is_above_none(self, session: DbSession) -> None:
        session.add(_price(above_context=0))

        assert violated_constraint(session) == "ck_prices_above_context"

    def test_its_rate_is_never_negative(self, session: DbSession) -> None:
        session.add(_price(rate=Decimal("-1")))

        assert violated_constraint(session) == "ck_prices_rate"


class TestToolCall:
    def test_a_tool_call_holds_what_its_publication_gave(
        self, session: DbSession, request_: Call
    ) -> None:
        transcripts.reference(
            session, Tool, "mcp__tracker__get_issues", mcp_server="tracker"
        )
        transcripts.reference(session, DenialKind, "rule")
        plain = transcripts.tool_call(session, request_)
        full = transcripts.tool_call(
            session,
            request_,
            tool_use_id="toolu_0002",
            tool_code="mcp__tracker__get_issues",
            first_argument="project: RB",
            returned_at=request_.completed_at + timedelta(seconds=4),
            failed=True,
            exit_code=2,
            interrupted=True,
            denial_kind_code="rule",
            result_characters=1_800,
            saved_characters=64_000,
        )
        session.expire_all()

        assert (plain.tool_code, plain.tool_use_id) == ("Bash", "toolu_0001")
        assert (plain.first_argument, plain.returned_at) == (None, None)
        assert (plain.failed, plain.interrupted) == (False, False)
        assert (plain.exit_code, plain.denial_kind_code) == (None, None)
        assert (plain.result_characters, plain.saved_characters) == (None, None)
        assert full.first_argument == "project: RB"
        assert full.returned_at == request_.completed_at + timedelta(seconds=4)
        assert (full.failed, full.exit_code, full.interrupted) == (True, 2, True)
        assert full.denial_kind_code == "rule"
        assert (full.result_characters, full.saved_characters) == (1_800, 64_000)
        assert session.get_one(Tool, full.tool_code).mcp_server == "tracker"

    def test_its_tool_use_id_is_unique_in_its_transcript(
        self, session: DbSession, thread: Transcript, request_: Call
    ) -> None:
        transcripts.tool_call(session, request_)
        later = transcripts.call(session, thread, 2)
        session.add(_tool_call(later))

        assert (
            violated_constraint(session) == "tool_calls_transcript_id_tool_use_id_key"
        )

    def test_another_transcript_holds_the_same_tool_use_id(
        self, session: DbSession, other: Transcript, request_: Call
    ) -> None:
        transcripts.tool_call(session, request_)
        transcripts.tool_call(session, transcripts.call(session, other, 1))

        assert _count(session, ToolCall) == 2

    def test_the_transcript_it_carries_is_its_calls(
        self, session: DbSession, other: Transcript, request_: Call
    ) -> None:
        session.add(_tool_call(request_, transcript_id=other.id))

        assert violated_constraint(session) == "tool_calls_transcript_id_call_id_fkey"

    @pytest.mark.parametrize(
        ("column", "constraint"),
        [
            ("tool_code", "tool_calls_tool_code_fkey"),
            ("denial_kind_code", "tool_calls_denial_kind_code_fkey"),
        ],
    )
    def test_what_classifies_it_is_held(
        self, session: DbSession, request_: Call, column: str, constraint: str
    ) -> None:
        requested = transcripts.tool_call(session, request_)
        setattr(requested, column, "other")

        assert violated_constraint(session) == constraint

    def test_an_exit_code_is_held_where_it_was_not_zero(
        self, session: DbSession, request_: Call
    ) -> None:
        session.add(_tool_call(request_, exit_code=0))

        assert violated_constraint(session) == "ck_tool_calls_exit_code"

    def test_one_a_hook_denied_is_failed(
        self, session: DbSession, request_: Call
    ) -> None:
        """DB 587."""
        transcripts.reference(session, DenialKind, "hook")
        denied = transcripts.tool_call(
            session, request_, denial_kind_code="hook", failed=True
        )
        denied.failed = False

        assert violated_constraint(session) == "ck_tool_calls_denied_by_hook"

    @pytest.mark.parametrize("column", ["result_characters", "saved_characters"])
    def test_its_sizes_are_never_negative(
        self, session: DbSession, request_: Call, column: str
    ) -> None:
        session.add(_tool_call(request_, **{column: -1}))

        assert violated_constraint(session) == "ck_tool_calls_characters"

    def test_it_goes_with_its_call(
        self, session: DbSession, thread: Transcript, request_: Call
    ) -> None:
        kept = transcripts.tool_call(
            session, transcripts.call(session, thread, 2), tool_use_id="toolu_0002"
        )
        transcripts.tool_call(session, request_)
        session.expunge_all()

        session.execute(Call.__table__.delete().where(Call.id == request_.id))

        assert session.scalars(select(ToolCall.id)).all() == [kept.id]

    def test_a_sub_agent_whose_spawning_call_goes_stays_with_none(
        self,
        session: DbSession,
        collector: ComponentVersion,
        thread: Transcript,
        request_: Call,
    ) -> None:
        spawning = transcripts.tool_call(session, request_)
        sub_agent = transcripts.transcript(
            session,
            collector,
            agent_id=SUB_AGENT,
            main_id=thread.id,
            spawned_by_id=spawning.id,
        )
        session.expunge_all()

        session.execute(Call.__table__.delete().where(Call.id == request_.id))

        kept = session.get_one(Transcript, sub_agent.id)
        assert (kept.main_id, kept.spawned_by_id) == (thread.id, None)


def _tool_call(request: Call, **overrides: object) -> ToolCall:
    """A call of `Bash` the Call requested, not yet added."""
    values: dict[str, object] = {
        "transcript_id": request.transcript_id,
        "call_id": request.id,
        "tool_use_id": "toolu_0001",
        "tool_code": "Bash",
        "requested_at": request.completed_at,
        "failed": False,
        "interrupted": False,
    }
    values.update(overrides)
    return ToolCall(**values)


class TestEvent:
    def test_a_call_is_marked_by_its_events(
        self, session: DbSession, request_: Call
    ) -> None:
        transcripts.reference(session, EventKind, "api_error", is_error=True)
        transcripts.reference(session, EventKind, "interrupt", is_error=False)
        session.add_all(
            [
                Event(
                    call_id=request_.id,
                    kind_code="api_error",
                    at=request_.completed_at,
                    detail="529",
                ),
                Event(
                    call_id=request_.id,
                    kind_code="interrupt",
                    at=request_.completed_at + timedelta(seconds=30),
                ),
            ]
        )
        session.flush()

        events = session.execute(
            select(Event.kind_code, Event.detail, EventKind.is_error)
            .join(EventKind, EventKind.code == Event.kind_code)
            .where(Event.call_id == request_.id)
            .order_by(Event.at)
        ).all()
        assert events == [("api_error", "529", True), ("interrupt", None, False)]

    def test_it_is_classified_by_an_event_kind(
        self, session: DbSession, request_: Call
    ) -> None:
        session.add(
            Event(call_id=request_.id, kind_code="other", at=request_.completed_at)
        )

        assert violated_constraint(session) == "events_kind_code_fkey"

    def test_it_marks_a_call(self, session: DbSession) -> None:
        transcripts.reference(session, EventKind, "api_error", is_error=True)
        session.add(Event(call_id=404, kind_code="api_error", at=STARTED))

        assert violated_constraint(session) == "events_call_id_fkey"

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
    def test_an_occurrence_another_entity_records_is_no_event(
        self, session: DbSession, request_: Call, kind: str
    ) -> None:
        """DB 560."""
        transcripts.reference(session, EventKind, kind, is_error=False)
        session.add(Event(call_id=request_.id, kind_code=kind, at=STARTED))

        assert violated_constraint(session) == "ck_events_kind"

    def test_it_goes_with_its_call(self, session: DbSession, request_: Call) -> None:
        transcripts.reference(session, EventKind, "api_retry", is_error=False)
        session.add(Event(call_id=request_.id, kind_code="api_retry", at=STARTED))
        session.flush()
        session.expunge_all()

        session.execute(Call.__table__.delete().where(Call.id == request_.id))

        assert _count(session, Event) == 0


class TestContextPart:
    def test_a_call_first_carries_its_context_parts(
        self, session: DbSession, request_: Call
    ) -> None:
        for kind in ("system_prompt", "skill_body"):
            transcripts.reference(session, ContextPartKind, kind)
        session.add_all(
            [
                ContextPart(
                    call_id=request_.id, kind_code="system_prompt", characters=9_000
                ),
                ContextPart(
                    call_id=request_.id,
                    kind_code="skill_body",
                    name="garden:planting",
                    characters=0,
                ),
            ]
        )
        session.flush()

        parts = session.execute(
            select(ContextPart.kind_code, ContextPart.name, ContextPart.characters)
            .where(ContextPart.call_id == request_.id)
            .order_by(ContextPart.id)
        ).all()
        assert parts == [
            ("system_prompt", None, 9_000),
            ("skill_body", "garden:planting", 0),
        ]

    def test_it_is_classified_by_a_context_part_kind(
        self, session: DbSession, request_: Call
    ) -> None:
        session.add(ContextPart(call_id=request_.id, kind_code="other", characters=1))

        assert violated_constraint(session) == "context_parts_kind_code_fkey"

    def test_it_is_first_carried_by_a_call(self, session: DbSession) -> None:
        transcripts.reference(session, ContextPartKind, "system_prompt")
        session.add(ContextPart(call_id=404, kind_code="system_prompt", characters=1))

        assert violated_constraint(session) == "context_parts_call_id_fkey"

    def test_its_length_is_never_negative(
        self, session: DbSession, request_: Call
    ) -> None:
        transcripts.reference(session, ContextPartKind, "system_prompt")
        session.add(
            ContextPart(call_id=request_.id, kind_code="system_prompt", characters=-1)
        )

        assert violated_constraint(session) == "ck_context_parts_characters"

    def test_it_goes_with_its_call(self, session: DbSession, request_: Call) -> None:
        transcripts.reference(session, ContextPartKind, "system_prompt")
        session.add(
            ContextPart(call_id=request_.id, kind_code="system_prompt", characters=1)
        )
        session.flush()
        session.expunge_all()

        session.execute(Call.__table__.delete().where(Call.id == request_.id))

        assert _count(session, ContextPart) == 0
