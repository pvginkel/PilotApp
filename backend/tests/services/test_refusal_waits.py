"""The wait on a file call the controller keeps refusing for a reason of its
own (P-64; V02, V17): each call's from the round of its first refusal counted,
judged at a round's start, so that the calls of one round wait side by side."""

import time

from app.services.refusal_waits import RefusalWaits

WAIT = 0.05


class TestRefusalWaits:
    def test_a_wait_passes_at_the_first_round_its_length_past_its_start(
        self,
    ) -> None:
        waits = RefusalWaits(WAIT, 1.0)
        waits.round(["a"])
        assert not waits.passed("a")
        assert "a" in waits
        waits.round(["a"])
        assert not waits.passed("a")

        time.sleep(WAIT + 0.01)
        waits.round(["a"])

        assert waits.passed("a")
        assert "a" not in waits

    def test_a_wait_of_none_passes_at_the_first_refusal(self) -> None:
        waits = RefusalWaits(0.0, 1.0)
        waits.round(["a"])

        assert waits.passed("a")

    def test_the_waits_started_in_one_round_pass_in_one(self) -> None:
        waits = RefusalWaits(WAIT, 1.0)
        waits.round(["a", "b"])
        assert not waits.passed("a")
        time.sleep(WAIT + 0.01)
        # Started with the round, and judged at its start.
        assert not waits.passed("b")

        waits.round(["a", "b"])

        assert (waits.passed("a"), waits.passed("b")) == (True, True)

    def test_a_restart_starts_the_wait_afresh_from_the_next_refusal(self) -> None:
        waits = RefusalWaits(WAIT, 1.0)
        waits.round(["a"])
        waits.passed("a")
        time.sleep(WAIT + 0.01)
        waits.round(["a"])

        waits.restart("a")

        assert "a" not in waits
        waits.round(["a"])
        assert not waits.passed("a")

    def test_a_round_drops_the_waits_of_the_calls_no_longer_owed(self) -> None:
        waits = RefusalWaits(WAIT, 1.0)
        waits.round(["a", "b"])
        waits.passed("a")
        waits.passed("b")

        waits.round(["b"])

        assert ("a" in waits, "b" in waits) == (False, True)

    def test_the_pause_is_the_retrys_or_less_when_a_wait_passes_sooner(
        self,
    ) -> None:
        long = RefusalWaits(10.0, 0.5)
        long.round(["a"])
        assert long.pause() == 0.5
        long.passed("a")
        assert long.pause() == 0.5
        short = RefusalWaits(WAIT, 5.0)
        short.round(["a"])
        short.passed("a")

        assert 0.0 < short.pause() <= WAIT
        time.sleep(WAIT + 0.01)
        assert short.pause() == 0.0
