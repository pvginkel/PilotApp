"""A conversation in the reader (F154.7, F165.7): its calls the chart's, each
joined to its blocks in the reading by the id its facts carry; each of a
block's texts cut at 1,500 characters, a cut block carrying its full length,
in batches of 200 calls, the one holding the selected call first; the full
texts in one answer where they add up to 2 MB or less, else a block's whole
as it opens; past 2,000 calls the reader stops and says so; and a reading
refused or gone an answer of its own.

The record is `tests.support.dashboard.record`'s: the work item's thread
holds three Calls, `msg_0001` to `msg_0003`, and its sub-agent one.
"""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from pilot_collection.reading import ReadingSchema
from pilot_scenario import SCENARIO
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.dashboard import reader as reader_module
from app.dashboard.reader import (
    CUT,
    WHOLE,
    Batch,
    Placed,
    ReaderService,
)
from app.dashboard.readings import ReadingsService
from app.exceptions import RecordNotFoundException, StateRefusedException
from app.models import Call, Project, Transcript, User
from app.models import Session as WorkSession
from app.services.container import ServiceContainer
from app.services.fake_collector import validator
from tests.support.dashboard import Record, record
from tests.support.fake_collector import ServedFakeCollector
from tests.support.transcripts import CAMP, STARTED, SUB_AGENT

AT = STARTED + timedelta(minutes=1)


@pytest.fixture
def worked(
    session: DbSession, person: User, project: Project, project_session: WorkSession
) -> Record:
    return record(session, person, project, project_session)


@pytest.fixture
def service(
    container: ServiceContainer, readings_service: ReadingsService
) -> ReaderService:
    return container.reader_service()


def _said(text: str) -> dict[str, Any]:
    return {"kind": "user", "at": AT, "writer": "person", "text": text}


def _answer(text: str) -> dict[str, Any]:
    return {"kind": "text", "at": AT, "text": text}


def _call(message_id: str, asked: str, answered: str) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "received": [_said(asked)],
        "sent": [_answer(answered)],
    }


def _reading(
    calls: list[dict[str, Any]],
    after: list[dict[str, Any]] | None = None,
    agent_id: str | None = None,
) -> ReadingSchema:
    return ReadingSchema.model_validate(
        {
            "session_id": CAMP,
            "agent_id": agent_id,
            "file_size": 48_112,
            "file_modified_at": STARTED + timedelta(minutes=12),
            "calls": calls,
            "after": after or [],
        }
    )


def _thread_reading(after: list[dict[str, Any]] | None = None) -> ReadingSchema:
    """A reading of the record's thread: each Call asked and answered."""
    return _reading(
        [
            _call("msg_0001", "Halve the soup", "Halved."),
            _call("msg_0002", "Now for two", "Two bowls."),
            _call("msg_0003", "And the bread?", "One loaf."),
        ],
        after,
    )


def _texts(blocks: Any) -> list[str]:
    return [shown.block.text for shown in blocks]


def _thread_calls(worked: Record) -> list[int]:
    return [call.id for call in worked.calls[:3]]


