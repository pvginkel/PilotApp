"""A view's items and a conversation's calls (F165.1, F165.4): the items of
a grain, each with the columns the catalogue gives it (R28), of the row
selected or of every row, of the rows a threshold keeps (D5), or an opened
item's calls; and every call of one thread over all time, each with its
events and their details (D6), Took and Waited (D7), and whether the view's
scope holds it.

The record is `tests.support.dashboard.record`'s: on 12 November 2026 the
work item's thread calls at 09:31, 09:32 and 09:33 and its sub-agent at
09:32:30, the project's chat stands in at 11:33, and a thread on no project
calls the next day at 09:30.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.dashboard import items as items_module
from app.dashboard.items import Calls, Detail, Items, ItemsService, items_grain
from app.dashboard.planner import plan
from app.dashboard.state import Item, Simple, State
from app.exceptions import RecordNotFoundException, StateRefusedException
from app.models import Project, User
from app.services.container import ServiceContainer
from tests.support.dashboard import Record, catalogue, record
from tests.support.transcripts import OPUS, STARTED

NOW = datetime(2026, 11, 20, tzinfo=UTC)

TOKENS = 1_204 + 3_310 + 48_112 + 2_870
"""What each of the record's Calls counts."""

CONTEXT = 1_204 + 3_310 + 48_112


@pytest.fixture
def worked(
    session: DbSession, person: User, project: Project, project_session: models.Session
) -> Record:
    return record(session, person, project, project_session)


@pytest.fixture
def service(container: ServiceContainer) -> ItemsService:
    return container.items_service()


def _items(service: ItemsService, written: str) -> Items:
    return service.items(written, now=NOW)


def _calls(service: ItemsService, written: str, thread: uuid.UUID) -> Calls:
    return service.calls(written, thread, now=NOW)


def _at(minutes: float) -> datetime:
    return STARTED + timedelta(minutes=minutes)


def _event_id(session: DbSession) -> int:
    found = session.scalar(select(models.Event.id))
    assert found is not None
    return found


