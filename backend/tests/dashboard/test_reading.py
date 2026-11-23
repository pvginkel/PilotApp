"""The reader of a view's state (F154.1, F154.2): every part read and checked
against the catalogue, a gone key dropped with a note, and a state with
faults refused with every fault at once."""

import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.dashboard.catalogue import Catalogue, Marker, QuickFilter
from app.dashboard.reading import Checked, is_entry, read, read_chip, read_simple, split
from app.dashboard.state import (
    OTHERS,
    Between,
    Draw,
    Filter,
    Focus,
    Item,
    Level,
    OnItems,
    OnRows,
    Outliers,
    Pin,
    Preset,
    RatioKey,
    Roll,
    Selected,
    Simple,
    Sort,
    State,
    Weeks,
    WrittenRatio,
    write,
)
from app.exceptions import StateRefusedException
from app.models import QuotaWeek
from app.services.quota_week_service import Period
from tests.support.dashboard import catalogue

PROJECT = "5b0e6a4c-2f4a-4d7e-9b1e-0c3f0c7c1a2b"
FIRST = datetime(2025, 1, 2, 10, tzinfo=UTC)
Reads = Callable[..., Checked]
Refuses = Callable[[str], list[str]]
SECOND = datetime(2025, 1, 9, 10, tzinfo=UTC)
MARKERS = tuple(
    Marker(key, key, f"Where a version of {key} was first seen", key)
    for key in ("claude_code_version", "plugin_pantry_version")
)


@pytest.fixture
def held(session: DbSession) -> Catalogue:
    return catalogue(session)


@pytest.fixture
def weeks(session: DbSession) -> list[Period]:
    return [
        Period(starts_at, ends_at)
        for starts_at, ends_at in session.execute(
            select(QuotaWeek.starts_at, QuotaWeek.ends_at).order_by(QuotaWeek.starts_at)
        )
    ]


@pytest.fixture
def reads(held: Catalogue, weeks: list[Period]) -> Reads:
    def reading(written: str, against: Catalogue | None = None) -> Checked:
        return read(written, against or held, weeks)

    return reading


@pytest.fixture
def refuses(held: Catalogue, weeks: list[Period]) -> Refuses:
    def refusal(written: str) -> list[str]:
        with pytest.raises(StateRefusedException) as refused:
            read(written, held, weeks)
        return refused.value.message.splitlines()

    return refusal


def _state(reads: Reads, written: str) -> State:
    checked: Checked = reads(written)
    assert checked.notes == ()
    return checked.state


class TestSplit:
    def test_a_states_parts_with_an_addresss_prefix_read_off(self) -> None:
        assert split("#dash/by=project&&m=cost.sum&x") == [
            ("by=project", "by", "project"),
            ("m=cost.sum", "m", "cost.sum"),
            ("x", "x", ""),
        ]

    def test_an_entry_is_its_focus_alone(self) -> None:
        assert is_entry(f"f=project:{PROJECT}")
        assert is_entry(f"#dash/f=project:{PROJECT}")
        assert not is_entry(f"f=project:{PROJECT}&t=all")
        assert not is_entry("by=project")
        assert not is_entry("f")


class TestState:
    def test_nothing_is_the_scratch(self, reads: Reads) -> None:
        assert _state(reads, "") == State()
        assert write(_state(reads, "#dash/")) == "t=qw&by=project&m=cost.sum&col=none"

    def test_its_parts_in_any_order(self, reads: Reads) -> None:
        assert _state(reads, "col=none&m=cost.sum&by=project&t=qw") == State()

    def test_every_fault_at_once_in_the_order_written(self, refuses: Refuses) -> None:
        assert refuses("x=1&by=phases&m=cost.medain&rel=2") == [
            "Cannot read the view because its state has 4 faults.",
            '- x=1: "x" is no part of a state.',
            '- by=phases: "phases" is no dimension. By takes a part or an '
            "attribute; the catalogue's dimensions list them.",
            '- m=cost.medain: "medain" is no aggregate. Did you mean "median" or '
            '"mean"? cost takes sum, median, mean, max and p90, and calls.count '
            "counts its fact's items.",
            '- rel=2: "2" is no switch. rel takes 1.',
            "A state reads <part>=<value>&…, its parts t, by, p, m, dr, c, b, col, "
            "o, d, sel, ig, it, call, f, rel, mk, dw, roll, lit, ev and z, as in "
            "t=qw&by=project&m=cost.sum.",
            "A By reads by=<dimension>, as in by=project.",
            "A measure reads m=<figure>.<aggregate>[.<grain>][(<filter>;…)], "
            "m=r:<ratio> or m=r:<name>:<measure>/<measure>, as in "
            "m=cost.median.conversation or m=cost.sum(miss=1).",
            "Relative reads rel=1, as in rel=1.",
        ]

    def test_a_part_with_no_value_and_one_unknown(self, refuses: Refuses) -> None:
        assert refuses("by&tt=qw")[1:3] == [
            '- by: "by" has no "=". A part reads <key>=<value>, as in by=project.',
            '- tt=qw: "tt" is no part of a state. Did you mean "t" or "it"?',
        ]

    def test_a_part_a_state_has_once_written_twice(self, refuses: Refuses) -> None:
        assert refuses("by=project&by=psession")[1] == (
            "- by=psession: by stands 2 times, and a state has one."
        )

    def test_a_percent_that_encodes_nothing(self, refuses: Refuses) -> None:
        assert refuses("c=effort:%zz")[1] == (
            '- c=effort:%zz: "%zz" holds a "%" that encodes no character. A '
            "value's reserved characters are percent-encoded, as in %2C for a comma."
        )


