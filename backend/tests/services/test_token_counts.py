"""A Turn's own tokens and its cost, read from `claude`'s `result` line
(F135.9; DB 272, 273, 275)."""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import Environment, Project, TokenCount, Turn
from app.models.reference import RecordKind, SessionState, TokenKind
from app.services.container import ServiceContainer
from app.services.token_counts import Spent, count_tokens, reported_before, spent
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.fake_controller import raw_turn

KINDS = (TokenKind.INPUT, TokenKind.CACHE_WRITE, TokenKind.CACHE_READ, TokenKind.OUTPUT)


def _result_line(name: str) -> dict[str, Any]:
    """The `result` line of the invented turn `name`."""
    (line,) = (
        parsed
        for parsed in map(json.loads, raw_turn(name))
        if parsed["type"] == "result"
    )
    return line


def _tokens(*counts: int) -> dict[TokenKind, int]:
    return dict(zip(KINDS, counts, strict=True))


def _models(**entries: dict[str, Any]) -> dict[str, Any]:
    """A `result` line of `claude`'s whose `modelUsage` is `entries`."""
    return {**_result_line("turn_text"), "modelUsage": entries}


TEXT = Spent(_tokens(3, 350, 1200, 11), Decimal("0.0021"))
"""What the invented `turn_text` run reports, a conversation's first."""
RESUMED = Spent(_tokens(6, 470, 2750, 20), Decimal("0.0029"))
"""What the invented `turn_resumed` run reports: it carries `turn_text`'s
conversation on, so its line holds the conversation's figures so far."""
RESUMED_OWN = Spent(_tokens(3, 120, 1550, 9), Decimal("0.0008"))
"""What `turn_resumed`'s run spent itself."""


class TestSpent:
    @pytest.mark.parametrize(
        ("name", "tokens", "cost"),
        [
            ("turn_text", _tokens(3, 350, 1200, 11), "0.0021"),
            ("turn_tool", _tokens(6, 350, 2400, 35), "0.0034"),
            ("turn_wall", _tokens(0, 0, 0, 0), "0"),
        ],
    )
    def test_a_result_line_reports_its_runs_tokens_and_cost(
        self, name: str, tokens: dict[TokenKind, int], cost: str
    ) -> None:
        assert spent(_result_line(name)) == Spent(tokens, Decimal(cost))

    def test_a_sub_agents_calls_count_with_the_main_threads(self) -> None:
        """`usage` counts the main thread's calls alone; `modelUsage` every
        model the run called, the sub-agent's on a model of its own too."""
        line = _result_line("turn_subagent")

        assert line["usage"]["input_tokens"] == 6
        assert spent(line) == Spent(_tokens(12, 2150, 2400, 49), Decimal("0.0043"))

    def test_a_count_a_model_leaves_out_is_0(self) -> None:
        line = _models(
            main={"inputTokens": 4, "outputTokens": 9},
            small={"cacheReadInputTokens": 700},
        )

        assert spent(line) == Spent(_tokens(4, 0, 700, 9), Decimal("0.0021"))

    def test_a_run_that_called_no_model_spent_none(self) -> None:
        assert spent(_models()) == Spent(_tokens(0, 0, 0, 0), Decimal("0.0021"))

    @pytest.mark.parametrize(
        "line",
        [
            {"type": "assistant", "message": {"content": []}},
            {"type": "rate_limit_event", "modelUsage": {}},
            {"modelUsage": {}},
            "The badge reads green.",
            None,
            [],
        ],
    )
    def test_any_other_line_reports_nothing(self, line: Any) -> None:
        assert spent(line) is None

    @pytest.mark.parametrize(
        "model_usage",
        [
            None,
            [],
            {"main": 3},
            {"main": {"inputTokens": -1}},
            {"main": {"outputTokens": "11"}},
            {"main": {"cacheReadInputTokens": 1.5}},
            {"main": {"cacheCreationInputTokens": True}},
            {"main": {"inputTokens": 3}, "small": {"inputTokens": None}},
        ],
    )
    def test_a_result_line_whose_model_usage_is_not_claudes_reports_nothing(
        self, model_usage: Any
    ) -> None:
        line = {**_result_line("turn_text"), "modelUsage": model_usage}

        assert spent(line) is None

    def test_a_result_line_without_model_usage_reports_nothing(self) -> None:
        line = _result_line("turn_text")
        del line["modelUsage"]

        assert spent(line) is None

    @pytest.mark.parametrize("cost", [None, "0.0021", -0.0021, True, float("inf")])
    def test_a_cost_that_is_no_amount_is_none(self, cost: Any) -> None:
        line = {**_result_line("turn_text"), "total_cost_usd": cost}

        assert spent(line) == Spent(_tokens(3, 350, 1200, 11), None)

    def test_a_result_line_without_a_cost_has_none(self) -> None:
        line = _result_line("turn_text")
        del line["total_cost_usd"]

        assert spent(line) == Spent(_tokens(3, 350, 1200, 11), None)

    def test_a_cost_keeps_the_figure_the_line_gives(self) -> None:
        line = {**_result_line("turn_text"), "total_cost_usd": 0.0023345450000000004}

        reported = spent(line)

        assert reported is not None
        assert reported.cost == Decimal("0.0023345450000000004")


