"""The carries a collector keeps between walks, and their bound (F152.15)."""

import tracemalloc
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pilot_collector.carry import Carries, Carry, Lead, Open, Standing, digest

STOOD = datetime(2026, 11, 12, 10, 2, 3, 456789, tzinfo=UTC)


def _carry(place: int = 0, queued: int = 0, removed: int = 0) -> Carry:
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
            leads=Lead(f"msg_01{place:022}", 3 + place),
            directory=f"/work/Loom{place}",
            environment=f"cleo-loom-{place:06}",
            launch=Open(STOOD + timedelta(hours=place), f"2.1.{place}", 300 + place),
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
        for queued in (0, 40):
            tracemalloc.start()
            before, _ = tracemalloc.get_traced_memory()
            carries = [_carry(place, queued) for place in range(1_000, 1_400)]
            taken = tracemalloc.get_traced_memory()[0] - before
            tracemalloc.stop()

            counted = sum(carry.size for carry in carries)
            assert taken <= counted <= 2 * taken

    def test_a_prompt_waiting_in_the_queue_counts(self) -> None:
        assert _carry(queued=3).size > _carry(queued=2).size > _carry().size

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