class TestTime:
    @pytest.mark.parametrize(
        "key", ["today", "d2", "d7", "qw", "lqw", "l2", "l4", "l8", "all"]
    )
    def test_a_range_of_the_catalogue(self, reads: Reads, key: str) -> None:
        assert _state(reads, f"t={key}").time == Preset(key)

    def test_one_it_has_not(self, refuses: Refuses) -> None:
        assert refuses("t=l3")[1] == (
            '- t=l3: "l3" is no time range. Did you mean "l2", "l4" or "l8"? A '
            "range is today, d2, d7, qw, lqw, l2, l4, l8 or all."
        )

    def test_weeks_by_their_keys_in_order_once_each(self, reads: Reads) -> None:
        state = _state(
            reads,
            "t=wk,2025-01-09T10%3A00%3A00Z,2025-01-02T10:00:00Z,2025-01-09T11:00:00%2B01:00",
        )

        assert state.time == Weeks((FIRST, SECOND))
        assert write(state).startswith(
            "t=wk,2025-01-02T10%3A00%3A00Z,2025-01-09T10%3A00%3A00Z&"
        )

    def test_a_weeks_label_is_not_its_key(self, refuses: Refuses) -> None:
        assert refuses("t=wk,2025-W02")[1] == (
            '- t=wk,2025-W02: "2025-W02" is a quota week\'s label, which two weeks '
            'may share, not its key. Did you mean "2025-01-09T10:00:00Z"? A quota '
            "week's key is the instant it starts, as in 2025-01-02T10:00:00Z."
        )

    def test_an_instant_in_a_week_names_that_week(self, refuses: Refuses) -> None:
        assert refuses("t=wk,2025-01-03T00:00:00Z")[1] == (
            '- t=wk,2025-01-03T00:00:00Z: "2025-01-03T00:00:00Z" is no quota '
            "week's key. Did you mean \"2025-01-02T10:00:00Z\"? A quota week's key "
            "is the instant it starts, as in 2025-01-02T10:00:00Z."
        )

    def test_weeks_that_name_none(self, refuses: Refuses) -> None:
        assert refuses("t=wk")[1] == "- t=wk: wk names no quota week."

    def test_a_range_between_dates_and_times(self, reads: Reads) -> None:
        assert _state(reads, "t=c,2026-11-01,2026-11-01").time == Between(
            date(2026, 11, 1), date(2026, 11, 1)
        )
        assert _state(reads, "t=c,2026-11-01T08%3A30,2026-11-01%2018:45:10").time == (
            Between(datetime(2026, 11, 1, 8, 30), datetime(2026, 11, 1, 18, 45, 10))
        )
        assert _state(reads, "t=c,,2026-11-07").time == Between(None, date(2026, 11, 7))

    @pytest.mark.parametrize(
        ("written", "fault"),
        [
            (
                "t=c,2026-11-07",
                "- t=c,2026-11-07: c takes two bounds, its start and its end.",
            ),
            ("t=c,,", "- t=c,,: c names neither a start nor an end."),
            (
                "t=c,2026-11-07,2026-11-01",
                "- t=c,2026-11-07,2026-11-01: the range ends before it starts.",
            ),
            (
                "t=c,2026-11-01T10:00,2026-11-01T10:00",
                "- t=c,2026-11-01T10:00,2026-11-01T10:00: the range ends before it "
                "starts.",
            ),
            (
                "t=c,1%20Nov,",
                '- t=c,1%20Nov,: "1 Nov" is no date or time. A bound reads '
                "YYYY-MM-DD, or YYYY-MM-DDTHH:MM[:SS] with a time of day, in "
                "Europe/Amsterdam.",
            ),
        ],
    )
    def test_a_range_that_does_not_read(
        self, refuses: Refuses, written: str, fault: str
    ) -> None:
        assert refuses(written)[1] == fault