class TestLess:
    def test_figures_carrying_the_conversation_on_are_less_those_before(
        self,
    ) -> None:
        assert RESUMED.less(TEXT) == RESUMED_OWN

    def test_with_nothing_before_the_figures_are_their_own(self) -> None:
        assert RESUMED.less(None) == RESUMED

    def test_figures_equal_to_those_before_spent_nothing(self) -> None:
        assert TEXT.less(TEXT) == Spent(_tokens(0, 0, 0, 0), Decimal("0"))

    @pytest.mark.parametrize(
        "fresh",
        [
            Spent(_tokens(6, 470, 1100, 20), Decimal("0.0029")),
            Spent(_tokens(2, 470, 2750, 20), Decimal("0.0029")),
            Spent(_tokens(6, 470, 2750, 20), Decimal("0.0019")),
        ],
    )
    def test_figures_with_any_below_its_own_before_are_a_fresh_total(
        self, fresh: Spent
    ) -> None:
        assert fresh.less(TEXT) == fresh

    def test_a_line_without_a_cost_has_none_of_its_own(self) -> None:
        assert Spent(RESUMED.tokens, None).less(TEXT) == Spent(RESUMED_OWN.tokens, None)

    def test_with_no_cost_before_the_cost_is_the_lines(self) -> None:
        assert RESUMED.less(Spent(TEXT.tokens, None)) == Spent(
            RESUMED_OWN.tokens, RESUMED.cost
        )


@pytest.fixture
def turn(session: DbSession, project_session: models.Session) -> Turn:
    sent = Turn(
        session_id=project_session.id,
        seq=1,
        message="Fix the client for v4.",
        started_at=datetime(2026, 10, 30, 9, 30, tzinfo=UTC),
    )
    session.add(sent)
    session.flush()
    return sent


def _spent(db: DbSession, turn: Turn) -> tuple[dict[TokenKind, int], Decimal | None]:
    counts = db.execute(
        select(TokenCount.token_kind_code, TokenCount.tokens).where(
            TokenCount.turn_id == turn.id
        )
    ).all()
    db.refresh(turn)
    return dict(counts), turn.cost


CAMP = _result_line("turn_text")["session_id"]
"""The conversation the invented turns' lines name."""


class _Conversation:
    """One conversation's Sessions, in `project`, and its Turns."""

    def __init__(
        self,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        conversation: str | None,
    ) -> None:
        self.db = container.db_session()
        self._records = container.session_record_service()
        self._project = project
        self._environment = environment
        self._conversation = conversation
        self._offset = 0
        self.session = self.carried_on()

    def carried_on(self) -> models.Session:
        """A Session of the conversation, created anew to carry it on."""
        run = models.Session(
            project_id=self._project.id,
            environment_id=self._environment.id,
            kind_code="work",
            cwd="/work/Example",
            conversation_id=self._conversation,
            token_hash=uuid.uuid4().hex,
            state_code=SessionState.RUNNING,
        )
        self.db.add(run)
        self.db.flush()
        self.session = run
        return run

    def turn(self) -> Turn:
        """The conversation's next Turn, in its latest Session."""
        run = self.session
        run.turns += 1
        sent = Turn(
            session_id=run.id,
            seq=run.turns,
            message="Fix the client for v4.",
            started_at=datetime(2026, 10, 30, 9, 30, tzinfo=UTC),
        )
        self.db.add(sent)
        self.db.flush()
        return sent

    def printed(self, turn: Turn, *lines: Any) -> None:
        """`claude` printed `lines` in the Turn, recorded and counted as the
        relay records and counts them."""
        for line in lines:
            self._records.append(
                turn.session_id,
                RecordKind.CLAUDE,
                payload=line,
                turn_id=turn.id,
                raw_offset=self._offset,
                controller_session="claude-1",
            )
            self._offset += len(json.dumps(line)) + 1
            count_tokens(self.db, turn.id, line)


@pytest.fixture
def conversation(
    container: ServiceContainer,
    project: Project,
    environment: Environment,
    _no_callbacks: None,
) -> _Conversation:
    """The invented turns' conversation, its first Session created."""
    return _Conversation(container, project, environment, CAMP)


@pytest.fixture
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


def _figures(
    line: dict[str, Any], tokens: dict[TokenKind, int], cost: float
) -> dict[str, Any]:
    """The `result` line `line`, its `modelUsage` reporting `tokens` on one
    model and its cost `cost`."""
    fields = {
        TokenKind.INPUT: "inputTokens",
        TokenKind.CACHE_WRITE: "cacheCreationInputTokens",
        TokenKind.CACHE_READ: "cacheReadInputTokens",
        TokenKind.OUTPUT: "outputTokens",
    }
    return {
        **line,
        "total_cost_usd": cost,
        "modelUsage": {
            "claude-example-1": {fields[kind]: count for kind, count in tokens.items()}
        },
    }


