"""A Turn's tokens and its cost, read from `claude`'s `result` line (F135.9; DB
272, 273, 275)."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import TokenCount, Turn
from app.models.reference import TokenKind
from app.services.token_counts import Spent, count_tokens, spent
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
