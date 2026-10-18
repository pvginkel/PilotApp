"""The block DSL's types."""

import pytest

from app.engine.dsl import AnswerChannel, BlockKind, parse
from app.models import reference


class TestAnswerChannel:
    def test_its_values_are_the_record_s(self) -> None:
        assert {str(channel) for channel in AnswerChannel} == {
            str(channel) for channel in reference.AnswerChannel
        }


class TestBlockKind:
    def test_its_values_are_the_record_s(self) -> None:
        assert {str(kind) for kind in BlockKind} == {
            str(kind) for kind in reference.BlockKind
        }


class TestBlock:
    @pytest.mark.parametrize(
        ("lines", "answered"),
        [
            ("answer: Oak\nby: ada", True),
            ("answer: deferred\nby: agent\nto: plan", True),
            ("done: 2026-10-12T09:40:00Z\nby: ben", True),
            ("note: not yet", False),
            ("", False),
        ],
    )
    def test_answered_is_an_answer_or_done(self, lines: str, answered: bool) -> None:
        [block] = parse(f"```action id=A1\n{lines}\n```\n").blocks

        assert block.answered is answered