class TestBy:
    @pytest.mark.parametrize("key", ["psession", "work_type", "model"])
    def test_a_part_or_an_attribute(self, reads: Reads, key: str) -> None:
        assert _state(reads, f"by={key}").by == key

    def test_a_time_dimension_is_over_time_by_the_level_under_the_stack(
        self, reads: Reads
    ) -> None:
        assert _state(reads, "by=day") == State(presentation="time", axis="day")
        state = _state(reads, f"dr=project:{PROJECT}@project&by=hod")

        assert (state.by, state.presentation, state.axis) == ("psession", "time", "hod")
        assert _state(reads, "dr=project:~@project&by=hod").by == "sitting"

    def test_an_order_dimension_is_its_part_in_order(self, reads: Reads) -> None:
        assert _state(reads, "by=session_start") == State(
            by="psession", presentation="order"
        )
        assert _state(reads, "by=session_start&p=rows").presentation == "rows"

    def test_one_it_has_not(self, refuses: Refuses) -> None:
        assert refuses("by=projekt")[1] == (
            '- by=projekt: "projekt" is no dimension. Did you mean "project"? By '
            "takes a part or an attribute; the catalogue's dimensions list them."
        )


class TestPresentation:
    def test_rows_is_written_as_none(self, reads: Reads) -> None:
        assert write(_state(reads, "p=rows")) == "t=qw&by=project&m=cost.sum&col=none"

    def test_a_table_and_lanes(self, reads: Reads) -> None:
        assert _state(reads, "p=table").presentation == "table"
        assert _state(reads, "by=conversation&p=lanes").presentation == "lanes"

    def test_in_order_names_its_order_where_it_is_not_the_bys_first(
        self, reads: Reads
    ) -> None:
        assert _state(reads, "by=psession&p=order,session_start") == State(
            by="psession", presentation="order"
        )

    def test_over_time_has_its_grain_the_first_where_it_names_none(
        self, reads: Reads
    ) -> None:
        assert _state(reads, "p=time").axis == "qweek"
        assert _state(reads, "p=time,weekday").axis == "weekday"

    @pytest.mark.parametrize(
        ("written", "fault"),
        [
            (
                "p=sideways",
                '- p=sideways: "sideways" is no presentation. A presentation is rows, '
                "order, time, lanes or table.",
            ),
            (
                "p=table,day",
                '- p=table,day: "table,day" has more after table than it takes.',
            ),
            (
                "by=source&p=lanes",
                "- p=lanes: source is no part, and a lane is a part's. Lanes take a "
                "By that is a part: project, psession, pturn, sitting, conversation "
                "or call.",
            ),
            (
                "p=order",
                "- p=order: project has no order. In order takes a By that has one: "
                "psession or pturn.",
            ),
            (
                "by=psession&p=order,turn_seq",
                '- p=order,turn_seq: "turn_seq" is no order of psession. psession is '
                "in order by session_start.",
            ),
            (
                "p=time,week",
                '- p=time,week: "week" is no time dimension. Did you mean "qweek"? '
                "Over time takes qweek, day, weekday or hod.",
            ),
        ],
    )
    def test_one_that_does_not_read(
        self, refuses: Refuses, written: str, fault: str
    ) -> None:
        assert refuses(written)[1] == fault


