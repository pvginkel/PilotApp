"""A view's rows (F154.1, F154.3): each measure on every row of the By and on
the All row, with the split by the color, answered from the record at the
query under the engine's bounds (F154.5).

The record is `tests.support.dashboard.record`'s: on the project Recipe box,
a work item's thread of three Calls, 0.50, 0.25 and 1.00, with its sub-agent's
Call of 0.10, and a chat's Turn of 0.75 standing in, its conversation never
collected; and on no project a thread of one Call of 0.05, a day later.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session as DbSession

from app import models
from app.dashboard import rows as rows_module
from app.dashboard.rows import ByRow, ColorValue, Rows, RowsService
from app.dashboard.state import Sort
from app.exceptions import QueryRefusedException, StateRefusedException
from app.models import Project, User
from app.services.container import ServiceContainer
from tests.support.dashboard import Record, record, sent
from tests.support.transcripts import OPUS, STARTED

NOW = datetime(2026, 11, 20, tzinfo=UTC)


@pytest.fixture
def worked(
    session: DbSession, person: User, project: Project, project_session: models.Session
) -> Record:
    return record(session, person, project, project_session)


@pytest.fixture
def service(container: ServiceContainer) -> RowsService:
    return container.rows_service()


def _rows(service: RowsService, written: str) -> Rows:
    return service.rows(written, now=NOW)


def _by_key(found: Rows) -> dict[object, ByRow]:
    return {row.key: row for row in found.rows}


def _round(values: tuple[float | None, ...]) -> tuple[float | None, ...]:
    return tuple(None if value is None else round(value, 6) for value in values)


@pytest.mark.usefixtures("worked")
class TestMeasures:
    def test_each_on_every_row_and_on_the_all_row(
        self, service: RowsService, worked: Record
    ) -> None:
        found = _rows(service, "t=all&m=cost.sum&m=calls.count&m=ctx.max&m=cost.mean")

        rows = _by_key(found)
        assert _round(rows[worked.project.id].values) == (2.6, 5, 52626, 0.52)
        assert rows[worked.project.id].n == (5, 5, 4, 5)
        assert rows[worked.project.id].label == "Recipe box"
        assert _round(rows[None].values) == (0.05, 1, 52626, 0.05)
        assert rows[None].label == "(No project)"
        assert _round(found.all.values) == (2.65, 6, 52626, 0.441667)
        assert found.all.n == (6, 6, 5, 6)

    def test_one_over_a_parts_items_takes_each_item_whole(
        self, service: RowsService, worked: Record
    ) -> None:
        found = _rows(
            service,
            "t=all&m=cost.sum.conversation&m=cost.max.conversation"
            "&m=calls.count.conversation&m=cost.median.conversation"
            "&m=ctx.sum.conversation",
        )

        recipe = _by_key(found)[worked.project.id]
        assert recipe.label == "Recipe box"
        assert _round(recipe.values) == (1.85, 1.75, 2, 0.925, 105252)
        assert recipe.n == (2, 2, 2, 2, 2)
        assert _round(found.all.values) == (1.9, 1.75, 3, 0.1, 157878)

    def test_a_median_and_a_p90_of_the_facts_own_rows(
        self, service: RowsService, worked: Record
    ) -> None:
        found = _rows(service, "t=all&m=cost.median&m=cost.p90")

        assert _round(_by_key(found)[worked.project.id].values) == (0.5, 0.9)
        assert _round(found.all.values) == (0.375, 0.875)

    def test_one_with_no_item_on_a_row_is_none_there(
        self, service: RowsService, worked: Record
    ) -> None:
        found = _rows(service, "t=all&m=turns.count&m=cost.sum")

        assert _by_key(found)[None].values == (None, 0.05)
        assert _by_key(found)[None].n == (0, 1)
        assert _by_key(found)[worked.project.id].values[0] == 2

    def test_its_own_filters_keep_its_rows(
        self, service: RowsService, worked: Record
    ) -> None:
        found = _rows(service, "t=all&m=cost.sum(source=chat)&m=cost.sum(!miss=1)")

        assert _round(_by_key(found)[worked.project.id].values) == (0.75, 1.6)
        assert _by_key(found)[None].values == (None, 0.05)

    def test_a_ratio_is_its_numerator_over_its_denominator(
        self, service: RowsService, worked: Record
    ) -> None:
        found = _rows(
            service,
            "t=all&m=r:per_call&m=r:Missed:miss_cost.sum/cost.sum"
            "&m=r:Per%20miss:cost.sum/misses.sum",
        )

        recipe, loose = _by_key(found)[worked.project.id], _by_key(found)[None]
        assert _round(recipe.values) == (0.52, 0.384615, 2.6)
        assert recipe.n == (5, 5, 5)
        assert loose.values == (0.05, 0.0, None)
        assert [measure.format for measure in found.measures] == ["usd", "share", "usd"]
        assert [measure.label for measure in found.measures] == [
            "Cost per call",
            "Missed",
            "Per miss",
        ]

    def test_one_whose_fact_has_no_by_is_refused_with_why(
        self, service: RowsService
    ) -> None:
        found = _rows(service, "t=all&by=model&m=cost.sum&m=turns.count")

        assert found.measures[1].refused == (
            "turns is a figure of Pilot turns, which have no model"
        )
        assert [row.values[1] for row in found.rows] == [None, None]
        assert found.all.values[1] is None


@pytest.mark.usefixtures("worked")
class TestScope:
    def test_a_drill_level_keeps_its_value(
        self, service: RowsService, worked: Record
    ) -> None:
        found = _rows(
            service, f"t=all&by=psession&dr=project:{worked.project.id}@project"
        )

        assert set(_by_key(found)) == {worked.work.id, worked.chat.id}
        assert _round(found.all.values) == (2.6,)

    def test_a_chip_keeps_its_values_or_all_but_them_none_among_them(
        self, service: RowsService, worked: Record
    ) -> None:
        kept = _rows(service, "t=all&by=psession&c=effort:high")
        unset = _rows(service, "t=all&by=psession&c=effort:~")
        dropped = _rows(service, "t=all&by=psession&c=!source:chat")

        assert _round(kept.all.values) == (0.5,)
        assert _round(unset.all.values) == (2.15,)
        assert set(_by_key(dropped)) == {worked.work.id, None}
        assert _round(dropped.all.values) == (1.9,)

    def test_a_chip_on_what_a_fact_lacks_keeps_its_conversations(
        self, service: RowsService, worked: Record
    ) -> None:
        kept = _rows(service, "t=all&by=conversation&c=event_kind:api_error")
        dropped = _rows(service, "t=all&by=conversation&c=!event_kind:api_error")

        assert set(_by_key(kept)) == {worked.thread.id}
        assert _round(kept.all.values) == (1.75,)
        assert set(_by_key(dropped)) == {worked.sub_agent.id, worked.loose.id, None}

    def test_the_window_keeps_its_time(
        self, service: RowsService, worked: Record
    ) -> None:
        found = _rows(service, "t=c,2026-11-12,2026-11-12")

        assert set(_by_key(found)) == {worked.project.id}
        assert found.window == (
            (
                datetime(2026, 11, 11, 23, tzinfo=UTC),
                datetime(2026, 11, 12, 23, tzinfo=UTC),
            ),
        )
        assert found.zone == "Europe/Amsterdam"

    def test_none_of_the_time_keeps_nothing(self, service: RowsService) -> None:
        found = _rows(service, "t=c,2020-01-01,2020-01-02")

        assert found.rows == ()
        assert found.all.values == (None,)
        assert found.total_rows == 0


@pytest.mark.usefixtures("worked")
class TestColor:
    def test_a_stacked_measure_splits_over_the_colors_values(
        self, service: RowsService, worked: Record
    ) -> None:
        found = _rows(service, "t=all&m=cost.sum&m=calls.count&m=ctx.max&col=model")

        assert found.color is not None
        assert (found.color.key, found.color.label) == ("model", "Model")
        assert [(value.key, value.label) for value in found.color.values] == [
            (OPUS, OPUS),
            (None, "(Estimate: no model)"),
        ]
        assert [round(value.total or 0, 6) for value in found.color.values] == [
            1.9,
            0.75,
        ]
        assert [measure.stacks for measure in found.measures] == [True, True, False]
        recipe = _by_key(found)[worked.project.id]
        assert recipe.split is not None
        assert _round(recipe.split[0] or ()) == (1.85, 0.75)
        assert recipe.split[1] == (4.0, 1.0)
        assert recipe.split[2] is None
        assert found.all.split is not None
        assert _round(found.all.split[0] or ()) == (1.9, 0.75)

    def test_a_measure_whose_fact_lacks_the_color_does_not_stack(
        self, service: RowsService
    ) -> None:
        found = _rows(service, "t=all&m=turns.count&m=cost.median&col=model")

        assert [measure.stacks for measure in found.measures] == [False, False]
        assert found.color is not None
        assert found.color.values == ()

    def test_the_token_kinds_split_a_figure_of_tokens(
        self, service: RowsService, worked: Record
    ) -> None:
        found = _rows(service, "t=all&m=tokens.sum&m=cost.sum&col=token_kind")

        assert found.color is not None
        assert [value.key for value in found.color.values] == [
            "input",
            "cache_write",
            "cache_read",
            "output",
        ]
        assert [measure.stacks for measure in found.measures] == [True, False]
        chat = _rows(service, "t=all&by=psession&m=tokens.sum&col=token_kind")
        split = _by_key(chat)[worked.chat.id].split
        assert split is not None
        assert split[0] == (100.0, 2_000.0, 30_000.0, 400.0)

    def test_values_past_the_cap_fold_into_one(
        self, service: RowsService, monkeypatch: pytest.MonkeyPatch, worked: Record
    ) -> None:
        monkeypatch.setattr(rows_module, "COLORS", 2)

        found = _rows(service, "t=all&m=cost.sum&col=conversation")

        assert found.color is not None
        assert found.color.values[:2] == (
            ColorValue(worked.thread.id, None, 1.75),
            ColorValue(None, "(No transcript)", 0.75),
        )
        folded = found.color.values[2]
        assert (folded.key, folded.label, folded.others) == (None, "2 other values", 2)
        assert round(folded.total or 0, 6) == 0.15
        assert found.all.split is not None
        assert _round(found.all.split[0] or ()) == (1.75, 0.75, 0.15)


@pytest.mark.usefixtures("worked")
class TestRowsOrder:
    def test_by_the_first_measure_the_largest_first(
        self, service: RowsService, worked: Record
    ) -> None:
        found = _rows(service, "t=all&by=conversation")

        assert [row.key for row in found.rows] == [
            worked.thread.id,
            None,
            worked.sub_agent.id,
            worked.loose.id,
        ]
        assert found.sort == Sort("desc", "cost.sum")

    def test_by_the_sort_named_none_in_its_column_last(
        self, service: RowsService, worked: Record
    ) -> None:
        ascending = _rows(service, "t=all&by=conversation&o=asc,cost.sum")
        missed = [
            _rows(
                service,
                f"t=all&by=conversation&m=cost.sum&m=miss_cost.sum&o={direction},miss_cost.sum",
            )
            for direction in ("asc", "desc")
        ]

        assert [row.key for row in ascending.rows] == [
            worked.loose.id,
            worked.sub_agent.id,
            None,
            worked.thread.id,
        ]
        for found in missed:
            assert found.rows[0].key == worked.thread.id
            assert [row.values[1] for row in found.rows[1:]] == [None, None, None]

    def test_by_the_label(self, service: RowsService, worked: Record) -> None:
        ascending = _rows(service, "t=all&o=asc,label")
        descending = _rows(service, "t=all&o=desc,label")

        assert [row.key for row in ascending.rows] == [None, worked.project.id]
        assert [row.key for row in descending.rows] == [worked.project.id, None]

    def test_at_most_the_cap_with_the_count_of_all(
        self, service: RowsService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(rows_module, "ROWS", 1)

        found = _rows(service, "t=all")

        assert len(found.rows) == 1
        assert found.total_rows == 2


@pytest.mark.usefixtures("worked")
class TestAnswer:
    def test_a_row_of_a_measure_over_items_alone_has_its_label_and_focus(
        self, service: RowsService, worked: Record
    ) -> None:
        found = _rows(
            service, f"t=all&m=cost.median.conversation&f=project:{worked.project.id}"
        )

        recipe = _by_key(found)[worked.project.id]
        assert (recipe.label, recipe.focus) == ("Recipe box", True)

    def test_a_row_holding_the_focus_is_marked_and_no_peer(
        self, service: RowsService, worked: Record
    ) -> None:
        found = _rows(service, f"t=all&by=psession&f=psession:{worked.work.id}")

        rows = _by_key(found)
        assert rows[worked.work.id].focus is True
        assert rows[worked.chat.id].focus is False
        assert found.measures[0].median == pytest.approx((0.75 + 0.05) / 2)

    def test_a_time_key_is_an_instant(
        self, service: RowsService, worked: Record
    ) -> None:
        found = _rows(service, "t=all&by=sitting")

        assert STARTED + timedelta(days=1) in _by_key(found)

    def test_it_carries_the_address_its_look_and_its_notes(
        self, service: RowsService
    ) -> None:
        found = _rows(service, "t=all&m=r:gone&rel=1")

        assert (
            found.address.address == "#dash/t=all&by=project&m=cost.sum&col=none&rel=1"
        )
        assert found.address.look == ("rel=1",)
        assert len(found.address.notes) == 2

    def test_an_entry_is_answered_as_filled_in(
        self, service: RowsService, worked: Record
    ) -> None:
        found = _rows(service, f"f=project:{worked.project.id}")

        assert found.by.key == "psession"
        assert [measure.key for measure in found.measures] == ["cost.sum", "misses.sum"]

    def test_a_state_with_a_fault_is_refused(self, service: RowsService) -> None:
        with pytest.raises(StateRefusedException):
            _rows(service, "by=nothing")

    def test_what_its_statements_do_not_apply_it_does_not_answer_yet(
        self, service: RowsService
    ) -> None:
        with pytest.raises(NotImplementedError, match="@outliers"):
            _rows(service, "c=@outliers")


@pytest.fixture
def many(session: DbSession, worked: Record) -> None:
    """Five thousand more Calls of the work item's thread, written at once."""
    session.execute(
        text(
            """
            INSERT INTO calls (transcript_id, message_id, position, completed_at,
                model_code, input_tokens, cache_write_5m_tokens,
                cache_write_1h_tokens, cache_read_tokens, output_tokens, cost)
            SELECT :thread, 'msg_many_' || n, 100 + n,
                :at + make_interval(secs => n), :model, 1, 0, 0, 0, 1, n * 0.001
            FROM generate_series(1, 5000) AS n
            """
        ),
        {"thread": worked.thread.id, "at": STARTED, "model": OPUS},
    )


@pytest.mark.usefixtures("worked")
class TestBounded:
    def test_its_statements_run_read_only_under_the_timeout(
        self, service: RowsService, session: DbSession
    ) -> None:
        with sent(session) as statements:
            _rows(service, "t=all&m=cost.sum&m=cost.median.conversation")

        at = statements.index("SET TRANSACTION READ ONLY")
        assert statements[at + 1] == "SET LOCAL statement_timeout = 30000"
        ended = statements.index(
            next(one for one in statements[at:] if one.startswith("ROLLBACK"))
        )
        read = statements[at + 2 : ended]
        assert len(read) == 2
        assert all(one.startswith("SELECT") for one in read)

    @pytest.mark.usefixtures("many")
    def test_one_past_the_limit_on_temporary_files_is_refused(
        self, service: RowsService, session: DbSession
    ) -> None:
        session.execute(text("SET LOCAL work_mem = '64kB'"))
        session.execute(text("SET LOCAL temp_file_limit = '64kB'"))

        with pytest.raises(QueryRefusedException) as refused:
            _rows(service, "t=all&by=call&m=cost.median")

        assert refused.value.reason == "temp_file_limit"
