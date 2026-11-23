"""A view's state written in its normal form (F159): each part in its place,
each value percent-encoded as the mockup's page encodes it, a part at its
default left out but t, by, m and col."""

import uuid
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from app.dashboard.state import (
    LOOK,
    OTHERS,
    PARTS,
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
    RatioKey,
    Roll,
    Selected,
    Simple,
    Sort,
    State,
    Weeks,
    WrittenRatio,
    dec,
    enc,
    instant,
    look,
    measure_key,
    write,
)

PROJECT = uuid.UUID("5b0e6a4c-2f4a-4d7e-9b1e-0c3f0c7c1a2b")
WEEK = datetime(2026, 11, 19, 10, tzinfo=UTC)


class TestEnc:
    def test_it_encodes_as_encode_uri_component_and_the_five_it_leaves(
        self,
    ) -> None:
        assert enc("a-b_c.d") == "a-b_c.d"
        assert enc("a,b:c|d;e/f=g&h@i") == "a%2Cb%3Ac%7Cd%3Be%2Ff%3Dg%26h%40i"
        assert enc("!'()*~") == "%21%27%28%29%2A%7E"
        assert enc("é …") == "%C3%A9%20%E2%80%A6"

    def test_it_writes_a_number_an_id_a_date_and_an_instant(self) -> None:
        assert enc(42) == "42"
        assert enc(PROJECT) == "5b0e6a4c-2f4a-4d7e-9b1e-0c3f0c7c1a2b"
        assert enc(date(2026, 11, 3)) == "2026-11-03"
        assert enc(WEEK) == "2026-11-19T10%3A00%3A00Z"


class TestDec:
    def test_it_reads_what_enc_writes(self) -> None:
        for text in ("a,b:c|d", "!'()*~", "é …", "plain"):
            assert dec(enc(text)) == text

    def test_it_reads_a_reserved_character_left_as_it_is(self) -> None:
        assert dec("2026-11-19T10:00:00Z") == "2026-11-19T10:00:00Z"

    @pytest.mark.parametrize("written", ["%zz", "50%", "%C3"])
    def test_a_percent_that_encodes_no_character_is_refused(self, written: str) -> None:
        with pytest.raises(ValueError):
            dec(written)


class TestInstant:
    def test_it_is_in_utc_with_its_seconds(self) -> None:
        assert instant(WEEK) == "2026-11-19T10:00:00Z"
        assert (
            instant(datetime(2026, 11, 19, 11, tzinfo=timezone(timedelta(hours=1))))
            == "2026-11-19T10:00:00Z"
        )

    def test_a_fraction_is_written_where_it_has_one(self) -> None:
        assert (
            instant(datetime(2026, 11, 19, 9, 59, 58, 500, tzinfo=UTC))
            == "2026-11-19T09:59:58.000500Z"
        )