class TestMeasures:
    def test_a_figure_takes_its_aggregate_where_it_names_none(
        self, reads: Reads
    ) -> None:
        assert _state(reads, "m=cost&m=ctx&m=calls").measures == (
            Simple("cost", "sum"),
            Simple("ctx", "max"),
            Simple("calls", "count"),
        )

    def test_its_facts_own_grain_is_written_as_none(self, reads: Reads) -> None:
        assert _state(
            reads, "m=cost.sum.call&m=turns.count.pturn&m=events.count.event"
        ).measures == (
            Simple("cost", "sum"),
            Simple("turns", "count"),
            Simple("events", "count"),
        )
        assert _state(reads, "m=cost.median.conversation").measures == (
            Simple("cost", "median", "conversation"),
        )

    def test_its_filters(self, reads: Reads) -> None:
        assert _state(
            reads, f"m=cost.sum(source=chat|pilot;!miss=1;session_start={PROJECT})"
        ).measures == (
            Simple(
                "cost",
                "sum",
                None,
                (
                    Filter("source", ("chat", "pilot")),
                    Filter("miss", (1,), negated=True),
                    Filter("psession", (uuid.UUID(PROJECT),)),
                ),
            ),
        )

    def test_a_ratio_of_the_catalogue_and_one_written_out(self, reads: Reads) -> None:
        assert _state(
            reads, "m=r:overhead&m=r:Miss%20share:miss_cost.sum/cost"
        ).measures == (
            RatioKey("overhead"),
            WrittenRatio(
                "Miss share", Simple("miss_cost", "sum"), Simple("cost", "sum")
            ),
        )

    def test_a_ratio_that_is_gone_is_dropped_with_a_note(self, reads: Reads) -> None:
        checked = reads("m=cost.sum&m=r:overhaed&o=desc,r:overhaed")

        assert checked.state.measures == (Simple("cost", "sum"),)
        assert checked.state.sort is None
        assert checked.notes == (
            'm=r:overhaed: no ratio has the key "overhaed", so the measure is '
            'dropped. Did you mean "overhead"?',
            "o=desc,r:overhaed: the sort is on a measure dropped, so it is dropped "
            "too.",
        )

    def test_a_view_left_with_no_measure_takes_the_scratchs(self, reads: Reads) -> None:
        checked = reads("m=r:gone")

        assert checked.state.measures == (Simple("cost", "sum"),)
        assert checked.notes[1] == (
            "m=r:gone: the view keeps no measure, so it takes cost.sum."
        )

    @pytest.mark.parametrize(
        ("written", "fault"),
        [
            (
                "m=coast.sum",
                '- m=coast.sum: "coast" is no figure. Did you mean "cost"? The '
                "catalogue's measures list the figures.",
            ),
            (
                "m=cost.count",
                "- m=cost.count: count counts a fact's items, on its counting figure "
                "alone. cost takes sum, median, mean, max and p90, and calls.count "
                "counts its fact's items.",
            ),
            (
                "m=cost.sum.events",
                '- m=cost.sum.events: "events" is no grain. Did you mean "event"? '
                "cost takes the grains project, psession, pturn, sitting, "
                "conversation and call.",
            ),
            (
                "m=turns.sum.call",
                "- m=turns.sum.call: turns is a figure of Pilot turns, which have no "
                "call. turns takes the grains project, psession, pturn, sitting and "
                "conversation.",
            ),
            (
                "m=cost.sum.call.x",
                '- m=cost.sum.call.x: "cost.sum.call.x" is no measure. A measure '
                "reads <figure>.<aggregate>[.<grain>].",
            ),
            (
                "m=cost.sum(miss=1",
                '- m=cost.sum(miss=1: "cost.sum(miss=1" opens a filter that does not '
                "close at its end.",
            ),
            (
                "m=cost.sum(miss)",
                '- m=cost.sum(miss): "miss" is no filter. A measure\'s filter reads '
                "[!]<dimension>=<value>|<value>….",
            ),
            ("m=r:", "- m=r:: r: names no ratio."),
            (
                "m=r:Share:cost.sum",
                "- m=r:Share:cost.sum: a ratio written out reads "
                "r:<name>:<measure>/<measure>.",
            ),
        ],
    )
    def test_one_that_does_not_read(
        self, refuses: Refuses, written: str, fault: str
    ) -> None:
        assert refuses(written)[1] == fault


class TestValues:
    def test_each_by_the_type_of_its_dimensions_path(self, reads: Reads) -> None:
        chips = _state(
            reads,
            f"c=project:{PROJECT.upper()}&c=pturn:12&c=day:2026-11-03&c=hod:9,10"
            "&c=sitting:2026-11-03T08%3A00%3A00%2B01%3A00&c=effort:a%2Cb,~"
            "&c=weekday:1&c=qweek:2025-01-02T10:00:00Z",
        ).chips

        assert chips == (
            Pin("project", (uuid.UUID(PROJECT),)),
            Pin("pturn", (12,)),
            Pin("day", (date(2026, 11, 3),)),
            Pin("hod", (9, 10)),
            Pin("sitting", (datetime(2026, 11, 3, 7, tzinfo=UTC),)),
            Pin("effort", ("a,b", None)),
            Pin("weekday", (1,)),
            Pin("qweek", (FIRST,)),
        )

    @pytest.mark.parametrize(
        ("written", "fault"),
        [
            ("c=pturn:x", '- c=pturn:x: pturn takes a whole number, not "x".'),
            ("c=project:42", '- c=project:42: project takes an id, a UUID, not "42".'),
            (
                "c=day:3%20Nov",
                '- c=day:3%20Nov: day takes a date, YYYY-MM-DD, not "3 Nov".',
            ),
            (
                "c=sitting:2026-11-03",
                "- c=sitting:2026-11-03: sitting takes an instant with its offset, as "
                'in 2026-11-19T10:00:00Z, not "2026-11-03".',
            ),
            (
                "c=miss:yes",
                '- c=miss:yes: "yes" is no value of miss. The values of miss are 1 and '
                "0.",
            ),
            (
                "c=source:chats",
                '- c=source:chats: "chats" is no value of source. Did you mean "chat"? '
                "The values of source are work, pilot and chat.",
            ),
            (
                "c=source:Pilot%27s%20chat",
                '- c=source:Pilot%27s%20chat: "Pilot\'s chat" is no value of source. '
                'Did you mean "chat"? The values of source are work, pilot and chat.',
            ),
        ],
    )
    def test_one_that_does_not_read(
        self, refuses: Refuses, written: str, fault: str
    ) -> None:
        assert refuses(written)[1] == fault


