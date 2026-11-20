"""A Call's derived caches beside its cost and a Transcript's first and last
Call's time (DB §2.7, Call; §7.4; decision 79.14; assertions 543 and 546).

The rule that protects the most: one statement says what a Call's caches
are, so the step after a deploy's revisions gives a stored Call what its
publication would have (`TestDerive`)."""

from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession

from app.models import Call, ComponentVersion, Transcript
from app.services.call_caches import (
    CallCacheService,
    Derived,
    caches,
    hold_sub_agents_calls,
)
from app.services.container import ServiceContainer
from tests.support import transcripts
from tests.support.database import Written, writes
from tests.support.transcripts import OTHER, STARTED, SUB_AGENT

CACHES = ("waited_seconds", "rewind", "cache_miss", "past_ttl", "launch_id")


def _at(minutes: float) -> datetime:
    return STARTED + timedelta(minutes=minutes)


@pytest.fixture
def collector(session: DbSession) -> ComponentVersion:
    return transcripts.component_version(session)


@pytest.fixture
def thread(session: DbSession, collector: ComponentVersion) -> Transcript:
    """The conversation's main thread."""
    return transcripts.transcript(session, collector)


@pytest.fixture
def sub_agent(
    session: DbSession, collector: ComponentVersion, thread: Transcript
) -> Transcript:
    """A sub-agent's thread under the main thread."""
    return transcripts.transcript(
        session, collector, agent_id=SUB_AGENT, main_id=thread.id
    )


@pytest.fixture
def call_caches(container: ServiceContainer) -> CallCacheService:
    return container.call_cache_service()


def _given(thread: Transcript, position: int, **overrides: Any) -> dict[str, Any]:
    """The Call at `position` of the thread as a publication gives it,
    completed that many minutes in: it read 48,112 tokens from the cache and
    wrote 3,310 to the one-hour one."""
    values: dict[str, Any] = {
        "id": position,
        "transcript_id": thread.id,
        "position": position,
        "prompt_id": None,
        "predecessor_id": None,
        "sent_at": None,
        "completed_at": _at(position),
        "input_tokens": 1_204,
        "cache_write_5m_tokens": 0,
        "cache_write_1h_tokens": 3_310,
        "cache_read_tokens": 48_112,
        "output_tokens": 2_870,
    }
    return values | overrides


def _after(thread: Transcript, **overrides: Any) -> dict[str, Any]:
    """The thread's second Call, which follows its first."""
    return _given(thread, 2, predecessor_id=1) | overrides


def _second(
    db: DbSession, thread: Transcript, first: dict[str, Any], **second: Any
) -> dict[str, Any]:
    """The caches of the thread's second Call, after a first with `first`."""
    return caches(db, [_given(thread, 1, **first), _after(thread, **second)])[2]


def _stored(db: DbSession, row: Call) -> dict[str, Any]:
    """The caches the record holds of the Call."""
    held = db.execute(
        select(*(getattr(Call, cache) for cache in CACHES)).where(Call.id == row.id)
    ).one()
    return dict(held._mapping)


class TestWaited:
    def test_a_call_waited_from_its_predecessors_completion_to_its_own_sending(
        self, session: DbSession, thread: Transcript
    ) -> None:
        derived = _second(session, thread, {}, sent_at=_at(1) + timedelta(seconds=12.5))

        assert derived["waited_seconds"] == 12.5

    def test_a_call_with_no_sending_time_waited_to_its_completion(
        self, session: DbSession, thread: Transcript
    ) -> None:
        assert _second(session, thread, {})["waited_seconds"] == 60.0

    def test_a_chains_first_call_waited_on_none(
        self, session: DbSession, thread: Transcript
    ) -> None:
        derived = caches(session, [_given(thread, 1)])

        assert derived == {
            1: {
                "waited_seconds": None,
                "rewind": False,
                "cache_miss": False,
                "past_ttl": False,
                "launch_id": None,
            }
        }

    def test_a_predecessor_not_given_is_read_from_the_record(
        self, session: DbSession, thread: Transcript
    ) -> None:
        """An appended publication's first Call follows one before its
        boundary."""
        held = transcripts.call(
            session, thread, 1, cache_read_tokens=0, cache_write_1h_tokens=90_000
        )

        derived = caches(
            session,
            [_given(thread, 2, id=held.id + 1, predecessor_id=held.id)],
        )

        assert derived[held.id + 1] == {
            "waited_seconds": 60.0,
            "rewind": False,
            "cache_miss": False,
            "past_ttl": False,
            "launch_id": None,
        }

    def test_a_call_given_is_read_as_given_whatever_the_record_holds_of_it(
        self, session: DbSession, thread: Transcript
    ) -> None:
        """A whole publication names the Calls Pilot holds again, moved."""
        held = transcripts.call(session, thread, 1, completed_at=_at(-30))

        derived = caches(
            session,
            [
                _given(thread, 1, id=held.id),
                _given(thread, 2, id=held.id + 1, predecessor_id=held.id),
            ],
        )

        assert derived[held.id + 1]["waited_seconds"] == 60.0

    def test_no_call_given_asks_nothing(self, session: DbSession) -> None:
        assert caches(session, []) == {}