class TestItems:
    def test_a_grains_items_the_earliest_first_with_its_columns(
        self, service: ItemsService, worked: Record
    ) -> None:
        found = _items(service, "t=all&ig=conversation")

        assert found.grain.key == "conversation"
        assert [column.key for column in found.figures] == [
            "calls",
            "cost",
            "tokens",
            "misses",
            "miss_cost",
            "ctx",
        ]
        assert found.figures[2].kinds == (
            "input",
            "cache_write",
            "cache_read",
            "output",
        )
        assert [(item.key, item.first, item.last) for item in found.items] == [
            (worked.thread.id, _at(1), _at(3)),
            (worked.sub_agent.id, _at(2.5), _at(2.5)),
            # The chat's Turn stands in: it has no thread.
            (None, _at(123), _at(123)),
            (worked.loose.id, STARTED + timedelta(days=1), STARTED + timedelta(days=1)),
        ]
        thread = found.items[0]
        assert thread.values == (3.0, 1.75, 3.0 * TOKENS, 1.0, 1.0, float(CONTEXT))
        assert thread.kinds[2] == (3 * 1_204.0, 3 * 3_310.0, 3 * 48_112.0, 3 * 2_870.0)
        assert thread.kinds[0] is None
        assert found.items[2].label == "(No transcript)"
        assert found.total == 4
        assert found.shows == ()

    def test_the_row_selected_holds_its_items(
        self, service: ItemsService, worked: Record
    ) -> None:
        found = _items(service, f"t=all&ig=conversation&sel={worked.project.id}")

        assert [item.key for item in found.items] == [
            worked.thread.id,
            worked.sub_agent.id,
            None,
        ]
        assert found.selected is not None
        assert found.selected.value == worked.project.id
        assert found.by.key == "project"

    def test_the_row_with_none_selected(
        self, service: ItemsService, worked: Record
    ) -> None:
        found = _items(service, "t=all&ig=conversation&sel=~")

        assert [item.key for item in found.items] == [worked.loose.id]

    def test_a_grains_item_carries_the_figures_of_another_fact(
        self, service: ItemsService, worked: Record
    ) -> None:
        found = _items(service, "t=all&ig=pturn")

        assert [column.key for column in found.figures][-3:] == [
            "turn_time",
            "reported_cost",
            "failed_turns",
        ]
        assert [(item.key, item.values[-3:]) for item in found.items] == [
            (worked.work_turn.id, (600.0, 2.5, 0.0)),
            (worked.chat_turn.id, (180.0, 0.75, 1.0)),
            (None, (None, None, None)),
        ]
        assert [item.values[0] for item in found.items] == [4.0, 1.0, 1.0]

    def test_a_call_is_an_item_of_its_own_with_what_it_shows(
        self, service: ItemsService, worked: Record
    ) -> None:
        found = _items(service, "t=all&ig=call")

        assert [column.key for column in found.figures] == [
            "cost",
            "tokens",
            "ctx",
            "waited",
            "took",
        ]
        assert [dimension.key for dimension in found.shows] == [
            "model",
            "effort",
            "miss",
            "miss_cause",
            "rewind",
            "compaction",
            "estimate",
        ]
        first, second, third, explored, by_hand = worked.calls
        assert [item.key for item in found.items] == [
            first.id,
            second.id,
            explored.id,
            third.id,
            None,
            by_hand.id,
        ]
        listed = found.items[0]
        assert (listed.first, listed.last, listed.label) == (_at(1), _at(1), None)
        assert (listed.conversation, listed.session, listed.turn_seq, listed.call) == (
            worked.thread.id,
            worked.work.id,
            1,
            first.id,
        )
        assert [(shown.key, shown.label) for shown in listed.shown] == [
            (OPUS, OPUS),
            ("high", None),
            (0, "No miss"),
            (None, "(No cause)"),
            (0, "No rewind"),
            (0, "No compaction"),
            (0, "Measured"),
        ]
        stand_in = found.items[4]
        assert (stand_in.session, stand_in.turn_seq, stand_in.call) == (
            worked.chat.id,
            1,
            None,
        )
        assert stand_in.shown[-1].key == 1
        assert found.total == 6

    def test_took_runs_from_sending_to_completion_and_waited_is_the_records(
        self, service: ItemsService, worked: Record
    ) -> None:
        found = _items(service, "t=all&ig=call")
        by_call = {item.call: item for item in found.items}
        first, second = worked.calls[:2]

        # waited, took
        assert by_call[second.id].values[3:] == (30.0, 30.0)
        assert by_call[first.id].values[3:] == (None, None)

    def test_an_event_is_an_item_by_its_key_with_its_detail(
        self, service: ItemsService, session: DbSession, worked: Record
    ) -> None:
        found = _items(service, "t=all&ig=event")

        assert found.figures == ()
        assert [dimension.key for dimension in found.shows] == [
            "event_kind",
            "event_error",
        ]
        keys = [item.key for item in found.items]
        first, second, third = worked.calls[:3]
        denied = session.scalar(
            select(models.ToolCall.id).where(models.ToolCall.denial_kind_code == "rule")
        )
        assert keys[:2] == [f"api_error:{_event_id(session)}", f"denied:{denied}"]
        assert f"cache_miss:{third.id}" in keys
        assert f"model_fallback:{second.id}" in keys
        error = found.items[0]
        assert [(shown.key, shown.label) for shown in error.shown] == [
            ("api_error", "api_error"),
            (1, "Error"),
        ]
        assert error.detail == Detail("529", None, None, None, None, None, None)
        assert (error.call, error.conversation) == (first.id, worked.thread.id)
        assert found.total == 10

    def test_an_opened_items_calls(self, service: ItemsService, worked: Record) -> None:
        found = _items(service, f"t=all&it=pturn,{worked.work_turn.id}")

        assert found.grain.key == "call"
        assert found.opened == Item("pturn", worked.work_turn.id)
        first, second, third, explored, _ = worked.calls
        assert [item.key for item in found.items] == [
            first.id,
            second.id,
            explored.id,
            third.id,
        ]

    def test_an_opened_events_call(
        self, service: ItemsService, session: DbSession, worked: Record
    ) -> None:
        found = _items(service, f"t=all&it=event,api_error%3A{_event_id(session)}")

        assert [item.key for item in found.items] == [worked.calls[0].id]

    @pytest.mark.usefixtures("worked")
    def test_an_opened_event_the_record_does_not_hold_has_no_calls(
        self, service: ItemsService
    ) -> None:
        found = _items(service, "t=all&it=event,api_error%3A999999")

        assert (found.items, found.total) == ((), 0)

    def test_under_a_threshold_the_items_of_the_rows_it_keeps(
        self, service: ItemsService, worked: Record
    ) -> None:
        found = _items(service, "t=all&ig=conversation&c=@rows,gt,1,cost.sum")

        assert [item.key for item in found.items] == [
            worked.thread.id,
            worked.sub_agent.id,
            None,
        ]

    def test_under_a_threshold_by_a_dimension_the_listing_fact_lacks(
        self, service: ItemsService, session: DbSession, worked: Record
    ) -> None:
        # The Event fact alone has the event's kind: the items are the
        # conversations that hold an event of a kind kept, so the loose
        # thread, whose one event is of the one kind dropped, is not one.
        by_hand = worked.calls[4]
        session.add(
            models.Event(
                call_id=by_hand.id, kind_code="api_error", at=by_hand.completed_at
            )
        )
        session.flush()

        found = _items(
            service, "t=all&by=event_kind&m=events.count&c=@rows,lt,2,events.count"
        )

        assert [item.key for item in found.items] == [worked.thread.id]

    def test_under_a_threshold_the_figures_of_a_fact_that_lacks_the_by(
        self, service: ItemsService, worked: Record
    ) -> None:
        # The Turn fact has no model: its figures are those of the
        # conversations that hold a Call of a model kept.
        found = _items(service, "t=all&by=model&ig=pturn&c=@rows,gt,1,cost.sum")

        assert [(item.key, item.values[-3:]) for item in found.items] == [
            (worked.work_turn.id, (600.0, 2.5, 0.0)),
            (None, (None, None, None)),
        ]

    @pytest.mark.usefixtures("worked")
    def test_under_a_marking_threshold_every_rows_items(
        self, service: ItemsService
    ) -> None:
        found = _items(service, "t=all&ig=conversation&c=~@rows,gt,1,cost.sum")

        assert found.total == 4

    def test_the_scope_keeps_its_items(
        self, service: ItemsService, worked: Record
    ) -> None:
        found = _items(service, "t=all&ig=call&c=miss:1")

        assert [item.key for item in found.items] == [worked.calls[2].id]

    def test_in_order_the_row_selected_is_a_member(
        self, service: ItemsService, worked: Record
    ) -> None:
        found = _items(
            service, f"t=all&by=psession&p=order&ig=conversation&sel={worked.chat.id}"
        )

        assert found.by.key == "session_start"
        assert [item.key for item in found.items] == [None]

    def test_the_focus_is_marked(self, service: ItemsService, worked: Record) -> None:
        found = _items(service, f"t=all&ig=project&f=project:{worked.project.id}")

        assert [(item.key, item.focus) for item in found.items] == [
            (worked.project.id, True),
            (None, False),
        ]

    def test_at_most_items_the_earliest(
        self, service: ItemsService, worked: Record, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(items_module, "ITEMS", 1)

        found = _items(service, "t=all&ig=conversation")

        assert [item.key for item in found.items] == [worked.thread.id]
        assert found.total == 4

    @pytest.mark.usefixtures("worked")
    def test_a_window_with_none_holds_no_item(self, service: ItemsService) -> None:
        found = _items(service, "t=c,2026-11-14,2026-11-15")

        assert (found.items, found.total) == ((), 0)


class TestItemsGrain:
    @pytest.mark.parametrize(
        ("state", "grain"),
        [
            (State(), "conversation"),
            (State(item_grain="pturn"), "pturn"),
            (State(item=Item("conversation", None)), "call"),
            (State(item_grain="pturn", item=Item("project", None)), "call"),
        ],
    )
    def test_a_views_grain_of_items(
        self, session: DbSession, state: State, grain: str
    ) -> None:
        found = plan(state, catalogue(session), (), NOW)

        assert items_grain(state, found) == grain

    def test_the_first_measures_grain(self, session: DbSession) -> None:
        state = State(measures=(Simple("cost", "median", "pturn"),))
        found = plan(state, catalogue(session), (), NOW)

        assert items_grain(state, found) == "pturn"


class TestCalls:
    def test_every_call_of_a_thread_over_all_time_in_its_order(
        self, service: ItemsService, worked: Record
    ) -> None:
        found = _calls(service, "t=c,2026-11-13,2026-11-13", worked.thread.id)

        assert [(call.call, call.position) for call in found.calls] == [
            (call.id, position)
            for position, call in enumerate(worked.calls[:3], start=1)
        ]
        assert [call.in_scope for call in found.calls] == [False] * 3
        assert found.total == 3
        assert found.conversation == worked.thread.id
        assert [column.key for column in found.figures] == [
            "cost",
            "tokens",
            "ctx",
            "waited",
            "took",
        ]

    def test_whether_the_views_window_and_scope_hold_each(
        self, service: ItemsService, worked: Record
    ) -> None:
        assert [
            call.in_scope for call in _calls(service, "t=all", worked.thread.id).calls
        ] == [True] * 3
        assert [
            call.in_scope
            for call in _calls(service, "t=all&c=miss:1", worked.thread.id).calls
        ] == [False, False, True]
        assert [
            call.in_scope
            for call in _calls(service, "t=all&c=!source:work", worked.thread.id).calls
        ] == [False] * 3

    def test_each_with_its_events_in_time_order_and_their_details(
        self, service: ItemsService, worked: Record
    ) -> None:
        found = _calls(service, "t=all", worked.thread.id)

        assert [[event.kind for event in call.events] for call in found.calls] == [
            ["api_error", "output_saved"],
            ["denied", "max_tokens", "model_fallback", "past_ttl", "rewind"],
            ["cache_miss", "hook_error", "compaction"],
        ]
        error, saved = found.calls[0].events
        assert (error.label, error.is_error, error.at) == ("api_error", True, _at(1.5))
        assert error.detail.qualifier == "529"
        assert saved.detail == Detail(None, "Bash", 90_000, None, None, None, None)
        compaction = found.calls[2].events[2]
        assert (compaction.label, compaction.detail.trigger) == ("Compaction", "auto")

    def test_took_and_waited(self, service: ItemsService, worked: Record) -> None:
        found = _calls(service, "t=all", worked.thread.id)

        assert [call.values[3:] for call in found.calls] == [
            (None, None),
            (30.0, 30.0),
            (None, None),
        ]

    def test_a_sub_agents_calls(self, service: ItemsService, worked: Record) -> None:
        found = _calls(service, "t=all", worked.sub_agent.id)

        assert [call.call for call in found.calls] == [worked.calls[3].id]
        assert found.calls[0].events == ()

    def test_at_most_calls_the_first(
        self, service: ItemsService, worked: Record, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(items_module, "CALLS", 2)

        found = _calls(service, "t=all", worked.thread.id)

        assert [call.position for call in found.calls] == [1, 2]
        assert found.total == 3

    @pytest.mark.usefixtures("worked")
    def test_a_thread_the_record_does_not_hold_is_not_found(
        self, service: ItemsService
    ) -> None:
        with pytest.raises(RecordNotFoundException):
            _calls(service, "t=all", uuid.uuid4())

    def test_a_state_with_faults_is_refused(
        self, service: ItemsService, worked: Record
    ) -> None:
        with pytest.raises(StateRefusedException):
            _calls(service, "t=never", worked.thread.id)