class TestLevels:
    def test_a_parts_value_and_what_it_was_drilled_from(self, reads: Reads) -> None:
        assert _state(
            reads,
            f"dr=project:{PROJECT}@project&dr=psession:~@session_start&dr=pturn:3",
        ).levels == (
            Level("project", uuid.UUID(PROJECT), "project"),
            Level("psession", None, "session_start"),
            Level("pturn", 3, None),
        )

    @pytest.mark.parametrize(
        ("written", "fault"),
        [
            (
                "dr=project",
                "- dr=project: a drill level reads <part>:<value>@<dimension>.",
            ),
            (
                "dr=model:x@model",
                "- dr=model:x@model: model is no part, and a drill level is a part's "
                "value. A filter on it is a chip, c=model:<value>.",
            ),
            (
                "dr=projects:x",
                '- dr=projects:x: "projects" is no dimension. Did you mean "project"?',
            ),
            (
                f"dr=project:{PROJECT}@projekt",
                f'- dr=project:{PROJECT}@projekt: "projekt" is no dimension. Did you '
                'mean "project"?',
            ),
        ],
    )
    def test_one_that_does_not_read(
        self, refuses: Refuses, written: str, fault: str
    ) -> None:
        assert refuses(written)[1] == fault


class TestChips:
    def test_a_dimensions_values_and_the_signs(self, reads: Reads) -> None:
        assert _state(
            reads, f"c=~!source:chat,pilot&c=!~miss:1&c=session_start:{PROJECT}"
        ).chips == (
            Pin("source", ("chat", "pilot"), negated=True, marked=True),
            Pin("miss", (1,), negated=True, marked=True),
            Pin("psession", (uuid.UUID(PROJECT),)),
        )

    def test_a_threshold_on_the_rows_a_condition_on_each_item_and_the_outliers(
        self, reads: Reads
    ) -> None:
        assert _state(
            reads,
            "c=~@rows,gt,100,cost.median.psession&c=!@items,le,0.5,cost&c=@outliers&c=~@outliers",
        ).chips == (
            OnRows("gt", 100.0, Simple("cost", "median", "psession"), marked=True),
            OnItems("le", 0.5, Simple("cost", "sum"), negated=True),
            Outliers(),
            Outliers(marked=True),
        )

    def test_a_threshold_on_the_rows_by_a_ratio(self, reads: Reads) -> None:
        assert _state(
            reads, "c=@rows,gt,0.5,r:per_call&c=~@rows,lt,2,r:Mine:cost.sum/calls.count"
        ).chips == (
            OnRows("gt", 0.5, RatioKey("per_call")),
            OnRows(
                "lt",
                2.0,
                WrittenRatio("Mine", Simple("cost", "sum"), Simple("calls", "count")),
                marked=True,
            ),
        )

    def test_a_threshold_by_a_ratio_whose_key_is_gone_is_dropped_with_a_note(
        self, reads: Reads
    ) -> None:
        checked = reads("c=@rows,gt,1,r:per_cal&c=miss:1")

        assert checked.state.chips == (Pin("miss", (1,)),)
        assert checked.notes == (
            'c=@rows,gt,1,r:per_cal: no ratio has the key "per_cal", so the chip is '
            'dropped. Did you mean "per_call"?',
        )

    def test_a_condition_on_each_item_takes_no_ratio(self, refuses: Refuses) -> None:
        assert refuses("c=@items,gt,1,r:per_call")[1] == (
            '- c=@items,gt,1,r:per_call: "r:per_call" is no figure. The '
            "catalogue's measures list the figures."
        )

    @pytest.mark.parametrize(
        ("written", "fault"),
        [
            ("c=miss", '- c=miss: "miss" is no chip.'),
            (
                "c=@row,gt,1,cost.sum",
                '- c=@row,gt,1,cost.sum: "@row" is no chip. Did you mean "@rows"?',
            ),
            (
                "c=!@rows,gt,1,cost.sum",
                "- c=!@rows,gt,1,cost.sum: @rows keeps or marks the By's rows, and is "
                "never negated.",
            ),
            (
                "c=!@outliers",
                "- c=!@outliers: @outliers keeps or marks the By's rows, and is never "
                "negated.",
            ),
            (
                "c=@outliers,cost.sum",
                "- c=@outliers,cost.sum: @outliers takes nothing after it.",
            ),
            (
                "c=@items,gt,1",
                "- c=@items,gt,1: @items reads @items,<op>,<number>,<measure>.",
            ),
            (
                "c=@items,gte,1,cost.sum",
                '- c=@items,gte,1,cost.sum: "gte" is no operator. Did you mean "gt" or '
                '"ge"? An operator is gt, ge, lt or le.',
            ),
            (
                "c=@items,gt,one,cost.sum",
                '- c=@items,gt,one,cost.sum: "one" is no number.',
            ),
            (
                "c=@rows,gt,nan,cost.sum",
                '- c=@rows,gt,nan,cost.sum: "nan" is no number.',
            ),
            (
                "c=@items,gt,1e400,cost.sum",
                '- c=@items,gt,1e400,cost.sum: "1e400" is no number.',
            ),
        ],
    )
    def test_one_that_does_not_read(
        self, refuses: Refuses, written: str, fault: str
    ) -> None:
        assert refuses(written)[1] == fault