class TestBatch:
    def test_each_call_takes_its_blocks_by_the_id_its_facts_carry(
        self,
        service: ReaderService,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        fake_collector.serve(_thread_reading(after=[_said("Thanks")]))

        found = service.batch("t=all", worked.thread.id)

        head = found.head
        assert (head.status, head.why, head.conversation) == (
            "served",
            None,
            worked.thread.id,
        )
        assert (head.total, head.held, head.stopped, head.batches) == (
            3,
            3,
            False,
            (0,),
        )
        assert found.batch == 0
        assert [call.call for call in found.calls] == _thread_calls(worked)
        assert [call.held for call in found.calls] == [True] * 3
        assert [_texts(call.received) for call in found.calls] == [
            ["Halve the soup"],
            ["Now for two"],
            ["And the bread?"],
        ]
        assert [_texts(call.sent) for call in found.calls] == [
            ["Halved."],
            ["Two bowls."],
            ["One loaf."],
        ]
        assert [_texts(call.after) for call in found.calls] == [[], [], ["Thanks"]]
        assert head.address.address == "#dash/t=all&by=project&m=cost.sum&col=none"

    def test_the_calls_come_in_the_order_of_their_positions_not_their_ids(
        self,
        service: ReaderService,
        session: DbSession,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        """A publication keeps a held Call's id while it writes positions
        from its boundary on, so ids and positions can run against each
        other: the chart's list is by position, and so is the reader."""
        first, second, third = worked.calls[:3]
        one, two = first.position, second.position
        first.position = 1_000
        session.flush()
        second.position, first.position = one, two
        session.flush()
        fake_collector.serve(_thread_reading(after=[]))

        found = service.batch("t=all", worked.thread.id)

        assert [call.call for call in found.calls] == [second.id, first.id, third.id]

    def test_a_reading_in_another_order_joins_by_the_id(
        self,
        service: ReaderService,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        fake_collector.serve(
            _reading(
                [
                    _call("msg_0003", "And the bread?", "One loaf."),
                    _call("msg_0001", "Halve the soup", "Halved."),
                ],
                after=[_said("Thanks")],
            )
        )

        found = service.batch("t=all", worked.thread.id)

        assert [call.call for call in found.calls] == _thread_calls(worked)
        assert [call.held for call in found.calls] == [True, False, True]
        assert [_texts(call.sent) for call in found.calls] == [
            ["Halved."],
            [],
            ["One loaf."],
        ]
        # what follows the reading's last Call stands on it, wherever it is
        assert [_texts(call.after) for call in found.calls] == [["Thanks"], [], []]

    def test_what_follows_a_call_the_record_lacks_stands_nowhere(
        self,
        service: ReaderService,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        reading = _thread_reading(after=[_said("Thanks")])
        fake_collector.serve(
            reading.model_copy(
                update={
                    "calls": [
                        *reading.calls,
                        _reading([_call("msg_0004", "More?", "No.")]).calls[0],
                    ]
                }
            )
        )

        found = service.batch("t=all", worked.thread.id)

        assert [call.call for call in found.calls] == _thread_calls(worked)
        assert [_texts(call.after) for call in found.calls] == [[], [], []]

    def test_a_sub_agents_reading(
        self,
        service: ReaderService,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        fake_collector.serve(
            _reading([_call("msg_0001", "Explore", "Found it.")], agent_id=SUB_AGENT)
        )

        found = service.batch("t=all", worked.sub_agent.id)

        assert [(call.call, _texts(call.sent)) for call in found.calls] == [
            (worked.calls[3].id, ["Found it."])
        ]

    def test_a_long_text_is_cut_and_carries_its_full_length(
        self,
        service: ReaderService,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        long, edge = "a" * (CUT + 1), "b" * CUT
        fake_collector.serve(
            _reading(
                [
                    {
                        "message_id": "msg_0001",
                        "received": [_said(long), _said(edge)],
                        "sent": [{"kind": "thinking", "at": AT, "text": long}],
                    }
                ]
            )
        )

        first = service.batch("t=all", worked.thread.id).calls[0]

        assert [(shown.block.text, shown.length) for shown in first.received] == [
            ("a" * CUT, CUT + 1),
            (edge, None),
        ]
        assert (first.sent[0].block.text, first.sent[0].length) == ("a" * CUT, CUT + 1)

    def test_a_tool_calls_input_at_its_bound_is_whole(
        self,
        service: ReaderService,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        given = {"command": "c" * 1_000, "description": "d" * (CUT - 1_000)}
        fake_collector.serve(
            _reading(
                [
                    {
                        "message_id": "msg_0001",
                        "received": [],
                        "sent": [
                            {
                                "kind": "tool_call",
                                "at": AT,
                                "tool_use_id": "toolu_01",
                                "tool": "Bash",
                                "input": given,
                                "started": None,
                                "result": None,
                            }
                        ],
                    }
                ]
            )
        )

        (shown,) = service.batch("t=all", worked.thread.id).calls[0].sent

        assert (shown.block.input, shown.length) == (given, None)

    def test_a_tool_calls_input_is_cut_together_and_its_result_on_its_own(
        self,
        service: ReaderService,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        given = {
            "command": "c" * 1_000,
            "description": "d" * 1_000,
            "timeout": 60,
            "paths": ["p" * 10],
        }
        result = {"at": AT, "error": False, "text": "r" * 2_000, "images": []}
        fake_collector.serve(
            _reading(
                [
                    {
                        "message_id": "msg_0001",
                        "received": [],
                        "sent": [
                            {
                                "kind": "tool_call",
                                "at": AT,
                                "tool_use_id": "toolu_01",
                                "tool": "Bash",
                                "input": given,
                                "started": None,
                                "result": result,
                            },
                            {
                                "kind": "tool_call",
                                "at": AT,
                                "tool_use_id": "toolu_02",
                                "tool": "Read",
                                "input": {"file_path": "/work/RecipeBox/soup.md"},
                                "started": None,
                                "result": None,
                            },
                        ],
                    }
                ]
            )
        )

        cut, whole = service.batch("t=all", worked.thread.id).calls[0].sent

        assert cut.block.input == {
            "command": "c" * 1_000,
            "description": "d" * 500,
            "timeout": 60,
            "paths": [""],
        }
        assert cut.block.result.text == "r" * CUT
        assert cut.length == 1_000 + 1_000 + 10 + 2_000
        assert (whole.block.input, whole.length) == (
            {"file_path": "/work/RecipeBox/soup.md"},
            None,
        )

    def test_an_image_and_a_wordless_line_stand_whole(
        self,
        service: ReaderService,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        fake_collector.serve(
            _reading(
                [
                    {
                        "message_id": "msg_0001",
                        "received": [
                            {
                                "kind": "image",
                                "at": AT,
                                "media_type": "image/png",
                                "size": 90_000,
                            },
                            {"kind": "system", "at": AT, "subtype": None, "text": None},
                        ],
                        "sent": [],
                    }
                ]
            )
        )

        found = service.batch("t=all", worked.thread.id)

        assert [shown.length for shown in found.calls[0].received] == [None, None]
        assert found.head.characters == 0

    def test_in_batches_the_one_holding_the_selected_call_first(
        self,
        service: ReaderService,
        worked: Record,
        fake_collector: ServedFakeCollector,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(reader_module, "BATCH", 2)
        fake_collector.serve(_thread_reading())
        first, second, third = _thread_calls(worked)
        selecting = f"t=all&d=items&it=conversation,{worked.thread.id}&call={third}"

        selected = service.batch(selecting, worked.thread.id)
        other = service.batch(selecting, worked.thread.id, batch=0)

        assert selected.head.batches == (1, 0)
        assert (selected.batch, [call.call for call in selected.calls]) == (1, [third])
        assert (other.batch, [call.call for call in other.calls]) == (
            0,
            [first, second],
        )
        assert service.batch("t=all", worked.thread.id).head.batches == (0, 1)

    def test_a_batch_past_the_last_holds_no_call(
        self,
        service: ReaderService,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        fake_collector.serve(_thread_reading())

        found = service.batch("t=all", worked.thread.id, batch=1)

        assert (found.batch, found.calls) == (1, ())

    def test_past_calls_it_stops_and_says_so(
        self,
        service: ReaderService,
        worked: Record,
        fake_collector: ServedFakeCollector,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(reader_module, "CALLS", 2)
        fake_collector.serve(_thread_reading(after=[_said("Thanks")]))

        found = service.batch("t=all", worked.thread.id)

        assert (found.head.total, found.head.held, found.head.stopped) == (3, 2, True)
        assert [call.call for call in found.calls] == _thread_calls(worked)[:2]
        assert [_texts(call.after) for call in found.calls] == [[], []]

    def test_a_thread_with_no_call_has_no_batch(
        self,
        service: ReaderService,
        session: DbSession,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        for call in session.scalars(
            select(Call).where(Call.transcript_id == worked.sub_agent.id)
        ):
            session.delete(call)
        session.flush()
        fake_collector.serve(_reading([], after=[_said("Hello")], agent_id=SUB_AGENT))

        found = service.batch("t=all", worked.sub_agent.id)

        assert (found.head.status, found.head.batches) == ("served", ())
        assert (found.batch, found.calls) == (None, ())

    def test_a_transcript_gone_from_the_home_says_so(
        self,
        service: ReaderService,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        found = service.batch("t=all", worked.thread.id)

        assert (found.head.status, found.head.why) == ("gone", None)
        assert (found.head.batches, found.head.characters, found.head.whole) == (
            (),
            None,
            None,
        )
        assert (found.head.total, found.head.held) == (3, 3)
        assert (found.batch, found.calls) == (None, ())

    def test_a_refused_read_says_why(
        self,
        service: ReaderService,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        fake_collector.serve(_thread_reading())
        fake_collector.refuse("version")

        found = service.batch("t=all", worked.thread.id)

        assert found.head.status == "refused"
        assert found.head.why is not None
        assert "Pilot reads version 1" in found.head.why
        assert found.calls == ()

    def test_it_asks_the_collector_conditionally_at_every_answer(
        self,
        service: ReaderService,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        reading = _thread_reading()
        fake_collector.serve(reading)

        service.batch("t=all", worked.thread.id)
        service.batch("t=all", worked.thread.id, batch=0)

        assert [(ask.validator, ask.status) for ask in fake_collector.asks()] == [
            (None, 200),
            (validator(reading), 304),
        ]

    def test_a_thread_the_record_does_not_hold_is_not_found(
        self, service: ReaderService, fake_collector: ServedFakeCollector
    ) -> None:
        with pytest.raises(RecordNotFoundException):
            service.batch("t=all", uuid.uuid4())

        assert fake_collector.asks() == []

    def test_a_state_with_faults_is_refused(
        self, service: ReaderService, worked: Record
    ) -> None:
        with pytest.raises(StateRefusedException):
            service.batch("t=never", worked.thread.id)


class TestTheSizeRule:
    def test_the_full_texts_come_in_one_answer_at_their_bound(
        self,
        service: ReaderService,
        worked: Record,
        fake_collector: ServedFakeCollector,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_collector.serve(_thread_reading(after=[_said("Thanks")]))
        characters = sum(
            len(text)
            for text in (
                "Halve the soup",
                "Halved.",
                "Now for two",
                "Two bowls.",
                "And the bread?",
                "One loaf.",
                "Thanks",
            )
        )

        monkeypatch.setattr(reader_module, "WHOLE", characters)
        whole = service.batch("t=all", worked.thread.id).head
        monkeypatch.setattr(reader_module, "WHOLE", characters - 1)
        cut = service.batch("t=all", worked.thread.id).head

        assert (whole.characters, whole.whole) == (characters, True)
        assert (cut.characters, cut.whole) == (characters, False)

    def test_a_reading_too_large_comes_a_block_at_a_time(
        self,
        service: ReaderService,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        fake_collector.serve(_thread_reading())
        fake_collector.too_large(CAMP)

        found = service.batch("t=all", worked.thread.id)

        assert found.head.whole is False
        assert found.head.characters is not None
        assert found.head.characters > WHOLE
        (line,) = found.calls[2].after
        assert (len(line.block.text), line.length) == (CUT, 3_000_000)
        assert service.texts("t=all", worked.thread.id).texts == ()


class TestTexts:
    def test_every_block_cut_whole_at_its_place(
        self,
        service: ReaderService,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        long = "a" * (CUT + 1)
        fake_collector.serve(
            _reading(
                [
                    {
                        "message_id": "msg_0001",
                        "received": [_said("Halve the soup"), _said(long)],
                        "sent": [_answer("Halved.")],
                    },
                    _call("msg_0003", "And the bread?", long),
                ],
                after=[_said(long)],
            )
        )
        first, _, third = _thread_calls(worked)

        found = service.texts("t=all", worked.thread.id)

        assert found.head.whole is True
        assert [
            (placed.call, placed.part, placed.index, placed.block.text)
            for placed in found.texts
        ] == [
            (first, "received", 1, long),
            (third, "sent", 0, long),
            (third, "after", 0, long),
        ]

    def test_none_where_they_do_not_come_in_one_answer(
        self,
        service: ReaderService,
        worked: Record,
        fake_collector: ServedFakeCollector,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(reader_module, "WHOLE", 10)
        fake_collector.serve(_reading([_call("msg_0001", "a" * (CUT + 1), "Halved.")]))

        found = service.texts("t=all", worked.thread.id)

        assert (found.head.whole, found.texts) == (False, ())

    def test_a_transcript_gone_has_none(
        self,
        service: ReaderService,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        found = service.texts("t=all", worked.thread.id)

        assert (found.head.status, found.texts) == ("gone", ())


class TestBlock:
    def test_one_block_whole_at_its_place(
        self,
        service: ReaderService,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        long = "a" * 3_000_000
        fake_collector.serve(_thread_reading(after=[_said("Thanks"), _said(long)]))
        first, _, third = _thread_calls(worked)

        opened = service.block("t=all", worked.thread.id, third, "after", 1)
        sent = service.block("t=all", worked.thread.id, first, "sent", 0)

        assert opened.head.whole is False
        assert opened.block == Placed(
            third, "after", 1, _reading([], after=[_said(long)]).after[0]
        )
        assert sent.block is not None
        assert sent.block.block.text == "Halved."

    def test_a_place_the_reading_lacks_is_not_found(
        self,
        service: ReaderService,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        fake_collector.serve(_thread_reading())
        first, second, _ = _thread_calls(worked)

        for call, part, index in (
            (first, "sent", 1),
            (first, "after", 0),
            (second + 1_000, "sent", 0),
        ):
            with pytest.raises(RecordNotFoundException):
                service.block("t=all", worked.thread.id, call, part, index)

    def test_a_refused_read_has_none(
        self,
        service: ReaderService,
        worked: Record,
        fake_collector: ServedFakeCollector,
    ) -> None:
        fake_collector.refuse("unreadable")
        first = _thread_calls(worked)[0]

        found = service.block("t=all", worked.thread.id, first, "sent", 0)

        assert (found.head.status, found.block) == ("refused", None)


@pytest.mark.usefixtures("service_user")
class TestTheScenariosConversations:
    def test_every_call_of_a_loaded_conversation_has_its_blocks(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        service: ReaderService,
    ) -> None:
        loaded = container.scenario_service().load(SCENARIO, {"recipe-box": project.id})

        for thread in loaded:
            found: Batch = service.batch("t=all", thread.id)

            assert found.head.status == "served"
            assert [call.call for call in found.calls] == list(
                session.scalars(
                    select(Call.id)
                    .where(Call.transcript_id == thread.id)
                    .order_by(Call.position)
                )
            )
            assert all(call.held for call in found.calls)
            assert all(call.sent for call in found.calls)
        assert {type(thread) for thread in loaded} == {Transcript}