class TestRewind:
    def test_a_call_whose_predecessor_is_not_the_one_before_it_is_a_rewind(
        self, session: DbSession, thread: Transcript
    ) -> None:
        derived = caches(
            session,
            [
                _given(thread, 1),
                _after(thread),
                _given(thread, 3, predecessor_id=1),
            ],
        )

        assert [derived[place]["rewind"] for place in (1, 2, 3)] == [False, False, True]

    def test_a_call_with_no_predecessor_is_none_wherever_it_stands(
        self, session: DbSession, thread: Transcript
    ) -> None:
        derived = caches(session, [_given(thread, 1), _given(thread, 2)])

        assert derived[2]["rewind"] is False


class TestCacheMiss:
    """DB 546. The first Call leaves 50,000 tokens cached."""

    LEFT: dict[str, Any] = {"cache_read_tokens": 46_000, "cache_write_1h_tokens": 4_000}

    @pytest.mark.parametrize(
        ("read", "missed"),
        [(24_999, True), (25_000, False)],
        ids=["more than half not read", "half read"],
    )
    def test_a_call_that_read_under_half_of_what_was_left_missed(
        self, session: DbSession, thread: Transcript, read: int, missed: bool
    ) -> None:
        derived = _second(
            session,
            thread,
            self.LEFT,
            cache_read_tokens=read,
            cache_write_1h_tokens=55_000 - read,
            input_tokens=0,
        )

        assert derived["cache_miss"] is missed

    @pytest.mark.parametrize(
        ("context", "missed"),
        [(45_000, True), (44_999, False)],
        ids=["nine tenths of what was left", "a smaller context"],
    )
    def test_a_context_under_nine_tenths_of_what_was_left_is_no_miss(
        self, session: DbSession, thread: Transcript, context: int, missed: bool
    ) -> None:
        """A context that shrank was compacted, and its cache did not
        expire."""
        derived = _second(
            session,
            thread,
            self.LEFT,
            cache_read_tokens=0,
            cache_write_1h_tokens=0,
            input_tokens=context,
        )

        assert derived["cache_miss"] is missed

    def test_what_was_left_counts_both_cache_writes_and_the_read(
        self, session: DbSession, thread: Transcript
    ) -> None:
        left = {
            "cache_read_tokens": 10_000,
            "cache_write_5m_tokens": 15_000,
            "cache_write_1h_tokens": 25_000,
        }
        reads = {"cache_write_1h_tokens": 0, "input_tokens": 30_000}

        hit = _second(session, thread, left, cache_read_tokens=25_000, **reads)
        miss = _second(session, thread, left, cache_read_tokens=24_999, **reads)

        assert (hit["cache_miss"], miss["cache_miss"]) == (False, True)

    def test_a_call_past_a_larger_context_is_measured_against_what_was_left(
        self, session: DbSession, thread: Transcript
    ) -> None:
        """The lesser of what was left and its own context: 200,000 tokens
        of context that read 26,000 of the 50,000 left missed nothing."""
        derived = _second(
            session,
            thread,
            self.LEFT,
            cache_read_tokens=26_000,
            cache_write_1h_tokens=174_000,
            input_tokens=0,
        )

        assert derived["cache_miss"] is False

    def test_a_call_after_one_that_left_nothing_missed_nothing(
        self, session: DbSession, thread: Transcript
    ) -> None:
        derived = _second(
            session,
            thread,
            {"cache_read_tokens": 0, "cache_write_1h_tokens": 0},
            cache_read_tokens=0,
        )

        assert derived["cache_miss"] is False