class TestQuickFilters:
    def test_those_the_catalogue_holds_once_each_in_order(
        self, reads: Reads, held: Catalogue
    ) -> None:
        with_filters = replace(
            held,
            quick_filters=(
                QuickFilter("misses", "Cache misses", "miss:1"),
                QuickFilter("expensive", "Expensive calls", "@items,gt,1,cost.sum"),
            ),
        )

        checked = reads("b=misses,expensive,misses", with_filters)

        assert checked.state.quick_filters == ("expensive", "misses")
        assert checked.notes == ()

    def test_one_that_is_gone_is_dropped_with_a_note(
        self, reads: Reads, held: Catalogue
    ) -> None:
        with_filters = replace(
            held, quick_filters=(QuickFilter("misses", "Cache misses", "miss:1"),)
        )

        checked = reads("b=misses,missed", with_filters)

        assert checked.state.quick_filters == ("misses",)
        assert checked.notes == (
            'b=misses,missed: no quick filter has the key "missed", so it is '
            'dropped. Did you mean "misses"?',
        )


class TestColor:
    def test_none_the_token_kinds_and_a_part_or_an_attribute(
        self, reads: Reads
    ) -> None:
        assert _state(reads, "col=none").color is None
        assert _state(reads, "col=token_kind").color == "token_kind"
        assert _state(reads, "col=event_kind").color == "event_kind"
        assert _state(reads, "col=conversation").color == "conversation"

    @pytest.mark.parametrize(
        ("written", "fault"),
        [
            (
                "col=day",
                '- col=day: "day" is no color, being a time dimension. A color is a '
                "part, an attribute, token_kind or none.",
            ),
            (
                "col=modle",
                '- col=modle: "modle" is no color. Did you mean "model"? A color is a '
                "part, an attribute, token_kind or none.",
            ),
        ],
    )
    def test_one_that_does_not_read(
        self, refuses: Refuses, written: str, fault: str
    ) -> None:
        assert refuses(written)[1] == fault


class TestSort:
    def test_the_bys_own_columns_and_a_measures(self, reads: Reads) -> None:
        assert _state(reads, "o=asc,label").sort == Sort("asc", "label")
        assert _state(
            reads, "m=cost.median.psession&o=desc,cost.median.psession"
        ).sort == (Sort("desc", "cost.median.psession"))

    def test_a_measure_spelled_otherwise_is_its_normal_form(self, reads: Reads) -> None:
        assert _state(reads, "m=cost&o=desc,cost.sum.call").sort == Sort(
            "desc", "cost.sum"
        )

    @pytest.mark.parametrize(
        ("written", "fault"),
        [
            (
                "o=desc,cost.max",
                '- o=desc,cost.max: "cost.max" is no column of the view. Its columns '
                "are label, axis, n and cost.sum.",
            ),
            (
                "o=down,label",
                '- o=down,label: "down" is no direction. A sort is asc or desc.',
            ),
            ("o=desc", "- o=desc: a sort reads <asc|desc>,<column>."),
        ],
    )
    def test_one_that_does_not_read(
        self, refuses: Refuses, written: str, fault: str
    ) -> None:
        assert refuses(written)[1] == fault


