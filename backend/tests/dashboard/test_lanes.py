"""A view's lanes (F164.6, F164.8): a lane per row of the By that holds
Calls, the earliest first, its waits and its events in time order, each
event with its detail (D6), merged past a bound at the whole span's
resolution.

The record is `tests.support.dashboard.record`'s: on 12 November 2026 the
work item's thread calls at 09:31, 09:32 and 09:33 and its sub-agent at
09:32:30, the project's chat stands in at 11:33, and a thread on no project
calls the next day at 09:30.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session as DbSession

from app import models
from app.dashboard import lanes as lanes_module
from app.dashboard.items import Detail
from app.dashboard.lanes import LaneEvent, Lanes, LanesService, Wait, merged
from app.exceptions import StateRefusedException
from app.models import Project, User
from app.services.container import ServiceContainer
from tests.support.dashboard import Record, record
from tests.support.transcripts import OPUS, STARTED

NOW = datetime(2026, 11, 20, tzinfo=UTC)

ERRORS = ["api_error", "hook_error", "max_tokens", "model_fallback"]
OTHERS = ["cache_miss", "compaction", "denied", "output_saved", "past_ttl", "rewind"]


@pytest.fixture
def worked(
    session: DbSession, person: User, project: Project, project_session: models.Session
) -> Record:
    return record(session, person, project, project_session)


@pytest.fixture
def service(container: ServiceContainer) -> LanesService:
    return container.lanes_service()


def _lanes(service: LanesService, written: str) -> Lanes:
    return service.lanes(written, now=NOW)


def _at(minutes: float) -> datetime:
    return STARTED + timedelta(minutes=minutes)


class TestLanes:
    def test_a_lane_per_row_of_the_by_the_earliest_first(
        self, service: LanesService, worked: Record
    ) -> None:
        found = _lanes(service, "t=all&p=lanes")

        assert [lane.key for lane in found.lanes] == [worked.project.id, None]
        assert [(lane.starts_at, lane.ends_at) for lane in found.lanes] == [
            (_at(1), _at(123)),
            (STARTED + timedelta(days=1), STARTED + timedelta(days=1)),
        ]
        assert [lane.values for lane in found.lanes] == [(2.6,), (0.05,)]
        assert [lane.label for lane in found.lanes] == ["Recipe box", "(No project)"]
        assert found.total_lanes == 2
        assert (found.starts_at, found.ends_at) == (
            _at(1),
            STARTED + timedelta(days=1),
        )
        assert found.all.values == (2.65,)
        assert found.by.key == "project"

    def test_a_wait_is_a_gap_of_a_minute_or_more_between_a_lanes_rows(
        self, service: LanesService, worked: Record
    ) -> None:
        found = _lanes(service, "t=all&p=lanes")

        assert found.wait_seconds == 60
        assert found.lanes[0].waits == (
            Wait(_at(1), _at(2), worked.thread.id, worked.calls[1].id, False),
            # The chat's Turn, standing in, has no thread and no Call.
            Wait(_at(3), _at(123), None, None, False),
        )
        assert found.lanes[1].waits == ()

    def test_a_wait_past_the_caches_lifetime_is_its_calls_own(
        self, service: LanesService, session: DbSession, worked: Record
    ) -> None:
        worked.calls[1].waited_seconds = 60.0
        session.flush()

        found = _lanes(service, "t=all&p=lanes")

        assert [wait.past_ttl for wait in found.lanes[0].waits] == [True, False]

    def test_a_gap_longer_than_the_calls_own_wait_is_not_past_its_lifetime(
        self, service: LanesService, worked: Record
    ) -> None:
        # The second Call waited 30 seconds, to its sending, past the cache's
        # lifetime; the lane's gap runs on to its completion, 60.
        found = _lanes(service, "t=all&p=lanes")

        assert worked.calls[1].past_ttl is True
        assert found.lanes[0].waits[0].past_ttl is False

    def test_each_event_in_time_order_with_its_detail(
        self, service: LanesService, worked: Record
    ) -> None:
        first, second, third = worked.calls[:3]

        events = _lanes(service, "t=all&p=lanes").lanes[0].events

        assert [(event.at, event.kind, event.call) for event in events] == [
            (_at(1.5), "api_error", first.id),
            (_at(2), "denied", second.id),
            (_at(2), "max_tokens", second.id),
            (_at(2), "model_fallback", second.id),
            (_at(2), "output_saved", first.id),
            (_at(2), "past_ttl", second.id),
            (_at(2), "rewind", second.id),
            (_at(3), "cache_miss", third.id),
            (_at(3), "hook_error", third.id),
            (_at(8), "compaction", third.id),
        ]
        details = {event.kind: event.detail for event in events}
        none = Detail(None, None, None, None, None, None, None)
        assert details["api_error"] == Detail("529", None, None, None, None, None, None)
        assert details["output_saved"] == Detail(
            None, "Bash", 90_000, None, None, None, None
        )
        assert details["denied"] == Detail(None, "Bash", None, "rule", None, None, None)
        assert details["hook_error"] == Detail(
            None, None, None, None, "signal_activity.sh", None, None
        )
        assert details["compaction"] == Detail(
            None, None, None, None, None, "auto", None
        )
        assert details["model_fallback"] == Detail(
            None, None, None, None, None, None, OPUS
        )
        assert [details[kind] for kind in ("cache_miss", "past_ttl", "rewind")] == [
            none
        ] * 3
        assert all(event.n == 1 for event in events)

    def test_an_event_carries_its_key_its_thread_and_its_calls_cost(
        self, service: LanesService, worked: Record
    ) -> None:
        events = _lanes(service, "t=all&p=lanes").lanes[0].events
        miss = next(event for event in events if event.kind == "cache_miss")
        error = next(event for event in events if event.kind == "api_error")

        assert (miss.key, miss.cost, miss.conversation) == (
            f"cache_miss:{worked.calls[2].id}",
            1.0,
            worked.thread.id,
        )
        assert error.key.startswith("api_error:")
        assert (error.is_error, miss.is_error) == (True, False)

    @pytest.mark.usefixtures("worked")
    def test_the_kinds_the_lanes_hold_the_errors_first(
        self, service: LanesService
    ) -> None:
        found = _lanes(service, "t=all&p=lanes")

        assert [kind.key for kind in found.kinds] == ERRORS + OTHERS
        assert {kind.key: kind.label for kind in found.kinds}["compaction"] == (
            "Compaction"
        )

    def test_by_conversation_a_lane_per_thread(
        self, service: LanesService, worked: Record
    ) -> None:
        found = _lanes(service, "t=all&by=conversation&p=lanes")

        assert [lane.key for lane in found.lanes] == [
            worked.thread.id,
            worked.sub_agent.id,
            None,
            worked.loose.id,
        ]
        assert [len(lane.events) for lane in found.lanes] == [10, 0, 0, 0]
        # The thread's calls are a minute apart: each gap a wait.
        assert [(wait.starts_at, wait.ends_at) for wait in found.lanes[0].waits] == [
            (_at(1), _at(2)),
            (_at(2), _at(3)),
        ]

    def test_the_scope_keeps_its_rows_and_their_events(
        self, service: LanesService, worked: Record
    ) -> None:
        found = _lanes(service, "t=all&p=lanes&c=miss:1")

        assert [lane.key for lane in found.lanes] == [worked.project.id]
        assert found.lanes[0].waits == ()
        assert [event.kind for event in found.lanes[0].events] == [
            "cache_miss",
            "hook_error",
            "compaction",
        ]

    def test_a_threshold_keeps_the_lanes_of_the_rows_it_keeps(
        self, service: LanesService, worked: Record
    ) -> None:
        found = _lanes(service, "t=all&p=lanes&c=@rows,gt,1,cost.sum")

        assert [lane.key for lane in found.lanes] == [worked.project.id]
        assert found.total_lanes == 1
        assert found.all.values == (2.6,)

    def test_a_row_with_no_call_has_no_lane(
        self, service: LanesService, worked: Record
    ) -> None:
        found = _lanes(service, "t=all&by=psession&p=lanes&m=turns.count")

        # The Turns' rows are the work item's and the chat's; the thread on
        # no project has Calls and no Turn.
        assert [lane.key for lane in found.lanes] == [worked.work.id, worked.chat.id]
        assert found.total_lanes == 2

    def test_at_most_lanes_the_earliest(
        self, service: LanesService, worked: Record, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(lanes_module, "LANES", 1)

        found = _lanes(service, "t=all&p=lanes")

        assert [lane.key for lane in found.lanes] == [worked.project.id]
        assert found.total_lanes == 2
        assert found.ends_at == _at(123)

    @pytest.mark.usefixtures("worked")
    def test_the_quota_weeks_that_start_within_the_span(
        self, service: LanesService
    ) -> None:
        found = _lanes(service, "t=all&p=lanes")

        # 12 November 2026 is a Thursday: its week starts at 10:00 UTC.
        assert found.weeks == (datetime(2026, 11, 12, 10, tzinfo=UTC),)

    @pytest.mark.usefixtures("worked")
    def test_a_window_with_none_has_no_lane(self, service: LanesService) -> None:
        found = _lanes(service, "t=c,2026-11-14,2026-11-15&p=lanes")

        assert (found.lanes, found.total_lanes, found.starts_at, found.weeks) == (
            (),
            0,
            None,
            (),
        )

    def test_a_view_in_another_presentation_is_refused(
        self, service: LanesService
    ) -> None:
        with pytest.raises(StateRefusedException) as refused:
            _lanes(service, "t=all")

        assert refused.value.message.splitlines()[1] == (
            "- p=rows: the view draws rows, and only a view in lanes has lanes. "
            "Lanes take p=lanes, with a By that is a part."
        )


class TestMerged:
    """Past the bound, the waits and the events merge at the whole span's
    resolution, doubled until they are within it."""

    @pytest.fixture
    def errors(self, session: DbSession, worked: Record) -> None:
        # Three more API errors on the first Call, ten seconds apart.
        session.add_all(
            models.Event(
                call_id=worked.calls[0].id,
                kind_code="api_error",
                at=_at(1.5) + timedelta(seconds=10 * step),
                detail="500",
            )
            for step in (1, 2, 3)
        )
        session.flush()

    @pytest.mark.usefixtures("errors")
    def test_within_the_bound_nothing_merges(self, service: LanesService) -> None:
        found = _lanes(service, "t=all&p=lanes")

        assert found.resolution is None
        assert len(found.lanes[0].events) == 13

    @pytest.mark.usefixtures("errors")
    def test_events_of_a_kind_merge_within_the_resolution(
        self, service: LanesService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Two waits and thirteen events: within twelve once the four API
        # errors, thirty seconds in all, are one.
        monkeypatch.setattr(lanes_module, "MARKS", 12)

        found = _lanes(service, "t=all&p=lanes")

        span = (found.ends_at - found.starts_at).total_seconds()  # type: ignore[operator]
        assert found.resolution == span / 4_000
        events = found.lanes[0].events
        errors = [event for event in events if event.kind == "api_error"]
        assert [(event.at, event.n, event.detail, event.cost) for event in errors] == [
            (_at(1.5), 4, None, 0.5)
        ]
        assert len(events) == 10
        assert [wait.n for wait in found.lanes[0].waits] == [1, 1]

    @pytest.mark.usefixtures("errors")
    def test_the_resolution_doubles_until_they_are_within_the_bound(
        self, service: LanesService, monkeypatch: pytest.MonkeyPatch, worked: Record
    ) -> None:
        # The minute between the two waits merges them at four times the
        # first resolution, some 86 seconds.
        monkeypatch.setattr(lanes_module, "MARKS", 11)

        found = _lanes(service, "t=all&p=lanes")

        span = (found.ends_at - found.starts_at).total_seconds()  # type: ignore[operator]
        assert found.resolution == span / 4_000 * 4
        assert found.lanes[0].waits == (Wait(_at(1), _at(123), None, None, False, n=2),)

    def test_a_span_of_no_length_merges_nothing(self) -> None:
        held = {None: [Wait(STARTED, STARTED, None, None, False)] * 2}

        assert merged(held, {}, STARTED, STARTED) == (None, held, {})

    def test_the_merged_waits_past_the_lifetime_where_one_is(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(lanes_module, "MARKS", 1)
        waits = {
            "lane": [
                Wait(_at(0), _at(1), None, 1, True),
                Wait(_at(1), _at(2), None, 2, False),
            ]
        }

        resolution, joined, _ = merged(waits, {}, _at(0), _at(2))

        assert resolution == 120 / 4_000
        assert joined == {"lane": [Wait(_at(0), _at(2), None, 2, True, n=2)]}

    def test_a_merged_events_cost_counts_each_call_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(lanes_module, "MARKS", 1)

        def error(second: float, call: int, cost: float) -> LaneEvent:
            return LaneEvent(
                _at(second), "api_error", True, "k", None, call, cost, None
            )

        events = {"lane": [error(0, 1, 0.5), error(0.5, 1, 0.5), error(1, 2, 0.25)]}

        _, _, folded = merged({}, events, _at(0), _at(2))

        assert [(event.n, event.cost) for event in folded["lane"]] == [(3, 0.75)]
