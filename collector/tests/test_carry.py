"""The carries a collector keeps between walks, and their bound (F152.15)."""

import tracemalloc
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pilot_collector.carry import (
    Carries,
    Carry,
    Lead,
    Left,
    Occurred,
    Open,
    Opening,
    Part,
    Prompted,
    Ran,
    Requested,
    Shape,
    Standing,
    digest,
)

STOOD = datetime(2026, 11, 12, 10, 2, 3, 456789, tzinfo=UTC)


def _carry(
    place: int = 0,
    queued: int = 0,
    removed: int = 0,
    awaited: int = 0,
    requested: int = 0,
    occurred: int = 0,
    ran: int = 0,
    loaded: int = 0,
    injected: int = 0,
) -> Carry:
    """A carry no other shares a word or a time with."""
    return Carry(
        file_size=61_000 + place,
        file_modified_at=STOOD + timedelta(seconds=place),
        collector=f"1.0.{place}",
        stands=Standing(
            byte=48_000 + place,
            calls=300 + place,
            launches=2 + place,
            prompts=400 + place,
            compactions=3 + place,
            link=f"{place:08}-8b2d-4d57-9e3a-71c5d2b8a690",
            leads=Lead(
                f"msg_01{place:022}",
                3 + place,
                Left(
                    place=299 + place,
                    completed_at=STOOD + timedelta(minutes=place),
                    model=f"claude-opus-4-{place}",
                    effort=f"high-{place}",
                    version=f"2.1.{place}",
                    cached=40_000 + place,
                    hour=place % 2 == 0,
                    shape=f"{place:064}",
                    sent=80 + place,
                ),
            ),
            awaited=tuple(
                f"{place:08}-{named:04}-4d57-9e3a-71c5d2b8a690"
                for named in range(awaited)
            ),
            requests=tuple(
                Requested(
                    f"{place:08}-{named:04}-4b1e-8c2d-5f0a9e3b7d61",
                    STOOD + timedelta(days=place, hours=named),
                    f"{place:032}{named:032}",
                    40 + named,
                    42 + named,
                    Shape(9_000 + place, 45_000 + named),
                )
                for named in range(requested)
            ),
            events=tuple(
                Occurred(
                    "api_retry",
                    STOOD + timedelta(days=place, seconds=named),
                    f"{place}{named}",
                )
                for named in range(occurred)
            ),
            directory=f"/work/Loom{place}",
            environment=f"cleo-loom-{place:06}",
            launch=Open(STOOD + timedelta(hours=place), f"2.1.{place}", 300 + place),
            prompt=Prompted(
                STOOD + timedelta(hours=place, seconds=1),
                f"typed-{place}",
                1_000 + place,
                tuple(
                    Ran(
                        f"/work/hooks/tidy-{place}-{named}.sh",
                        2_000 + named,
                        False,
                        True,
                    )
                    for named in range(ran)
                ),
            ),
            opening=Opening(
                Shape(8_000 + place, 40_000 + place),
                tuple(
                    (f"/work/Loom{place}/looms/{named}/CLAUDE.md", 3_000 + named)
                    for named in range(loaded)
                ),
                (1_000 + place,),
            ),
            injected=tuple(
                Part("reminder", 400 + named, f"total_tokens_reminder-{place}-{named}")
                for named in range(injected)
            ),
            queue=tuple(
                (
                    digest(f"{place} {waiting}".encode()),
                    STOOD + timedelta(days=place, seconds=waiting),
                )
                for waiting in range(queued)
            ),
            removed=tuple(
                (
                    digest(f"{place} removed {held}".encode()),
                    STOOD + timedelta(days=place, minutes=held),
                )
                for held in range(removed)
            ),
        ),
        end=digest(str(place).encode()),
    )


def _path(name: str) -> Path:
    return Path("/home/ubuntu/.claude/projects/-work-Loom") / f"{name}.jsonl"