class TestPastTtl:
    @pytest.mark.parametrize(
        ("wrote", "waited", "past"),
        [
            ({"cache_write_1h_tokens": 3_310}, 3_600.5, True),
            ({"cache_write_1h_tokens": 3_310}, 3_600, False),
            ({"cache_write_1h_tokens": 0, "cache_write_5m_tokens": 800}, 300.5, True),
            ({"cache_write_1h_tokens": 0, "cache_write_5m_tokens": 800}, 300, False),
            (
                {"cache_write_1h_tokens": 3_310, "cache_write_5m_tokens": 800},
                400,
                False,
            ),
            ({"cache_write_1h_tokens": 0, "cache_write_5m_tokens": 0}, 86_400, False),
        ],
        ids=[
            "past an hour",
            "an hour",
            "past five minutes",
            "five minutes",
            "both caches written",
            "no cache written",
        ],
    )
    def test_a_wait_longer_than_the_cache_its_predecessor_wrote_lives_is_past_it(
        self,
        session: DbSession,
        thread: Transcript,
        wrote: dict[str, int],
        waited: float,
        past: bool,
    ) -> None:
        derived = _second(
            session, thread, wrote, sent_at=_at(1) + timedelta(seconds=waited)
        )

        assert (derived["waited_seconds"], derived["past_ttl"]) == (waited, past)


class TestLaunch:
    """DB 543."""

    def test_a_main_threads_call_is_made_in_its_prompts_launch(
        self, session: DbSession, thread: Transcript
    ) -> None:
        transcripts.launch(session, thread, ended_at=_at(9))
        resumed = transcripts.launch(session, thread, started_at=_at(10))
        prompt = transcripts.prompt(session, resumed, received_at=_at(10))

        derived = caches(session, [_given(thread, 1, prompt_id=prompt.id)])

        assert derived[1]["launch_id"] == resumed.id

    def test_a_main_threads_call_that_follows_no_prompt_is_made_in_none(
        self, session: DbSession, thread: Transcript
    ) -> None:
        transcripts.launch(session, thread)

        assert caches(session, [_given(thread, 1)])[1]["launch_id"] is None

    def test_a_sub_agents_call_is_made_in_the_launch_that_holds_its_completion(
        self, session: DbSession, thread: Transcript, sub_agent: Transcript
    ) -> None:
        first = transcripts.launch(session, thread, ended_at=_at(9))
        resumed = transcripts.launch(session, thread, started_at=_at(20))

        derived = caches(
            session,
            [
                _given(sub_agent, 1, completed_at=_at(0)),
                _given(sub_agent, 2, completed_at=_at(9)),
                _given(sub_agent, 3, completed_at=_at(12)),
                _given(sub_agent, 4, completed_at=_at(20)),
                _given(sub_agent, 5, completed_at=_at(600)),
            ],
        )

        assert [derived[place]["launch_id"] for place in range(1, 6)] == [
            first.id,
            first.id,
            None,
            resumed.id,
            resumed.id,
        ]

    def test_a_sub_agents_call_from_before_its_main_threads_first_launch_is_in_none(
        self, session: DbSession, thread: Transcript, sub_agent: Transcript
    ) -> None:
        transcripts.launch(session, thread, started_at=_at(5))

        assert caches(session, [_given(sub_agent, 1)])[1]["launch_id"] is None

    def test_a_sub_agents_call_whose_main_thread_pilot_does_not_hold_is_in_none(
        self, session: DbSession, collector: ComponentVersion, thread: Transcript
    ) -> None:
        transcripts.launch(session, thread)
        orphan = transcripts.transcript(
            session, collector, session_id=OTHER, agent_id=SUB_AGENT
        )

        assert caches(session, [_given(orphan, 1)])[1]["launch_id"] is None


class TestHoldSubAgentsCalls:
    def test_a_sub_agents_call_is_left_in_the_launch_that_holds_it(
        self, session: DbSession, thread: Transcript, sub_agent: Transcript
    ) -> None:
        launch = transcripts.launch(session, thread)
        calls = [transcripts.call(session, sub_agent, place) for place in (1, 2)]

        with writes(session) as wrote:
            hold_sub_agents_calls(session, thread.session_id)

        assert [_stored(session, call)["launch_id"] for call in calls] == [
            launch.id,
            launch.id,
        ]
        assert wrote == {"calls": Written(updated=2)}

    def test_a_call_in_the_launch_that_holds_it_is_not_written(
        self, session: DbSession, thread: Transcript, sub_agent: Transcript
    ) -> None:
        transcripts.launch(session, thread)
        transcripts.call(session, sub_agent, 1)
        hold_sub_agents_calls(session, thread.session_id)

        with writes(session) as wrote:
            hold_sub_agents_calls(session, thread.session_id)

        assert wrote == {}

    def test_a_call_no_launch_holds_any_longer_is_left_in_none(
        self, session: DbSession, thread: Transcript, sub_agent: Transcript
    ) -> None:
        launch = transcripts.launch(session, thread)
        call = transcripts.call(session, sub_agent, 12, launch_id=launch.id)
        launch.ended_at = _at(9)
        session.flush()

        hold_sub_agents_calls(session, thread.session_id)

        assert _stored(session, call)["launch_id"] is None

    def test_a_main_threads_own_calls_are_left_alone(
        self, session: DbSession, thread: Transcript
    ) -> None:
        launch = transcripts.launch(session, thread)
        transcripts.call(session, thread, 1, launch_id=launch.id)

        with writes(session) as wrote:
            hold_sub_agents_calls(session, thread.session_id)

        assert wrote == {}

    def test_another_conversations_calls_are_left_alone(
        self, session: DbSession, collector: ComponentVersion, thread: Transcript
    ) -> None:
        other = transcripts.transcript(session, collector, session_id=OTHER)
        transcripts.launch(session, other)
        under = transcripts.transcript(
            session, collector, session_id=OTHER, agent_id=SUB_AGENT, main_id=other.id
        )
        call = transcripts.call(session, under, 1)

        hold_sub_agents_calls(session, thread.session_id)

        assert _stored(session, call)["launch_id"] is None


