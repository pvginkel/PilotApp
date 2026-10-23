"""The controller unreachable, the process's own state (design 2 §13.4; review
O2): on at a call with no answer and while the fleet stream is down, off at the
fleet stream's reconnect and at the probe's success while it is up."""

import pytest

from app.services.controller_outage import ControllerOutage


def _turns(outage: ControllerOutage) -> list[bool]:
    """What a listener of the outage reads at each turn."""
    seen: list[bool] = []
    outage.subscribe(lambda: seen.append(outage.holds))
    return seen


class TestControllerOutage:
    def test_a_fresh_one_is_off(self) -> None:
        outage = ControllerOutage()

        assert (outage.holds, outage.since) == (False, None)

    def test_a_call_unanswered_turns_it_on_once(self) -> None:
        outage = ControllerOutage()
        turns = _turns(outage)

        outage.call_unanswered()
        since = outage.since
        outage.call_unanswered()

        assert outage.holds
        assert since is not None and outage.since == since
        assert turns == [True]

    def test_the_probes_answer_turns_it_off(self) -> None:
        outage = ControllerOutage()
        turns = _turns(outage)
        outage.call_unanswered()

        outage.probe_answered()
        outage.probe_answered()

        assert (outage.holds, outage.since) == (False, None)
        assert turns == [True, False]

    def test_it_holds_while_the_fleet_stream_is_down_whatever_the_probe_finds(
        self,
    ) -> None:
        outage = ControllerOutage()
        turns = _turns(outage)

        outage.fleet_stream_down()
        outage.probe_answered()

        assert outage.holds
        assert turns == [True]

    @pytest.mark.parametrize("cause", ["call", "fleet"])
    def test_the_fleet_streams_reconnect_turns_it_off(self, cause: str) -> None:
        outage = ControllerOutage()
        turns = _turns(outage)
        if cause == "call":
            outage.call_unanswered()
        else:
            outage.fleet_stream_down()

        outage.fleet_stream_up()

        assert not outage.holds
        assert turns == [True, False]

    def test_a_reconnect_with_nothing_on_turns_nothing(self) -> None:
        outage = ControllerOutage()
        turns = _turns(outage)

        outage.fleet_stream_up()
        outage.probe_answered()

        assert turns == []

    def test_a_listener_that_fails_keeps_the_turn_from_no_other(self) -> None:
        outage = ControllerOutage()

        def fails() -> None:
            raise RuntimeError("a listener fails")

        outage.subscribe(fails)
        turns = _turns(outage)

        outage.call_unanswered()

        assert turns == [True]
