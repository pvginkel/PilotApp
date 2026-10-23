"""The gate every start passes (design 2 §13.4; F141.4, F141.5; DB 229)."""

import pytest

from app.schemas.timeline import HeldReason
from app.services.start_gate import held_reason


class TestHeldReason:
    @pytest.mark.parametrize(
        ("paused", "kind_code", "unreachable", "reason"),
        [
            (False, "work", False, None),
            (True, "work", False, HeldReason.PAUSED),
            (False, "work", True, HeldReason.CONTROLLER_UNREACHABLE),
            # The pause comes first: the outage is the gold bar's.
            (True, "work", True, HeldReason.PAUSED),
            (True, "job", False, HeldReason.PAUSED),
            # A Chat is never held for the pause, and is for the outage.
            (True, "chat", False, None),
            (True, "chat", True, HeldReason.CONTROLLER_UNREACHABLE),
            (False, "chat", True, HeldReason.CONTROLLER_UNREACHABLE),
        ],
    )
    def test_the_gate_holds_for_the_pause_and_the_outage(
        self,
        paused: bool,
        kind_code: str,
        unreachable: bool,
        reason: HeldReason | None,
    ) -> None:
        assert (
            held_reason(paused=paused, kind_code=kind_code, unreachable=unreachable)
            == reason
        )