class TestACarrysSize:
    def test_it_is_counted_at_no_less_than_the_memory_it_takes(self) -> None:
        for queued, awaited, requested, occurred, ran, loaded, injected in (
            (0, 0, 0, 0, 0, 0, 0),
            (40, 0, 0, 0, 0, 0, 0),
            (0, 3, 0, 0, 0, 0, 0),
            (0, 0, 7, 0, 0, 0, 0),
            (0, 0, 0, 9, 0, 0, 0),
            (0, 0, 0, 0, 6, 0, 0),
            (0, 0, 0, 0, 0, 8, 0),
            (0, 0, 0, 0, 0, 0, 12),
        ):
            tracemalloc.start()
            before, _ = tracemalloc.get_traced_memory()
            carries = [
                _carry(
                    place,
                    queued,
                    awaited=awaited,
                    requested=requested,
                    occurred=occurred,
                    ran=ran,
                    loaded=loaded,
                    injected=injected,
                )
                for place in range(1_000, 1_400)
            ]
            taken = tracemalloc.get_traced_memory()[0] - before
            tracemalloc.stop()

            counted = sum(carry.size for carry in carries)
            assert taken <= counted <= 2 * taken

    def test_a_prompt_waiting_in_the_queue_counts(self) -> None:
        assert _carry(queued=3).size > _carry(queued=2).size > _carry().size

    def test_a_line_awaited_counts(self) -> None:
        assert _carry(awaited=2).size > _carry(awaited=1).size > _carry().size

    def test_a_request_held_counts(self) -> None:
        assert _carry(requested=2).size > _carry(requested=1).size > _carry().size

    def test_an_event_held_counts(self) -> None:
        assert _carry(occurred=2).size > _carry(occurred=1).size > _carry().size

    def test_a_hook_run_of_the_latest_prompt_counts(self) -> None:
        assert _carry(ran=2).size > _carry(ran=1).size > _carry().size

    def test_an_instruction_file_the_boundarys_call_carries_counts(self) -> None:
        assert _carry(loaded=2).size > _carry(loaded=1).size > _carry().size

    def test_a_part_injected_before_the_boundarys_call_counts(self) -> None:
        assert _carry(injected=2).size > _carry(injected=1).size > _carry().size

    def test_what_the_boundarys_call_carries_counts(self) -> None:
        carry = _carry()
        opened = replace(carry, stands=replace(carry.stands, opening=None))

        assert carry.size > opened.size

    def test_a_prompt_a_remove_took_out_and_held_counts_as_one_waiting(
        self,
    ) -> None:
        assert _carry(removed=2).size == _carry(queued=2).size > _carry().size


class TestTheBound:
    def test_a_carry_is_held_by_its_transcripts_file(self) -> None:
        carries = Carries(2, 64_000_000)
        carries.keep(_path("a"), _carry(1))
        carries.keep(_path("b"), _carry(2))

        assert carries.get(_path("a")) == _carry(1)
        assert carries.get(_path("b")) == _carry(2)
        assert carries.get(_path("c")) is None
        assert (len(carries), carries.size) == (2, _carry(1).size + _carry(2).size)

    def test_a_later_carry_takes_the_place_of_the_one_held(self) -> None:
        carries = Carries(2, 64_000_000)
        carries.keep(_path("a"), _carry(1, queued=5))
        carries.keep(_path("a"), _carry(2))

        assert carries.get(_path("a")) == _carry(2)
        assert (len(carries), carries.size) == (1, _carry(2).size)

    def test_past_the_number_the_one_whose_file_changed_longest_ago_is_forgotten(
        self,
    ) -> None:
        """A carry's file changed its `place` seconds after the first's."""
        carries = Carries(2, 64_000_000)
        carries.keep(_path("a"), _carry(1))
        carries.keep(_path("b"), _carry(2))
        carries.keep(_path("a"), _carry(3))
        carries.keep(_path("c"), _carry(4))

        assert carries.get(_path("b")) is None
        assert carries.get(_path("a")) == _carry(3)
        assert carries.get(_path("c")) == _carry(4)

    def test_a_carry_kept_last_is_the_one_forgotten_where_its_file_is_the_oldest(
        self,
    ) -> None:
        """A walk publishes the most recently changed first."""
        carries = Carries(2, 64_000_000)
        for place in (9, 8, 7, 6):
            carries.keep(_path(f"file-{place}"), _carry(place))

        assert [carries.get(_path(f"file-{place}")) for place in (9, 8, 7, 6)] == [
            _carry(9),
            _carry(8),
            None,
            None,
        ]

    def test_past_the_size_the_one_whose_file_changed_longest_ago_is_forgotten(
        self,
    ) -> None:
        small, large = _carry(3), _carry(2, queued=50)
        assert small.size == _carry(1).size
        carries = Carries(2_500, 2 * small.size + large.size - 1)
        carries.keep(_path("a"), small)
        carries.keep(_path("b"), _carry(1))
        carries.keep(_path("c"), large)

        assert carries.get(_path("b")) is None
        assert (len(carries), carries.size) == (2, small.size + large.size)

    def test_one_carry_past_the_size_alone_is_not_held(self) -> None:
        carries = Carries(2_500, _carry(1).size - 1)
        carries.keep(_path("a"), _carry(1))

        assert (len(carries), carries.size) == (0, 0)

    def test_a_bound_of_no_transcript_holds_none(self) -> None:
        carries = Carries(0, 64_000_000)
        carries.keep(_path("a"), _carry(1))

        assert carries.get(_path("a")) is None

    def test_a_forgotten_carry_counts_no_more(self) -> None:
        carries = Carries(2, 64_000_000)
        carries.keep(_path("a"), _carry(1))
        carries.forget(_path("a"))
        carries.forget(_path("a"))

        assert (len(carries), carries.size, carries.get(_path("a"))) == (0, 0, None)