class TestDrawer:
    def test_its_parts(self, reads: Reads) -> None:
        state = _state(
            reads, f"d=items&sel={PROJECT}&ig=call&it=conversation,{PROJECT}&call=7"
        )

        assert (
            state.drawer,
            state.selected,
            state.item_grain,
            state.item,
            state.call,
        ) == (
            True,
            Selected(uuid.UUID(PROJECT)),
            "call",
            Item("conversation", uuid.UUID(PROJECT)),
            7,
        )

    def test_the_row_selected_is_a_value_of_what_the_view_asks_by(
        self, reads: Reads
    ) -> None:
        assert _state(reads, "sel=~").selected == Selected(None)
        assert _state(reads, "p=time,day&sel=2026-11-03").selected == Selected(
            date(2026, 11, 3)
        )
        assert _state(reads, f"by=psession&p=order&sel={PROJECT}").selected == (
            Selected(uuid.UUID(PROJECT))
        )

    def test_an_event_is_an_item_by_its_kind_and_the_id_of_its_row(
        self, reads: Reads
    ) -> None:
        state = _state(reads, "it=event,cache_miss%3A42")

        assert state.item == Item("event", "cache_miss:42")
        assert write(state).endswith("&it=event,cache_miss%3A42")

    @pytest.mark.parametrize(
        ("written", "fault"),
        [
            ("d=rows", '- d=rows: "rows" is no drawer. d takes items.'),
            ("sel=x", '- sel=x: project takes an id, a UUID, not "x".'),
            (
                "ig=calls",
                '- ig=calls: "calls" is no grain. Did you mean "call"? A grain is '
                "project, psession, pturn, sitting, conversation, call or event.",
            ),
            ("it=conversation", "- it=conversation: an item reads <grain>,<its key>."),
            (
                "it=event,a%2Cb",
                "- it=event,a%2Cb: \"a,b\" is no event's key. An event's key reads "
                "<kind>:<id>, the id of the row that records it.",
            ),
            (
                "it=event,cache_miss%3A0",
                '- it=event,cache_miss%3A0: "cache_miss:0" is no event\'s key. An '
                "event's key reads <kind>:<id>, the id of the row that records it.",
            ),
            (
                "it=event,cache_mis%3A42",
                '- it=event,cache_mis%3A42: "cache_mis" is no kind of event. Did you '
                'mean "cache_miss"? The catalogue\'s event_kind lists the kinds.',
            ),
            (
                "it=pturn,3&call=7",
                "- call=7: a call is selected in the reader, which a conversation's "
                "item opens. call takes it=conversation,<id> beside it.",
            ),
            (
                f"it=conversation,{PROJECT}&call=x",
                '- call=x: call takes a whole number, not "x".',
            ),
        ],
    )
    def test_one_that_does_not_read(
        self, refuses: Refuses, written: str, fault: str
    ) -> None:
        assert refuses(written)[1] == fault


class TestFocus:
    @pytest.mark.parametrize("key", ["project", "psession"])
    def test_pilots_own(self, reads: Reads, key: str) -> None:
        assert _state(reads, f"f={key}:{PROJECT}").focus == Focus(
            key, uuid.UUID(PROJECT)
        )

    @pytest.mark.parametrize(
        ("written", "fault"),
        [
            (
                "f=slice:x",
                '- f=slice:x: "slice" is no focus. A focus is project or psession.',
            ),
            (
                "f=conversation:x",
                '- f=conversation:x: "conversation" is no focus. A focus is project or '
                "psession.",
            ),
            ("f=project:~", "- f=project:~: a focus names one project, never none."),
            ("f=project", "- f=project: a focus reads <dimension>:<key>."),
            ("f=project:1", '- f=project:1: project takes an id, a UUID, not "1".'),
        ],
    )
    def test_one_that_does_not_read(
        self, refuses: Refuses, written: str, fault: str
    ) -> None:
        assert refuses(written)[1] == fault