class TestDerive:
    def test_a_stored_call_with_no_caches_is_given_what_its_publication_gives(
        self,
        session: DbSession,
        call_caches: CallCacheService,
        thread: Transcript,
        sub_agent: Transcript,
    ) -> None:
        """A wait past the hour its predecessor's cache lives, a miss, a
        rewind, a Prompt's Launch and a sub-agent's Call the main thread's
        Launch holds, each as `caches` gives it for the same rows."""
        launch = transcripts.launch(session, thread)
        prompt = transcripts.prompt(session, launch)
        first = transcripts.call(session, thread, 1, prompt_id=prompt.id)
        second = transcripts.call(
            session, thread, 2, prompt_id=prompt.id, predecessor_id=first.id
        )
        third = transcripts.call(
            session,
            thread,
            3,
            predecessor_id=first.id,
            sent_at=_at(90),
            completed_at=_at(91),
            cache_read_tokens=0,
            cache_write_1h_tokens=52_000,
        )
        under = transcripts.call(session, sub_agent, 1)
        stored = [first, second, third, under]
        given = caches(
            session,
            [
                {
                    column.name: getattr(row, column.name)
                    for column in Call.__table__.columns
                }
                for row in stored
            ],
        )

        derived = call_caches.derive()

        assert derived == Derived(calls=4, transcripts=2)
        assert [_stored(session, row) for row in stored] == [
            given[row.id] for row in stored
        ]
        assert _stored(session, third) == {
            "waited_seconds": 89 * 60.0,
            "rewind": True,
            "cache_miss": True,
            "past_ttl": True,
            "launch_id": None,
        }
        assert _stored(session, second)["launch_id"] == launch.id
        assert _stored(session, under)["launch_id"] == launch.id

    def test_the_transcript_of_such_a_call_is_given_its_first_and_last_calls_time(
        self, session: DbSession, call_caches: CallCacheService, thread: Transcript
    ) -> None:
        """By `position`, whatever order the Calls completed in."""
        transcripts.call(session, thread, 1, completed_at=_at(4))
        transcripts.call(session, thread, 2, completed_at=_at(9))
        transcripts.call(session, thread, 3, completed_at=_at(7))

        call_caches.derive()

        assert session.execute(
            select(Transcript.first_call_at, Transcript.last_call_at).where(
                Transcript.id == thread.id
            )
        ).one() == (_at(4), _at(7))

    def test_a_call_that_holds_its_caches_is_left_as_it_is(
        self, session: DbSession, call_caches: CallCacheService, thread: Transcript
    ) -> None:
        first = transcripts.call(session, thread, 1)
        transcripts.call(session, thread, 2, predecessor_id=first.id)
        call_caches.derive()
        session.execute(
            update(Transcript).values(first_call_at=None, last_call_at=None)
        )

        with writes(session) as wrote:
            derived = call_caches.derive()

        assert derived == Derived(calls=0, transcripts=0)
        assert wrote == {}

    def test_a_transcript_with_no_such_call_keeps_its_times(
        self,
        session: DbSession,
        call_caches: CallCacheService,
        collector: ComponentVersion,
        thread: Transcript,
    ) -> None:
        other = transcripts.transcript(
            session,
            collector,
            session_id=OTHER,
            first_call_at=_at(-60),
            last_call_at=_at(-50),
        )
        transcripts.call(
            session,
            other,
            1,
            rewind=False,
            cache_miss=False,
            past_ttl=False,
        )
        transcripts.call(session, thread, 1)

        assert call_caches.derive() == Derived(calls=1, transcripts=1)
        assert session.execute(
            select(Transcript.first_call_at, Transcript.last_call_at).where(
                Transcript.id == other.id
            )
        ).one() == (_at(-60), _at(-50))
