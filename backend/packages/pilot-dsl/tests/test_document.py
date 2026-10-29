"""The block DSL's types."""

import pytest
from pilot_dsl import parse


class TestBlock:
    @pytest.mark.parametrize(
        ("lines", "answered"),
        [
            ("answer: Oak\nby: ada", True),
            ("answer: deferred\nby: agent\nto: plan", True),
            ("done: 2026-10-12T09:40:00Z\nby: ben", True),
            ("note: not yet", False),
            ("", False),
            ("answer: Pilot does it\nby: agent\nnote: Rotating it", False),
            ("answer: Pilot does it\nby: ada", True),
        ],
    )
    def test_answered_is_an_answer_or_done_a_claim_not_until_done(
        self, lines: str, answered: bool
    ) -> None:
        [block] = parse(f"```action id=A1\n{lines}\n```\n").blocks

        assert block.answered is answered

    @pytest.mark.parametrize(
        ("text", "claimed"),
        [
            ("```action id=A1\nanswer: Pilot does it\nby: agent\n```\n", True),
            ("```action id=A1\nanswer: Pilot does it\nby: ada\n```\n", False),
            ("```action id=A1\nanswer: Later\nby: agent\n```\n", False),
            (
                "```question id=Q1\nanswer: Pilot does it\nby: agent\n```\n",
                False,
            ),
            ("```action id=A1\ndone: 2026-10-12T09:40:00Z\nby: agent\n```\n", False),
        ],
    )
    def test_claimed_is_an_action_pilot_said_it_does_and_has_not_done(
        self, text: str, claimed: bool
    ) -> None:
        [block] = parse(text).blocks

        assert block.claimed is claimed