class TestLook:
    def test_relative_and_the_markers(self, reads: Reads, held: Catalogue) -> None:
        marked = replace(held, markers=MARKERS)

        assert _state(reads, "rel=1").relative
        assert not _state(reads, "rel=0").relative
        assert _state(reads, "mk=none").markers == ()
        assert reads(
            "mk=plugin_pantry_version,claude_code_version,plugin_pantry_version",
            marked,
        ).state.markers == ("claude_code_version", "plugin_pantry_version")

    def test_a_marker_is_the_catalogues_kind_alone(
        self, held: Catalogue, weeks: list[Period]
    ) -> None:
        with pytest.raises(StateRefusedException) as refused:
            read("mk=claude_code_versoin,model", replace(held, markers=MARKERS), weeks)

        assert refused.value.message.splitlines()[1:3] == [
            '- mk=claude_code_versoin,model: "claude_code_versoin" is no kind of '
            'marker. Did you mean "claude_code_version"? A kind of marker is '
            "claude_code_version or plugin_pantry_version.",
            '- mk=claude_code_versoin,model: "model" is no kind of marker. A kind of '
            "marker is claude_code_version or plugin_pantry_version.",
        ]

    def test_what_a_series_draws(self, reads: Reads) -> None:
        assert _state(reads, "dw=band:off,dots:all,cols:on").draw == Draw(
            dots="all", band=False
        )
        assert write(_state(reads, "dw=cols:on")).endswith("col=none")

    def test_the_bands_length(self, reads: Reads) -> None:
        assert _state(reads, "roll=5,5").roll == Roll(5, 5)
        assert (
            write(_state(reads, "roll=10,15")) == "t=qw&by=project&m=cost.sum&col=none"
        )

    def test_the_values_lit_once_each_in_order(self, reads: Reads) -> None:
        assert _state(reads, "col=source&lit=work,~,%E2%80%A6,chat,work").lit == (
            OTHERS,
            "chat",
            "work",
            None,
        )
        assert _state(reads, "col=token_kind&lit=output,input").lit == (
            "input",
            "output",
        )

    @pytest.mark.parametrize(
        ("written", "normal"),
        [
            ("col=source&lit=work,\u2026", "lit=%E2%80%A6,work"),
            ("col=token_kind&lit=input,inpu%74", "lit=input"),
        ],
    )
    def test_the_values_lit_read_back_as_written(
        self, reads: Reads, written: str, normal: str
    ) -> None:
        once = write(_state(reads, written))
        assert once.endswith(normal)
        assert write(_state(reads, once)) == once

    def test_the_events_drawn_by_their_kinds(self, reads: Reads) -> None:
        assert _state(reads, "ev=hook_error,-cache_miss").events == (
            ("cache_miss", False),
            ("hook_error", True),
        )

    def test_a_window(self, reads: Reads) -> None:
        assert _state(reads, "z=1763600000,1763686400.5").zoom == (
            1763600000.0,
            1763686400.5,
        )

    @pytest.mark.parametrize(
        ("written", "fault"),
        [
            ("rel=yes", '- rel=yes: "yes" is no switch. rel takes 1.'),
            (
                "mk=model",
                '- mk=model: "model" is no kind of marker. A kind of marker is the '
                "version of a component the record holds, and it holds none.",
            ),
            (
                "dw=dots:some",
                '- dw=dots:some: "some" is no setting of dots. dots takes all, out or none.',
            ),
            (
                "dw=med:no",
                '- dw=med:no: "no" is no setting of med. med takes on or off.',
            ),
            ("dw=line:off", '- dw=line:off: "line" is no part of what a series draws.'),
            (
                "roll=0,5",
                '- roll=0,5: "0,5" is no length of the band. It takes two whole numbers '
                "above 0, the items it reads and the items before it draws.",
            ),
            (
                "lit=work",
                "- lit=work: lit lights the color's values, and the view has no color. "
                "It takes col=<dimension> or col=token_kind beside it.",
            ),
            (
                "col=token_kind&lit=outputs",
                '- lit=outputs: "outputs" is no token kind. Did you mean "output"? A '
                "token kind is input, cache_write, cache_read or output.",
            ),
            (
                "ev=hook_errors",
                '- ev=hook_errors: "hook_errors" is no kind of event. Did you mean '
                '"hook_error"? The catalogue\'s dimensions list the values of event_kind.',
            ),
            (
                "z=2,1",
                '- z=2,1: "2,1" is no window. A window is two epoch seconds, the first '
                "the earlier.",
            ),
            (
                "z=nan,1",
                '- z=nan,1: "nan,1" is no window. A window is two epoch seconds, the '
                "first the earlier.",
            ),
            (
                "z=1,inf",
                '- z=1,inf: "1,inf" is no window. A window is two epoch seconds, the '
                "first the earlier.",
            ),
        ],
    )
    def test_one_that_does_not_read(
        self, refuses: Refuses, written: str, fault: str
    ) -> None:
        assert refuses(written)[1] == fault


class TestReadOne:
    def test_a_measure_of_a_figure(self, held: Catalogue, weeks: list[Period]) -> None:
        assert read_simple("cost.sum(source=chat|pilot)", held, weeks) == Simple(
            "cost", "sum", None, (Filter("source", ("chat", "pilot")),)
        )

    def test_the_built_in_ratios_sides_read(
        self, held: Catalogue, weeks: list[Period]
    ) -> None:
        for ratio in held.ratios:
            read_simple(ratio.numerator, held, weeks)
            read_simple(ratio.denominator, held, weeks)

    def test_a_chip(self, held: Catalogue, weeks: list[Period]) -> None:
        assert read_chip("@items,gt,1,cost.sum", held, weeks) == OnItems(
            "gt", 1.0, Simple("cost", "sum")
        )

    def test_one_with_a_fault_is_refused(
        self, held: Catalogue, weeks: list[Period]
    ) -> None:
        with pytest.raises(StateRefusedException) as refused:
            read_chip("miss:2", held, weeks)

        assert refused.value.message.splitlines()[1] == (
            '- c=miss:2: "2" is no value of miss. The values of miss are 1 and 0.'
        )

    def test_one_by_a_ratio_whose_key_is_gone_is_refused(
        self, held: Catalogue, weeks: list[Period]
    ) -> None:
        with pytest.raises(StateRefusedException) as refused:
            read_chip("@rows,gt,1,r:per_cal", held, weeks)

        assert refused.value.message.splitlines()[1] == (
            '- c=@rows,gt,1,r:per_cal: no ratio has the key "per_cal". Did you mean '
            '"per_call"? The catalogue\'s measures list the ratios.'
        )

    def test_one_whose_threshold_is_no_finite_number_is_refused(
        self, held: Catalogue, weeks: list[Period]
    ) -> None:
        with pytest.raises(StateRefusedException) as refused:
            read_chip("@rows,gt,-inf,cost.sum", held, weeks)

        assert refused.value.message.splitlines()[1] == (
            '- c=@rows,gt,-inf,cost.sum: "-inf" is no number.'
        )
