"""The tie of a commit held from its call to the one its Repository's history
gives (F152.11, F158.4; DB assertion 577, decision 79.39): by its hash, else
by its subject where its author's time lies within the hour of the call; a
hash wins over a subject, and each is tied once.

The rules that protect the most: an amended commit's two calls are settled
by the hash (`test_a_hash_wins_over_a_subject_whichever_comes_first`), and a
rebased commit is found by its subject within the hour and no further
(`TestBySubject`)."""

from datetime import datetime, timedelta
from typing import Any

import pytest

from app.services.commit_tie import HOUR, Held, Read, tie
from tests.support.transcripts import STARTED

SUBJECT = "Scale the stew for six"
WHOLE = "3f9a2c1e7b04d6a51c8f2930d4e6b7a8c9d0e1f2"
REBASED = "8e1d4b2a6c90f3e57d1b2a4c6e8f0a1b3c5d7e9f"
AMENDED = "5c7e9a1b3d5f7092b4d6f8a0c2e4a6b8d0f2a4c6"

REQUESTED = STARTED
RETURNED = STARTED + timedelta(seconds=4)


def _held(key: int = 1, sha: str | None = "3f9a2c1", **overrides: Any) -> Held:
    values: dict[str, Any] = {
        "key": key,
        "sha": sha,
        "subject": SUBJECT,
        "requested_at": REQUESTED,
        "returned_at": RETURNED,
    }
    return Held(**(values | overrides))


def _read(key: int = 1, sha: str = WHOLE, **overrides: Any) -> Read:
    values: dict[str, Any] = {
        "key": key,
        "sha": sha,
        "subject": SUBJECT,
        "made_at": REQUESTED,
    }
    return Read(**(values | overrides))


def _keys(tied: list[tuple[Held, Read]]) -> list[tuple[int, int]]:
    return [(held.key, read.key) for held, read in tied]


class TestByHash:
    def test_a_read_commit_ties_the_held_one_whose_hash_it_starts_with(self) -> None:
        assert _keys(tie([_held()], [_read()])) == [(1, 1)]

    def test_a_hash_ties_whatever_its_subject_and_time(self) -> None:
        read = _read(subject="Season the stew", made_at=REQUESTED + 9 * HOUR)

        assert _keys(tie([_held()], [read])) == [(1, 1)]

    def test_the_longest_hash_it_starts_with_has_it(self) -> None:
        held = [_held(1, "3f9a"), _held(2, WHOLE), _held(3, "3f9a2c1")]

        assert _keys(tie(held, [_read()])) == [(2, 1)]

    def test_a_hash_it_does_not_start_with_ties_nothing(self) -> None:
        assert tie([_held(sha="9d0e1f2", subject="Plan")], [_read()]) == []


class TestBySubject:
    def test_a_rebased_commit_is_found_by_its_subject(self) -> None:
        assert _keys(tie([_held()], [_read(sha=REBASED)])) == [(1, 1)]

    def test_one_whose_call_showed_no_hash_is_found_by_its_subject(self) -> None:
        assert _keys(tie([_held(sha=None)], [_read()])) == [(1, 1)]

    @pytest.mark.parametrize(
        "made_at",
        [REQUESTED - HOUR, RETURNED + HOUR],
        ids=["an hour before it was requested", "an hour after it returned"],
    )
    def test_its_author_time_may_lie_an_hour_from_its_call(
        self, made_at: datetime
    ) -> None:
        assert _keys(tie([_held(sha=None)], [_read(made_at=made_at)])) == [(1, 1)]

    @pytest.mark.parametrize(
        "made_at",
        [
            REQUESTED - HOUR - timedelta(seconds=1),
            RETURNED + HOUR + timedelta(seconds=1),
        ],
        ids=["before", "after"],
    )
    def test_one_past_the_hour_ties_nothing(self, made_at: datetime) -> None:
        assert tie([_held(sha=None)], [_read(made_at=made_at)]) == []

    def test_a_call_that_never_returned_is_timed_from_its_request(self) -> None:
        held = _held(sha=None, returned_at=None)

        assert _keys(tie([held], [_read(made_at=REQUESTED + HOUR)])) == [(1, 1)]
        assert tie([held], [_read(made_at=REQUESTED + HOUR * 1.01)]) == []

    def test_another_subject_ties_nothing(self) -> None:
        assert tie([_held(sha=None)], [_read(subject="Season the stew")]) == []

    def test_each_held_one_in_its_calls_order_takes_the_earliest_made(self) -> None:
        later = REQUESTED + timedelta(minutes=30)
        held = [
            _held(2, None, requested_at=later, returned_at=later),
            _held(1, None),
        ]
        read = [_read(1, REBASED, made_at=later), _read(2, AMENDED)]

        assert sorted(_keys(tie(held, read))) == [(1, 2), (2, 1)]


class TestTiedOnce:
    def test_a_hash_wins_over_a_subject_whichever_comes_first(self) -> None:
        """An amended commit keeps its first author's time: the call that
        made it and the one that amended it both have its subject, and the
        one whose hash it starts with has it."""
        first = _held(1, "3f9a2c1")
        amending = _held(2, "5c7e9a1")

        assert _keys(tie([first, amending], [_read(sha=AMENDED)])) == [(2, 1)]

    def test_a_held_commit_is_completed_once(self) -> None:
        read = [_read(1), _read(2, REBASED)]

        assert _keys(tie([_held()], read)) == [(1, 1)]

    def test_a_read_commit_completes_one_held_commit(self) -> None:
        held = [_held(1, None), _held(2, None)]

        assert _keys(tie(held, [_read()])) == [(1, 1)]

    def test_two_reads_of_one_abbreviation_tie_it_once(self) -> None:
        clashing = "3f9a2c1ff0b8e6d4c2a0b8e6d4c2a0b8e6d4c2a0"
        read = [_read(1, subject="Plan"), _read(2, clashing, subject="Plan")]

        assert _keys(tie([_held()], read)) == [(1, 1)]