class TestWrite:
    def test_the_default_is_the_scratch(self) -> None:
        assert write(State()) == "t=qw&by=project&m=cost.sum&col=none"

    def test_every_part_stands_in_its_place(self) -> None:
        state = State(
            time=Weeks((WEEK,)),
            by="psession",
            presentation="order",
            axis="session_start",
            measures=(Simple("cost", "median", "conversation"), RatioKey("overhead")),
            levels=(Level("project", PROJECT, "project"),),
            chips=(Pin("miss", (1,)), Outliers(marked=True)),
            quick_filters=("expensive",),
            color="model",
            sort=Sort("desc", "cost.median.conversation"),
            drawer=True,
            selected=Selected(None),
            item_grain="call",
            item=Item("conversation", PROJECT),
            call=7,
            focus=Focus("project", PROJECT),
            relative=True,
            markers=(),
            draw=Draw(dots="out", band=False),
            roll=Roll(5, 5),
            lit=(None, OTHERS),
            events=(("cache_miss", False), ("hook_error", True)),
            zoom=(1763600000.0, 1763686400.5),
        )

        written = write(state)

        assert written == (
            "t=wk,2026-11-19T10%3A00%3A00Z&by=psession&p=order,session_start"
            "&m=cost.median.conversation&m=r:overhead"
            f"&dr=project:{PROJECT}@project&c=miss:1&c=~@outliers&b=expensive"
            "&col=model&o=desc,cost.median.conversation&d=items&sel=~&ig=call"
            f"&it=conversation,{PROJECT}&call=7&f=project:{PROJECT}&rel=1&mk=none"
            "&dw=dots:out,band:off&roll=5,5&lit=~,%E2%80%A6"
            "&ev=-cache_miss,hook_error&z=1763600000,1763686400.5"
        )
        keys = [part.partition("=")[0] for part in written.split("&")]
        assert keys == sorted(keys, key=PARTS.index)

    def test_a_part_at_its_default_is_left_out(self) -> None:
        state = State(draw=Draw(), roll=Roll(10, 15), relative=False)

        assert write(state) == "t=qw&by=project&m=cost.sum&col=none"

    def test_a_range_between_two_bounds(self) -> None:
        assert (
            write(State(time=Between(date(2026, 11, 1), datetime(2026, 11, 7, 18, 30))))
            == "t=c,2026-11-01,2026-11-07T18%3A30&by=project&m=cost.sum&col=none"
        )
        assert write(State(time=Between(None, datetime(2026, 11, 7, 18, 30, 5)))) == (
            "t=c,,2026-11-07T18%3A30%3A05&by=project&m=cost.sum&col=none"
        )

    def test_the_chips_and_their_signs(self) -> None:
        measure = Simple("cost", "sum")
        chips = (
            Pin("source", ("chat", "pilot"), negated=True, marked=True),
            OnRows("gt", 100, measure, marked=True),
            OnItems("ge", 1.5, measure, negated=True),
            Outliers(),
        )

        assert write(State(chips=chips)).split("&")[3:7] == [
            "c=~!source:chat,pilot",
            "c=~@rows,gt,100,cost.sum",
            "c=!@items,ge,1.5,cost.sum",
            "c=@outliers",
        ]

    def test_a_threshold_on_the_rows_by_a_ratio(self) -> None:
        chips = (
            OnRows("gt", 0.5, RatioKey("per_call")),
            OnRows(
                "lt",
                2,
                WrittenRatio("Mine", Simple("cost", "sum"), Simple("calls", "count")),
            ),
        )

        assert write(State(chips=chips)).split("&")[3:5] == [
            "c=@rows,gt,0.5,r:per_call",
            "c=@rows,lt,2,r:Mine:cost.sum/calls.count",
        ]


class TestMeasureKey:
    def test_a_figures_measure_its_grain_and_its_filters(self) -> None:
        assert measure_key(Simple("cost", "sum")) == "cost.sum"
        assert measure_key(Simple("cost", "p90", "psession")) == "cost.p90.psession"
        assert (
            measure_key(
                Simple(
                    "cost",
                    "sum",
                    None,
                    (
                        Filter("source", ("chat", "pilot")),
                        Filter("model", (None, "a,b"), negated=True),
                    ),
                )
            )
            == "cost.sum(source=chat|pilot;!model=~|a%2Cb)"
        )

    def test_a_ratio_by_its_key_and_one_written_out(self) -> None:
        assert measure_key(RatioKey("overhead")) == "r:overhead"
        assert (
            measure_key(
                WrittenRatio(
                    "Miss share", Simple("miss_cost", "sum"), Simple("cost", "sum")
                )
            )
            == "r:Miss%20share:miss_cost.sum/cost.sum"
        )


class TestLook:
    def test_the_look_only_parts_as_written(self) -> None:
        state = State(
            drawer=True,
            relative=True,
            markers=("model",),
            draw=Draw(cols=False),
            lit=("work",),
            color="source",
            events=(("cache_miss", True),),
            zoom=(1.0, 2.0),
            sort=Sort("asc", "label"),
        )

        assert look(state) == (
            "d=items",
            "rel=1",
            "mk=model",
            "dw=cols:off",
            "lit=work",
            "ev=cache_miss",
            "z=1,2",
        )
        assert set(LOOK) == {"d", "rel", "mk", "dw", "lit", "ev", "z"}

    def test_a_state_at_its_defaults_has_none(self) -> None:
        assert look(State()) == ()