class TestCountTokens:
    def test_a_result_line_writes_the_turns_counts_and_cost(
        self, session: DbSession, turn: Turn
    ) -> None:
        count_tokens(session, turn.id, _result_line("turn_subagent"))

        assert _spent(session, turn) == (
            _tokens(12, 2150, 2400, 49),
            Decimal("0.0043"),
        )

    def test_a_later_result_line_of_the_run_writes_its_figures_in_their_place(
        self, session: DbSession, turn: Turn
    ) -> None:
        """A run's `result` lines carry its figures so far: the last one's
        stand."""
        count_tokens(session, turn.id, _result_line("turn_text"))
        later = {**_result_line("turn_tool"), "total_cost_usd": None}

        count_tokens(session, turn.id, later)

        assert _spent(session, turn) == (_tokens(6, 350, 2400, 35), None)

    def test_a_line_that_reports_nothing_writes_nothing(
        self, session: DbSession, turn: Turn
    ) -> None:
        count_tokens(session, turn.id, _result_line("turn_text"))

        for line in (
            {"type": "assistant", "message": {"content": []}},
            {**_result_line("turn_tool"), "modelUsage": None},
        ):
            count_tokens(session, turn.id, line)

        assert _spent(session, turn) == (
            _tokens(3, 350, 1200, 11),
            Decimal("0.0021"),
        )

    def test_a_turn_with_no_result_line_has_neither(
        self, session: DbSession, turn: Turn
    ) -> None:
        count_tokens(session, turn.id, {"type": "assistant", "message": {}})

        assert _spent(session, turn) == ({}, None)

    def test_a_resumed_turns_line_writes_its_own_figures(
        self, session: DbSession, conversation: _Conversation
    ) -> None:
        first = conversation.turn()
        conversation.printed(first, _result_line("turn_text"))
        resumed = conversation.turn()

        conversation.printed(resumed, _result_line("turn_resumed"))

        assert _spent(session, first) == (TEXT.tokens, TEXT.cost)
        assert _spent(session, resumed) == (RESUMED_OWN.tokens, RESUMED_OWN.cost)

    def test_each_line_of_a_resumed_run_is_taken_against_the_turn_before(
        self, session: DbSession, conversation: _Conversation
    ) -> None:
        """A backgrounded task woke the resumed run again: its later line
        carries the earlier one's figures, and its own stand."""
        first = conversation.turn()
        conversation.printed(first, _result_line("turn_text"))
        resumed = conversation.turn()
        conversation.printed(
            resumed,
            _figures(_result_line("turn_resumed"), _tokens(4, 400, 2000, 15), 0.0025),
        )

        conversation.printed(resumed, _result_line("turn_resumed"))

        assert _spent(session, resumed) == (RESUMED_OWN.tokens, RESUMED_OWN.cost)


class TestReportedBefore:
    def test_a_conversations_first_turn_has_nothing_before_it(
        self, session: DbSession, conversation: _Conversation
    ) -> None:
        first = conversation.turn()

        assert reported_before(session, first.id) is None

    def test_a_turn_of_a_session_with_no_conversation_has_nothing_before_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        _no_callbacks: None,
    ) -> None:
        unnamed = _Conversation(container, project, environment, None)
        first = unnamed.turn()
        unnamed.printed(first, _result_line("turn_text"))

        assert reported_before(session, unnamed.turn().id) is None

    def test_it_is_the_previous_turns_last_line_that_reports(
        self, session: DbSession, conversation: _Conversation
    ) -> None:
        """Its earlier line and a later `result` line that reports nothing
        are not what the conversation reported last."""
        first = conversation.turn()
        conversation.printed(
            first,
            _figures(_result_line("turn_text"), _tokens(1, 350, 400, 5), 0.0009),
            _result_line("turn_text"),
            {**_result_line("turn_tool"), "modelUsage": None},
        )

        assert reported_before(session, conversation.turn().id) == TEXT

    def test_a_turn_with_no_result_line_is_passed_over(
        self, session: DbSession, conversation: _Conversation
    ) -> None:
        """A turn cut before `claude` printed its `result` line."""
        first = conversation.turn()
        conversation.printed(first, _result_line("turn_text"))
        cut = conversation.turn()
        conversation.printed(cut, {"type": "assistant", "message": {}})

        assert reported_before(session, conversation.turn().id) == TEXT

    def test_the_conversation_spans_its_sessions(
        self, session: DbSession, conversation: _Conversation
    ) -> None:
        first = conversation.turn()
        conversation.printed(first, _result_line("turn_text"))
        conversation.carried_on()

        assert reported_before(session, conversation.turn().id) == TEXT

    def test_another_conversations_turns_are_not_its(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        conversation: _Conversation,
    ) -> None:
        first = conversation.turn()
        conversation.printed(first, _result_line("turn_text"))
        other = _Conversation(
            container, project, environment, "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
        )
        other.printed(other.turn(), _result_line("turn_tool"))

        assert reported_before(session, conversation.turn().id) == TEXT

    def test_a_later_turn_is_not_before_it(
        self, session: DbSession, conversation: _Conversation
    ) -> None:
        first = conversation.turn()
        later = conversation.turn()
        conversation.printed(later, _result_line("turn_text"))

        assert reported_before(session, first.id) is None
